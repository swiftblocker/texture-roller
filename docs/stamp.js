/* Stamp tab. The same art and lettering as the roller, made into a flat hand stamp you press into clay.
 * The engine (engine/stamp.py) returns the face height map and the clay shading as small grey pictures plus plain-word
 * checks (R80-R85); this file draws two views (the stamp face, which reads backwards, and the print in the clay, which
 * reads the right way), keeps the settings, and runs the download (one zip: stamp.stl, knob.stl, stamp.3mf,
 * clay_preview.png, sheet.md). The lettering controls come from the roller (same fields, fonts and ideas). */

const KEY = "stamp.params";
const DEFAULTS = {
  shape: "rect", width_mm: 60, height_mm: 60, depth: 1.5, draft_deg: 15, edge_round: 0.4,
  rim_on: true, rim_mm: 2.5, knob_on: true, n_across: 1,
  art_source: "pattern:leaf", art_style: "trace", sketch_detail: 0.5, sketch_shading: true,
  art_scale: 100, art_shift_x: 0, art_shift_y: 0, invert: false,
  text: "", text_font: "pacifico", text_size: 12, text_layout: "single", text_count: 1, text_x: 50, text_y: 50,
  text_angle: 0, text_arch: 0, text_wave: 0, text_track: 8, text_relief: "pressed", text_frame: "halo", text_halo: 1.5,
  text_style: "solid", text_sep: "dot", text_gap: 5, text_row_gap: 6,
};
const FRIENDLY = "R80: This drawing tripped up the stamp maker. Try a slightly different size or a simpler drawing.";
/* Engine errors reach the page as "StampError: sentence" (our own plain messages) or as raw Python text.
 * Show our sentence when there is one, the friendly line otherwise; the raw text goes to the console only. */
function plainError(e) {
  console.error("stamp engine error:", e && e.message ? e.message : e);
  const m = /StampError: (.+)$/.exec(String((e && e.message) || ""));
  if (m && !/Exception|Traceback/.test(m[1])) return m[1].trim();
  return FRIENDLY;
}
const ARTISH = /\.(png|jpe?g|webp|svg)$/i;
const LABEL = { pass: "OK", warn: "Look", block: "Stop" };
const CLS = { pass: "info", warn: "warn", block: "block" };
/* Words that say "slab" or "around" are the roller's; the stamp has a face and an across. */
const RELABEL = [["Height on the slab", "Height on the face"], ["Place around", "Place across"], ["Copies around", "Copies across"]];
const TEXT_LAYOUT = [["single", "In place"], ["band", "Band across"], ["allover", "All over"]];

export function initStamp(ctx) {
  const { engine, $, el, css, toEngineFile, mb, dlLink, hasText, isSingle, isRepeat, OPTS, FONTS, TEXT_IDEAS, textFields } = ctx;
  const T = { params: { ...DEFAULTS }, file: null, last: null, seq: 0, shown: 0, busy: false, exporting: false, gen: 0, t0: 0, secs: 0, images: null };
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "null");
    if (saved && typeof saved === "object") for (const k of Object.keys(DEFAULTS)) if (saved[k] !== undefined && typeof saved[k] === typeof DEFAULTS[k]) T.params[k] = saved[k];
    if (T.params.art_source === "upload") T.params.art_source = DEFAULTS.art_source;     // the picture itself is not kept
  } catch (e) { /* storage may be unavailable */ }
  const P = T.params;
  const inputs = {};
  const rows = [];                       // {row, on, hide}
  let hideOff = false;                   // rows added while this is on disappear (not just grey out) when they do not apply
  const narrow = window.matchMedia("(max-width: 1023px)");
  const upload = () => P.art_source === "upload";
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(P)); } catch (e) { /* ignore */ } };

  /* ---------- settings panel ---------- */
  let tick = null;
  function throttled() {          // while a slider moves: at most one request every 120 ms
    if (tick) return;
    tick = setTimeout(() => { tick = null; clearTimeout(timer); requestPreview(); }, 120);
  }
  let timer = null;
  function schedule() { clearTimeout(timer); timer = setTimeout(requestPreview, 250); }
  /* Any change makes the last download stale: take away its Save link and file list. */
  function clearResult() {
    T.gen++;
    if (!T.exporting) $("stamp-export-result").replaceChildren();
    updateExport();
  }
  function changed(k, v, live) {
    P[k] = v;
    clearResult();
    save();
    syncEnabled();
    if (k === "text_size" || k === "text_font") syncTextNote();
    if (live) throttled(); else schedule();
  }
  function syncEnabled() {
    for (const r of rows) {
      if (!r.on) continue;
      const on = !!r.on(P);
      r.row.classList.toggle("is-off", !on);
      r.row.hidden = !!r.hide && !on;
      for (const c of r.row.querySelectorAll("input, select, button, textarea")) c.disabled = !on;
    }
  }
  function add(body, row, on) { body.append(row); rows.push({ row, on, hide: hideOff }); return row; }

  function hint(f) { return el("span", { class: "hint", id: "s-hint-" + f.k, hidden: true, text: f.min + " to " + f.max + (f.unit ? " " + f.unit : "") }); }
  function numRow(body, f, on) {
    const inp = el("input", { type: "number", id: "s-" + f.k, step: f.step, min: f.min, max: f.max, inputmode: "decimal" });
    inp.value = P[f.k];
    const h = hint(f);
    inp.setAttribute("aria-describedby", h.id);
    const rng = f.slider ? el("input", { type: "range", min: f.min, max: f.max, step: f.step, "aria-label": f.label, value: P[f.k] }) : null;
    inp.addEventListener("input", () => {
      const v = Number(inp.value);
      if (inp.value === "" || !Number.isFinite(v) || v < f.min || v > f.max) { inp.classList.add("invalid"); inp.setAttribute("aria-invalid", "true"); h.hidden = false; clearResult(); return; }
      inp.classList.remove("invalid"); inp.removeAttribute("aria-invalid"); h.hidden = true;
      if (rng) rng.value = v;
      changed(f.k, v, false);
    });
    const lab = el("label", { for: "s-" + f.k }, f.label, f.unit ? el("span", { class: "unit", text: f.unit }) : null);
    const row = el("div", { class: "row" }, lab, inp, h);
    add(body, row, on);
    inputs[f.k] = inp; inp.hint = h;
    if (rng) {
      rng.addEventListener("input", () => { inp.value = rng.value; inp.classList.remove("invalid"); h.hidden = true; changed(f.k, Number(rng.value), true); });
      rng.addEventListener("change", () => { clearTimeout(tick); tick = null; changed(f.k, Number(rng.value), true); });
      add(body, el("div", { class: "row wide srow" }, rng), on);
      inp.rng = rng;
    }
  }
  function intRow(body, f, on) {
    const inp = el("input", { type: "number", id: "s-" + f.k, step: 1, min: f.min, max: f.max, inputmode: "numeric" });
    inp.value = P[f.k];
    const set = (v) => { v = Math.max(f.min, Math.min(f.max, Math.round(v))); inp.value = v; inp.classList.remove("invalid"); changed(f.k, v, false); };
    inp.addEventListener("input", () => { const v = Number(inp.value); if (inp.value === "" || !Number.isFinite(v)) { inp.classList.add("invalid"); clearResult(); } else set(v); });
    const st = el("div", { class: "stepper" },
      el("button", { type: "button", "aria-label": f.label + ", one fewer", text: "-", onclick: () => set(Number(inp.value) - 1) }),
      inp,
      el("button", { type: "button", "aria-label": f.label + ", one more", text: "+", onclick: () => set(Number(inp.value) + 1) }));
    add(body, el("div", { class: "row" }, el("label", { for: "s-" + f.k }, f.label), st), on);
    inputs[f.k] = inp;
  }
  function selRow(body, f, opts, on) {
    const sel = el("select", { id: "s-" + f.k });
    for (const [v, t] of opts) sel.append(el("option", { value: String(v), text: t }));
    sel.value = String(P[f.k]);
    sel.addEventListener("change", () => changed(f.k, sel.value, false));
    add(body, el("div", { class: "row" }, el("label", { for: "s-" + f.k }, f.label), sel), on);
    inputs[f.k] = sel;
  }
  function boolRow(body, f, on) {
    const cb = el("input", { type: "checkbox", id: "s-" + f.k });
    cb.checked = !!P[f.k];
    cb.addEventListener("change", () => changed(f.k, cb.checked, false));
    add(body, el("div", { class: "row wide" }, el("label", { class: "check" }, cb, f.label)), on);
    inputs[f.k] = cb;
  }
  function segRow(body, label, items, key, onPick, on) {
    const seg = el("div", { class: "seg full", role: "group", "aria-label": label });
    const btns = items.map(([v, t]) => {
      const b = el("button", { type: "button", text: t });
      b.onclick = () => { changed(key, v, false); sync(); if (onPick) onPick(v); };
      seg.append(b);
      return [v, b];
    });
    const sync = () => { for (const [v, b] of btns) b.setAttribute("aria-pressed", String(P[key] === v)); };
    sync();
    add(body, el("div", { class: "row wide" }, el("span", { class: "lbl", text: label }), seg), on);
    return sync;
  }

  /* ----- art ----- */
  let fileNameEl = null, artSel = null;
  function artRow(body) {
    const wrap = el("div", { class: "row wide" });
    artSel = el("select", { id: "s-art" });
    artSel.append(el("option", { value: "upload", text: "Upload a picture" }));
    fileNameEl = el("p", { class: "upload-name" });
    artSel.addEventListener("change", () => {
      changed("art_source", artSel.value === "upload" ? "upload" : "pattern:" + artSel.value, false);
      if (artSel.value === "upload" && !T.file) $("stamp-upload-file").click();
      syncUploadUI();
    });
    engine.patterns().then((list) => {
      for (const pt of list.slice().reverse()) artSel.prepend(el("option", { value: pt.id, text: pt.name }));
      artSel.value = upload() ? "upload" : P.art_source.replace("pattern:", "");
      if (!artSel.value) artSel.value = list.length ? list[0].id : "upload";
      syncUploadUI();
    }).catch(() => { artSel.value = "upload"; syncUploadUI(); });
    wrap.append(el("label", { for: "s-art", class: "lbl" }, "Art"), artSel, fileNameEl);
    wrap.style.gridTemplateColumns = "1fr";
    add(body, wrap);
  }
  function syncUploadUI() {
    const up = upload();
    if (artSel && artSel.value !== (up ? "upload" : P.art_source.replace("pattern:", ""))) artSel.value = up ? "upload" : P.art_source.replace("pattern:", "");
    if (fileNameEl) fileNameEl.textContent = up ? (T.file ? T.file.name : "No file chosen yet.") : "";
    const b = $("stamp-upload");
    b.textContent = up && T.file ? "Change picture" : "Upload a picture";
    b.title = up && T.file ? T.file.name : "SVG, PNG, JPEG or WEBP. Drawings are traced to black and white; a photo of a person becomes a pen sketch.";
    syncEnabled();
  }

  /* ----- text (the roller's controls) ----- */
  let textNoteEl = null;
  function syncTextNote() {
    if (!textNoteEl) return;
    const f = FONTS.find((x) => x[0] === P.text_font);
    if (!hasText(P) || !f) { textNoteEl.textContent = ""; textNoteEl.hidden = true; return; }
    textNoteEl.hidden = false;
    const small = P.text_size < f[3];
    textNoteEl.textContent = small
      ? f[1] + " needs " + f[3] + " mm or more to keep 1 mm gaps in clay. Make it taller or pick a bolder font."
      : "Letter height is the height of a capital H. Words print backwards on the face and read right in the clay.";
    textNoteEl.classList.toggle("warn", small);
  }
  function setMany(vals) {
    Object.assign(P, vals);
    for (const [k, v] of Object.entries(vals)) {
      const inp = inputs[k];
      if (!inp) continue;
      if (inp.type === "checkbox") inp.checked = !!v; else inp.value = v == null ? "" : String(v);
      if (inp.rng) inp.rng.value = v;
      inp.classList.remove("invalid");
    }
    clearResult(); save(); syncEnabled(); syncTextNote(); schedule();
  }
  function ideasRow(body) {
    const grid = el("div", { class: "ideas", role: "group", "aria-label": "Text ideas" });
    for (const idea of TEXT_IDEAS) {
      const b = el("button", { type: "button", class: "idea" });
      b.innerHTML = '<svg viewBox="0 0 44 40" aria-hidden="true">' + idea.svg + "</svg>";
      b.append(el("span", { text: idea.label }));
      b.onclick = () => {
        const v = idea.set(P);
        if (!hasText(P) || TEXT_IDEAS.some((x) => x.sample === P.text)) v.text = idea.sample;
        setMany(v);
      };
      grid.append(b);
    }
    add(body, el("div", { class: "row wide" }, el("span", { class: "lbl", text: "Start from an idea" }), grid));
  }
  function textInputRow(body) {
    const ta = el("textarea", { id: "s-text", rows: 2, maxlength: 60, placeholder: "A name, a date or a saying. Enter starts a new line (3 lines at most)." });
    ta.value = P.text || "";
    ta.addEventListener("input", () => { changed("text", ta.value, false); syncTextNote(); });
    inputs.text = ta;
    add(body, el("div", { class: "row wide" }, el("label", { for: "s-text", class: "lbl" }, "Words"), ta));
  }

  /* ----- build ----- */
  function buildForm() {
    const form = $("stamp-params");
    form.replaceChildren();
    rows.length = 0;
    const isUp = (p) => p.art_source === "upload";
    const isPortrait = (p) => p.art_source === "upload" && p.art_style === "portrait";
    const phone = window.matchMedia("(max-width: 767px)").matches;
    const group = (name, open, fill) => {
      const body = el("div", { class: "group-body" });
      fill(body);
      form.append(el("details", { class: "group", open: phone ? name === "Shape and size" : open }, el("summary", { text: name }), body));
    };

    group("Shape and size", true, (b) => {
      segRow(b, "Shape", [["rect", "Square or rectangle"], ["round", "Round or oval"]], "shape", null);
      numRow(b, { k: "width_mm", label: "Width", unit: "mm", min: 25, max: 150, step: 1, slider: true });
      numRow(b, { k: "height_mm", label: "Height", unit: "mm", min: 25, max: 150, step: 1, slider: true });
      b.append(el("p", { class: "note", text: "R80: each side 25 to 150 mm. A round stamp with different width and height is an oval." }));
    });

    group("Art", true, (b) => {
      hideOff = true;
      artRow(b);
      segRow(b, "What the picture is", [["trace", "Drawing or logo"], ["portrait", "Photo of a person"]], "art_style", (v) => {
        // the roller's advice for pen sketches: a shallower, gentler relief keeps the close strokes apart in clay
        if (v === "portrait" && !T.sketchTouched) setMany({ depth: 1.2, draft_deg: 10 });
        T.sketchTouched = true;
      }, isUp);
      numRow(b, { k: "sketch_detail", label: "Sketch detail", min: 0, max: 1, step: 0.05, slider: true }, isPortrait);
      boolRow(b, { k: "sketch_shading", label: "Sketch shading" }, isPortrait);
      numRow(b, { k: "art_scale", label: "Picture size", unit: "%", min: 25, max: 300, step: 5, slider: true }, isUp);
      numRow(b, { k: "art_shift_x", label: "Move left or right", min: -1, max: 1, step: 0.02, slider: true }, isUp);
      numRow(b, { k: "art_shift_y", label: "Move up or down", min: -1, max: 1, step: 0.02, slider: true }, isUp);
      intRow(b, { k: "n_across", label: "Pattern repeats across", min: 1, max: 12 }, (p) => !isUp(p));
      segRow(b, "What the clay shows", [[false, "Art pressed in"], [true, "Art stands up"]], "invert", null);
      hideOff = false;
    });

    group("Text", true, (b) => {
      for (const f0 of textFields) {
        if (f0.special === "text-ideas") { ideasRow(b); continue; }
        if (f0.special === "text-input") { textInputRow(b); continue; }
        if (f0.special === "text-size-note") { textNoteEl = el("p", { class: "note text-note", role: "status" }); b.append(textNoteEl); syncTextNote(); continue; }
        let label = f0.label;
        for (const [a, c] of RELABEL) if (label === a) label = c;
        const f = { ...f0, label };
        if (f.t === "num") numRow(b, f, f.on);
        else if (f.t === "int") intRow(b, f, f.on);
        else if (f.t === "sel") selRow(b, f, f.k === "text_layout" ? TEXT_LAYOUT : OPTS[f.k], f.on);
        else boolRow(b, f, f.on);
      }
    });

    group("Relief", true, (b) => {
      numRow(b, { k: "depth", label: "Depth", unit: "mm", min: 0.8, max: 3, step: 0.1, slider: true });
      numRow(b, { k: "draft_deg", label: "Draft", unit: "deg", min: 0, max: 45, step: 1 });
      numRow(b, { k: "edge_round", label: "Edge round", unit: "mm", min: 0, max: 2, step: 0.1 });
    });

    group("Border and knob", true, (b) => {
      boolRow(b, { k: "rim_on", label: "Border rim at full height" });
      numRow(b, { k: "rim_mm", label: "Border width", unit: "mm", min: 1.5, max: 6, step: 0.5, slider: true }, (p) => p.rim_on);
      boolRow(b, { k: "knob_on", label: "Knob (glued to the back)" });
      b.append(el("p", { class: "note", text: "With a knob the block under the relief is 6 mm. With no knob it is 12 mm thick so you can hold it by the edges." }));
    });

    form.append(el("div", { class: "group-body" }, el("button", {
      type: "button", class: "btn", text: "Reset to the defaults", onclick: () => {
        const keepFile = T.file;
        Object.assign(P, DEFAULTS);
        T.sketchTouched = false;
        if (keepFile) T.file = keepFile;
        save(); buildForm(); syncUploadUI(); schedule();
      },
    })));
    syncEnabled();
  }

  /* ---------- status and requests ---------- */
  function setStatus(text, kind) {
    const s = $("stamp-status");
    s.textContent = text;
    s.className = "cookie-status" + (kind ? " " + kind : "");
    if (narrow.matches && kind) s.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  function setBusy(on) {
    T.busy = on;
    $("busy").textContent = on ? "Updating" : "";
    if (on) setStatus("Making the stamp...", "busy");
    $("stamp-stage").classList.toggle("busy", on);
    $("stamp-stage").setAttribute("aria-busy", String(on));
    updateExport();
  }
  function empty(msg, isErr) {
    const e = $("stamp-empty");
    e.textContent = msg; e.hidden = false; e.classList.toggle("err", !!isErr);
  }
  async function requestPreview() {
    if (document.querySelector("#stamp-params input.invalid")) return;
    if (upload() && !T.file) { T.last = null; setStatus("Upload a picture to start.", ""); empty("Upload a drawing, logo or photo to start. SVG, PNG, JPEG or WEBP.", false); renderChecks(); drawAll(); return; }
    const mine = ++T.seq;
    T.t0 = performance.now();
    setBusy(true);
    try {
      const data = await engine.stampPreview({ ...P }, upload() ? T.file : null);
      if (mine <= T.shown) return;
      T.shown = mine;
      T.last = data;
      T.secs = (performance.now() - T.t0) / 1000;
      // the engine may have limited a value (depth, border width, draft, edge round)
      for (const k of ["depth", "rim_mm", "draft_deg", "edge_round"]) {
        const v = data.params && data.params[k];
        if (Number.isFinite(v) && v !== P[k]) { P[k] = v; if (inputs[k]) { inputs[k].value = v; if (inputs[k].rng) inputs[k].rng.value = v; } }
      }
      buildImages();
      renderAll();
      const warns = data.checks.filter((x) => x.level === "warn").length;
      if (!data.face) {
        const why = data.checks.filter((x) => x.level === "block").map((x) => x.text).join(" ");
        setStatus(why || "Nothing to show.", "err");
        empty(why || "Nothing to show.", true);
      } else {
        $("stamp-empty").hidden = true;
        setStatus("Ready: " + data.size.w + " x " + data.size.h + " mm " + (data.size.shape === "round" ? "round" : "square") + " stamp"
          + (data.can_export ? "" : ", but the download is blocked (see Checks)") + (warns ? ", " + warns + " thing" + (warns > 1 ? "s" : "") + " to look at." : "."), data.can_export ? "ok" : "err");
      }
    } catch (e) {
      if (e.name === "Superseded") return;
      T.last = null; T.images = null;
      const msg = plainError(e);
      setStatus(msg, "err");
      empty(msg, true);
      renderChecks(); drawAll();
    } finally { setBusy(false); }
  }

  /* ---------- checks ---------- */
  function renderChecks() {
    const ul = $("stamp-checks");
    ul.replaceChildren();
    const d = T.last;
    if (!d) { $("stamp-count").textContent = ""; ul.append(el("li", { class: "rules-empty", text: "Checks appear after the first preview." })); updateExport(); return; }
    const order = { block: 0, warn: 1, pass: 2 };
    const list = [...d.checks].sort((a, b) => order[a.level] - order[b.level]);
    for (const c of list) {
      ul.append(el("li", { class: "rule " + CLS[c.level] }, el("span", { class: "rid", text: LABEL[c.level] }), el("span", { class: "msg", text: c.text }), el("span")));
    }
    const nb = list.filter((c) => c.level === "block").length, nw = list.filter((c) => c.level === "warn").length;
    $("stamp-count").textContent = nb ? nb + " stop" : nw ? nw + " to look at" : "all clear";
    updateExport();
  }
  function updateExport() {
    const d = T.last;
    const b = $("stamp-export");
    const invalid = !!document.querySelector("#stamp-params input.invalid");
    b.disabled = T.exporting || T.busy || invalid || !d || !d.can_export;
    const note = $("stamp-export-note");
    note.classList.toggle("block", !!(d && !d.can_export));
    note.textContent = T.exporting ? "Building the files..." : invalid ? "Fix the number marked in red first." : T.busy ? "Updating the preview..."
      : !d ? "" : d.can_export ? "The zip has the stamp, the knob, a plated 3MF, a clay preview and a print sheet." : "The download is blocked until the stop items above are fixed.";
  }
  function renderCaption() {
    const d = T.last;
    if (!d || !d.face) { $("stamp-caption").textContent = ""; return; }
    const s = d.size;
    $("stamp-caption").textContent = "Face " + s.w + " x " + s.h + " mm, " + (d.params.total_height_mm) + " mm tall"
      + (s.knob ? ", knob pad " + s.knob.pad + " mm" : ", no knob") + ", about " + Math.round(s.tris / 1000).toLocaleString() + " thousand triangles" + (T.secs ? ", " + T.secs.toFixed(1) + " s" : "");
  }
  function renderAll() { renderChecks(); renderCaption(); syncUploadUI(); drawAll(); }

  /* ---------- pictures ---------- */
  const probe = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  probe.canvas.width = probe.canvas.height = 1;
  function rgbOf(name) {
    probe.clearRect(0, 0, 1, 1);
    probe.fillStyle = "#000"; probe.fillStyle = css(name);
    probe.fillRect(0, 0, 1, 1);
    const d = probe.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2]];
  }
  function unb64(b64) {
    const s = atob(b64);
    const a = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i);
    return a;
  }
  function toCanvas(cols, rows, fn) {
    const cv = document.createElement("canvas");
    cv.width = cols; cv.height = rows;
    const g = cv.getContext("2d");
    const im = g.createImageData(cols, rows);
    for (let i = 0; i < cols * rows; i++) { const [r, gg, b] = fn(i); im.data[4 * i] = r; im.data[4 * i + 1] = gg; im.data[4 * i + 2] = b; im.data[4 * i + 3] = 255; }
    g.putImageData(im, 0, 0);
    return cv;
  }
  function buildImages() {
    const f = T.last && T.last.face;
    if (!f) { T.images = null; return; }
    const face = unb64(f.face_b64), clay = unb64(f.clay_b64);
    const base = rgbOf("--clay-fired");
    T.images = {
      face: toCanvas(f.cols, f.rows, (i) => [face[i], face[i], face[i]]),
      clay: toCanvas(f.cols, f.rows, (i) => { const k = clay[i] / 205; return [Math.min(255, base[0] * k), Math.min(255, base[1] * k), Math.min(255, base[2] * k)]; }),
    };
  }
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
  function outline(g, d, x0, y0, w, h) {
    g.beginPath();
    if (d.size.shape === "round") g.ellipse(x0 + w / 2, y0 + h / 2, w / 2, h / 2, 0, 0, Math.PI * 2);
    else g.rect(x0, y0, w, h);
  }
  function drawOne(id, key, shadow) {
    const { g, W, H } = setup($(id));
    const d = T.last;
    if (!d || !d.face || !T.images) return;
    const pad = 28, capH = 26;
    const k = Math.min((W - 2 * pad) / d.size.w, (H - 2 * pad - capH) / d.size.h);
    const w = d.size.w * k, h = d.size.h * k, x0 = (W - w) / 2, y0 = pad + (H - 2 * pad - capH - h) / 2 + 4;
    if (shadow) {
      g.save(); g.shadowColor = "rgba(0,0,0,0.45)"; g.shadowBlur = 14; g.shadowOffsetY = 4;
      g.fillStyle = css("--clay-fired"); outline(g, d, x0, y0, w, h); g.fill(); g.restore();
    }
    g.save();
    outline(g, d, x0, y0, w, h); g.clip();
    g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high";
    g.drawImage(T.images[key], x0, y0, w, h);
    g.restore();
    g.strokeStyle = "rgba(0,0,0,0.5)"; g.lineWidth = 1.5;
    outline(g, d, x0, y0, w, h); g.stroke();
  }
  function drawAll() {
    drawOne("stamp-face", "face", false);
    drawOne("stamp-clay", "clay", true);
  }

  /* ---------- upload, drag and drop, view switch ---------- */
  /* A 256 px thumbnail with more than 40 grey levels and over 30 % mid-tones is a photograph, not a drawing. */
  async function looksLikePhoto(f) {
    if (/\.svg$/i.test(f.name) || f.type === "image/svg+xml") return false;
    try {
      const bmp = await createImageBitmap(f);
      const k = 256 / Math.max(bmp.width, bmp.height, 1);
      const w = Math.max(1, Math.round(bmp.width * Math.min(1, k))), h = Math.max(1, Math.round(bmp.height * Math.min(1, k)));
      const c = document.createElement("canvas");
      c.width = w; c.height = h;
      const g = c.getContext("2d", { willReadFrequently: true });
      g.fillStyle = "#fff"; g.fillRect(0, 0, w, h);
      g.drawImage(bmp, 0, 0, w, h);
      const d = g.getImageData(0, 0, w, h).data;
      const seen = new Set();
      let mid = 0;
      for (let i = 0; i < d.length; i += 4) {
        const v = Math.round(0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]);
        seen.add(v);
        if (v > 40 && v < 215) mid++;
      }
      // same test as the cookie engine: a photo has many grey levels AND lots of mid-tones; a drawing shrunk to
      // 256 px gains grey levels on its edges but stays mostly black and white
      return seen.size > 40 && mid / (d.length / 4) > 0.30;
    } catch (e) { return false; }
  }
  /* A raster picture is shrunk to 2000 px on its longest side before it goes to the engine (the engine refuses
   * more than 25 megapixels); the stamp face is at most 150 mm, so nothing visible is lost. */
  async function shrink(f) {
    if (/\.svg$/i.test(f.name) || f.type === "image/svg+xml") return f;
    try {
      const bmp = await createImageBitmap(f);
      const k = 2000 / Math.max(bmp.width, bmp.height, 1);
      if (k >= 1) { if (bmp.close) bmp.close(); return f; }
      const c = document.createElement("canvas");
      c.width = Math.max(1, Math.round(bmp.width * k)); c.height = Math.max(1, Math.round(bmp.height * k));
      const g = c.getContext("2d");
      g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
      g.drawImage(bmp, 0, 0, c.width, c.height);
      if (bmp.close) bmp.close();
      const blob = await new Promise((res) => c.toBlob(res, "image/png"));
      return blob ? new File([blob], f.name.replace(/\.[^.]+$/, "") + ".png", { type: "image/png" }) : f;
    } catch (e) { return f; }
  }
  const NOT_PICTURE = "R80: That file is not a picture. Use a PNG, JPEG, WEBP or SVG file.";
  async function useFile(f) {
    if (!f) return;
    // a big picture takes a while to read; if another file is chosen meanwhile, the later choice wins
    const ticket = (T.uploadTicket = (T.uploadTicket || 0) + 1);
    if (!(ARTISH.test(f.name) || /^image\//.test(f.type))) { setStatus(NOT_PICTURE, "err"); empty(NOT_PICTURE, true); return; }
    setStatus("Reading the picture...", "busy");
    const photo = await looksLikePhoto(f);
    const ready = await shrink(await toEngineFile(f));
    if (ticket !== T.uploadTicket) return;
    T.file = ready;
    clearResult();
    T.sketchTouched = false;
    Object.assign(P, { art_source: "upload", art_style: photo ? "portrait" : "trace", art_scale: 100, art_shift_x: 0, art_shift_y: 0 });
    if (photo) { T.sketchTouched = true; Object.assign(P, { depth: 1.2, draft_deg: 10 }); }
    T.last = null;
    save();
    buildForm();
    syncUploadUI();
    schedule();
  }
  $("stamp-upload-file").addEventListener("change", (e) => { useFile(e.target.files[0]); e.target.value = ""; });
  const stage = $("stamp-stage");
  stage.addEventListener("dragover", (e) => { e.preventDefault(); stage.classList.add("drop"); });
  stage.addEventListener("dragleave", () => stage.classList.remove("drop"));
  stage.addEventListener("drop", (e) => {
    e.preventDefault(); stage.classList.remove("drop");
    const files = [...(e.dataTransfer?.files || [])];
    const f = files.find((x) => ARTISH.test(x.name) || /^image\//.test(x.type));
    if (f) useFile(f);
    else if (files.length) { setStatus(NOT_PICTURE, "err"); empty(NOT_PICTURE, true); }
  });
  const setView = (v) => {
    stage.dataset.view = v;
    for (const id of ["both", "face", "clay"]) $("sv-" + id).setAttribute("aria-pressed", String(id === v));
    requestAnimationFrame(drawAll);
  };
  for (const id of ["both", "face", "clay"]) $("sv-" + id).onclick = () => setView(id);
  narrow.addEventListener("change", () => setView(narrow.matches ? "clay" : "both"));   // re-pick when the phone turns
  new ResizeObserver(() => drawAll()).observe(stage);

  /* ---------- download ---------- */
  $("stamp-export").onclick = async () => {
    if (T.exporting) return;
    const res = $("stamp-export-result");
    const snap = { ...P }, file = snap.art_source === "upload" ? T.file : null, gen = T.gen;   // what was on screen at the click
    T.exporting = true;
    res.replaceChildren(el("span", { text: "Building the files. This takes a few seconds; the page stays usable." }));
    updateExport();
    try {
      const j = await engine.stampExport(snap, file);
      res.replaceChildren();
      if (gen !== T.gen) {            // a setting changed while it was building: the zip is of the old settings
        res.append(el("span", { class: "err", text: "The settings changed while the files were building, so this download was dropped. Press Download again." }));
      } else if (j.blocked || !j.href) {
        const why = (j.checks || []).filter((c) => c.level === "block").map((c) => c.text);
        res.append(el("span", { class: "err", text: "Not exported. " + (why.join(" ") || "R85: The model is not printable.") }));
      } else {
        const a = dlLink(j.href, j.filename, "Save " + j.filename + ", " + mb(j.bytes), true);
        res.append(a);
        a.click();
        res.append(el("p", { class: "caption", text: "Inside: " + (j.files || []).join(", ") + "." }));
        res.append(el("p", { class: "caption", text: "Print the stamp face up, no supports, 0.2 mm layers. Print the knob standing on its flat pad. Glue the pad centred on the back with CA glue or epoxy." }));
      }
    } catch (e) {
      res.replaceChildren(el("span", { class: "err", text: plainError(e) }));
    } finally { T.exporting = false; updateExport(); }
  };

  buildForm();
  syncUploadUI();
  renderChecks();
  if (narrow.matches) setView("clay");       // one view at a time on a phone; the toggle switches
  return {
    show() { syncUploadUI(); schedule(); requestAnimationFrame(drawAll); },
    hide() { clearTimeout(timer); },
    state: T,
  };
}
