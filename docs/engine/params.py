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
    "art_style": ("trace", "portrait", "group"),
    "text_layout": ("single", "band", "allover"),
    "text_relief": ("pressed", "raised"),
    "text_frame": ("halo", "none", "pill", "ring"),
    "text_style": ("solid", "outline"),
    "text_sep": ("none", "dot", "star", "heart", "diamond", "flower", "wave"),
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
    art_scale: float = 100.0
    art_shift_x: float = 0.0
    art_shift_y: float = 0.0
    art_fit: bool = False
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
    # lettering (text.py); empty text = none
    text: str = ""
    text_font: str = "pacifico"
    text_size: float = 12.0
    text_layout: str = "single"
    text_count: float = 1
    text_x: float = 50.0
    text_y: float = 85.0
    text_angle: float = 0.0
    text_arch: float = 0.0
    text_wave: float = 0.0
    text_track: float = 8.0
    text_relief: str = "pressed"
    text_frame: str = "halo"
    text_halo: float = 1.5
    text_style: str = "solid"
    text_sep: str = "dot"
    text_gap: float = 5.0
    text_row_gap: float = 6.0
    # R86 export anyway: read by the export entry points only. Not in to_dict(), so no preview, cache key or echo sees it.
    export_anyway: bool = False

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
                elif f.name == "text":
                    v = "" if v is None else str(v)
                elif isinstance(default, str):
                    v = str(v)
            except (TypeError, ValueError):
                raise ParamError(f"parameter {f.name}: bad value {v!r}")
            if f.name in ENUMS and v not in ENUMS[f.name]:
                raise ParamError(f"parameter {f.name}: {v!r} not in {ENUMS[f.name]}")
            if isinstance(v, float) and not math.isfinite(v):
                raise ParamError(f"parameter {f.name} is not finite")
            setattr(p, f.name, v)
        _lim = {"art_scale": (10.0, 400.0), "art_shift_x": (-1.0, 1.0), "art_shift_y": (-1.0, 1.0), "text_size": (3.0, 120.0), "text_count": (1, 24), "text_x": (0.0, 100.0), "text_y": (0.0, 100.0),
                "text_angle": (-180.0, 180.0), "text_arch": (-300.0, 300.0), "text_wave": (0.0, 60.0),
                "text_track": (-20.0, 80.0), "text_halo": (0.0, 10.0), "text_gap": (0.0, 100.0), "text_row_gap": (0.0, 100.0)}
        for k, (lo, hi) in _lim.items():
            setattr(p, k, min(hi, max(lo, getattr(p, k))))
        p.text_count = int(round(p.text_count))
        if p.text and (len(p.text) > 200):
            p.text = p.text[:200]
        if not (p.art_source.startswith("pattern:") or p.art_source == "upload"):
            raise ParamError("art_source must be pattern:<id> or upload")
        return p

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("export_anyway", None)
        return d

    def replace(self, **kw) -> "Params":
        d = self.to_dict()
        d["export_anyway"] = self.export_anyway
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
