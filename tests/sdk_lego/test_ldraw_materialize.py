from __future__ import annotations

from pathlib import Path

import pytest

from agent.compiler import compile_urdf_report
from sdk_lego.ldraw_materialize import (
    LDrawResolutionError,
    LDrawSubfileRef,
    LDrawTriangle,
    flatten_ldraw_document,
    materialize_ldraw_mpd_to_obj,
    parse_ldraw_mpd,
)


def test_parse_mpd_file_blocks_and_primitives() -> None:
    document = parse_ldraw_mpd(
        """
0 FILE main.ldr
1 4 10 0 0 1 0 0 0 1 0 0 0 1 part.dat
0 FILE part.dat
3 16 0 0 0 1 0 0 0 1 0
4 1 0 0 0 1 0 0 1 1 0 0 1 0
""".strip()
    )

    assert document.main_file == "main.ldr"
    assert set(document.files) == {"main.ldr", "part.dat"}
    assert isinstance(document.files["main.ldr"].commands[0], LDrawSubfileRef)
    assert isinstance(document.files["part.dat"].commands[0], LDrawTriangle)
    assert len(document.files["part.dat"].commands) == 2


def test_flatten_transforms_type_1_refs_and_inherits_color() -> None:
    document = parse_ldraw_mpd(
        """
0 FILE main.ldr
1 4 10 0 0 1 0 0 0 1 0 0 0 1 part.dat
0 FILE part.dat
3 16 0 0 0 1 0 0 0 1 0
""".strip()
    )

    mesh = flatten_ldraw_document(document)

    assert len(mesh.triangles) == 1
    triangle = mesh.triangles[0]
    assert triangle.color_id == 4
    assert triangle.vertices == ((10.0, 0.0, 0.0), (11.0, 0.0, 0.0), (10.0, 1.0, 0.0))


def test_flatten_triangulates_quads() -> None:
    document = parse_ldraw_mpd(
        """
0 FILE main.ldr
4 14 0 0 0 1 0 0 1 1 0 0 1 0
""".strip()
    )

    mesh = flatten_ldraw_document(document)

    assert len(mesh.triangles) == 2
    assert [triangle.color_id for triangle in mesh.triangles] == [14, 14]
    assert mesh.triangles[0].vertices == ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0))
    assert mesh.triangles[1].vertices == ((0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0))


def test_materialize_resolves_local_dat_file(tmp_path: Path) -> None:
    parts_dir = tmp_path / "ldraw" / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "tri.dat").write_text(
        "3 16 0 0 0 10 0 0 0 10 0\n",
        encoding="utf-8",
    )
    mpd_text = "0 FILE main.ldr\n1 1 0 0 0 1 0 0 0 1 0 0 0 1 tri.dat\n"

    result = materialize_ldraw_mpd_to_obj(
        mpd_text,
        output_path=tmp_path / "out" / "model.obj",
        library_root=tmp_path / "ldraw",
    )

    assert result.triangle_count == 1
    assert result.material_count == 1
    assert result.obj_path.exists()
    assert result.mtl_path.exists()
    obj_text = result.obj_path.read_text(encoding="utf-8")
    assert "mtllib model.mtl" in obj_text
    assert "usemtl ldraw_1_blue" in obj_text
    assert "f 1 2 3" in obj_text


def test_materialize_embedded_mpd_to_obj(tmp_path: Path) -> None:
    mpd_text = """
0 FILE main.ldr
1 4 0 0 0 1 0 0 0 1 0 0 0 1 embedded.dat
0 FILE embedded.dat
3 16 0 0 0 10 0 0 0 10 0
""".strip()

    result = materialize_ldraw_mpd_to_obj(
        mpd_text,
        output_path=tmp_path / "model.obj",
        library_root=tmp_path / "empty_ldraw",
    )

    assert result.triangle_count == 1
    assert "usemtl ldraw_4_red" in result.obj_path.read_text(encoding="utf-8")


def test_missing_subfile_raises_clear_error(tmp_path: Path) -> None:
    mpd_text = "0 FILE main.ldr\n1 4 0 0 0 1 0 0 0 1 0 0 0 1 missing.dat\n"

    with pytest.raises(LDrawResolutionError, match="missing.dat"):
        materialize_ldraw_mpd_to_obj(
            mpd_text,
            output_path=tmp_path / "model.obj",
            library_root=tmp_path / "ldraw",
        )


def test_lego_compile_writes_render_mesh_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "ldraw"
    parts_dir = cache_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "3001.dat").write_text(
        "3 16 0 0 0 20 0 0 0 20 0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARTICRAFT_LDRAW_CACHE_DIR", str(cache_dir))
    monkeypatch.delenv("REBRICKABLE_API_KEY", raising=False)
    monkeypatch.setenv("ARTICRAFT_LEGO_CACHE_DIR", str(tmp_path / "rebrickable"))
    script = tmp_path / "model.py"
    script.write_text(
        """
from __future__ import annotations

from sdk_lego import ArticulatedObject, Origin


object_model = ArticulatedObject(name="lego_single")
object_model.part("brick", part_num="3001", color="red", origin=Origin())
""".strip(),
        encoding="utf-8",
    )

    report = compile_urdf_report(script, sdk_package="sdk_lego", target="visual")

    assert report.warnings == []
    assert (tmp_path / "assets" / "lego" / "model.obj").exists()
    assert (tmp_path / "assets" / "lego" / "model.mtl").exists()
    assert report.sidecar_json is not None
    assert report.sidecar_json["render_mesh"]["path"] == "assets/lego/model.obj"
    assert report.sidecar_json["render_mesh"]["triangle_count"] == 1
