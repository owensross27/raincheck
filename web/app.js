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
 *   basemap.js    the vector basemap: the vendored dark style spliced in above `bg` and
 *                 below all twelve, the pmtiles protocol, and the fall back to `bg`.
 *   app.js        this file: boot.
 *
 * frontend2 03 added no module: the geography layers are LAYERS entries in layers.js, their
 * paint and their draw are in insight.js beside the Cell fill's, and their two controls -
 * the scenario radio and the Cell-fill OFF option - are delegated from here like every
 * other control on this page. `applyRamp()` runs after anything that can change which fill
 * is lit, which is D1's one-ramp rule.
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
import { applyVisibility, renderLayers, toggle, toggleDet } from "./panel.js";
import { applyRamp, closeCard, loadRecent, locateEvent, pointTip, setHour, setScenario, setView,
         showCard, showTip } from "./insight.js";
import { toggleLive } from "./live.js";

map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
// NO AttributionControl (frontend3 02): at 375 the compact control rendered EXPANDED over
// the map strip, duplicating the credit strip below - and the strip is now fixed at the
// viewport bottom at every width, so the OSMF adjacency requirement is met without it.
// Its customAttribution credits were collapsed, never deleted: they live in the #info
// dialog (the nycbuspositions archive credit existed nowhere else on the page).

// delegated, because the rows are rebuilt: #layers itself is the stable element. Three
// controls live inside it now - the layer boxes, frontend2 03's scenario radio and its
// Cell-fill OFF option - and all three are read off the target's own data attribute.
$("layers").addEventListener("change", async e => {
  const d = e.target.dataset || {};
  if (d.l) { await toggle(d.l, e.target.checked); applyRamp(); return; }
  if (d.sc) { await setScenario(d.sc); renderLayers(); return; }
  if (d.nofill) {
    // clear whichever fill is lit; toggle() already forgets its sources, re-applies
    // visibility and re-renders the rows, so the OFF row is the one left checked
    const lit = LAYERS.find(l => l.fill && on[l.id]);
    if (lit) await toggle(lit.id, false); else renderLayers();
    applyRamp();
  }
});

// the per-row detail chevrons (frontend3 02), delegated like every other row control: the
// rows are rebuilt on six events, so the OPEN state lives in panel.js's openDet Set and
// rowHTML re-emits it - a DOM-held state would slam shut on every 30 s live tick. The
// live row's chevron is static markup; same Set, same handler.
$("layers").addEventListener("click", e => {
  const b = e.target.closest ? e.target.closest("#layers [data-det]") : null;
  if (b) toggleDet(b.dataset.det);
});

// the info dialog (frontend3 02): a native <dialog> - focus trap, Esc and ::backdrop come
// from the platform - and NOT a second <details>: the analyst disclosure stays the page's
// one. A click on the dialog element itself is a click on the backdrop.
$("info-btn").addEventListener("click", () => $("info").showModal());
$("info-close").addEventListener("click", () => $("info").close());
$("info").addEventListener("click", e => { if (e.target === $("info")) $("info").close(); });

// renderLayers() after a view or hour switch: frontend2 03's route row explains WHY its
// lines are grey on the view that is showing, and that sentence changes with the view.
$("views").addEventListener("click", e => {
  if (e.target.dataset.v) { setView(e.target.dataset.v); renderLayers(); } });
$("hours").addEventListener("click", e => {
  if (e.target.dataset.h) { setHour(e.target.dataset.h); renderLayers(); } });

map.on("mousemove", "cells", showTip);
map.on("click", "cells", showTip);          // touch
map.on("mouseleave", "cells", () => { $("tip").style.display = "none"; });

// frontend4 02: one hover mechanism (insight.pointTip), wired here for the four point
// layers that answered only to click (hist) or not at all (subway, mta, fn). Click is the
// touch path, the cells tooltip's own pattern above. Registered BEFORE hist's own
// click -> showCard handler below, so on a hist tap the tip paints first and the card
// handler's `#tip` hide runs after - a tap lands on the card, never a stale tip.
for (const id of ["hist", "subway", "mta", "fn"]) {
  const tip = pointTip(id);
  map.on("mousemove", id, tip);
  map.on("click", id, tip);
  map.on("mouseleave", id, () => { $("tip").style.display = "none"; });
}

// frontend 07: the record card opens on CLICK, never hover (touch parity), and the Cell
// tooltip is hidden so the two cannot stack on one marker. Close returns focus to the
// hist toggle row (insight.closeCard); Escape works anywhere while the card is open.
map.on("click", "hist", (e) => {
  $("tip").style.display = "none";
  showCard(e.features[0].properties);
});
$("card-close").addEventListener("click", closeCard);
addEventListener("keydown", (e) => { if (e.key === "Escape") closeCard(); });

// `load`, not `styledata`: styledata fires while isStyleLoaded() is still false and every
// setPaintProperty / setLayoutProperty below still throws "Style is not done loading".
map.on("load", async () => {
  markStyled();
  for (const lyr of LAYERS) if (on[lyr.id] && lyr.draw) await load(lyr.id);
  applyVisibility();
  applyRamp();
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

// frontend2 05 (D7): ONE disclosure holds everything analyst-grade, default CLOSED.
// The reader's choice is remembered per browser; localStorage can throw (private
// windows, storage-blocking settings), so BOTH sides are guarded and an absent or
// unreadable value means closed - the rider default, never the analyst one.
try { $("analyst").open = localStorage.getItem("raincheck.analyst") === "open"; } catch {}
$("analyst").addEventListener("toggle", () => {
  try { localStorage.setItem("raincheck.analyst", $("analyst").open ? "open" : "closed"); }
  catch {}
});

// the rider's recent-flooding rows ring their Cells on the map (prototype variant C's
// hover-locate). focusin/focusout give a keyboard - and a tap, which focuses the row -
// the same ring hover gives a mouse. Delegated: the rows are rebuilt by loadRecent().
const recRow = (t) => t && t.closest ? t.closest("#recent [data-ev]") : null;
$("recent").addEventListener("mouseover", e => {
  const r = recRow(e.target); if (r) locateEvent(Number(r.dataset.ev)); });
// mouseleave, NOT mouseout: mouseout bubbles from every child-to-child move inside the
// list, so each row-to-row hover cleared and re-set the locate ring (frontend2 05's
// filed nit); mouseleave fires only when the pointer leaves the list itself.
$("recent").addEventListener("mouseleave", () => locateEvent(null));
$("recent").addEventListener("focusin", e => {
  const r = recRow(e.target); if (r) locateEvent(Number(r.dataset.ev)); });
$("recent").addEventListener("focusout", () => locateEvent(null));

// the list itself needs no map, so it is not gated on `load`; 32,924 B raw, dated
// through grab() like every other payload
loadRecent();

// first paint of the panel itself: the rows exist before the map is loaded, with
// every control disabled, so the reader sees the layer set rather than a blank column.
renderLayers();
