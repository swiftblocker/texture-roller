# Printing and CNC: orientation, layer height, nozzle, materials, supports, CNC rotary, bits

"(weak)" = only trust 1-2 sources back the claim.

## Orientation
- Print vertically with the roller axis up (one listing asks for vertical printing) [S062] (weak); "print in the direction the files are placed" [S060] (weak).
- Rod printed on its side in a different design [S103].
- Layer lines run around the circumference when vertical; the claim that this reduces drag is not stated by any source.

## Layer height and nozzle
- 0.16 mm layers default (0.12 or 0.20 selectable) [S100]; 0.16 mm tested in a MakerWorld roller [S050]; 0.15 mm recommended [S060, S061 (weak)]; 0.2 mm [S021, S104]; 0.3 mm [S103]; 0.12 mm [S065] (weak); 0.16-0.20 mm advised [S067] (weak).
- Nozzle: 0.4 mm vs 0.2 mm tested; 0.2 gives finer cracks, layer lines visible up close on 0.4 [S021]; minimum joint width 0.8 mm on 0.4 mm nozzle [S101].
- Adaptive layers were used with 0.2 mm on an A1 [S021].
- Arachne walls; outer brim on tall slim rollers [S100].
- Raft used for a 40 x 60 mm roller [S104].
- Layer lines transfer to clay detail at close range [S021].

## Walls, infill, speed
- Walls: 2 [S050]; 3-4 [S067] (weak).
- Infill: 10% [S050]; 15% [S060, S061 (weak), S062 (weak)]; 15% gyroid [S100]; 15-20% [S067] (weak); 30% [S104].
- Slower outer-wall speed recommended [S067] (weak); print temperature 210 C for PLA [S104].
- Print times: about 2 h for 100 x 25 hollow [S021]; about 2 h for 40 x 60 [S104]; about 1.5 h [S022]; about 8 h for a 60 x 180 on A1 Mini [S060] (weak).
- Conflicting infill advice (10-30%) and no source tests crush resistance.

## Materials
- PLA is the common choice [S021, S050, S062 (weak), S067 (weak), S104]; PLA fine, PETG copes with warm water [S100].
- Resin printing implied in one Blender tutorial [S025] (weak).
- Rubber (Xiem) and wood (MKM, hickory) as commercial alternatives [S040-S047].
- Printed rollers stick to clay without release agent [S020].
- Cleaning, sealing and food contact: see food-safety-sealing.md.

## Supports
- No supports for [S050 (S063 summary), S060, S061 (weak), S067 (weak)]; supports needed for the middle roller in one Nomad Sculpt design [S022].
- Overhang 15 degrees or less; support resolution 2 mm [S103].
- Mesh tips: voxel remesh to merge, decimate under about 100,000 vertices [S022]; decimate 0.2-0.3 after displace so booleans do not fail [S027]; recalc outside normals before export [S025] (weak).
- Cylinder end caps complicate UVs [S025] (weak); texture sides only (top/bottom OFF) [S021, S027].
- Printer limits: roller length up to 320 mm and diameter up to 300 mm in Bambu H2C [S100].

## CNC rotary and bits
- 4-axis desktop CNC limit: 170 mm long with tailstock (225 mm without), 136 mm diameter [S110]; tailstock recommended for long pieces [S110].
- Feed and plunge both 400 mm/min; stepdown 1.5 mm per pass; stepover half the bit diameter; straight-groove V-bit stepover 0.12 mm [S110].
- Hand-carved comparison: porcupine quill carving of clay roulettes [S084]; CNC milling used for linoleum mats [S082].
- Laser engraved wood pin at 1.5 mm depth [S111] (weak).
- Bit diameters, V-bit angle, RPM, min feature width: not stated by any source.
- No source on wood species for CNC rollers; hickory used in commercial rollers [S047].
- Commercial wood rollers use food-safe/oil finishes: tung oil [S048]; protective oil [S044]; food-safe finish [S042].
- CNC max length (170-225 mm) is below the project's 254 mm requirement [S110].

## Open questions
- Best print orientation for roundness and layer-line smoothness on a 254 mm roller; any test of vertical vs horizontal?
- PETG vs PLA vs resin stickiness and wear against wet clay.
- CNC rotary bit sizes, V-bit angles, feeds for 1.5-3 mm relief in wood/MDF/acrylic; how to hit 254 mm length.
- Does ironing, sanding or vapor smoothing improve release?
- Printer volume limits: what can a typical 256 mm bed print at 254 mm length?
