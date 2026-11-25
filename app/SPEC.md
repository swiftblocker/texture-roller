# App spec (contract between engine, server and UI)

Read first: `../CLAUDE.md`, `../brief.md`, `../decisions.md` (Stack section), `../skill/pottery-roller/SKILL.md`, `../skill/pottery-roller/references/checks.json`.

Layout:
```
app/
  engine/            Python package `engine` (engine agent owns it)
    params.py        dataclass Params + defaults + presets + validation of types
    art.py           SVG load, Bezier cleanup, PNG trace, procedural patterns -> binary mask (clay-view)
    layout.py        tiling: n_around, n_along, offset, rotation, mirror, invert, spacing, seam placement
    relief.py        mask -> height field (depth, draft, edge round, bands); feature-width metrics
    mesh.py          height field -> watertight trimesh; split halves; test strip
    body.py          build123d blank body (cylinder, bore, chamfers, split key) -> STEP; reference dims
    rules.py         loads checks.json, evaluates every rule, returns RuleResult list
    derived.py       C, repeat width, revs, fired sizes, grams, print minutes, repeat solver
    export.py        writes the output folder
    api.py           the functions the server calls (below)
  tests/             pytest (engine agent owns it)
  server.py          FastAPI app (UI agent owns it)
  web/               index.html, app.css, app.js, vendor/three.module.js (UI agent owns it)
  run.ps1            starts the server on 127.0.0.1:8790
```

## Coordinates and sign conventions (both sides MUST follow)

- The roller axis is Z. z = 0 at the bottom end, z = L at the top end.
- theta goes from 0 to 2pi, counter-clockwise seen from +Z. The seam is at theta = 0.
- The height field H[row, col]: row = z index (row 0 at z = 0), col = theta index (col 0 at theta = 0). Value = the relief height above the bottom level in mm, 0 <= H <= d. Surface radius r = R_top - d + H, where R_top = D/2.
- **Clay image** K[y, x]: what the potter sees on the slab looking down. x = travel direction (mm, 0 to C per revolution), y = axis direction (mm, equals z). It is the "art as drawn" when mirror = ON.
- Rolling: the roller contact point moves theta = 0 -> 2pi while the roller travels +x. The clay at x receives the roller column at theta = 2pi * x / C, and clay depth there = H (raised roller parts sink deepest).
- Clay image rows are in PICTURE order: row 0 = top of the art = z = L end of the roller; last row = z = 0. The UI draws row 0 at the top. (H rows stay z-ascending.)
- `bore_diameter_used` = the final printed bore (rod/dowel + clearance).
- derived also carries `image_height_mm` (wet, axial extent of the art) and `fired.image_height_mm`. test_strip returns the same shape as export. **Mirror rule:** with mirror ON, H's column order is the clay image's x order REVERSED (col j <-> x = C - j*pitch). The round-trip test (R72) proves this: unroll the mesh radius, apply the same mapping, compare to K.
- Positive mode (invert = false): filled art = raised on the roller (H = d) = recessed in clay. Negative mode: filled art = recessed on the roller (H = 0) = raised in clay. The UI labels the modes by the clay result: "Art pressed in" / "Art stands up".

## Params (all mm / deg; JSON keys exactly these)

```
diameter 45.0, length 250.0,
art_source "pattern:waves" | "upload",   # pattern ids: waves, chevron, leaf
tile_width_mm null (null = C / n_around), n_around 3 (int), n_along null (null = derived from the tile aspect),
offset "none" | "half_drop" | "brick", offset_fraction 0.5,
rotation 0 (0/90/180/270), mirror true, invert false, spacing 0.0,
depth 1.5, draft_deg 15.0, edge_round 0.4,
seam_method "auto" | "tile" | "background" | "blend" | "gutter", seam_blend_pct 5.0, seam_theta_deg null (null = auto),
band 3.0, bands_on true, end_chamfer 1.0, alignment_ticks false,
bore_preset "dowel_half" | "none" | "rod_8" | "dowel_3q" | "custom", bore_diameter null (custom or measured), bore_clearance 0.3,
split false, clay_body "stoneware" | "porcelain" | "earthenware" | "paper", clay_state "soft" | "firm" | "leather",
glaze_flag false, nozzle 0.4, pitch_preview 0.5, pitch_export 0.2,
cnc_rotary_max_length 0
```
Bore diameters: dowel_half 12.70, dowel_3q 19.05, rod_8 8.00, plus bore_clearance. `bore_diameter`, when set, is the measured rod/dowel.

## Engine API (engine/api.py)

```python
def preview(params: dict, upload: bytes | None, upload_name: str | None) -> dict
def export(params: dict, upload: bytes | None, upload_name: str | None, out_dir: str) -> dict  # {"files": [...], "rules": [...], "blocked": bool}
def test_strip(params: dict, out_dir: str) -> dict        # 40 mm long, same D and bore, 5 depth bands 0.8/1.2/1.6/2.0/2.5
def solve_repeat(tile_width: float, d_min=25, d_max=100, max_n=12) -> list[dict]  # [{"diameter","n_around","C","stretch_pct"}], best 6
def patterns() -> list[dict]    # [{"id","name"}]
```

`preview` returns JSON-serialisable:
```
{
 "params": {...resolved, incl. bore_diameter_used, seam_theta_deg_used},
 "derived": {"C": mm, "repeat_width": mm, "tile_height": mm, "n_along": float,
             "revs_per_254": float, "LD": float, "wall_min": mm,
             "fired": {"shrink_pct": float, "image_height_mm": float, "repeat_width_mm": float},
             "grams": float, "print_minutes": float, "triangles_export": int},
 "rules": [{"id":"R08","action":"BLOCK"|"WARN"|"INFO","msg":str,"value":float|null,"limit":float|null}],
 "can_export": bool,
 "heightmap": {"cols": int, "rows": int, "pitch_theta_mm": float, "pitch_z_mm": float,
               "depth": float, "data_b64": base64 of float32 little-endian row-major H (preview pitch)},
 "clay": {"cols": int, "rows": int, "data_b64": base64 uint8 row-major clay depth image, 0 = untouched surface, 255 = full depth, x = travel, y = axis, ONE revolution},
 "art_report": {"paths": int, "segments_in": int, "segments_out": int, "dropped_thin": int, "traced": bool}
}
```
Preview must return in under 1.5 s for the default part at pitch_preview 0.5.

## Server (server.py)

- `GET /` serves web/index.html; static under /web.
- `POST /api/preview` multipart: field `params` (JSON string), optional file `art`. Returns preview JSON.
- `POST /api/export` same input. Returns JSON {files, rules, blocked}; the files are written to `app/out/<timestamp>/`. `GET /api/download/<timestamp>` streams a zip.
- `POST /api/test_strip` params JSON -> same as export.
- `GET /api/solve_repeat?tile_width=..` and `GET /api/patterns`.
- Bind 127.0.0.1:8790 only.

## Export folder contents
`roller.stl`, `roller.3mf` (or `roller_a.*`, `roller_b.*` when split), `body.step`, `heightmap_16bit.png` (the unrolled clay-side relief for CNC, 1 px = pitch_export, white = deepest clay cut), `slab_preview.png`, `roller.json` (sidecar, R73), `sheet.md` (print settings, release and clay instructions, rule results).
