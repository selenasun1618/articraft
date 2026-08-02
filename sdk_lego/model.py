from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sdk import ArticulatedObject as _BaseArticulatedObject
from sdk import Origin, Part, ValidationError

from .catalog import LegoPartRecord, resolve_lego_color, resolve_lego_part
from .catalog_snapshot import get_active_catalog_snapshot

STUD_PITCH_LDU = 20.0
PLATE_HEIGHT_LDU = 8.0
BRICK_HEIGHT_LDU = 24.0


@dataclass(frozen=True, slots=True)
class LegoPieceSpec:
    part_num: str
    ldraw_id: str
    color_id: int
    color_name: str
    origin: Origin
    record: LegoPartRecord


@dataclass(frozen=True, slots=True)
class LegoConnector:
    id: str
    type: str
    position_ldu: tuple[float, float, float]
    axis: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class LegoConnection:
    parent: str
    child: str
    parent_connector: str
    child_connector: str
    connection_type: str = "fixed"


def _piece_height_ldu(record: LegoPartRecord) -> float:
    raw_height = record.raw.get("height_ldu")
    if isinstance(raw_height, (int, float)) and float(raw_height) > 0:
        return float(raw_height)
    name = record.name.lower()
    if "plate" in name or "tile" in name:
        return PLATE_HEIGHT_LDU
    return BRICK_HEIGHT_LDU


def derive_connectors(record: LegoPartRecord) -> tuple[LegoConnector, ...]:
    size = record.nominal_size
    if size is None:
        return ()
    width, depth = size
    height = _piece_height_ldu(record)
    x0 = -((width - 1) * STUD_PITCH_LDU) / 2.0
    z0 = -((depth - 1) * STUD_PITCH_LDU) / 2.0
    connectors: list[LegoConnector] = []
    for x_index in range(width):
        for z_index in range(depth):
            x = x0 + x_index * STUD_PITCH_LDU
            z = z0 + z_index * STUD_PITCH_LDU
            connectors.append(
                LegoConnector(
                    id=f"stud_{x_index}_{z_index}",
                    type="stud",
                    position_ldu=(x, -height, z),
                    axis=(0.0, -1.0, 0.0),
                )
            )
            connectors.append(
                LegoConnector(
                    id=f"antistud_{x_index}_{z_index}",
                    type="antistud",
                    position_ldu=(x, 0.0, z),
                    axis=(0.0, 1.0, 0.0),
                )
            )
    return tuple(connectors)


class ArticulatedObject(_BaseArticulatedObject):
    """LEGO profile object model.

    In this profile, each Part is exactly one LEGO catalog piece. Assemblies are
    expressed as connector-level relationships and exported as LDraw MPD files.
    """

    def __post_init__(self) -> None:
        super().__post_init__()
        snapshot = get_active_catalog_snapshot()
        existing_id = self.meta.get("lego_catalog_id")
        existing_sha = self.meta.get("lego_catalog_sha256")
        if existing_id is not None and existing_id != snapshot.catalog_id:
            raise ValidationError(
                f"Model catalog {existing_id!r} does not match active catalog "
                f"{snapshot.catalog_id!r}"
            )
        if existing_sha is not None and existing_sha != snapshot.sha256:
            raise ValidationError("Model LEGO catalog fingerprint does not match active catalog")
        self.meta["lego_catalog_id"] = snapshot.catalog_id
        self.meta["lego_catalog_sha256"] = snapshot.sha256

    def part(  # type: ignore[override]
        self,
        name: str,
        *,
        part_num: str,
        color: str | int | None = None,
        ldraw_id: str | None = None,
        origin: Origin | None = None,
        meta: dict[str, object] | None = None,
    ) -> Part:
        snapshot = get_active_catalog_snapshot()
        record = resolve_lego_part(part_num)
        lego_color = resolve_lego_color(color)
        snapshot.validate_color(lego_color.ldraw_id)
        approved = snapshot.resolve_part(record.part_num)
        resolved_ldraw_id = str(ldraw_id or approved.ldraw_id)
        if resolved_ldraw_id != approved.ldraw_id:
            raise ValidationError(
                f"Part {record.part_num!r} must use approved LDraw id "
                f"{approved.ldraw_id!r}, got {resolved_ldraw_id!r}"
            )
        spec = LegoPieceSpec(
            part_num=record.part_num,
            ldraw_id=resolved_ldraw_id,
            color_id=lego_color.ldraw_id,
            color_name=lego_color.name,
            origin=origin or Origin(),
            record=record,
        )
        piece_meta: dict[str, object] = dict(meta or {})
        piece_meta["lego"] = spec
        piece_meta["lego_connectors"] = derive_connectors(record)
        piece = Part(
            name=name,
            visuals=[],
            collisions=[],
            inertial=None,
            meta=piece_meta,
            assets=self.assets,
        )
        self.parts.append(piece)
        self._part_index[name] = piece
        return piece

    def lego_connection(
        self,
        parent: str | Part,
        child: str | Part,
        *,
        parent_connector: str,
        child_connector: str,
        connection_type: str = "fixed",
    ) -> LegoConnection:
        connection = LegoConnection(
            parent=_part_name(parent),
            child=_part_name(child),
            parent_connector=str(parent_connector),
            child_connector=str(child_connector),
            connection_type=str(connection_type),
        )
        self.meta.setdefault("lego_connections", [])
        connections = self.meta["lego_connections"]
        if not isinstance(connections, list):
            raise ValidationError("model.meta['lego_connections'] must be a list")
        connections.append(connection)
        return connection

    def lego_connections(self) -> list[LegoConnection]:
        connections = self.meta.get("lego_connections", [])
        if not isinstance(connections, list):
            return []
        return [item for item in connections if isinstance(item, LegoConnection)]


def _part_name(value: str | Part) -> str:
    if isinstance(value, str):
        name = value.strip()
    else:
        name = str(getattr(value, "name", "")).strip()
    if not name:
        raise ValidationError("LEGO connection part name is required")
    return name


def lego_piece_spec(part: Part) -> LegoPieceSpec:
    spec = part.meta.get("lego")
    if not isinstance(spec, LegoPieceSpec):
        raise ValidationError(f"Part {part.name!r} is not a LEGO piece")
    return spec


def lego_connectors(part: Part) -> tuple[LegoConnector, ...]:
    connectors = part.meta.get("lego_connectors")
    if not isinstance(connectors, tuple):
        return ()
    return tuple(item for item in connectors if isinstance(item, LegoConnector))


def connector_by_id(part: Part, connector_id: str) -> LegoConnector:
    for connector in lego_connectors(part):
        if connector.id == connector_id:
            return connector
    raise ValidationError(f"Part {part.name!r} has no LEGO connector {connector_id!r}")


def connector_world_position_ldu(part: Part, connector: LegoConnector) -> tuple[float, float, float]:
    spec = lego_piece_spec(part)
    origin = _origin_translation_ldu(spec.origin)
    return (
        origin[0] + connector.position_ldu[0],
        origin[1] + connector.position_ldu[1],
        origin[2] + connector.position_ldu[2],
    )


def _origin_translation_ldu(origin: Origin) -> tuple[float, float, float]:
    x, y, z = origin.xyz
    # SDK uses +Z-up meters; LDraw uses -Y-up LDraw units.
    return (float(x) * 2500.0, -float(z) * 2500.0, float(y) * 2500.0)


def distance_sq(a: Sequence[float], b: Sequence[float]) -> float:
    return sum((float(a[index]) - float(b[index])) ** 2 for index in range(3))
