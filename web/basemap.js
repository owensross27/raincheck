/* The vector basemap: land, water and shoreline, roads, place labels (frontend2 02).
 *
 * Reverses the 2026-08-17 refusal in `.scratch/pipeline/issues/14-serving-surface.md:88-97`
 * ("no basemap now ... needs a Range server"). What changed: serving moved to an R2 bucket
 * behind a custom domain (frontend 03/04) and R2 answers byte ranges, which is the only
 * thing a PMTiles archive ever asks for. `make basemap` builds the one file; `make publish
 * FAMILY=tiles` puts it on the host; `make web` (raincheck.webserve) serves ranges locally.
 *
 * FOUR RULES, and each of them is why this file exists rather than five lines in layers.js:
 *
 *  1. THE BASEMAP IS A SOURCE LIKE ANY OTHER. It is a `LAYERS` entry with its own freshness
 *     row, so the reader is told how old the ground under the data is. Its source is read
 *     with a HEAD - `Date` - `Last-Modified` off the response, the same reader-dated age
 *     every other source uses (frontend 01 D2), and zero bytes of body, because the age of
 *     a 52 MB archive must not cost 52 MB to learn. A GET would also be a lie in the other
 *     direction: the tiles themselves are fetched by the pmtiles protocol INSIDE MapLibre,
 *     and a source MapLibre fetches for itself can never report its own age (TRAPS).
 *  2. A MISSING BASEMAP IS AN EXPLAINED CHIP, NEVER A BLACK SCREEN AND NEVER A THROWN BOOT.
 *     If the archive or the style is not there, the layer goes OFF with the reason printed
 *     and the page falls back to the flat `bg` rectangle it has always had. Nothing here
 *     may throw into the `load` handler: a basemap is the least important thing on this
 *     page and it must never be able to stop the delay Cells from painting.
 *  3. ITS LAYERS SIT ABOVE `bg` AND BELOW ALL TWELVE DATA LAYERS - IN TWO SPLICES (frontend4
 *     01). Non-symbol layers (fills, lines) insert before the first data layer, so the
 *     twelve keep their frozen relative order (frontend 02 D3) and the whole basemap lands
 *     in the one gap between the background and the ground. Symbol layers (place and street
 *     labels) insert before a SECOND, higher point: above every fill/line and below every
 *     point layer, so a name is never painted over by a dot. Both insertion points are the
 *     single sanctioned use of addLayer() on this page - a lazily added layer with NO
 *     beforeId lands on top, which is what rule 1 of layers.js forbids - and the
 *     frozen-order test is re-derived to assert the invariant rather than a longer literal.
 *  4. IT RECEDES. The vendored theme is the official Protomaps DARK flavour, taken
 *     unmodified except structurally: its own `background` is dropped (the page has `bg`),
 *     `pois` is dropped (its icons need a sprite, which would be a fourth vendored asset
 *     for labels nobody asked for), and its three fontstacks collapse onto one - the page
 *     vendors ONE glyph range, and a basemap under a diverging Cell ramp should not carry
 *     a type hierarchy of its own. No new hue, no second ramp (frontend 02 D1).
 *
 * ATTRIBUTION IS A CONDITION OF USING THIS DATA, not a credit line, and it lives in the
 * always-visible `#provenance` strip beside MTA's - see index.html. Read 2026-08-25 from
 * the two upstream requirements themselves: the OSMF Attribution Guidelines (credit
 * "(c) OpenStreetMap contributors", adjacent to the map, made clear to be under the Open
 * Database License by linking openstreetmap.org/copyright) and github.com/protomaps/
 * basemaps ("Web maps ... that use this Produced Work must visibly attribute (c)
 * OpenStreetMap"; credit to Protomaps requested, and given).
 */
import { L, map, on } from "./layers.js";
// `pmtiles` is a GLOBAL from the vendored UMD bundle, exactly as `maplibregl` is - and it
// has to be. The ESM build carries a bare `from "fflate"`, which no browser resolves
// without an import map (measured, not assumed: node's resolver refused it). The UMD build
// bundles fflate, so index.html carries two classic library tags and still ONE module entry.

// gitignored, built by `make basemap`, published as the `tiles` family - NOT a `site` key
export const TILES = "tiles/nyc.pmtiles";
// vendored by `make vendor`, sha256-pinned: never fetched from a third host at demo time
export const STYLE = "vendor/basemap-dark.json";
// the one fontstack every label is rewritten onto; `glyphs` in layers.js names the same file
export const FONT = "notosans";

const SRC = "basemap";
// the first of the twelve. Every non-symbol basemap layer is inserted BEFORE it, so all of
// it is above `bg` (the only layer below this one) and below every data layer.
const FIRST_DATA_LAYER = "zones-fill";
// SPEC_ORDER[7]: the second splice point. Every symbol (label) basemap layer is inserted
// BEFORE it instead, so labels sit above every fill/line (cells, impact, geography band,
// zone lines) and below every point layer (locate, live, hist, fn, mta) - the dots keep
// top billing over the ground they sit on.
export const LABELS_BEFORE = "locate";
// its icons need a sprite; the sprite would be a fourth vendored asset for POI dots that
// would fight the tier points. Dropped, not disabled, so nothing requests the sprite.
const DROP = new Set(["pois"]);

// Density: interpolation-stop overrides for the minor/service/other/link road layers (+
// their casings), keyed by style layer id. The width curve IS the zoom gate on this style -
// most road layers have no minzoom of their own - so "denser sooner" means moving the curve's
// own stops earlier, tuned against real screenshots rather than by eye-reading the vendored
// JSON. Casing `line-gap-width` always mirrors its fill's `line-width`: that is what makes
// the casing read as a border rather than a second, wider line. Untouched: highway/major/
// rail curves, colors, and every layer this table does not name.
const OVERRIDES = {
  roads_minor: {
    "line-width": ["interpolate", ["exponential", 1.6], ["zoom"], 10.5, 0, 12, 0.5, 15, 2, 18, 11],
  },
  roads_minor_casing: {
    "line-width": ["interpolate", ["exponential", 1.6], ["zoom"], 10.5, 0, 12, 1],
    "line-gap-width": ["interpolate", ["exponential", 1.6], ["zoom"], 10.5, 0, 12, 0.5, 15, 2, 18, 11],
  },
  roads_minor_service: {
    minzoom: 12,
    "line-width": ["interpolate", ["exponential", 1.6], ["zoom"], 12, 0, 18, 8],
  },
  roads_minor_service_casing: {
    minzoom: 12,
    "line-width": ["interpolate", ["exponential", 1.6], ["zoom"], 12, 0, 12.5, 0.8],
    "line-gap-width": ["interpolate", ["exponential", 1.6], ["zoom"], 12, 0, 18, 8],
  },
  roads_other: {
    "line-width": ["interpolate", ["exponential", 1.6], ["zoom"], 13, 0, 20, 7],
  },
  roads_link: {
    "line-width": ["interpolate", ["exponential", 1.6], ["zoom"], 10.5, 0, 12, 1, 18, 11],
  },
  roads_link_casing: {
    minzoom: 10.5,
    "line-width": ["interpolate", ["exponential", 1.6], ["zoom"], 10.5, 0, 12, 1.5],
    "line-gap-width": ["interpolate", ["exponential", 1.6], ["zoom"], 10.5, 0, 12, 1, 18, 11],
  },
};

let added = [];

/** Recursively replace every array-valued `text-font` member with our one fontstack -
 *  including the ones nested inside a `text-field` `format` expression's override objects,
 *  which the top-level-only collapse this replaced could not see. Wrapped in `"literal"`
 *  rather than the bare-array shorthand: a `format` override sits INSIDE an expression
 *  tree, where a bare array is parsed as an expression call (`["notosans"]` throws
 *  "Unknown expression \"notosans\""), and `["literal", [...]]` is the one form valid in
 *  both that position and the plain layout property. */
function collapseFonts(node) {
  if (Array.isArray(node)) return node.map(collapseFonts);
  if (node && typeof node === "object") {
    const out = {};
    for (const [k, v] of Object.entries(node))
      out[k] = k === "text-font" && Array.isArray(v) ? ["literal", [FONT]] : collapseFonts(v);
    return out;
  }
  return node;
}

/** Patch a layer's minzoom/paint per OVERRIDES, leaving every layer OVERRIDES does not name
 *  byte-identical apart from the source/font rewrite every layer gets. */
function applyOverride(l) {
  const ov = OVERRIDES[l.id];
  if (!ov) return l;
  const out = { ...l, paint: { ...l.paint } };
  if ("minzoom" in ov) out.minzoom = ov.minzoom;
  if (ov["line-width"]) out.paint["line-width"] = ov["line-width"];
  if (ov["line-gap-width"]) out.paint["line-gap-width"] = ov["line-gap-width"];
  return out;
}

/** Style layers -> our source, our one fontstack (collapsed everywhere it is nested), the
 *  density overrides, the minor-labels minzoom drop, the theme's own background dropped -
 *  then partitioned into the two splices (symbol labels, everything else). */
export function prepare(styleLayers) {
  const out = styleLayers
    .filter(l => l.type !== "background" && !DROP.has(l.id))
    .map(l => {
      let layer = { ...l, source: SRC };
      if (layer.layout) layer.layout = collapseFonts(layer.layout);
      // the extract is maxzoom 13; 15 was overzoom-only, so minor street names never showed
      if (layer.id === "roads_labels_minor") layer.minzoom = 13;
      return applyOverride(layer);
    });
  return { fill: out.filter(l => l.type !== "symbol"), symbol: out.filter(l => l.type === "symbol") };
}

/** Undo a partial insert, so a failure leaves the page on `bg` rather than half-painted. */
function dropBasemap() {
  for (const id of added) if (map.getLayer(id)) map.removeLayer(id);
  added = [];
  if (map.getSource(SRC)) map.removeSource(SRC);
  L("basemap").map = [];
}

/** The layer's `draw`. `ok` is what the HEAD on the archive returned: null means it is not
 *  on this host, and then the only honest thing to do is not claim a basemap. */
export async function drawBasemap(ok) {
  const lyr = L("basemap");
  if (map.getSource(SRC)) return;          // idempotent: toggling off and on again
  if (!ok) { on.basemap = false; return; }
  try {
    // no-cache, not no-store: revalidate the vendored style (a 304 costs no body) rather
    // than re-download 8 KB every load - same rule as grab()'s fetch in freshness.js
    const res = await fetch(STYLE, { cache: "no-cache" });
    if (!res.ok) throw new Error(`style HTTP ${res.status}`);
    const style = await res.json();
    maplibregl.addProtocol("pmtiles", new pmtiles.Protocol().tile);
    map.addSource(SRC, { type: "vector", url: "pmtiles://" + TILES });
    const { fill, symbol } = prepare(style.layers);
    for (const l of fill) {
      map.addLayer(l, FIRST_DATA_LAYER);
      added.push(l.id);
    }
    for (const l of symbol) {
      map.addLayer(l, LABELS_BEFORE);
      added.push(l.id);
    }
    lyr.map = [...added];
  } catch (err) {
    // never into the boot handler: the delay Cells matter and the ground does not
    dropBasemap();
    on.basemap = false;
  }
}
