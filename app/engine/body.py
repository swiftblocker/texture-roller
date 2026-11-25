"""Blank body reference dims (analytic, used by R68) and the optional build123d STEP (lazy import)."""
from __future__ import annotations
import os
import tempfile


def reference_dims(P):
    """Analytic reference for R68: outer diameter at the relief top, length, bore diameter."""
    return {"diameter": P.diameter, "length": P.length, "bore": P.bore_used, "end_chamfer": P.end_chamfer}


_CACHE = {}


def step_bytes(P, lay=None):
    """STEP of the blank (cylinder, bore, end chamfers, split key) or None when build123d is missing."""
    key = (P.diameter, P.length, P.bore_used, P.end_chamfer, P.split)
    if key in _CACHE:
        return _CACHE[key]
    try:
        import build123d as b
    except Exception:
        return None
    try:
        R, L, br, c = P.R, P.length, P.bore_used / 2, P.end_chamfer
        body = b.Cylinder(R, L, align=(b.Align.CENTER, b.Align.CENTER, b.Align.MIN))
        if c > 0:
            ed = [e for e in body.edges() if e.geom_type == b.GeomType.CIRCLE and abs(e.radius - R) < 1e-6]
            body = b.chamfer(ed, c)
        if br > 0:
            body = body - b.Cylinder(br, L + 2, align=(b.Align.CENTER, b.Align.CENTER, b.Align.MIN)).moved(b.Location((0, 0, -1)))
        shape = body
        if P.split:
            mid = L / 2
            lower = body & b.Box(4 * R, 4 * R, mid, align=(b.Align.CENTER, b.Align.CENTER, b.Align.MIN))
            upper = body & b.Box(4 * R, 4 * R, L - mid, align=(b.Align.CENTER, b.Align.CENTER, b.Align.MIN)).moved(b.Location((0, 0, mid)))
            r0 = br + 1.0 if br > 0 else 2.0
            r1 = R - P.depth - 1.0
            if r1 - r0 >= 2.0:
                w = r1 - r0
                tongue = b.Box(w, 2.0, 2.0, align=(b.Align.MIN, b.Align.CENTER, b.Align.MIN)).moved(b.Location((r0, 0, mid)))
                groove = b.Box(w + 0.4, 2.3, 2.3, align=(b.Align.MIN, b.Align.CENTER, b.Align.MIN)).moved(b.Location((r0 - 0.2, 0, mid)))
                lower = lower + tongue
                upper = upper - groove
            shape = b.Compound([lower, upper])
        fd, path = tempfile.mkstemp(suffix=".step")
        os.close(fd)
        try:
            b.export_step(shape, path)
            with open(path, "rb") as f:
                data = f.read()
        finally:
            os.remove(path)
        _CACHE[key] = data
        return data
    except Exception:
        return None
