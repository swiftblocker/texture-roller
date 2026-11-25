/* Service worker: after the first visit the page, fonts, engine files and the Pyodide
 * runtime and packages come from cache, so the tool works offline.
 * Same-origin files: network first, cache as the fallback (updates arrive on deploy).
 * Runtime and package downloads (jsDelivr, PyPI): cache first, they never change per version.
 * Relative URLs only, so it works under https://<user>.github.io/<repo>/ . */
const VERSION = "roller-v2";
const CDN_HOSTS = ["cdn.jsdelivr.net", "pypi.org", "files.pythonhosted.org"];
const CORE = [
  "./", "index.html", "app.css", "app.js", "engine-client.js", "worker.js",
  "vendor/three.module.js", "vendor/OrbitControls.js",
  "fonts/sofia-sans-latin-wght-normal.woff2", "fonts/chivo-mono-latin-wght-normal.woff2",
  "engine_manifest.json",
];

self.addEventListener("install", (e) => {
  e.waitUntil((async () => {
    const cache = await caches.open(VERSION);
    await Promise.all(CORE.map((u) => cache.add(u).catch(() => {})));
    try {
      const m = await (await fetch("engine_manifest.json", { cache: "no-store" })).json();
      await Promise.all((m.files || []).map((u) => cache.add(u).catch(() => {})));
    } catch (err) { /* manifest missing in dev, fine */ }
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== VERSION) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;
  if (sameOrigin && url.pathname.includes("/api/")) return;
  if (!sameOrigin && !CDN_HOSTS.includes(url.hostname)) return;

  if (sameOrigin) {
    e.respondWith((async () => {
      const cache = await caches.open(VERSION);
      try {
        // no-cache: always revalidate with the server, so a deploy is never mixed with a
        // heuristically cached older file (304 when unchanged)
        const r = await fetch(req.mode === "navigate" ? req : new Request(req, { cache: "no-cache" }));
        if (r.ok) cache.put(req, r.clone());
        return r;
      } catch (err) {
        const hit = await cache.match(req, { ignoreSearch: true });
        if (hit) return hit;
        throw err;
      }
    })());
    return;
  }
  e.respondWith((async () => {
    const cache = await caches.open(VERSION);
    const hit = await cache.match(req);
    if (hit) return hit;
    const r = await fetch(req);
    if (r.ok) cache.put(req, r.clone());
    return r;
  })());
});
