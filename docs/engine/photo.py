"""Photo -> clean line drawing for the cookie cutter (the drawing then goes through the normal cutter engine).

A photo must never go through "Otsu + potrace" (that traces the biggest dark patch, which is shadow or table, not
the subject). Route, tried in this order:
  head    a Haar frontal face was found: grabCut seeded from the face box -> head-shaped cookie
  subject no face: grabCut with a centre prior -> cookie shaped like the main subject
  plaque  the mask failed the gate (area, solidity, aspect, neck, edge contrast): a plain round
Inside lines are the strongest blurred Canny edges (min 6 mm long, 3.5 mm apart, at most 14). A plaque with fewer
than 6 lines, or too little line length, is refused. The result is a black-on-white picture of the outline plus the
lines (8 px/mm at most), which the existing drawing engine turns into ribs and mesh.

Everything is numpy / scipy / skimage / cv2 (cv2 only inside make_cutter_drawing; analyze needs no cv2). No shapely.
"""
from __future__ import annotations
import io
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi

CASCADES = Path(__file__).resolve().parent / "data" / "cascades"
WORK = 360            # px on the long side while segmenting
MAX_LINES = 14
MIN_LINE_MM = 6.0
LINE_GAP_MM = 3.5
EDGE_MM = 3.5
REFUSE = ("We could not find a clear subject in this photo. Use a photo with one subject on a plain background, "
          "or upload a drawing.")
MSG = {"head": "Photo: we found a face and made a head-shaped cookie",
       "subject": "Photo: we found the main subject and cut around it",
       "plaque": "Photo: round cookie with the main lines"}


class NeedsCv(Exception):
    """OpenCV is not loaded (in the browser the worker loads it on demand and retries)."""


class PhotoRefused(Exception):
    pass


# ---------------------------------------------------------------- is it a photo?
def _open(upload: bytes):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(upload)))
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg
    return im.convert("RGB")


def analyze(upload: bytes) -> dict:
    """Cheap photo test, no cv2. Photo = mid-tone share over 0.30 AND over 40 distinct grey levels (each holding
    more than 0.5 % of the pixels, after a 3 px median). Flat-colour logos have under 12; SVG is never a photo."""
    out = {"is_photo": False, "midtone": 0.0, "levels": 0}
    head = upload[:512].lstrip().lower()
    if head.startswith(b"<?xml") or b"<svg" in head:
        return out
    try:
        im = _open(upload)
    except Exception:
        return out
    k = 200.0 / max(im.size)
    if k < 1:
        im = im.resize((max(1, int(im.size[0] * k)), max(1, int(im.size[1] * k))))
    g = np.asarray(im.convert("L"))
    mid = float(((g > 45) & (g < 210)).mean())
    med = ndi.median_filter(g, size=3)
    levels = int((np.bincount(med.ravel(), minlength=256) > 0.005 * med.size).sum())
    out.update(midtone=round(mid, 3), levels=levels, is_photo=bool(mid > 0.30 and levels > 40))
    return out


# ---------------------------------------------------------------- mask finding
def _biggest(m):
    lab, n = ndi.label(m)
    if not n:
        return m
    return lab == 1 + int(np.argmax(np.bincount(lab.ravel())[1:]))


def _smooth(cv2, m, r):
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, k)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
    m = ndi.binary_fill_holes(_biggest(m > 0))
    b = cv2.GaussianBlur(m.astype(np.float32), (0, 0), r * 0.8)
    return _biggest(b > 0.5)


def _skin_frac(rgb, x, y, w):
    c = rgb[int(y + 0.25 * w):int(y + 0.75 * w), int(x + 0.25 * w):int(x + 0.75 * w)].astype(float) / 255
    if c.size == 0:
        return 0.0
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    return float(((r > 0.35) & (r - b > 0.08) & (r >= g) & (r - g < 0.35)).mean())


def find_face(cv2, rgb):
    """Biggest frontal Haar face (min side 12 % of the short edge, looks like skin) or None."""
    g = cv2.equalizeHist(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))
    c = cv2.CascadeClassifier(str(CASCADES / "haarcascade_frontalface_default.xml"))
    if c.empty():
        return None
    mn = int(0.12 * min(g.shape))
    f = c.detectMultiScale(g, 1.1, 6, minSize=(mn, mn))
    f = [r for r in f if _skin_frac(rgb, r[0], r[1], r[2]) > 0.3]
    return max(f, key=lambda r: r[2] * r[3]) if len(f) else None


def _grab(cv2, rgb, fc):
    h, w = rgb.shape[:2]
    mk = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    if fc is not None:                       # head + neck
        x, y, fw, fh = [int(v) for v in fc]
        cx, cy = x + fw // 2, y + fh // 2
        cv2.ellipse(mk, (cx, cy - int(.1 * fh)), (int(.85 * fw), int(1.05 * fh)), 0, 0, 360, cv2.GC_PR_FGD, -1)
        cv2.ellipse(mk, (cx, cy), (int(.38 * fw), int(.5 * fh)), 0, 0, 360, cv2.GC_FGD, -1)
        out = np.ones((h, w), np.uint8)
        cv2.ellipse(out, (cx, cy - int(.1 * fh)), (int(1.25 * fw), int(1.45 * fh)), 0, 0, 360, 0, -1)
        mk[out > 0] = cv2.GC_BGD
    else:                                    # centre prior: border is background, middle is probably subject
        b = max(3, int(.03 * min(h, w)))
        cv2.ellipse(mk, (w // 2, h // 2), (int(.40 * w), int(.42 * h)), 0, 0, 360, cv2.GC_PR_FGD, -1)
        mk[:b] = mk[-b:] = cv2.GC_BGD
        mk[:, :b] = mk[:, -b:] = cv2.GC_BGD
    cv2.grabCut(np.ascontiguousarray(rgb[:, :, ::-1]), mk, None, np.zeros((1, 65)), np.zeros((1, 65)), 6, cv2.GC_INIT_WITH_MASK)
    return (mk == cv2.GC_FGD) | (mk == cv2.GC_PR_FGD)


def _hull_area(m):
    from skimage.morphology import convex_hull_image
    ys, xs = np.nonzero(m)
    sub = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return int(convex_hull_image(sub).sum())


def gate(cv2, m, rgb, is_face, size_mm):
    """Is this mask a cookie shape? -> (ok, numbers)."""
    if not m.any():
        return False, dict(area=0.0)
    area = float(m.mean())
    solidity = float(m.sum() / max(_hull_area(m), 1))
    ys, xs = np.nonzero(m)
    bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    aspect = float(max(bw, bh) / max(min(bw, bh), 1))
    r = max(1, int(3.0 * max(bw, bh) / size_mm))                 # 3 mm radius at cookie scale
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    kept = float(cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, k).sum() / max(m.sum(), 1))
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    ring_in = m & ~ndi.binary_erosion(m, iterations=4)
    ring_out = ndi.binary_dilation(m, iterations=4) & ~m
    contrast = float(np.linalg.norm(lab[ring_in].mean(0) - lab[ring_out].mean(0))) if ring_in.any() and ring_out.any() else 0.0
    ok = ((0.03 if is_face else 0.10) <= area <= 0.80 and solidity >= 0.72 and aspect <= 2.2 and kept >= 0.90
          and contrast >= 18.0)
    return bool(ok), dict(area=round(area, 3), solidity=round(solidity, 2), aspect=round(aspect, 2),
                          kept_after_6mm_opening=round(kept, 2), edge_contrast=round(contrast, 1))


def _plaque(cv2, h, w):
    m = np.zeros((h, w), np.uint8)
    s = min(h, w)
    cv2.ellipse(m, (w // 2, h // 2), (int(.47 * s), int(.47 * s)), 0, 0, 360, 1, -1)
    return m > 0


# ---------------------------------------------------------------- inside lines
def inside_lines(cv2, rgb, S, ppm, max_lines=MAX_LINES, min_len_mm=MIN_LINE_MM, gap_mm=LINE_GAP_MM, edge_mm=EDGE_MM):
    """A few strong lines, spaced so dough survives between them -> (mask of the lines, list of strokes)."""
    from skimage.morphology import skeletonize
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    g = cv2.bilateralFilter(g, 9, 50, 7)
    g = cv2.GaussianBlur(g, (0, 0), 0.6 * ppm)             # 0.6 mm blur: fur, wood grain, stars go away
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag = np.hypot(gx, gy)
    inner = ndi.binary_erosion(S, iterations=max(1, int(edge_mm * ppm)))
    hi = float(np.percentile(mag[inner], 92)) if inner.any() else 1.0
    ed = cv2.Canny(g, 0.4 * hi, hi, L2gradient=True) > 0
    sk = skeletonize(ed & inner)
    nb = ndi.convolve(sk.astype(np.uint8), np.ones((3, 3), np.uint8), mode="constant")
    sk &= ~((nb >= 4) & sk)                                 # cut at junctions -> separate strokes
    lab, n = ndi.label(sk, np.ones((3, 3)))
    cand = []
    for i in range(1, n + 1):
        c = lab == i
        L = c.sum() / ppm
        if L >= min_len_mm:
            cand.append((float(mag[c].mean()) * min(L, 25.0), c))
    cand.sort(key=lambda t: -t[0])
    kept = np.zeros_like(sk)
    strokes = []
    for _, c in cand[:120]:
        if len(strokes) >= max_lines:
            break
        if kept.any():
            dist = ndi.distance_transform_edt(~kept)
            c = c & (dist >= gap_mm * ppm)                  # only the part far enough from lines already kept
            lab2, n2 = ndi.label(c, np.ones((3, 3)))
            if not n2:
                continue
            c = lab2 == 1 + int(np.argmax(np.bincount(lab2.ravel())[1:]))
            if c.sum() / ppm < min_len_mm:
                continue
        kept |= c
        strokes.append(c)
    return kept, strokes


# ---------------------------------------------------------------- the drawing handed to the engine
def _drawing(cv2, S, lines, ppm, size_mm):
    s = min(8.0, 600.0 / size_mm)               # px per mm of the drawing
    f = s / ppm
    H, W = max(8, int(S.shape[0] * f)), max(8, int(S.shape[1] * f))
    Sb = cv2.resize(S.astype(np.uint8), (W, H), interpolation=cv2.INTER_LINEAR)
    Sb = cv2.GaussianBlur(Sb.astype(np.float32), (0, 0), 0.75 * s) > 0.5
    ring = Sb & ~ndi.binary_erosion(Sb, iterations=max(2, int(round(1.25 * s))))      # 1.25 mm outline stroke
    ys, xs = np.nonzero(lines)
    L = np.zeros((H, W), np.uint8)
    L[np.clip((ys * f).astype(int), 0, H - 1), np.clip((xs * f).astype(int), 0, W - 1)] = 1
    kk = max(3, int(round(1.5 * s)) | 1)
    L = cv2.dilate(L, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kk, kk)))
    L = cv2.GaussianBlur(L.astype(np.float32), (0, 0), 0.4 * s) > 0.5
    img = np.full((H, W), 255, np.uint8)
    img[ring | (L & Sb)] = 0
    return np.pad(img, 40, constant_values=255)


def _poly(cv2, m, off, wh, eps=0.8):
    """Outline of a mask as one polyline, normalised 0..1 of the photo."""
    cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return []
    c = max(cs, key=cv2.contourArea)
    c = cv2.approxPolyDP(c, eps, True).reshape(-1, 2).astype(float)
    return [[round((x + off[0]) / wh[0], 4), round((y + off[1]) / wh[1], 4)] for x, y in c]


REF_MM = 80.0    # size at which "clear subject?" and "enough lines?" are decided


def make_cutter_drawing(upload: bytes, size_mm: float) -> dict:
    """-> {png, route, message, report, overlay, lines}. Raises NeedsCv or PhotoRefused."""
    try:
        import cv2
    except ImportError as exc:
        raise NeedsCv("NEEDS_CV photo cookies need the OpenCV package, which is not available here") from exc
    from PIL import Image
    rgb = np.asarray(_open(upload))
    k = WORK / max(rgb.shape[:2])
    if k < 1:
        rgb = cv2.resize(rgb, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    h0, w0 = rgb.shape[:2]
    fc = find_face(cv2, rgb)
    m = _smooth(cv2, _grab(cv2, rgb, fc), 5)
    # what the photo IS (subject or not, enough lines or not) must not depend on how big the
    # cookie is made: decide at a fixed reference size, draw at the user's size
    ok, num = gate(cv2, m, rgb, fc is not None, REF_MM)
    route = ("head" if fc is not None else "subject") if ok else "plaque"
    if not ok:
        m = _plaque(cv2, h0, w0)
    ys, xs = np.nonzero(m)
    y0, y1, x0, x1 = max(ys.min() - 6, 0), ys.max() + 7, max(xs.min() - 6, 0), xs.max() + 7
    mc, crop = m[y0:y1, x0:x1], rgb[y0:y1, x0:x1]
    ppm = max(mc.shape) / size_mm
    lines, strokes = inside_lines(cv2, crop, mc, ppm)
    total_mm = float(lines.sum()) / ppm
    report = dict(route=route, gate=num, face=fc is not None, lines=len(strokes), line_mm=round(total_mm, 1))
    if route == "plaque":
        ref_ppm = max(mc.shape) / REF_MM
        ref_lines, ref_strokes = (lines, strokes) if abs(ref_ppm - ppm) < 1e-9 else inside_lines(cv2, crop, mc, ref_ppm)
        ref_mm = float(ref_lines.sum()) / ref_ppm
        report.update(ref_lines=len(ref_strokes), ref_line_mm=round(ref_mm, 1))
    if route == "plaque" and (report["ref_lines"] < 6 or report["ref_line_mm"] < 40.0):
        report["refused"] = True
        raise PhotoRefused(REFUSE)
    dr = _drawing(cv2, mc, lines, ppm, size_mm)
    b = io.BytesIO()
    Image.fromarray(dr).save(b, "PNG")
    wh = (float(w0), float(h0))
    lpolys = []
    for st in strokes:
        cs, _ = cv2.findContours(st.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cs:
            c = cv2.approxPolyDP(c, 1.0, False).reshape(-1, 2)
            if len(c) >= 2:
                lpolys.append([[round((x + x0) / wh[0], 4), round((y + y0) / wh[1], 4)] for x, y in c])
    return dict(png=b.getvalue(), route=route, message=MSG[route], report=report,
                overlay=dict(aspect=round(wh[0] / wh[1], 4), outline=_poly(cv2, m, (0, 0), wh), lines=lpolys))
