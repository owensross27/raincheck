/* The layer panel: one row per layer, its own freshness rows underneath it.
 *
 * The Cell FILL rows are RADIOS in one group so two ramps on one geography cannot even be
 * asked for; everything else is a checkbox. A gated row is DARK, not missing: the box is
 * disabled and the reason is printed, so absence is explained rather than mysterious.
 */
import { $, L, LAYERS, map, on, shut, styled } from "./layers.js";
import { fmtAge, forget, load, srcState, worst } from "./freshness.js";

const chipHTML = (state) => `<span class="st st-${state}">${state}</span>`;

export function srcRows(lyr) {
  return lyr.srcs.map(s => {
    const st = srcState(lyr, s);
    const age = st.age === undefined ? "" : fmtAge(st.age) + " ";
    return `<div class="src"><b>${s.k}</b><span>${age}${chipHTML(st.s)}</span></div>` +
      (st.why ? `<div class="src why"><span>${st.why}</span></div>` : "");
  }).join("");
}

export function rowHTML(lyr) {
  const dark = shut(lyr);
  const kind = lyr.fill ? "radio" : "checkbox";
  const owed = lyr.owed && !dark
    ? `<p class="note">Declared and dark: ${lyr.owed} lands this payload.</p>` : "";
  const gate = dark
    ? `<p class="note">Dark: publishing anything on this gate side needs the MTA
       redistribution terms verified. The row stays, so the page never pretends the layer
       does not exist.</p>` : "";
  return `<div class="lyr${dark ? " gated" : ""}">
    <label><input type="${kind}" ${lyr.fill ? 'name="cellfill"' : ""} data-l="${lyr.id}"
      ${on[lyr.id] ? "checked" : ""} ${dark || !styled ? "disabled" : ""}>
      <span class="nm">${lyr.name}</span>${chipHTML(worst(lyr))}</label>
    ${srcRows(lyr)}${gate}${owed}</div>`;
}

/* Rebuilding the rows destroys the control the reader just activated and focus falls to
 * <body> - a keyboard user would tab through the map and every other row again on each
 * toggle. This is the same restore the hour buttons use in setHour() below, and it is the
 * whole reason that mechanism exists. */
export function renderLayers() {
  const a = document.activeElement;
  const keep = a && a.dataset ? a.dataset.l : undefined;
  $("layers-fill").innerHTML = LAYERS.filter(l => l.fill).map(rowHTML).join("");
  $("layers-pts").innerHTML =
    LAYERS.filter(l => !l.fill && !l.toggle).map(rowHTML).join("");
  // the live fleet's row is the Live panel: it owns the 30 s interval and its own readout,
  // and #livetoggle is its checkbox. Only its freshness rows are rendered here.
  const live = L("live");
  $("src-live").innerHTML = srcRows(live) + (shut(live)
    ? `<p class="note">Dark: the vehicle side of the MTA gate is shut, so the fleet is not
       published on this host. The toggle stays: locally, <code>make live-export</code>
       writes the two files and the panel reads them.</p>` : "");
  $("live-chip").innerHTML = chipHTML(worst(live));
  if (keep !== undefined) {
    const b = document.querySelector(`#layers [data-l="${keep}"]`);
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
