/* Cookie cutter tab. Art goes in, a printable cutter-with-stamp STL comes out.
 * The engine (engine/cookie.py) returns mm polygons of the cutter as printed plus plain-word checks;
 * this file draws two views from them (the back of the cutter, and the pressed cookie, which is its
 * mirror) and runs the download. Both views are drawn mirrored in x relative to the print bed view,
 * so they read the way the cookie will. Drawings and logos only: photos are not supported yet. */

const KEY = "cookie.params";
const DEFAULTS = { size_mm: 80, dough_mm: 6, imprint_mm: 2.5, wall_mm: 14 };
const FIELDS = [
  { k: "size_mm", label: "Cut size, longest side", unit: "mm", min: 30, max: 200, step: 1 },
  { k: "dough_mm", label: "Dough thickness", unit: "mm", min: 3, max: 12, step: 0.5 },
  { k: "imprint_mm", label: "Imprint depth", unit: "mm", min: 0.5, max: 6, step: 0.5 },
  { k: "wall_mm", label: "Cutter height", unit: "mm", min: 10, max: 30, step: 1 },
];
const FRIENDLY = "This drawing tripped up the cutter maker. Try a slightly different size or a simpler drawing.";
/* Engine errors reach the page as "CookieError: sentence" (our own plain messages) or as raw Python text.
 * Show our sentence when there is one, the friendly line otherwise; the raw text goes to the console only. */
function plainError(e) {
  console.error("cookie engine error:", e && e.message ? e.message : e);
  const m = /CookieError: (.+)$/.exec(String((e && e.message) || ""));
  if (m && !/Exception|Traceback|Error:/.test(m[1])) return m[1].trim();
  return FRIENDLY;
}
const ARTISH = /\.(png|jpe?g|webp|svg)$/i;

export function initCookie(ctx) {
  const { engine, S, $, el, css, toEngineFile, mb, dlLink } = ctx;
  const C = { params: { ...DEFAULTS }, file: null, last: null, seq: 0, shown: 0, busy: false, photo: false, photoFor: null, t0: 0 };
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "null");
    if (saved && typeof saved === "object") for (const f of FIELDS) if (Number.isFinite(saved[f.k])) C.params[f.k] = saved[f.k];
  } catch (e) { /* storage may be unavailable */ }

  const inputs = {};
  /* A photo has many mid-tone pixels; a drawing or logo is mostly paper and ink with soft edges. */
  async function isPhoto(f) {
    if (/\.svg$/i.test(f.name) || f.type === "image/svg+xml") return false;
    try {
      const bmp = await createImageBitmap(f);
      const k = 200 / Math.max(bmp.width, bmp.height, 1);
      const w = Math.max(1, Math.round(bmp.width * Math.min(1, k))), h = Math.max(1, Math.round(bmp.height * Math.min(1, k)));
      const cv = document.createElement("canvas");
      cv.width = w; cv.height = h;
      const g = cv.getContext("2d", { willReadFrequently: true });
      g.fillStyle = "#fff"; g.fillRect(0, 0, w, h);
      g.drawImage(bmp, 0, 0, w, h);
      const d = g.getImageData(0, 0, w, h).data;
      let mid = 0;
      for (let i = 0; i < d.length; i += 4) {
        const v = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
        if (v > 45 && v < 210) mid++;
      }
      return mid / (w * h) > 0.3;
    } catch (e) { return false; }
  }
  const currentFile = () => C.file || S.upload || null;

  /* ---------- settings panel ---------- */
  function buildForm() {
    const form = $("cookie-params");
    form.replaceChildren();
    const body = el("div", { class: "group-body" });
    for (const f of FIELDS) {
      const inp = el("input", { type: "number", id: "c-" + f.k, step: f.step, min: f.min, max: f.max, inputmode: "decimal" });
      inp.value = C.params[f.k];
      const hint = el("span", { class: "hint", id: "c-hint-" + f.k, hidden: true, text: f.min + " to " + f.max + " " + f.unit });
      inp.setAttribute("aria-describedby", hint.id);
      inp.addEventListener("input", () => {
        const v = Number(inp.value);
        if (inp.value === "" || !Number.isFinite(v) || v < f.min || v > f.max) {
          inp.classList.add("invalid"); inp.setAttribute("aria-invalid", "true"); hint.hidden = false; return;
        }
        inp.classList.remove("invalid"); inp.removeAttribute("aria-invalid"); hint.hidden = true;
        C.params[f.k] = v;
        save();
        schedule();
      });
      inputs[f.k] = inp;
      inp.hint = hint;
      body.append(el("div", { class: "row" }, el("label", { for: "c-" + f.k }, f.label, el("span", { class: "unit", text: f.unit })), inp, hint));
    }
    body.append(el("p", { class: "note", text: "The cutting edge, back bars and rib sizes are fixed to what prints well: a 0.86 mm edge (two lines of a 0.4 mm nozzle), 6 x 2.4 mm bars." }));
    form.append(el("details", { class: "group", open: true }, el("summary", { text: "Cookie" }), body));
    const reset = el("div", { class: "group-body" }, el("button", {
      type: "button", class: "btn", text: "Reset to the defaults", onclick: () => {
        C.params = { ...DEFAULTS };
        for (const f of FIELDS) {
          inputs[f.k].value = C.params[f.k]; inputs[f.k].classList.remove("invalid");
          inputs[f.k].removeAttribute("aria-invalid"); inputs[f.k].hint.hidden = true;
        }
        save(); schedule();
      },
    }));
    form.append(reset);
  }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(C.params)); } catch (e) { /* ignore */ } }

  /* ---------- status line under the Upload button ---------- */
  const narrow = window.matchMedia("(max-width: 1023px)");
  function setStatus(text, kind) {
    const s = $("cookie-status");
    s.textContent = text;
    s.className = "cookie-status" + (kind ? " " + kind : "");
    if (narrow.matches && kind) s.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  /* ---------- preview requests ---------- */
  let timer = null;
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(requestPreview, 300);
  }
  function setBusy(on) {
    C.busy = on;
    $("busy").textContent = on ? "Updating" : "";
    if (on) setStatus("Making the cutter...", "busy");
    $("cookie-stage").classList.toggle("busy", on);
    $("cookie-stage").setAttribute("aria-busy", String(on));
  }
  function empty(msg, isErr) {
    const e = $("cookie-empty");
    e.textContent = msg; e.hidden = false; e.classList.toggle("err", !!isErr);
  }
  async function requestPreview() {
    if (document.querySelector("#cookie-params input.invalid")) return;
    const file = currentFile();
    if (!file) { C.last = null; setStatus("Upload a drawing or logo to start.", ""); empty("Upload a drawing or logo to start. SVG, PNG, JPEG or WEBP.", false); renderChecks(); drawAll(); return; }
    if (C.photoFor !== file) { C.photoFor = file; C.photo = false; isPhoto(file).then((p) => { if (C.photoFor === file) { C.photo = p; renderNote(); } }); }
    const mine = ++C.seq;
    C.t0 = performance.now();
    setBusy(true);
    try {
      const data = await engine.cookiePreview({ ...C.params }, file);
      if (mine <= C.shown) return;
      C.shown = mine;
      C.last = data;
      C.secs = (performance.now() - C.t0) / 1000;
      // the engine may have limited a value (for example the imprint must leave 2 mm of dough)
      for (const f of FIELDS) {
        const v = data.params && data.params[f.k];
        if (Number.isFinite(v) && v !== C.params[f.k]) { C.params[f.k] = v; inputs[f.k].value = v; }
      }
      $("cookie-empty").hidden = true;
      renderAll();
      const warns = data.checks.filter((x) => x.level === "warn").length;
      setStatus("Ready: cut shape " + data.size.cut_w + " x " + data.size.cut_h + " mm"
        + (data.can_export ? "" : ", but the download is blocked (see Checks)") + (warns ? ", " + warns + " thing" + (warns > 1 ? "s" : "") + " to look at." : "."), data.can_export ? "ok" : "err");
    } catch (e) {
      if (e.name === "Superseded") return;
      C.last = null;
      const msg = plainError(e);
      setStatus(msg, "err");
      empty(msg, true);
      renderChecks(); drawAll();
    } finally { setBusy(false); }
  }

  /* ---------- checks ---------- */
  const LABEL = { pass: "OK", warn: "Look", block: "Stop" };
  const CLS = { pass: "info", warn: "warn", block: "block" };
  function renderChecks() {
    const ul = $("cookie-checks");
    ul.replaceChildren();
    const d = C.last;
    if (!d) { $("cookie-count").textContent = ""; ul.append(el("li", { class: "rules-empty", text: "Checks appear after the first preview." })); updateExport(); return; }
    const order = { block: 0, warn: 1, pass: 2 };
    const rows = [...d.checks].sort((a, b) => order[a.level] - order[b.level]);
    for (const c of rows) {
      ul.append(el("li", { class: "rule " + CLS[c.level] }, el("span", { class: "rid", text: LABEL[c.level] }), el("span", { class: "msg", text: c.text }), el("span")));
    }
    const nb = rows.filter((c) => c.level === "block").length, nw = rows.filter((c) => c.level === "warn").length;
    $("cookie-count").textContent = nb ? nb + " stop" : nw ? nw + " to look at" : "all clear";
    updateExport();
  }
  function updateExport() {
    const d = C.last;
    const b = $("cookie-export");
    b.disabled = !d || !d.can_export;
    const note = $("cookie-export-note");
    note.classList.toggle("block", !!(d && !d.can_export));
    note.textContent = !d ? "" : d.can_export ? "Print with the flat back on the bed, no supports." : "The download is blocked until the stop items above are fixed.";
  }

  function renderNote() {
    const n = $("cookie-note");
    n.classList.toggle("warn", C.photo);
    n.textContent = C.photo
      ? "This looks like a photo. Photos are not supported yet in cookie mode, so the result may be rough. A line drawing or a logo works best."
      : "Cookie mode works with drawings and logos (SVG, PNG, JPEG, WEBP). Photos are not supported yet: use a line drawing or a logo.";
  }
  function renderCaption() {
    const d = C.last;
    $("cookie-caption").textContent = d
      ? "Cut shape " + d.size.cut_w + " x " + d.size.cut_h + " mm, cutter " + d.size.outer_w + " x " + d.size.outer_h + " x " + d.size.height + " mm, "
        + d.size.tris.toLocaleString() + " triangles" + (C.secs ? ", " + C.secs.toFixed(1) + " s" : "")
      : "";
  }
  function renderAll() { renderChecks(); renderCaption(); renderNote(); syncUpload(); drawAll(); }

  /* ---------- drawing ---------- */
  function setup(cv) {
    const wrap = cv.parentElement;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = Math.max(10, wrap.clientWidth), H = Math.max(10, wrap.clientHeight);
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const g = cv.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = css("--clay-ground");
    g.fillRect(0, 0, W, H);
    return { g, W, H };
  }
  function bounds(polys) {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const poly of polys) for (const [x, y] of poly[0]) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    return [x0, y0, x1, y1];
  }
  /* Both views are the mirror of the print-bed view: x flips. */
  function fitTo(W, H, geom) {
    const [x0, y0, x1, y1] = bounds(geom.rim);
    const pad = 28, capH = 22;
    const k = Math.min((W - 2 * pad) / (x1 - x0), (H - 2 * pad - capH) / (y1 - y0));
    const cx = W / 2, cy = (H - capH) / 2 + 4, mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
    return { k, X: (x) => cx - (x - mx) * k, Y: (y) => cy - (y - my) * k };
  }
  function pathOf(polys, T) {
    const p = new Path2D();
    for (const poly of polys) for (const ring of poly) {
      ring.forEach(([x, y], i) => (i ? p.lineTo(T.X(x), T.Y(y)) : p.moveTo(T.X(x), T.Y(y))));
      p.closePath();
    }
    return p;
  }
  function drawBack() {
    const cv = $("cookie-back");
    const { g, W, H } = setup(cv);
    const d = C.last;
    if (!d) return;
    const T = fitTo(W, H, d.geom);
    g.fillStyle = css("--color-well-hover"); g.fill(pathOf(d.geom.rim, T), "evenodd");
    g.fillStyle = css("--color-ink-2"); g.fill(pathOf(d.geom.wall, T), "evenodd");
    g.fillStyle = css("--clay-ground"); g.fill(pathOf(d.geom.cut, T), "evenodd");
    g.fillStyle = css("--color-seam"); g.globalAlpha = 0.85; g.fill(pathOf(d.geom.bars, T), "evenodd"); g.globalAlpha = 1;
    g.fillStyle = css("--color-accent"); g.fill(pathOf(d.geom.ribs, T), "evenodd");
  }
  function drawCookie() {
    const cv = $("cookie-cookie");
    const { g, W, H } = setup(cv);
    const d = C.last;
    if (!d) return;
    const T = fitTo(W, H, d.geom);
    const cut = pathOf(d.geom.cut, T), ribs = pathOf(d.geom.ribs, T);
    const dough = css("--clay-fired");
    g.save();
    g.shadowColor = "rgba(0,0,0,0.45)"; g.shadowBlur = 14; g.shadowOffsetY = 4;
    g.fillStyle = dough; g.fill(cut, "evenodd");
    g.restore();
    g.fillStyle = dough; g.fill(cut, "evenodd");
    // rounded, baked edge
    g.save(); g.clip(cut, "evenodd");
    g.lineJoin = "round";
    g.strokeStyle = "rgba(0,0,0,0.22)"; g.lineWidth = Math.max(3, T.k * 1.6); g.stroke(cut);
    g.restore();
    // the pressed lines: a darker floor, a shadow along the upper left wall, a lip of light on the lower right
    g.save(); g.clip(cut, "evenodd");
    g.fillStyle = "rgba(0,0,0,0.30)"; g.fill(ribs, "evenodd");
    g.restore();
    const off = Math.max(1, T.k * 0.5);
    g.save(); g.clip(ribs, "evenodd");
    g.translate(off, off); g.strokeStyle = "rgba(0,0,0,0.55)"; g.lineWidth = off * 1.8; g.lineJoin = "round"; g.stroke(ribs);
    g.restore();
    g.save(); g.clip(cut, "evenodd"); g.translate(off * 0.9, off * 0.9);
    g.strokeStyle = "rgba(255,240,220,0.35)"; g.lineWidth = Math.max(1, off * 0.8); g.lineJoin = "round"; g.stroke(ribs);
    g.restore();
  }
  function drawAll() {
    drawBack();
    drawCookie();
  }

  /* ---------- upload, drag and drop, view switch ---------- */
  function syncUpload() {
    const f = currentFile();
    const b = $("cookie-upload");
    b.textContent = f ? "Change picture" : "Upload a picture";
    b.title = f ? f.name : "SVG, PNG, JPEG or WEBP. A line drawing or a logo works best; photos are not supported yet.";
  }
  async function useFile(f) {
    if (!f) return;
    setStatus("Reading the picture...", "busy");
    C.file = await toEngineFile(f);
    C.last = null;
    syncUpload();
    schedule();
  }
  $("cookie-upload-file").addEventListener("change", (e) => { useFile(e.target.files[0]); e.target.value = ""; });
  const stage = $("cookie-stage");
  stage.addEventListener("dragover", (e) => { e.preventDefault(); stage.classList.add("drop"); });
  stage.addEventListener("dragleave", () => stage.classList.remove("drop"));
  stage.addEventListener("drop", (e) => {
    e.preventDefault(); stage.classList.remove("drop");
    const f = [...(e.dataTransfer?.files || [])].find((x) => ARTISH.test(x.name) || /^image\//.test(x.type));
    if (f) useFile(f);
  });
  const setView = (v) => {
    stage.dataset.view = v;
    for (const id of ["both", "back", "cookie"]) $("cv-" + id).setAttribute("aria-pressed", String(id === v));
    requestAnimationFrame(drawAll);
  };
  for (const id of ["both", "back", "cookie"]) $("cv-" + id).onclick = () => setView(id);
  new ResizeObserver(() => drawAll()).observe(stage);

  /* ---------- download ---------- */
  $("cookie-export").onclick = async () => {
    const res = $("cookie-export-result");
    res.replaceChildren(el("span", { text: "Building the STL. This takes a few seconds; the page stays usable." }));
    const b = $("cookie-export");
    b.disabled = true;
    try {
      const j = await engine.cookieExport({ ...C.params }, currentFile());
      res.replaceChildren();
      if (j.blocked || !j.href) {
        const why = (j.checks || []).filter((c) => c.level === "block").map((c) => c.text);
        res.append(el("span", { class: "err", text: "Not exported. " + (why.join(" ") || "The model is not printable.") }));
      } else {
        const a = dlLink(j.href, j.filename, "Save STL, " + mb(j.bytes), true);
        res.append(a);
        a.click();
        res.append(el("p", { class: "caption", text: "Print with the flat back on the bed, 0.2 mm layers, no supports. The cutting edge goes up." }));
      }
    } catch (e) {
      res.replaceChildren(el("span", { class: "err", text: plainError(e) }));
    } finally { updateExport(); }
  };

  buildForm();
  renderChecks();
  renderNote();
  syncUpload();
  if (narrow.matches) setView("cookie");   // one view at a time on a phone; the toggle switches
  return {
    show() { syncUpload(); schedule(); requestAnimationFrame(drawAll); },
    hide() { clearTimeout(timer); },
    state: C,
  };
}
