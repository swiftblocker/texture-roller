---
name: pottery-roller
description: Rules for designing clay texture rollers (cylinders with relief art rolled across clay slabs), 3D printed or CNC cut. Use when sizing a roller, setting relief depth, wrapping art onto a cylinder, hiding the wrap seam, choosing a bore or handle, or checking a roller mesh before export. The generator in app/ enforces these rules by number.
---

# Pottery texture roller rules

Every rule has an ID (`R##`), a value, the reason, source IDs from `research/INDEX.md`, a confidence, and a check.
The generator reports the ID when it warns or blocks.

- **Action**: `BLOCK` stops export. `WARN` shows a warning and still allows export.
- **Confidence**: `high` = several sources agree, or it is geometry. `med` = one good source or consistent weak ones. `low` = derived by Claude from adjacent evidence. These need a clay test before anyone trusts them.
- `D` = outer diameter at the relief top level (the rolling surface). `C` = pi x D. `L` = roller body length. `d` = relief depth. `t` = wall under the deepest recess.
- **Research caveat**: no source measured impression depth against clay type and state. Every depth rule is med or low until the owner's test rollers are rolled. Reddit, Etsy, Printables and MakerWorld were mostly blocked (see INDEX.md).

Reference tables: `references/dimensions.md` (commercial and printed sizes), `references/shrinkage.md` (clay bodies), `references/checks.md` (machine-readable check list for the engine).

---

## 1. Geometry

| ID | Rule | Why | Sources | Conf | Check / action |
|---|---|---|---|---|---|
| R01 | Body length L <= 254 mm (10 in). | Project limit. X1C Z is 256 mm. | brief | high | `L <= 254` BLOCK |
| R02 | Printed upright on the X1C: L + brim/raft <= 250 mm recommended. | Leaves 6 mm under the 256 mm Z limit for the first layer and nozzle clearance. | S100 | med | `L > 250` WARN |
| R03 | The image's axial height + 2 x end band <= L. | The end bands sit inside the body length. | S100, S101 | high | BLOCK |
| R04 | D range 16-100 mm. Recommended 25-60 mm. | Commercial rollers run 16-51 mm, printed ones 20-100 mm. Under 16 mm deflects. Over 100 mm wastes plastic and gets hard to steer. | S040-S045, S050, S021, S022 | med | `D<16` BLOCK, `D>100` WARN |
| R05 | Slenderness L/D <= 8 for a solid or hollow printed body with no metal axle. Over 8, require a through-axle bore. | A long thin plastic tube bends under hand pressure and the impression goes shallow in the middle. Commercial long rollers are 25 x 200 mm (L/D 8). | S045, S049 | low | `L/D>8 and bore==0` WARN |
| R06 | L/D > 5: add a brim (or print in two halves) | Tall slim prints curl or tip over. | S100, S104 | med | WARN |
| R07 | Circumference C = pi x D. Repeat width around the roller = C / n_around. The UI shows both live. | One turn prints exactly one circumference. | S101, S104, S083 | high | always shown |
| R08 | The art's wrap width must equal C within 0.05 mm, after scaling. | A mismatch makes a gap or an overlap at the seam on every turn. | S104 | high | `abs(w-C)>0.05` BLOCK |
| R09 | Hollow body: wall under the deepest recess t >= 2.0 mm (L <= 160) or >= 3.0 mm (L > 160). | 3 mm is "more than strong enough" at 100 mm. Longer bodies carry more bending. | S021, S024, S104 | med | BLOCK below 1.6, WARN below the target |
| R10 | Solid body: allowed. Hollow is the default when D >= 30 mm, to cut print time. | 60 x 180 solid took about 8 h on an A1 mini and users asked for lighter ones. | S060, S021 | med | info |
| R11 | Recommended starting pair for a 10 in axial image: D 40-50 mm, L 254 mm, 12.7 mm (1/2 in) dowel bore. | C = 126-157 mm gives a usable repeat. L/D 5-6 keeps it stiff with a dowel. | derived from R04, R05, R07 | low | default preset |
| R12 | Report what one revolution covers: roll-out per revolution = C, and roll-out over a 254 mm slab = 254 / C revolutions. | Tells the potter how many repeats land on a slab. | derived | high | shown |

## 2. Relief

| ID | Rule | Why | Sources | Conf | Check / action |
|---|---|---|---|---|---|
| R13 | Relief depth d default 1.5 mm. Usable range 0.8-3.0 mm. | 1.5-3 mm "reads clearly". Generators default to 1.2-2 mm. Embossed rolling pins use 1.5-2 mm. | S100, S101, S103, S104, S111 | med | info |
| R14 | d < 0.8 mm: WARN "impression may not show". | Shallow printed rollers barely showed in clay. | S022, S026 | med | WARN |
| R15 | d > 3.0 mm WARN. d > 5.0 mm BLOCK. | Above 3 mm only one source (S102) recommends it, and it is far deeper than every other source. Deep narrow recesses trap clay. | S102 (conflict), S100 | low | WARN/BLOCK |
| R16 | d <= 0.12 x D. | Keeps the relief from eating the core and keeps the wrap distortion (inner vs outer arc length) under about 25%. | derived (geometry) | med | WARN |
| R17 | Clay-state presets for d: soft 1.0-2.0 mm, firm/soft-leather 1.5-2.5 mm, leather-hard 2.0-3.0 mm with dusting. | Soft clay takes detail easily but distorts with deep relief. Firmer clay needs more relief and pressure. | S086 (weak), S063, S100 | low | preset only |
| R18 | Clay-body presets: porcelain keeps fine detail (min feature can drop 20%) but dries fast. Earthenware softens detail (raise d by 0.3 mm). Stoneware is the baseline. | Only one weak source compares bodies. | S086 (weak), S087 | low | preset only |
| R19 | Raised feature on the roller (makes a recess in clay): top width >= 1.0 mm. | 0.8 mm is the FDM minimum on a 0.4 nozzle. Clay needs extra width to hold the edge without tearing. | S101, S021 | med | WARN below 1.0, BLOCK below 0.8 |
| R20 | Recess on the roller (makes a raised ridge in clay): opening width >= max(1.0 mm, 0.8 x d). | Clay must fill the groove and release from it. Narrow deep grooves keep clay (the same reason dough sticks in rolling pins). | S104, S081 | low | WARN |
| R21 | Gap between raised features on the roller >= 1.0 mm. | The groove between them is a recess (see R20). | S101 | med | WARN |
| R22 | Sidewall draft >= 5 deg from radial. Default 15 deg. | Rolling pins use 2-5 deg taper to release. Clay is stickier than dough, so the default is steeper. | S104 | low (value), high (need) | measured max slope; WARN under 5 deg |
| R23 | No undercuts. The relief is a single-valued radius r(theta, z). | Undercuts lock clay. The engine builds relief as a heightmap, so undercuts are impossible by construction. The check confirms it. | S080 (gap), derived | high | radial ray test BLOCK |
| R24 | Edge round on relief tops and groove bottoms: radius >= 0.3 mm (default 0.4). | Sharp top edges tear the clay surface. A sharp inside corner holds clay. Bevelled edges release cleanly in commercial rollers. | S043, S047, S103 | low | built in by the chamfer parameter |
| R25 | Minimum relief area fraction 20%, maximum 80% (fraction of the surface at the top level). | Under 20% the roller rides on a few ridges and wobbles. Over 80% the image is mostly background and reads weakly. | derived | low | WARN |
| R26 | Strokes thinner than 2 x the nozzle width after scaling are dropped or thickened (user choice), never silently printed. | They do not print and would be missing from the clay. | S101 | high | WARN with a count |
| R27 | Fired-size display: show the slab preview at wet size and at fired size, using the body's shrinkage from references/shrinkage.md (earthenware 5-10%, stoneware 10-15%, porcelain 14-17%). | Relief and image shrink by the same fraction. A 254 mm wet image is about 221 mm fired in stoneware. | S105-S109 | med | info |
| R28 | Relief that has to survive glaze: d >= 1.2 mm when glaze will pool in the clay's recesses. | Shrinkage (about 13%) plus glaze fill softens shallow texture. | S080, S087 (qualitative) | low | WARN when the glaze flag is on |

## 3. Pattern and repeat

| ID | Rule | Why | Sources | Conf | Check / action |
|---|---|---|---|---|---|
| R29 | n_around is an integer >= 1. | A non-integer repeat leaves a partial tile at the seam. | S104 | high | BLOCK |
| R30 | n_along is any positive value, but the art must end inside the end bands (R03). | Partial tiles at the roller ends are fine. They fall at the slab edge. | derived | high | info |
| R31 | Tile aspect check: tile width = C / n_around. Keep the scale error from stretching the art <= 2%. If fitting the art to C needs more, change D or n_around. | Non-uniform stretch distorts circles into ovals that people notice. | derived | med | WARN at 2%, BLOCK at 10% |
| R32 | Half-drop/brick offset: allowed when n_around >= 2. Offset = 0.5 tile. Any offset fraction f is allowed when the rows still close around the roller (n_around x tile = C). | A half-drop on one tile cannot close the seam. | derived | high | BLOCK when n_around=1 with offset |
| R33 | Rotation of the art inside the tile must keep the tile periodic (0, 90, 180, 270 deg), or the art must sit inside the tile with margin >= 1 mm. | Rotating a periodic tile by an odd angle breaks its edges. | derived | high | WARN |
| R34 | Spacing between tiles >= R21's 1.0 mm when spacing is not 0. | The spacing becomes a groove or a land in clay. | S101 | med | WARN |
| R35 | Mirror default ON for the roller surface, so the slab reads the way the art was drawn. | The roller prints the mirror image of its own surface. Text especially comes out backwards. | S022, S100 | high | default; the slab preview always shows the clay side |
| R36 | Positive mode (default): dark/filled art = raised on the roller = recessed in clay. Negative mode: dark art = recessed on the roller = raised in clay. The UI labels both by their CLAY result. | Potters think in what the clay shows. Sources confuse the two directions. | S100, S022, S080 | high | label rule |
| R37 | Long rolls: rotating the roller or changing the start point breaks up visible repetition. The slab preview offers a random start phase. | Potters do this by hand. | S049, S088 | med | preview feature |

## 4. Seams

| ID | Rule | Why | Sources | Conf | Check / action |
|---|---|---|---|---|---|
| R38 | Preferred seam method: art that tiles. The heightmap's first and last columns must match within 0.05 mm. | A seamless tile leaves no seam. | S050, S025, S104 | high | edge-diff check, BLOCK over 0.2 mm, WARN over 0.05 mm |
| R39 | Non-tiling art: choose one. (a) Background seam: place the seam where both edge columns are at the background level for >= 90% of their length. (b) Blend: crossfade a band 3-8% of C wide. (c) Gutter: a plain land 1-3 mm wide at the seam. | The seam shows as a line in clay unless it falls on background. | S021, S025, derived | med | the engine picks (a) when possible, otherwise asks |
| R40 | Seam position is a parameter (theta_0). The engine auto-rotates the art to the column with the least relief to place the seam there. | Cheap and invisible when the art has open space. | derived | med | auto |
| R41 | Mesh closure at the seam: vertices at theta = 0 and theta = 2pi are shared (welded), not duplicated. | Duplicated seam vertices make a non-manifold slit. | S025 | high | manifold check BLOCK |
| R42 | End bands (rims): width 2-4 mm at full radius (the top level), default 3 mm. | Rims keep depth even across the slab and stop the roller ends marking the clay. | S101, S100 | med | WARN under 2 mm, 0 allowed if the user turns rims off |
| R43 | Roller ends: chamfer or round >= 1 mm x 45 deg on the outer edge. | The bevelled ends of commercial rollers keep the roller from marking the clay. | S043, S047 | med | WARN when 0 |
| R44 | Slab tiling across passes: alignment notches on the end band at the seam (optional, 1 mm V). | No source covers alignment. A tick shows where the repeat starts. | derived | low | option |

## 5. Clay compatibility

| ID | Rule | Why | Sources | Conf | Check / action |
|---|---|---|---|---|---|
| R45 | Release: dust lightly with cornstarch. Leather-hard clay can be rolled with a dusted roller. Oil in the grooves for detailed work. Print this on the export sheet. | Printed rollers stick without a release agent. | S020, S050, S100, S081, S082 | high | info on the export sheet |
| R46 | Surface finish: printed surfaces stick more than wood. Recommend a matte, slightly textured finish. Never gloss epoxy for release. | Clay sticks more to PVC than wood. Smooth non-porous surfaces suck onto wet clay. | S049, S069 | low | info |
| R47 | Clay state window: between soft and leather-hard. Too soft distorts, too firm will not take the texture. The UI clay-state selector sets the R17 preset. | | S086, S084, S080 | med | preset |
| R48 | Slab thickness >= 2 x d + 3 mm, and >= 6 mm for slabs that will be formed. | The texture must not thin the slab through. Sources used 9.5 mm slabs. | S082, S085, derived | low | slab preview WARN |
| R49 | Rolling pressure: light, even, one pass. Rotate the start point per pass. | Re-rolling double-prints. | S049, S020 | med | info |
| R50 | Mold/stamp hygiene: no plaster rollers. Clean the roller between clay bodies. | Plaster chips contaminate clay. | S083 | med | info |

## 6. Manufacturing

| ID | Rule | Why | Sources | Conf | Check / action |
|---|---|---|---|---|---|
| R51 | FDM: print upright (axis vertical). Relief on the vertical wall prints as clean perimeters with no supports. | Most makers print vertical with no supports. Lying down makes a flat spot and support scars on the relief. | S060, S062, S050 | med | export metadata |
| R52 | Layer height 0.12-0.16 mm for d <= 1.5 mm; up to 0.20 mm for d > 1.5 mm. Nozzle 0.4 mm (0.2 mm for detail <= 1.0 mm). | Layer lines show in clay up close. 0.16 mm is the common default. | S021, S050, S100 | med | export sheet; WARN when the feature is under 2 x nozzle |
| R53 | Upright printing means the relief's slopes are in the XY plane. The 45 deg overhang limit applies only to the end chamfers and the handle shoulders. Keep those <= 45 deg from vertical. | Vertical walls have no overhang problem. Only horizontal ledges do. | S103 | high | overhang check on Z-facing faces, WARN |
| R54 | Material: PLA OK. PETG preferred when it will be washed in warm water. No resin for rollers over 150 mm without a core (brittle, and needs post-cure). | PETG copes with warm water. PLA softens at 60-70 C. | S100, S070, S071 | med | info |
| R55 | Walls >= 3 perimeters. Infill 15% gyroid for solid bodies. | Common settings across sources. | S050, S060, S100 | med | export sheet |
| R56 | Bore clearance: printed bore = rod diameter + 0.3 mm for a slip fit (dowel/rod turning inside), + 0.1 mm for a press fit. Bore presets: none, 8 mm rod, 12.7 mm (1/2 in) dowel, 19.05 mm (3/4 in) dowel, custom. | FDM holes print undersize. Presets match S100's option list. | S100, S101, derived (fit) | med | BLOCK when the bore wall is under R09's t |
| R57 | Bore through the full length, chamfered 0.5 mm at both ends. | The rod starts cleanly and nothing traps clay at the ends. | derived | med | geometry |
| R58 | Integrated handles: stub diameter <= D - 2 x d - 6 mm, length 80-110 mm each, counted OUTSIDE the 254 mm body limit. Separate handles must not touch the clay plane. | Handles too thick jam against the clay. Handle grip length runs 100-127 mm. | S022, S026, S103 | med | BLOCK when the handle radius >= the roller radius minus 3 mm |
| R59 | Handle frame option (axle on one or both sides): the frame arm clears the slab by >= 5 mm at the roller's lowest point. | Frame arms drag in the clay otherwise. | S083, S044, derived | low | geometry check |
| R60 | X1C total height: body + any integrated handle printed in the same piece <= 250 mm. Otherwise print handles separately. | 256 mm Z. | derived | high | BLOCK |
| R61 | CNC (wood/HDPE on a rotary axis): smallest concave radius in the relief >= the bit radius. Default bit: 1/8 in (3.175 mm) ball or a 30 deg V-bit. Raised features >= 1.5 mm wide. Stepdown <= 1.5 mm. | A rotary router cannot cut an inside corner tighter than its tool. Feeds from S110. | S110 | med | curvature check, WARN |
| R62 | CNC length limit: L <= the rotary axis capacity (the owner's Laguna is not specified yet). The desktop 4th-axis limit seen in sources is 170-225 mm. | 254 mm may exceed many rotary setups. | S110 | med | config value, BLOCK when over |
| R63 | Clay-contact safety: the roller touches raw clay that is later fired, so food contact is indirect. Still use undyed or standard filament and a stainless or hardened nozzle (no brass) for rollers used on tableware. Do not seal with gloss epoxy (see R46). | Firing burns off organic traces. Brass nozzles carry lead. | S070, S071 | low | info |
| R64 | Mesh budget: <= 2,000,000 triangles in the export, <= 300,000 in the preview. | Slicers and the browser slow down. Sources decimate to about 100k for sculpt tools. | S022, S027 | med | WARN |

## 7. Validation

| ID | Rule | Why | Sources | Conf | Check / action |
|---|---|---|---|---|---|
| R65 | The exported mesh is watertight: every edge is shared by exactly 2 faces. | A slicer fills holes unpredictably. | S025, S024 | high | BLOCK |
| R66 | Consistent outward normals and positive volume. | Flipped normals show red in slicers. | S025 | high | BLOCK |
| R67 | No self-intersections. | Over-strong displacement folds the mesh. Booleans fail. | S027 | high | BLOCK |
| R68 | Bounding box: diameter = D (top level) within 0.05 mm. Length = L within 0.05 mm. | Confirms the scale. Avoids the mm vs m unit mistake. | S025 | high | BLOCK |
| R69 | Radial monotonicity: for every (theta, z), a ray from the axis crosses the outer surface exactly once. | Proves no undercut (R23). | derived | high | BLOCK |
| R70 | Minimum wall measured on the mesh (not only from parameters) >= R09. | Parameters can lie when the art goes deeper than expected. | derived | high | BLOCK |
| R71 | The slab preview is generated from the exported heightmap, not from the source art. | The preview must show what the roller will actually print. | derived | high | test |
| R72 | Round-trip test: unroll the exported mesh's radius map, mirror it, and compare it to the slab preview. Max error <= 0.05 mm. | Proves the mirror, invert and seam logic end to end. | derived | high | test suite |
| R73 | Every export writes a sidecar `.json` with all parameters, the rule results, and the warnings the user accepted. | You can tell later why a roller printed the way it did. | derived | high | always |
| R74 | Letter strokes (10th percentile along the skeleton) >= 1 mm plus the draft loss at three quarters height for pressed letters; >= the R20 groove width plus draft for raised letters. The warning names the smallest letter height that passes. | Hairlines of scripts and serifs are thinner than clay can take. | derived | medium | WARN |
| R75 | Text stays inside the art area: never on the end bands, never off the roller. | Letters cut by the band read as a mistake. | derived | high | WARN |
| R76 | Text copies fit their share of the circumference; text bigger than 1.5 x C or taller than L is not drawn. The warning names the largest height that fits. | Overlapping copies merge into a smear; oversized text costs seconds for nothing. | derived | high | WARN |
| R77 | Letters must differ from what surrounds them (at least 30 % of a 2-pixel ring around the letters). | Raised letters on untouched clay with no frame are invisible. | derived | high | WARN |
| R78 | Characters the font lacks, a 4th line, or more than 60 characters are reported, never dropped silently. | The potter must see what the roller will not carry. | derived | high | WARN |
| R79 | If the clay clean-up (slivers under the R74 width) removes more than 15 % of the letter area, say so. | Text that is too small vanishes; it must not vanish silently. | derived | high | WARN |

## 8. Stamp tab (flat hand stamp, not a roller)

The stamp tab lays the same art and relief on a flat block with a knob, pressed face down into clay. Face width W and height H; `d` = relief depth. Confidence is `low` for all of these until a stamp is printed and pressed.

| ID | Rule | Why | Sources | Conf | Check / action |
|---|---|---|---|---|---|
| R80 | Face size and input: the stamp face is 25 to 150 mm each way (W and H), and the input is usable: a picture under 25 megapixels that opens as PNG, JPEG, WEBP or SVG, and settings that are numbers. | Under 25 mm the knob pad and the lines are too small to hold and print; over 150 mm one hand cannot press it evenly and the mesh gets heavy; a huge or unreadable picture cannot be traced in a browser tab. | derived | low | BLOCK |
| R81 | Raised lines and gaps on the face use the roller's limits, measured the same way but without wrapping at the edges, always on one 0.25 mm grid (so preview and export agree): raised line >= 1.0 mm (R19a) and block under 0.8 mm (R19b); groove >= max(1.0, 0.8 d) (R20); gap between raised parts >= 1.0 mm (R21); no feature under 2 x nozzle (R26). Raised slivers under 2 grid pixels wide within 3 mm of the outline are ignored; a thin tip within 3 mm of the outline only warns ("where the art meets the edge: turn the border on or make the art smaller"). | Same clay and same printer as the roller, so the same widths; a tip cut by the edge loses only the tip. | derived | low | BLOCK under R19b away from the edge, else WARN |
| R82 | Raised share of the face (inside the outline, height >= 0.75 d): under 2 % blocks ("nothing to stamp"), 98 % or more blocks ("the face is solid"); under 8 % warns (the stamp will rock, turn the border on or add art); over 85 % warns (almost solid, the print will be faint); a border with no art or text warns (it prints just a frame). | A stamp pressed by hand needs enough contact to sit flat, little enough that clay can move aside, and something to print at all. | derived | low | BLOCK at the extremes, else WARN |
| R83 | With the border rim off, art that runs into the outline (more than 1 % of the 0.75 mm band inside the edge is raised) is cut off at the edge. | Art cut by the edge reads as a mistake; the rim or a smaller picture fixes it. | derived | low | WARN |
| R84 | Knob glue pad = min(40, 0.7 x the short side) mm. Under 20 mm the glued joint may pop off under hand pressure. | A small pad is a small glue joint; epoxy, or a thick block held by its edges (no knob), is the fix. | derived | low | WARN |
| R85 | Both exported meshes (stamp and knob) pass their own check before the zip is built: watertight, every edge shared by exactly two faces with opposite directions (consistent winding), volume > 0, no zero-area triangles. | A slicer fills holes unpredictably; the check is the same proof as R65-R66 on the stamp's own mesh. | derived | low | BLOCK |
| R86 | Export anyway: the owner may override any stop item; the file is marked -override and lists what was overridden. With the tick the engine writes the files whatever the checks say: a broken mesh gets one cheap repair pass (merge vertices, drop degenerate and duplicate faces, fix normals, fill small holes) and is exported either way; a stamp face outside R80's range is built at the nearest limit and the sheet says so; an unexpected engine error is tried once more on a coarser grid. Never overridden: no picture, a file that is not a picture, a picture of one flat colour, and (cookie) a picture with no outline. The flag never changes a preview. | The owner decides what is worth a print; the engine must not hide the risk, so every STL, 3MF and zip carries -override and the sheet lists each stop word for word. | derived | high | none (owner choice) |

Fixed numbers behind these rules (see `app/out/stamp/brief.md`): block under the relief 6 mm with a knob or 12 mm without; face mirrored left to right (R35 on a flat stamp); 0.6 mm chamfer on the outer top edge; border rim 1.5 to 6 mm at full relief height; mushroom knob 28 mm grip, 30 mm tall, 18 mm grip minimum on faces under 35 mm; relief 0.8 to 3.0 mm; export grid pitch max(0.2, max(W, H) / 450) mm, coarsened so the face stays under 300k triangles (250k round; round blocks halve the spoke count inward so edges stay near one pitch).

---

## How to use these rules

1. Size first: R01-R12. Pick D from the repeat you want (R07), then check L/D (R05).
2. Set depth from the clay state and body: R13-R18 and R27.
3. Prepare the art: R19-R26 for feature sizes and R35-R36 for direction.
4. Lay out the repeat: R29-R34, then close the seam: R38-R43.
5. Pick the build: R51-R62.
6. Validate: R65-R73. Any BLOCK stops export.
7. Stamp tab: R80-R85 (size, lines, contact, edge, knob pad, mesh).
8. Export anyway: R86, on all three tabs.

## Known gaps (needing a clay test)

- Measured impression depth vs d for each body and state (R13-R18 are guesses within the sources' range).
- Draft angle for clay release (R22).
- Wall thickness at 254 mm length (R09) and whether a dowel core is needed (R05).
- Release on PLA vs PETG (R45-R46).
