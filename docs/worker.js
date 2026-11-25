/* Web Worker: runs the Python engine in Pyodide, entirely in the browser.
 * Messages in:  {id, op, ...args}   op = preview | export | test_strip | solve_repeat | patterns | fit_portrait
 * Messages out: {type:"progress", text, done, total}, {type:"ready"}, {type:"fatal", message},
 *               {type:"result", id, ok, json, zip, error}
 * All URLs are relative to this file so it works under a GitHub Pages subpath. */
const PYODIDE_VERSION = "0.27.7";
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v" + PYODIDE_VERSION + "/full/";
const BASE = new URL(".", self.location.href);
const PACKAGES = ["numpy", "scipy", "scikit-image", "pillow"];
const PIP = ["svgelements", "potracer", "trimesh"];

importScripts(PYODIDE + "pyodide.js");

let py = null;
const post = (m, t) => self.postMessage(m, t || []);
const progress = (text, done, total) => post({ type: "progress", text, done: done == null ? null : done, total: total == null ? null : total });

async function sizeOf(url) {
  try {
    const r = await fetch(url, { method: "HEAD" });
    return Number(r.headers.get("content-length")) || 0;
  } catch (e) { return 0; }
}

/* Download the two big runtime files with a visible MB counter. The browser (and the
 * service worker) keep them, so loadPyodide below reads them from cache. */
async function prefetchRuntime() {
  const files = ["pyodide.asm.wasm", "python_stdlib.zip"].map((f) => PYODIDE + f);
  const sizes = await Promise.all(files.map(sizeOf));
  const total = sizes.reduce((a, b) => a + b, 0) || 31e6;
  let done = 0;
  for (const url of files) {
    const r = await fetch(url);
    if (!r.ok) throw new Error("Could not download " + url + " (" + r.status + ")");
    const reader = r.body.getReader();
    for (;;) {
      const { value, done: end } = await reader.read();
      if (end) break;
      done += value.length;
      progress("Loading Python runtime " + (done / 1e6).toFixed(0) + " / " + (total / 1e6).toFixed(0) + " MB", done, total);
    }
  }
}

const HELPER = `
import json, io, os, shutil, tempfile, zipfile, sys
sys.path.insert(0, "/home/pyodide")
from engine import api

_zip = None
_m3 = None
_stls = []

def _pick3mf(z):
    global _m3, _stls
    _m3 = b""
    _stls = []
    if not z:
        return
    zf = zipfile.ZipFile(io.BytesIO(z))
    for n in zf.namelist():
        low = n.lower()
        if low.endswith(".3mf") and not _m3:
            _m3 = zf.read(n)
        elif low.endswith(".stl"):
            _stls.append([os.path.basename(n), zf.read(n)])

def _dumps(o):
    return json.dumps(o, default=lambda x: x.item() if hasattr(x, "item") else str(x))

def _up(u):
    return bytes(u.to_py()) if u is not None else None

def _zipdir(d):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, names in os.walk(d):
            for n in names:
                full = os.path.join(root, n)
                z.write(full, os.path.relpath(full, d))
    return buf.getvalue()

def _names(z):
    return zipfile.ZipFile(io.BytesIO(z)).namelist() if z else []

def op_preview(p, u, name):
    return _dumps(api.preview(json.loads(p), _up(u), name))

def op_export(p, u, name):
    global _zip, _m3
    params = json.loads(p)
    if hasattr(api, "export_bytes"):
        r = api.export_bytes(params, _up(u), name)
        z = r.get("zip") or b""
    else:
        d = tempfile.mkdtemp()
        r = api.export(params, _up(u), name, d)
        z = b"" if r.get("blocked") else _zipdir(d)
        shutil.rmtree(d, ignore_errors=True)
    _zip = bytes(z)
    _pick3mf(_zip)
    return _dumps({"rules": r.get("rules", []), "blocked": bool(r.get("blocked")), "files": _names(_zip)})

def op_test_strip(p):
    global _zip, _m3
    d = tempfile.mkdtemp()
    r = api.test_strip(json.loads(p), d)
    _zip = _zipdir(d)
    _pick3mf(_zip)
    shutil.rmtree(d, ignore_errors=True)
    return _dumps({"rules": r.get("rules", []), "blocked": bool(r.get("blocked")), "files": _names(_zip)})

def op_solve(tw, dmin, dmax, mx):
    return _dumps(api.solve_repeat(float(tw), float(dmin), float(dmax), int(mx)))

def op_fit(p, u):
    return _dumps(api.fit_portrait(json.loads(p), _up(u)))

def op_patterns():
    return _dumps(api.patterns())
`;

async function boot() {
  progress("Starting download");
  await prefetchRuntime();
  progress("Starting Python");
  py = await loadPyodide({ indexURL: PYODIDE });

  for (let i = 0; i < PACKAGES.length; i++) {
    progress("Loading " + PACKAGES[i] + " (" + (i + 1) + " / " + PACKAGES.length + ")");
    await py.loadPackage(PACKAGES[i], { messageCallback: () => {}, errorCallback: () => {} });
  }
  progress("Loading installer");
  await py.loadPackage("micropip", { messageCallback: () => {}, errorCallback: () => {} });
  const micropip = py.pyimport("micropip");
  for (let i = 0; i < PIP.length; i++) {
    progress("Installing " + PIP[i] + " (" + (i + 1) + " / " + PIP.length + ")");
    await micropip.install(PIP[i]);
  }

  progress("Loading engine");
  const manifest = await (await fetch(new URL("engine_manifest.json", BASE))).json();
  const files = manifest.files || [];
  py.FS.mkdirTree("/home/pyodide");
  for (let i = 0; i < files.length; i++) {
    const rel = files[i];
    const r = await fetch(new URL(rel, BASE));
    if (!r.ok) throw new Error("Engine file missing: " + rel + " (" + r.status + ")");
    const bytes = new Uint8Array(await r.arrayBuffer());
    const dest = "/home/pyodide/" + rel;
    py.FS.mkdirTree(dest.slice(0, dest.lastIndexOf("/")));
    py.FS.writeFile(dest, bytes);
    progress("Loading engine (" + (i + 1) + " / " + files.length + ")");
  }
  progress("Starting engine");
  py.runPython(HELPER);
}

function run(m) {
  const g = py.globals;
  const out = (fn, ...a) => {
    const r = g.get(fn)(...a);
    return r;
  };
  switch (m.op) {
    case "preview": return out("op_preview", m.params, m.upload || null, m.name || null);
    case "export": return out("op_export", m.params, m.upload || null, m.name || null);
    case "test_strip": return out("op_test_strip", m.params);
    case "solve_repeat": return out("op_solve", m.tw, m.dmin, m.dmax, m.mx);
    case "fit_portrait": return out("op_fit", m.params, m.upload || null);
    case "patterns": return out("op_patterns");
    default: throw new Error("unknown op " + m.op);
  }
}

self.onmessage = (ev) => {
  const m = ev.data;
  if (!py) { post({ type: "result", id: m.id, ok: false, error: "engine not ready" }); return; }
  try {
    const json = run(m);
    let zip = null, m3 = null, stls = [];
    if (m.op === "export" || m.op === "test_strip") {
      const proxy = py.globals.get("_zip");
      if (proxy && proxy.toJs) {
        const u8 = proxy.toJs();
        zip = new Uint8Array(u8);
        proxy.destroy();
      }
      const p3 = py.globals.get("_m3");
      if (p3 && p3.toJs) {
        const b = p3.toJs();
        if (b.length) m3 = new Uint8Array(b);
        p3.destroy();
      }
      const ps = py.globals.get("_stls");
      if (ps && ps.toJs) {
        for (const [name, data] of ps.toJs()) stls.push({ name: String(name), data: new Uint8Array(data) });
        ps.destroy();
      }
    }
    const tr = [];
    if (zip) tr.push(zip.buffer);
    if (m3) tr.push(m3.buffer);
    for (const f of stls) tr.push(f.data.buffer);
    post({ type: "result", id: m.id, ok: true, json, zip, m3, stls }, tr);
  } catch (e) {
    post({ type: "result", id: m.id, ok: false, error: String(e && e.message ? e.message : e).split("\n").slice(-3).join(" ") });
  }
};

boot().then(() => post({ type: "ready" })).catch((e) => post({ type: "fatal", message: String(e && e.message ? e.message : e).trim().split("\n").pop() }));
