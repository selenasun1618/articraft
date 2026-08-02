from __future__ import annotations

from pathlib import Path

import pytest

from agent.compiler import compile_urdf_report
from agent.tools.find_examples import FindExamplesInvocation, FindExamplesParams
from sdk_lego import ArticulatedObject, Origin, ValidationError
from sdk_lego.ldraw_export import compile_object_to_ldraw_mpd


@pytest.fixture(autouse=True)
def _offline_lego_catalog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("REBRICKABLE_API_KEY", raising=False)
    monkeypatch.setenv("ARTICRAFT_LEGO_CACHE_DIR", str(tmp_path / "rebrickable"))


def _stacked_model() -> ArticulatedObject:
    model = ArticulatedObject(name="lego_stack")
    lower = model.part("lower", part_num="3001", color="red", origin=Origin())
    upper = model.part(
        "upper",
        part_num="3020",
        color="blue",
        origin=Origin(xyz=(0.0, 0.0, 0.0096)),
    )
    model.lego_connection(
        lower,
        upper,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )
    return model


def test_ldraw_export_emits_mpd_and_sidecar() -> None:
    export = compile_object_to_ldraw_mpd(_stacked_model(), target="strict", validate=True)

    assert export.mpd_text.startswith("0 FILE lego_stack.ldr")
    assert "0 !ARTICRAFT_FORMAT LEGO_LDRAW_MPD 1" in export.mpd_text
    assert "3001.dat" in export.mpd_text
    assert "3020.dat" in export.mpd_text
    assert export.sidecar_json["format"] == "articraft_lego_ldraw_sidecar"
    assert [piece["part_num"] for piece in export.sidecar_json["pieces"]] == ["3001", "3020"]
    assert export.sidecar_json["connections"] == [
        {
            "parent": "lower",
            "child": "upper",
            "parent_connector": "stud_0_0",
            "child_connector": "antistud_0_0",
            "connection_type": "fixed",
        }
    ]


def test_buildable_validation_rejects_unconnected_multi_piece_model() -> None:
    model = ArticulatedObject(name="loose")
    model.part("a", part_num="3001", color="red", origin=Origin())
    model.part("b", part_num="3020", color="blue", origin=Origin(xyz=(0.1, 0.0, 0.0)))

    with pytest.raises(ValidationError, match="requires explicit lego_connection"):
        compile_object_to_ldraw_mpd(model, target="buildable", validate=True)


def test_strict_validation_rejects_misaligned_connector_pair() -> None:
    model = ArticulatedObject(name="misaligned")
    lower = model.part("lower", part_num="3001", color="red", origin=Origin())
    upper = model.part(
        "upper",
        part_num="3020",
        color="blue",
        origin=Origin(xyz=(0.001, 0.0, 0.0096)),
    )
    model.lego_connection(
        lower,
        upper,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )

    with pytest.raises(ValidationError, match="endpoints must coincide"):
        compile_object_to_ldraw_mpd(model, target="strict", validate=True)


def test_compiler_routes_sdk_lego_to_ldraw_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "ldraw"
    parts_dir = cache_dir / "parts"
    parts_dir.mkdir(parents=True)
    (parts_dir / "3001.dat").write_text("0 Brick 2 x 4\n", encoding="utf-8")
    (parts_dir / "3020.dat").write_text("0 Plate 2 x 4\n", encoding="utf-8")
    monkeypatch.setenv("ARTICRAFT_LDRAW_CACHE_DIR", str(cache_dir))
    script = tmp_path / "model.py"
    script.write_text(
        """
from __future__ import annotations

from sdk_lego import ArticulatedObject, Origin, TestContext, TestReport


def build_object_model() -> ArticulatedObject:
    model = ArticulatedObject(name="lego_stack")
    lower = model.part("lower", part_num="3001", color="red", origin=Origin())
    upper = model.part("upper", part_num="3020", color="blue", origin=Origin(xyz=(0.0, 0.0, 0.0096)))
    model.lego_connection(lower, upper, parent_connector="stud_0_0", child_connector="antistud_0_0")
    return model


def run_tests() -> TestReport:
    return TestContext(object_model).report()


object_model = build_object_model()
""".strip(),
        encoding="utf-8",
    )

    report = compile_urdf_report(script, sdk_package="sdk_lego", target="strict")

    assert report.artifact_format == "ldraw-mpd"
    assert report.artifact_filename == "model.mpd"
    assert report.output_text.startswith("0 FILE lego_stack.ldr")
    assert "3001.dat" in report.output_text
    assert report.sidecar_json is not None
    assert report.warnings == []


def test_find_examples_uses_lego_catalog_fallback() -> None:
    invocation = FindExamplesInvocation(
        FindExamplesParams(query="brick 2 x 4", limit=2),
        sdk_package="sdk_lego",
        include_paths=True,
    )

    import asyncio

    result = asyncio.run(invocation.execute())

    assert result.is_success()
    assert result.output
    first = result.output[0]
    assert first["part_num"] == "3001"
    assert first["ldraw_filename"] == "3001.dat"
    assert first["catalog_id"] == "structural_v1"
    assert first["path"] == "lego-catalog://structural_v1/parts/3001"
