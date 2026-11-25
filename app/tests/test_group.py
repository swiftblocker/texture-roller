"""Group photo mode (engine/group.py). Public sample images only (skimage), never a private photo."""
import io
import time

import numpy as np
import pytest
from PIL import Image

cv2 = pytest.importorskip("cv2")

from engine import api, group as G  # noqa: E402


def _png(a):
    b = io.BytesIO()
    Image.fromarray(a).save(b, "PNG")
    return b.getvalue()


@pytest.fixture(scope="module")
def astro():
    import skimage.data as d
    return _png(d.astronaut())


def test_cascades_bundled():
    for n in ("haarcascade_frontalface_alt2.xml", "haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
        assert (G.CASCADES / n).is_file()
        assert not cv2.CascadeClassifier(str(G.CASCADES / n)).empty()


def test_finds_the_face(astro):
    faces = G.detect_faces(G.open_photo(astro))
    assert len(faces) == 1
    x, y, w = faces[0]
    assert 150 < x + w / 2 < 280 and 60 < y + w / 2 < 200      # the astronaut's face


def test_fit_and_preview(astro):
    P = dict(art_source="upload", art_style="group", length=200.0)
    fit = api.fit_portrait(P, astro)
    assert fit["n_around"] == 1 and fit["faces"] == 1 and 16 <= fit["diameter"] <= 100
    P.update({k: fit[k] for k in ("diameter", "n_around", "n_along", "depth", "draft_deg")})
    t = time.time()
    r = api.preview(P, astro, "astro.png")
    assert time.time() - t < 30
    assert r["art_report"]["sketch"]["mode"] == "group"
    assert r["can_export"]
    blocks = [x["id"] for x in r["rules"] if x["action"] == "BLOCK" and not x["ok"]]
    assert blocks == []


def test_clay_safe_at_export_pitch(astro):
    P = dict(art_source="upload", art_style="group", length=200.0, pitch_preview=0.2)
    fit = api.fit_portrait(P, astro)
    P.update({k: fit[k] for k in ("diameter", "n_around", "n_along", "depth", "draft_deg")})
    r = api.preview(P, astro, "astro.png")
    bad = [x["id"] for x in r["rules"] if not x["ok"] and x["action"] in ("WARN", "BLOCK")
           and x["id"] in ("R19a", "R19b", "R20", "R21", "R26")]
    assert bad == []


def test_no_faces_is_a_clear_error():
    flat = np.full((300, 400, 3), 200, np.uint8)
    flat[100:200, 150:250] = 40
    with pytest.raises(Exception) as e:
        api.fit_portrait(dict(art_source="upload", art_style="group"), _png(flat))
    assert "no faces" in str(e.value)


def test_deterministic(astro):
    G._CACHE.clear()
    a, _ = G.make_group(astro, 150.0, ppm=5.0)
    G._CACHE.clear()
    b, _ = G.make_group(astro, 150.0, ppm=5.0)
    assert np.array_equal(a, b)
