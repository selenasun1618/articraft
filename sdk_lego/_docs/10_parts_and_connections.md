# LEGO Parts and Connections

## Parts

In `sdk_lego`, an Articraft `Part` is one physical LEGO piece selected from the
active immutable catalog snapshot:

```python
piece = model.root_piece(
    "red_2x4_brick",
    part_num="3001",
    color="red",
)
```

Generation never resolves arbitrary Rebrickable results. The default
`structural_v1` catalog is versioned, fingerprinted, and revalidated during
compile. Rebrickable access is reserved for offline catalog-ingestion tooling.

## Connectors

For common rectangular bricks and plates, connector IDs are derived from the
catalog name:

```text
stud_<x>_<y>
antistud_<x>_<y>
```

Examples:

- `3001` / `Brick 2 x 4` has `stud_0_0` through `stud_1_3`.
- It also has `antistud_0_0` through `antistud_1_3`.

## Connections

Attach every non-root piece through explicit connector pairs:

```python
upper = model.attach(
    "upper",
    part_num="3020",
    color="blue",
    parent=lower,
    parent_connector="stud_0_0",
    child_connector="antistud_0_0",
    quarter_turns=0,
)
```

`attach(...)` computes the child transform from the parent connector frame,
child connector frame, and optional 90-degree clocking. Do not hand-author XYZ
placements for normal generated assemblies.

Supported compatibility in the initial LEGO compiler:

- `stud` to `antistud`
- `bar` to `clip`
- `ball` to `socket`
- `towball` to `towball_socket`
- `rail` to `groove`

Only stud/antistud connectors are derived automatically in this first profile.
Other articulation families need explicit connector metadata in the part index
before strict validation can reason about them.

## Articulations

LDraw is a static model format. Authoring can include Articraft articulations for
semantic sidecar metadata, but the MPD output treats them as fixed placements.
Use sidecar consumers for dynamic behavior.

## URDF Proxy Authoring

The native `sdk_lego.ArticulatedObject` path exports catalog pieces directly to
LDraw MPD and does not create URDF visuals. For quick viewer iteration, use the
separate proxy surface in `sdk_lego.proxy`: it creates ordinary SDK primitive
visuals while preserving LEGO part metadata for later MPD export.

```python
from sdk import Origin, TestContext, TestReport
from sdk_lego.proxy import LegoProxyObject, compile_proxy_object_to_ldraw_mpd


def build_object_model() -> LegoProxyObject:
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
    return model


def run_tests() -> TestReport:
    return TestContext(object_model).report()


object_model = build_object_model()
mpd_export = compile_proxy_object_to_ldraw_mpd(object_model, target="visual")
```

The current proxy seed supports common rectangular bricks and plates such as
`3001`, `3003`, `3004`, `3005`, `3020`, `3022`, `3023`, `3024`, plus a simple
round `3062b` proxy. The index is intentionally small but exposed through
`top_lego_parts()`, `resolve_top_lego_part(...)`, and `find_top_lego_parts(...)`
so it can grow toward a larger top-parts list.

Proxy MPD conversion is strict: every part must be authored through
`LegoProxyObject.lego_part(...)` or `add_lego_proxy_part(...)`. Arbitrary SDK
geometry is rejected instead of being silently dropped from the LDraw export.
