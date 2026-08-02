from __future__ import annotations

import math
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

    def root_piece(
        self,
        name: str,
        *,
        part_num: str,
        color: str | int | None = None,
        origin: Origin | None = None,
        meta: dict[str, object] | None = None,
    ) -> Part:
        if self.parts:
            raise ValidationError("root_piece() requires an empty LEGO assembly")
        return self.part(
            name,
            part_num=part_num,
            color=color,
            origin=origin,
            meta=meta,
        )

    def attach(
        self,
        name: str,
        *,
        part_num: str,
        color: str | int | None,
        parent: str | Part,
        parent_connector: str,
        child_connector: str,
        quarter_turns: int = 0,
        meta: dict[str, object] | None = None,
    ) -> Part:
        parent_part = self.get_part(parent)
        parent_frame = connector_by_id(parent_part, parent_connector)
        child_record = resolve_lego_part(part_num)
        child_connectors = derive_connectors(child_record)
        child_frame = _connector_from_sequence(
            child_connectors,
            child_connector,
            part_name=name,
        )
        if not connectors_compatible(parent_frame, child_frame):
            raise ValidationError(
                "Incompatible LEGO connectors: "
                f"{parent_part.name}.{parent_frame.id} ({parent_frame.type}) -> "
                f"{name}.{child_frame.id} ({child_frame.type})"
            )

        parent_origin = lego_piece_spec(parent_part).origin
        parent_rotation = _rpy_rotation_matrix(parent_origin.rpy)
        clocking = _rpy_rotation_matrix((0.0, 0.0, int(quarter_turns) * math.pi / 2.0))
        child_rotation = _mat3_multiply(parent_rotation, clocking)
        parent_local = _ldraw_vector_to_sdk_m(parent_frame.position_ldu)
        child_local = _ldraw_vector_to_sdk_m(child_frame.position_ldu)
        parent_world = _vec_add(parent_origin.xyz, _mat3_vec(parent_rotation, parent_local))
        child_xyz = _vec_sub(parent_world, _mat3_vec(child_rotation, child_local))
        child_origin = Origin(
            xyz=child_xyz,
            rpy=_rotation_matrix_to_rpy(child_rotation),
        )
        child = self.part(
            name,
            part_num=part_num,
            color=color,
            origin=child_origin,
            meta=meta,
        )
        self.lego_connection(
            parent_part,
            child,
            parent_connector=parent_connector,
            child_connector=child_connector,
        )
        return child

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


def connectors_compatible(a: LegoConnector, b: LegoConnector) -> bool:
    return frozenset((a.type, b.type)) in {
        frozenset(("stud", "antistud")),
        frozenset(("bar", "clip")),
        frozenset(("ball", "socket")),
        frozenset(("towball", "towball_socket")),
        frozenset(("rail", "groove")),
    }


def connector_world_position_ldu(part: Part, connector: LegoConnector) -> tuple[float, float, float]:
    spec = lego_piece_spec(part)
    rotation = _rpy_rotation_matrix(spec.origin.rpy)
    local_sdk = _ldraw_vector_to_sdk_m(connector.position_ldu)
    world_sdk = _vec_add(spec.origin.xyz, _mat3_vec(rotation, local_sdk))
    return _sdk_m_vector_to_ldraw(world_sdk)


def connector_world_axis_sdk(part: Part, connector: LegoConnector) -> tuple[float, float, float]:
    spec = lego_piece_spec(part)
    rotation = _rpy_rotation_matrix(spec.origin.rpy)
    x, y, z = connector.axis
    local_sdk = (float(x), float(z), -float(y))
    world = _mat3_vec(rotation, local_sdk)
    magnitude = math.sqrt(sum(value * value for value in world))
    if magnitude <= 1e-12:
        raise ValidationError(f"Part {part.name!r} connector {connector.id!r} has a zero axis")
    return tuple(value / magnitude for value in world)  # type: ignore[return-value]


def _origin_translation_ldu(origin: Origin) -> tuple[float, float, float]:
    x, y, z = origin.xyz
    # SDK uses +Z-up meters; LDraw uses -Y-up LDraw units.
    return (float(x) * 2500.0, -float(z) * 2500.0, float(y) * 2500.0)


def distance_sq(a: Sequence[float], b: Sequence[float]) -> float:
    return sum((float(a[index]) - float(b[index])) ** 2 for index in range(3))


Matrix3 = tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]


def _connector_from_sequence(
    connectors: Sequence[LegoConnector],
    connector_id: str,
    *,
    part_name: str,
) -> LegoConnector:
    for connector in connectors:
        if connector.id == connector_id:
            return connector
    raise ValidationError(f"Part {part_name!r} has no LEGO connector {connector_id!r}")


def _ldraw_vector_to_sdk_m(values: Sequence[float]) -> tuple[float, float, float]:
    x, y, z = (float(value) for value in values)
    return (x / 2500.0, z / 2500.0, -y / 2500.0)


def _sdk_m_vector_to_ldraw(values: Sequence[float]) -> tuple[float, float, float]:
    x, y, z = (float(value) for value in values)
    return (x * 2500.0, -z * 2500.0, y * 2500.0)


def _rpy_rotation_matrix(rpy: Sequence[float]) -> Matrix3:
    roll, pitch, yaw = (float(value) for value in rpy)
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return (
        (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
        (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
        (-sp, cp * sr, cp * cr),
    )


def _rotation_matrix_to_rpy(matrix: Matrix3) -> tuple[float, float, float]:
    pitch = math.asin(max(-1.0, min(1.0, -matrix[2][0])))
    cp = math.cos(pitch)
    if abs(cp) > 1e-9:
        roll = math.atan2(matrix[2][1], matrix[2][2])
        yaw = math.atan2(matrix[1][0], matrix[0][0])
    else:
        roll = 0.0
        yaw = math.atan2(-matrix[0][1], matrix[1][1])
    return (roll, pitch, yaw)


def _mat3_multiply(a: Matrix3, b: Matrix3) -> Matrix3:
    return tuple(
        tuple(sum(a[row][index] * b[index][column] for index in range(3)) for column in range(3))
        for row in range(3)
    )  # type: ignore[return-value]


def _mat3_vec(matrix: Matrix3, vector: Sequence[float]) -> tuple[float, float, float]:
    return tuple(
        sum(matrix[row][column] * float(vector[column]) for column in range(3))
        for row in range(3)
    )  # type: ignore[return-value]


def _vec_add(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return tuple(float(a[index]) + float(b[index]) for index in range(3))  # type: ignore[return-value]


def _vec_sub(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return tuple(float(a[index]) - float(b[index]) for index in range(3))  # type: ignore[return-value]
