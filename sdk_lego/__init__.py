from __future__ import annotations

from sdk import Origin, TestContext, TestReport, ValidationError

from .catalog import LegoPartRecord, find_lego_parts, resolve_lego_part
from .ldraw_export import LDrawExport, compile_object_to_ldraw_mpd
from .model import ArticulatedObject, LegoConnection, LegoPieceSpec
from .proxy import (
    LegoProxyMetadata,
    LegoProxyObject,
    add_lego_proxy_connection,
    add_lego_proxy_part,
    compile_proxy_object_to_ldraw_mpd,
    proxy_object_to_native_lego_object,
)
from .top_parts import LegoTopPart, find_top_lego_parts, resolve_top_lego_part, top_lego_parts

__all__ = [
    "ArticulatedObject",
    "LDrawExport",
    "LegoConnection",
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
    "compile_proxy_object_to_ldraw_mpd",
    "find_lego_parts",
    "find_top_lego_parts",
    "proxy_object_to_native_lego_object",
    "resolve_lego_part",
    "resolve_top_lego_part",
    "top_lego_parts",
]
