"""Portrait sketch stage (app/SKETCH_SPEC.md section 8). Public test photo: skimage astronaut.
A private photo at app/out/sketch/test_person.webp is used only when it exists (it is never committed)."""
import io
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from scipy import ndimage as ndi

from engine import api, art as artmod, sketch as sk
from engine.params import Params

APP = Path(__file__).resolve().parents[1]
OUT = APP / "out" / "sketch"
PRIVATE = OUT / "test_person.webp"
W_MM = 140.0


def astronaut_png():
    from skimage import data
    b = io.BytesIO()
    Image.fromarray(data.astronaut()).save(b, "PNG")
    return b.getvalue()


@pytest.fixture(scope="module")
def astro():
    data = astronaut_png()
    t = time.time()
    s = sk.make_sketch(data, W_MM, measure=True, debug=True)
    return data, s, time.time() - t


def test_face_found_and_crop_contains_face(astro):
    data, s, _ = astro
    assert s.report["face_found"] and s.report["face_path"] == "cascade"
    img = Image.open(io.BytesIO(data)).convert("RGB")
    g = sk.geometry(img)
    fx, fy, fw, fh = g["face"]
    x0, y0, x1, y1 = g["crop"]
    assert x0 <= fx and y0 <= fy and x1 >= fx + fw and y1 >= fy + fh


def test_clay_floor_line_and_gap(astro):
    _, s, _ = astro
    assert s.report["min_line_mm"] >= 1.0
    assert s.report["min_gap_mm"] >= 1.0
    # independent check: opening the ink / paper by a 1 mm disk changes (almost) nothing
    m = s.mask
    ppm = s.ppm
    r = 0.5 * ppm
    for a in (m, ~m):
        a = np.pad(a, 3, constant_values=False) if a is m else np.pad(a, 3, constant_values=True)
        e = ndi.distance_transform_edt(a) > r - 0.5
        op = a & (ndi.distance_transform_edt(~e) <= r)
        lost = float((a & ~op).sum()) / max(1.0, float(a.sum()))
        assert lost < 0.01


def test_blacks_and_tone_share(astro):
    _, s, _ = astro
    assert s.report["blacks"] <= 3
    assert 0.15 <= s.report["tone_share"] <= 0.50


def test_light_side_is_brighter_side(astro):
    data, s, _ = astro
    L = sk._L_from_rgb(s.crop_rgb)
    bx, by, bw, bh = s.face_box
    xa, xb = int(bx), int(bx + bw)
    ya, yb = int(by), int(by + bh)
    mid = (xa + xb) // 2
    left = L[ya:yb, xa:mid].mean() >= L[ya:yb, mid:xb].mean()
    assert s.report["light_side"] == ("left" if left else "right")


def test_eyes_have_ink_and_mouth_has_horizontal_stroke(astro):
    _, s, _ = astro
    bx, by, bw, bh = s.face_box
    m = s.mask
    for c0, c1 in ((0.15, 0.45), (0.55, 0.85)):
        box = m[int(by + 0.30 * bh):int(by + 0.50 * bh), int(bx + c0 * bw):int(bx + c1 * bw)]
        assert box.mean() > 0.03
    mouth = m[int(by + 0.68 * bh):int(by + 0.85 * bh), int(bx + 0.25 * bw):int(bx + 0.75 * bw)]
    # a near-horizontal stroke: some row of the mouth box is at least 25% ink in a long run
    runs = 0
    for row in mouth:
        lab, n = ndi.label(row)
        if n:
            runs = max(runs, int(max(ndi.sum(row, lab, index=np.arange(1, n + 1)))))
    assert runs >= 0.2 * bw * 0.5 / 2


def test_sketch_time(astro):
    _, s, _ = astro
    t = time.time()
    sk.make_sketch(astronaut_png(), W_MM, measure=False)
    assert time.time() - t < 8.0  # load-dependent; typical 3.3-3.7 s alone


def portrait_params(data):
    fit = api.fit_portrait({"length": 250.0}, data)
    return {"art_source": "upload", "art_style": "portrait", "pitch_preview": 0.5, "pitch_export": 0.5,
            "diameter": fit["diameter"], "n_around": fit["n_around"], "n_along": fit["n_along"]}


def test_fit_portrait_and_preview_export():
    data = astronaut_png()
    fit = api.fit_portrait({"length": 250.0}, data)
    assert fit["n_around"] == 1 and fit["n_along"] == 1 and 16 <= fit["diameter"] <= 100
    p = portrait_params(data)
    r = api.preview(p, data, "astro.png")
    assert r["can_export"], [x for x in r["rules"] if x["action"] == "BLOCK"]
    rep = r["art_report"]["sketch"]
    assert rep["face_found"] and rep["blacks"] <= 3
    e = api.export_bytes(p, data, "astro.png")
    assert not e["blocked"]
    z = zipfile.ZipFile(io.BytesIO(e["zip"]))
    import trimesh
    mesh = trimesh.load(io.BytesIO(z.read("roller.stl")), file_type="stl")
    assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "astronaut_slab.png").write_bytes(z.read("slab_preview.png"))


def test_portrait_cache_key_changes_with_tile_width():
    data = astronaut_png()
    a = artmod.load("upload", data, "a.png", "portrait", 100.0, 0.5, True)
    b = artmod.load("upload", data, "a.png", "portrait", 100.0, 0.5, True)
    c = artmod.load("upload", data, "a.png", "portrait", 140.0, 0.5, True)
    assert a is b and a is not c
    t = artmod.load("upload", data, "a.png", "trace", 140.0)
    assert t is not c and t.sketch is None


def test_portrait_stage_stays_pyodide_safe():
    code = (
        "import sys\n"
        "for m in ('cv2','torch','tensorflow','onnxruntime','build123d','manifold3d','lib3mf'): sys.modules[m]=None\n"
        f"sys.path.insert(0, r'{APP}')\n"
        "import io\nfrom PIL import Image\nfrom skimage import data\nfrom engine import api\n"
        "b=io.BytesIO(); Image.fromarray(data.astronaut()).save(b,'PNG')\n"
        "r=api.preview({'art_source':'upload','art_style':'portrait','n_around':1,'n_along':1,'diameter':60.0,'pitch_preview':0.5},b.getvalue(),'a.png')\n"
        "assert r['art_report']['sketch']['face_found']\nprint('OK')\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0 and "OK" in out.stdout, out.stderr[-2000:]


def test_review_images_astronaut(astro):
    data, s, _ = astro
    OUT.mkdir(parents=True, exist_ok=True)
    Image.fromarray(s.crop_rgb).save(OUT / "astronaut_photo.png")
    sketch_img = Image.fromarray(np.where(s.mask, 0, 255).astype(np.uint8))
    sketch_img.save(OUT / "astronaut_sketch.png")
    a = Image.fromarray(s.crop_rgb)
    c = Image.new("RGB", (a.width * 2 + 20, a.height), "white")
    c.paste(a, (0, 0))
    c.paste(sketch_img.convert("RGB"), (a.width + 20, 0))
    c.save(OUT / "astronaut_compare.png")


@pytest.mark.skipif(not PRIVATE.exists(), reason="private test photo not present")
def test_private_photo_webp():
    data = PRIVATE.read_bytes()
    s = sk.make_sketch(data, W_MM, measure=True)
    assert s.report["face_found"]
    assert s.report["min_line_mm"] >= 1.0 and s.report["min_gap_mm"] >= 1.0
    assert s.report["blacks"] <= 3 and 0.15 <= s.report["tone_share"] <= 0.50
    img = Image.fromarray(s.crop_rgb)
    sketch_img = Image.fromarray(np.where(s.mask, 0, 255).astype(np.uint8))
    sketch_img.save(OUT / "person_sketch.png")
    c = Image.new("RGB", (img.width * 2 + 20, img.height), "white")
    c.paste(img, (0, 0))
    c.paste(sketch_img.convert("RGB"), (img.width + 20, 0))
    c.save(OUT / "person_compare.png")
    p = portrait_params(data)
    e = api.export_bytes(p, data, "test_person.webp")
    assert not e["blocked"]
    z = zipfile.ZipFile(io.BytesIO(e["zip"]))
    (OUT / "person_slab.png").write_bytes(z.read("slab_preview.png"))
