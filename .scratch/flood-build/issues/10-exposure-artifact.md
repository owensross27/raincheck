# 10 — Exposure artifact: gold/flood_exposure and the coefficient JSON

**What to build:** The published exposure object — one row per Unit with score_ref, score_severe,
score_index and surge_margin_ft — and the one in-repo coefficient JSON the detector will load, so
the score has exactly one artifact chain. Spec: Exposure score (published object); Testing seam 1.

**Blocked by:** 07, 09

**Status:** done (2026-08-24, branch `flood10-exposure-artifact`)

- [x] `gold/flood_exposure`: one row per Unit — score_ref and score_severe (evaluated at frozen reference forcings: median and p90 of fit-era trigger-event precip), score_index (within-kind percentile on score_ref), surge_margin_ft from ticket 07, flags, all version stamps; NO NULL scores (fallbacks guarantee coverage, reasons ride flags); probabilities live in validation tables only
- [x] plain Parquet, single sorted part, byte-identical rebuild gate
- [x] the coefficient JSON (one in-repo file): coefficients, preprocessing constants, feature definitions, per-kind CDFs, reference forcings, the 0.86–0.92 scale band, and score_version = sha1 over label/features/precip identities plus model constants
- [x] if the ticket-09 gate shipped B2, this artifact carries B2's parameters and the model id says so — the exposure table publishes either way — **AMENDED: the gate fired MODEL, so the fitted parameters shipped, and the B2 branch is REFUSED LOUDLY rather than guessed.** `models_of()` raises `NotImplementedError` naming `flood_fits.climatology()`: `final.<role>` publishes the FITTED model only, so a B2 ship needs per-Unit climatology values that flood 09 publishes nowhere. Building that path now would be speculative machinery for a branch that measurably did not fire; the refusal names exactly what a future B2 ticket must add.
- [x] non-negative event-side coefficients asserted here at build (the detector's monotone-latch claim depends on it) — **SCOPED to the two IN-WINDOW terms; see the close-out**
- [x] both artifacts name the estimand: `flooded_reported` — in the exposure table's metadata and as a top-level field of the coefficient JSON
- [x] DuckDB contract tests: one row per Unit, no NULL scores, percentile bounds, version stamps chain structurally


## Close-out (2026-08-24, `make flood-exposure`, +50 tests)

**Both artifacts exist and rebuild byte-identical.** `gold/flood_exposure/part-00000.parquet`
(**15,166 rows** = 445 complexes + 13,370 bus stops + 1,351 Cells, sorted by (kind, asset_id),
zstd, no Hive partitioning) and **`research/flood-10-coefficients.json`** — THE file the
detector loads, via `flood_exposure.coefficients()`.

- **A score is the LINEAR PREDICTOR (eta), never a probability.** The spec puts probabilities
  in the validation tables only and ticket 11's display is a rank, so a sigmoid would add a
  monotone transform nobody reads and invite calibration claims the evidence cannot support.
  `score_ref` = eta at p50 of the fit rows' precip terms, `score_severe` = at p90, every other
  feature the Unit's own. `eta(model, feats)` is the SAME function offline and live, which is
  what stops the two numbers drifting apart.
- **Verified by independent replay on the real root, not by re-running the builder:** all
  13,310 model-scored bus stops and all 445 complexes reproduce to 1e-12 from the coefficient
  JSON alone (pure SQL, no repo code); all 15,166 `score_index` values equal DuckDB's
  `cume_dist() OVER (PARTITION BY kind ORDER BY score_ref)`; the per-kind CDF knots match the
  table's own count/min/max.
- **Coverage, and where the fallback bites.** `flags` is a closed vocabulary, never NULL, and
  empty for 14,726 rows: `elev_ring15_fallback` **36** (29 bus stops + the seven complexes) ·
  `no_dem_footprint` **60** · `no_matrix_row` **0** · `score_fallback_kind_median` **60** ·
  `no_surge_margin` **404** (344 Cells scored through a taxi Zone + the same 60 stops). The 60
  out-of-DEM stops take the **kind-median** score — an imputed SCORE, declared in flags, which
  is the one thing that is not an imputed elevation.
- **`no_matrix_row` is a new flag and it is 0 here on purpose.** A complex with no scorable
  doorway cannot be a max over doorways; on this registry every complex has one, so the count
  is gated at 0 and any regression fails the build. On a partial fixture root it is NOT 0,
  which is why the fallback generalises instead of crashing.
- **The seven zero-grade_ok complexes are RE-DERIVED every build** and gated as
  `{complex_id: name}` — ids are the gate, names ride along as the drift canary. A name-keyed
  set matches 18 on the real root, asserted in a test so the trap cannot quietly stop being
  real.
- **The version chain reconciles end to end.** `matrix_version` is read from the matrix footer
  AND recomputed from `label_version`/`features_version`/`precip_identity` (equal on the real
  root), and the fits' own `matrix_version` must equal it — so coefficients fitted on a
  different table are refused rather than silently scored. `score_version` covers exactly what
  can move a published score; the flag vocabulary, the assertion scope and the informational
  scale band are deliberately OUT, so a reworded sentence cannot make the live model tier
  refuse itself on version skew.
- **Mutation-checked, 5/5 red, pristine control restored and run last:** widening `IN_WINDOW`
  to include the antecedent (6 failed + 19 errors — it breaks the build outright, exactly as
  the ticket warned) · dropping the non-negative assertion · scoring through a sigmoid ·
  taking MIN instead of MAX over child entrances · dropping the `no_dem_footprint` reason.


## Adversarial review round (same session, before landing) — what it changed

An independent reviewer applied 19 mutants to the module and re-ran all tests each time.
The scoring maths, the complex rollup and `cume_dist` survived every attack; **seven real
defects came back and all seven are fixed.** What they were, because each is a shape worth
recognising rather than a typo:

- **`score_severe >= score_ref` was a COINCIDENCE, not the asserted invariant.** The
  in-Window assertion says nothing about the net. Measured: the p50 -> p90 shift is a
  per-Unit CONSTANT summing the in-Window gain and the antecedent, **point +1.1940 and
  -0.2657 (net +0.9283)**, cell +1.1831 and +0.0262. Strengthen the point antecedent past
  about **-0.42** with both in-Window coefficients still positive, and every point row ships
  with a "severe" storm scoring BELOW a median one. Now a separate gate in `_gates`, and the
  test no longer carries a causal name the code cannot support.
- **A gate that could not fire.** The Cell drift check summed three `count(DISTINCT ...)`
  and compared to 3 — but `count(DISTINCT ...)` SKIPS NULLs, so **2 + 1 + 0 also reaches 3**
  and a drifting column passed while `min()` silently picked the smaller value. Now a TUPLE
  comparison, matching what the point query always did. Same fix added `kind`/`complex_id` to
  the point tuple, which were aggregated with `any_value` outside any gate.
- **The published CDF's interior was unasserted.** Replacing `np.percentile` with
  `np.linspace(min, max, 101)` — a curve with no relation to the distribution — left the
  suite green, and under it a Cell at the true median reads as the **24.9th percentile**.
  Endpoints-and-sorted is not a CDF test. Now every one of the 101 knots is asserted against
  DuckDB's `quantile_cont`, which also kills the subtler `method="lower"` mutant (the two
  estimators diverge most in the TAILS — up to 5.0e-2 at p99 — exactly where a sampled check
  does not look).
- **`score_version` claimed more than it covered.** `SW_DUMMY` maps a stormwater level to a
  coefficient name; **permuting it moves every point score**, and `models_of`'s guard is set
  containment, which a permutation satisfies. The digest did not move. `SW_DUMMY` and the
  kind indicator are now IN it (score_version is therefore `dda793c2c8c7`, not the
  `dd8636f9bb70` of the first build), and the docstring now states the real limit: this is a
  hash of VALUES, so the module's own code rides only as labels — the tests, not the stamp,
  are what hold the rules.
- **The loader contract had a gap the replay test could not see.** The artifact made a
  consumer re-derive `"not-analyzed" -> "sw_not_analyzed"` from spelling, and the one test
  that replays a published score from the artifact alone used the CELL role — the only one
  with no dummies, no kind indicator and no rollup. `preprocessing.stormwater_dummy` and a
  structured `kind_indicator` are now published, and a second test replays the POINT model
  and the complex rollup out of the artifact alone.
- **`arg_max` and `max(event_id)` decouple under NULL.** `arg_max(v, e)` skips rows whose
  VALUE is null; `max(e)` does not. A NULL density on the newest event would score a Cell off
  an older one while `density_311_3y_as_of` still published the newest date. Zero such Cells
  today; now gated, and the published as-of date is asserted (swapping it for `min` used to
  ship silently).
- **Three defensive gates were decoration** — the NO-NULL/finite check, the matrix-staleness
  check and the margins-vs-registry universe check could all be deleted with the suite still
  green. All three now have firing tests.

Two honesty defects in my own prose were also corrected: a test docstring claimed the
artifact "carries no metric at all" when `complex_rule.evidence` quotes the null result
(CSI 0.0025) as its disclaimer — the assertion now pins metric FIELDS and pins that the only
quoted metric lives in that one evidence string; and the `cdf` note claimed to be "the same
distribution `score_index` reports" when it is the same DATA under a different estimator,
agreeing to within ~0.6 percentage points rather than exactly.

**MEASURED CORRECTION, repo-wide: "86 St" names SIX complexes, not five** — ids 38, 79,
158, 311, 397, 476. The 18-total is right and the trap is unchanged in force; only the
number was wrong, inherited from `flood_matrix.py:82` and repeated in TRAPS and this
ticket. Corrected here and in TRAPS; the copy in `flood_matrix.py` is flood 08's file and is
named there for a later session rather than edited mid-wave.


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
  299: Dyckman St}`; a name match returns 18 because "86 St" alone names SIX complexes
  (MEASURED by flood 10 2026-08-24 — ids 38, 79, 158, 311, 397, 476; the repo-wide "five"
  was wrong, the 18 total was right).
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
  Measured on `coef_raw`, per role (assert against the role you are building):
  `log1p_precip_max_mm_1h` point **+0.449** / cell **+0.379**, `log1p_precip_total_mm` point
  **+0.601** / cell **+0.735** — positive in both. But
  **`log1p_antecedent_mm_24h` is NEGATIVE at point grain (-0.093)** while positive at Cell
  grain (+0.011). The
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
