from __future__ import annotations

from dataclasses import dataclass

from sdk import ArticulatedObject as SdkArticulatedObject
from sdk import ArticulationType, Box, Cylinder, Material, Origin, Part, ValidationError, Visual

from .catalog import LegoColorRecord, resolve_lego_color
from .ldraw_export import LDrawExport, compile_object_to_ldraw_mpd
from .model import (
    ArticulatedObject as NativeLegoObject,
)
from .model import (
    LegoConnection,
    LegoConnector,
    LegoPieceSpec,
    derive_connectors,
    lego_connectors,
    lego_piece_spec,
)
from .top_parts import LDU_TO_M, STUD_PITCH_LDU, LegoTopPart, resolve_top_lego_part


@dataclass(frozen=True, slots=True)
class LegoProxyMetadata:
    """Metadata proving a normal SDK part was generated from a LEGO catalog proxy."""

    part_num: str
    ldraw_id: str
    color_id: int
    color_name: str
    origin: Origin
    dimensions_m: tuple[float, float, float]
    geometry: str
    visual_names: tuple[str, ...]


class LegoProxyObject(SdkArticulatedObject):
    """URDF-friendly LEGO proxy object.

    Parts authored through :meth:`lego_part` are normal SDK parts with primitive
    visuals, plus metadata that allows deterministic conversion back to LDraw MPD.
    """

    def lego_part(
        self,
        name: str,
        *,
        part_num: str,
        color: str | int | None = None,
        origin: Origin | None = None,
        parent: str | Part | None = None,
        parent_connector: str | None = None,
        child_connector: str | None = None,
        meta: dict[str, object] | None = None,
    ) -> Part:
        return add_lego_proxy_part(
            self,
            name,
            part_num=part_num,
            color=color,
            origin=origin,
            parent=parent,
            parent_connector=parent_connector,
            child_connector=child_connector,
            meta=meta,
        )

    def lego_connection(
        self,
        parent: str | Part,
        child: str | Part,
        *,
        parent_connector: str,
        child_connector: str,
        connection_type: str = "fixed",
    ) -> LegoConnection:
        return add_lego_proxy_connection(
            self,
            parent,
            child,
            parent_connector=parent_connector,
            child_connector=child_connector,
            connection_type=connection_type,
        )

    def lego_connections(self) -> list[LegoConnection]:
        return _proxy_connections(self)


def add_lego_proxy_part(
    object_model: SdkArticulatedObject,
    name: str,
    *,
    part_num: str,
    color: str | int | None = None,
    origin: Origin | None = None,
    parent: str | Part | None = None,
    parent_connector: str | None = None,
    child_connector: str | None = None,
    meta: dict[str, object] | None = None,
) -> Part:
    """Add a LEGO catalog part as SDK proxy visuals and MPD-preserving metadata."""

    top_part = resolve_top_lego_part(part_num)
    lego_color = resolve_lego_color(color)
    part_origin = origin or Origin()
    material = _material_from_lego_color(lego_color)
    visuals = _proxy_visuals(top_part, material=material)
    visual_names = tuple(str(visual.name) for visual in visuals if visual.name)
    record = top_part.to_record()
    spec = LegoPieceSpec(
        part_num=record.part_num,
        ldraw_id=record.ldraw_filename,
        color_id=lego_color.ldraw_id,
        color_name=lego_color.name,
        origin=part_origin,
        record=record,
    )
    part_meta: dict[str, object] = dict(meta or {})
    part_meta["lego"] = spec
    part_meta["lego_connectors"] = _proxy_connectors(top_part)
    part_meta["lego_proxy"] = LegoProxyMetadata(
        part_num=spec.part_num,
        ldraw_id=spec.ldraw_id,
        color_id=spec.color_id,
        color_name=spec.color_name,
        origin=part_origin,
        dimensions_m=top_part.dimensions_m,
        geometry=top_part.geometry,
        visual_names=visual_names,
    )
    part = object_model.part(name, visuals=visuals, meta=part_meta)

    if parent is not None:
        _add_fixed_proxy_articulation(object_model, parent, part)
        if parent_connector is not None and child_connector is not None:
            add_lego_proxy_connection(
                object_model,
                parent,
                part,
                parent_connector=parent_connector,
                child_connector=child_connector,
            )
        elif parent_connector is not None or child_connector is not None:
            raise ValidationError(
                "Both parent_connector and child_connector are required for a LEGO proxy connection"
            )

    return part


def add_lego_proxy_connection(
    object_model: SdkArticulatedObject,
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
    connections = object_model.meta.setdefault("lego_connections", [])
    if not isinstance(connections, list):
        raise ValidationError("model.meta['lego_connections'] must be a list")
    connections.append(connection)
    return connection


def compile_proxy_object_to_ldraw_mpd(
    object_model: SdkArticulatedObject,
    *,
    target: str = "buildable",
    validate: bool = True,
) -> LDrawExport:
    """Convert a LEGO proxy-authored SDK object back to native LDraw MPD."""

    native_model = proxy_object_to_native_lego_object(object_model)
    return compile_object_to_ldraw_mpd(native_model, target=target, validate=validate)


def native_lego_object_to_proxy_object(
    object_model: NativeLegoObject,
) -> LegoProxyObject:
    """Render one catalog-native assembly through ordinary SDK proxy visuals."""

    proxy_model = LegoProxyObject(name=f"{object_model.name}_proxy")
    proxy_model.meta.update(
        {
            "lego_catalog_id": object_model.meta.get("lego_catalog_id"),
            "lego_catalog_sha256": object_model.meta.get("lego_catalog_sha256"),
        }
    )
    proxy_parts: dict[str, Part] = {}
    for native_part in object_model.parts:
        spec = lego_piece_spec(native_part)
        proxy_parts[native_part.name] = add_lego_proxy_part(
            proxy_model,
            native_part.name,
            part_num=spec.part_num,
            color=spec.color_id,
            origin=spec.origin,
        )

    child_names: set[str] = set()
    for connection in object_model.lego_connections():
        if connection.child in child_names:
            raise ValidationError(
                f"LEGO proxy URDF requires one parent per piece; "
                f"piece {connection.child!r} has multiple incoming connections"
            )
        child_names.add(connection.child)
        parent = proxy_parts.get(connection.parent)
        child = proxy_parts.get(connection.child)
        if parent is None or child is None:
            raise ValidationError(
                f"LEGO connection references missing proxy part: {connection!r}"
            )
        _add_fixed_proxy_articulation(proxy_model, parent, child)
        add_lego_proxy_connection(
            proxy_model,
            parent,
            child,
            parent_connector=connection.parent_connector,
            child_connector=connection.child_connector,
            connection_type=connection.connection_type,
        )
    return proxy_model


def compile_native_object_to_proxy_urdf_xml(
    object_model: NativeLegoObject,
    *,
    pretty: bool = True,
) -> str:
    from sdk.v0._urdf_export import compile_object_to_urdf_xml

    proxy_model = native_lego_object_to_proxy_object(object_model)
    return compile_object_to_urdf_xml(
        proxy_model,
        pretty=pretty,
        include_physical_collisions=False,
        validate=True,
    )


def proxy_object_to_native_lego_object(object_model: SdkArticulatedObject) -> NativeLegoObject:
    """Build a catalog-native LEGO object from proxy metadata.

    This function is intentionally strict: all parts must be proxy-authored LEGO
    parts, so arbitrary SDK geometry cannot be silently dropped during MPD export.
    """

    native_model = NativeLegoObject(name=object_model.name)
    native_model.meta["lego_connections"] = list(_proxy_connections(object_model))
    for part in object_model.parts:
        _validate_proxy_part(part)
        native_part = Part(
            name=part.name,
            visuals=[],
            collisions=[],
            inertial=None,
            meta={
                "lego": lego_piece_spec(part),
                "lego_connectors": lego_connectors(part),
            },
            assets=native_model.assets,
        )
        native_model.parts.append(native_part)
        native_model._part_index[native_part.name] = native_part
    native_model.articulations.extend(object_model.articulations)
    return native_model


def _proxy_visuals(top_part: LegoTopPart, *, material: Material) -> list[Visual]:
    width_m, depth_m, height_m = top_part.dimensions_m
    stud_height_m = top_part.stud_height_m
    if top_part.geometry == "round":
        body = Visual(
            geometry=Cylinder(radius=width_m / 2.0, length=height_m),
            origin=Origin(xyz=(0.0, 0.0, height_m / 2.0)),
            material=material,
            name="lego_proxy_body",
        )
    else:
        body = Visual(
            geometry=Box(size=(width_m, depth_m, height_m)),
            origin=Origin(xyz=(0.0, 0.0, height_m / 2.0)),
            material=material,
            name="lego_proxy_body",
        )
    visuals = [body]
    for x_index, y_index, x_m, y_m in _stud_positions_m(top_part):
        name = f"lego_proxy_stud_{x_index}_{y_index}"
        visuals.append(
            Visual(
                geometry=Cylinder(radius=top_part.stud_radius_m, length=stud_height_m),
                origin=Origin(xyz=(x_m, y_m, height_m + stud_height_m / 2.0)),
                material=material,
                name=name,
            )
        )
    return visuals


def _proxy_connectors(top_part: LegoTopPart) -> tuple[LegoConnector, ...]:
    return derive_connectors(top_part.to_record())


def _stud_positions_m(top_part: LegoTopPart) -> tuple[tuple[int, int, float, float], ...]:
    x0 = -((top_part.width_studs - 1) * STUD_PITCH_LDU) / 2.0
    y0 = -((top_part.depth_studs - 1) * STUD_PITCH_LDU) / 2.0
    positions: list[tuple[int, int, float, float]] = []
    for x_index in range(top_part.width_studs):
        for y_index in range(top_part.depth_studs):
            positions.append(
                (
                    x_index,
                    y_index,
                    (x0 + x_index * STUD_PITCH_LDU) * LDU_TO_M,
                    (y0 + y_index * STUD_PITCH_LDU) * LDU_TO_M,
                )
            )
    return tuple(positions)


def _material_from_lego_color(lego_color: LegoColorRecord) -> Material:
    name = "lego_" + "_".join(lego_color.name.lower().split())
    return Material(name=name, rgba=_rgb_hex_to_rgba(lego_color.rgb))


def _rgb_hex_to_rgba(value: str) -> tuple[float, float, float, float]:
    text = str(value).strip().lstrip("#")
    if len(text) != 6:
        return (1.0, 1.0, 1.0, 1.0)
    channels = tuple(int(text[index : index + 2], 16) / 255.0 for index in (0, 2, 4))
    return (channels[0], channels[1], channels[2], 1.0)


def _add_fixed_proxy_articulation(
    object_model: SdkArticulatedObject,
    parent: str | Part,
    child: Part,
) -> None:
    parent_part = object_model.get_part(parent)
    parent_origin = _proxy_origin(parent_part)
    child_origin = _proxy_origin(child)
    relative_xyz = tuple(child_origin.xyz[index] - parent_origin.xyz[index] for index in range(3))
    object_model.articulation(
        _unique_articulation_name(object_model, f"{parent_part.name}_to_{child.name}_fixed"),
        ArticulationType.FIXED,
        parent_part,
        child,
        origin=Origin(xyz=relative_xyz, rpy=child_origin.rpy),
        meta={"lego_proxy": True},
    )


def _unique_articulation_name(object_model: SdkArticulatedObject, base: str) -> str:
    existing = {articulation.name for articulation in object_model.articulations}
    if base not in existing:
        return base
    index = 2
    while f"{base}_{index}" in existing:
        index += 1
    return f"{base}_{index}"


def _proxy_origin(part: Part) -> Origin:
    return lego_piece_spec(part).origin


def _validate_proxy_part(part: Part) -> None:
    proxy_meta = part.meta.get("lego_proxy")
    if not isinstance(proxy_meta, LegoProxyMetadata):
        raise ValidationError(
            f"Part {part.name!r} is not a LEGO proxy part; "
            "author it with sdk_lego.proxy.add_lego_proxy_part or LegoProxyObject.lego_part"
        )
    lego_piece_spec(part)
    visual_names = tuple(visual.name for visual in part.visuals)
    if visual_names != proxy_meta.visual_names:
        raise ValidationError(
            f"Part {part.name!r} contains non-proxy visuals and cannot be converted to LDraw"
        )


def _proxy_connections(object_model: SdkArticulatedObject) -> list[LegoConnection]:
    connections = object_model.meta.get("lego_connections", [])
    if not isinstance(connections, list):
        return []
    return [item for item in connections if isinstance(item, LegoConnection)]


def _part_name(value: str | Part) -> str:
    if isinstance(value, str):
        name = value.strip()
    else:
        name = str(getattr(value, "name", "")).strip()
    if not name:
        raise ValidationError("LEGO proxy connection part name is required")
    return name
