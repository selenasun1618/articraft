# LEGO Parts and Connections

## Parts

In `sdk_lego`, an Articraft `Part` is one physical LEGO piece:

```python
piece = model.part(
    "red_2x4_brick",
    part_num="3001",
    color="red",
    origin=Origin(xyz=(0.0, 0.0, 0.0)),
)
```

The compiler resolves `part_num` through the local LEGO cache, then Rebrickable
when `REBRICKABLE_API_KEY` is configured. The exporter references the resolved
LDraw `.dat` filename.

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

Use explicit connector pairs:

```python
model.lego_connection(
    parent=lower,
    child=upper,
    parent_connector="stud_0_0",
    child_connector="antistud_0_0",
)
```

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
