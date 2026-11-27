"""Cookie cutter + embosser: art in, printable cutter STL out.

Pure shapely / numpy / scipy / scikit-image / trimesh-core, so it runs in Pyodide as well as locally
(no earcut, no manifold3d, no cv2, no matplotlib). Frame: mm, x right, y up; z up with the back plane on
the bed (z = 0) and the cutting edge at z = wall_mm. The art is flipped in x once, because the stamp is
pressed face down: the printed cutter is the mirror of the cookie.

Route: art.Art -> ink (even-odd polygons) -> outline + inside lines -> uniform 1.2 mm ribs (skeleton) ->
rules gate (runs last: dots, pockets, dough land) -> back bridges -> stacked slabs -> closed mesh.
"""
from __future__ import annotations
import hashlib
import math
import time
from collections import OrderedDict
from dataclasses import dataclass, asdict

import numpy as np
import shapely
import shapely.affinity
from shapely.geometry import Polygon, LineString, Point


FRIENDLY = "This drawing tripped up the cutter maker. Try a slightly different size or a simpler drawing."


class CookieError(ValueError):
    pass


@dataclass
class CookieParams:
    size_mm: float = 80.0      # longest side of the cut shape
    dough_mm: float = 6.0      # thickness the dough is rolled to
    imprint_mm: float = 2.5    # how deep the inside lines press
    wall_mm: float = 14.0      # height of the cutter, back to cutting edge
    # R86 export anyway: read by export_bytes only. Neither is in to_dict(), so no preview, cache key or echo sees them.
    export_anyway: bool = False
    pitch_scale: float = 1.0   # >1 = coarser working grid; only the export retry sets it

    LIMITS = {"size_mm": (30.0, 200.0), "dough_mm": (3.0, 12.0), "imprint_mm": (0.5, 6.0), "wall_mm": (10.0, 30.0)}

    @classmethod
    def from_dict(cls, d: dict | None):
        d = dict(d or {})
        out, notes = {}, []
        for k, (lo, hi) in cls.LIMITS.items():
            v = d.get(k, getattr(cls, k))
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise CookieError("%s must be a number" % k)
            if not math.isfinite(v):
                raise CookieError("%s must be a number" % k)
            c = min(hi, max(lo, v))
            if c != v:
                notes.append("%s limited to %g (range %g to %g)" % (k, c, lo, hi))
            out[k] = c
        # the imprint must leave at least 2 mm of dough under it, and the ribs must stand clear of the back
        if out["imprint_mm"] > out["dough_mm"] - 2.0:
            out["imprint_mm"] = round(out["dough_mm"] - 2.0, 2)
            notes.append("imprint depth limited to %g mm (2 mm of dough must stay under it)" % out["imprint_mm"])
        need = out["dough_mm"] - out["imprint_mm"] + 2.4 + 4.0
        if out["wall_mm"] < need:
            out["wall_mm"] = round(need, 1)
            notes.append("cutter height raised to %g mm so the lines stand 4 mm off the back" % out["wall_mm"])
        p = cls(**out)
        p.notes = notes
        v = d.get("export_anyway", False)
        p.export_anyway = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
        return p

    def to_dict(self):
        d = asdict(self)
        d.pop("export_anyway", None)
        d.pop("pitch_scale", None)
        return d


# fixed design values (red-team fixes); dough/imprint/wall come from CookieParams
P = dict(H=14.0, dough=6.0, imprint=2.5, base_t=2.4, rim_w=3.5, wall_back=1.6, wall_tip=0.86,
         rib_w=1.2, land=3.0, pocket=5.0, dot=5.0, bar_w=6.0, maxrun=35.0, window=8.0,
         size=80.0, grid=0.002, simp=0.04, outline=0.5)


def design(cp: CookieParams) -> dict:
    p = dict(P)
    p.update(H=cp.wall_mm, dough=cp.dough_mm, imprint=cp.imprint_mm, size=cp.size_mm)
    return p




def _polys(g):
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [p for x in getattr(g, "geoms", []) for p in _polys(x)]


def mirror(g, cx):
    """Flip x about cx (the cutter is the mirror of the cookie)."""
    return shapely.affinity.scale(g, xfact=-1, yfact=1, origin=(cx, 0))


GRID = 0.002   # mm: every polygon corner sits on this grid, every overlay runs on it


# ---------------------------------------------------------------- raster toolbox
# GEOS buffers and overlays abort the whole Pyodide runtime on a topology error (shapely 2.0.6 on GEOS 3.12),
# and an exception cannot be caught there. So all morphology (offset, opening, closing, taper steps, rim,
# land / pocket / dot checks) is done on a raster with Euclidean distance transforms. shapely is used only for
# polygons built from contours, a few straight bars, and fixed-grid (snap-rounding) union / difference.
class Grid:
    def __init__(self, x0, y0, px, W, H):
        self.x0, self.y0, self.px, self.W, self.H = x0, y0, px, W, H

    @property
    def shape(self):
        return (self.H, self.W)

    def xs(self):
        return self.x0 + (np.arange(self.W) + 0.5) * self.px

    def ys(self):
        return self.y0 + (np.arange(self.H) + 0.5) * self.px

    def to_px(self, x, y):
        return (np.asarray(x) - self.x0) / self.px - 0.5, (np.asarray(y) - self.y0) / self.px - 0.5   # col, row

    def to_mm(self, col, row):
        return self.x0 + (np.asarray(col) + 0.5) * self.px, self.y0 + (np.asarray(row) + 0.5) * self.px


def _edt(m):
    from scipy import ndimage as ndi
    return ndi.distance_transform_edt(m)


def dilate(m, r, g):
    """Pixels within r mm of the mask (distance to its edge, sub-pixel corrected)."""
    if not m.any():
        return m.copy()
    return (_edt(~m) - 0.5) * g.px <= r


def erode(m, r, g):
    if not m.any():
        return m.copy()
    return (_edt(m) - 0.5) * g.px > r


def opening(m, r, g):
    return dilate(erode(m, r, g), r, g) & m if m.any() else m.copy()


def sdf(m, g):
    """Signed distance in mm (negative inside); the zero level sits half a pixel out from the mask's pixels."""
    if not m.any():
        return np.full(m.shape, 1e3, np.float32)
    if m.all():
        return np.full(m.shape, -1e3, np.float32)
    out = _edt(~m)
    inn = _edt(m)
    return (np.where(m, -(inn - 0.5), out - 0.5) * g.px).astype(np.float32)


def _label(m):
    from scipy import ndimage as ndi
    return ndi.label(m, structure=np.ones((3, 3), int))


def _comps(m, min_mm2, g):
    """[(label, area_mm2)] of connected pieces of at least min_mm2."""
    lab, n = _label(m)
    if not n:
        return lab, []
    cnt = np.bincount(lab.ravel(), minlength=n + 1)[1:]
    a = cnt * g.px * g.px
    return lab, [(i + 1, float(a[i])) for i in range(n) if a[i] >= min_mm2]


def drop_small(m, min_mm2, g):
    lab, keep = _comps(m, min_mm2, g)
    out = np.zeros_like(m)
    for i, _ in keep:
        out |= lab == i
    return out


def inscribed_d(comp, g):
    """Diameter of the biggest circle inside a pixel piece, mm, and where its centre is (col, row)."""
    d = _edt(comp)
    k = int(np.argmax(d))
    r, c = divmod(k, comp.shape[1])
    return 2 * (float(d[r, c]) - 0.5) * g.px, (c, r)


def seg_mask(g, a, b, halfw, ext=0.0):
    """Flat-ended bar of half width halfw around the segment a-b (mm), as a raster."""
    ax, ay = a; bx, by = b
    L = math.hypot(bx - ax, by - ay)
    out = np.zeros(g.shape, bool)
    if L < 1e-9:
        return out
    ux, uy = (bx - ax) / L, (by - ay) / L
    xs, ys = g.xs(), g.ys()
    xlo = min(ax, bx) - halfw - ext - g.px; xhi = max(ax, bx) + halfw + ext + g.px
    ylo = min(ay, by) - halfw - ext - g.px; yhi = max(ay, by) + halfw + ext + g.px
    ci = np.nonzero((xs >= xlo) & (xs <= xhi))[0]
    ri = np.nonzero((ys >= ylo) & (ys <= yhi))[0]
    if not len(ci) or not len(ri):
        return out
    X, Y = np.meshgrid(xs[ci], ys[ri])
    t = (X - ax) * ux + (Y - ay) * uy
    n = np.abs(-(X - ax) * uy + (Y - ay) * ux)
    out[ri[0]:ri[-1] + 1, ci[0]:ci[-1] + 1] = (n <= halfw) & (t >= -ext) & (t <= L + ext)
    return out


# ---------------------------------------------------------------- contours -> polygons
def _snap_ring(c):
    c = np.round(np.asarray(c) / GRID) * GRID
    keep = np.ones(len(c), bool)
    keep[1:] = np.any(np.diff(c, axis=0) != 0, axis=1)
    return c[keep]


def _shoelace(c):
    x, y = c[:, 0], c[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def level_polys(field, level, g, tol=0.03):
    """Level set of a field as polygons: marching squares, Douglas-Peucker (numpy), corners snapped to
    GRID, holes nested by containment. No GEOS morphology is involved."""
    from skimage import measure
    f = np.pad(np.asarray(field, np.float32), 1, mode="constant", constant_values=1e3)   # shapes never touch the border
    rings = []
    for c in measure.find_contours(f, level):
        if len(c) < 4 or not np.allclose(c[0], c[-1]):
            continue
        col, row = c[:, 1] - 1, c[:, 0] - 1
        x, y = g.to_mm(col, row)
        pts = np.column_stack([x, y])
        for t in (tol, tol / 3, 0.0):
            s = measure.approximate_polygon(pts, t) if t > 0 else pts
            s = _snap_ring(s)
            if len(s) >= 4 and abs(_shoelace(s[:-1])) > 1e-4 and Polygon(s).is_valid:
                rings.append(s)
                break
    if not rings:
        return Polygon()
    rings.sort(key=lambda c: -abs(_shoelace(c[:-1])))
    polys = [Polygon(r) for r in rings]
    depth, parent = [], []
    for i, r in enumerate(rings):
        pt = Point(r[0])
        cont = [j for j in range(i) if polys[j].contains(pt)]
        depth.append(len(cont))
        parent.append(cont[-1] if cont else None)     # smallest container (sorted by area)
    shells = {i: [] for i in range(len(rings)) if depth[i] % 2 == 0}
    for i in range(len(rings)):
        if depth[i] % 2 == 1 and parent[i] in shells:
            shells[parent[i]].append(rings[i])
    out = [Polygon(rings[i], holes) for i, holes in shells.items()]
    return out[0] if len(out) == 1 else shapely.MultiPolygon(out)


def _union(geoms):
    gs = [x for x in geoms if x is not None and not x.is_empty]
    if not gs:
        return Polygon()
    return shapely.union_all(gs, grid_size=GRID)


def _diff(a, b):
    return shapely.difference(a, b, grid_size=GRID)


# ---------------------------------------------------------------- art -> raster parts
def _art_polys(art, size_mm):
    """Flattened art subpaths in mm (art frame at the origin, y up), x flipped (the stamp is pressed face
    down, so the printed cutter is the mirror of the cookie), longest side size_mm."""
    x0, y0, x1, y1 = art.frame
    scale = size_mm / max(x1 - x0, y1 - y0, 1e-9)
    polys, _ = art.flatten(scale)
    W = (x1 - x0) * scale
    out = []
    for a in polys:
        a = (np.asarray(a, float) - [x0, y0]) * scale
        a[:, 0] = W - a[:, 0]
        if len(a) >= 3:
            out.append(a)
    if not out:
        raise CookieError("no art found in the picture")
    return out, W, (y1 - y0) * scale


def _raster_ink(polys, g):
    """Even-odd fill of the subpaths."""
    from skimage.draw import polygon as fill
    m = np.zeros(g.shape, bool)
    for a in polys:
        col, row = g.to_px(a[:, 0], a[:, 1])
        rr, cc = fill(row, col, g.shape)
        m[rr, cc] ^= True
    return m


def _pitch(size_mm):
    return float(min(0.2, max(0.08, size_mm / 560.0)))


def _parts(polys, g, p):
    """ink raster -> (S, R_raw, solid): S = outline loop filled and pulled in 0.5 mm."""
    from scipy import ndimage as ndi
    ink = _raster_ink(polys, g)
    lab, n = _label(ink)
    if not n:
        raise CookieError("no art found in the picture")
    best, ba = None, -1
    for i, sl in enumerate(ndi.find_objects(lab)):
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if h * w > ba:
            best, ba = i + 1, h * w
    S0 = ndi.binary_fill_holes(lab == best)
    solid = ink[S0].sum() / max(S0.sum(), 1) > 0.75
    if solid:
        return S0, np.zeros_like(ink), True
    S = erode(S0, p["outline"], g)
    if not S.any():
        raise CookieError("the outline is too thin to use")
    lab2, n2 = _label(S)
    if n2 > 1:
        S = lab2 == (1 + int(np.argmax(np.bincount(lab2.ravel())[1:])))
    return S, ink & S, False


def thin_lines(R, g, p):
    """Fat or noisy strokes -> uniform ribs, on the raster: blobs (eyes, dots) are kept by an opening, the
    rest of the strokes become their skeleton dilated to rib_w."""
    from skimage.morphology import skeletonize
    if not R.any():
        return R
    blobs = opening(R, 1.6, g)
    lines = R & ~dilate(blobs, 0.25, g)
    sk = skeletonize(lines) if lines.any() else np.zeros_like(R)
    dil = dilate(sk, p["rib_w"] / 2 + 0.05, g) if sk.any() else np.zeros_like(R)
    return blobs | dil


# ---------------------------------------------------------------- metrics and the rules gate (on the raster)
def dough_metrics(S, R, sdS, g, p):
    """Rule breaks on the stamp level: narrow land, small closed pockets, fat dots."""
    D = S & ~R
    nar = D & ~dilate(erode(D, (p["land"] + 0.15) / 2, g), (p["land"] + 0.15) / 2, g)
    nar_c = _comps(nar, 4.0, g)[1]
    wallish = sdS > -1.5 * g.px
    lab, comps = _comps(D, 0.3, g)
    pockets = []
    for i, _ in comps:
        c = lab == i
        if not (c & wallish).any():
            pockets.append(inscribed_d(c, g)[0])
    fat = _comps(opening(R, p["dot"] / 2 + 0.05, g), 0.5, g)[1] if R.any() else []
    return dict(narrow_land_spots=len(nar_c), narrow_land_mm2=round(sum(a for _, a in nar_c), 1),
                pockets=len(pockets), pockets_under=sum(d < p["pocket"] for d in pockets),
                fat_dots=len(fat), rib_pieces=len(_comps(R, 0.0, g)[1]), rib_area=round(float(R.sum()) * g.px ** 2, 1))


def rules_gate(S, R, sdS, g, p, rounds=8):
    """Runs last on the ribs: dots over 5 mm become rings or shrink, closed pockets under 5 mm are filled or
    opened, land under 3 mm is cut back. Nothing is ever refilled afterwards."""
    from scipy.spatial import cKDTree
    before = dough_metrics(S, R, sdS, g, p)
    wallish = sdS > -1.5 * g.px
    for _ in range(rounds):
        # a) dots / bosses wider than dot
        r_ = p["dot"] / 2 + 0.05
        op = opening(R, r_, g) if R.any() else R
        lab, comps = _comps(op, 0.5, g)
        for i, _a in comps:
            b = lab == i
            d, _c = inscribed_d(b, g)
            if d >= p["pocket"] + 2 * p["rib_w"]:
                rep = b & ~erode(b, p["rib_w"], g)
            else:
                shrink = (d - (p["dot"] - 0.3)) / 2
                rep = erode(b, shrink, g) if shrink > 0 else b
            R = (R & ~dilate(b, 0.3, g)) | rep
        # b) closed pockets smaller than pocket
        D = S & ~R
        lab, comps = _comps(D, 0.3, g)
        ocean = np.zeros_like(R)
        pockets = []
        for i, _a in comps:
            c = lab == i
            if (c & wallish).any():
                ocean |= c
            else:
                pockets.append(c)
        for c in pockets:
            d, (cc, rr) = inscribed_d(c, g)
            if d < p["pocket"]:
                if d + 2 * p["rib_w"] <= p["dot"] + 0.6:
                    R = R | c
                elif ocean.any():
                    ys, xs = np.nonzero(ocean)
                    k = int(cKDTree(np.column_stack([xs, ys])).query([cc, rr])[1])
                    xm, ym = g.to_mm([cc, xs[k]], [rr, ys[k]])
                    cut = dilate(seg_mask(g, (xm[0], ym[0]), (xm[1], ym[1]), 0.05), p["land"] / 2, g)
                    R = R & ~cut
        # c) land narrower than land between ribs / rib and wall: cut the ribs back, never fill
        D = S & ~R
        eff = (p["land"] + 0.15) / 2
        nar = D & ~dilate(erode(D, eff, g), eff, g)
        lab, comps = _comps(nar, 4.0, g)
        if comps:
            nm = np.zeros_like(R)
            for i, _a in comps:
                nm |= lab == i
            R = R & ~dilate(nm, 1.0, g)
        # d) slivers and specks out
        if R.any():
            R = drop_small(opening(R, 0.45, g), 5.0, g)
        m = dough_metrics(S, R, sdS, g, p)
        if m["narrow_land_spots"] == 0 and m["pockets_under"] == 0 and m["fat_dots"] == 0:
            break
    return R, before, dough_metrics(S, R, sdS, g, p)


# ---------------------------------------------------------------- outline checks (raster only)
def _contour_len(m, g):
    """Length in mm of the outline of a mask (sub-pixel marching squares on its signed distance)."""
    from skimage import measure
    if not m.any():
        return 0.0
    f = np.pad(sdf(m, g), 1, mode="constant", constant_values=1e3)
    return float(sum(np.hypot(*np.diff(c, axis=0).T).sum() for c in measure.find_contours(f, 0.0))) * g.px


def outline_metrics(S, g):
    """Neck (share of the area that survives a 3 mm radius opening, and how many real pieces it splits into),
    raggedness (outline length over the length after a 2 mm close-open), fullness (area over convex hull)."""
    from skimage.morphology import convex_hull_image
    area = float(S.sum())
    op = opening(S, 3.0, g)
    kept = float(op.sum()) / max(area, 1.0)
    pieces = len(_comps(op, 0.03 * area * g.px ** 2, g)[1])
    r = 2.0
    cl = erode(dilate(S, r, g), r, g) | S
    sm = opening(cl, r, g)
    L0, L1 = _contour_len(S, g), _contour_len(sm, g)
    ys, xs = np.nonzero(S)
    sub = S[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    hull = float(convex_hull_image(sub).sum())
    return dict(neck_kept=round(kept, 3), neck_pieces=pieces, ragged=round(L0 / max(L1, 1e-6), 2),
                fullness=round(area / max(hull, 1.0), 3))


# ---------------------------------------------------------------- bridges (raster)
def _length(pc, g):
    """Half the outline length of a rib piece in mm: a stroke's length, a dot's half circumference."""
    from scipy import ndimage as ndi
    edge = pc & ~ndi.binary_erosion(pc)
    return float(edge.sum()) * g.px / 2 * 0.9


def _tree(m):
    from scipy.spatial import cKDTree
    ys, xs = np.nonzero(m)
    return cKDTree(np.column_stack([xs, ys])), xs, ys


def place_bridges(S, R, sdS, g, p):
    """6 mm lattice (no free bar run over maxrun), then every rib piece gets >= 2 bar contacts (1 if under
    10 mm long; touching the wall counts as one), then the back plan is ONE piece."""
    w, bw = p["wall_back"], p["bar_w"]
    base = (sdS < w + p["rim_w"]) & ~S
    zone = sdS < w + 0.6
    ys, xs = np.nonzero(S)
    minx, maxx = g.to_mm(xs.min(), 0)[0] - g.px / 2, g.to_mm(xs.max(), 0)[0] + g.px / 2
    miny, maxy = g.to_mm(0, ys.min())[1] - g.px / 2, g.to_mm(0, ys.max())[1] + g.px / 2
    kv = max(1, math.ceil((maxx - minx) / p["maxrun"]) - 1)
    kh = max(1, math.ceil((maxy - miny) / p["maxrun"]) - 1)
    cand = np.zeros(g.shape, bool)
    for i in range(kv):
        x = minx + (maxx - minx) * (i + 1) / (kv + 1)
        cand |= seg_mask(g, (x, miny - 5), (x, maxy + 5), bw / 2)
    for j in range(kh):
        y = miny + (maxy - miny) * (j + 1) / (kh + 1)
        cand |= seg_mask(g, (minx - 5, y), (maxx + 5, y), bw / 2)
    cand &= zone
    lab, n = _label(cand)
    bars = np.zeros(g.shape, bool)
    from scipy import ndimage as ndi
    for i, sl in enumerate(ndi.find_objects(lab)):
        c = lab == i + 1
        ext = max((sl[0].stop - sl[0].start), (sl[1].stop - sl[1].start)) * g.px
        if (c & R).sum() * g.px ** 2 > 0.5 or ext > 12:
            bars |= c
    n0 = int(_label(bars)[1])
    extra = 0
    wallc = sdS > -0.35
    rl, rn = _label(R)
    pieces = [(rl == i) for i in range(1, rn + 1)]
    done = set()
    for _ in range(120):
        U = bars | base
        worst = None
        for idx, pc in enumerate(pieces):
            if idx in done:
                continue
            need = 1 if _length(pc, g) < 10 else 2
            cs = _comps(pc & U, 1.8, g)
            nc = len(cs[1]) + (1 if (pc & wallc).any() else 0)
            held = (pc & U).sum() >= 0.4 * pc.sum()       # lying along a bar: held all the way
            if nc < need and not held:
                worst = (idx, pc, cs)
                break
        if worst is None:
            break
        idx, pc, (clab, ccl) = worst
        if ccl:
            contacts = np.zeros(g.shape, bool)
            for i, _a in ccl:
                contacts |= clab == i
            d = _edt(~contacts)
            d[~pc] = -1
            k = int(np.argmax(d))
        else:
            d = _edt(~U)
            d[~pc] = 1e9
            k = int(np.argmin(d))
        far = divmod(k, g.W)       # (row, col)
        tgt = (U & ~dilate(pc, 0.5, g))
        if not tgt.any():
            done.add(idx)
            continue
        tree, tx, ty = _tree(tgt)
        j = int(tree.query([far[1], far[0]])[1])
        a = g.to_mm(far[1], far[0]); b = g.to_mm(tx[j], ty[j])
        add = (seg_mask(g, a, b, bw / 2, ext=1.5) & (zone | S)) if math.hypot(a[0] - b[0], a[1] - b[1]) > 0.3             else dilate(_one(g, far), bw / 2, g)
        if (add & ~bars).sum() * g.px ** 2 < 0.5:
            done.add(idx)       # nothing new can be added here
            continue
        bars |= add
        extra += 1
    for _ in range(100):
        F = bars | base | R
        lab, n = _label(F)
        if n <= 1:
            break
        main = lab == lab[np.nonzero(base)[0][0], np.nonzero(base)[1][0]]
        mt, mx, my = _tree(main)
        best = None
        for i in range(1, n + 1):
            if (lab == i)[main].any():
                continue
            ys2, xs2 = np.nonzero(lab == i)
            dd, jj = mt.query(np.column_stack([xs2, ys2]))
            q = int(np.argmin(dd))
            if best is None or dd[q] < best[0]:
                best = (dd[q], (xs2[q], ys2[q]), (mx[jj[q]], my[jj[q]]))
        a = g.to_mm(*best[1]); b = g.to_mm(*best[2])
        bars |= (seg_mask(g, a, b, bw / 2, ext=1.5) & (zone | S)) if best[0] * g.px > 0.3 else dilate(_one(g, (best[1][1], best[1][0])), bw / 2, g)
        extra += 1
    return bars, n0, extra


def _one(g, rc):
    m = np.zeros(g.shape, bool)
    m[int(rc[0]), int(rc[1])] = True
    return m


def bridge_report(S, R, bars, sdS, g, p):
    base = (sdS < p["wall_back"] + p["rim_w"]) & ~S
    U = bars | base
    wallc = sdS > -0.35
    rl, rn = _label(R)
    bad = 0
    for i in range(1, rn + 1):
        pc = rl == i
        nc = len(_comps(pc & U, 1.8, g)[1]) + (1 if (pc & wallc).any() else 0)
        if nc < (1 if _length(pc, g) < 10 else 2) and (pc & U).sum() < 0.4 * pc.sum():
            bad += 1
    win = S & ~R & ~bars
    lab, comps = _comps(win, 6.0, g)
    ds = [inscribed_d(lab == i, g)[0] for i, _a in comps]
    return dict(ribs_short_of_contacts=bad, windows=len(ds), windows_under=sum(d < p["window"] for d in ds),
                min_window_d=round(min(ds), 1) if ds else None)


# ---------------------------------------------------------------- slabs: stacked footprints from level sets
def _unpinch(g):
    """A footprint whose boundary touches itself at a vertex gives a mesh edge that four faces share. Move the second
    visit of every such vertex 0.004 mm into the polygon's own material, which turns the touch into a real gap."""
    out = []
    seen = {}
    for pg in _polys(g):
        rings = [np.array(pg.exterior.coords)[:-1]] + [np.array(r.coords)[:-1] for r in pg.interiors]
        changed = False
        for ri, c in enumerate(rings):
            ctr = c.mean(0)
            for i in range(len(c)):
                k = (round(c[i, 0] / GRID), round(c[i, 1] / GRID))
                if k in seen:
                    v = ctr - c[i] if ri == 0 else c[i] - ctr
                    n = np.hypot(*v)
                    if n > 1e-9:
                        c[i] = np.round((c[i] + v / n * 2 * GRID * 2) / GRID) * GRID
                        changed = True
                else:
                    seen[k] = 1
        if changed:
            cand = Polygon(rings[0], rings[1:])
            if cand.is_valid:
                pg = cand
        out.append(pg)
    return out[0] if len(out) == 1 else shapely.MultiPolygon(out)


def make_slabs(S, R, bars, sdS, g, p, rlevel=0.05):
    """Footprints from the back (slab 0 = rim + bridges + ribs) to the cutting edge. The wall steps in from 1.6
    mm at the back to 1.05 mm, and the last 2 mm is exactly wall_tip (0.86 mm = two 0.43 mm nozzle lines);
    nothing between 0.45 and 0.86. The top 2 mm of every rib is 0.2 mm slimmer per side. Every outline is a
    level set of a distance field, so each slab sits inside the one below (nothing overhangs)."""
    H = p["H"]
    rib_top = H - (p["dough"] - p["imprint"])
    t = p["base_t"]
    tip0 = H - 2.0
    must = {0.0, round(t, 3), round(rib_top - 2.0, 3), round(rib_top, 3), round(tip0, 3), round(H, 3)}
    levels = []
    for z in sorted({round(c, 3) for c in (0.0, t, 4.0, 6.0, rib_top - 2.0, rib_top, tip0, H)}):
        if levels and z - levels[-1] < 0.3:
            if z in must and levels[-1] not in must:
                levels[-1] = z
            continue
        levels.append(z)
    PS = level_polys(sdS, 0.0, g)
    sdR = sdf(R, g) if R.any() else None
    PR = level_polys(sdR, rlevel, g) if sdR is not None else Polygon()
    PRd = level_polys(sdR, rlevel - 0.2, g) if sdR is not None else Polygon()
    PB = level_polys(sdf(bars, g), 0.05, g) if bars.any() else Polygon()
    outer = {}
    fp = []
    for i in range(len(levels) - 1):
        zt, zm = levels[i + 1], 0.5 * (levels[i] + levels[i + 1])
        if i == 0:
            rim = _diff(level_polys(sdS, p["wall_back"] + p["rim_w"], g), PS)
            fp.append(_unpinch(_union([rim, PB, PR])))
            continue
        w = p["wall_tip"] if zm >= tip0 else round(p["wall_back"] - (p["wall_back"] - 1.05) * (zm - t) / max(tip0 - t, 1e-6), 2)
        if w not in outer:
            outer[w] = level_polys(sdS, w, g)
        parts = [_diff(outer[w], PS)]
        if zt <= rib_top - 2.0 + 1e-6:
            parts.append(PR)
        elif zt <= rib_top + 1e-6:
            parts.append(PRd)
        fp.append(_unpinch(_union(parts)))
    return levels, fp, rib_top, dict(S=PS, R=PR, bars=PB)


# ---------------------------------------------------------------- triangulation
def _tri_inside(px, py, ax, ay, bx, by, cx, cy, eps=1e-9):
    d1 = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    d2 = (cx - bx) * (py - by) - (cy - by) * (px - bx)
    d3 = (ax - cx) * (py - cy) - (ay - cy) * (px - cx)
    return (d1 >= -eps) & (d2 >= -eps) & (d3 >= -eps)      # on the boundary counts: it would make a T-junction


def _seg_cross_any(ax, ay, bx, by, X, Y):
    X2 = np.roll(X, -1); Y2 = np.roll(Y, -1)

    def side(px, py, qx, qy, rx, ry):
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)
    d1 = side(ax, ay, bx, by, X, Y); d2 = side(ax, ay, bx, by, X2, Y2)
    d3 = side(X, Y, X2, Y2, ax, ay); d4 = side(X, Y, X2, Y2, bx, by)
    return bool(((d1 * d2 < -1e-12) & (d3 * d4 < -1e-12)).any())


def _on_segment(ax, ay, bx, by, X, Y, tol=1e-6):
    """True if any ring vertex other than the endpoints lies on the segment a-b (a collinear or touching bridge)."""
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-18:
        return True
    t = np.clip(((X - ax) * dx + (Y - ay) * dy) / L2, 0.0, 1.0)
    d = np.hypot(X - (ax + t * dx), Y - (ay + t * dy))
    ends = (np.hypot(X - ax, Y - ay) < 1e-9) | (np.hypot(X - bx, Y - by) < 1e-9)
    return bool(((d < tol) & ~ends).any())


def earclip(rings):
    """rings: [(ids, Nx2 coords)], first exterior CCW, rest holes CW -> list of (id,id,id) CCW.
    Holes are bridged to the outer ring by the nearest unobstructed vertex; pure python + numpy."""
    ids = list(rings[0][0]); co = [tuple(c) for c in rings[0][1]]
    holes = sorted(rings[1:], key=lambda r: -max(c[0] for c in r[1]))
    for hid, hco in holes:
        hco = np.asarray(hco)
        k = int(np.argmax(hco[:, 0]))
        M = hco[k]
        Xo = np.array([c[0] for c in co]); Yo = np.array([c[1] for c in co])
        order = np.argsort((Xo - M[0]) ** 2 + (Yo - M[1]) ** 2)
        for j in order:
            if not _seg_cross_any(M[0], M[1], Xo[j], Yo[j], Xo, Yo) and \
               not _seg_cross_any(M[0], M[1], Xo[j], Yo[j], hco[:, 0], hco[:, 1]):
                n = len(hid)
                hring = [(hid[(k + i) % n], tuple(hco[(k + i) % n])) for i in range(n)]
                hring.append((hid[k], tuple(hco[k])))
                ids = ids[:j + 1] + [h[0] for h in hring] + [ids[j]] + ids[j + 1:]
                co = co[:j + 1] + [h[1] for h in hring] + [co[j]] + co[j + 1:]
                break
        else:
            raise RuntimeError("hole bridge failed")
    n = len(ids)
    X = np.array([c[0] for c in co]); Y = np.array([c[1] for c in co])
    nxt = [(i + 1) % n for i in range(n)]; prv = [(i - 1) % n for i in range(n)]
    alive = np.ones(n, bool)
    tris = []
    cnt = n; i = 0; fails = 0
    while cnt > 3:
        a, b, c = prv[i], i, nxt[i]
        cr = (X[b] - X[a]) * (Y[c] - Y[a]) - (Y[b] - Y[a]) * (X[c] - X[a])
        ear = cr > 1e-10
        if ear:
            m = alive.copy(); m[[a, b, c]] = False
            for q in (a, b, c):       # bridge duplicates sit exactly on a corner: they do not block
                m &= ~((np.abs(X - X[q]) < 1e-9) & (np.abs(Y - Y[q]) < 1e-9))
            ear = not (_tri_inside(X, Y, X[a], Y[a], X[b], Y[b], X[c], Y[c]) & m).any()
        if ear:
            tris.append((ids[a], ids[b], ids[c]))
            alive[b] = False; nxt[a] = c; prv[c] = a; cnt -= 1; i = a; fails = 0
        else:
            i = nxt[i]; fails += 1
            if fails > cnt:  # no strict ear left: clip the flattest vertex (degenerate sliver)
                best = None; bv = 1e18; j = i
                for _ in range(cnt):
                    aa, cc = prv[j], nxt[j]
                    crr = (X[j] - X[aa]) * (Y[cc] - Y[aa]) - (Y[j] - Y[aa]) * (X[cc] - X[aa])
                    if -1e-9 <= crr < bv:
                        bv = crr; best = j
                    j = nxt[j]
                if best is None:
                    best = i
                aa, cc = prv[best], nxt[best]
                tris.append((ids[aa], ids[best], ids[cc]))
                alive[best] = False; nxt[aa] = cc; prv[cc] = aa; cnt -= 1; i = aa; fails = 0
    tris.append((ids[prv[i]], ids[i], ids[nxt[i]]))
    return tris


# ---------------------------------------------------------------- mesh
def _collapse_pinches(verts, F, tol=0.7):
    """Edges used by 4 faces are pinch points (two ribs/wall touching at a corner): collapse the
    sub-tol edge to one vertex and drop the triangles that become degenerate."""
    for _ in range(8):
        e = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1)
        u, c = np.unique(e, axis=0, return_counts=True)
        bad = u[c > 2]
        if not len(bad):
            break
        rep = np.arange(len(verts))
        for a, b in bad:
            if np.linalg.norm(verts[a] - verts[b]) < tol:
                rep[b] = rep[a]
        F = rep[F]
        F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])]
    return F


def build_mesh(levels, fps, p=P):
    """Planar arrangement of all slab outlines -> faces with shared vertices. Every face is
    triangulated once; caps where occupancy changes between slabs, wall quads on each edge where
    the neighbour face is empty. All columns share all level heights, so the shell is closed."""
    import trimesh
    t0 = time.time()
    net = shapely.unary_union([g.boundary for g in fps if not g.is_empty], grid_size=p["grid"])
    faces = list(shapely.polygonize([net]).geoms)
    nS = len(fps)
    vid = {}; vxy = []

    def V(pt):
        k = (round(pt[0] / p["grid"]), round(pt[1] / p["grid"]))
        if k not in vid:
            vid[k] = len(vxy); vxy.append((k[0] * p["grid"], k[1] * p["grid"]))
        return vid[k]
    occ = [[bool(fp.contains(f.representative_point())) for fp in fps] for f in faces]
    edge_face = {}; rings = []
    for fi, f in enumerate(faces):
        f = shapely.geometry.polygon.orient(f, 1.0)
        rs = []
        for r in [f.exterior] + list(f.interiors):
            c = list(r.coords)[:-1]
            ids = [V(q) for q in c]
            rs.append((ids, c))
            for i in range(len(ids)):
                edge_face[(ids[i], ids[(i + 1) % len(ids)])] = fi
        rings.append(rs)
    t1 = time.time()
    F = []; vz = {}

    def VZ(i, k):
        key = (i, k)
        if key not in vz:
            vz[key] = len(vz)
        return vz[key]
    for fi, rs in enumerate(rings):
        o = occ[fi]
        if not any(o):
            continue
        ch = [(k, (o[k] if k < nS else False), (o[k - 1] if k > 0 else False)) for k in range(nS + 1)]
        if any(a != b for _, a, b in ch):
            tri = earclip([(ids, np.array(c)) for ids, c in rs])
            for k, above, below in ch:
                if above and not below:       # bottom cap, normal -z
                    F.extend((VZ(a, k), VZ(c, k), VZ(b, k)) for a, b, c in tri)
                elif below and not above:     # top cap, normal +z
                    F.extend((VZ(a, k), VZ(b, k), VZ(c, k)) for a, b, c in tri)
        for ids, c in rs:
            n = len(ids)
            for i in range(n):
                a, b = ids[i], ids[(i + 1) % n]
                nb = edge_face.get((b, a))
                on = occ[nb] if nb is not None else [False] * nS
                for j in range(nS):
                    if o[j] and not on[j]:
                        F.append((VZ(a, j), VZ(b, j), VZ(b, j + 1)))
                        F.append((VZ(a, j), VZ(b, j + 1), VZ(a, j + 1)))
    verts = np.zeros((len(vz), 3))
    for (i, k), n in vz.items():
        verts[n] = (vxy[i][0], vxy[i][1], levels[k])
    F = _collapse_pinches(verts, np.array(F))
    m = trimesh.Trimesh(verts, F, process=False)
    return m, dict(faces2d=len(faces), t_arrange=round(t1 - t0, 2), t_mesh=round(time.time() - t1, 2))






# ---------------------------------------------------------------- checks
def _bodies(m):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    f = np.asarray(m.faces)
    used = np.unique(f)
    remap = -np.ones(len(m.vertices), int)
    remap[used] = np.arange(len(used))
    f = remap[f]
    n = len(used)
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]]])
    g = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    return int(connected_components(g, directed=False)[0])


def mesh_checks(m, S, R, bars, sdS, g, fps, p):
    r = {}
    r["watertight"] = bool(m.is_watertight)
    r["winding_consistent"] = bool(m.is_winding_consistent)
    r["volume_mm3"] = round(float(m.volume), 1)
    r["tris"] = int(len(m.faces))
    r["bodies"] = _bodies(m)
    r["overhang_mm2"] = round(float(sum(shapely.difference(fps[j], fps[j - 1], grid_size=GRID).area for j in range(1, len(fps)))), 4)
    r["back_components"] = len(_polys(fps[0]))
    r["final_stamp_level"] = dough_metrics(S, R, sdS, g, p)
    r["bridges"] = bridge_report(S, R, bars, sdS, g, p)
    r["bbox_mm"] = [round(float(x), 1) for x in (m.bounds[1] - m.bounds[0])]
    return r


def plain_checks(ck, info, p, notes=()):
    """[{level: pass|warn|block, text}] in words a baker can read. Only a broken mesh or a floating
    piece blocks the download."""
    out = []
    def add(level, text, id=None):
        out.append({"level": level, "text": text} if id is None else {"level": level, "text": text, "id": id})
    ok_mesh = ck["watertight"] and ck["winding_consistent"]
    add("pass" if ok_mesh else "block",
        "The model is one closed solid, ready to slice." if ok_mesh else "The model has holes in its surface, so it cannot be printed. Try a simpler picture.", "closed solid")
    one = ck["bodies"] == 1 and ck["back_components"] == 1
    add("pass" if one else "block",
        "Every inside piece is held by the back bars: nothing floats." if one else "Some inside pieces are not attached to the cutter, so they would fall off.", "attached pieces")
    b = ck["bridges"]
    add("pass" if b["ribs_short_of_contacts"] == 0 else "warn",
        "Every inside line is held in at least two places (one for short ones)." if b["ribs_short_of_contacts"] == 0
        else "%d inside lines are held at too few points and may snap off." % b["ribs_short_of_contacts"])
    add("pass", "Cutting edge is %.2f mm: two nozzle lines with a 0.4 mm nozzle." % p["wall_tip"])
    add("pass", "Back bars are %g x %g mm and no bar runs free for more than %g mm." % (p["bar_w"], p["base_t"], p["maxrun"]))
    fm, ra = ck["final_stamp_level"], ck["rules_after"]
    add("pass" if ra["pockets_under"] == 0 and fm["pockets_under"] == 0 else "warn",
        "Dough pockets: none under %g mm." % p["pocket"] if ra["pockets_under"] == 0 and fm["pockets_under"] == 0
        else "%d closed pockets under %g mm could pull a plug of dough out." % (max(ra["pockets_under"], fm["pockets_under"]), p["pocket"]))
    add("pass" if fm["narrow_land_spots"] == 0 else "warn",
        "At least %g mm of dough between inside lines, and between lines and the edge." % p["land"] if fm["narrow_land_spots"] == 0
        else "%d spots have less than %g mm of dough between lines." % (fm["narrow_land_spots"], p["land"]))
    add("pass" if fm["fat_dots"] == 0 else "warn",
        "Dots and solid shapes are %g mm or smaller (bigger ones become rings)." % p["dot"] if fm["fat_dots"] == 0
        else "%d solid shapes are wider than %g mm." % (fm["fat_dots"], p["dot"]))
    add("pass" if ck["overhang_mm2"] < 0.05 else "warn",
        "Prints back-down with no supports." if ck["overhang_mm2"] < 0.05 else "Some parts overhang and would need supports.")
    wu = b["windows_under"]
    add("pass" if wu == 0 else "warn",
        "Back windows are at least %g mm across, so dough can be pushed out." % p["window"] if wu == 0
        else "%d back windows are under %g mm across; dough is harder to push out there." % (wu, p["window"]))
    ph = info.get("photo")
    if ph:
        add("pass", ph["message"] + ".")
        if ph.get("lines", 99) < 4:
            add("warn", "We found only %d line%s in this photo, so the cookie has little pattern." % (ph["lines"], "" if ph["lines"] == 1 else "s"))
    ol = info.get("outline")
    if ol:
        if ol["neck_kept"] < 0.90 or ol["neck_pieces"] > 1:
            add("block", "The cookie has a neck thinner than 6 mm and would break there. Make the shape fuller or the size bigger.", "thin neck")
        else:
            add("pass", "No neck thinner than 6 mm: the cookie will not snap when lifted.", "thin neck")
        if ol["ragged"] > 1.35:
            add("warn", "The edge is ragged. Dough will tear on it. A smoother outline cuts cleaner.")
        if ol["fullness"] < 0.55:
            add("warn", "This shape has deep cuts and thin arms, so the dough may bend when lifted.")
    if info.get("solid"):
        add("warn", "We could not find lines in this photo, so the cookie has no inside lines." if ph
            else "The picture is a solid shape, so the cookie has no inside lines. Use a line drawing for an embossed cookie.")
    add("pass", "Roll the dough to %g mm: the lines then press %g mm deep." % (p["dough"], p["imprint"]))
    for n in notes:
        add("warn", n)
    return out




# ---------------------------------------------------------------- build with caches
_PREP = OrderedDict()    # (art hash, size) -> rasters of outline + ribs  (the slow part)
_BUILT = OrderedDict()   # (art hash, all params) -> finished build


def _hash(upload):
    return hashlib.sha1(upload).hexdigest()


def _frame(polys, px, margin):
    allp = np.vstack(polys)
    x0, y0 = allp.min(0) - margin
    x1, y1 = allp.max(0) + margin
    return Grid(float(x0), float(y0), px, int((x1 - x0) / px) + 2, int((y1 - y0) / px) + 2)


def prepare(upload, name, cp: CookieParams):
    from . import art as artmod
    key = (_hash(upload), round(cp.size_mm, 1), cp.pitch_scale)
    if key in _PREP:
        _PREP.move_to_end(key)
        r = dict(_PREP[key]); r["prep_cached"] = True
        return r
    t0 = time.time()
    from . import photo as photomod
    src, photo_info = upload, None
    if photomod.analyze(upload)["is_photo"]:
        # a photo never goes through Otsu + potrace (that traces shadow, not the subject): find the subject,
        # make a clean line drawing of it, and feed that to the drawing engine
        try:
            ph = photomod.make_cutter_drawing(upload, cp.size_mm)
        except photomod.NeedsCv as exc:
            raise CookieError(str(exc))
        except photomod.PhotoRefused as exc:
            raise CookieError(str(exc))
        src = ph["png"]
        photo_info = dict(route=ph["route"], message=ph["message"], lines=ph["report"]["lines"], report=ph["report"], overlay=ph["overlay"])
    try:
        art = artmod.load("upload", src, name, "trace")
    except Exception as exc:       # ArtError, or the image could not be decoded
        # plain words for the person; the technical cause stays chained for the console
        if "identify image" in str(exc) or "cannot" in str(exc).lower():
            raise CookieError("We could not open this file as a picture. Use a PNG, JPEG, WEBP or SVG file.") from exc
        raise CookieError("We could not use this picture: %s" % exc) from exc
    p = design(cp)
    polys0, _w, _h = _art_polys(art, cp.size_mm)
    margin = p["wall_back"] + p["rim_w"] + 3.0
    pitch = _pitch(cp.size_mm) * cp.pitch_scale
    t1 = time.time()
    # pass 1 on a coarse grid finds the scale that makes the CUT shape (not the picture frame) size_mm long
    gc = _frame(polys0, max(pitch, 0.2), margin)
    S, _R, _solid = _parts(polys0, gc, p)
    ys, xs = np.nonzero(S)
    f = cp.size_mm / (max(xs.max() - xs.min(), ys.max() - ys.min()) + 1) / gc.px
    for _ in range(3):
        polys = [a * f for a in polys0]
        g = _frame(polys, pitch, margin)
        S, Rraw, solid = _parts(polys, g, p)
        sdS = sdf(S, g)
        b = level_polys(sdS, 0.0, g).bounds
        meas = max(b[2] - b[0], b[3] - b[1])
        err = cp.size_mm / meas
        if abs(err - 1) < 0.0015:
            break
        f *= err
    R = thin_lines(Rraw, g, p)
    R = drop_small(R & (sdS < 0.3), 1.0, g)
    info = dict(solid=bool(solid), outline=outline_metrics(S, g))
    if photo_info:
        info["photo"] = photo_info
    r = dict(g=g, S=S, R=R, sdS=sdS, info=info, pitch=pitch,
             t_art=round(t1 - t0, 2), t_ribs=round(time.time() - t1, 2), prep_cached=False)
    _PREP[key] = r
    while len(_PREP) > 3:
        _PREP.popitem(last=False)
    return dict(r)


def build(upload, name, cp: CookieParams):
    if not upload:
        raise CookieError("no picture to use")
    key = (_hash(upload), tuple(sorted(cp.to_dict().items())), cp.pitch_scale)
    if key in _BUILT:
        _BUILT.move_to_end(key)
        r = dict(_BUILT[key]); r["cached"] = True
        return r
    prep = prepare(upload, name, cp)
    p = design(cp)
    g, S, sdS = prep["g"], prep["S"], prep["sdS"]
    T = {"art": prep["t_art"], "ribs": prep["t_ribs"]}
    t = time.time()
    R, before, after = rules_gate(S, prep["R"], sdS, g, p); T["rules"] = round(time.time() - t, 2); t = time.time()
    bars, n0, extra = place_bridges(S, R, sdS, g, p); T["bridges"] = round(time.time() - t, 2); t = time.time()
    keep = None
    # A footprint that touches itself at a point gives an edge four faces share. The outlines are level sets of
    # distance fields, so a slightly different level removes the touch; try a few before giving up.
    for rlevel in (0.05, 0.062, 0.041, 0.071):
        levels, fps, rib_top, polys = make_slabs(S, R, bars, sdS, g, p, rlevel)
        m, mi = build_mesh(levels, fps, p)
        ck = mesh_checks(m, S, R, bars, sdS, g, fps, p)
        keep = keep or (levels, fps, rib_top, polys, m, ck)
        if ck["watertight"] and ck["bodies"] == 1 and ck["back_components"] == 1:
            keep = (levels, fps, rib_top, polys, m, ck)
            break
    levels, fps, rib_top, polys, m, ck = keep
    T["mesh"] = round(time.time() - t, 2)
    ck.update(rules_before=before, rules_after=after, bars_lattice=n0, bars_extra=extra, rib_top_z=rib_top, pitch_mm=prep["pitch"])
    res = dict(S=polys["S"], R=polys["R"], bars=polys["bars"], sdS=sdS, g=g, mesh=m, ck=ck, info=prep["info"], p=p, cp=cp, time=T,
               prep_cached=prep["prep_cached"], cached=False, levels=levels, fps=fps)
    _BUILT[key] = res
    while len(_BUILT) > 2:
        _BUILT.popitem(last=False)
    return dict(res)


# ---------------------------------------------------------------- API
def _rings(g):
    out = []
    for pg in _polys(g):
        out.append([[[round(x, 2), round(y, 2)] for x, y in ring.coords] for ring in [pg.exterior] + list(pg.interiors)])
    return out


def _friendly(fn):
    """Any engine failure other than a CookieError becomes the plain sentence; the cause stays chained."""
    import functools

    @functools.wraps(fn)
    def run(*a, **k):
        try:
            return fn(*a, **k)
        except CookieError:
            raise
        except Exception as exc:
            raise CookieError(FRIENDLY) from exc
    return run


@_friendly
def preview(params: dict, upload: bytes | None = None, upload_name: str | None = None) -> dict:
    """-> {size, checks (plain words), can_export, geom (mm polygons of the CUTTER as printed), timings}.
    The page draws the back view straight from geom and the pressed cookie as its mirror."""
    cp = CookieParams.from_dict(params)
    r = build(upload, upload_name, cp)
    p, S = r["p"], r["S"]
    checks_ = plain_checks(r["ck"], r["info"], p, getattr(cp, "notes", []))
    w = S.bounds[2] - S.bounds[0]
    h = S.bounds[3] - S.bounds[1]
    g, sdS = r["g"], r["sdS"]
    return {
        "params": cp.to_dict(),
        "size": {"cut_w": round(w, 1), "cut_h": round(h, 1), "outer_w": r["ck"]["bbox_mm"][0], "outer_h": r["ck"]["bbox_mm"][1],
                 "height": p["H"], "tris": r["ck"]["tris"]},
        "checks": checks_,
        "can_export": not any(c["level"] == "block" for c in checks_),
        "geom": {"cut": _rings(S), "wall": _rings(level_polys(sdS, p["wall_back"], g)),
                 "rim": _rings(level_polys(sdS, p["wall_back"] + p["rim_w"], g)), "bars": _rings(r["bars"]),
                 "ribs": _rings(r["R"])},
        "rules": {"before": r["ck"]["rules_before"], "after": r["ck"]["rules_after"], "final": r["ck"]["final_stamp_level"]},
        "timings": {**r["time"], "cached": bool(r["cached"]), "art_cached": bool(r["prep_cached"]), "pitch_mm": r["ck"]["pitch_mm"]},
        "solid": bool(r["info"].get("solid")),
        "outline": r["info"].get("outline"),
        "photo": r["info"].get("photo"),
    }


def _export(cp, upload, upload_name, override, notes=()):
    from . import override as overmod
    r = build(upload, upload_name, cp)
    checks_ = plain_checks(r["ck"], r["info"], r["p"], getattr(cp, "notes", []))
    blocked = any(c["level"] == "block" for c in checks_)
    mesh, ck = r["mesh"], r["ck"]
    over = None
    loose = list(notes)
    if override and blocked:
        stops = [c for c in checks_ if c["level"] == "block"]
        rep_notes = list(notes)
        if not (ck["watertight"] and ck["winding_consistent"]):
            # R86: one cheap repair pass, then check again
            import trimesh
            V2, F2, info = overmod.repair_mesh(mesh.vertices, mesh.faces)
            rep_notes.insert(0, overmod.repair_note(info))
            if info["kept"] == "repaired":
                mesh = trimesh.Trimesh(vertices=V2, faces=F2, process=False)
                ck = dict(ck, watertight=bool(mesh.is_watertight), winding_consistent=bool(mesh.is_winding_consistent),
                          volume_mm3=round(float(mesh.volume), 1), tris=int(len(mesh.faces)), bodies=_bodies(mesh))
                checks_ = plain_checks(ck, r["info"], r["p"], getattr(cp, "notes", []))
                for c in checks_:
                    if c["level"] == "block" and all(c["text"] != x["text"] for x in stops):
                        stops.append(c)
        over = {"ids": [c.get("id") or "stop" for c in stops], "stops": [c["text"] for c in stops], "notes": rep_notes}
        loose = []
    S = r["S"]
    w = S.bounds[2] - S.bounds[0]
    h = S.bounds[3] - S.bounds[1]
    stl = b"" if (blocked and not over) else bytes(mesh.export(file_type="stl"))
    side = {"kind": "cookie-cutter", "params": cp.to_dict(), "cut_shape_mm": [round(w, 1), round(h, 1)],
            "checks": checks_, "design": {k: r["p"][k] for k in ("wall_tip", "bar_w", "base_t", "maxrun", "land", "pocket", "dot", "rib_w")},
            "mirrored_for_pressing": True, "triangles": int(len(mesh.faces)),
            "print": "Back plate flat on the bed, 0.2 mm layers, 0.4 mm nozzle, no supports."}
    if loose:
        side["notes"] = loose          # R86: said in the sidecar even when nothing was overridden (for example the coarser retry)
    name = "cookie-cutter-%dx%d.stl" % (round(w), round(h))
    out = {"stl": stl, "sidecar": side, "blocked": blocked and not over, "checks": checks_, "filename": name}
    if over:
        side["exported_anyway"] = {"rule": "R86", "heading": overmod.HEAD, "stop_items": over["stops"], "ids": over["ids"], "notes": over["notes"],
                                   "watertight": bool(ck["watertight"])}
        out["filename"] = overmod.mark_name(name)
        out["override"] = {"ids": over["ids"], "stops": over["stops"], "notes": over["notes"]}
        out["watertight"] = bool(ck["watertight"])
    return out


def export_bytes(params: dict, upload: bytes | None = None, upload_name: str | None = None) -> dict:
    """-> {stl: bytes, sidecar: dict, blocked: bool, checks, filename}. Blocked only for a broken mesh, a floating piece or a
    thin neck. With export_anyway (R86) the STL is written whatever the checks say; a picture with no outline still raises
    CookieError, and an unexpected engine error is tried once more on a coarser grid."""
    cp = CookieParams.from_dict(params)
    if not cp.export_anyway:
        return _friendly(_export)(cp, upload, upload_name, False)
    try:
        return _export(cp, upload, upload_name, True)
    except CookieError as exc:
        raise CookieError("R86: Export anyway cannot fix this. %s" % exc) from exc
    except Exception:
        pass
    import dataclasses
    cp2 = dataclasses.replace(cp, pitch_scale=1.5)
    cp2.notes = list(getattr(cp, "notes", []))
    try:
        return _export(cp2, upload, upload_name, True,
                       ["R86: the first build failed, so this one was made on a coarser grid (1.5 x the usual pitch)."])
    except CookieError as exc:
        raise CookieError("R86: Export anyway cannot fix this. %s" % exc) from exc
    except Exception as exc:
        raise CookieError("R86: Export anyway could not build this cutter, even on a coarser grid. " + FRIENDLY) from exc
