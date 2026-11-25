"""Params dataclass, defaults, presets, type coercion."""
from __future__ import annotations
import math
from dataclasses import dataclass, asdict, fields


class ParamError(ValueError):
    pass


ENUMS = {
    "offset": ("none", "half_drop", "brick"),
    "seam_method": ("auto", "tile", "background", "blend", "gutter"),
    "bore_preset": ("dowel_half", "none", "rod_8", "dowel_3q", "custom"),
    "clay_body": ("stoneware", "porcelain", "earthenware", "paper"),
    "clay_state": ("soft", "firm", "leather"),
    "art_style": ("trace", "portrait"),
}
BORE_BASE = {"dowel_half": 12.70, "dowel_3q": 19.05, "rod_8": 8.00}
SHRINK = {"earthenware": 7.0, "stoneware": 12.5, "porcelain": 15.0, "paper": 14.0}
STATE_DEPTH = {"soft": (1.0, 2.0), "firm": (1.5, 2.5), "leather": (2.0, 3.0)}


@dataclass
class Params:
    diameter: float = 45.0
    length: float = 250.0
    art_source: str = "pattern:waves"
    art_style: str = "trace"
    sketch_detail: float = 0.5
    sketch_shading: bool = True
    tile_width_mm: float | None = None
    n_around: float = 3
    n_along: float | None = None
    offset: str = "none"
    offset_fraction: float = 0.5
    rotation: int = 0
    mirror: bool = True
    invert: bool = False
    spacing: float = 0.0
    depth: float = 1.5
    draft_deg: float = 15.0
    edge_round: float = 0.4
    seam_method: str = "auto"
    seam_blend_pct: float = 5.0
    seam_theta_deg: float | None = None
    band: float = 3.0
    bands_on: bool = True
    end_chamfer: float = 1.0
    alignment_ticks: bool = False
    bore_preset: str = "dowel_half"
    bore_diameter: float | None = None
    bore_clearance: float = 0.3
    split: bool = False
    clay_body: str = "stoneware"
    clay_state: str = "soft"
    glaze_flag: bool = False
    nozzle: float = 0.4
    pitch_preview: float = 0.5
    pitch_export: float = 0.2
    cnc_rotary_max_length: float = 0

    @classmethod
    def from_dict(cls, d: dict | None) -> "Params":
        d = dict(d or {})
        p = cls()
        for f in fields(cls):
            if f.name not in d:
                continue
            v = d[f.name]
            default = getattr(p, f.name)
            try:
                if f.name in ("tile_width_mm", "n_along", "seam_theta_deg", "bore_diameter"):
                    v = None if v in (None, "") else float(v)
                elif f.name == "n_around":
                    v = float(v)
                    if abs(v - round(v)) < 1e-9:
                        v = int(round(v))
                elif f.name == "rotation":
                    v = int(round(float(v)))
                elif isinstance(default, bool):
                    v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
                elif isinstance(default, (int, float)):
                    v = float(v)
                elif isinstance(default, str):
                    v = str(v)
            except (TypeError, ValueError):
                raise ParamError(f"parameter {f.name}: bad value {v!r}")
            if f.name in ENUMS and v not in ENUMS[f.name]:
                raise ParamError(f"parameter {f.name}: {v!r} not in {ENUMS[f.name]}")
            if isinstance(v, float) and not math.isfinite(v):
                raise ParamError(f"parameter {f.name} is not finite")
            setattr(p, f.name, v)
        if not (p.art_source.startswith("pattern:") or p.art_source == "upload"):
            raise ParamError("art_source must be pattern:<id> or upload")
        return p

    def to_dict(self) -> dict:
        return asdict(self)

    def replace(self, **kw) -> "Params":
        d = self.to_dict()
        d.update(kw)
        return Params.from_dict(d)

    # --- derived scalars -------------------------------------------------
    @property
    def R(self) -> float:
        return self.diameter / 2.0

    @property
    def C(self) -> float:
        return math.pi * self.diameter

    @property
    def n_int(self) -> int:
        return max(1, int(round(self.n_around)))

    @property
    def bore_used(self) -> float:
        if self.bore_preset == "none":
            return 0.0
        if self.bore_diameter:
            base = self.bore_diameter
        else:
            base = BORE_BASE.get(self.bore_preset, 12.70)
        return float(base + self.bore_clearance)

    @property
    def band_eff(self) -> float:
        return self.band if self.bands_on else 0.0


PRESETS = {
    "10 in image": {},
    "border roller": {"length": 60.0, "diameter": 30.0, "n_around": 2, "bore_preset": "rod_8"},
    "small hand roller": {"length": 100.0, "diameter": 25.0, "n_around": 2, "bore_preset": "none"},
}
