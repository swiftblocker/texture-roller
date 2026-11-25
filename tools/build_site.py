"""Build the GitHub Pages site into docs/ (Pages serves main:/docs).

    python tools/build_site.py

Copies app/web/ (minus dev-only files) to docs/, copies every engine file listed by
app/web/build_manifest.py into docs/engine/, and writes docs/engine_manifest.json.
ASCII output only.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "app" / "web"
ENGINE = ROOT / "app" / "engine"
DOCS = ROOT / "docs"
SKIP = {"dev_fixture.json", "build_manifest.py", "__pycache__"}


def main():
    subprocess.run([sys.executable, str(WEB / "build_manifest.py")], check=True)
    if DOCS.exists():
        shutil.rmtree(DOCS)
    shutil.copytree(WEB, DOCS, ignore=lambda d, names: [n for n in names if n in SKIP])
    n = 0
    for p in sorted(ENGINE.rglob("*")):
        rel = p.relative_to(ENGINE)
        if not p.is_file() or "__pycache__" in rel.parts or p.suffix in {".pyc", ".pyo"}:
            continue
        dst = DOCS / "engine" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
        n += 1
    (DOCS / ".nojekyll").write_text("")
    print("docs/ built: %d engine files" % n)


if __name__ == "__main__":
    main()
