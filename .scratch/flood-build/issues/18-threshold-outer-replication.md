# 18 — 311-threshold outer replication

**What to build:** The sensitivity sweep that cannot run in-fold because it redefines the event universe:
the spine re-derived at alternate 311 thresholds, labels and training rebuilt under each alternate
universe, the fits re-run, and the delta table published — parameterizing the 04→09 machinery,
not writing new logic. Spec: Exposure score (validation — the 311-threshold sweep is an outer
replication); Testing: build-asset evidence.

**Blocked by:** 09

**Status:** done (2026-08-24, `make flood-replication`)

- [x] the spine re-derives at the alternate 311 daily-count thresholds (around the frozen p99-union primary), reusing ticket 04's derivation as a pure function of the threshold constant — no fork of the logic
- [x] labels (05), the flood-era coverage check (06) and the training table (08) rebuild under each alternate event universe through the same jobs, version stamps distinguishing every alternate universe from the primary
- [x] the fits re-run per universe and a delta table publishes as a build asset: headline metrics per alternate threshold beside the frozen primary, so reviewers see the knob without the knob having selected the result
- [x] the primary artifacts are untouched: nothing under the frozen primary's version stamps changes byte-wise during the replication


## Inherited from flood 08's build (2026-08-24, `gold/flood_matrix`, commit 9c8b501)

`gold/flood_matrix` EXISTS — `make flood-matrix`, 1,006,123 rows, `matrix_version
8bc1e8912b1badadb69fa0bb5c676a65e0b8200b`. It is a READ. Nothing below is re-derived.

- **Filter on `role`, never on `kind` alone.** `fit_point` (entrance 280,595 rows /
  1,177 positives; bus_stop 502,756 / 2,831) · `fit_cell` (179,683 / 6,554) ·
  `validate_complex` (43,089 / 118 — never a fit row).
- Label is `flooded` BOOLEAN. Positives AND negatives are both already in the table;
  there is no anti-join left to do at fit time.
- Columns: `asset_id, kind, event_id, cell, complex_id, role, era, flooded` ·
  `log1p_precip_max_mm_1h, log1p_precip_total_mm, log1p_antecedent_mm_24h` (every role) ·
  `elev_ft, relief_ft, stormwater_cat` (fit_point) · `share_deep, share_nuisance,
  share_not_analyzed, density_311_3y` (fit_cell) · `matrix_version`.
- **The precip terms are stored ALREADY log1p'd.** Transforming again is a silent bug;
  raw mm is `expm1`.
- **Complex score = max over child-entrance scores is a `GROUP BY complex_id, event_id`**
  over the `fit_point` rows — `complex_id` rides on them, so ref/assets is never re-joined.
- Pure seams, already tested: `flood_matrix.era(day_start)` -> `fit` / `validation_only` /
  `replication` (`MRMS_FROM = 2026-08-14`); `flood_matrix.pairs(assets, events, positives)
  -> (rows, delta)` over the same plain mappings `flood_labels.negatives()` takes;
  `flood_matrix.matrix_version(root, label_version)` chains label + features + precip
  identities; `flood_matrix.elev_source(feat)` / `relief_m(feat)` are the per-row
  ring15_med fallback.
- **The pairable delta you must not discover late:** running the positives through
  `flood_labels.pairable()` drops **4,069 of 14,749** pluvial fit-era positives, and
  **4,068 of them are pre-2020 bus stops** (against 2,831 bus-stop positives kept). The
  same rule already deletes their negatives, so this is a symmetry rather than a loss —
  but any base rate, class weighting or bus-stop performance claim has to say it. Published
  in the file's parquet metadata (`census`, `gates`).
- **The 60 out-of-DEM-footprint stops are NOT IN THE MATRIX** (EXCLUDE-WITH-COUNT; all 60
  are Nassau County and all carry stormwater `not-analyzed`, so 745 = 685 in-matrix + 60
  excluded). They need a published flag class downstream, never an imputed elevation.
- **Freeze complexes by `complex_id`, never by station name.** The seven zero-grade_ok
  complexes are `{59: 9 Av, 74: 18 Av, 75: 20 Av, 78: Avenue U, 79: 86 St, 134: Sutter Av,
  299: Dyckman St}`; a name match returns 18 because "86 St" alone names five complexes.
- Recorded limit: `precip_identity()` names the built AORC Cell-month partition SET, not
  the pixel bytes — a month rewritten under the same name does not move the stamp.


## Inherited from flood 09's build (2026-08-24) — WHAT 09 DEFERRED TO YOU

- **The {50, 100, 200} m LABEL RADIUS sweep is yours too, not just the 311 threshold.**
  Ticket 09 could not run it in fold: `flood_labels.RADIUS_M = 100.0` is a constant inside
  ticket 05's Sedona `ST_DWithin` join, upstream of `gold/flood_matrix`, so moving it
  redefines which (Unit, event) pairs are positive — the same class of change as the
  threshold. Parameterize it the same way (05 re-runs, 08 rebuilds, the fits re-run, the
  delta table publishes beside the frozen primary), and stamp each alternate universe's
  `label_version` / `matrix_version` so nothing collides with the primary's bytes.
- The fits are `make flood-fits` (`raincheck.flood_fits.run(root)` returns the whole result
  dict; `flood_fits_report.render(result)` is a pure rendering). Re-running them under an
  alternate universe is a call, not a fork: point the data root at the alternate build.
- The primary's frozen numbers to publish against: point CSI **0.0310**, cell **0.1591**
  (location-blocked, out of fold), fits_version `8050dfa41fc1` over matrix_version
  `8bc1e8912b1b`.


## Delivered (2026-08-24, branch `flood18-threshold-replication`)

`make flood-replication` -> `research/flood-18-replication.{md,json}`. FOUR universes, each a
full rebuild of 04 -> 05 -> 06 -> 08 -> 09 through the same jobs onto its own root under
`<root>/alt/<uid>/`: **q9750** (311 q0.975 = 59/45) · **q9950** (q0.995 = 126/153) · **r050**
(radius 50 m) · **r200** (radius 200 m). The 311 arm asks `flood_spine.remeasure_311(root,
asof, q)` for a QUANTILE and never types a count.

**THE FINDING — the headline is robust to the 311 threshold and sensitive to the label
radius, and the raw CSI ranks the radius BACKWARDS.** Point CSI (location-blocked, out of
fold) runs 0.0237 (50 m) · **0.0310 (primary, 100 m)** · 0.0667 (200 m), so the raw column
says the widest radius is twice as good. Divided by each universe's OWN B0 — which under
location blocking IS its base rate, B2 having degenerated onto it (flood 09's trap) — the
lift runs **11.13x (50 m) · 6.05x (primary) · 4.42x (200 m)**: the widest radius has the
highest raw CSI and the LOWEST skill. 200 m nearly triples the point base rate (0.00512 ->
0.01509, positives 4,008 -> 11,818) because a 200 m circle round a doorway catches 311
reports from the next street. **The radius moves what "flooded" MEANS at point grain, not how
well the model finds it.** The 311 threshold is mild by comparison: +-2.5 percentiles moves
the point lift 5.94x-6.31x and the raw point CSI by at most 0.0010. Every gate re-fired
MODEL in all four universes.

**The radius is structurally INERT at Cell grain and that is checked, not assumed**: the cell
branch attaches on `a.cell = oe.cell` with no distance predicate, so both radius universes'
`fit_cell` rows are BYTE-IDENTICAL to the primary's (179,683 rows, same sha256 over the
sorted rows minus the stamp) while their `fit_point` positives move 4,008 -> 1,668 / 11,818.
Two real-root tests pin both halves.

**The primary is untouched, receipted twice.** `verify_primary()` hashes the frozen artifacts
AND recomputes `assets_version` / `features_version` / `precip_identity`, then re-derives
`label_version` and `matrix_version` from them, before and after the run; `diff_manifest` was
empty on both the build run and the re-run. Hashing artifacts alone would NOT have sufficed:
a new AORC month under the primary root moves `precip_identity` — and so stops
`matrix_version 8bc1e8912b1b` reproducing — without touching an artifact byte, which is why
q9750's 31 new AORC months (15 Pixel + 16 Cell) had to land in the ALTERNATE root. Stamps
asserted distinct rather than trusted; `spine_version` is exempt for the radius arm and
collides on purpose (the event list did not move).

**Cost, measured**: fits leg **187 s** per universe against the box's ~7 min expectation;
whole universes 313 s (q9950) · 301 s (r050) · 284 s (r200) · 499 s (q9750, which built the
31 AORC months). ~23 min for all four. Per-universe results cache at
`<root>/alt/<uid>/universe.json` (`UNIVERSE=<uid>`, `REBUILD=1`).

**Parameterization, no forks**: `flood_labels.attach_sql(radius_m)` (was the module-level
`ATTACH` constant) · `flood_labels.build(root, spark, asof, radius_m)` ·
`flood_labels.label_version(root, spine_version, asof, radius_m)` ·
`flood_spine.remeasure_311(root, asof, q)`. **Every default reproduces flood 05's frozen text
and the primary's own `label_version 46bbfd665b78` byte for byte** — verified before anything
else was built, and pinned by a test.

**A staging defect this ticket found and fixed before it could publish**: the first staging
enumerated the inputs a universe needs and missed `archive/subway_alerts` (the live alert
capture `flood_obs.alert_rows` folds in beside the Socrata snapshots). The alternate spine
silently lost an alert-triggered 2026 event — and `spine_version`, `label_version` and
`matrix_version` were all IDENTICAL to the corrected run's, because those stamps hash what
the build DECLARED, not what it read. Staging now DISCOVERS the tree by walking it. A stamp
in this chain cannot catch a missing input tree; only the walk can.
