import * as THREE from "./vendor/three.module.js";
import { OrbitControls } from "./vendor/OrbitControls.js";
import { createEngine } from "./engine-client.js";

/* ---------- parameters ---------- */
const DEFAULTS = {
  diameter: 45.0, length: 250.0,
  art_source: "pattern:waves",
  art_style: "trace", sketch_detail: 0.5, sketch_shading: true,
  art_scale: 100, art_shift_x: 0, art_shift_y: 0, art_fit: false,
  tile_width_mm: null, n_around: 3, n_along: null,
  offset: "none", offset_fraction: 0.5, rotation: 0, mirror: true, invert: false, spacing: 0.0,
  depth: 1.5, draft_deg: 15.0, edge_round: 0.4,
  seam_method: "auto", seam_blend_pct: 5.0, seam_theta_deg: null,
  band: 3.0, bands_on: true, end_chamfer: 1.0, alignment_ticks: false,
  bore_preset: "dowel_half", bore_diameter: null, bore_clearance: 0.3,
  split: false, clay_body: "stoneware", clay_state: "firm",
  glaze_flag: false, nozzle: 0.4, pitch_preview: 0.5, pitch_export: 0.2,
  cnc_rotary_max_length: 0,
  text: "", text_font: "pacifico", text_size: 12.0, text_layout: "single", text_count: 1,
  text_x: 50.0, text_y: 85.0, text_angle: 0.0, text_arch: 0.0, text_wave: 0.0, text_track: 8.0,
  text_relief: "pressed", text_frame: "halo", text_halo: 1.5, text_style: "solid",
  text_sep: "dot", text_gap: 5.0, text_row_gap: 6.0,
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
  shown: 0,
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
  text_font: [],
  text_layout: [["single", "In place"], ["band", "Band around"], ["allover", "All over"]],
  text_relief: [["pressed", "Pressed in"], ["raised", "Stands up"]],
  text_frame: [["halo", "Clear margin"], ["pill", "Pill"], ["ring", "Pill with border"], ["none", "None"]],
  text_style: [["solid", "Solid"], ["outline", "Outline"]],
  text_sep: [["dot", "Dot"], ["star", "Star"], ["heart", "Heart"], ["diamond", "Diamond"], ["flower", "Flower"], ["wave", "Wave"], ["none", "None"]],
};

/* Open source fonts (SIL OFL) bundled in engine/data/fonts. min_mm matches engine/text.py FONTS:
 * the smallest letter height that keeps 1 mm clay gaps at 1.5 mm depth. */
const FONTS = [
  ["pacifico", "Pacifico", "retro script", 12], ["shrikhand", "Shrikhand", "groovy 70s", 16],
  ["cherrybomb", "Cherry Bomb One", "bubble", 12], ["fraunces", "Fraunces", "soft serif", 12],
  ["bebas", "Bebas Neue", "tall caps", 11], ["nunito", "Nunito Black", "rounded", 11],
  ["caveat", "Caveat Bold", "handwritten", 11], ["dancing", "Dancing Script", "wedding script", 28],
  ["lilita", "Lilita One", "chunky", 9],
];
OPTS.text_font = FONTS.map(([id, n, v, m]) => [id, n + ", " + v + " (" + m + " mm and up)"]);

const hasText = (p) => !!(p.text && p.text.trim());
const isSingle = (p) => hasText(p) && p.text_layout === "single";
// the idea samples; picking another idea swaps a sample for the new one, typed words are kept
const isRepeat = (p) => hasText(p) && p.text_layout !== "single";

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
  { name: "Text", open: true, fields: [
    { special: "text-ideas" },
    { special: "text-input" },
    { k: "text_font", label: "Font", t: "sel", on: hasText },
    { k: "text_size", label: "Letter height", unit: "mm", t: "num", step: 0.5, min: 3, max: 120, on: hasText, rule: "R74" },
    { special: "text-size-note" },
    { k: "text_layout", label: "Layout", t: "sel", on: hasText },
    { k: "text_count", label: "Copies around", t: "int", min: 1, max: 24, on: isSingle, rule: "R76" },
    { k: "text_y", label: "Height on the slab", unit: "% from bottom", t: "num", step: 1, min: 0, max: 100, on: (p) => hasText(p) && p.text_layout !== "allover", rule: "R75" },
    { k: "text_x", label: "Place around", unit: "% of each share", t: "num", step: 1, min: 0, max: 100, on: hasText },
    { k: "text_arch", label: "Arch", unit: "deg", t: "num", step: 5, min: -300, max: 300, on: isSingle },
    { k: "text_wave", label: "Wave", unit: "% of height", t: "num", step: 1, min: 0, max: 60, on: hasText },
    { k: "text_angle", label: "Turn", unit: "deg", t: "num", step: 5, min: -180, max: 180, on: isSingle },
    { k: "text_track", label: "Letter spacing", unit: "%", t: "num", step: 1, min: -20, max: 80, on: hasText, rule: "R21" },
    { k: "text_relief", label: "Letters in the clay", t: "sel", on: hasText, rule: "R77" },
    { k: "text_frame", label: "Frame", t: "sel", on: hasText },
    { k: "text_halo", label: "Margin", unit: "mm", t: "num", step: 0.5, min: 0, max: 10, on: (p) => hasText(p) && p.text_frame !== "none" },
    { k: "text_style", label: "Letter style", t: "sel", on: hasText },
    { k: "text_sep", label: "Between words", t: "sel", on: isRepeat },
    { k: "text_gap", label: "Space between words", unit: "mm", t: "num", step: 0.5, min: 0, max: 100, on: isRepeat },
    { k: "text_row_gap", label: "Space between rows", unit: "mm", t: "num", step: 0.5, min: 0, max: 100, on: (p) => hasText(p) && p.text_layout === "allover" },
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
  if (k === "text_size" || k === "text_font") syncTextNote();
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
  sel.append(el("option", { value: "upload", text: "Upload SVG, PNG, JPEG or WEBP" }));
  inputs.art_source = sel;
  const file = el("input", { type: "file", id: "f-file", accept: "image/png,image/jpeg,image/webp,image/svg+xml,.svg,.webp", hidden: true });
  const name = el("p", { class: "upload-name" });
  const sync = () => {
    const up = sel.value === "upload";
    file.hidden = !up;
    name.textContent = up ? (S.upload ? S.upload.name : "No file chosen. SVG is clean-up only, drawings are traced, photos of people become a pen sketch.") : "";
  };
  sel.addEventListener("change", () => {
    if (sel.value === "upload") setParam("art_source", "upload");
    else setParam("art_source", "pattern:" + sel.value);
    sync();
  });
  file.addEventListener("change", () => { useUpload(file.files[0] || null).then(sync); });
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

/* ---------- text ---------- */
/* Each idea is a starting layout a potter would reach for. The drawing shows where the words go
 * on one revolution of the slab (black bars = words, grey = the picture). */
const TEXT_IDEAS = [
  { id: "name", label: "Name over the picture", sample: "Grandma Rose",
    set: () => ({ text_layout: "single", text_count: 1, text_y: 88, text_x: 50, text_arch: 0, text_wave: 0, text_angle: 0, text_font: "pacifico", text_size: 14, text_frame: "halo", text_relief: "pressed", text_style: "solid" }),
    svg: '<rect x="4" y="16" width="16" height="16" rx="3" class="pic"/><rect x="24" y="16" width="16" height="16" rx="3" class="pic"/><rect x="5" y="7" width="14" height="4" rx="2"/><rect x="25" y="7" width="14" height="4" rx="2"/>' },
  { id: "arch", label: "Rainbow arch", sample: "Sunny Days",
    set: () => ({ text_layout: "single", text_count: 1, text_y: 84, text_x: 50, text_arch: 70, text_wave: 0, text_angle: 0, text_font: "shrikhand", text_size: 14, text_frame: "halo", text_relief: "pressed", text_style: "solid" }),
    svg: '<rect x="8" y="20" width="12" height="12" rx="3" class="pic"/><rect x="26" y="20" width="12" height="12" rx="3" class="pic"/><path d="M5 16 Q14 4 23 16" class="ln"/><path d="M23 16 Q32 4 41 16" class="ln"/>' },
  { id: "band", label: "Word band", sample: "HOPE",
    set: () => ({ text_layout: "band", text_y: 50, text_x: 50, text_wave: 0, text_font: "bebas", text_size: 12, text_sep: "star", text_gap: 5, text_frame: "halo", text_relief: "pressed", text_style: "solid" }),
    svg: '<rect x="2" y="4" width="40" height="9" rx="2" class="pic"/><rect x="2" y="27" width="40" height="9" rx="2" class="pic"/><rect x="3" y="18" width="9" height="4" rx="1"/><circle cx="16" cy="20" r="1.6"/><rect x="20" y="18" width="9" height="4" rx="1"/><circle cx="33" cy="20" r="1.6"/><rect x="37" y="18" width="5" height="4" rx="1"/>' },
  { id: "wavy", label: "Wavy saying", sample: "be still",
    set: () => ({ text_layout: "band", text_y: 50, text_x: 0, text_wave: 25, text_font: "caveat", text_size: 12, text_sep: "none", text_gap: 14, text_frame: "halo", text_relief: "pressed", text_style: "solid" }),
    svg: '<path d="M2 20 Q8 12 14 20 T26 20 T38 20 T44 20" class="ln"/>' },
  { id: "allover", label: "Words all over", sample: "JOY",
    set: () => ({ text_layout: "allover", text_x: 50, text_wave: 0, text_font: "lilita", text_size: 14, text_sep: "heart", text_gap: 4, text_row_gap: 6, text_frame: "halo", text_relief: "pressed", text_style: "solid" }),
    svg: '<rect x="2" y="5" width="10" height="4" rx="2"/><rect x="17" y="5" width="10" height="4" rx="2"/><rect x="32" y="5" width="10" height="4" rx="2"/><rect x="9" y="18" width="10" height="4" rx="2"/><rect x="24" y="18" width="10" height="4" rx="2"/><rect x="2" y="31" width="10" height="4" rx="2"/><rect x="17" y="31" width="10" height="4" rx="2"/><rect x="32" y="31" width="10" height="4" rx="2"/>' },
  { id: "stamp", label: "Maker's stamp", sample: "HANDMADE",
    set: () => ({ text_layout: "single", text_count: 1, text_y: 8, text_x: 50, text_arch: 0, text_wave: 0, text_angle: 0, text_font: "nunito", text_size: 12, text_frame: "ring", text_relief: "pressed", text_style: "solid" }),
    svg: '<rect x="4" y="6" width="36" height="20" rx="3" class="pic"/><rect x="13" y="29" width="18" height="8" rx="4" class="ln"/><rect x="17" y="32" width="10" height="2" rx="1"/>' },
  { id: "side", label: "Up the side", sample: "made with love",
    set: () => ({ text_layout: "single", text_count: 1, text_y: 50, text_x: 0, text_arch: 0, text_wave: 0, text_angle: 90, text_font: "lilita", text_size: 10, text_frame: "halo", text_relief: "pressed", text_style: "solid" }),
    svg: '<rect x="10" y="4" width="30" height="32" rx="3" class="pic"/><rect x="3" y="8" width="4" height="24" rx="2"/>' },
];

function setMany(vals) {
  Object.assign(S.params, vals);
  for (const [k, v] of Object.entries(vals)) {
    const inp = inputs[k];
    if (!inp) continue;
    if (inp.type === "checkbox") inp.checked = !!v; else inp.value = v == null ? "" : String(v);
    inp.classList.remove("invalid");
  }
  const k0 = Object.keys(vals)[0];
  setParam(k0, vals[k0]);
  syncTextNote();
}

function textIdeas() {
  const wrap = el("div", { class: "row wide" });
  const grid = el("div", { class: "ideas", role: "group", "aria-label": "Text ideas" });
  for (const idea of TEXT_IDEAS) {
    const b = el("button", { type: "button", class: "idea" });
    b.innerHTML = '<svg viewBox="0 0 44 40" aria-hidden="true">' + idea.svg + "</svg>";
    b.append(el("span", { text: idea.label }));
    b.onclick = () => {
      const v = idea.set(S.params);
      if (!hasText(S.params) || TEXT_IDEAS.some((x) => x.sample === S.params.text)) v.text = idea.sample;
      setMany(v);
    };
    grid.append(b);
  }
  wrap.append(el("span", { class: "lbl", text: "Start from an idea" }), grid);
  return wrap;
}

function textInput() {
  const wrap = el("div", { class: "row wide" });
  const ta = el("textarea", { id: "f-text", rows: 2, maxlength: 60, placeholder: "A name, a date or a saying. Enter starts a new line (3 lines at most)." });
  ta.value = S.params.text || "";
  ta.addEventListener("input", () => { setParam("text", ta.value); syncTextNote(); });
  inputs.text = ta;
  wrap.append(el("label", { for: "f-text", class: "lbl" }, "Words"), ta);
  return wrap;
}

let textNoteEl = null;
function textSizeNote() {
  textNoteEl = el("p", { class: "note text-note", role: "status" });
  syncTextNote();
  return textNoteEl;
}
function syncTextNote() {
  if (!textNoteEl) return;
  const p = S.params;
  const f = FONTS.find((x) => x[0] === p.text_font);
  if (!hasText(p) || !f) { textNoteEl.textContent = ""; textNoteEl.hidden = true; return; }
  textNoteEl.hidden = false;
  const small = p.text_size < f[3];
  textNoteEl.textContent = small
    ? f[1] + " needs " + f[3] + " mm or more to keep 1 mm gaps in clay. Make it taller or pick a bolder font."
    : "Letter height is the height of a capital H.";
  textNoteEl.classList.toggle("warn", small);
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
      if (f.special === "text-ideas") { body.append(textIdeas()); continue; }
      if (f.special === "text-input") { body.append(textInput()); continue; }
      if (f.special === "text-size-note") { body.append(textSizeNote()); continue; }
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
    form.replaceChildren(); readoutEls = {}; buildForm(); syncEnabled(); readouts(); schedule(); syncStyleUI();
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
  if (S.params.art_source === "upload" && !file) { showEmpty("Upload a picture, or drag one onto this area. SVG, PNG, JPEG or WEBP.", false); return; }
  const mine = ++S.seq;
  busy(true);
  try {
    const data = await engine.preview({ ...S.params }, file);
    // Show any result newer than the one on screen, so a drag shows each finished step.
    if (mine <= S.shown) return;
    S.shown = mine;
    S.last = data;
    applyPreview();
  } catch (e) {
    if (e.name === "Superseded") return;
    showEmpty("Preview failed: " + e.message, true);
  } finally { busy(false); }
}

function showEmpty(msg, isErr) {
  const e = $("slab-empty");
  S.pend = null;
  e.textContent = msg; e.hidden = false; e.classList.toggle("err", !!isErr);
}

function applyPreview() {
  const d = S.last;
  S.pend = null;
  $("slab-empty").hidden = true;
  readouts();
  renderStrip();
  renderRules();
  imageCache = null;
  drawSlab();
  buildRoller();
  syncStyleUI();
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
let slabG = null;   // last slab geometry in CSS px: revolution size and mm sizes
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
  slabG = { revW, revH, C, L };
  const dg = S.drag || S.pend, ddx = dg ? dg.dx : 0, ddy = dg ? dg.dy : 0;
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
    let x = -phase + ddx;
    while (x > 0) x -= revW;
    for (; x < W; x += revW) ctx.drawImage(rev, x, y0 + ddy, revW + 0.5, revH);
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
  uploadBtn.title = f ? S.upload.name : "SVG, PNG, JPEG or WEBP. Drawings are traced to black and white; a photo of a person becomes a pen sketch.";
};
/* The label opens its own always-rendered input (#upload-file): phones refuse to open a
   picker for an input inside a collapsed section, so the Art panel's input is not used here. */
/* WEBP goes through the browser's own decoder and reaches the engine as PNG, so it does not
   depend on the Python build having a WEBP codec. */
async function toEngineFile(f) {
  if (!(/\.webp$/i.test(f.name) || f.type === "image/webp")) return f;
  try {
    const bmp = await createImageBitmap(f);
    const c = document.createElement("canvas");
    c.width = bmp.width; c.height = bmp.height;
    c.getContext("2d").drawImage(bmp, 0, 0);
    const blob = await new Promise((res) => c.toBlob(res, "image/png"));
    if (!blob) return f;
    return new File([blob], f.name.replace(/\.webp$/i, "") + ".png", { type: "image/png" });
  } catch (e) { return f; }
}
/* More than 64 distinct grey levels in a 256 px thumbnail means a photograph, not a drawing. */
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
    for (let i = 0; i < d.length; i += 4) seen.add(Math.round(0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]));
    return seen.size > 64;
  } catch (e) { return false; }
}
function syncStyleUI() {
  const up = S.params.art_source === "upload" && !!S.upload;
  const portrait = up && S.params.art_style === "portrait";
  const group = up && S.params.art_style === "group";
  $("art-style").hidden = !up;
  syncArtUI();
  $("style-trace").setAttribute("aria-pressed", String(!portrait && !group));
  $("style-portrait").setAttribute("aria-pressed", String(portrait));
  $("style-group").setAttribute("aria-pressed", String(group));
  for (const id of ["pt-detail-wrap", "pt-shading-wrap"]) $(id).hidden = !portrait;
  $("pt-fit").hidden = !(portrait || group);
  $("pt-fit").textContent = group ? "Fit roller to this group" : "Fit roller to this face";
  $("pt-detail").value = S.params.sketch_detail;
  $("pt-detail-out").textContent = Number(S.params.sketch_detail).toFixed(2);
  $("pt-shading").checked = !!S.params.sketch_shading;
  const rep = S.last && S.last.art_report && S.last.art_report.sketch;
  const note = $("pt-note");
  if (group) {
    note.hidden = !(rep && rep.mode === "group");
    note.textContent = note.hidden ? "" : (rep.faces === 1 ? "Found 1 face." : "Found " + rep.faces + " faces.") + " Faces turned away may be missed.";
  } else {
    note.hidden = !(portrait && rep && rep.face_found === false);
    note.textContent = note.hidden ? "" : "No face found; using the centre of the photo.";
  }
}
async function useUpload(f) {
  if (!f) return;
  const photo = await looksLikePhoto(f);
  S.upload = await toEngineFile(f);
  S.params.art_scale = 100; S.params.art_shift_x = 0; S.params.art_shift_y = 0;
  S.params.art_style = photo ? "portrait" : "trace";
  S.fitTouched = false;
  S.params.art_fit = photo;
  S.last = null;
  const sel = $("f-art");
  sel.value = "upload";
  sel.dispatchEvent(new Event("change"));
  setParam("art_style", S.params.art_style);
  syncUploadBtn();
  syncStyleUI();
}
$("upload-file").addEventListener("change", (e) => { useUpload(e.target.files[0]); e.target.value = ""; });
// Fit-to-roller follows the style (on for photos and groups) until the user touches the checkbox for this picture.
const autoFit = (style) => { if (!S.fitTouched) S.params.art_fit = style !== "trace"; };
$("art-fit").addEventListener("change", (e) => { S.fitTouched = true; setParam("art_fit", e.target.checked); });
$("style-trace").onclick = () => { autoFit("trace"); setParam("art_style", "trace"); syncStyleUI(); };
$("style-portrait").onclick = () => { autoFit("portrait"); setParam("art_style", "portrait"); syncStyleUI(); };
// Group photo: the whole group goes once round the roller at full length, so fit it straight away
$("style-group").onclick = () => {
  S.params.art_style = "group";
  autoFit("group");
  setParam("art_fit", S.params.art_fit);
  syncStyleUI();
  $("pt-note").hidden = false;
  $("pt-note").textContent = "Finding faces. The first group photo loads the face finder (11 MB).";
  $("pt-fit").click();
};
// Redraw while dragging: send a request at most every 120 ms. The engine runs one at a time and
// keeps only the newest waiting request, so the drawing follows the thumb without piling up.
let detailTick = null;
function sendDetail(v) {
  S.params.sketch_detail = v;
  readouts();
  try { localStorage.setItem("roller.params", JSON.stringify(S.params)); } catch (e) { /* ignore */ }
  clearTimeout(timer);
  requestPreview();
}
$("pt-detail").addEventListener("input", (e) => {
  $("pt-detail-out").textContent = Number(e.target.value).toFixed(2);
  if (detailTick) return;
  detailTick = setTimeout(() => { detailTick = null; sendDetail(Number($("pt-detail").value)); }, 120);
});
$("pt-detail").addEventListener("change", (e) => {
  clearTimeout(detailTick); detailTick = null;
  if (Number(e.target.value) !== S.params.sketch_detail) sendDetail(Number(e.target.value));
});
$("pt-shading").addEventListener("change", (e) => setParam("sketch_shading", e.target.checked));
$("pt-fit").onclick = async () => {
  if (!S.upload) return;
  const b = $("pt-fit");
  b.disabled = true;
  try {
    const r = await engine.fitPortrait({ ...S.params }, S.upload);
    for (const k of ["diameter", "n_around", "n_along", "depth", "draft_deg"]) {
      if (r[k] === undefined) continue;
      S.params[k] = r[k];
      if (inputs[k]) inputs[k].value = r[k];
    }
    S.params.tile_width_mm = null;
    if (inputs.tile_width_mm) inputs.tile_width_mm.value = "";
    setParam("n_along", r.n_along);
  } catch (e) {
    $("pt-note").hidden = false; $("pt-note").textContent = "Could not fit the roller: " + e.message;
  } finally { b.disabled = false; }
};
$("f-file").addEventListener("change", syncUploadBtn);

/* ---------- move and size the uploaded picture ---------- */
const ART_MIN = 25, ART_MAX = 300;
const artActive = () => S.params.art_source === "upload" && !!S.upload;
const clampN = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
function syncArtUI() {
  const up = artActive();
  for (const id of ["art-size-wrap", "art-reset", "art-fit-wrap"]) $(id).hidden = !up;
  const sc = clampN(Math.round(Number(S.params.art_scale) || 100), ART_MIN, ART_MAX);
  $("art-fit").checked = !!S.params.art_fit;
  $("art-size").value = sc;
  $("art-size-out").textContent = sc + "%";
  $("slab-wrap").classList.toggle("movable", up);
  $("slab").tabIndex = up ? 0 : -1;
}
let artTick = null;
function sendArt() {
  try { localStorage.setItem("roller.params", JSON.stringify(S.params)); } catch (e) { /* ignore */ }
  clearTimeout(timer);
  requestPreview();
}
/* Change size and/or shift. Sends a preview at most every 120 ms while it keeps changing. */
function setArt(p, now) {
  if (p.scale != null) S.params.art_scale = clampN(Math.round(p.scale), ART_MIN, ART_MAX);
  if (p.x != null) S.params.art_shift_x = clampN(+p.x.toFixed(4), -1, 1);
  if (p.y != null) S.params.art_shift_y = clampN(+p.y.toFixed(4), -1, 1);
  syncArtUI();
  if (now) { clearTimeout(artTick); artTick = null; sendArt(); return; }
  if (artTick) return;
  artTick = setTimeout(() => { artTick = null; sendArt(); }, 120);
}
$("art-size").addEventListener("input", (e) => {
  $("art-size-out").textContent = e.target.value + "%";
  setArt({ scale: Number(e.target.value) });
});
$("art-size").addEventListener("change", (e) => setArt({ scale: Number(e.target.value) }, true));
$("art-reset").onclick = () => setArt({ scale: 100, x: 0, y: 0 }, true);
// Screen direction to shift direction: with Mirror off the clay shows the art flipped, so left-right reverses.
const artSignX = () => (S.params.mirror ? 1 : -1);
function dragToShift(dx, dy) {
  if (!slabG || !S.last) return { x: S.params.art_shift_x, y: S.params.art_shift_y };
  const n = Math.max(1, Math.round(S.params.n_around));
  const th = (S.last.derived && S.last.derived.tile_height) || S.params.length;
  const cellPx = slabG.revW / n;
  const tilePx = th * slabG.revH / slabG.L;
  return { x: S.params.art_shift_x + artSignX() * dx / cellPx, y: S.params.art_shift_y + dy / tilePx };
}
const slabCv = $("slab");
let dragRaf = 0;
slabCv.addEventListener("pointerdown", (e) => {
  if (!artActive() || !S.last || (e.pointerType === "mouse" && e.button !== 0)) return;
  S.drag = { id: e.pointerId, x0: e.clientX, y0: e.clientY, dx: 0, dy: 0 };
  try { slabCv.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
  $("slab-wrap").classList.add("grabbing");
  slabCv.focus({ preventScroll: true });
  e.preventDefault();
});
slabCv.addEventListener("pointermove", (e) => {
  if (!S.drag || e.pointerId !== S.drag.id) return;
  S.drag.dx = e.clientX - S.drag.x0; S.drag.dy = e.clientY - S.drag.y0;
  if (!dragRaf) dragRaf = requestAnimationFrame(() => { dragRaf = 0; drawSlab(); });
});
function endDrag(e, commit) {
  if (!S.drag || e.pointerId !== S.drag.id) return;
  const d = S.drag; S.drag = null;
  $("slab-wrap").classList.remove("grabbing");
  if (commit && (d.dx || d.dy)) { const r = dragToShift(d.dx, d.dy); S.pend = d; setArt({ x: r.x, y: r.y }, true); }
  else drawSlab();
}
slabCv.addEventListener("pointerup", (e) => endDrag(e, true));
slabCv.addEventListener("pointercancel", (e) => endDrag(e, false));
slabWrapEl().addEventListener("wheel", (e) => {
  if (!artActive() || !S.last) return;
  e.preventDefault();
  if (!e.deltaY) return;
  setArt({ scale: S.params.art_scale + (e.deltaY < 0 ? 5 : -5) });
}, { passive: false });
slabCv.addEventListener("keydown", (e) => {
  if (!artActive() || !S.last || e.ctrlKey || e.metaKey || e.altKey) return;
  const st = e.shiftKey ? 0.1 : 0.02, sx = artSignX();
  const p = S.params;
  switch (e.key) {
    case "ArrowLeft": setArt({ x: p.art_shift_x - sx * st }); break;
    case "ArrowRight": setArt({ x: p.art_shift_x + sx * st }); break;
    case "ArrowUp": setArt({ y: p.art_shift_y - st }); break;
    case "ArrowDown": setArt({ y: p.art_shift_y + st }); break;
    case "+": case "=": setArt({ scale: p.art_scale + 5 }); break;
    case "-": case "_": setArt({ scale: p.art_scale - 5 }); break;
    default: return;
  }
  e.preventDefault();
});
function slabWrapEl() { return $("slab-wrap"); }
/* Drag a picture onto the slab to use it. */
const slabWrap = $("slab-wrap");
const ARTISH = /\.(png|jpe?g|webp|svg)$/i;
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
