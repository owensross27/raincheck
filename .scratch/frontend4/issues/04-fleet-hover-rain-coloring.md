# frontend4 04 — fleet hover + rain-conditioned coloring on the frozen ramp

Status: ready-for-agent
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
