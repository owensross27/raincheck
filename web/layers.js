/* The layer table, the gate, the ramps, and the map declared at boot.
 *
 * (ticket 13 / spec L; frontend 05 grew it into the seven-layer map; frontend2 01 split
 * one 781-line app.js into the six modules named in web/app.js's header, changing nothing.)
 *
 * Reads three files written by `make export` and nothing else. The paint rule that makes
 * the page honest is ["!", ["has", p]] -> grey: the pure-SQL writer guarantees an
 * unpublishable property is an ABSENT KEY, so `has` is false and the Cell paints grey.
 * (A GDAL-written null would make `has` true and `interpolate` would error on it.)
 * One setPaintProperty per layer/hour switch, one fixed ramp - never a per-view rescale,
 * which would make two storms' colours mean different things.
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
import { drawCells } from "./insight.js";
import { drawBasemap } from "./basemap.js";

// Fixed ramps. Ratio: diverging around 1.0 (red slower, blue faster), 0.5 .. 1.2 always.
export const RATIO_STOPS = [[0.5, "#7f0000"], [0.65, "#d7301f"], [0.8, "#fc8d59"], [0.9, "#fdd49e"],
                     [1.0, "#f7f7f7"], [1.1, "#c7dcef"], [1.2, "#6baed6"]];
// Dry Speed level, m/s: sequential, a different scale for a different quantity.
export const SPEED_STOPS = [[2, "#0d1b2a"], [3.5, "#1b4965"], [5, "#3d7ea6"], [6.5, "#7fb3d5"], [8, "#cfe6f4"]];
export const GREY = "#3a4049";
// live dots: bright while the pipeline is writing, dimmed the moment it is not (ticket 14)
export const LIVE_FRESH = "#b0bec5", LIVE_STALE = "#5d666f";

// frontend 02 D2: four new hues, none on either arm of the diverging ramp above, which is
// left byte-untouched. A dry/stale FloodNet sensor is a HOLLOW RING rather than a fifth
// grey - at 2.6 px a dry sensor, a dimmed vehicle and the "no publishable value" Cell fill
// were three meanings on one #3a4049, which is one too many.
export const WATER = "#35d6c2";    // a FloodNet sensor reporting water NOW
export const ALERT = "#ffc447";    // an MTA station with water on the tracks (the page's .warn family)
export const HIST = "#8f7bd6";     // a stop or Cell with a flood record: history, not an alarm
export const GATED_HUE = "#d2a24c";    // a gated layer's chip: dark, never absent

// Ticket 14's staleness cuts, kept a TABLE and never a formula (a "2x cadence" rule would
// silently retune the deliberately chosen bronze value from 900 s to 1200). Hoisted above
// LAYERS because the live sources' budget IS this number - one source of truth.
export const STALE_AFTER_S = { live: 120, bronze: 900 };   // Bronze flushes in 10-min parts
export const DELAY_CUT_S = 300;   // 06's Delay cutoff, borrowed for an agency-computed quantity

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
export const LAYERS = [
  // frontend2 02. The ground under the ground: ONE PMTiles archive, read by range request,
  // whose style layers are spliced in above `bg` and below all twelve (see basemap.js).
  // `map: []` until it loads, because its layer ids come from the vendored style and not
  // from this file; a failed fetch leaves it empty and the page falls back to `bg`.
  // Its source is HEAD-ed, not fetched: an age must not cost 52 MB to learn, and the tiles
  // themselves are read by MapLibre's own protocol, which reports no headers to us.
  { id: "basemap", name: "Ground: basemap", gate: null, fill: false, open: true,
    map: [], owed: null,
    srcs: [{ k: "tiles/nyc.pmtiles", url: "tiles/nyc.pmtiles", budget: null, head: true }],
    draw: ([ok]) => drawBasemap(ok) },

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
export const L = (id) => LAYERS.find(x => x.id === id);
export const shut = (lyr) => Boolean(lyr.gate) && !GATE[lyr.gate];

export const $ = (id) => document.getElementById(id);
export const fmt = (v, d = 2) => (v === undefined || v === null ? "—" : v.toFixed(d));

// MapLibre has parsed the style: before that every layer call throws. An imported binding
// is read-only in the importing module, so app.js's `load` handler flips it through
// markStyled() rather than assigning across the module boundary.
export let styled = false;
export const markStyled = () => { styled = true; };

// frontend 02 D7: the 60vh map strip carries about two layers legibly at 375 px, so a small
// screen OPENS with the Cell fill on and every point layer off and the reader adds them one
// at a time. The panel set itself does not collapse - it was measured at 375 px and nothing
// overlaps. The rule lives here so a later slice that defaults a point layer on cannot
// quietly break the phone.
const SMALL = window.matchMedia("(max-width: 900px)").matches;
export const on = {};
LAYERS.forEach(l => { on[l.id] = l.open && !(SMALL && l.point); });

/* ------------------------------------------------------------------ declare at boot
 * Twelve layers, the order frozen by frontend 02 D3: ambient at the bottom, urgent on top.
 * Every source is an EMPTY FeatureCollection here and gets its data from a fetch the page
 * makes itself - which is also what makes the per-source age readable, since the age comes
 * off that response's own headers. No promoteId anywhere (rule 2 at the top of this file).
 */
const empty = () => ({ type: "geojson", data: { type: "FeatureCollection", features: [] } });
export const map = new maplibregl.Map({
  container: "map", center: [-73.93, 40.72], zoom: 10.1, attributionControl: false,
  style: {
    version: 8,
    // frontend2 02: the basemap's labels. Declared HERE rather than set later because it is
    // part of the frozen style, and it is a RELATIVE path - the bucket is the web/ tree, so
    // the glyph range is same-origin and no third host is in the demo path (spec L). One
    // fontstack, one range: basemap.js rewrites the vendored theme's three onto this file.
    glyphs: "vendor/{fontstack}-{range}.pbf",
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
