# LEGO SDK Quickstart

This SDK profile generates catalog-native LEGO assemblies and exports them as
LDraw MPD text plus Articraft sidecar metadata. Import from `sdk_lego`.

## Script Contract

Every generated script should define:

```python
def build_object_model() -> ArticulatedObject: ...
def run_tests() -> TestReport: ...
object_model = build_object_model()
```

`compile_model` compiles `object_model` to an LDraw MPD payload, validates LEGO
piece and connector rules, and treats Articraft articulations as fixed in the
LDraw output while preserving articulation metadata in the sidecar block.

## Minimal Example

```python
from sdk_lego import ArticulatedObject, Origin, TestContext, TestReport


def build_object_model() -> ArticulatedObject:
    model = ArticulatedObject(name="stacked_bricks")
    lower = model.root_piece("lower", part_num="3001", color="red")
    model.attach(
        "upper",
        part_num="3020",
        color="blue",
        parent=lower,
        parent_connector="stud_0_0",
        child_connector="antistud_0_0",
    )
    return model


def run_tests() -> TestReport:
    ctx = TestContext(object_model)
    return ctx.report()


object_model = build_object_model()
```

## Units

- `Origin.xyz` is authored in meters with Articraft's normal `+Z` up convention.
- The LDraw exporter converts to LDraw Units, where `1 LDU = 0.4 mm`.
- LDraw uses `-Y` as up.

## Authoring Rules

- Each `Part` is exactly one LEGO catalog piece.
- Start with exactly one `model.root_piece(...)`.
- Add all other pieces with `model.attach(...)`; it computes placement from the
  selected connector frames.
- Search only the active approved catalog. Do not invent part numbers, override
  LDraw IDs, or call Rebrickable directly during generation.
- `model.part(...)` and `model.lego_connection(...)` remain low-level diagnostic
  surfaces; do not use them for normal generated assemblies.
- Basic bricks and plates derive stud and antistud connector locations from the
  versioned approved catalog.
- `buildable` validation checks connector compatibility, duplicate connector
  use, and connectedness.
- `strict` validation additionally requires connected connector endpoints to
  coincide and connector axes to oppose.
