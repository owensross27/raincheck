# 08 — Training table: the event-Unit design matrix

**What to build:** The one table both fits read: every (Unit, event) row with the frozen feature vector,
negatives generated at read, era rules applied, and the barred-features wall asserted — so the fit
step is a read, not a judgment call. Spec: Exposure score (features, era rules); Testing seam 1.

**Blocked by:** 03, 05, 06

**Status:** ready-for-agent

- [ ] grain (unit, event), pluvial events only; Sandy polygon labels are excluded from fit rows (one coastal event would mint ~250–350 of ~1,350 cell positives); negatives via ticket 05's generator under the coverage calendars
- [ ] era rules: fit rows are AORC Precip source, union events 2010–2025; the 2026 pre-MRMS gap (2026-01-01..08-13 by date range) is tagged validation-only; the MRMS era is tagged out-of-sample replication and read against the 0.86–0.92 Pass2/AORC scale band
- [ ] point-model features, frozen pre-fit, log1p on precip: running max mm_1h in Window, Window total, antecedent mm_24h frozen at Window open, elevation, ONE relief term ((elev − ring15_med) in feet), stormwater category (4 levels: deep / nuisance / analyzed-none / not-analyzed — never imputed), kind indicator
- [ ] cell-model features: the three precip terms, stormwater area shares, own-source 311 trailing density (3 years strictly before Window open — the chronic-reporter control)
- [ ] barred-features assertion: no FloodNet-derived, grade_ok/epoch-delta, alert-derived, borough, asset-count or impact columns exist in the matrix
- [ ] leakage checks as tests: no feature reads information after Window open (antecedent frozen at open; trailing density strictly before)
- [ ] DuckDB contract tests: grain uniqueness, positives match gold/flood_labels, era tags, version stamps chaining on label/features/precip identities
