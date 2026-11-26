"""Functions the server (and the browser build) call. Core imports: numpy, scipy, scikit-image, Pillow,
svgelements, potracer, trimesh. build123d is imported lazily in body.py only."""
from __future__ import annotations
import base64
import math
from dataclasses import dataclass
import numpy as np

from . import art as artmod, layout as layoutmod, relief, derived as derivedmod, rules as rulesmod
from .params import Params, ParamError  # noqa: F401


@dataclass
class Field:
    P: Params
    art: object
    lay: object
    H: np.ndarray
    Rm: np.ndarray
    metrics: dict
    pitch: float


def compute(P: Params, upload=None, upload_name=None, pitch=None) -> Field:
    pitch = pitch or P.pitch_preview
    tw = P.tile_width_mm or (P.C / P.n_int)
    tw = max(20.0, tw - max(0.0, P.spacing))
    # Draft widens every raised line at its base by depth*tan(draft) per side, so the sketch
    # leaves gaps wide enough that the clay gap stays >= 1.0 mm (R20, R21).
    gap = 1.0 + 2.0 * P.depth * math.tan(math.radians(P.draft_deg))
    # group photos fill the roller's length: art height = length - both end bands - 4 mm air
    gh = max(20.0, P.length - 2 * P.band_eff - 4.0)
    art = artmod.load(P.art_source, upload, upload_name, P.art_style, tw, P.sketch_detail, P.sketch_shading, gap, gh)
    lay = layoutmod.build(P, art, pitch)
    if art.sketch:
        lay.art_report["sketch"] = art.sketch
    H = relief.height_field(P, lay)
    Rm = relief.radius_map(P, H, lay)
    met = relief.metrics(P, H, lay)
    lay.art_report["dropped_thin"] = int(met["thin_components"])
    return Field(P, art, lay, H, Rm, met, pitch)


def clay_depth(F: Field) -> np.ndarray:
    """Clay depth image in mm, picture order (row 0 = z = L end). K[i] = H[(N-i)%N]; clay depth = H."""
    H = F.H
    N = H.shape[1]
    idx = (-np.arange(N)) % N
    return np.ascontiguousarray(H[:, idx][::-1])


def _b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def resolved(P, F):
    d = P.to_dict()
    d["bore_diameter_used"] = P.bore_used
    d["seam_theta_deg_used"] = F.lay.seam_theta_used
    d["seam_method_used"] = F.lay.method_used
    d["rotation_used"] = P.rotation
    return d


def preview(params: dict, upload: bytes | None = None, upload_name: str | None = None) -> dict:
    P = Params.from_dict(params)
    pitch = P.pitch_preview
    if (P.text or "").strip() or (P.art_style == "group" and P.art_source == "upload"):
        pitch = min(pitch, 0.35)   # letters need a finer grid than the art to be measured (R19-R21)
    F = compute(P, upload, upload_name, pitch)
    dv = derivedmod.derived(P, F)
    rules = rulesmod.evaluate(P, F, dv)
    vis, can = rulesmod.summarize(rules)
    K = clay_depth(F)
    M, N = F.H.shape
    return {
        "params": resolved(P, F),
        "derived": {k: v for k, v in dv.items() if k != "volume_mm3"},
        "rules": vis,
        "can_export": can,
        "heightmap": {"cols": N, "rows": M, "pitch_theta_mm": F.lay.pt, "pitch_z_mm": F.lay.pz,
                      "depth": P.depth, "data_b64": _b64(F.H.astype("<f4"))},
        "clay": {"cols": N, "rows": M,
                 "data_b64": _b64(np.clip(np.round(K / P.depth * 255.0), 0, 255).astype(np.uint8))},
        "art_report": F.lay.art_report,
    }


def fit_portrait(params: dict, upload: bytes | None) -> dict:
    """One face per revolution, art height = length - 2 x band. -> {diameter, n_around, n_along, face_found}."""
    from . import sketch as sketchmod
    P = Params.from_dict(params)
    if not upload:
        raise artmod.ArtError("no picture to fit")
    if P.art_style == "group":
        return fit_group(P, upload)
    aspect, found = sketchmod.head_aspect(upload)
    art_h = max(10.0, P.length - 2 * P.band_eff)
    width = art_h * aspect
    d = min(100.0, max(16.0, math.floor(width / math.pi * 10.0) / 10.0))
    # Portrait relief: shallower and gentler than the default so the sketch's close strokes
    # stay separate in clay (gap floor 1.0 + 2 d tan(draft) = 1.42 mm). R13 range, R17 soft clay 1-2 mm, R22 >= 5 deg.
    return {"diameter": d, "n_around": 1, "n_along": 1, "depth": 1.2, "draft_deg": 10.0, "face_found": bool(found)}


def fonts() -> list:
    from . import text as textmod
    return textmod.fonts()


def fit_group(P, upload) -> dict:
    """Whole group once around: art height = length - bands - 4 mm, circumference = art width.
    Block-print relief: 1.2 mm deep, 10 deg draft (gap floor stays near 1.4 mm, R20/R21)."""
    from . import group as groupmod
    asp, n = groupmod.aspect(upload)
    if n == 0:
        raise artmod.ArtError("no faces found in the photo; try a photo where faces look at the camera")
    art_h = max(20.0, P.length - 2 * P.band_eff - 4.0)
    d = min(100.0, max(16.0, math.floor(art_h * asp / math.pi * 10.0) / 10.0))
    return {"diameter": d, "n_around": 1, "n_along": 1, "depth": 1.2, "draft_deg": 10.0, "faces": n, "face_found": True}


def patterns() -> list:
    return [dict(p) for p in artmod.PATTERNS]


def solve_repeat(tile_width: float, d_min=25, d_max=100, max_n=12) -> list:
    return derivedmod.solve_repeat(float(tile_width), d_min, d_max, max_n)


def export_bytes(params: dict, upload: bytes | None = None, upload_name: str | None = None) -> dict:
    from . import export as ex
    return ex.build_zip(params, upload, upload_name)


def export(params: dict, upload: bytes | None, upload_name: str | None, out_dir: str) -> dict:
    from . import export as ex
    return ex.write_dir(ex.build_zip(params, upload, upload_name), out_dir)


def test_strip(params: dict, out_dir: str | None = None) -> dict:
    from . import export as ex
    r = ex.build_strip(params)
    if out_dir:
        return ex.write_dir(r, out_dir)
    return r


def cookie_preview(params: dict, upload: bytes | None = None, upload_name: str | None = None) -> dict:
    """Cookie cutter tab: outline + inside lines + back bridges as mm polygons, plain-word checks."""
    from . import cookie as cookiemod
    return cookiemod.preview(params, upload, upload_name)


def cookie_export(params: dict, upload: bytes | None = None, upload_name: str | None = None) -> dict:
    """-> {stl: bytes, sidecar: dict, blocked: bool, checks, filename}."""
    from . import cookie as cookiemod
    return cookiemod.export_bytes(params, upload, upload_name)


def stamp_preview(params: dict, upload: bytes | None = None, upload_name: str | None = None) -> dict:
    """Stamp tab: checks (R80-R85 in plain words), the face heightmap and the clay shading as base64 uint8."""
    from . import stamp as stampmod
    return stampmod.preview(params, upload, upload_name)


def stamp_export(params: dict, upload: bytes | None = None, upload_name: str | None = None) -> dict:
    """-> {zip: bytes, blocked: bool, checks, filename, files, bytes, triangles}. A blocked export has no zip."""
    from . import stamp as stampmod
    return stampmod.export_bytes(params, upload, upload_name)
