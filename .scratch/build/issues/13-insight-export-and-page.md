# 13 — Insight export and the page: cells, headline, zones from Gold

**What to build:** `make export` writes the insight files from Gold, the baseline, AORC precip and the ref layer
with the pure-SQL JSON writer, `make vendor` fetches the pinned MapLibre, and `make web` serves
one static page whose insight panel shows the footprint hexes coloured by wet/dry Speed ratio
per window and by storm hour with intervals, gates, hidden counts, estimands and the required
disclaimers - the real map on localhost. Spec: L (insight), I (analysis outputs, wet event);
Testing 14-1 (tier 1 twin on fixture Gold, tier 2 on the slice), 14-4.

**Blocked by:** 06

**Status:** built 2026-08-23 on `claude/determined-driscoll-e43969` (commit 8d3a45b),
awaiting landing. Every box below is done and verified against the real data root; full
suite 186 passed, `make gates` green including the new 14-1.

**Status (previous):** claimed for next session (2026-08-23) - read spec L + this ticket +
research/14-serving-surface.md + research/14-serving-prototype/ before building.
Orientation findings from the claiming session: (1) DuckDB 1.5.5 spatial has
ST_AsGeoJSON / ST_SimplifyPreserveTopology / ST_ReducePrecision / ST_IsValid
(ST_AsGeoJSON takes no precision arg - reduce first); (2) the prototype's export is
pandas+h3 throwaway and its control is a single control day - the real export is
pure-SQL over ref/cells with the dry hour-of-week baseline; (3) chord-band r values
are at research/10-backfill-slice-and-speed.md:78-80 (class medians 1.164 under
3 m/s, 1.025 at 3-6, 1.016 above 10); (4) windows + school dates are constants in
raincheck/ref.py (WINDOWS, SCHOOL_FIRST_DAY, SCHOOL_CLOSED); (5) gates.py is the
tier-2 home for 14-1; suite baseline 136, web/ does not exist yet, .gitignore needs
web/files/ + web/vendor/ lines; (6) the one open design call: H_lo/H_hi for a single
storm hour has no within-hour scatter in Gold - derive the interval from the dry
same-hour-of-week bin's scatter recomputed from cell_hour_speed x the dry mask
(cell_hourofweek_baseline stores only pooled sums).

- [x] one SQL text computes: per-Cell wet anomalies per window scored against the hour-of-week bin with 95% intervals clustered by wet event (spec's definition) and by service day as the sensitivity check; the two storm composites per fixed citywide hour against the window's dry baseline with the same interval gate; H_mm and H_lag from precip_cell_hourly src=aorc; W_ratio_ex_preschool from ref/calendar; the numeric chord band pair
- [x] `cells.geojson`: one Feature per footprint Cell, geometry from ref/cells at 5 dp, id = hex Cell, wide properties per spec L, absent (never null) when unpublishable, no route breakdown; `headline.json` rows carry value, the literal estimand sentence, the median-Cell companion and its estimand, n_legs, n_cells, n_cells_hidden, band as [ratio, ratio_chord_upper]; `zones.geojson` 263 simplified zones; every query ORDER BY so re-export is byte-identical; explicit round(x, 3)
- [x] the page: MapLibre 5.9.0 UMD vendored (v6 is ESM-only), no build step; layers W1/W2 wet-dry, Ida 02Z-08Z, 2023-09-29 10Z-21Z, dry baseline; fixed ramp 0.5..1.2; grey = property absent; the legend names the estimand and "rain: AORC hourly, hour-ending"; the preview sentence, the 2023 band-reaches-1.0 statement and n_cells_hidden beside every median figure; headline = citywide + median Cell + rain-lag curve; provenance strip; taxi zones as the ground; zone name in the tooltip from the export
- [x] 14-1 tier 1 on a three-Cell fixture Gold: no null property, finite values, estimand + numeric band + hidden count on every row, byte-identical re-export; 14-1 tier 2 on the slice: feature count == publishable footprint Cells, fixture Cell 882a100895fffff has w1_dry > 0 and an Ida hour, 263 valid zones
- [x] 14-4: the stdlib server answers 200 for the page, the two vendored files and cells/headline/zones; web/files and web/vendor are gitignored

## Closing notes (2026-08-23, the building session)

Design calls made where the ticket left them open, and the numbers behind them:

1. **H_lo/H_hi for a single storm hour** (the ticket's one open call): taken as the dry
   same-hour-of-week bin's own sampling scatter, recomputed from `cell_hour_speed` x the
   dry mask (the baseline table stores pooled sums only), propagated through the ratio by
   the delta method - `half = t * ratio * se(D)/D`, dry Hours clustered one per Hour. It
   captures the DENOMINATOR's uncertainty only; the storm Hour itself has no within-hour
   scatter in Gold, so the interval understates total uncertainty and every storm-hour
   estimand string in `headline.json` says exactly that.
2. **Window intervals** cluster by wet event as spec I requires; service-day clustering
   rides along as `sensitivity_day` on every window row. t multipliers by df, never a flat
   1.96 - per-Cell cluster counts are 8-13, where 1.96 would be ~5% too narrow.
3. **Chord band**: `[ratio, ratio * r(wet)/r(dry)]` with research 10 B1b's class medians
   (1.164 under 3 m/s, 1.025 at 3-6, 1.015 at 6-10, 1.016 above 10). Reproduces the
   research's own arithmetic - Ida 03Z 0.757 -> 0.859, 04Z 0.720 -> 0.817 - and the
   2023-09-29 13Z/14Z bands reach 1.021/1.020, so the page states that storm's slowdown is
   not separable from chord bias.
4. **Ida 09Z-12Z** carry headline rows but no map properties (`on_map: false`): spec L
   fixes the map layers at 02Z-08Z, but the recovery tail is where the rain-lag story ends
   (0.924 / 0.757 / 0.720 / 0.786 / 0.801 / 0.916 / 0.929 / 0.980 / 0.981 / 0.987 / 1.017
   over 02Z-12Z), so the page's curve plots it.

**Two findings that are Ross's call, not the gate's** - surfaced, not smoothed:

- The 0.30 interval-width gate publishes only **47% (324/687) of Cells at Ida 07Z and 45%
  (297/656) at 08Z**. That is the storm tail where service collapsed and Cells lost their
  Legs, so it is the gate working, not a gate mis-set. Left at 0.30; `make export` and
  `make gates` both print shown/hidden per layer and flag any layer under half. `GATE=`
  sweeps it without touching the SQL.
- **Window-scale wet/dry is ~1.00 citywide for both windows** (W1 1.002 [0.973, 1.031],
  W2 0.999 [0.938, 1.061]) and the pooled rain-lag curve is flat for the same reason:
  across a two-month window most wet Hours are drizzle. The slowdown is an extreme-hour
  phenomenon. The page shows the flat curve beside the heavy-rain one rather than
  showing only Ida.

## What the review pass changed (2026-08-23, same session)

A five-lens review fan-out with adversarial refutation (28 raw findings, 8 verified, 7
confirmed) found a **critical bug in the first commit (8d3a45b)** and six other real
defects. All are fixed; the numbers above are the corrected ones.

1. **CRITICAL - the baseline join was one local day out.** `gold.baseline()` reaches
   "Monday 00 local = 0" with SPARK's `dayofweek` (1=Sunday); `export.sql` carried the
   byte-identical text into DuckDB, whose `dayofweek` is 0=Sunday. Every wet Cell-hour was
   therefore scored against the WRONG DAY's dry baseline. Measured: the shipped expression
   reproduced **0 of 178,826** w1 baseline rows, `(dayofweek + 6) % 7` reproduces 175,952.
   Corrected, W1 moves 1.002 -> 1.012 and W2 0.999 -> **0.979**. Storm hours were
   unaffected (they use `hw` on both sides of their own join, and `hw` is a bijection).
   The comment claiming the expression "cannot drift" because it matched gold.py's text
   was exactly backwards and is now the warning.
2. **CRITICAL - the tier-1 fixture could not have caught it,** and was not testing the
   window layer at all: each wet Hour's dry counterpart was built a day later, landing in a
   different bin, so the baseline join dropped every one and `w_cell` was empty. A 999x
   interval and a null-instead-of-absent property both shipped green against it. The
   fixture now runs two window bins (wet weeks then dry weeks in the SAME hour-of-week),
   and the convention is pinned against FIXED DATES rather than against a fixture built
   with the same expression - a self-consistent fixture cannot catch a convention error.
3. **The storm-hour gate censored on the answer.** `half = t * ratio * se(D)/D` is
   proportional to the estimate, so an absolute-width gate kept slow Cells and dropped fast
   ones at equal baseline precision, biasing every published median down, and it waved
   through a Cell whose storm Speed was 0 with a degenerate [0, 0] interval. The gate is
   now the same width on the DRY BASELINE's own relative interval, which is what the
   storm-hour interval measures and is independent of the ratio. Effect: Ida 03Z median
   Cell 0.845 -> **0.875**, 04Z 0.838 -> 0.859 - the old numbers were too dramatic.
4. **`n_cells_hidden` did not reconcile with the map.** It counted only Cells whose
   interval was too wide, omitting Cells with Legs but no interval at all (one wet event,
   or no dry baseline), while the note promised it covered them. Now it is every footprint
   Cell with Legs in the layer that did not publish, so shown + hidden equals the Cells on
   screen.
5. **The band-reaches-1.0 statement was gated per Hour,** so it vanished on ten of the
   twelve 2023-09-29 hours - the storm spec L requires it for. It is now a layer-level
   statement over the Hours that measure a slowdown (Ida, whose slowdown IS separable,
   correctly does not carry it).
6. `make vendor` verified the checksum after overwriting the known-good copy; it now
   downloads to `.new`, verifies, then moves. `export.run()` wrote files one at a time,
   so a mid-run failure left `web/files` mixing two builds; it now stages and replaces.
   `headline.json` could emit `median_cell: null`, breaking its own absent-key contract.
   The tooltip set `zone_name` (third-party TLC shapefile) as innerHTML. Selected-button
   contrast was 3.4:1. Hour-button clicks dropped keyboard focus to `<body>`.
7. **Six mutation tests now guard the suite** - the dayofweek offset, the t table at the
   fixture's own df, the chord class medians, the default gate width, the property
   writer's ORDER BY, and a CDN script tag - each verified to FAIL the suite when
   introduced. Tier 1 is 20 tests.

Not fixed, deliberately, and why:

- **The chord band classifies chord speeds against B1b's POLYLINE speed classes.** An arm
  can land one class low, which inflates the correction. That is the conservative direction
  for a band whose upper edge is defined as an upper bound, and it reproduces 10 section
  2's own worked arithmetic; `chord_note` now says so outright rather than leaving it
  implicit.
- **The rain-lag curve has no interval.** Adding one needs an estimator decision (the
  clusters are Cell-hours at a given lag, not wet events) that belongs with 10, not here.
  The curve's estimand and the page caption now both say no interval is published and to
  read the shape, not a point.
- **Per-Cell values are mouse-only.** Every Cell's ratio, interval, Legs and rain live in
  the hover tooltip, so keyboard and screen-reader users get citywide and median-Cell
  figures but nothing at Cell grain. A real fix is a keyboard-navigable Cell list or a
  table view - a design question, not a patch. Flagged for Ross.

**Two contract notes for ticket 14:**

- MapLibre 5.9.0 **silently drops** a GeoJSON source whose `promoteId` resolves to a
  non-integer-like string: zero features, no `error` event, style never finishes loading.
  The Cell id is a hex string, so the `cells` source carries no `promoteId`; do not add one
  to `live` unless `vehicle_id` is integer-like.
- MapLibre needs the tab **visible** to finish loading at all (`requestAnimationFrame` is
  throttled when hidden), so a headless screenshot check reports a blank map on a page that
  is perfectly fine.
