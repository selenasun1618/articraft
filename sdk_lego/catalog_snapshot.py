from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from sdk import ValidationError

from .catalog import LegoPartRecord

DEFAULT_CATALOG_ID = "structural_v1"


@dataclass(frozen=True, slots=True)
class ApprovedLegoPart:
    part_num: str
    name: str
    ldraw_id: str
    nominal_size: tuple[int, int]
    height_ldu: float
    geometry: str

    def to_record(self, *, catalog_id: str, catalog_sha256: str) -> LegoPartRecord:
        ldraw_stem = self.ldraw_id.removesuffix(".dat")
        return LegoPartRecord(
            part_num=self.part_num,
            name=self.name,
            ldraw_ids=(ldraw_stem,),
            raw={
                "source": "approved_catalog",
                "catalog_id": catalog_id,
                "catalog_sha256": catalog_sha256,
                "nominal_size": list(self.nominal_size),
                "height_ldu": self.height_ldu,
                "geometry": self.geometry,
            },
        )


@dataclass(frozen=True, slots=True)
class LegoCatalogSnapshot:
    schema_version: int
    catalog_id: str
    description: str
    parts: tuple[ApprovedLegoPart, ...]
    allowed_ldraw_color_ids: frozenset[int]
    sha256: str

    @property
    def parts_by_num(self) -> dict[str, ApprovedLegoPart]:
        return {part.part_num.lower(): part for part in self.parts}

    def resolve_part(self, part_num: str) -> ApprovedLegoPart:
        key = str(part_num).strip().lower()
        if not key:
            raise ValidationError("LEGO part_num is required")
        part = self.parts_by_num.get(key)
        if part is None:
            raise ValidationError(
                f"LEGO part {part_num!r} is not approved in catalog {self.catalog_id!r}"
            )
        return part

    def resolve_record(self, part_num: str) -> LegoPartRecord:
        return self.resolve_part(part_num).to_record(
            catalog_id=self.catalog_id,
            catalog_sha256=self.sha256,
        )

    def validate_color(self, ldraw_color_id: int) -> None:
        if int(ldraw_color_id) not in self.allowed_ldraw_color_ids:
            raise ValidationError(
                f"LDraw color {ldraw_color_id!r} is not approved in catalog {self.catalog_id!r}"
            )


def active_catalog_id() -> str:
    return (
        os.environ.get("ARTICRAFT_LEGO_CATALOG_ID", DEFAULT_CATALOG_ID).strip()
        or DEFAULT_CATALOG_ID
    )


def _catalog_path(catalog_id: str) -> Path:
    safe_id = str(catalog_id).strip()
    if not safe_id or Path(safe_id).name != safe_id:
        raise ValidationError(f"Invalid LEGO catalog id: {catalog_id!r}")
    return Path(__file__).resolve().parent / "catalogs" / f"{safe_id}.json"


@lru_cache(maxsize=8)
def load_catalog_snapshot(catalog_id: str = DEFAULT_CATALOG_ID) -> LegoCatalogSnapshot:
    path = _catalog_path(catalog_id)
    if not path.exists():
        raise ValidationError(f"Unknown LEGO catalog snapshot: {catalog_id!r}")
    raw_bytes = path.read_bytes()
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValidationError(f"Invalid LEGO catalog snapshot {catalog_id!r}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationError(f"LEGO catalog snapshot {catalog_id!r} must be a JSON object")
    if payload.get("catalog_id") != catalog_id:
        raise ValidationError(
            f"LEGO catalog id mismatch: expected {catalog_id!r}, got {payload.get('catalog_id')!r}"
        )
    raw_parts = payload.get("parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        raise ValidationError(f"LEGO catalog snapshot {catalog_id!r} has no parts")

    parts: list[ApprovedLegoPart] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_parts):
        if not isinstance(item, dict):
            raise ValidationError(f"LEGO catalog part at index {index} must be an object")
        part = _parse_approved_part(item, index=index)
        key = part.part_num.lower()
        if key in seen:
            raise ValidationError(f"Duplicate LEGO catalog part: {part.part_num!r}")
        seen.add(key)
        parts.append(part)

    raw_colors = payload.get("allowed_ldraw_color_ids")
    if not isinstance(raw_colors, list) or not raw_colors:
        raise ValidationError(f"LEGO catalog snapshot {catalog_id!r} has no approved colors")
    colors = frozenset(int(value) for value in raw_colors)
    return LegoCatalogSnapshot(
        schema_version=int(payload.get("schema_version", 1)),
        catalog_id=catalog_id,
        description=str(payload.get("description") or ""),
        parts=tuple(parts),
        allowed_ldraw_color_ids=colors,
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


def get_active_catalog_snapshot() -> LegoCatalogSnapshot:
    return load_catalog_snapshot(active_catalog_id())


def _parse_approved_part(payload: dict[str, Any], *, index: int) -> ApprovedLegoPart:
    part_num = str(payload.get("part_num") or "").strip()
    name = str(payload.get("name") or "").strip()
    ldraw_id = str(payload.get("ldraw_id") or "").strip()
    nominal_size = payload.get("nominal_size")
    if not part_num or not name or not ldraw_id:
        raise ValidationError(f"LEGO catalog part at index {index} is missing identity fields")
    if not ldraw_id.lower().endswith(".dat"):
        raise ValidationError(f"LEGO catalog part {part_num!r} must use a .dat LDraw id")
    if (
        not isinstance(nominal_size, list)
        or len(nominal_size) != 2
        or any(int(value) <= 0 for value in nominal_size)
    ):
        raise ValidationError(f"LEGO catalog part {part_num!r} has invalid nominal_size")
    height_ldu = float(payload.get("height_ldu", 0.0))
    if height_ldu <= 0:
        raise ValidationError(f"LEGO catalog part {part_num!r} has invalid height_ldu")
    return ApprovedLegoPart(
        part_num=part_num,
        name=name,
        ldraw_id=ldraw_id,
        nominal_size=(int(nominal_size[0]), int(nominal_size[1])),
        height_ldu=height_ldu,
        geometry=str(payload.get("geometry") or "rectangular"),
    )
