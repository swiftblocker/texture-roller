"""R86 Export anyway. Shared helpers for the three tabs.

The owner may override any stop item. The file is marked "-override" and lists what was overridden.
Nothing here is used unless the params carry export_anyway = true; the preview never reads the flag.
No shapely, no buffers: numpy and trimesh only.
"""
from __future__ import annotations
import numpy as np

SUFFIX = "-override"
HEAD = "Exported anyway over these stop items"
RULE = "R86"


def mark_name(filename: str) -> str:
    """'a.zip' -> 'a-override.zip'; no double mark."""
    if filename.endswith(SUFFIX) or (SUFFIX + ".") in filename:
        return filename
    i = filename.rfind(".")
    return filename + SUFFIX if i <= 0 else filename[:i] + SUFFIX + filename[i:]


def as_flag(v) -> bool:
    return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")


def ascii_text(s: str) -> str:
    return str(s).encode("ascii", "replace").decode("ascii")


def sheet_block(stops, notes=()):
    """Markdown lines for the sheet: the stop items word for word, then notes."""
    out = ["## " + HEAD, "",
           "R86: Export anyway was ticked. These stop items were overridden. The part may fail in clay or in the printer.", ""]
    out += ["- " + s for s in stops] if stops else ["- (none left after the mesh repair)"]
    for n in notes:
        out.append("- Note: " + n)
    out.append("")
    return out


def result_line(ids):
    ids = [i for i in dict.fromkeys(ids) if i]
    return "Exported anyway over: " + ", ".join(ids) + "." if ids else "Exported anyway."


def repair_mesh(V, F, max_hole_edges=2000):
    """Cheap repair with trimesh: merge vertices, drop degenerate and duplicate faces, fix normals, fill small holes.
    -> (V, F, info). Never raises; on any failure returns the input unchanged. info = {tried, steps, open_edges_before,
    open_edges_after, watertight_before, watertight_after}."""
    info = {"tried": True, "steps": [], "watertight_before": None, "watertight_after": None,
            "open_edges_before": None, "open_edges_after": None, "kept": "original"}
    try:
        import trimesh
        m = trimesh.Trimesh(vertices=np.asarray(V, dtype=np.float64).copy(), faces=np.asarray(F, dtype=np.int64).copy(), process=False)
        info["watertight_before"] = bool(m.is_watertight)
        info["open_edges_before"] = _open_edges(m)
        n0 = len(m.faces)
        m.merge_vertices()
        m.update_faces(m.nondegenerate_faces())
        m.update_faces(m.unique_faces())
        m.remove_unreferenced_vertices()
        info["steps"].append("merged vertices, removed %d degenerate or duplicate faces" % (n0 - len(m.faces)))
        try:
            trimesh.repair.fix_normals(m, multibody=False)
            info["steps"].append("fixed normals")
        except Exception:
            info["steps"].append("normals left as they were")
        if not m.is_watertight and _open_edges(m) <= max_hole_edges:
            try:
                trimesh.repair.fill_holes(m)
                info["steps"].append("filled small holes")
            except Exception:
                info["steps"].append("holes could not be filled")
        info["watertight_after"] = bool(m.is_watertight)
        info["open_edges_after"] = _open_edges(m)
        # keep the repaired mesh unless it is clearly worse than what came in
        if info["open_edges_after"] <= info["open_edges_before"]:
            info["kept"] = "repaired"
            return np.asarray(m.vertices), np.asarray(m.faces), info
    except Exception as exc:                       # never fail an export because a repair did not work
        info["steps"].append("repair skipped (%s)" % type(exc).__name__)
    return np.asarray(V), np.asarray(F), info


def _open_edges(m):
    try:
        e = np.sort(np.asarray(m.edges), axis=1)
        _, cnt = np.unique(e, axis=0, return_counts=True)
        return int((cnt == 1).sum())
    except Exception:
        return -1


def repair_note(info):
    if not info or not info.get("tried"):
        return None
    if info["kept"] != "repaired":
        return "Mesh repair was tried and did not help, so the original mesh is exported (watertight: %s)." % ("yes" if info["watertight_before"] else "no")
    return "Mesh repair (%s): watertight %s -> %s, open edges %s -> %s." % (
        "; ".join(info["steps"]), "yes" if info["watertight_before"] else "no", "yes" if info["watertight_after"] else "no",
        info["open_edges_before"], info["open_edges_after"])
