"""Group photo -> block-print art for a roller (art_style "group").

Route (any photo with one or more people):
 1 faces: three OpenCV Haar cascades (frontal alt2, frontal default, profile both ways), merged and
   filtered by skin colour and size. Cascade files ship in data/cascades (OpenCV, BSD licence).
 2 people: grabCut seeded from the faces (heads sure, torsos probable), largest piece kept.
 3 drawing at the art's final size (mm): dark masses solid, patterned cloth as a windowpane,
   fold lines in light cloth, faces from feature-scale marks with a fixed ink budget; faces under
   SMALL_FACE_MM use a per-face tone renderer; eyes of larger faces are redrawn as matching
   smiling-almond glyphs with brows (the cutout loses eyes into hair and shadow).
 4 clay: thin marks redrawn as LINE strokes on their skeleton, narrow white channels carved open
   along their centre line (never closed), forced GAP carve outside faces, specks dropped.
OpenCV (cv2) is needed: in the browser the worker loads Pyodide's opencv-python only for this mode.
"""
from __future__ import annotations
import io
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from skimage.morphology import skeletonize

CASCADES = Path(__file__).resolve().parent / "data" / "cascades"
LINE, GAP, SPECK = 1.3, 1.9, 4.0       # mm, mm, mm2
SMALL_FACE_MM = 30.0
PPM = 5.0                              # px per mm while drawing (set by make_group)
V = dict(dark=0.46, tex=0.055, body_sig=0.9, body_k=-0.012, body_len=10.0, plaid_pitch=8.0,
         face_sig=0.016, face_k=0.045, face_dark=0.56, budget=15.0, hl_mass=1500.0, hl_q=0.70)


class GroupError(ValueError):
    pass


# ---------------- distance helpers (cv2's transform: ~10x faster than scipy's) ----------------
def edt(m):
    import cv2
    m = np.ascontiguousarray(m, dtype=np.uint8)
    return cv2.distanceTransform(m, cv2.DIST_L2, cv2.DIST_MASK_PRECISE) / PPM


def dil(m, r):
    return edt(~m) <= r


def opening(m, r):
    # as in the approved prototype (grows about 0.1 mm; changing it changes the look)
    return dil(edt(m) > r - 0.1, r)


def drop_small(m, mm2):
    lab, n = ndi.label(m, np.ones((3, 3)))
    if n == 0:
        return m
    a = ndi.sum(m, lab, np.arange(1, n + 1)) / PPM ** 2
    return np.concatenate([[False], a >= mm2])[lab]


# ---------------- 1 faces ----------------
def _skin_frac(rgb, x, y, w):
    c = rgb[int(y + 0.25 * w):int(y + 0.75 * w), int(x + 0.25 * w):int(x + 0.75 * w)].astype(float) / 255
    if c.size == 0:
        return 0.0
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    return float(((r > 0.35) & (r - b > 0.08) & (r >= g) & (r - g < 0.35)).mean())


def _iou(a, b):
    ax, ay, aw = a[:3]
    bx, by, bw = b[:3]
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + aw, by + bw) - max(ay, by))
    i = ix * iy
    return i / (aw * aw + bw * bw - i)


def detect_faces(rgb, log=None):
    """rgb uint8 HxWx3 -> [(x, y, w)] face boxes in photo px, largest first."""
    import cv2
    H, W = rgb.shape[:2]
    s = min(1.0, 1700.0 / max(H, W))        # small profile faces need about 1700 px
    g = cv2.cvtColor(cv2.resize(rgb, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2GRAY)
    g = cv2.equalizeHist(g)
    mn = max(24, int(0.04 * min(g.shape)))
    cands = []
    for name, flip in (("haarcascade_frontalface_alt2.xml", False), ("haarcascade_frontalface_default.xml", False),
                       ("haarcascade_profileface.xml", False), ("haarcascade_profileface.xml", True)):
        c = cv2.CascadeClassifier(str(CASCADES / name))
        if c.empty():
            raise GroupError("face detector file missing: " + name)
        im = np.ascontiguousarray(g[:, ::-1]) if flip else g
        for (x, y, w, h) in (c.detectMultiScale(im, 1.08, 5, minSize=(mn, mn)) if True else []):
            if flip:
                x = im.shape[1] - x - w
            if "profile" in name:
                # a profile box covers the back of the head too: move it onto the face
                x = x + (0.35 * w if flip else -0.35 * w)
            cands.append((x / s, y / s, w / s))
    keep = [c for c in cands if _skin_frac(rgb, *c) > 0.45]
    groups = []
    for c in sorted(keep, key=lambda c: -c[2]):
        for gp in groups:
            g0 = gp[0]
            if _iou(g0, c) > 0.25 or (abs((g0[0] + g0[2] / 2) - (c[0] + c[2] / 2)) < 0.4 * g0[2]
                                      and abs((g0[1] + g0[2] / 2) - (c[1] + c[2] / 2)) < 0.4 * g0[2]):
                gp.append(c)
                break
        else:
            groups.append([c])
    faces = [tuple(float(v) for v in np.median(np.array(gp, float), axis=0)) for gp in groups]
    if not faces:
        return []
    med = float(np.median([f[2] for f in faces]))
    faces = [f for f in faces if f[2] <= 1.7 * med]          # torsos and skirts first
    big = max(f[2] for f in faces)
    faces = [f for f in faces if f[2] >= 0.35 * big]          # then specks, against real faces
    # Haar boxes run about 8 % larger than the face the drawing step expects (brow to chin):
    # shrink about the centre
    faces = [(x + 0.04 * w, y + 0.04 * w, 0.92 * w) for x, y, w in faces]
    faces.sort(key=lambda f: -f[2])
    if log:
        log("faces: " + ", ".join("%d,%d w%d" % f for f in faces))
    return faces


# ---------------- 2 people ----------------
def segment(rgb, faces):
    """People mask by grabCut, seeded from the face boxes (art px)."""
    import cv2
    f = 0.5
    small = cv2.resize(rgb[:, :, ::-1], None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    h, w = small.shape[:2]
    mk = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    for x, y, fw in faces:
        x, y, fw = x * f, y * f, fw * f
        cx = x + fw / 2
        cv2.rectangle(mk, (int(cx - 1.25 * fw), int(y + 1.1 * fw)), (int(cx + 1.25 * fw), h), cv2.GC_PR_FGD, -1)
    for x, y, fw in faces:
        x, y, fw = x * f, y * f, fw * f
        cx = x + fw / 2
        cv2.ellipse(mk, (int(cx), int(y + 0.45 * fw)), (int(0.75 * fw), int(0.95 * fw)), 0, 0, 360, cv2.GC_PR_FGD, -1)
        cv2.ellipse(mk, (int(cx), int(y + 0.42 * fw)), (int(0.45 * fw), int(0.72 * fw)), 0, 0, 360, cv2.GC_FGD, -1)
        cv2.rectangle(mk, (int(cx - 0.3 * fw), int(y + fw)), (int(cx + 0.3 * fw), int(y + 2.2 * fw)), cv2.GC_FGD, -1)
    mk[:3, :] = cv2.GC_BGD
    mk[:, :3] = cv2.GC_BGD
    mk[:, -3:] = cv2.GC_BGD
    cv2.setRNGSeed(1)           # grabCut's colour clustering is random: same photo, same art
    cv2.grabCut(np.ascontiguousarray(small), mk, None, np.zeros((1, 65)), np.zeros((1, 65)), 6, cv2.GC_INIT_WITH_MASK)
    m = (mk == cv2.GC_FGD) | (mk == cv2.GC_PR_FGD)
    m = cv2.resize(m.astype(np.uint8), (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR) > 0
    m = opening(m, 2.0)
    m = ~opening(~m, 2.0)
    lab, n = ndi.label(m)
    if n > 1:
        a = ndi.sum(m, lab, np.arange(1, n + 1))
        m = lab == (1 + int(np.argmax(a)))
    return ndi.binary_fill_holes(m)


def face_zone(shape, faces, grow=1.0):
    yy, xx = np.mgrid[:shape[0], :shape[1]]
    z = np.zeros(shape, bool)
    sig = np.zeros(shape)
    for x, y, fw in faces:
        e = ((xx - (x + fw / 2)) / (0.50 * fw * grow)) ** 2 + ((yy - (y + 0.52 * fw)) / (0.66 * fw * grow)) ** 2 <= 1
        z |= e
        sig[e] = fw
    return z, sig


# ---------------- 3 drawing ----------------
def draw(rgb, faces, people, v):
    g = np.asarray(Image.fromarray(rgb).convert("L"), float) / 255
    H, W = g.shape
    fz, fwmap = face_zone(g.shape, faces)
    body = people & ~fz
    gs = ndi.gaussian_filter(g, 0.7 * PPM)
    dark = (gs < v["dark"]) & people
    # patterned cloth (lots of fine contrast in a mid/dark area) -> windowpane, not a slab
    hf = np.abs(g - ndi.gaussian_filter(g, 0.5 * PPM))
    tex = ndi.gaussian_filter(hf, 2.5 * PPM)
    plaid = opening((tex > v["tex"]) & (ndi.gaussian_filter(g, 3 * PPM) < 0.5) & body, 4.0)
    plaid = drop_small(plaid, 600.0)
    plaid = ndi.binary_fill_holes(~opening(~plaid, 5.0)) & body
    dark = dark | plaid
    s = v["body_sig"] * PPM
    d = ndi.gaussian_filter(g, s) - 0.985 * ndi.gaussian_filter(g, 1.6 * s)
    lines = (d < v["body_k"]) & body & (gs > v["dark"] + 0.04)
    lines = drop_small(lines, v["body_len"])
    ink = (dark | lines) & body
    if plaid.any():
        yy, xx = np.mgrid[:H, :W]
        p = v["plaid_pitch"] * PPM
        a = np.deg2rad(8)
        u = (xx * np.cos(a) + yy * np.sin(a)) % p
        w_ = (-xx * np.sin(a) + yy * np.cos(a)) % p
        gw = (GAP + 0.9) * PPM                  # windowpane lines drawn wide so they survive the clay pass
        grid = (u < gw) | (w_ < gw)
        ink &= ~(grid & plaid & ~dil(~plaid, 2.2))
    fink = np.zeros_like(ink)
    yy, xx = np.mgrid[:H, :W]
    for (x, y, fw) in faces:
        s = max(v["face_sig"] * fw, 0.4 * PPM)
        dd = ndi.gaussian_filter(g, s) - ndi.gaussian_filter(g, 2.5 * s)
        z = fwmap == fw
        inner = ((xx - (x + fw / 2)) / (0.40 * fw)) ** 2 + ((yy - (y + 0.56 * fw)) / (0.52 * fw)) ** 2 <= 1
        core = ((xx - (x + fw / 2)) / (0.25 * fw)) ** 2 + ((yy - (y + 0.55 * fw)) / (0.3 * fw)) ** 2 <= 1
        skin = float(np.median(g[core])) if core.any() else 0.6
        kb = min(-0.02, float(np.percentile(dd[inner], v["budget"]))) if inner.any() else -0.02
        fink |= inner & (dd < kb)
        fink |= z & ~inner & (dd < -v["face_k"])
        fink |= z & ~inner & (ndi.gaussian_filter(g, 0.4 * PPM) < v["face_dark"] * skin)
    ink |= fink & people
    rim = people & ~(edt(people) > LINE + 0.1)
    ink |= rim
    return ink, fz


def tone_face(photo, box, size_mm, dark_q=0.16, smooth_mm=0.55):
    """Small faces: per-face contrast, the darkest features become clay marks.
    photo float RGB 0..1; box (x, y, w) photo px -> (ink, oval) over a 1.6w x 2.0w head box."""
    x, y, w = box
    cw, ch = 1.6 * w, 2.0 * w
    x0, y0 = x + w / 2 - cw / 2, y - 0.6 * w
    wpx = max(8, int(size_mm * PPM))
    hpx = int(wpx * ch / cw)
    im = Image.fromarray((np.clip(photo, 0, 1) * 255).astype(np.uint8))
    crop = im.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).resize((wpx * 2, hpx * 2), Image.LANCZOS)
    rgb = np.asarray(crop).astype(float) / 255
    L = 0.3 * rgb[..., 0] + 0.59 * rgb[..., 1] + 0.11 * rgb[..., 2]
    L = ndi.gaussian_filter(L, smooth_mm * PPM * 2)
    L = np.asarray(Image.fromarray((L * 255).astype(np.uint8)).resize((wpx, hpx), Image.LANCZOS), float) / 255
    yy, xx = np.mgrid[0:hpx, 0:wpx]
    fcx, fcy = wpx / 2, (0.6 * w + 0.5 * w) / ch * hpx
    face = ((xx - fcx) / (0.42 * w / cw * wpx)) ** 2 + ((yy - fcy) / (0.5 * w / ch * hpx)) ** 2 <= 1
    oval = ((xx - fcx) / (0.6 * w / cw * wpx)) ** 2 + ((yy - fcy) / (0.8 * w / ch * hpx)) ** 2 <= 1
    thr = np.quantile(L[face], dark_q)
    feat = ((L <= thr) | ((L - ndi.gaussian_filter(L, 2.0 * PPM)) < -0.06)) & face
    hair = (L <= np.quantile(L[oval & ~face], 0.45)) & oval & ~face
    ink = feat | hair
    rim = dil(face, LINE / 2) & ~(edt(face) > LINE / 2) & oval
    ink |= rim & ~dil(hair, GAP)
    r = GAP / 2
    ink = ~dil(edt(~ink) > r, r)
    r = LINE / 2
    ink = dil(edt(ink) > r, r + 0.1)
    ink = drop_small(ink, 2.5)
    return ink & oval, oval


def _paste(shape, src, x0, y0):
    H, W = shape
    h, w = src.shape
    out = np.zeros(shape, bool)
    ys, xs = slice(max(0, y0), min(H, y0 + h)), slice(max(0, x0), min(W, x0 + w))
    if ys.stop > ys.start and xs.stop > xs.start:
        out[ys, xs] = src[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0]
    return out


def highlights(ink, rgb, people, v):
    """Big solid masses get their light passages knocked out (hands, folds, the baby's legs)."""
    g = np.asarray(Image.fromarray(rgb).convert("L"), float) / 255
    gs = ndi.gaussian_filter(g, 0.6 * PPM)
    solid = opening(ink, 2.5) & people
    lab, n = ndi.label(solid)
    if not n:
        return ink
    area = ndi.sum(solid, lab, np.arange(1, n + 1)) / PPM ** 2
    out = ink.copy()
    for i in np.where(area > v["hl_mass"])[0] + 1:
        m = lab == i
        hl = m & (gs > np.quantile(gs[m], v["hl_q"])) & (edt(m) > 1.5)
        out &= ~drop_small(hl, 6.0)
    return out


# ---------------- eyes ----------------
def _lens(cx, cy, w, h_top, h_bot, ang, n=40):
    t = np.linspace(-1, 1, n)
    p = np.vstack([np.stack([t * w / 2, -h_top * (1 - t ** 2)], 1), np.stack([t[::-1] * w / 2, h_bot * (1 - t[::-1] ** 2)], 1)])
    R = np.array([[math.cos(ang), -math.sin(ang)], [math.sin(ang), math.cos(ang)]])
    return p @ R.T + [cx, cy]


def _arc(cx, cy, w, h, ang, n=40):
    t = np.linspace(-1, 1, n)
    p = np.stack([t * w / 2, -h * (1 - t ** 2)], 1)
    R = np.array([[math.cos(ang), -math.sin(ang)], [math.sin(ang), math.cos(ang)]])
    return p @ R.T + [cx, cy]


def find_eyes(photo, box):
    """photo float RGB 0..1, box photo px -> eyes [(x,y)], spacing, brow heights, skin crop."""
    x, y, w = box
    pad = int(0.17 * w)
    X0, Y0, S = int(x - pad), int(y - pad), int(w + 2 * pad)
    Hh, Ww = photo.shape[:2]
    if X0 < 0 or Y0 < 0 or X0 + S > Ww or Y0 + S > Hh:
        return None
    cc = photo[Y0:Y0 + S, X0:X0 + S]
    g = cc.mean(2)
    skin = (cc[..., 0] - cc[..., 2] > 0.12) & (cc[..., 0] > 0.45)
    skin = ndi.binary_closing(skin, iterations=4)
    lab, n = ndi.label(skin)
    if not n:
        return None
    skin = ndi.binary_fill_holes(lab == (1 + int(np.argmax(np.bincount(lab.ravel())[1:]))))
    yy, xx = np.mgrid[:S, :S]
    skin &= ((xx - (pad + 0.5 * w)) / (0.50 * w)) ** 2 + ((yy - (pad + 0.55 * w)) / (0.66 * w)) ** 2 <= 1
    d = ndi.gaussian_filter(g, 0.011 * w) - ndi.gaussian_filter(g, 0.05 * w)
    eyes = []
    for a, b in ((0.15, 0.52), (0.52, 0.92)):
        m = np.zeros_like(skin)
        m[pad + int(0.22 * w):pad + int(0.6 * w), pad + int(a * w):pad + int(b * w)] = True
        dd = np.where(m & skin, d, 1.0)
        if dd.min() > -0.04:
            return None                                   # no clear eye: leave the face alone
        r, c = np.unravel_index(dd.argmin(), dd.shape)
        blob = (dd < 0.5 * dd.min()) & (np.hypot(yy - r, xx - c) < 0.12 * w)
        rr, cs = np.nonzero(blob)
        eyes.append((X0 + cs.mean(), Y0 + rr.mean()))
    (lx, ly), (rx, ry) = eyes
    span = math.hypot(rx - lx, ry - ly)
    if not (0.25 * w < span < 0.75 * w):
        return None
    gb = ndi.gaussian_filter(g, 0.015 * w)
    brows = []
    for ex, ey in eyes:
        cx, cy = int(ex - X0), int(ey - Y0)
        col = gb[max(0, cy - int(0.45 * span)):max(1, cy - int(0.12 * span)), max(0, cx - 4):cx + 5].mean(1)
        brows.append(ey - 0.12 * span - (len(col) - 1 - int(col.argmin())) if len(col) else ey - 0.3 * span)
    return {"eyes": eyes, "span": span, "brows": brows, "skin": skin, "origin": (X0, Y0)}


def _curve(p3, n=40):
    """Quadratic through 3 points (passes through the middle one at t = 0.5)."""
    p0, pm, p2 = [np.array(p, float) for p in p3]
    c = 2 * pm - 0.5 * (p0 + p2)
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 2 * p0 + 2 * t * (1 - t) * c + t ** 2 * p2


def _stroke(shape, pts, width_mm, S=4):
    """Round-capped, round-jointed stroke (no butt ends, no stair notches)."""
    H, W = shape
    big = Image.new("L", (W * S, H * S), 0)
    dr = ImageDraw.Draw(big)
    r = width_mm * PPM * S / 2
    for a, b in zip(pts[:-1], pts[1:]):
        dr.line([tuple(a * S), tuple(b * S)], fill=255, width=int(round(2 * r)))
    for q in pts:
        dr.ellipse([q[0] * S - r, q[1] * S - r, q[0] * S + r, q[1] * S + r], fill=255)
    return np.asarray(big.resize((W, H), Image.BOX)) >= 128


def _ellipse(shape, c, w_mm, h_mm, ang):
    H, W = shape
    yy, xx = np.mgrid[:H, :W]
    dx, dy = xx - c[0], yy - c[1]
    u = dx * math.cos(ang) + dy * math.sin(ang)
    v = -dx * math.sin(ang) + dy * math.cos(ang)
    return (u / (w_mm * PPM / 2)) ** 2 + (v / (h_mm * PPM / 2)) ** 2 <= 1


EYE_GAP = 1.6           # mm between lid, brow and hair (face tolerance; R21 limit 1.0)
NOSE_STYLE = "hook"     # dainty: slim shadow-side line turning under the tip + one small nostril


def redraw_eyes(ink, photo, box, to_art, log=None, only_if_lost=False):
    """Smiling eyes as in the eye red team's variant A: a crescent lid stroke (outer corner, apex,
    inner corner), an iris hanging under the apex, a low near-straight brow lifted only as far as
    the clay gap needs; isolated marks in the eye band are cleared whole, one smooth clearing per
    eye and brow, the hair edge rounded afterwards."""
    from skimage.morphology import convex_hull_image
    info = find_eyes(photo, box)
    if info is None:
        if log:
            log("eyes: not found clearly, face left as drawn")
        return ink
    (lx, ly), (rx, ry) = info["eyes"]
    bx, by_, bw_ = box
    # a half-hidden eye (hair over its outer half) is found too close to the nose: if the pair is
    # short, the eye nearer the hairline moves out to a typical spacing (0.43 x face width)
    target = 0.45 * bw_
    span = math.hypot(rx - lx, ry - ly)
    ang = math.atan2(ry - ly, rx - lx)
    lim = math.radians(11.0)
    lost = span < 0.9 * target or abs(ang) > lim
    if only_if_lost and not lost:
        if log:
            log("eyes: both found, face left as drawn")
        return ink
    if lost:
        X0, Y0 = info["origin"]
        sd = ndi.distance_transform_edt(info["skin"])
        dl = sd[int(min(sd.shape[0] - 1, max(0, ly - Y0))), int(min(sd.shape[1] - 1, max(0, lx - X0)))]
        dr_ = sd[int(min(sd.shape[0] - 1, max(0, ry - Y0))), int(min(sd.shape[1] - 1, max(0, rx - X0)))]
        a2 = max(-lim, min(lim, ang))
        sp = max(span, target)
        if dl < dr_:      # left eye nearer the hair: rebuild it from the right one
            lx, ly = rx - sp * math.cos(a2), ry - sp * math.sin(a2)
        else:
            rx, ry = lx + sp * math.cos(a2), ly + sp * math.sin(a2)
        if log:
            log("eyes: half-hidden %s eye placed by spacing" % ("left" if dl < dr_ else "right"))
    ax0, ay0 = to_art(lx, ly)
    ax1, ay1 = to_art(rx, ry)
    span_px = math.hypot(ax1 - ax0, ay1 - ay0)
    ang = math.atan2(ay1 - ay0, ax1 - ax0)
    ca, sa = math.cos(ang), math.sin(ang)
    rot = lambda c, u, v: (c[0] + u * ca - v * sa, c[1] + u * sa + v * ca)
    ew = max(5.0 * PPM, 0.44 * span_px)
    H, W = ink.shape
    k = span_px / max(1e-6, math.hypot(rx - lx, ry - ly))
    X0, Y0 = info["origin"]
    sk = info["skin"]
    sx0, sy0 = to_art(X0, Y0)
    sm = np.asarray(Image.fromarray(sk.astype(np.uint8) * 255).resize(
        (max(1, int(sk.shape[1] * k)), max(1, int(sk.shape[0] * k))), Image.BILINEAR)) > 127
    skin = _paste((H, W), sm, int(round(sx0)), int(round(sy0)))
    yy, xx = np.mgrid[:H, :W]
    eye_cy = (ay0 + ay1) / 2
    # clear whole isolated pieces (under 60 mm2, so never the hair mass) that reach the eye band
    band = skin & (yy > eye_cy - 0.75 * span_px) & (yy < eye_cy + 0.30 * span_px)
    lab, n = ndi.label(ink)
    out = ink
    if n:
        area = ndi.sum(ink, lab, np.arange(1, n + 1)) / PPM ** 2
        hit = np.unique(lab[band & ink])
        kill = [i for i in hit if i > 0 and area[i - 1] < 60]
        out = ink & ~np.isin(lab, kill)
    g = np.zeros_like(ink)
    clear = np.zeros_like(ink)
    for c, outer in (((ax0, ay0), -1), ((ax1, ay1), +1)):
        o = rot(c, outer * ew / 2, 0.06 * ew)            # corners sit a little below the apex line
        i_ = rot(c, -outer * ew / 2, 0.10 * ew)
        apex = rot(c, outer * 0.05 * ew, -0.12 * ew)
        lid = _stroke(ink.shape, _curve([o, apex, i_]), 1.5)
        # iris tucked up under the lid (eye 3.0-3.2 mm tall reads as a squint, not looking down)
        iris = _ellipse(ink.shape, rot(apex, 0, 0.7 * PPM), 2.6, 2.0, ang)
        e = lid | iris
        e = ndi.binary_closing(e, iterations=2) | e       # fill the wedge where iris meets lid
        part = e.copy()
        d_e = edt(~e)
        lift = 0.0
        while lift <= 4.0 * PPM:
            pts = [rot(c, outer * 0.48 * ew, -(0.12 * ew + 2.9 * PPM) + 0.5 * PPM - lift),
                   rot(c, 0.0, -(0.12 * ew + 2.9 * PPM) - 0.4 * PPM - lift),
                   rot(c, -outer * 0.50 * ew, -(0.12 * ew + 2.9 * PPM) - lift)]
            b = _stroke(ink.shape, _curve(pts), 1.35)
            if d_e[b].min() >= EYE_GAP:
                break
            lift += 0.5
        part |= b
        g |= part
        hull = convex_hull_image(part)
        clear |= opening(edt(~hull) <= EYE_GAP + 0.2, 2.0) | hull   # no square notch in the hair
    out = (out & ~clear) | g
    # round the hair edge the clearing left
    zone = edt(~clear) <= 3.0
    ink_wo = out & ~g
    sm_ink = ndi.binary_opening(ndi.binary_closing(ink_wo, iterations=4), structure=np.ones((3, 3)), iterations=3) & ~clear
    out = np.where(zone, sm_ink, ink_wo) | g
    if log:
        log("eyes: spacing %.1f mm, eye %.1f mm, tilt %.0f deg" % (span_px / PPM, ew / PPM, math.degrees(ang)))
    return out


def redraw_nose(ink, face, rgb=None, eye_info=None, log=None):
    """Heavy nostril dots or a nose-shadow bar (the cutout's darkest marks under the nose) read as
    holes. Replace them with one dainty mark (nose red team, variant V1): a slim 1.3 mm line down
    the shadow side of the nose that turns under the tip and stops.
    The foot sits on the real nose base (the bottom of the removed nostril marks), so the gap to
    the upper lip matches the photo; it lifts at most 1 mm, and only for ink right under the nose.
    face = (x, y, w) art px; rgb = the photo at art scale (shadow side);
    eye_info = (eye line y at the nose, eye-line angle) in art px / rad, or None."""
    x, y, w = face
    H, W = ink.shape
    cx = x + w / 2
    lab, n = ndi.label(ink)
    if not n:
        return ink
    y0, y1 = int(max(0, y + 0.50 * w)), int(min(H, y + 0.74 * w))
    x0, x1 = int(max(0, x + 0.25 * w)), int(min(W, x + 0.75 * w))
    nos = []
    for i in [i for i in np.unique(lab[y0:y1, x0:x1]) if i]:
        m = lab == i
        a = m.sum() / PPM ** 2
        rr, cc = np.nonzero(m)
        if not (2.0 <= a <= 45.0) or (cc.max() - cc.min() + 1) > 0.5 * w or abs(cc.mean() - cx) > 0.2 * w:
            continue
        if rr.min() < y + 0.42 * w or rr.max() > y + 0.74 * w or rr.mean() > y + 0.68 * w:
            continue                         # reaches the eyes or the mouth: not a nose mark
        nos.append((i, cc.mean(), rr.mean(), cc.min(), cc.max(), rr.max()))
    if not nos:
        return ink
    kill = np.isin(lab, [t[0] for t in nos])
    out = ink & ~kill
    nos.sort(key=lambda t: t[1])
    mx = (min(t[3] for t in nos) + max(t[4] for t in nos)) / 2
    # the drawn nostril marks are blurred downward, so their bottom edge is too low: the real
    # nostril bottom is about 0.7 mm below the nostril centres. The stroke's lowest edge (path dip
    # 0.25 mm + half the 1.3 mm stroke) is put on that line.
    nostril_bottom = float(np.mean([t[2] for t in nos])) + 0.7 * PPM
    wings = max(t[4] for t in nos) - min(t[3] for t in nos)
    wings = min(max(wings, 0.20 * w), 0.28 * w)
    if eye_info is not None:
        eye_y, ang = eye_info
    elif len(nos) >= 2:
        eye_y, ang = y + 0.40 * w, math.atan2(nos[-1][2] - nos[0][2], nos[-1][1] - nos[0][1])
    else:
        eye_y, ang = y + 0.40 * w, 0.0
    ang = max(-math.radians(12), min(math.radians(12), ang))
    ca, sa = math.cos(ang), math.sin(ang)
    if rgb is not None:
        # measured as on the photo: a strip +-1.5 mm wide down the nose axis, levelled by the eye
        # line; the nostril shadow is the first run darker than 0.62 x the skin above it; its
        # bottom is the nose base
        g = np.asarray(Image.fromarray(rgb).convert("L"), float) / 255
        vs = np.arange(-0.25 * w, 0.20 * w)
        prof = []
        for v in vs:
            vals = []
            for u in np.arange(-1.5 * PPM, 1.5 * PPM + 1):
                px, py = mx + u * ca - v * sa, nostril_bottom + u * sa + v * ca
                if 0 <= int(py) < H and 0 <= int(px) < W:
                    vals.append(g[int(py), int(px)])
            prof.append(np.mean(vals) if vals else 1.0)
        prof = np.array(prof)
        skin = float(np.median(prof[: int(0.12 * w)]))
        dark = np.nonzero(prof < 0.62 * skin)[0]
        if len(dark):
            run = np.split(dark, np.nonzero(np.diff(dark) > 1)[0] + 1)[0]
            nostril_bottom = nostril_bottom + vs[run[-1]] * 1.0
    base = nostril_bottom - (0.25 + 0.65) * PPM          # stroke's lowest edge on the nose base
    foot = min(5.0, max(3.5, 0.42 * wings / PPM))         # mm, under the tip
    h = foot / 2
    Lb = 0.45 * max(4.0, (base - eye_y) / PPM)           # mm, flank line height
    up = -0.35 if foot < 4.0 else -0.15
    # shadow side: the darker flank of the nose in the photo
    sgn = 1.0
    if rgb is not None:
        g = np.asarray(Image.fromarray(rgb).convert("L"), float)
        def strip(side):
            us = side * np.linspace(0.4, 1.3, 6) * wings / 2
            vs = -np.linspace(0.3, 0.9, 6) * Lb * PPM
            vals = []
            for u in us:
                for v in vs:
                    px, py = mx + u * ca - v * sa, base + u * sa + v * ca
                    if 0 <= int(py) < H and 0 <= int(px) < W:
                        vals.append(g[int(py), int(px)])
            return np.mean(vals) if vals else 255.0
        sgn = 1.0 if strip(1.0) < strip(-1.0) else -1.0
    P = lambda u, v, lift: (mx + PPM * (u * ca - (v - lift) * sa), base + PPM * (u * sa + (v - lift) * ca))
    under = out & ~kill
    yy, xx = np.mgrid[:H, :W]
    du = (xx - mx) * ca + (yy - base) * sa
    dv = -(xx - mx) * sa + (yy - base) * ca
    below = under & (np.abs(du) < 1.3 * wings / 2) & (dv > 0) & (dv < 0.3 * w)
    for lift in np.arange(0.0, 1.0 + 1e-6, 0.25):
        pts = [P(sgn * (h - 0.6), -Lb, lift), P(sgn * (h - 0.2), -0.5 * Lb, lift), P(sgn * h, -1.3, lift),
               P(sgn * (h - 0.5), -0.1, lift), P(0.0, 0.25, lift), P(-sgn * h, up, lift)]
        curve = np.vstack([_curve(pts[:3], 16), _curve(pts[2:5], 16), _curve(pts[4:] + [P(-sgn * (h + 0.01), up, lift)], 6)])
        mark = _stroke(ink.shape, curve, 1.3)
        if not below.any() or edt(~mark)[below].min() >= 1.5:
            break
    halo = (edt(~mark) <= EYE_GAP) & ~mark
    out = (out & ~halo) | mark
    if log:
        log("nose: base kept at the nostril line, foot %.1f mm, flank %.1f mm, lift %.2f mm, shadow side %s"
            % (foot, Lb, lift, "right" if sgn > 0 else "left"))
    return out


# ---------------- 4 clay ----------------
def slim(ink, rs, rw, min_len=3.0):
    op = opening(ink, rs)
    sk = skeletonize(ink) & ~op
    lab, n = ndi.label(sk, np.ones((3, 3)))
    if n:
        ln = ndi.sum(sk, lab, np.arange(1, n + 1)) / PPM
        touch = ndi.maximum(dil(op, 0.3), lab, np.arange(1, n + 1)) > 0
        sk = np.concatenate([[False], (ln >= min_len) | (touch & (ln >= 1.5))])[lab]
    return op | dil(sk, rw + 0.05)


def clay(ink, iters=7, line=LINE, gap=GAP, rs=1.0):
    rw, rg = line / 2, gap / 2
    ink = slim(ink, rs, rw)
    for _ in range(iters):
        W = ~ink
        ink = ink | (W & ~drop_small(W, 3.0))
        W = ~ink
        narrow = W & ~opening(W, rg - 0.1)
        real = drop_small(narrow, 0.8)
        ink = ink | (narrow & ~real)
        if real.any():
            ink = ink & ~dil(skeletonize(real), rg + 0.12)
        ink = drop_small(opening(ink, rw - 0.05), SPECK)
    return ink


def force_gaps(ink, keep, gap=GAP, rounds=6):
    rg = gap / 2
    for _ in range(rounds):
        W = ~ink
        narrow = drop_small(W & ~opening(W, rg), 0.6) & ~keep
        if not narrow.any():
            break
        ink = ink & ~dil(skeletonize(narrow), rg + 0.15)
        ink = np.where(keep, ink, drop_small(opening(ink, LINE / 2 - 0.05), SPECK))
    W = ~ink
    return ink | (W & ~drop_small(W, 3.0) & ~keep)


# ---------------- whole ----------------
def open_photo(upload: bytes):
    from PIL import ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(upload)))
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg
    im = im.convert("RGB")
    if max(im.size) > 2400:
        s = 2400.0 / max(im.size)
        im = im.resize((int(im.size[0] * s), int(im.size[1] * s)), Image.LANCZOS)
    return np.asarray(im)


def people_box(rgb, faces):
    """Crop (photo px): every face with room for hair above and bodies below, inside the photo."""
    H, W = rgb.shape[:2]
    x0 = min(f[0] - 1.4 * f[2] for f in faces)
    x1 = max(f[0] + 2.3 * f[2] for f in faces)
    y0 = min(f[1] - 0.35 * f[2] for f in faces)
    y1 = max(f[1] + 3.5 * f[2] for f in faces)
    return (int(max(0, x0)), int(max(0, y0)), int(min(W, x1)), int(min(H, y1)))


def aspect(upload: bytes):
    """width / height of the crop the drawing will use, and the face count (cheap)."""
    rgb = open_photo(upload)
    faces = detect_faces(rgb)
    if not faces:
        return rgb.shape[1] / rgb.shape[0], 0
    x0, y0, x1, y1 = people_box(rgb, faces)
    return (x1 - x0) / max(1, (y1 - y0)), len(faces)


_CACHE = {}


def make_group(upload: bytes, art_h_mm: float, ppm: float = 4.0, log=None, eye_glyphs=True):
    """-> (ink bool mask at ppm px/mm, row 0 = top, report dict)."""
    global PPM
    import hashlib
    key = (hashlib.sha1(upload).hexdigest(), round(float(art_h_mm), 1), float(ppm))
    if key in _CACHE:
        return _CACHE[key]
    PPM = float(ppm)
    rgb_full = open_photo(upload)
    faces_p = detect_faces(rgb_full, log)
    if not faces_p:
        raise GroupError("no faces found in the photo; try a photo where faces look at the camera")
    crop = people_box(rgb_full, faces_p)
    im = Image.fromarray(rgb_full).crop(crop)
    hpx = int(art_h_mm * PPM)
    sc = hpx / im.size[1]
    wpx = max(8, int(round(im.size[0] * sc)))
    rgb = np.asarray(im.resize((wpx, hpx), Image.LANCZOS))
    faces = [((x - crop[0]) * sc, (y - crop[1]) * sc, w * sc) for x, y, w in faces_p]
    people = segment(rgb, faces)
    raw, fz = draw(rgb, faces, people, V)
    photo = rgb_full.astype(float) / 255
    to_art = lambda X, Y: ((X - crop[0]) * sc, (Y - crop[1]) * sc)
    big = max(f[2] for f in faces)
    is_small = [fw / PPM < SMALL_FACE_MM or fw < 0.8 * big for (_, _, fw) in faces]
    small = 0
    for (x, y, fw), fp, sm_ in zip(faces, faces_p, is_small):
        if not sm_:
            continue
        ink_f, oval = tone_face(photo, fp, 1.6 * fw / PPM)
        x0, y0 = int(round(x + fw / 2 - ink_f.shape[1] / 2)), int(round(y - 0.6 * fw))
        o = _paste(raw.shape, oval, x0, y0)
        raw = (raw & ~o) | _paste(raw.shape, ink_f, x0, y0)
        small += 1
    raw = highlights(raw, rgb, people, V)
    # faces get the light pass only (thin marks redrawn at clay width, specks dropped): the full
    # pass fattens crinkled eyes and lip lines into blobs and closes the teeth band
    fzd = dil(fz, 1.0)
    face_ink = drop_small(slim(raw, 1.0, LINE / 2), SPECK)
    ink = np.where(fzd, face_ink, clay(raw))
    ink = force_gaps(ink, keep=fzd)
    eyes = 0
    for fp, sm_ in zip(faces_p, is_small):
        if not sm_ and eye_glyphs:
            before = ink
            ink = redraw_eyes(ink, photo, fp, to_art, log, only_if_lost=True)
            eyes += int(ink is not before)
    for f, fp, sm_ in zip(faces, faces_p, is_small):
        if not sm_:
            ei = find_eyes(photo, fp)
            eye_info = None
            if ei is not None:
                (lx, ly), (rx, ry) = ei["eyes"]
                (ax0, ay0), (ax1, ay1) = to_art(lx, ly), to_art(rx, ry)
                eye_info = ((ay0 + ay1) / 2, math.atan2(ay1 - ay0, ax1 - ax0))
            ink = redraw_nose(ink, f, rgb, eye_info, log)
    rep = {"faces": len(faces), "small_faces": small, "eyes_redrawn": eyes,
           "width_mm": round(wpx / PPM, 1), "height_mm": round(hpx / PPM, 1), "ink": round(float(ink.mean()), 3)}
    _CACHE.clear()
    _CACHE[key] = (ink, rep)
    return ink, rep
