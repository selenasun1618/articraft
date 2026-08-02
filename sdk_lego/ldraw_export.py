from __future__ import annotations

import json
import math
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sdk import ArticulationType, Origin, ValidationError

from .catalog_snapshot import get_active_catalog_snapshot
from .model import (
    ArticulatedObject,
    connector_by_id,
    connector_world_axis_sdk,
    connector_world_position_ldu,
    connectors_compatible,
    distance_sq,
    lego_connectors,
    lego_piece_spec,
)

LegoCompileTarget = Literal["visual", "buildable", "strict"]
@dataclass(frozen=True, slots=True)
class LDrawExport:
    mpd_text: str
    sidecar_json: dict[str, Any]
    warnings: list[str]


def compile_object_to_ldraw_mpd(
    object_model: ArticulatedObject,
    *,
    target: str = "buildable",
    validate: bool = True,
) -> LDrawExport:
    target_key = _normalize_target(target)
    if validate:
        _validate_lego_model(object_model, target=target_key)
    warnings = _download_referenced_parts(object_model) if target_key in {"buildable", "strict"} else []
    sidecar = _build_sidecar(object_model, target=target_key)
    return LDrawExport(
        mpd_text=_render_mpd(object_model, sidecar=sidecar),
        sidecar_json=sidecar,
        warnings=warnings,
    )


def _normalize_target(target: str) -> LegoCompileTarget:
    value = str(target or "buildable").strip().lower()
    if value == "full":
        value = "buildable"
    if value not in {"visual", "buildable", "strict"}:
        raise ValidationError("LEGO compile target must be one of: visual, buildable, strict")
    return value  # type: ignore[return-value]


def _validate_lego_model(object_model: ArticulatedObject, *, target: LegoCompileTarget) -> None:
    snapshot = get_active_catalog_snapshot()
    model_catalog_id = object_model.meta.get("lego_catalog_id")
    model_catalog_sha256 = object_model.meta.get("lego_catalog_sha256")
    if model_catalog_id != snapshot.catalog_id:
        raise ValidationError(
            f"Model LEGO catalog {model_catalog_id!r} does not match active catalog "
            f"{snapshot.catalog_id!r}"
        )
    if model_catalog_sha256 != snapshot.sha256:
        raise ValidationError("Model LEGO catalog fingerprint does not match active catalog")
    if not object_model.parts:
        raise ValidationError("LEGO object must contain at least one part")
    seen_names: set[str] = set()
    for part in object_model.parts:
        if part.name in seen_names:
            raise ValidationError(f"Duplicate LEGO part name: {part.name!r}")
        seen_names.add(part.name)
        spec = lego_piece_spec(part)
        approved = snapshot.resolve_part(spec.part_num)
        if spec.ldraw_id != approved.ldraw_id:
            raise ValidationError(
                f"Part {part.name!r} uses LDraw id {spec.ldraw_id!r}; "
                f"catalog {snapshot.catalog_id!r} requires {approved.ldraw_id!r}"
            )
        snapshot.validate_color(spec.color_id)

    if target == "visual":
        return

    connections = object_model.lego_connections()
    if len(object_model.parts) > 1 and not connections:
        raise ValidationError("LEGO buildable target requires explicit lego_connection(...) entries")

    part_by_name = {part.name: part for part in object_model.parts}
    used_connectors: set[tuple[str, str]] = set()
    graph: dict[str, set[str]] = {part.name: set() for part in object_model.parts}
    for connection in connections:
        parent = part_by_name.get(connection.parent)
        child = part_by_name.get(connection.child)
        if parent is None:
            raise ValidationError(f"LEGO connection references missing parent {connection.parent!r}")
        if child is None:
            raise ValidationError(f"LEGO connection references missing child {connection.child!r}")
        if parent is child:
            raise ValidationError(f"LEGO connection {connection!r} cannot connect a part to itself")
        parent_connector = connector_by_id(parent, connection.parent_connector)
        child_connector = connector_by_id(child, connection.child_connector)
        if not connectors_compatible(parent_connector, child_connector):
            raise ValidationError(
                "Incompatible LEGO connectors: "
                f"{parent.name}.{parent_connector.id} ({parent_connector.type}) -> "
                f"{child.name}.{child_connector.id} ({child_connector.type})"
            )
        for key in (
            (parent.name, parent_connector.id),
            (child.name, child_connector.id),
        ):
            if key in used_connectors:
                raise ValidationError(
                    f"LEGO connector {key[0]}.{key[1]} is used by multiple connections"
                )
            used_connectors.add(key)
        graph[parent.name].add(child.name)
        graph[child.name].add(parent.name)

        if target == "strict":
            parent_pos = connector_world_position_ldu(parent, parent_connector)
            child_pos = connector_world_position_ldu(child, child_connector)
            if distance_sq(parent_pos, child_pos) > 1e-8:
                raise ValidationError(
                    "Strict LEGO connection endpoints must coincide in LDraw space: "
                    f"{parent.name}.{parent_connector.id}={parent_pos} "
                    f"{child.name}.{child_connector.id}={child_pos}"
                )
            parent_axis = connector_world_axis_sdk(parent, parent_connector)
            child_axis = connector_world_axis_sdk(child, child_connector)
            axis_dot = sum(
                parent_axis[index] * child_axis[index] for index in range(3)
            )
            if axis_dot > -0.999:
                raise ValidationError(
                    "Strict LEGO connection axes must oppose each other: "
                    f"{parent.name}.{parent_connector.id} axis={parent_axis} "
                    f"{child.name}.{child_connector.id} axis={child_axis}"
                )

    if len(object_model.parts) > 1:
        visited: set[str] = set()
        stack = [object_model.parts[0].name]
        while stack:
            name = stack.pop()
            if name in visited:
                continue
            visited.add(name)
            stack.extend(sorted(graph[name] - visited))
        if visited != set(part_by_name):
            missing = sorted(set(part_by_name) - visited)
            raise ValidationError(f"LEGO build is disconnected; unreachable parts: {missing}")


def _build_sidecar(
    object_model: ArticulatedObject,
    *,
    target: LegoCompileTarget,
) -> dict[str, Any]:
    snapshot = get_active_catalog_snapshot()
    pieces = []
    for part in object_model.parts:
        spec = lego_piece_spec(part)
        pieces.append(
            {
                "name": part.name,
                "part_num": spec.part_num,
                "ldraw_id": spec.ldraw_id,
                "color_id": spec.color_id,
                "color_name": spec.color_name,
                "origin": {"xyz": list(spec.origin.xyz), "rpy": list(spec.origin.rpy)},
                "connectors": [
                    {
                        "id": connector.id,
                        "type": connector.type,
                        "position_ldu": list(connector.position_ldu),
                        "axis": list(connector.axis),
                    }
                    for connector in lego_connectors(part)
                ],
            }
        )

    articulations = []
    for articulation in object_model.articulations:
        articulation_type = (
            articulation.articulation_type.value
            if isinstance(articulation.articulation_type, ArticulationType)
            else str(articulation.articulation_type)
        )
        articulations.append(
            {
                "name": articulation.name,
                "type": articulation_type,
                "ldraw_behavior": "fixed",
                "parent": articulation.parent,
                "child": articulation.child,
                "origin": {
                    "xyz": list(articulation.origin.xyz),
                    "rpy": list(articulation.origin.rpy),
                },
                "axis": list(articulation.axis),
            }
        )

    return {
        "schema_version": 1,
        "format": "articraft_lego_ldraw_sidecar",
        "name": object_model.name,
        "target": target,
        "catalog": {
            "catalog_id": snapshot.catalog_id,
            "catalog_sha256": snapshot.sha256,
        },
        "used_part_nums": sorted({lego_piece_spec(part).part_num for part in object_model.parts}),
        "pieces": pieces,
        "connections": [
            {
                "parent": connection.parent,
                "child": connection.child,
                "parent_connector": connection.parent_connector,
                "child_connector": connection.child_connector,
                "connection_type": connection.connection_type,
            }
            for connection in object_model.lego_connections()
        ],
        "articulations": articulations,
    }


def _render_mpd(object_model: ArticulatedObject, *, sidecar: dict[str, Any]) -> str:
    main_name = _safe_ldraw_name(f"{object_model.name}.ldr")
    lines = [
        f"0 FILE {main_name}",
        f"0 {object_model.name}",
        "0 !ARTICRAFT_FORMAT LEGO_LDRAW_MPD 1",
        (
            "0 !ARTICRAFT_CATALOG "
            f"{sidecar['catalog']['catalog_id']} {sidecar['catalog']['catalog_sha256']}"
        ),
        "0 !ARTICRAFT_SIDECAR_BEGIN",
        *_json_comment_lines(sidecar),
        "0 !ARTICRAFT_SIDECAR_END",
    ]
    for part in object_model.parts:
        spec = lego_piece_spec(part)
        x, y, z = _origin_translation_ldu(spec.origin)
        a, b, c, d, e, f, g, h, i = _origin_matrix(spec.origin)
        lines.append(
            "1 "
            f"{spec.color_id} "
            f"{_num(x)} {_num(y)} {_num(z)} "
            f"{_num(a)} {_num(b)} {_num(c)} "
            f"{_num(d)} {_num(e)} {_num(f)} "
            f"{_num(g)} {_num(h)} {_num(i)} "
            f"{spec.ldraw_id}"
        )
    lines.append("")
    return "\r\n".join(lines)


def _json_comment_lines(payload: dict[str, Any]) -> list[str]:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return [f"0 !ARTICRAFT_SIDECAR {text[index:index + 240]}" for index in range(0, len(text), 240)]


def _safe_ldraw_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in value)


def _origin_translation_ldu(origin: Origin) -> tuple[float, float, float]:
    x, y, z = origin.xyz
    return (float(x) * 2500.0, -float(z) * 2500.0, float(y) * 2500.0)


def _origin_matrix(origin: Origin) -> tuple[float, float, float, float, float, float, float, float, float]:
    roll, pitch, yaw = (float(value) for value in origin.rpy)
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    # SDK convention: Rz(yaw) * Ry(pitch) * Rx(roll).
    r_sdk = (
        (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
        (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
        (-sp, cp * sr, cp * cr),
    )
    # Convert SDK +Z-up basis into LDraw -Y-up basis.
    basis = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0))
    converted = _matmul(_matmul(basis, r_sdk), _transpose(basis))
    return (
        converted[0][0],
        converted[0][1],
        converted[0][2],
        converted[1][0],
        converted[1][1],
        converted[1][2],
        converted[2][0],
        converted[2][1],
        converted[2][2],
    )


def _matmul(
    a: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]],
    b: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    return tuple(
        tuple(sum(a[row][k] * b[k][col] for k in range(3)) for col in range(3))
        for row in range(3)
    )  # type: ignore[return-value]


def _transpose(
    matrix: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    return tuple(tuple(matrix[row][col] for row in range(3)) for col in range(3))  # type: ignore[return-value]


def _num(value: float) -> str:
    if abs(value) < 1e-12:
        value = 0.0
    return f"{float(value):.6g}"


def _download_referenced_parts(object_model: ArticulatedObject) -> list[str]:
    cache_root = Path(os.environ.get("ARTICRAFT_LDRAW_CACHE_DIR", "data/cache/lego/ldraw"))
    warnings: list[str] = []
    for part in object_model.parts:
        spec = lego_piece_spec(part)
        local_path = cache_root / "parts" / spec.ldraw_id
        if local_path.exists():
            continue
        try:
            _download_ldraw_part(spec.ldraw_id, local_path)
        except Exception as exc:
            warnings.append(f"LDraw part {spec.ldraw_id!r} was not cached on demand: {exc}")
    return warnings


def _download_ldraw_part(ldraw_id: str, local_path: Path) -> None:
    # LDraw has changed hosting details over time; try stable library mirrors first.
    candidates = [
        f"https://library.ldraw.org/library/official/parts/{ldraw_id}",
        f"https://library.ldraw.org/library/unofficial/parts/{ldraw_id}",
    ]
    for url in candidates:
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                data = response.read()
            if data.strip():
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(data)
                return
        except Exception:
            continue
    raise FileNotFoundError(f"could not download {ldraw_id}")
