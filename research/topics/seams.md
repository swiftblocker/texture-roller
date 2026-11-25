# Seams: wrap seam, tiling, repeat

"(weak)" = only trust 1-2 sources back the claim. Note: two meanings of "seam" here: the pattern wrap seam on the roller, and slab joins in clay.

## Wrap seam on the roller
- The pattern must wrap exactly one revolution: width = pi x diameter (125.66 mm for 40 mm OD) [S104]; one turn prints pi x diameter of imprint (94 mm at 30 mm) [S101].
- A seamless pattern wraps end-to-end with no visible join [S050]; same claim in [S063] (weak).
- The source texture must tile seamlessly or a visible seam appears [S025] (weak); tile seams were removed with an inpainting brush before use [S021].
- Gaussian blur, high-pass, black/white, levels used in image prep [S021].
- Seam in a sheet-metal-style sleeve: 1 mm gap, 0.7 mm join, 0.5 mm strip extrude [S104].
- UV seam: move end-cap UVs off the texture area so the image does not show there [S025] (weak).
- Merging unconnected vertices fixes the bent-plane seam (128 vertices merged) [S025] (weak).
- Inner roughness after displace is cleaned with inner/outer cylinders and a boolean difference [S024] (weak).
- Raised texture at the join is avoided by bridging/merging edge loops [S025] (weak).

## Repeat length
- Clay coil roller repeat is a little over 3 times the roller diameter [S083].
- Rotate the roller or vary start/end points to reduce visible repetition on a slab [S049, S088].
- Roller can border or run along straight and curvy lines (design face 1.2 in) [S046].
- Conflicting scope: S083 gives repeat as a multiple of diameter (about 3.1 x D, consistent with pi x D) while S104 gives exactly pi x D; these agree if "a little over 3" means pi.

## Tiling across rolls
- Rolling adjacent passes: no source gives overlap, alignment marks, or tiling guidance.
- Pattern depth is kept even across a slab with 2-4 mm rims [S101].
- Large slabs can be rolled with the same roller at the same scale [S049].
- A matched positive and negative roller pair exists as a design [S064] (weak).

## Clay slab seams (joins)
- Over-bend slabs over a large-diameter pipe to build flex; score, slip and compress joins with a rib or brayer without damaging texture [S068, S080].
- Slabs open up as they dry [S068, S080].
- Attach slab firmly so it does not shift while a mat is pressed [S081].

## Open questions
- How to align repeat marks for tile-by-tile rolling on slabs longer than one revolution?
- Does a visible seam survive in clay at 2 mm relief, and what blend width hides it?
- Should end caps carry texture? (Sources disagree on whether to texture caps: displace sides only [S021, S027] vs whole shell.)
- What tolerance on pi x D (fractions of a mm) before the seam shows in clay?
