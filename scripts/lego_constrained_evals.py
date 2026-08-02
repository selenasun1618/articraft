from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sdk_lego import ArticulatedObject, compile_native_object_to_proxy_urdf_xml
from sdk_lego.ldraw_export import compile_object_to_ldraw_mpd
from sdk_lego.ldraw_materialize import materialize_ldraw_mpd_to_obj


def build_flamingo() -> ArticulatedObject:
    model = ArticulatedObject(name="constrained_flamingo")
    feet = model.root_piece("feet", part_num="3020", color="black")
    leg_left = model.attach(
        "leg_left",
        part_num="3005",
        color="dark_pink",
        parent=feet,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )
    model.attach(
        "leg_right",
        part_num="3005",
        color="dark_pink",
        parent=feet,
        parent_connector="stud_1_0",
        child_connector="antistud_0_0",
    )
    body = model.attach(
        "body",
        part_num="3001",
        color="dark_pink",
        parent=leg_left,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )
    neck_lower = model.attach(
        "neck_lower",
        part_num="3005",
        color="pink",
        parent=body,
        parent_connector="stud_1_3",
        child_connector="antistud_0_0",
    )
    neck_upper = model.attach(
        "neck_upper",
        part_num="3005",
        color="pink",
        parent=neck_lower,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )
    head = model.attach(
        "head",
        part_num="3062b",
        color="pink",
        parent=neck_upper,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )
    model.attach(
        "beak",
        part_num="3024",
        color="black",
        parent=head,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )
    return model


def build_painted_ladies() -> ArticulatedObject:
    model = ArticulatedObject(name="constrained_painted_ladies")
    street = model.root_piece("street", part_num="3034", color="light_gray")
    colors = ("pink", "blue", "yellow")
    base_connectors = ("stud_0_0", "stud_0_3", "stud_0_6")
    for index, (color, base_connector) in enumerate(zip(colors, base_connectors, strict=True)):
        lower = model.attach(
            f"house_{index}_lower",
            part_num="3004",
            color=color,
            parent=street,
            parent_connector=base_connector,
            child_connector="antistud_0_0",
        )
        upper = model.attach(
            f"house_{index}_upper",
            part_num="3004",
            color=color,
            parent=lower,
            parent_connector="stud_0_0",
            child_connector="antistud_0_0",
        )
        model.attach(
            f"house_{index}_roof",
            part_num="3023",
            color="white",
            parent=upper,
            parent_connector="stud_0_0",
            child_connector="antistud_0_0",
            quarter_turns=index % 2,
        )
    return model


def build_jwst() -> ArticulatedObject:
    model = ArticulatedObject(name="constrained_jwst")
    sunshield = model.root_piece("sunshield", part_num="3034", color="white")
    bus = model.attach(
        "bus",
        part_num="3003",
        color="dark_gray",
        parent=sunshield,
        parent_connector="stud_0_3",
        child_connector="antistud_0_0",
    )
    mirror_hub = model.attach(
        "mirror_hub",
        part_num="3020",
        color="yellow",
        parent=bus,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )
    for index, connector in enumerate(("stud_0_0", "stud_0_3", "stud_1_0", "stud_1_3")):
        model.attach(
            f"mirror_{index}",
            part_num="3062b",
            color="yellow",
            parent=mirror_hub,
            parent_connector=connector,
            child_connector="antistud_0_0",
        )
    return model


BUILDERS = {
    "flamingo": build_flamingo,
    "painted_ladies": build_painted_ladies,
    "jwst": build_jwst,
}


def run_eval(name: str, *, output_root: Path, ldraw_root: Path) -> dict[str, object]:
    model = BUILDERS[name]()
    export = compile_object_to_ldraw_mpd(model, target="strict")
    output_dir = output_root / name
    output_dir.mkdir(parents=True, exist_ok=True)
    mpd_path = output_dir / "model.mpd"
    sidecar_path = output_dir / "model.sidecar.json"
    proxy_urdf_path = output_dir / "model.proxy.urdf"
    mpd_path.write_text(export.mpd_text, encoding="utf-8")
    sidecar_path.write_text(
        json.dumps(export.sidecar_json, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    proxy_urdf_path.write_text(
        compile_native_object_to_proxy_urdf_xml(model),
        encoding="utf-8",
    )
    render = materialize_ldraw_mpd_to_obj(
        export.mpd_text,
        output_path=output_dir / "assets" / "lego" / "model.obj",
        library_root=ldraw_root,
    )
    summary: dict[str, object] = {
        "name": name,
        "catalog": export.sidecar_json["catalog"],
        "piece_count": len(model.parts),
        "connection_count": len(model.lego_connections()),
        "used_part_nums": export.sidecar_json["used_part_nums"],
        "warnings": export.warnings,
        "proxy_urdf_path": proxy_urdf_path.as_posix(),
        "mpd_path": mpd_path.as_posix(),
        "sidecar_path": sidecar_path.as_posix(),
        "render_obj_path": render.obj_path.as_posix(),
        "render_triangle_count": render.triangle_count,
        "render_material_count": render.material_count,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/local/lego_constrained_evals"),
    )
    parser.add_argument(
        "--ldraw-root",
        type=Path,
        default=Path("data/cache/lego/ldraw_official/library/ldraw"),
    )
    parser.add_argument(
        "--eval",
        action="append",
        choices=tuple(BUILDERS),
        dest="evals",
    )
    args = parser.parse_args()
    if not args.ldraw_root.exists():
        raise FileNotFoundError(
            f"LDraw library not found: {args.ldraw_root}. "
            "Download the official complete.zip before running native render evals."
        )
    os.environ["ARTICRAFT_LDRAW_CACHE_DIR"] = str(args.ldraw_root)
    selected = args.evals or list(BUILDERS)
    summaries = [
        run_eval(name, output_root=args.output_root, ldraw_root=args.ldraw_root)
        for name in selected
    ]
    print(json.dumps(summaries, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
