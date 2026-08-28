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
import { drawCells, drawRoutes, drawZones } from "./insight.js";
import { drawBasemap } from "./basemap.js";
import { drawFn, drawImpact, drawImpactSub, drawMta } from "./live.js";

// Fixed ramps. Ratio: diverging around 1.0 (red slower, blue faster), 0.5 .. 1.2 always.
export const RATIO_STOPS = [[0.5, "#7f0000"], [0.65, "#d7301f"], [0.8, "#fc8d59"], [0.9, "#fdd49e"],
                     [1.0, "#f7f7f7"], [1.1, "#c7dcef"], [1.2, "#6baed6"]];
// Dry Speed level, m/s: sequential, a different scale for a different quantity.
export const SPEED_STOPS = [[2, "#0d1b2a"], [3.5, "#1b4965"], [5, "#3d7ea6"], [6.5, "#7fb3d5"], [8, "#cfe6f4"]];
export const GREY = "#3a4049";
// live dots: bright while the pipeline is writing, dimmed the moment it is not (ticket 14)
export const LIVE_FRESH = "#b0bec5", LIVE_STALE = "#5d666f";

// frontend4 04: the fleet joins the delay fill's frozen ramp - impact-fill's own case
// pattern (below), one vocabulary on a second mark. `ratio` is attached client-side, per
// vehicle, only when it is raining in that vehicle's Cell and the Cell publishes a band
// (live.js's liveTick); absent -> LIVE_FRESH, the mark's OWN neutral, never fill-GREY (an
// absent-value colour is a property of the mark, frontend2 03's lesson). Shared by the
// boot declaration and renderLive's fresh branch so the expression is written once.
export const LIVE_COLOR = ["case", ["!", ["has", "ratio"]], LIVE_FRESH,
  ["interpolate", ["linear"], ["get", "ratio"], ...RATIO_STOPS.flat()]];

// frontend 02 D2: four new hues, none on either arm of the diverging ramp above, which is
// left byte-untouched. A dry/stale FloodNet sensor is a HOLLOW RING rather than a fifth
// grey - at 2.6 px a dry sensor, a dimmed vehicle and the "no publishable value" Cell fill
// were three meanings on one #3a4049, which is one too many.
export const WATER = "#35d6c2";    // a FloodNet sensor reporting water NOW
export const ALERT = "#ffc447";    // an MTA station with water on the tracks (the page's .warn family)
export const HIST = "#8f7bd6";     // a stop or Cell with a flood record: history, not an alarm
export const GATED_HUE = "#d2a24c";    // a gated layer's chip: dark, never absent

/* frontend2 03's geography band. Two rules decided these four values rather than taste.
 *  - A MODELLED extent may not be drawn in the hue an OBSERVED one uses. WATER (#35d6c2)
 *    means "a FloodNet sensor is reporting water NOW"; DEP's design storm is a planning
 *    map of what WOULD flood at a rain rate, and painting the two in one hue is the single
 *    confusion this layer must not create.
 *  - Neither arm of the diverging ramp, which is left byte-untouched (frontend 02 D2).
 * Green is the one family this page had not spent: red and blue are the ramp, aqua is
 * observed water, amber is an MTA alert, violet is flood history, and #d2a24c is a gated
 * chip. `deep` and `nuisance` are two TONES of it - one hue, two depths - and DEP's
 * exclusion mask gets a NEUTRAL that is deliberately not GREY, which already means "no
 * publishable value for this layer" on the Cell fill three layers up.
 */
export const ZONE_DEEP = "#2e7d5b";       // ponding >= 1 ft ("Deep and Contiguous Flooding")
export const ZONE_NUISANCE = "#8fcfae";   // >= 4 in, < 1 ft ("Nuisance Flooding")
export const ZONE_MASK = "#7a8794";       // "Area not included in analysis" - NOT "no flooding"
export const ROUTE_PLAIN = "#5b6572";     // a route line carrying geometry and no number

/* flood 17's subway impact overlay: one new hue for one new mark family (complex-grain
 * points), and the clamp its `rel` ramp must carry. `rel` is the complex against the
 * citywide same-hour median of the SAME feed and it is unbounded above - measured 18.7
 * against a median drop_share of 0.0247 (2026-08-26) - so the size ramp saturates at
 * REL_CLAMP: past several times the citywide median the mark has said everything a mark
 * can say, and an unclamped linear ramp is one station and 437 flat ones. A complex below
 * the payload's own `min_planned` carries NO `rel` - absent, not zero - and renders as a
 * RING, the page's established "present, no publishable value" mark (the fn layer's). */
export const SUBWAY = "#e07ba0";   // a complex's dropped-service share vs the citywide median
export const REL_CLAMP = 4;

// frontend5 01 MUST 4, rung 2: hist is the one interactive point layer with NO
// circle-stroke-width at all, so a transparent stroke this wide is a pure hit-target
// affordance - MapLibre's CircleStyleLayer sums circle-radius + circle-stroke-width for
// its click hit test (queryRadius AND queryIntersectsFeature both, read from the vendored
// bundle), so this widens what a click can land on without moving a single visible pixel.
// Measured before shipping, not assumed (a real CDP click past the visible disc, still on
// the marker): see docs/adr or the ticket close-out for the number.
export const HIST_HIT_STROKE = 4;

// The category -> hue mapping, as ONE expression both the paint and the legend read, so a
// swatch cannot show a colour the map does not use. An unrecognised category falls to the
// mask neutral rather than to a depth tone: a tone would CLAIM a depth for something this
// page has never seen, and the neutral only claims "not something we can colour".
export const ZONE_COLOR = ["match", ["get", "category"],
  "deep", ZONE_DEEP, "nuisance", ZONE_NUISANCE, "not_analyzed", ZONE_MASK, ZONE_MASK];
export const ZONE_LEGEND = [
  ["deep", ZONE_DEEP, "deep and contiguous ponding, at least 1 ft"],
  ["nuisance", ZONE_NUISANCE, "nuisance flooding, 4 in to 1 ft"],
  ["not_analyzed", ZONE_MASK, "DEP did not model here \u2014 this is NOT \u201cno flooding\u201d"],
];
/* The mask is DRAWN and it RECEDES, and both halves are the rule. `not_analyzed` polygons
 * are the big ones - rail corridors, large lots, open space - so at the depths' own opacity
 * they wash the whole city out and hide both the modelled classes and the route lines under
 * them (measured in a real tab, not predicted). It carries less ink than a modelled class
 * because it carries less information, and it is never zero: painting DEP's exclusion mask
 * as clear is the exact lie this layer exists not to tell. */
export const ZONE_FILL_OPACITY = ["match", ["get", "category"], "not_analyzed", 0.16, 0.5];
export const ZONE_LINE_OPACITY = ["match", ["get", "category"], "not_analyzed", 0.3, 0.85];

// A route line is 16,117 km of geometry in one layer, so its weight is a zoom ramp and not
// a number: at z10 the whole network is on screen and anything thicker is a mat.
export const ROUTE_W_THIN = ["interpolate", ["linear"], ["zoom"], 10, 0.5, 14, 1.2];
export const ROUTE_W_RAMP = ["interpolate", ["linear"], ["zoom"], 10, 0.9, 14, 2.6];

// Ticket 14's staleness cuts, kept a TABLE and never a formula (a "2x cadence" rule would
// silently retune the deliberately chosen bronze value from 900 s to 1200). Hoisted above
// LAYERS because the live sources' budget IS this number - one source of truth.
export const STALE_AFTER_S = { live: 120, bronze: 900 };   // Bronze flushes in 10-min parts
export const DELAY_CUT_S = 300;   // 06's Delay cutoff, borrowed for an agency-computed quantity

/* THE MTA GATE CUTS BY LINEAGE, and it has TWO SIDES (frontend 01 D3). Withholding the
 * vehicles must never withhold the FloodNet tier, and opening the vehicles must never
 * open MTA-derived ALERT rows - so the page keys each layer on its own gate side rather
 * than on one global switch. Both sides follow the same deploy-time constant,
 * `raincheck.publish.LIVE_TERMS_VERIFIED` - OPEN since 2026-08-27, when the MTA
 * Developer Agreement was verified (docs/adr/0003: the terms authorize, and in fact
 * require, serving the data to others from a non-MTA server); a test cross-checks these
 * two booleans against it. Either side can be shut again alone, with no re-plumbing.
 */
const GATE = {
  "mta-vehicles": true,    // GTFS-RT vehicle positions -> the live fleet, flood 17's bus overlay
  "mta-alerts": true,      // archive/subway_alerts -> the MTA flood tier's alert rows
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
    sub: "Streets, parks and water under everything else.",
    map: [], owed: null,
    srcs: [{ k: "tiles/nyc.pmtiles", url: "tiles/nyc.pmtiles", budget: null, head: true }],
    draw: ([ok]) => drawBasemap(ok) },

  { id: "zones", name: "Ground: taxi zones", gate: null, fill: false, open: false,
    sub: "Taxi-zone outlines, for finding where you are.",
    map: ["zones-fill", "zones-line"], owed: null,
    srcs: [{ k: "files/zones.geojson", url: "files/zones.geojson", budget: null }],
    draw: ([z]) => { if (z) map.getSource("zones").setData(z); } },

  /* frontend2 03. Both are GROUND: they sit in the style block between `zones-fill` and
   * `cells`, so they are above the basemap and below every layer that carries an answer.
   * Neither is `fill: true` - the Cell-fill radio is frozen (frontend 02 D1) and a
   * non-Cell polygon does not join it. What binds them to it instead is the one-ramp rule
   * `applyRamp()` enforces: while a Cell fill is lit the zones are OUTLINES and the route
   * is thin and uncoloured; with the fill off, the zones fill and the route carries the
   * ramp. Both are `open: false` - nothing here is fetched until the reader ticks it, and
   * routes.geojson is 7.78 MiB. */
  { id: "routes", name: "Bus route lines", gate: null, fill: false, open: false,
    sub: "Where the buses run.",
    det: "21,868 Cell crossings; loads 7.8 MB when ticked, never before.",
    map: ["routes"], owed: null,
    srcs: [{ k: "files/geo/routes.geojson", url: "files/geo/routes.geojson", budget: null }],
    draw: ([r]) => drawRoutes(r) },

  // its FIRST source is the scenario manifest, and the scenario payload is a second source
  // drawZones() adds once it knows which one is selected - see insight.js. A browser cannot
  // list a directory, and `geo` is a TREE family whose served set is derived from the
  // table, so the manifest is what makes a second scenario a DATA change and not a rewrite.
  { id: "stormwater", name: "Ground: flood zones (DEP design storm)", gate: null, fill: false,
    sub: "The city's planning map of where heavy rain would pond.",
    det: "Loads 4.4 MB when ticked, never before.",
    open: false, map: ["stormwater-fill", "stormwater-line"], owed: null,
    srcs: [{ k: "files/geo/scenarios.json", url: "files/geo/scenarios.json", budget: null }],
    draw: ([m]) => drawZones(m) },

  { id: "cells", name: "Delay cells", gate: null, fill: true, open: false,
    sub: "How much slower the buses ran in the rain, area by area.",
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
    sub: "Street flood sensors around the city, lit when one is reporting water.",
    map: ["fn"], owed: null,
    srcs: [{ k: "files/flood.json", url: "files/flood.json", budget: 600 }],
    draw: ([f]) => drawFn(f) },

  // no budget: unlike the impact pair below, no staleness constant for the alert side is
  // frozen anywhere in the repo (flood 15's budgets_s carries the six FEED budgets, none
  // for this file), so this row renders an AGE and judges nothing - the chip states inside
  // the payload carry their own per-incident verdicts. frontend 02 D6: never a guessed one.
  { id: "mta", point: true, name: "Flood tier: MTA alerts", gate: "mta-alerts", fill: false, open: true,
    sub: "Stations where the MTA has reported water on the tracks.",
    map: ["mta"], owed: null,
    srcs: [{ k: "files/flood-mta.json", url: "files/flood-mta.json", budget: null }],
    draw: ([m]) => drawMta(m) },

  // 122400 = flood_overlay.BUS_BUDGET_S (one nightly cycle + daily.TAIL_H); the test
  // derives it from that module so the two cannot drift. The payload's own staleness is
  // the DATA's age at write; the draw adds it to the file age (the live pair's composite),
  // so a fresh file over a stale Gold hour still reads STALE.
  { id: "impact", name: "Impact overlay: bus", gate: "mta-vehicles", fill: true, open: false,
    sub: "How the buses are doing right now against a dry baseline.",
    map: ["impact-fill", "impact-line"], owed: null,
    srcs: [{ k: "files/impact.json", url: "files/impact.json", budget: 122400 }],
    draw: ([b]) => drawImpact(b) },

  // flood 17's subway overlay: complex-grain POINTS, a different channel from the
  // Cell-fill radio entirely (never a second fill - a Cell overlay and a complex overlay
  // in one legend would be lying about their grain). 4200 = flood_overlay.SUBWAY_BUDGET_S
  // (the hour + archiver.WINDOW), derived in the test like the bus budget above.
  { id: "subway", point: true, name: "Impact overlay: subway", gate: "mta-vehicles", fill: false,
    sub: "This hour's dropped subway service - stations well above the citywide median " +
         "stand out; normal service fades to a trace.",
    open: true, map: ["subway"], owed: null,
    srcs: [{ k: "files/impact-subway.json", url: "files/impact-subway.json", budget: 4200 }],
    draw: ([d]) => drawImpactSub(d) },

  /* frontend 07. `open: false` is the boot-vs-toggle decision, taken on the measured
   * sizes: the manifest is 1,458,148 B RAW (nothing on this host compresses), ~40% of the
   * page's current first paint, so it is fetched ONCE on the first tick and never at boot.
   * A click then fetches ONE per-asset record (median 1,138 B, max 21,994 B) - the card's
   * fetch in insight.js, and the only thing under files/history/ ever fetched besides
   * this manifest. No budget is frozen for this source anywhere in the repo, so its row
   * reads a bare AGE - reporting a verdict here would be a guessed constant. */
  { id: "hist", point: true, name: "Flood history markers", gate: null, fill: false, open: false,
    sub: "Places that have flooded before; click a marker for its record.",
    det: "8,146 assets; loads 1.5 MB once when first ticked - never at boot. A marker click fetches that one record alone (~1 KB, at most 22 KB).",
    map: ["hist"], owed: null,
    srcs: [{ k: "files/history/manifest.geojson", url: "files/history/manifest.geojson",
             budget: null }],
    draw: ([m]) => { if (m) {
      map.getSource("hist").setData(m);
      L("hist").legend = `<p class="note">${m.features.length.toLocaleString()} assets with a
        flood record. Click a marker for its record card - one small fetch per click.</p>`;
    } } },
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
    sources: { zones: empty(), stormwater: empty(), routes: empty(), cells: empty(),
               impact: empty(), locate: empty(),
               live: empty(), hist: empty(), fn: empty(), mta: empty(), subway: empty() },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": "#0b0d10" } },
      { id: "zones-fill", type: "fill", source: "zones", layout: { visibility: "none" },
        paint: { "fill-color": "#141920" } },
      /* frontend2 03's geography band - the ONE place anything is added by this ticket,
       * and it is ABOVE `zones-fill` on purpose. Every basemap layer is inserted with
       * `beforeId: "zones-fill"` (basemap.js, derived from SPEC_ORDER[1]), so a layer
       * declared BELOW `zones-fill` would land underneath all 66 of them and never be
       * seen. Declared here, the geography sits above the basemap and below every layer
       * that carries an answer, and the twelve keep their frozen relative order. */
      { id: "stormwater-fill", type: "fill", source: "stormwater", layout: { visibility: "none" },
        paint: { "fill-color": ZONE_COLOR, "fill-opacity": ZONE_FILL_OPACITY } },
      // the OUTLINE is what survives the one-ramp rule: with a Cell fill lit the fill above
      // goes to opacity 0 and this is all that is left of the zones
      { id: "stormwater-line", type: "line", source: "stormwater", layout: { visibility: "none" },
        paint: { "line-color": ZONE_COLOR, "line-width": 0.7,
                 "line-opacity": ZONE_LINE_OPACITY } },
      { id: "routes", type: "line", source: "routes", layout: { visibility: "none" },
        paint: { "line-color": ROUTE_PLAIN, "line-width": ROUTE_W_THIN, "line-opacity": 0.85 } },
      { id: "cells", type: "fill", source: "cells", layout: { visibility: "none" },
        paint: { "fill-color": GREY, "fill-opacity": 0.86 } },
      // the impact overlay shares the Cell fill channel and the frozen ramp above; it gets
      // no ramp of its own and can never be lit at the same time as `cells` (frontend 02 D1).
      // The paint is declared AT BOOT off the same RATIO_STOPS the delay fill uses: `ratio`
      // is an ABSENT key wherever no capture-era baseline exists (today: everywhere, and
      // the payload says why), so ["!", ["has", "ratio"]] paints grey - spec L's own rule.
      { id: "impact-fill", type: "fill", source: "impact", layout: { visibility: "none" },
        paint: { "fill-color": ["case", ["!", ["has", "ratio"]], GREY,
                   ["interpolate", ["linear"], ["get", "ratio"], ...RATIO_STOPS.flat()]],
                 "fill-opacity": 0.86 } },
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
        paint: { "circle-radius": 2.6, "circle-color": LIVE_COLOR, "circle-opacity": 0.9 } },
      // the radius ramp is sized on the manifest's own measured tail: n_events max is 73
      // (cell:882a1062d5fffff), so the top stop is real data, not a guess. frontend5 01
      // MUST 4: the minimum stop was 1.6 - most of the 8,146 markers sit near it, and it
      // is the only one of the four interactive point layers with NO circle-stroke-width
      // at all, so it is also the one whose hit test the rung-1 bump alone cannot fix (see
      // HIST_HIT_STROKE below). Bumped a step, measured against the other three below.
      { id: "hist", type: "circle", source: "hist", layout: { visibility: "none" },
        paint: { "circle-color": HIST, "circle-opacity": 0.5,
          "circle-radius": ["interpolate", ["linear"], ["get", "n_events"],
                            1, 2.6, 12, 4.6, 73, 8],
          // MapLibre's CircleStyleLayer sums circle-radius + circle-stroke-width for BOTH
          // its candidate query padding and its exact queryIntersectsFeature test (read
          // from the vendored 5.9.0 bundle, and confirmed by a real CDP click test - a
          // dispatched click that misses the visible disc still opens the card). Zero
          // alpha, so no pixel changes: the affordance is a hit target only.
          "circle-stroke-width": HIST_HIT_STROKE, "circle-stroke-color": "rgba(0,0,0,0)" } },
      // the hollow ring: a sensor reporting water is a filled aqua disc, a dry or stale one
      // is a STROKE with no fill, so "sensor present, no water" reads as a different MARK.
      // frontend5 01 MUST 4: both radii bumped a step; the stroke it already carries for
      // the dry-ring mark already extends its hit test (queryRadius sums radius+stroke),
      // so fn needs no separate invisible affordance the way hist does.
      { id: "fn", type: "circle", source: "fn", layout: { visibility: "none" },
        paint: { "circle-color": ["case", ["get", "display"], WATER, "rgba(0,0,0,0)"],
                 "circle-radius": ["case", ["get", "display"], 7, 4.4],
                 "circle-stroke-color": ["case", ["get", "display"], "#0b0d10", WATER],
                 "circle-stroke-width": 1.2 } },
      // flood 17's subway overlay: `rel` drives the SIZE, clamped at REL_CLAMP (an
      // interpolate holds its last output past its last stop, so the clamp is the
      // expression itself). Absent `rel` (below the payload's min_planned) is a RING -
      // present, no publishable value - never a zero-sized or zero-valued mark.
      { id: "subway", type: "circle", source: "subway", layout: { visibility: "none" },
        paint: { "circle-color": ["case", ["has", "rel"], SUBWAY, "rgba(0,0,0,0)"],
                 "circle-radius": ["case", ["has", "rel"],
                   ["interpolate", ["linear"], ["get", "rel"], 1, 3.5, REL_CLAMP, 9], 3],
                 "circle-stroke-color": SUBWAY, "circle-stroke-width": 1.2,
                 // frontend5 03: ONLY THE TAIL READS (the payload's own caveat, verbatim in
                 // its strings). `rel` exists for every complex every hour - the citywide-
                 // median complex is rel 1.0, i.e. NORMAL service - so a flat opacity lit
                 // the whole system and read as "impact at literally every stop". The
                 // opacity now follows rel: the median fades to a trace and only complexes
                 // dropping service several times the citywide median stand out. A display
                 // rule, not a filter - every dot is still there, still hoverable.
                 "circle-opacity": ["case", ["has", "rel"],
                   ["interpolate", ["linear"], ["get", "rel"], 1, 0.06, 2, 0.3, REL_CLAMP, 0.92], 0],
                 "circle-stroke-opacity": ["case", ["has", "rel"],
                   ["interpolate", ["linear"], ["get", "rel"], 1, 0.1, 2, 0.4, REL_CLAMP, 1],
                   0.35] } },
      // an "affected station" is a dot on the COMPLEX (frontend 02 D4): the flood_truth chip
      // is per-incident and spans one or more complexes, so the chip is what the card shows
      // frontend5 01 MUST 4: bumped a step. Its own contrast stroke (1.5) already extends
      // the hit test the way fn's dry-ring stroke does, so no separate affordance needed.
      { id: "mta", type: "circle", source: "mta", layout: { visibility: "none" },
        paint: { "circle-color": ALERT, "circle-radius": 8, "circle-opacity": 0.92,
                 "circle-stroke-color": "#0b0d10", "circle-stroke-width": 1.5 } },
    ],
  },
});
