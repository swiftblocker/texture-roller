"""Photo of a person -> one-colour pen sketch at the roller's real size (see app/SKETCH_SPEC.md).

Method: marker-line-art skill, from-a-photograph.md. Pyodide-safe: numpy, scipy.ndimage, scikit-image, Pillow.
All sizes are millimetres at OUTPUT size; the raster runs at about 8 px/mm. Every printed line and every
gap is held at 1.0 mm or more (clay floor, skill R19/R21) by an open/close pass at the end.
"""
from __future__ import annotations
import io
import math
import time
from dataclasses import dataclass, field
import numpy as np
from scipy import ndimage as ndi
from PIL import Image, ImageOps, ImageDraw

PPM = 8.0
MAX_PX = 2000
MAX_AREA = 1.7e6     # raster pixels; keeps the sketch inside a few seconds on a phone-class CPU
FLOOR = 1.0          # mm, clay floor for lines and gaps
LW = 1.55            # mm, thinnest line drawn. The roller's draft and edge round eat about 0.65 mm of a raised
                     # line's width at 0.75 of the depth (R19b blocks under 0.8 mm), so lines are drawn 1.5 mm and up
PITCH = 3.7          # mm, hatch pitch (gap = 2.1 mm = 1.4 w, never under 1.0 mm)


@dataclass
class Sketch:
    mask: np.ndarray                 # bool, True = ink (pressed into clay in positive mode)
    report: dict
    crop_rgb: np.ndarray             # uint8 photo crop at output size
    face_box: tuple                  # x, y, w, h in output px
    ppm: float
    layers: dict = field(default_factory=dict)


# ------------------------------------------------------------------ small helpers
def _L_from_rgb(rgb):
    c = rgb.astype(np.float32) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    Y = lin @ np.array([0.2126729, 0.7151522, 0.0721750], np.float32)
    f = np.where(Y > 0.008856, np.cbrt(Y), 7.787 * Y + 16.0 / 116.0)
    return ((116.0 * f - 16.0) / 100.0).astype(np.float32)


def _gauss(a, sigma):
    return ndi.gaussian_filter(a, sigma, mode="nearest")


def _nblur(a, m, sigma):
    """Blur a INSIDE mask m only (normalised convolution)."""
    mf = m.astype(np.float32)
    num = _gauss(a * mf, sigma)
    den = _gauss(mf, sigma)
    return np.where(den > 1e-4, num / np.maximum(den, 1e-4), 0.0).astype(np.float32)


_STRUCT = {}


def _disk_struct(r):
    key = round(float(r), 3)
    if key not in _STRUCT:
        n = int(math.floor(r))
        gy, gx = np.mgrid[-n:n + 1, -n:n + 1]
        _STRUCT[key] = (gx * gx + gy * gy) <= r * r
    return _STRUCT[key]


def _open(m, r):
    """Opening by a disk of radius r px: ink thinner than 2r px vanishes. Same result as the two-EDT form, but run on
    the ink's bounding box, and with a small structuring element when r is small (3x faster)."""
    if not m.any():
        return m
    H, W = m.shape
    ys, xs_ = np.nonzero(m.any(axis=1))[0], np.nonzero(m.any(axis=0))[0]
    pad = int(math.ceil(r)) + 2
    y0, y1 = max(0, ys[0] - pad), min(H, ys[-1] + 1 + pad)
    x0, x1 = max(0, xs_[0] - pad), min(W, xs_[-1] + 1 + pad)
    sub = m[y0:y1, x0:x1]
    if r <= 4.5:
        st = _disk_struct(r)
        e = ndi.binary_erosion(sub, structure=st, border_value=1)
        op = ndi.binary_dilation(e, structure=st) & sub
    else:
        e = ndi.distance_transform_edt(sub) > r
        op = sub & (ndi.distance_transform_edt(~e) <= r)
    out = np.zeros_like(m)
    out[y0:y1, x0:x1] = op
    return out


def _close(m, r):
    """Closing = opening of the paper: gaps narrower than 2r px fill."""
    return ~_open(~m, r)


def _up_f(a, f, h, w):
    if f == 1:
        return a[:h, :w]
    z = ndi.zoom(a, f, order=1)
    if z.shape[0] < h or z.shape[1] < w:
        z = np.pad(z, ((0, max(0, h - z.shape[0])), (0, max(0, w - z.shape[1]))), mode="edge")
    return z[:h, :w]


def _upsample_bool(m, f):
    if f == 1:
        return m
    z = ndi.zoom(m.astype(np.float32), f, order=1)
    return z > 0.5


def _largest(m):
    lab, n = ndi.label(m)
    if n <= 1:
        return m
    sizes = ndi.sum(m, lab, index=np.arange(1, n + 1))
    return lab == (1 + int(np.argmax(sizes)))


def _fill_small_holes(m, max_area):
    holes = ~m
    lab, n = ndi.label(holes)
    if n == 0:
        return m
    sizes = ndi.sum(holes, lab, index=np.arange(1, n + 1))
    small = np.zeros(n + 1, bool)
    small[1:] = sizes < max_area
    # never fill the background (touching the border)
    border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    small[border] = False
    return m | small[lab]


def _smooth_noise_1d(n, rng, scale):
    k = max(2, int(n / scale) + 2)
    pts = rng.random(k)
    return np.interp(np.linspace(0, k - 1, n), np.arange(k), pts)


# ------------------------------------------------------------------ face finding
def detect_face(img):
    """-> ((x, y, w, h) in img px, path) or (None, 'fallback'). Largest LBP frontal-face box."""
    W, H = img.size
    s = min(1.0, 360.0 / max(W, H))
    sm = img.convert("L").resize((max(8, int(round(W * s))), max(8, int(round(H * s)))), Image.BILINEAR)
    g = np.asarray(sm, np.float64) / 255.0
    try:
        from skimage.feature import Cascade
        from skimage import data as skdata
        casc = Cascade(skdata.lbp_frontal_face_cascade_filename())
        mn = max(20, int(0.10 * min(g.shape)))
        dets = casc.detect_multi_scale(img=g, scale_factor=1.2, step_ratio=1,
                                       min_size=(mn, mn), max_size=(min(g.shape), min(g.shape)))
    except Exception:
        return None, "fallback"
    if not dets:
        return None, "fallback"
    d = max(dets, key=lambda r: r["width"] * r["height"])
    return (d["c"] / s, d["r"] / s, d["width"] / s, d["height"] / s), "cascade"


def geometry(img):
    """Face box and head crop box in image px. Returns dict."""
    W, H = img.size
    face, path = detect_face(img)
    found = face is not None
    if not found:
        fw = 0.45 * W
        fh = min(1.25 * fw, 0.95 * H - 0.18 * H)
        face = ((W - fw) / 2.0, 0.18 * H, fw, fh)
    fx, fy, fw, fh = face
    cw, ch = 1.45 * fw, 1.9 * fh
    x0 = fx + fw / 2.0 - cw / 2.0
    y0 = fy - 0.55 * fh
    x1, y1 = x0 + cw, y0 + ch
    x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(float(W), x1), min(float(H), y1)
    return {"face": face, "crop": (x0, y0, x1, y1), "found": found, "path": path}


def head_aspect(upload: bytes):
    """width / height of the head crop and whether a face was found (cheap; no sketch)."""
    img = _open_image(upload)
    g = geometry(img)
    x0, y0, x1, y1 = g["crop"]
    return (x1 - x0) / max(y1 - y0, 1e-6), g["found"]


def _open_image(upload):
    im = Image.open(io.BytesIO(upload))
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg
    im = im.convert("RGB")
    if max(im.size) > 3000:
        s = 3000.0 / max(im.size)
        im = im.resize((int(im.size[0] * s), int(im.size[1] * s)), Image.LANCZOS)
    return im


# ------------------------------------------------------------------ stamping variable-width strokes
def _resample(pts, step=1.0):
    pts = np.asarray(pts, float)
    if len(pts) < 2:
        return pts, np.zeros(len(pts))
    seg = np.hypot(*np.diff(pts, axis=0).T)
    s = np.concatenate([[0], np.cumsum(seg)])
    n = max(2, int(s[-1] / step) + 1)
    t = np.linspace(0, s[-1], n)
    return np.stack([np.interp(t, s, pts[:, 0]), np.interp(t, s, pts[:, 1])], 1), t


def _stamp(draw, pts, width_px):
    """pts Nx2 (x, y) px; width_px scalar or array per point. Round-capped variable stroke."""
    p, t = _resample(pts, 1.0)
    if len(p) == 0:
        return
    w = np.broadcast_to(np.asarray(width_px, float), (len(p),)) if np.ndim(width_px) == 0 else \
        np.interp(t, np.linspace(0, t[-1] if t[-1] > 0 else 1, len(width_px)), width_px)
    for (x, y), ww in zip(p, w):
        r = ww / 2.0
        if r > 0.3:
            draw.ellipse((x - r, y - r, x + r, y + r), fill=255)


def _profile(n, w_mid, w_end, power=0.8):
    t = np.linspace(0, 1, n)
    return w_end + (w_mid - w_end) * np.sin(np.pi * t) ** power


def _smooth_poly(pts, win):
    if len(pts) < 3 or win < 3:
        return pts
    k = win | 1
    pad = k // 2
    a = np.pad(pts, ((pad, pad), (0, 0)), mode="edge")
    ker = np.ones(k) / k
    return np.stack([np.convolve(a[:, 0], ker, "valid"), np.convolve(a[:, 1], ker, "valid")], 1)


def _walk_chains(edges, min_px):
    """Edge pixels (thin) -> ordered polylines (list of Nx2 [x, y])."""
    lab, n = ndi.label(edges, structure=np.ones((3, 3)))
    objs = ndi.find_objects(lab)
    out = []
    nb4 = [(0, 1), (0, -1), (1, 0), (-1, 0)]
    nb8 = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    for i, sl in enumerate(objs):
        if sl is None:
            continue
        sub = lab[sl] == (i + 1)
        if sub.sum() < min_px:
            continue
        ys, xs = np.nonzero(sub)
        pix = {(int(y), int(x)) for y, x in zip(ys, xs)}
        remaining = set(pix)

        def nbrs(p):
            y, x = p
            for dy, dx in nb4 + nb8:
                q = (y + dy, x + dx)
                if q in remaining:
                    yield q
        while remaining:
            ends = [p for p in remaining if sum(1 for _ in nbrs(p)) <= 1]
            start = ends[0] if ends else next(iter(remaining))
            chain = [start]
            remaining.discard(start)
            cur = start
            while True:
                nxt = next(nbrs(cur), None)
                if nxt is None:
                    break
                chain.append(nxt)
                remaining.discard(nxt)
                cur = nxt
            if len(chain) >= min_px:
                a = np.array(chain, float)
                a = a[:, ::-1] + np.array([sl[1].start, sl[0].start])
                out.append(a)
    return out


def _disk(mask_shape, cx, cy, r):
    h, w = mask_shape
    y0, y1 = int(max(0, cy - r - 1)), int(min(h, cy + r + 2))
    x0, x1 = int(max(0, cx - r - 1)), int(min(w, cx + r + 2))
    out = np.zeros(mask_shape, bool)
    if y1 <= y0 or x1 <= x0:
        return out
    gy, gx = np.mgrid[y0:y1, x0:x1]
    out[y0:y1, x0:x1] = (gx - cx) ** 2 + (gy - cy) ** 2 <= r * r
    return out


def _col_stroke(comp, ppm, wmin_mm, wmax_mm, end_taper, flip=False, taper_ends=False, smooth_mm=3.0):
    """Centreline of a near-horizontal dark component, one point per column, as (pts, widths_px).
    Width follows the component's thickness (clamped), tapers along x (end_taper 0..1 of the far end)."""
    cols = np.nonzero(comp.any(axis=0))[0]
    if len(cols) < 4:
        return None, None
    ys = np.arange(comp.shape[0], dtype=np.float32)[:, None]
    cnt = comp.sum(axis=0)[cols].astype(np.float32)
    cy = (comp * ys).sum(axis=0)[cols] / np.maximum(cnt, 1)
    k = max(3, int(smooth_mm * ppm)) | 1
    pts = _smooth_poly(np.stack([cols.astype(float), cy.astype(float)], 1), k)
    th = _smooth_poly(np.stack([cnt, cnt], 1).astype(float), k)[:, 0] / ppm
    wd = np.clip(th * 0.9, wmin_mm, wmax_mm)
    n = len(pts)
    u = np.linspace(0, 1, n)
    if flip:
        u = u[::-1]
    wd = wd * (1.0 - end_taper * u)
    if taper_ends:
        e = np.minimum(np.linspace(0, 1, n), np.linspace(1, 0, n))
        wd = wmin_mm + (wd - wmin_mm) * np.clip(e / 0.35, 0, 1)
    wd = np.maximum(wd, wmin_mm)
    return pts, wd * ppm


def _white_strands(blk, L, ppm, thr, nmax, minlen_mm, margin_mm, w_mm=1.15, scale_mm=2.0):
    """Tapered white strands cut from a solid black mass where the fine image is brighter than the mass
    (FL 8). Redrawn as strokes w_mm wide, stopping margin_mm before the mass edge."""
    out = Image.new("L", (blk.shape[1], blk.shape[0]), 0)
    interior = ndi.distance_transform_edt(blk) > margin_mm * ppm
    cand = blk & (_gauss(L, 0.3 * ppm) > _gauss(L, scale_mm * ppm) + thr)
    cand = _open(cand, 0.45 * ppm) & interior
    if not cand.any():
        return np.zeros(blk.shape, bool)
    from skimage.morphology import skeletonize
    chains = _walk_chains(skeletonize(cand), int(minlen_mm * ppm))
    chains = sorted(chains, key=lambda c: -len(c))[:nmax]
    dr = ImageDraw.Draw(out)
    for c in chains:
        c = _smooth_poly(c, 9)
        _stamp(dr, c, _profile(len(c), (w_mm + 0.3) * ppm, w_mm * ppm))
    return (np.asarray(out) > 0) & interior


def _flow_tensor(L, ppm, sigma_mm=3.0):
    """Flow direction of the photo's own texture (structure tensor): unit field along the strands, and coherence 0..1."""
    g = _gauss(L, 0.5 * ppm)
    gy, gx = np.gradient(g)
    s = sigma_mm * ppm
    jxx, jyy, jxy = _gauss(gx * gx, s), _gauss(gy * gy, s), _gauss(gx * gy, s)
    th = 0.5 * np.arctan2(2.0 * jxy, jxx - jyy) + math.pi / 2.0
    coh = np.sqrt((jxx - jyy) ** 2 + 4.0 * jxy ** 2) / (jxx + jyy + 1e-9)
    return np.cos(th).astype(np.float32), np.sin(th).astype(np.float32), coh.astype(np.float32)


def _flow_strands(region, fx, fy, ppm, rng, n, len_mm, margin_mm, w_mm, score=None, sep_mm=14.0, curv=1.0 / 15.0,
                  max_straight_mm=8.0):
    """n curved white strands that follow the unit field (fx, fy) inside region: each len_mm=(lo, hi) long, tapering to a point
    at both ends, centreline never closer than margin_mm to the region edge, no straight run over max_straight_mm
    (a constant turn of curv per mm is added to the field), never closer than sep_mm to one another (FL 6, FL 15)."""
    h, w = region.shape
    interior = ndi.distance_transform_edt(region) > margin_mm * ppm
    out = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(out)
    ys, xs = np.nonzero(interior)
    if len(ys) == 0:
        return np.zeros((h, w), bool)
    sc = score[ys, xs] if score is not None else rng.random(len(ys))
    take = np.argsort(-(sc + 0.15 * rng.random(len(ys))))[:max(400, len(ys) // 6)]
    take = take[rng.permutation(len(take))] if score is None else take
    step = 0.5 * ppm
    chosen = []
    made = 0
    for i in take:
        if made >= n:
            break
        x0, y0 = float(xs[i]), float(ys[i])
        if any(math.hypot(x0 - cx, y0 - cy) < sep_mm * ppm for cx, cy in chosen):
            continue
        total = rng.uniform(*len_mm) * ppm
        sgn_c = 1.0 if rng.random() < 0.5 else -1.0
        d0 = np.array([fx[int(y0), int(x0)], fy[int(y0), int(x0)]], float)
        if d0[1] < 0 or (abs(d0[1]) < 1e-3 and d0[0] < 0):
            d0 = -d0
        halves = []
        for side, sg in ((0, 1.0), (1, -1.0)):
            px, py = x0, y0
            hd = d0 * sg
            pts = [(px, py)]
            run = 0.0
            budget = total * (0.5 if side == 0 else 0.5)
            while run < budget:
                xi, yi = int(round(px)), int(round(py))
                if not (0 <= xi < w and 0 <= yi < h) or not interior[yi, xi]:
                    break
                d = np.array([fx[yi, xi], fy[yi, xi]], float)
                if float(d @ hd) < 0:
                    d = -d
                hd = 0.5 * hd + 0.5 * d
                hd = hd / (np.hypot(*hd) + 1e-9)
                a = sgn_c * sg * curv * (step / ppm)
                ca, sa = math.cos(a), math.sin(a)
                hd = np.array([hd[0] * ca - hd[1] * sa, hd[0] * sa + hd[1] * ca])
                px += hd[0] * step
                py += hd[1] * step
                pts.append((px, py))
                run += step
            halves.append(pts)
        pts = np.array(halves[1][::-1][:-1] + halves[0], float)
        if len(pts) < 3 or float(np.hypot(*np.diff(pts, axis=0).T).sum()) < 0.8 * len_mm[0] * ppm:
            continue
        pts = _smooth_poly(pts, 5)
        # no straight run: in every window of max_straight_mm of arc, some point must be >= 0.3 mm off the chord
        k = int(max_straight_mm * ppm / step)
        bad = False
        for a0 in range(0, max(1, len(pts) - k), max(1, k // 3)):
            seg = pts[a0:a0 + k + 1]
            if len(seg) < k:
                break
            c = seg[-1] - seg[0]
            nn = np.hypot(*c) + 1e-9
            dev = np.abs((seg[:, 0] - seg[0, 0]) * c[1] - (seg[:, 1] - seg[0, 1]) * c[0]) / nn
            if dev.max() < 0.3 * ppm:
                bad = True
                break
        if bad:
            continue
        wd = _profile(len(pts), w_mm * ppm, 0.15 * ppm, 0.9)
        _stamp(dr, pts, wd)
        chosen.append((x0, y0))
        made += 1
    return (np.asarray(out) > 0) & interior


def _bdisk(r):
    rr = int(math.ceil(r))
    yy, xx = np.mgrid[-rr:rr + 1, -rr:rr + 1]
    return (xx * xx + yy * yy) <= r * r


def _flow_strokes(region, fx, fy, spm, ppm, rng, lens, wmid_mm, seed_mm=1.5, extra_block=None):
    """Hair as tapered streamlines (FL 6, FL 15): seeds on a jittered lattice, each traced both ways along the
    unit field (fx, fy) inside region, stopped short of a neighbour (centre distance >= radius for its tone) and
    ended with a round cap at LW. spm = wanted centre spacing in mm per pixel (2.8 dense, 3.6 middle, 5.2 open).
    lens = {spacing_class: (min_mm, max_mm)}. Returns a bool raster."""
    h, w = region.shape
    img = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(img)
    rads = {2.6: 2.6, 2.8: 2.7, 3.4: 3.4, 5.2: 4.5, "stop": 2.35}
    forb = {k: np.zeros((h, w), bool) for k in rads}
    disks = {k: _bdisk(r * ppm) for k, r in rads.items()}
    ys, xs = np.nonzero(region)
    if len(ys) == 0:
        return np.zeros((h, w), bool)
    sp_px = seed_mm * ppm
    gy, gx = np.mgrid[int(ys.min()):int(ys.max()) + 1:sp_px, int(xs.min()):int(xs.max()) + 1:sp_px]
    sx = gx.ravel() + rng.uniform(-0.3, 0.3, gx.size) * sp_px
    sy = gy.ravel() + rng.uniform(-0.3, 0.3, gy.size) * sp_px
    order = rng.permutation(sx.size)
    step = 0.6 * ppm

    def cls(v):
        return 2.6 if v < 2.7 else (2.8 if v < 3.1 else (3.4 if v < 4.2 else 5.2))

    def stamp_forb(px, py):
        for k, d in disks.items():
            r = d.shape[0] // 2
            y0, x0 = int(py) - r, int(px) - r
            ya, xa = max(0, y0), max(0, x0)
            yb, xb = min(h, y0 + d.shape[0]), min(w, x0 + d.shape[1])
            if yb > ya and xb > xa:
                forb[k][ya:yb, xa:xb] |= d[ya - y0:yb - y0, xa - x0:xb - x0]

    for i in order:
        x, y = float(sx[i]), float(sy[i])
        xi, yi = int(round(x)), int(round(y))
        if not (0 <= xi < w and 0 <= yi < h) or not region[yi, xi]:
            continue
        c = cls(float(spm[yi, xi]))
        if forb[c][yi, xi]:
            continue
        lo, hi = lens.get(c, lens[2.8])
        total = rng.uniform(lo, hi) * ppm
        fr = rng.uniform(0.3, 0.7)
        pieces = []
        for sgn, budget in ((1.0, total * fr), (-1.0, total * (1 - fr))):
            px, py = x, y
            pts = []
            run = 0.0
            while run < budget:
                xi, yi = int(round(px)), int(round(py))
                if not (0 <= xi < w and 0 <= yi < h) or not region[yi, xi] or forb["stop"][yi, xi] and run > 0:
                    break
                pts.append((px, py))
                px += sgn * fx[yi, xi] * step
                py += sgn * fy[yi, xi] * step
                run += step
            pieces.append(pts)
        pts = pieces[1][::-1][:-1] + pieces[0] if len(pieces[1]) > 1 else pieces[0]
        if len(pts) < 4.0 * ppm / step:
            continue
        a = _smooth_poly(np.array(pts, float), 5)
        wd = _profile(len(a), wmid_mm * ppm, LW * ppm)
        _stamp(dr, a, wd)
        pa, _ = _resample(a, 1.0 * ppm)
        for (qx, qy) in pa:
            stamp_forb(qx, qy)
    return np.asarray(img) > 0


def _mirror_cols(m, xc):
    w = m.shape[1]
    cols = np.clip(np.round(2 * xc - np.arange(w)).astype(int), 0, w - 1)
    return m[:, cols]


def _hair_cuts(hm, xc, bx, bw, ppm, rng, h, w, L06):
    """White strands from the part outward and down, a lit crown band with two hairlines, curl notches in the top edge
    (red team r2: FL 6, FL 15). Returns (white mask, black hairlines mask)."""
    inn = ndi.distance_transform_edt(hm) > 3.5 * ppm
    cols = np.nonzero(hm.any(axis=0))[0]
    if len(cols) < 40 * ppm * 0.2:
        return np.zeros((h, w), bool), np.zeros((h, w), bool)
    topy = np.full(w, np.nan)
    th = np.zeros(w)
    for c in cols:
        r_ = np.nonzero(hm[:, c])[0]
        topy[c], th[c] = r_.min(), len(r_)
    x0c, x1c = int(cols.min()), int(cols.max())
    ok = ~np.isnan(topy)
    topy = np.interp(np.arange(w), np.nonzero(ok)[0], topy[ok])
    th = np.interp(np.arange(w), np.nonzero(ok)[0], th[ok])
    wimg = Image.new("L", (w, h), 0)
    wd_ = ImageDraw.Draw(wimg)
    span = x1c - x0c
    white = (np.asarray(wimg) > 0) & inn
    # lit crown band
    a0, a1 = int(x0c + 0.40 * span), int(x0c + 0.60 * span)
    s_ = np.clip((np.arange(w) - a0) / max(1.0, a1 - a0), 0, 1)
    ybr = topy + np.minimum(0.4 * th, 16.0 * ppm)
    for c in range(a0, a1 + 1):          # the band rides the brightest row of the mass (the sheen), not a fixed depth
        r0_, r1_ = int(topy[c] + 6.0 * ppm), int(topy[c] + min(0.7 * th[c], 28.0 * ppm))
        if r1_ > r0_ + 2:
            ybr[c] = r0_ + int(np.argmax(L06[r0_:r1_, c]))
    yb = _gauss(ybr, 4.0 * ppm)
    tb = 6.6 * ppm * np.sin(np.pi * s_) ** 0.7
    rows = np.arange(h)[:, None]
    band = (np.abs(rows - yb[None, :]) < (tb / 2.0)[None, :]) & inn & (np.arange(w)[None, :] >= a0) & (np.arange(w)[None, :] <= a1)
    band = _open(band, 0.5 * ppm)
    white |= band
    hl = np.zeros((h, w), bool)
    for off in (-1.0 / 6, 1.0 / 6):
        yl = yb + off * tb
        for c in range(int(a0 + 0.12 * (a1 - a0)), int(a1 - 0.12 * (a1 - a0))):
            if tb[c] >= 5.6 * ppm:
                r_ = int(round(yl[c]))
                hl[max(0, r_ - int(0.78 * ppm)):r_ + int(0.78 * ppm) + 1, c] = True
    # curl notches: white curls leaving the top silhouette
    cimg = Image.new("L", (w, h), 0)
    cd_ = ImageDraw.Draw(cimg)
    for xk in x0c + span * np.array([0.30, 0.50, 0.70]) + rng.uniform(-0.02, 0.02, 3) * span:
        c = int(np.clip(xk, 0, w - 1))
        sg = 1.0 if rng.random() < 0.5 else -1.0
        t = np.linspace(0, 1, 12)
        cx_ = xk + sg * 3.2 * ppm * np.sin(np.pi * t * 0.9)
        cy_ = topy[c] - 1.5 * ppm + 8.5 * ppm * t
        _stamp(cd_, np.stack([cx_, cy_], 1), _profile(12, 1.3 * ppm, 0.9 * ppm))
    white |= (np.asarray(cimg) > 0) & hm
    return white, hl & hm


# ------------------------------------------------------------------ the sketch
def make_sketch(upload: bytes, tile_width_mm: float, detail: float = 0.5, shading: bool = True,
                debug: bool = False, measure: bool = True, gap_mm: float = 1.0) -> Sketch:
    t0 = time.time()
    rng = np.random.default_rng(11)
    detail = float(min(1.0, max(0.0, detail)))
    img = _open_image(upload)
    geo = geometry(img)
    W = max(20.0, float(tile_width_mm))
    x0, y0, x1, y1 = geo["crop"]
    asp = (x1 - x0) / max(y1 - y0, 1e-6)
    Hmm = W / asp
    ppm = PPM
    if max(W, Hmm) * ppm > MAX_PX:
        ppm = MAX_PX / max(W, Hmm)
    ppm = min(ppm, math.sqrt(MAX_AREA / (W * Hmm)))
    f = 2 if ppm >= 5 else 1                     # low-res factor for the smooth value fields
    wpx = max(4 * f, int(round(W * ppm / (4 * f))) * 4 * f)
    hpx = max(4 * f, int(round(wpx / asp / (4 * f))) * 4 * f)
    ppm = wpx / W
    ppm_y = hpx / Hmm
    crop = img.crop((int(math.floor(x0)), int(math.floor(y0)), int(math.ceil(x1)), int(math.ceil(y1))))
    crop = crop.resize((wpx, hpx), Image.LANCZOS)
    rgb = np.asarray(crop)
    L = _L_from_rgb(rgb)
    h, w = L.shape
    sx = wpx / max(x1 - x0, 1e-6)
    sy = hpx / max(y1 - y0, 1e-6)
    fx, fy, fw, fh = geo["face"]
    bx = (fx - x0) * sx
    by = (fy - y0) * sy
    bw, bh = fw * sx, fh * sy
    face_box = (bx, by, bw, bh)
    mm = lambda v: v * ppm            # mm -> px (isotropic enough; ppm_y ~ ppm)
    fwmm = bw / ppm

    # -------- light direction (FP 2.5)
    xa, xb = int(max(0, bx)), int(min(w, bx + bw))
    ya, yb = int(max(0, by)), int(min(h, by + bh))
    mid = (xa + xb) // 2
    lmean, rmean = float(L[ya:yb, xa:mid].mean()), float(L[ya:yb, mid:xb].mean())
    light_left = lmean >= rmean
    light_side = "left" if light_left else "right"

    # -------- low-res fields
    Ll = L.reshape(h // f, f, w // f, f).mean(axis=(1, 3)) if f > 1 else L
    hl, wl = Ll.shape
    ppl = ppm / f
    from skimage import color as skcolor
    rgbl = rgb.reshape(h // f, f, w // f, f, 3).mean(axis=(1, 3)).astype(np.uint8) if f > 1 else rgb
    lab = skcolor.rgb2lab(rgbl)

    # -------- subject mask (FP 2.4)
    yy, xx = np.mgrid[0:hl, 0:wl].astype(np.float32)
    cxl, cyl = wl / 2.0, hl / 2.0
    ell = ((xx - cxl) / (0.48 * wl)) ** 2 + ((yy - cyl) / (0.48 * hl)) ** 2 <= 1.0
    chin = min(hl - 2, (by + bh) / f)                   # chin row, low-res
    tt = np.clip((yy - chin) / max(hl - chin, 1.0), 0, 1)
    half = (0.27 + 0.07 * tt) * wl                      # neck column only: collar and suit fade out
    trap = (yy >= chin) & (np.abs(xx - cxl) <= half)
    shape = ell | trap
    ring = np.zeros((hl, wl), bool)
    rr = max(2, int(0.06 * min(hl, wl)))
    ring[:rr] = True
    ring[:, :rr] = True
    ring[:, -rr:] = True
    ring &= (yy < chin)
    if ring.sum() < 20:
        ring[:rr] = True
    labs = lab[ring]
    med = np.median(labs, axis=0)
    mad = np.median(np.abs(labs - med), axis=0) * 1.4826
    sc = np.maximum(mad, 2.5)
    labs_s = np.stack([_gauss(lab[..., c], 1.0) for c in range(3)], -1)
    z = np.sqrt((((labs_s - med) / sc) ** 2).mean(-1))
    cand = (z < 2.2) | ~shape
    cl, ncl = ndi.label(cand)
    edge_labels = np.unique(np.concatenate([cl[0], cl[-1], cl[:, 0], cl[:, -1]]))
    edge_labels = edge_labels[edge_labels > 0]
    bgm = np.isin(cl, edge_labels)
    mlo = shape & ~bgm
    r2 = max(1, int(round(1.0 * ppl)))                   # close 2 mm = radius 1 mm
    mlo = _close(mlo, r2) & shape
    if mlo.sum() < 0.08 * hl * wl:        # background model ate the subject: keep the plain head shape
        mlo = shape.copy()
    mlo = _largest(mlo)
    mlo = _fill_small_holes(mlo, 25.0 * ppl * ppl)
    mask = _upsample_bool(mlo, f)
    mask = mask[:h, :w]
    area_mm2 = float(mask.sum()) / (ppm * ppm)

    # -------- values (FP 3)
    Lm = _nblur(Ll, mlo, 2.0 * ppl)
    vals = Lm[mlo]
    cuts_extra = 0.0
    CUT = (6.0, 17.0, 30.0)
    LDT = (0.040, 0.085)
    Dl = _nblur(Ll, mlo, 6.0 * ppl) - _nblur(Ll, mlo, 0.8 * ppl)
    D2 = _nblur(Ll, mlo, 3.0 * ppl) - _nblur(Ll, mlo, 0.7 * ppl)
    nb_ = np.zeros((hl, wl), bool)
    nb_[int((by + 0.40 * bh) / f):int((by + 0.72 * bh) / f), int((bx + 0.25 * bw) / f):int((bx + 0.75 * bw) / f)] = True
    Dl = np.where(nb_, np.maximum(Dl, D2 * 1.25), Dl)
    ro = max(1, int(round(0.8 * ppl)))

    def band_levels(extra):
        q = np.percentile(vals, [CUT[0] + extra, CUT[1] + extra, CUT[2] + extra])
        dense = _open((Lm <= q[0]) | (Dl > LDT[1]), ro) & mlo
        middle = _open((Lm <= q[1]) | (Dl > LDT[0]), ro) & mlo
        opn = _open(Lm <= q[2], ro) & mlo
        lvl = np.zeros((hl, wl), np.uint8)
        if shading:
            lvl[opn] = 1
            lvl[middle] = 2
        lvl[dense] = 3
        if fwmm < 55:
            lvl[lvl == 1] = 0
        return lvl

    # -------- hair / beard zones (FL 6)
    xs = np.arange(w)[None, :]
    ys_ = np.arange(h)[:, None]
    hair_zone = mask & ((ys_ < by + 0.15 * bh) | ((xs < bx + 0.02 * bw) | (xs > bx + 0.98 * bw)) & (ys_ < by + 0.62 * bh))
    beard_zone = mask & (ys_ > by + 0.72 * bh) & (xs > bx - 0.02 * bw) & (xs < bx + 1.02 * bw) & (ys_ < by + 1.45 * bh)
    Lb = _gauss(L, 0.25 * ppm)
    L06 = _gauss(L, 0.6 * ppm)
    L12 = _gauss(L, 1.2 * ppm)
    hair_med = float(np.median(L[hair_zone])) if hair_zone.sum() > 100 else 1.0
    dark_hair = float(np.percentile(L[hair_zone], 40)) < 0.35 if hair_zone.sum() > 100 else False

    # -------- r2 features: eyes, brows, nose (red team r1 findings 1-2; FG 5)
    ys_f = np.arange(h)[:, None]
    face_in = mask & (xs >= bx) & (xs <= bx + bw) & (ys_f >= by + 0.2 * bh) & (ys_f <= by + 0.9 * bh) & ~hair_zone
    face_med = float(np.median(L12[face_in])) if face_in.sum() > 100 else 0.55
    L05 = _gauss(L, 0.5 * ppm)
    fdraw = Image.new("L", (w, h), 0)
    fd = ImageDraw.Draw(fdraw)
    clear_f = np.zeros((h, w), bool)          # no hatch, lines or black here: eyes and brows own it
    catch_f = np.zeros((h, w), bool)
    eye_cx = []
    for sd, (c0, c1) in enumerate(((0.12, 0.46), (0.54, 0.88))):
        xa, xb = int(max(0, bx + c0 * bw)), int(min(w, bx + c1 * bw))
        i0, i1 = xa + int(0.2 * (xb - xa)), xb - int(0.1 * (xb - xa))
        ra, rb = int(max(0, by + 0.16 * bh)), int(min(h, by + 0.50 * bh))
        prof = _gauss(L05[ra:rb, i0:i1].mean(axis=1), 1.0 * ppm)
        nb_end = max(2, int((by + 0.34 * bh) - ra))
        brow_r = ra + int(np.argmin(prof[:nb_end]))
        dp = prof - _gauss(prof, 4.0 * ppm)
        e0, e1 = int(brow_r + 3.5 * ppm) - ra, int(brow_r + 15 * ppm) - ra
        e0, e1 = max(0, e0), min(len(dp), e1)
        eye_r = ra + (e0 + int(np.argmin(dp[e0:e1])) if e1 > e0 + 2 else int(0.12 * bh))
        # brow: dark component round brow_r, drawn as its own tapered stroke, thick at the nose end
        r0, r1 = int(max(0, brow_r - 5 * ppm)), int(min(h, brow_r + 5 * ppm))
        reg = np.zeros((h, w), bool)
        xab = int(max(0, bx + (0.10 if sd == 0 else 0.50) * bw))
        xbb = int(min(w, bx + (0.46 if sd == 0 else 0.90) * bw))
        reg[r0:r1, xab:xbb] = True
        reg &= mask
        if reg.sum() > 100:
            ref = np.percentile(L05[reg], 60)
            bc = _open(reg & (L05 < ref - 0.07), 0.45 * ppm)
            loose_b = _open(reg & (L05 < ref - 0.035) & ~hair_zone, 0.45 * ppm)
            lb_, nbc = ndi.label(bc)
            if nbc:
                szb = ndi.sum(bc, lb_, index=np.arange(1, nbc + 1))
                comp = lb_ == (1 + int(np.argmax(szb)))
                comp = ndi.binary_propagation(comp, mask=loose_b | comp)
                if szb.max() >= 15 * ppm * ppm:
                    pts, wd = _col_stroke(comp, ppm, LW, 2.8, 0.5, flip=(sd == 0), smooth_mm=4.0)
                    if pts is not None:
                        _stamp(fd, pts, wd)
        clear_f[int(max(0, brow_r - 5.5 * ppm)):int(brow_r + 5.5 * ppm), xa:xb] = True
        # eye: lid line from the dark slit, iris dot, catchlight; sclera stays bare paper
        r0, r1 = int(max(0, eye_r - 3.0 * ppm)), int(min(h, eye_r + 3.0 * ppm))
        x0e, x1e = xa + int(0.15 * (xb - xa)), xb - int(0.05 * (xb - xa))
        win = np.zeros((h, w), bool)
        win[r0:r1, x0e:x1e] = True
        win &= mask
        if win.sum() > 100:
            ref = np.percentile(L05[win], 60)
            ec = _open(win & (L05 < ref - 0.10), 0.4 * ppm)
            lb_, nec = ndi.label(ec)
            if nec:
                sze = ndi.sum(ec, lb_, index=np.arange(1, nec + 1))
                comp = lb_ == (1 + int(np.argmax(sze)))
                pts, wd = _col_stroke(comp, ppm, LW, 2.3, 0.0, taper_ends=True, smooth_mm=2.5)
                if pts is not None and len(pts) > 3 * ppm:
                    _stamp(fd, pts, wd)
            inner = np.zeros((h, w), bool)
            inner[r0:r1, x0e + int(0.15 * (x1e - x0e)):x1e - int(0.15 * (x1e - x0e))] = True
            sub = np.where(inner & mask, L05, 9.0)
            iy, ix = np.unravel_index(int(np.argmin(sub)), sub.shape)
            iy = iy + 1.3 * ppm                       # the iris sits under the upper lid, cut by it
            fd.ellipse((ix - 2.3 * ppm, iy - 2.3 * ppm, ix + 2.3 * ppm, iy + 2.3 * ppm), fill=255)
            catch_f |= _disk((h, w), ix + 0.8 * ppm, iy + 0.4 * ppm, 0.55 * ppm)
            eye_cx.append(ix)
        clear_f[int(max(0, eye_r - 6.5 * ppm)):int(eye_r + 8.0 * ppm), xa:xb] = True
    xc = float(np.mean(eye_cx)) if len(eye_cx) == 2 else bx + 0.5 * bw
    # nose: two solid nostrils, a wing arc from each, a shadow under the tip (FG 5 Nose)
    nostril_pts = []
    nose_clear = np.zeros((h, w), bool)
    nb0, nb1 = int(by + 0.50 * bh), int(by + 0.64 * bh)
    nbx0, nbx1 = int(max(0, xc - 0.15 * bw)), int(min(w, xc + 0.15 * bw))
    nbox = np.zeros((h, w), bool)
    nbox[nb0:nb1, nbx0:nbx1] = True
    nbox &= mask
    if nbox.sum() > 100:
        cut = np.percentile(L05[nbox], 8)
        cand = _open(nbox & (L05 <= cut), 0.4 * ppm)
        lb_, nn_ = ndi.label(cand)
        best = {}
        for o in range(1, nn_ + 1):
            cyo, cxo = ndi.center_of_mass(lb_ == o)
            ar = float((lb_ == o).sum())
            sdn = 0 if cxo < xc else 1
            if sdn not in best or ar > best[sdn][2]:
                best[sdn] = (cxo, cyo, ar)
        for sdn, (cxo, cyo, ar) in best.items():
            nostril_pts.append((cxo, cyo, -1.0 if sdn == 0 else 1.0))
    for (cxo, cyo, sg) in nostril_pts:
        fd.ellipse((cxo - 2.4 * ppm, cyo - 1.7 * ppm, cxo + 2.4 * ppm, cyo + 1.7 * ppm), fill=255)
        nose_clear[int(cyo - 4 * ppm):int(cyo + 6 * ppm), int(cxo - 4 * ppm):int(cxo + 4 * ppm)] = True
        t = np.linspace(0, 1, 40)[:, None]
        p0 = np.array([cxo + sg * 2.8 * ppm, cyo - 0.6 * ppm])
        p1 = np.array([cxo + sg * 8.0 * ppm, cyo + 0.4 * ppm])
        p2 = np.array([cxo + sg * 7.6 * ppm, cyo - 4.4 * ppm])
        arc = (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2
        _stamp(fd, arc, np.linspace(2.0, LW, 40) * ppm)
    if len(nostril_pts) == 2:
        (xl, yl, _), (xr, yr, _) = sorted(nostril_pts)
        ysh = 0.5 * (yl + yr) + 4.4 * ppm
        L12s = L12
        xi = int(np.clip(0.5 * (xl + xr), 0, w - 1)); yi = int(np.clip(ysh, 0, h - 1))
        if float(L12s[yi, xi]) < face_med - 0.04:
            t = np.linspace(0, 1, 30)
            xmid = 0.5 * (xl + xr)
            sh = np.stack([xmid - 7.0 * ppm + 14.0 * ppm * t, ysh + 1.0 * ppm * np.sin(np.pi * t)], 1)
            _stamp(fd, sh, _profile(30, 2.0 * ppm, LW * ppm))

    # -------- black (FP 5)
    eye_boxes = []
    for (c0, c1) in ((0.15, 0.45), (0.55, 0.85)):
        eye_boxes.append((bx + c0 * bw, by + 0.30 * bh, bx + c1 * bw, by + 0.50 * bh))
    ebox = np.zeros((h, w), bool)
    for (a, b, c, d) in eye_boxes:
        ebox[int(max(0, b)):int(min(h, d)), int(max(0, a)):int(min(w, c))] = True
    head_area = area_mm2 * ppm * ppm
    thr = 0.20
    zones = (hair_zone | beard_zone)
    for _ in range(5):
        fine = (Lb < thr)
        zthr = np.where(beard_zone & ~hair_zone, 0.0, thr + 0.03)
        black = np.where(zones, (L12 < zthr), fine) & mask
        black = _open(black, 0.6 * ppm)
        lab_b, nb = ndi.label(black)
        sizes = ndi.sum(black, lab_b, index=np.arange(1, nb + 1)) if nb else np.array([])
        big = int((sizes > 0.02 * head_area).sum())
        if big <= 3:
            break
        thr -= 0.015
    # solid hair mass (Beardsley) when the hair is dark; white strands cut in as tapered strokes (FL 8)
    strands_white = np.zeros((h, w), bool)
    extra_black = np.zeros((h, w), bool)
    if dark_hair:
        side_h = hair_zone & ((xs < bx + 0.02 * bw) | (xs > bx + 0.98 * bw)) & (ys_ >= by + 0.15 * bh)
        thr_h = np.where(side_h, float(np.percentile(L[hair_zone], 50)), min(0.5, float(np.percentile(L[hair_zone], 85))))
        hm = hair_zone & (L06 < thr_h)
        hm = _close(hm, 1.5 * ppm) & hair_zone
        hm = _fill_small_holes(hm, 20 * ppm * ppm)
        hm = _open(hm, 1.2 * ppm)
        # side hair: one coherent mass or nothing, no porous mosaic (red team r3)
        side_m = side_h & ~(ys_ < by + 0.15 * bh)
        hs_ = _fill_small_holes(_close(hm & side_m, 3.5 * ppm) & hair_zone, 120 * ppm * ppm)
        hm = (hm & ~side_m) | hs_
        black |= hm
        hair_black = hm
        hfx, hfy, hcoh = _flow_tensor(L, ppm, 3.0)
        hsc = hcoh + 3.0 * (L06 - _gauss(L, 4.0 * ppm)) + 0.12 * np.minimum(ndi.distance_transform_edt(hair_black) / ppm, 12.0)
        strands_white |= _flow_strands(hair_black, hfx, hfy, ppm, rng, 6, (14.0, 25.0), 3.0 + 0.7, 1.6, score=hsc, sep_mm=14.0, curv=1.0 / 20.0)
        hw_, hb_ = _hair_cuts(hm, xc, bx, bw, ppm, rng, h, w, L06)
        strands_white |= hw_
        extra_black |= hb_
    hair_area_px = float(black.sum())
    black &= ~clear_f | hair_zone
    catch = catch_f.copy()

    # teeth: bright band inside the dark mouth stays bare paper (FG 5 mouth)
    mouth_box = np.zeros((h, w), bool)
    mouth_box[int(by + 0.66 * bh):int(by + 0.88 * bh), int(bx + 0.25 * bw):int(bx + 0.75 * bw)] = True
    teeth = _open(mouth_box & (L06 > 0.72) & mask, 0.5 * ppm)
    teeth_only = np.zeros_like(teeth)
    if teeth.any():
        lt, nt = ndi.label(teeth)
        for o, sl in enumerate(ndi.find_objects(lt), start=1):
            ww, hh = sl[1].stop - sl[1].start, sl[0].stop - sl[0].start
            # teeth are a long thin bright band between two dark lips, not a patch of lit skin
            if ww >= 0.15 * bw and ww >= 4.0 * hh:
                teeth_only |= lt == o
        if teeth_only.any():
            tr_ = np.nonzero(teeth_only.any(axis=1))[0]
            band_rows = (ys_ >= tr_.min() - 1.5 * ppm) & (ys_ <= tr_.max() + 1.5 * ppm)
            teeth_only = ndi.binary_propagation(teeth_only, mask=_open(mouth_box & (L06 > 0.60) & band_rows & mask, 0.4 * ppm) | teeth_only)
            teeth_only = ndi.binary_dilation(teeth_only, structure=np.ones((3, 1), bool), iterations=int(0.8 * ppm)) & mask
    if teeth_only.any():
        # the whole bright band, bare paper: fill each column from the teeth's top to bottom edge (hatch never enters)
        tb = np.zeros((h, w), bool)
        for c_ in np.nonzero(teeth_only.any(axis=0))[0]:
            r_ = np.nonzero(teeth_only[:, c_])[0]
            tb[r_.min():r_.max() + 1, c_] = True
        teeth_only = _close(tb | teeth_only, 1.0 * ppm) & mask
        t_rows = np.nonzero(teeth_only.any(axis=1))[0]
        cut_row = float(0.5 * (t_rows.min() + t_rows.max()))
        lip_clear = ndi.distance_transform_edt(~teeth_only) <= 2.5 * ppm
    else:
        cut_row = by + 0.74 * bh
        lip_clear = np.zeros((h, w), bool)

    # -------- moustache and beard: each ONE smoothed mass (FL 6), white strands cut in, 2.5 mm clear round the lips
    mou_zone = mask & (ys_ > by + 0.60 * bh) & (ys_ < by + 0.80 * bh) & (xs > bx + 0.14 * bw) & (xs < bx + 0.86 * bw)
    Tm1, Tm2 = _gauss(Ll, 0.8 * ppl), _gauss(Ll * Ll, 0.8 * ppl)
    Tex = _up_f(_gauss(np.sqrt(np.maximum(Tm2 - Tm1 * Tm1, 0)), 1.5 * ppl), f, h, w)     # stubble and moustache hair read as texture
    inner_ = ndi.distance_transform_edt(mask) > 3.0 * ppm
    mass = (mou_zone | (beard_zone & ~hair_zone)) & ((L12 < face_med - 0.12) | (Tex > 0.07)) & ~teeth_only & inner_
    mass = _close(mass, 1.5 * ppm) & (mou_zone | beard_zone)
    mass = _fill_small_holes(mass, 12 * ppm * ppm)
    mass = _open(mass, 1.5 * ppm) & mask & ~teeth_only
    mous = mass & mou_zone & (ys_ <= cut_row + 0.5 * ppm)
    mous = _close(mous, 2.0 * ppm)
    mous = _open(mous, 1.6 * ppm) & mask & ~teeth_only & (ys_ <= cut_row + 0.5 * ppm)
    # solid only where the moustache is darkest (thickest at the centre); its edge stays dense hatch
    mous_core = _open(mous & (L12 < face_med - 0.19), 1.6 * ppm)
    mous_hatch = mous & ~mous_core
    beard_m = (mass & ~mous & ~lip_clear)
    beard_m = _open(_close(beard_m, 2.5 * ppm), 2.0 * ppm) & ~lip_clear & mask
    # beard = ONE continuous dense-grid band, no solid clumps; the only solid is the soul patch right under the lip
    beard_m = _open(_close(beard_m, 3.0 * ppm), 2.5 * ppm) & ~lip_clear & mask
    core = np.zeros((h, w), bool)
    if teeth_only.any():
        sy0, sy1 = int(cut_row + 0.0 * ppm), int(cut_row + 22 * ppm)
        sp = np.zeros((h, w), bool)
        sp[sy0:sy1, int(xc - 0.12 * bw):int(xc + 0.12 * bw)] = True
        sp &= beard_m & ~lip_clear & (L12 < face_med - 0.14)
        sp = _open(sp, 1.5 * ppm)
        lb_, nsp = ndi.label(sp)
        if nsp:
            szs = ndi.sum(sp, lb_, index=np.arange(1, nsp + 1))
            if szs.max() >= 8 * ppm * ppm:
                core = _close(lb_ == (1 + int(np.argmax(szs))), 1.5 * ppm)
    # beard footprint straight from the photo: stubble texture or clearly darker than skin, not the shirt (red team r2 #1)
    collar_ = _gauss(rgb[..., 2].astype(np.float32) - rgb[..., 0].astype(np.float32), 1.0 * ppm) > 15
    t_bot = float(np.nonzero(teeth_only.any(axis=1))[0].max()) if teeth_only.any() else by + 0.86 * bh
    breg = ((Tex > 0.05) | (L12 < face_med - 0.12)) & ~collar_ & mask & (ys_ > t_bot + 3.0 * ppm) & (ys_ < by + 1.5 * bh)
    breg &= (xs > bx + 0.12 * bw) & (xs < bx + 0.88 * bw)
    breg = _largest(_open(_close(breg, 3.0 * ppm), 2.5 * ppm))
    if breg.any() and float(np.median(Tex[breg])) < 0.05:     # no stubble texture: a clean-shaven chin has no beard
        breg = np.zeros((h, w), bool)
    beard_m = breg & ~lip_clear
    beard_only = beard_m & ~core
    # moustache = two symmetric wings from the philtrum (red team r2): what both halves share, no solid wedges
    mous_core = np.zeros((h, w), bool)
    mous_sym = mous.copy()
    mous_sym = _open(_close(mous_sym, 2.0 * ppm), 1.6 * ppm) & mask & ~teeth_only & ~lip_clear
    if teeth_only.any() and len(nostril_pts) == 2:
        # the moustache hangs from the nose to the lip: fill every dark row between the nostrils and the teeth (FL 6)
        t_top = float(np.nonzero(teeth_only.any(axis=1))[0].min())
        ny0 = float(np.mean([q[1] for q in nostril_pts]))
        xm_ = np.nonzero(mous)[1]
        if len(xm_) > 100:
            ext = mask & (ys_ > ny0 + 3.0 * ppm) & (ys_ < t_top) & (xs >= xm_.min()) & (xs <= xm_.max())
            ext &= (L12 < face_med - 0.09) | (Tex > 0.06)
            ext = _open(_close(ext, 2.5 * ppm), 1.6 * ppm) & ~teeth_only & ~lip_clear
            mous_sym = _close(mous_sym | ext, 2.0 * ppm) & mask & ~teeth_only & ~lip_clear
    mous_hatch = mous_sym
    mass_hatch = beard_only | mous_sym
    solid_mass = core
    black |= solid_mass
    flow_ink = np.zeros((h, w), bool)
    ribbon = np.zeros((h, w), bool)
    chin_ln = np.zeros((h, w), bool)
    lip_far = ndi.distance_transform_edt(~teeth_only) <= 5.0 * ppm if teeth_only.any() else lip_clear
    beard_reg = beard_only & ~lip_far
    if beard_reg.sum() > 200 * ppm * ppm / 10:
        fxb = np.zeros((h, w), np.float32)
        Dm = ndi.distance_transform_edt(beard_reg) / ppm
        Ds = _gauss(Dm.astype(np.float32), 2.5 * ppm)
        gyb, gxb = np.gradient(Ds)
        nn = np.hypot(gxb, gyb) + 1e-6
        nx_, ny_ = gxb / nn, gyb / nn
        cxb = float(xc)
        bys, bxs = np.nonzero(beard_reg)
        hw_b = max(1.0, 0.5 * (bxs.max() - bxs.min()))
        tx_, ty_ = -ny_, nx_
        score = ty_ + 0.5 * tx_ * (cxb - xx_full(h, w)) / hw_b
        flip = np.where(score < 0, -1.0, 1.0)
        tx_, ty_ = tx_ * flip, ty_ * flip
        ca, sa = math.cos(math.radians(25)), math.sin(math.radians(25))
        ex_, ey_ = tx_ * ca + nx_ * sa, ty_ * ca + ny_ * sa
        fx_ = 0.6 * (cxb - xx_full(h, w)) / hw_b
        fy_ = np.ones((h, w), np.float32)
        sblend = np.clip((Ds - 5.0) / 7.0, 0, 1)
        dx_ = (1 - sblend) * ex_ + sblend * fx_
        dy_ = (1 - sblend) * ey_ + sblend * fy_
        ang = np.arctan2(dy_, dx_)
        nz_ = _gauss(rng.normal(size=(h // 4 + 1, w // 4 + 1)).astype(np.float32), 2.0 * ppm / 4)
        nz_ = nz_ / (np.abs(nz_).max() + 1e-6)
        nz_ = np.kron(nz_, np.ones((4, 4), np.float32))[:h, :w]
        ang = ang + nz_ * math.radians(6)
        fxb = _gauss(np.cos(ang).astype(np.float32), 1.5 * ppm)
        fyb = _gauss(np.sin(ang).astype(np.float32), 1.5 * ppm)
        nb2 = np.hypot(fxb, fyb) + 1e-6
        fxb, fyb = fxb / nb2, fyb / nb2
        # graded spacing: dark and the outer rim dense, lit middle open, a rim under the jaw always dense
        lb_vals = L12[beard_reg]
        q1, q2 = np.percentile(lb_vals, [60, 88])
        # tight at the chin and under the lower lip (2.6), opening up the cheeks (3.4 to 5.2), a little darker photo = a little tighter
        latb = np.abs(xx_full(h, w) - cxb) / hw_b
        gcheek = np.clip((latb - 0.30) / 0.55, 0, 1)
        spm = np.where(gcheek <= 0, 2.6, 3.4 + 1.8 * gcheek ** 1.2).astype(np.float32)
        spm = np.where((L12 <= q1) & (gcheek > 0), np.maximum(3.4, spm - 0.5), spm)
        yc_b = float(bys.mean())
        rim = (Dm < 11.0) & (yy_full(h, w) > yc_b - 3 * ppm) & (latb < 0.75)
        spm = np.where(rim, 2.6, spm)
        spm = _gauss(spm, 1.0 * ppm)
        # ribbon: a dark crescent along the underside of the jaw, tapered at both ends
        x0r, x1r = int(bxs.min()), int(bxs.max())
        ybot = np.full(w, np.nan)
        for c_ in range(x0r, x1r + 1):
            rr_ = np.nonzero(beard_reg[:, c_])[0]
            if len(rr_):
                ybot[c_] = rr_.max()
        ok_ = ~np.isnan(ybot)
        if ok_.sum() > 10:
            ybot = np.interp(np.arange(w), np.nonzero(ok_)[0], ybot[ok_])
            ybot = _gauss(ybot.astype(np.float32), 4.0 * ppm)
            ss_ = np.clip((np.arange(w) - x0r) / max(1.0, x1r - x0r), 0, 1)
            thick = 5.0 * ppm * np.sin(np.pi * ss_) ** 0.7
            rowsr = yy_full(h, w)
            ribbon = (rowsr < (ybot - 1.8 * ppm)[None, :]) & (rowsr > (ybot - 1.8 * ppm - thick)[None, :])
            ribbon &= beard_reg & (np.arange(w)[None, :] > x0r + 0.12 * (x1r - x0r)) & (np.arange(w)[None, :] < x1r - 0.12 * (x1r - x0r))
            ribbon = _open(ribbon, 0.9 * ppm)
        reg_b = beard_reg & ~_close(ribbon, 0.5 * ppm)
        flow_ink |= _flow_strokes(reg_b, fxb, fyb, spm, ppm, rng, {2.6: (10, 18), 2.8: (10, 18), 3.4: (8, 14), 5.2: (6, 10)}, 1.7)
        flow_ink |= ribbon
        # chin contour: the beard silhouette's lower edge in long runs with short lifts
        from skimage import measure as skm
        cs_ = skm.find_contours(_gauss(beard_reg.astype(np.float32), 1.0 * ppm), 0.5)
        if cs_:
            cmax = max(cs_, key=len)[:, ::-1]
            pc, _ = _resample(cmax, 1.0)
            pc = _smooth_poly(pc, int(2.0 * ppm))
            lowhalf = pc[:, 1] > yc_b + 2 * ppm
            iy_c = np.clip(pc[:, 1].astype(int), 0, h - 1)
            ix_c = np.clip(pc[:, 0].astype(int), 0, w - 1)
            lowhalf &= ~lip_far[iy_c, ix_c]
            i_ = 0
            n_c = len(pc)
            cimg = Image.new("L", (w, h), 0)
            cdr = ImageDraw.Draw(cimg)
            while i_ < n_c:
                if not lowhalf[i_]:
                    i_ += 1
                    continue
                j_ = min(n_c, i_ + int(rng.uniform(14, 28) * ppm))
                seg_ = np.arange(i_, j_)
                seg_ = seg_[lowhalf[seg_]]
                if len(seg_) > 4 * ppm:
                    _stamp(cdr, pc[seg_], _profile(len(seg_), 1.9 * ppm, LW * ppm))
                i_ = j_ + int(1.5 * ppm)
            chin_ln = np.asarray(cimg) > 0
    # moustache: the darkest shape of the lower face. A solid core under the nose wings, then flow strokes at pitch 2.6 mm
    # out and down from the philtrum to tapering points at the photo's corners, 2-3 thin white strands inside (FL 6)
    if mous_sym.sum() > 100:
        xm = np.nonzero(mous_sym)[1]
        rw_ = max(1.0, float(np.abs(xm - xc).max()))
        aa_ = np.clip(np.abs(xx_full(h, w) - xc) / rw_, 0, 1)
        sg_ = np.where(xx_full(h, w) >= xc, 1.0, -1.0)
        mfx = sg_ * (0.85 + 0.9 * aa_)
        mfy = 0.60 - 0.10 * aa_
        mn = np.hypot(mfx, mfy)
        mfx, mfy = (mfx / mn).astype(np.float32), (mfy / mn).astype(np.float32)
        msp = np.full((h, w), 2.6, np.float32)
        mreg = mous_sym & ~nose_clear
        if nostril_pts:
            ny_m = float(np.mean([q[1] for q in nostril_pts]))
            mc = _open(mous_sym & (L12 < face_med - 0.16) & (ys_ > ny_m + 3.0 * ppm) & (ys_ < ny_m + 13.0 * ppm) & ~nose_clear, 1.6 * ppm)
            black |= mc
            mreg = mreg & ~mc
        flow_ink |= _flow_strokes(mreg, mfx, mfy, msp, ppm, rng, {2.6: (10, 18), 2.8: (10, 18), 3.4: (10, 18), 5.2: (10, 18)}, 1.6, seed_mm=1.1)
        strands_white |= _flow_strands(mous_sym, mfx, mfy, ppm, rng, 3, (6.0, 10.0), 2.4, 1.1, sep_mm=7.0, curv=1.0 / 25.0, max_straight_mm=6.0)
    nostril = np.zeros((h, w), bool)
    # ears: bowl as a small solid dark shape (FG 5 Ear)
    ear_boxes = [(bx - 0.14 * bw, by + 0.32 * bh, bx + 0.03 * bw, by + 0.66 * bh),
                 (bx + 0.97 * bw, by + 0.32 * bh, bx + 1.14 * bw, by + 0.66 * bh)]
    for (a, b, c, d) in ear_boxes:
        eb_ = np.zeros((h, w), bool)
        eb_[int(max(0, b)):int(min(h, d)), int(max(0, a)):int(min(w, c))] = True
        eb_ &= mask
        if eb_.sum() > 200:
            cut = np.percentile(L06[eb_], 14)
            bowl = _open(eb_ & (L06 <= cut), 0.7 * ppm)
            lb_, nbw = ndi.label(bowl)
            if nbw:
                szb = ndi.sum(bowl, lb_, index=np.arange(1, nbw + 1))
                k_ = 1 + int(np.argmax(szb))
                if szb[k_ - 1] >= 3.0 * ppm * ppm:
                    # a small solid bowl (an ellipse with the found shape's axes, at most 14 mm2), not the raw blob
                    yy_, xx_ = np.nonzero(lb_ == k_)
                    cxy = np.cov(np.stack([xx_, yy_]).astype(float))
                    ev, evec = np.linalg.eigh(cxy)
                    ax = 2.0 * np.sqrt(np.maximum(ev, 1e-6))
                    sc_ = min(1.0, math.sqrt(14.0 * ppm * ppm / (math.pi * ax[0] * ax[1])))
                    ax = np.maximum(ax * sc_, 1.2 * ppm)
                    tt = np.linspace(0, 2 * math.pi, 40)
                    ell = (evec @ np.stack([ax[0] * np.cos(tt), ax[1] * np.sin(tt)])).T + np.array([xx_.mean(), yy_.mean()])
                    eimg = Image.new("L", (w, h), 0)
                    ImageDraw.Draw(eimg).polygon([tuple(q) for q in ell], fill=255)
                    black |= (np.asarray(eimg) > 0) & mask

    # shade-side band: one open-middle band of hatch on the side away from the light (FG 12; red team r1 #3)
    L3s = _up_f(_nblur(Ll, mlo, 3.0 * ppl), f, h, w)
    shade_half = (xs > bx + 0.5 * bw) if light_left else (xs < bx + 0.5 * bw)
    shade_band = face_in & shade_half & (L3s < face_med - 0.05) & ~clear_f & ~mass & ~teeth_only & ~black
    shade_band = _open(shade_band, 2.0 * ppm)
    _lb, _nb = ndi.label(shade_band)
    if _nb:
        _sz = ndi.sum(shade_band, _lb, index=np.arange(1, _nb + 1))
        _ok = np.zeros(_nb + 1, bool)
        _ok[1:] = _sz >= 90 * ppm * ppm
        shade_band = _ok[_lb]

    # -------- levels
    blo = (black.reshape(h // f, f, w // f, f).mean(axis=(1, 3)) > 0.5) if f > 1 else black
    vals = Lm[mlo & ~blo]
    redo = 0
    lvl_full = None
    tone_share = 0.0
    layers = {}
    for attempt in range(2):
        lvl_lo = band_levels(3.0 * attempt)
        lv = [_upsample_bool(lvl_lo >= k, f)[:h, :w] for k in (1, 2, 3)]
        lvl = lv[0].astype(np.uint8) + lv[1].astype(np.uint8) + lv[2].astype(np.uint8)
        lvl[~mask] = 0
        # drop open patches under 40 mm2 and middle patches under 20 mm2 (spottiness, RE 6)
        for kk, amin in ((1, 40.0), (2, 20.0)):
            pm = lvl == kk
            lp, npz = ndi.label(pm)
            if npz:
                szp = ndi.sum(pm, lp, index=np.arange(1, npz + 1))
                bad = np.zeros(npz + 1, bool)
                bad[1:] = szp < amin * ppm * ppm
                lvl[bad[lp]] = 0
        lvl[shade_band & (lvl < 2)] = 2
        lvl[mass_hatch] = 3
        lvl[teeth_only] = 0
        lvl[black] = 3

        # -------- hatch grid (FP 3.6)
        pitch, wh = PITCH * ppm, LW * ppm
        if light_left:
            u = (yy_full(h, w) - xx_full(h, w)) / math.sqrt(2.0)
            v = (xx_full(h, w) + yy_full(h, w)) / math.sqrt(2.0)
        else:
            u = (yy_full(h, w) + xx_full(h, w)) / math.sqrt(2.0)
            v = (xx_full(h, w) - yy_full(h, w)) / math.sqrt(2.0)
        u = u + 0.0
        kf = np.rint(u / pitch)
        k = kf.astype(np.int32)
        k0 = k - k.min()
        nk = int(k0.max()) + 1
        vmin = float(v.min())
        nv = int((v.max() - vmin) / (6.0 * ppm)) + 3
        noise = rng.uniform(-1, 1, (nk, nv)).astype(np.float32) * (0.15 * ppm)
        vv = (v - vmin) / (6.0 * ppm)
        v0 = np.floor(vv).astype(np.int32)
        fr = (vv - v0).astype(np.float32)
        jit = noise[k0, v0] * (1 - fr) + noise[k0, v0 + 1] * fr
        d = np.abs(u - kf * pitch - jit)
        on_line = d < wh / 2.0
        allowed = (lvl == 3) | ((lvl == 2) & (k % 2 == 0)) | ((lvl == 1) & (k % 3 == 0))
        hatch = on_line & allowed & mask & ~teeth_only & ~clear_f & ~lip_clear & ~nose_clear
        hatch &= ~ndi.binary_dilation(mass_hatch, iterations=int(1.0 * ppm))
        if dark_hair:
            hatch &= ~hair_zone          # hair is one solid mass or bare paper, never a hatch mosaic (red team r3)
        # drop short strokes < 3 mm
        lh, nh = ndi.label(hatch)
        if nh:
            szh = ndi.sum(hatch, lh, index=np.arange(1, nh + 1))
            okc = np.zeros(nh + 1, bool)
            okc[1:] = szh >= 5.0 * LW * ppm * ppm
            hatch = okc[lh]
        # tone share check
        inkp = (hatch | black)
        tone_share = float(inkp[mask].mean()) if mask.any() else 0.0
        if tone_share > 0.50 and attempt == 0:
            redo = 1
            continue
        break

    # -------- vignette: marks fade out below the chin, collar and suit never show
    fade0 = by + 1.18 * bh
    fade1 = h - 2.0 * ppm
    nz = _smooth_noise_1d(w, rng, 14 * ppm)
    y_end = fade0 + 0.4 * (fade1 - fade0) * (0.2 + 0.8 * nz)
    side = np.clip((np.abs(np.arange(w) - w / 2.0) / w - 0.15) / 0.10, 0, 1)
    y_end = y_end - side * (0.20 * bh + (y_end - fade0))
    keep = (np.arange(h)[:, None] < y_end[None, :])
    keep &= (np.arange(w)[None, :] > 2 * ppm) & (np.arange(w)[None, :] < w - 2 * ppm) & (np.arange(h)[:, None] > 1.5 * ppm)
    hatch &= keep
    black &= keep
    flow_ink &= keep & ~teeth_only & ~clear_f
    chin_ln &= keep

    # -------- surface lines from the photo's own edges (FP 6)
    from skimage.feature import canny
    emask = _open(mask, 1.5 * ppm) if False else (ndi.distance_transform_edt(mask) > 1.5 * ppm)
    gm = ndi.gaussian_gradient_magnitude(L, 0.3 * ppm)
    edges = canny(L, sigma=0.3 * ppm, low_threshold=0.7, high_threshold=0.9, use_quantiles=True, mask=emask)
    chains = _walk_chains(edges, int(4.0 * ppm))
    lines = []
    for ch_ in chains:
        sm = _smooth_poly(ch_, 11)
        seglen = float(np.hypot(*np.diff(sm, axis=0).T).sum()) / ppm
        if seglen < 4.0:
            continue
        iy = np.clip(sm[:, 1].astype(int), 0, h - 1)
        ix = np.clip(sm[:, 0].astype(int), 0, w - 1)
        g = float(gm[iy, ix].mean())
        zone = int(np.median(lvl[iy, ix]))
        lines.append({"pts": sm, "g": g, "len": seglen, "zone": zone, "c": sm.mean(0)})
    if lines:
        order = np.argsort(np.argsort([l["g"] for l in lines]))
        for l, rk in zip(lines, order):
            l["rank"] = rk / max(1, len(lines) - 1)
    coi = (bx + 0.15 * bw, by + 0.28 * bh, bx + 0.85 * bw, by + 0.85 * bh)

    def in_box(c, b):
        return b[0] <= c[0] <= b[2] and b[1] <= c[1] <= b[3]

    def horiz(l, tol_deg):
        p = l["pts"]
        dx, dy = p[-1] - p[0]
        return abs(math.degrees(math.atan2(dy, dx))) % 180 < tol_deg or abs(math.degrees(math.atan2(dy, dx))) % 180 > 180 - tol_deg

    for l in lines:
        iy_ = np.clip(l["pts"][:, 1].astype(int), 0, h - 1)
        ix_ = np.clip(l["pts"][:, 0].astype(int), 0, w - 1)
        l["in_clear"] = float(clear_f[iy_, ix_].mean()) > 0.3
    lines = [l for l in lines if not l["in_clear"]]
    beard_near = ndi.distance_transform_edt(~(beard_m | core | mous_sym)) <= 2.0 * ppm
    lines = [l for l in lines if not beard_near[int(np.clip(l["c"][1], 0, h - 1)), int(np.clip(l["c"][0], 0, w - 1))]]
    for (a, b, c, d) in ear_boxes:
        inside = [l for l in lines if in_box(l["c"], (a, b, c, d)) and l["len"] >= 6.0 and l.get("role") is None]
        if inside:
            max(inside, key=lambda l: l["g"] * l["len"])["role"] = "ear"
    mb = (bx + 0.25 * bw, by + 0.68 * bh, bx + 0.75 * bw, by + 0.85 * bh)
    mouths = [l for l in lines if in_box(l["c"], mb) and horiz(l, 25) and l["len"] >= 0.12 * fwmm and l.get("role") is None]
    if mouths:
        max(mouths, key=lambda l: l["g"] * l["len"])["role"] = "lip"
    thr_shift = (0.5 - detail) * 0.3
    zone_thr = {0: 0.80, 1: 0.66, 2: 0.56, 3: 0.76}
    kept = []
    for l in lines:
        if l.get("role"):
            kept.append(l)
            continue
        t = zone_thr[min(3, l["zone"])] + thr_shift
        if in_box(l["c"], coi):
            t -= 0.18
        if l["rank"] > t:
            kept.append(l)
    inbox = sorted([l for l in kept if in_box(l["c"], coi) and not l.get("role")], key=lambda l: -l["rank"])
    drop = {id(l) for l in inbox[6:]}
    kept = [l for l in kept if id(l) not in drop]

    # at most one forehead line, and only if strong (FL 9: furrows only for age)
    fb = (bx + 0.10 * bw, by - 0.02 * bh, bx + 0.90 * bw, by + 0.22 * bh)
    fh_ = [l for l in kept if in_box(l["c"], fb) and not l.get("role")]
    if fh_:
        top = max(fh_, key=lambda l: l["rank"] * (1.0 if horiz(l, 25) else 0.0))
        keep_one = top if (top["rank"] > 0.85 and horiz(top, 25)) else None
        fh_ids = {id(x) for x in fh_}
        kept = [l for l in kept if id(l) not in fh_ids or l is keep_one]

    line_img = Image.new("L", (w, h), 0)
    ld = ImageDraw.Draw(line_img)
    for l in kept:
        p, t = _resample(l["pts"], 1.0)
        n = len(p)
        role = l.get("role")
        if role == "upper":
            wd = _profile(n, 2.2 * ppm, LW * ppm)
        elif role == "ear":
            wd = _profile(n, 2.1 * ppm, LW * ppm)
        elif role == "lower":
            wd = np.full(n, LW * ppm)
        elif role == "lip":
            wd = _profile(n, 2.5 * ppm, LW * ppm)
        elif role == "brow":
            ramp = np.linspace(2.0, LW, n) * ppm
            near_right = l["pts"][-1][0] > l["pts"][0][0]
            if l.get("nose_right") != near_right:
                ramp = ramp[::-1]
            wd = ramp
        else:
            base = LW + 0.25 * l["rank"] + (0.15 if in_box(l["c"], coi) else 0.0)
            wd = np.full(n, base * ppm)
        _stamp(ld, p, wd)
    if teeth_only.any():
        cols = np.nonzero(teeth_only.any(axis=0))[0]
        if len(cols) > 10:
            bot = np.array([np.nonzero(teeth_only[:, c_])[0].max() for c_ in cols], float) + 0.5 * ppm
            lipp = _smooth_poly(np.stack([cols.astype(float), bot], 1), int(2.5 * ppm))
            pp, _ = _resample(lipp, 1.0)
            _stamp(ld, pp, _profile(len(pp), 2.5 * ppm, LW * ppm))
    # two nasolabial folds, each found as the darkest ridge in a corridor from the nose wing to the mouth corner
    L12s = L12
    if len(nostril_pts) == 2 and mous.any():
        ycs, xcs = np.nonzero(mous)
        for (nx, ny, sg) in nostril_pts:
            ci = int(np.argmin(xcs)) if sg < 0 else int(np.argmax(xcs))
            ex, ey = xcs[ci] + sg * 1.5 * ppm, float(ycs[ci])
            sx, sy = nx + sg * 6.5 * ppm, ny + 0.5 * ppm
            if ey - sy < 8 * ppm:
                continue
            yp = np.arange(int(sy), int(ey))
            xl = sx + (ex - sx) * (yp - sy) / (ey - sy)
            xp = []
            for yv, xv in zip(yp, xl):
                a_, b_ = int(max(0, xv - 3 * ppm)), int(min(w - 1, xv + 3 * ppm))
                xp.append(a_ + int(np.argmin(L12s[yv, a_:b_ + 1])) if b_ > a_ else xv)
            path = _smooth_poly(np.stack([_gauss(np.array(xp, float), 2 * ppm), yp.astype(float)], 1), int(7 * ppm))
            ix_ = np.clip(path[:, 0].astype(int), 0, w - 1)
            if float(L12s[yp, ix_].mean()) < face_med - 0.03:
                _stamp(fd, path, _profile(len(path), 2.0 * ppm, LW * ppm))
    feat_m = (np.asarray(fdraw) > 0) & mask
    lines_m = ((np.asarray(line_img) > 0) & mask & keep) | feat_m

    # -------- outline (FP 7)
    outline_m = _outline(mask, lvl, black, L, ppm, light_left, rng, h, w, face_box)
    outline_m &= keep

    # -------- composite and finish (FP step 11)
    ink = hatch | lines_m | outline_m | black | flow_ink | chin_ln
    white = catch | strands_white | teeth_only
    ink &= ~white
    ink |= extra_black & mask
    r = FLOOR / 2.0 * ppm
    rg = max(FLOOR, float(gap_mm)) / 2.0 * ppm   # gap floor grows with the roller's draft (R20, R21)
    ink = _open(ink, r)
    ink = _close(ink, rg)
    ink = _open(ink, r)
    # orphan fragments: small pieces away from every drawn feature are deleted (red team r1 #9)
    prot = ndi.distance_transform_edt(~(feat_m | catch | teeth_only | flow_ink | chin_ln)) <= 3.0 * ppm
    lab_i, ni = ndi.label(ink)
    if ni:
        objs = ndi.find_objects(lab_i)
        szi = ndi.sum(ink, lab_i, index=np.arange(1, ni + 1))
        pr = ndi.maximum(prot, lab_i, index=np.arange(1, ni + 1))
        for k_, (sl, a_, p_) in enumerate(zip(objs, szi, pr)):
            dim = max(sl[0].stop - sl[0].start, sl[1].stop - sl[1].start) / ppm
            if a_ < 37.0 * ppm * ppm and not p_:
                ink[sl] &= ~(lab_i[sl] == k_ + 1)
    # specks under 1 mm^2
    lab_i, ni = ndi.label(ink)
    if ni:
        szi = ndi.sum(ink, lab_i, index=np.arange(1, ni + 1))
        okc = np.zeros(ni + 1, bool)
        okc[1:] = szi >= 1.0 * ppm * ppm
        ink = okc[lab_i]

    rep = {
        "face_found": bool(geo["found"]), "face_path": geo["path"], "light_side": light_side,
        "blacks": int(_count_large(ink & (black | ndi.binary_dilation(black, iterations=1)), head_area)),
        "tone_share": float(ink[mask].mean()) if mask.any() else 0.0,
        "lines_kept": int(len(kept)), "px_per_mm": float(ppm), "dark_hair": bool(dark_hair),
        "tile_w_mm": float(W), "tile_h_mm": float(Hmm), "redo_tone": int(redo),
        "seconds": round(time.time() - t0, 2),
    }
    if measure:
        zone = ndi.binary_dilation(mask, iterations=int(4 * ppm))
        rep["min_line_mm"], rep["min_gap_mm"] = measure_floor(ink, zone, ppm)
    if debug:
        layers = {"hatch": hatch, "lines": lines_m, "outline": outline_m, "black": black, "mask": mask,
                  "white": white, "lvl": lvl, "feat": feat_m, "solid": solid_mass, "dbg": {"eye_cx": eye_cx, "nostrils": nostril_pts}, "teeth": teeth_only, "beard": beard_only, "core": core, "mous": mous, "mhatch": mous_hatch, "beard_reg": beard_reg, "flow": flow_ink, "ribbon": ribbon, "face_med": face_med}
    return Sketch(mask=ink, report=rep, crop_rgb=rgb, face_box=face_box, ppm=float(ppm), layers=layers)


def _count_large(m, head_area):
    lab, n = ndi.label(m)
    if n == 0:
        return 0
    sizes = ndi.sum(m, lab, index=np.arange(1, n + 1))
    return int((sizes > 0.02 * head_area).sum())


_YX = {}


def xx_full(h, w):
    key = ("x", h, w)
    if key not in _YX:
        _YX.clear()
        _YX[key] = np.broadcast_to(np.arange(w, dtype=np.float32)[None, :], (h, w))
    return _YX[key]


def yy_full(h, w):
    return np.broadcast_to(np.arange(h, dtype=np.float32)[:, None], (h, w))


def _outline(mask, lvl, black, L, ppm, light_left, rng, h, w, face_box):
    """Outline walked round the subject mask, weight by who owns the line (LO, FP 7)."""
    from skimage import measure as skm
    m = _gauss(mask.astype(np.float32), 0.8 * ppm)
    cs = skm.find_contours(m, 0.5)
    img = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(img)
    lightv = np.array([-1.0, -1.0]) / math.sqrt(2) if light_left else np.array([1.0, -1.0]) / math.sqrt(2)
    bx, by, bw, bh = face_box
    for c in cs:
        pts = c[:, ::-1]                       # x, y
        if len(pts) < 30 * ppm * 0.5:
            continue
        closed = np.hypot(*(pts[0] - pts[-1])) < 2.0
        # resample at 1 px, smooth with a 2 mm moving average
        p, s = _resample(pts, 1.0)
        if len(p) < 40:
            continue
        k = int(2.0 * ppm) | 1
        if closed:
            pad = np.concatenate([p[-k:], p, p[:k]])
            a = np.stack([np.convolve(pad[:, 0], np.ones(k) / k, "same"), np.convolve(pad[:, 1], np.ones(k) / k, "same")], 1)[k:-k]
        else:
            a = _smooth_poly(p, k)
        tang = np.gradient(a, axis=0)
        tn = np.hypot(tang[:, 0], tang[:, 1]) + 1e-6
        tang = tang / tn[:, None]
        nrm = np.stack([tang[:, 1], -tang[:, 0]], 1)
        # point normal outward: test the mask a little way along it
        probe = (a + nrm * 2.5)
        pi = np.clip(probe.round().astype(int), [0, 0], [w - 1, h - 1])
        outside = ~mask[pi[:, 1], pi[:, 0]]
        if outside.mean() < 0.5:
            nrm = -nrm
        n_ = len(a)
        width = np.full(n_, 1.3)
        ins = np.clip((a - nrm * 1.5 * ppm).round().astype(int), [0, 0], [w - 1, h - 1])
        lv_in = lvl[ins[:, 1], ins[:, 0]]
        blk_in = black[ins[:, 1], ins[:, 0]]
        face = nrm @ lightv
        width = np.where(face > 0.35, 2.0, np.where(face < -0.35, LW, 1.7))
        width = np.where(lv_in == 2, np.minimum(width, LW), width)
        width = np.where(blk_in, 0.0, width)
        # vignette towards the bottom edge
        yb = a[:, 1] / h
        width = np.where(yb > 0.97, 0.0, width)
        width = np.where(a[:, 0] < 2 * ppm, 0.0, width)
        width = np.where(a[:, 0] > w - 2 * ppm, 0.0, width)
        # runs and lifts: long runs, lifts only at the lit side (FP 10: runs too short read as dashed)
        lit = face > 0.2
        i = 0
        while i < n_:
            if width[i] <= 0:
                i += 1
                continue
            heavy = width[i] >= 2.0
            run = rng.uniform(12, 28) if heavy else rng.uniform(5, 12)
            j = min(n_, i + int(run * ppm))
            ext = min(n_, j + int(6 * ppm))
            while j < ext and not lit[min(j, n_ - 1)]:
                j += 1
            seg = np.arange(i, min(j, n_))
            seg = seg[width[seg] > 0]
            if len(seg) > 3 * ppm:
                ww = _smooth_poly(np.stack([width[seg], width[seg]], 1), 9)[:, 0]
                ww = np.maximum(ww, LW) * ppm
                _stamp(dr, a[seg], ww)
            i = j + int(rng.uniform(1.3, 1.6) * ppm)
    return np.asarray(img) > 0


def measure_floor(ink, zone, ppm):
    """Thinnest line and narrowest gap (mm), by opening with growing disks. Tolerance 0.3% of the area lost."""
    def width_of(m, region):
        if not m.any():
            return 99.0
        d = ndi.distance_transform_edt(m)
        best = 0.0
        tot = float((m & region).sum())
        for diam_px in (0.75 * ppm, 0.9 * ppm, 1.0 * ppm, 1.1 * ppm, 1.25 * ppm):
            r = diam_px / 2.0
            e = d > r
            op = m & (ndi.distance_transform_edt(~e) <= r)
            lost = float(((m & ~op) & region).sum()) / max(tot, 1.0)
            if lost <= 0.003:
                best = diam_px
            else:
                break
        return best / ppm
    return round(width_of(ink, zone), 3), round(width_of(~ink, zone & True), 3)
