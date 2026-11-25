# S027: How to displace on a Cylinder in Blender (3D Printing Professor)
- URL: https://www.youtube.com/watch?v=HmZ6TyHESMk
- Date read: 2026-11-24
- Type: youtube
- Trust (1-5): 3
## Key claims
- Not a clay roller: jewelry pendant tutorial. Included for the displace-on-cylinder method.
- Cylinder 32 vertices; bore 5 mm diameter; outer tube radius 2.5 + 1.6 mm (1.6 mm wall); 50 mm depth. Bool Tool difference used to cut the bore.
- Displace needs mesh points: add loop cuts (about 60) so the squares are regular; then UV editing to place the texture over the mesh, coordinates switched from Local to UV.
- Subdivision Surface level 2-3 before displace; crease (mean crease 1) on top and bottom edge rings to keep corners sharp.
- Vertex group excludes top and bottom rings; displace applies only to side rings.
- Displace mid-level: lower mid-level makes walls thinner; 0.5 mentioned as the minimum, with wall possibly too thin to print below that.
- Decimate ratio 0.2 to 0.3 placed after subdivision and displace so Boolean operations do not fail. Ratio 0.1 very slow.
- Strength 0.75 on one pattern; 3 on a coral pattern gave too much relief; 5 caused boolean failure.
- Texture UV rotated 180 degrees so the design reads right side up when worn.
- No printer, material, or clay test shown.
## Quotes (each under 15 words, max 3)
- "if it doesn't work for you it's probably because you've got too many points" (no timestamp captured)
- "we want those corners to be sharp" (no timestamp captured)
