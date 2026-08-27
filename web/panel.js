/* The layer panel: one row per layer - name, box, chip - with everything else one tap
 * away behind the row's chevron (frontend3 02: a control is a control).
 *
 * The Cell FILL rows are RADIOS in one group so two ramps on one geography cannot even be
 * asked for; everything else is a checkbox. A gated row is DARK, not missing: the box is
 * disabled and the reason prints in the row's detail, so absence is explained rather than
 * mysterious - the chip itself never leaves the default row.
 *
 * THE DETAIL STATE IS MODULE STATE, NOT DOM STATE. renderLayers() rewrites the rows'
 * innerHTML on six events (every toggle, view switch, hour switch, scenario change, boot,
 * and every 30 s while the live toggle is on), so an open detail held only as a DOM
 * attribute would slam shut on the next rebuild. `openDet` is the one home; rowHTML()
 * re-emits `hidden`/`aria-expanded` from it, and the delegated click in app.js (every
 * listener lives there) flips it through toggleDet(). The live row's chevron is STATIC
 * markup in index.html; renderLayers() syncs its detail from the same Set.
 */
import { $, L, LAYERS, map, on, shut, styled } from "./layers.js";
import { fmtAge, forget, load, srcState, worst } from "./freshness.js";

const chipHTML = (state) => `<span class="st st-${state}">${state}</span>`;

// which rows' details are open, keyed by layer id - survives every innerHTML rebuild
export const openDet = new Set();
export function toggleDet(id) {
  if (openDet.has(id)) openDet.delete(id); else openDet.add(id);
  renderLayers();
}

/* frontend2 03: a layer may offer an EXCLUSIVE CHOICE inside its own row (`lyr.opts`, the
 * flood zones' scenario). It is a second radio GROUP, not a second member of the Cell-fill
 * radio - `fill: true` is still exactly {cells, impact} and the frozen channel is
 * untouched. The options are set by the layer's own draw from the payload it fetched, so a
 * scenario appearing in the data appears here with no code change. */
const optsHTML = (lyr) => !lyr.opts || !lyr.opts.length ? "" :
  `<div class="opts" role="radiogroup" aria-label="${lyr.name}">` + lyr.opts.map(o =>
    `<label class="note"><input type="radio" name="${lyr.id}-opt" data-sc="${o.id}"
       ${o.id === lyr.opt ? "checked" : ""} ${styled ? "" : "disabled"}>
     <span>${o.label}</span></label>`).join("") + `</div>`;

/* THE OFF OPTION, and it is what makes D1's other half reachable at all. A radio cannot be
 * un-checked by clicking it, and today the only other fill option (`impact`) is gated and
 * therefore disabled - so without this row the Cell fill could never be turned off, the
 * flood zones could never fill, and the route line could never carry the ramp. It declares
 * no layer and claims no channel - so it gets NO chip and NO detail (a chip here would be
 * a sixth meaning for the frozen five-state vocabulary): it just clears whichever fill is
 * lit. */
const noFillHTML = () => `<div class="lyr"><div class="lrow"><label><input type="radio" name="cellfill"
    data-nofill="1" ${LAYERS.some(l => l.fill && on[l.id]) ? "" : "checked"}
    ${styled ? "" : "disabled"}>
    <span class="nm">None &mdash; show the geography instead</span></label></div>
  <p class="note sub">With the fill off, zones and routes carry the ramp.</p></div>`;

export function srcRows(lyr) {
  return lyr.srcs.map(s => {
    const st = srcState(lyr, s);
    const age = st.age === undefined ? "" : fmtAge(st.age) + " ";
    return `<div class="src"><b>${s.k}</b><span>${age}${chipHTML(st.s)}${st.why
      ? ` <span class="why">${st.why}</span>` : ""}</span></div>`;
  }).join("");
}

export function rowHTML(lyr) {
  const dark = shut(lyr);
  const kind = lyr.fill ? "radio" : "checkbox";
  const open = openDet.has(lyr.id);
  const owed = lyr.owed && !dark
    ? `<p class="note">Declared and dark: ${lyr.owed} lands this payload.</p>` : "";
  const gate = dark
    ? `<p class="note">Dark: needs the MTA terms verified. The row stays so the page never
       pretends the layer does not exist.</p>` : "";
  return `<div class="lyr${dark ? " gated" : ""}">
    <div class="lrow"><label><input type="${kind}" ${lyr.fill ? 'name="cellfill"' : ""} data-l="${lyr.id}"
      ${on[lyr.id] ? "checked" : ""} ${dark || !styled ? "disabled" : ""}>
      <span class="nm">${lyr.name}</span></label>${chipHTML(worst(lyr))}
    <button type="button" class="chev" data-det="${lyr.id}" aria-expanded="${open}"
      aria-label="${lyr.name} detail">&rsaquo;</button></div>
    ${lyr.sub ? `<p class="note sub">${lyr.sub}</p>` : ""}
    <div class="det" ${open ? "" : "hidden"}>${srcRows(lyr)}${lyr.det
      ? `<p class="note">${lyr.det}</p>` : ""}${gate}${owed}</div>
    ${on[lyr.id] ? optsHTML(lyr) + (lyr.legend || "") : ""}</div>`;
}

/* Rebuilding the rows destroys the control the reader just activated and focus falls to
 * <body> - a keyboard user would tab through the map and every other row again on each
 * toggle. This is the same restore the hour buttons use in setHour() below, and it is the
 * whole reason that mechanism exists; the chevrons get the same treatment. */
export function renderLayers() {
  const a = document.activeElement;
  const keep = a && a.dataset ? a.dataset.l : undefined;
  $("layers-fill").innerHTML = LAYERS.filter(l => l.fill).map(rowHTML).join("") + noFillHTML();
  $("layers-pts").innerHTML =
    LAYERS.filter(l => !l.fill && !l.toggle).map(rowHTML).join("");
  // the live fleet's row is STATIC markup in index.html: it owns the 30 s interval, its
  // own readout and #livetoggle. Only its freshness rows, its chip and its detail's
  // open state are rendered here - the detail follows the same openDet Set.
  const live = L("live");
  $("src-live").innerHTML = srcRows(live) + (shut(live)
    ? `<p class="note">Dark: the vehicle gate side is shut, so the fleet is not published
       on this host. The toggle stays. (Locally, <code>make live-export</code> feeds it.)</p>` : "");
  $("live-chip").innerHTML = chipHTML(worst(live));
  $("det-live").hidden = !openDet.has("live");
  const lchev = document.querySelector('#layers [data-det="live"]');
  if (lchev) lchev.setAttribute("aria-expanded", String(openDet.has("live")));
  if (keep !== undefined) {
    const b = document.querySelector(`#layers [data-l="${keep}"]`);
    if (b) b.focus();
  } else if (a && a.dataset && a.dataset.det !== undefined) {
    // the chevron the reader just clicked was rebuilt with its row - refocus it
    const b = document.querySelector(`#layers [data-det="${a.dataset.det}"]`);
    if (b) b.focus();
  } else if (a && a.dataset && a.dataset.sc !== undefined) {
    // the scenario radios are rebuilt too, so they need the same restore the layer rows get
    const b = document.querySelector(`#layers [data-sc="${a.dataset.sc}"]`);
    if (b) b.focus();
  }
}

export function applyVisibility() {
  if (!styled) return;
  for (const lyr of LAYERS) {
    const lit = on[lyr.id] && !shut(lyr) ? "visible" : "none";
    lyr.map.forEach(id => map.setLayoutProperty(id, "visibility", lit));
  }
}

export async function toggle(id, want) {
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
