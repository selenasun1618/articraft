from __future__ import annotations

from sdk import Origin, TestContext, TestReport, ValidationError

from .catalog import (
    LegoPartRecord,
    fetch_rebrickable_part,
    find_lego_parts,
    resolve_lego_part,
    search_rebrickable_parts,
)
from .catalog_snapshot import (
    ApprovedLegoPart,
    LegoCatalogSnapshot,
    get_active_catalog_snapshot,
    load_catalog_snapshot,
)
from .ldraw_export import LDrawExport, compile_object_to_ldraw_mpd
from .model import ArticulatedObject, LegoConnection, LegoPieceSpec
from .proxy import (
    LegoProxyMetadata,
    LegoProxyObject,
    add_lego_proxy_connection,
    add_lego_proxy_part,
    compile_native_object_to_proxy_urdf_xml,
    compile_proxy_object_to_ldraw_mpd,
    native_lego_object_to_proxy_object,
    proxy_object_to_native_lego_object,
)
from .top_parts import LegoTopPart, find_top_lego_parts, resolve_top_lego_part, top_lego_parts

__all__ = [
    "ArticulatedObject",
    "LDrawExport",
    "LegoConnection",
    "ApprovedLegoPart",
    "LegoCatalogSnapshot",
    "LegoPartRecord",
    "LegoPieceSpec",
    "LegoProxyMetadata",
    "LegoProxyObject",
    "Origin",
    "TestContext",
    "TestReport",
    "ValidationError",
    "LegoTopPart",
    "add_lego_proxy_connection",
    "add_lego_proxy_part",
    "compile_object_to_ldraw_mpd",
    "compile_native_object_to_proxy_urdf_xml",
    "compile_proxy_object_to_ldraw_mpd",
    "find_lego_parts",
    "fetch_rebrickable_part",
    "get_active_catalog_snapshot",
    "find_top_lego_parts",
    "proxy_object_to_native_lego_object",
    "resolve_lego_part",
    "search_rebrickable_parts",
    "load_catalog_snapshot",
    "native_lego_object_to_proxy_object",
    "resolve_top_lego_part",
    "top_lego_parts",
]
