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
 * STALE_AFTER_S and DELAY_CUT_S live in layers.js: the live pair's freshness budget in
 * LAYERS is the same number, and a second copy would be a second truth.
 *
 * The #livetoggle checkbox is wired in app.js (every DOM wiring is), which calls
 * toggleLive() at the bottom of this file - `liveTimer` / `liveMeta` are this module's to
 * write, and an imported binding is read-only in the importing module.
 * -------------------------------------------------------------------------------- */
import { $, DELAY_CUT_S, L, LIVE_COLOR, LIVE_STALE, map, on, STALE_AFTER_S } from "./layers.js";
import { ages, forget, grab, load, whys } from "./freshness.js";
import { renderLayers } from "./panel.js";
import { bandCaveats, cellFeatures } from "./insight.js";

// mirrored from raincheck.live_export.RAIN_MM (spec L): the same rain flag bronze exports
// against. tests/test_page.py derives the expected literal from the python constant, so
// the two cannot drift apart silently - never re-typed a second time. Exported so
// insight.js's fleet tip can tell "raining, no published band" from "not raining" off the
// SAME constant rather than a second copy.
export const RAIN_MM = 1.0;

let liveTimer = null, liveFeatures = null;
export let liveMeta = null;

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
  // staleness wins over everything: the stale branch is flat LIVE_STALE regardless of any
  // attached ratio; the fresh branch restores the CASE EXPRESSION, never flat LIVE_FRESH,
  // so a Cell's band keeps colouring the fleet the moment the feed is trusted again.
  map.setPaintProperty("live", "circle-color", stale ? LIVE_STALE : LIVE_COLOR);
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

// cell -> {ratio, lo, hi, win} off the cells FeatureCollection insight.js already fetched
// (cellFeatures(), one fetch, one parse - never a second cells.geojson request). w2 (the
// 2023 window) preferred over w1 (2021) when both are published, matching the panel's own
// view-switching preference order; a Cell with neither carries no band at all.
function cellBands() {
  const m = new Map();
  for (const f of cellFeatures()) {
    const p = f.properties;
    const win = typeof p.w2_ratio === "number" ? "w2"
      : typeof p.w1_ratio === "number" ? "w1" : null;
    if (win) m.set(p.cell, { ratio: p[win + "_ratio"], lo: p[win + "_lo"], hi: p[win + "_hi"], win });
  }
  return m;
}

async function liveTick() {
  const live = L("live");
  const meta = await grab("live", live.srcs[1]);          // meta.json FIRST: the fleet is
  liveMeta = meta;                                        // only re-read on a clean tick
  if (meta && (meta.error === null || meta.error === undefined)) {
    const fc = await grab("live", live.srcs[0]);
    if (fc) {
      // the join is a client-side dict lookup at tick time: attach ratio/lo/hi/win BEFORE
      // setData, and ONLY when all three hold - a Cell present, raining there (the
      // mirrored RAIN_MM), and that Cell publishing a band. Anything else attaches
      // nothing, which is what leaves the mark on its own LIVE_COLOR neutral branch.
      const bands = cellBands();
      let anyRatio = false;
      for (const f of fc.features) {
        const p = f.properties;
        if (p.cell && typeof p.mm_1h === "number" && p.mm_1h >= RAIN_MM) {
          const band = bands.get(p.cell);
          if (band) { Object.assign(p, band); anyRatio = true; }
        }
      }
      map.getSource("live").setData(fc);
      liveFeatures = fc.features;
      // caveats RENDERED, never restated: while any vehicle carries a band, the legend
      // renders headline.json's own citywide estimand (the window preferred above) and
      // its preview-status note, verbatim, through this module's existing note()/esc()
      // path - cells.geojson carries no strings of its own.
      const c = anyRatio ? bandCaveats() : null;
      L("live").legend = c ? note(c.estimand) + note(c.preview_note) : "";
    }
  }
  renderLive(meta);
  renderLayers();
}

/* ============================== frontend 08: the flood tier points and the two impact
 * overlays (flood 15/17's payloads). Every claim string rendered below is READ from the
 * payload - flood 11's display.* strings selected by flood_panel.strings(), the same
 * artifact every notify message reads - never re-worded here, so the panel and a message
 * cannot disagree. Tier words go through strings.tier_labels; no tier is ever spelled in
 * this file and nothing here may print an absent value ("None"/undefined) - an absent
 * member renders NOTHING, never a placeholder. Each draw sets its layer's `legend`
 * (frontend2 03's mechanism: rendered under the row while the layer is lit) and the
 * panel's srcState() row does the freshness verdict off the frozen `budget:` fields.
 */

// a payload string -> one sentence; absent -> nothing at all
const note = (s, cls = "note") => (s === null || s === undefined || s === "")
  ? "" : `<p class="${cls}">${esc(s)}</p>`;
const sentences = (list) => (Array.isArray(list) ? list : []).map(c => note(c)).join("");

/* The DATA-age composite, the live pair's `vp_age_s + metaAge` idiom in the overlay rows.
 * The payload's `staleness.age_min` is the data's age AT WRITE (the writer recomputes it
 * every tick); the header age grab() recorded is the file's age SINCE the write. Their sum
 * is the data's age now, dated at the reader, and it keeps counting after the writer dies
 * - without it a freshly rewritten file over a stale Gold hour would read FRESH. ages{} is
 * grab()'s own registry and load() runs the draw after grab() has set it; this is a
 * property write, not a cross-module binding write. */
function addDataAge(lyrId, body) {
  const lyr = L(lyrId);
  const key = lyrId + "/" + lyr.srcs[0].k;
  if (body && body.staleness && typeof body.staleness.age_min === "number"
      && typeof ages[key] === "number")
    ages[key] += Math.max(0, body.staleness.age_min * 60);
}

/** files/flood.json -> the FloodNet sensor points + the flood panel's own text. */
export function drawFn(f) {
  const lyr = L("fn");
  if (!f) { lyr.legend = ""; return; }
  const fn = f.floodnet || {};
  if (fn.geojson) map.getSource("fn").setData(fn.geojson);
  const s = f.strings || {};
  const read = fn.read || {};
  const parts = [];
  if (typeof read.rendered === "number")
    parts.push(note(`${read.rendered} sensors drawn, ${fn.detected ?? 0} reporting water now.`));
  if (s.panel)
    parts.push(note([s.panel.headline, s.panel.release, s.panel.caveat]
      .filter(Boolean).join(" · ")));
  parts.push(note(s.operating_truth));
  if (f.provisional) parts.push(note(s.tiers_provisional));
  const w = f.window;
  parts.push(w && w.state ? note(`Window ${w.state}${w.anchor ? `, anchor ${w.anchor}` : ""}.`)
                          : note("No Window is open."));
  // a refusal is rendered, never papered over with a last-good number (units is [] then)
  if (f.model_tier && f.model_tier !== "ok")
    parts.push(note(`model tier ${f.model_tier}${f.skew && f.skew.reason ? ": " + f.skew.reason : ""}`, "note warn"));
  if (f.dim && f.dim.dimmed && typeof f.dim.dry_hours === "number")
    parts.push(note(`Dimmed: ${f.dim.dry_hours} dry hours since rain.`));
  if (f.winter && f.winter.suppressed) parts.push(note(f.winter.label || s.winter_label));
  // Units at ELEVATED+ only; the tier word comes from strings.tier_labels, never typed
  // here, and the asset_id prints beside the name (names are not unique at any grain)
  const us = Array.isArray(f.units) ? f.units : [];
  if (us.length) parts.push(note(`${us.length} flagged Units:`));
  for (const u of us.slice(0, 12)) {
    const tier = (s.tier_labels || {})[u.tier];
    parts.push(note([u.name, `(${u.asset_id})`, tier, u.rank !== undefined ? `rank ${u.rank}` : ""]
      .filter(Boolean).join(" ")));
  }
  if (us.length > 12) parts.push(note(`… and ${us.length - 12} more flagged Units not listed.`));
  if (us.some(u => u.kind === "complex")) parts.push(note(s.no_complex_skill_claim));
  const inCells = us.map(u => u.cell).filter(Boolean);
  if (new Set(inCells).size < inCells.length) parts.push(note(s.within_cell));
  // the writer's per-feed verdicts at last write; the file's OWN age is the srcState row
  const st = f.staleness || {};
  if (Object.keys(st).length)
    parts.push(note("Feeds at last write: " + Object.entries(st).map(([k, v]) =>
      `${k} ${v.state}` + (typeof v.age_min === "number" ? ` (${Math.round(v.age_min)} min)` : ""))
      .join(" · ") + "."));
  parts.push(sentences(fn.caveats));
  // flood-build 20's storm-comparison block, IF the payload carries it (frozen shape,
  // 2026-08-26): `display.sentence` has ONE placeholder, {mm_1h}, substituted per Cell
  // from cells[hex].design_storm - present on SCORED Cells only, ONLY while raining
  // there. The panel renders the WETTEST such Cell and says so; the three bound
  // qualifier notes travel with the claim, verbatim. A dry night (block present, zero
  // per-Cell keys) and a pre-fb20 payload (block absent) both render NOTHING.
  const dsB = f.design_storm;
  if (dsB && dsB.display) {
    const rain = Object.values(f.cells || {}).map(c => c && c.design_storm).filter(Boolean);
    if (rain.length) {
      const worst = rain.reduce((a, c) => (c.mm_1h > a.mm_1h ? c : a));
      parts.push(note(`${rain.length} scored Cell${rain.length === 1 ? "" : "s"} raining; the wettest: `
        + String(dsB.display.sentence || "").replace("{mm_1h}", worst.mm_1h)));
      if (worst.bracket && dsB.display.bracket_sentence)
        parts.push(note(String(dsB.display.bracket_sentence).replace("{bracket}", worst.bracket)));
      for (const k of ["bracket_note", "climate_note", "extent_note"])
        parts.push(note(dsB.display[k]));
    }
  }
  lyr.legend = parts.join("");
}

/** files/flood-mta.json -> the affected-complex dots + the chip rows. */
export function drawMta(m) {
  const lyr = L("mta");
  if (!m) { lyr.legend = ""; return; }
  const t = m.mta || {};
  if (t.geojson) map.getSource("mta").setData(t.geojson);
  const s = m.strings || {};
  const parts = [];
  if (typeof t.active === "number")
    parts.push(note(`${t.active} active alert${t.active === 1 ? "" : "s"} in the last ${t.hours ?? "—"} h of alert capture.`));
  for (const c of (Array.isArray(t.chips) ? t.chips : []))
    parts.push(note([(c.stations || []).map(x => `${x.name} (stn:${x.complex_id})`).join(", "),
                     c.state, typeof c.age_min === "number" ? `${Math.round(c.age_min)} min ago` : ""]
      .filter(Boolean).join(" · ")));
  if ((t.chips || []).length) parts.push(note(s.no_complex_skill_claim));
  parts.push(note(s.operating_truth));
  lyr.legend = parts.join("");
}

/** files/impact.json -> the bus overlay: the hour's Cells joined onto the geometry the
 *  page already parsed (cells.geojson is fetched ONCE - frontend 05 retired the double
 *  parse - so the join reads the map's own `cells` source rather than fetching again). */
export function drawImpact(b) {
  const lyr = L("impact");
  if (!b) { lyr.legend = ""; return; }
  addDataAge("impact", b);
  const src = map.getSource("cells");
  const fc = src && src.serialize ? src.serialize().data : null;
  const feats = ((fc && fc.features) || []).map(f => ({
    type: "Feature", geometry: f.geometry,
    properties: { cell: f.properties.cell, ...((b.cells || {})[f.properties.cell] || {}) },
  }));
  map.getSource("impact").setData({ type: "FeatureCollection", features: feats });
  const s = b.strings || {};
  const parts = [note(s.label)];
  if (!feats.length)
    parts.push(note("No Cell geometry is loaded (files/cells.geojson), so there is nothing to paint on."));
  // the sparse head is SAID, not just painted: 19 Cells without a count reads as a claim
  // about the city (flood 17's own counts, re-shipped in the payload every cycle)
  if (typeof b.n_cells === "number")
    parts.push(note(`Newest closed hour ${b.hour_end_utc ?? ""}: ${b.n_cells} Cells, against ${b.densest_cells ?? "—"} in the densest hour (${b.densest_hour_end_utc ?? ""}).`));
  if (b.baseline && b.baseline.reason && b.state === "no_baseline")
    parts.push(note(b.baseline.reason));
  parts.push(note(s.never_a_detector_input));
  parts.push(sentences(s.caveats));
  lyr.legend = parts.join("");
}

/** files/impact-subway.json -> complex-grain points. `rel` rides only when the payload
 *  carries it - absent (below min_planned), not zero - and the mark reads it as SIZE. */
export function drawImpactSub(d) {
  const lyr = L("subway");
  if (!d) { lyr.legend = ""; return; }
  addDataAge("subway", d);
  const feats = Object.entries(d.complexes || {})
    .filter(([, c]) => typeof c.lon === "number" && typeof c.lat === "number")
    .map(([id, c]) => ({
      type: "Feature", geometry: { type: "Point", coordinates: [c.lon, c.lat] },
      // hour_end_utc rides on EVERY feature (frontend5 03): the tooltip renders from
      // feature properties alone, and an impact mark whose hover does not date itself
      // reads as "now" - which this payload, with no scheduled republish, rarely is.
      properties: { complex_id: id, name: c.name, cell: c.cell, planned: c.planned,
                    dropped: c.dropped, runs: c.runs, drop_share: c.drop_share,
                    hour_end_utc: d.hour_end_utc,
                    ...("rel" in c ? { rel: c.rel } : {}) },
    }));
  map.getSource("subway").setData({ type: "FeatureCollection", features: feats });
  const s = d.strings || {};
  const parts = [note(s.label)];
  if (typeof d.n_complexes === "number")
    parts.push(note(`Hour ${d.hour_end_utc ?? ""}: ${d.n_complexes} complexes, ${d.planned ?? "—"} planned stop rows, ${d.dropped ?? "—"} dropped. ${d.n_rel ?? "—"} carry a rel value; a complex under ${d.min_planned ?? "—"} planned rows carries none - absent, not zero.`));
  if (d.level && d.level.note) parts.push(note(d.level.note));
  parts.push(note(s.never_a_detector_input));
  parts.push(sentences(s.caveats));
  lyr.legend = parts.join("");
}

export function toggleLive(lit) {
  on.live = lit;
  map.setLayoutProperty("live", "visibility", lit ? "visible" : "none");
  clearInterval(liveTimer);
  liveTimer = null;
  if (lit) {
    // frontend4 05: the band join reads the cells payload, and with the Cell fill off by
    // default nothing else loads it. Data only - the fill's visibility stays the radio's,
    // and a failed load leaves the fleet neutral, which is the honest degradation.
    if (!on.cells && cellFeatures().length === 0) load("cells").then(liveTick, () => {});
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
}
