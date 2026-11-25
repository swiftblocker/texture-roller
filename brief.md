# Brief: parametric clay texture roller (functional-cad step 1)

Units: mm and degrees. Inches are converted once here: 10 in = 254.0 mm, 1/2 in = 12.70 mm, 3/4 in = 19.05 mm.

## Function
A cylinder with relief art. It is rolled once across a clay slab and leaves the art as a continuous impression.

## Loads
- Hand rolling pressure: UNVERIFIED, estimated 20-50 N spread along the body. No FEA (the owner's rule). Stiffness is handled by geometry rules R05 (L/D <= 8 without an axle) and R09 (minimum wall).

## Interfaces
| Interface | Value | Tolerance | Status |
|---|---|---|---|
| Hardwood dowel, 1/2 in | 12.70 nominal | store dowels often run 12.3-12.9 | UNVERIFIED; bore = measured dowel + 0.3 mm slip fit (R56) |
| Hardwood dowel, 3/4 in | 19.05 nominal | as above | UNVERIFIED |
| Steel rod, 8 mm | 8.00 | h9 typical | UNVERIFIED |
| Clay slab | 6-12 mm thick | - | from S082, S085 |

## Envelope
- Body length L <= 254.0 (R01). X1C build volume 256 x 256 x 256. Printed upright: L <= 250 is recommended (R02).
- Diameter D (top of relief) 16-100, preset 25-60 (R04).

## Material and process
- FDM on a Bambu X1C, 0.4 mm nozzle, PLA or PETG, printed upright, no supports (R51-R55).
- Gate limits: minimum wall 1.6 mm hard / 2-3 mm target (R09); minimum printed feature 0.8 mm (R19); overhangs only at the end chamfers, 45 deg or less (R53).

## Tolerances that matter
- Wrap width = pi x D within 0.05 mm (R08). Seam step under 0.05 mm (R38). Exported bounding box within 0.05 mm of the parameters (R68).

## Default part (preset "10 in image")
D 45.0, L 250.0, relief 1.5, draft 15 deg, edge round 0.4, end band 3.0, end chamfer 1.0, bore 13.0 (1/2 in dowel + 0.3). C = 141.37 mm.

## User and use
- User: a potter, possibly a first-time roller user, at a wedging table.
- First-time action: dust the roller with cornstarch, set it on the slab, roll once with even pressure.
- Likely wrong actions: (1) text comes out backwards because the art was not mirrored (prevented: mirror default ON, the slab preview shows the clay side); (2) the clay is too dry or too wet, or the roller is pressed harder at one end (informed: clay-state preset and the instructions on the export sheet); (3) the dowel will not fit (prevented: the bore is a measured-dowel parameter, and the test strip checks the fit first).
