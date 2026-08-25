/* raincheck serving page - the ENTRY module, and the only one that wires anything.
 *
 * One page, ES modules, no build step (spec L: no npm, no bundler). index.html carries one
 * script tag for the page's own code - this file, `type="module"` - and one classic tag for
 * the vendored MapLibre UMD, which stays a global.
 *
 *   layers.js     the ramps and hues, STALE_AFTER_S / DELAY_CUT_S, the GATE table, the
 *                 LAYERS table, $ / fmt / L / shut / on / SMALL, and the declare-at-boot
 *                 map + style (twelve layers, frozen order). Constructs `map`.
 *   freshness.js  ages / whys, grab / load / forget, fmtAge, srcState (the five states in
 *                 their frozen precedence) and worst.
 *   panel.js      the layer rows, the focus restore, applyVisibility, toggle.
 *   insight.js    paint / headline / curve / views / hours / tooltip / drawCells.
 *   live.js       metaAge / isStale / renderLive / liveTick / toggleLive.
 *   app.js        this file: boot.
 *
 * WHY ALL THE WIRING IS HERE, and not beside the code it drives. The module graph is
 * CYCLIC by construction - layers.js needs drawCells (insight) inside a LAYERS.draw
 * closure, and freshness.js needs liveMeta (live) inside srcState - so the bodies do NOT
 * evaluate in import order. Measured under node 25: panel, live, freshness, insight,
 * layers, then this file; layers.js, which every other module reads, evaluates almost
 * LAST. A cycle is safe exactly while no module BODY reads another module's binding, so
 * every addEventListener, every map.on/map.once and both ResizeObservers live here, after
 * all six have evaluated. Put one back beside its own code and the page throws a TDZ
 * ReferenceError at load with the map never painting.
 *
 * For the same reason the two cross-module WRITES go through a function - an imported
 * binding is read-only in the importing module: layers.markStyled() and live.toggleLive().
 */
import { $, LAYERS, map, markStyled, on } from "./layers.js";
import { load } from "./freshness.js";
import { applyVisibility, renderLayers, toggle } from "./panel.js";
import { setHour, setView, showTip } from "./insight.js";
import { toggleLive } from "./live.js";

map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution:
  "MTA Bus Time GTFS-RT; nycbuspositions archive; NOAA AORC; NYC TLC taxi zones" }));

// delegated, because the rows are rebuilt: #layers itself is the stable element
$("layers").addEventListener("change", e => {
  const id = e.target.dataset && e.target.dataset.l;
  if (id) toggle(id, e.target.checked);
});

$("views").addEventListener("click", e => { if (e.target.dataset.v) setView(e.target.dataset.v); });
$("hours").addEventListener("click", e => { if (e.target.dataset.h) setHour(e.target.dataset.h); });

map.on("mousemove", "cells", showTip);
map.on("click", "cells", showTip);          // touch
map.on("mouseleave", "cells", () => { $("tip").style.display = "none"; });

// `load`, not `styledata`: styledata fires while isStyleLoaded() is still false and every
// setPaintProperty / setLayoutProperty below still throws "Style is not done loading".
map.on("load", async () => {
  markStyled();
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

// The toggle stays disabled until the map is loaded, because every branch of toggleLive()
// touches the `live` layer and setPaintProperty / getSource THROW before it exists - which
// would kill the tick silently and leave the panel on its "off" text under a ticked box
// (measured in a real tab). `load`, not `styledata`: styledata fires while
// isStyleLoaded() is still false and setPaintProperty still throws "Style is not done
// loading". A hidden tab throttles rAF and never fires it, which is why this panel can
// only be checked in a VISIBLE tab - a headless screenshot is misleading.
if (map.loaded()) $("livetoggle").disabled = false;
else map.once("load", () => { $("livetoggle").disabled = false; });

$("livetoggle").addEventListener("change", () => toggleLive($("livetoggle").checked));

// first paint of the panel itself: the rows exist before the map is loaded, with
// every control disabled, so the reader sees the layer set rather than a blank column.
renderLayers();
