# 04 — Flood observations and the event spine

**What to build:** `silver/flood_obs` (every label-grade flood observation in one table) and
`silver/flood_events` (the deterministic spine of dated flood events with UTC windows), with the
311 thresholds re-measured on the four-literal union and canaries on every frozen source literal —
so "during the event" means the same hours everywhere downstream. Spec: Labels and the event
spine; Testing seams 1 and 2.

**Blocked by:** 02

**Status:** in-review (built, reviewed and re-verified 2026-08-23; worktree mystifying-germain-35e4d4, branch claude/mystifying-germain-35e4d4)

- [x] `silver/flood_obs` GeoParquet (~60K rows), label-grade sources only: 311 street/highway flooding points, FloodNet events from the curated Socrata event table (never the row-capped raw API), station-labeled alerts from ticket 02, USGS high-water marks, Sandy inundation polygons; columns source, source_id, ts_utc, obs_ts_kind {incident, report, alert}, geometry, Cell, depth_mm (nullable), text (nullable); covariate sources never enter
- [x] the 311 descriptor set is FOUR exact literals — 'Street Flooding (SJ)', 'Highway Flooding (SH)' and their 2023-09 renames 'Flooding on Street', 'Flooding on Highway' — and the daily-count p99 triggers are RE-MEASURED on the union per era-dataset (nearest-rank), frozen as named constants with the era they were measured on (the original 97/84 were legacy-literal-only and biased low across the 2023-09..2026 overlap)
- [x] spine triggers, any of: (a) 311 daily count ≥ frozen p99; (b) ≥ 1 station-naming alert flood event; (c) NOAA Storm Events flood types by county FIPS and the enumerated coastal zone names; (d) CO-OPS water level at the Battery or Kings Point ≥ that station's own NWS minor threshold, station datum both sides, two consecutive readings
- [x] contiguous event-days merge; window = [NY-midnight of first day − 3 h, NY-midnight after last day + 3 h] as UTC hour_end bounds — never observation-derived; event class from Storm Events FLOOD_CAUSE where present, else trigger-based; Dec–Mar pluvial days at or below freezing reclass to snowmelt and leave the pluvial fit
- [x] fixture: 2023-09-29 appears as an event-day under the four-literal union
- [x] canary: each of the four 311 literals matches trailing-30-day rows, and every frozen source literal and endpoint answers — the build fails otherwise
- [x] spine derivation is a pure function tested on fixtures; DuckDB contract tests on both written tables

## Build notes (2026-08-23, worktree mystifying-germain-35e4d4)

Both tables are built and landed from the real sources. `make flood-obs` then
`make flood-spine`; every source is snapshotted once under `<root>/archive/flood`
(~110 MB, against a 4.6/10 GB Bronze budget) so a rebuild never calls the network.

**The re-measured 311 pins (the ticket's headline).** Nearest rank (ceil(0.99·N)-th
smallest over the N days with at least one report) on the FOUR-literal union, per
era-dataset, measured 2026-08-23 and frozen as `flood_spine.P99_311`:

| era-dataset | span | reports | days ≥ 1 | p95 | **p99 (frozen)** | legacy-two p99 | max |
|---|---|---|---|---|---|---|---|
| `76ig-c548` | 2010-01-02..2019-12-31 | 28,538 | 3,166 | 37 | **97** | 97 | 279 |
| `erm2-nwe9` | 2020-01-01..2026-08-21 | 23,512 | 2,319 | 30 | **85** | 84 | 1,233 |

The eras do not overlap (erm2 holds zero legacy-literal rows before 2020), so the
threshold is per-dataset with no seam. The union moves the modern pin 84 → 85 only, but
that was never where the two-literal bias hurt: the union is what makes **2023-09-29 the
modern era's biggest day at 1,233 reports** (3× the runner-up), and it is also the week
the city renamed the dropdown. 76ig is unchanged because the renamed literals never
appear before 2020. `build()` re-measures at every build and refuses to run if the pins
no longer reproduce — the thresholds define the event universe, so they may only move
deliberately.

**What landed.** `silver/flood_obs` 52,014 rows, one GeoParquet part, 24 MB:

| source | rows | note |
|---|---|---|
| 311 | 48,177 | of 52,050 reports; 3,873 (7.4%) carry no usable point and are counted but not placed |
| floodnet | 2,927 | curated event table, depth inches → mm |
| mta_alert | 148 | 2015-12..2026-08, 94 distinct complexes, after cross-event reconciliation |
| usgs_hwm | 270 | Sandy 111 (matches the vault's independent count) + Ida 159 |
| sandy | 492 | field-verified inundation polygons, 2,334,138 vertices, full resolution |

`silver/flood_events` 206 events over 248 event-days, 2010-03-13..2026-08-20 — pluvial
141, coastal 44, mixed 18, snowmelt 3, unclassified 0. Trigger day counts: 311 58,
alert 89, storm 105 (80 pluvial / 25 coastal), tide 80. **2023-09-29 is an event-day**
under (a), (b) and (c), window `2023-09-29T01:00Z .. 2023-09-30T07:00Z` — the calendar
rule exactly. Note for ticket 09: the union is **248 event-days, not the 115** that
ticket's coverage-honesty line quotes; 09's figure predates all four triggers running
over 2010-2026 on the re-measured pins, and its subway/bus coverage fractions must be
recomputed against this spine.

**Decisions taken here (each one a place the design left a choice).**

1. **Alert observations land one row per (complex, physical flood), not per (event,
   complex).** flood_alerts.py's inline comment says "one flood_obs row per pair", but
   that comment predates this ticket being handed the reconciliation duty. One physical
   flood mints several event ids — the 2026-08-20 night put World Trade Center under four
   and Utica Av under two — and a per-event row would count that night four times in any
   downstream density. The merged event ids stay visible in `source_id`
   (`264031+264043+264050+264060+264063:624`).
2. **The reconciliation rule is span OVERLAP, with no gap tolerance**, because the
   measured disagreements overlap: 264048 runs 23:37→02:43 (ends active on Utica Av) and
   264063 runs 01:17→03:30 (reports it cleared). The newest revision across the merged
   events owns the state, which resolves that disagreement to `cleared`. No invented
   constant was needed, so none was added.
3. **All three alert eras run through ticket 02's ONE extractor**, by rendering the
   Socrata archives' own incident keys into 02's frozen `alert_id` grammar. This required
   widening `ALERT_ID_RE`'s event component from `\d+` to `[^:]+`: the 2012-2020 archive
   keys incidents by a status_id GUID. The live grammar stays a strict subset and 02's
   tests still pass unchanged. Without the pre-2020 era the alert signal starts in 2020;
   with it, 2015-12 (and the extractor's own Socrata-era holdout finally covers data that
   is actually in the table).
4. **FloodNet stamps are UTC, not New York.** Measured, not assumed: over the 141 events
   inside the built AORC precip months, mean `mm_1h` in the sensor's own Cell at the
   flood-start hour peaks at 8.49 reading them as UTC and falls monotonically either side
   (3.25 at the −4 h EDT reading). 311 and the alert archives ARE New York floating time.
   Reading FloodNet as local would have shifted every evening event onto the wrong NY day.
5. **Spine temperature is GHCN-Daily Central Park TMAX, not AORC `t2m_c`.** The design
   names t2m_c, but AORC covers 5 of the ~52 months the flood era needs until ticket 06
   lands its extension — a spine whose event classes change when a LATER ticket runs is
   not a spine. GHCN spans the whole era in one 18 MB station file and matches the live
   detector's own Central Park choice. The reclass fires on 3 events, all Dec-Mar
   alert-triggered days that never rose above freezing.
6. **A SODA query that answers zero rows fails the build** rather than caching the hole.
   This is not theoretical: the two alert archives do not share an agency vocabulary
   (`Subway` vs `NYCT Subway`), one filter for both silently cached an EMPTY 2012-2020
   archive, and the only symptom was an alert trigger that started in 2020.
7. **Storm Events snapshots keep the New York subset only** (the national details CSVs are
   ~50 MB/year × 17 and the archive root is on a byte budget). The published file names
   carry a version and creation date that move under NCEI's feet, so the year's file is
   resolved from the live listing and its real name printed at fetch.
8. **USGS high-water marks carry `depth_mm` NULL.** `elev_ft` is a peak water-SURFACE
   elevation in NAVD88, not a height above ground; ticket 07 owns the ground elevation
   that would turn one into the other. The county filter is state-qualified — STN answers
   nationwide and Kings/Richmond are county names in other states Sandy and Ida also hit.

**Corrections to earlier measurements.** The wayfinder recorded ~2.4% of 311 rows lacking
coordinates; measured here on the four-literal union it is **7.4%** (10.7% in the legacy
era, 3.5% in the modern one). The `sensor_id` "trailing-space quirk" attributed to the
FloodNet join in wayfinder 01 is a misattribution — the documented trailing space is on
`mounted_over`; `sensor_id` values are clean on both sides. The real join hazard is that
the event table is not a subset of the deployment table (`BK-w-st-kent-st-31i7yc` has
events and no location row), so the join is a left join whose orphans are dropped and
reported, never landed at (0, 0).

**Debt left deliberately.**
- The tide trigger watches the Battery and Kings Point only; Jamaica Bay / the Rockaways
  have no CO-OPS gauge (recorded in `flood_spine.COOPS_BLIND`). A Coastal Flood row in
  Storm Events still classes those days coastal, which is why storm-coastal-only days are
  COASTAL and not, as a first cut had them, `unclassified`.
- `spine_version` chains the thresholds, vocabularies, window rule and source as-of stamp,
  so ticket 18's alternate universes stamp differently by construction. `label_version`
  (ticket 05) should chain THIS, plus assets_version.

## Adversarial review (2026-08-23, four lenses + refutation round)

Four independent lenses (correctness/time, spec conformance, test-quality mutation, and
over-engineering) filed findings; each was handed to a skeptic instructed to refute it.
The Mac crashed mid-run and the surviving findings were judged here. What changed:

**Refuted, but worth recording so nobody re-files it.**
- *"Storm Events stamps are Eastern STANDARD time — a one-day shift."* Every NYC row does
  carry `CZ_TIMEZONE='EST-5'`, so the inference is reasonable, but the field is a zone
  LABEL, not the applied offset. Measured the same way FloodNet's clock was, over the 68
  NYC county flash/flood rows inside the built AORC months: citywide mean mm_1h at the
  implied hour is **24.84 reading the stamps as NY wall time vs 18.13 as EST-5**, a clean
  single peak at +4 h. The stamps are NY wall clock; the code was already right, and the
  measurement is now in `_storm_span`'s docstring so the next reader does not "fix" it.
- *"The 311 rename canary is anchored to the frozen ASOF, so its trailing-30-day window
  never advances."* ASOF also gates the DATA — it is the stamp on every snapshot the build
  reads — so the canary window and the snapshot window move together. Bump ASOF to refresh
  and the canary asks about the new window, which is exactly when a rename must be caught.
  Docstring now says so.
- Alert trigger (b) using the flood's first-seen day rather than its whole span: worth 4
  extra event-days in 16 years, and the window's own +3 h pad already covers a flood that
  runs past midnight, so the label still attaches. Left alone.

**Confirmed and fixed.**
1. **The tide rule was untestable** — a reviewer mutated `COOPS_CONSECUTIVE` 2 → 1 and the
   whole suite still passed. The run-scan is now a pure `exceedance_days()` and the rule is
   pinned directly: one spike does not trigger, two adjacent readings do, two exceedances
   across a data gap do not, and the boundary is at-or-above.
2. **`cov_tide` was written but never asserted** (hardcoding it True passed the suite), and
   the `>= p99` boundary was indistinguishable from `>`. Both now have tests, and the
   coverage test asserts the fixture exercises BOTH values of the flag rather than one.
3. **Storm Events had no coverage flag and a silent skip.** The source LAGS: NY rows are
   published only through **2026-05-29**, so the 4 most recent events (2026-07-06 onward)
   were reporting `by_storm=False` — indistinguishable from "no storm activity". Added
   `cov_storm` from the measured publication horizon, and a missing details file for a PAST
   year now raises instead of printing and continuing.
4. **The alert coverage floor was the dataset era, not the label era.** `COVERAGE_ALERT[0]`
   is 2012-10-02, but the spec's calendar says "alerts effectively 2016+" and the extractor
   agrees (1 observation in 2015, 10 in 2016, ~15/year after). Coverage now uses
   `ALERT_LABELS_FROM = 2016-01-01`: a day wrongly marked covered mints FALSE NEGATIVES in
   ticket 05's anti-join, so the floor is deliberately conservative. 57 of 206 events are
   now alert-uncovered.
5. **A comment stated a share the data contradicts.** It claimed the 2023-09 renames "carry
   a third of the modern record"; they are 1,445 of erm2's 23,512 rows (6.1%), or 11.9% of
   the 2023-09-28-onward overlap era. Corrected to the measured numbers.
6. Smaller: the p99 reproduction gate compared thresholds by identity (`is`), so an
   equal-but-distinct dict silently skipped it — now `==`. `reconcile()` guarded against a
   None seen-span in its sort key but not in the comparison two lines later — it now
   refuses the input outright, because a None there means an upstream shape changed.
   `COOPS_BLIND` was a constant nothing read; it is a comment now.

**Still open, deliberately.** The spine canary and the flood_obs canary are separate (each
module canaries its own endpoints) and both are skippable with `--skip-canary` for an
offline rebuild from snapshots — which is the reproducibility case the design asks for, and
the case where the canary SHOULD be expected to fail years later.

## Domain fact from flood-02 (2026-08-23, recorded by the orchestrator)

alert_id is NOT a stable text key: MTA revises (header, description) IN PLACE under the
same alert_id — measured 14 of 24 water alert_ids carrying multiple distinct texts, 50
revisions total. Any fold keyed per alert_id silently keeps one arbitrary variant. The
spine's cross-event merging and any text-derived field must work at revision grain (or
deliberately reduce revisions with a stated rule), not assume one text per id. Ticket 02
is re-measuring its extractor precision at revision grain for the same reason.

## Inherit from flood-02's landing (2026-08-23, recorded by the orchestrator)

- The frozen keys are named constants in src/raincheck/flood_alerts.py: REVISION_KEY,
  INCIDENT_KEY = ("event_id",), OBSERVATION_KEY = ("event_id","complex_id"), plus
  ALERT_ID_RE and MIN_PRECISION. Import them; do not restate the tuples.
- Routes fold per alert_id, NOT per revision — in-place edits split informed-entity rows
  across revisions, and a revision-local route set manufactures ambiguity (caught by
  adversarial review; flood-02's own test had blessed the loss).
- Cross-event state reconciliation is THIS ticket's job: concurrent events disagree about
  a shared complex (measured: 264048 ends active on Utica Av while 264063 reports it
  cleared). Ticket 13 renders per-(event,complex) state from the newest revision and does
  NOT reconcile.
