from __future__ import annotations

import math

import pytest

from sdk import Origin, ValidationError
from sdk_lego import ArticulatedObject
from sdk_lego.ldraw_export import compile_object_to_ldraw_mpd
from sdk_lego.model import lego_piece_spec


def test_attach_computes_vertical_stud_antistud_transform() -> None:
    model = ArticulatedObject(name="stack")
    lower = model.root_piece("lower", part_num="3001", color="red")

    upper = model.attach(
        "upper",
        part_num="3020",
        color="blue",
        parent=lower,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )

    assert lego_piece_spec(upper).origin.xyz == pytest.approx((0.0, 0.0, 0.0096))
    export = compile_object_to_ldraw_mpd(model, target="strict")
    assert export.sidecar_json["connections"][0]["parent_connector"] == "stud_0_0"


def test_attach_computes_offset_from_selected_connectors() -> None:
    model = ArticulatedObject(name="offset")
    lower = model.root_piece("lower", part_num="3001", color="red")

    upper = model.attach(
        "upper",
        part_num="3005",
        color="blue",
        parent=lower,
        parent_connector="stud_1_3",
        child_connector="antistud_0_0",
    )

    assert lego_piece_spec(upper).origin.xyz == pytest.approx((0.004, 0.012, 0.0096))
    compile_object_to_ldraw_mpd(model, target="strict")


def test_attach_supports_quarter_turn_clocking() -> None:
    model = ArticulatedObject(name="clocked")
    lower = model.root_piece("lower", part_num="3001", color="red")

    upper = model.attach(
        "upper",
        part_num="3004",
        color="blue",
        parent=lower,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
        quarter_turns=1,
    )

    assert lego_piece_spec(upper).origin.rpy == pytest.approx((0.0, 0.0, math.pi / 2.0))
    compile_object_to_ldraw_mpd(model, target="strict")


def test_attach_respects_rotated_parent_frame() -> None:
    model = ArticulatedObject(name="rotated_parent")
    lower = model.root_piece(
        "lower",
        part_num="3001",
        color="red",
        origin=Origin(rpy=(0.0, 0.0, math.pi / 2.0)),
    )

    model.attach(
        "upper",
        part_num="3005",
        color="blue",
        parent=lower,
        parent_connector="stud_1_3",
        child_connector="antistud_0_0",
    )

    compile_object_to_ldraw_mpd(model, target="strict")


def test_attach_rejects_incompatible_connector_pair() -> None:
    model = ArticulatedObject(name="bad_pair")
    lower = model.root_piece("lower", part_num="3001", color="red")

    with pytest.raises(ValidationError, match="Incompatible LEGO connectors"):
        model.attach(
            "upper",
            part_num="3020",
            color="blue",
            parent=lower,
            parent_connector="stud_0_0",
            child_connector="stud_0_0",
        )


def test_compile_rejects_duplicate_connector_occupancy() -> None:
    model = ArticulatedObject(name="duplicate_occupancy")
    lower = model.root_piece("lower", part_num="3001", color="red")
    model.attach(
        "upper_a",
        part_num="3005",
        color="blue",
        parent=lower,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )
    model.attach(
        "upper_b",
        part_num="3005",
        color="green",
        parent=lower,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )

    with pytest.raises(ValidationError, match="used by multiple connections"):
        compile_object_to_ldraw_mpd(model, target="buildable")


def test_strict_compile_rejects_coincident_but_same_direction_axes() -> None:
    model = ArticulatedObject(name="bad_axis")
    lower = model.root_piece("lower", part_num="3005", color="red")
    upper = model.part(
        "upper",
        part_num="3005",
        color="blue",
        origin=Origin(xyz=(0.0, 0.0, 0.0096), rpy=(math.pi, 0.0, 0.0)),
    )
    model.lego_connection(
        lower,
        upper,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )

    with pytest.raises(ValidationError, match="axes must oppose"):
        compile_object_to_ldraw_mpd(model, target="strict")


def test_buildable_compile_rejects_multiple_attachment_parents() -> None:
    model = ArticulatedObject(name="multiple_parents")
    root = model.root_piece("root", part_num="3001", color="red")
    brace = model.attach(
        "brace",
        part_num="3005",
        color="blue",
        parent=root,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )
    child = model.attach(
        "child",
        part_num="3003",
        color="green",
        parent=root,
        parent_connector="stud_1_0",
        child_connector="antistud_0_0",
    )
    model.lego_connection(
        brace,
        child,
        parent_connector="stud_0_0",
        child_connector="antistud_1_1",
    )

    with pytest.raises(ValidationError, match="multiple attachment parents"):
        compile_object_to_ldraw_mpd(model, target="buildable")


def test_buildable_compile_rejects_parent_after_child_in_step_order() -> None:
    model = ArticulatedObject(name="forward_reference")
    root = model.root_piece("root", part_num="3001", color="red")
    child = model.part("child", part_num="3005", color="blue")
    parent = model.part("parent", part_num="3005", color="green")
    model.lego_connection(
        root,
        parent,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )
    model.lego_connection(
        parent,
        child,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )

    with pytest.raises(ValidationError, match="requires parent"):
        compile_object_to_ldraw_mpd(model, target="buildable")
