"""Rule evaluation. Thresholds come from data/checks.json (copy of skill/.../checks.json)."""
from __future__ import annotations
import json
import math
import operator
from pathlib import Path
from .params import STATE_DEPTH, SHRINK

_OPS = {">": operator.gt, "<": operator.lt, "<=": operator.le, ">=": operator.ge}
_CHECKS = None
REQUIRED_T = 1.6  # R70 uses the hard R09 limit


def checks():
    global _CHECKS
    if _CHECKS is None:
        p = Path(__file__).parent / "data" / "checks.json"
        _CHECKS = {c["id"]: c for c in json.loads(p.read_text(encoding="utf-8"))["checks"]}
    return _CHECKS


UNITS = {"R01": "mm", "R02": "mm", "R03": "mm", "R04a": "mm", "R04b": "mm", "R05": "", "R06": "", "R08": "mm",
         "R09a": "mm", "R09b": "mm", "R14": "mm", "R15a": "mm", "R15b": "mm", "R16": "", "R19a": "mm", "R19b": "mm",
         "R20": "mm", "R21": "mm", "R22": " deg", "R25a": "", "R25b": "", "R31a": "", "R31b": "", "R38a": "mm",
         "R38b": "mm", "R42": "mm", "R43": "mm", "R60": "mm", "R62": "mm", "R64": " triangles", "R68": "mm",
         "R70": "mm"}
LABEL = {"R01": "body length", "R02": "body length", "R03": "art plus end bands", "R04a": "diameter",
         "R04b": "diameter", "R05": "length over diameter", "R06": "length over diameter",
         "R08": "wrap width minus circumference", "R09a": "wall under the deepest recess",
         "R09b": "wall under the deepest recess", "R14": "relief depth", "R15a": "relief depth",
         "R15b": "relief depth", "R16": "depth over diameter", "R19a": "narrowest raised feature",
         "R19b": "narrowest raised feature", "R20": "narrowest groove", "R21": "narrowest gap",
         "R22": "steepest sidewall draft", "R25a": "raised fraction", "R25b": "raised fraction",
         "R31a": "art stretch", "R31b": "art stretch", "R38a": "seam step", "R38b": "seam step",
         "R42": "end band", "R43": "end chamfer", "R60": "printed height", "R62": "length",
         "R64": "mesh size", "R68": "size error", "R70": "measured wall"}


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.3g}"
    return str(v)


def _res(rid, action, msg, value=None, limit=None, ok=False):
    return {"id": rid, "action": action, "msg": msg, "value": None if value is None else float(value),
            "limit": None if limit is None else float(limit), "ok": bool(ok)}


def evaluate(P, F, dv, val=None, ref=None, per_part=None):
    """P Params, F field object, dv derived dict, val mesh validation dict (export only), ref expected dims."""
    ck = checks()
    lay, met = F.lay, F.metrics
    L, D, d = P.length, P.diameter, P.depth
    bore = P.bore_used
    t_min = dv["wall_min"]
    tri = dv["triangles_export"]
    printed_h = (L / 2 + 2.0) if P.split else L
    V = {}  # id -> (value, limit) or None
    V["R01"] = (L, None)
    V["R02"] = (L, None)
    V["R03"] = (lay.art_axial + 2 * P.band_eff, L)
    V["R04a"] = (D, None)
    V["R04b"] = (D, None)
    V["R05"] = (L / D, None) if bore == 0 else None
    V["R06"] = (L / D, None)
    V["R08"] = (abs(lay.wrap_width - P.C), None)
    V["R09a"] = (t_min, None) if bore > 0 else None
    V["R09b"] = (t_min, 2.0 if L <= 160 else 3.0) if bore > 0 else None
    V["R14"] = (d, None)
    V["R15a"] = (d, None)
    V["R15b"] = (d, None)
    V["R16"] = (d / D, None)
    V["R19a"] = (met["min_raised_width"], None) if met["min_raised_width"] is not None else None
    V["R19b"] = V["R19a"]
    V["R20"] = (met["min_recess_width"], max(1.0, 0.8 * d)) if met["min_recess_width"] is not None else None
    V["R21"] = (met["min_gap"], None) if met["min_gap"] is not None else None
    V["R22"] = (met["min_draft_deg"], None) if met["min_draft_deg"] is not None else None
    V["R25a"] = (met["raised_fraction"], None)
    V["R25b"] = (met["raised_fraction"], None)
    V["R31a"] = (lay.stretch_error, None)
    V["R31b"] = (lay.stretch_error, None)
    V["R38a"] = (met["seam_edge_diff"], None)
    V["R38b"] = (met["seam_edge_diff"], None)
    V["R42"] = (P.band, None) if P.bands_on else None
    V["R43"] = (P.end_chamfer, None)
    V["R60"] = (printed_h, 250.0)
    V["R62"] = (L, P.cnc_rotary_max_length) if P.cnc_rotary_max_length > 0 else None
    V["R64"] = (tri, None)
    out = []
    grid_tol = F.pitch if (val is None and (P.text or "").strip() and F.pitch > P.pitch_export) else 0.0
    for rid, c in ck.items():
        if rid in V:
            vl = V[rid]
            if vl is None:
                continue
            v, lim = vl
            if lim is None:
                lim = c["value"]
            bad = _OPS[c["op"]](v, lim)
            u = UNITS.get(rid, "")
            if bad and grid_tol and rid in ("R19a", "R19b", "R20", "R21") and not _OPS[c["op"]](v + grid_tol, lim):
                # lettering on the coarse preview grid: a width within one grid cell of its limit
                # cannot be told apart from a pass. The export re-measures at pitch_export.
                out.append(_res(rid, c["action"], f"{rid}: ok on the {_fmt(F.pitch)} mm preview grid ({LABEL.get(rid, 'value')} {_fmt(v)}{u}, limit {c['op']} {_fmt(lim)}{u}); the export measures it again at {_fmt(P.pitch_export)} mm.", v, lim, True))
                continue
            if bad:
                msg = f"{rid}: {c['msg']}. {LABEL.get(rid, 'value')} is {_fmt(v)}{u}, limit {c['op']} {_fmt(lim)}{u}."
            else:
                msg = f"{rid}: ok. {LABEL.get(rid, 'value')} {_fmt(v)}{u} (limit {c['op']} {_fmt(lim)}{u})."
            out.append(_res(rid, c["action"], msg, v, lim, not bad))
    # custom checks
    n = P.n_around
    bad29 = (abs(n - round(n)) > 1e-9) or n < 1
    out.append(_res("R29", "BLOCK", f"R29: Repeat around must be a whole number of 1 or more. n_around is {_fmt(float(n))}.",
                    n, 1, not bad29))
    bad32 = P.offset != "none" and P.n_int == 1
    out.append(_res("R32", "BLOCK", "R32: Offset needs 2 or more repeats around. n_around is %d, offset is %s." % (P.n_int, P.offset),
                    P.n_int, 2, not bad32))
    if lay.flags.get("odd_half_drop"):
        out.append(_res("R32b", "WARN", "R32: Half-drop with an odd repeat count leaves one mismatched column at the seam. Use an even count.",
                        P.n_int, None))
    if lay.flags.get("rotation_snapped"):
        out.append(_res("R33", "WARN", "R33: Rotation must be 0, 90, 180 or 270 degrees. Snapped to the nearest.", P.rotation, None))
    if 0 < P.spacing < 1.0:
        out.append(_res("R34", "WARN", f"R34: Spacing {_fmt(P.spacing)} mm is under 1.0 mm and becomes a groove or land too narrow for clay.", P.spacing, 1.0))
    if P.edge_round < 0.3:
        out.append(_res("R24", "WARN", f"R24: Edge round {_fmt(P.edge_round)} mm is under 0.3 mm. Sharp edges tear clay.", P.edge_round, 0.3))
    if met["thin_components"]:
        out.append(_res("R26", "WARN", f"R26: {met['thin_components']} feature(s) thinner than {_fmt(2 * P.nozzle)} mm (2 x nozzle) will not print. Thicken or remove them.",
                        met["thin_components"], 2 * P.nozzle))
    tr = lay.art_report.get("text") if isinstance(lay.art_report, dict) else None
    if tr:
        if tr.get("min_size_mm"):
            out.append(_res("R74", "WARN", f"R74: Letter strokes are {_fmt(tr['stroke_mm'])} mm, under {_fmt(tr['stroke_limit_mm'])} mm. Make the text at least {_fmt(tr['min_size_mm'])} mm tall or pick a bolder font.",
                            tr["stroke_mm"], tr["stroke_limit_mm"]))
        if tr.get("kept", 1.0) < 0.85:
            out.append(_res("R79", "WARN", f"R79: To keep 1 mm clay gaps, {round(100 * (1 - tr['kept']))}% of the letter area was cut away. Make the text bigger or add letter spacing.",
                            tr["kept"], 0.85))
        if tr.get("clipped"):
            out.append(_res("R75", "WARN", "R75: The text runs into the end band or off the roller. Move it toward the middle or make it smaller.", None, None))
        if tr.get("too_big"):
            out.append(_res("R76", "WARN", f"R76: The text is {_fmt(tr['width_mm'])} x {_fmt(tr['height_mm'])} mm, bigger than the roller can carry, so it is not drawn. Make it smaller or shorter.", None, None))
        elif tr.get("overlap"):
            out.append(_res("R76", "WARN", "R76: The text copies are wider than the space for each one and run into each other. " + (f"Make the text {_fmt(tr['fit_size_mm'])} mm tall or less, or use fewer copies." if tr.get("fit_size_mm") else "Use fewer copies or smaller text."), None, None))
        if tr.get("contrast", 1.0) < 0.3:
            out.append(_res("R77", "WARN", "R77: The letters match what is around them and will not show. Add a frame or switch pressed / raised.", tr["contrast"], 0.3))
        if tr.get("chars_cut"):
            out.append(_res("R78", "WARN", "R78: Text is cut to the first 60 characters.", None, 60))
        if tr.get("lines_cut"):
            out.append(_res("R78", "WARN", f"R78: {tr['lines_cut']} lines typed; only the first 3 are used.", tr["lines_cut"], 3))
        if tr.get("missing"):
            out.append(_res("R78", "WARN", "R78: This font has no letter for: " + " ".join(tr["missing"]).encode("ascii", "replace").decode() + ". They print as spaces.", None, None))
    if P.glaze_flag and d < 1.2:
        out.append(_res("R28", "WARN", f"R28: Relief {_fmt(d)} mm is under 1.2 mm and glaze will soften it.", d, 1.2))
    if P.cnc_rotary_max_length > 0 and met["min_recess_width"] is not None and met["min_recess_width"] < 3.175:
        out.append(_res("R61", "WARN", f"R61: Narrowest groove {_fmt(met['min_recess_width'])} mm is under the 3.175 mm (1/8 in) CNC bit.",
                        met["min_recess_width"], 3.175))
    # R70 from the field wall (the mesh value replaces it at export)
    if bore > 0:
        tm = val["mesh_t_min"] if val else t_min
        out.append(_res("R70", "BLOCK", f"R70: Measured wall {_fmt(tm)} mm vs required {_fmt(REQUIRED_T)} mm." + ("" if val else " (from the height field; re-measured on the mesh at export)"),
                        tm, REQUIRED_T, tm >= REQUIRED_T))
    if val is not None:
        out.append(_res("R65", "BLOCK", "R65: Mesh is " + ("watertight." if val["watertight"] else "NOT watertight."), float(val["watertight"]), 1, val["watertight"]))
        out.append(_res("R66", "BLOCK", f"R66: Volume {_fmt(val['volume'])} mm3, winding " + ("consistent." if val["winding_consistent"] else "INCONSISTENT."),
                        val["volume"], 0, val["volume"] > 0 and val["winding_consistent"]))
        si = 0 if (val["mesh_t_min"] > 0 and val["bad_rays"] == 0) else 1
        out.append(_res("R67", "BLOCK", "R67: Self-intersections: " + ("none found." if not si else "possible."), si, 0, si == 0))
        out.append(_res("R68", "BLOCK", f"R68: Bounding box error {_fmt(val['bbox_error'])} mm, limit 0.05 mm.", val["bbox_error"], 0.05, val["bbox_error"] <= 0.05))
        out.append(_res("R69", "BLOCK", f"R69: Rays crossing the surface more than once: {val['bad_rays']}.", val["bad_rays"], 0, val["bad_rays"] == 0))
        out.append(_res("R41", "INFO", "R41: Seam vertices are welded (no duplicate column at theta 0).", None, None, True))
    # info
    I = []
    I.append(("R07", f"R07: One revolution is {_fmt(P.C)} mm. Each repeat is {_fmt(lay.cell_w)} mm wide, {n if isinstance(n, int) else _fmt(n)} around."))
    I.append(("R12", f"R12: A 254 mm slab takes {_fmt(254.0 / P.C)} revolutions."))
    I.append(("R10", "R10: Hollow body on a dowel." if bore > 0 else "R10: Solid body (no bore)."))
    I.append(("R13", f"R13: Relief {_fmt(d)} mm (usual range 0.8 to 3.0 mm)."))
    lo, hi = STATE_DEPTH[P.clay_state]
    I.append(("R17", f"R17: For {P.clay_state} clay, relief of {lo} to {hi} mm is typical. Yours is {_fmt(d)} mm."))
    I.append(("R18", {"porcelain": "R18: Porcelain holds fine detail but dries fast.", "earthenware": "R18: Earthenware softens detail. Add 0.3 mm of relief.",
                      "stoneware": "R18: Stoneware is the baseline body.", "paper": "R18: Paper clay: test a sample first."}[P.clay_body]))
    I.append(("R27", f"R27: Fired in {P.clay_body} ({_fmt(SHRINK[P.clay_body])} % shrink) the art is {_fmt(dv['fired']['image_height_mm'])} mm tall and each repeat {_fmt(dv['fired']['repeat_width_mm'])} mm wide."))
    I.append(("R30", f"R30: The art covers {_fmt(lay.n_along)} repeats along the roller; partial tiles at the ends are fine."))
    I.append(("R36", "R36: Art pressed in (clay shows the art as a recess)." if not P.invert else "R36: Art stands up (clay shows the art as raised)."))
    I.append(("R35", "R35: Mirror is ON: the clay reads the way the art was drawn." if P.mirror else "R35: Mirror is OFF: the clay shows the art flipped left to right. Text will read backwards."))
    I.append(("R39", f"R39/R40: Seam method used: {lay.method_used}; art rotated {_fmt(lay.seam_theta_used)} deg."))
    I.append(("R37", "R37: Start each pass at a different spot to break up the repeat."))
    I.append(("R45", "R45: Dust with cornstarch before rolling; oil the grooves for fine detail."))
    I.append(("R48", f"R48: Use a slab at least {_fmt(max(6.0, 2 * d + 3))} mm thick."))
    I.append(("R49", "R49: Roll once with light, even pressure."))
    I.append(("R56", f"R56: Printed bore {_fmt(bore)} mm (rod or dowel plus {_fmt(P.bore_clearance)} mm slip fit)." if bore > 0 else "R56: No bore."))
    I.append(("R63", "R63: Use standard filament and a hardened or stainless nozzle for tableware work."))
    if P.alignment_ticks:
        I.append(("R44", "R44: V notches on the end bands mark the seam."))
    for rid, m in I:
        out.append(_res(rid, "INFO", m, None, None, True))
    return out


def summarize(rules):
    """-> (visible rules for the UI, can_export)."""
    vis = [r for r in rules if (not r["ok"]) or r["action"] == "INFO"]
    can = not any(r["action"] == "BLOCK" and not r["ok"] for r in rules)
    return vis, can
