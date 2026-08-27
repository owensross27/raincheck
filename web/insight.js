/* The insight view (ticket 13): the paint, the headline, the curve, the view/hour
 * switching, the Cell tooltip, and the boot draw that builds all of them from
 * cells.geojson + headline.json.
 *
 * frontend2 03 added the GEOGRAPHY half at the bottom of this file - drawZones,
 * setScenario and applyRamp - because it is a PAINT rule and this is where paint lives.
 * `applyRamp()` is DESTINATION-PLAN D1's "one ramp on screen at a time", enforced on the
 * paint expressions rather than promised in prose: it reads the same `activeProp()` and the
 * same `colorExpr()` the Cell fill uses, which is what makes "the route line shows the SAME
 * estimand as the fill, restricted to one route" true by construction. It is called from
 * paint() (a view or hour switch re-colours the line) and from app.js (a toggle changes
 * which fill is lit).
 */
import { $, fmt, GREY, L, LAYERS, map, on, RATIO_STOPS, ROUTE_PLAIN, ROUTE_W_RAMP,
         ROUTE_W_THIN, shut, SPEED_STOPS, styled, ZONE_FILL_OPACITY,
         ZONE_LEGEND } from "./layers.js";
import { ages, fmtAge, grab, whys } from "./freshness.js";

let head = null;         // headline.json
let cellKeys = new Set();  // property keys present in cells.geojson
let views = [];
let view = null;         // the active view object
let hourKey = null;      // active storm-hour key (MMDDHH) or null

// ---------------------------------------------------------------- paint and legend
// absent -> grey, per spec L. The `absent` colour is a parameter because the same MEANING
// needs a different value on a line: GREY (#3a4049) is calibrated to recede among coloured
// Cell fills and disappears entirely as a hairline on the dark basemap, so a route with no
// publishable number would read as no route at all (measured in a real tab). ROUTE_PLAIN is
// the hue that already means "geometry, no number" - one meaning, two marks.
function colorExpr(prop, stops, absent = GREY) {
  const interp = ["interpolate", ["linear"], ["get", prop]];
  stops.forEach(([v, c]) => interp.push(v, c));
  return ["case", ["!", ["has", prop]], absent, interp];
}

const activeProp = () => (view.hours ? "r" + hourKey : view.prop);

function paint() {
  const s = view.kind === "speed" ? SPEED_STOPS : RATIO_STOPS;
  map.setPaintProperty("cells", "fill-color", colorExpr(activeProp(), s));
  $("swatches").innerHTML = s.map(([, c]) => `<span style="background:${c}"></span>`).join("");
  $("legend-title").textContent = view.kind === "speed"
    ? "Dry baseline Speed, m/s" : "Speed ratio, wet over dry";
  $("tick-lo").textContent = s[0][0] + (view.kind === "speed" ? " m/s" : " slower");
  $("tick-mid").textContent = view.kind === "speed" ? "" : "1.0 no change";
  $("tick-hi").textContent = s[s.length - 1][0] + (view.kind === "speed" ? " m/s" : " faster");
  const row = currentRow();
  $("legend-estimand").textContent = view.kind === "speed"
    ? "space-mean chord Speed over the window's dry Cell-hours (dry = mm_1h < 0.1, mm_1h_prev < 0.1, mm_6h < 0.5), rule set R2"
    : (row ? row.median_cell_estimand : "");
  applyRamp();   // the route line follows the view it is showing (D1)
}

// ---------------------------------------------------------------- headline rendering
const currentRow = () => head.rows.find(r =>
  r.layer === view.layer && (view.hours ? r.key === hourKey : true));

function renderHeadline() {
  const r = currentRow();
  if (!r) { $("headline").innerHTML = ""; $("answer").innerHTML = ""; return; }
  const bandLo = Math.min(r.band[0], r.band[1]), bandHi = Math.max(r.band[0], r.band[1]);
  // frontend2 05: the rider's one-line answer - the published band value with a plain
  // gloss, no interval and no estimand (both sit in the analyst disclosure, verbatim)
  $("answer").innerHTML = `<div class="big">${fmt(bandLo)}&ndash;${fmt(bandHi)}</div>
    <div class="band">how fast the buses moved in this rain, as a share of their
      dry-weather Speed &mdash; 1.00 means no change (${view.label})</div>`;
  // spec L requires the panel to state that the 2023-09-29 band reaches ~1.0. That is a
  // property of the STORM, not of the selected Hour: band() collapses to a point whenever
  // both arms sit in one chord class, so an hour-local test would hide the statement on
  // most hours of exactly the storm it is required for. It is therefore taken over the
  // Hours that MEASURE a slowdown - an Hour whose measured ratio is already above 1.0 has
  // a band reaching 1.0 trivially and says nothing about chord bias.
  const slow = head.rows.filter(x => x.layer === r.layer && x.value < 0.98);
  const layerHi = slow.length ? Math.max(...slow.map(x => Math.max(x.band[0], x.band[1]))) : 0;
  const bandNear1 = layerHi >= 0.98 && r.value < 1.0;
  const parts = [];

  parts.push(`<div class="row">
    <div class="big">${fmt(bandLo)}&ndash;${fmt(bandHi)}</div>
    <div class="band">citywide Speed ratio (chord band), 95% CI [${fmt(r.lo, 3)}, ${fmt(r.hi, 3)}]
      &middot; ${r.n_legs.toLocaleString()} Legs</div>
    <p class="note">${r.estimand}</p>
    ${bandNear1 ? `<p class="note warn">Across this layer the chord-corrected band reaches
       ${fmt(layerHi)}: this storm's slowdown is not separable from chord bias.</p>` : ""}</div>`);

  parts.push(`<div class="row">
    <div class="big">${fmt(r.median_cell)}</div>
    <div class="band">median Cell &middot; ${r.n_cells} Cells shown,
      <b>${r.n_cells_hidden} hidden</b></div>
    <p class="note">${r.median_cell_estimand}</p></div>`);

  if (r.value_ex_preschool !== undefined && r.value_ex_preschool !== null) {
    parts.push(`<div class="row">
      <div class="band">${fmt(r.value_ex_preschool, 3)}
        [${fmt(r.lo_ex_preschool, 3)}, ${fmt(r.hi_ex_preschool, 3)}] excluding the pre-school weeks
        &middot; ${r.n_events} wet events, ${r.n_cell_hours.toLocaleString()} wet Cell-hours</div>
      <p class="note">${r.estimand_ex_preschool}</p>
      <p class="note">sensitivity, clustered by service day instead of wet event:
        [${fmt(r.sensitivity_day.lo, 3)}, ${fmt(r.sensitivity_day.hi, 3)}]
        over ${r.sensitivity_day.n_days} days.</p></div>`);
  }
  if (r.mm_1h_citywide_mean !== undefined && r.mm_1h_citywide_mean !== null) {
    parts.push(`<div class="row"><div class="band">${fmt(r.mm_1h_citywide_mean)} mm
      mean rain over the footprint this Hour (AORC, hour-ending)</div></div>`);
  }
  $("headline").innerHTML = parts.join("");
}

// -------------------------------------------------------------------- the curve
// Storm views: that storm's own hour-by-hour trajectory (the rain-lag story lives on the
// storm, not on a window-pooled lag curve). Window views: the pooled lag curves, which
// come out flat - shown because that flatness is the finding.
function renderCurve() {
  const W = 340, H = 96, PADL = 30, PADR = 8, PADT = 10, PADB = 18;
  let series, caption, xs;
  if (view.hours) {
    const rows = head.rows.filter(r => r.layer === view.layer).sort((a, b) => a.key < b.key ? -1 : 1);
    series = [{ name: "hour", pts: rows.map((r, i) => [i, r.value]), color: "#fc8d59" }];
    xs = rows.map(r => r.label.slice(-3));
    caption = `${view.label}: citywide Speed ratio by Hour` +
      (rows.length > view.hourKeys.length ? " (the tail beyond the map layers is the recovery)" : "");
  } else {
    const pick = (rain) => head.lag.filter(l => l.window === view.layer && l.rain === rain)
      .sort((a, b) => a.lag_h - b.lag_h);
    const all = pick("all"), heavy = pick("heavy");
    series = [{ name: "all", pts: all.map(l => [l.lag_h, l.ratio]), color: "#6baed6" },
              { name: "heavy", pts: heavy.map(l => [l.lag_h, l.ratio]), color: "#fc8d59" }];
    xs = all.map(l => String(l.lag_h));
    caption = `${view.label}: Speed ratio by Hours since the Cell's last wet Hour ` +
      `(blue: any rain ≥ 1 mm; orange: ≥ 10 mm). No interval is published for this curve - ` +
      `read its shape, not any single point.`;
  }
  const vals = series.flatMap(s => s.pts.map(p => p[1]));
  // fit the domain to the data (padded, always containing 1.0) rather than clamping into a
  // fixed band: a clamped point is drawn at the edge and reads as a real value
  const lo = Math.min(0.9, ...vals) - 0.03, hi = Math.max(1.05, ...vals) + 0.03;
  const n = Math.max(1, xs.length - 1);
  const X = (i) => PADL + (i / n) * (W - PADL - PADR);
  const Y = (v) => PADT + (1 - (v - lo) / (hi - lo)) * (H - PADT - PADB);
  const bits = [`<line x1="${PADL}" x2="${W - PADR}" y1="${Y(1)}" y2="${Y(1)}"
      stroke="#5a6472" stroke-dasharray="3 3"/>`,
    `<text x="2" y="${Y(1) + 4}" fill="#9aa4b2" font-size="10">1.0</text>`,
    `<text x="2" y="${Y(lo) + 4}" fill="#9aa4b2" font-size="10">${lo.toFixed(2)}</text>`];
  series.forEach(s => {
    if (!s.pts.length) return;
    const d = s.pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    bits.push(`<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2"/>`);
    s.pts.forEach(p => bits.push(
      `<circle cx="${X(p[0]).toFixed(1)}" cy="${Y(p[1]).toFixed(1)}" r="2.2" fill="${s.color}"/>`));
  });
  if (view.hours) {
    const idx = head.rows.filter(r => r.layer === view.layer)
      .sort((a, b) => a.key < b.key ? -1 : 1).findIndex(r => r.key === hourKey);
    if (idx >= 0) bits.push(`<line x1="${X(idx)}" x2="${X(idx)}" y1="${PADT}" y2="${H - PADB}"
      stroke="#8ecbff" stroke-width="1"/>`);
  }
  xs.forEach((t, i) => { if (xs.length < 14 || i % 2 === 0)
    bits.push(`<text x="${X(i)}" y="${H - 5}" fill="#9aa4b2" font-size="9" text-anchor="middle">${t}</text>`); });
  $("curve-svg").innerHTML = bits.join("");
  $("curve-cap").textContent = caption;
}

// ---------------------------------------------------------------- view switching
export function setHour(k) {
  const hadFocus = document.activeElement && document.activeElement.dataset
    && document.activeElement.dataset.h !== undefined;
  hourKey = k;
  drawHourButtons();
  // drawHourButtons() rebuilds #hours, so the button the user just activated is gone and
  // focus falls to <body>; a keyboard user would tab through the map and every layer
  // button again for each hour step. Put focus back where they left it.
  if (hadFocus) {
    const b = document.querySelector(`#hours button[data-h="${k}"]`);
    if (b) b.focus();
  }
  paint(); renderHeadline(); renderCurve();
}

function drawHourButtons() {
  if (!view.hours) { $("hours").innerHTML = ""; return; }
  $("hours").innerHTML = view.hourKeys.map(k => {
    const row = head.rows.find(r => r.layer === view.layer && r.key === k);
    return `<button type="button" data-h="${k}" aria-pressed="${k === hourKey}">${row.label.slice(-3)}</button>`;
  }).join("");
}

export function setView(id) {
  view = views.find(v => v.id === id);
  document.querySelectorAll("#views button").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.v === id)));
  hourKey = view.hours ? (view.hourKeys.includes(hourKey) ? hourKey : view.defaultHour) : null;
  drawHourButtons(); paint(); renderHeadline(); renderCurve();
}

function buildViews() {
  const storms = [["ida", "Ida 2021-09-02"], ["f23", "2023-09-29 flood"]];
  views = [];
  for (const [layer, label] of storms) {
    const keys = head.rows.filter(r => r.layer === layer && r.on_map).map(r => r.key).sort();
    if (!keys.length) continue;
    const worst = keys.reduce((a, k) =>   // open on the storm's own worst Hour
      head.rows.find(r => r.key === k).value < head.rows.find(r => r.key === a).value ? k : a);
    views.push({ id: layer, layer, label, kind: "ratio", hours: true,
                 hourKeys: keys, defaultHour: worst });
  }
  for (const w of ["w1", "w2"]) {
    if (head.rows.some(r => r.layer === w))
      views.push({ id: w, layer: w, label: `${w.toUpperCase()} wet vs dry`, kind: "ratio",
                   hours: false, prop: `${w}_ratio` });
    // the dry baseline is a Speed LEVEL straight off cells.geojson, so it is offered
    // whenever the property exists - it does not depend on the wet aggregation producing a row
    if (cellKeys.has(`${w}_dry`))
      views.push({ id: w + "d", layer: w, label: `${w.toUpperCase()} dry baseline`,
                   kind: "speed", hours: false, prop: `${w}_dry` });
  }
  $("views").innerHTML = views.map(v =>
    `<button type="button" data-v="${v.id}" aria-pressed="false">${v.label}</button>`).join("");
}

// ------------------------------------------------------------------------ tooltip
// Zone name comes from the Cell's own exported property (04's centroid rule), never from a
// hover-time hit test against the zones layer - a hit test is not the centroid rule.
export function showTip(e) {
  const tip = $("tip");
  const p = e.features[0].properties;
  const where = p.zone_name ? `${p.zone_name}, ${p.borough}` : "outside a taxi zone";
  let body;
  if (view.kind === "speed") {
    body = p[view.prop] !== undefined
      ? `dry Speed ${fmt(p[view.prop])} m/s over ${p[view.layer + "_ndry"]} dry Cell-hours`
      : "no dry baseline for this Cell";
  } else if (view.hours) {
    const k = hourKey;
    body = p["r" + k] !== undefined
      ? `ratio ${fmt(p["r" + k])} [${fmt(p["lo" + k], 3)}, ${fmt(p["hi" + k], 3)}]<br>` +
        `${p["n" + k]} Legs this Hour, ${p["d" + k]} dry Hours in the baseline bin`
      : "interval too wide to publish for this Hour";
    if (p["mm" + k] !== undefined) body += `<br>rain ${fmt(p["mm" + k])} mm this Hour (AORC)`;
    if (p["lag" + k] !== undefined) body += `, ${p["lag" + k]} h since this Cell's last wet Hour`;
  } else {
    const w = view.layer;
    body = p[w + "_ratio"] !== undefined
      ? `ratio ${fmt(p[w + "_ratio"])} [${fmt(p[w + "_lo"], 3)}, ${fmt(p[w + "_hi"], 3)}]<br>` +
        `${p[w + "_nwet"]} wet Cell-hours over ${p[w + "_nev"]} wet events`
      : "interval too wide to publish for this window";
    if (p[w + "_dry"] !== undefined) body += `<br>dry baseline ${fmt(p[w + "_dry"])} m/s`;
  }
  tip.style.display = "block";
  tip.style.left = Math.min(e.point.x + 14, window.innerWidth - 280) + "px";
  tip.style.top = (e.point.y + 14) + "px";
  // `body` is built from literals and rounded numbers, but `where` carries zone_name and
  // borough, which originate in the downloaded TLC shapefile - the one string here that
  // crosses a trust boundary. Set it as text, never as markup.
  tip.innerHTML = `<b></b>Cell ${p.cell}<br>${body}`;
  tip.querySelector("b").textContent = where;
}

// ------------------------------------------------------------------------- boot draw
export function drawCells(cells, h) {
  if (!cells || !h) {
    const msg = whys["cells/files/cells.geojson"] === "not published on this host"
      ? "the insight files are not published on this host."
      : "export files missing - run `make export` and reload.";
    $("preview-note").textContent = msg;
    // the disclosure ships closed, so the failure must also land on the rider surface -
    // a broken host cannot be a secret the analyst view keeps
    $("answer").textContent = msg;
    return;
  }
  head = h;
  map.getSource("cells").setData(cells);
  cells.features.forEach(f => Object.keys(f.properties).forEach(k => cellKeys.add(k)));
  $("preview-note").textContent = head.preview_note;
  $("note-chord").textContent = head.chord_note;
  $("note-hidden").textContent = head.hidden_note;
  $("note-gate").textContent = head.gate;
  $("prov-files").textContent =
    ` ${cells.features.length} footprint Cells; publish gate: 95% interval width < ${head.gate_width}.`;
  buildViews();
  setView(views[0].id);
}


/* ============================================ frontend2 03: the geography layers ======
 *
 * ONE RAMP ON SCREEN AT A TIME (DESTINATION-PLAN D1). The Cell fill is an exclusive radio
 * and it is frozen (frontend 02 D1); the flood zones are non-Cell polygons and the route
 * line is a separate channel, so neither JOINS that radio. What binds them to it is this:
 *
 *   a Cell fill is lit  ->  the zones render as OUTLINES (the fill goes to opacity 0) and
 *                           the route line is THIN and UNCOLOURED - geometry, no number
 *   no Cell fill is lit ->  the zones may FILL and the route line carries the ramp, on the
 *                           SAME property and with the SAME expression the fill would use
 *
 * The layer ORDER says the same thing a second way and neither is redundant: the geography
 * band sits below `cells`, so while the fill is lit it is physically behind an 0.86-opacity
 * paint over the whole footprint. The paint rule is what makes the intent legible and
 * testable; the order is what makes it true even if a paint call is missed.
 */
let scenarios = [];     // the manifest's rows, in the order `make geo` published them
let scenario = null;    // the selected scenario's name, kept across re-draws

/** D1, applied. Safe to call before a view exists (a 404 on cells.geojson leaves `view`
 *  null) and before MapLibre has parsed the style, which is when every paint call throws. */
/* ATTRIBUTION IS A CONDITION OF DISPLAYING THE DATA, so it is mounted while the data is on
 * screen and read OFF THE PAYLOAD rather than mirrored into this file. Both geo payloads
 * carry a top-level `attribution` member (`stormwater_extent.ATTRIBUTION` for DEP's,
 * web/geo.sql's for the route lines), and the repo's standing rule is that a page constant
 * mirroring a src/ constant pins the mirror to itself - so the strip prints what the file
 * says, and a wording change in the writer reaches the page with no page edit. `#provenance`
 * is mode-invariant and always mounted; this paragraph inside it fills when a geography
 * layer is on and empties when it is off, because with the layer off no DEP or GTFS
 * geometry is being displayed. textContent, never markup: it is a string from a payload. */
let routeAttr = "", zoneAttr = "";

function renderGeoAttribution() {
  const parts = [];
  if (on.routes && routeAttr) parts.push(routeAttr);
  if (on.stormwater && zoneAttr) parts.push(zoneAttr);
  $("geo-attribution").textContent = parts.join("  ");
}

/** The route layer's `draw`: the data, and the credit that travels with it. */
export function drawRoutes(body) {
  if (body) map.getSource("routes").setData(body);
  routeAttr = (body && body.attribution) || "";
  renderGeoAttribution();
}

export function applyRamp() {
  renderGeoAttribution();
  if (!styled) return;
  const fillOn = LAYERS.some(l => l.fill && on[l.id] && !shut(l));
  map.setPaintProperty("stormwater-fill", "fill-opacity", fillOn ? 0 : ZONE_FILL_OPACITY);
  const ramped = !fillOn && view !== null;
  map.setPaintProperty("routes", "line-color", ramped
    ? colorExpr(activeProp(), view.kind === "speed" ? SPEED_STOPS : RATIO_STOPS, ROUTE_PLAIN)
    : ROUTE_PLAIN);
  map.setPaintProperty("routes", "line-width", ramped ? ROUTE_W_RAMP : ROUTE_W_THIN);
  // SAY WHY THE LINES ARE GREY, because there are two different reasons and only one of
  // them is the reader's to change. A route feature carries the two WINDOW estimands and
  // no storm-hour ones - a single Hour at route grain has no interval anyone could publish
  // - so on a storm view every line is honestly grey, and without this note that reads as
  // a broken layer rather than as an absent number. Found in the node harness, not by eye.
  L("routes").legend = !view ? "" : fillOn
    ? `<p class="note">A Cell fill is on, so these are geometry only: one ramp on screen at
       a time. Choose <b>None</b> in the Cell fill group to colour them.</p>`
    : view.hours
    ? `<p class="note">The <b>${view.label}</b> view is a single storm HOUR, and a route
       through one Cell in one Hour carries no interval anyone could publish - so the lines
       are uncoloured. Choose a <b>W1</b> or <b>W2</b> view to colour them.</p>`
    : `<p class="note">Coloured by <b>${view.label}</b> &mdash; the same estimand the Cell
       fill shows, restricted to that route's rows in each Cell. An uncoloured crossing is
       one whose 95% interval is too wide to publish, not a missing road.</p>`;
}

/** The legend for whatever the payload actually holds - and `not_analyzed` is NEVER
 *  omitted and never drawn as clear. A legend showing two flood depths and nothing else
 *  tells the reader that everything unpainted was modelled and found dry, which is false:
 *  DEP's exclusion mask is a CATEGORY (features.sample()'s own refusal, carried through
 *  silver/stormwater_extent as polygons for exactly this reason). Every ZONE_LEGEND row is
 *  rendered whether or not the payload carries it, so a build that lost a category shows
 *  an empty count rather than a shorter legend. */
function zoneLegend(body, row) {
  const counts = {};
  if (body) for (const f of body.features) counts[f.properties.category] = f.properties.n_polygons;
  const seen = Object.keys(counts).filter(k => !ZONE_LEGEND.some(([id]) => id === k));
  const line = (hue, name, what, n) =>
    `<div class="zl"><span class="sw" style="background:${hue}"></span>` +
    `<b>${name}</b><span>${what}${n === undefined ? "" : ` &middot; ${n.toLocaleString()} areas`}</span></div>`;
  return `<div class="zlegend">` +
    ZONE_LEGEND.map(([id, hue, what]) => line(hue, id.replace("_", " "), what, counts[id])).join("") +
    // an unrecognised category is NOT named as markup: it is the one string here that could
    // come from a future writer rather than from this file
    seen.map(() => line(GREY, "unrecognised", "a category this page has no legend for")).join("") +
    `<div class="zl note">${row ? `DEP design storm: ${Number(row.rain_in_hr)} in/hr, ` +
      `current sea level. A PLANNING map of what would flood at that rain rate - not an ` +
      `observation of water, not a forecast, and not a site-specific determination.` : ""}</div>` +
    `</div>`;
}

/** The zones layer's `draw`, and it is TWO-PHASE on purpose. `geo` is a TREE family whose
 *  served set is DERIVED from silver/stormwater_extent, and a browser cannot list a
 *  directory - so the layer's first source is the manifest `make geo` writes, and the
 *  scenario payload is a SECOND source added here once the selection is known. It is
 *  fetched through the same grab() every other source uses, so it gets a freshness row of
 *  its own and that row follows the radio instead of naming a file the page is not showing.
 *  A second scenario appearing is then a DATA change: the radio grows, nothing is edited. */
export async function drawZones(manifest) {
  const lyr = L("stormwater");
  lyr.srcs = [lyr.srcs[0]];                       // drop the previous scenario's row
  scenarios = manifest && Array.isArray(manifest.scenarios) ? manifest.scenarios : [];
  // `scenario` and `rain_in_hr` come from stormwater_extent.SCENARIOS - a module constant,
  // not a string out of the downloaded geodatabase - so they are this repo's own text.
  lyr.opts = scenarios.map(s => ({ id: s.scenario, label: `${s.scenario} &middot; ${Number(s.rain_in_hr)} in/hr` }));
  if (!scenarios.length) {
    lyr.opt = null;
    zoneAttr = "";
    lyr.legend = `<p class="note">No current-sea-level scenario is published on this host.</p>`;
    applyRamp();
    return;
  }
  if (!scenarios.some(s => s.scenario === scenario)) scenario = scenarios[0].scenario;
  lyr.opt = scenario;
  const row = scenarios.find(s => s.scenario === scenario);
  const src = { k: "files/geo/" + row.key, url: "files/geo/" + row.key, budget: null };
  lyr.srcs = [lyr.srcs[0], src];
  const body = await grab(lyr.id, src);
  if (body) map.getSource("stormwater").setData(body);
  zoneAttr = (body && body.attribution) || "";
  lyr.legend = zoneLegend(body, row);
  applyRamp();
}

/** The scenario radio inside the zones toggle. One scenario visible at a time. */
export async function setScenario(name) {
  scenario = name;
  await drawZones({ scenarios });
}


/* ================================= frontend 07: the flood-history record card ==========
 *
 * One manifest paints the layer; ONE fetch per click paints the card, and nothing under
 * files/history/ is fetched before a click - the manifest IS the absence test (an asset it
 * does not list has no record, and no request is ever made to discover that). The record
 * is dated READER-side off its own response headers through grab(), like every other
 * payload on this page - no wall clock is ever written into the family.
 *
 * The id prints even when a name exists: names are unique at NO grain ("86 St" names six
 * complexes; two bus stops metres apart share one name and one event count), so the
 * asset_id is the identity and the name is a courtesy. `name` is an ABSENT key on every
 * Cell - undefined, never null, never the word - so the title falls back to the id.
 */
let cardSeq = 0;   // clicks race: a slow record must never paint over a later click's card

const esc = (s) => String(s).replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const EVENT_CAP = 12;   // newest-first; 73 rows would bury the freshness rows below

/* The exposure block. 928 assets - every entrance - have NO `exposure` key AT ALL (absent,
 * not null: a fabricated 0.0 would read as "safe"), so the branch tests the KEY and the
 * absence is rendered as a sentence, never a zero and never a blank. What IS rendered is
 * `score_index` - the within-kind rank bounded (0, 1] - beside the payload's own estimand
 * sentence, verbatim. The two linear-predictor numbers in the payload are deliberately not
 * rendered: they are negative for nearly every Unit and are not probabilities, and a card
 * has no honest one-line gloss for them. */
function exposureHTML(doc) {
  if (doc.exposure === undefined) {
    const ask = doc.exposure_unavailable && doc.exposure_unavailable.ask;
    return `<p class="note">No flood-exposure score for this asset kind` +
      (ask ? ` &mdash; the score lives on its complex, <b>${esc(ask)}</b>.` : `.`) + `</p>`;
  }
  const e = doc.exposure;
  const bits = [`<div class="row"><div class="big">${fmt(e.score_index)}</div>
    <div class="band">flood-exposure rank within its kind, in (0, 1]</div>
    <p class="note">${esc(e.estimand || "")}</p>`];
  if (e.modelled === false) bits.push(`<p class="note">kind-median estimate &mdash; not a
    modelled rank for this asset.</p>`);
  // an absent surge margin is NOT a zero: a zero margin means water AT the doorway
  if (e.surge_margin_ft !== undefined)
    bits.push(`<p class="note">coastal surge margin ${fmt(e.surge_margin_ft, 1)} ft</p>`);
  if (e.flags && e.flags.length)
    bits.push(`<p class="note">flags: ${e.flags.map(esc).join(", ")} &mdash; meanings
      published in research/flood-10-coefficients.json</p>`);
  return bits.join("") + `</div>`;
}

function eventHTML(ev) {
  const srcs = ev.event_source_counts
    ? Object.entries(ev.event_source_counts).map(([s, n]) => `${esc(s)} &times;${n}`).join(", ")
    : (ev.sources || []).map(esc).join(", ");
  const span = ev.day_start === ev.day_end ? esc(ev.day_start)
    : `${esc(ev.day_start)} &rarr; ${esc(ev.day_end)}`;
  const support = ev.label_support && ev.label_support.length
    ? ` &middot; support: ${ev.label_support.map(esc).join(" + ")}` : "";
  return `<div class="src"><b>${span}</b><span>${esc(ev.event_class || "")}</span></div>` +
    `<div class="src why"><span>${esc(ev.flood_cause || "")}` +
    `${srcs ? " &middot; " + srcs : ""}${support}</span></div>`;
}

export async function showCard(p) {
  const seq = ++cardSeq;
  const h = $("card-h");
  // textContent, never markup: `name` originates in the GTFS registry, the one string
  // here that crosses a trust boundary. The id line prints UNCONDITIONALLY (see header).
  h.textContent = p.name || p.asset_id;
  $("card-id").textContent = `${p.kind} · ${p.asset_id}`;
  $("card-body").innerHTML = `<p class="note">fetching this asset&rsquo;s record&hellip;</p>`;
  $("card").hidden = false;
  h.focus();
  // the id VERBATIM in the URL: flat tree, no shards, no encoding (charset measured over
  // the whole registry: [A-Za-z0-9:._-], every character legal in a path segment)
  const src = { k: "files/history/" + p.asset_id + ".json",
                url: "files/history/" + p.asset_id + ".json", budget: null };
  const doc = await grab("hist", src);
  if (seq !== cardSeq) return;   // a later click or a close owns the card now
  if (!doc) {
    $("card-body").innerHTML = `<p class="note">no record could be fetched:
      ${esc(whys["hist/" + src.k] || "fetch failed")}</p>`;
    return;
  }
  const age = ages["hist/" + src.k];
  const events = (doc.events || []).slice().reverse();   // the seam orders oldest-first
  const shown = events.slice(0, EVENT_CAP);
  const label = doc.versions && doc.versions.label_version;
  $("card-body").innerHTML =
    `<p class="note">${doc.n_events} flood event${doc.n_events === 1 ? "" : "s"} on record
       &middot; ${age === null || age === undefined
         ? "record age unknown" : `record ${fmtAge(age)} old`} (dated from its own
       response headers)</p>` +
    exposureHTML(doc) +
    shown.map(eventHTML).join("") +
    (events.length > shown.length
      ? `<p class="note">&hellip;and ${events.length - shown.length} earlier events.</p>` : "") +
    `<p class="note">Source counts are city-wide at EVENT grain &mdash; what the whole
       event generated across the city, not what was observed at this asset.</p>` +
    (label ? `<p class="note">label version <code>${esc(label).slice(0, 12)}</code></p>` : "");
}

export function closeCard() {
  if ($("card").hidden) return;
  cardSeq++;                     // a record still in flight must not repaint a closed card
  $("card").hidden = true;
  // focus returns to the marker's own toggle row, so a keyboard reader lands back where
  // the layer is controlled rather than at <body>
  const t = document.querySelector('#layers [data-l="hist"]');
  if (t) t.focus();
}


/* ========================= frontend2 05: the rider's recent-flooding list ==============
 *
 * files/summary/recent.json (frontend2 04's payload - key shapes frozen by use). The
 * strings render VERBATIM: `strings.label` and every `strings.caveats[]` sentence are the
 * writer's, and the window's dates are printed as the payload's own dates - the window is
 * anchored on the SPINE'S newest day_end, so the page never presents `until` as today.
 * Rows carry no analyst vocabulary: a date span and labelled-asset counts, both facts.
 *
 * Hovering or focusing a row rings that event's Cells on the boot-declared `locate` layer
 * (prototype variant C's hover-locate, taken): the centroids are derived from the map's
 * own `cells` source, so cells.geojson stays ONE fetch. The wiring is app.js's, like all
 * wiring on this page.
 */
let recentEvents = [];   // the fetched events, indexed by the rows' data-ev attribute

const REC_CAP = 8;   // a glance, not an archive; the rest is named, not hidden

export async function loadRecent() {
  const src = { k: "files/summary/recent.json", url: "files/summary/recent.json",
                budget: null };
  const doc = await grab("recent", src);
  const box = $("recent");
  recentEvents = doc && Array.isArray(doc.events) ? doc.events : [];
  if (!doc) { box.innerHTML = ""; return; }   // not published: no section, no claim
  const s = doc.strings || {};
  const w = doc.window || {};
  const rows = recentEvents.slice(0, REC_CAP).map((ev, i) => {
    const span = ev.day_start === ev.day_end ? esc(ev.day_start)
      : `${esc(ev.day_start)} &rarr; ${esc(ev.day_end)}`;
    const n = ev.n_assets || {};
    const bits = [ev.flood_cause ? esc(ev.flood_cause) : "",
      typeof n.bus_stop === "number" ? `${n.bus_stop.toLocaleString()} bus stops` : "",
      typeof n.complex === "number" ? `${n.complex.toLocaleString()} station complexes` : "",
    ].filter(Boolean).join(" · ");
    return `<div class="rec" tabindex="0" data-ev="${i}"><b>${span}</b><span>${bits}</span></div>`;
  }).join("");
  box.innerHTML =
    `<h2 class="lbl">Flooding on record, ${esc(w.since || "")} to ${esc(w.until || "")}</h2>` +
    `<p class="note">${esc(s.label || "")}</p>` +
    `<p class="note">Point at an event to ring its areas on the map.</p>` +
    rows +
    (recentEvents.length > REC_CAP
      ? `<p class="note">&hellip;and ${recentEvents.length - REC_CAP} earlier events in
         <code>files/summary/recent.json</code>.</p>` : "") +
    (Array.isArray(s.caveats) ? s.caveats.map(c => `<p class="note">${esc(c)}</p>`).join("") : "");
}

/** Ring one event's Cells on the `locate` layer; null clears it. The geometry comes from
 *  the map's own `cells` source (the drawImpact idiom), so an unloaded fill, a 404 or a
 *  hex outside the footprint all degrade to an empty ring - never a throw. */
export function locateEvent(i) {
  if (!styled) return;
  const ev = i === null ? null : recentEvents[i];
  const hexes = ev && Array.isArray(ev.cells) ? ev.cells : [];
  if (!hexes.length) { map.setLayoutProperty("locate", "visibility", "none"); return; }
  const src = map.getSource("cells");
  const fc = src && src.serialize ? src.serialize().data : null;
  const want = new Set(hexes);
  const feats = ((fc && fc.features) || [])
    .filter(f => f.geometry && f.geometry.type === "Polygon" && want.has(f.properties.cell))
    .map(f => {
      const ring = f.geometry.coordinates[0];
      const c = ring.reduce((a, p) => [a[0] + p[0], a[1] + p[1]], [0, 0]);
      return { type: "Feature", properties: {}, geometry: { type: "Point",
               coordinates: [c[0] / ring.length, c[1] / ring.length] } };
    });
  map.getSource("locate").setData({ type: "FeatureCollection", features: feats });
  map.setLayoutProperty("locate", "visibility", feats.length ? "visible" : "none");
}
