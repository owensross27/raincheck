# 09 — Fits, baselines, validation, and the headline gate

**What to build:** The two L2 logistic fits and the validation battery designed to embarrass them — four
baselines, two split schemes, the bootstrap, the sensitivity sweeps — ending in the headline gate
that decides which model id ships. Spec: Exposure score (models, validation); Testing: build-asset
evidence, not pytest.

**Blocked by:** 08

**Status:** done (2026-08-24, `make flood-fits`)

- [x] two fits, L2 logistic, unweighted, lambda by inner CV: the pooled POINT model (entrances + bus stops, shared feature vector + kind indicator) and the CELL model over cells_scored; GBM, hand-weighted index and a third complex-level fit stay rejected
- [x] complex score = max over child-entrance scores; the alert-sourced complex-event pairs stay out of training (MEASURED 2026-08-24 on the landed labels: 140 complex labels in all, **118** on pluvial fit-era events — the spec's 155 is superseded) and validate at complex grain independently
- [x] four baselines: base rate, precip-only, unit climatology (B2), density-only (B3)
- [x] splits: primary = event-grouped 5-fold (deterministic sha1 folds); secondary = location-blocked 5-fold (grouped by Cell); the history-covariate with/without contrast reports under the location-blocked split
- [x] metrics: pooled CSI/POD/FAR at the in-fold operating point with an event-cluster bootstrap (B=1000); per-event POD + raw false-positive count (no per-event CSI — the "61%" is SUPERSEDED by measurement: single-positive events are 6 of 100 at point grain, 7 of 133 at Cell grain, 55 of 71 at complex grain); PR-AUC secondary
- [x] HEADLINE GATE: the model beats B2 AND B3 under the location-blocked split; if B2 wins, the shipped model id is B2 and the alternate panel strings are selected. **Delivered: the gate fired, `flood_fits.gate()` re-evaluates it purely from the published tables, and `gate.panel_strings` carries the fired branch's strings. NOT delivered here and OWED TO TICKET 10: the release checklist that asserts the branch — no such checklist exists in the repo yet, and the asset says so rather than claiming it**
- [x] sweeps: 26 one-at-a-time configs around the frozen primary, plus the 1/fan-out weight-sensitivity fit and a frozen-lambda REFERENCE row per role — 30 published rows (16 point, 14 cell). Every delta is against the reference row, which is the same estimator the configs are (fixed lambda); differencing against the nested-CV primary would have put a lambda-estimator offset on top of every feature effect. At Cell grain the 1/fan-out proxy is DEGENERATE and says so instead of republishing the primary: there is exactly one fit_cell row per (event, Cell), so the proxy has nothing to collapse — **but the {50,100,200} m radius sweep is NOT in fold and was NOT run here: the radius is a constant inside ticket 05's Sedona `ST_DWithin` label join, upstream of the matrix this ticket only reads, so sweeping it redefines the event universe exactly as the 311 threshold does. Both are DEFERRED TO TICKET 18 with the reason published in the asset; 18's checklist now names the radius alongside the threshold. **DELIVERED 2026-08-24 by flood 18** (`research/flood-18-replication.{md,json}`, `make flood-replication`): four rebuilt universes at 311 quantiles {0.975, 0.995} and radii {50, 200} m, every gate re-firing MODEL. **NO NUMBER IN THIS TICKET'S ASSET IS SUPERSEDED** — the primary is untouched, receipted byte-wise and by re-derived identities. The finding: the headline is robust to the threshold (point CSI moves <= 0.0010) and sensitive to the radius (0.0237 / 0.0310 / 0.0667 raw), but the radius's raw ranking is BACKWARDS — divided by each universe's own B0 the lift runs 11.13x / 6.05x / 4.42x, so 200 m has the highest raw CSI and the lowest skill while nearly tripling the base rate.**
- [x] the bus-stop churn deltas publish as a build asset: metrics with and without the era-restricted bus-stop negatives, naming why the original sensitivity method was dropped (no historical Picks locally)
- [x] the MRMS-era out-of-sample replication publishes — as **NOT COMPUTED with the count and the reason**: the matrix is fit-era only (AORC has no 2026 year) and the replication era holds ONE event, so there is no MRMS-era feature row to score. The 0.86–0.92 band caveat is stamped on the table for when it can run.
- [x] pre/post-2014 split published with the label-availability confound stamped on it
- [x] the published CSI table carries the FIM reference band (published FIM systems run CSI 0.26–0.45) and the comparison is stamped order-of-magnitude-only
- [x] all validation tables publish as build assets the release links; the runnable check is a small test that the fold assignment is deterministic and the gate evaluation is a pure function of the published tables

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


## What this build MEASURED (2026-08-24, `make flood-fits`, fits_version `8050dfa41fc1`)

Build assets: `research/flood-09-fits.md` (the tables the release links) and
`research/flood-09-fits.json` (machine-readable; ticket 10 loads it). Code:
`src/raincheck/flood_fits.py` (the fits, the metrics, the baselines, the gate, `run()`),
`src/raincheck/flood_fits_sweeps.py` (the sensitivity battery: sweeps, the named contrasts,
the coverage recompute, the MRMS-era status), `src/raincheck/flood_fits_report.py` (a PURE
rendering of the JSON — `python -m raincheck.flood_fits --render-only` re-renders without
refitting), `tests/test_flood_fits.py` (**+14**). ~7 min on the real matrix.

- **HEADLINE GATE: MODEL, both roles**, under the location-blocked split — point CSI
  **0.0310** vs B2 0.0051 / B3 0.0130; cell **0.1591** vs B2 0.0365 / B3 0.0819. Shipped
  ids `point:l2_logistic` and `cell:l2_logistic`; `gate.panel_strings` carries the MODEL
  branch's headline/caveat/release strings (the alternates live in
  `flood_fits.PANEL_STRINGS`).
- **The gate is not the whole truth, and the asset says so.** Under the PRIMARY
  event-grouped split the POINT model LOSES to B2 unit climatology (0.0286 vs 0.0340) and
  its 95% CI overlaps both baselines. The cell model is the one with separated intervals
  (0.117-0.203 against B3's 0.066-0.100). Anything quoting a point-grain number quotes the
  weaker half.
- **B2 degenerates to B0 EXACTLY under location blocking** — identical TP/FP/FN, because a
  held-out Unit's whole history sits in the held-out fold. Not a bug in the baseline: it is
  what the split is for, and it is why both splits publish.
- **The independent complex-grain set is the weak number**: 1 of 118 positives caught
  (location-blocked), CSI 0.0025, PR-AUC 0.0057 against a 0.0027 base rate. All 43,089
  complex-event pairs have child entrance rows; nothing was skipped. A complex-grain claim
  is not validated on this evidence.
- **The operating point transfers as an ALERT BUDGET, not a raw threshold** (in-fold
  max-CSI cut -> its alert rate -> a quantile of the held-out scores; no held-out label is
  read). Transferring the raw probability makes any constant-scored baseline read CSI 0.0
  for a reason about its score scale — it would have flattered this gate. Both rules are
  published as sweep rows; the difference is <= 0.0006 CSI.
- Sweeps: **26 one-at-a-time configs** in fold plus a frozen-lambda reference row and the
  1/fan-out fit per role — 30 published rows (16 point, 14 cell), including a rung BEYOND
  the lambda grid. Biggest single contributors: `stormwater` for the point model
  (-0.0074 CSI when dropped) and the 311 history density for the cell model (-0.0248).
  The **radius {50, 100, 200} m and p99-union threshold sweeps are DEFERRED to ticket 18**
  with the reason published: both redefine the event universe upstream of the matrix.
- MRMS-era replication: **NOT COMPUTED** and counted — the matrix is fit-era only and the
  replication era holds ONE event. The 0.86-0.92 band caveat is stamped for when it runs.
- Coverage recomputed: **206 events / 248 event-days** (pluvial fit era 133 / 147). The
  drafted 115 is superseded, as flood 04's correction above required.
- Single-positive events, measured: point 6 of 100, cell 7 of 133, complex 55 of 71 — the
  spec's "61% of events" is superseded; the decision it justified (per-event POD + raw FP,
  never per-event CSI) stands.


## What the adversarial review changed (same session, 4 lenses x skeptics, 4 findings CONFIRMED)

- **A keep-restricted CV run was spending its alert budget on rows it was told not to fit.**
  `cv(keep=ent)` picks each fold's budget on entrance training rows; `decide` was taking the
  quantile across the whole point vector, diluting it with 502,756 bus rows, so every fold
  under-delivered its declared rate on entrance rows by 28-47% and the published churn delta
  was inflated ~2.5x. Fixed: a run carries its `population` and the cut is spent inside it;
  every subset row in the churn table is now cut on the rows it scores (realized rates
  0.0111 / 0.0111 / 0.0111 / 0.0126) and the delta reads **0.0152 vs 0.0129**, not
  0.0176 vs 0.0119. The pre/post-2014 table deliberately keeps ONE global cut — there is no
  deployable per-era recut — and publishes each era's realized rate beside it.
- **The 1/fan-out row was a no-op at Cell grain** (one fit_cell row per (event, Cell), so the
  proxy had nothing to collapse and republished the primary as a +0.0000 "sensitivity").
  Now detected and published as DEGENERATE, NOT RUN.
- **Sweep deltas were differenced against a lambda-reselected primary** while the configs
  held lambda fixed, putting a constant estimator offset on every feature effect. Now every
  delta is against a published frozen-lambda REFERENCE row (the same estimator).
- **Two claims outran their evidence**: the complex-grain single-positive count (55 of 71)
  was asserted in prose but computed nowhere — it is now measured in `complex_validation`
  and published; and the pairable-symmetry paragraph hardcoded four counts — three now read
  off the matrix's own metadata (the 14,749 denominator is `candidates - negatives + drop`)
  and the one that cannot be re-derived is labelled as flood 08's, not as measured here.
  Also corrected: `modal_lambda`'s tie-break is now a stated rule (stronger penalty), and the
  lambda paragraph names, per role, whether the shipped rung is the best CSI rung — for the
  point model it is the WORST, which the earlier wording had left out.
