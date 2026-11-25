# Portrait sketch stage (photo of a person -> pen sketch -> trace -> roller)

Goal: a phone photo of a person becomes a one-colour pen drawing of their face, drawn by the
marker-line-art method, at the roller's real size. That drawing is then traced exactly like an
uploaded drawing (potrace -> Bezier -> mask) and wrapped onto the roller.

Method source: `~/.claude/skills/marker-line-art/` (read SKILL.md, references/from-a-photograph.md,
line-and-outline.md, tone-and-black.md, tools-and-vector.md, flowing-line.md sections 6-9 and 13-15,
figure.md sections 4, 5, 12, 13, 16, realism.md sections 5-8 and 15). Rule tags below (FP = from-a-photograph section,
TB = tone-and-black, LO = line-and-outline, FL = flowing-line, FG = figure, RE = realism) say where each step comes from.
Everything numeric that the skill gives in pixels at 1200 px is restated here in millimetres at OUTPUT size,
because a roller has a hard floor the skill does not: every printed line >= 1.0 mm wide and every gap >= 1.0 mm
(SKILL.md R19, R21) or the clay will not hold it.

## 0. Where it runs
- New module `app/engine/sketch.py`. Pyodide-safe: numpy, scipy.ndimage, scikit-image, Pillow only.
- Face detection: `skimage.feature.Cascade(skimage.data.lbp_frontal_face_cascade_filename())`,
  `detect_multi_scale` on a copy downscaled to ~360 px on the long side. If the cascade file or detection is
  missing (Pyodide build may lack it), fall back to: face box = centred, width 45% of image, top at 18%.
  Report which path was used.
- Param `art_style`: "trace" (today's behaviour) | "portrait". Default "trace". Params `sketch_detail` 0..1 (default 0.5,
  moves the edge-rank thresholds by +-0.15) and `sketch_shading` bool (default true).
- In `art.load`, portrait mode needs the output size: pass the resolved tile width in mm
  (tile_width_mm or C/n_around) into the sketch. Cache key = sha1(upload) + tile width rounded to 0.5 mm + detail + shading.

## 1. Prepare (FP 2)
1. EXIF-transpose (`ImageOps.exif_transpose`), RGB, Lab via skimage. L in 0..1.
2. Detect the face (largest box). Head box = face box widened to 1.45x and heightened to 1.9x, shifted up so
   the crown and hair are in (top = face top - 0.55 face h), and down to the chin + 0.25 face h for the neck.
   Clip to the image. This crop is the drawing; its aspect sets the tile height.
3. Output raster: width = tile width W mm at 8 px/mm (cap the long side at 2000 px; if capped, lower px/mm and
   keep every size below in mm). All sizes below are in mm at output.
4. Subject mask without an ML model: head ellipse (inscribed in the head box, 0.96 of it) union a soft
   shoulder trapezoid below the chin; then remove background inside it: model the background from the outer
   6% border ring of the crop (Lab median + MAD); pixels within 2.2 MAD-scaled distance of it AND connected to the
   border are background. Close 2 mm, keep the largest component, fill holes under 25 mm^2.
   Outside the mask the drawing fades: no marks (FP 11 "never let the blur show"; TB vignette).
5. Light direction (FP 2.5, FG 12): compare mean L of the left and right halves of the face box. Light comes from
   the brighter side, 45 deg above. Hatch slant runs along the light: 45 deg rising toward the light side
   (TB "shadow strokes slant with the light").
6. Centre of interest (FP 2.6): the eye-nose-mouth box = face box shrunk to its middle 70% width, rows 28%..85%.
   Eye boxes: two boxes at face rows 30%..50%, columns 15%..45% and 55%..85%.

## 2. Values: three steps on one grid (FP 3, TB value scheme, FG 12)
1. Blur L inside the mask only (normalized convolution), sigma = 2.0 mm -> big masses.
2. Percentile cuts of the subject's own values (a face is a light subject): darkest 5% = dense, 5-15% = middle,
   15-31% = open, rest bare paper. `sketch_shading=false` drops the open and middle bands (dense stays).
3. Local darks (FP 3.4): D = blur(L, 6 mm) - blur(L, 0.8 mm). D > 0.055 -> middle, D > 0.115 -> dense.
   This catches eye sockets, nostrils, mouth corners and under the nose and chin (FG 12 "where the darks sit").
4. Clean each band with a morphological open of 1.6 mm.
5. ONE grid of parallel lines along the light slant (FP 3.6). Line width w = 1.0 mm, pitch p = 2.6 mm
   (gap 1.6 mm = 1.6 w, TB/tools "gap never under 1.5 w"). Dense = every line, middle = every 2nd, open = every 3rd.
   If the face box is narrower than 55 mm at output, drop the open band (too coarse to read; TB "spacing stays small
   relative to the object").
6. Jitter each line sideways by up to 0.15 mm, low-frequency (smooth along the line), so it is not ruled (FP 3.7).
   Taper stroke ends over 1.5 mm where they end inside the form (rounded form, TB stroke ends) but never thinner than 1.0 mm.
   Drop strokes shorter than 3 mm.
7. No cross-hatching anywhere (TB, FL 8).

## 3. Solid black (FP 5, TB black, FL 8)
1. Black where L blurred 0.25 mm < 0.20. Inside eye boxes the limit is 0.27, and keep a catchlight: the brightest
   1.2 mm disc inside each eye's dark stays white (FG 5 Eye).
2. Hair (FL 6): hair region = mask above the face box top + 0.15 face h, plus the side strips beside the face box.
   If its median L < 0.35 (dark hair): fill it solid black (Beardsley mass, FL 6 / FL 15 "close the polygon along
   the scalp, fill black") and cut 3 to 7 white strands where the fine image is brighter than the mass
   (L at 0.3 mm > L at 2 mm + 0.08), skeletonised and redrawn 1.0-1.3 mm wide, tapered, stopping before the edge (FL 8 BA1026).
   Leave the lit crown a bare band one bundle wide (FL 6 "what stays bare paper"). If hair is light: no fill; its own
   edges come through step 4 as bundles of strands.
3. Count black components after cleaning. More than 3 large ones (area > 2% of the head) -> raise the cut toward 0.17
   until <= 3 (TB "one or two pure blacks"; FP 9 "any black shape that is not in the photo is a threshold set too loose").
4. Every black keeps a small white relief somewhere inside or beside it (TB black).

## 4. Surface lines from the photo's own edges (FP 6, FL 9)
1. Canny on L blurred 0.3 mm, low/high thresholds from the image (quantiles 0.7 / 0.9 of gradient magnitude),
   inside the mask eroded 1.5 mm.
2. Trace edges as polylines (skimage.measure.find_contours on the edge map dilated by 1 px, or a skeleton walk).
   Drop lines shorter than 4 mm. Smooth each with a 5-point moving average (FL: one decisive line).
3. Rank by mean gradient magnitude, 0..1 among all lines. Keep if rank beats the zone threshold:
   full light 0.66, open 0.50, middle 0.40, dense 0.62; minus 0.24 inside the centre of interest;
   plus (0.5 - sketch_detail) * 0.3 everywhere.
4. Feature caps (FL 9 "a face is 6 to 10 marks", FG 5): inside the centre-of-interest box keep at most 12 lines,
   the highest ranked. Upper lid = the strongest line in each eye box: draw it 1.6 mm at its middle tapering to 1.0 mm;
   lower lid 1.0 mm. Lip parting = the strongest roughly horizontal line in the mouth rows (68%..85%): heaviest line
   of the face, 1.8 mm middle tapering to 1.0. Nostrils: solid dark (from section 3 or local darks), no outline round the nose.
   Brows: tapering stroke, thickest at the nose end.
   Cross-contours never enter the eye, lip or ear (FL 9).
5. Other lines 1.0 to 1.4 mm by rank, a little heavier inside the focus.

## 5. Outline (FP 7, LO who owns the line, RE 8)
Walk the mask contour (smoothed with a 2 mm moving average):
| at this point | width |
|---|---|
| black mass or dense hatch on either side | none |
| middle hatch just inside | 1.0 |
| faces the light | 1.7 |
| faces away from the light | 1.0 |
| between | 1.3 |
Draw in runs: heavy runs 10-28 mm, light runs 5-12 mm, lifts of 1.2 to 2.0 mm between (gaps must stay >= 1.0 mm).
Lift at the lit cheek (FL 7 "a skin line breaks at the lit side of a cheek"). The shoulders/neck outline thins and
stops before the bottom edge of the crop (vignette, TB).

## 6. Composite and finish (SKILL step 11, tools-and-vector checks)
1. Render strokes into the raster with round caps (variable width = filled shapes), union with blacks and hatch.
2. Clay floor: remove black specks < 1.0 mm^2, fill white holes < 1.0 mm^2 except catchlights, and make every gap
   >= 1.0 mm: where two black regions come within 1.0 mm, erase a 1.0 mm white gap rather than merge them
   (tools-and-vector: "white gap between touching dark shapes: at least one stroke width"). Lines must not fall
   below 1.0 mm anywhere (check with a distance transform; thicken any thinner piece).
3. Tone share of the subject: target 25-35%; over 50% reads grey and heavy (FP 9) -> raise the percentile cuts by 3
   points and redo once.
4. Return the binary mask (True = ink = pressed into clay in positive mode) plus a report: face_found, light_side,
   blacks, tone_share, lines_kept, min_line_mm, min_gap_mm, px_per_mm.
5. Hand the mask to the same potrace trace used for PNG today (refactor `_load_raster`'s trace into `_trace_mask(mask)`),
   so the roller gets smooth Bezier edges (tools-and-vector: few anchors).

## 7. Size the roller to the face
Add a helper `api.fit_portrait(params, upload) -> {diameter, n_around, n_along}`: one face per revolution
(n_around 1, n_along 1), art height = L - 2 x band, width from the head-crop aspect, D = width / pi, clamped to R04 (16..100).
The UI calls it from a button "Fit roller to this face".

## 8. Checks the tests must make (pytest, app/tests/test_sketch.py)
- Use `skimage.data.astronaut()` (public-domain NASA portrait) saved to PNG bytes as the person photo.
- Face found; head crop contains the face box.
- Output mask: min line width >= 1.0 mm and min gap >= 1.0 mm (distance transforms on ink and on paper, ignoring
  the outer 1 px and catchlights), black components <= 3 large, tone share 15-50%.
- Light side detected equals the brighter side of the face box.
- Eye boxes contain ink; the mouth rows contain a near-horizontal stroke.
- Portrait art goes through preview() and export_bytes(); the exported STL is watertight (reuse existing checks).
- Runs with build123d/manifold3d/lib3mf blocked (existing pattern). Time the sketch: under 4 s on CPython at 140 mm.
- Save visual outputs for review: app/out/sketch/astronaut_photo.png, astronaut_sketch.png (the mask at output size,
  black ink on white), astronaut_slab.png (the slab preview), astronaut_compare.png (photo crop and sketch side by side,
  same size: FP 9 "put the drawing beside the photo").
