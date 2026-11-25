# Decisions

Format: date | decision | who | why

- 2026-11-24 | Project lives in `Scripts/pottery-roller/` | Claude | Code project, same home as other generators; finished exports will be copied to Google Drive.
- 2026-11-24 | Twitter/X skipped as a research channel | Claude | Agent Reach Twitter backend is not installed; Reddit, YouTube, forums and maker sites cover the questions.
- 2026-11-24 | Max length 10 in (254 mm); must roll a full 10 in tall image | owner | Brief.
- 2026-11-24 | No FEA | owner | Brief.
- 2026-11-24 | Reddit cluster (S001-S019) blocked | Claude | reddit.com returns 403/login on direct, Jina and WebSearch; Chrome-based read was denied by the permission check. Pending the owner's call at checkpoint 1.

## Checkpoint 1 answers (owner: "you make all the decisions"), 2026-11-24
- Output: STL + 3MF (X1C) for the textured roller; STEP for the blank body only (bore, chamfers, split key). | Claude | A B-rep with a 1M-face displaced surface is not practical in STEP; the mesh is the print artifact.
- CNC: no rotary axis is known on the Laguna, so v1 exports a 16-bit PNG heightmap of the unrolled relief (for a flat texture board in VCarve/Aspire) instead of rotary toolpaths. R62 stays configurable (rotary length 0 = disabled). | Claude | No rotary axis known.
- Handles: default is a through bore for a 1/2 in (12.7 mm nominal) hardwood dowel, slip fit +0.3 mm. Options: no bore, 8 mm rod, 3/4 in dowel, custom. Integrated handles are deferred. | Claude | Simplest and cheapest, no extra prints; the dowel is the handle. The dowel's real diameter is UNVERIFIED (store dowels run undersize); the bore is a parameter and the test strip checks fit.
- Two-piece split: for L > 160 mm offer two halves on the shared dowel with a keyed joint so the art lines up. | Claude | Stiffness and X1C height margin.
- Image orientation: the art's height runs along the roller axis; the circumference sets the repeat. Sizes are WET; the slab preview toggles to fired size by clay body. | Claude | A 254 mm fired image would need a 290 mm roller (over R01).
- Mirror default ON; positive/negative labelled by what the clay shows; smallest preset D 25 mm, block under 16 mm. | Claude | SKILL R04, R35, R36.
- Reddit: not retried. | Claude | Permission check blocked Chrome access; the other sources cover the questions.
- Features in v1: depth test strip; fired-size toggle; glaze-pool shading on the slab preview; auto seam placement; repeat-count solver; alignment ticks; slab preview with random start phase; sidecar JSON + Markdown sheet; two-piece split; weight and print-time estimate; three procedural starter patterns. Deferred: text tool, matched positive/negative pair, integrated handles, border-roller preset (short L already works).

## Stack, 2026-11-24
- Engine in Python (numpy/scipy/scikit-image). Relief is a heightmap on a (theta, z) grid; the mesh is generated as a structured grid (outer textured surface + bore surface + end annuli + chamfers) so it is watertight and radially monotone by construction (R23, R65, R69). trimesh + manifold3d validate it. | Claude | Displacing a B-rep in build123d at print resolution is too slow and fragile; a structured grid makes the hard guarantees structural instead of hoped-for.
- build123d (functional-cad) builds the blank body: cylinder, bore, end chamfers, split key. That body's dims are the reference the mesh is checked against (R68), and it exports the STEP. Gates: validate, analyze_printability on the blank and dfam_tool on the final STL.
- SVG: svgelements for parsing; Bezier cleanup = drop zero-length segments, merge points under 0.05 mm, flatten to polylines at 0.02 mm tolerance; rasterize with even-odd fill. PNG: threshold then potrace (potracer, pure Python) to Bezier paths, then the same SVG route. | Claude | Pure Python, no Cairo/Inkscape install on Windows.
- Draft and rounds: Euclidean distance transform of the art mask turns depth + draft angle + edge round into a height profile. Feature widths are measured from the skeleton of the mask (R19-R21). | Claude | Draft becomes a real measured slope, not a guess.
- Server: FastAPI + uvicorn, local only. UI: one static page, three.js (vendored) for the 3D view, canvas 2D for the slab preview. | Claude | Local tool, no build step, works offline.

## Distribution, 2026-11-24
- Hosted on GitHub Pages as a static site; the Python engine runs in the browser via Pyodide in a Web Worker; downloads are Blob URLs. | owner asked for "an easy way ... people can download it and use it cleanly without claude"; Claude chose Pages+Pyodide | No install, no server, works on any OS; same engine code as the tests. Same pattern as the stave app.
- Pyodide loads from the jsDelivr CDN (pinned version), then a service worker caches everything for offline use. | Claude | Vendoring 31 MB of runtime into the repo is heavier than it is worth; first visit needs internet, later visits do not.
- STEP export only in the desktop install (build123d does not run in Pyodide). Browser exports STL, 3MF, heightmap PNG, slab preview, sidecar. | Claude |
- FastAPI server stays for local dev and tests (`backend=http`). | Claude |
- SPEC fix: clay depth = H (not d - H); clay image rows in picture order. | Claude, found by the UI agent |
- 2026-11-24 | Repo: public `swiftblocker/texture-roller`, Pages from `main:/docs` (built by a local script), no GitHub Actions | owner named the swiftblocker account; Claude picked the name and Pages mode | gh token lacks the `workflow` scope; serving /docs needs none.
