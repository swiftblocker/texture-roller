"""Art sources -> polygons in a frame (x right, y UP), plus rasterisation.

Route for every source: segments (lines/Beziers) -> cleanup (drop zero-length, merge points
closer than 0.05 mm, flatten at 0.02 mm) -> polygons -> even-odd fill (XOR of subpaths).
PNG/JPG: grayscale, Otsu, potrace to Beziers, then the same route.
"""
from __future__ import annotations
import hashlib
import io
import math
from collections import OrderedDict
import numpy as np

FLATTEN_TOL = 0.02
MERGE_DIST = 0.05

PATTERNS = [
    {"id": "waves", "name": "Waves"},
    {"id": "chevron", "name": "Chevron"},
    {"id": "leaf", "name": "Leaf"},
    {"id": "plain", "name": "Plain (text only)"},
]


class ArtError(ValueError):
    pass


class Art:
    """subpaths: list of segment lists. segment = ('L',p0,p1) or ('C',p0,c1,c2,p1); points (x,y), y up."""

    def __init__(self, subpaths, frame, tiles=False, traced=False, name=""):
        self.sketch = None  # portrait report dict (art_style "portrait")
        self.subpaths = subpaths
        self.frame = frame  # (x0,y0,x1,y1)
        self.tiles = tiles
        self.traced = traced
        self.name = name

    @property
    def aspect(self):
        x0, y0, x1, y1 = self.frame
        return (x1 - x0) / max(y1 - y0, 1e-9)

    def rotated(self, k):
        k = (k // 90) % 4
        if k == 0:
            return self
        x0, y0, x1, y1 = self.frame
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

        def rot(p):
            x, y = p[0] - cx, p[1] - cy
            for _ in range(k):
                x, y = -y, x
            return (x, y)
        sub = [[(s[0],) + tuple(rot(p) for p in s[1:]) for s in sp] for sp in self.subpaths]
        w, h = (x1 - x0), (y1 - y0)
        if k % 2:
            w, h = h, w
        a = Art(sub, (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), self.tiles, self.traced, self.name)
        a.sketch = self.sketch
        return a

    def flatten(self, scale):
        """-> (list of Nx2 arrays in art units, report). scale = mm per art unit."""
        tol = FLATTEN_TOL / scale
        md = MERGE_DIST / scale
        polys, seg_in, seg_out = [], 0, 0
        for sp in self.subpaths:
            pts = []
            for s in sp:
                seg_in += 1
                p0 = np.array(s[1], float)
                p3 = np.array(s[-1], float)
                if s[0] == "C":
                    c1, c2 = np.array(s[2], float), np.array(s[3], float)
                    m = max(np.linalg.norm(p0 - 2 * c1 + c2), np.linalg.norm(c1 - 2 * c2 + p3))
                    n = int(min(400, max(1, math.ceil(math.sqrt(0.75 * m / tol)))))
                    t = np.linspace(0, 1, n + 1)[:, None]
                    q = ((1 - t) ** 3) * p0 + 3 * ((1 - t) ** 2) * t * c1 + 3 * (1 - t) * t * t * c2 + t ** 3 * p3
                else:
                    q = np.array([p0, p3])
                if not pts:
                    pts.extend(q.tolist())
                else:
                    pts.extend(q[1:].tolist())
            if len(pts) < 3:
                continue
            a = np.asarray(pts)
            keep = [0]
            for i in range(1, len(a)):  # drop zero-length + merge near points
                if np.linalg.norm(a[i] - a[keep[-1]]) >= md:
                    keep.append(i)
            a = a[keep]
            if len(a) > 1 and np.linalg.norm(a[0] - a[-1]) < md:
                a = a[:-1]
            if len(a) < 3:
                continue
            seg_out += len(a)
            polys.append(a)
        return polys, {"paths": len(polys), "segments_in": seg_in, "segments_out": seg_out}


def raster_polys(polys, sx, sy, fx0, fy0, ox, oy, ny, nx, ps):
    """sx, sy: mm per art unit (may differ = stretch). ox, oy: mm offset of the frame origin in the cell.
    ps = (psx, psy) mm per pixel. Pixel (r,c) centre at ((c+.5)*psx, (r+.5)*psy) mm; row 0 = y min. Even-odd = XOR of subpaths."""
    from skimage.draw import polygon
    m = np.zeros((ny, nx), bool)
    from PIL import Image, ImageDraw
    for a in polys:
        c = ((a[:, 0] - fx0) * sx + ox) / ps[0] - 0.5
        r = ((a[:, 1] - fy0) * sy + oy) / ps[1] - 0.5
        if len(a) > 40 and (c.max() - c.min()) * (r.max() - r.min()) > 4e4:
            # large polygons (traced portraits): PIL scanline fill, skimage's point-in-polygon is far slower
            c0, r0 = int(max(0, math.floor(c.min()) - 1)), int(max(0, math.floor(r.min()) - 1))
            c1, r1 = int(min(nx, math.ceil(c.max()) + 2)), int(min(ny, math.ceil(r.max()) + 2))
            if c1 <= c0 or r1 <= r0:
                continue
            im = Image.new("1", (c1 - c0, r1 - r0), 0)
            ImageDraw.Draw(im).polygon([(float(x - c0), float(y - r0)) for x, y in zip(c, r)], fill=1)
            m[r0:r1, c0:c1] ^= np.asarray(im, bool)
            continue
        rr, cc = polygon(r, c, shape=(ny, nx))
        if len(rr):
            m[rr, cc] ^= True
    return m


# ---------------- procedural -------------------------------------------------
def _poly_to_segs(a):
    pts = [tuple(p) for p in a]
    return [("L", pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]


def _pattern(pid):
    polys = []
    x = np.linspace(0, 1, 241)
    if pid == "waves":
        for y0 in (1 / 6, 1 / 2, 5 / 6):
            y = y0 + 0.05 * np.sin(2 * np.pi * x)
            polys.append(np.vstack([np.stack([x, y + 0.05], 1), np.stack([x[::-1], (y - 0.05)[::-1]], 1)]))
    elif pid == "chevron":
        x = np.linspace(0, 1, 401)
        tri = 0.07 * (np.abs(((2 * x) % 1.0) - 0.5) * 4 - 1)  # 2 periods per tile
        for y0 in (1 / 6, 1 / 2, 5 / 6):
            y = tri + y0
            polys.append(np.vstack([np.stack([x, y + 0.055], 1), np.stack([x[::-1], (y - 0.055)[::-1]], 1)]))
    elif pid == "plain":
        return Art([], (0, 0, 1, 1), tiles=True, name=pid)
    elif pid == "leaf":
        a, b = 0.22, 0.09
        for (cx, cy, ang) in ((0.25, 0.25, 45), (0.75, 0.25, -45), (0.25, 0.75, -45), (0.75, 0.75, 45)):
            u = np.linspace(-1, 1, 80)
            w = b * (1 - u * u)
            top = np.stack([a * u, w], 1)
            bot = np.stack([a * u[::-1], -w[::-1]], 1)
            L = np.vstack([top, bot[1:-1]])
            th = math.radians(ang)
            R = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
            polys.append(L @ R.T + np.array([cx, cy]))
    else:
        raise ArtError("unknown pattern %r" % pid)
    return Art([_poly_to_segs(p) for p in polys], (0, 0, 1, 1), tiles=True, name=pid)


# ---------------- SVG ------------------------------------------------------------
def _close(cur, start):
    if cur:
        a, b = cur[-1][-1], cur[0][1]
        if math.hypot(a[0] - b[0], a[1] - b[1]) > 1e-9:
            cur = cur + [("L", a, b)]
    return cur


def _load_svg(data: bytes) -> Art:
    import svgelements as se
    svg = se.SVG.parse(io.BytesIO(data), reify=True)
    subpaths = []
    for e in svg.elements():
        if not isinstance(e, se.Shape):
            continue
        fill = getattr(e, "fill", None)
        if fill is not None and getattr(fill, "value", 1) is None:
            continue  # fill none
        try:
            path = se.Path(e)
        except Exception:
            continue
        cur, start = [], None
        for s in path.segments(transformed=True):
            if isinstance(s, se.Move):
                if cur:
                    subpaths.append(_close(cur, start))
                cur, start = [], (s.end.x, s.end.y)
            elif isinstance(s, (se.Line, se.Close)):
                if s.start is None or s.end is None:
                    continue
                cur.append(("L", (s.start.x, s.start.y), (s.end.x, s.end.y)))
            elif isinstance(s, se.CubicBezier):
                cur.append(("C", (s.start.x, s.start.y), (s.control1.x, s.control1.y),
                            (s.control2.x, s.control2.y), (s.end.x, s.end.y)))
            elif isinstance(s, se.QuadraticBezier):
                p0 = np.array((s.start.x, s.start.y)); q = np.array((s.control.x, s.control.y)); p1 = np.array((s.end.x, s.end.y))
                cur.append(("C", tuple(p0), tuple(p0 + 2 / 3 * (q - p0)), tuple(p1 + 2 / 3 * (q - p1)), tuple(p1)))
            elif isinstance(s, se.Arc):
                for c in s.as_cubic_curves():
                    cur.append(("C", (c.start.x, c.start.y), (c.control1.x, c.control1.y),
                                (c.control2.x, c.control2.y), (c.end.x, c.end.y)))
        if cur:
            subpaths.append(_close(cur, start))
    subpaths = [sp for sp in subpaths if sp]
    if not subpaths:
        raise ArtError("SVG has no filled shapes")
    flipped = [[(s[0],) + tuple((p[0], -p[1]) for p in s[1:]) for s in sp] for sp in subpaths]  # y up
    vb = getattr(svg, "viewbox", None)
    allp = np.array([p for sp in flipped for s in sp for p in s[1:]])
    if vb is not None and vb.width and vb.height:
        frame = (vb.x, -(vb.y + vb.height), vb.x + vb.width, -vb.y)
    else:
        frame = (allp[:, 0].min(), allp[:, 1].min(), allp[:, 0].max(), allp[:, 1].max())
    return Art(flipped, frame, name="svg")


# ---------------- PNG / JPG -----------------------------------------------------------
def _load_raster(data: bytes) -> Art:
    from PIL import Image
    from skimage.filters import threshold_otsu
    im = Image.open(io.BytesIO(data))
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg
    im = im.convert("L")
    mx = 700
    if max(im.size) > mx:
        s = mx / max(im.size)
        im = im.resize((max(1, int(im.size[0] * s)), max(1, int(im.size[1] * s))), Image.LANCZOS)
    g = np.asarray(im)
    if g.min() == g.max():
        raise ArtError("image is a single flat colour")
    th = threshold_otsu(g)
    return _trace_mask(g <= th)


def _trace_mask(ink) -> Art:
    """Bool mask (True = filled art, row 0 = top) -> Art of Bezier subpaths via potrace."""
    import potrace
    mask = np.pad(np.asarray(ink, bool), 1)
    plist = potrace.Bitmap(~mask).trace(turdsize=2, alphamax=1.0, opticurve=True, opttolerance=0.2)
    H, W = mask.shape
    subpaths = []
    for curve in plist:
        sp = []
        p0 = (curve.start_point.x, curve.start_point.y)
        for seg in curve.segments:
            e = (seg.end_point.x, seg.end_point.y)
            if seg.is_corner:
                c = (seg.c.x, seg.c.y)
                sp.append(("L", p0, c))
                sp.append(("L", c, e))
            else:
                sp.append(("C", p0, (seg.c1.x, seg.c1.y), (seg.c2.x, seg.c2.y), e))
            p0 = e
        subpaths.append(sp)
    if not subpaths:
        raise ArtError("no dark art found in image")
    flipped = [[(s[0],) + tuple((p[0] - 1, H - 1 - p[1]) for p in s[1:]) for s in sp] for sp in subpaths]
    return Art(flipped, (0, 0, W - 2, H - 2), traced=True, name="raster")


_CACHE: "OrderedDict[str, Art]" = OrderedDict()
LAST = (None, None)


def _load_portrait(upload: bytes, tile_w: float, detail: float, shading: bool, gap_mm: float = 1.0) -> Art:
    from . import sketch as sketchmod
    sk = sketchmod.make_sketch(upload, tile_w, detail=detail, shading=shading, measure=False, gap_mm=gap_mm)
    m = sk.mask
    # trace at most ~5 px/mm: potrace is pure Python in the browser
    if sk.ppm > 5.0:
        f = 5.0 / sk.ppm
        from PIL import Image
        im = Image.fromarray((m * 255).astype(np.uint8)).resize(
            (max(8, int(m.shape[1] * f)), max(8, int(m.shape[0] * f))), Image.BOX)
        m = np.asarray(im) >= 128
    a = _trace_mask(m)
    a.name = "portrait"
    rep = dict(sk.report)
    a.sketch = rep
    return a


def _load_group(upload: bytes, art_h_mm: float) -> Art:
    from . import group as groupmod
    try:
        ink, rep = groupmod.make_group(upload, art_h_mm, ppm=5.0)
    except groupmod.GroupError as exc:
        raise ArtError(str(exc))
    a = _trace_mask(ink)
    a.name = "group"
    a.sketch = dict(rep, mode="group")
    return a


def load(art_source: str, upload: bytes | None = None, upload_name: str | None = None,
         art_style: str = "trace", tile_width_mm: float | None = None,
         sketch_detail: float = 0.5, sketch_shading: bool = True, sketch_gap_mm: float = 1.0,
         group_h_mm: float | None = None) -> Art:
    if art_source.startswith("pattern:"):
        key = art_source
        if key not in _CACHE:
            _CACHE[key] = _pattern(art_source.split(":", 1)[1])
        return _CACHE[key]
    if not upload:
        raise ArtError("art_source is 'upload' but no file was given")
    global LAST
    LAST = (upload, upload_name)
    key = hashlib.sha1(upload).hexdigest()
    head = upload[:512].lstrip().lower()
    nm = (upload_name or "").lower()
    is_svg = nm.endswith(".svg") or head.startswith(b"<?xml") or b"<svg" in head
    portrait = art_style == "portrait" and not is_svg
    grp = art_style == "group" and not is_svg
    if grp:
        gh = round(float(group_h_mm or 240.0) * 2) / 2.0
        key = "%s|group|%.1f" % (key, gh)
    if portrait:
        tw = float(tile_width_mm or 140.0)
        key = "%s|portrait|%.1f|%.2f|%d|%.2f" % (key, round(tw * 2) / 2.0, round(float(sketch_detail), 2), 1 if sketch_shading else 0, round(float(sketch_gap_mm), 2))
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    try:
        if is_svg:
            a = _load_svg(upload)
        elif grp:
            a = _load_group(upload, gh)
        elif portrait:
            a = _load_portrait(upload, round(tw * 2) / 2.0, float(sketch_detail), bool(sketch_shading), float(sketch_gap_mm))
        else:
            a = _load_raster(upload)
    except ArtError:
        raise
    except Exception as exc:
        if is_svg or not (portrait or grp):
            raise
        raise ArtError("could not read the picture: %s" % exc)
    _CACHE[key] = a
    while len(_CACHE) > 8:
        _CACHE.popitem(last=False)
    return a
