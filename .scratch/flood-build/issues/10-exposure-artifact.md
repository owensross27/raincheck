# 10 — Exposure artifact: gold/flood_exposure and the coefficient JSON

**What to build:** The published exposure object — one row per Unit with score_ref, score_severe,
score_index and surge_margin_ft — and the one in-repo coefficient JSON the detector will load, so
the score has exactly one artifact chain. Spec: Exposure score (published object); Testing seam 1.

**Blocked by:** 07, 09

**Status:** ready-for-agent

- [ ] `gold/flood_exposure`: one row per Unit — score_ref and score_severe (evaluated at frozen reference forcings: median and p90 of fit-era trigger-event precip), score_index (within-kind percentile on score_ref), surge_margin_ft from ticket 07, flags, all version stamps; NO NULL scores (fallbacks guarantee coverage, reasons ride flags); probabilities live in validation tables only
- [ ] plain Parquet, single sorted part, byte-identical rebuild gate
- [ ] the coefficient JSON (one in-repo file): coefficients, preprocessing constants, feature definitions, per-kind CDFs, reference forcings, the 0.86–0.92 scale band, and score_version = sha1 over label/features/precip identities plus model constants
- [ ] if the ticket-09 gate shipped B2, this artifact carries B2's parameters and the model id says so — the exposure table publishes either way
- [ ] non-negative event-side coefficients asserted here at build (the detector's monotone-latch claim depends on it)
- [ ] both artifacts name the estimand: `flooded_reported` — in the exposure table's metadata and as a top-level field of the coefficient JSON
- [ ] DuckDB contract tests: one row per Unit, no NULL scores, percentile bounds, version stamps chain structurally


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


## Inherited from flood 09's build (2026-08-24, `research/flood-09-fits.json`, fits_version `8050dfa41fc1`)

The gate FIRED **MODEL** for both roles under the location-blocked split, so this artifact
carries the FITTED parameters, not B2's. Everything below is a READ of
`research/flood-09-fits.json` — do not refit to find it.

- **Shipped ids: `point:l2_logistic`, `cell:l2_logistic`** (`gate.shipped`). `gate.branch`
  is `MODEL` and `gate.panel_strings` holds the headline/caveat/release strings the branch
  selected; the release checklist asserts THAT branch. `flood_fits.gate(summary)` is a pure
  function of the published summary — re-evaluate it, never re-type the verdict.
- Parameters per role live in `final.<role>`: `lambda`, `coef_standardized` +
  `intercept_standardized`, **`coef_raw` + `intercept_raw`** (the same model on the raw
  matrix scale — score it as a plain dot product), `standardization` (mean/std per feature),
  `features`, `stormwater_base_level` = `analyzed-none` (the dummy-coded reference level, so
  a point row that is `analyzed-none` gets NO stormwater term).
- **SCOPE THE "non-negative event-side coefficients" ASSERTION TO THE IN-WINDOW TERMS.**
  Measured: `log1p_precip_max_mm_1h` +0.449 and `log1p_precip_total_mm` +0.601 are positive
  in both models, but **`log1p_antecedent_mm_24h` is NEGATIVE at point grain (-0.093)**. The
  monotone-latch claim is about terms that can only RISE inside a Window; the antecedent is
  frozen at Window open and never moves within one, so it is not an event-side term. Assert
  the two in-Window coefficients >= 0 and this build passes; assert all three and it fails
  on a coefficient the latch does not depend on.
- Reference forcings: `final.<role>.precip_percentiles_log1p` and `precip_percentiles_mm`
  carry p50/p90 of the fit rows' precip terms in BOTH scales. The matrix stores log1p
  already — `expm1` before quoting mm, and never log1p twice.
- **A complex-grain score is NOT validated by this evidence**: the independent complex set
  caught 1 of 118 positives (CSI 0.0025, PR-AUC 0.0057 against a 0.0027 base rate). The
  max-over-child-entrances rule still defines the complex score; what it may not carry is a
  skill claim. Ticket 15's panel strings should say what it is (an aggregate of doorway
  scores) rather than what it was proven to do.
- Honest-strings load: under the PRIMARY event-grouped split the point model LOSES to B2
  (0.0286 vs 0.0340, overlapping CIs). The cell model is the one with separated intervals.
