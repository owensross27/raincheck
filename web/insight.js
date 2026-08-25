/* The insight view (ticket 13): the paint, the headline, the curve, the view/hour
 * switching, the Cell tooltip, and the boot draw that builds all of them from
 * cells.geojson + headline.json.
 */
import { $, fmt, GREY, map, RATIO_STOPS, SPEED_STOPS } from "./layers.js";
import { whys } from "./freshness.js";

let head = null;         // headline.json
let cellKeys = new Set();  // property keys present in cells.geojson
let views = [];
let view = null;         // the active view object
let hourKey = null;      // active storm-hour key (MMDDHH) or null

// ---------------------------------------------------------------- paint and legend
function colorExpr(prop, stops) {
  const interp = ["interpolate", ["linear"], ["get", prop]];
  stops.forEach(([v, c]) => interp.push(v, c));
  return ["case", ["!", ["has", prop]], GREY, interp];   // absent -> grey, per spec L
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
}

// ---------------------------------------------------------------- headline rendering
const currentRow = () => head.rows.find(r =>
  r.layer === view.layer && (view.hours ? r.key === hourKey : true));

function renderHeadline() {
  const r = currentRow();
  if (!r) { $("headline").innerHTML = ""; return; }
  const bandLo = Math.min(r.band[0], r.band[1]), bandHi = Math.max(r.band[0], r.band[1]);
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
    $("preview-note").textContent = whys["cells/files/cells.geojson"] === "not published on this host"
      ? "the insight files are not published on this host."
      : "export files missing - run `make export` and reload.";
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
