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
 *  3. ITS LAYERS SIT ABOVE `bg` AND BELOW ALL TWELVE DATA LAYERS. Every one is inserted
 *     with `beforeId` = the first data layer, so the twelve keep their frozen relative
 *     order (frontend 02 D3) and the whole basemap lands in the one gap between the
 *     background and the ground. This is the single sanctioned use of addLayer() on this
 *     page - a lazily added layer with NO beforeId lands on top, which is what rule 1 of
 *     layers.js forbids, and the frozen-order test is re-derived to assert the invariant
 *     rather than a longer literal.
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
// the first of the twelve. Everything here is inserted BEFORE it, so all of it is above
// `bg` (the only layer below this one) and below every data layer.
const FIRST_DATA_LAYER = "zones-fill";
// its icons need a sprite; the sprite would be a fourth vendored asset for POI dots that
// would fight the tier points. Dropped, not disabled, so nothing requests the sprite.
const DROP = new Set(["pois"]);

let added = [];

/** Style layers -> our source, our one fontstack, the theme's own background dropped. */
export function prepare(styleLayers) {
  return styleLayers
    .filter(l => l.type !== "background" && !DROP.has(l.id))
    .map(l => {
      const out = { ...l, source: SRC };
      if (out.layout && out.layout["text-font"])
        out.layout = { ...out.layout, "text-font": [FONT] };
      return out;
    });
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
    const res = await fetch(STYLE, { cache: "no-store" });
    if (!res.ok) throw new Error(`style HTTP ${res.status}`);
    const style = await res.json();
    maplibregl.addProtocol("pmtiles", new pmtiles.Protocol().tile);
    map.addSource(SRC, { type: "vector", url: "pmtiles://" + TILES });
    for (const l of prepare(style.layers)) {
      map.addLayer(l, FIRST_DATA_LAYER);
      added.push(l.id);
    }
    lyr.map = [...added];
  } catch (err) {
    // never into the boot handler: the delay Cells matter and the ground does not
    dropBasemap();
    on.basemap = false;
  }
}
