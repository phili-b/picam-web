// Picam-web - web UI. Plain JavaScript, talks to the HTTP API (/docs).
"use strict";

const $ = (id) => document.getElementById(id);
// FastAPI errors: {"detail": "text"} or, for invalid parameters, {"detail": [{"loc": [...], "msg": ...}]}
const errorText = (data, fallback) => {
  const d = data && data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => `${(x.loc || []).slice(1).join(".") || "value"}: ${x.msg}`).join("; ");
  return typeof data === "string" && data ? data : fallback;
};
const api = async (path, options = {}) => {
  const opts = { ...options };
  if (opts.json !== undefined) {
    opts.body = JSON.stringify(opts.json);
    opts.headers = { "Content-Type": "application/json" };
    delete opts.json;
  }
  const r = await fetch(path, opts);
  const data = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(errorText(data, r.statusText));
  return data;
};
const hex = (v, bytes = 1) => "0x" + Number(v).toString(16).padStart(2 * bytes, "0");
const num = (t) => {
  const s = String(t).trim().toLowerCase();
  const v = s.startsWith("0x") ? parseInt(s, 16) : Number(s);
  if (s === "" || Number.isNaN(v)) throw new Error(`'${t}' is not a number`);
  return v;
};
const fmt = (v, d = 2) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "-" : Number(v).toFixed(d));
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const say = (id, text, error = false) => { const e = $(id); e.textContent = text; e.className = "msg" + (error ? " error" : ""); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const COLOURS = { R: "#ff5a5a", G: "#9acd56", B: "#50a0ff", Y: "#dcdeda" };

let info = null, controls = null, rois = [], activeTab = "controls";

// Tabs ----------------------------------------------------------------------------------------
document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("#tabs button, .tab").forEach((e) => e.classList.remove("active"));
  b.classList.add("active");
  $("tab-" + b.dataset.tab).classList.add("active");
  activeTab = b.dataset.tab;
  refresh();
}));

// Waiting for a restarted service -------------------------------------------------------------
// The service answers with a new "instance" after a restart (tuning file, camera reset).
async function waitForRestart(oldInstance, msgId, timeout = 60000) {
  const t0 = Date.now();
  await sleep(1500);
  while (Date.now() - t0 < timeout) {
    try {
      const h = await api("/api/health");
      if (h.instance !== oldInstance) { location.reload(); return; }
    } catch { /* not answering yet */ }
    await sleep(1000);
  }
  if (msgId) say(msgId, "The service did not come back within a minute. Check `journalctl -u picam-web`.", true);
}

// Canvas helpers ------------------------------------------------------------------------------
function drawHistogram(canvas, channels, log) {
  canvas.width = canvas.clientWidth || 400;
  const ctx = canvas.getContext("2d"), w = canvas.width, h = canvas.height;
  ctx.fillStyle = "#141614"; ctx.fillRect(0, 0, w, h);
  const scaled = Object.fromEntries(Object.entries(channels).map(([k, v]) => [k, v.map((c) => (log ? Math.log1p(c) : c))]));
  const top = Math.max(...Object.values(scaled).map((v) => Math.max(...v)), 1e-9);
  for (const [name, v] of Object.entries(scaled)) {
    ctx.strokeStyle = COLOURS[name] || "#dcdeda"; ctx.beginPath();
    v.forEach((c, i) => { const x = (i * (w - 1)) / Math.max(1, v.length - 1), y = h - 1 - (c / top) * (h - 4); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke();
  }
}

function drawMap(canvas, rows) {
  const hgt = rows.length, wid = rows[0].length, ctx = canvas.getContext("2d");
  canvas.width = wid; canvas.height = hgt;
  const top = Math.max(...rows.flat(), 1e-9), img = ctx.createImageData(wid, hgt);
  rows.flat().forEach((v, i) => { const g = Math.round((v / top) * 255); img.data.set([g, g, g, 255], i * 4); });
  ctx.putImageData(img, 0, 0);
}

function drawOverlay() {
  const c = $("overlay"), img = $("stream");
  c.width = img.clientWidth; c.height = img.clientHeight;
  const ctx = c.getContext("2d");
  ctx.clearRect(0, 0, c.width, c.height);
  ctx.font = "13px sans-serif"; ctx.lineWidth = 2;
  const colours = ["#9acd56", "#00adfd", "#ffaa00", "#e254ff", "#ff5a5a", "#ffffff"];
  rois.forEach((r, i) => {
    if (!r.view) return;
    const [u0, v0, u1, v1] = r.view, col = colours[i % colours.length];
    ctx.strokeStyle = col; ctx.fillStyle = col;
    ctx.strokeRect(u0 * c.width, v0 * c.height, (u1 - u0) * c.width, (v1 - v0) * c.height);
    ctx.fillText(`${r.name}: ${fmt(r.mean, 1)}`, u0 * c.width + 4, v0 * c.height + 14);
  });
}

// Controls ------------------------------------------------------------------------------------
const BASIC = new Set(["AeEnable", "ExposureTime", "AnalogueGain"]);
const SKIP = new Set(["ScalerCrops", "AfWindows"]);

function controlInput(name, c) {
  const v = c.value ?? c.default;
  if (typeof c.min === "boolean" || typeof c.default === "boolean") return `<input type="checkbox" data-ctrl="${name}" ${v ? "checked" : ""}>`;
  if (Array.isArray(c.default) || Array.isArray(v) || Array.isArray(c.min)) {
    return `<input data-ctrl="${name}" data-array="1" value="${esc((v || []).join(", "))}" placeholder="a, b, ...">`;
  }
  const step = Number.isInteger(c.min) && Number.isInteger(c.max) ? 1 : "any";
  return `<input type="number" data-ctrl="${name}" min="${c.min}" max="${c.max}" step="${step}" value="${v ?? ""}">`;
}

function controlValue(e) {
  const c = controls[e.dataset.ctrl];
  if (e.type === "checkbox") return e.checked;
  if (e.dataset.array) return e.value.split(",").filter((s) => s.trim()).map((s) => num(s));
  const integer = Number.isInteger(c.min) && Number.isInteger(c.max) && typeof c.min !== "boolean";
  return integer ? Math.round(num(e.value)) : num(e.value);
}

async function loadControls() {
  controls = await api("/api/controls");
  $("ae").checked = !!(controls.AeEnable?.value ?? controls.AeEnable?.default ?? true);
  if (controls.ExposureTime) $("exposure").value = controls.ExposureTime.value ?? controls.ExposureTime.default ?? "";
  if (controls.AnalogueGain) $("gain").value = fmt(controls.AnalogueGain.value ?? controls.AnalogueGain.default ?? 1, 2);
  $("all-controls").innerHTML = Object.entries(controls)
    .filter(([n]) => !BASIC.has(n) && !SKIP.has(n))
    .map(([n, c]) => `<div class="row" title="min ${esc(c.min)}, max ${esc(c.max)}, default ${esc(c.default)}"><label>${n}</label>${controlInput(n, c)}</div>`)
    .join("");
  document.querySelectorAll("#all-controls [data-ctrl]").forEach((e) => e.addEventListener("change", () => (e.dataset.changed = "1")));
  manualState();
}

async function setControls(values) {
  if (!Object.keys(values).length) { say("controls-msg", "Nothing changed."); return; }
  try {
    const r = await api("/api/controls?remember=" + $("remember").checked, { method: "POST", json: values });
    say("controls-msg", "Set " + r.set.join(", ") + (r.remembered ? " (kept after a restart)" : ""));
  } catch (e) { say("controls-msg", e.message, true); }
}

function manualState() {
  $("exposure").disabled = $("gain").disabled = $("ae").checked;
}
$("ae").onchange = () => { manualState(); if ($("ae").checked) setControls({ AeEnable: true }); };
$("apply-basic").onclick = () => {
  try {
    const v = { AeEnable: $("ae").checked };
    if (!$("ae").checked) { v.ExposureTime = Math.round(num($("exposure").value)); v.AnalogueGain = num($("gain").value); }
    setControls(v);
  } catch (e) { say("controls-msg", e.message, true); }
};
$("apply-all").onclick = () => {
  const v = {};
  try {
    document.querySelectorAll("#all-controls [data-ctrl][data-changed]").forEach((e) => { v[e.dataset.ctrl] = controlValue(e); });
  } catch (e) { say("controls-msg", e.message, true); return; }
  document.querySelectorAll("#all-controls [data-changed]").forEach((e) => delete e.dataset.changed);
  setControls(v);
};
$("forget-controls").onclick = async () => {
  try { await api("/api/controls/remembered", { method: "DELETE" }); say("controls-msg", "Remembered controls cleared: the defaults apply after a restart."); }
  catch (e) { say("controls-msg", e.message, true); }
};
$("mode").onchange = async () => {
  const sel = $("mode"), index = Number(sel.value);
  sel.disabled = true;
  say("controls-msg", "Switching sensor mode...");
  try {
    const r = await api("/api/mode", { method: "POST", json: { index } });
    rois = r.rois; renderRoiTable();
    await loadInfo(); await loadControls();
    say("controls-msg", "Sensor mode " + sel.selectedOptions[0].text);
  } catch (e) {
    say("controls-msg", e.message, true);
    if (info) sel.value = info.mode;
  }
  sel.disabled = false;
};
$("apply-tuning").onclick = async () => {
  const opt = $("tuning").selectedOptions[0], path = $("tuning").value || null;
  const warn = opt && opt.dataset.note;
  if (warn && !confirm(`This tuning file does not fit this sensor (${warn}). If it does not load, the service ` +
      "falls back to the default tuning. Restart with it anyway?")) return;
  say("controls-msg", "Checking the tuning file and restarting the camera with " + (path || "the default tuning") + " ...");
  $("apply-tuning").disabled = true;
  try {
    const r = await api("/api/tuning", { method: "POST", json: { path } });
    await waitForRestart(r.instance, "controls-msg");
  } catch (e) { say("controls-msg", e.message, true); }
  $("apply-tuning").disabled = false;
};

// Info / camera -------------------------------------------------------------------------------
const CFA = { 0: "RGGB", 1: "GRBG", 2: "GBRG", 3: "BGGR", 4: "RGB", 5: "mono" };
async function loadInfo() {
  info = await api("/api/info");
  const p = info.properties, raw = info.raw || {}, main = info.main || {};
  const size = (s) => (s ? s.join("x") : "-");
  $("sensor").textContent = `${p.Model} · ${raw.format} ${size(raw.size)}`;
  document.title = `Picam-web - ${p.Model}`;
  $("mode").innerHTML = info.sensor_modes.map((m, i) =>
    `<option value="${i}" ${i === info.mode ? "selected" : ""}>${m.unpacked} ${m.size.join("x")} ${m.bit_depth}-bit ${fmt(m.fps, 1)} fps</option>`).join("");
  const rows = [["Model", p.Model], ["Pipeline", p.PipelineHandler], ["Pixel array", (p.PixelArraySize || []).join("x")],
    ["Unit cell size", p.UnitCellSize ? p.UnitCellSize.join(" x ") + " nm" : "-"], ["Colour filter", CFA[p.ColorFilterArrangement] ?? "-"],
    ["Raw stream", `${raw.format} ${size(raw.size)}, stride ${raw.stride}`],
    ["Preview stream", `${main.format} ${size(main.size)}`], ["Tuning file", info.tuning_file || "default"],
    ["Sensor (I2C)", info.sensor || "-"], ["Version", info.version]];
  $("camera-table").innerHTML = rows.map(([k, v]) => `<tr><th>${k}</th><td>${esc(v)}</td></tr>`).join("");
  $("modes-table").innerHTML = "<tr><th>Format</th><th>Size</th><th>Bits</th><th>Max fps</th><th>Crop</th></tr>" +
    info.sensor_modes.map((m) => `<tr><td>${m.unpacked}</td><td>${m.size.join("x")}</td><td>${m.bit_depth}</td><td>${fmt(m.fps, 1)}</td><td>${m.crop_limits}</td></tr>`).join("");
  const t = await api("/api/tuning"), model = (p.Model || "").toLowerCase();
  // Fits = this sensor's model, and mono files for a mono sensor (a colour file does not load on a mono one)
  const base = (f) => f.split("/").pop().toLowerCase();
  const note = (f) => !base(f).startsWith(model) ? "other sensor"
    : (info.is_mono !== base(f).includes("mono")) ? (info.is_mono ? "colour, sensor is mono" : "mono, sensor is colour") : "";
  const files = [...t.files.filter((f) => !note(f)), ...t.files.filter((f) => note(f))];
  $("tuning").innerHTML = `<option value="" ${t.current ? "" : "selected"}>default (libcamera's file for this sensor)</option>` + files.map((f) =>
    `<option value="${esc(f)}" data-note="${esc(note(f))}" ${f === t.current ? "selected" : ""}>${esc(f.split("/").slice(-2).join("/"))}${note(f) ? "  (" + note(f) + ")" : ""}</option>`).join("");
}

// Capture -------------------------------------------------------------------------------------
// Downloads through fetch, so an error (e.g. a packed sensor mode) shows here instead of a JSON page.
async function download(url, fallbackName, button) {
  button.disabled = true;
  say("capture-msg", "Capturing...");
  try {
    const r = await fetch(url);
    if (!r.ok) {
      throw new Error(errorText(await r.json().catch(() => null), r.statusText));
    }
    const blob = await r.blob();
    const name = (r.headers.get("content-disposition") || "").match(/filename="?([^";]+)"?/)?.[1] || fallbackName;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    say("capture-msg", `Saved ${name} (${(blob.size / 1e6).toFixed(1)} MB) to the download folder.`);
  } catch (e) { say("capture-msg", e.message, true); }
  button.disabled = false;
}
document.querySelectorAll("[data-download]").forEach((b) => (b.onclick = () => {
  let url = b.dataset.download;
  if (url.includes("format=npz")) url += "&count=" + Math.max(1, Math.round(Number($("cap-count").value) || 1));
  download(url, b.dataset.name, b);
}));

// Frames --------------------------------------------------------------------------------------
function renderFrames(f) {
  $("frames-table").innerHTML = [["Frames received", f.frames], ["Dropped frames", f.dropped], ["Measured fps", fmt(f.fps)],
    ["Expected fps", fmt(f.expected_fps)], ["Last gap", fmt(f.last_gap_ms) + " ms"], ["Max gap", fmt(f.max_gap_ms) + " ms"]]
    .map(([k, v]) => `<tr><th>${k}</th><td class="num">${v}</td></tr>`).join("");
}
$("frames-reset").onclick = async () => {
  try { renderFrames(await api("/api/frames/reset", { method: "POST" })); } catch (e) { $("statusline").textContent = e.message; }
};

// Histogram -----------------------------------------------------------------------------------
async function refreshHistogram() {
  const h = await api("/api/histogram");
  if (h.error) { say("hist-info", h.error, true); return; }
  drawHistogram($("hist"), h.channels, $("hist-log").checked);
  say("hist-info", `${h.bits}-bit raw: mean ${fmt(h.mean, 1)}, min ${h.min}, max ${h.max} DN`);
}

// ROIs ----------------------------------------------------------------------------------------
function renderRoiTable() {
  $("roi-table").querySelector("tbody").innerHTML = rois.map((r, i) =>
    `<tr data-i="${i}"><td><input value="${esc(r.name)}" data-k="name"></td>` +
    ["x", "y", "w", "h"].map((k) => `<td><input type="number" min="${k === "w" || k === "h" ? 1 : 0}" value="${r[k]}" data-k="${k}"></td>`).join("") +
    `<td class="num roi-mean">${fmt(r.mean, 1)}</td><td><button data-del="${i}" title="Remove">x</button></td></tr>`).join("");
  const sel = $("noise-roi").value;
  $("noise-roi").innerHTML = '<option value="">full frame</option>' +
    rois.map((r, i) => `<option value="${i}">${esc(r.name)} (${r.x}, ${r.y}, ${r.w}x${r.h})</option>`).join("");
  if (sel && Number(sel) < rois.length) $("noise-roi").value = sel;
  document.querySelectorAll("[data-del]").forEach((b) => (b.onclick = () => {
    if (!readRoiTable()) return;
    rois.splice(Number(b.dataset.del), 1); saveRois();
  }));
}
function readRoiTable() {
  try {
    document.querySelectorAll("#roi-table tbody tr").forEach((tr) => {
      const r = rois[Number(tr.dataset.i)];
      tr.querySelectorAll("input").forEach((e) => (r[e.dataset.k] = e.dataset.k === "name" ? e.value : Math.round(num(e.value))));
    });
    return true;
  } catch (e) { say("roi-msg", e.message, true); return false; }
}
async function saveRois() {
  try {
    rois = await api("/api/rois", { method: "PUT", json: rois.map(({ name, x, y, w, h }) => ({ name, x, y, w, h })) });
    say("roi-msg", rois.length ? `${rois.length} ROI(s)` : "No ROIs");
  } catch (e) {
    say("roi-msg", e.message, true);
    rois = await api("/api/rois").catch(() => rois);
  }
  renderRoiTable();
}
$("roi-add").onclick = () => {
  if (!info || !readRoiTable()) return;
  const [w, h] = info.raw.size, s = Math.max(16, Math.floor(Math.min(w, h) / 8)), n = rois.length;
  rois.push({ name: `ROI${n + 1}`, x: Math.max(0, Math.min(w - s, Math.floor(w / 2 - s / 2) + (n % 4) * s)),
    y: Math.max(0, Math.min(h - s, Math.floor(h / 2 - s / 2) + (n % 4) * s)), w: s, h: s });
  saveRois();
};
$("roi-save").onclick = () => { if (readRoiTable()) saveRois(); };
async function refreshRois() {
  const live = await api("/api/rois");
  live.forEach((r, i) => { if (rois[i]) { rois[i].mean = r.mean; rois[i].view = r.view; } });
  if (live.length !== rois.length) { rois = live; renderRoiTable(); }
  document.querySelectorAll(".roi-mean").forEach((td, i) => (td.textContent = fmt(rois[i]?.mean, 1)));
  drawOverlay();
}

// Noise ---------------------------------------------------------------------------------------
const NOISE_ROWS = [["mean", "Mean"], ["min", "Min"], ["max", "Max"], ["temporal_noise", "Temporal noise"], ["fpn", "Total FPN"],
  ["row_fpn", "Row FPN"], ["col_fpn", "Column FPN"], ["row_temporal_noise", "Row temporal noise"], ["col_temporal_noise", "Column temporal noise"]];
$("noise-run").onclick = async () => {
  const sel = $("noise-roi").value, roi = sel === "" ? null : ["x", "y", "w", "h"].map((k) => rois[Number(sel)][k]);
  const frames = Math.max(1, Math.round(Number($("noise-frames").value) || 16));
  say("noise-msg", `Capturing ${frames} frames...`); $("noise-run").disabled = true;
  try {
    const r = await api("/api/noise", { method: "POST", json: { frames, roi } });
    $("noise-table").innerHTML = NOISE_ROWS.map(([k, n]) => `<tr><th>${n} [DN]</th><td class="num">${fmt(r[k], 3)}</td></tr>`).join("");
    say("noise-msg", `${r.frames} frames, ${r.format} ${r.bit_depth}-bit, ${r.pixels} pixels` + (r.roi ? `, ROI ${r.roi.join(", ")}` : ", full frame"));
  } catch (e) { say("noise-msg", e.message, true); }
  $("noise-run").disabled = false;
};

// Registers -----------------------------------------------------------------------------------
async function loadRegisters() {
  const k = await api("/api/registers/known");
  $("reg-sensor").textContent = k.sensor || "No sensor found on an I2C bus";
  $("reg-known").innerHTML = '<option value="">(address below)</option>' +
    k.registers.map((r) => `<option value="${r.address},${r.bytes}">${r.name}  ${hex(r.address, 2)}</option>`).join("");
  document.querySelectorAll(".banked").forEach((e) => (e.style.display = k.banked ? "" : "none"));
  document.querySelectorAll("#tab-registers button").forEach((b) => (b.disabled = !k.sensor));
}
$("reg-known").onchange = () => { const [a, b] = $("reg-known").value.split(","); if (a) { $("reg-addr").value = hex(a, 2); $("reg-bytes").value = b; } };
const regLog = (t) => { $("reg-log").textContent = `${new Date().toLocaleTimeString()} ${t}\n` + $("reg-log").textContent; };
const bankSel = () => ({ bank: $("reg-bank").value === "" ? null : Number($("reg-bank").value),
  context: $("reg-ctx").value === "" ? null : Number($("reg-ctx").value) });
const regQuery = (extra) => {
  const q = new URLSearchParams(extra), s = bankSel();
  if (s.bank !== null) q.set("bank", s.bank);
  if (s.context !== null) q.set("context", s.context);
  return q;
};
$("reg-read").onclick = async () => {
  try {
    const a = num($("reg-addr").value), n = Number($("reg-bytes").value);
    const r = await api(`/api/registers/${a}?${regQuery({ nbytes: n })}`);
    $("reg-value").value = hex(r.value, r.bytes);
    regLog(`read  ${hex(a, 2)} = ${hex(r.value, r.bytes)} (${r.value})`);
  } catch (e) { regLog("ERROR " + e.message); }
};
$("reg-write").onclick = async () => {
  try {
    const a = num($("reg-addr").value), value = num($("reg-value").value), nbytes = Number($("reg-bytes").value);
    await api(`/api/registers/${a}`, { method: "PUT", json: { value, nbytes, ...bankSel() } });
    regLog(`write ${hex(a, 2)} = ${hex(value, nbytes)}`);
  } catch (e) { regLog("ERROR " + e.message); }
};
$("reg-dump").onclick = async () => {
  try {
    const q = regQuery({ start: num($("dump-start").value), count: Math.round(num($("dump-count").value)) });
    const d = await api(`/api/registers/dump?${q}`), lines = [];
    for (let i = 0; i < d.length; i += 16) lines.push(hex(d[i].address, 2) + ": " + d.slice(i, i + 16).map((x) => x.value.toString(16).padStart(2, "0")).join(" "));
    regLog("dump\n" + lines.join("\n"));
  } catch (e) { regLog("ERROR " + e.message); }
};

// ISP statistics ------------------------------------------------------------------------------
$("isp-enable").onchange = async () => {
  try { await api("/api/isp_stats/enable", { method: "POST", json: { enabled: $("isp-enable").checked } }); }
  catch (e) { $("isp-enable").checked = false; say("isp-msg", e.message, true); }
};
async function refreshIspStats() {
  const s = await api("/api/isp_stats");
  $("isp-enable").checked = !!s.enabled;
  if (s.error) { say("isp-msg", s.error, s.enabled && !s.error.startsWith("waiting")); return; }
  drawHistogram($("isp-hist"), { Y: s.histogram }, true);
  drawMap($("isp-zones"), s.zones_mean);
  drawMap($("isp-focus"), s.focus);
  say("isp-msg", `${s.count} statistics frames received`);
}

// Health and recovery -------------------------------------------------------------------------
let lastHealth = null;
async function doReset(action) {
  if (action === "reboot" && !confirm("Reboot the Raspberry Pi? The page reconnects when it is back.")) return;
  const before = lastHealth && lastHealth.instance;
  try { await api("/api/reset", { method: "POST", json: { action } }); }
  catch (e) { $("health").className = "health failed"; $("health").textContent = e.message; return; }
  $("health").className = "health recovering";
  $("health").textContent = { stream: "Restarting the stream...", camera: "Reopening the camera...", reboot: "Rebooting..." }[action];
  if (action !== "stream") await waitForRestart(before, null, action === "reboot" ? 180000 : 60000);
}
document.querySelectorAll("[data-reset]").forEach((b) => (b.onclick = () => doReset(b.dataset.reset)));
$("auto-reboot").onchange = async () => {
  try { await api("/api/auto_reboot", { method: "POST", json: { enabled: $("auto-reboot").checked } }); }
  catch (e) { $("auto-reboot").checked = !$("auto-reboot").checked; $("statusline").textContent = e.message; }
};

async function refreshHealth() {
  const h = await api("/api/health");
  const changedToStreaming = lastHealth && lastHealth.state !== "streaming" && h.state === "streaming";
  lastHealth = h;
  const banner = $("health");
  banner.className = "health " + h.state;
  banner.innerHTML = h.state === "streaming" ? "" : `<b>${esc(h.state)}</b>: ${esc(h.message)}` +
    (h.kernel.length ? `<br><small>kernel: ${esc(h.kernel[h.kernel.length - 1])}</small>` : "") +
    (h.state === "failed" ? ' <button data-banner="camera">Reset camera</button><button data-banner="reboot">Reboot Pi</button>' : "");
  banner.querySelectorAll("[data-banner]").forEach((b) => (b.onclick = () => doReset(b.dataset.banner)));
  if (document.activeElement !== $("auto-reboot")) $("auto-reboot").checked = h.auto_reboot;
  $("health-history").textContent = [...h.history].reverse().map((x) => x.join(" ")).join("\n") +
    (h.kernel.length ? "\n\nKernel:\n" + h.kernel.join("\n") : "");
  if (changedToStreaming) { $("stream").src = "/stream.mjpg?" + Date.now(); }  // reconnect the preview
  return h;
}

// Polling -------------------------------------------------------------------------------------
let refreshing = false;
async function refresh() {
  if (refreshing) return;  // a slow answer must not pile up requests
  refreshing = true;
  try {
    const h = await refreshHealth();
    if (h.state === "failed" && !info) return;
    const f = await api("/api/frames");
    $("statusline").textContent = f.error || `${fmt(f.fps, 1)} fps · ${f.frames} frames · ${f.dropped} dropped`;
    $("statusline").className = f.error ? "error" : "";
    if (activeTab === "frames") renderFrames(f);
    if (activeTab === "histogram") await refreshHistogram();
    if (activeTab === "ispstats") await refreshIspStats();
    if (activeTab === "camera") $("metadata").textContent = JSON.stringify(await api("/api/metadata"), null, 1);
    if (activeTab === "controls" && $("ae").checked) {
      const md = await api("/api/metadata");
      if (md.ExposureTime !== undefined) $("exposure").value = md.ExposureTime;
      if (md.AnalogueGain !== undefined) $("gain").value = fmt(md.AnalogueGain, 2);
    }
    if (info) await refreshRois();
  } catch (e) {
    $("statusline").textContent = "Connection: " + e.message;
    $("statusline").className = "error";
    $("health").className = "health recovering";
    $("health").textContent = "Waiting for the camera service (restarting or rebooting)...";
    lastHealth = { ...(lastHealth || {}), state: "offline" };
  } finally {
    refreshing = false;
  }
}

(async () => {
  setInterval(refresh, 500);
  window.addEventListener("resize", drawOverlay);
  $("stream").addEventListener("load", drawOverlay);
  // When the camera is unavailable the rest of the API answers 503: keep polling health, retry later
  for (;;) {
    try {
      await loadInfo();
      await loadControls();
      await loadRegisters();
      rois = await api("/api/rois");
      renderRoiTable();
      return;
    } catch (e) {
      info = null;
      await sleep(3000);
    }
  }
})();
