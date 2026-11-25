# Geometry: diameter, length, wall, circumference/repeat

"(weak)" = only trust 1-2 sources back the claim.

## Diameter
- Commercial rollers: MKM hand roller 5/8 in (15.9 mm) dia [S042]; MKM big hand roller 1 in (25.4 mm) dia [S043]; MKM long hand roller 1 in (2.5 cm) dia [S045]; MKM large handle roller 1.6 in (40.6 mm) dia [S044]; Xiem rubber roller 2 in (about 51 mm) dia [S040, S041].
- Printed rollers seen: 38 mm dia (medium) and 60 mm dia (large) [S050]; 100 mm dia [S022]; 25 mm dia [S021]; 30 mm default [S101]; 40 mm OD [S104]; 45-50 mm sleeve [S103]; 15 mm rod [S103].
- Small diameters seen in weak sources: 20 mm dia [S023] (weak); 20 mm high Greek wave roller [S065] (weak); 10 cm x 1.5 cm wooden roller [S052] (weak); 8 cm Etsy roller [S051] (weak).
- Hand dowel roller: 1-1/4 in (about 32 mm) dia [S049, S069, S088].
- Clay coil roller: about 1 in (25 mm) dia [S083].
- Generator max (Bambu H2C): diameter up to 300 mm [S100].
- 3D Printing Professor pendant tube: 2.5 mm radius + 1.6 mm wall (not a clay roller) [S027].

## Length (working face)
- Commercial: 4 in (10.16 cm) [S042]; 4.75 in (12.06 cm) [S043]; 7.9 in (20 cm) [S045]; 7 in (178 mm) rubber [S040, S041]; 2.4 in (6.10 cm) wide handle roller [S044]; design face 1.2 in (3 cm) [S046]; 30 mm face [S047].
- Other commercial widths listed: MKM Rollers4Clay 1.5, 3 and 6 cm; Amaco rubber 4-1/4 in; Xiem 7 in (31 patterns); Chinese Clay Art 9 and 10 in [S083].
- Printed: 100 mm [S021, S023]; 127 mm (5 in) [S022, S026, S103]; 120 mm and 160 mm [S050]; 134 mm [S064] (weak); 150 mm example [S100, S104 comment]; 60 mm default [S101, S104]; 70 mm [S024] (weak); 180 mm overall with handle [S060, S061 (weak)].
- Longest hand roller: 16 in (40.6 cm) wooden dowel for large platters; length flexible with slab size [S049, S069, S088].
- Printer limit for generator: length up to 320 mm [S100]. Project max is 254 mm (10 in) per CLAUDE.md; no source tests a 254 mm printed roller.
- Sources disagree on handle-roller scale: handle-roller faces are short (30 mm to 61 mm) [S044, S046, S047] while hand/dowel rollers run 100-406 mm [S043, S045, S049].

## Wall thickness (hollow rollers)
- 3 mm Solidify wall is "more than strong enough" for rolling on clay [S021].
- 2 mm then 2.5 mm wall chosen in Blender [S024] (weak).
- Instructables sleeve: 0.75 mm extruded wall on a 15 mm rod [S103]; sheet-metal wall 2.5 mm in a 40 mm OD roller [S104].
- Generator default wall 5 mm (-t) [S102].
- Commenters want thinner walls to cut print time (8 h on an A1 Mini for one 60x180 roller) [S060] (weak).
- Pendant example 1.6 mm wall (not a roller) [S027].
- Conflict: 0.75 mm [S103] vs 3 mm [S021] vs 5 mm [S102]; none measured under load.

## Circumference and repeat
- One revolution imprints pi x diameter: 94 mm at 30 mm dia [S101]; 125.66 mm at 40 mm OD [S104].
- The pattern width must equal pi x diameter or the join shows [S104]; flattened pattern sizes seen: 148.089 mm x 127 mm [S103].
- Pattern repeat on a clay-coil roller: a little over 3 times the roller diameter [S083].
- Pattern wraps end-to-end with no visible join on a printed roller [S050]; the same claim appears in [S063] (weak).
- Rims/end bands: 2-4 mm recommended so depth stays even across the slab [S101]; plain end bands offered [S100]; bevelled edges keep roller sides from marking the clay [S043, S047].
- Same roller works on small or large slabs at the same design scale [S049].
- Scale in the slicer, not Blender, when Blender unit scale is 1 [S025] (weak).
- Radius-from-image width formula: radius = width/(8 x pi x ppi) - 0.039 x depth (inches) [S102].

## Open questions
- What diameter/length maximizes roll-out of a 254 mm (10 in) tall image without wobble or print failure?
- What minimum diameter keeps a motif undistorted (circumference vs repeat length)?
- Minimum wall that survives rolling pressure for a 254 mm hollow roller, by material?
- Is a taller image usually rolled along the axis or around the circumference by potters?
- Do bevelled edges need a specific angle or width?
