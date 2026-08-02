# LEGO External Validation Handoff

The repository can now validate a constrained catalog, connector-driven
placement, MPD serialization, ordered `0 STEP` instructions, proxy URDF output,
and native LDraw-to-OBJ materialization.

The following checks require external software or credentials and are not
claimed as locally verified.

## Regenerate Deterministic Evals

Download and extract the official LDraw `complete.zip` so this path exists:

```text
data/cache/lego/ldraw_official/library/ldraw/parts/3001.dat
```

Then run:

```bash
uv run python scripts/lego_constrained_evals.py
```

Outputs:

```text
data/local/lego_constrained_evals/flamingo/
data/local/lego_constrained_evals/painted_ladies/
data/local/lego_constrained_evals/jwst/
```

Each directory contains:

```text
model.mpd
model.sidecar.json
model.proxy.urdf
assets/lego/model.obj
assets/lego/model.mtl
summary.json
```

## BrickLink Studio Checks

For each `model.mpd`:

1. Import or open the MPD in BrickLink Studio.
2. Confirm every referenced `.dat` part resolves.
3. Confirm colors match the sidecar.
4. Confirm no pieces are unexpectedly floating, mirrored, or rotated.
5. Confirm `0 STEP` boundaries import in a useful order.
6. Save/export from Studio and compare piece counts against
   `model.sidecar.json.inventory`.

The current deterministic models are mechanical smoke tests built from the
16-part `structural_v1` catalog. Painted Ladies and JWST are not expected to be
visually convincing until windows, slopes, dishes, bars, hinges, and other
verified parts are added.

## Instruction Checks

Open each MPD in LPub3D or Studio's instruction maker:

1. Verify each step adds a piece to an already existing parent.
2. Verify callouts and camera angles remain understandable.
3. Verify pieces are not trapped by later geometry.
4. Verify the partial assembly remains stable enough to build.

The compiler currently proves attachment order, but not insertion clearance,
gravity stability, hand/tool access, or instruction-page composition.

## LXF Checks

LXF export is not implemented. Before implementing it, confirm:

1. Which Studio version and import route must be supported.
2. Whether LXF or LXFML is required.
3. The accepted LEGO design-ID and material-ID mappings.
4. How unsupported LDraw-only pieces should fail or fall back.

MPD remains the canonical supported interchange format.

## LLM Generation Evals

Provider credentials are required to run fresh constrained generations for:

```text
flamingo
Painted Ladies in San Francisco
James Webb Space Telescope
```

Acceptance criteria:

1. Every selected part belongs to the active catalog snapshot.
2. The compile report records the catalog ID and SHA-256.
3. All non-root pieces are created with `attach(...)`.
4. Strict compile succeeds.
5. MPD, sidecar, proxy URDF, and native render mesh are produced.
6. Human visual score is recorded after Studio/OBJ inspection.
