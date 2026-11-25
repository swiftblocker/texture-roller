/* One module between the UI and the engine. Two backends with the same surface:
 *   "pyodide"  the engine runs in a Web Worker in the browser (default, works on GitHub Pages)
 *   "http"     the local FastAPI server (server.py), chosen when GET api/patterns answers
 *              or when the URL has ?backend=http. ?backend=pyodide forces the browser one.
 *
 * Surface (all promises):
 *   engine.backend, engine.note
 *   patterns()                       -> [{id,name}]
 *   preview(params, file|null)       -> preview JSON; rejects with name "Superseded" when a newer call replaced it
 *   exportZip(params, file|null)     -> {rules, blocked, files, href, filename}
 *   testStrip(params)                -> same shape
 *   solveRepeat(tileWidth)           -> [{diameter,n_around,C,stretch_pct}]
 * All URLs are relative, so a GitHub Pages subpath works. */

async function probeHttp() {
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 1500);
    const r = await fetch("api/patterns", { signal: ctl.signal });
    clearTimeout(t);
    if (!r.ok) return false;
    const j = await r.json();
    return Array.isArray(j);
  } catch (e) { return false; }
}

export async function createEngine(onProgress) {
  const q = new URLSearchParams(location.search);
  let backend = q.get("backend");
  if (backend !== "http" && backend !== "pyodide") backend = (await probeHttp()) ? "http" : "pyodide";
  return backend === "http" ? httpEngine(onProgress) : pyodideEngine(onProgress);
}

/* ---------- http backend ---------- */
async function httpEngine(onProgress) {
  onProgress({ text: "Connecting to the local server" });
  const form = (params, file) => {
    const fd = new FormData();
    fd.append("params", JSON.stringify(params));
    if (file) fd.append("art", file, file.name);
    return fd;
  };
  const check = async (r) => {
    if (r.ok) return r.json();
    let msg = String(r.status);
    try { msg = (await r.json()).detail || msg; } catch (e) { /* ignore */ }
    throw new Error(msg);
  };
  let ctl = null;
  let note = null;
  try {
    const s = await (await fetch("api/status")).json();
    if (!s.engine) note = "Engine not loaded, showing fixture data";
  } catch (e) { /* ignore */ }
  const done = async (r) => {
    const j = await check(r);
    return { ...j, href: j.download, filename: "roller-" + j.id + ".zip" };
  };
  return {
    backend: "http",
    note,
    patterns: async () => check(await fetch("api/patterns")),
    preview: async (params, file) => {
      if (ctl) ctl.abort();
      ctl = new AbortController();
      try {
        return await check(await fetch("api/preview", { method: "POST", body: form(params, file), signal: ctl.signal }));
      } catch (e) {
        if (e.name === "AbortError") { const s = new Error("Superseded"); s.name = "Superseded"; throw s; }
        throw e;
      }
    },
    exportZip: async (params, file) => done(await fetch("api/export", { method: "POST", body: form(params, file) })),
    testStrip: async (params) => done(await fetch("api/test_strip", { method: "POST", body: form(params, null) })),
    solveRepeat: async (tw) => check(await fetch("api/solve_repeat?tile_width=" + encodeURIComponent(tw))),
  };
}

/* ---------- pyodide backend ---------- */
async function registerServiceWorker() {
  if (!("serviceWorker" in navigator) || !(location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) return;
  try {
    await navigator.serviceWorker.register("sw.js");
    await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) {
      // first visit: wait briefly for the worker to claim this page so downloads get cached
      await new Promise((res) => {
        const t = setTimeout(res, 2500);
        navigator.serviceWorker.addEventListener("controllerchange", () => { clearTimeout(t); res(); }, { once: true });
      });
    }
  } catch (e) { /* offline caching is optional */ }
}

async function pyodideEngine(onProgress) {
  onProgress({ text: "Preparing offline cache" });
  await registerServiceWorker();
  const worker = new Worker(new URL("worker.js", import.meta.url));
  let nextId = 1;
  const waiting = new Map();
  await new Promise((resolve, reject) => {
    worker.onmessage = (ev) => {
      const m = ev.data;
      if (m.type === "progress") onProgress({ text: m.text, done: m.done, total: m.total });
      else if (m.type === "ready") resolve();
      else if (m.type === "fatal") reject(new Error(m.message));
      else if (m.type === "result") {
        const w = waiting.get(m.id);
        if (!w) return;
        waiting.delete(m.id);
        if (m.ok) w.resolve(m); else w.reject(new Error(m.error));
      }
    };
    worker.onerror = (e) => reject(new Error(e.message || "worker failed to start"));
  });

  const call = (msg) => new Promise((resolve, reject) => {
    const id = nextId++;
    waiting.set(id, { resolve, reject });
    worker.postMessage({ id, ...msg });
  });
  const bytesOf = async (file) => (file ? new Uint8Array(await file.arrayBuffer()) : null);

  // The worker is single threaded. Keep at most one preview waiting behind the running one.
  let running = false;
  let pending = null;
  const pump = async () => {
    if (running || !pending) return;
    const job = pending; pending = null; running = true;
    try {
      const m = await call({ op: "preview", params: JSON.stringify(job.params), upload: await bytesOf(job.file), name: job.file ? job.file.name : null });
      job.resolve(JSON.parse(m.json));
    } catch (e) { job.reject(e); }
    running = false;
    pump();
  };

  let blobUrl = null;
  const asDownload = (m, prefix) => {
    const j = JSON.parse(m.json);
    if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = null; }
    if (m.zip && !j.blocked) blobUrl = URL.createObjectURL(new Blob([m.zip], { type: "application/zip" }));
    return { ...j, href: blobUrl, filename: prefix + "-" + new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14) + ".zip" };
  };

  return {
    backend: "pyodide",
    note: null,
    patterns: async () => JSON.parse((await call({ op: "patterns" })).json),
    preview: (params, file) => new Promise((resolve, reject) => {
      if (pending) { const s = new Error("Superseded"); s.name = "Superseded"; pending.reject(s); }
      pending = { params, file, resolve, reject };
      pump();
    }),
    exportZip: async (params, file) => asDownload(await call({ op: "export", params: JSON.stringify(params), upload: await bytesOf(file), name: file ? file.name : null }), "roller"),
    testStrip: async (params) => asDownload(await call({ op: "test_strip", params: JSON.stringify(params) }), "roller-test-strip"),
    solveRepeat: async (tw) => JSON.parse((await call({ op: "solve_repeat", tw, dmin: 25, dmax: 100, mx: 12 })).json),
  };
}
