# Failure modes

"(weak)" = only trust 1-2 sources back the claim. Each bullet names the symptom and the cited cause or fix.

## Clay-side failures
- Roller sticks to clay: no release agent [S020]; PVC core worse than wood [S049, S069, S088]; fix by cornstarch or baby powder [S020, S050, S100], oil on grooves [S081, S082].
- Printed roller still sticks even with baby powder on Model Magic [S020].
- Shallow impression: relief too shallow [S022]; wrap clay too thin [S026]; clay too firm [S086] (weak).
- Distorted impression: clay too soft [S086] (weak); slab shifts [S081].
- Warped slab or cracked mat: dry clay cracks linoleum and shows in impression [S082]; Model Magic and putty warp [S020].
- Uneven depth across slab: use rims 2-4 mm [S101]; slab larger than mat for even pressure [S082].
- Slabs open up at joins as they dry; over-bend and compress [S068, S080].
- Texture rounding or warping in firing: clay softens near melting point; porcelain worst; thin walls worse [S087].
- Glaze pools in recesses and catches on raised areas [S080]; slip may not break over texture if the wrong thickness [S085].
- Handles too thick jam against clay and stop the roller turning [S022].
- Pattern prints mirrored: text must be mirrored on the roller [S022, S100].
- Visible repeat/seam: pattern width must equal pi x diameter [S104]; texture must tile [S025] (weak).

## Print-side failures
- Roller too slow to print: thick walls, large size; 8 h reported for a 60x180 roller on A1 Mini [S060] (weak).
- Rough inside after displace; fix with boolean [S024] (weak).
- Displace too strong: boolean fails at strength 5; too many points breaks the model [S027].
- Too many vertices slow the slicer; keep under about 100,000 [S022]; decimate ratio 0.1 very slow [S027].
- Flipped normals show red in the slicer [S025] (weak).
- Layer lines visible up close, especially 0.4 mm layers/nozzle [S021].
- Thin hollow shell fails unless Solidify added [S024] (weak).
- Brass nozzle lead concern; PLA softens at 60-70 C [S070, S071].
- Printed pattern skewed by overhangs above 15 degrees without supports [S103].
- Tall slim rollers curl or fall: brim recommended [S100]; raft used [S104].
- Commercial licence limits on some downloads [S064] (weak).
- Wooden roller reviews mention uneven grooves and splintering [S051] (weak).

## Design-side failures
- Printed rolling stamps on clay do not work at all in one test [S020].
- Hard XPS foam rolled hardest and gave the least detail [S020].
- Printed texture failed to show in a first test; test a small version first [S022].
- A roller that is too thin walled will not survive; no source gives a failure load [S021, S024].
- Plaster roller chips contaminate clay [S083].
- Sizing: scale in slicer rather than Blender when units cause tiny objects [S025] (weak).

## Open questions
- Failure frequency data: which of these is most common in real use?
- Crush/bend failure load for hollow printed rollers at 254 mm length.
- Does mold release spray or oil degrade PLA/PETG over repeated use?
- Cracking of a printed roller from solvent release agents (WD-40 on plastics)?
- Fired-ware failure from deep relief (cracking at thin sections) in sources: none found.
