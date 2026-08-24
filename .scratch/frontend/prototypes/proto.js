"use strict";
/* THROWAWAY PROTOTYPE - frontend ticket 02. NOT the implementation.
 *
 * Three structurally different answers to "how do seven layers read together", on the ONE
 * page ticket 01 settled (web/index.html grows per-layer toggles; no second page, no modes).
 *   A  one fill channel, mutually exclusive; a stacked row per layer
 *   B  one channel per quantity (fill / outline / point); everything coexists; dense grid
 *   C  the map paints ONE quantity, the rest is a ranked ledger with locate-on-hover
 *
 * Every payload is REAL (see README.md); the only fixture is data/chips-demo.json, cut to
 * flood_truth.chips()' verbatim dict shape because the real tier returns [] today.
 *
 * Ticket 01 MUSTs honoured here so the prototype tests the real thing:
 *  - every layer DECLARES AT BOOT with an empty FeatureCollection + visibility:"none";
 *    there is not one lazy addSource/addLayer in this file.
 *  - promoteId is OFF everywhere (asset ids are hex strings; MapLibre 5.9.0 silently
 *    drops a source whose promoted id is not integer-like).
 *  - age is <origin Date header> - <Last-Modified header>, per SOURCE, never a payload
 *    stamp; the live pair keeps its vp_age_s composite.
 *  - #provenance is always mounted; no variant may hide it.
 */

// ------------------------------------------------------------------ frozen, copied verbatim
const RATIO_STOPS = [[0.5, "#7f0000"], [0.65, "#d7301f"], [0.8, "#fc8d59"], [0.9, "#fdd49e"],
                     [1.0, "#f7f7f7"], [1.1, "#c7dcef"], [1.2, "#6baed6"]];
const GREY = "#3a4049";
const WATER = "#35d6c2", ALERT = "#ffc447", HIST = "#8f7bd6", LIVE_C = "#b0bec5";

const WEB = "../../../web/", R14 = "../../../research/14-serving-prototype/files/", D = "data/";

/* The staleness table. Ticket 01: thresholds stay a TABLE, never a formula. Only TWO of the
 * nine sources below have a budget frozen anywhere in the repo -- app.js's STALE_AFTER_S.live
 * (120) and flood_truth.MAX_AGE_MIN (10 min). Everything else is `null`, which renders as an
 * AGE with no verdict rather than a guessed FRESH. That gap is a finding, not an oversight. */
const LAYERS = [
  { id: "zones",  name: "Ground: taxi zones", base: true, gated: false, fill: false,
    srcs: [{ k: "zones.geojson", url: WEB + "files/zones.geojson", budget: null }] },
  { id: "cells",  name: "Delay cells", gated: false, fill: true,
    srcs: [{ k: "cells.geojson", url: WEB + "files/cells.geojson", budget: null },
           { k: "headline.json", url: WEB + "files/headline.json", budget: null }] },
  { id: "live",   name: "Live fleet", gated: true, fill: false,
    srcs: [{ k: "live.geojson", url: R14 + "live.geojson", budget: 120, inner: "vp_age_s" },
           { k: "meta.json",    url: R14 + "meta.json",    budget: 120 }] },
  { id: "fn",     name: "Flood tier: FloodNet", gated: false, fill: false,
    srcs: [{ k: "FloodNet sensors", url: D + "truth.json", budget: 600 }] },
  { id: "mta",    name: "Flood tier: MTA alerts", gated: true, fill: false,
    srcs: [{ k: "archive/subway_alerts", url: D + "chips-demo.json", budget: null }] },
  { id: "impact", name: "Impact overlay: bus", gated: true, fill: true,
    srcs: [{ k: "gold/cell_hour_speed", url: D + "impact.json", budget: null }] },
  { id: "hist",   name: "Flood history markers", gated: false, fill: false,
    srcs: [{ k: "notify 05 manifest", url: D + "markers.geojson", budget: null }] },
];
const L = (id) => LAYERS.find(x => x.id === id);

const $ = (id) => document.getElementById(id);
const q = new URLSearchParams(location.search);
let VAR = (q.get("variant") || "A").toUpperCase();
if (!"ABC".includes(VAR)) VAR = "A";
let GATE_OPEN = q.get("gate") === "open";

const on = { zones: true, cells: true, live: false, fn: false, mta: false, impact: false, hist: false };
const ages = {};          // "<layer>/<source key>" -> seconds, or null
let head = null, cellsFC = null, view = null, hourKey = null, views = [];

// ------------------------------------------------------------------------ declare at boot
const empty = () => ({ type: "geojson", data: { type: "FeatureCollection", features: [] } });
const map = new maplibregl.Map({
  container: "map", center: [-73.93, 40.72], zoom: 10.1, attributionControl: false,
  style: { version: 8,
    // no promoteId ANYWHERE: Cell ids are hex strings and vehicle_id is "MTA NYCT_1234".
    sources: { zones: empty(), cells: empty(), impact: empty(), live: empty(),
               fn: empty(), mta: empty(), hist: empty(), locate: empty() },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": "#0b0d10" } },
      { id: "zones-fill", type: "fill", source: "zones", paint: { "fill-color": "#141920" } },
      { id: "cells", type: "fill", source: "cells", layout: { visibility: "none" },
        paint: { "fill-color": GREY, "fill-opacity": 0.86 } },
      // A and C paint the overlay as a FILL (it replaces the delay fill); B paints it as an
      // OUTLINE on the same geography so both cell quantities read at once. Both declared.
      { id: "impact-fill", type: "fill", source: "impact", layout: { visibility: "none" },
        paint: { "fill-color": GREY, "fill-opacity": 0.86 } },
      { id: "cells-line", type: "line", source: "cells", layout: { visibility: "none" },
        paint: { "line-color": "#0b0d10", "line-width": 0.4 } },
      { id: "impact-line", type: "line", source: "impact", layout: { visibility: "none" },
        paint: { "line-color": ALERT, "line-opacity": 0.9,
          "line-width": ["interpolate", ["linear"], ["get", "ratio"], 0.6, 3.4, 1.0, 0.2] } },
      { id: "zones-line", type: "line", source: "zones",
        paint: { "line-color": "#39424f", "line-width": 0.8 } },
      { id: "locate", type: "circle", source: "locate",
        paint: { "circle-radius": 13, "circle-color": "rgba(0,0,0,0)",
                 "circle-stroke-color": "#8ecbff", "circle-stroke-width": 2 } },
      // point stack, ambient at the bottom and most urgent on top
      { id: "live", type: "circle", source: "live", layout: { visibility: "none" },
        paint: { "circle-radius": 2.6, "circle-color": LIVE_C, "circle-opacity": 0.9 } },
      { id: "hist", type: "circle", source: "hist", layout: { visibility: "none" },
        paint: { "circle-color": HIST, "circle-opacity": 0.5,
          "circle-radius": ["interpolate", ["linear"], ["get", "n_events"], 1, 1.6, 12, 4.6] } },
      { id: "fn", type: "circle", source: "fn", layout: { visibility: "none" },
        paint: { "circle-color": ["case", ["get", "display"], WATER, GREY],
                 "circle-radius": ["case", ["get", "display"], 6, 2.6],
                 "circle-stroke-color": "#0b0d10", "circle-stroke-width": 1 } },
      { id: "mta", type: "circle", source: "mta", layout: { visibility: "none" },
        paint: { "circle-color": ALERT, "circle-radius": 7, "circle-opacity": 0.92,
                 "circle-stroke-color": "#0b0d10", "circle-stroke-width": 1.5 } },
    ] },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution:
  "MTA Bus Time GTFS-RT; FloodNet NYC; NYC 311; NOAA AORC; NYC TLC taxi zones" }));

// ------------------------------------------------------------------- age, from the headers
/* Ticket 01, D2: age = <origin Date> - <Last-Modified>, both from the response the page
 * already made, both on the ORIGIN's clock, so a browser clock cannot fake freshness. */
async function grab(url) {
  const res = await fetch(url, { cache: "no-store" });
  const d = Date.parse(res.headers.get("Date")), m = Date.parse(res.headers.get("Last-Modified"));
  return { body: await res.json(),
           age: (Number.isNaN(d) || Number.isNaN(m)) ? null : Math.max(0, (d - m) / 1000) };
}
async function load(layerId) {
  const lyr = L(layerId), out = [];
  for (const s of lyr.srcs) {
    try { const r = await grab(s.url); ages[layerId + "/" + s.k] = r.age; out.push(r.body); }
    catch (e) { ages[layerId + "/" + s.k] = null; out.push(null); }
  }
  return out;
}

const fmtAge = (s) => s === null || s === undefined ? "age unknown"
  : s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min`
  : s < 172800 ? `${Math.round(s / 3600)} h` : `${Math.round(s / 86400)} d`;

/* FRESH / STALE(+reason) / OFF / GATED -- and AGE, for a source with no budget frozen.
   Freshness is NOT verdict: flood 15's tier states are rendered separately, below. */
function srcState(lyr, s) {
  if (lyr.gated && !GATE_OPEN) return { s: "GATED", why: "MTA terms not verified" };
  if (!on[lyr.id]) return { s: "OFF", why: "nothing fetched" };
  let age = ages[lyr.id + "/" + s.k];
  if (age === null || age === undefined) return { s: "STALE", why: "no age from headers" };
  if (s.inner && liveMeta && typeof liveMeta[s.inner] === "number") age += liveMeta[s.inner];
  if (s.budget === null) return { s: "AGE", why: "no budget frozen", age };
  return age <= s.budget ? { s: "FRESH", age } : { s: "STALE", why: `over ${s.budget} s`, age };
}
const worst = (lyr) => { const o = lyr.srcs.map(s => srcState(lyr, s).s);
  for (const k of ["GATED", "STALE", "OFF", "AGE", "FRESH"]) if (o.includes(k)) return k; };

// ------------------------------------------------------------------------ layer painting
let liveMeta = null, truth = null, chips = null, markers = null, impact = null,
    complexes = null;

async function fill(id) {
  if (id === "zones") { const [z] = await load("zones"); map.getSource("zones").setData(z); return; }
  if (id === "cells") {
    const [c, h] = await load("cells"); cellsFC = c; head = h;
    map.getSource("cells").setData(c);
    $("prov-files").textContent = ` ${c.features.length} footprint Cells; ` +
      `publish gate: 95% interval width < ${h.gate_width}.`;
    buildViews(); return;
  }
  if (id === "live") { const [fc, m] = await load("live"); liveMeta = m;
    map.getSource("live").setData(fc); return; }
  if (id === "fn") { const [t] = await load("fn"); truth = t;
    map.getSource("fn").setData({ type: "FeatureCollection", features:
      t.floodnet.sensors.filter(s => s.lon != null).map(s => ({ type: "Feature",
        geometry: { type: "Point", coordinates: [s.lon, s.lat] }, properties: s })) }); return; }
  if (id === "mta") { const [t] = await load("mta"); chips = t;
    // A chip is one INCIDENT over one or more complexes; the marker is the complex. The chip
    // itself carries NO coordinates (flood_truth.chips() emits {complex_id, name, state}),
    // so placing it needs this second lookup off ref/assets. Recorded on the ticket.
    if (!complexes) complexes = await (await fetch(D + "complexes.json")).json();
    const pts = [];
    for (const c of t.chips) for (const st of c.stations) {
      const cx = complexes[st.complex_id];
      const a = cx ? [cx.lon, cx.lat] : null;
      if (a) pts.push({ type: "Feature", geometry: { type: "Point", coordinates: a },
        properties: { ...st, event_id: c.event_id, age_min: c.age_min, chip_state: c.state,
                      alert_ids: c.alert_ids.join(",") } });
    }
    map.getSource("mta").setData({ type: "FeatureCollection", features: pts }); return; }
  if (id === "hist") { const [fc] = await load("hist"); markers = { fc };
    map.getSource("hist").setData(fc); return; }
  if (id === "impact") { const [j] = await load("impact"); impact = j;
    const by = new Map(j.cells.map(c => [c.cell, c]));
    const feats = [];
    for (const f of (cellsFC ? cellsFC.features : [])) {
      const r = by.get(f.properties.cell); if (!r) continue;
      const dry = f.properties.w2_dry;
      feats.push({ type: "Feature", geometry: f.geometry, properties: { cell: r.cell,
        speed_mps: r.speed_mps, n_legs: r.n_legs, n_vehicles: r.n_vehicles,
        ratio: dry ? +(r.speed_mps / dry).toFixed(3) : undefined } });
    }
    map.getSource("impact").setData({ type: "FeatureCollection", features: feats });
    map.setPaintProperty("impact-fill", "fill-color", colorExpr("ratio", RATIO_STOPS));
    return; }
}

function colorExpr(prop, stops) {
  const i = ["interpolate", ["linear"], ["get", prop]];
  stops.forEach(([v, c]) => i.push(v, c));
  return ["case", ["!", ["has", prop]], GREY, i];
}

function vis() {
  const lit = (id) => on[id] && !(L(id).gated && !GATE_OPEN);
  map.setLayoutProperty("cells", "visibility", lit("cells") ? "visible" : "none");
  map.setLayoutProperty("cells-line", "visibility", lit("cells") ? "visible" : "none");
  // the ONE structural difference on the map itself: which channel the overlay uses
  map.setLayoutProperty("impact-fill", "visibility",
    lit("impact") && VAR !== "B" ? "visible" : "none");
  map.setLayoutProperty("impact-line", "visibility",
    lit("impact") && VAR === "B" ? "visible" : "none");
  for (const id of ["live", "fn", "mta", "hist"])
    map.setLayoutProperty(id, "visibility", lit(id) && VAR !== "C" ? "visible" : "none");
}

async function toggle(id, want) {
  const lyr = L(id);
  if (lyr.gated && !GATE_OPEN) return;
  on[id] = want;
  if (want && lyr.fill && VAR !== "B")
    for (const o of LAYERS) if (o.fill && o.id !== id && on[o.id]) { on[o.id] = false; }
  if (want) await fill(id);
  else { lyr.srcs.forEach(s => delete ages[id + "/" + s.k]); }
  vis(); render();
}

// ------------------------------------------------------------------ delay views (trimmed)
function buildViews() {
  const keys = new Set(); cellsFC.features.forEach(f =>
    Object.keys(f.properties).forEach(k => keys.add(k)));
  views = [];
  for (const [layer, label] of [["ida", "Ida 2021-09-02"], ["f23", "2023-09-29 flood"]]) {
    const hs = head.rows.filter(r => r.layer === layer && r.on_map).map(r => r.key).sort();
    if (hs.length) views.push({ id: layer, layer, label, hours: true, hourKeys: hs,
      defaultHour: hs.reduce((a, k) => head.rows.find(r => r.key === k).value <
        head.rows.find(r => r.key === a).value ? k : a) });
  }
  for (const w of ["w1", "w2"]) if (head.rows.some(r => r.layer === w))
    views.push({ id: w, layer: w, label: `${w.toUpperCase()} wet vs dry`, hours: false,
                 prop: `${w}_ratio` });
  $("views").innerHTML = views.map(v =>
    `<button type="button" data-v="${v.id}" aria-pressed="false">${v.label}</button>`).join("");
  setView(views[views.length - 1].id);
}
const activeProp = () => (view.hours ? "r" + hourKey : view.prop);
function setView(id) {
  view = views.find(v => v.id === id);
  document.querySelectorAll("#views button").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.v === id)));
  hourKey = view.hours ? (view.hourKeys.includes(hourKey) ? hourKey : view.defaultHour) : null;
  $("hours").innerHTML = !view.hours ? "" : view.hourKeys.map(k =>
    `<button type="button" data-h="${k}" aria-pressed="${k === hourKey}">${
      head.rows.find(r => r.layer === view.layer && r.key === k).label.slice(-3)}</button>`).join("");
  map.setPaintProperty("cells", "fill-color", colorExpr(activeProp(), RATIO_STOPS));
  $("swatches").innerHTML = RATIO_STOPS.map(([, c]) => `<span style="background:${c}"></span>`).join("");
  $("tick-lo").textContent = "0.5 slower"; $("tick-mid").textContent = "1.0";
  $("tick-hi").textContent = "1.2 faster";
  const r = head.rows.find(x => x.layer === view.layer && (view.hours ? x.key === hourKey : true));
  $("headline").innerHTML = r ? `<div class="row"><div class="big">${r.value.toFixed(3)}</div>
    <div class="band">citywide Speed ratio &middot; ${r.n_cells} Cells shown,
    <b>${r.n_cells_hidden} hidden</b></div></div>` : "";
  $("preview-note").textContent = head.preview_note;
}
$("views").addEventListener("click", e => { if (e.target.dataset.v) setView(e.target.dataset.v); });
$("hours").addEventListener("click", e => { if (e.target.dataset.h) {
  hourKey = e.target.dataset.h; setView(view.id); } });

// ------------------------------------------------------------------------- the panels
const chip = (st) => `<span class="st st-${st.s}">${st.s}</span>`;
// ref/assets names only stops and complexes: a `cell`-kind asset has name = NULL, and the
// most-flooded assets are exactly those. Never label off `name` alone.
const label = (p) => p.name || (p.kind === "cell" ? "Cell " + p.asset_id.slice(5, 12) + "\u2026"
                                                  : p.asset_id);
function srcLines(lyr) {
  return lyr.srcs.map(s => { const st = srcState(lyr, s);
    return `<div class="src"><b>${s.k}</b><span>${
      st.age !== undefined ? fmtAge(st.age) + " " : ""}${chip(st)}</span></div>` +
      (st.why ? `<div class="src" style="opacity:.75"><span>${st.why}</span></div>` : "");
  }).join("");
}
const gateNote = (lyr) => lyr.gated && !GATE_OPEN
  ? `<p class="note">Dark: publishing this needs the MTA redistribution terms verified.
     The toggle stays, so the page never pretends the layer does not exist.</p>` : "";

function renderA() {
  const row = (lyr, kind) => `<div class="lyr ${lyr.gated && !GATE_OPEN ? "gated" : ""}">
    <label><input type="${kind}" ${kind === "radio" ? 'name="cellfill"' : ""}
      data-l="${lyr.id}" ${on[lyr.id] ? "checked" : ""}
      ${lyr.gated && !GATE_OPEN ? "disabled" : ""}>
      <span class="nm">${lyr.name}</span>${chip({ s: worst(lyr) })}</label>
    ${on[lyr.id] || (lyr.gated && !GATE_OPEN) ? srcLines(lyr) : ""}${gateNote(lyr)}</div>`;
  $("a-fill").innerHTML = LAYERS.filter(l => l.fill).map(l => row(l, "radio")).join("");
  $("a-pts").innerHTML = LAYERS.filter(l => !l.fill && !l.base).map(l => row(l, "checkbox")).join("");
  $("keys-extra").textContent = "One fill at a time: the delay layer and the impact overlay " +
    "are the same quantity (a Speed ratio) over the same Cells at different time-scales, " +
    "so they share one ramp and one channel and can never disagree on screen.";
}

function renderB() {
  $("grid-body").innerHTML = LAYERS.filter(l => !l.base).map(lyr => {
    const g = lyr.gated && !GATE_OPEN;
    return `<tr class="${g ? "gated" : ""}"><td><input type="checkbox" data-l="${lyr.id}"
      ${on[lyr.id] ? "checked" : ""} ${g ? "disabled" : ""}></td>
      <td class="n">${lyr.name}<div class="sub">${CHANNEL[lyr.id]}</div></td>
      <td>${chip({ s: worst(lyr) })}</td><td class="sub">${
        lyr.srcs.map(s => { const st = srcState(lyr, s);
          return `${s.k}: ${st.age !== undefined ? fmtAge(st.age) : (st.why || "-")}`;
        }).join("<br>")}</td></tr>`;
  }).join("");
  $("keys-extra").textContent = "Every quantity owns one channel: Cell FILL is the delay " +
    "ratio, Cell OUTLINE thickness is this hour's impact, and the three flood facts are " +
    "points at three sizes. Nothing has to be switched off to read something else.";
}
const CHANNEL = { cells: "channel: Cell fill (frozen ratio ramp)", live: "channel: small grey dots",
  fn: "channel: aqua dot, filled only when water is detected", mta: "channel: amber dot on the complex",
  impact: "channel: Cell OUTLINE width (same Cells, no second fill)",
  hist: "channel: violet dot, radius by event count" };

function renderC() {
  const sec = (head_, body) => `<div class="sec">${head_}${body}</div>`;
  const led = (color, name, right, detail, data) =>
    `<div class="led" ${data} aria-expanded="false"><div class="hd">
      <span class="dot" style="background:${color}"></span><b>${name}</b>
      <span class="sub note" style="margin:0">${right}</span></div>
      <div class="detail">${detail}</div></div>`;
  const parts = [];
  for (const lyr of LAYERS.filter(l => !l.base)) {
    const g = lyr.gated && !GATE_OPEN;
    const head_ = `<label style="display:flex;gap:7px;align-items:baseline;cursor:pointer">
      <input type="checkbox" data-l="${lyr.id}" ${on[lyr.id] ? "checked" : ""}
        ${g ? "disabled" : ""}><span style="flex:1">${lyr.name}</span>
      ${chip({ s: worst(lyr) })}</label>`;
    let body = "";
    if (g) body = gateNote(lyr);
    else if (!on[lyr.id]) body = `<p class="note">off - nothing is being fetched.</p>`;
    else if (lyr.id === "fn" && truth) {
      const w = truth.floodnet.sensors.filter(s => s.display);
      body = w.length ? w.map(s => led(WATER, s.name, `${s.depth_mm} mm`,
        `<div class="ev"><span class="k">deployment</span> ${s.deployment_id} &middot;
         <span class="k">age</span> ${s.age_min} min &middot; <span class="k">state</span>
         ${s.state}<br>${s.label || ""}</div>`,
        `data-lon="${s.lon}" data-lat="${s.lat}"`)).join("")
        : `<p class="note">${truth.floodnet.read.rendered} sensors read, none reporting water.
           ${truth.floodnet.read.muted} muted, ${truth.floodnet.read.unknown} unknown.</p>`;
    }
    else if (lyr.id === "mta" && chips) {
      body = chips.chips.map(c => led(ALERT, c.stations.map(s => s.name).join(" + "),
        `${c.state} &middot; ${Math.round(c.age_min)} min`,
        `<div class="ev"><span class="k">incident</span> ${c.event_id} &middot;
         <span class="k">first seen</span> ${c.first_seen} &middot;
         <span class="k">last seen</span> ${c.last_seen}</div>`,
        `data-cx="${c.stations[0].complex_id}"`)).join("");
    }
    else if (lyr.id === "hist" && markers) {
      const top = [...markers.fc.features].sort((a, b) =>
        b.properties.n_events - a.properties.n_events).slice(0, 25);
      body = `<p class="note">${markers.fc.features.length.toLocaleString()} stops and Cells
        have a flood record. Top 25 by event count:</p>` + top.map(f => led(HIST,
        label(f.properties), `${f.properties.n_events} events`,
        `<div class="ev" data-hist="${f.properties.asset_id}">loading record&hellip;</div>`,
        `data-lon="${f.geometry.coordinates[0]}" data-lat="${f.geometry.coordinates[1]}"
         data-asset="${f.properties.asset_id}"`)).join("");
    }
    else if (lyr.id === "impact" && impact) {
      body = `<p class="note">${impact.cells.length} Cells carried buses in the hour ending
        ${impact.hour_end_utc}.</p>`;
    }
    else if (lyr.id === "cells" && head) {
      body = `<p class="note">painted on the map - this is the ONE quantity the map carries.</p>`;
    }
    else if (lyr.id === "live" ) body = `<p class="note">-</p>`;
    parts.push(sec(head_, body + (on[lyr.id] && !g ? srcLines(lyr) : "")));
  }
  $("ledger-body").innerHTML = parts.join("");
  $("keys-extra").textContent = "The map carries one quantity. Everything else is a ranked " +
    "row: hover to locate it, click to open its record in place. No popover ever covers " +
    "the map, and the whole surface survives 375px without collapsing.";
}

function render() {
  $("layers").hidden = VAR !== "A"; $("grid").hidden = VAR !== "B"; $("ledger").hidden = VAR !== "C";
  $("vname").textContent = { A: "A - Stack (one fill)", B: "B - Channels (all at once)",
                             C: "C - Ledger (map is the index)" }[VAR];
  $("gate").classList.toggle("on", GATE_OPEN);
  ({ A: renderA, B: renderB, C: renderC })[VAR]();
}

// ------------------------------------------------------------------------- interaction
document.body.addEventListener("change", e => {
  const id = e.target.dataset && e.target.dataset.l; if (!id) return;
  if (e.target.type === "radio")
    LAYERS.filter(l => l.fill && l.id !== id).forEach(l => { if (on[l.id]) toggle(l.id, false); });
  toggle(id, e.target.checked);
});

/* A and B: one card, pinned bottom-right, out of the left column's way and never over the
   panels. C: no card at all - the record opens inside the ledger row. */
async function openCard(assetId, title) {
  if (VAR === "C") return;
  $("card").classList.add("on");
  $("card-body").innerHTML = `<h3>${title}</h3><p class="note">loading record&hellip;</p>`;
  $("card-body").innerHTML = `<h3>${title}</h3>` + await historyHTML(assetId);
}
async function historyHTML(assetId) {
  try {
    const p = await (await fetch(D + "history/" + assetId.replace(":", "_") + ".json")).json();
    if (!p.n_events) return `<p class="note">${p.reason}</p>`;
    return `<p class="note">${p.asset.kind} ${p.asset.asset_id} &middot;
      <b>${p.n_events}</b> flood events on record &middot; label ${p.versions.label_version}</p>` +
      p.events.slice(-8).reverse().map(e => `<div class="ev">
        <b>${e.event_id}</b> <span class="k">${e.event_class}${
          e.flood_cause ? " &middot; " + e.flood_cause : ""}</span><br>
        <span class="k">sources</span> ${Object.entries(e.event_source_counts || {})
          .map(([s, n]) => `${s} ${n}`).join(", ")}
        <span class="k">&middot; support</span> ${(e.label_support || []).join(", ")}</div>`).join("") +
      `<p class="note">counts are city-wide at EVENT grain, not this asset's own reports.</p>`;
  } catch (e) { return `<p class="note">no per-asset file cut for this one (the prototype
    ships 40 of 7,955).</p>`; }
}
$("card-x").onclick = () => $("card").classList.remove("on");

map.on("click", "hist", e => { const p = e.features[0].properties;
  openCard(p.asset_id, `${label(p)} - ${p.n_events} flood events`); });
map.on("click", "fn", e => { const p = e.features[0].properties;
  if (VAR === "C") return;
  $("card").classList.add("on");
  $("card-body").innerHTML = `<h3>${p.name}</h3><p class="note">FloodNet ${p.deployment_id}
    &middot; ${p.state} &middot; ${p.age_min} min old<br>${p.depth_mm} mm depth,
    ${p.samples} samples${p.label ? "<br>" + p.label : ""}</p>`; });
map.on("click", "mta", e => { const p = e.features[0].properties;
  if (VAR === "C") return;
  $("card").classList.add("on");
  $("card-body").innerHTML = `<h3>${p.name}</h3><p class="note">water on the tracks -
    incident ${p.event_id}, ${p.chip_state}, ${Math.round(p.age_min)} min<br>
    complex ${p.complex_id}</p>`; });
["hist", "fn", "mta"].forEach(id => {
  map.on("mouseenter", id, () => map.getCanvas().style.cursor = "pointer");
  map.on("mouseleave", id, () => map.getCanvas().style.cursor = "");
});

// C: hover a ledger row to locate it, click to expand in place
$("ledger").addEventListener("mouseover", e => {
  const r = e.target.closest(".led"); if (!r || !r.dataset.lon) return;
  map.getSource("locate").setData({ type: "Feature", geometry: { type: "Point",
    coordinates: [+r.dataset.lon, +r.dataset.lat] }, properties: {} });
});
$("ledger").addEventListener("mouseleave", () =>
  map.getSource("locate").setData({ type: "FeatureCollection", features: [] }));
$("ledger").addEventListener("click", async e => {
  const r = e.target.closest(".led"); if (!r) return;
  const open = r.getAttribute("aria-expanded") === "true";
  r.setAttribute("aria-expanded", String(!open));
  const slot = r.querySelector("[data-hist]");
  if (!open && slot && r.dataset.asset && !slot.dataset.done) {
    slot.dataset.done = "1"; slot.outerHTML = await historyHTML(r.dataset.asset);
  }
});

// ---------------------------------------------------------------------- the switcher
const go = (k, v) => { const u = new URLSearchParams(location.search); u.set(k, v);
  history.replaceState(null, "", "?" + u); };
const step = (d) => { VAR = "ABC"[("ABC".indexOf(VAR) + d + 3) % 3];
  go("variant", VAR); vis(); render(); };
$("prev").onclick = () => step(-1);
$("next").onclick = () => step(1);
$("gate").onclick = () => { GATE_OPEN = !GATE_OPEN; go("gate", GATE_OPEN ? "open" : "closed");
  LAYERS.filter(l => l.gated).forEach(l => { if (!GATE_OPEN) on[l.id] = false; });
  vis(); render(); };
addEventListener("keydown", e => { if (/^(INPUT|TEXTAREA)$/.test(e.target.tagName)) return;
  if (e.key === "ArrowLeft") step(-1); if (e.key === "ArrowRight") step(1); });

// -------------------------------------------------------------------------- first paint
map.on("load", async () => {
  await fill("zones");
  await fill("cells");
  map.setLayoutProperty("cells", "visibility", "visible");
  map.setLayoutProperty("cells-line", "visibility", "visible");
  render();
});
render();
new ResizeObserver(() => map.resize()).observe($("map"));
