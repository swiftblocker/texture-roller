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
    art = artmod.load(P.art_source, upload, upload_name)
    lay = layoutmod.build(P, art, pitch)
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
    F = compute(P, upload, upload_name, P.pitch_preview)
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
