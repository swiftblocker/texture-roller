"""Tiling layout: clay-view art mask on the oversampled (theta, z) grid.

Conventions (SPEC): H[row=z index, col=theta index]; theta = 2*pi*col/N; seam at col 0 (welded).
D = art as drawn (clay view, mirror ON). H = D reversed in columns when mirror is ON (col j <- D col (N-j)%N),
H = D when mirror is OFF. The clay always receives K[i] = H[(N-i)%N], so mirror ON gives K = D and
mirror OFF gives the left-right flipped art.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
import numpy as np
from . import art as artmod

OS = 2  # oversample of the grid used for distance transforms


def grid_dims(P, pitch):
    C = P.C
    n = P.n_int
    k = max(1, int(round(C / (n * pitch))))
    N = n * max(k, int(math.ceil(12 / n)))
    M = int(round(P.length / pitch)) + 1
    if P.split and (M - 1) % 2:
        M += 1
    M = max(M, 3)
    return N, M, C / N, P.length / (M - 1)


@dataclass
class Layout:
    N: int
    M: int
    pt: float
    pz: float
    os: int
    top_os: np.ndarray            # (M2,N2) bool, mirrored, ready for EDT
    drawn_top: np.ndarray         # (M2,N2) bool, as drawn (clay view)
    band_rows: np.ndarray         # (M2,) bool
    cell_w: float
    tile_h: float
    n_along: float
    art_axial: float
    wrap_width: float
    stretch_error: float
    method_used: str
    phase_mm: float
    seam_theta_used: float
    seam_mismatch: float          # mean fraction of art rows where the seam columns differ
    bg_edge_fraction: float
    blend_half: float
    flags: dict = field(default_factory=dict)
    art_report: dict = field(default_factory=dict)
    text_os: object = None        # (M2,N2) bool, text letters + frame, same orientation as top_os


def _lattice_dist(x, phase, cell):
    return np.abs(((x - phase + cell / 2) % cell) - cell / 2)


def build(P, art, pitch, os=OS) -> Layout:
    N, M, pt, pz = grid_dims(P, pitch)
    C, L, n = P.C, P.length, P.n_int
    cell_w = C / n
    tw = P.tile_width_mm or cell_w
    rot = P.rotation if P.rotation in (0, 90, 180, 270) else int(round(P.rotation / 90.0)) * 90 % 360
    a = art.rotated(rot)
    fx0, fy0, fx1, fy1 = a.frame
    fw, fh = fx1 - fx0, fy1 - fy0
    sp = max(0.0, P.spacing)
    sp = min(sp, 0.8 * min(cell_w, tw))
    sx = max(cell_w - sp, 1e-6) / fw
    sy = max(tw - sp, 1e-6) / fw
    art_h = fh * sy
    tile_h = art_h + sp
    band = P.band_eff
    Aav = max(L - 2 * band, 1e-6)
    if P.n_along:
        n_along = float(P.n_along)
        Aext = n_along * tile_h
        y0 = band + (Aav - Aext) / 2.0
        if Aext > Aav:
            y0 = band
    else:
        n_along = Aav / tile_h
        Aext = Aav
        y0 = band
    # tile raster
    ps = max(pitch / os / 2.0, math.sqrt(cell_w * tile_h / 14e6))
    nx = max(2, int(round(cell_w / ps)))
    ny = max(2, int(round(tile_h / ps)))
    polys, rep = a.flatten((sx + sy) / 2.0)
    tile = artmod.raster_polys(polys, sx, sy, fx0, fy0, sp / 2.0, sp / 2.0, ny, nx, (cell_w / nx, tile_h / ny))
    N2, M2 = N * os, (M - 1) * os + 1
    x2 = np.arange(N2) * (C / N2)
    z2 = np.arange(M2) * (L / (M2 - 1))
    band_rows = (z2 < band - 1e-9) | (z2 > L - band + 1e-9) if P.bands_on else np.zeros(M2, bool)
    brick = P.offset == "brick"
    hdrop = P.offset == "half_drop"
    f = P.offset_fraction

    def make_f(phase):
        xl = x2[None, :] - phase
        zl = (z2 - y0)[:, None]
        if brick:
            r = np.floor(zl / tile_h)
            xl = xl - (r % 2) * f * cell_w
            u = (xl / cell_w) % 1.0
            v = (zl / tile_h) % 1.0 + 0 * u
        elif hdrop:
            kcol = np.floor(xl / cell_w)
            u = (xl / cell_w) % 1.0
            v = ((zl - (kcol % 2) * f * tile_h) / tile_h) % 1.0
        else:
            u = (xl / cell_w) % 1.0 + 0 * zl
            v = (zl / tile_h) % 1.0 + 0 * xl
        tx = np.minimum((u * nx).astype(np.int32), nx - 1)
        ty = np.minimum((v * ny).astype(np.int32), ny - 1)
        ff = tile[ty, tx]
        valid = ((z2 >= y0 - 1e-9) & (z2 <= y0 + Aext + 1e-9))[:, None]
        return ff & valid

    def finish(ff, gutter_phase=None):
        ff = ff.copy()
        if gutter_phase is not None:
            g = 2.0
            ff[:, _lattice_dist(x2, gutter_phase, cell_w) < g / 2] = False
        top = ~ff if P.invert else ff
        top[band_rows, :] = True
        return ff, top

    art_rows = ~band_rows

    def stats(ff, top):
        e0, e1 = ff[art_rows, 0], ff[art_rows, -1]
        mism = float(np.mean(e0 != e1)) if art_rows.any() else 0.0
        bgf = float(min(1 - e0.mean(), 1 - e1.mean())) if art_rows.any() else 1.0
        return mism, bgf

    method = P.seam_method
    phase = 0.0
    if P.seam_theta_deg is not None:
        phase = (P.seam_theta_deg / 360.0 * C) % C
    ff0 = make_f(phase)
    ff, top = finish(ff0)
    mism, bgf = stats(ff, top)
    used = method
    gutter_phase = None
    blend_half = 0.0
    tol = 0.05 / max(P.depth, 1e-6)

    def bg_phase(ffx):
        col = ffx[art_rows].mean(axis=0) if art_rows.any() else np.zeros(N2)
        w = max(1, int(round(1.0 / (C / N2))))
        k = np.ones(w) / w
        padc = np.concatenate([col[-w:], col, col[:w]])
        sm = np.convolve(padc, k, mode="same")[w:-w]
        return -x2[int(np.argmin(sm))]

    if method == "auto":
        if mism <= tol:
            used = "tile"
        else:
            ph = bg_phase(ff0) if P.seam_theta_deg is None else phase
            ffb = make_f(ph)
            ffb2, topb = finish(ffb)
            m2, b2 = stats(ffb2, topb)
            if b2 >= 0.9 and m2 <= tol:
                used, phase, ff, top, mism, bgf = "background", ph, ffb2, topb, m2, b2
            else:
                used = "blend"
    elif method == "background":
        if P.seam_theta_deg is None:
            phase = bg_phase(ff0)
        ff0 = make_f(phase)
        ff, top = finish(ff0)
        mism, bgf = stats(ff, top)
    if used == "gutter":
        gutter_phase = phase
        ff, top = finish(ff0, gutter_phase)
        mism, bgf = stats(ff, top)
        mism = 0.0
    if used == "blend":
        blend_half = min(P.seam_blend_pct / 100.0 * C / 2.0, 0.45 * cell_w)
        mism = 0.0

    text_mask, text_rep = None, None
    if (P.text or "").strip():
        from . import text as textmod
        top, text_mask, text_rep = textmod.apply(P, top, C, L, band_rows, phase, cell_w)
    drawn = top
    idx = (-np.arange(N2)) % N2
    top_os = drawn[:, idx] if P.mirror else drawn
    text_os = None if text_mask is None else (text_mask[:, idx] if P.mirror else text_mask)
    rep = dict(rep)
    rep["traced"] = bool(art.traced)
    rep["dropped_thin"] = 0
    if text_rep:
        rep["text"] = text_rep
    return Layout(
        N=N, M=M, pt=pt, pz=pz, os=os, top_os=np.ascontiguousarray(top_os), drawn_top=drawn,
        band_rows=band_rows, cell_w=cell_w, tile_h=tile_h, n_along=n_along,
        art_axial=Aext, wrap_width=n * tw, stretch_error=abs(n * tw - C) / C,
        method_used=used, phase_mm=phase, seam_theta_used=float((phase % C) / C * 360.0),
        seam_mismatch=mism, bg_edge_fraction=bgf, blend_half=blend_half,
        flags={"rotation_snapped": rot != P.rotation, "odd_half_drop": hdrop and n % 2 == 1,
               "y0": y0, "invert": P.invert},
        art_report=rep, text_os=text_os,
    )
