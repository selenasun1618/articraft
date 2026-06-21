from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from sdk import ValidationError

from .catalog import LegoPartRecord

LDU_TO_M = 0.0004
STUD_PITCH_LDU = 20.0
STUD_RADIUS_LDU = 6.0
STUD_HEIGHT_LDU = 4.0
PLATE_HEIGHT_LDU = 8.0
BRICK_HEIGHT_LDU = 24.0

LegoProxyGeometryFamily = Literal["rectangular", "round"]

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class LegoTopPart:
    """Seed record for common LEGO parts that can be proxied as SDK visuals."""

    part_num: str
    name: str
    ldraw_id: str
    width_studs: int
    depth_studs: int
    height_ldu: float
    geometry: LegoProxyGeometryFamily = "rectangular"
    rank: int = 0

    @property
    def ldraw_filename(self) -> str:
        return self.ldraw_id if self.ldraw_id.lower().endswith(".dat") else f"{self.ldraw_id}.dat"

    @property
    def dimensions_ldu(self) -> tuple[float, float, float]:
        return (
            float(self.width_studs) * STUD_PITCH_LDU,
            float(self.depth_studs) * STUD_PITCH_LDU,
            float(self.height_ldu),
        )

    @property
    def dimensions_m(self) -> tuple[float, float, float]:
        return tuple(value * LDU_TO_M for value in self.dimensions_ldu)

    @property
    def stud_radius_m(self) -> float:
        return STUD_RADIUS_LDU * LDU_TO_M

    @property
    def stud_height_m(self) -> float:
        return STUD_HEIGHT_LDU * LDU_TO_M

    def to_record(self) -> LegoPartRecord:
        return LegoPartRecord(
            part_num=self.part_num,
            name=self.name,
            ldraw_ids=(self.ldraw_id.removesuffix(".dat"),),
            raw={"source": "top_parts_seed", "proxy_geometry": self.geometry},
        )


_SEED_TOP_PARTS: tuple[LegoTopPart, ...] = (
    LegoTopPart("3001", "Brick 2 x 4", "3001", 2, 4, BRICK_HEIGHT_LDU, rank=1),
    LegoTopPart("3003", "Brick 2 x 2", "3003", 2, 2, BRICK_HEIGHT_LDU, rank=2),
    LegoTopPart("3004", "Brick 1 x 2", "3004", 1, 2, BRICK_HEIGHT_LDU, rank=3),
    LegoTopPart("3005", "Brick 1 x 1", "3005", 1, 1, BRICK_HEIGHT_LDU, rank=4),
    LegoTopPart("3020", "Plate 2 x 4", "3020", 2, 4, PLATE_HEIGHT_LDU, rank=5),
    LegoTopPart("3022", "Plate 2 x 2", "3022", 2, 2, PLATE_HEIGHT_LDU, rank=6),
    LegoTopPart("3023", "Plate 1 x 2", "3023", 1, 2, PLATE_HEIGHT_LDU, rank=7),
    LegoTopPart("3024", "Plate 1 x 1", "3024", 1, 1, PLATE_HEIGHT_LDU, rank=8),
    LegoTopPart("3002", "Brick 2 x 3", "3002", 2, 3, BRICK_HEIGHT_LDU, rank=9),
    LegoTopPart("3010", "Brick 1 x 4", "3010", 1, 4, BRICK_HEIGHT_LDU, rank=10),
    LegoTopPart("3021", "Plate 2 x 3", "3021", 2, 3, PLATE_HEIGHT_LDU, rank=11),
    LegoTopPart("3034", "Plate 2 x 8", "3034", 2, 8, PLATE_HEIGHT_LDU, rank=12),
    LegoTopPart("3622", "Brick 1 x 3", "3622", 1, 3, BRICK_HEIGHT_LDU, rank=13),
    LegoTopPart("3710", "Plate 1 x 4", "3710", 1, 4, PLATE_HEIGHT_LDU, rank=14),
    LegoTopPart("3795", "Plate 2 x 6", "3795", 2, 6, PLATE_HEIGHT_LDU, rank=15),
    LegoTopPart(
        "3062b",
        "Brick Round 1 x 1 Open Stud",
        "3062b",
        1,
        1,
        BRICK_HEIGHT_LDU,
        geometry="round",
        rank=16,
    ),
)

_TOP_PARTS_BY_NUM: dict[str, LegoTopPart] = {
    part.part_num.lower(): part for part in _SEED_TOP_PARTS
}


def top_lego_parts() -> tuple[LegoTopPart, ...]:
    """Return the current seed of common parts, ordered by extension rank."""

    return tuple(sorted(_SEED_TOP_PARTS, key=lambda part: part.rank))


def resolve_top_lego_part(part_num: str) -> LegoTopPart:
    key = str(part_num).strip().lower()
    if not key:
        raise ValidationError("LEGO part_num is required")
    part = _TOP_PARTS_BY_NUM.get(key)
    if part is None:
        raise ValidationError(f"LEGO part {part_num!r} is not in the proxy top-parts seed index")
    return part


def find_top_lego_parts(query: str, *, limit: int = 5) -> list[LegoTopPart]:
    normalized_query = " ".join(str(query).strip().split())
    if not normalized_query:
        return []
    limit = max(1, int(limit))
    query_tokens = set(_tokens(normalized_query))
    scored: list[tuple[float, LegoTopPart]] = []
    for part in _SEED_TOP_PARTS:
        haystack_tokens = set(_tokens(f"{part.part_num} {part.name} {part.ldraw_id}"))
        score = 0.0
        if normalized_query.lower() == part.part_num.lower():
            score += 200.0
        if normalized_query.lower() == part.name.lower():
            score += 160.0
        if normalized_query.lower() in part.name.lower():
            score += 80.0
        matched = len(query_tokens & haystack_tokens)
        if query_tokens:
            score += 60.0 * (matched / len(query_tokens))
        if matched == len(query_tokens):
            score += 30.0
        if score > 0.0:
            scored.append((score, part))
    scored.sort(key=lambda item: (-item[0], item[1].rank, item[1].part_num))
    return [part for _, part in scored[:limit]]


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(value.lower().replace("\u00d7", "x")))
