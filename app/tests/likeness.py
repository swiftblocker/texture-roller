"""Squint score: does the sketch put its ink where the photo is dark? (realism.md s15)

Helper only; no photo inside. Takes a Sketch from engine.sketch.make_sketch (crop_rgb + mask + subject mask
in layers['mask'], needs debug=True) or the three arrays directly.
"""
import numpy as np
from scipy import ndimage as ndi


def _L(rgb):
    c = rgb.astype(np.float32) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    Y = lin @ np.array([0.2126729, 0.7151522, 0.0721750], np.float32)
    f = np.where(Y > 0.008856, np.cbrt(Y), 7.787 * Y + 16.0 / 116.0)
    return (116.0 * f - 16.0) / 100.0


def _nblur(a, m, s):
    mf = m.astype(np.float32)
    num = ndi.gaussian_filter(a * mf, s, mode="nearest")
    den = ndi.gaussian_filter(mf, s, mode="nearest")
    return num / np.maximum(den, 1e-4)


def _pearson(a, b):
    if a.size < 10 or a.std() < 1e-6 or b.std() < 1e-6:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def squint_fields(crop_rgb, ink, subject, ppm, sigma_mm=3.0):
    s = sigma_mm * ppm
    dark_photo = 1.0 - _L(crop_rgb)            # photo darkness
    dens = ink.astype(np.float32)               # ink density = 1 - paper
    return _nblur(dark_photo, subject, s), _nblur(dens, subject, s)


def squint_score(crop_rgb, ink, subject, ppm, face_box=None, sigma_mm=3.0):
    """-> {'score': pearson inside subject, 'zones': 4x3 list of per-zone pearson (rows x cols) over the face box}."""
    a, b = squint_fields(crop_rgb, ink, subject, ppm, sigma_mm)
    out = {"score": _pearson(a[subject], b[subject])}
    if face_box is not None:
        bx, by, bw, bh = face_box
        # head only: neck and suit below the chin fade out by design (collar never draws), so the head score
        # stops 0.2 face heights below the chin box
        head = subject.copy()
        head[int(by + 1.2 * bh):] = False
        out["score_head"] = _pearson(a[head], b[head])
        zones = []
        for r in range(4):
            row = []
            for c in range(3):
                y0, y1 = int(by + bh * r / 4), int(by + bh * (r + 1) / 4)
                x0, x1 = int(bx + bw * c / 3), int(bx + bw * (c + 1) / 3)
                m = np.zeros(subject.shape, bool)
                m[max(0, y0):y1, max(0, x0):x1] = True
                m &= subject
                row.append(round(_pearson(a[m], b[m]), 3) if m.sum() > 50 else None)
            zones.append(row)
        out["zones"] = zones
    return out


def of_sketch(sk, sigma_mm=3.0):
    return squint_score(sk.crop_rgb, sk.mask, sk.layers["mask"], sk.ppm, sk.face_box, sigma_mm)
