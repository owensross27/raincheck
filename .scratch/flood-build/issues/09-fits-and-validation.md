# 09 — Fits, baselines, validation, and the headline gate

**What to build:** The two L2 logistic fits and the validation battery designed to embarrass them — four
baselines, two split schemes, the bootstrap, the sensitivity sweeps — ending in the headline gate
that decides which model id ships. Spec: Exposure score (models, validation); Testing: build-asset
evidence, not pytest.

**Blocked by:** 08

**Status:** ready-for-agent

- [ ] two fits, L2 logistic, unweighted, lambda by inner CV: the pooled POINT model (entrances + bus stops, shared feature vector + kind indicator) and the CELL model over cells_scored; GBM, hand-weighted index and a third complex-level fit stay rejected
- [ ] complex score = max over child-entrance scores; the alert-sourced complex-event pairs stay out of training (MEASURED 2026-08-24 on the landed labels: 140 complex labels in all, **118** on pluvial fit-era events — the spec's 155 is superseded) and validate at complex grain independently
- [ ] four baselines: base rate, precip-only, unit climatology (B2), density-only (B3)
- [ ] splits: primary = event-grouped 5-fold (deterministic sha1 folds); secondary = location-blocked 5-fold (grouped by Cell); the history-covariate with/without contrast reports under the location-blocked split
- [ ] metrics: pooled CSI/POD/FAR at the in-fold operating point with an event-cluster bootstrap (B=1000); per-event POD + raw false-positive count (61% of events are single-positive — no per-event CSI); PR-AUC secondary
- [ ] HEADLINE GATE: the model beats B2 AND B3 under the location-blocked split; if B2 wins, the shipped model id is B2 and the alternate panel strings are selected — the release checklist asserts whichever branch fired
- [ ] sweeps: ~25 one-at-a-time configs around the frozen primary (100 m, p99-union, ring15_med, history-on); one weight-sensitivity fit (1/fan-out); {50,100,200} m radius sweep in-fold — the 311-threshold sweep is NOT here: it redefines the event universe and runs as its own outer-replication ticket (18)
- [ ] the bus-stop churn deltas publish as a build asset: metrics with and without the era-restricted bus-stop negatives, naming why the original sensitivity method was dropped (no historical Picks locally)
- [ ] the MRMS-era out-of-sample replication metrics publish alongside the AORC-fit metrics, read under the 0.86–0.92 Pass2/AORC scale band with the band caveat stamped on the table
- [ ] pre/post-2014 split published with the label-availability confound stamped on it
- [ ] the published CSI table carries the FIM reference band (published FIM systems run CSI 0.26–0.45) and the comparison is stamped order-of-magnitude-only
- [ ] all validation tables publish as build assets the release links; the runnable check is a small test that the fold assignment is deterministic and the gate evaluation is a pure function of the published tables

## Correction from flood-04's build (2026-08-23, recorded by the orchestrator)

The "115 union event days" coverage-honesty figure in this ticket is SUPERSEDED: the
landed spine (silver/flood_events) carries 206 events over 248 event-days,
2010-03-13..2026-08-20. Recompute the subway/bus coverage fractions against
silver/flood_events at build time here — do not reuse 115-based fractions.


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
