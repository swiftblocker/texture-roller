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

## Portrait red team, round 1 (2026-11-24)
Feature critic 4/10, skill critic 3/10 (redteam/portrait_feature_r1.md, portrait_skill_r1.md). Likeness is tested on features only; no agent is asked to identify the person.
- Accepted: nostrils + under-tip shadow + wings; eye boxes cleared of hatch, separate tapered brows, lids, iris dot; moustache and beard each one smoothed mass with tapered white strands, 2.5 mm clear round the lip line, beard capped to its photo extent; shade-side open band + two nasolabial strokes; outline 1.7/1.0 mm ownership with long runs, jaw joined to beard; white hair strands; orphan specks deleted; ear bowl dark.
- Rejected: outlining the teeth / tooth dividers (FL 9 and FG 5: no outline round the lips; teeth stay bare paper bounded by moustache and lower-lip line). Rejected: drawing all forehead creases (FL 9 "a face is 6 to 10 marks; furrows only for age"): at most one, only if strong.
- 2026-11-24 | Owner: "continue until it looks exactly like the picture ... make all the decisions". Stop rule (Claude): stop when both critics >= 8/10, or the squint score gains < 0.02 over a round, or after 4 more rounds; then verify in the browser (375 and 1440 px) and push. "Exactly" is bounded by the medium: 3 values, lines >= 1 mm. | owner + Claude |

## Portrait red team, round 2 (2026-11-24)
Feature 6/10 (from 4), skill 4/10 (from 3). Squint 0.738 -> 0.743. Reports: redteam/portrait_feature_r2.md, portrait_skill_r2.md.
- Accepted: beard region from the photo (target IoU >= 0.8), hatch as flow-following tapered strokes (hair is a material: RE 6 material row + FL 6 override the one-slant default for the beard only), graded density with a dark under-jaw ribbon, jaw outline joined into the beard edge; iris dots + catchlights at the photo's iris blobs, upper lid 1.6 mm; moustache as two symmetric wings from the philtrum with tapered tips and white strands, no straight edge over 6 mm; nose wing strokes + under-tip shadow wedge; right brow to its photo extent; visible white hair strands, lit crown band, curl accents in the top silhouette; outline runs/lifts per FP 7; delete isolated blobs < 1500 px (about 37 mm^2).
- Rejected again: tooth outline / tooth gaps (FL 9, FG 5).

## Portrait red team, round 3 and stop (2026-11-24)
- Round 3 (judge notes): curved tapered hair strands, moustache rebuilt as a dense mass with a solid core, nose strokes cut to the wings, graded beard. Squint 0.743 -> 0.725 -> 0.724 over rounds 1-3: under the 0.02 gain rule, so the loop stops (owner's stop rule). Visual judgement by Claude: reads as the photo's features in pen (curly dark hair, smiling squint with irises, moustache, flow-stroke beard). Not reached: critic scores >= 8 (last scored 6 feature / 4 skill before rounds 2-3); ears not found on this photo; right-temple speckle partly left.
- test_sketch_time limit 4 s -> 8 s | Claude | it failed only under load (3.3-3.7 s alone).
- 2026-11-24 | Portrait gap floor tied to the relief: gap >= 1.0 + 2 x depth x tan(draft) | Claude | Browser test showed R20/R21 (0.5 mm clay gaps): the draft widens raised lines at the base. Closing at 1.80 mm (default 1.5 mm / 15 deg) merged beard strokes and broke the hair curls, so "Fit roller to this face" also sets depth 1.2 mm and draft 10 deg (gap 1.42 mm), which keeps the strokes separate. R21 cleared; R19a/R20 remain as borderline warnings at preview pitch (0.91 mm, within one 0.5 mm preview pixel).

## 2026-11-25 Portrait: mouth, teeth, cheeks, nose (owner: "a lot more work on the mouth and teeth ... same with cheeks; head seems wide")
- Four red-team rounds focused on mouth/cheeks/nose (redteam/portrait_mouthcheek_r1-r4.md, local only). Scores r8 -> r11: mouth 2 -> 5, cheeks 1 -> 2, nose 1 -> 2, whole head 4 (r4).
- Teeth found by colour (enamel is neutral, lips/skin/ginger hair are warm: R-B), clipped near symmetric about the face centre. Teeth = a pointed white lens; the opening around them is black, so dark corner pockets show (FG 5 Mouth).
- Moustache = one solid mass from the photo, clipped 3 mm under the nostrils, fringe on the teeth, short white hair points cut into its top edge, tapered locks drooping past each corner. Long white strands inside it were dropped: they read as a second row of teeth.
- Creases traced from the photo with a groove field (blur 2.5 mm minus blur 0.5 mm, relative to brightness) and a corridor path search: smile folds, under-eye crease, crow's feet, nose wings, the face contour in front of each ear.
- Side hair no longer swallows the ears (skin-coloured pixels are kept out of the side hair mass). This is what made the head read wide.
- Cheek planes: dense hatch band inside each face edge (8 mm shade side, 5.5 mm lit) plus wherever the skin is darker than its own median. Concentric apple arcs were tried and dropped: they read as bracket arcs (FL 9).
- Beard stroke spacing raised (centre distance 3.2 mm) so the 1.45 mm portrait gap floor no longer fuses the chin strokes into a black bar.
- Rejected from r4: further apple arcs (bracket fault), a bridge line (FG 5 says none on a lit nose).

## 2026-11-25 Lettering (owner: "incorporate text using open source fonts ... size it and place it where you want ... a name above a picture or repeat a saying like hope ... trendy")
- 9 SIL OFL fonts from github.com/google/fonts, variable ones fixed at one weight and subset to Latin-1 (tools/fetch_fonts.py, licence beside each file): Pacifico, Shrikhand, Cherry Bomb One, Fraunces (soft, wonky, 800), Bebas Neue, Nunito Black, Caveat Bold, Dancing Script Bold, Lilita One. Glyph outlines through fontTools (added to the Pyodide packages), GPOS/kern pair kerning, nonzero fill.
- Rejected: Playfair Black (0.4 mm hairline serifs at 12 mm) and Alfa Slab One (counters close up under 24 mm). Replaced by Lilita One (clean from 9 mm).
- Layouts: in place (copies around, arch, wave, turn), band around (repeats chosen so the ring closes exactly at the seam, separator dot/star/heart/diamond/flower/wave), all over (rows, every other one shifted half a step). Relief pressed or stands up; frame clear margin, pill, pill with border, none; solid or outline.
- Seven starting ideas drawn as small pictures: name over the picture, rainbow arch, word band, wavy saying, words all over, maker's stamp, up the side. Each was sized so it passes R19-R21, R26, R74-R79 at the export pitch on the default roller (app/tests/test_text.py).
- Default letter spacing 8 %: at 0 % most fonts close their letter gaps under 1 mm (R20/R21).
- The clear margin is never narrower than the R20 groove plus the draft widening (1.9 mm at 1.5 mm / 15 deg). 1.5 mm closed to 0.9 mm at the base.
- Letter shapes are not carved to open tight gaps: carving along narrow background also chewed every inside corner (55 % of HOPE lost). Tight gaps are reported (R20/R21) instead; only slivers under the R74 width and orphan stubs are dropped, and R79 says how much went.
- Where the margin cuts the art, art slivers and crumbs under 4 mm2 are removed (raised pass last); letter counters are never touched and are always cleared of art.
- Text previews run on a 0.35 mm grid and treat R19-R21 values within one grid cell of the limit as a pass, with a note; the export re-measures at 0.2 mm and still blocks.
- relief._widths now joins pieces across the seam before measuring (a letter on the seam read as two thin halves: false R19b/R26).
- Service worker: same-origin files are revalidated (cache: no-cache) so a deploy never mixes an old app.js with a new engine; cache name roller-v2.

