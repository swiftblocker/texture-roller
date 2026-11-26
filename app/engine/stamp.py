"""Stamp tab: the roller's art and relief engine laid on a flat hand stamp.

Trick (proven in app/out/stamp/stamp_spike.py): a roller whose circumference equals the stamp width and whose
length equals the stamp height, one tile around, no end bands, gives the clay picture K at the size of the stamp
face. The stamp face is K mirrored left to right (a face-down stamp flips the picture), so what reads right in the
clay is printed backwards on the face.

Everything here is numpy / scipy / Pillow. There is NO shapely in this file: in Pyodide a GEOS TopologyException
aborts the whole runtime, so outlines, the border rim and the edge chamfer are distance fields (closed form for a
rectangle and an ellipse), and both meshes are built by index arithmetic (a heightfield grid for the rectangle, a
rings-and-spokes polar grid for the ellipse). Both are closed by construction; check_mesh() proves it anyway and a
failed proof blocks the download (R85).

Frame: mm, x right, y up, z up. The back of the block is on z = 0, the face is up; the knob file stands on its
glue pad (z = 0).
"""
from __future__ import annotations
import base64
import hashlib
import io
import json
import math
import time
import zipfile
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage as ndi
from skimage.morphology import skeletonize

from . import api as apimod, art as artmod, export as ex, relief
from .params import Params, ParamError
from .rules import checks as roller_checks

FRIENDLY = "R80: This drawing tripped up the stamp maker. Try a slightly different size or a simpler drawing."

SIZE_MIN, SIZE_MAX = 25.0, 150.0          # R80, mm each way
BASE_KNOB, BASE_PLAIN = 6.0, 12.0         # block under the relief; thick when there is no knob (gripped by the edges)
CHAMFER = 0.6                             # outer top edge, mm
KNOB_H, KNOB_GRIP, KNOB_PAD_MAX = 30.0, 28.0, 40.0
SHARE_LOW, SHARE_HIGH = 0.08, 0.85        # R82 warn
SHARE_NONE, SHARE_SOLID = 0.02, 0.98      # R82 block: nothing to stamp / a solid face
MEASURE_PITCH = 0.25                      # R81-R84 are measured on this one grid, for the preview and the export alike
EDGE_BAND = 3.0                           # mm: slivers this close to the outline are cut-off art, not real thin lines
TRI_CAP_RECT, TRI_CAP_ROUND = 300000, 250000
MAX_MEGAPIXELS = 25
CHUNK = 60000                             # rows per numpy chunk when writing or checking big meshes
LIMITS = {"depth": (0.8, 3.0), "rim_mm": (1.5, 6.0), "draft_deg": (0.0, 45.0), "edge_round": (0.0, 2.0)}
# roller parameters a stamp may pass through: the art, the picture controls and every lettering control
ART_KEYS = ("art_source", "art_style", "sketch_detail", "sketch_shading", "art_scale", "art_shift_x", "art_shift_y",
            "invert", "text", "text_font", "text_size", "text_layout", "text_count", "text_x", "text_y", "text_angle",
            "text_arch", "text_wave", "text_track", "text_relief", "text_frame", "text_halo", "text_style", "text_sep",
            "text_gap", "text_row_gap")
PRINT_NOTES = ("Print the stamp face up on the bed, no supports, 0.2 mm layers, 0.4 mm nozzle. "
               "Print the knob standing on its flat pad, no supports. "
               "Glue the knob pad centred on the back of the stamp with CA glue or epoxy.")


class StampError(ValueError):
    pass


def _mm(v):
    """A length for a message: two decimals only when they are needed."""
    return ("%.2f" % v).rstrip("0").rstrip(".")


# ---------------------------------------------------------------- parameters
@dataclass
class StampParams:
    shape: str = "rect"            # "rect" or "round" (round with W != H is an oval)
    width_mm: float = 60.0
    height_mm: float = 60.0
    depth: float = 1.5
    draft_deg: float = 15.0
    edge_round: float = 0.4
    rim_on: bool = True
    rim_mm: float = 2.5
    knob_on: bool = True
    n_across: int = 1              # pattern repeats across the face (patterns only)
    art: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict):
            raise StampError("R80: The stamp settings were not understood. Reload the page and try again.")
        d = dict(d)
        sp = cls()

        def num(k, default):
            v = d.get(k, default)
            try:
                if isinstance(v, (bool, list, dict)) or v is None:
                    raise TypeError
                v = float(v)
            except (TypeError, ValueError):
                raise StampError("R80: %s must be a number." % k.replace("_mm", "").replace("_", " "))
            if not math.isfinite(v):
                raise StampError("R80: %s must be a number." % k.replace("_mm", "").replace("_", " "))
            return v

        def flag(k, default):
            v = d.get(k, default)
            return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
        sp.shape = str(d.get("shape", "rect"))
        if sp.shape not in ("rect", "round"):
            raise StampError("R80: shape must be square or round.")
        sp.width_mm, sp.height_mm = num("width_mm", 60.0), num("height_mm", 60.0)
        for k, (lo, hi) in LIMITS.items():
            v = num(k, getattr(cls, k))
            c = min(hi, max(lo, v))
            if abs(c - v) > 1e-9:
                sp.notes.append("%s limited to %g (range %g to %g)" % (k.replace("_mm", "").replace("_", " "), c, lo, hi))
            setattr(sp, k, c)
        sp.rim_on, sp.knob_on = flag("rim_on", True), flag("knob_on", True)
        sp.n_across = int(min(12, max(1, round(num("n_across", 1)))))
        sp.art = {k: d[k] for k in ART_KEYS if k in d}
        if sp.art.get("art_style", "trace") not in ("trace", "portrait"):
            raise StampError("R80: Group photos are not supported on the stamp tab. Use a drawing, a logo or a photo of one person.")
        return sp

    @property
    def base(self):
        return BASE_KNOB if self.knob_on else BASE_PLAIN

    @property
    def top_z(self):
        return self.base + self.depth

    @property
    def is_upload(self):
        return self.art.get("art_source", "pattern:waves") == "upload"

    def to_dict(self):
        d = {"shape": self.shape, "width_mm": self.width_mm, "height_mm": self.height_mm, "depth": self.depth,
             "draft_deg": self.draft_deg, "edge_round": self.edge_round, "rim_on": self.rim_on, "rim_mm": self.rim_mm,
             "knob_on": self.knob_on, "n_across": self.n_across}
        d.update(self.art)
        return d


def export_pitch(sp):
    return max(0.2, max(sp.width_mm, sp.height_mm) / 450.0)


def preview_pitch(sp):
    return max(0.5, max(sp.width_mm, sp.height_mm) / 300.0)


def knob_dims(sp):
    """(glue pad diameter, grip diameter) in mm. Pad = min(40, 0.7 x the short side); under a 35 mm face the grip
    shrinks too but never below 18 mm."""
    m = min(sp.width_mm, sp.height_mm)
    pad = min(KNOB_PAD_MAX, 0.7 * m)
    grip = KNOB_GRIP if m >= 35.0 else max(18.0, KNOB_GRIP * m / 35.0)
    return pad, grip


def roller_dict(sp, pitch):
    """The roller Params this stamp runs on: diameter = W / pi, length = H, one tile around, no bands."""
    d = dict(sp.art)
    up = sp.is_upload
    d.update(diameter=sp.width_mm / math.pi, length=sp.height_mm, n_around=1 if up else sp.n_across, n_along=None,
             tile_width_mm=None, offset="none", rotation=0, spacing=0.0, bands_on=False, band=0.0, end_chamfer=0.0,
             # "tile": the art is never slid round the seam; it would wrap round the edge of a flat stamp
             seam_method="tile", seam_blend_pct=0.0, seam_theta_deg=None, alignment_ticks=False,
             bore_preset="none", split=False, mirror=True, depth=sp.depth, draft_deg=sp.draft_deg,
             edge_round=sp.edge_round, art_fit=up, pitch_preview=pitch, pitch_export=pitch)
    return d


# ---------------------------------------------------------------- outline distance fields (closed form, no GEOS)
def _ellipse_dist(px, py, a, b, t, iters):
    for _ in range(iters):
        ct, st = np.cos(t), np.sin(t)
        ex_ = (a * a - b * b) * ct ** 3 / a
        ey_ = (b * b - a * a) * st ** 3 / b
        rx, ry = a * ct - ex_, b * st - ey_
        qx, qy = px - ex_, py - ey_
        r = np.hypot(rx, ry)
        q = np.maximum(np.hypot(qx, qy), 1e-12)
        t = np.clip(np.arctan2((qy * r / q + ey_) / b, (qx * r / q + ex_) / a), 0.0, math.pi / 2)
    return np.hypot(px - a * np.cos(t), py - b * np.sin(t))


def ellipse_sd(x, y, a, b, iters=6):
    """Signed distance to the ellipse x^2/a^2 + y^2/b^2 = 1 about the origin, positive inside. Exact for a circle;
    for an ellipse the evolute iteration (from two starting angles, the smaller distance wins, because a point
    close to the long axis can get stuck on the far end) converges to the true distance."""
    px, py = np.abs(x), np.abs(y)
    if abs(a - b) < 1e-9:
        return a - np.hypot(px, py)
    d1 = _ellipse_dist(px, py, a, b, np.arctan2(a * py, b * px), iters)
    d2 = _ellipse_dist(px, py, a, b, np.full_like(px, math.pi / 2 - 0.05), iters) if a > b else         _ellipse_dist(px, py, a, b, np.full_like(px, 0.05), iters)
    dist = np.minimum(d1, d2)
    return np.where((px / a) ** 2 + (py / b) ** 2 < 1.0, dist, -dist)


def outline_sd(shape, X, Y, W, H):
    """Distance in mm from each point to the outline, positive inside."""
    if shape == "round":
        return ellipse_sd(X - W / 2.0, Y - H / 2.0, W / 2.0, H / 2.0)
    return np.minimum(np.minimum(X, W - X), np.minimum(Y, H - Y))


# ---------------------------------------------------------------- the face
def check_picture_size(upload):
    """Refuse a raster picture over 25 megapixels from its header, before anything decodes it (a 100 MP PNG is
    hundreds of MB of pixels in a browser tab)."""
    head = upload[:512].lstrip().lower()
    if head.startswith(b"<?xml") or b"<svg" in head:
        return
    try:
        from PIL import Image
        w, h = Image.open(io.BytesIO(upload)).size
    except Exception:
        return                      # not readable: the loader says so in its own plain words
    if w * h > MAX_MEGAPIXELS * 1e6:
        raise StampError("R80: This picture is %d x %d pixels (%.0f megapixels). The limit is %d megapixels. Make it smaller and try again." % (w, h, w * h / 1e6, MAX_MEGAPIXELS))


def build_face(sp, upload, name, pitch):
    """-> dict(S0 (M x N+1 clay-depth heights as the FACE, mm), pt, pz, P, art_report). Face column j is clay column
    N - j: an exact reflection about the middle of the face, spanning 0..W."""
    try:
        P = Params.from_dict(roller_dict(sp, pitch))
    except ParamError as exc:
        import re
        m = re.search(r"parameter (\w+)", str(exc))
        raise StampError("R80: The setting %s is not a usable value." % (m.group(1).replace("_", " ") if m else "")) from exc
    if sp.is_upload and not upload:
        raise StampError("R80: Upload a picture to start.")
    if sp.is_upload:
        check_picture_size(upload)
    try:
        F = apimod.compute(P, upload, name, pitch)
    except (StampError, ParamError):
        raise
    except artmod.ArtError as exc:
        raise StampError("R80: We could not use this picture (%s)." % exc) from exc
    except Exception as exc:
        if "identify image" in str(exc) or "cannot" in str(exc).lower():
            raise StampError("R80: We could not open this file as a picture. Use a PNG, JPEG, WEBP or SVG file.") from exc
        raise StampError(FRIENDLY) from exc
    K = apimod.clay_depth(F)                              # picture as read in the clay, row 0 = top
    M, N = K.shape
    S0 = np.concatenate([K[:, -1:], K[:, ::-1]], axis=1).astype(np.float64)
    return dict(S0=S0, K=K, pt=sp.width_mm / N, pz=sp.height_mm / (M - 1), P=P, F=F, art_report=F.lay.art_report)


def rim_height(dO, rim_w, P):
    """Rim profile: full height at the outline, sloping down on its inner side with the roller's own draft and edge round."""
    sl, hl, _ = relief.profile_lut(P.depth, P.draft_deg, P.edge_round)
    return np.interp(rim_w - dO, sl, hl)


def compose(sp, S0, pt, pz, P):
    """-> S (face relief incl. rim, mm above the block), Zm (the same with the 0.6 mm outer-edge chamfer), dO, inside."""
    M, Nc = S0.shape
    W, H, d = sp.width_mm, sp.height_mm, sp.depth
    X, Y = np.meshgrid(np.arange(Nc) * pt, (M - 1 - np.arange(M)) * pz)
    dO = outline_sd(sp.shape, X, Y, W, H)
    S = S0
    if sp.rim_on:
        S = np.maximum(S, rim_height(dO, sp.rim_mm, P))
    Zm = np.maximum(np.minimum(S, d - CHAMFER + dO), 0.0)
    return S, Zm, dO, dO > -1e-6


# ---------------------------------------------------------------- checks
def _raised_widths(mask, dO, pt, pz, nozzle):
    """Same skeleton method as relief._widths for raised lines (2nd percentile along the skeleton, tips ignored,
    whole pieces under 1 mm2 ignored), plus where the thin places are: -> (width, thin pieces, near_edge)."""
    if not mask.any():
        return math.inf, 0, False
    edt = ndi.distance_transform_edt(mask, sampling=(pz, pt))
    pm = 0.5 * (pt + pz)
    sk = skeletonize(mask)
    nb = ndi.convolve(sk.astype(np.uint8), np.ones((3, 3), np.uint8), mode="constant")
    ends = sk & (nb <= 2)
    ok = sk.copy()
    if ends.any():
        ok &= ndi.distance_transform_edt(~ends, sampling=(pz, pt)) > max(2.0, 3 * pm)
    ys, xs = np.nonzero(ok)
    if len(ys) == 0:
        ys, xs = np.nonzero(sk)
    vals = (2 * edt - pm)[ys, xs]
    p2 = float(np.percentile(vals, 2)) if vals.size else math.inf
    lab, n = ndi.label(mask)
    cmin, thin = math.inf, 0
    if n:
        ix = np.arange(1, n + 1)
        mx = np.asarray(ndi.maximum(edt, lab, index=ix))
        area = np.asarray(ndi.sum(np.ones_like(lab), lab, index=ix)) * pt * pz
        cw = (2 * mx - pm)[area >= 1.0]
        if cw.size:
            thin, cmin = int(np.sum(cw < 2 * nozzle)), float(cw.min())
    w = min(p2, cmin)
    low = vals <= max(w, 1.0) + 1e-9
    near = bool(low.any() and float(np.mean(dO[ys[low], xs[low]] < EDGE_BAND)) >= 0.5)
    return w, thin, near


def face_metrics(S, inside, dO, pt, pz, d, nozzle):
    """The roller's width and gap metrics (the same skeleton method) on a NON-wrapping face. Outside the outline
    counts as open space for grooves and gaps and as nothing for raised lines. Raised pieces under 2 pixels wide
    within 3 mm of the outline are one-pixel slivers where the art meets the edge or the rim slope; they are
    ignored (a real thin line near the edge is reported as "where the art meets the edge")."""
    m = 26
    raised = (S >= 0.75 * d) & inside
    sliver = raised & ~ndi.binary_opening(raised, structure=np.ones((2, 2), bool)) & (dO < EDGE_BAND)
    raised &= ~sliver
    dOp = np.pad(dO, m, mode="constant", constant_values=-1.0)
    raised = np.pad(raised, m, mode="constant", constant_values=False)
    recess = np.pad((S < 0.5 * d) | ~inside, m, mode="constant", constant_values=True)
    gap = np.pad((S < 0.75 * d) | ~inside, m, mode="constant", constant_values=True)
    rw, thin, near = _raised_widths(raised, dOp, pt, pz, nozzle)
    out = {"raised": rw, "thin": thin, "near_edge": near, "recess": relief._widths(recess, pt, pz, nozzle)[0],
           "gap": relief._widths(gap, pt, pz, nozzle)[0]}
    for k in ("raised", "recess", "gap"):
        if out[k] == math.inf:
            out[k] = None
    return out


def _g(v):
    return "%.3g" % v


def make_checks(sp, P, pt, pz, S, S0, inside, dO, met):
    """Plain-word checks, each naming its rule number. Levels: pass, warn, block. A pure function of the face at the
    one measuring pitch, so the preview and the export cannot disagree."""
    ck = roller_checks()
    d = sp.depth
    out = []
    for n in sp.notes:
        out.append({"id": "NOTE", "level": "pass", "text": n[0].upper() + n[1:] + "."})
    out.append({"id": "R80", "level": "pass", "text": "R80: Face %s x %s mm, inside the %g to %g mm limit." % (_mm(sp.width_mm), _mm(sp.height_mm), SIZE_MIN, SIZE_MAX)})
    # R81: raised lines and gaps, the roller's R19-R21 and R26 limits on the stamp face
    rw, rc_, gp = met["raised"], met["recess"], met["gap"]
    fix = "Turn the border on or make the art smaller." if met.get("near_edge") else "Make the art bigger or bolder."
    where = " where the art meets the edge" if met.get("near_edge") else ""
    if rw is not None and rw < ck["R19b"]["value"]:
        # a thin tip where the art is cut by the edge only loses that tip in the print (R83 says so); a thin line in the
        # middle of the art is what blocks
        out.append({"id": "R81", "level": "warn" if met.get("near_edge") else "block", "text": "R81 (R19b): The thinnest raised line is %s mm%s. Under %s mm it will not print. %s" % (_g(rw), where, _g(ck["R19b"]["value"]), fix)})
    elif rw is not None and rw < ck["R19a"]["value"]:
        out.append({"id": "R81", "level": "warn", "text": "R81 (R19a): The thinnest raised line is %s mm%s. Under %s mm clay can pull it off. %s" % (_g(rw), where, _g(ck["R19a"]["value"]), fix)})
    lim20 = max(1.0, 0.8 * d)
    if rc_ is not None and rc_ < lim20:
        out.append({"id": "R81", "level": "warn", "text": "R81 (R20): The narrowest pressed-in groove is %s mm. Under %s mm clay will not fill it and let go cleanly. Widen the groove or the lines." % (_g(rc_), _g(lim20))})
    if gp is not None and gp < ck["R21"]["value"]:
        out.append({"id": "R81", "level": "warn", "text": "R81 (R21): Raised features come closer than %s mm (narrowest gap %s mm). Space them out." % (_g(ck["R21"]["value"]), _g(gp))})
    if met["thin"]:
        out.append({"id": "R81", "level": "warn", "text": "R81 (R26): %d feature(s) are thinner than %s mm (2 x nozzle) and will not print. Thicken or remove them." % (met["thin"], _g(2 * P.nozzle))})
    if not any(c["id"] == "R81" for c in out):
        out.append({"id": "R81", "level": "pass", "text": "R81: Raised lines at least %s mm wide, gaps at least %s mm." % (_g(rw) if rw is not None else "-", _g(gp) if gp is not None else "-")})
    if sp.draft_deg < ck["R22"]["value"]:
        out.append({"id": "R22", "level": "warn", "text": "R22: Draft %g deg is under %g deg. Steep sides grip the clay and tear it." % (sp.draft_deg, ck["R22"]["value"])})
    if sp.edge_round < 0.3:
        out.append({"id": "R24", "level": "warn", "text": "R24: Edge round %g mm is under 0.3 mm. Sharp edges tear clay." % sp.edge_round})
    # R82: enough contact, but something to stamp
    n_in = max(1, int(inside.sum()))
    share = float(((S >= 0.75 * d) & inside).sum()) / n_in
    art_share = float(((S0 >= 0.75 * d) & inside).sum()) / n_in
    if share < SHARE_NONE:
        why = " Raised letters need something around them to show (try Pressed in)." if sp.art.get("text") and sp.art.get("text_relief") == "raised" else ""
        out.append({"id": "R82", "level": "block", "text": "R82: Less than 2 %% of the face is raised, so there is nothing to stamp. Add art or text.%s" % why})
    elif share >= SHARE_SOLID:
        out.append({"id": "R82", "level": "block", "text": "R82: The face is solid (%d %% raised) and it will print nothing. Add some empty space to the art." % round(100 * share)})
    elif sp.rim_on and art_share < SHARE_NONE:
        out.append({"id": "R82", "level": "warn", "text": "R82: Only the border is raised, so this stamp prints just a frame. Add art or text."})
    elif share < SHARE_LOW:
        tip = "Make the border wider or add more art." if sp.rim_on else "Turn the border on or add more art."
        out.append({"id": "R82", "level": "warn", "text": "R82: Only %d %% of the face is raised: this stamp will rock. %s" % (round(100 * share), tip)})
    elif share > SHARE_HIGH:
        out.append({"id": "R82", "level": "warn", "text": "R82: %d %% of the face is raised: it is almost solid and the print will be faint. Add some empty space to the art." % round(100 * share)})
    else:
        out.append({"id": "R82", "level": "pass", "text": "R82: %d %% of the face is raised, enough to press evenly." % round(100 * share)})
    # R83: art running into the outline with no border
    if not sp.rim_on:
        band = inside & (dO < 0.75)
        frac = float(((S >= 0.75 * d) & band).sum()) / max(1, int(band.sum()))
        if frac > 0.01:
            out.append({"id": "R83", "level": "warn", "text": "R83: The art runs to the edge of the stamp and will be cut off there. Turn the border on or make the art smaller."})
        else:
            out.append({"id": "R83", "level": "pass", "text": "R83: The art stays clear of the edge."})
    # R84: knob pad
    if sp.knob_on:
        pad, grip = knob_dims(sp)
        if pad < 20.0:
            out.append({"id": "R84", "level": "warn", "text": "R84: The knob's glue pad is only %s mm (under 20 mm). It may pop off; use epoxy, or turn the knob off and grip the thick block by its edges." % _g(pad)})
        else:
            out.append({"id": "R84", "level": "pass", "text": "R84: Knob glue pad %s mm." % _g(pad)})
    return out, share


# ---------------------------------------------------------------- meshes (numpy only, closed by construction)
def _closed_solid(Vtop, Ftop, ring):
    """Close a top surface into a solid: vertical walls from the boundary ring (counter-clockwise from above) down to
    z = 0, and a flat bottom as a fan round one centre vertex."""
    nt = len(Vtop)
    R = len(ring)
    xy = Vtop[ring, :2]
    Vb = np.concatenate([xy, np.zeros((R, 1))], axis=1)
    cen = np.array([[xy[:, 0].mean(), xy[:, 1].mean(), 0.0]])
    V = np.concatenate([Vtop, Vb, cen])
    t = ring.astype(np.int64)
    b = nt + np.arange(R, dtype=np.int64)
    tn, bn = np.roll(t, -1), np.roll(b, -1)
    c = np.full(R, nt + R, dtype=np.int64)
    F = np.concatenate([Ftop, np.c_[t, b, tn], np.c_[tn, b, bn], np.c_[c, bn, b]])
    return V, F


def rect_mesh(Z, pt, pz, base):
    """Heightfield block: top surface base + Z on the grid, four walls, flat bottom."""
    M, N = Z.shape
    X, Y = np.meshgrid(np.arange(N) * pt, (M - 1 - np.arange(M)) * pz)
    Vtop = np.c_[X.ravel(), Y.ravel(), (base + Z).ravel()]
    idx = np.arange(M * N, dtype=np.int64).reshape(M, N)
    a, b, c, e = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel()
    Ftop = np.concatenate([np.c_[a, c, b], np.c_[b, c, e]])
    ring = np.concatenate([idx[M - 1, :N - 1], idx[M - 1:0:-1, N - 1], idx[0, N - 1:0:-1], idx[0:M - 1, 0]])
    return _closed_solid(Vtop, Ftop, ring)


def ellipse_perimeter(a, b):
    return math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))


def polar_rings(a, b, pitch):
    """Spoke count for each ring of a round or oval block. Rings are at most one pitch apart; the spoke count
    halves going inward each time a ring's circumference halves, so the edges stay near one pitch long all the way in
    (one count for every ring would crowd the middle with slivers and double the triangles)."""
    n_r = max(2, int(math.ceil(max(a, b) / pitch)))
    n_out = int(math.ceil(ellipse_perimeter(a, b) / pitch))
    J = 0
    while n_out / 2 ** (J + 1) >= 24 and J < 6:
        J += 1
    mult = 4 * 2 ** J
    n_s = max(mult, int(math.ceil(n_out / mult)) * mult)      # a multiple of 4 puts spokes on both axes
    counts = []
    for k in range(1, n_r + 1):
        j = min(J, int(math.floor(math.log2(n_r / k) + 1e-9)))
        counts.append(n_s >> j)
    return n_r, counts


def polar_tris(counts):
    return counts[0] + sum(counts[k] + counts[k + 1] for k in range(len(counts) - 1)) + 3 * counts[-1]


def polar_mesh(Z, pt, pz, W, H, base, pitch):
    """Round or oval block on a polar grid: one centre vertex, rings of N and 2N spokes stitched with triangle
    strips, the face sampled by bilinear interpolation. The outer ring is the true ellipse."""
    a, b = W / 2.0, H / 2.0
    n_r, counts = polar_rings(a, b, pitch)
    xs, ys = [np.array([a])], [np.array([b])]
    for k, n in enumerate(counts, 1):
        rho = k / n_r
        phi = 2.0 * math.pi * np.arange(n) / n
        xs.append(a + a * rho * np.cos(phi))
        ys.append(b + b * rho * np.sin(phi))
    X, Y = np.concatenate(xs), np.concatenate(ys)
    Zs = ndi.map_coordinates(Z, [(H - Y) / pz, X / pt], order=1, mode="nearest")
    Vtop = np.c_[X, Y, base + Zs]
    off = np.concatenate([[1], 1 + np.cumsum(counts)])           # first vertex id of each ring
    faces = []
    n0 = counts[0]
    i = np.arange(n0, dtype=np.int64)
    faces.append(np.c_[np.zeros(n0, dtype=np.int64), 1 + i, 1 + (i + 1) % n0])
    for k in range(n_r - 1):
        m, m2 = counts[k], counts[k + 1]
        i = np.arange(m, dtype=np.int64)
        inx = (i + 1) % m
        o, o2 = off[k], off[k + 1]
        if m2 == m:
            aa, bb, cc, ee = o + i, o + inx, o2 + i, o2 + inx
            faces += [np.c_[aa, cc, bb], np.c_[bb, cc, ee]]
        else:                                                   # m2 == 2 m: three triangles per inner edge
            aa, bb = o + i, o + inx
            c0, c1, c2 = o2 + 2 * i, o2 + 2 * i + 1, o2 + (2 * i + 2) % m2
            faces += [np.c_[aa, c0, c1], np.c_[aa, c1, bb], np.c_[bb, c1, c2]]
    ring = off[n_r - 1] + np.arange(counts[-1], dtype=np.int64)
    return _closed_solid(Vtop, np.concatenate(faces), ring)


def knob_mesh(pad, grip, h=KNOB_H, sections=72):
    """Mushroom knob that prints standing on its flat pad with no supports: pad disc, 45 degree taper to the waist,
    waist, 45 degree underside out to the cap, dome. Centred on x = y = 0, pad on z = 0."""
    rp, rc = pad / 2.0, grip / 2.0
    rw = min(max(4.0, 0.3 * grip), rp - 1.0)
    t0 = 2.5
    hd = 0.5 * rc
    z_c1 = h - hd
    z_c0 = z_c1 - (rc - rw)
    z_w0 = t0 + (rp - rw)
    if z_c0 < z_w0 + 1.0:
        raise StampError("knob does not fit its height")
    prof = [(0.0, 0.0), (rp, 0.0), (rp, t0), (rw, z_w0), (rw, z_c0), (rc, z_c1)]
    for tt in np.linspace(0.0, math.pi / 2, 13)[1:-1]:
        prof.append((rc * math.cos(tt), z_c1 + hd * math.sin(tt)))
    prof.append((0.0, h))
    prof = np.array(prof)
    ring_pts = prof[1:-1]
    P_ = len(ring_pts)
    ang = 2.0 * math.pi * np.arange(sections) / sections
    ca, sa = np.cos(ang), np.sin(ang)
    V = [np.array([[0.0, 0.0, 0.0]])]
    for r, z in ring_pts:
        V.append(np.c_[r * ca, r * sa, np.full(sections, z)])
    V.append(np.array([[0.0, 0.0, h]]))
    V = np.concatenate(V)
    i = np.arange(sections, dtype=np.int64)
    inx = (i + 1) % sections
    rid = lambda p: 1 + p * sections          # first vertex of ring p
    F = [np.c_[np.zeros(sections, dtype=np.int64), rid(0) + inx, rid(0) + i]]
    for p in range(P_ - 1):
        a_, b_, c_, e_ = rid(p) + i, rid(p) + inx, rid(p + 1) + i, rid(p + 1) + inx
        F += [np.c_[a_, b_, c_], np.c_[b_, e_, c_]]
    top = len(V) - 1
    F.append(np.c_[np.full(sections, top, dtype=np.int64), rid(P_ - 1) + i, rid(P_ - 1) + inx])
    F = np.concatenate(F)
    if mesh_volume(V, F) < 0:
        F = F[:, ::-1].copy()
    return V, F


def mesh_volume(V, F):
    vol = 0.0
    for c in range(0, len(F), CHUNK):
        t = V[F[c:c + CHUNK]]
        vol += float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum())
    return vol / 6.0


def check_mesh(V, F):
    """Watertight, every edge used by exactly two faces with opposite directions (consistent winding), positive
    volume, no zero-area triangles. Edges are paired by sorting one 64-bit key per directed edge (smaller vertex
    id, larger vertex id, direction bit), built a chunk at a time so a 600k-triangle mesh stays light.
    -> dict (ok is True only when all pass)."""
    nF, n = len(F), len(V)
    keys = np.empty(3 * nF, np.int64)
    area_bad = 0
    vol = 0.0
    for c in range(0, nF, CHUNK):
        f = np.asarray(F[c:c + CHUNK], dtype=np.int64)
        for j, (p_, q_) in enumerate(((0, 1), (1, 2), (2, 0))):
            u, v = f[:, p_], f[:, q_]
            keys[j * nF + c:j * nF + c + len(f)] = (np.minimum(u, v) * n + np.maximum(u, v)) * 2 + (u > v)
        t = V[f]
        cr = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        area_bad += int((np.linalg.norm(cr, axis=1) < 2e-9).sum())
        vol += float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum())
    vol /= 6.0
    keys.sort()
    edge, d = keys >> 1, keys & 1
    starts = np.concatenate([[0], np.flatnonzero(edge[1:] != edge[:-1]) + 1])
    sizes = np.diff(np.concatenate([starts, [len(edge)]]))
    open_edges = int((sizes == 1).sum())
    pair = starts[sizes == 2]
    nonmanifold = int((sizes > 2).sum()) + int((d[pair] == d[pair + 1]).sum())      # shared by 3+ faces, or twice the same way
    ok = open_edges == 0 and nonmanifold == 0 and area_bad == 0 and vol > 0
    return {"ok": bool(ok), "watertight": open_edges == 0, "nonmanifold_edges": nonmanifold, "open_edges": open_edges,
            "degenerate": area_bad, "volume": vol, "triangles": int(nF),
            "bbox_min": V.min(0).tolist(), "bbox_max": V.max(0).tolist()}


def mesh_check_text(name, r):
    if r["ok"]:
        return "%s: watertight, every edge shared by two faces, volume %.1f cm3." % (name, r["volume"] / 1000.0)
    bits = []
    if r["open_edges"]:
        bits.append("%d open edges" % r["open_edges"])
    if r["nonmanifold_edges"]:
        bits.append("%d edges shared wrongly" % r["nonmanifold_edges"])
    if r["degenerate"]:
        bits.append("%d zero-size triangles" % r["degenerate"])
    if r["volume"] <= 0:
        bits.append("volume %.1f" % r["volume"])
    return "%s: the %s mesh failed its check (%s)." % ("R85", name, ", ".join(bits))


# ---------------------------------------------------------------- files (written in chunks: no big temporary copies)
_STL_DT = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])


def stl_bytes(V, F):
    """Binary STL, filled in place a chunk at a time (the roller's helper makes three full-size copies)."""
    n = len(F)
    buf = bytearray(84 + 50 * n)
    buf[:80] = b"pottery roller stamp".ljust(80, b" ")
    buf[80:84] = np.uint32(n).tobytes()
    rec = np.frombuffer(buf, _STL_DT, count=n, offset=84)
    for c in range(0, n, CHUNK):
        tri = V[F[c:c + CHUNK]].astype(np.float32)
        nm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        ln = np.linalg.norm(nm, axis=1, keepdims=True)
        rec["n"][c:c + len(tri)] = nm / np.where(ln > 0, ln, 1)
        rec["v"][c:c + len(tri)] = tri
    return buf


def _rows(arr, fmt):
    sio = io.StringIO()
    np.savetxt(sio, arr, fmt=fmt, newline="")
    return sio.getvalue().encode("ascii")


def threemf_bytes(parts):
    """Minimal 3MF (millimetres) streamed into the zip a chunk at a time: numpy formats each chunk, nothing is
    turned into Python lists and the whole model text never exists in memory. parts: [(name, V, F)]."""
    ct = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        with z.open("3D/3dmodel.model", "w") as f:
            f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
                    b'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources>')
            for i, (name, V, F) in enumerate(parts, 1):
                f.write(('<object id="%d" name="%s" type="model"><mesh><vertices>' % (i, name)).encode("ascii"))
                for c in range(0, len(V), CHUNK):
                    f.write(_rows(V[c:c + CHUNK], '<vertex x="%.4f" y="%.4f" z="%.4f"/>'))
                f.write(b"</vertices><triangles>")
                for c in range(0, len(F), CHUNK):
                    f.write(_rows(F[c:c + CHUNK], '<triangle v1="%d" v2="%d" v3="%d"/>'))
                f.write(b"</triangles></mesh></object>")
            f.write(b"</resources><build>")
            f.write("".join('<item objectid="%d"/>' % i for i in range(1, len(parts) + 1)).encode("ascii"))
            f.write(b"</build></model>")
    return bio.getvalue()


# ---------------------------------------------------------------- pictures
def clay_shade(Kc, d, pt, pz):
    """Gray relief shading of the clay picture (same light and tone as the roller's slab preview)."""
    gy, gx = np.gradient(Kc, pz, pt)
    nx, ny, nz = -gx, gy, np.ones_like(Kc)
    nn = np.sqrt(nx * nx + ny * ny + nz * nz)
    sh = (nx * -0.5 + ny * 0.6 + nz * 0.62) / nn
    return np.clip(205 - 55 * (Kc / max(d, 1e-6)) + 120 * (sh - 0.62), 0, 255).astype(np.uint8)


def _b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def clay_png(S, inside, d, pt, pz, round_):
    sh = clay_shade(S[:, ::-1], d, pt, pz)
    rgba = np.stack([sh, sh, sh, np.full_like(sh, 255)], axis=-1)
    if round_:
        rgba[~inside[:, ::-1], 3] = 0
    return ex.png_bytes(rgba)


# ---------------------------------------------------------------- analysis shared by preview and export
def face_only(sp, upload, name, pitch):
    f = build_face(sp, upload, name, pitch)
    S, Zm, dO, inside = compose(sp, f["S0"], f["pt"], f["pz"], f["P"])
    return dict(f, S=S, Zm=Zm, dO=dO, inside=inside)


def analyse(sp, upload, name, pitch):
    """The face at one pitch and every check measured on it."""
    t0 = time.time()
    r = face_only(sp, upload, name, pitch)
    t1 = time.time()
    P = r["P"]
    met = face_metrics(r["S"], r["inside"], r["dO"], r["pt"], r["pz"], sp.depth, P.nozzle)
    checks, share = make_checks(sp, P, r["pt"], r["pz"], r["S"], r["S0"], r["inside"], r["dO"], met)
    return dict(r, met=met, checks=checks, share=share, timings={"art": round(t1 - t0, 2), "checks": round(time.time() - t1, 2)})


_MEASURED = OrderedDict()


def measure(sp, upload, name):
    """R81-R84 for these settings, always at MEASURE_PITCH, whichever of preview or export asks (and the second
    ask for the same settings is free). One function, one grid: the two cannot disagree."""
    key = (json.dumps(sp.to_dict(), sort_keys=True, default=str), hashlib.sha1(upload).hexdigest() if upload else None)
    if key in _MEASURED:
        _MEASURED.move_to_end(key)
        return _MEASURED[key]
    r = analyse(sp, upload, name, MEASURE_PITCH)
    keep = {k: r[k] for k in ("checks", "share", "S", "S0", "inside", "pt", "pz", "met", "timings")}
    keep["art_report"] = {k: v for k, v in r["art_report"].items() if k in ("traced", "dropped_thin", "text", "sketch")}
    _MEASURED[key] = keep
    while len(_MEASURED) > 2:
        _MEASURED.popitem(last=False)
    return keep


def size_check(sp):
    w, h = sp.width_mm, sp.height_mm
    if SIZE_MIN <= w <= SIZE_MAX and SIZE_MIN <= h <= SIZE_MAX:
        return None
    return {"id": "R80", "level": "block", "text": "R80: The stamp face must be %g to %g mm each way. Yours is %s x %s mm." % (SIZE_MIN, SIZE_MAX, _mm(w), _mm(h))}


def est_triangles(sp, pitch):
    W, H = sp.width_mm, sp.height_mm
    if sp.shape == "round":
        return polar_tris(polar_rings(W / 2, H / 2, pitch)[1])
    N = max(12, int(round(W / pitch)))
    M = int(round(H / pitch)) + 1
    return 2 * N * (M - 1) + 2 * (N + M) * 3


def mesh_pitch(sp):
    """Export grid: max(0.2, longest side / 450) mm, coarsened until the face has no more triangles than the cap
    (250k round, 300k rectangle), so a 150 mm stamp stays a file a phone and a slicer can open."""
    p = max(0.2, max(sp.width_mm, sp.height_mm) / 450.0)
    cap = TRI_CAP_ROUND if sp.shape == "round" else TRI_CAP_RECT
    while est_triangles(sp, p) > cap:
        p *= 1.03
    return p


def _resolved(sp):
    d = sp.to_dict()
    d["base_mm"] = sp.base
    d["total_height_mm"] = round(sp.top_z, 2)
    if sp.knob_on:
        pad, grip = knob_dims(sp)
        d["knob"] = {"pad_mm": round(pad, 1), "grip_mm": round(grip, 1), "height_mm": KNOB_H}
    return d


def preview(params, upload=None, upload_name=None):
    """-> {params, size, checks, can_export, face (heightmap + clay shading as base64 uint8), timings}.
    A face outside R80's range returns the block and no picture. Any failure other than a StampError becomes the
    plain sentence (the cause stays chained for the console)."""
    try:
        return _preview(params, upload, upload_name)
    except StampError:
        raise
    except Exception as exc:
        raise StampError(FRIENDLY) from exc


def _preview(params, upload, upload_name):
    sp = StampParams.from_dict(params)
    bad = size_check(sp)
    size = {"w": sp.width_mm, "h": sp.height_mm, "shape": sp.shape, "base": sp.base, "top_z": round(sp.top_z, 2),
            "tris": 0, "knob": None}
    if bad:
        return {"params": _resolved(sp), "size": size, "checks": [bad], "can_export": False, "face": None, "timings": {}}
    r = measure(sp, upload, upload_name)
    S, d = r["S"], sp.depth
    step = max(1, int(math.ceil(max(S.shape) / 320.0)))          # the picture is at most about 320 pixels a side
    Ss = S[::step, ::step]
    pad, grip = knob_dims(sp)
    size["tris"] = est_triangles(sp, mesh_pitch(sp))
    size["knob"] = {"pad": round(pad, 1), "grip": round(grip, 1), "height": KNOB_H} if sp.knob_on else None
    checks = list(r["checks"])
    checks.append({"id": "R85", "level": "pass", "text": "R85: The 3D mesh is checked (watertight, every edge shared by two faces, volume) when you download."})
    face = {"cols": int(Ss.shape[1]), "rows": int(Ss.shape[0]), "pitch_x": r["pt"] * step, "pitch_y": r["pz"] * step,
            "face_b64": _b64(np.clip(np.round(Ss / d * 255.0), 0, 255).astype(np.uint8)),
            "clay_b64": _b64(clay_shade(Ss[:, ::-1], d, r["pt"] * step, r["pz"] * step))}
    return {"params": _resolved(sp), "size": size, "checks": checks,
            "can_export": not any(c["level"] == "block" for c in checks), "face": face,
            "art_report": r["art_report"], "timings": dict(r["timings"], pitch_mm=MEASURE_PITCH)}


# ---------------------------------------------------------------- export
def _sheet(sp, checks, files, tris, knob):
    lines = ["# Stamp sheet", "",
             "Face %s x %s mm, %s. Relief %g mm, draft %g deg, edge round %g mm." % (
                 _mm(sp.width_mm), _mm(sp.height_mm), "round (oval when the sides differ)" if sp.shape == "round" else "square / rectangle",
                 sp.depth, sp.draft_deg, sp.edge_round),
             "Border rim: %s. Block under the relief %g mm (%s). Total height %g mm." % (
                 ("on, %g mm wide" % sp.rim_mm) if sp.rim_on else "off", sp.base,
                 "with knob" if sp.knob_on else "no knob, gripped by the edges", sp.top_z),
             "Art: %s%s. Text: %s." % (sp.art.get("art_source", "pattern:waves"), " (%s)" % sp.art.get("art_style", "trace") if sp.is_upload else "",
                                       repr(sp.art.get("text")) if (sp.art.get("text") or "").strip() else "none"),
             "The face is the mirror of what you see in the clay: words print backwards on the stamp and read right in the clay (R35).", ""]
    if knob:
        lines += ["Knob: glue pad %g mm, grip %g mm, %g mm tall." % (knob[0], knob[1], KNOB_H), ""]
    lines += ["## Print notes", "",
              "- Stamp face up on the bed, no supports, 0.2 mm layers, 0.4 mm nozzle.",
              "- Knob standing on its flat pad, no supports." if knob else "- No knob: the thick block is held by its edges.",
              "- Glue the knob pad centred on the back of the stamp with CA glue or epoxy." if knob else "- Check the back is flat before you stamp.",
              "- Triangles in stamp.stl: %s." % format(tris, ","), "",
              "## Using it", "",
              "- Dust the face with cornstarch. Press straight down, once, do not rock or twist (R49).",
              "- Use a slab at least %g mm thick (R48)." % max(6.0, 2 * sp.depth + 3), "",
              "## Checks", "", "| Rule | Result | Note |", "|---|---|---|"]
    for c in checks:
        lines.append("| %s | %s | %s |" % (c["id"], {"pass": "ok", "warn": "WARN", "block": "BLOCK"}[c["level"]], c["text"].replace("|", "/")))
    lines += ["", "## Files", ""] + ["- " + f for f in files] + [""]
    return "\n".join(lines)


def filename(sp):
    return "stamp-%s-%dx%d.zip" % (sp.shape, int(round(sp.width_mm)), int(round(sp.height_mm)))


def _blocked(sp, checks, name=None):
    return {"zip": b"", "blocked": True, "checks": checks, "filename": name or filename(sp), "files": [], "bytes": 0}


def export_bytes(params, upload=None, upload_name=None, _checks_only=False):
    """-> {zip, blocked, checks, filename, files, bytes, triangles, seconds}. A blocked export returns no files.
    Anything that goes wrong comes back as a blocked export with a plain sentence, never as an exception.
    _checks_only stops after R80-R84 (the part the preview shares), for tests."""
    t0 = time.time()
    try:
        sp = StampParams.from_dict(params)
    except StampError as exc:
        return {"zip": b"", "blocked": True, "checks": [{"id": "R80", "level": "block", "text": str(exc)}], "filename": "stamp.zip", "files": [], "bytes": 0}
    bad = size_check(sp)
    if bad:
        return _blocked(sp, [bad])
    try:
        r = measure(sp, upload, upload_name)
        checks = list(r["checks"])
        if any(c["level"] == "block" for c in checks):
            return _blocked(sp, checks)
        if _checks_only:
            return {"zip": b"", "blocked": False, "checks": checks, "filename": filename(sp), "files": [], "bytes": 0}
        W, H = sp.width_mm, sp.height_mm
        pitch = mesh_pitch(sp)
        m = face_only(sp, upload, upload_name, pitch)
        if sp.shape == "round":
            V, F = polar_mesh(m["Zm"], m["pt"], m["pz"], W, H, sp.base, pitch)
        else:
            V, F = rect_mesh(m["Zm"], m["pt"], m["pz"], sp.base)
        F = F.astype(np.int32)
        if mesh_volume(V, F) < 0:
            F = F[:, ::-1].copy()
        parts = [("stamp", V, F, check_mesh(V, F))]
        knob = None
        if sp.knob_on:
            pad, grip = knob_dims(sp)
            kV, kF = knob_mesh(pad, grip)
            parts.append(("knob", kV, kF, check_mesh(kV, kF)))
            knob = (pad, grip)
        failed = [(n, c) for n, _v, _f, c in parts if not c["ok"]]
        if failed:
            for n, c in failed:
                checks.append({"id": "R85", "level": "block", "text": mesh_check_text(n, c)})
            return _blocked(sp, checks)
        checks.append({"id": "R85", "level": "pass", "text": "R85: " + "; ".join("%s mesh is watertight, every edge shared by two faces, volume %.1f cm3" % (n, c["volume"] / 1000.0) for n, _v, _f, c in parts) + "."})
        files = {"stamp.stl": stl_bytes(V, F)}
        plated = [("stamp", V, F)]
        if knob:
            files["knob.stl"] = stl_bytes(parts[1][1], parts[1][2])
            off = np.array([W + 10.0 + max(knob) / 2.0, H / 2.0, 0.0])      # side by side, 10 mm clear of the widest part
            plated.append(("knob", parts[1][1] + off, parts[1][2]))
        files["stamp.3mf"] = threemf_bytes(plated)
        del plated
        files["clay_preview.png"] = clay_png(m["S"], m["inside"], sp.depth, m["pt"], m["pz"], sp.shape == "round")
        names = list(files) + ["sheet.md"]
        files["sheet.md"] = _sheet(sp, checks, names, len(F), knob).encode("utf-8")
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as z:
            for k in list(files):
                z.writestr(k, files[k])
        n_tri, stl_len = int(len(F)), len(files["stamp.stl"])
        del files, parts, V, F
        return {"zip": bio.getvalue(), "blocked": False, "checks": checks, "filename": filename(sp), "files": names,
                "bytes": stl_len, "triangles": n_tri, "seconds": round(time.time() - t0, 2)}
    except StampError as exc:
        return _blocked(sp, [{"id": "R80", "level": "block", "text": str(exc)}])
    except Exception as exc:
        import sys
        print("stamp export error: %r" % (exc,), file=sys.stderr)
        return _blocked(sp, [{"id": "R80", "level": "block", "text": FRIENDLY}])
