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
import { $, DELAY_CUT_S, L, LIVE_FRESH, LIVE_STALE, map, on, STALE_AFTER_S } from "./layers.js";
import { forget, grab, whys } from "./freshness.js";
import { renderLayers } from "./panel.js";

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

export function toggleLive(lit) {
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
}
