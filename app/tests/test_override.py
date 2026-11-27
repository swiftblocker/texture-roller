"""R86 Export anyway: every tab, every stop item we can trigger.

Without the flag nothing changes (blocked, no file). With the flag a file comes back, its name carries -override,
the sheet or sidecar lists the stop items word for word, and the mesh loads in trimesh (watertight is reported,
it does not have to be). A picture that cannot be read stays a plain message even with the flag.
"""
import io
import json
import math
import zipfile

import numpy as np
import pytest
from PIL import Image, ImageDraw

from engine import api, cookie as K, stamp as ST, export as EX, override as OV
import engine.mesh as meshmod

FAST = {"pitch_preview": 0.5, "pitch_export": 0.5}
REPORT = []          # (tab, case, stop ids, watertight) printed at the end of the module


def _png(im):
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def _load_stl(data):
    import trimesh
    m = trimesh.load(io.BytesIO(data), file_type="stl")
    assert len(m.faces) > 0
    return m


def _zip_stl(zbytes, startswith=""):
    z = zipfile.ZipFile(io.BytesIO(zbytes))
    names = [n for n in z.namelist() if n.endswith(".stl") and n.startswith(startswith)]
    assert names, z.namelist()
    return z, names


def _no_python_text(msg):
    for bad in ("Traceback", "Error:", "Exception", "File \"", "numpy", "ndarray"):
        assert bad not in msg, msg


# ====================================================================== ROLLER
ROLLER_CASES = [
    ("R01", {"length": 300.0}),
    ("R03", {"n_along": 12}),
    ("R04a", {"diameter": 12.0, "bore_preset": "none", "n_around": 1}),
    ("R08", {"tile_width_mm": 40.0}),
    ("R09a", {"diameter": 24.0, "bore_preset": "dowel_3q"}),
    ("R15b", {"depth": 5.5}),
    ("R19b", {"art_source": "pattern:waves", "n_around": 12, "diameter": 30.0, "art_scale": 20}),
    ("R29", {"n_around": 2.5}),
    ("R31b", {"tile_width_mm": 30.0}),
    ("R32", {"n_around": 1, "offset": "half_drop"}),
    ("R60", {"length": 252.0}),
    ("R62", {"cnc_rotary_max_length": 100.0}),
]


@pytest.mark.parametrize("rid,over", ROLLER_CASES, ids=[c[0] for c in ROLLER_CASES])
def test_roller_every_block_can_be_overridden(rid, over):
    base = {**FAST, **over}
    pv = api.preview(base)
    assert not pv["can_export"]
    assert any(r["id"] == rid and r["action"] == "BLOCK" and not r["ok"] for r in pv["rules"]), rid
    # without the flag: blocked, no file, exactly as before
    r0 = api.export_bytes(base)
    assert r0["blocked"] and "override" not in r0
    assert not any(n.endswith((".stl", ".3mf")) for n in r0["files"])          # today a blocked roller zip holds only the sheet and the json
    # with the flag: files, marked
    r = api.export_bytes({**base, "export_anyway": True})
    assert not r["blocked"] and r["zip"]
    assert rid in r["override"]["ids"], r["override"]["ids"]
    z = zipfile.ZipFile(io.BytesIO(r["zip"]))
    names = z.namelist()
    stls = [n for n in names if n.endswith(".stl")]
    assert stls and all(n.endswith("-override.stl") for n in stls), names
    assert any(n.endswith("-override.3mf") for n in names), names
    sheet = z.read("sheet.md").decode("utf-8")
    assert "Exported anyway over these stop items" in sheet
    for text in r["override"]["stops"]:
        assert text in sheet
    side = json.loads(z.read("roller.json"))
    assert side["exported_anyway"]["ids"] == r["override"]["ids"]
    m = _load_stl(z.read(stls[0]))
    REPORT.append(("roller", rid, r["override"]["ids"], bool(m.is_watertight)))


def test_roller_r20_is_a_warning_not_a_stop():
    """The brief lists R20 among the roller stops; in this app R20 is a WARN, so there is nothing to override."""
    over = {**FAST, "art_source": "pattern:chevron", "art_scale": 20, "depth": 3.0, "draft_deg": 30.0, "invert": True}
    pv = api.preview(over)
    r20 = [r for r in pv["rules"] if r["id"] == "R20"]
    assert r20 and r20[0]["action"] == "WARN" and not r20[0]["ok"]
    assert pv["can_export"]
    r = api.export_bytes({**over, "export_anyway": True})
    assert not r["blocked"] and "override" not in r          # nothing was overridden, so the file is not marked
    assert all("-override" not in n for n in r["files"])


def test_roller_flag_with_no_stops_changes_nothing():
    a = api.export_bytes({**FAST})
    b = api.export_bytes({**FAST, "export_anyway": True})
    assert a["files"] == b["files"] and "override" not in b


def test_roller_preview_is_identical_with_and_without_the_flag():
    for over in ({}, {"length": 300.0}, {"n_around": 2.5}):
        a = api.preview({**FAST, **over})
        b = api.preview({**FAST, **over, "export_anyway": True})
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _bad_part_builder(real, drop=6):
    def build(P, R, lay):
        parts = real(P, R, lay)
        out = []
        for name, m, exp in parts:
            m2 = m.copy()
            m2.update_faces(np.arange(len(m2.faces)) % (len(m2.faces) // drop) != 5)   # a few faces gone: holes
            m2.metadata.update(m.metadata)
            out.append((name, m2, exp))
        return out
    return build


def test_roller_broken_mesh_is_repaired_and_exported(monkeypatch):
    base = {**FAST, "length": 60.0, "diameter": 30.0}
    monkeypatch.setattr(meshmod, "build_parts", _bad_part_builder(meshmod.build_parts, drop=500))
    r0 = api.export_bytes(base)
    assert r0["blocked"] and any(x["id"] == "R65" for x in r0["rules"])
    r = api.export_bytes({**base, "export_anyway": True})
    assert not r["blocked"]
    z, stls = _zip_stl(r["zip"])
    sheet = z.read("sheet.md").decode()
    assert "Mesh repair" in sheet
    m = _load_stl(z.read(stls[0]))
    REPORT.append(("roller", "mesh holes, repaired", r.get("override", {}).get("ids"), bool(m.is_watertight)))
    assert m.is_watertight                                  # the holes were small: the repair closed them


def test_roller_broken_mesh_exports_even_when_repair_does_not_help(monkeypatch):
    base = {**FAST, "length": 60.0, "diameter": 30.0}
    monkeypatch.setattr(meshmod, "build_parts", _bad_part_builder(meshmod.build_parts, drop=500))
    monkeypatch.setattr(OV, "repair_mesh", lambda V, F, **k: (V, F, {"tried": True, "kept": "original", "steps": [], "watertight_before": False}))
    r = api.export_bytes({**base, "export_anyway": True})
    assert not r["blocked"] and "R65" in r["override"]["ids"]
    z, stls = _zip_stl(r["zip"])
    assert all(n.endswith("-override.stl") for n in stls)
    m = _load_stl(z.read(stls[0]))
    REPORT.append(("roller", "mesh holes, repair no help", r["override"]["ids"], bool(m.is_watertight)))
    assert not m.is_watertight                              # honest: it is exported broken and says so
    assert "R65" in z.read("sheet.md").decode()


def test_roller_engine_crash_retries_coarser_then_plain_message(monkeypatch):
    base = {**FAST, "length": 60.0, "diameter": 30.0, "export_anyway": True}
    real = meshmod.build_parts
    calls = []

    def flaky(P, R, lay):
        calls.append(P.pitch_export)
        if len(calls) == 1:
            raise RuntimeError("boom in numpy")
        return real(P, R, lay)
    monkeypatch.setattr(meshmod, "build_parts", flaky)
    r = api.export_bytes(base)
    assert not r["blocked"] and r["zip"]
    assert calls == [0.5, 1.0]
    assert "coarser grid" in zipfile.ZipFile(io.BytesIO(r["zip"])).read("sheet.md").decode()

    def always(P, R, lay):
        raise RuntimeError("boom in numpy")
    monkeypatch.setattr(meshmod, "build_parts", always)
    r = api.export_bytes(base)
    assert r["blocked"] and r["zip"] == b"" and r["message"]
    _no_python_text(r["message"])
    assert "R86" in r["message"]
    with pytest.raises(RuntimeError):                        # no flag: the engine error is not swallowed (as today)
        api.export_bytes({**base, "export_anyway": False})


def test_roller_not_a_picture_and_blank_picture_stay_messages():
    up = {**FAST, "art_source": "upload", "export_anyway": True}
    r = api.export_bytes(up, b"this is not a picture", "x.png")
    assert r["blocked"] and r["zip"] == b"" and r["message"]
    _no_python_text(r["message"])
    blank = _png(Image.new("L", (200, 200), 255))
    r = api.export_bytes(up, blank, "blank.png")
    assert r["blocked"] and r["zip"] == b"" and "flat colour" in r["message"]
    _no_python_text(r["message"])
    r = api.export_bytes(up, None, None)
    assert r["blocked"] and r["zip"] == b"" and r["message"]


def test_roller_flag_is_not_in_the_echoed_params():
    pv = api.preview({**FAST, "export_anyway": True})
    assert "export_anyway" not in pv["params"]


# ====================================================================== COOKIE
def _dumbbell():
    im = Image.new("L", (700, 400), 255)
    d = ImageDraw.Draw(im)
    d.ellipse((20, 100, 220, 300), fill=0)
    d.ellipse((480, 100, 680, 300), fill=0)
    d.rectangle((215, 192, 485, 208), fill=0)                  # a thin neck
    return _png(im)


def _heart():
    n = 600
    im = Image.new("L", (n, n), 255)
    d = ImageDraw.Draw(im)
    pts = []
    for t in np.linspace(0, 2 * math.pi, 200):
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((n / 2 + x * 16, n / 2 - y * 16 - 10))
    d.polygon(pts, outline=0, width=8)
    d.arc((200, 260, 400, 420), 20, 160, fill=0, width=12)
    d.ellipse((260, 190, 300, 240), fill=0)
    return _png(im)


@pytest.fixture
def fresh_cookie_caches():
    K._BUILT.clear(); K._PREP.clear()
    yield
    K._BUILT.clear(); K._PREP.clear()


def _cookie_stop_ids(r):
    return [c.get("id") for c in r["checks"] if c["level"] == "block"]


def test_cookie_neck_block_can_be_overridden(fresh_cookie_caches):
    up = _dumbbell()
    r0 = api.cookie_export({"size_mm": 80}, up, "d.png")
    assert r0["blocked"] and r0["stl"] == b"" and "override" not in r0 and r0["filename"].endswith("80x24.stl")
    r = api.cookie_export({"size_mm": 80, "export_anyway": True}, up, "d.png")
    assert not r["blocked"] and len(r["stl"]) > 1000
    assert r["filename"].endswith("-override.stl")
    assert "thin neck" in r["override"]["ids"]
    side = r["sidecar"]["exported_anyway"]
    assert side["stop_items"] == r["override"]["stops"] and "neck thinner than 6 mm" in side["stop_items"][0]
    m = _load_stl(r["stl"])
    REPORT.append(("cookie", "thin neck", r["override"]["ids"], bool(m.is_watertight)))


def test_cookie_floating_piece_can_be_overridden(fresh_cookie_caches, monkeypatch):
    real = K.mesh_checks

    def two_bodies(*a, **k):
        ck = real(*a, **k)
        ck["bodies"] = 2
        return ck
    monkeypatch.setattr(K, "mesh_checks", two_bodies)
    up = _heart()
    r0 = api.cookie_export({"size_mm": 61}, up, "h.png")
    assert r0["blocked"] and r0["stl"] == b"" and "attached pieces" in _cookie_stop_ids(r0)
    r = api.cookie_export({"size_mm": 61, "export_anyway": True}, up, "h.png")
    assert not r["blocked"] and r["filename"].endswith("-override.stl")
    assert "attached pieces" in r["override"]["ids"]
    m = _load_stl(r["stl"])
    REPORT.append(("cookie", "floating piece", r["override"]["ids"], bool(m.is_watertight)))


def _holey(real_build_mesh):
    def build(*a, **k):
        m, mi = real_build_mesh(*a, **k)
        keep = np.ones(len(m.faces), bool)
        keep[[10, 11, 400]] = False
        m = m.copy()
        m.update_faces(keep)
        return m, mi
    return build


def test_cookie_broken_mesh_repaired_or_exported_as_is(fresh_cookie_caches, monkeypatch):
    monkeypatch.setattr(K, "build_mesh", _holey(K.build_mesh))
    up = _heart()
    r0 = api.cookie_export({"size_mm": 62}, up, "h.png")
    assert r0["blocked"] and "closed solid" in _cookie_stop_ids(r0)
    r = api.cookie_export({"size_mm": 62, "export_anyway": True}, up, "h.png")
    assert not r["blocked"] and r["filename"].endswith("-override.stl")
    assert "closed solid" in r["override"]["ids"]
    assert any("Mesh repair" in n for n in r["override"]["notes"])
    m = _load_stl(r["stl"])
    REPORT.append(("cookie", "mesh holes, repaired", r["override"]["ids"], bool(m.is_watertight)))
    assert m.is_watertight and r["watertight"]
    # repair does not help: still exported, said so
    K._BUILT.clear()
    monkeypatch.setattr(OV, "repair_mesh", lambda V, F, **k: (V, F, {"tried": True, "kept": "original", "steps": [], "watertight_before": False}))
    r = api.cookie_export({"size_mm": 62, "export_anyway": True}, up, "h.png")
    assert not r["blocked"] and len(r["stl"]) > 1000 and not r["watertight"]
    m = _load_stl(r["stl"])
    REPORT.append(("cookie", "mesh holes, repair no help", r["override"]["ids"], bool(m.is_watertight)))


def test_cookie_no_outline_and_not_a_picture_stay_messages(fresh_cookie_caches):
    for data in (b"this is not a picture", _png(Image.new("L", (300, 300), 255)), None):
        with pytest.raises(K.CookieError) as e:
            api.cookie_export({"size_mm": 70, "export_anyway": True}, data, "x.png")
        _no_python_text(str(e.value))
        assert "R86" in str(e.value)


def test_cookie_engine_crash_retries_coarser_then_plain_message(fresh_cookie_caches, monkeypatch):
    real = K.build
    seen = []

    def flaky(upload, name, cp):
        seen.append(cp.pitch_scale)
        if cp.pitch_scale == 1.0:
            raise RuntimeError("boom in numpy")
        return real(upload, name, cp)
    monkeypatch.setattr(K, "build", flaky)
    up = _heart()
    r = api.cookie_export({"size_mm": 64, "export_anyway": True}, up, "h.png")
    assert seen == [1.0, 1.5]
    assert not r["blocked"] and len(r["stl"]) > 1000
    assert any("coarser grid" in n for n in r["sidecar"]["notes"])
    monkeypatch.setattr(K, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom in numpy")))
    with pytest.raises(K.CookieError) as e:
        api.cookie_export({"size_mm": 64, "export_anyway": True}, up, "h.png")
    _no_python_text(str(e.value))
    with pytest.raises(K.CookieError) as e:                    # no flag: the plain sentence, as today
        api.cookie_export({"size_mm": 64}, up, "h.png")
    assert str(e.value) == K.FRIENDLY


def test_cookie_preview_identical_with_and_without_the_flag(fresh_cookie_caches):
    for up in (_heart(), _dumbbell()):
        a = api.cookie_preview({"size_mm": 66}, up, "x.png")
        b = api.cookie_preview({"size_mm": 66, "export_anyway": True}, up, "x.png")
        for d in (a, b):
            d.pop("timings", None)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_cookie_flag_with_no_stops_changes_nothing(fresh_cookie_caches):
    up = _heart()
    a = api.cookie_export({"size_mm": 65}, up, "h.png")
    b = api.cookie_export({"size_mm": 65, "export_anyway": True}, up, "h.png")
    assert a["filename"] == b["filename"] and not b["blocked"] and "override" not in b and a["stl"] == b["stl"]


# ====================================================================== STAMP
def sp_(**kw):
    d = dict(shape="rect", width_mm=60, height_mm=60, art_source="pattern:leaf")
    d.update(kw)
    return d


STAMP_CASES = [
    ("R80 20 mm", sp_(width_mm=20), "R80"),
    ("R80 200 mm", sp_(width_mm=200, height_mm=200), "R80"),
    ("R80 20 x 200", sp_(width_mm=20, height_mm=200, shape="round"), "R80"),
    ("R81 thin line", sp_(width_mm=25, height_mm=25, art_source="pattern:waves", n_across=12), "R81"),
    ("R82 blank", sp_(art_source="pattern:plain", rim_on=False), "R82"),
    ("R82 solid", sp_(art_source="pattern:plain", rim_on=False, invert=True), "R82"),
    ("R82 blank, no knob", sp_(art_source="pattern:plain", rim_on=False, knob_on=False, shape="round"), "R82"),
]


@pytest.mark.parametrize("name,params,rid", STAMP_CASES, ids=[c[0] for c in STAMP_CASES])
def test_stamp_every_block_can_be_overridden(name, params, rid):
    r0 = api.stamp_export(params)
    assert r0["blocked"] and r0["zip"] == b"" and r0["files"] == [] and "override" not in r0
    assert any(c["id"] == rid and c["level"] == "block" for c in r0["checks"])
    r = api.stamp_export({**params, "export_anyway": True})
    assert not r["blocked"] and r["zip"]
    assert rid in r["override"]["ids"], r["override"]["ids"]
    assert r["filename"].endswith("-override.zip")
    z, stls = _zip_stl(r["zip"])
    assert all(n.endswith("-override.stl") for n in stls) and any(n.endswith("-override.3mf") for n in z.namelist())
    sheet = z.read("sheet.md").decode()
    assert "Exported anyway over these stop items" in sheet
    for text in r["override"]["stops"]:
        assert text in sheet
    m = _load_stl(z.read([n for n in stls if n.startswith("stamp")][0]))
    REPORT.append(("stamp", name, r["override"]["ids"], bool(m.is_watertight)))


def test_stamp_r80_is_clamped_to_the_nearest_limit_and_says_so():
    r = api.stamp_export(sp_(width_mm=20, height_mm=200, export_anyway=True))
    assert r["filename"] == "stamp-rect-25x150-override.zip"
    z, stls = _zip_stl(r["zip"])
    sheet = z.read("sheet.md").decode()
    assert "outside the 25 to 150 mm limit" in sheet and "25 x 150 mm" in sheet
    m = _load_stl(z.read("stamp-override.stl"))
    ext = m.bounds[1] - m.bounds[0]
    assert abs(ext[0] - 25) < 0.5 and abs(ext[1] - 150) < 0.5


def test_stamp_broken_mesh_repaired_or_exported_as_is(monkeypatch):
    real = ST.check_mesh
    calls = {"n": 0}

    def holey(V, F):
        calls["n"] += 1
        if calls["n"] == 1:                                    # the first look at the stamp mesh fails
            return dict(real(V, F), ok=False, open_edges=3, watertight=False)
        return real(V, F)
    monkeypatch.setattr(ST, "check_mesh", holey)
    p = sp_(knob_on=False)
    r = api.stamp_export({**p, "export_anyway": True})
    assert not r["blocked"] and r["zip"]
    z, stls = _zip_stl(r["zip"])
    assert "Mesh repair" in z.read("sheet.md").decode()
    # a real hole the repair cannot fix: still exported, R85 listed, marked
    monkeypatch.setattr(ST, "check_mesh", lambda V, F: dict(real(V, F), ok=False, open_edges=3, watertight=False))
    monkeypatch.setattr(OV, "repair_mesh", lambda V, F, **k: (V, F, {"tried": True, "kept": "original", "steps": [], "watertight_before": False}))
    r0 = api.stamp_export(p)
    assert r0["blocked"] and r0["zip"] == b"" and any(c["id"] == "R85" and c["level"] == "block" for c in r0["checks"])
    r = api.stamp_export({**p, "export_anyway": True})
    assert not r["blocked"] and "R85" in r["override"]["ids"] and r["filename"].endswith("-override.zip")
    z, stls = _zip_stl(r["zip"])
    m = _load_stl(z.read("stamp-override.stl"))
    REPORT.append(("stamp", "mesh holes (check forced)", r["override"]["ids"], bool(m.is_watertight)))


def test_stamp_engine_crash_retries_coarser_then_plain_message(monkeypatch):
    real = ST.mesh_pitch
    seen = []

    def flaky(sp):
        seen.append(sp.pitch_scale)
        if sp.pitch_scale == 1.0:
            raise RuntimeError("boom in numpy")
        return real(sp)
    monkeypatch.setattr(ST, "mesh_pitch", flaky)
    p = sp_(width_mm=40, height_mm=40, art_source="pattern:waves")
    r = api.stamp_export({**p, "export_anyway": True, "rim_on": True})
    assert seen[:2] == [1.0, 1.5]
    assert not r["blocked"] and r["zip"]
    monkeypatch.setattr(ST, "mesh_pitch", lambda sp: (_ for _ in ()).throw(RuntimeError("boom in numpy")))
    r = api.stamp_export({**p, "export_anyway": True, "width_mm": 20})
    assert r["blocked"] and r["zip"] == b"" and "R86" in r["checks"][0]["text"]
    _no_python_text(r["checks"][0]["text"])
    r = api.stamp_export(p)                                  # no flag: the plain sentence, as today
    assert r["blocked"] and r["checks"][0]["text"] == ST.FRIENDLY


def test_stamp_not_a_picture_and_blank_picture_stay_messages():
    p = sp_(art_source="upload", export_anyway=True)
    for data in (b"this is not a picture at all", _png(Image.new("L", (200, 200), 255)), None):
        r = api.stamp_export(p, data, "x.png")
        assert r["blocked"] and r["zip"] == b"" and r["files"] == []
        t = r["checks"][0]["text"]
        _no_python_text(t)
        assert t.startswith("R80")


def test_stamp_preview_identical_with_and_without_the_flag():
    for p in (sp_(), sp_(width_mm=20), sp_(art_source="pattern:plain", rim_on=False)):
        a = api.stamp_preview(p)
        b = api.stamp_preview({**p, "export_anyway": True})
        for d in (a, b):
            d.pop("timings", None)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_stamp_flag_with_no_stops_changes_nothing():
    a = api.stamp_export(sp_())
    b = api.stamp_export({**sp_(), "export_anyway": True})
    assert a["files"] == b["files"] and a["filename"] == b["filename"] and "override" not in b


# ====================================================================== helpers
def test_mark_name():
    assert OV.mark_name("a.zip") == "a-override.zip"
    assert OV.mark_name("a-override.zip") == "a-override.zip"
    assert OV.mark_name("roller_a.stl") == "roller_a-override.stl"


def test_zz_report():
    print()
    for row in REPORT:
        print("OVERRIDE %-7s %-30s stops=%s watertight=%s" % (row[0], row[1], ",".join(str(x) for x in (row[2] or [])), row[3]))
