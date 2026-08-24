# 18 — 311-threshold outer replication

**What to build:** The sensitivity sweep that cannot run in-fold because it redefines the event universe:
the spine re-derived at alternate 311 thresholds, labels and training rebuilt under each alternate
universe, the fits re-run, and the delta table published — parameterizing the 04→09 machinery,
not writing new logic. Spec: Exposure score (validation — the 311-threshold sweep is an outer
replication); Testing: build-asset evidence.

**Blocked by:** 09

**Status:** ready-for-agent

- [ ] the spine re-derives at the alternate 311 daily-count thresholds (around the frozen p99-union primary), reusing ticket 04's derivation as a pure function of the threshold constant — no fork of the logic
- [ ] labels (05), the flood-era coverage check (06) and the training table (08) rebuild under each alternate event universe through the same jobs, version stamps distinguishing every alternate universe from the primary
- [ ] the fits re-run per universe and a delta table publishes as a build asset: headline metrics per alternate threshold beside the frozen primary, so reviewers see the knob without the knob having selected the result
- [ ] the primary artifacts are untouched: nothing under the frozen primary's version stamps changes byte-wise during the replication


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
