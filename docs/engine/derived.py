"""Derived numbers: C, repeats, fired sizes, weight, print time, triangle count, repeat solver."""
from __future__ import annotations
import math
import numpy as np
from . import layout as layoutmod
from .params import SHRINK

PLA_G_CM3 = 1.24
# print-time model (documented): extruded volume / 10 mm3/s effective flow + 3 s per layer
# (X1C, 0.4 nozzle, quality profile, PLA). Rough: expect +-30 %.
FLOW_MM3_S = 10.0
LAYER_S = 3.0
WALLS = 3
LINE_W = 0.45
INFILL = 0.15


def layer_height(P):
    return 0.16 if P.depth <= 1.5 else 0.20


def triangles(P, pitch):
    N, M, _, _ = layoutmod.grid_dims(P, pitch)
    t = 2 * N * (M - 1)
    if P.bore_used > 0:
        t += 6 * N + 4 * N
    else:
        t += 2 * N
    if P.split:
        t += 12 * N // 4
    return int(t)


def volume_mm3(P, Rm, lay):
    M, N = Rm.shape
    ring = 0.5 * (2 * math.pi / N) * (Rm ** 2).sum(1)
    v = float((ring[:-1] + ring[1:]).sum() * 0.5 * lay.pz)
    return v - math.pi * (P.bore_used / 2) ** 2 * P.length


def derived(P, F):
    lay, Rm, met = F.lay, F.Rm, F.metrics
    C = P.C
    bore_r = P.bore_used / 2
    wall = float(Rm.min() - bore_r) if bore_r > 0 else float(Rm.min())
    shrink = SHRINK[P.clay_body]
    vol = volume_mm3(P, Rm, lay)
    area = (C * P.length * met["area_factor"]) + math.pi * P.bore_used * P.length \
        + 2 * (math.pi * P.R ** 2 - math.pi * bore_r ** 2)
    shell = min(area * WALLS * LINE_W, vol)
    printed = shell + INFILL * (vol - shell)
    grams = printed / 1000.0 * PLA_G_CM3
    layers = P.length / layer_height(P)
    minutes = (printed / FLOW_MM3_S + layers * LAYER_S) / 60.0
    f = 1 - shrink / 100.0
    return {
        "C": C, "repeat_width": lay.cell_w, "tile_height": lay.tile_h, "n_along": lay.n_along,
        "image_height_mm": lay.art_axial,
        "revs_per_254": 254.0 / C, "LD": P.length / P.diameter, "wall_min": wall,
        "fired": {"shrink_pct": shrink, "image_height_mm": lay.art_axial * f, "repeat_width_mm": lay.cell_w * f,
                  "bodies": {k: {"shrink_pct": v, "image_height_mm": lay.art_axial * (1 - v / 100),
                                 "repeat_width_mm": lay.cell_w * (1 - v / 100)} for k, v in SHRINK.items()}},
        "grams": float(grams), "print_minutes": float(minutes),
        "triangles_export": triangles(P, P.pitch_export),
        "volume_mm3": float(vol),
    }


def solve_repeat(tile_width, d_min=25, d_max=100, max_n=12):
    out = []
    for n in range(1, int(max_n) + 1):
        d = n * tile_width / math.pi
        dd = min(max(d, d_min), d_max)
        dd = round(dd, 1)
        C = math.pi * dd
        stretch = (C / n - tile_width) / tile_width * 100.0
        if abs(stretch) > 10:
            continue
        out.append({"diameter": dd, "n_around": n, "C": C, "stretch_pct": stretch})
    out.sort(key=lambda r: (round(abs(r["stretch_pct"]), 1), abs(r["diameter"] - 45.0)))
    return out[:6]
