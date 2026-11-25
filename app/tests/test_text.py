"""Lettering (engine/text.py): fonts, placement, clay checks R74-R79, seam handling."""
import re
import time
from pathlib import Path

import numpy as np
import pytest

from engine import api, relief, text as T

WEB = Path(__file__).resolve().parents[1] / "web"

# the seven ideas in app.js TEXT_IDEAS, with their sample words
PRESETS = {
    "name": dict(text="Grandma Rose", text_count=1, text_y=88, text_font="pacifico", text_size=14),
    "arch": dict(text="Sunny Days", text_count=1, text_y=84, text_arch=70, text_font="shrikhand", text_size=14),
    "band": dict(text="HOPE", text_layout="band", text_y=50, text_font="bebas", text_sep="star", text_size=12),
    "wavy": dict(text="be still", text_layout="band", text_y=50, text_x=0, text_wave=25, text_font="caveat",
                 text_sep="none", text_gap=14, text_size=12),
    "allover": dict(text="JOY", text_layout="allover", text_font="lilita", text_sep="heart", text_gap=4, text_size=14),
    "stamp": dict(text="HANDMADE", text_y=8, text_font="nunito", text_frame="ring", text_size=12),
    "side": dict(text="made with love", text_y=50, text_x=0, text_angle=90, text_font="lilita", text_size=10),
}
CLAY = ("R19a", "R19b", "R20", "R21", "R26", "R74", "R76", "R77", "R79")


def _fails(r, ids=CLAY):
    return [x["id"] for x in r["rules"] if not x["ok"] and x["action"] in ("WARN", "BLOCK") and x["id"] in ids]


def _clay(r):
    import base64
    c = r["clay"]
    return np.frombuffer(base64.b64decode(c["data_b64"]), np.uint8).reshape(c["rows"], c["cols"])


def test_fonts_installed_with_licence_and_match_app():
    for f in T.FONTS:
        assert (T.FONT_DIR / (f["id"] + ".ttf")).is_file()
        assert "Open Font License" in (T.FONT_DIR / (f["id"] + "-OFL.txt")).read_text(encoding="utf-8", errors="replace")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    block = js[js.index("const FONTS = ["):js.index("];", js.index("const FONTS = ["))]
    rows = re.findall(r'\["(\w+)", "[^"]+", "[^"]+", (\d+)\]', block)
    assert {k: int(v) for k, v in rows} == {f["id"]: f["min_mm"] for f in T.FONTS}


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_presets_are_clay_clean_at_export_pitch(name):
    r = api.preview(dict(PRESETS[name], pitch_preview=0.2))
    assert r["art_report"]["text"]["kept"] > 0.9
    assert _fails(r) == []


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_presets_preview_clean_and_quick(name):
    t = time.time()
    r = api.preview(PRESETS[name])
    assert time.time() - t < 3.0
    assert _fails(r) == []


def test_no_text_changes_nothing():
    a = api.preview({})
    for t in ("", "   ", None, "\n\n"):
        b = api.preview({"text": t})
        assert b["clay"]["data_b64"] == a["clay"]["data_b64"]
        assert "text" not in b["art_report"]


def test_reads_left_to_right_in_clay_with_mirror_on_and_off():
    # a big L: its foot runs to the right, so the bottom of the word has more ink right of the stem
    for mirror in (True, False):
        r = api.preview(dict(art_source="pattern:plain", text="L", text_font="lilita", text_size=40,
                             text_y=50, text_x=50, mirror=mirror))
        K = _clay(r) > 128
        rows, cols = np.where(K[30:-30])          # skip the end bands
        foot = cols[rows > rows.min() + 0.8 * (rows.max() - rows.min())]
        stem_x = np.median(cols[rows < rows.min() + 0.3 * (rows.max() - rows.min())])
        assert np.mean(foot > stem_x) > 0.7, "L reads backwards with mirror=%s" % mirror


def test_tiny_script_warns_instead_of_vanishing_silently():
    r = api.preview(dict(text="forever", text_font="dancing", text_size=8, text_y=50))
    f = _fails(r)
    assert "R74" in f and "R79" in f


def test_too_many_lines_and_too_big_are_reported_fast():
    r = api.preview(dict(text="A\nB\nC\nD"))
    assert any(x["id"] == "R78" for x in r["rules"])
    t = time.time()
    r = api.preview(dict(text="W" * 60, text_layout="band", text_size=120, diameter=150))
    assert time.time() - t < 3.0
    assert r["art_report"]["text"]["too_big"]
    assert "R76" in _fails(r)


def test_overlapping_copies_say_what_size_fits():
    r = api.preview(dict(text="Grandma Rose", text_count=3, text_size=14))
    m = [x["msg"] for x in r["rules"] if x["id"] == "R76"]
    assert m and "mm tall or less" in m[0]


def test_raised_letters_with_no_frame_on_plain_clay_are_flagged_invisible():
    r = api.preview(dict(art_source="pattern:plain", text="HI", text_font="lilita", text_size=20,
                         text_relief="raised", text_frame="none", text_y=50))
    assert "R77" in _fails(r)


def test_band_closes_evenly_at_the_seam():
    r = api.preview(dict(art_source="pattern:plain", text="HOPE", text_layout="band", text_font="bebas",
                         text_size=12, text_y=50))
    tr = r["art_report"]["text"]
    C = r["derived"]["C"]
    assert abs(tr["repeats"] * tr["pitch_mm"] - C) < 0.05


def test_text_never_covers_the_end_bands():
    r = api.preview(dict(art_source="pattern:plain", text="JOY", text_layout="allover", text_font="lilita",
                         text_size=14, band=4.0))
    K = _clay(r)
    rows_band = int(round(4.0 / r["heightmap"]["pitch_z_mm"])) - 1
    band_v = K[0, 0]
    assert (K[:rows_band] == band_v).all() and (K[-rows_band:] == band_v).all()


def test_label_joins_pieces_across_the_seam():
    m = np.zeros((5, 10), bool)
    m[2, 0] = m[2, 9] = True
    m[0, 4] = True
    lab, n = relief._label_wrapped(m)
    assert n == 2 and lab[2, 0] == lab[2, 9] != lab[0, 4]
