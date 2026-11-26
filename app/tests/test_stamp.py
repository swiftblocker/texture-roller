"""Stamp tab (engine/stamp.py). Synthetic art only, plus skimage's public astronaut photo for the sketch style."""
import io
import math
import time
import zipfile
from functools import lru_cache

import numpy as np
import pytest
from PIL import Image, ImageDraw

from engine import api, stamp as ST


# ---------------------------------------------------------------- the GEOS guard
@pytest.fixture(scope="module", autouse=True)
def no_risky_geos():
    """In the browser (Pyodide: shapely 2.0.6 on GEOS 3.12) a GEOS topology error aborts the whole runtime, so the
    stamp path must never buffer an area and never overlay areas without a grid. This makes either raise; the stamp
    engine must also not import shapely at all."""
    import ast
    import inspect
    src = inspect.getsource(ST)
    for node in ast.walk(ast.parse(src)):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        assert not any(n.split(".")[0] == "shapely" for n in names), "engine/stamp.py must not import shapely"
    try:
        import shapely
        from shapely.geometry.base import BaseGeometry
    except ImportError:
        yield
        return
    mp = pytest.MonkeyPatch()

    def boom(*a, **k):
        raise AssertionError("shapely buffer / area overlay called in the stamp path")
    mp.setattr(shapely, "buffer", boom)
    mp.setattr(BaseGeometry, "buffer", boom)
    for name in ("difference", "intersection", "union", "symmetric_difference"):
        mp.setattr(shapely, name, boom)
        mp.setattr(BaseGeometry, name, boom)
    for name in ("union_all", "unary_union"):
        mp.setattr(shapely, name, boom)
    yield
    mp.undo()


# ---------------------------------------------------------------- helpers
def read_stl(b):
    n = int(np.frombuffer(b[80:84], "<u4")[0])
    rec = np.frombuffer(b[84:84 + 50 * n], np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    return rec["v"].reshape(-1, 3).astype(np.float64), n


def stl_mesh(b):
    import trimesh
    return trimesh.load(io.BytesIO(b), file_type="stl")


def unzip(r):
    return zipfile.ZipFile(io.BytesIO(r["zip"]))


def p(**kw):
    d = dict(shape="rect", width_mm=60, height_mm=60, art_source="pattern:leaf")
    d.update(kw)
    return d


@lru_cache(maxsize=None)
def exported(shape, w, h, depth=1.5, art="pattern:leaf", knob=True):
    r = ST.export_bytes(p(shape=shape, width_mm=w, height_mm=h, depth=depth, art_source=art, knob_on=knob))
    return r


def png_bytes(im):
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def blob_png():
    im = Image.new("L", (500, 400), 255)
    d = ImageDraw.Draw(im)
    d.ellipse((60, 50, 440, 350), outline=0, width=34)
    d.rectangle((200, 150, 300, 250), fill=0)
    return png_bytes(im)


def blob_svg():
    return (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 80"><circle cx="50" cy="40" r="30" fill="#000"/>'
            b'<circle cx="50" cy="40" r="14" fill="#fff"/><rect x="46" y="4" width="8" height="14" fill="#000"/></svg>')


def astronaut_png():
    from skimage import data
    return png_bytes(Image.fromarray(data.astronaut()))


# ---------------------------------------------------------------- the mirror
def hope_params():
    return ST.StampParams.from_dict(dict(shape="rect", width_mm=80, height_mm=50, art_source="pattern:plain", text="hope",
                                         text_size=22, text_x=50, text_y=50, text_frame="none"))


def _iou(a, b):
    return (a & b).sum() / max(1, (a | b).sum())


def test_mirror_hope_reads_right_in_the_clay_and_backwards_on_the_face():
    sp = hope_params()
    f = ST.build_face(sp, None, None, 0.25)
    F, K, S0, d = f["F"], f["K"], f["S0"], sp.depth
    os_ = F.lay.os
    idx = (-np.arange(F.lay.top_os.shape[1])) % F.lay.top_os.shape[1]
    # the text mask as drawn (clay view), in picture order (row 0 = top), on the vertex grid
    drawn = F.lay.text_os[:, idx][::-1][::os_, ::os_]
    assert drawn.shape == K.shape and drawn.sum() > 200
    clay_high, face_high = K > 0.5 * d, S0 > 0.5 * d
    assert _iou(clay_high, drawn) > 0.8                      # the clay shows the word the way it was drawn
    assert _iou(face_high[:, 1:], drawn[:, ::-1]) > 0.8      # the stamp face is that picture flipped left to right
    assert _iou(face_high[:, 1:], drawn) < _iou(face_high[:, 1:], drawn[:, ::-1]) - 0.3   # "hope" is not a mirror word: unflipped fits far worse
    # the face really is the clay picture reversed, column for column
    assert np.allclose(S0[:, 1:], K[:, ::-1]) and np.allclose(S0[:, 0], K[:, -1])


def test_mirror_survives_the_mesh_press_the_exported_face_into_clay():
    """STL -> top surface heights -> flip left/right = the clay picture the engine promised."""
    sp = ST.StampParams.from_dict(dict(shape="rect", width_mm=40, height_mm=30, art_source="pattern:plain", text="hope",
                                       text_size=14, text_x=50, text_y=50, text_frame="none", rim_on=False))
    pitch = 0.2
    r = ST.analyse(sp, None, None, pitch)
    V, F = ST.rect_mesh(r["Zm"], r["pt"], r["pz"], sp.base)
    M, Nc = r["Zm"].shape
    top = V[:M * Nc, 2].reshape(M, Nc) - sp.base            # the face as printed, row 0 = far edge
    pressed = top[:, ::-1]                                  # face down in clay: left and right swap
    clay = r["K"]
    k = 6                                                   # the outline chamfer only touches the edge
    assert np.abs(pressed[:, :clay.shape[1]][k:-k, k:-k] - clay[k:-k, k:-k]).max() < 1e-9
    assert (clay[k:-k, k:-k] > 0.5).sum() > 100             # and there is a word to compare


# ---------------------------------------------------------------- meshes
@pytest.mark.parametrize("shape", ["rect", "round"])
@pytest.mark.parametrize("size", [25, 60, 150])
@pytest.mark.parametrize("depth", [0.8, 3.0])
def test_export_watertight_volume_and_box(shape, size, depth):
    r = exported(shape, size, size, depth)
    assert not r["blocked"], [c["text"] for c in r["checks"] if c["level"] == "block"]
    z = unzip(r)
    V, n = read_stl(z.read("stamp.stl"))
    assert n == r["triangles"]
    pitch = ST.mesh_pitch(ST.StampParams.from_dict(p(shape=shape, width_mm=size, height_mm=size)))
    lo, hi = V.min(0), V.max(0)
    assert abs((hi[0] - lo[0]) - size) <= pitch and abs((hi[1] - lo[1]) - size) <= pitch
    assert abs(lo[2]) < 1e-3 and abs(hi[2] - (6.0 + depth)) <= pitch
    # own proof (the same one the export enforces) and trimesh's, on the part the slicer will read
    if size <= 60:
        m = stl_mesh(z.read("stamp.stl"))
        assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    assert any(c["id"] == "R85" and c["level"] == "pass" for c in r["checks"])


def test_oval_outline_is_a_true_ellipse():
    r = ST.export_bytes(p(shape="round", width_mm=80, height_mm=40))
    assert not r["blocked"]
    V, _ = read_stl(unzip(r).read("stamp.stl"))
    ring = np.unique(V[np.abs(V[:, 2]) < 1e-9][:, :2], axis=0)     # bottom ring + centre vertex
    ring = ring[np.hypot(ring[:, 0] - 40, (ring[:, 1] - 20) * 2) > 1.0]
    assert len(ring) > 400
    th = np.linspace(0, 2 * np.pi, 20001)
    ell = np.c_[40 + 40 * np.cos(th), 20 + 20 * np.sin(th)]
    dmin = np.array([np.min(np.hypot(ell[:, 0] - x, ell[:, 1] - y)) for x, y in ring[::7]])
    assert dmin.max() < 0.1
    # and it fills the whole box: both axes are touched
    assert abs(V[:, 0].max() - V[:, 0].min() - 80) < 0.01 and abs(V[:, 1].max() - V[:, 1].min() - 40) < 0.01


def test_ellipse_distance_function_against_brute_force():
    rng = np.random.default_rng(3)
    for a, b in ((40.0, 20.0), (20.0, 40.0), (75.0, 12.5)):
        pts = np.c_[rng.uniform(-a - 5, a + 5, 300), rng.uniform(-b - 5, b + 5, 300)]
        th = np.linspace(0, 2 * np.pi, 40001)
        ell = np.c_[a * np.cos(th), b * np.sin(th)]
        bf = np.array([np.min(np.hypot(ell[:, 0] - x, ell[:, 1] - y)) for x, y in pts])
        sd = ST.ellipse_sd(pts[:, 0], pts[:, 1], a, b)
        assert np.abs(np.abs(sd) - bf).max() < 0.01
        assert np.array_equal(sd > 0, (pts[:, 0] / a) ** 2 + (pts[:, 1] / b) ** 2 < 1)


def test_knob_is_watertight_and_the_right_size():
    r = exported("rect", 60, 60)
    z = unzip(r)
    m = stl_mesh(z.read("knob.stl"))
    assert m.is_watertight and m.is_winding_consistent and m.volume > 0
    lo, hi = m.bounds
    assert abs(lo[2]) < 1e-3 and abs(hi[2] - 30.0) < 1e-3          # 30 mm tall, pad on z = 0
    assert abs((hi[0] - lo[0]) - 40.0) < 0.1                        # glue pad = min(40, 0.7 x 60) = 40 mm, the widest part
    # the cap is 28 mm across at the equator
    zs = m.vertices[:, 2]
    cap = m.vertices[np.abs(zs - zs[np.argmax(np.hypot(m.vertices[:, 0], m.vertices[:, 1]) * (zs > 10))]) < 1e-6]
    assert abs(2 * np.hypot(cap[:, 0], cap[:, 1]).max() - 28.0) < 0.2
    for small, pad, grip in ((25, 17.5, 20.0), (35, 24.5, 28.0), (150, 40.0, 28.0)):
        sp = ST.StampParams.from_dict(p(width_mm=small, height_mm=small))
        got = ST.knob_dims(sp)
        assert abs(got[0] - pad) < 1e-9 and abs(got[1] - grip) < 1e-9 and got[1] >= 18.0
        V, F = ST.knob_mesh(*got)
        assert ST.check_mesh(V, F)["ok"]


def test_threemf_holds_two_objects_ten_mm_apart():
    import trimesh
    r = exported("rect", 60, 60)
    raw = unzip(r).read("stamp.3mf")
    sc = trimesh.load(io.BytesIO(raw), file_type="3mf")
    geoms = list(sc.geometry.values()) if hasattr(sc, "geometry") else [sc]
    assert len(geoms) == 2
    boxes = sorted([g.bounds for g in geoms], key=lambda b: b[0][0])
    gap = boxes[1][0][0] - boxes[0][1][0]
    assert abs(gap - 10.0) < 0.05                                                    # 10 mm apart (the pad is the knob's widest part)
    assert abs(boxes[0][1][0] - 60.0) < 0.05


def test_zip_has_every_file_and_sheet_is_ascii_plain():
    r = exported("round", 60, 60)
    z = unzip(r)
    assert set(z.namelist()) == {"stamp.stl", "knob.stl", "stamp.3mf", "clay_preview.png", "sheet.md"}
    assert r["filename"] == "stamp-round-60x60.zip"
    sheet = z.read("sheet.md").decode("utf-8")
    assert "0.2 mm layers" in sheet and "no supports" in sheet.lower() and "centred" in sheet and "R85" in sheet
    im = Image.open(io.BytesIO(z.read("clay_preview.png")))
    assert im.size[0] > 100 and im.mode == "RGBA"


def test_no_knob_export_has_no_knob_file_and_a_twelve_mm_base():
    r = exported("rect", 60, 60, 1.5, "pattern:leaf", False)
    assert not r["blocked"]
    z = unzip(r)
    assert "knob.stl" not in z.namelist() and set(z.namelist()) == {"stamp.stl", "stamp.3mf", "clay_preview.png", "sheet.md"}
    V, _ = read_stl(z.read("stamp.stl"))
    assert abs(V[:, 2].max() - (12.0 + 1.5)) < 0.01
    import trimesh
    sc = trimesh.load(io.BytesIO(z.read("stamp.3mf")), file_type="3mf")
    geoms = list(sc.geometry.values()) if hasattr(sc, "geometry") else [sc]
    assert len(geoms) == 1


def test_mesh_check_catches_a_hole_a_flipped_face_and_a_collapsed_triangle():
    V, F = ST.rect_mesh(np.full((6, 6), 1.0), 1.0, 1.0, 6.0)
    assert ST.check_mesh(V, F)["ok"]
    assert not ST.check_mesh(V, F[1:])["ok"]                                  # hole
    G = F.copy(); G[7] = G[7][::-1]
    c = ST.check_mesh(V, G)
    assert not c["ok"] and (c["nonmanifold_edges"] or c["open_edges"])        # flipped face
    G = F.copy(); G[3, 2] = G[3, 0]
    assert ST.check_mesh(V, G)["degenerate"] > 0                              # zero area
    assert not ST.check_mesh(V, F[:, ::-1])["ok"]                             # inside out: negative volume


# ---------------------------------------------------------------- art sources
def test_uploaded_png_and_svg_drawings_export():
    for data, name in ((blob_png(), "blob.png"), (blob_svg(), "blob.svg")):
        for shape in ("rect", "round"):
            r = ST.export_bytes(p(shape=shape, width_mm=70, height_mm=50, art_source="upload", art_style="trace"), data, name)
            assert not r["blocked"], (name, [c["text"] for c in r["checks"] if c["level"] == "block"])
            m = stl_mesh(unzip(r).read("stamp.stl"))
            assert m.is_watertight and m.volume > 0


def test_sketch_style_photo_exports_and_pattern_text_exports():
    data = astronaut_png()
    r = ST.export_bytes(p(shape="round", width_mm=90, height_mm=90, art_source="upload", art_style="portrait", depth=1.2, draft_deg=10), data, "astro.png")
    assert not r["blocked"], [c["text"] for c in r["checks"] if c["level"] == "block"]
    r = ST.export_bytes(p(width_mm=70, height_mm=40, art_source="pattern:chevron", text="HOPE", text_font="bebas", text_size=14))
    assert not r["blocked"], [c["text"] for c in r["checks"] if c["level"] == "block"]


def test_every_pass_through_param_validates_at_the_smallest_and_largest_face():
    for size in (25, 150):
        for art in ("pattern:waves", "pattern:chevron", "pattern:leaf", "pattern:plain"):
            for extra in ({}, {"invert": True}, {"text": "Rose", "text_layout": "band", "text_size": 12}, {"n_across": 3}):
                sp = ST.StampParams.from_dict(p(width_mm=size, height_mm=size, art_source=art, **extra))
                f = ST.build_face(sp, None, None, ST.preview_pitch(sp))
                assert np.isfinite(f["S0"]).all() and f["S0"].shape[0] > 10 and f["S0"].shape[1] > 10
    for size in (25, 150):
        sp = ST.StampParams.from_dict(p(width_mm=size, height_mm=size, art_source="upload", art_style="trace"))
        f = ST.build_face(sp, blob_png(), "blob.png", ST.preview_pitch(sp))
        assert np.isfinite(f["S0"]).all()


# ---------------------------------------------------------------- checks and blocks
def test_preview_shape_and_speed():
    t = time.time()
    r = ST.preview(p(shape="round", width_mm=150, height_mm=150))
    assert time.time() - t < 6.0
    assert r["can_export"] and r["face"]["cols"] > 100
    ids = [c["id"] for c in r["checks"]]
    assert {"R80", "R81", "R82", "R84", "R85"} <= set(ids)
    assert r["size"]["tris"] > 100000 and r["params"]["total_height_mm"] == 7.5
    assert len(__import__("base64").b64decode(r["face"]["face_b64"])) == r["face"]["cols"] * r["face"]["rows"]


def test_r80_size_blocks_and_no_files():
    for w, h in ((20, 60), (60, 20), (160, 60), (60, 151)):
        r = ST.export_bytes(p(width_mm=w, height_mm=h))
        assert r["blocked"] and r["zip"] == b"" and r["files"] == [] and any(c["id"] == "R80" and c["level"] == "block" for c in r["checks"])
        pv = ST.preview(p(width_mm=w, height_mm=h))
        assert not pv["can_export"] and pv["face"] is None and pv["checks"][0]["id"] == "R80"
    assert not ST.export_bytes(p(width_mm=25, height_mm=150))["blocked"]


def test_broken_art_returns_no_stl_and_a_plain_sentence():
    r = ST.export_bytes(p(art_source="upload"), b"this is not a picture at all", "junk.png")
    assert r["blocked"] and r["zip"] == b"" and r["checks"][0]["level"] == "block"
    assert "Traceback" not in r["checks"][0]["text"] and "Error" not in r["checks"][0]["text"]
    with pytest.raises(ST.StampError):
        ST.preview(p(art_source="upload"), b"this is not a picture at all", "junk.png")
    r = ST.export_bytes(p(art_source="upload"), None, None)
    assert r["blocked"] and r["zip"] == b""
    r = ST.export_bytes(p(art_style="group"))
    assert r["blocked"] and r["zip"] == b""
    r = ST.export_bytes(p(width_mm="abc"))
    assert r["blocked"] and r["zip"] == b""


def test_r85_failed_mesh_check_blocks_the_download(monkeypatch):
    real = ST.check_mesh
    monkeypatch.setattr(ST, "check_mesh", lambda V, F: dict(real(V, F), ok=False, open_edges=3, watertight=False))
    r = ST.export_bytes(p())
    assert r["blocked"] and r["zip"] == b"" and r["files"] == []
    assert any(c["id"] == "R85" and c["level"] == "block" for c in r["checks"])


def _checks_for(sp, met=None, S=None, S0=None, dO=None):
    P = ST.Params.from_dict(ST.roller_dict(sp, 0.25))
    inside = np.ones((20, 20), bool)
    S = np.zeros((20, 20)) if S is None else S
    S0 = S if S0 is None else S0
    dO = np.full((20, 20), 5.0) if dO is None else dO
    base = dict(raised=1.5, thin=0, recess=3.0, gap=3.0, near_edge=False)
    return ST.make_checks(sp, P, 0.25, 0.25, S, S0, inside, dO, {**base, **(met or {})})[0]


def test_r81_limits_are_the_rollers_and_the_message_says_where():
    sp = ST.StampParams.from_dict(p())
    lv = lambda cs, rid: [c["level"] for c in cs if c["id"] == rid]
    full = np.full((20, 20), 1.5)
    half = full.copy()
    half[:, :8] = 0.0
    run = lambda met: _checks_for(sp, met, S=half)
    assert lv(run({"raised": 0.5}), "R81") == ["block"]
    assert lv(run({"raised": 0.9}), "R81") == ["warn"]
    assert lv(run({"recess": 0.7}), "R81") == ["warn"]
    assert lv(run({"gap": 0.7}), "R81") == ["warn"]
    assert lv(run({"thin": 2}), "R81") == ["warn"]
    assert lv(run({}), "R81") == ["pass"]
    mid = [c["text"] for c in run({"raised": 0.5}) if c["id"] == "R81"][0]
    edge = [c["text"] for c in run({"raised": 0.5, "near_edge": True}) if c["id"] == "R81"][0]
    assert "bigger" in mid and "meets the edge" not in mid
    assert lv(run({"raised": 0.5, "near_edge": True}), "R81") == ["warn"]          # a cut tip at the edge loses only the tip
    assert "where the art meets the edge" in edge and "border" in edge and "bigger" not in edge


def test_r82_blank_solid_and_frame_only_faces():
    sp = ST.StampParams.from_dict(p())
    half = np.zeros((20, 20)); half[:, :10] = 1.5
    lv = lambda cs: [(c["level"], c["text"]) for c in cs if c["id"] == "R82"][0]
    assert lv(_checks_for(sp, S=np.zeros((20, 20))))[0] == "block" and "nothing to stamp" in lv(_checks_for(sp, S=np.zeros((20, 20))))[1]
    assert lv(_checks_for(sp, S=np.full((20, 20), 1.5)))[0] == "block" and "solid" in lv(_checks_for(sp, S=np.full((20, 20), 1.5)))[1]
    lvl, txt = lv(_checks_for(sp, S=half, S0=np.zeros((20, 20))))              # a rim and no art
    assert lvl == "warn" and "frame" in txt
    assert lv(_checks_for(sp, S=half))[0] == "pass"
    few = np.zeros((20, 20)); few[:2, :6] = 1.5                                  # 3 % raised
    assert lv(_checks_for(ST.StampParams.from_dict(p(rim_on=False)), S=few))[0] == "warn" and "rock" in lv(_checks_for(ST.StampParams.from_dict(p(rim_on=False)), S=few))[1]
    most = np.full((20, 20), 1.5); most[:2, :] = 0.0                              # 85 to 98 % raised
    assert lv(_checks_for(sp, S=most))[0] == "warn" and "faint" in lv(_checks_for(sp, S=most))[1]


def test_blank_and_solid_stamps_do_not_download():
    for kw in (dict(art_source="pattern:plain", rim_on=False), dict(art_source="pattern:plain", rim_on=False, invert=True),
               dict(art_source="pattern:plain", rim_on=False, text="HOPE", text_relief="raised", text_frame="none")):
        r = ST.export_bytes(p(**kw))
        assert r["blocked"] and r["zip"] == b"" and any(c["id"] == "R82" and c["level"] == "block" for c in r["checks"]), kw
        assert not ST.preview(p(**kw))["can_export"]
    frame = ST.preview(p(art_source="pattern:plain"))                              # border only: allowed, but says so
    assert frame["can_export"] and [c["level"] for c in frame["checks"] if c["id"] == "R82"] == ["warn"]


def test_edge_slivers_are_not_false_blocks():
    """Cases the red team found: one-pixel slivers where the art meets the outline or the rim slope."""
    cases = [p(shape="rect", width_mm=80, height_mm=40, art_source="pattern:waves", rim_on=False, knob_on=False),
             p(shape="round", width_mm=25, height_mm=25, art_source="pattern:waves", depth=2.0, rim_mm=2.5, knob_on=False),
             p(shape="round", width_mm=25, height_mm=25, art_source="pattern:waves", depth=3.0, rim_mm=2.5, knob_on=False),
             p(shape="round", width_mm=100, height_mm=60, art_source="pattern:plain", text="HOPE", text_font="pacifico", text_size=18, rim_on=False, knob_on=False)]
    for c in cases:
        pv = ST.preview(c)
        assert not [x for x in pv["checks"] if x["level"] == "block"], (c, [x["text"] for x in pv["checks"] if x["level"] == "block"])


def test_preview_and_export_agree_on_all_180_combos():
    """The a6 sweep of the red team: preview and export share one measuring function at one pitch, so a block in
    one is a block in the other (the export is stopped right after its checks here; its mesh is tested above)."""
    n = 0
    for shape in ("rect", "round"):
        for pat in ("waves", "leaf", "chevron"):
            for W in (30, 45, 60, 80, 110):
                for H in (30, 60, 80):
                    for rim in (False, True):
                        c = dict(shape=shape, width_mm=W, height_mm=H, rim_on=rim, knob_on=False, art_source="pattern:" + pat)
                        pv = ST.preview(c)
                        ex = ST.export_bytes(c, None, None, _checks_only=True)
                        assert pv["can_export"] == (not ex["blocked"]), c
                        assert [x["text"] for x in pv["checks"] if x["id"] != "R85"] == [x["text"] for x in ex["checks"]], c
                        n += 1
    assert n == 180


def test_check_mesh_stays_light_and_triangles_are_capped():
    import tracemalloc
    sp = ST.StampParams.from_dict(p(shape="round", width_mm=150, height_mm=150))
    pitch = ST.mesh_pitch(sp)
    assert ST.est_triangles(sp, pitch) <= 250000
    Z = np.zeros((int(150 / pitch) + 2, int(150 / pitch) + 2))
    V, F = ST.polar_mesh(Z, pitch, pitch, 150, 150, 6.0, pitch)
    assert len(F) == ST.est_triangles(sp, pitch)
    tracemalloc.start()
    c = ST.check_mesh(V, F.astype(np.int32))
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert c["ok"] and peak < 60e6, peak
    rect = ST.StampParams.from_dict(p(shape="rect", width_mm=150, height_mm=150))
    assert ST.est_triangles(rect, ST.mesh_pitch(rect)) <= 300000


def test_pictures_over_25_megapixels_are_refused_by_header():
    big = io.BytesIO()
    Image.new("1", (6000, 5000), 1).save(big, "PNG")              # 30 MP, tiny file
    r = ST.export_bytes(p(art_source="upload"), big.getvalue(), "big.png")
    assert r["blocked"] and r["zip"] == b"" and "megapixels" in r["checks"][0]["text"] and r["checks"][0]["text"].startswith("R80")
    with pytest.raises(ST.StampError):
        ST.preview(p(art_source="upload"), big.getvalue(), "big.png")


def test_small_fixes():
    for bad in ("text", None, [1, 2], 5):
        r = ST.export_bytes(bad)
        assert r["blocked"] and r["checks"][0]["text"].startswith("R80")
        with pytest.raises(ST.StampError):
            ST.preview(bad)
    assert ST.export_bytes(p(width_mm=25.5, height_mm=60.4), None, None, _checks_only=True)["filename"] == "stamp-rect-26x60.zip"
    assert "20.25 x 60" in ST.export_bytes(p(width_mm=20.25))["checks"][0]["text"]
    assert ST._mm(60.0) == "60" and ST._mm(20.5) == "20.5" and ST._mm(20.25) == "20.25"
    # every block and warn carries an R number
    for kw in (dict(art_source="upload"), dict(art_style="group"), dict(width_mm="abc"), dict(art_source="pattern:plain", rim_on=False)):
        r = ST.export_bytes(p(**kw))
        assert all(c["text"].startswith("R") for c in r["checks"] if c["level"] in ("block", "warn")), kw
    for c in ST.preview(p(width_mm=25, height_mm=25, rim_on=False, art_source="pattern:waves"))["checks"]:
        if c["level"] in ("block", "warn"):
            assert c["text"].startswith("R"), c


def test_r83_edge_cut_off_only_when_the_border_is_off():
    off = ST.preview(p(art_source="pattern:waves", rim_on=False))
    assert [c["level"] for c in off["checks"] if c["id"] == "R83"] == ["warn"]
    on = ST.preview(p(art_source="pattern:waves", rim_on=True))
    assert not [c for c in on["checks"] if c["id"] == "R83"]


def test_r84_small_knob_pad_warns():
    small = ST.preview(p(width_mm=25, height_mm=25))
    assert [c["level"] for c in small["checks"] if c["id"] == "R84"] == ["warn"]
    big = ST.preview(p(width_mm=60, height_mm=60))
    assert [c["level"] for c in big["checks"] if c["id"] == "R84"] == ["pass"]
    none = ST.preview(p(width_mm=25, height_mm=25, knob_on=False))
    assert not [c for c in none["checks"] if c["id"] == "R84"]


def test_limits_are_clamped_with_a_note_and_the_roller_is_untouched():
    sp = ST.StampParams.from_dict(p(depth=9, rim_mm=0.1, draft_deg=99))
    assert sp.depth == 3.0 and sp.rim_mm == 1.5 and sp.draft_deg == 45.0 and len(sp.notes) == 3
    # the stamp path never edits the roller's own defaults
    from engine.params import Params
    assert Params().depth == 1.5 and Params().seam_method == "auto" and Params().bands_on is True
    assert api.stamp_preview(p())["can_export"]


# ---------------------------------------------------------------- the big one
def test_150_round_export_size_and_time():
    t = time.time()
    r = ST.export_bytes(p(shape="round", width_mm=150, height_mm=150, depth=1.5))
    secs = time.time() - t
    assert not r["blocked"]
    print("stamp 150x150 round: export %.1f s, stamp.stl %.1f MB, %d triangles, zip %.1f MB" % (
        secs, r["bytes"] / 1e6, r["triangles"], len(r["zip"]) / 1e6))
    assert r["bytes"] < 40e6 and r["triangles"] <= 260000
