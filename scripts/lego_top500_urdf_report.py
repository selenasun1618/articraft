from __future__ import annotations

import argparse
import csv
import gzip
import html
import json
import re
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

DOWNLOAD_BASE = "https://cdn.rebrickable.com/media/downloads"
PARTS_URL = f"{DOWNLOAD_BASE}/parts.csv.gz"
INVENTORY_PARTS_URL = f"{DOWNLOAD_BASE}/inventory_parts.csv.gz"

STUD_M = 0.008
BRICK_H_M = 0.0096
PLATE_H_M = 0.0032
STUD_RADIUS_M = 0.0024
STUD_H_M = 0.0016

SIZE_RE = re.compile(r"\b(?P<w>\d+)\s*x\s*(?P<d>\d+)(?:\s*x\s*(?P<h>\d+(?:\.\d+)?))?\b", re.I)


@dataclass(frozen=True, slots=True)
class PartInfo:
    part_num: str
    name: str
    part_cat_id: str
    ldraw_id: str
    frequency: int
    proxy_kind: str
    width_studs: int | None
    depth_studs: int | None
    height_m: float
    confidence: str


def _download(url: str, path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "articraft-lego-top500/0.1"})
    with urllib.request.urlopen(req, timeout=120) as response:
        path.write_bytes(response.read())


def _parse_external_ids(raw: str) -> tuple[str, ...]:
    text = (raw or "").strip()
    if not text:
        return ()
    try:
        payload = json.loads(text.replace("'", '"'))
    except Exception:
        try:
            import ast

            payload = ast.literal_eval(text)
        except Exception:
            return ()
    if not isinstance(payload, dict):
        return ()
    value = payload.get("LDraw")
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _load_parts(path: Path) -> dict[str, dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return {row["part_num"]: row for row in csv.DictReader(handle)}


def _top_part_frequencies(path: Path, *, limit: int) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("is_spare", "").lower() in {"t", "true", "1"}:
                continue
            part_num = (row.get("part_num") or "").strip()
            if not part_num:
                continue
            try:
                quantity = int(row.get("quantity") or "1")
            except ValueError:
                quantity = 1
            counts[part_num] += max(quantity, 0)
    return counts.most_common(limit)


def _infer_proxy(row: dict[str, str], frequency: int) -> PartInfo:
    part_num = row["part_num"]
    name = row.get("name", part_num)
    ldraw_ids = _parse_external_ids(row.get("external_ids", ""))
    ldraw_id = (ldraw_ids[0] if ldraw_ids else part_num) + (
        "" if (ldraw_ids[0] if ldraw_ids else part_num).lower().endswith(".dat") else ".dat"
    )
    lowered = name.lower()
    match = SIZE_RE.search(name)
    width = int(match.group("w")) if match else None
    depth = int(match.group("d")) if match else None
    height_token = float(match.group("h")) if match and match.group("h") else None

    proxy_kind = "box"
    confidence = "low"
    height_m = BRICK_H_M
    if "plate" in lowered or "tile" in lowered:
        height_m = PLATE_H_M
    if height_token is not None:
        height_m = height_token * PLATE_H_M
    if "round" in lowered or "cylinder" in lowered or "cone" in lowered:
        proxy_kind = "cylinder"
    if match is not None:
        confidence = "medium"
    if any(word in lowered for word in ("brick", "plate", "tile")) and match is not None:
        confidence = "high"

    return PartInfo(
        part_num=part_num,
        name=name,
        part_cat_id=row.get("part_cat_id", ""),
        ldraw_id=ldraw_id,
        frequency=frequency,
        proxy_kind=proxy_kind,
        width_studs=width,
        depth_studs=depth,
        height_m=height_m,
        confidence=confidence,
    )


def _dimensions(info: PartInfo) -> tuple[float, float, float]:
    width = (info.width_studs or 1) * STUD_M
    depth = (info.depth_studs or 1) * STUD_M
    return width, depth, info.height_m


def _write_urdf(info: PartInfo, path: Path) -> None:
    width, depth, height = _dimensions(info)
    robot = ET.Element("robot", {"name": f"lego_proxy_{info.part_num}"})
    link = ET.SubElement(robot, "link", {"name": "piece"})
    mat = ET.SubElement(robot, "material", {"name": "lego_light_gray"})
    ET.SubElement(mat, "color", {"rgba": "0.62 0.62 0.58 1"})
    visual = ET.SubElement(link, "visual", {"name": "proxy_body"})
    ET.SubElement(visual, "origin", {"xyz": f"0 0 {height / 2:.6g}", "rpy": "0 0 0"})
    geometry = ET.SubElement(visual, "geometry")
    if info.proxy_kind == "cylinder":
        ET.SubElement(
            geometry,
            "cylinder",
            {"radius": f"{max(width, depth) / 2:.6g}", "length": f"{height:.6g}"},
        )
    else:
        ET.SubElement(geometry, "box", {"size": f"{width:.6g} {depth:.6g} {height:.6g}"})
    ET.SubElement(visual, "material", {"name": "lego_light_gray"})

    if info.width_studs and info.depth_studs and info.confidence in {"medium", "high"}:
        x0 = -((info.width_studs - 1) * STUD_M) / 2
        y0 = -((info.depth_studs - 1) * STUD_M) / 2
        for x_index in range(info.width_studs):
            for y_index in range(info.depth_studs):
                stud = ET.SubElement(link, "visual", {"name": f"proxy_stud_{x_index}_{y_index}"})
                ET.SubElement(
                    stud,
                    "origin",
                    {
                        "xyz": f"{x0 + x_index * STUD_M:.6g} {y0 + y_index * STUD_M:.6g} {height + STUD_H_M / 2:.6g}",
                        "rpy": "0 0 0",
                    },
                )
                stud_geom = ET.SubElement(stud, "geometry")
                ET.SubElement(
                    stud_geom,
                    "cylinder",
                    {"radius": f"{STUD_RADIUS_M:.6g}", "length": f"{STUD_H_M:.6g}"},
                )
                ET.SubElement(stud, "material", {"name": "lego_light_gray"})

    _indent(robot)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ET.tostring(robot, encoding="unicode"), encoding="utf-8")


def _svg_render(info: PartInfo) -> str:
    width, depth, _height = _dimensions(info)
    scale = 900.0
    w = max(width * scale, 28)
    d = max(depth * scale, 28)
    pad = 18
    body_x = pad
    body_y = pad + 10
    svg_w = int(w + 2 * pad)
    svg_h = int(d + 2 * pad + 24)
    rx = 8 if info.proxy_kind == "cylinder" else 2
    parts = [
        f'<svg viewBox="0 0 {svg_w} {svg_h}" width="180" height="140" xmlns="http://www.w3.org/2000/svg">',
        '<rect width="100%" height="100%" fill="#f7f7f7"/>',
        f'<rect x="{body_x:.1f}" y="{body_y:.1f}" width="{w:.1f}" height="{d:.1f}" rx="{rx}" fill="#b8b8b0" stroke="#444" stroke-width="1.2"/>',
    ]
    if info.width_studs and info.depth_studs and info.confidence in {"medium", "high"}:
        for x_index in range(info.width_studs):
            for y_index in range(info.depth_studs):
                cx = body_x + (x_index + 0.5) * w / info.width_studs
                cy = body_y + (y_index + 0.5) * d / info.depth_studs
                r = max(min(w / info.width_studs, d / info.depth_studs) * 0.22, 2.5)
                parts.append(
                    f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="#d0d0ca" stroke="#555" stroke-width="0.8"/>'
                )
    parts.append(
        f'<text x="{pad}" y="{svg_h - 8}" font-size="10" font-family="monospace" fill="#333">{html.escape(info.part_num)} {html.escape(info.confidence)}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _write_html(parts: list[PartInfo], output_dir: Path) -> None:
    rows = []
    for index, info in enumerate(parts, start=1):
        urdf_rel = f"urdf/{info.part_num}.urdf"
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{_svg_render(info)}</td>"
            "<td>"
            f"<b>{html.escape(info.part_num)}</b><br/>"
            f"{html.escape(info.name)}<br/>"
            f"<small>LDraw: {html.escape(info.ldraw_id)}<br/>"
            f"Frequency: {info.frequency:,}<br/>"
            f"Proxy: {html.escape(info.proxy_kind)} / {html.escape(info.confidence)}<br/>"
            f"Stud footprint: {info.width_studs or '?'} x {info.depth_studs or '?'}<br/>"
            f"<a href='{html.escape(urdf_rel)}'>URDF</a></small>"
            "</td>"
            "</tr>"
        )
    html_text = f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\"/>
  <title>Top 500 LEGO URDF Proxy Audit</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    td, th {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
    th {{ background: #eee; position: sticky; top: 0; }}
    small {{ color: #444; line-height: 1.45; }}
  </style>
</head>
<body>
  <h1>Top 500 LEGO URDF Proxy Audit</h1>
  <p>Left column is a lightweight SVG rendering of the generated URDF proxy. Right column is the Rebrickable/LDraw description and links to the generated URDF file.</p>
  <table>
    <thead><tr><th>Rank</th><th>Rendered URDF proxy</th><th>LDraw/Rebrickable description</th></tr></thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    (output_dir / "index.html").write_text(html_text, encoding="utf-8")


def _indent(elem: ET.Element, level: int = 0) -> None:
    indent = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        for child in elem:
            _indent(child, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
    elif level and (not elem.tail or not elem.tail.strip()):
        elem.tail = indent


def generate_report(*, cache_dir: Path, output_dir: Path, limit: int = 500) -> list[PartInfo]:
    parts_gz = cache_dir / "parts.csv.gz"
    inventory_parts_gz = cache_dir / "inventory_parts.csv.gz"
    _download(PARTS_URL, parts_gz)
    _download(INVENTORY_PARTS_URL, inventory_parts_gz)
    parts_by_num = _load_parts(parts_gz)
    ranked = _top_part_frequencies(inventory_parts_gz, limit=limit * 3)
    selected: list[PartInfo] = []
    seen: set[str] = set()
    for part_num, frequency in ranked:
        if part_num in seen:
            continue
        row = parts_by_num.get(part_num)
        if row is None:
            continue
        selected.append(_infer_proxy(row, frequency))
        seen.add(part_num)
        if len(selected) >= limit:
            break

    urdf_dir = output_dir / "urdf"
    urdf_dir.mkdir(parents=True, exist_ok=True)
    for info in selected:
        _write_urdf(info, urdf_dir / f"{info.part_num}.urdf")
    _write_html(selected, output_dir)
    (output_dir / "parts.json").write_text(
        json.dumps([asdict(info) for info in selected], indent=2),
        encoding="utf-8",
    )
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache/lego/rebrickable_csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/local/lego_top500_urdf_report"))
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    parts = generate_report(cache_dir=args.cache_dir, output_dir=args.output_dir, limit=args.limit)
    confidence = Counter(part.confidence for part in parts)
    print(f"wrote {len(parts)} parts to {args.output_dir}")
    print("confidence:", dict(confidence))
    print("html:", args.output_dir / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
