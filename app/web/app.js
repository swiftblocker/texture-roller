import * as THREE from "./vendor/three.module.js";
import { OrbitControls } from "./vendor/OrbitControls.js";
import { createEngine } from "./engine-client.js";

/* ---------- parameters ---------- */
const DEFAULTS = {
  diameter: 45.0, length: 250.0,
  art_source: "pattern:waves",
  tile_width_mm: null, n_around: 3, n_along: null,
  offset: "none", offset_fraction: 0.5, rotation: 0, mirror: true, invert: false, spacing: 0.0,
  depth: 1.5, draft_deg: 15.0, edge_round: 0.4,
  seam_method: "auto", seam_blend_pct: 5.0, seam_theta_deg: null,
  band: 3.0, bands_on: true, end_chamfer: 1.0, alignment_ticks: false,
  bore_preset: "dowel_half", bore_diameter: null, bore_clearance: 0.3,
  split: false, clay_body: "stoneware", clay_state: "firm",
  glaze_flag: false, nozzle: 0.4, pitch_preview: 0.5, pitch_export: 0.2,
  cnc_rotary_max_length: 0,
};

const S = {
  params: { ...DEFAULTS },
  upload: null,
  last: null,
  fired: false,
  glaze: false,
  passes: 1,
  phases: [0, 0, 0],
  seq: 0,
  ctl: null,
  busy: 0,
};

try {
  const saved = JSON.parse(localStorage.getItem("roller.params") || "null");
  if (saved && typeof saved === "object") Object.assign(S.params, saved);
} catch (e) { /* storage may be unavailable */ }

const MQ_NARROW = window.matchMedia("(max-width: 1023px)");
const MQ_PHONE = window.matchMedia("(max-width: 767px)");
const IOS = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v === true) n.setAttribute(k, "");
    else if (v !== false && v != null) n.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) n.append(k);
  return n;
};
const fmt = (v, d = 1) => (v == null || Number.isNaN(v) ? "-" : Number(v).toFixed(d));
const trim = (v) => (v == null ? "" : String(Math.round(v * 100) / 100));

/* ---------- form ---------- */
const OPTS = {
  offset: [["none", "None"], ["half_drop", "Half drop"], ["brick", "Brick"]],
  rotation: [[0, "0 deg"], [90, "90 deg"], [180, "180 deg"], [270, "270 deg"]],
  seam_method: [["auto", "Auto"], ["tile", "Tiling art"], ["background", "On background"], ["blend", "Blend"], ["gutter", "Gutter"]],
  bore_preset: [["dowel_half", "1/2 in dowel"], ["dowel_3q", "3/4 in dowel"], ["rod_8", "8 mm rod"], ["custom", "Custom"], ["none", "No bore"]],
  clay_body: [["stoneware", "Stoneware"], ["porcelain", "Porcelain"], ["earthenware", "Earthenware"], ["paper", "Paper clay"]],
  clay_state: [["soft", "Soft"], ["firm", "Firm"], ["leather", "Leather hard"]],
};

const GROUPS = [
  { name: "Size", open: true, fields: [
    { k: "length", label: "Length", unit: "mm", t: "num", step: 1, min: 20, max: 400, rule: "R01" },
    { k: "diameter", label: "Diameter at top of relief", unit: "mm", t: "num", step: 0.5, min: 5, max: 200, rule: "R04" },
    { special: "size-readouts" },
  ] },
  { name: "Art", open: true, fields: [
    { special: "art-source" },
    { k: "tile_width_mm", label: "Tile width", unit: "mm", t: "num", opt: true, step: 0.5, min: 1, ph: "auto" },
    { k: "n_around", label: "Repeats around", t: "int", min: 1, max: 99, rule: "R29" },
    { k: "n_along", label: "Repeats along", t: "num", opt: true, step: 0.25, min: 0.1, ph: "auto", rule: "R30" },
    { k: "offset", label: "Offset", t: "sel", rule: "R32" },
    { k: "rotation", label: "Rotation", t: "sel", num: true, rule: "R33" },
    { k: "mirror", label: "Mirror for the roller surface", t: "bool", rule: "R35" },
    { k: "spacing", label: "Spacing between tiles", unit: "mm", t: "num", step: 0.5, min: 0, rule: "R34" },
    { special: "mode" },
    { special: "solver" },
  ] },
  { name: "Relief", open: true, fields: [
    { k: "depth", label: "Depth", unit: "mm", t: "num", step: 0.1, min: 0.1, max: 8, rule: "R13" },
    { k: "draft_deg", label: "Draft", unit: "deg", t: "num", step: 1, min: 0, max: 45, rule: "R22" },
    { k: "edge_round", label: "Edge round", unit: "mm", t: "num", step: 0.1, min: 0, max: 2, rule: "R24" },
  ] },
  { name: "Seam", open: false, fields: [
    { k: "seam_method", label: "Method", t: "sel", rule: "R39" },
    { k: "seam_blend_pct", label: "Blend width", unit: "% of C", t: "num", step: 0.5, min: 0, max: 20, on: (p) => p.seam_method === "blend" || p.seam_method === "auto" },
    { k: "seam_theta_deg", label: "Seam angle", unit: "deg", t: "num", opt: true, step: 5, min: 0, max: 360, ph: "auto", rule: "R40" },
    { k: "alignment_ticks", label: "Alignment ticks on the end band", t: "bool", rule: "R44" },
  ] },
  { name: "Core", open: false, fields: [
    { k: "bore_preset", label: "Bore", t: "sel", rule: "R56" },
    { k: "bore_diameter", label: "Measured dowel diameter", unit: "mm", t: "num", opt: true, step: 0.05, min: 1, ph: "nominal", on: (p) => p.bore_preset !== "none" },
    { k: "bore_clearance", label: "Clearance", unit: "mm", t: "num", step: 0.05, min: 0, max: 1, on: (p) => p.bore_preset !== "none" },
    { k: "bands_on", label: "End bands", t: "bool", rule: "R42" },
    { k: "band", label: "End band width", unit: "mm", t: "num", step: 0.5, min: 0, max: 10, on: (p) => p.bands_on },
    { k: "end_chamfer", label: "End chamfer", unit: "mm", t: "num", step: 0.25, min: 0, max: 5, rule: "R43" },
    { k: "split", label: "Split in two", t: "bool" },
  ] },
  { name: "Clay", open: false, fields: [
    { k: "clay_body", label: "Body", t: "sel", rule: "R18" },
    { k: "clay_state", label: "State", t: "sel", rule: "R47" },
    { k: "glaze_flag", label: "Will be glazed", t: "bool", rule: "R28" },
  ] },
];

const inputs = {};   // key -> input element
const rowsByKey = {};

function setParam(k, v) {
  S.params[k] = v;
  syncEnabled();
  readouts();
  schedule();
  try { localStorage.setItem("roller.params", JSON.stringify(S.params)); } catch (e) { /* ignore */ }
}

function numField(f) {
  const inp = el("input", { type: "number", id: "f-" + f.k, step: f.step, min: f.min, max: f.max, placeholder: f.ph || null, inputmode: "decimal" });
  inp.value = S.params[f.k] == null ? "" : S.params[f.k];
  inp.addEventListener("input", () => {
    if (inp.value === "") {
      if (f.opt) { inp.classList.remove("invalid"); setParam(f.k, null); }
      else inp.classList.add("invalid");
      return;
    }
    const v = Number(inp.value);
    if (!Number.isFinite(v) || (f.min != null && v < f.min) || (f.max != null && v > f.max)) { inp.classList.add("invalid"); return; }
    inp.classList.remove("invalid");
    setParam(f.k, v);
  });
  inputs[f.k] = inp;
  return inp;
}

function intField(f) {
  const inp = el("input", { type: "number", id: "f-" + f.k, step: 1, min: f.min, max: f.max, inputmode: "numeric" });
  inp.value = S.params[f.k];
  const set = (v) => { v = Math.max(f.min, Math.min(f.max, Math.round(v))); inp.value = v; inp.classList.remove("invalid"); setParam(f.k, v); };
  inp.addEventListener("input", () => { const v = Number(inp.value); if (inp.value === "" || !Number.isFinite(v)) inp.classList.add("invalid"); else set(v); });
  inputs[f.k] = inp;
  return el("div", { class: "stepper" },
    el("button", { type: "button", "aria-label": f.label + ", one fewer", text: "-", onclick: () => set(Number(inp.value) - 1) }),
    inp,
    el("button", { type: "button", "aria-label": f.label + ", one more", text: "+", onclick: () => set(Number(inp.value) + 1) }));
}

function selField(f) {
  const sel = el("select", { id: "f-" + f.k });
  for (const [v, t] of OPTS[f.k]) sel.append(el("option", { value: String(v), text: t }));
  sel.value = String(S.params[f.k]);
  sel.addEventListener("change", () => setParam(f.k, f.num ? Number(sel.value) : sel.value));
  inputs[f.k] = sel;
  return sel;
}

function boolField(f) {
  const cb = el("input", { type: "checkbox", id: "f-" + f.k });
  cb.checked = !!S.params[f.k];
  cb.addEventListener("change", () => setParam(f.k, cb.checked));
  inputs[f.k] = cb;
  return cb;
}

function labelFor(f) {
  const l = el("label", { for: "f-" + f.k }, f.label);
  if (f.unit) l.append(el("span", { class: "unit", text: f.unit }));
  if (f.rule) l.append(el("span", { class: "rule-ref", text: f.rule }));
  return l;
}

let readoutEls = {};
function sizeReadouts() {
  const dl = el("dl", { class: "readouts", "aria-live": "polite" });
  for (const [id, label] of [["C", "Circumference C, mm"], ["rw", "Repeat width, mm"], ["th", "Tile height, mm"], ["rev", "Revolutions per 254 mm"]]) {
    const dd = el("dd", { text: "-" });
    readoutEls[id] = dd;
    dl.append(el("div", { class: "ro-" + id }, el("dt", { text: label }), dd));
  }
  return dl;
}
function readouts() {
  const p = S.params;
  const C = Math.PI * p.diameter;
  if (!readoutEls.C) return;
  readoutEls.C.textContent = fmt(C, 2);
  readoutEls.rw.textContent = fmt(p.tile_width_mm || C / Math.max(1, p.n_around), 2);
  const th = S.last && S.last.derived ? S.last.derived.tile_height : null;
  readoutEls.th.textContent = th == null ? "-" : fmt(th, 1);
  readoutEls.rev.textContent = fmt(254 / C, 2);
  if (liveEls.C) {
    liveEls.C.textContent = readoutEls.C.textContent;
    liveEls.rw.textContent = readoutEls.rw.textContent;
    liveEls.rev.textContent = readoutEls.rev.textContent;
  }
}
const liveEls = {};
function buildLive() {
  const dl = $("live");
  for (const [id, label] of [["C", "C, mm"], ["rw", "Repeat width, mm"], ["rev", "Revs per 254 mm"]]) {
    const dd = el("dd", { text: "-" });
    liveEls[id] = dd;
    dl.append(el("div", {}, el("dt", { text: label }), dd));
  }
}

function artSource() {
  const wrap = el("div", { class: "row wide" });
  const sel = el("select", { id: "f-art" });
  sel.append(el("option", { value: "upload", text: "Upload SVG, PNG or JPEG" }));
  inputs.art_source = sel;
  const file = el("input", { type: "file", id: "f-file", accept: "image/png,image/jpeg,image/svg+xml,.svg", hidden: true });
  const name = el("p", { class: "upload-name" });
  const sync = () => {
    const up = sel.value === "upload";
    file.hidden = !up;
    name.textContent = up ? (S.upload ? S.upload.name : "No file chosen. SVG is clean-up only, PNG and JPEG are traced.") : "";
  };
  sel.addEventListener("change", () => {
    if (sel.value === "upload") setParam("art_source", "upload");
    else setParam("art_source", "pattern:" + sel.value);
    sync();
  });
  file.addEventListener("change", () => { S.upload = file.files[0] || null; sync(); schedule(); });
  engine.patterns().then((list) => {
    for (const pt of list.slice().reverse()) sel.prepend(el("option", { value: pt.id, text: pt.name }));
    const cur = S.params.art_source;
    sel.value = cur === "upload" ? "upload" : cur.replace("pattern:", "");
    if (!sel.value) sel.value = list.length ? list[0].id : "upload";
    sync();
  }).catch(() => { sel.value = "upload"; sync(); });
  wrap.append(el("label", { for: "f-art", class: "lbl" }, "Art"), sel, file, name);
  wrap.style.gridTemplateColumns = "1fr";
  return wrap;
}

function modeField() {
  const wrap = el("div", { class: "row wide" });
  const seg = el("div", { class: "seg full", role: "group", "aria-label": "What the clay shows" });
  const a = el("button", { type: "button", text: "Art pressed in" });
  const b = el("button", { type: "button", text: "Art stands up" });
  const sync = () => { a.setAttribute("aria-pressed", String(!S.params.invert)); b.setAttribute("aria-pressed", String(!!S.params.invert)); };
  a.onclick = () => { setParam("invert", false); sync(); };
  b.onclick = () => { setParam("invert", true); sync(); };
  sync();
  seg.append(a, b);
  wrap.append(el("span", { class: "lbl", text: "What the clay shows" + " (R36)" }), seg);
  return wrap;
}

function solverBlock() {
  const wrap = el("div", { class: "row wide", style: "gap:6px;display:grid" });
  const list = el("div", { class: "solver-list", hidden: true, role: "list" });
  const note = el("p", { class: "note" });
  const btn = el("button", { type: "button", class: "btn", text: "Find diameters for this tile" });
  btn.onclick = async () => {
    const tw = S.params.tile_width_mm || (Math.PI * S.params.diameter) / Math.max(1, S.params.n_around);
    note.textContent = "Solving for a " + fmt(tw, 2) + " mm tile.";
    try {
      const rows = await engine.solveRepeat(tw);
      list.replaceChildren();
      list.hidden = rows.length === 0;
      note.textContent = rows.length ? "Pick a row to set diameter and repeats around." : "No diameter between 25 and 100 mm fits this tile.";
      for (const c of rows) {
        const b = el("button", { type: "button", role: "listitem" },
          el("span", { text: "D " + fmt(c.diameter, 1) }),
          el("span", { text: c.n_around + " around" }),
          el("span", { text: (c.stretch_pct >= 0 ? "+" : "") + fmt(c.stretch_pct, 2) + "% stretch" }));
        b.onclick = () => {
          S.params.diameter = c.diameter; S.params.n_around = c.n_around;
          inputs.diameter.value = c.diameter; inputs.n_around.value = c.n_around;
          for (const x of list.children) x.removeAttribute("aria-current");
          b.setAttribute("aria-current", "true");
          setParam("diameter", c.diameter);
        };
        list.append(b);
      }
    } catch (e) { note.textContent = "Solver failed (" + e.message + ")."; }
  };
  wrap.append(btn, list, note);
  return wrap;
}

function buildForm() {
  const form = $("params");
  for (const g of GROUPS) {
    const body = el("div", { class: "group-body" });
    for (const f of g.fields) {
      if (f.special === "size-readouts") { body.append(sizeReadouts()); continue; }
      if (f.special === "art-source") { body.append(artSource()); continue; }
      if (f.special === "mode") { body.append(modeField()); continue; }
      if (f.special === "solver") { body.append(solverBlock()); continue; }
      let ctl;
      if (f.t === "num") ctl = numField(f);
      else if (f.t === "int") ctl = intField(f);
      else if (f.t === "sel") ctl = selField(f);
      else ctl = boolField(f);
      let row;
      if (f.t === "bool") {
        row = el("div", { class: "row wide" }, el("label", { class: "check" }, ctl, f.label, f.rule ? el("span", { class: "rule-ref", text: f.rule }) : null));
      } else {
        row = el("div", { class: "row" }, labelFor(f), ctl);
      }
      rowsByKey[f.k] = { row, f };
      body.append(row);
    }
    form.append(el("details", { class: "group", open: MQ_PHONE.matches ? g.name === "Size" : g.open }, el("summary", { text: g.name }), body));
  }
  const reset = el("div", { class: "group-body" }, el("button", { type: "button", class: "btn", text: "Reset to the default part", onclick: () => {
    S.params = { ...DEFAULTS }; S.upload = null;
    form.replaceChildren(); readoutEls = {}; buildForm(); syncEnabled(); readouts(); schedule();
    try { localStorage.removeItem("roller.params"); } catch (e) { /* ignore */ }
  } }));
  form.append(reset);
  syncEnabled();
  readouts();
}

function syncEnabled() {
  for (const { row, f } of Object.values(rowsByKey)) {
    if (!f.on) continue;
    const on = !!f.on(S.params);
    const inp = inputs[f.k];
    if (inp) inp.disabled = !on;
    row.classList.toggle("is-off", !on);
  }
}

/* ---------- preview requests ---------- */
let timer = null;
function schedule() {
  clearTimeout(timer);
  timer = setTimeout(requestPreview, 250);
}

function busy(on) {
  S.busy += on ? 1 : -1;
  const b = S.busy > 0;
  $("busy").textContent = b ? "Updating" : "";
  $("slab-wrap").classList.toggle("busy", b);
  $("slab-wrap").setAttribute("aria-busy", String(b));
}

async function requestPreview() {
  if (document.querySelector("input.invalid")) return;
  const file = S.params.art_source === "upload" ? S.upload : null;
  if (S.params.art_source === "upload" && !file) { showEmpty("Upload a picture, or drag one onto this area. SVG, PNG or JPEG.", false); return; }
  const mine = ++S.seq;
  busy(true);
  try {
    const data = await engine.preview({ ...S.params }, file);
    if (mine !== S.seq) return;
    S.last = data;
    applyPreview();
  } catch (e) {
    if (e.name === "Superseded") return;
    showEmpty("Preview failed: " + e.message, true);
  } finally { busy(false); }
}

function showEmpty(msg, isErr) {
  const e = $("slab-empty");
  e.textContent = msg; e.hidden = false; e.classList.toggle("err", !!isErr);
}

function applyPreview() {
  const d = S.last;
  $("slab-empty").hidden = true;
  readouts();
  renderStrip();
  renderRules();
  imageCache = null;
  drawSlab();
  buildRoller();
}

/* ---------- derived strip ---------- */
function minutesText(m) {
  if (m == null) return "-";
  const h = Math.floor(m / 60);
  return h ? h + " h " + Math.round(m - h * 60) + " min" : Math.round(m) + " min";
}
function renderStrip() {
  const d = S.last.derived;
  const items = [
    ["Mass", fmt(d.grams, 0), "g"],
    ["Print time", minutesText(d.print_minutes), ""],
    ["Triangles", d.triangles_export >= 1e6 ? fmt(d.triangles_export / 1e6, 2) : fmt(d.triangles_export / 1e3, 0), d.triangles_export >= 1e6 ? "million" : "thousand"],
    ["L/D", fmt(d.LD, 2), ""],
    ["Minimum wall", fmt(d.wall_min, 2), "mm"],
    ["Fired height", d.fired ? fmt(d.fired.image_height_mm, 0) : "-", "mm"],
  ];
  const dl = $("strip");
  dl.replaceChildren();
  for (const [t, v, u] of items) {
    dl.append(el("div", {}, el("dt", { text: t }), el("dd", {}, v, u ? el("small", { text: u }) : null)));
  }
}

/* ---------- rules ---------- */
const ORDER = { BLOCK: 0, WARN: 1, INFO: 2 };
const ACT = { BLOCK: "Block", WARN: "Warn", INFO: "Info" };
function renderRules() {
  const rules = S.last.rules.slice().sort((a, b) => ORDER[a.action] - ORDER[b.action] || a.id.localeCompare(b.id));
  const ul = $("rules");
  ul.replaceChildren();
  const counts = { BLOCK: 0, WARN: 0, INFO: 0 };
  for (const r of rules) {
    counts[r.action]++;
    const vl = r.value == null ? "" : (r.limit == null ? trim(r.value) : null);
    const right = el("span", { class: "vl" });
    if (r.value != null && r.limit != null) { right.append(el("b", { text: trim(r.value) }), " vs " + trim(r.limit)); }
    else if (r.value != null) right.textContent = trim(r.value);
    ul.append(el("li", { class: "rule " + r.action.toLowerCase() },
      el("span", { class: "rid", text: r.id }),
      el("span", {}, el("span", { class: "act", text: ACT[r.action] + ". " }), el("span", { class: "msg", text: r.msg })),
      right));
  }
  if (!rules.length) ul.append(el("li", { class: "rules-empty", text: "No rules reported." }));
  $("rules-count").textContent = counts.BLOCK + " block, " + counts.WARN + " warn, " + counts.INFO + " info";
  $("toggle-rules").textContent = "Rules: " + counts.BLOCK + " block, " + counts.WARN + " warn";
  const blockers = rules.filter((r) => r.action === "BLOCK").map((r) => r.id);
  const can = S.last.can_export && blockers.length === 0;
  S.blockers = blockers;
  S.canExport = can;
  $("sec-rules").classList.toggle("has-block", blockers.length > 0);
  if (blockers.length && !S.hadBlock && MQ_NARROW.matches) setOpen("rules", true);
  S.hadBlock = blockers.length > 0;
  $("export").disabled = !can;
  exportLabel();
  const note = $("export-note");
  note.textContent = can ? "No blocking rules." : "Export is blocked by " + blockers.join(", ") + ".";
  note.classList.toggle("block", !can);
}

/* The Export button shows the blocking rule id on narrow screens, where it lives in the sticky bar. */
function exportLabel() {
  const b = $("export");
  const blocked = S.last && S.blockers && S.blockers.length > 0;
  b.classList.toggle("is-blocked", !!blocked);
  b.textContent = MQ_NARROW.matches && blocked
    ? "Blocked " + S.blockers.slice(0, 2).join(", ") + (S.blockers.length > 2 ? " +" + (S.blockers.length - 2) : "")
    : "Download STL";
}

/* ---------- narrow layout: export button placement, collapsible sections ---------- */
const sec = {
  three: { el: $("sec-3d"), btn: $("toggle-3d"), open: true },
  rules: { el: $("sec-rules"), btn: $("toggle-rules"), open: true },
};
function setOpen(name, open) {
  const s = sec[name === "3d" ? "three" : name];
  s.open = open;
  s.el.classList.toggle("is-collapsed", !open);
  s.btn.setAttribute("aria-expanded", String(open));
  if (s === sec.three) syncGL();
}
function applyMode() {
  const narrow = MQ_NARROW.matches;
  if (narrow) $("bar-export").append($("export"));
  else document.querySelector(".export").prepend($("export"));
  exportLabel();
  if (!narrow) { setOpen("3d", true); setOpen("rules", true); }
  else if (MQ_PHONE.matches) { setOpen("3d", false); setOpen("rules", !!(S.blockers && S.blockers.length)); }
  else { setOpen("3d", true); setOpen("rules", true); }
  $("view-cap").textContent = window.matchMedia("(pointer: coarse)").matches ? "Drag to orbit, pinch to zoom" : "Drag to orbit, wheel to zoom";
}
sec.three.btn.onclick = () => setOpen("3d", !sec.three.open);
sec.rules.btn.onclick = () => setOpen("rules", !sec.rules.open);

/* ---------- colours from tokens ---------- */
const probe = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
probe.canvas.width = probe.canvas.height = 1;
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function rgb(name) {
  probe.clearRect(0, 0, 1, 1);
  probe.fillStyle = "#000"; probe.fillStyle = css(name);
  probe.fillRect(0, 0, 1, 1);
  const d = probe.getImageData(0, 0, 1, 1).data;
  return [d[0], d[1], d[2]];
}

/* ---------- slab ---------- */
let imageCache = null;
function b64bytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function revolutionCanvas() {
  const key = [S.fired, S.glaze].join();
  if (imageCache && imageCache.key === key) return imageCache.canvas;
  const clay = S.last.clay, hm = S.last.heightmap, dv = S.last.derived;
  const { cols, rows } = clay;
  const K = imageCache && imageCache.K ? imageCache.K : b64bytes(clay.data_b64);
  const depth = hm.depth || S.params.depth;
  const C = dv.C;
  const px = C / cols, py = (hm.pitch_z_mm || S.params.length / rows);
  const base = rgb(S.fired ? "--clay-fired" : "--clay-base");
  const glaze = rgb("--clay-glaze");
  const l = [-0.55, -0.6, 0.58]; const ln = Math.hypot(...l); l[0] /= ln; l[1] /= ln; l[2] /= ln;
  const flat = l[2];
  const c = document.createElement("canvas");
  c.width = cols; c.height = rows;
  const ctx = c.getContext("2d");
  const img = ctx.createImageData(cols, rows);
  const o = img.data;
  const E = 1.5;
  for (let y = 0; y < rows; y++) {
    const y0 = Math.max(0, y - 1), y1 = Math.min(rows - 1, y + 1);
    for (let x = 0; x < cols; x++) {
      const xm = (x - 1 + cols) % cols, xp = (x + 1) % cols;
      const dx = ((K[y * cols + xp] - K[y * cols + xm]) / 255) * depth / (2 * px);
      const dy = ((K[y1 * cols + x] - K[y0 * cols + x]) / 255) * depth / ((y1 - y0) * py);
      const nx = dx * E, ny = dy * E, nz = 1;
      const nl = Math.hypot(nx, ny, nz);
      const shade = (nx * l[0] + ny * l[1] + nz * l[2]) / nl;
      const f = 1 + 1.7 * (shade - flat);
      const dep = K[y * cols + x] / 255;
      let k = Math.max(0.25, f) * (1 - 0.16 * dep);
      let r = base[0] * k, g = base[1] * k, b = base[2] * k;
      if (S.glaze) {
        const m = Math.pow(dep, 0.8) * 0.85;
        const gk = Math.max(0.55, f);
        r = r * (1 - m) + glaze[0] * gk * m; g = g * (1 - m) + glaze[1] * gk * m; b = b * (1 - m) + glaze[2] * gk * m;
      }
      const i = (y * cols + x) * 4;
      o[i] = r > 255 ? 255 : r; o[i + 1] = g > 255 ? 255 : g; o[i + 2] = b > 255 ? 255 : b; o[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  imageCache = { key, canvas: c, K };
  return c;
}

function drawSlab() {
  const cv = $("slab");
  const wrap = $("slab-wrap");
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const W = Math.max(10, wrap.clientWidth), H = Math.max(10, wrap.clientHeight);
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = css("--clay-ground");
  ctx.fillRect(0, 0, W, H);
  if (!S.last) return;
  const dv = S.last.derived;
  const L = S.params.length, C = dv.C;
  const shrink = S.fired && dv.fired ? 1 - dv.fired.shrink_pct / 100 : 1;
  const margin = 30, gap = 14, passes = S.passes;
  const s = Math.min((W - 24) / (C * 1.2), (H - 2 * margin - gap * (passes - 1)) / (passes * L));
  const revW = C * shrink * s, revH = L * shrink * s;
  const rev = revolutionCanvas();
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
  const seamCol = css("--color-seam"), ink = css("--color-ink-2");
  ctx.font = "500 11px " + css("--font-ui");
  const totalH = passes * revH + gap * (passes - 1);
  let y0 = Math.max(margin, (H - totalH) / 2 - 4);
  for (let p = 0; p < passes; p++) {
    const phase = (S.phases[p] / C) * revW;
    ctx.save();
    ctx.beginPath(); ctx.rect(0, y0, W, revH); ctx.clip();
    let x = -phase;
    while (x > 0) x -= revW;
    for (; x < W; x += revW) ctx.drawImage(rev, x, y0, revW + 0.5, revH);
    // seam markers
    ctx.strokeStyle = seamCol; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
    for (x = -phase; x < W; x += revW) {
      if (x < 0) continue;
      ctx.beginPath(); ctx.moveTo(Math.round(x) + 0.5, y0); ctx.lineTo(Math.round(x) + 0.5, y0 + revH); ctx.stroke();
    }
    ctx.restore();
    ctx.setLineDash([]);
    ctx.fillStyle = seamCol; ctx.textBaseline = "bottom";
    for (x = -phase; x < W; x += revW) {
      if (x < 0) continue;
      ctx.fillText("seam", x + 4, y0 - 3);
    }
    if (passes > 1) { ctx.fillStyle = css("--clay-ground"); ctx.fillRect(0, y0 + revH - 18, 52, 18); ctx.fillStyle = ink; ctx.textBaseline = "bottom"; ctx.fillText("Pass " + (p + 1), 6, y0 + revH - 3); }
    y0 += revH + gap;
  }
  // scale bar, 50 mm basis
  const bars = [10, 20, 50, 100, 200];
  let mm = bars[0];
  for (const b of bars) if (b * s <= 190) mm = b;
  const bx = 16, by = H - 12, bw = mm * s;
  ctx.strokeStyle = ink; ctx.fillStyle = ink; ctx.lineWidth = 1.5; ctx.setLineDash([]);
  ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(bx + bw, by); ctx.moveTo(bx, by - 4); ctx.lineTo(bx, by + 4); ctx.moveTo(bx + bw, by - 4); ctx.lineTo(bx + bw, by + 4); ctx.stroke();
  ctx.textBaseline = "bottom";
  ctx.fillText(mm + " mm " + (S.fired ? "fired" : "wet"), bx + bw + 8, by + 4);
  const revs = (W / (revW)).toFixed(1);
  $("slab-caption").textContent = (S.fired ? "Fired" : "Wet") + " size, " + fmt(C * shrink, 1) + " mm per revolution, " + revs + " revolutions across" + (String(S.params.art_source).startsWith("pattern:") ? ". This is a sample pattern; upload a picture to make your own." : "");
}

function setSize(fired) {
  S.fired = fired;
  $("size-wet").setAttribute("aria-pressed", String(!fired));
  $("size-fired").setAttribute("aria-pressed", String(fired));
  drawSlab();
}

/* ---------- 3D roller ---------- */
let gl = null;
/* The renderer exists only while the 3D view is on screen. On narrow screens it is created when the
 * section opens and disposed when it closes, so a phone does not hold a WebGL context it cannot see. */
function syncGL() {
  const want = !MQ_NARROW.matches || sec.three.open;
  if (want && !gl) { initGL(); if (S.last) buildRoller(); }
  else if (!want && gl) disposeGL();
}
function disposeGL() {
  const g = gl; gl = null;
  g.observer.disconnect();
  g.controls.dispose();
  if (g.mesh) { g.scene.remove(g.mesh); g.mesh.geometry.dispose(); g.mesh.material.forEach((m) => m.dispose()); }
  g.renderer.dispose();
  g.renderer.forceContextLoss();
  g.canvas.remove();
}
function initGL() {
  const canvas = el("canvas", { id: "gl", "aria-label": "3D roller, drag to orbit" });
  $("view3d").prepend(canvas);
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: !engine.lowMemory, preserveDrawingBuffer: !engine.lowMemory });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  const scene = new THREE.Scene();
  const bg = rgb("--stage-bg");
  scene.background = new THREE.Color(bg[0] / 255, bg[1] / 255, bg[2] / 255).convertSRGBToLinear();
  const cam = new THREE.PerspectiveCamera(32, 1, 1, 4000);
  cam.up.set(0, 0, 1);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x5a5048, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(-300, -260, 380); scene.add(key);
  const fill = new THREE.DirectionalLight(0xffffff, 0.7); fill.position.set(300, 200, 100); scene.add(fill);
  const controls = new OrbitControls(cam, canvas);
  controls.enableDamping = false;
  const render = () => renderer.render(scene, cam);
  controls.addEventListener("change", render);
  const resize = () => {
    const w = canvas.parentElement.clientWidth, h = canvas.parentElement.clientHeight;
    renderer.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix(); render();
  };
  const observer = new ResizeObserver(resize);
  observer.observe(canvas.parentElement);
  gl = { canvas, observer, renderer, scene, cam, controls, render, mesh: null, fitted: false };
  resize();
}

function toLinear(name) {
  const c = rgb(name);
  return new THREE.Color(c[0] / 255, c[1] / 255, c[2] / 255).convertSRGBToLinear();
}

function buildRoller() {
  if (!gl || !S.last) return;
  const hm = S.last.heightmap;
  const { cols, rows } = hm;
  const H = new Float32Array(b64bytes(hm.data_b64).buffer);
  const D = S.params.diameter, L = S.params.length;
  const Rt = D / 2, d = hm.depth;
  const pz = L / (rows - 1);
  const rb = Math.max(0, ((S.last.params && S.last.params.bore_diameter_used) || 0) / 2);
  const n = rows * cols;
  const pos = [];
  const idx = [];
  const rOuter = (i, j) => Rt - d + H[i * cols + j];
  const T = new Float32Array(cols * 2); for (let j = 0; j < cols; j++) { T[2 * j] = Math.cos((2 * Math.PI * j) / cols); T[2 * j + 1] = Math.sin((2 * Math.PI * j) / cols); }
  // outer surface
  for (let i = 0; i < rows; i++) for (let j = 0; j < cols; j++) { const r = rOuter(i, j); pos.push(r * T[2 * j], r * T[2 * j + 1], i * pz); }
  for (let i = 0; i < rows - 1; i++) for (let j = 0; j < cols; j++) {
    const a = i * cols + j, b = i * cols + ((j + 1) % cols), c = (i + 1) * cols + j, e = (i + 1) * cols + ((j + 1) % cols);
    idx.push(a, b, c, b, e, c);
  }
  const outerEnd = idx.length;
  // end caps and bore, own vertices so normals stay crisp
  let base = n;
  const ring = (iRow, zv, up) => {
    for (let j = 0; j < cols; j++) { const r = rOuter(iRow, j); pos.push(r * T[2 * j], r * T[2 * j + 1], zv); }
    for (let j = 0; j < cols; j++) pos.push(rb * T[2 * j], rb * T[2 * j + 1], zv);
    for (let j = 0; j < cols; j++) {
      const j2 = (j + 1) % cols;
      const o1 = base + j, o2 = base + j2, i1 = base + cols + j, i2 = base + cols + j2;
      if (up) idx.push(o1, o2, i1, o2, i2, i1); else idx.push(o1, i1, o2, o2, i1, i2);
    }
    base += 2 * cols;
  };
  ring(0, 0, false);
  ring(rows - 1, L, true);
  const capEnd = idx.length;
  if (rb > 0) {
    for (let j = 0; j < cols; j++) pos.push(rb * T[2 * j], rb * T[2 * j + 1], 0);
    for (let j = 0; j < cols; j++) pos.push(rb * T[2 * j], rb * T[2 * j + 1], L);
    for (let j = 0; j < cols; j++) { const j2 = (j + 1) % cols; idx.push(base + j, base + j2, base + cols + j, base + j2, base + cols + j2, base + cols + j); }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  geo.setIndex(idx);
  geo.computeVertexNormals();
  geo.addGroup(0, outerEnd, 0);
  geo.addGroup(outerEnd, capEnd - outerEnd, 0);
  geo.addGroup(capEnd, idx.length - capEnd, 1);
  const bodyMat = new THREE.MeshStandardMaterial({ color: toLinear("--stage-body"), roughness: 0.72, metalness: 0.0, side: THREE.DoubleSide });
  const boreMat = new THREE.MeshStandardMaterial({ color: toLinear("--stage-bore"), roughness: 0.9, side: THREE.DoubleSide });
  if (gl.mesh) { gl.scene.remove(gl.mesh); gl.mesh.geometry.dispose(); gl.mesh.material.forEach((m) => m.dispose()); }
  gl.mesh = new THREE.Mesh(geo, [bodyMat, boreMat]);
  gl.scene.add(gl.mesh);
  if (!gl.fitted) {
    gl.controls.target.set(0, 0, L / 2);
    gl.cam.position.set(-L * 0.66, -L * 1.5, L * (0.5 + 0.95));
    gl.controls.update();
    gl.fitted = true;
  }
  gl.render();
}

/* ---------- export ---------- */
let engine = null;
const mb = (n) => (n >= 1e6 ? fmt(n / 1e6, 1) + " MB" : Math.max(1, Math.round(n / 1e3)) + " KB");
function dlLink(href, name, text, primary) {
  return el("a", { href, download: name, target: IOS ? "_blank" : null, rel: IOS ? "noopener" : null, class: primary ? "primary" : null, text });
}
async function doExport(kind) {
  const res = $("export-result");
  res.replaceChildren(el("span", { text: "Building the STL. This takes a few seconds; the page stays usable." }));
  $("export").disabled = true; $("strip-btn").disabled = true;
  if (MQ_NARROW.matches) document.querySelector(".export").scrollIntoView({ block: "start" });
  try {
    const file = S.params.art_source === "upload" ? S.upload : null;
    const j = kind === "strip" ? await engine.testStrip({ ...S.params }) : await engine.exportZip({ ...S.params }, file);
    res.replaceChildren();
    if (j.blocked || !j.href) {
      const ids = (j.rules || []).filter((x) => x.action === "BLOCK").map((x) => x.id);
      res.append(el("span", { class: "err", text: "Not exported. Blocked by " + (ids.join(", ") || "a rule") + "." }));
    } else {
      const stls = j.stls || [];
      const halves = stls.length > 1;
      for (const f of stls) {
        const part = halves ? (/_a\.stl$/i.test(f.filename) ? " (bottom half)" : " (top half)") : "";
        res.append(dlLink(f.href, f.filename, "Save STL" + part + ", " + mb(f.bytes), true));
      }
      /* Start the first STL download right away; the links stay for a second try. */
      if (stls.length) res.querySelector("a.primary").click();
      const other = el("p", { class: "export-other", text: "Other files:" });
      if (j.href3mf) other.append(" ", dlLink(j.href3mf, j.filename3mf, "3MF (" + mb(j.bytes3mf) + ")", false));
      other.append(" ", dlLink(j.href, j.filename, "everything as a zip (" + (j.files || []).length + " files, " + mb(j.zipBytes || 0) + ")", false));
      if (!stls.length) other.firstChild.textContent = "Files:";
      res.append(other);
      res.append(el("p", { class: "caption", text: "The zip adds the heightmap for CNC, a slab picture and a print sheet with settings and how to use the roller." }));
    }
  } catch (e) {
    res.replaceChildren(el("span", { class: "err", text: "Export failed: " + e.message }));
  } finally {
    $("strip-btn").disabled = false;
    if (S.last) renderRules();
  }
}

/* ---------- boot: load the engine with a visible progress line ---------- */
function bootProgress(p) {
  $("boot-text").textContent = p.text;
  const bar = $("boot-bar");
  if (p.total) { bar.hidden = false; bar.max = p.total; bar.value = p.done || 0; } else { bar.hidden = true; }
}
async function boot() {
  try {
    engine = await createEngine(bootProgress);
  } catch (e) {
    $("boot-text").textContent = "Could not start the engine: " + e.message;
    $("boot-bar").hidden = true;
    $("boot-retry").hidden = false;
    return false;
  }
  $("boot").hidden = true;
  return true;
}
$("boot-retry").onclick = () => location.reload();

/* ---------- wire up ---------- */
if (!(await boot())) throw new Error("engine did not start");
if (engine.note) { const n = $("engine-note"); n.hidden = false; n.textContent = engine.note; }
buildForm();
buildLive();
readouts();
$("phone-note").classList.toggle("on", !!engine.lowMemory);
applyMode();
MQ_NARROW.addEventListener("change", applyMode);
MQ_PHONE.addEventListener("change", applyMode);
$("size-wet").onclick = () => setSize(false);
$("size-fired").onclick = () => setSize(true);
$("glaze-pool").onchange = (e) => { S.glaze = e.target.checked; imageCache = null; if (S.last) drawSlab(); };
/* Upload picture: switch the Art source to upload and open the file picker in one tap. */
const uploadBtn = $("upload-art");
const syncUploadBtn = () => {
  const f = S.params.art_source === "upload" && S.upload;
  uploadBtn.textContent = f ? "Change picture" : "Upload a picture";
  uploadBtn.title = f ? S.upload.name : "SVG, PNG or JPEG. PNG and JPEG are traced to black and white.";
};
/* The label opens its own always-rendered input (#upload-file): phones refuse to open a
   picker for an input inside a collapsed section, so the Art panel's input is not used here. */
function useUpload(f) {
  if (!f) return;
  S.upload = f;
  const sel = $("f-art");
  sel.value = "upload";
  sel.dispatchEvent(new Event("change"));
  syncUploadBtn();
  schedule();
}
$("upload-file").addEventListener("change", (e) => { useUpload(e.target.files[0]); e.target.value = ""; });
$("f-file").addEventListener("change", syncUploadBtn);
/* Drag a picture onto the slab to use it. */
const slabWrap = $("slab-wrap");
const ARTISH = /\.(png|jpe?g|svg)$/i;
slabWrap.addEventListener("dragover", (e) => { e.preventDefault(); slabWrap.classList.add("drop"); });
slabWrap.addEventListener("dragleave", () => slabWrap.classList.remove("drop"));
slabWrap.addEventListener("drop", (e) => {
  e.preventDefault(); slabWrap.classList.remove("drop");
  const f = [...(e.dataTransfer?.files || [])].find((x) => ARTISH.test(x.name) || /^image\//.test(x.type));
  if (!f) return;
  useUpload(f);
});
$("f-art").addEventListener("change", syncUploadBtn);
$("random-start").onclick = () => {
  if (!S.last) return;
  const C = S.last.derived.C;
  S.passes = 3; S.phases = [0, 1, 2].map(() => Math.random() * C);
  $("one-pass").hidden = false; $("slab-wrap").classList.add("multi"); drawSlab();
};
$("one-pass").onclick = () => { S.passes = 1; S.phases = [0, 0, 0]; $("one-pass").hidden = true; $("slab-wrap").classList.remove("multi"); drawSlab(); };
$("export").onclick = () => doExport("full");
$("strip-btn").onclick = () => doExport("strip");
new ResizeObserver(() => drawSlab()).observe($("slab-wrap"));

showEmpty("Waiting for the first preview.", false);
schedule();
