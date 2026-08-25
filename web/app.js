"use strict";
/* raincheck serving page (ticket 13 / spec L; frontend 05 grew it into the seven-layer map).
 *
 * Reads three files written by `make export` and nothing else. The paint rule that makes
 * the page honest is ["!", ["has", p]] -> grey: the pure-SQL writer guarantees an
 * unpublishable property is an ABSENT KEY, so `has` is false and the Cell paints grey.
 * (A GDAL-written null would make `has` true and `interpolate` would error on it.)
 * One setPaintProperty per layer/hour switch, one fixed ramp - never a per-view rescale,
 * which would make two storms' colours mean different things.
 *
 * Ticket 14 owns the #live panel and the `live` source/layer stubbed at the bottom.
 *
 * frontend 05 (spec .scratch/frontend/spec.md, decisions on frontend 01/02) turned the page
 * into ONE surface with seven independently toggled layers. Four rules from those tickets
 * are structural here rather than remembered:
 *
 *  1. DECLARE AT BOOT. All twelve map layers below are declared up front with an empty
 *     FeatureCollection and visibility:"none" - never a lazy addSource/addLayer. A lazily
 *     added layer lands on TOP of the order, so with everything lazy the stacking would
 *     depend on click order, and a `beforeId` naming a not-yet-added layer THROWS (the
 *     vendored 5.9.0 bundle carries the literal `Cannot add layer ... before non-existing`).
 *  2. promoteId is OFF EVERYWHERE. Asset ids are hex strings (`cell:882a100001fffff`) and
 *     vehicle_id is "MTA NYCT_1234"; MapLibre 5.9.0 SILENTLY drops a GeoJSON source whose
 *     promoted id is not integer-like (measured: zero features, no error event).
 *  3. AGE COMES FROM THE HTTP HEADERS, per SOURCE: <origin Date> - <Last-Modified>, both
 *     off the response the page already made, both on the ORIGIN's clock, so a browser
 *     clock cannot fake freshness. No payload gains an `as_of_utc` stamp (that would break
 *     export's byte-identity test), and no source shows a verdict it has no budget for.
 *  4. THE CELL FILL IS ONE EXCLUSIVE CHANNEL. The delay layer and flood 17's impact overlay
 *     are the same quantity (a Speed ratio) over the same ~1,200 Cells at two time-scales,
 *     so they share one frozen ramp and one channel, offered as a radio. Two ramps on one
 *     geography is structurally impossible, not merely discouraged.
 */

// Fixed ramps. Ratio: diverging around 1.0 (red slower, blue faster), 0.5 .. 1.2 always.
const RATIO_STOPS = [[0.5, "#7f0000"], [0.65, "#d7301f"], [0.8, "#fc8d59"], [0.9, "#fdd49e"],
                     [1.0, "#f7f7f7"], [1.1, "#c7dcef"], [1.2, "#6baed6"]];
// Dry Speed level, m/s: sequential, a different scale for a different quantity.
const SPEED_STOPS = [[2, "#0d1b2a"], [3.5, "#1b4965"], [5, "#3d7ea6"], [6.5, "#7fb3d5"], [8, "#cfe6f4"]];
const GREY = "#3a4049";
// live dots: bright while the pipeline is writing, dimmed the moment it is not (ticket 14)
const LIVE_FRESH = "#b0bec5", LIVE_STALE = "#5d666f";

// frontend 02 D2: four new hues, none on either arm of the diverging ramp above, which is
// left byte-untouched. A dry/stale FloodNet sensor is a HOLLOW RING rather than a fifth
// grey - at 2.6 px a dry sensor, a dimmed vehicle and the "no publishable value" Cell fill
// were three meanings on one #3a4049, which is one too many.
const WATER = "#35d6c2";    // a FloodNet sensor reporting water NOW
const ALERT = "#ffc447";    // an MTA station with water on the tracks (the page's .warn family)
const HIST = "#8f7bd6";     // a stop or Cell with a flood record: history, not an alarm
const GATED_HUE = "#d2a24c";    // a gated layer's chip: dark, never absent

// Ticket 14's staleness cuts, kept a TABLE and never a formula (a "2x cadence" rule would
// silently retune the deliberately chosen bronze value from 900 s to 1200). Hoisted above
// LAYERS because the live sources' budget IS this number - one source of truth.
const STALE_AFTER_S = { live: 120, bronze: 900 };   // Bronze flushes in 10-min parts
const DELAY_CUT_S = 300;   // 06's Delay cutoff, borrowed for an agency-computed quantity

/* THE MTA GATE CUTS BY LINEAGE, and it has TWO SIDES (frontend 01 D3). Withholding the
 * vehicles must never withhold the FloodNet tier, and opening the vehicles must never
 * open MTA-derived ALERT rows - so the page keys each layer on its own gate side rather
 * than on one global switch. Both sides are shut by the same deploy-time constant today,
 * `raincheck.publish.LIVE_TERMS_VERIFIED` (None = not verified, so nothing MTA-derived is
 * published); a test cross-checks these two booleans against it. Ticket 08 lights a side
 * by flipping ONE of these, with no re-plumbing.
 */
const GATE = {
  "mta-vehicles": false,   // GTFS-RT vehicle positions -> the live fleet, flood 17's bus overlay
  "mta-alerts": false,     // archive/subway_alerts -> the MTA flood tier's alert rows
};

/* The seven layers, their SOURCES and their budgets. A layer takes the worst of its
 * sources; the panel shows the sources, because a layer's several feeds publish on
 * different cadences and only some have a budget frozen anywhere in the repo. Of the nine
 * sources here exactly THREE do: STALE_AFTER_S.live (120 s) for the live pair and
 * flood_truth.MAX_AGE_MIN (10 min) for FloodNet. The other six carry `budget: null`, which
 * renders an AGE with no verdict rather than a guessed FRESH. That gap is a finding, not
 * an oversight, and flood 15 / flood 17 / notify 05 owe the constants that close it.
 *
 * `draw: null` means the payload's writer has not shipped: the layer, its toggle, its hues
 * and its freshness rows are all declared here, and the owing ticket lands the
 * payload -> feature mapping. Rendering truthfully with layers dark is the design
 * requirement, not a degraded mode.
 */
const LAYERS = [
  { id: "zones", name: "Ground: taxi zones", gate: null, fill: false, open: true,
    map: ["zones-fill", "zones-line"], owed: null,
    srcs: [{ k: "files/zones.geojson", url: "files/zones.geojson", budget: null }],
    draw: ([z]) => { if (z) map.getSource("zones").setData(z); } },

  { id: "cells", name: "Delay cells", gate: null, fill: true, open: true,
    map: ["cells", "cells-line"], owed: null,
    srcs: [{ k: "files/cells.geojson", url: "files/cells.geojson", budget: null },
           { k: "files/headline.json", url: "files/headline.json", budget: null }],
    draw: ([c, h]) => drawCells(c, h) },

  // its toggle is #livetoggle in the Live panel, which owns the 30 s interval and the
  // vp_age_s composite; `draw` is null because liveTick has to read meta BEFORE the fleet.
  { id: "live", point: true, name: "Live fleet", gate: "mta-vehicles", fill: false, open: false,
    map: ["live"], owed: null, toggle: "livetoggle",
    srcs: [{ k: "files/live.geojson", url: "files/live.geojson",
             budget: STALE_AFTER_S.live, inner: "vp_age_s" },
           { k: "files/meta.json", url: "files/meta.json", budget: STALE_AFTER_S.live }],
    draw: null },

  { id: "fn", point: true, name: "Flood tier: FloodNet", gate: null, fill: false, open: false,
    map: ["fn"], owed: "flood 15",
    srcs: [{ k: "files/flood.json", url: "files/flood.json", budget: 600 }],
    draw: null },

  { id: "mta", point: true, name: "Flood tier: MTA alerts", gate: "mta-alerts", fill: false, open: false,
    map: ["mta"], owed: "flood 15",
    srcs: [{ k: "files/flood-mta.json", url: "files/flood-mta.json", budget: null }],
    draw: null },

  { id: "impact", name: "Impact overlay: bus", gate: "mta-vehicles", fill: true, open: false,
    map: ["impact-fill", "impact-line"], owed: "flood 17",
    srcs: [{ k: "files/impact.json", url: "files/impact.json", budget: null }],
    draw: null },

  { id: "hist", point: true, name: "Flood history markers", gate: null, fill: false, open: false,
    map: ["hist"], owed: "notify 05",
    srcs: [{ k: "files/history/manifest.geojson", url: "files/history/manifest.geojson",
             budget: null }],
    draw: ([m]) => { if (m) map.getSource("hist").setData(m); } },
];
const L = (id) => LAYERS.find(x => x.id === id);
const shut = (lyr) => Boolean(lyr.gate) && !GATE[lyr.gate];

const $ = (id) => document.getElementById(id);
const fmt = (v, d = 2) => (v === undefined || v === null ? "—" : v.toFixed(d));

let head = null;         // headline.json
let cellKeys = new Set();  // property keys present in cells.geojson
let views = [];
let view = null;         // the active view object
let hourKey = null;      // active storm-hour key (MMDDHH) or null
let styled = false;      // MapLibre has parsed the style: before that every layer call throws

// frontend 02 D7: the 60vh map strip carries about two layers legibly at 375 px, so a small
// screen OPENS with the Cell fill on and every point layer off and the reader adds them one
// at a time. The panel set itself does not collapse - it was measured at 375 px and nothing
// overlaps. The rule lives here so a later slice that defaults a point layer on cannot
// quietly break the phone.
const SMALL = window.matchMedia("(max-width: 900px)").matches;
const on = {};
LAYERS.forEach(l => { on[l.id] = l.open && !(SMALL && l.point); });

/* ------------------------------------------------------------------ declare at boot
 * Twelve layers, the order frozen by frontend 02 D3: ambient at the bottom, urgent on top.
 * Every source is an EMPTY FeatureCollection here and gets its data from a fetch the page
 * makes itself - which is also what makes the per-source age readable, since the age comes
 * off that response's own headers. No promoteId anywhere (rule 2 at the top of this file).
 */
const empty = () => ({ type: "geojson", data: { type: "FeatureCollection", features: [] } });
const map = new maplibregl.Map({
  container: "map", center: [-73.93, 40.72], zoom: 10.1, attributionControl: false,
  style: {
    version: 8,
    sources: { zones: empty(), cells: empty(), impact: empty(), locate: empty(),
               live: empty(), hist: empty(), fn: empty(), mta: empty() },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": "#0b0d10" } },
      { id: "zones-fill", type: "fill", source: "zones", layout: { visibility: "none" },
        paint: { "fill-color": "#141920" } },
      { id: "cells", type: "fill", source: "cells", layout: { visibility: "none" },
        paint: { "fill-color": GREY, "fill-opacity": 0.86 } },
      // the impact overlay shares the Cell fill channel and the frozen ramp above; it gets
      // no ramp of its own and can never be lit at the same time as `cells` (frontend 02 D1)
      { id: "impact-fill", type: "fill", source: "impact", layout: { visibility: "none" },
        paint: { "fill-color": GREY, "fill-opacity": 0.86 } },
      { id: "cells-line", type: "line", source: "cells", layout: { visibility: "none" },
        paint: { "line-color": "#0b0d10", "line-width": 0.4 } },
      { id: "impact-line", type: "line", source: "impact", layout: { visibility: "none" },
        paint: { "line-color": "#0b0d10", "line-width": 0.4 } },
      { id: "zones-line", type: "line", source: "zones", layout: { visibility: "none" },
        paint: { "line-color": "#39424f", "line-width": 0.8 } },
      // ticket 07's hover-locate ring: declared here so it exists in the right place in the
      // order, empty until something locates an asset in it
      { id: "locate", type: "circle", source: "locate", layout: { visibility: "none" },
        paint: { "circle-radius": 13, "circle-color": "rgba(0,0,0,0)",
                 "circle-stroke-color": "#8ecbff", "circle-stroke-width": 2 } },
      { id: "live", type: "circle", source: "live", layout: { visibility: "none" },
        paint: { "circle-radius": 2.6, "circle-color": LIVE_FRESH, "circle-opacity": 0.9 } },
      { id: "hist", type: "circle", source: "hist", layout: { visibility: "none" },
        paint: { "circle-color": HIST, "circle-opacity": 0.5,
          "circle-radius": ["interpolate", ["linear"], ["get", "n_events"], 1, 1.6, 12, 4.6] } },
      // the hollow ring: a sensor reporting water is a filled aqua disc, a dry or stale one
      // is a STROKE with no fill, so "sensor present, no water" reads as a different MARK
      { id: "fn", type: "circle", source: "fn", layout: { visibility: "none" },
        paint: { "circle-color": ["case", ["get", "display"], WATER, "rgba(0,0,0,0)"],
                 "circle-radius": ["case", ["get", "display"], 6, 3.4],
                 "circle-stroke-color": ["case", ["get", "display"], "#0b0d10", WATER],
                 "circle-stroke-width": 1.2 } },
      // an "affected station" is a dot on the COMPLEX (frontend 02 D4): the flood_truth chip
      // is per-incident and spans one or more complexes, so the chip is what the card shows
      { id: "mta", type: "circle", source: "mta", layout: { visibility: "none" },
        paint: { "circle-color": ALERT, "circle-radius": 7, "circle-opacity": 0.92,
                 "circle-stroke-color": "#0b0d10", "circle-stroke-width": 1.5 } },
    ],
  },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution:
  "MTA Bus Time GTFS-RT; nycbuspositions archive; NOAA AORC; NYC TLC taxi zones" }));

/* --------------------------------------------------------- age, straight off the headers
 * frontend 01 D2. `age = <origin Date> - <Last-Modified>`, both taken from the response the
 * page already made. Rejected alternative: an `as_of_utc` in every payload - it breaks
 * test_export.py's byte-identity invariant and notify 05's re-export requirement, and it
 * dates the WRITE, not the newest input, so a nightly rebuild over week-old Gold would
 * paint FRESH. Both headers come from the ORIGIN, so a browser clock running an hour behind
 * cannot clamp an age to 0, and a CDN serving a cached copy returns the ORIGINAL
 * Last-Modified, which errs stale - the safe direction.
 *
 * A missing file is NOT an empty one: a 404 records a reason and never an age, because an
 * absent payload and an empty FeatureCollection must not both paint an empty map under a
 * fresh clock.
 */
const ages = {};    // "<layer id>/<source key>" -> age in seconds, or null
const whys = {};    // "<layer id>/<source key>" -> why there is no age

async function grab(lyrId, s) {
  const key = lyrId + "/" + s.k;
  delete whys[key];
  ages[key] = null;
  try {
    const res = await fetch(s.url, { cache: "no-store" });
    if (!res.ok) {
      whys[key] = res.status === 404 ? "not published on this host" : `HTTP ${res.status}`;
      return null;
    }
    const d = Date.parse(res.headers.get("Date")), m = Date.parse(res.headers.get("Last-Modified"));
    if (Number.isNaN(d) || Number.isNaN(m)) whys[key] = "no age from the response headers";
    else ages[key] = Math.max(0, (d - m) / 1000);
    return await res.json();
  } catch (err) {
    whys[key] = "fetch failed";
    return null;
  }
}

async function load(lyrId) {
  const lyr = L(lyrId);
  const bodies = [];
  for (const s of lyr.srcs) bodies.push(await grab(lyrId, s));
  if (lyr.draw) lyr.draw(bodies);
  return bodies;
}

function forget(lyrId) {
  L(lyrId).srcs.forEach(s => { delete ages[lyrId + "/" + s.k]; delete whys[lyrId + "/" + s.k]; });
}

const fmtAge = (s) => s === null || s === undefined ? "age unknown"
  : s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min`
  : s < 172800 ? `${Math.round(s / 3600)} h` : `${Math.round(s / 86400)} d`;

/* FRESH / STALE(+reason) / OFF / GATED / AGE - the whole vocabulary, one row per SOURCE.
 * Freshness is NOT verdict: flood 15's tier states (INSUFFICIENT_DATA, HOLES, the winter
 * gate, a version-skew refusal) are the flood layer's own rendered vocabulary and stay
 * flood 15's. `ERROR` is not a state either - it is a reason string on a STALE row.
 * The order of these five branches is the contract:
 *   GATED  the layer's gate side is shut: dark, explained, never absent
 *   OFF    nothing is being fetched, so there is nothing to be fresh about
 *   STALE  we have no age at all (missing file, missing headers) - stale, never fresh
 *   AGE    age known, no budget frozen anywhere in the repo -> report it, judge nothing
 *   FRESH / STALE  compared against the frozen budget
 */
function srcState(lyr, s) {
  const key = lyr.id + "/" + s.k;
  let age = ages[key];
  if (typeof age === "number" && s.inner && liveMeta && typeof liveMeta[s.inner] === "number")
    age += liveMeta[s.inner];       // the live pair's composite: file age + DATA age
  if (shut(lyr)) return { s: "GATED", why: "the MTA redistribution terms are not verified" };
  if (!on[lyr.id]) return { s: "OFF", why: "nothing is being fetched" };
  if (age === null || age === undefined)
    return { s: "STALE", why: whys[key] || "no age from the response headers" };
  if (s.budget === null) return { s: "AGE", why: "no budget frozen for this source", age };
  return age <= s.budget ? { s: "FRESH", age }
                         : { s: "STALE", why: `over the ${s.budget} s budget`, age };
}

// a layer is only as fresh as its worst source
const worst = (lyr) => {
  const seen = lyr.srcs.map(s => srcState(lyr, s).s);
  return ["GATED", "STALE", "OFF", "AGE", "FRESH"].find(k => seen.includes(k));
};

/* ------------------------------------------------------------------------ the layer panel
 * One row per layer, its own freshness rows underneath it. The Cell FILL rows are RADIOS in
 * one group so two ramps on one geography cannot even be asked for; everything else is a
 * checkbox. A gated row is DARK, not missing: the box is disabled and the reason is printed,
 * so absence is explained rather than mysterious.
 */
const chipHTML = (state) => `<span class="st st-${state}">${state}</span>`;

function srcRows(lyr) {
  return lyr.srcs.map(s => {
    const st = srcState(lyr, s);
    const age = st.age === undefined ? "" : fmtAge(st.age) + " ";
    return `<div class="src"><b>${s.k}</b><span>${age}${chipHTML(st.s)}</span></div>` +
      (st.why ? `<div class="src why"><span>${st.why}</span></div>` : "");
  }).join("");
}

function rowHTML(lyr) {
  const dark = shut(lyr);
  const kind = lyr.fill ? "radio" : "checkbox";
  const owed = lyr.owed && !dark
    ? `<p class="note">Declared and dark: ${lyr.owed} lands this payload.</p>` : "";
  const gate = dark
    ? `<p class="note">Dark: publishing anything on this gate side needs the MTA
       redistribution terms verified. The row stays, so the page never pretends the layer
       does not exist.</p>` : "";
  return `<div class="lyr${dark ? " gated" : ""}">
    <label><input type="${kind}" ${lyr.fill ? 'name="cellfill"' : ""} data-l="${lyr.id}"
      ${on[lyr.id] ? "checked" : ""} ${dark || !styled ? "disabled" : ""}>
      <span class="nm">${lyr.name}</span>${chipHTML(worst(lyr))}</label>
    ${srcRows(lyr)}${gate}${owed}</div>`;
}

/* Rebuilding the rows destroys the control the reader just activated and focus falls to
 * <body> - a keyboard user would tab through the map and every other row again on each
 * toggle. This is the same restore the hour buttons use in setHour() below, and it is the
 * whole reason that mechanism exists. */
function renderLayers() {
  const a = document.activeElement;
  const keep = a && a.dataset ? a.dataset.l : undefined;
  $("layers-fill").innerHTML = LAYERS.filter(l => l.fill).map(rowHTML).join("");
  $("layers-pts").innerHTML =
    LAYERS.filter(l => !l.fill && !l.toggle).map(rowHTML).join("");
  // the live fleet's row is the Live panel: it owns the 30 s interval and its own readout,
  // and #livetoggle is its checkbox. Only its freshness rows are rendered here.
  const live = L("live");
  $("src-live").innerHTML = srcRows(live) + (shut(live)
    ? `<p class="note">Dark: the vehicle side of the MTA gate is shut, so the fleet is not
       published on this host. The toggle stays: locally, <code>make live-export</code>
       writes the two files and the panel reads them.</p>` : "");
  $("live-chip").innerHTML = chipHTML(worst(live));
  if (keep !== undefined) {
    const b = document.querySelector(`#layers [data-l="${keep}"]`);
    if (b) b.focus();
  }
}

function applyVisibility() {
  if (!styled) return;
  for (const lyr of LAYERS) {
    const lit = on[lyr.id] && !shut(lyr) ? "visible" : "none";
    lyr.map.forEach(id => map.setLayoutProperty(id, "visibility", lit));
  }
}

async function toggle(id, want) {
  const lyr = L(id);
  if (shut(lyr)) return;                 // a gated layer never fetches anything
  on[id] = want;
  // the exclusive fill channel, enforced in the state and not only in the radio group's
  // markup: a second fill can never be HELD on, however the toggle was reached
  if (want && lyr.fill) for (const o of LAYERS) if (o.fill && o.id !== id) on[o.id] = false;
  if (want) await load(id); else forget(id);
  applyVisibility();
  renderLayers();
}

// delegated, because the rows are rebuilt: #layers itself is the stable element
$("layers").addEventListener("change", e => {
  const id = e.target.dataset && e.target.dataset.l;
  if (id) toggle(id, e.target.checked);
});

// ---------------------------------------------------------------- paint and legend
function colorExpr(prop, stops) {
  const interp = ["interpolate", ["linear"], ["get", prop]];
  stops.forEach(([v, c]) => interp.push(v, c));
  return ["case", ["!", ["has", prop]], GREY, interp];   // absent -> grey, per spec L
}

const activeProp = () => (view.hours ? "r" + hourKey : view.prop);

function paint() {
  const s = view.kind === "speed" ? SPEED_STOPS : RATIO_STOPS;
  map.setPaintProperty("cells", "fill-color", colorExpr(activeProp(), s));
  $("swatches").innerHTML = s.map(([, c]) => `<span style="background:${c}"></span>`).join("");
  $("legend-title").textContent = view.kind === "speed"
    ? "Dry baseline Speed, m/s" : "Speed ratio, wet over dry";
  $("tick-lo").textContent = s[0][0] + (view.kind === "speed" ? " m/s" : " slower");
  $("tick-mid").textContent = view.kind === "speed" ? "" : "1.0 no change";
  $("tick-hi").textContent = s[s.length - 1][0] + (view.kind === "speed" ? " m/s" : " faster");
  const row = currentRow();
  $("legend-estimand").textContent = view.kind === "speed"
    ? "space-mean chord Speed over the window's dry Cell-hours (dry = mm_1h < 0.1, mm_1h_prev < 0.1, mm_6h < 0.5), rule set R2"
    : (row ? row.median_cell_estimand : "");
}

// ---------------------------------------------------------------- headline rendering
const currentRow = () => head.rows.find(r =>
  r.layer === view.layer && (view.hours ? r.key === hourKey : true));

function renderHeadline() {
  const r = currentRow();
  if (!r) { $("headline").innerHTML = ""; return; }
  const bandLo = Math.min(r.band[0], r.band[1]), bandHi = Math.max(r.band[0], r.band[1]);
  // spec L requires the panel to state that the 2023-09-29 band reaches ~1.0. That is a
  // property of the STORM, not of the selected Hour: band() collapses to a point whenever
  // both arms sit in one chord class, so an hour-local test would hide the statement on
  // most hours of exactly the storm it is required for. It is therefore taken over the
  // Hours that MEASURE a slowdown - an Hour whose measured ratio is already above 1.0 has
  // a band reaching 1.0 trivially and says nothing about chord bias.
  const slow = head.rows.filter(x => x.layer === r.layer && x.value < 0.98);
  const layerHi = slow.length ? Math.max(...slow.map(x => Math.max(x.band[0], x.band[1]))) : 0;
  const bandNear1 = layerHi >= 0.98 && r.value < 1.0;
  const parts = [];

  parts.push(`<div class="row">
    <div class="big">${fmt(bandLo)}&ndash;${fmt(bandHi)}</div>
    <div class="band">citywide Speed ratio (chord band), 95% CI [${fmt(r.lo, 3)}, ${fmt(r.hi, 3)}]
      &middot; ${r.n_legs.toLocaleString()} Legs</div>
    <p class="note">${r.estimand}</p>
    ${bandNear1 ? `<p class="note warn">Across this layer the chord-corrected band reaches
       ${fmt(layerHi)}: this storm's slowdown is not separable from chord bias.</p>` : ""}</div>`);

  parts.push(`<div class="row">
    <div class="big">${fmt(r.median_cell)}</div>
    <div class="band">median Cell &middot; ${r.n_cells} Cells shown,
      <b>${r.n_cells_hidden} hidden</b></div>
    <p class="note">${r.median_cell_estimand}</p></div>`);

  if (r.value_ex_preschool !== undefined && r.value_ex_preschool !== null) {
    parts.push(`<div class="row">
      <div class="band">${fmt(r.value_ex_preschool, 3)}
        [${fmt(r.lo_ex_preschool, 3)}, ${fmt(r.hi_ex_preschool, 3)}] excluding the pre-school weeks
        &middot; ${r.n_events} wet events, ${r.n_cell_hours.toLocaleString()} wet Cell-hours</div>
      <p class="note">${r.estimand_ex_preschool}</p>
      <p class="note">sensitivity, clustered by service day instead of wet event:
        [${fmt(r.sensitivity_day.lo, 3)}, ${fmt(r.sensitivity_day.hi, 3)}]
        over ${r.sensitivity_day.n_days} days.</p></div>`);
  }
  if (r.mm_1h_citywide_mean !== undefined && r.mm_1h_citywide_mean !== null) {
    parts.push(`<div class="row"><div class="band">${fmt(r.mm_1h_citywide_mean)} mm
      mean rain over the footprint this Hour (AORC, hour-ending)</div></div>`);
  }
  $("headline").innerHTML = parts.join("");
}

// -------------------------------------------------------------------- the curve
// Storm views: that storm's own hour-by-hour trajectory (the rain-lag story lives on the
// storm, not on a window-pooled lag curve). Window views: the pooled lag curves, which
// come out flat - shown because that flatness is the finding.
function renderCurve() {
  const W = 340, H = 96, PADL = 30, PADR = 8, PADT = 10, PADB = 18;
  let series, caption, xs;
  if (view.hours) {
    const rows = head.rows.filter(r => r.layer === view.layer).sort((a, b) => a.key < b.key ? -1 : 1);
    series = [{ name: "hour", pts: rows.map((r, i) => [i, r.value]), color: "#fc8d59" }];
    xs = rows.map(r => r.label.slice(-3));
    caption = `${view.label}: citywide Speed ratio by Hour` +
      (rows.length > view.hourKeys.length ? " (the tail beyond the map layers is the recovery)" : "");
  } else {
    const pick = (rain) => head.lag.filter(l => l.window === view.layer && l.rain === rain)
      .sort((a, b) => a.lag_h - b.lag_h);
    const all = pick("all"), heavy = pick("heavy");
    series = [{ name: "all", pts: all.map(l => [l.lag_h, l.ratio]), color: "#6baed6" },
              { name: "heavy", pts: heavy.map(l => [l.lag_h, l.ratio]), color: "#fc8d59" }];
    xs = all.map(l => String(l.lag_h));
    caption = `${view.label}: Speed ratio by Hours since the Cell's last wet Hour ` +
      `(blue: any rain ≥ 1 mm; orange: ≥ 10 mm). No interval is published for this curve - ` +
      `read its shape, not any single point.`;
  }
  const vals = series.flatMap(s => s.pts.map(p => p[1]));
  // fit the domain to the data (padded, always containing 1.0) rather than clamping into a
  // fixed band: a clamped point is drawn at the edge and reads as a real value
  const lo = Math.min(0.9, ...vals) - 0.03, hi = Math.max(1.05, ...vals) + 0.03;
  const n = Math.max(1, xs.length - 1);
  const X = (i) => PADL + (i / n) * (W - PADL - PADR);
  const Y = (v) => PADT + (1 - (v - lo) / (hi - lo)) * (H - PADT - PADB);
  const bits = [`<line x1="${PADL}" x2="${W - PADR}" y1="${Y(1)}" y2="${Y(1)}"
      stroke="#5a6472" stroke-dasharray="3 3"/>`,
    `<text x="2" y="${Y(1) + 4}" fill="#9aa4b2" font-size="10">1.0</text>`,
    `<text x="2" y="${Y(lo) + 4}" fill="#9aa4b2" font-size="10">${lo.toFixed(2)}</text>`];
  series.forEach(s => {
    if (!s.pts.length) return;
    const d = s.pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    bits.push(`<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2"/>`);
    s.pts.forEach(p => bits.push(
      `<circle cx="${X(p[0]).toFixed(1)}" cy="${Y(p[1]).toFixed(1)}" r="2.2" fill="${s.color}"/>`));
  });
  if (view.hours) {
    const idx = head.rows.filter(r => r.layer === view.layer)
      .sort((a, b) => a.key < b.key ? -1 : 1).findIndex(r => r.key === hourKey);
    if (idx >= 0) bits.push(`<line x1="${X(idx)}" x2="${X(idx)}" y1="${PADT}" y2="${H - PADB}"
      stroke="#8ecbff" stroke-width="1"/>`);
  }
  xs.forEach((t, i) => { if (xs.length < 14 || i % 2 === 0)
    bits.push(`<text x="${X(i)}" y="${H - 5}" fill="#9aa4b2" font-size="9" text-anchor="middle">${t}</text>`); });
  $("curve-svg").innerHTML = bits.join("");
  $("curve-cap").textContent = caption;
}

// ---------------------------------------------------------------- view switching
function setHour(k) {
  const hadFocus = document.activeElement && document.activeElement.dataset
    && document.activeElement.dataset.h !== undefined;
  hourKey = k;
  drawHourButtons();
  // drawHourButtons() rebuilds #hours, so the button the user just activated is gone and
  // focus falls to <body>; a keyboard user would tab through the map and every layer
  // button again for each hour step. Put focus back where they left it.
  if (hadFocus) {
    const b = document.querySelector(`#hours button[data-h="${k}"]`);
    if (b) b.focus();
  }
  paint(); renderHeadline(); renderCurve();
}

function drawHourButtons() {
  if (!view.hours) { $("hours").innerHTML = ""; return; }
  $("hours").innerHTML = view.hourKeys.map(k => {
    const row = head.rows.find(r => r.layer === view.layer && r.key === k);
    return `<button type="button" data-h="${k}" aria-pressed="${k === hourKey}">${row.label.slice(-3)}</button>`;
  }).join("");
}

function setView(id) {
  view = views.find(v => v.id === id);
  document.querySelectorAll("#views button").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.v === id)));
  hourKey = view.hours ? (view.hourKeys.includes(hourKey) ? hourKey : view.defaultHour) : null;
  drawHourButtons(); paint(); renderHeadline(); renderCurve();
}

function buildViews() {
  const storms = [["ida", "Ida 2021-09-02"], ["f23", "2023-09-29 flood"]];
  views = [];
  for (const [layer, label] of storms) {
    const keys = head.rows.filter(r => r.layer === layer && r.on_map).map(r => r.key).sort();
    if (!keys.length) continue;
    const worst = keys.reduce((a, k) =>   // open on the storm's own worst Hour
      head.rows.find(r => r.key === k).value < head.rows.find(r => r.key === a).value ? k : a);
    views.push({ id: layer, layer, label, kind: "ratio", hours: true,
                 hourKeys: keys, defaultHour: worst });
  }
  for (const w of ["w1", "w2"]) {
    if (head.rows.some(r => r.layer === w))
      views.push({ id: w, layer: w, label: `${w.toUpperCase()} wet vs dry`, kind: "ratio",
                   hours: false, prop: `${w}_ratio` });
    // the dry baseline is a Speed LEVEL straight off cells.geojson, so it is offered
    // whenever the property exists - it does not depend on the wet aggregation producing a row
    if (cellKeys.has(`${w}_dry`))
      views.push({ id: w + "d", layer: w, label: `${w.toUpperCase()} dry baseline`,
                   kind: "speed", hours: false, prop: `${w}_dry` });
  }
  $("views").innerHTML = views.map(v =>
    `<button type="button" data-v="${v.id}" aria-pressed="false">${v.label}</button>`).join("");
}

$("views").addEventListener("click", e => { if (e.target.dataset.v) setView(e.target.dataset.v); });
$("hours").addEventListener("click", e => { if (e.target.dataset.h) setHour(e.target.dataset.h); });

// ------------------------------------------------------------------------ tooltip
// Zone name comes from the Cell's own exported property (04's centroid rule), never from a
// hover-time hit test against the zones layer - a hit test is not the centroid rule.
const tip = $("tip");
function showTip(e) {
  const p = e.features[0].properties;
  const where = p.zone_name ? `${p.zone_name}, ${p.borough}` : "outside a taxi zone";
  let body;
  if (view.kind === "speed") {
    body = p[view.prop] !== undefined
      ? `dry Speed ${fmt(p[view.prop])} m/s over ${p[view.layer + "_ndry"]} dry Cell-hours`
      : "no dry baseline for this Cell";
  } else if (view.hours) {
    const k = hourKey;
    body = p["r" + k] !== undefined
      ? `ratio ${fmt(p["r" + k])} [${fmt(p["lo" + k], 3)}, ${fmt(p["hi" + k], 3)}]<br>` +
        `${p["n" + k]} Legs this Hour, ${p["d" + k]} dry Hours in the baseline bin`
      : "interval too wide to publish for this Hour";
    if (p["mm" + k] !== undefined) body += `<br>rain ${fmt(p["mm" + k])} mm this Hour (AORC)`;
    if (p["lag" + k] !== undefined) body += `, ${p["lag" + k]} h since this Cell's last wet Hour`;
  } else {
    const w = view.layer;
    body = p[w + "_ratio"] !== undefined
      ? `ratio ${fmt(p[w + "_ratio"])} [${fmt(p[w + "_lo"], 3)}, ${fmt(p[w + "_hi"], 3)}]<br>` +
        `${p[w + "_nwet"]} wet Cell-hours over ${p[w + "_nev"]} wet events`
      : "interval too wide to publish for this window";
    if (p[w + "_dry"] !== undefined) body += `<br>dry baseline ${fmt(p[w + "_dry"])} m/s`;
  }
  tip.style.display = "block";
  tip.style.left = Math.min(e.point.x + 14, window.innerWidth - 280) + "px";
  tip.style.top = (e.point.y + 14) + "px";
  // `body` is built from literals and rounded numbers, but `where` carries zone_name and
  // borough, which originate in the downloaded TLC shapefile - the one string here that
  // crosses a trust boundary. Set it as text, never as markup.
  tip.innerHTML = `<b></b>Cell ${p.cell}<br>${body}`;
  tip.querySelector("b").textContent = where;
}
map.on("mousemove", "cells", showTip);
map.on("click", "cells", showTip);          // touch
map.on("mouseleave", "cells", () => { tip.style.display = "none"; });

// ------------------------------------------------------------------------- boot
function drawCells(cells, h) {
  if (!cells || !h) {
    $("preview-note").textContent = whys["cells/files/cells.geojson"] === "not published on this host"
      ? "the insight files are not published on this host."
      : "export files missing - run `make export` and reload.";
    return;
  }
  head = h;
  map.getSource("cells").setData(cells);
  cells.features.forEach(f => Object.keys(f.properties).forEach(k => cellKeys.add(k)));
  $("preview-note").textContent = head.preview_note;
  $("note-chord").textContent = head.chord_note;
  $("note-hidden").textContent = head.hidden_note;
  $("note-gate").textContent = head.gate;
  $("prov-files").textContent =
    ` ${cells.features.length} footprint Cells; publish gate: 95% interval width < ${head.gate_width}.`;
  buildViews();
  setView(views[0].id);
}

// `load`, not `styledata`: styledata fires while isStyleLoaded() is still false and every
// setPaintProperty / setLayoutProperty below still throws "Style is not done loading".
map.on("load", async () => {
  styled = true;
  for (const lyr of LAYERS) if (on[lyr.id] && lyr.draw) await load(lyr.id);
  applyVisibility();
  renderLayers();
});

new ResizeObserver(() => map.resize()).observe($("map"));

// #provenance is a CONDITION of publishing (spec sec.9), so it is always mounted - and its
// height is not a constant: it wraps differently with the attribution text and at every
// width. Measure it and drive the two side columns off the measurement. A guessed clearance
// (the old `bottom: 84px`) put the last toggle UNDERNEATH the strip in the prototype, where
// a real click never reached it - caught by a hit test, not by eye.
new ResizeObserver(() => document.documentElement.style.setProperty(
  "--prov", ($("provenance").offsetHeight + 20) + "px")).observe($("provenance"));

/* --------------------------------------------------------------------------------
 * Live panel (ticket 14 / spec L). Reads the two files `make live-export` swaps into
 * files/, every 30 s, and only while the toggle is on.
 *
 * The panel's job is to be honest about age, so STALE is the DEFAULT and freshness has
 * to be proven: a missing meta.json, an unparseable one, an `error`, an exporter-set
 * `stale`, or a missing vp_age_s all read as stale, and only a vp_age_s inside the
 * source's threshold clears it. `setData` runs only when `error` is null - a failed tick
 * leaves live.geojson untouched on purpose, and re-reading it would repaint an old fleet
 * as a new one.
 *
 * frontend 01 D3: a 404 is NOT "the pipeline is not writing". On the public host the
 * vehicle side of the MTA gate is shut and these two files are simply not served, so
 * saying an operator should run `make live-export` would be false in both halves.
 *
 * STALE_AFTER_S and DELAY_CUT_S are hoisted to the top of this file: the live pair's
 * freshness budget in LAYERS is the same number, and a second copy would be a second truth.
 * -------------------------------------------------------------------------------- */
let liveTimer = null, liveFeatures = null, liveMeta = null;

const ago = (s) => (s === null || s === undefined || !Number.isFinite(s)) ? "age unknown"
  : s < 90 ? `${Math.round(s)} s ago` : `${Math.round(s / 60)} min ago`;
const plural = (n, one, many) => `${n ?? "—"} ${n === 1 ? one : many}`;
// meta.error is a DuckDB message carrying a filesystem path; everything else on the panel
// is a number we generated. Escape it so a '<' in a path cannot garble the markup.
const esc = (s) => String(s).replace(/[<&]/g, c => (c === "<" ? "&lt;" : "&amp;"));

// How old meta.json itself is, by OUR clock (cloud 09). `vp_age_s` is a number the
// EXPORTER computed and froze into the file: if the exporter dies - or the publisher
// does, or a CDN keeps serving a cached copy - the page re-fetches the same small
// vp_age_s forever and paints a stopped city as a live one. Dating the file closes that.
// Clock skew errs safe: a browser clock behind the exporter's contributes 0, which is
// exactly the old behaviour, and one ahead only ever reads staler. An unparseable or
// absent stamp is Infinity - stale, never fresh.
function metaAge(m) {
  const t = Date.parse(m.as_of_utc);
  return Number.isNaN(t) ? Infinity : Math.max(0, (Date.now() - t) / 1000);
}

// STALE unless proven otherwise. `vp_age_s` is the exporter's wall-clock age of the
// newest row in the pruned partitions, so it keeps counting up after the stream dies;
// + metaAge keeps it counting up after the EXPORTER dies.
function isStale(m) {
  if (!m || m.error || m.stale) return true;
  const limit = STALE_AFTER_S[m.source] ?? STALE_AFTER_S.live;
  return !(typeof m.vp_age_s === "number" && m.vp_age_s + metaAge(m) <= limit);
}

function renderLive(m) {
  const stale = isStale(m);
  map.setPaintProperty("live", "circle-color", stale ? LIVE_STALE : LIVE_FRESH);
  map.setPaintProperty("live", "circle-opacity", stale ? 0.35 : 0.9);
  $("live").classList.toggle("stale", stale);
  $("live").title = stale ? "STALE: the pipeline is not writing" : "";

  if (!m) {
    $("livemeta").innerHTML = whys["live/files/meta.json"] === "not published on this host"
      ? `<b class="warn">Not published on this host.</b> The vehicle side of the MTA gate is
         shut, so <code>files/meta.json</code> is not served here - this is a designed state,
         not a broken pipeline.`
      : `<b class="warn">STALE: the pipeline is not writing.</b>
      No <code>files/meta.json</code> - run <code>make live-export</code>.`;
    return;
  }
  const p = m.stream_progress;
  const bits = [
    `${plural(m.n_vehicles, "vehicle", "vehicles")} in the last ${m.window_min} min,`,
    `${m.n_in_rain_cells ?? "—"} in Cells at &ge; 1 mm RadarOnly,`,
    `${m.n_with_prediction ?? "—"} with a next-stop Prediction.`,
    `Feed ${ago(m.vp_age_s)} (VP ${m.vp_fetched_at_utc ?? "never"}).`,
    // the exporter's own age, so "STALE" beside a 30 s feed age reads as the one thing it
    // can mean: nobody has written this file since (cloud 09)
    `Exported ${ago(metaAge(m))}.`,
    p ? `Stream batch ${p.batch_id}, ${p.rows} rows, ${ago(p.age_s)}.`
      : "No stream progress file.",
    `source: ${m.source}.`,
  ];
  if (m.error) bits.push(`<span class="warn">export error: ${esc(m.error)}</span>`);
  $("livemeta").innerHTML =
    (stale ? `<b class="warn">STALE: the pipeline is not writing.</b> ` : "") + bits.join(" ");

  // "MTA-reported trip delay > 5 min" - never "late": it is the agency's own number,
  // unvalidated, and 300 s is 06's Delay cutoff borrowed. Gated until it actually arrives.
  $("delaystate").textContent = !m.n_with_trip_delay
    ? "unavailable - no live TU row carries trip_delay_s yet"
    : `${(liveFeatures || []).filter(f => f.properties.trip_delay_s > DELAY_CUT_S).length}` +
      ` of ${m.n_vehicles} over 5 min (agency-computed, unvalidated)`;

  $("rainstate").textContent = m.precip_valid_ts
    ? `valid ${m.precip_valid_ts} (${ago(m.precip_age_s)})`
    : "no live tick yet";
}

async function liveTick() {
  const live = L("live");
  const meta = await grab("live", live.srcs[1]);          // meta.json FIRST: the fleet is
  liveMeta = meta;                                        // only re-read on a clean tick
  if (meta && (meta.error === null || meta.error === undefined)) {
    const fc = await grab("live", live.srcs[0]);
    if (fc) {
      map.getSource("live").setData(fc);
      liveFeatures = fc.features;
    }
  }
  renderLive(meta);
  renderLayers();
}

// The toggle stays disabled until the map is loaded, because every branch below touches
// the `live` layer and setPaintProperty / getSource THROW before it exists - which would
// kill the tick silently and leave the panel on its "off" text under a ticked box
// (measured in a real tab). `load`, not `styledata`: styledata fires while
// isStyleLoaded() is still false and setPaintProperty still throws "Style is not done
// loading". A hidden tab throttles rAF and never fires it, which is why this panel can
// only be checked in a VISIBLE tab - a headless screenshot is misleading.
if (map.loaded()) $("livetoggle").disabled = false;
else map.once("load", () => { $("livetoggle").disabled = false; });

$("livetoggle").addEventListener("change", () => {
  const lit = $("livetoggle").checked;
  on.live = lit;
  map.setLayoutProperty("live", "visibility", lit ? "visible" : "none");
  clearInterval(liveTimer);
  liveTimer = null;
  if (lit) {
    liveTick();
    liveTimer = setInterval(liveTick, 30000);
  } else {
    forget("live");
    liveMeta = null;
    $("live").classList.remove("stale");
    $("live").title = "";
    $("livemeta").textContent = "off - nothing is being fetched.";
    renderLayers();
  }
});

// first paint of the panel itself: the rows exist before the map is loaded, with
// every control disabled, so the reader sees the layer set rather than a blank column.
renderLayers();
