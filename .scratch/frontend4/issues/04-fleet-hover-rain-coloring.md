# frontend4 04 — fleet hover + rain-conditioned coloring on the frozen ramp

Status: done
Spec: `.scratch/frontend4/spec.md` (F3b). Charter: `.scratch/frontend4/charter.md`.
Blocked by: 02 (the `TIPS` mechanism — BRANCH FROM `frontend4-02-hover-point-layers`),
03 (the bronze contract — its completion entry must be in RUN-LOG before you claim
this; re-export locally to see real values).
Files: `web/live.js`, `web/layers.js`, `web/insight.js`, `web/app.js`,
`tests/test_page.py`.

## What this builds

Hover a bus: route, the agency's own next-stop prediction, and — when it is raining in
that bus's Cell and the Cell publishes a wet/dry band — the band, on the same frozen
ramp the delay fill uses. Neutral otherwise, honestly.

## MUSTs

1. **The join is a client-side dict lookup at tick time.** `insight.js` exposes a named
   getter over the cells FeatureCollection it already fetched (one fetch, one parse —
   NEVER a second `fetch` of cells.geojson; a cross-module read is a named function in
   the owning module, the `layers.markStyled()` shape). `liveTick` (`live.js:103-116`)
   builds `cell -> {ratio, lo, hi, win}` from it (once per cells arrival is fine) and,
   per feature BEFORE `setData`, attaches `ratio`/`lo`/`hi`/`win` ONLY when ALL hold:
   `p.cell` present; `p.mm_1h >= <RAIN_MM>`; the Cell publishes a band. Band source:
   `w2_ratio`/`w2_lo`/`w2_hi` when published, else `w1_*` (win = "w2"/"w1"). The page's
   rain-threshold literal is MIRRORED from `live_export.RAIN_MM` — the test derives the
   expected string from the Python constant (`str(live_export.RAIN_MM)`), never writes
   it twice.
2. **Paint: the frozen ramp, boot-declared, absent -> the mark's own neutral.** The
   `live` style layer's `circle-color` (`layers.js:339-340`) becomes the `impact-fill`
   pattern (`layers.js:325-326`): `["case", ["!", ["has", "ratio"]], LIVE_FRESH,
   ["interpolate", ["linear"], ["get", "ratio"], ...RATIO_STOPS.flat()]]`.
   `RATIO_STOPS` stays BYTE-UNTOUCHED (Ross's recorded wave-11 gate decision; reuse is
   the point — one vocabulary, second mark). Neutral is `LIVE_FRESH`, NOT `GREY`
   (absent-value color is a property of the mark — frontend2 03). `renderLive`
   (`live.js:59-61`): stale branch paints flat `LIVE_STALE` + 0.35 opacity (staleness
   wins over everything); fresh branch restores the CASE EXPRESSION, not flat
   `LIVE_FRESH`. Radius and opacity numbers untouched. If
   `test_page.py:660` (one ramp on screen) pins a literal count rather than the
   fill-channel rule, re-derive it onto the rule and say so in your entry.
3. **Fleet hover via 02's mechanism** (a `TIPS.live` entry + the `app.js` trio for the
   `live` layer): title `Route {route_id}` with `vehicle_id` fallback; sub
   `vehicle_id`; lines — next stop `next_stop_id` in `pred_next_s` (labeled the
   agency's own prediction, absent keys -> line absent); `trip_delay_s` when present,
   worded as the agency-reported number (the `live.js:92-96` discipline); and a
   conditions line ONLY when `ratio` was attached: the BAND —
   "wet-hour speed {lo}-{hi}x dry same-hour ({win})" — NEVER the point ratio alone.
   Raining with no published band: "no published band for this Cell". Not raining / no
   cell / no mm: NO conditions line. Nothing anywhere says or implies "late because of
   rain" — descriptive vocabulary only. Untrusted strings through `esc()`/
   `textContent` (route_id/stop ids are feed strings — treat as untrusted).
4. **Caveats RENDERED, never restated.** While any vehicle carries `ratio`, the live
   layer's legend (the `lyr.legend` mechanism, `live.js` draw functions) renders
   `headline.json`'s published `estimand` and `preview_note` strings verbatim through
   the existing `note()`/`esc()` path. `cells.geojson` carries no strings; headline is
   where the estimand prose lives — take it from the payload `insight.js` already
   fetched, no new fetch, no page-authored copy.
5. **Old-JS-over-new-HTML degradation:** the republish serves mixed pages for up to a
   day — keep every id the current modules touch; additive markup only.
6. **Tests** (`tests/test_page.py`):
   - The mirrored threshold, derived from `live_export.RAIN_MM`.
   - The boot paint case expression on the live layer (absent -> `LIVE_FRESH`,
     interpolate on `RATIO_STOPS`) and `:603`'s frozen-ramp byte-assert still green.
   - Stale-overrides-color: the stale branch paints `LIVE_STALE` flat.
   - The three-legged attach condition (cell / rain / band) — anchor each leg in the
     source; mutation kills each independently.
   - The band-not-point rule: the conditions template renders `lo` and `hi`, and no
     tip path renders `ratio` as a bare number.
   - The wiring trio for `live` in `app.js` only; no second cells fetch
     (`fetch(` count per module or the existing static-contract test extended).
7. **Evidence:** re-run `make live-export ONCE=1 SOURCE=bronze` on the main root (03
   landed) and load the page locally (`make web`); one screenshot with rain-colored or
   neutral fleet (whatever the sky provides — say which) via the standing headless
   recipe. A dry day means neutral dots and a working tip — that is a pass, not a gap.
8. **Mutation round** (standing rules): at minimum — drop one attach leg; flip the
   w2-else-w1 preference; point-number the band line; stale branch keeps the ramp;
   second cells fetch introduced. Record kills.

## Refusals

- `RATIO_STOPS`, `GREY`, `LIVE_FRESH`/`LIVE_STALE` values: byte-untouched.
- No new ramp, no new hue, no legend swatch row for the fleet (the ramp legend is
  `applyRamp()`'s and already on screen when a fill is lit; do not contest it).
- No `promoteId`, no feature-state, no Popup.
- No wording that grades, blames, or forecasts: no "late because", no "delayed by
  rain", no invented tier words (tier vocabulary comes from payloads only — the
  `:853` rule).
- No reading of `impact.json`'s live overlay for the fleet (it publishes no ratio
  today; the coloring keys on cells.geojson's capture-window bands, per the charter).

## Protocol

Worktree at `/Users/ross/raincheck-wt/frontend4-04`, branch
`frontend4-04-fleet-rain-coloring` CREATED FROM `frontend4-02-hover-point-layers` (the
gate lands 02 then 04, in order — your commits only on top). Own-module tests only,
never the full suite, no pin commits. Commit explicit paths, push, RUN-LOG entry +
forward-context.

## Close-out (2026-08-28)

Landed as specified: `insight.js` exposes `cellFeatures()` (a named getter over the
FeatureCollection `drawCells()` already stored — no second fetch) and `bandCaveats()`
(headline.json's citywide `estimand` for the preferred window plus `preview_note`).
`live.js` owns `export const RAIN_MM = 1.0` (mirrored from `live_export.RAIN_MM`,
derived in the test) and a `cellBands()` helper (`cell -> {ratio, lo, hi, win}`, w2
preferred over w1). `liveTick` attaches `ratio`/`lo`/`hi`/`win` per feature BEFORE
`setData` only when `p.cell` is present AND `p.mm_1h >= RAIN_MM` AND `cellBands()` has
an entry for that cell; it also sets the legend (`anyRatio ? bandCaveats() : null`).
`layers.js` gained `LIVE_COLOR` (the impact-fill case pattern, `RATIO_STOPS`/`GREY`/
`LIVE_FRESH`/`LIVE_STALE` byte-untouched) shared by the boot declaration and
`renderLive`'s fresh branch; the stale branch stays flat `LIVE_STALE`.
`insight.js`'s `TIPS.live` renders `Route {route_id}` (vehicle_id fallback), the
agency's own next-stop prediction, the agency-reported trip delay, and — only when
`ratio` was attached — the BAND (`{lo}–{hi}x dry same-hour ({win})`), never the bare
point ratio; raining with no band says so; dry/no-cell renders nothing. `app.js` adds
`"live"` to 02's shared `pointTip` wiring loop — no bespoke handler.

**DEVIATION, disclosed**: MUST 4 (the legend) required touching two files outside the
ticket's named list — `web/index.html` (one new `<div id="live-legend">` beside
`#src-live`) and `web/panel.js` (one new `$("live-legend").innerHTML = live.legend ||
"";` in `renderLayers()`'s live-specific block). Reason: the `#live` row is the ONE
STATIC row in `index.html` (panel.js's own documented exception — `rowHTML()`'s generic
`(lyr.legend || "")` emission never runs for it), so setting `L("live").legend` alone
was inert — computed every tick, never shown. Caught before commit by actually loading
the page rather than trusting the source-level test alone.

Mutation round (commit first, `PYTHONDONTWRITEBYTECODE=1`, pristine control before/after,
`git status --porcelain` empty after every restore): drop the cell leg — KILLED; drop the
rain leg — KILLED; drop the band leg (attach a fallback band when none published) —
KILLED; flip w2-else-w1 to w1-else-w2 — KILLED; point-number the band line — KILLED;
stale branch keeps the ramp — KILLED; a second `cells.geojson` fetch introduced in
`live.js` — KILLED (by two tests); legend set unconditionally instead of gated on
`anyRatio` — KILLED. All eight killed on the first pass; none needed a fixture/test fix.

The one-ramp test (`test_page.py:660`, now `test_one_ramp_on_screen_is_a_paint_rule_and_not_a_promise`)
pins the FILL-CHANNEL RULE (`LAYERS.some(l => l.fill && on[l.id])`), not a literal ramp
count — the `live` layer's `fill: false` never contests it, and no re-derivation was
needed.

**Evidence, real headless browser** (Chrome 152, swiftshader flags, CDP capture, cold
profile, `setDeviceMetricsOverride`, `--remote-allow-origins=*`): re-ran
`live_export --source bronze --once` from the frontend4-03 branch against the real root
into this worktree's `web/files` (`n_vehicles: 2221`, `n_in_rain_cells: 52`); served with
`raincheck.webserve`; loaded the page and ticked the Live fleet toggle. Dynamic
`import('/layers.js')` against the running page (no source edits) confirmed **51 of
2221** live features carried an attached band (`ratio`/`lo`/`hi`/`win`, e.g.
`{ratio: 1.138, lo: 0.995, hi: 1.281, win: "w1"}` on `MTA NYCT_1688`/SIM2), and that the
CURRENT applied `circle-color` paint property was byte-identical to the exported
`LIVE_COLOR` case expression (the fresh/ramp branch, not the flat stale override) —
i.e. real colored dots, not neutral, on tonight's rain. Hovering that vehicle rendered:
`Route SIM2 / MTA NYCT_1688 / next stop 250066 in 68 s (the agency's own prediction) /
MTA-reported trip delay 134 s / wet-hour speed 0.99–1.28x dry same-hour (w1)` — the BAND,
never a bare point ratio. Screenshot committed: `research/frontend4-04-fleet.png`
(showing this tip open over the colored fleet). A separate earlier capture (taken with
an older, since-restaled export) also showed the `#live-legend` caveats rendering
verbatim (`bus-seconds-weighted citywide mean over wet Cell-hours...`), confirming MUST
4's fix works, but was not committed (superseded by the fresh capture above).

Forward-context: nothing else discovered that changes another ticket's contract.
