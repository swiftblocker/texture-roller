"""Cookie cutter (engine/cookie.py): synthetic art only (a heart with an inside line and an eye dot, a letter R)."""
import io
import math
import time

import numpy as np
import pytest
import shapely
import shapely.affinity
from PIL import Image, ImageDraw

from engine import api, cookie as K


def _areal(g):
    return g.is_empty or g.geom_type in ("Polygon", "MultiPolygon") or (
        g.geom_type == "GeometryCollection" and all(_areal(x) for x in g.geoms))


@pytest.fixture(scope="module", autouse=True)
def no_risky_geos():
    """In the browser (Pyodide: shapely 2.0.6 on GEOS 3.12) a GEOS topology error aborts the whole runtime, so
    the engine must not buffer anything but a point or a two-point line, and must run every area overlay on
    a fixed grid (snap-rounding). Anything else raises here."""
    from shapely.geometry.base import BaseGeometry
    mp = pytest.MonkeyPatch()

    def simple(g):
        return g.geom_type == "Point" or (g.geom_type == "LineString" and len(g.coords) == 2)

    fb = shapely.buffer
    mp.setattr(shapely, "buffer", lambda g, d, *a, **k: fb(g, d, *a, **k) if simple(g) else (_ for _ in ()).throw(AssertionError("buffer of " + g.geom_type)))
    mb = BaseGeometry.buffer
    mp.setattr(BaseGeometry, "buffer", lambda self, d, *a, **k: mb(self, d, *a, **k) if simple(self) else (_ for _ in ()).throw(AssertionError("buffer of " + self.geom_type)))
    for name in ("difference", "intersection", "union", "symmetric_difference"):
        fn = getattr(shapely, name)

        def f(a, b, grid_size=None, _fn=fn, _n=name, **k):
            if grid_size is None and _areal(a) and _areal(b):
                raise AssertionError(_n + " on areas without grid_size")
            return _fn(a, b, grid_size=grid_size, **k)
        mp.setattr(shapely, name, f)

        def m(self, other, grid_size=None, _fn=fn, _n=name):
            if grid_size is None and _areal(self) and _areal(other):
                raise AssertionError(_n + " on areas without grid_size")
            return _fn(self, other, grid_size=grid_size)
        mp.setattr(BaseGeometry, name, m)
    for name in ("union_all", "unary_union"):
        fn = getattr(shapely, name)

        def u(geoms, grid_size=None, _fn=fn, _n=name, **k):
            if grid_size is None and any(_areal(g) and not g.is_empty for g in geoms):
                raise AssertionError(_n + " on areas without grid_size")
            return _fn(geoms, grid_size=grid_size, **k)
        mp.setattr(shapely, name, u)
    yield
    mp.undo()


def _png(im):
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def heart_png(n=600):
    im = Image.new("L", (n, n), 255)
    d = ImageDraw.Draw(im)
    pts = []
    for t in np.linspace(0, 2 * math.pi, 200):
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((n / 2 + x * 16, n / 2 - y * 16 - 10))
    d.polygon(pts, outline=0, width=8)
    d.arc((200, 260, 400, 420), 20, 160, fill=0, width=12)       # an inside line
    d.ellipse((260, 190, 300, 240), fill=0)                       # an eye dot
    return _png(im)


def letter_r_png(n=500):
    im = Image.new("L", (n, n), 255)
    d = ImageDraw.Draw(im)
    d.ellipse((10, 10, n - 10, n - 10), outline=0, width=8)
    w = 26
    d.line((170, 340, 170, 150), fill=0, width=w)
    d.line((170, 150, 270, 150), fill=0, width=w)
    d.arc((130, 150, 330, 270), -90, 90, fill=0, width=w)
    d.line((170, 255, 270, 255), fill=0, width=w)
    d.line((250, 258, 335, 345), fill=0, width=w)
    return _png(im)


@pytest.fixture(scope="module")
def heart():
    return heart_png()


def test_heart_builds_clean(heart):
    cp = K.CookieParams.from_dict({"size_mm": 80})
    r = K.build(heart, "heart.png", cp)
    ck = r["ck"]
    assert ck["watertight"] and ck["winding_consistent"]
    assert ck["volume_mm3"] > 0
    assert ck["bodies"] == 1
    assert ck["back_components"] == 1
    assert ck["overhang_mm2"] < 0.05
    # rules gate: nothing left to fix, on the ribs and on the final footprint
    for m in (ck["rules_after"], ck["final_stamp_level"]):
        assert m["narrow_land_spots"] == 0 and m["pockets_under"] == 0 and m["fat_dots"] == 0
    assert ck["bridges"]["ribs_short_of_contacts"] == 0
    # the eye dot and the smile survive as ribs
    assert len(K._polys(r["R"])) >= 2


def test_size_is_honoured(heart):
    for size in (60.0, 120.0):
        r = api.cookie_preview({"size_mm": size}, heart, "heart.png")
        longest = max(r["size"]["cut_w"], r["size"]["cut_h"])
        assert abs(longest - size) <= 1.0, (size, longest)


def test_preview_json_and_checks(heart):
    r = api.cookie_preview({}, heart, "heart.png")
    assert r["can_export"]
    assert {"cut", "wall", "rim", "bars", "ribs"} <= set(r["geom"])
    texts = " ".join(c["text"] for c in r["checks"])
    assert "0.86 mm" in texts and "held by the back bars" in texts
    assert all(c["level"] in ("pass", "warn", "block") for c in r["checks"])
    import json
    json.dumps(r)   # plain JSON


def test_tip_is_two_lines_and_nothing_between(heart):
    r = K.build(heart, "heart.png", K.CookieParams.from_dict({}))
    S, p, levels = r["S"], r["p"], r["levels"]
    widths = []
    for f in r["fps"][1:]:
        ring = shapely.difference(f, S, grid_size=0.002)       # the wall band (ribs sit inside the cut shape)
        widths.append(ring.area / S.length)
    assert abs(widths[-1] - 0.86) < 0.08, widths
    assert all(not (0.47 < w < 0.82) for w in widths), widths
    assert levels[-1] == p["H"]


def test_mirror_letter_r_reads_correctly():
    png = letter_r_png()
    cp = K.CookieParams.from_dict({"size_mm": 70})
    r = K.build(png, "R.png", cp)
    S, Rm = r["S"], r["R"]
    # In the art the R sits left of the ring's centre. The printed cutter is the mirror image, so its lines
    # sit right of centre; the pressed cookie (the mirror of the cutter) then reads like the art again.
    assert Rm.centroid.x > S.centroid.x + 1.0, (Rm.centroid.x, S.centroid.x)
    # the same art drawn mirrored must give the mirrored cutter
    im = Image.open(io.BytesIO(png)).transpose(Image.FLIP_LEFT_RIGHT)
    r2 = K.build(_png(im), "R2.png", cp)
    back = shapely.affinity.translate(K.mirror(r2["R"], r2["S"].centroid.x), r["S"].centroid.x - r2["S"].centroid.x, r["S"].centroid.y - r2["S"].centroid.y)
    inter = shapely.intersection(back, Rm, grid_size=0.01).area
    union = shapely.union_all([back, Rm], grid_size=0.01).area
    assert inter / union > 0.55, inter / union


def test_cache_hit_is_faster(heart):
    cp = K.CookieParams.from_dict({"size_mm": 77})
    K._PREP.clear(); K._BUILT.clear()
    t = time.time(); K.build(heart, "heart.png", cp); cold = time.time() - t
    t = time.time(); r = K.build(heart, "heart.png", cp); hot = time.time() - t
    assert r["cached"] and hot < cold / 5
    # a new dough thickness reuses the slow rib step
    r2 = K.build(heart, "heart.png", K.CookieParams.from_dict({"size_mm": 77, "dough_mm": 7}))
    assert r2["prep_cached"] and not r2["cached"]


def test_params_are_clamped():
    cp = K.CookieParams.from_dict({"size_mm": 1000, "dough_mm": 6, "imprint_mm": 5.5, "wall_mm": 10})
    assert cp.size_mm == 200.0
    assert cp.imprint_mm <= cp.dough_mm - 2.0
    assert cp.wall_mm >= cp.dough_mm - cp.imprint_mm + 6.4 - 1e-6
    assert cp.notes
    with pytest.raises(K.CookieError):
        K.CookieParams.from_dict({"size_mm": "abc"})


def test_export_stl_and_sidecar(heart):
    e = api.cookie_export({"size_mm": 70}, heart, "heart.png")
    assert not e["blocked"] and len(e["stl"]) > 1000 and e["filename"].endswith(".stl")
    assert e["sidecar"]["mirrored_for_pressing"] is True
    import trimesh
    m = trimesh.load(io.BytesIO(e["stl"]), file_type="stl")
    assert m.is_watertight and m.volume > 0


def test_no_art_is_an_error():
    with pytest.raises(K.CookieError):
        K.build(None, None, K.CookieParams.from_dict({}))
    with pytest.raises(K.CookieError):
        K.build(b"not an image", "x.png", K.CookieParams.from_dict({"size_mm": 41}))


def heart2_png(n=600):
    """Heart outline, two eye dots and a smile arc (the diagnostic drawing from the live site)."""
    im = Image.new("L", (n, n), 255)
    d = ImageDraw.Draw(im)
    pts = []
    for t in np.linspace(0, 2 * math.pi, 240):
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((n / 2 + x * 17, n / 2 - y * 17 - 10))
    d.polygon(pts, outline=0, width=9)
    d.ellipse((205, 215, 245, 265), fill=0)
    d.ellipse((355, 215, 395, 265), fill=0)
    d.arc((210, 290, 390, 420), 20, 160, fill=0, width=12)
    return _png(im)


@pytest.mark.parametrize("name,maker", [("heart", heart_png), ("heart2", heart2_png), ("R", letter_r_png)])
def test_size_sweep_never_breaks(name, maker):
    """Every 5 mm from 40 to 140: one closed solid, nothing floating (regression: 80 mm heart had a
    single unreferenced vertex counted as a body and a four-face pinch column on GEOS 3.14)."""
    data = maker()
    for size in range(40, 145, 5):
        r = K.build(data, name + ".png", K.CookieParams.from_dict({"size_mm": size}))
        ck = r["ck"]
        assert ck["watertight"] and ck["winding_consistent"], (name, size)
        assert ck["bodies"] == 1 and ck["back_components"] == 1, (name, size, ck["bodies"], ck["back_components"])


# ---------------------------------------------------------------- outline checks (no cv2 needed)
def _texts(r, level=None):
    return [c["text"] for c in r["checks"] if level is None or c["level"] == level]


def test_neck_blocks_a_dumbbell():
    im = Image.new("L", (700, 400), 255)
    d = ImageDraw.Draw(im)
    d.ellipse((20, 100, 220, 300), fill=0)
    d.ellipse((480, 100, 680, 300), fill=0)
    d.rectangle((215, 192, 485, 208), fill=0)          # a thin neck: about 2 mm at 80 mm
    r = api.cookie_preview({"size_mm": 80}, _png(im), "dumbbell.png")
    assert not r["can_export"]
    assert any("neck thinner than 6 mm" in t for t in _texts(r, "block"))
    assert r["outline"]["neck_kept"] < 0.9 or r["outline"]["neck_pieces"] > 1


def test_ragged_and_thin_arms_warn():
    n = 600
    im = Image.new("L", (n, n), 255)
    d = ImageDraw.Draw(im)
    pts = []
    for i in range(240):
        a = 2 * math.pi * i / 240
        rr = 270 if i % 2 else 240          # a saw-tooth edge
        pts.append((n / 2 + rr * math.cos(a), n / 2 + rr * math.sin(a)))
    d.polygon(pts, fill=0)
    r = api.cookie_preview({"size_mm": 80}, _png(im), "saw.png")
    assert r["outline"]["ragged"] > 1.35, r["outline"]
    assert any("ragged" in t for t in _texts(r, "warn"))
    # a thin crescent: low fullness
    im = Image.new("L", (n, n), 255)
    d = ImageDraw.Draw(im)
    d.ellipse((30, 30, 570, 570), fill=0)
    d.ellipse((120, 60, 640, 540), fill=255)
    r = api.cookie_preview({"size_mm": 80}, _png(im), "crescent.png")
    assert r["outline"]["fullness"] < 0.55, r["outline"]


def test_drawings_pass_outline_checks(heart):
    r = api.cookie_preview({"size_mm": 80}, heart, "heart.png")
    assert r["can_export"] and r["photo"] is None
    assert r["outline"]["neck_kept"] >= 0.9 and r["outline"]["ragged"] <= 1.35 and r["outline"]["fullness"] >= 0.55
    assert not any("solid" in t and "photo" in t for t in _texts(r))


# ---------------------------------------------------------------- photos
def _photo_png(name):
    import skimage.data as sd
    try:
        arr = getattr(sd, name)()
    except Exception:
        pytest.skip("skimage sample photo %s not available offline" % name)
    return _png(Image.fromarray(arr).convert("RGB"))


def test_photo_detection_needs_no_cv2(heart):
    from engine import photo
    assert photo.analyze(_photo_png("astronaut"))["is_photo"]
    assert not photo.analyze(heart)["is_photo"]
    assert not photo.analyze(letter_r_png())["is_photo"]
    assert not photo.analyze(b"<svg xmlns='http://www.w3.org/2000/svg'/>")["is_photo"]


def test_photo_without_cv2_asks_for_it(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "cv2":
            raise ImportError("no cv2")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(K.CookieError, match="NEEDS_CV"):
        K.prepare(_photo_png("astronaut"), "a.png", K.CookieParams.from_dict({}))


@pytest.mark.parametrize("name,route", [("coffee", "subject"), ("astronaut", "head"), ("chelsea", "plaque")])
def test_photo_routes_export_with_ribs(name, route):
    pytest.importorskip("cv2")
    r = api.cookie_preview({"size_mm": 80}, _photo_png(name), name + ".png")
    assert r["photo"]["route"] == route, r["photo"]["route"]
    assert r["can_export"]
    assert len(r["geom"]["ribs"]) >= 3, len(r["geom"]["ribs"])
    assert r["photo"]["overlay"]["outline"] and r["photo"]["message"].startswith("Photo:")
    assert not any("picture is a solid shape" in t or "could not find lines" in t for t in _texts(r))
    e = api.cookie_export({"size_mm": 80}, _photo_png(name), name + ".png")
    assert not e["blocked"] and len(e["stl"]) > 1000


def test_rocket_photo_is_refused():
    pytest.importorskip("cv2")
    with pytest.raises(K.CookieError, match="could not find a clear subject"):
        api.cookie_preview({"size_mm": 80}, _photo_png("rocket"), "rocket.png")
    with pytest.raises(K.CookieError, match="could not find a clear subject"):
        api.cookie_export({"size_mm": 80}, _photo_png("rocket"), "rocket.png")


def test_photo_decision_does_not_depend_on_cookie_size():
    """Owner diagnostic: the rocket photo was refused at 80 mm but accepted at 110 mm, because the
    "enough lines" rule was measured in mm. What a photo is must not change with the size."""
    pytest.importorskip("cv2")
    import io as _io
    import skimage.data as _d
    from PIL import Image as _Image
    for arr, want in ((_d.rocket(), "refused"), (_d.coffee(), "subject")):
        b = _io.BytesIO(); _Image.fromarray(arr).convert("RGB").save(b, "JPEG", quality=92)
        got = set()
        for s in (40, 80, 110, 160):
            try:
                got.add((api.cookie_preview({"size_mm": s}, b.getvalue(), "p.jpg").get("photo") or {}).get("route"))
            except Exception as e:  # the refusal is a CookieError with the plain message
                got.add("refused" if "clear subject" in str(e) else "error")
        assert got == {want}, got
