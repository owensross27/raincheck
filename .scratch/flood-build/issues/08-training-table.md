# 08 — Training table: the event-Unit design matrix

**What to build:** The one table both fits read: every (Unit, event) row with the frozen feature vector,
negatives generated at read, era rules applied, and the barred-features wall asserted — so the fit
step is a read, not a judgment call. Spec: Exposure score (features, era rules); Testing seam 1.

**Blocked by:** 03, 05, 06

**Status:** DONE 2026-08-24 (branch `flood08-training-table`) — see the close-out below

- [x] grain (unit, event), pluvial events only; Sandy polygon labels are excluded from fit rows (one coastal event would mint ~250–350 of ~1,350 cell positives); negatives via ticket 05's generator under the coverage calendars
- [x] era rules: fit rows are AORC Precip source, union events 2010–2025; the 2026 pre-MRMS gap (2026-01-01..08-13 by date range) is tagged validation-only; the MRMS era is tagged out-of-sample replication and read against the 0.86–0.92 Pass2/AORC scale band
- [x] point-model features, frozen pre-fit, log1p on precip: running max mm_1h in Window, Window total, antecedent mm_24h frozen at Window open, elevation, ONE relief term ((elev − ring15_med) in feet), stormwater category (4 levels: deep / nuisance / analyzed-none / not-analyzed — never imputed), kind indicator
- [x] cell-model features: the three precip terms, stormwater area shares, own-source 311 trailing density (3 years strictly before Window open — the chronic-reporter control)
- [x] barred-features assertion: no FloodNet-derived, grade_ok/epoch-delta, alert-derived, borough, asset-count or impact columns exist in the matrix
- [x] leakage checks as tests: no feature reads information after Window open (antecedent frozen at open; trailing density strictly before)
- [x] DuckDB contract tests: grain uniqueness, positives match gold/flood_labels, era tags, version stamps chaining on label/features/precip identities

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


## Close-out (2026-08-24, branch `flood08-training-table`)

**Shipped:** `src/raincheck/flood_matrix.py` -> `gold/flood_matrix`, `make flood-matrix
[CENSUS=1]`, `tests/test_flood_matrix.py` (20 tests, 12 s, one Spark session for the
fixture labels). Real build: **1,006,123 rows**, `matrix_version =
8bc1e8912b1badadb69fa0bb5c676a65e0b8200b`, reproduced identically on two runs.

### The shape ticket 09 reads

One table, one row per (Unit, event), column `role` naming which fit reads it:

| role | kind | rows | positives | rate |
|---|---|---|---|---|
| `fit_point` | entrance | 280,595 | 1,177 | 0.42% |
| `fit_point` | bus_stop | 502,756 | 2,831 | 0.56% |
| `fit_cell` | cell | 179,683 | 6,554 | 3.65% |
| `validate_complex` | complex | 43,089 | 118 | 0.27% |

Columns: `asset_id, kind, event_id, cell, complex_id, role, era, flooded` +
`log1p_precip_max_mm_1h, log1p_precip_total_mm, log1p_antecedent_mm_24h` (every role) +
`elev_ft, relief_ft, stormwater_cat` (fit_point) + `share_deep, share_nuisance,
share_not_analyzed, density_311_3y` (fit_cell) + `matrix_version`.

- **The precip terms are stored ALREADY log1p'd.** Do not transform them again. Raw mm is
  recoverable with `expm1` (ticket 10's reference forcings).
- **`complex_id` rides on the entrance rows.** Complex score = max over child-entrance
  scores is a `GROUP BY complex_id, event_id`, not a second join into `ref/assets`.
- Complex rows carry the shared precip terms and NULL for every point/Cell feature. They
  are never fit rows; `role` says so and a test asserts it.

### The pairable delta, published rather than hidden

Running the POSITIVES through `flood_labels.pairable()` drops **4,069 of 14,749**
pluvial fit-era positives — and **4,068 of them are bus stops**, against 2,831 bus-stop
positives kept. Pre-2020 bus-stop labels lose to the `BUS_STOPS_FROM` anachronism rule
that already deletes every pre-2020 bus-stop NEGATIVE, so keeping them would have
manufactured a 2.4x class imbalance out of bookkeeping. The remaining 1 is a complex.
The full census rides in the file's parquet metadata (`census`, `gates`).

### Measured facts that correct the spec / this ticket

- The spec's **"155 alert-sourced complex-event pairs"** is superseded: `gold/flood_labels`
  holds **140** complex labels in total, **118** of them on pluvial fit-era events. That
  118 is the size of the independent complex-grain validation set. Corrected in BOTH
  spec copies (`.scratch/flood-build/spec.md` and `.scratch/flood/spec.md`) and in flood
  09's ticket file. Deliberately NOT rewritten: `.scratch/flood/map.md`,
  `.scratch/flood/issues/08-exposure-score-design.md` and
  `.scratch/flood/assets/09-adversarial-verdicts.json` are dated records of what the
  wayfinder decided and measured at the time — a record, not an instruction.
- **`stormwater not-analyzed = 745` splits, and the two exclusions overlap exactly.** All
  60 out-of-DEM-footprint stops are Nassau County, which is outside DEP's study area, so
  all 60 carry `not-analyzed`: 745 = **685 in the matrix + 60 excluded**. Both numbers are
  frozen in `EXPECT` and the arithmetic is asserted.
- **The seven zero-grade_ok complexes cannot be gated by NAME.** Station names are not
  unique — "86 St" alone names five complexes and a name match returns **18**, not 7. They
  are frozen by `complex_id` with the name each must still carry (the `flood_labels.OPENED`
  precedent) and the set is re-derived at build: `{59: 9 Av, 74: 18 Av, 75: 20 Av,
  78: Avenue U, 79: 86 St, 134: Sutter Av, 299: Dyckman St}`.
- Every entrance, bus stop and complex sits in a `cells_scored` Cell (measured: zero
  exceptions), so flood 06's coverage assertion — which only covers `cells_scored` —
  covers every Unit in this matrix. The build asserts precip totality anyway.

### Policies this ticket owed

- **Out of the DEM footprint: EXCLUDE-WITH-COUNT.** The 60 Nassau stops are dropped, the
  count lands in the file's `gates` metadata and in a frozen `EXPECT`, and the build
  raises rather than publish a NULL elevation on a fit row. A separate gate catches a
  point Unit with no `asset_features` row at all — that is registry drift, a different
  fact from out-of-footprint, and must not be miscounted as it.
- **The ring15_med fallback runs PER ROW, before any aggregate** (`elev_source()`). A
  fallback row reports `relief_ft = 0.0` — it has no relief information and says so rather
  than imputing a neighbourhood delta it never measured. 70 point Units use the fallback.
- **Sandy leaves by event CLASS, not by a special case**, and the build asserts no
  Sandy-sourced positive lands on a pluvial fit-era event.

### The leakage contract, as arithmetic

The Window is **(open, close]**. An hour STAMPED at Window open covers the hour BEFORE the
Window, so it is antecedent, not Window — and that same row is where `mm_24h` is frozen.
One precip scan serves both terms, which makes the freeze structural. The fixture plants
99 mm on the at-open hour and 50 mm on a spike hour inside the Window, and `mm_24h` = 7 at
open against 999 everywhere else, so a widened Window or an unfrozen antecedent lands a
wrong number rather than a subtle one. The 311 control reads **strictly before** Window
open over 3 years and is recomputed independently in Python in the test.

**Mutation-checked** (each mutant turns a named test red, verified 2026-08-24): Window
swallowing its open hour; antecedent not frozen at open; positives bypassing `pairable`;
the 311 control reading into the Window; the out-of-footprint exclusion removed; a barred
column (`source_mix`) riding along. The last two fail at BUILD time, before bytes are
written.

### Limits recorded, not hidden

- `density_311_3y` is a COUNT over 3 years; H3 Cells are equal-area, so it is a density up
  to one constant. It is not divided by anything.
- The matrix emits FIT rows only, because AORC has no 2026 year. `era()` is the pure seam
  tickets 09 and 18 call for the other two eras: `fit` / `validation_only` (2026-01-01..
  2026-08-13) / `replication` (`MRMS_FROM = 2026-08-14`+). Measured on the landed spine:
  195 fit, 10 validation_only, 1 replication.
- `precip_identity()` names the built AORC Cell-month partition SET, not the pixel bytes.
  A silently rewritten month with the same name would not move the stamp.
