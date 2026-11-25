# S021: 0.4mm vs 0.2mm Texture Roller Test - Which Gives Better Wargaming Detail? (Designed In Layers)
- URL: https://www.youtube.com/watch?v=82vhj7quUB4
- Date read: 2026-11-24
- Type: youtube
- Trust (1-5): 4
## Key claims
- Roller is a plain cylinder exported from Bambu Studio as STL, then textured in Bump Mesh (free browser tool). Texture settings: texture height, "inverted" ON so the relief cuts into the roller, top and bottom faces OFF so only the sides carry texture; scale adjusted.
- Print: Bambu Lab A1, PLA Basic, 0.2 mm layers with adaptive layers, about 2 h for the roller. Also printed with 0.4 nozzle and 0.2 nozzle to compare; 0.2 gives finer cracks but both usable at normal distance. Layer lines visible up close on 0.4.
- Blender setup: units mm, unit scale 0.001, grid scale 0.001. Cylinder 100 mm long x 25 mm diameter, 64 vertices, cap fill none (hollow tube).
- Hollow wall: Solidify modifier 3 mm thick ("more than strong enough for rolling on clay"). Apply solidify first.
- 20 loop cuts; vertex group on side verts only (not top/bottom); Subdivision Surface level 6; Displace modifier set to UV coordinates, strength -1 (pushes inward), texture sampling 4 to soften hard B/W edges.
- Trim top and bottom flat with box trim in sculpt mode, then export STL.
- Image prep in Affinity (free): inpainting brush to remove tile seams, Gaussian blur, high-pass, black/white, levels.
- Test medium: air-dry clay from hobby shop; masking putty for cheap previews.
## Quotes (each under 15 words, max 3)
- "make sure you've got inverted selected" (no timestamp captured)
- "that's what we'll use to control the texture layer" (no timestamp captured)
