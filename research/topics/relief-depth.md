# Relief depth: vs clay type and state, minimum feature size, draft

"(weak)" = only trust 1-2 sources back the claim. No source measures depth against clay type; all figures are designer defaults or claims.

## Depth figures
- Pattern depth 1.5-3 mm reads clearly; default 2 mm [S100].
- Defaults and ranges from generators: relief 1.2 mm and groove 1.2 mm [S101]; 5 mm default with 3-8 mm recommended range [S102]; -1.5 mm cut [S103]; 2 mm emboss [S104].
- 1 to 1.5 mm of relief suits polymer and air-dry clay; more for thick soft-clay slabs [S101].
- 2 mm craft foam gives the effective relief on the hand dowel roller [S049, S069, S088].
- A laser-engraved wooden embossing pin states 1.5 mm pattern depth [S111] (weak).
- Commercial rollers: "deeply carved patterns for bold clay impressions" with no depth number [S042, S043]; rubber Xiem rollers give no depth [S040, S041].
- A printed roller made too shallow barely showed in clay; designer says make it deeper and test a small version first [S022].
- A hand-made polymer wrap roller too thin gave shallow impressions; the wrap clay was rolled to about 2 mm [S026].
- Displace strength in Blender: -0.07 for a cobblestone relief [S025] (weak); 0.75 for one pattern, 3 for a coral pattern gave too much relief, 5 caused boolean failure [S027]; about 0.3 mentioned [S024] (weak).
- Depth/radius relation: radius = r + relief x (1 - clay) [S101].
- Conflict: 1.2-1.5 mm [S101, S103, S111] vs 2 mm [S100, S104] vs 3-8 mm [S102]. S102 is far deeper than every other source.

## Clay type and state
- Texture works best when clay is between soft and leather-hard; too soft distorts, too firm may not take the impression [S086] (weak).
- Roll on soft, pliable clay for sharpest detail [S063] (weak).
- Clay type behavior: stoneware gives clean defined impressions; earthenware softer detail; porcelain captures fine detail but dries quickly; air-dry clay is fragile long term [S086] (weak).
- Rolling a printed roller into Model Magic, air-dry clay and putty gave about twice the detail of dollar-store foam, which gave about twice the detail of XPS foam [S020].
- Leather-hard clay can be rolled with a dusted roller [S100].
- Larger slab than the mat gives even pressure across the mat [S082].
- Slab thickness must exceed the final target (trial and error); a 3/8 in (9.5 mm) earthenware slab was used with textured slip [S082, S085].
- Slip breaks over texture so the red clay shows through; depends on slip thickness [S085].
- Dry clay can crack the mat and show in the impression [S082].
- Texture board paste layer 3/16-1/4 in (4.8-6.4 mm); impression depth not given [S081].

## Minimum feature size
- On a 0.4 mm FDM nozzle keep joint width at 0.8 mm or more [S101].
- 0.2 mm nozzle gives finer cracks but both 0.4 and 0.2 are usable at normal viewing distance; layer lines visible up close on 0.4 [S021].
- Image resolution for image-to-roller default 72 ppi, 72-300 ppi recommended [S102].
- Source images around 900-1000 px worked for a displace texture [S024] (weak).
- Minimum line width is only a UI warning in one generator; value not stated [S100].
- Impression detail is limited by clay softness and 3D-print layer lines, not just geometry [S021, S086].

## Draft and release geometry
- Taper of -2 to -5 degrees on the emboss walls to help release [S104].
- Overhang 15 degrees or less in a printable pattern [S103].
- Bevelled roller edges for clean release [S043, S047].
- Rounded corners: sharp top/bottom rim corners kept with crease in a displace workflow [S027].
- Relief mode choices: pressed in or raised on the roller [S100]; recessed roller surface presses raised relief into clay [S022]; carved stamps reverse the imprint so positive/negative must be planned [S080, S112 (weak)].
- Mirror text on the roller or it prints backwards on clay [S022, S100].
- Undercuts and sharp edges: not addressed by any source [S080, S083, S084, S088].

## Open questions
- Measured imprint depth in mm for soft, medium, leather-hard stoneware/earthenware/porcelain at a given roller pressure.
- Minimum feature width and spacing that holds in leather-hard clay (not only FDM nozzle limits).
- Does 3-8 mm depth [S102] work, or tear/stick? Where is the upper limit?
- Draft angle beyond -2 to -5 degrees for deep relief in clay; undercut limits.
- Depth lost to shrinkage and glaze, by percent.
