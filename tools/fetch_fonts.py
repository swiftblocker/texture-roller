"""Download the open source (SIL OFL) fonts the text feature uses, fix variable fonts at one
weight, subset to Latin-1 and write them to app/engine/data/fonts/ with each family's licence.

    python tools/fetch_fonts.py

Source: github.com/google/fonts (every family here is under the SIL Open Font License 1.1).
ASCII output only.
"""
import io
import urllib.request
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools import subset
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "engine" / "data" / "fonts"
RAW = "https://raw.githubusercontent.com/google/fonts/main/ofl/"

# id, folder, file, axis values for variable fonts
FONTS = [
    ("pacifico", "pacifico", "Pacifico-Regular.ttf", None),
    ("shrikhand", "shrikhand", "Shrikhand-Regular.ttf", None),
    ("cherrybomb", "cherrybombone", "CherryBombOne-Regular.ttf", None),
    ("fraunces", "fraunces", "Fraunces[SOFT,WONK,opsz,wght].ttf", {"wght": 800, "SOFT": 100, "WONK": 1, "opsz": 72}),
    ("bebas", "bebasneue", "BebasNeue-Regular.ttf", None),
    ("nunito", "nunito", "Nunito[wght].ttf", {"wght": 900}),
    ("caveat", "caveat", "Caveat[wght].ttf", {"wght": 700}),
    ("dancing", "dancingscript", "DancingScript[wght].ttf", {"wght": 700}),
    ("lilita", "lilitaone", "LilitaOne-Regular.ttf", None),
]

# Basic Latin, Latin-1 letters and punctuation, curly quotes, dashes, ellipsis, heart
UNICODES = list(range(0x20, 0x7F)) + list(range(0xA0, 0x100)) + [0x2018, 0x2019, 0x201C, 0x201D, 0x2013, 0x2014, 0x2026, 0x2665, 0x2764]


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "font-fetch"}), timeout=60) as r:
        return r.read()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for fid, folder, fname, axes in FONTS:
        data = get(RAW + folder + "/" + urllib.request.quote(fname))
        f = TTFont(io.BytesIO(data))
        if axes:
            have = {a.axisTag for a in f["fvar"].axes}
            f = instancer.instantiateVariableFont(f, {k: v for k, v in axes.items() if k in have})
        opts = subset.Options()
        opts.layout_features = ["kern", "liga", "calt", "clig"]
        opts.name_IDs = ["*"]
        opts.notdef_outline = True
        opts.hinting = False
        sub = subset.Subsetter(opts)
        sub.populate(unicodes=UNICODES)
        sub.subset(f)
        dst = OUT / (fid + ".ttf")
        f.save(str(dst))
        lic = get(RAW + folder + "/OFL.txt")
        (OUT / (fid + "-OFL.txt")).write_bytes(lic)
        print("%-10s %6d bytes" % (fid, dst.stat().st_size))


if __name__ == "__main__":
    main()
