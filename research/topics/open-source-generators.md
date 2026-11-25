# Open-source and existing generators: parameters and defaults

"(weak)" = only trust 1-2 sources back the claim.

## Sparaa/clay-roller-studio (Bambu 3MF, picture to roller) [S100]
- Default relief 2 mm; README says 1.5-3 mm reads clearly [S100].
- Settings: diameter, length, plain end bands, bore (solid, 8 mm rod, 1/2 in, 3/4 in dowel, custom) [S100].
- Example roller 40 x 150 mm [S100].
- Printer limits (Bambu H2C): length up to 320 mm (325 mm right nozzle only); diameter up to 300 mm [S100].
- Print: 0.16 mm layers (0.12 or 0.20 selectable), Arachne walls, 15% gyroid infill, outer brim on tall slim rollers [S100].
- Relief modes pressed in or raised; mirror on by default [S100].
- Release advice: PLA fine; PETG copes with warm water; dust with cornstarch or roll leather-hard clay [S100].
- Minimum line width is a UI warning, value not stated [S100].

## sh0tybumbati/clay-roller (flagstone, brick, cobble, cracked, cuneiform STL) [S101]
- Defaults (roller.py): size 12 mm; groove 1.2 mm; relief 1.2 mm; grain 0.15 x relief; diameter 30 mm; length 60 mm; bore 8 mm (0 = solid); rim 0 mm; grid res 0.25 mm [S101].
- One turn = pi x diameter imprint (94 mm at 30 mm) [S101].
- Relief 1-1.5 mm for polymer/air-dry; more for thick soft-clay slabs [S101].
- 0.4 mm nozzle: joint width >= 0.8 mm; rims 2-4 mm recommended [S101].
- Surface formula: radius = r + relief x (1 - clay), mirrored [S101].

## disdyakis/ceramics-tools (OpenSCAD bash; roller, stamp, sprig mold) [S102]
- img_to_cylinder.sh: texture depth (-d) default 5 mm, recommended 3-8 mm; wall thickness (-t) default 5 mm; image resolution default 72 ppi, recommended 72-300 [S102].
- Analyze mode formula: radius = width/(8 x pi x ppi) - 0.039 x depth (inches) [S102].
- Tools: hollow cylindrical roller, spherical roller, stamp with dowel handle, sprig mold [S102].
- License CC BY-NC-SA 4.0 on the code [S102].

## Blender add-ons and tutorials
- Superhive Texture Rollers Generator: commercial Blender add-on; Egg Roller, Shaft Roller, Texture Ball; texture category, adjustable depth, edge smoothing, Random Seed; STL output; no diameter/length/bore stated; 0.16-0.20 mm layer, 3-4 walls, 15-20% infill, PLA, no supports [S067] (weak).
- Tutorial workflows: Bump Mesh browser texture tool with "inverted" and top/bottom OFF [S021]; Blender cylinder displace on UV map with vertex group [S021, S023 (weak), S024 (weak), S027]; plane bent 360 degrees [S025] (weak); Nomad Sculpt stamp tool [S022].
- Blender settings used: unit scale 0.001; 64 [S021], 128 [S023], 280 [S024] vertices; loop cuts about 20 [S021], about 500 [S023], about 600 [S024], about 60 [S027]; Subdivision level 6 [S021], 2-3 [S027]; displace sampling set to soften/clean B/W edges [S021, S023].

## Printed-model sources (blocked or partly read)
- MakerWorld Floral Damask: 120 x 38 mm and 160 x 60 mm, 0.16 layer, 2 walls, 10% infill, 121 g PLA, light cornstarch, no visible join [S050].
- 3Demon Nature Rollers: 60 x 60 x 180 mm, 0.15 layer, 15% infill, no supports, separate handle file [S060] (weak).
- Printables sets and MakerWorld positive/negative pair [S061, S062, S064] (weak, blocked); OpenSCAD customisable roller with rebate depth and height settings, repo ostat/OpenSCAD-Projects not opened [S066] (weak); Greek wave roller 0.12 layer, metal shaft [S065] (weak).
- Instructables cookie rollers: 15 mm rod x 127 mm; sleeve 45-50 mm dia; pattern -1.5 mm; 0.3 mm layers [S103]; 40 x 60 mm with 2 mm emboss, taper -2 to -5 deg, 0.2 layers, 30% infill [S104].

## Comparison summary
- Depth defaults differ: 1.2 mm [S101] / 2 mm [S100, S104] / 5 mm [S102].
- Diameter defaults: 30 mm [S101]; 40 mm example [S100, S104]; other designs [S050, S022].
- Only [S100] and [S101] expose bore; only [S100] exposes end bands; only [S101] sets rims.
- No generator source provides a 254 mm (10 in) default.

## Open questions
- What do ostat/OpenSCAD-Projects and the blocked Printables/MakerWorld models actually expose (bore, handle, seam handling)?
- Do any generators enforce wall/depth checks, and what do their warnings say?
- Is there a generator that bends art with true cylinder wrap and handles seam blending?
- License terms for reusing generator code (S102 is CC BY-NC-SA 4.0).
- A default depth that all sources would accept for the stated clay types.
