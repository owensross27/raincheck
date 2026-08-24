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

## Inherit from flood-03's build (2026-08-23, recorded by the orchestrator)

Two measured facts that change this ticket's design:
1. SEVEN complexes have entrances but ZERO grade_ok entrances (9 Av, 18 Av, 20 Av,
   Avenue U, 86 St, Sutter Av, Dyckman St). A read-side GROUP BY over grade_ok children
   returns NOTHING for them while gold/flood_exposure mandates no NULL scores — apply
   the ring15_med fallback BEFORE the aggregate, not after.
2. 60 bus stops have no elevation and no ring fallback: MTA Bus Company stops in Nassau
   County, outside the NYC DEM footprint entirely. This ticket owes them an explicit
   policy (exclude-with-count, or a stated out-of-footprint class — never silent NULLs).
3. The stormwater not-analyzed count at point grain is 745 total: 673 inside DEP's
   exclusion mask + 72 outside the study area entirely. (Corrects the 673 quoted
   mid-day on 2026-08-23, which was only the in-mask share; flood-03's ticket file
   carries the same breakdown.)

## Inherited from the wave-1 landing (2026-08-24, recorded by the gate)

- **Gate satisfied**: flood 05 is landed AND verified — tests/test_flood_labels.py
  23/23 green inside the 557/0/0 landing suite, master `7b7bfc8`. The
  gold/flood_labels contract you consume is now backed by a green run, not a claim.
- **DuckDB read-path trap (this ticket reads several tables with `duck`)**: on this
  DuckDB, `rel.arrow()` returns a LAZY RecordBatchReader on the relation's own
  connection. Registering unconsumed readers back into that connection and querying
  them DEADLOCKS at 0% CPU — this, not table size, was flood 05's ">400 s hang".
  Consume readers immediately (`.read_all()`) or skip the bridge entirely with
  `rel.select(...).create_view(name)`. Also `rel.query("t", sql)` lazily registers
  the shared virtual name "t": two lazy `.query("t", ...)` relations on one
  connection cross-bind — the second silently rebinds the first's "t".
