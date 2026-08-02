from __future__ import annotations

from dataclasses import replace

import pytest

from sdk import ValidationError
from sdk_lego import (
    ArticulatedObject,
    LegoPieceSpec,
    Origin,
    find_lego_parts,
    get_active_catalog_snapshot,
    resolve_lego_part,
)
from sdk_lego.ldraw_export import compile_object_to_ldraw_mpd


def test_structural_v1_catalog_is_versioned_and_fingerprinted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARTICRAFT_LEGO_CATALOG_ID", "structural_v1")

    snapshot = get_active_catalog_snapshot()

    assert snapshot.catalog_id == "structural_v1"
    assert len(snapshot.sha256) == 64
    assert len(snapshot.parts) == 16
    assert snapshot.resolve_part("3001").ldraw_id == "3001.dat"


def test_public_part_resolution_rejects_unapproved_rebrickable_part(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARTICRAFT_LEGO_CATALOG_ID", "structural_v1")

    with pytest.raises(ValidationError, match="not approved"):
        resolve_lego_part("2780")


def test_find_lego_parts_searches_only_approved_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARTICRAFT_LEGO_CATALOG_ID", "structural_v1")

    results = find_lego_parts("brick 2 x 4")
    approved = {part.part_num for part in get_active_catalog_snapshot().parts}
    assert results[0].part_num == "3001"
    assert {part.part_num for part in results} <= approved
    assert find_lego_parts("technic pin") == []


def test_model_rejects_unapproved_part_color_and_ldraw_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARTICRAFT_LEGO_CATALOG_ID", "structural_v1")
    model = ArticulatedObject(name="catalog_checks")

    with pytest.raises(ValidationError, match="not approved"):
        model.part("pin", part_num="2780", color="black")
    with pytest.raises(ValidationError, match="color"):
        model.part("brick_bad_color", part_num="3001", color=999)
    with pytest.raises(ValidationError, match="approved LDraw id"):
        model.part("brick_bad_id", part_num="3001", color="red", ldraw_id="3001a.dat")


def test_compile_revalidates_tampered_piece_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARTICRAFT_LEGO_CATALOG_ID", "structural_v1")
    model = ArticulatedObject(name="tampered")
    part = model.part("brick", part_num="3001", color="red", origin=Origin())
    spec = part.meta["lego"]
    assert isinstance(spec, LegoPieceSpec)
    part.meta["lego"] = replace(spec, ldraw_id="3001a.dat")

    with pytest.raises(ValidationError, match="requires '3001.dat'"):
        compile_object_to_ldraw_mpd(model, target="visual")


def test_export_records_catalog_provenance_and_used_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARTICRAFT_LEGO_CATALOG_ID", "structural_v1")
    model = ArticulatedObject(name="provenance")
    model.part("brick", part_num="3001", color="red", origin=Origin())

    export = compile_object_to_ldraw_mpd(model, target="visual")
    snapshot = get_active_catalog_snapshot()

    assert export.sidecar_json["catalog"] == {
        "catalog_id": "structural_v1",
        "catalog_sha256": snapshot.sha256,
    }
    assert export.sidecar_json["used_part_nums"] == ["3001"]
    assert f"0 !ARTICRAFT_CATALOG structural_v1 {snapshot.sha256}" in export.mpd_text
