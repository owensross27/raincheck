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
import { $, LAYERS, map, markStyled, on, shut, styled } from "./layers.js";
import { initChat } from "./chat.js";
import { load } from "./freshness.js";
import { applyVisibility, openDet, renderLayers, toggle, toggleDet } from "./panel.js";
import { applyRamp, cellFeatures, closeCard, loadRecent, locateEvent, pinEvent,
         pinnedEvent, pointTip, recentFilterState, setHourIndex, setRecentBorough,
         setRecentZone, setScenario, setView, showCard, showTip } from "./insight.js";
import { toggleLive } from "./live.js";

// NO NavigationControl either (Ross, 2026-09-01): scroll/pinch/double-tap zoom cover it,
// and the buttons were the only chrome floating over the map face.
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

// frontend5 01 MUST 2: the ground group's own open state, remembered the same way the row
// chevrons are - the browser toggles the native <details> itself (no click handler needed
// for that half), this only SYNCS openDet so the next rebuild renders it the way the
// reader left it. Capture, not bubble: the element is destroyed and recreated on every
// renderLayers() call, so only delegation from a container that survives the rebuild can
// ever see this event, and capture catches it on the way down regardless of whether
// "toggle" bubbles in a given engine.
$("layers").addEventListener("toggle", e => {
  if (e.target.id !== "ground-layers") return;
  if (e.target.open) openDet.add("ground"); else openDet.delete("ground");
}, true);

// the info dialog (frontend3 02): a native <dialog> - focus trap, Esc and ::backdrop come
// from the platform - and NOT a second <details>: the analyst disclosure stays the page's
// one. A click on the dialog element itself is a click on the backdrop.
$("info-btn").addEventListener("click", () => $("info").showModal());
$("info-close").addEventListener("click", () => $("info").close());
$("info").addEventListener("click", e => { if (e.target === $("info")) $("info").close(); });

// renderLayers() after a view or hour switch: frontend2 03's route row explains WHY its
// lines are grey on the view that is showing, and that sentence changes with the view.
// frontend5 03: the view picker is a <select> and the hours are a range input - both
// delegated from their stable containers because insight.js rebuilds the controls.
$("views").addEventListener("change", e => {
  if (e.target.id === "views-sel") { setView(e.target.value); renderLayers(); } });
$("hours").addEventListener("input", e => {
  if (e.target.id === "hour-range") { setHourIndex(e.target.valueAsNumber); renderLayers(); } });

/* frontend5 03: the MODE BAR - a mode is a named layer set, switched through the same
 * toggle()/toggleLive() every checkbox uses, so gates, freshness rows and the one-ramp
 * rule all apply unchanged. The drawer keeps the full per-layer controls reachable. */
// storms: the delay answer. history: everything flood-record (the MTA flood tier included).
// live: the fleet ONLY. The impact overlays are deliberately NOT in the live set: nothing
// republishes the impact family on a schedule yet, so their newest hour can be half a day
// old - and a stale hour painted under a "Live now" button is exactly the lie "nothing can
// look live when it is not" exists to prevent. They stay in the drawer, chips honest,
// opt-in. Put them back here the day the impact tick publishes hourly.
const MODE_SET = { storms: ["cells"],
                   history: ["hist", "fn", "stormwater", "mta"],
                   live: [] };
const MODE_MANAGED = [...new Set(Object.values(MODE_SET).flat())];
// the h1 answers per mode (UI round item 8, Ross 2026-09-01): the storm question is the
// page's thesis, but #answer is hidden outside storms (app.css) and a heading that asks
// what the mode below it never answers reads as a broken promise. The storms string is
// also index.html's static h1, so a pre-JS paint and the storms mode agree.
const MODE_H1 = { storms: "Does rain slow the NYC buses, and where?",
                  history: "Where has flooding hit buses and subways?",
                  live: "How are the buses doing right now?" };
async function setMode(m) {
  document.body.dataset.mode = m;
  $("insight-h").textContent = MODE_H1[m];
  for (const b of document.querySelectorAll("#modes button"))
    b.setAttribute("aria-pressed", String(b.dataset.m === m));
  if (!styled) return;         // boot re-applies the mode once the style is loaded
  const want = MODE_SET[m];
  for (const m_id of MODE_MANAGED)
    if (Boolean(on[m_id]) !== want.includes(m_id)) await toggle(m_id, want.includes(m_id));
  const liveOn = m === "live";
  if (!$("livetoggle").disabled && $("livetoggle").checked !== liveOn) {
    $("livetoggle").checked = liveOn;
    toggleLive(liveOn);
  }
  applyRamp(); renderLayers();
}
$("modes").addEventListener("click", e => {
  if (e.target.dataset.m) setMode(e.target.dataset.m);
});
$("layers-btn").addEventListener("click", () => {
  const open = document.body.classList.toggle("drawer-open");
  $("layers-btn").setAttribute("aria-expanded", String(open));
  // under 900px the columns are position:static, so the drawer opens BELOW the whole
  // insight column - off-screen. Scroll to it or the button appears to do nothing.
  if (open) $("right").scrollIntoView({ behavior: "smooth", block: "start" });
});

map.on("mousemove", "cells", showTip);
map.on("click", "cells", showTip);          // touch
map.on("mouseenter", "cells", () => { map.getCanvas().style.cursor = "pointer"; });
map.on("mouseleave", "cells", () => {
  $("tip").style.display = "none"; map.getCanvas().style.cursor = "";
});

// frontend4 02: one hover mechanism (insight.pointTip), wired here for the point layers
// that answered only to click (hist) or not at all (subway, mta, fn). Click is the
// touch path, the cells tooltip's own pattern above. Registered BEFORE hist's own
// click -> showCard handler below, so on a hist tap the tip paints first and the card
// handler's `#tip` hide runs after - a tap lands on the card, never a stale tip.
// frontend4 04 adds `live`, the same way: a layer-scoped handler never fires while the
// fleet toggle is off, so no gate/toggle guard is needed here either.
for (const id of ["hist", "subway", "mta", "fn", "live"]) {
  const tip = pointTip(id);
  map.on("mousemove", id, tip);
  map.on("click", id, tip);
  map.on("mouseenter", id, () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", id, () => {
    $("tip").style.display = "none"; map.getCanvas().style.cursor = "";
  });
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
  // frontend5 03: the MODE runs FIRST - it settles which layers are on before anything
  // fetches, so a layer that boots `open: true` but sits outside the default mode's set
  // (subway, mta, on a host whose gate is open) is turned off BEFORE its payload is
  // fetched and drawn - no wasted fetch, no flash of dots that then vanish. toggle()
  // loads whatever the mode turns on; the loop below loads the rest (the basemap).
  await setMode(document.body.dataset.mode || "storms");
  for (const lyr of LAYERS)
    if (on[lyr.id] && lyr.draw && !MODE_MANAGED.includes(lyr.id)) await load(lyr.id);
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
// filed nit); mouseleave fires only when the pointer leaves the list itself. The clear
// falls back to the PINNED event: a hover is a preview laid over a choice, never its end.
$("recent").addEventListener("mouseleave", () => locateEvent(pinnedEvent()));
$("recent").addEventListener("focusin", e => {
  const r = recRow(e.target); if (r) locateEvent(Number(r.dataset.ev)); });
$("recent").addEventListener("focusout", () => locateEvent(pinnedEvent()));
// clicks, one delegation: a row pins its ring (click again to unpin), a borough chip
// filters and zooms, a neighborhood chip drills in (the rows rebuild under all three)
$("recent").addEventListener("click", e => {
  const b = e.target.closest ? e.target.closest("#rec-chips [data-b]") : null;
  if (b) return setRecentBorough(b.dataset.b);
  const z = e.target.closest ? e.target.closest("#rec-zones [data-z]") : null;
  if (z) return setRecentZone(z.dataset.z);
  const r = recRow(e.target);
  if (r) pinEvent(Number(r.dataset.ev));
});
// the event timeline: each slider stop pins that event (input, so a drag scrubs live)
$("recent").addEventListener("input", e => {
  if (e.target.id !== "rec-slider") return;
  const order = e.target.dataset.order.split(",").map(Number);
  const i = order[Number(e.target.value)];
  if (i !== pinnedEvent()) pinEvent(i);
});

// the list itself needs no map, so it is not gated on `load`; 32,924 B raw, dated
// through grab() like every other payload
loadRecent();

// first paint of the panel itself: the rows exist before the map is loaded, with
// every control disabled, so the reader sees the layer set rather than a blank column.
renderLayers();

/* "Ask the map" (chat-integration ticket): the registry chat.js drives. Every entry is a
 * thin wrapper over a function this file already imports or defines - chat.js never
 * touches layers.js, insight.js or panel.js directly, which is the whole point of the
 * registry seam (it can be unit-tested / swapped without chat.js knowing anything changed).
 */
async function queryData(path) {
  // the ONE safety rule the read-API contract requires of any consumer: this is a read
  // of the PUBLIC static surface (docs/read-api-contract.md) and nothing else - never
  // app.js's own source, never a path outside the served tree.
  if (typeof path !== "string" || !path.startsWith("files/"))
    throw new Error('query_data: path must start with "files/"');
  const res = await fetch(path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`query_data: HTTP ${res.status} for ${path}`);
  // a directory path gets the stdlib server's HTML listing - name the mistake instead
  // of letting JSON.parse throw "Unexpected token '<'" (measured: the model's first
  // instinct on a truncated payload was to query "files/history/", a directory)
  if (!/json|geo/.test(res.headers.get("content-type") || ""))
    throw new Error(`query_data: ${path} is not a JSON file - one FILE per call, `
      + `never a directory (files/index.json lists what exists)`);
  // the chat's VIEW of the payload, never the page's: long arrays (an event's ~100
  // member cells, a geojson's features) would eat the whole 4000-char tool budget and
  // truncate away the scalar fields the model actually reasons over. Collapsed to
  // their count; every scalar and short array survives.
  const prune = (v) => Array.isArray(v)
    ? (v.length > 24 ? `[${v.length} items, collapsed for chat]` : v.map(prune))
    : (v && typeof v === "object"
       ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, prune(x)])) : v);
  return prune(await res.json());
}

const chatRegistry = {
  set_mode: {
    description: "Switch the map's mode: storms (a past storm's bus slowdown), history " +
      "(the flood record) or live (the current fleet).",
    parameters: { type: "object",
      properties: { mode: { type: "string", enum: ["storms", "history", "live"] } },
      required: ["mode"] },
    run: async ({ mode }) => { await setMode(mode); return { mode }; },
  },
  list_layers: {
    description: "List every map layer: id, display name, whether it is currently on, " +
      "and whether it is gated (dark - needs the MTA terms verified, cannot be turned on).",
    parameters: { type: "object", properties: {} },
    run: async () => LAYERS.map(l => ({ id: l.id, name: l.name, on: Boolean(on[l.id]),
                                        gated: shut(l) })),
  },
  set_layer: {
    description: "Turn one map layer on or off by its id (call list_layers first for the " +
      "id list). A gated layer refuses silently - check `gated` before calling this.",
    parameters: { type: "object",
      properties: { id: { type: "string" }, on: { type: "boolean" } },
      required: ["id", "on"] },
    run: async ({ id, on: want }) => { await toggle(id, want); applyRamp(); return { id, on: want }; },
  },
  query_data: {
    description: "Fetch one JSON file from the site's static read API - a FILE path under " +
      "files/, never a directory. Start from files/index.json to discover what's " +
      "published, or files/summary/recent.json for the recent-flooding list. Arrays " +
      "longer than 24 come back collapsed to their count; scalar fields all survive.",
    parameters: { type: "object", properties: { path: { type: "string" } },
      required: ["path"] },
    run: async ({ path }) => queryData(path),
  },
  locate_event: {
    description: "Ring one recent flood event's Cells on the map by its index in " +
      "files/summary/recent.json's events array (0 = newest). Call with a negative " +
      "number or omit to clear the ring.",
    parameters: { type: "object", properties: { index: { type: "number" } },
      required: ["index"] },
    run: async ({ index }) => { locateEvent(index >= 0 ? index : null); return { located: index }; },
  },
  filter_flood_record: {
    description: "Filter the flood-record list by borough, and optionally one " +
      "neighborhood inside it (exact TLC zone name). Empty strings clear the filter. " +
      "Switches the map to history mode, applies the page's own chips, zooms to the " +
      "area, and RETURNS the matching events plus the borough's neighborhoods ranked " +
      "by how many events touched them - filter by borough first and use the returned " +
      "neighborhood names for a tighter follow-up call.",
    parameters: { type: "object", properties: {
      borough: { type: "string",
        enum: ["", "Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"] },
      neighborhood: { type: "string" } },
      required: ["borough"] },
    run: async ({ borough, neighborhood }) => {
      if (document.body.dataset.mode !== "history") await setMode("history");
      // the borough/zone join reads cells.geojson; without it the filters are inert
      // (MEASURED: the tool filtered to zero before the payload landed). The fetch is
      // what matters - on a map that cannot draw yet, the draw may throw after the
      // data is in, which is fine here.
      if (!cellFeatures().length) { try { await load("cells"); } catch { /* data landed */ } }
      await setRecentBorough(borough || "");
      if (neighborhood) await setRecentZone(neighborhood);
      return recentFilterState();
    },
  },
  set_view: {
    description: "Select which storm or time-period view the Cell fill and curve show - " +
      "one of the options in the page's own view picker (#views-sel): typically \"ida\" " +
      "(Ida 2021), \"f23\" (the 2023-09-29 flood), \"w1\"/\"w1d\" or \"w2\"/\"w2d\" (the " +
      "two wet-vs-dry windows and their dry-speed baselines) - not all are published on " +
      "every host, and only the cells layer's own data determines which exist. Only " +
      "meaningful in storms mode; call set_mode first if the map is in another mode.",
    parameters: { type: "object", properties: { id: { type: "string" } }, required: ["id"] },
    run: async ({ id }) => { setView(id); renderLayers(); return { view: id }; },
  },
};

initChat(chatRegistry);
