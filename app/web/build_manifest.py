"""Regenerate engine_manifest.json from app/engine/ (every .py and data file, no tests, no caches).

DEPLOY (GitHub Pages): the site root is app/web/. Before publishing:
    python app/web/build_manifest.py          # writes app/web/engine_manifest.json
    copy app/engine/  ->  <site root>/engine/  # same files the manifest lists, keep the layout
Any data file the engine reads at run time (for example the rules table) must live inside
app/engine/ so it is listed here and copied; the browser has no access to the rest of the repo.
The page fetches engine_manifest.json, downloads each listed file (paths are relative to the
site root, e.g. "engine/api.py") and writes it into the Pyodide file system.

Dev: server.py serves /engine/ straight from app/engine/, so no copy is needed locally.
Run with ASCII output only (Windows console).
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "engine"
SKIP_DIRS = {"__pycache__", "tests", ".pytest_cache"}
SKIP_SUFFIX = {".pyc", ".pyo"}


def collect():
    files = []
    for p in sorted(ENGINE.rglob("*")):
        if not p.is_file() or p.suffix in SKIP_SUFFIX:
            continue
        rel = p.relative_to(ENGINE)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        files.append("engine/" + rel.as_posix())
    return files


def main():
    if not ENGINE.is_dir():
        raise SystemExit("app/engine/ not found")
    files = collect()
    h = hashlib.sha1()
    for f in files:
        h.update(f.encode())
        h.update((HERE.parent / f).read_bytes())
    out = HERE / "engine_manifest.json"
    out.write_text(json.dumps({"version": h.hexdigest()[:12], "files": files}, indent=2), encoding="ascii")
    print("wrote %s with %d files" % (out, len(files)))


if __name__ == "__main__":
    main()
