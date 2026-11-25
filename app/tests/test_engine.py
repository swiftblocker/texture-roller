import io
import json
import math
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest

from engine import api, art as artmod, mesh as meshmod, relief
from engine.params import Params

APP = Path(__file__).resolve().parents[1]
FAST = {"pitch_preview": 0.5, "pitch_export": 0.5}


def field(over=None, upload=None, name=None, pitch=0.5):
    P = Params.from_dict({**FAST, **(over or {})})
    return P, api.compute(P, upload, name, pitch)


def mesh_for(over=None, pitch=0.5):
    P, F = field(over, pitch=pitch)
    return P, F, meshmod.build_parts(P, F.Rm, F.lay)


def check_closed(m, exp):
    v = meshmod.validate(m, exp)
    assert v["watertight"] and v["winding_consistent"]
    assert v["volume"] > 0
    assert v["bbox_error"] <= 0.05, v["bbox"]
    assert v["bad_rays"] == 0
    return v


# ---------------------------------------------------------------- mesh
def test_default_mesh_closed():
    P, F, parts = mesh_for()
    assert len(parts) == 1
    for _, m, exp in parts:
        check_closed(m, exp)
        import trimesh
        assert m.is_watertight and m.is_winding_consistent and m.volume > 0


def test_no_bore_mesh_closed():
    P, F, parts = mesh_for({"bore_preset": "none"})
    for _, m, exp in parts:
        v = check_closed(m, exp)
        assert m.metadata["bore_r"] == 0


def test_split_halves_closed():
    P, F, parts = mesh_for({"split": True})
    assert [p[0] for p in parts] == ["roller_a", "roller_b"]
    for _, m, exp in parts:
        check_closed(m, exp)
        assert m.metadata["key"]
    # tongue makes half A 2 mm longer than L/2
    assert abs(parts[0][2][1] - (P.length / 2 + 2.0)) < 0.06


def test_split_no_bore_closed():
    P, F, parts = mesh_for({"split": True, "bore_preset": "none"})
    for _, m, exp in parts:
        check_closed(m, exp)


def test_test_strip_closed():
    r = api.test_strip({**FAST, "pitch_export": 0.5})
    assert not r["blocked"], r["rules"]
    names = [f for f in r["files"]]
    assert "test_strip.stl" in names and "test_strip.3mf" in names
    assert not any(x["id"] in ("R65", "R66", "R68", "R69") and not x["ok"] for x in r["rules"])


def test_bbox_matches_params():
    P, F, parts = mesh_for({"diameter": 50.0, "length": 120.0, "n_around": 4})
    m, exp = parts[0][1], parts[0][2]
    assert abs(m.bounds[1][2] - m.bounds[0][2] - 120.0) <= 0.05
    assert abs(max(m.extents[:2]) - 50.0) <= 0.05


def test_seam_weld():
    P, F, parts = mesh_for()
    m = parts[0][1]
    N = F.lay.N
    outer = m.vertices[:F.lay.M * N].reshape(F.lay.M, N, 3)
    # no duplicate column: col N-1 differs from col 0 and the whole outer set has unique points
    assert np.abs(outer[:, 0] - outer[:, -1]).max() > 1e-3
    uq = np.unique(np.round(m.vertices, 6), axis=0)
    assert len(uq) == len(m.vertices)
    # theta=0 column lies on +x
    assert np.allclose(outer[:, 0, 1], 0, atol=1e-9)


# ---------------------------------------------------------------- round trip
def unroll(P, F, m):
    M, N = F.lay.M, F.lay.N
    r = np.hypot(m.vertices[:M * N, 0], m.vertices[:M * N, 1]).reshape(M, N)
    return r - (P.R - P.depth)  # recovered H (mm)


def test_r72_roundtrip():
    P, F, parts = mesh_for()
    m = parts[0][1]
    Hm = unroll(P, F, m)
    M, N = Hm.shape
    z = np.arange(M) * F.lay.pz
    keep = (z > P.end_chamfer + 1e-6) & (z < P.length - P.end_chamfer - 1e-6)
    # SPEC mirror mapping applied to the mesh radius map -> clay image, compared with the clay image
    idx = (-np.arange(N)) % N
    Kmesh = Hm[:, idx][::-1]
    Kclay = api.clay_depth(F)
    err = np.abs(Kmesh - Kclay)[keep[::-1]]
    assert err.max() <= 0.05
    # and against the drawn art (clay = art as drawn when mirror ON), one pixel tolerance at edges
    os = F.lay.os
    drawn = F.lay.drawn_top[::os, ::os][::-1]
    bin_k = Kclay >= P.depth / 2
    from scipy import ndimage as ndi
    edge = ndi.binary_dilation(drawn, iterations=1) & ~ndi.binary_erosion(drawn, iterations=1)  # +-1 pixel at edges
    bad = (bin_k != drawn) & ~edge
    assert bad[keep[::-1]].sum() == 0


def f_svg(inset=20):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path fill="#000" d="M 30 20 L 70 20 L 70 32 L 44 32 '
            'L 44 46 L 62 46 L 62 58 L 44 58 L 44 80 L 30 80 Z"/></svg>').encode()


def test_mirror_flips_text():
    up = f_svg()
    base = {"art_source": "upload", "n_around": 1, "bands_on": False, "end_chamfer": 0.0, "length": 100.0,
            "diameter": 40.0, "bore_preset": "none", "seam_method": "tile"}
    P1, F1 = field({**base, "mirror": True}, up, "f.svg")
    P0, F0 = field({**base, "mirror": False}, up, "f.svg")
    K1, K0 = api.clay_depth(F1) > 0.75, api.clay_depth(F0) > 0.75
    N = K1.shape[1]
    third = N // 3
    # mirror ON: stem (left) heavy on the left of the clay image; arms on the right
    assert K1[:, :third * 1].sum() > 0 and K1.sum() > 0
    left1, right1 = K1[:, :N // 2].sum(), K1[:, N // 2:].sum()
    left0, right0 = K0[:, :N // 2].sum(), K0[:, N // 2:].sum()
    # F: stem x 30-44, arms to 70: ink centre is left of centre of frame (50) -> centroid check
    cx1 = (np.nonzero(K1)[1]).mean() / N
    cx0 = (np.nonzero(K0)[1]).mean() / N
    assert abs(cx1 + cx0 - 1.0) < 0.03          # mirror images of each other
    assert abs(cx1 - cx0) > 0.02
    # ON equals drawn orientation: vertical: arms at the TOP of the picture
    top = K1[:K1.shape[0] // 2].sum()
    assert top > K1[K1.shape[0] // 2:].sum() * 0.9
    # exact reversal relation between OFF and ON
    idx = (-np.arange(N)) % N
    assert (K0[:, idx] != K1).mean() < 0.01


def test_invert_flips_clay_depth():
    base = {"bands_on": False, "end_chamfer": 0.0}
    P, F = field(base)
    Pi, Fi = field({**base, "invert": True})
    K, Ki = api.clay_depth(F), api.clay_depth(Fi)
    assert np.abs((K + Ki) - P.depth).mean() < 0.12


# ---------------------------------------------------------------- rules
def rule(r, rid):
    return [x for x in r["rules"] if x["id"] == rid]


@pytest.mark.parametrize("over,rid", [
    ({"length": 300.0}, "R01"),
    ({"diameter": 12.0, "bore_preset": "none", "n_around": 1}, "R04a"),
    ({"tile_width_mm": 40.0}, "R08"),
    ({"diameter": 24.0, "bore_preset": "dowel_3q"}, "R09a"),
    ({"depth": 5.5}, "R15b"),
    ({"n_around": 2.5}, "R29"),
    ({"tile_width_mm": 30.0}, "R31b"),
    ({"n_around": 1, "offset": "half_drop"}, "R32"),
    ({"length": 252.0}, "R60"),
    ({"n_along": 12}, "R03"),
])
def test_block_rules_fire(over, rid):
    r = api.preview({**FAST, **over})
    hit = rule(r, rid)
    assert hit and hit[0]["action"] == "BLOCK" and not hit[0]["ok"], (rid, [x["id"] for x in r["rules"]])
    assert r["can_export"] is False
    assert str(rid) in hit[0]["msg"] and hit[0]["value"] is not None


def test_r19b_thin_feature_blocks():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect x="10" y="10" width="80" height="0.3" fill="#000"/>'
           '<rect x="10" y="50" width="80" height="20" fill="#000"/></svg>').encode()
    P = Params.from_dict({**FAST, "art_source": "upload", "n_around": 1, "diameter": 60.0})
    r = api.preview({**FAST, "art_source": "upload", "n_around": 1, "diameter": 60.0, "pitch_preview": 0.25}, svg, "t.svg")
    ids = {x["id"]: x for x in r["rules"]}
    assert "R19b" in ids and not ids["R19b"]["ok"], ids.keys()
    assert "R26" in ids


def test_default_has_no_block():
    r = api.preview({})
    assert r["can_export"]
    assert [x["id"] for x in r["rules"] if x["action"] == "BLOCK"] == []


def test_export_blocked_writes_no_mesh(tmp_path):
    r = api.export({**FAST, "length": 300.0}, None, None, str(tmp_path))
    assert r["blocked"]
    assert not any(f.endswith(".stl") for f in r["files"])


# ---------------------------------------------------------------- draft / timing / art
@pytest.mark.parametrize("draft", [10.0, 15.0, 25.0])
def test_draft_measured(draft):
    P = Params.from_dict({"draft_deg": draft})
    F = api.compute(P, pitch=0.2)
    assert F.metrics["min_draft_deg"] >= draft - 1.0, F.metrics["min_draft_deg"]


def test_preview_timing():
    api.preview({})
    t = time.time()
    r = api.preview({})
    dt = time.time() - t
    assert dt < 1.5, dt
    assert r["heightmap"]["cols"] > 0


def iou(a, b):
    return (a & b).sum() / max((a | b).sum(), 1)


def test_svg_png_agree():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path fill="#000" '
           'd="M 10 90 C 10 10, 60 10, 60 50 S 40 90, 55 90 Z"/>'
           '<path fill="#000" d="M 70 20 L 95 20 L 95 32 L 82 32 L 82 46 L 92 46 L 92 58 L 82 58 L 82 85 L 70 85 Z"/></svg>').encode()
    a = artmod.load("upload", svg, "x.svg")
    polys, rep = a.flatten(0.5)
    assert rep["paths"] == 2
    ps = 0.25
    fx0, fy0 = a.frame[0], a.frame[1]
    img = artmod.raster_polys(polys, 1, 1, fx0, fy0, 0, 0, 400, 400, (0.25, 0.25))
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(np.where(img[::-1], 0, 255).astype(np.uint8)).save(buf, "PNG")
    base = {"art_source": "upload", "n_around": 1, "diameter": 60.0, "length": 200.0, "bands_on": False,
            "end_chamfer": 0.0, "seam_method": "tile", "pitch_preview": 0.5}
    P1, F1 = field(base, svg, "x.svg")
    P2, F2 = field(base, buf.getvalue(), "x.png")
    assert F2.art.traced and not F1.art.traced
    m1, m2 = F1.lay.drawn_top[::2, ::2], F2.lay.drawn_top[::2, ::2]
    assert m1.any() and iou(m1, m2) > 0.9, iou(m1, m2)


def test_procedural_patterns_tile():
    for pid in ("waves", "chevron", "leaf"):
        P, F = field({"art_source": "pattern:" + pid}, pitch=0.5)
        assert F.metrics["seam_edge_diff"] <= 0.05
        assert F.metrics["min_raised_width"] >= 1.0, (pid, F.metrics["min_raised_width"])


def test_split_key_aligned_theta0():
    P, F, parts = mesh_for({"split": True})
    a, b = parts[0][1], parts[1][1]
    # tongue peak and groove floor both straddle theta = 0 (y = 0 plane)
    za = a.vertices[:, 2].max()
    tip = a.vertices[a.vertices[:, 2] > za - 1e-6]
    assert abs(tip[:, 1]).max() < 1.5 and tip[:, 0].min() > 0
    zb = b.vertices[:, 2].min()
    floor = b.vertices[(b.vertices[:, 2] > zb + 1.0) & (b.vertices[:, 2] < zb + 2.5)]
    assert len(floor) > 0


# ---------------------------------------------------------------- export + packaging
def test_export_bytes_files_and_sidecar():
    r = api.export_bytes({**FAST})
    z = zipfile.ZipFile(io.BytesIO(r["zip"]))
    names = set(z.namelist())
    for n in ("roller.stl", "roller.3mf", "heightmap_16bit.png", "slab_preview.png", "roller.json", "sheet.md"):
        assert n in names
    side = json.loads(z.read("roller.json"))
    assert side["params"]["bore_diameter_used"] == pytest.approx(13.0)
    assert any(x["id"] == "R65" for x in side["rules_all"])
    import trimesh
    m = trimesh.util.concatenate(list(trimesh.load(io.BytesIO(z.read("roller.3mf")), file_type="3mf").geometry.values()))
    assert m.is_watertight
    s = trimesh.load(io.BytesIO(z.read("roller.stl")), file_type="stl")
    assert abs(s.volume - m.volume) / m.volume < 1e-3
    from PIL import Image
    h = Image.open(io.BytesIO(z.read("heightmap_16bit.png")))
    assert h.mode.startswith("I;16") or h.mode == "I"


def test_export_to_disk(tmp_path):
    r = api.export({**FAST}, None, None, str(tmp_path))
    assert not r["blocked"]
    assert (tmp_path / "roller.stl").exists() and (tmp_path / "sheet.md").exists()


def test_checks_json_copies_identical():
    a = (APP.parent / "skill" / "pottery-roller" / "references" / "checks.json").read_bytes()
    b = (APP / "engine" / "data" / "checks.json").read_bytes()
    assert a == b


def test_manifest_lists_real_files():
    lines = [l.strip() for l in (APP / "engine" / "MANIFEST.txt").read_text().splitlines() if l.strip()]
    assert lines
    for l in lines:
        assert (APP / "engine" / l).exists(), l
    on_disk = {p.relative_to(APP / "engine").as_posix() for p in (APP / "engine").rglob("*")
               if p.is_file() and p.suffix in (".py", ".json") and "__pycache__" not in p.parts}
    assert on_disk <= set(lines)


def test_no_heavy_deps_in_core_path():
    code = (
        "import sys\n"
        "for m in ('build123d','manifold3d','lib3mf'): sys.modules[m]=None\n"
        f"sys.path.insert(0, r'{APP}')\n"
        "from engine import api\n"
        "r=api.preview({'pitch_preview':0.5})\n"
        "assert r['can_export']\n"
        "e=api.export_bytes({'pitch_export':0.5})\n"
        "assert not e['blocked']\n"
        "import zipfile,io\n"
        "n=zipfile.ZipFile(io.BytesIO(e['zip'])).namelist()\n"
        "assert 'roller.stl' in n and 'roller.3mf' in n and 'body.step' not in n, n\n"
        "assert any('desktop install' in x['msg'] for x in e['rules'])\n"
        "s=api.test_strip({'pitch_export':0.5})\n"
        "assert not s['blocked']\n"
        "print('OK')\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0 and "OK" in out.stdout, out.stderr[-2000:]
