# Lettering red-team round 1 (scratch: app/out/text/*.py)

Harness: api.preview({'art_source':'pattern:waves', ...}). Default text_font pacifico.

## Findings

1. MAJOR - Preview can take 14.5 s (limit 1.5 s). Params: text='W'*60, text_layout='band', text_size=120, diameter=150 (art waves).
   Observed 14.47 s, R75+R76 fire. Expected under 1.5 s or an early clamp. Also text='Hope\nLove\nJoy', text_size=120 single: 1.69 s.
   Cost grows with text area x circumference; size 120 + big diameter has no cap or fast path.
2. MINOR - 4+ lines silently truncated to 3 (MAX_LINES) with no rule and no art_report warning. Params: text='A\nB\nC\nD\nE', text_size=8.
   Observed lines=3, warnings=[], no R7x. Expected a warning like the 60-char cut ("Text cut to 60 characters." exists, lines has none).
3. MINOR - text=None (API) draws text. Params: text=None. Observed output differs from text='' and art_report['text'] exists (width 36.5 mm at 12 mm),
   i.e. it is rendered as the string "None" while r['params']['text'] still echoes None. Expected: no text. (text=123 renders "123"; fine.)
4. MINOR - Unknown param names are silently ignored, e.g. length_mm=30 (real name is length). text_layout='allover' length_mm=30 ran at full 244 mm.
   Not text-specific but bites the allover-short-roller case; the real `length=30` case works (rows=1, 61 clay rows, no crash).
5. MINOR - Seam-blend eats a few text pixels. Params: art plain, text='RAG', text_size=20, text_frame='none', seam_method='blend', text_x=50, mirror False:
   3606 text px vs 3646 with gutter (-1.1%); mirror True 3595 vs 3638. Expected identical (text_os should skip blend). Cosmetic, tiny.
6. MINOR - Mirror True vs False text masks differ by about 12 px in band mode (d=45 'RAG' 4208 vs 4196). Reading direction is correct for both; this is a rounding asymmetry only.

## Checked and OK (tried to break, could not)

- Reading direction: 'RAG' 20 mm, clay PNG, mirror True and False: upright, left to right, both. (app/out/text/rag_m1.png, rag_m0.png)
- No exception for: empty, whitespace, only newlines, 60+ chars (cut + R76), emoji and CJK (R78), tab (R78), size 500 (clamped, R75/R76) and 0.1 (R74/R79),
  count 24, arch +-300, wave 60, angle 180/-90, track -20, halo 0/10, band wider than circumference (d=10, R76/R70), bands_on False, invert, blend, gutter, tile, auto,
  offset brick, n_around 1 and 6, diameter 10 and 150, text_x 0/100, text_y 0/100 (R75).
- Exceptions that are deliberate and clean: text_font='zzz' -> TextError "unknown font"; text_size=NaN -> ParamError.
- All 96 combos of frame(4) x relief(2) x style(2) x layout(3) x mirror(2) with 'Hope & Love' 14 mm: no crash, max 0.23 s.
- Determinism: identical clay bytes on repeat run (band, blend, 2 lines).
- Band closure: for 10 combos (mirror x diameter 10/33/45/150, repeats 1..6, gutter) the text mask rolled by W/repeats mismatches by 0 px. Closes evenly at the seam.
- Text across seam: text_x 0 and 100 draw columns 0 and 281 (wraps), same pixel count as centred (+-10 px).
- End bands: text_y=100 first changed row 6, y=0 last row 494 of 501 (band is 3 mm = ~6 rows). Text never drawn over the end band. R75 fires at y 0/100.
- Silent-vanish check: invert + frame none + plain art -> 0 px changed but R77 fires. Good.
- Perf otherwise: all other cases under 0.8 s (d=150 allover ring/outline/raised 0.68 s).

## Not tested
- export_bytes (slow); relief 3D heightmap seam colouring beyond the clay view.
- 'upload' art source.

## Resolution (main session, 2026-11-25)

1. Fixed: text wider than 1.5 x C or taller than L is not drawn; R76 says so with the size. 'W'*60 band at 120 mm: 14.5 s -> 0.7 s.
2. Fixed: a 4th line raises R78; the 60-character cut raises R78 too.
3. Fixed: text=None is no text (params.py).
4. Rejected: unknown parameter names are ignored engine-wide by design (old saved settings must still load); not lettering.
5. Fixed: the seam blend now skips the letters plus their sloped sides (draft + edge round).
6. Accepted as is: about 12 px of rounding between mirror on and off; reading direction is right for both.

## Round 2 (main session, own probes at export pitch 0.2 mm and in the browser engine)

- MAJOR fixed: 1.5 mm default margin closed to 0.9 mm grooves at the base (R20 on every word). Margin floor = R20 groove + draft.
- MAJOR fixed: margin cut the waves into tapering slivers (R19b BLOCK on "Word band" and "Words all over").
- MAJOR fixed: art scraps left inside letter counters (O, e) as thin slivers.
- MAJOR fixed: the clean-up filled small letter counters solid when there was no frame.
- MAJOR fixed: letters crossing the seam measured as two thin halves (false R19b, R26), relief._widths.
- MAJOR fixed: raised letters and the stamp border are grooves on the roller and now use the groove width.
- MAJOR fixed: service worker served a stale app.js after deploy.
- MINOR fixed: preview grid 0.5 mm reported false R19-R21 on every word.
- Open: the "e" slit in Lilita / Pacifico and the Bebas O counter genuinely close below about 16 mm; R20 says so. Not auto-fixed (would distort the letter).

