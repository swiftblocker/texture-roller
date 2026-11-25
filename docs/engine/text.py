"""Lettering on the roller: open source fonts (SIL OFL, app/engine/data/fonts/) set as relief.

Text is placed in clay view (what the slab shows: x around the circumference, z along the roller,
z up), on the same oversampled grid as the art, after the art is tiled and the seam chosen. It
always reads the right way round in the clay, whatever the mirror setting.

Layouts
    single   one block of text, repeated text_count times around (count = repeats around puts one
             over every tile; text_x is the place inside each share, 50 = centred on the tile)
    band     the words repeat all the way round in a ribbon, with a separator, spaced so the ring
             closes exactly at the seam
    allover  bands stacked over the whole length, every other row shifted half a step

Relief: pressed = letters pressed into the clay (like the art), raised = letters stand up and the
frame around them is pressed. Frame: none, halo (clears the art in a margin that follows the
letters), pill (clears a rounded box), ring (pill with a border line).
Glyph fill uses the nonzero rule (sum of signed contours), so overlapping contours stay solid.
"""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np

FONT_DIR = Path(__file__).resolve().parent / "data" / "fonts"
# min_mm: smallest letter height where "Hope Love 2026" clears R19-R21, R26, R74, R79 at
# 1.5 mm depth, 15 deg draft, 8% spacing, 0.2 mm grid (app.js FONTS repeats these)
FONTS = [
    {"id": "pacifico", "min_mm": 12, "name": "Pacifico", "vibe": "retro surf script"},
    {"id": "shrikhand", "min_mm": 16, "name": "Shrikhand", "vibe": "groovy 70s"},
    {"id": "cherrybomb", "min_mm": 12, "name": "Cherry Bomb One", "vibe": "bubble letters"},
    {"id": "fraunces", "min_mm": 12, "name": "Fraunces", "vibe": "soft wonky serif"},
    {"id": "bebas", "min_mm": 11, "name": "Bebas Neue", "vibe": "tall caps"},
    {"id": "nunito", "min_mm": 11, "name": "Nunito Black", "vibe": "rounded sans"},
    {"id": "caveat", "min_mm": 11, "name": "Caveat Bold", "vibe": "handwritten"},
    {"id": "dancing", "min_mm": 28, "name": "Dancing Script", "vibe": "wedding script"},
    {"id": "lilita", "min_mm": 9, "name": "Lilita One", "vibe": "chunky friendly"},
]
FONT_IDS = [f["id"] for f in FONTS]
SEPS = ["none", "dot", "star", "heart", "diamond", "flower", "wave"]
MAX_CHARS = 60
MAX_LINES = 3
LINE_PITCH = 1.55     # baseline to baseline, in cap heights
SEP_SIZE = 0.42       # separator height, in cap heights
MIN_STROKE = 1.0      # R19a raised feature / R21 gap, mm


class TextError(ValueError):
    pass


# ---------------- fonts --------------------------------------------------------------
_FONT = {}


class _Font:
    def __init__(self, fid):
        from fontTools.ttLib import TTFont
        p = FONT_DIR / (fid + ".ttf")
        if not p.is_file():
            raise TextError("font %r is not installed" % fid)
        self.tt = TTFont(str(p), lazy=False)
        self.gs = self.tt.getGlyphSet()
        self.cmap = self.tt.getBestCmap()
        self.hmtx = self.tt["hmtx"].metrics
        cap = getattr(self.tt["OS/2"], "sCapHeight", 0) or 0
        if cap <= 0:
            g = self.cmap.get(ord("H"))
            cs = self._contours(g) if g else []
            cap = max((c[:, 1].max() for c in cs), default=0) or 0.7 * self.tt["head"].unitsPerEm
        self.cap = float(cap)
        self._g = {}
        self._kern1, self._kern2 = self._read_kern()
        self._kc = {}

    def _contours(self, gname):
        from fontTools.pens.basePen import BasePen
        out = []

        class Pen(BasePen):
            def __init__(s):
                super().__init__(self.gs)
                s.cur = None

            def _moveTo(s, p):
                s.cur = [p]

            def _lineTo(s, p):
                s.cur.append(p)

            def _curveToOne(s, p1, p2, p3):
                p0 = np.array(s.cur[-1], float)
                c = np.array([p0, p1, p2, p3], float)
                L = np.linalg.norm(np.diff(c, axis=0), axis=1).sum()
                n = int(min(24, max(3, math.ceil(L / 25.0))))
                t = np.linspace(0, 1, n + 1)[1:, None]
                q = (1 - t) ** 3 * c[0] + 3 * (1 - t) ** 2 * t * c[1] + 3 * (1 - t) * t * t * c[2] + t ** 3 * c[3]
                s.cur.extend(map(tuple, q))

            def _closePath(s):
                if s.cur and len(s.cur) > 2:
                    out.append(np.array(s.cur, float))
                s.cur = None

            _endPath = _closePath

        self.gs[gname].draw(Pen())
        return out

    def glyph(self, gname):
        if gname not in self._g:
            self._g[gname] = [c / self.cap for c in self._contours(gname)]
        return self._g[gname]

    def adv(self, gname):
        return self.hmtx[gname][0] / self.cap

    def _read_kern(self):
        pairs, classes = {}, []
        if "GPOS" in self.tt:
            g = self.tt["GPOS"].table
            idx = set()
            if g.FeatureList:
                for fr in g.FeatureList.FeatureRecord:
                    if fr.FeatureTag == "kern":
                        idx.update(fr.Feature.LookupListIndex)
            for i in sorted(idx):
                lk = g.LookupList.Lookup[i]
                for st in lk.SubTable:
                    if lk.LookupType == 9:
                        if st.ExtensionLookupType != 2:
                            continue
                        st = st.ExtSubTable
                    elif lk.LookupType != 2:
                        continue
                    if st.Format == 1:
                        for first, ps in zip(st.Coverage.glyphs, st.PairSet):
                            for r in ps.PairValueRecord:
                                v = getattr(r.Value1, "XAdvance", 0) or 0 if r.Value1 is not None else 0
                                pairs.setdefault((first, r.SecondGlyph), v)
                    elif st.Format == 2:
                        classes.append((set(st.Coverage.glyphs), st.ClassDef1.classDefs, st.ClassDef2.classDefs, st.Class1Record))
        if "kern" in self.tt:
            for kt in getattr(self.tt["kern"], "kernTables", []):
                for k, v in getattr(kt, "kernTable", {}).items():
                    pairs.setdefault(k, v)
        return pairs, classes

    def kern(self, a, b):
        k = (a, b)
        if k in self._kc:
            return self._kc[k]
        v = self._kern1.get(k)
        if v is None:
            v = 0
            for cov, c1, c2, rec in self._kern2:
                if a in cov:
                    val = rec[c1.get(a, 0)].Class2Record[c2.get(b, 0)].Value1
                    v = (getattr(val, "XAdvance", 0) or 0) if val is not None else 0
                    break
        self._kc[k] = v / self.cap
        return self._kc[k]


def font(fid):
    if fid not in FONT_IDS:
        raise TextError("unknown font %r" % fid)
    if fid not in _FONT:
        _FONT[fid] = _Font(fid)
    return _FONT[fid]


def fonts() -> list:
    return [dict(f) for f in FONTS]


# ---------------- shapes (cap-height units, y up) -----------------------------------
def _sep(kind):
    """Separator contours centred on (0, 0.5) in cap units, and its width."""
    s = SEP_SIZE
    t = np.linspace(0, 2 * np.pi, 73)[:-1]
    if kind == "dot":
        c = [np.stack([0.32 * s * np.cos(t), 0.32 * s * np.sin(t)], 1)]
    elif kind == "star":
        a = np.arange(10) * np.pi / 5 + np.pi / 2
        r = np.where(np.arange(10) % 2 == 0, 0.62 * s, 0.27 * s)
        c = [np.stack([r * np.cos(a), r * np.sin(a)], 1)]
    elif kind == "heart":
        x = 16 * np.sin(t) ** 3
        y = 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)
        c = [np.stack([x, y + 1.5], 1) * (0.55 * s / 16)]
    elif kind == "diamond":
        c = [np.array([[0, 0.6], [0.38, 0], [0, -0.6], [-0.38, 0]]) * s]
    elif kind == "flower":
        r = 0.55 * s * (0.62 + 0.38 * np.cos(5 * t))
        c = [np.stack([r * np.cos(t + np.pi / 2), r * np.sin(t + np.pi / 2)], 1)]
    elif kind == "wave":
        x = np.linspace(-0.9, 0.9, 60) * s
        y = 0.16 * s * np.sin(x / s * 2 * np.pi / 0.9)
        h = 0.11 * s
        c = [np.vstack([np.stack([x, y + h], 1), np.stack([x[::-1], y[::-1] - h], 1)])]
    else:
        return [], 0.0
    c = [p + np.array([0.0, 0.5]) for p in c]
    w = max(p[:, 0].max() for p in c) - min(p[:, 0].min() for p in c)
    return c, float(w)


def _set_lines(f, text, track):
    """-> contours (cap units) of the text block, each line centred on x=0, first baseline y=0;
    the advance width of the widest line; missing characters."""
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n")]
    lines = [ln for ln in lines if ln][:MAX_LINES]
    out, missing, width = [], set(), 0.0
    space = f.cmap.get(32)
    for li, ln in enumerate(lines):
        x, prev, row = 0.0, None, []
        for ch in ln:
            g = f.cmap.get(ord(ch))
            if g is None:
                missing.add(ch)
                g = space
                if g is None:
                    continue
            if prev is not None:
                x += f.kern(prev, g)
            for c in f.glyph(g):
                row.append(c + np.array([x, 0.0]))
            x += f.adv(g) + track
            prev = g
        w = x - track if prev is not None else 0.0
        width = max(width, w)
        y = -li * LINE_PITCH
        out.extend(c + np.array([-w / 2, y]) for c in row)
    return out, width, len(lines), sorted(missing)


def _pill(x0, y0, x1, y1, n=48):
    h = y1 - y0
    r = h / 2
    cx0, cx1, cy = x0 + r, max(x0 + r, x1 - r), (y0 + y1) / 2
    a = np.linspace(-np.pi / 2, np.pi / 2, n)
    right = np.stack([cx1 + r * np.cos(a), cy + r * np.sin(a)], 1)
    left = np.stack([cx0 - r * np.cos(a), cy - r * np.sin(a)], 1)
    return np.vstack([right, left])


def _subdivide(c, step):
    d = np.roll(c, -1, axis=0) - c
    L = np.hypot(d[:, 0], d[:, 1])
    n = np.maximum(1, np.ceil(L / step).astype(int))
    out = [c[i] + d[i] * (np.arange(n[i])[:, None] / n[i]) for i in range(len(c))]
    return np.vstack(out)


def _area(c):
    x, y = c[:, 0], c[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


# ---------------- raster -------------------------------------------------------------
def _raster(contours, x0, y0, nx, ny, dx, dz):
    """Nonzero fill: each contour adds +1 or -1 by its orientation."""
    from skimage.draw import polygon
    acc = np.zeros((ny, nx), np.int16)
    for c in contours:
        if len(c) < 3:
            continue
        sgn = 1 if _area(c) > 0 else -1
        rr, cc = polygon((c[:, 1] - y0) / dz, (c[:, 0] - x0) / dx, shape=(ny, nx))
        if len(rr):
            acc[rr, cc] += sgn
    return acc != 0


def _edt(mask, dz, dx):
    from scipy.ndimage import distance_transform_edt
    return distance_transform_edt(mask, sampling=(dz, dx))


# ---------------- main ---------------------------------------------------------------
def _unit(P, f, size, dx, dz, pitch=None, max_w=None, max_h=None):
    """Build one stamp. Returns dict(ink, region, x0, y0, w, h, ...) in mm, origin = stamp centre."""
    track = P.text_track / 100.0
    cs, adv_w, nlines, missing = _set_lines(f, P.text, track)
    if not cs:
        return None
    pts = np.vstack(cs)
    bx0, by0 = pts.min(0)
    bx1, by1 = pts.max(0)
    seps = []
    if pitch is not None and P.text_sep != "none":
        sc, _ = _sep(P.text_sep)
        yc = (by0 + by1) / 2 - 0.5     # separator centred on the block's middle
        for c in sc:
            seps.append(c + np.array([pitch / size / 2, yc]))
    contours = [c * size for c in cs + seps]
    bx0, by0, bx1, by1 = bx0 * size, by0 * size, bx1 * size, by1 * size
    frame = P.text_frame
    pad = margin(P)
    if frame in ("pill", "ring"):
        pad = max(pad, 0.35 * size)
        fr = [_pill(bx0 - pad, by0 - pad, bx1 + pad, by1 + pad)]
    else:
        fr = []
    # centre on the ink box
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    if pitch is not None:
        cx = 0.0   # band: the word stays centred on x=0 so the separator sits half a step away
    contours = [c - [cx, cy] for c in contours]
    fr = [c - [cx, cy] for c in fr]
    W = bx1 - bx0
    if (max_w and W > max_w) or (max_h and (by1 - by0) > max_h):
        return {"too_big": True, "w": float(W), "h": float(by1 - by0)}
    warp = pitch is None and abs(P.text_arch) >= 1.0
    wave = abs(P.text_wave) > 0.0
    if warp or wave:
        step = max(0.2, min(dx, dz))
        contours = [_subdivide(c, step) for c in contours]
        fr = [_subdivide(c, step) for c in fr]
        lam = pitch if pitch is not None else max(W, 1e-6)
        A = P.text_wave / 100.0 * size
        Rr = W / math.radians(P.text_arch) if warp else None

        def tf(c):
            u, v = c[:, 0], c[:, 1]
            if wave:
                v = v + A * np.sin(2 * np.pi * u / lam)
            if warp:
                th = u / Rr
                r = Rr + v
                u, v = r * np.sin(th), r * np.cos(th) - Rr
            return np.stack([u, v], 1)
        contours = [tf(c) for c in contours]
        fr = [tf(c) for c in fr]
        if pitch is None:
            allp = np.vstack(contours + fr)
            m = (allp.min(0) + allp.max(0)) / 2
            contours = [c - m for c in contours]
            fr = [c - m for c in fr]
    ang = 0.0 if pitch is not None else P.text_angle
    if ang:
        a = math.radians(ang)
        R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        contours = [c @ R.T for c in contours]
        fr = [c @ R.T for c in fr]
    if not P.mirror:
        # the clay shows the drawn layer flipped; flip the letters so they still read
        contours = [c * [-1, 1] for c in contours]
        fr = [c * [-1, 1] for c in fr]
    allp = np.vstack(contours + fr)
    halo = margin(P) if frame == "halo" else 0.0
    marg = halo + 2 * max(dx, dz)
    x0, y0 = allp.min(0) - marg
    x1, y1 = allp.max(0) + marg
    nx, ny = int(math.ceil((x1 - x0) / dx)) + 1, int(math.ceil((y1 - y0) / dz)) + 1
    raw = _raster(contours, x0, y0, nx, ny, dx, dz)
    letters = _clay_safe(raw, P, dz, dx)
    kept = float(letters.sum()) / max(1.0, float(raw.sum()))
    ink = letters
    if P.text_style == "outline":
        # raised letters are grooves on the roller, so their lines need groove width (R20)
        wline = max(min_groove(P) if P.text_relief == "raised" else min_feature(P) + 0.1, 0.09 * size)
        ink = letters & (_edt(letters, dz, dx) <= wline)
    if frame == "halo":
        from scipy.ndimage import binary_fill_holes
        # the inside of o, e, a is cleared too, so no scrap of the art sits in a counter
        region = binary_fill_holes(letters) | (_edt(~letters, dz, dx) <= halo)
    elif frame in ("pill", "ring"):
        region = _raster(fr, x0, y0, nx, ny, dx, dz)
        if frame == "ring":
            # border line; the pill pad (>= 0.35 x size) keeps it clear of the letters
            wr = max(min_groove(P) if P.text_relief == "raised" else min_feature(P) + 0.1, 0.08 * size)
            ink = ink | (region & (_edt(region, dz, dx) <= wr))
    else:
        region = letters
    return {"ink": ink, "region": region, "x0": float(x0), "y0": float(y0), "nx": nx, "ny": ny,
            "w": float(allp[:, 0].max() - allp[:, 0].min()), "h": float(allp[:, 1].max() - allp[:, 1].min()),
            "adv_w": adv_w * size, "lines": nlines, "missing": missing, "raw": raw, "kept": kept}


def clay_gap(P):
    """Narrowest gap the letters keep: the groove limit (R20, R21) plus a quarter mm for the grid."""
    return max(MIN_STROKE, 0.8 * P.depth) + 0.25


def min_feature(P):
    """Narrowest feature kept, measured on the drawing: 1 mm (R19a) at three quarters of the
    relief height, where the draft has already narrowed a raised line by 2 x 0.25 d tan(draft)."""
    return MIN_STROKE + 0.5 * P.depth * math.tan(math.radians(P.draft_deg)) + 0.05


def min_groove(P):
    """Narrowest groove kept, on the drawing: the R20 limit at the bottom quarter of the relief,
    where the draft has widened the raised parts on both sides by 0.75 d tan(draft) each."""
    return max(MIN_STROKE, 0.8 * P.depth) + 1.5 * P.depth * math.tan(math.radians(P.draft_deg)) + 0.1


def margin(P):
    """The clear margin round the letters, never narrower than a groove clay can fill (R20)."""
    return max(P.text_halo, min_groove(P))


def _clay_safe(m, P, dz, dx):
    """Drop slivers thinner than 0.9 mm (R19b: they will not print). Letter shapes are not
    otherwise changed; tight gaps are reported (R20, R21) so the potter can add spacing."""
    if not m.any():
        return m
    r = min_feature(P) / 2
    core = _edt(m, dz, dx) > r
    out = m & (_edt(~core, dz, dx) <= r + 0.5 * max(dz, dx))
    # the trim can leave a stub of a thin stroke (a t crossbar) standing alone: drop stubs
    # under 2.5 mm2 that were part of something bigger before the trim
    from scipy.ndimage import label
    lab, n = label(out)
    if n:
        area = np.bincount(lab.ravel()) * dx * dz
        lab0, _ = label(m)
        area0 = np.bincount(lab0.ravel()) * dx * dz
        small = (area < 2.5)
        small[0] = False
        stub = small[lab] & (area0[lab0] > area[lab] * 1.5)
        out &= ~stub
    return out


def _stroke(ink, dz, dx):
    """10th percentile stroke width (mm) along the skeleton, or None."""
    from skimage.morphology import skeletonize
    if not ink.any():
        return None
    d = _edt(ink, dz, dx)
    sk = skeletonize(ink)
    v = 2 * d[sk]
    v = v[v > 0]
    if not len(v):
        return None
    return float(np.percentile(v, 10))


def _wrap_edt(mask, dz, dx, pad_mm=4.0):
    """EDT on the roller grid: columns wrap round the circumference."""
    k = min(mask.shape[1], int(math.ceil(pad_mm / dx)) + 1)
    big = np.concatenate([mask[:, -k:], mask, mask[:, :k]], axis=1)
    return _edt(big, dz, dx)[:, k:-k]


def _wrap_sizes(m):
    """Pixel count of the connected piece each True pixel belongs to; pieces that cross the
    seam (column 0 / last column) count as one."""
    from scipy.ndimage import label
    N2 = m.shape[1]
    lab, n = label(np.concatenate([m, m], axis=1))
    cnt = np.bincount(lab.ravel())
    cnt[0] = 0
    return np.maximum(cnt[lab[:, :N2]], cnt[lab[:, N2:]])


def _stamp(dst, m, col0, row0):
    """OR m into dst at (row0, col0), wrapping columns, clipping rows."""
    M2, N2 = dst.shape
    ny, nx = m.shape
    r = row0 + np.arange(ny)
    ok = (r >= 0) & (r < M2)
    if not ok.any():
        return
    mm = m[ok]
    cols = (col0 + np.arange(nx)) % N2
    if nx <= N2:
        dst[np.ix_(r[ok], cols)] |= mm
    else:
        acc = np.zeros((mm.shape[0], N2), np.int32)
        np.add.at(acc.T, cols, mm.T.astype(np.int32))
        dst[r[ok]] |= acc > 0


def apply(P, top, C, L, band_rows, phase, cell_w):
    """Composite the text into `top` (M2, N2 bool, clay view, row 0 = z 0). -> (top, mask, report)."""
    M2, N2 = top.shape
    dx, dz = C / N2, L / (M2 - 1)
    txt = ("" if P.text is None else str(P.text)).strip()
    nl = len([ln for ln in txt.replace("\r", "").split("\n") if ln.strip()])
    rep = {"warnings": []}
    if len(txt) > MAX_CHARS:
        txt = txt[:MAX_CHARS]
        rep["warnings"].append("Text cut to %d characters." % MAX_CHARS)
        rep["chars_cut"] = MAX_CHARS
    if nl > MAX_LINES:
        rep["warnings"].append("Only the first %d lines are used." % MAX_LINES)
        rep["lines_cut"] = nl
    P = P.replace(text=txt) if txt != P.text else P
    f = font(P.text_font)
    size = float(P.text_size)
    layout = P.text_layout
    band = P.band_eff
    if layout == "single":
        u = _unit(P, f, size, dx, dz, max_w=1.5 * C, max_h=L)
        if u is None:
            return top, None, None
        k = max(1, int(round(P.text_count)))
        share = C / k
        xs = [phase + (j + P.text_x / 100.0) * share for j in range(k)]
        zs = [P.text_y / 100.0 * L]
        rows = [(z, xs) for z in zs]
        if u["w"] > share + 1e-6 and k > 1:
            rep["overlap"] = True
            rep["fit_size_mm"] = round(size * 0.92 * share / u["w"], 1)
        if u["w"] > C:
            rep["overlap"] = True
    else:
        _, adv0, _, _ = _set_lines(f, P.text, P.text_track / 100.0)
        word = adv0 * size
        _, sw = _sep(P.text_sep)
        sw *= size
        gap = max(P.text_gap, 0.0)
        need = word + (2 * gap + sw if P.text_sep != "none" else gap)
        k = max(1, int(C // max(need, 1e-6)))
        pitch = C / k
        rep["repeats"] = k
        rep["pitch_mm"] = round(pitch, 2)
        if need > C:
            rep["overlap"] = True
        u = _unit(P, f, size, dx, dz, pitch=pitch, max_w=1.5 * C, max_h=L)
        if u is None:
            return top, None, None
        xs = [phase + P.text_x / 100.0 * pitch + j * pitch for j in range(k)]
        if layout == "band":
            rows = [(P.text_y / 100.0 * L, xs)]
        else:
            rp = u["h"] + max(P.text_row_gap, 0.0)
            avail = L - 2 * band
            nr = max(1, int((avail - u["h"]) // rp) + 1)
            z0 = band + (avail - (nr - 1) * rp) / 2
            rows = []
            for i in range(nr):
                sh = (pitch / 2) if i % 2 else 0.0
                rows.append((z0 + i * rp, [x + sh for x in xs]))
            rep["rows"] = nr
    if u.get("too_big"):
        rep.update({"too_big": True, "overlap": True, "width_mm": round(u["w"], 1), "height_mm": round(u["h"], 1),
                    "font": P.text_font, "size_mm": size, "layout": layout})
        return top, None, rep
    ink = np.zeros_like(top)
    region = np.zeros_like(top)
    clipped = False
    for z, xr in rows:
        row0 = int(round((z + u["y0"]) / dz))
        if (z - u["h"] / 2) < band - 1e-6 or (z + u["h"] / 2) > L - band + 1e-6:
            clipped = True
        for x in xr:
            col0 = int(round((x + u["x0"]) / dx))
            _stamp(region, u["region"], col0, row0)
            _stamp(ink, u["ink"], col0, row0)
    raised = P.text_relief == "raised"
    letter_val = not raised
    out = top.copy()
    out[region] = not letter_val
    out[ink] = letter_val
    # Where the frame cuts the art it leaves tapering slivers (half a wave, a leaf tip) that
    # will not print (R19b) or fill with clay (R20). Remove art features under 1 mm within
    # 2 mm of the frame; the letters themselves are left alone.
    near = _wrap_edt(~(region | ink), dz, dx) <= 2.0
    # never touch letter counters (the inside of o, e, a): they are the letters' own shape
    from scipy.ndimage import binary_fill_holes
    keep_out = region | binary_fill_holes(ink)   # letters, their frame, their own counters
    near &= ~keep_out
    if near.any():
        for val in (False, True):   # raised last, so filling a pocket never leaves a crumb
            m = out == val
            rr = (min_feature(P) if val else min_groove(P)) / 2
            core = _wrap_edt(m, dz, dx) > rr
            kept = _wrap_edt(~core, dz, dx) <= rr + 0.5 * max(dz, dx)
            out[near & m & ~kept] = not val
        # crumbs: whole art pieces under 4 mm2 next to the text (thick enough to pass the
        # sliver test, too small to survive the draft)
        near6 = (_wrap_edt(~(region | ink), dz, dx, pad_mm=8.0) <= 6.0) & ~keep_out
        for val in (False, True):   # raised last, so filling a pocket never leaves a crumb
            sz = _wrap_sizes(out == val)
            out[near6 & (out == val) & (sz * dx * dz < 4.0)] = not val
    out[band_rows, :] = True
    mask = (region | ink) & ~band_rows[:, None]
    # how much the letters differ from what surrounds them (a raised word with no frame on an
    # untouched background is invisible)
    from scipy.ndimage import binary_dilation
    ring = binary_dilation(ink, iterations=2) & ~ink & ~band_rows[:, None]
    vis = float(np.mean(out[ring] != letter_val)) if ring.any() else 1.0
    sw_ = _stroke(u["raw"], dz, dx)
    rep.update({
        "font": P.text_font, "size_mm": size, "layout": layout, "lines": u["lines"],
        "width_mm": round(u["w"], 1), "height_mm": round(u["h"], 1),
        "stroke_mm": None if sw_ is None else round(sw_, 2),
        "missing": u["missing"], "clipped": clipped, "contrast": round(vis, 2),
        "relief": P.text_relief, "kept": round(u["kept"], 2), "margin_mm": round(margin(P), 2),
    })
    lim = min_feature(P) if not raised else min_groove(P)
    rep["stroke_limit_mm"] = round(lim, 2)
    if sw_ is not None and sw_ < lim:
        rep["min_size_mm"] = round(size * lim / sw_ + 0.05, 1)
    return out, mask, rep
