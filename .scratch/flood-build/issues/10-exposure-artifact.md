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
