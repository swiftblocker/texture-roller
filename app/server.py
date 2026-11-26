"""Pottery roller generator: local FastAPI server (127.0.0.1:8790 only).

Calls engine.api when it imports. If it does not, falls back to web/dev_fixture.json
so the UI can be built and checked; /api/status reports which one is live.
"""
import json
import math
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

ENGINE = None
ENGINE_ERROR = None
try:
    import engine.api as ENGINE  # type: ignore
except Exception as exc:  # engine not built yet, or broken
    ENGINE = None
    ENGINE_ERROR = f"{type(exc).__name__}: {exc}"

app = FastAPI(title="Pottery roller generator")
app.mount("/web", StaticFiles(directory=str(WEB)), name="web")


def _fixture():
    with open(WEB / "dev_fixture.json", "r", encoding="utf-8") as fh:
        return json.load(fh)


def _fixture_rules(p):
    rules = []
    L, D = float(p.get("length") or 0), float(p.get("diameter") or 0)
    if L > 254:
        rules.append({"id": "R01", "action": "BLOCK", "msg": "Body length is over the 10 in project limit.", "value": L, "limit": 254.0})
    elif L > 250:
        rules.append({"id": "R02", "action": "WARN", "msg": "Printed upright with a brim, this leaves under 6 mm below the X1C Z limit.", "value": L, "limit": 250.0})
    if 0 < D < 16:
        rules.append({"id": "R04", "action": "BLOCK", "msg": "Diameter under 16 mm deflects under hand pressure.", "value": D, "limit": 16.0})
    if D > 0 and L / D > 8 and p.get("bore_preset") == "none":
        rules.append({"id": "R05", "action": "WARN", "msg": "L/D over 8 with no axle bore.", "value": L / D, "limit": 8.0})
    rules.append({"id": "R07", "action": "INFO", "msg": "One revolution lays down one circumference.", "value": math.pi * D, "limit": None})
    rules.append({"id": "R45", "action": "INFO", "msg": "Dust the roller lightly with cornstarch before rolling.", "value": None, "limit": None})
    return rules


def _fixture_preview(p):
    fx = _fixture()
    D = float(p.get("diameter") or 45)
    L = float(p.get("length") or 250)
    n = max(1, int(p.get("n_around") or 3))
    C = math.pi * D
    fx["derived"].update({"C": C, "repeat_width": C / n, "revs_per_254": 254.0 / C, "LD": L / D})
    fx["params"] = {**p, "bore_diameter_used": 13.0, "seam_theta_deg_used": 0.0}
    fx["rules"] = _fixture_rules(p)
    fx["can_export"] = not any(r["action"] == "BLOCK" for r in fx["rules"])
    fx["fixture"] = True
    return fx


def _parse(params: str):
    try:
        p = json.loads(params)
        if not isinstance(p, dict):
            raise ValueError("params must be an object")
        return p
    except Exception as exc:
        raise HTTPException(400, f"bad params JSON: {exc}")


async def _read_upload(art):
    if art is None:
        return None, None
    return await art.read(), art.filename


def _new_out_dir():
    ts = time.strftime("%Y%m%d-%H%M%S")
    d = OUT / ts
    n = 1
    while d.exists():
        n += 1
        d = OUT / f"{ts}-{n}"
    d.mkdir(parents=True)
    return d


def _fixture_export(p, d):
    pv = _fixture_preview(p)
    side = {"params": p, "rules": pv["rules"], "note": "engine not loaded; fixture sidecar only"}
    (d / "roller.json").write_text(json.dumps(side, indent=2), encoding="utf-8")
    return {"files": ["roller.json"], "rules": pv["rules"], "blocked": not pv["can_export"]}


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/status")
def status():
    return {"engine": ENGINE is not None, "error": ENGINE_ERROR}


@app.post("/api/preview")
async def preview(params: str = Form(...), art: Optional[UploadFile] = File(None)):
    p = _parse(params)
    data, name = await _read_upload(art)
    if ENGINE is None:
        return JSONResponse(_fixture_preview(p))
    try:
        return JSONResponse(ENGINE.preview(p, data, name))
    except Exception as exc:
        raise HTTPException(422, f"{type(exc).__name__}: {exc}")


def _run_export(kind, p, data, name):
    d = _new_out_dir()
    if ENGINE is None:
        res = _fixture_export(p, d)
    else:
        try:
            if kind == "test_strip":
                res = ENGINE.test_strip(p, str(d))
            else:
                res = ENGINE.export(p, data, name, str(d))
        except Exception as exc:
            shutil.rmtree(d, ignore_errors=True)
            raise HTTPException(422, f"{type(exc).__name__}: {exc}")
    res = dict(res)
    res["id"] = d.name
    res["download"] = f"/api/download/{d.name}"
    return JSONResponse(res)


@app.post("/api/export")
async def export(params: str = Form(...), art: Optional[UploadFile] = File(None)):
    p = _parse(params)
    data, name = await _read_upload(art)
    return _run_export("export", p, data, name)


@app.post("/api/fit_portrait")
async def fit_portrait(params: str = Form(...), art: Optional[UploadFile] = File(None)):
    p = _parse(params)
    data, _name = await _read_upload(art)
    if ENGINE is None:
        raise HTTPException(503, "engine not loaded")
    if not data:
        raise HTTPException(400, "no picture")
    try:
        return JSONResponse(ENGINE.fit_portrait(p, data))
    except Exception as exc:
        raise HTTPException(422, f"{type(exc).__name__}: {exc}")


@app.post("/api/test_strip")
async def test_strip(params: str = Form(...)):
    return _run_export("test_strip", _parse(params), None, None)


# ---- cookie cutter tab: results are held in memory (nothing is written to disk) ----
COOKIE_KEEP = {}


@app.post("/api/cookie_preview")
async def cookie_preview(params: str = Form(...), art: Optional[UploadFile] = File(None)):
    p = _parse(params)
    data, name = await _read_upload(art)
    if ENGINE is None:
        raise HTTPException(503, "engine not loaded")
    try:
        return JSONResponse(ENGINE.cookie_preview(p, data, name))
    except Exception as exc:
        raise HTTPException(422, f"{type(exc).__name__}: {exc}")


@app.post("/api/cookie_export")
async def cookie_export(params: str = Form(...), art: Optional[UploadFile] = File(None)):
    p = _parse(params)
    data, name = await _read_upload(art)
    if ENGINE is None:
        raise HTTPException(503, "engine not loaded")
    try:
        r = ENGINE.cookie_export(p, data, name)
    except Exception as exc:
        raise HTTPException(422, f"{type(exc).__name__}: {exc}")
    out = {"blocked": bool(r["blocked"]), "checks": r["checks"], "filename": r["filename"], "bytes": len(r["stl"])}
    if not r["blocked"]:
        key = time.strftime("%Y%m%d-%H%M%S") + "-%d" % len(COOKIE_KEEP)
        COOKIE_KEEP[key] = (r["stl"], r["filename"], r["sidecar"])
        while len(COOKIE_KEEP) > 6:
            COOKIE_KEEP.pop(next(iter(COOKIE_KEEP)))
        out["id"] = key
        out["download"] = f"/api/cookie_download/{key}"
        out["sidecar"] = f"/api/cookie_sidecar/{key}"
    return JSONResponse(out)


@app.get("/api/cookie_download/{key}")
def cookie_download(key: str):
    from fastapi.responses import Response
    if key not in COOKIE_KEEP:
        raise HTTPException(404, "no such export")
    stl, fname, _side = COOKIE_KEEP[key]
    return Response(stl, media_type="model/stl", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.get("/api/cookie_sidecar/{key}")
def cookie_sidecar(key: str):
    if key not in COOKIE_KEEP:
        raise HTTPException(404, "no such export")
    return JSONResponse(COOKIE_KEEP[key][2])


# ---- stamp tab: the zip is held in memory (nothing is written to disk) ----
STAMP_KEEP = {}


@app.post("/api/stamp_preview")
async def stamp_preview(params: str = Form(...), art: Optional[UploadFile] = File(None)):
    p = _parse(params)
    data, name = await _read_upload(art)
    if ENGINE is None:
        raise HTTPException(503, "engine not loaded")
    try:
        return JSONResponse(ENGINE.stamp_preview(p, data, name))
    except Exception as exc:
        raise HTTPException(422, f"{type(exc).__name__}: {exc}")


@app.post("/api/stamp_export")
async def stamp_export(params: str = Form(...), art: Optional[UploadFile] = File(None)):
    p = _parse(params)
    data, name = await _read_upload(art)
    if ENGINE is None:
        raise HTTPException(503, "engine not loaded")
    try:
        r = ENGINE.stamp_export(p, data, name)
    except Exception as exc:
        raise HTTPException(422, f"{type(exc).__name__}: {exc}")
    out = {"blocked": bool(r["blocked"]), "checks": r["checks"], "filename": r["filename"], "bytes": len(r["zip"]),
           "files": r["files"], "stl_bytes": r.get("bytes", 0)}
    if not r["blocked"]:
        key = time.strftime("%Y%m%d-%H%M%S") + "-%d" % len(STAMP_KEEP)
        STAMP_KEEP[key] = (r["zip"], r["filename"])
        while len(STAMP_KEEP) > 4:
            STAMP_KEEP.pop(next(iter(STAMP_KEEP)))
        out["id"] = key
        out["download"] = f"/api/stamp_download/{key}"
    return JSONResponse(out)


@app.get("/api/stamp_download/{key}")
def stamp_download(key: str):
    from fastapi.responses import Response
    if key not in STAMP_KEEP:
        raise HTTPException(404, "no such export")
    z, fname = STAMP_KEEP[key]
    return Response(z, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.get("/api/download/{stamp}")
def download(stamp: str):
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}(-[0-9]+)?", stamp):
        raise HTTPException(400, "bad id")
    d = OUT / stamp
    if not d.is_dir():
        raise HTTPException(404, "no such export")
    zpath = shutil.make_archive(str(OUT / f"_zip_{stamp}"), "zip", root_dir=str(d))
    return FileResponse(zpath, media_type="application/zip", filename=f"roller-{stamp}.zip")


@app.get("/api/solve_repeat")
def solve_repeat(tile_width: float, d_min: float = 25, d_max: float = 100, max_n: int = 12):
    if tile_width <= 0:
        raise HTTPException(400, "tile_width must be positive")
    if ENGINE is not None:
        return ENGINE.solve_repeat(tile_width, d_min, d_max, max_n)
    rows = []
    for n in range(1, int(max_n) + 1):
        for dia in {round(n * tile_width / math.pi), round(n * tile_width / math.pi, 1)}:
            if d_min <= dia <= d_max:
                C = math.pi * dia
                rows.append({"diameter": dia, "n_around": n, "C": C, "stretch_pct": (C / n / tile_width - 1) * 100})
    rows.sort(key=lambda r: (abs(r["stretch_pct"]) > 0.05, abs(r["stretch_pct"]), abs(r["diameter"] - 45)))
    return rows[:6]


@app.get("/api/patterns")
def patterns():
    if ENGINE is not None:
        return ENGINE.patterns()
    return [{"id": "waves", "name": "Waves"}, {"id": "chevron", "name": "Chevron"}, {"id": "leaf", "name": "Leaf"}]


# Static files at the root so the page's relative URLs (app.js, fonts/...) work here exactly as on
# GitHub Pages. Mounted last so every route above wins. /engine serves app/engine for the
# in-browser engine during local dev (the deploy step copies it into web/engine/ instead).
if (HERE / "engine").is_dir() and not (WEB / "engine").exists():
    app.mount("/engine", StaticFiles(directory=str(HERE / "engine")), name="engine")
app.mount("/", StaticFiles(directory=str(WEB), html=True), name="root")
