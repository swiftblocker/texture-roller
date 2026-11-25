"""Mask -> height field H (mm above the bottom level), feature metrics.

Method (documented per R19-R24):
 1. Signed distance s (mm, + inside the raised art) from the Euclidean distance transform of the mask,
    computed on a 2x oversampled grid with wrap-around padding in theta, boundary at the pixel edge
    (distance - half pixel).
 2. H = profile(s). The profile is one analytic cross-section: flat top at d, a straight sidewall whose
    run is d*tan(draft) (a real slope at the draft angle from radial), flat bottom at 0, and circular
    fillets of radius edge_round at BOTH corners (top edge and groove bottom, a rolling-ball round).
 3. H is sampled at the vertex grid (every 2nd oversampled sample), then optional blend / alignment ticks.
Widths: raised = {H >= 0.75 d}; recess = {H < 0.5 d}; gap = {H < 0.75 d}. Width = 2 x EDT on the skeleton
minus one pixel; the 2nd percentile ignores pixel noise; skeleton pixels within 2 mm of a stroke end
(sharp tips) are ignored; whole components thinner than 2 x nozzle are counted as thin (R26).
"""
from __future__ import annotations
import math
import numpy as np
from scipy import ndimage as ndi
from skimage.morphology import skeletonize


def profile_lut(d, draft_deg, rho):
    draft = min(max(draft_deg, 0.5), 80.0)
    run = d * math.tan(math.radians(draft))
    alpha = math.atan2(d, run)
    ln = math.hypot(run, d)
    rho = max(0.0, rho)
    ta = math.tan(alpha / 2)
    if rho > 0 and ta > 1e-9:
        rho = min(rho, 0.499 * ln / ta)
    T = rho * ta
    ca, sa = math.cos(alpha), math.sin(alpha)
    smin, smax = -run - T - 1e-3, T + 1e-3
    s = np.linspace(smin, smax, 6001)
    h = np.zeros_like(s)
    h[s >= T] = d
    m = (s >= -T * ca) & (s < T)
    if rho > 0:
        h[m] = (d - rho) + np.sqrt(np.clip(rho ** 2 - (s[m] - T) ** 2, 0, None))
    m = (s >= -run + T * ca) & (s < -T * ca)
    h[m] = d + s[m] * (d / max(run, 1e-9))
    m = (s >= -run - T) & (s < -run + T * ca)
    if rho > 0:
        h[m] = rho - np.sqrt(np.clip(rho ** 2 - (s[m] - (-run - T)) ** 2, 0, None))
    h = np.clip(h, 0, d)
    return s, h, run


def signed_distance(top_os, pz_os, pt_os, pad_mm=10.0):
    M2, N2 = top_os.shape
    pad = int(min(N2 // 2, math.ceil(pad_mm / pt_os)))
    t = np.pad(top_os, ((0, 0), (pad, pad)), mode="wrap") if pad else top_os
    if t.all():
        return np.full(top_os.shape, 1e3)
    if not t.any():
        return np.full(top_os.shape, -1e3)
    po = 0.5 * (pz_os + pt_os)
    din = ndi.distance_transform_edt(t, sampling=(pz_os, pt_os))
    dout = ndi.distance_transform_edt(~t, sampling=(pz_os, pt_os))
    s = np.where(t, din - 0.5 * po, -(dout - 0.5 * po))
    return s[:, pad:pad + N2] if pad else s


def height_field(P, lay, s=None):
    d = P.depth
    os = lay.os
    pz_os, pt_os = lay.pz / os, lay.pt / os
    if s is None:
        s = signed_distance(lay.top_os, pz_os, pt_os)
    sl, hl, run = profile_lut(d, P.draft_deg, P.edge_round)
    H2 = np.interp(s, sl, hl)
    H = np.ascontiguousarray(H2[::os, ::os])
    M, N = lay.M, lay.N
    z = np.arange(M) * lay.pz
    x = np.arange(N) * lay.pt
    bandrow = (z < P.band_eff - 1e-9) | (z > P.length - P.band_eff + 1e-9) if P.bands_on else np.zeros(M, bool)
    if lay.blend_half > 0:
        cell = lay.cell_w
        ph = -lay.phase_mm if P.mirror else lay.phase_mm
        dist = np.abs(((x - ph + cell / 2) % cell) - cell / 2)
        w = np.clip(dist / lay.blend_half, 0, 1)
        w = w * w * (3 - 2 * w)
        if lay.text_os is not None:
            # protect the letters and their sloped sides (draft + edge round) from the blend
            k = int(math.ceil((d * math.tan(math.radians(P.draft_deg)) + P.edge_round + 0.3) / pt_os))
            tm = np.pad(lay.text_os, ((0, 0), (k, k)), mode="wrap")
            tm = ndi.binary_dilation(tm, iterations=k)[:, k:-k]
            w = np.where(tm[::os, ::os], 1.0, w[None, :])
        else:
            w = w[None, :]
        hbg = d if P.invert else 0.0
        art = ~bandrow
        H[art] = hbg + (np.broadcast_to(w, H.shape)[art]) * (H[art] - hbg)
    if P.alignment_ticks and P.bands_on:
        xx = np.minimum(x, P.C - x)
        v = np.clip(1 - xx / 0.5, 0, 1)
        notch = d - 0.8 * v
        sel = (z < P.band_eff) | (z > P.length - P.band_eff)
        H[sel] = np.minimum(H[sel], np.where(v > 0, notch, d)[None, :])
    return np.clip(H, 0, d)


def radius_map(P, H, lay):
    """Outer radius per vertex incl. end chamfers (chamfer only at the true roller ends)."""
    R, d, c, L = P.R, P.depth, P.end_chamfer, P.length
    r = R - d + H
    if c > 0:
        z = (np.arange(lay.M) * lay.pz)[:, None]
        r = np.minimum(r, R - c + z)
        r = np.minimum(r, R - c + (L - z))
    return r


# ---------------------------------------------------------------- metrics
def _label_wrapped(mask):
    """ndi.label, but a piece crossing the seam (last column -> column 0) is one piece, not two
    thin halves (which would read as a false R19b / R26)."""
    lab, n = ndi.label(mask)
    if n == 0:
        return lab, n
    parent = np.arange(n + 1)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    a, b = lab[:, -1], lab[:, 0]
    both = (a > 0) & (b > 0)
    for x, y in set(zip(a[both].tolist(), b[both].tolist())):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)
    roots = np.array([find(i) for i in range(n + 1)])
    uniq, inv = np.unique(roots, return_inverse=True)
    return inv[lab].astype(lab.dtype), len(uniq) - 1


def _widths(mask, pt, pz, nozzle, pad=24):
    """-> (skeleton p2 width or inf, min component max-width or inf, thin component count)."""
    if not mask.any():
        return math.inf, math.inf, 0
    N = mask.shape[1]
    pad = min(pad, N // 2)
    mp = np.pad(mask, ((0, 0), (pad, pad)), mode="wrap")
    edt = ndi.distance_transform_edt(mp, sampling=(pz, pt))
    pm = 0.5 * (pt + pz)
    sk = skeletonize(mp)
    nb = ndi.convolve(sk.astype(np.uint8), np.ones((3, 3), np.uint8), mode="constant")
    ends = sk & (nb <= 2)
    ok = sk.copy()
    if ends.any():
        de = ndi.distance_transform_edt(~ends, sampling=(pz, pt))
        ok &= de > max(2.0, 3 * pm)
    cs = slice(pad, pad + N)
    vals = (2 * edt - pm)[:, cs][ok[:, cs]]
    if vals.size == 0:
        vals = (2 * edt - pm)[:, cs][sk[:, cs]]
    p2 = float(np.percentile(vals, 2)) if vals.size else math.inf
    lab, n = _label_wrapped(mask)
    if n:
        ix = np.arange(1, n + 1)
        mx = ndi.maximum(edt[:, cs], lab, index=ix)
        area = np.asarray(ndi.sum(np.ones_like(lab), lab, index=ix)) * pt * pz
        big = area >= 1.0  # specks under 1 mm2 (sampling debris at sharp tips) are ignored
        cw = (2 * np.asarray(mx) - pm)[big]
        if cw.size == 0:
            return p2, math.inf, 0
        thin = int(np.sum(cw < 2 * nozzle))
        cmin = float(cw.min())
    else:
        thin, cmin = 0, math.inf
    return p2, cmin, thin


def metrics(P, H, lay):
    d = P.depth
    pt, pz = lay.pt, lay.pz
    out = {}
    rp2, rc, thin = _widths(H >= 0.75 * d, pt, pz, P.nozzle)
    out["min_raised_width"] = min(rp2, rc)
    out["thin_components"] = thin
    out["min_recess_width"] = _widths(H < 0.5 * d, pt, pz, P.nozzle)[0]
    out["min_gap"] = _widths(H < 0.75 * d, pt, pz, P.nozzle)[0]
    gz = np.gradient(H, pz, axis=0)
    gt = (np.roll(H, -1, 1) - np.roll(H, 1, 1)) / (2 * pt)
    g = np.hypot(gz, gt)
    sel = g[g > 0.05]
    if sel.size > 20:
        out["min_draft_deg"] = float(math.degrees(math.atan(1.0 / float(np.percentile(sel, 99.0)))))
    else:
        out["min_draft_deg"] = None
    out["raised_fraction"] = float((H >= 0.9 * d).mean())
    out["seam_edge_diff"] = float(lay.seam_mismatch * d)
    out["area_factor"] = float(np.sqrt(1 + g * g).mean())
    out["Hmin"], out["Hmax"] = float(H.min()), float(H.max())
    for k in ("min_raised_width", "min_recess_width", "min_gap"):
        if out[k] == math.inf:
            out[k] = None
    return out
