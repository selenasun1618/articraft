# LEGO LDraw materialization

Articraft LEGO records keep `model.mpd` as the canonical compile artifact. During LEGO
compile, the LDraw materializer also attempts to emit:

- `assets/lego/model.obj`
- `assets/lego/model.mtl`

The OBJ uses Articraft's Z-up meter frame and can be served by the viewer API through the
normal record file endpoint. A viewer-side LDraw/LEGO mesh hook can consume the sidecar's
`render_mesh.path` value, load that OBJ with the existing Three.js OBJ loader, and use the
MPD sidecar piece metadata for selection/labels.

Limitations in the current slice:

- Only MPD `0 FILE`, type 1 subfile refs, type 3 triangles, and type 4 quads are rendered.
- Type 2 lines, type 5 optional lines, BFC winding metadata, official LDConfig color parsing,
  and primitive substitutions are not implemented yet.
- Missing local `.dat` files are explicit resolver errors in the standalone materializer and
  non-blocking compile warnings in the normal LEGO compile path.
