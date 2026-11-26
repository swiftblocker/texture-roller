"""Cookie cutter (engine/cookie.py): synthetic art only (a heart with an inside line and an eye dot, a letter R)."""
import io
import math
import time

import numpy as np
import pytest
import shapely
import shapely.affinity
from PIL import Image, ImageDraw

from engine import api, art as artmod, cookie as K


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
    levels = r["levels"]
    S = r["S"]
    p = r["p"]
    _, fps, _ = K.make_slabs(S, r["R"], r["bars"], p)
    widths = []
    for f in fps[1:]:
        ring = f.intersection(S.buffer(2.0)).difference(S)
        widths.append(ring.area / S.length)
    assert abs(widths[-1] - 0.86) < 0.06
    assert all(not (0.46 < w < 0.84) for w in widths)
    assert levels[-1] == p["H"]


def test_mirror_letter_r_reads_correctly():
    png = letter_r_png()
    cp = K.CookieParams.from_dict({"size_mm": 70})
    r = K.build(png, "R.png", cp)
    S, Rm = r["S"], r["R"]
    # the pressed cookie is the mirror of the cutter; compare with the unflipped art
    art = artmod.load("upload", png, "R.png", "trace")
    ink0 = K.ink_from_art(art, 70, flip=False)
    S0, R0, _ = K.parts_from_ink(ink0)
    f = (S.bounds[2] - S.bounds[0]) / (S0.bounds[2] - S0.bounds[0])
    R0 = shapely.affinity.scale(R0, f, f, origin=(0, 0))
    S0 = shapely.affinity.scale(S0, f, f, origin=(0, 0))
    dx, dy = S0.centroid.x - S.centroid.x, S0.centroid.y - S.centroid.y
    cookie = shapely.affinity.translate(K.mirror(Rm, S.centroid.x), dx, dy)
    unflipped = shapely.affinity.translate(Rm, dx, dy)
    iou = lambda a, b: a.intersection(b).area / max(a.union(b).area, 1e-9)
    good, bad = iou(cookie, R0.buffer(0.6)), iou(unflipped, R0.buffer(0.6))
    assert good > bad + 0.1, (good, bad)


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
