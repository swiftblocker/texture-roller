# S025: Create a Texture Roller in Blender. (Tutorial) (EmperorGuam)
- URL: https://www.youtube.com/watch?v=aLg3Uuq---M
- Date read: 2026-11-24
- Type: youtube
- Trust (1-5): 2
## Key claims
- Starts from a plane (UVs already set), not a cylinder, because cylinder end caps complicate UVs.
- Plane subdivided twice to 10 cuts each. Simple Deform bent to a full 360 degrees (set to -360 so the curve closes on the correct side), origin set to an empty rotated 90 degrees on X.
- Apply the bend, then bridge and merge edge loops at the centre to close the ends; "merge by distance" removes 128 unconnected vertices.
- UV seam: move the end-cap UVs off the texture area so the image does not show on them.
- Displace modifier: mid-level set to 1 (not 0.5), coordinates UV, strength about -0.07 (negative = mortar low, brick high).
- Texture must tile seamlessly or a visible seam appears.
- Subdivision Surface added after displace. Blender unit scale 1 makes the object tiny; scale in slicer (example x10) rather than in Blender.
- Recalculate outside normals before export; if the slicer (Lychee, resin) shows the part red, fix normals in Blender.
- Printer type implied resin (Lychee slicer). No layer height or clay test shown.
## Quotes (each under 15 words, max 3)
- "the white is high the black is low" (no timestamp captured)
- "recalculate outside and it should ... be blue" (no timestamp captured)
