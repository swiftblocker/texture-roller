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
from shapely.ops import unary_union, nearest_points


class CookieError(ValueError):
    pass


@dataclass
class CookieParams:
    size_mm: float = 80.0      # longest side of the cut shape
    dough_mm: float = 6.0      # thickness the dough is rolled to
    imprint_mm: float = 2.5    # how deep the inside lines press
    wall_mm: float = 14.0      # height of the cutter, back to cutting edge

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
        return p

    def to_dict(self):
        return asdict(self)


# fixed design values (red-team fixes); dough/imprint/wall come from CookieParams
P = dict(H=14.0, dough=6.0, imprint=2.5, base_t=2.4, rim_w=3.5, wall_back=1.6, wall_tip=0.86,
         rib_w=1.2, land=3.0, pocket=5.0, dot=5.0, bar_w=6.0, maxrun=35.0, window=8.0,
         size=80.0, grid=0.002, simp=0.04, outline=0.5)


def design(cp: CookieParams) -> dict:
    p = dict(P)
    p.update(H=cp.wall_mm, dough=cp.dough_mm, imprint=cp.imprint_mm, size=cp.size_mm)
    return p


def _polys(g):
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [p for x in getattr(g, "geoms", []) for p in _polys(x)]


def _xor_all(gs):
    """Even-odd fill of many subpaths: balanced pairwise symmetric difference."""
    gs = list(gs)
    while len(gs) > 1:
        nxt = [gs[i].symmetric_difference(gs[i + 1]) for i in range(0, len(gs) - 1, 2)]
        if len(gs) % 2:
            nxt.append(gs[-1])
        gs = nxt
    return gs[0]


def mirror(g, cx):
    """The stamp is pressed face down: flip x so the cookie, not the cutter, reads correctly."""
    return shapely.affinity.scale(g, xfact=-1, yfact=1, origin=(cx, 0))


# ---------------------------------------------------------------- art -> parts
def ink_from_art(art, size_mm, flip=True):
    """engine art.Art -> ink geometry in mm (even-odd over its subpaths), x flipped."""
    x0, y0, x1, y1 = art.frame
    scale = size_mm / max(x1 - x0, y1 - y0, 1e-9)
    polys, _ = art.flatten(scale)
    pgs = []
    for a in polys:
        pg = Polygon((np.asarray(a) - [x0, y0]) * scale).buffer(0)
        if not pg.is_empty and pg.area > 0.05:
            pgs.append(pg)
    if not pgs:
        raise CookieError("no art found in the picture")
    ink = _xor_all(pgs)
    ink = ink.buffer(0).simplify(0.03)
    return mirror(ink, (x1 - x0) * scale / 2) if flip else ink


def parts_from_ink(ink, p=P):
    """-> (silhouette S, raw inside lines R, info). A solid fill has no inside lines; line art uses its
    outline loop as the silhouette."""
    pieces = sorted(_polys(ink), key=lambda g: -Polygon(g.exterior).area)
    if not pieces:
        raise CookieError("no art found in the picture")
    main = pieces[0]
    S0 = Polygon(main.exterior)
    solid = ink.intersection(S0).area / max(S0.area, 1e-9) > 0.75
    if solid:
        return S0.simplify(p["simp"]), Polygon(), dict(solid=True)
    S = S0.buffer(-p["outline"]).simplify(p["simp"])
    if S.is_empty:
        raise CookieError("the outline is too thin to use")
    S = max(_polys(S), key=lambda g: g.area)
    return S, ink.intersection(S), dict(solid=False)


def thin_lines(R, p=P, px=0.12, blob_r=1.6):
    """Noisy/fat strokes -> uniform ribs: keep blobs as they are, replace stroke parts by their
    skeleton buffered to rib_w. skimage skeletonize on a 0.12 mm raster."""
    from skimage.morphology import skeletonize
    blobs = R.buffer(-blob_r).buffer(blob_r)
    lines = R.difference(blobs.buffer(0.25))
    if lines.is_empty:
        return R
    x0, y0, x1, y1 = lines.bounds
    x0 -= 1; y0 -= 1
    W = int((x1 + 1 - x0) / px) + 1; H = int((y1 + 1 - y0) / px) + 1
    X, Y = np.meshgrid(x0 + (np.arange(W) + .5) * px, y0 + (np.arange(H) + .5) * px)
    shapely.prepare(lines)
    sk = skeletonize(shapely.contains_xy(lines, X, Y))
    ys, xs = np.nonzero(sk)
    on = set(zip(ys.tolist(), xs.tolist()))
    segs = []
    for (r, c) in on:
        for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
            if (r + dr, c + dc) in on:
                segs.append(((x0 + (c + .5) * px, y0 + (r + .5) * px),
                             (x0 + (c + dc + .5) * px, y0 + (r + dr + .5) * px)))
    if not segs:
        return R
    cl = unary_union(shapely.linestrings(np.array(segs)))
    return unary_union([blobs, cl.simplify(0.05).buffer(p["rib_w"] / 2 + 0.05)])


def clean_ribs(R, S, p=P):
    """Width >= rib_w, clip to silhouette, drop specks. (No gap closing: the rules gate trims.)"""
    if R.is_empty:
        return R
    R = unary_union([g for g in _polys(R) if g.area > 0.5])
    R = thin_lines(R, p)
    out = []
    for g in _polys(R):
        w = 2 * g.area / max(g.length, 1e-9)
        if w < p["rib_w"]:
            g = g.buffer((p["rib_w"] - w) / 2 + 0.02)
        out.append(g)
    R = unary_union(out).intersection(S.buffer(0.3))
    R = unary_union([q for q in _polys(R) if q.area > 1.0])
    return R.simplify(p["simp"])


# ---------------------------------------------------------------- rules gate (runs LAST on the ribs)
def inscribed_d(poly):
    from shapely.ops import polylabel
    pt = polylabel(poly, 0.1)
    return 2 * poly.boundary.distance(pt), pt


def dough_metrics(S, R, p=P):
    """Counts of rule breaks on the stamp level: narrow land, small closed pockets, fat dots."""
    D = S.difference(R)
    nar = D.difference(D.buffer(-p["land"] / 2).buffer(p["land"] / 2))
    nar = [g for g in _polys(nar) if g.area > 4.0]
    bd = S.boundary.buffer(0.05)
    pockets = []
    for q in _polys(D):
        if q.area > 0.3 and not q.intersects(bd):
            d, _ = inscribed_d(q)
            pockets.append(d)
    r_ = p["dot"] / 2 + 0.05
    fat = [g for g in _polys(R.buffer(-r_).buffer(r_)) if g.area > 0.5]
    return dict(narrow_land_spots=len(nar), narrow_land_mm2=round(sum(g.area for g in nar), 1),
                pockets=len(pockets), pockets_under=sum(d < p["pocket"] for d in pockets),
                fat_dots=len(fat), rib_pieces=len(_polys(R)), rib_area=round(R.area, 1))


def rules_gate(S, R, p=P, rounds=8, fixed=None):
    fx = fixed if fixed is not None and not fixed.is_empty else Polygon()
    R = R.union(fx)
    before = dough_metrics(S, R, p)
    for it in range(rounds):
        # a) dots/bosses wider than dot: ring if the ring would enclose >= pocket mm, else shrink to a dot
        r_ = p["dot"] / 2 + 0.05
        for b in _polys(R.buffer(-r_).buffer(r_)):
            if b.area < 0.5:
                continue
            d, _ = inscribed_d(b)
            if d >= p["pocket"] + 2 * p["rib_w"]:
                rep = b.difference(b.buffer(-p["rib_w"]))
            else:
                rep = b.buffer(-(d - (p["dot"] - 0.3)) / 2)   # 0.3 mm margin: the slab overlap adds 0.2
            R = unary_union([R.difference(b.buffer(0.3)), rep])
        # b) closed pockets smaller than pocket: fill if the result stays a dot, else cut a 3 mm break
        D = S.difference(R)
        bd = S.boundary.buffer(0.05)
        ocean = unary_union([q for q in _polys(D) if q.intersects(bd)])
        for q in _polys(D):
            if q.area > 0.3 and not q.intersects(bd):
                d, pt = inscribed_d(q)
                if d < p["pocket"]:
                    if d + 2 * p["rib_w"] <= p["dot"] + 0.6:
                        R = R.union(q)
                    elif not ocean.is_empty:
                        a, b2 = nearest_points(pt, ocean)
                        R = R.difference(LineString([(a.x, a.y), (b2.x, b2.y)]).buffer((p["land"] + 0.15) / 2))
        # c) land narrower than 'land' between ribs / rib and wall: cut the ribs back, never fill
        D = S.difference(R)
        nar = D.difference(D.buffer(-(p["land"] + 0.15) / 2).buffer((p["land"] + 0.15) / 2))
        for g in _polys(nar):
            if g.area > 4.0:
                R = R.difference(g.buffer(1.0))
        # d) slivers and specks out
        R = R.buffer(-0.45).buffer(0.45)
        R = unary_union([q for q in _polys(R) if q.area > 5.0]).union(fx)
        m = dough_metrics(S, R, p)
        if m["narrow_land_spots"] == 0 and m["pockets_under"] == 0 and m["fat_dots"] == 0:
            break
    return R.simplify(p["simp"]), before, dough_metrics(S, R, p)


# ---------------------------------------------------------------- bridges
def _contacts(piece, struct, p):
    c = piece.intersection(struct)
    return [g for g in _polys(c) if g.area >= 1.8]


def _bar(a, b, bw, zone, S):
    d = math.hypot(a.x - b.x, a.y - b.y)
    if d < 0.3:
        bar = Point(a.x, a.y).buffer(bw / 2)
    else:
        ux, uy = (b.x - a.x) / d, (b.y - a.y) / d
        bar = LineString([(a.x - ux * 1.5, a.y - uy * 1.5), (b.x + ux * 1.5, b.y + uy * 1.5)]).buffer(bw / 2, cap_style=2)
    return bar.intersection(zone.union(S))


def place_bridges(S, R, p=P):
    """6 mm lattice (no free bar run over maxrun), then every rib piece gets >= 2 bar contacts
    (1 if under 10 mm long; touching the wall counts as one), then the back plan is ONE piece."""
    w = p["wall_back"]; bw = p["bar_w"]
    base = S.buffer(w + p["rim_w"]).difference(S)
    zone = S.buffer(w + 0.6)
    minx, miny, maxx, maxy = S.bounds
    kv = max(1, math.ceil((maxx - minx) / p["maxrun"]) - 1)
    kh = max(1, math.ceil((maxy - miny) / p["maxrun"]) - 1)
    lines = []
    for i in range(kv):
        x = minx + (maxx - minx) * (i + 1) / (kv + 1)
        lines.append(LineString([(x, miny - 5), (x, maxy + 5)]))
    for j in range(kh):
        y = miny + (maxy - miny) * (j + 1) / (kh + 1)
        lines.append(LineString([(minx - 5, y), (maxx + 5, y)]))
    cand = _polys(unary_union([l.buffer(bw / 2, cap_style=2) for l in lines]).intersection(zone))
    bars = [q for q in cand if q.intersection(R).area > 0.5 or max(q.bounds[2] - q.bounds[0], q.bounds[3] - q.bounds[1]) > 12]
    n0 = len(bars)
    Rp = _polys(R)
    extra = 0
    wallc = S.buffer(0.05)
    for _ in range(120):
        U = unary_union(bars + [base])
        worst = None
        for pc in Rp:
            need = 1 if pc.length / 2 < 10 else 2
            cs = _contacts(pc, U, p)
            nc = len(cs) + (1 if pc.intersects(wallc) else 0)
            if nc < need:
                worst = (pc, cs)
                break
        if worst is None:
            break
        pc, cs = worst
        pts = [Point(c) for c in list(pc.exterior.coords)[::2]]
        ref = unary_union(cs) if cs else None
        far = max(pts, key=lambda q: (q.distance(ref) if ref is not None else 0) + 0.001 * q.distance(U))
        tgt = U.difference(pc.buffer(0.5))
        a, b = nearest_points(far, tgt)
        bars.append(_bar(a, b, bw, zone, S))
        extra += 1
    for _ in range(100):
        F = unary_union([base] + bars + Rp).buffer(0.01)
        comps = _polys(F)
        if len(comps) <= 1:
            break
        main = next(g for g in comps if g.intersects(base))
        g = sorted([c for c in comps if c is not main], key=lambda c: c.distance(main))[0]
        a, b = nearest_points(g, main)
        bars.append(_bar(a, b, bw, zone, S))
        extra += 1
    return (unary_union(bars) if bars else Polygon()), n0, extra


def bridge_report(S, R, bars, p=P):
    U = unary_union([bars, S.buffer(p["wall_back"] + p["rim_w"]).difference(S)])
    wallc = S.buffer(0.05)
    bad = 0
    for pc in _polys(R):
        nc = len(_contacts(pc, U, p)) + (1 if pc.intersects(wallc) else 0)
        if nc < (1 if pc.length / 2 < 10 else 2):
            bad += 1
    win = S.difference(unary_union([R, bars]))
    ds = [inscribed_d(g)[0] for g in _polys(win) if g.area > 6]
    return dict(ribs_short_of_contacts=bad, windows=len(ds), windows_under=sum(d < p["window"] for d in ds),
                min_window_d=round(min(ds), 1) if ds else None)



# ---------------------------------------------------------------- triangulation
def _tri_inside(px, py, ax, ay, bx, by, cx, cy, eps=1e-9):
    d1 = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    d2 = (cx - bx) * (py - by) - (cy - by) * (px - bx)
    d3 = (ax - cx) * (py - cy) - (ay - cy) * (px - cx)
    return (d1 > eps) & (d2 > eps) & (d3 > eps)


def _seg_cross_any(ax, ay, bx, by, X, Y):
    X2 = np.roll(X, -1); Y2 = np.roll(Y, -1)

    def side(px, py, qx, qy, rx, ry):
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)
    d1 = side(ax, ay, bx, by, X, Y); d2 = side(ax, ay, bx, by, X2, Y2)
    d3 = side(X, Y, X2, Y2, ax, ay); d4 = side(X, Y, X2, Y2, bx, by)
    return bool(((d1 * d2 < -1e-12) & (d3 * d4 < -1e-12)).any())


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




# ---------------------------------------------------------------- slabs
def make_slabs(S, R, bars, p=P):
    """Stack of footprints from the back (slab 0 = rim + bridges + ribs) to the cutting edge. The wall
    steps in from 1.6 mm at the back to 1.05 mm, and the last 2 mm is exactly wall_tip (0.86 mm = two
    0.43 mm nozzle lines); nothing between 0.45 and 0.86. The top 2 mm of every rib is 0.2 mm slimmer
    per side (draft). Each slab sits inside the one below, so nothing overhangs."""
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
    cl = lambda g, r: g if g.is_empty else g.buffer(r, quad_segs=4).buffer(-r, quad_segs=4).simplify(0.02)
    R = cl(R, 0.1).buffer(0.05, quad_segs=2)       # 0.05 overlap: corner touches become real joints
    bars = bars.buffer(0.05, quad_segs=2)
    b0 = unary_union([cl(unary_union([bars, R]), 0.75), R])   # no gaps under 1.5 mm in the flat back plate
    fp = []
    for i in range(len(levels) - 1):
        zt, zm = levels[i + 1], 0.5 * (levels[i] + levels[i + 1])
        if i == 0:
            rim = S.buffer(p["wall_back"] + p["rim_w"], quad_segs=4).difference(S)
            g = unary_union([rim, b0])
        else:
            if zm >= tip0:
                w = p["wall_tip"]
            else:
                w = round(p["wall_back"] - (p["wall_back"] - 1.05) * (zm - t) / max(tip0 - t, 1e-6), 2)
            parts = [S.buffer(w, quad_segs=4).difference(S)]
            if zt <= rib_top - 2.0 + 1e-6:
                parts.append(R)
            elif zt <= rib_top + 1e-6:
                parts.append(R.buffer(-0.2))
            g = unary_union(parts)
        fp.append(shapely.set_precision(g.buffer(0), p["grid"]))
    return levels, fp, rib_top


# ---------------------------------------------------------------- checks in plain words
def _bodies(m):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    f = np.asarray(m.faces)
    n = len(m.vertices)
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]]])
    g = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    return int(connected_components(g, directed=False)[0])


def mesh_checks(m, S, R, bars, fps, p):
    r = {}
    r["watertight"] = bool(m.is_watertight)
    r["winding_consistent"] = bool(m.is_winding_consistent)
    r["volume_mm3"] = round(float(m.volume), 1)
    r["tris"] = int(len(m.faces))
    r["bodies"] = _bodies(m)
    r["overhang_mm2"] = round(float(sum(fps[j].difference(fps[j - 1].buffer(1e-3)).area for j in range(1, len(fps)))), 4)
    r["back_components"] = len(_polys(fps[0].buffer(0.01)))
    Rf = fps[2].intersection(S) if len(fps) > 2 else R
    r["final_stamp_level"] = dough_metrics(S, Rf, p)
    r["bridges"] = bridge_report(S, R, bars, p)
    r["bbox_mm"] = [round(float(x), 1) for x in (m.bounds[1] - m.bounds[0])]
    return r


def plain_checks(ck, info, p, notes=()):
    """[{level: pass|warn|block, text}] in words a baker can read. Only a broken mesh or a floating
    piece blocks the download."""
    out = []
    add = lambda level, text: out.append({"level": level, "text": text})
    ok_mesh = ck["watertight"] and ck["winding_consistent"]
    add("pass" if ok_mesh else "block",
        "The model is one closed solid, ready to slice." if ok_mesh else "The model has holes in its surface, so it cannot be printed. Try a simpler picture.")
    one = ck["bodies"] == 1 and ck["back_components"] == 1
    add("pass" if one else "block",
        "Every inside piece is held by the back bars: nothing floats." if one else "Some inside pieces are not attached to the cutter, so they would fall off.")
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
    if info.get("solid"):
        add("warn", "The picture is a solid shape, so the cookie has no inside lines. Use a line drawing for an embossed cookie.")
    add("pass", "Roll the dough to %g mm: the lines then press %g mm deep." % (p["dough"], p["imprint"]))
    for n in notes:
        add("warn", n)
    return out


# ---------------------------------------------------------------- build with caches
_PREP = OrderedDict()    # (art hash, size) -> outline + ribs  (the slow skeleton step)
_BUILT = OrderedDict()   # (art hash, all params) -> finished build


def _hash(upload):
    return hashlib.sha1(upload).hexdigest()


def prepare(upload, name, cp: CookieParams):
    from . import art as artmod
    key = (_hash(upload), round(cp.size_mm, 1))
    if key in _PREP:
        _PREP.move_to_end(key)
        r = dict(_PREP[key]); r["prep_cached"] = True
        return r
    t = time.time()
    try:
        art = artmod.load("upload", upload, name, "trace")
    except Exception as exc:       # ArtError, or the image could not be decoded
        raise CookieError("could not read the picture: %s" % exc)
    p = design(cp)
    ink = ink_from_art(art, cp.size_mm)
    t1 = time.time()
    S, R, info = parts_from_ink(ink, p)
    # honour the asked size: the CUT shape (not the picture frame) gets the longest side size_mm
    bx0, by0, bx1, by1 = S.bounds
    f = cp.size_mm / max(bx1 - bx0, by1 - by0, 1e-9)
    S = shapely.affinity.scale(S, f, f, origin=(0, 0))
    R = shapely.affinity.scale(R, f, f, origin=(0, 0)) if not R.is_empty else R
    R = clean_ribs(R, S, p)
    r = dict(S=S, R=R, info=info, t_art=round(t1 - t, 2), t_ribs=round(time.time() - t1, 2), prep_cached=False)
    _PREP[key] = r
    while len(_PREP) > 4:
        _PREP.popitem(last=False)
    return dict(r)


def build(upload, name, cp: CookieParams):
    if not upload:
        raise CookieError("no picture to use")
    key = (_hash(upload), tuple(sorted(cp.to_dict().items())))
    if key in _BUILT:
        _BUILT.move_to_end(key)
        r = dict(_BUILT[key]); r["cached"] = True
        return r
    prep = prepare(upload, name, cp)
    p = design(cp)
    S = prep["S"]
    T = {"art": prep["t_art"], "ribs": prep["t_ribs"]}
    t = time.time()
    R, before, after = rules_gate(S, prep["R"], p); T["rules"] = round(time.time() - t, 2); t = time.time()
    bars, n0, extra = place_bridges(S, R, p); T["bridges"] = round(time.time() - t, 2); t = time.time()
    levels, fps, rib_top = make_slabs(S, R, bars, p)
    m, mi = build_mesh(levels, fps, p); T["mesh"] = round(time.time() - t, 2)
    ck = mesh_checks(m, S, R, bars, fps, p)
    ck.update(rules_before=before, rules_after=after, bars_lattice=n0, bars_extra=extra, rib_top_z=rib_top)
    res = dict(S=S, R=R, bars=bars, mesh=m, ck=ck, info=prep["info"], p=p, cp=cp, time=T,
               prep_cached=prep["prep_cached"], cached=False, levels=levels)
    _BUILT[key] = res
    while len(_BUILT) > 2:
        _BUILT.popitem(last=False)
    return dict(res)


# ---------------------------------------------------------------- API
def _rings(g, tol=0.03):
    if g.is_empty:
        return []
    g = g.simplify(tol)
    out = []
    for pg in _polys(g):
        out.append([[[round(x, 2), round(y, 2)] for x, y in ring.coords] for ring in [pg.exterior] + list(pg.interiors)])
    return out


def preview(params: dict, upload: bytes | None = None, upload_name: str | None = None) -> dict:
    """-> {size, checks (plain words), can_export, geom (mm polygons of the CUTTER as printed), timings}.
    The page draws the back view straight from geom and the pressed cookie as its mirror."""
    cp = CookieParams.from_dict(params)
    r = build(upload, upload_name, cp)
    p, S = r["p"], r["S"]
    checks_ = plain_checks(r["ck"], r["info"], p, getattr(cp, "notes", []))
    w = S.bounds[2] - S.bounds[0]
    h = S.bounds[3] - S.bounds[1]
    return {
        "params": cp.to_dict(),
        "size": {"cut_w": round(w, 1), "cut_h": round(h, 1), "outer_w": r["ck"]["bbox_mm"][0], "outer_h": r["ck"]["bbox_mm"][1],
                 "height": p["H"], "tris": r["ck"]["tris"]},
        "checks": checks_,
        "can_export": not any(c["level"] == "block" for c in checks_),
        "geom": {"cut": _rings(S, 0.05), "wall": _rings(S.buffer(p["wall_back"]), 0.05),
                 "rim": _rings(S.buffer(p["wall_back"] + p["rim_w"]), 0.08), "bars": _rings(r["bars"], 0.05),
                 "ribs": _rings(r["R"], 0.03)},
        "rules": {"before": r["ck"]["rules_before"], "after": r["ck"]["rules_after"], "final": r["ck"]["final_stamp_level"]},
        "timings": {**r["time"], "cached": bool(r["cached"]), "art_cached": bool(r["prep_cached"])},
        "solid": bool(r["info"].get("solid")),
    }


def export_bytes(params: dict, upload: bytes | None = None, upload_name: str | None = None) -> dict:
    """-> {stl: bytes, sidecar: dict, blocked: bool, checks, filename}. Blocked only for a broken mesh or a floating piece."""
    cp = CookieParams.from_dict(params)
    r = build(upload, upload_name, cp)
    checks_ = plain_checks(r["ck"], r["info"], r["p"], getattr(cp, "notes", []))
    blocked = any(c["level"] == "block" for c in checks_)
    S = r["S"]
    w = S.bounds[2] - S.bounds[0]
    h = S.bounds[3] - S.bounds[1]
    stl = b"" if blocked else bytes(r["mesh"].export(file_type="stl"))
    side = {"kind": "cookie-cutter", "params": cp.to_dict(), "cut_shape_mm": [round(w, 1), round(h, 1)],
            "checks": checks_, "design": {k: r["p"][k] for k in ("wall_tip", "bar_w", "base_t", "maxrun", "land", "pocket", "dot", "rib_w")},
            "mirrored_for_pressing": True, "triangles": r["ck"]["tris"],
            "print": "Back plate flat on the bed, 0.2 mm layers, 0.4 mm nozzle, no supports."}
    return {"stl": stl, "sidecar": side, "blocked": blocked, "checks": checks_,
            "filename": "cookie-cutter-%dx%d.stl" % (round(w), round(h))}
