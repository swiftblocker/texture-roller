"""Builds every output file in memory (zip) and optionally writes the folder. No build123d here except body.py (lazy)."""
from __future__ import annotations
import io
import json
import math
import time
import zipfile
import numpy as np
from PIL import Image

from . import art as artmod, api as apimod, derived as derivedmod, rules as rulesmod, mesh as meshmod, relief, layout as layoutmod, body
from . import override as overmod
from .params import Params, ParamError

STRIP_DEPTHS = (0.8, 1.2, 1.6, 2.0, 2.5)


# ------------------------------------------------------------------ writers
def stl_bytes(V, F):
    tri = V[F].astype(np.float32)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = n / np.where(ln > 0, ln, 1)
    dt = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec = np.zeros(len(F), dt)
    rec["n"] = n
    rec["v"] = tri
    return b"pottery roller engine".ljust(80, b" ") + np.uint32(len(F)).tobytes() + rec.tobytes()


def threemf_bytes(parts):
    """parts: list of (name, V, F). Minimal 3MF, millimetre units."""
    res, items = [], []
    for i, (name, V, F) in enumerate(parts, 1):
        vf = '<vertex x="%.4f" y="%.4f" z="%.4f"/>'
        vs = "".join([vf % (a, b, c) for a, b, c in V.tolist()])
        tf = '<triangle v1="%d" v2="%d" v3="%d"/>'
        ts = "".join([tf % (a, b, c) for a, b, c in F.tolist()])
        res.append('<object id="%d" name="%s" type="model"><mesh><vertices>%s</vertices><triangles>%s</triangles></mesh></object>'
                   % (i, name, vs, ts))
        items.append('<item objectid="%d"/>' % i)
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources>%s</resources><build>%s</build></model>'
             % ("".join(res), "".join(items)))
    ct = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
    return bio.getvalue()


def png_bytes(arr, mode=None):
    im = Image.fromarray(arr)
    bio = io.BytesIO()
    im.save(bio, "PNG")
    return bio.getvalue()


def slab_preview(P, K):
    """Gray relief shading of the clay image K (mm, picture order), two revolutions side by side."""
    Kt = np.concatenate([K, K], axis=1)
    gy, gx = np.gradient(Kt)
    p = 1.0
    nx, ny, nz = -gx / p, gy / p, np.ones_like(Kt)
    nn = np.sqrt(nx * nx + ny * ny + nz * nz)
    light = np.array([-0.5, 0.6, 0.62])
    sh = (nx * light[0] + ny * light[1] + nz * light[2]) / nn
    base = 205 - 55 * (Kt / max(P.depth, 1e-6))
    img = np.clip(base + 120 * (sh - 0.62), 0, 255).astype(np.uint8)
    return png_bytes(img)


# ------------------------------------------------------------------ sheet
def sheet_md(P, dv, rules, can, F, files, notes=(), over=None):
    d = P.depth
    lh = derivedmod.layer_height(P)
    lines = [f"# Roller sheet", "",
             f"Diameter {P.diameter:g} mm, length {P.length:g} mm, relief {d:g} mm, draft {P.draft_deg:g} deg. "
             f"Circumference {dv['C']:.2f} mm, repeat {dv['repeat_width']:.2f} mm x {P.n_around:g} around.",
             f"Bore {P.bore_used:g} mm. Art {P.art_source}. Mirror {'ON' if P.mirror else 'OFF'}, "
             f"{'art stands up' if P.invert else 'art pressed in'}.", ""]
    lines += ["## Print settings (R51-R55)", "",
              "- Printer: Bambu X1C, 0.4 mm nozzle. Print upright (axis vertical), no supports (R51, R53).",
              f"- Layer height {lh:g} mm (0.12-0.16 for relief up to 1.5 mm, up to 0.20 mm deeper) (R52).",
              "- Material: PLA is fine; PETG if it will be washed in warm water. No brass nozzle for tableware (R54, R63).",
              "- At least 3 perimeters, 15 % gyroid infill (R55).",
              f"- Brim: {'yes, length over diameter is %.1f' % dv['LD'] if dv['LD'] > 5 else 'optional'} (R06).",
              f"- Estimate: {dv['grams']:.0f} g, about {dv['print_minutes'] / 60:.1f} h (rough).", ""]
    if P.split:
        lines += ["- Two halves: print both upright. The tongue on half A fits the groove on half B; line up the notch marks / theta 0.", ""]
    lines += ["## Before you roll (R45-R49)", "",
              "- Dust the roller lightly with cornstarch. Oil in the grooves for detailed work (R45).",
              f"- Clay: {P.clay_state}, {P.clay_body}. Slab at least {max(6.0, 2 * d + 3):g} mm thick (R48).",
              "- Roll once, light even pressure, same pressure at both ends. Do not re-roll the same strip (R49).",
              "- Start each pass at a different spot to break up the repeat (R37).",
              f"- Fired size: {dv['fired']['image_height_mm']:.0f} mm tall ({P.clay_body}, {dv['fired']['shrink_pct']:g} % shrink) (R27).",
              "- Test the dowel fit with the test strip first (R56).", ""]
    lines += ["## Rules", "", "| Rule | Result | Note |", "|---|---|---|"]
    for r in rules:
        st = "INFO" if r["action"] == "INFO" else ("ok" if r["ok"] else r["action"])
        lines.append(f"| {r['id']} | {st} | {r['msg'].replace('|', '/')} |")
    lines += ["", "Export " + ("allowed." if can else ("ALLOWED BY THE OWNER over the stop items below (R86)." if over else "BLOCKED. Fix the BLOCK rules above.")), ""]
    if over:
        lines += overmod.sheet_block(over["stops"], over.get("notes", ()))
    if notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
    lines += ["## Files", ""] + [f"- {f}" for f in files] + [""]
    return "\n".join(lines)


def _aggregate(vals):
    return {
        "watertight": all(v["watertight"] for v in vals), "winding_consistent": all(v["winding_consistent"] for v in vals),
        "volume": min(v["volume"] for v in vals), "bbox_error": max(v["bbox_error"] for v in vals),
        "bad_rays": sum(v["bad_rays"] for v in vals), "mesh_t_min": min(v["mesh_t_min"] for v in vals),
        "triangles": sum(v["triangles"] for v in vals),
    }


def _finish(P, F, dv, rules, can, files, extra_notes, prefix_files, strip=False, over=None):
    vis, can2 = rulesmod.summarize(rules)
    sidecar = {"engine": "pottery-roller", "created": time.strftime("%Y-%m-%d %H:%M:%S"),
               "params": apimod.resolved(P, F), "derived": {k: v for k, v in dv.items()},
               "rules_all": rules, "accepted_warnings": [r["id"] for r in rules if r["action"] == "WARN" and not r["ok"]],
               "art_report": F.lay.art_report, "files": list(prefix_files) + ["roller.json", "sheet.md"]}
    if over:
        sidecar["exported_anyway"] = {"rule": "R86", "stop_items": over["stops"], "ids": over["ids"], "notes": over.get("notes", [])}
    files["roller.json"] = json.dumps(sidecar, indent=1, default=float).encode("utf-8")
    files["sheet.md"] = sheet_md(P, dv, rules, can2, F, sidecar["files"], extra_notes, over).encode("utf-8")
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as z:
        for k, v in files.items():
            z.writestr(k, v)
    out = {"zip": bio.getvalue(), "files": list(files.keys()), "rules": vis, "blocked": not can2 and not over, "_files": files}
    if over:
        out["override"] = {"ids": over["ids"], "stops": over["stops"], "notes": over.get("notes", [])}
    return out


def _stops(rules):
    """BLOCK rules that failed, as (id, message)."""
    return [(r["id"], r["msg"]) for r in rules if r["action"] == "BLOCK" and not r["ok"]]


def _revalidate(m, old, expected):
    """Measure a repaired mesh again. The repair renumbers vertices, so the wall measurement from before is kept."""
    V, F = m.vertices, m.faces
    w, c = meshmod.edge_checks(F, len(V))
    bb = m.bounds
    dia = max(bb[1][0] - bb[0][0], bb[1][1] - bb[0][1])
    err = max(abs(dia - expected[0]), abs((bb[1][2] - bb[0][2]) - expected[1]))
    return dict(old, watertight=w, winding_consistent=c, volume=float(m.volume), bbox_error=float(err),
                bad_rays=meshmod.radial_ray_check(m, 40), triangles=int(len(F)), vertices=int(len(V)))


def _repair_parts(parts, vals):
    """R86: one cheap repair pass on every part that is not a closed solid, then measure it again."""
    import trimesh
    out, nv, notes = [], [], []
    for (name, m, exp), v in zip(parts, vals):
        if v["watertight"] and v["winding_consistent"]:
            out.append((name, m, exp)); nv.append(v)
            continue
        V2, F2, info = overmod.repair_mesh(m.vertices, m.faces)
        notes.append("%s: %s" % (name, overmod.repair_note(info)))
        if info["kept"] == "repaired":
            m2 = trimesh.Trimesh(vertices=V2, faces=F2, process=False)
            m2.metadata.update(m.metadata)
            out.append((name, m2, exp)); nv.append(_revalidate(m2, v, exp))
        else:
            out.append((name, m, exp)); nv.append(v)
    return out, nv, notes


def _mark_files(files):
    """R86: every STL and 3MF carries -override in its name."""
    return {(overmod.mark_name(k) if k.lower().endswith((".stl", ".3mf")) else k): v for k, v in files.items()}


def _build(P, upload, upload_name, override, extra_notes=()):
    F = apimod.compute(P, upload, upload_name, P.pitch_export)
    dv = derivedmod.derived(P, F)
    rules = rulesmod.evaluate(P, F, dv)
    vis, can = rulesmod.summarize(rules)
    files, notes = {}, list(extra_notes)
    repair_notes = []
    if can or override:
        parts = meshmod.build_parts(P, F.Rm, F.lay)
        vals = [meshmod.validate(m, exp) for _, m, exp in parts]
        val = _aggregate(vals)
        rules = rulesmod.evaluate(P, F, dv, val)
        vis, can = rulesmod.summarize(rules)
        if override and not can and any(not (v["watertight"] and v["winding_consistent"]) for v in vals):
            parts, vals, repair_notes = _repair_parts(parts, vals)
            val = _aggregate(vals)
            rules = rulesmod.evaluate(P, F, dv, val)
            vis, can = rulesmod.summarize(rules)
        dv["triangles_actual"] = val["triangles"]
        if can or override:
            outp = []
            for name, m, exp in parts:
                V = m.vertices - np.array([0, 0, m.vertices[:, 2].min()])
                F_ = m.faces.astype(np.int64)
                files[name + ".stl"] = stl_bytes(V, F_)
                outp.append((name, V, F_))
            files["roller.3mf"] = threemf_bytes(outp)
            step = body.step_bytes(P, F.lay)
            if step is None:
                notes.append("body.step skipped: STEP needs the desktop install (build123d).")
                rules.append(rulesmod._res("INFO_STEP", "INFO", "STEP needs the desktop install (build123d). body.step was not written.", None, None, True))
            else:
                files["body.step"] = step
            K = apimod.clay_depth(F)
            files["heightmap_16bit.png"] = png_bytes(np.clip(np.round(K / P.depth * 65535), 0, 65535).astype(np.uint16), "I;16")
            files["slab_preview.png"] = slab_preview(P, K)
    vis, can = rulesmod.summarize(rules)
    over = None
    stops = _stops(rules) if (override and files) else []
    if stops:
        over = {"stops": [m for _i, m in stops], "ids": [i for i, _m in stops], "notes": repair_notes + list(extra_notes)}
        files = _mark_files(files)
    else:
        notes += repair_notes
    return _finish(P, F, dv, rules, can, files, notes, list(files), over=over)


_PLAIN = "R86: Export anyway cannot fix this. "


def _plain_error(exc):
    """A message that says what to change, never Python text."""
    t = overmod.ascii_text(str(exc))
    if isinstance(exc, artmod.ArtError):
        if "flat colour" in t:
            return _PLAIN + "The picture is one flat colour, so there is nothing to put on the roller. Use a picture with something drawn on it."
        if "no file" in t:
            return _PLAIN + "No picture was uploaded. Upload a picture first."
        return _PLAIN + "The picture could not be used (%s). Use a PNG, JPEG, WEBP or SVG with something drawn on it." % t
    return _PLAIN + "A setting is not a usable value (%s). Reset that setting." % t


def build_zip(params, upload=None, upload_name=None):
    P = Params.from_dict(params)
    if not P.export_anyway:
        return _build(P, upload, upload_name, False)
    # R86: a picture that cannot be read stays a plain message. An unexpected engine error is tried once more
    # on a grid twice as coarse, and only then becomes a plain message.
    def msg(m):
        return {"zip": b"", "files": [], "rules": [], "blocked": True, "message": m, "_files": {}}
    try:
        return _build(P, upload, upload_name, True)
    except (artmod.ArtError, ParamError) as exc:
        return msg(_plain_error(exc))
    except Exception:
        pass
    try:
        P2 = P.replace(pitch_export=P.pitch_export * 2.0)
        return _build(P2, upload, upload_name, True,
                      ["R86: the first build failed, so this one was made on a coarser grid (%g mm instead of %g mm)." % (P2.pitch_export, P.pitch_export)])
    except (artmod.ArtError, ParamError) as exc:
        return msg(_plain_error(exc))
    except Exception:
        return msg(_PLAIN + "The engine could not build this roller, even on a coarser grid. Try a smaller diameter or length, fewer repeats, or a simpler picture.")


# ------------------------------------------------------------------ test strip
def build_strip(params):
    P0 = Params.from_dict(params)
    P = P0.replace(length=40.0, split=False, band=min(P0.band, 2.0) if P0.bands_on else P0.band, depth=max(STRIP_DEPTHS),
                   n_along=None, alignment_ticks=False)
    F = apimod.compute(P, None if P.art_source.startswith("pattern:") else artmod.LAST[0], artmod.LAST[1], P.pitch_export)
    lay = F.lay
    s = relief.signed_distance(lay.top_os, lay.pz / lay.os, lay.pt / lay.os)
    z = np.arange(lay.M) * lay.pz
    zb = P.band_eff
    sec = np.clip(((z - zb) / max(40.0 - 2 * zb, 1e-6) * 5).astype(int), 0, 4)
    in_band = (z < zb) | (z > 40.0 - zb)
    Hs = np.zeros((lay.M, lay.N))
    R = np.zeros_like(Hs)
    for k, dk in enumerate(STRIP_DEPTHS):
        Pk = P.replace(depth=dk)
        Hk = relief.height_field(Pk, lay, s)
        rk = P.R - dk + Hk
        rows = (sec == k) & ~in_band
        R[rows] = rk[rows]
        Hs[rows] = Hk[rows]
    R[in_band] = P.R
    Hs[in_band] = P.depth
    c = P.end_chamfer
    if c > 0:
        zz = z[:, None]
        R = np.minimum(R, P.R - c + zz)
        R = np.minimum(R, P.R - c + (40.0 - zz))
    F.Rm, F.H = R, Hs
    dv = derivedmod.derived(P, F)
    rules = rulesmod.evaluate(P, F, dv)
    vis, can = rulesmod.summarize(rules)
    files = {}
    if can:
        m = meshmod.build_part(R, z, P.bore_used)
        val = meshmod.validate(m, (P.diameter, 40.0))
        rules = rulesmod.evaluate(P, F, dv, val)
        vis, can = rulesmod.summarize(rules)
        if can:
            V = m.vertices
            files["test_strip.stl"] = stl_bytes(V, m.faces.astype(np.int64))
            files["test_strip.3mf"] = threemf_bytes([("test_strip", V, m.faces.astype(np.int64))])
    r = _finish(P, F, dv, rules, can, files, ["Test strip: 40 mm, depth bands %s mm from the bottom." % ", ".join("%g" % x for x in STRIP_DEPTHS)],
                list(files))
    return r


def write_dir(r, out_dir):
    import os
    os.makedirs(out_dir, exist_ok=True)
    names = []
    for k, v in r["_files"].items():
        with open(os.path.join(out_dir, k), "wb") as f:
            f.write(v)
        names.append(os.path.join(out_dir, k))
    return {"files": names, "rules": r["rules"], "blocked": r["blocked"], "override": r.get("override"), "message": r.get("message")}
