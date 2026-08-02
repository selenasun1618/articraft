from __future__ import annotations

from pathlib import Path

import pytest

from sdk import ArticulatedObject, Box, Origin, ValidationError, Visual
from sdk.v0._urdf_export import compile_object_to_urdf_xml
from sdk_lego.proxy import (
    LegoProxyObject,
    add_lego_proxy_part,
    compile_native_object_to_proxy_urdf_xml,
    compile_proxy_object_to_ldraw_mpd,
)
from sdk_lego.top_parts import resolve_top_lego_part, top_lego_parts


@pytest.fixture(autouse=True)
def _offline_lego_catalog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("REBRICKABLE_API_KEY", raising=False)
    monkeypatch.setenv("ARTICRAFT_LEGO_CACHE_DIR", str(tmp_path / "rebrickable"))


def test_top_parts_seed_exposes_common_proxy_dimensions() -> None:
    assert {part.part_num for part in top_lego_parts()} >= {
        "3001",
        "3003",
        "3004",
        "3005",
        "3020",
        "3022",
        "3023",
        "3024",
        "3062b",
    }

    brick = resolve_top_lego_part("3001")
    plate = resolve_top_lego_part("3020")
    round_brick = resolve_top_lego_part("3062b")

    assert brick.dimensions_m == pytest.approx((0.016, 0.032, 0.0096))
    assert plate.dimensions_m == pytest.approx((0.016, 0.032, 0.0032))
    assert round_brick.geometry == "round"
    assert round_brick.dimensions_m == pytest.approx((0.008, 0.008, 0.0096))


def test_proxy_part_preserves_connectors_and_creates_urdf_visuals() -> None:
    model = LegoProxyObject(name="proxy_stack")
    lower = model.lego_part("lower", part_num="3001", color="red", origin=Origin())
    upper = model.lego_part(
        "upper",
        part_num="3020",
        color="blue",
        origin=Origin(xyz=(0.0, 0.0, 0.0096)),
        parent=lower,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )

    lower_connectors = lower.meta["lego_connectors"]
    upper_connectors = upper.meta["lego_connectors"]
    assert isinstance(lower_connectors, tuple)
    assert isinstance(upper_connectors, tuple)
    assert len(lower_connectors) == 16
    assert len(upper_connectors) == 16
    assert len(lower.visuals) == 9
    assert len(upper.visuals) == 9

    urdf = compile_object_to_urdf_xml(
        model,
        include_physical_collisions=False,
        validate=True,
    )

    assert '<link name="lower">' in urdf
    assert '<link name="upper">' in urdf
    assert "<box" in urdf
    assert "<cylinder" in urdf
    assert '<joint name="lower_to_upper_fixed" type="fixed">' in urdf


def test_proxy_round_brick_uses_cylinder_visual() -> None:
    model = LegoProxyObject(name="round_proxy")
    head = model.lego_part("head", part_num="3062b", color="yellow")

    urdf = compile_object_to_urdf_xml(
        model,
        include_physical_collisions=False,
        validate=True,
    )

    assert len(head.visuals) == 2
    assert '<link name="head">' in urdf
    assert "<cylinder" in urdf
    assert "3062b.dat" == head.meta["lego"].ldraw_id


def test_proxy_metadata_round_trips_to_mpd() -> None:
    model = LegoProxyObject(name="proxy_stack")
    lower = model.lego_part("lower", part_num="3001", color="red", origin=Origin())
    model.lego_part(
        "upper",
        part_num="3020",
        color="blue",
        origin=Origin(xyz=(0.0, 0.0, 0.0096)),
        parent=lower,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )

    export = compile_proxy_object_to_ldraw_mpd(model, target="visual", validate=True)

    assert export.mpd_text.startswith("0 FILE proxy_stack.ldr")
    assert "3001.dat" in export.mpd_text
    assert "3020.dat" in export.mpd_text
    assert [piece["part_num"] for piece in export.sidecar_json["pieces"]] == ["3001", "3020"]
    assert export.sidecar_json["pieces"][0]["connectors"][0]["id"] == "stud_0_0"
    assert export.sidecar_json["connections"] == [
        {
            "parent": "lower",
            "child": "upper",
            "parent_connector": "stud_0_0",
            "child_connector": "antistud_0_0",
            "connection_type": "fixed",
        }
    ]


def test_native_catalog_assembly_renders_through_proxy_urdf() -> None:
    from sdk_lego import ArticulatedObject

    model = ArticulatedObject(name="native_stack")
    lower = model.root_piece("lower", part_num="3001", color="red")
    model.attach(
        "upper",
        part_num="3020",
        color="blue",
        parent=lower,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )

    urdf = compile_native_object_to_proxy_urdf_xml(model)

    assert '<robot name="native_stack_proxy">' in urdf
    assert '<link name="lower">' in urdf
    assert '<link name="upper">' in urdf
    assert '<joint name="lower_to_upper_fixed" type="fixed">' in urdf
    assert urdf.count("<cylinder") == 16


def test_proxy_export_rejects_arbitrary_sdk_geometry() -> None:
    model = ArticulatedObject(name="plain_sdk")
    model.part(
        "box",
        visuals=[
            Visual(
                geometry=Box(size=(0.01, 0.01, 0.01)),
                origin=Origin(),
                name="plain_box",
            )
        ],
    )

    with pytest.raises(ValidationError, match="not a LEGO proxy part"):
        compile_proxy_object_to_ldraw_mpd(model, target="visual")


def test_proxy_export_rejects_extra_visuals_on_proxy_part() -> None:
    model = ArticulatedObject(name="tampered")
    part = add_lego_proxy_part(model, "brick", part_num="3005", color="red")
    part.visual(Box(size=(0.001, 0.001, 0.001)), name="extra")

    with pytest.raises(ValidationError, match="non-proxy visuals"):
        compile_proxy_object_to_ldraw_mpd(model, target="visual")
