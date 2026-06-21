from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sdk import ValidationError

_REBRICKABLE_BASE_URL = "https://rebrickable.com/api/v3"
_NAME_SIZE_RE = re.compile(r"\b(?P<x>\d+)\s*x\s*(?P<y>\d+)\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DEFAULT_CACHE_ROOT = Path("data/cache/lego/rebrickable")


@dataclass(frozen=True, slots=True)
class LegoPartRecord:
    part_num: str
    name: str
    part_cat_id: int | None = None
    ldraw_ids: tuple[str, ...] = ()
    lego_ids: tuple[str, ...] = ()
    bricklink_ids: tuple[str, ...] = ()
    year_from: int | None = None
    year_to: int | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def ldraw_filename(self) -> str:
        part_id = self.ldraw_ids[0] if self.ldraw_ids else self.part_num
        return f"{part_id}.dat" if not part_id.lower().endswith(".dat") else part_id

    @property
    def nominal_size(self) -> tuple[int, int] | None:
        match = _NAME_SIZE_RE.search(self.name)
        if match is None:
            return _COMMON_PART_SIZES.get(self.part_num)
        return (int(match.group("x")), int(match.group("y")))


@dataclass(frozen=True, slots=True)
class LegoColorRecord:
    color_id: int
    name: str
    rgb: str
    ldraw_id: int


_COMMON_PART_SIZES: dict[str, tuple[int, int]] = {
    "3001": (2, 4),
    "3002": (2, 3),
    "3003": (2, 2),
    "3004": (1, 2),
    "3005": (1, 1),
    "3010": (1, 4),
    "3020": (2, 4),
    "3021": (2, 3),
    "3022": (2, 2),
    "3023": (1, 2),
    "3024": (1, 1),
    "3034": (2, 8),
    "3622": (1, 3),
    "3710": (1, 4),
    "3795": (2, 6),
    "3062b": (1, 1),
}

_FALLBACK_PARTS: dict[str, LegoPartRecord] = {
    part_num: LegoPartRecord(
        part_num=part_num,
        name=name,
        ldraw_ids=(part_num,),
        raw={"source": "fallback"},
    )
    for part_num, name in {
        "3001": "Brick 2 x 4",
        "3002": "Brick 2 x 3",
        "3003": "Brick 2 x 2",
        "3004": "Brick 1 x 2",
        "3005": "Brick 1 x 1",
        "3010": "Brick 1 x 4",
        "3020": "Plate 2 x 4",
        "3021": "Plate 2 x 3",
        "3022": "Plate 2 x 2",
        "3023": "Plate 1 x 2",
        "3024": "Plate 1 x 1",
        "3034": "Plate 2 x 8",
        "3622": "Brick 1 x 3",
        "3710": "Plate 1 x 4",
        "3795": "Plate 2 x 6",
        "3062b": "Brick Round 1 x 1 Open Stud",
    }.items()
}

_FALLBACK_COLORS_BY_NAME: dict[str, LegoColorRecord] = {
    "black": LegoColorRecord(0, "Black", "05131D", 0),
    "blue": LegoColorRecord(1, "Blue", "0055BF", 1),
    "green": LegoColorRecord(2, "Green", "237841", 2),
    "red": LegoColorRecord(4, "Red", "C91A09", 4),
    "dark_pink": LegoColorRecord(5, "Dark Pink", "C870A0", 5),
    "salmon": LegoColorRecord(12, "Salmon", "F2705E", 12),
    "pink": LegoColorRecord(13, "Pink", "FC97AC", 13),
    "bright_pink": LegoColorRecord(29, "Bright Pink", "E4ADC8", 29),
    "coral": LegoColorRecord(1050, "Coral", "FF698F", 353),
    "white": LegoColorRecord(15, "White", "FFFFFF", 15),
    "yellow": LegoColorRecord(14, "Yellow", "F2CD37", 14),
    "light_gray": LegoColorRecord(71, "Light Bluish Gray", "A0A5A9", 71),
    "light_bluish_gray": LegoColorRecord(71, "Light Bluish Gray", "A0A5A9", 71),
    "dark_gray": LegoColorRecord(72, "Dark Bluish Gray", "6C6E68", 72),
    "dark_bluish_gray": LegoColorRecord(72, "Dark Bluish Gray", "6C6E68", 72),
}


def _cache_root() -> Path:
    configured = os.environ.get("ARTICRAFT_LEGO_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    return _DEFAULT_CACHE_ROOT


def _api_key() -> str | None:
    value = os.environ.get("REBRICKABLE_API_KEY")
    return value.strip() if value and value.strip() else None


def _get_json(path: str, params: dict[str, object] | None = None) -> dict[str, Any]:
    key = _api_key()
    if key is None:
        raise FileNotFoundError("REBRICKABLE_API_KEY is not configured")
    url = f"{_REBRICKABLE_BASE_URL}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"key {key}", "User-Agent": "articraft-lego/0.1"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValidationError("Rebrickable returned a non-object payload")
    return payload


def _part_cache_path(part_num: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in part_num)
    return _cache_root() / "parts" / f"{safe}.json"


def _search_cache_path(query: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in query.lower())[:80]
    return _cache_root() / "search" / f"{safe or 'blank'}.json"


def _read_cached_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _write_cached_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        return


def _list_external_ids(payload: dict[str, Any], system: str) -> tuple[str, ...]:
    external = payload.get("external_ids")
    if not isinstance(external, dict):
        return ()
    values = external.get(system)
    if not isinstance(values, list):
        return ()
    return tuple(str(value) for value in values if str(value).strip())


def _record_from_payload(payload: dict[str, Any]) -> LegoPartRecord:
    part_num = str(payload.get("part_num") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not part_num or not name:
        raise ValidationError("Rebrickable part payload is missing part_num or name")
    part_cat_id = payload.get("part_cat_id")
    return LegoPartRecord(
        part_num=part_num,
        name=name,
        part_cat_id=int(part_cat_id) if isinstance(part_cat_id, int) else None,
        ldraw_ids=_list_external_ids(payload, "LDraw"),
        lego_ids=_list_external_ids(payload, "LEGO"),
        bricklink_ids=_list_external_ids(payload, "BrickLink"),
        year_from=payload.get("year_from") if isinstance(payload.get("year_from"), int) else None,
        year_to=payload.get("year_to") if isinstance(payload.get("year_to"), int) else None,
        raw=dict(payload),
    )


def _search_tokens(value: str) -> tuple[str, ...]:
    normalized = value.lower().replace("×", "x")
    return tuple(_TOKEN_RE.findall(normalized))


def _search_phrase(value: str) -> str:
    return " ".join(_search_tokens(value))


def _part_search_score(record: LegoPartRecord, *, query: str) -> float:
    query_phrase = _search_phrase(query)
    query_tokens = _search_tokens(query)
    if not query_tokens:
        return 0.0

    name_phrase = _search_phrase(record.name)
    part_num_phrase = _search_phrase(record.part_num)
    haystack = " ".join(
        (part_num_phrase, name_phrase, *(_search_phrase(item) for item in record.ldraw_ids))
    )
    haystack_tokens = set(_search_tokens(haystack))

    score = 0.0
    if query_phrase == part_num_phrase:
        score += 200.0
    if query_phrase == name_phrase:
        score += 160.0
    elif query_phrase and query_phrase in name_phrase:
        score += 90.0

    matched = sum(1 for token in query_tokens if token in haystack_tokens)
    coverage = matched / max(len(query_tokens), 1)
    score += coverage * 60.0
    if matched == len(query_tokens):
        score += 40.0

    # Prefer unprinted/base shapes when the query does not ask for decoration.
    lowered_name = record.name.lower()
    if "print" in lowered_name or "pattern" in lowered_name or "sticker" in lowered_name:
        score -= 12.0
    if "pr" in record.part_num.lower() and "print" not in query_phrase:
        score -= 8.0

    # Small tie-break toward concise generic names over long decorated names.
    score -= min(len(record.name), 120) / 1000.0
    return score


def _dedupe_ranked_parts(
    records: list[LegoPartRecord], *, query: str, limit: int
) -> list[LegoPartRecord]:
    best_by_part_num: dict[str, tuple[float, LegoPartRecord]] = {}
    for record in records:
        score = _part_search_score(record, query=query)
        if score <= 0:
            continue
        current = best_by_part_num.get(record.part_num)
        if current is None or score > current[0]:
            best_by_part_num[record.part_num] = (score, record)
    ranked = sorted(
        best_by_part_num.values(),
        key=lambda item: (-item[0], item[1].name.lower(), item[1].part_num),
    )
    return [record for _, record in ranked[:limit]]


def resolve_lego_part(part_num: str) -> LegoPartRecord:
    key = str(part_num).strip()
    if not key:
        raise ValidationError("part_num is required")
    cached = _read_cached_json(_part_cache_path(key))
    if cached is not None:
        return _record_from_payload(cached)
    try:
        payload = _get_json(f"/lego/parts/{urllib.parse.quote(key)}/")
    except Exception:
        fallback = _FALLBACK_PARTS.get(key)
        if fallback is not None:
            return fallback
        raise
    _write_cached_json(_part_cache_path(key), payload)
    return _record_from_payload(payload)


def find_lego_parts(query: str, *, limit: int = 5) -> list[LegoPartRecord]:
    normalized_query = " ".join(str(query).strip().split())
    if not normalized_query:
        return []
    limit = max(1, int(limit))
    candidate_records = list(_FALLBACK_PARTS.values())
    if normalized_query in _FALLBACK_PARTS:
        return [_FALLBACK_PARTS[normalized_query]][:limit]

    cached = _read_cached_json(_search_cache_path(normalized_query))
    payload: dict[str, Any] | None = cached
    if payload is None:
        try:
            payload = _get_json(
                "/lego/parts/",
                {
                    "search": normalized_query,
                    "page_size": min(max(limit, 10), 100),
                    "inc_part_details": 1,
                },
            )
        except Exception:
            return _dedupe_ranked_parts(candidate_records, query=normalized_query, limit=limit)
        _write_cached_json(_search_cache_path(normalized_query), payload)
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return _dedupe_ranked_parts(candidate_records, query=normalized_query, limit=limit)
    for item in raw_results:
        if isinstance(item, dict):
            try:
                candidate_records.append(_record_from_payload(item))
            except ValidationError:
                continue
    return _dedupe_ranked_parts(candidate_records, query=normalized_query, limit=limit)


def resolve_lego_color(value: str | int | None) -> LegoColorRecord:
    if value is None:
        return LegoColorRecord(16, "Current Color", "FFFFFF", 16)
    if isinstance(value, int):
        return LegoColorRecord(value, str(value), "FFFFFF", value)
    normalized = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if normalized.isdigit():
        color_id = int(normalized)
        return LegoColorRecord(color_id, normalized, "FFFFFF", color_id)
    color = _FALLBACK_COLORS_BY_NAME.get(normalized)
    if color is None:
        raise ValidationError(f"Unknown LEGO color: {value!r}")
    return color
