# 10 Backfill slice and speed-derivation rules

Type: grilling
Status: resolved
Blocked by: 06, 09

## Question

The `nycbuspositions` archive (2017-07-14 to 2024-09, ~20 MB/day CSV.xz, speed
column empty) is the fastest route to the headline insight. Which slice first
(Ida Sept 2021 and 2023-09-29 flood plus one dry control month each, ~120 days,
~2.4 GB, was the reality-check proposal), what are the rules for deriving speed
from successive pings (geodesic distance / dt, dt bounds, outlier cutoffs, stop
dwell handling, trip boundary resets), how do archive rows map onto the Silver
schema from ticket 09 so history and live are one table, and what is the
acceptance test (the Ida hour shows the expected signal on a fixture day)?
The Answer is the slice and the rules; loading it is downstream build work.

## Answer

Resolved 2026-08-16 by grilling; measured first (archive census 2017-2024, Leg
experiments on the two storm days and their controls, AORC wet-hour census over the
whole span, benchmark and archiver forensics), verified against primary sources, then
two adversarial reviews (transit/analysis lens, data/Spark lens) reversed six parts of
the first draft before the round. All four recommendations accepted as-is ("all rec").
The slice, the rules, the landing and the tests are the asset
[research/10-backfill-slice-and-speed.md](../../../research/10-backfill-slice-and-speed.md);
the numbers are in [research/10-backfill-evidence.md](../../../research/10-backfill-evidence.md)
(scripts `10-backfill-speed-evidence.py`, `10-aorc-wet-census.py`,
`10-backfill-terminal-variants.py`, table `10-aorc-month-cell-stats.parquet`); this
Answer is the index.

1. **The slice: two contiguous windows, no separate control months.** W1 = service
   days 2021-08-16..10-15, W2 = 2023-09-01..10-31 (122 service days, 124 UTC-day xz
   files incl. D+1, ~2.5 GB). Ida and the 2023-09-29 flood sit inside their own weeks;
   86% / 79% of Cell-hours are dry by 08's rule so the baseline is built in; the AORC
   census over 96 months makes 2023-09 the wettest month of the archive and W2 the
   wettest window (371K wet Cell-hours, 104 wet Hours; W1 238K / 73). The two windows
   are baselined and fitted separately (2021 vs 2023 regimes) and each is the other's
   out-of-sample check; the independent unit is the wet event, not the Cell-hour, so
   errors cluster by event and per-Cell ratios are published only with intervals.
   Calendar confounds inside the windows (school start 09-13-2021 / 09-07-2023, Labor
   Day, High Holidays, UNGA week) become day flags in a 124-row `ref/calendar`. Picks
   C1/D1 (W1) and C3/D3 (W2) x six feeds = 24 downloads from ticket 13; the Speed path
   needs none and lands first. Hard precondition: the external SSD - the internal disk
   has ~10 GB free, 05's 10 GB Bronze loud stop counts everything under `data/archive/`
   and would trip ~9 days into the conversion (`RAINCHECK_ARCHIVE_ROOT` build item;
   07's "budget covers all of data/" corrected: only `data/archive/` is counted).
   Archive facts corrected on the way: the bucket runs to 2024-11-04 (not 09-06), the
   day files are UTC calendar days (Ida's peak hours are in the 09-02 file), the
   archiver is Bus-Data-NYC's `mta-bus-archive` polling the GTFS-RT feed every ~120 s,
   `timestamp` is the vehicle's fix time, zero duplicate Pings, `speed`/`progress`/
   `dist_*` never populated, occupancy a placeholder in every year but 2019.
2. **Speed = chord speed on Legs, rule set R2, pick-free.** Leg = the movement between
   consecutive Pings of one vehicle on the vehicle clock (one Ping per (vehicle_id, ts),
   earliest `fetched_at` kept live); keep same non-null trip_id both ends,
   `0 < dt_s <= 300`, `<= 30 m/s`; a run = gaps-and-islands of (trip_id, start_date)
   per vehicle; drop only **stationary** (< 25 m) legs before the run's first stop_id
   flip / after its last / in never-flip runs (whole-region deletion was rain-
   correlated: 18.7% of the Ida 04Z storm hour vs 12.2% of its control; R2 deletes
   6.7% vs 7.2%), keep stationary mid-trip legs (the phenomenon), carry
   `n_dropped_terminal`; geodesic chord (`ST_DistanceSpheroid`); Cell = H3 res 8 of the
   midpoint (never a third Cell), Hour = `ceil_hour(t_mid)`; route class from route_id
   (`upper(route_id) RLIKE '^(X|BM|QM|BXM|SIM)'` express, `LIKE '%+'` SBS); the
   Cell-hour Speed is the space-mean `sum(dist_m)/sum(dt_s)`, median Leg speed at day
   grain. Measured: Ida hours ending 2021-09-02T03Z/04Z run at 0.77/0.73 of the same
   hours a week earlier and still 0.89 six hours after the rain stopped; 2023-09-29 at
   0.90 for eight hours; not a geographic or route-composition artefact; the
   bus-minute-weighted citywide ratio and the median-Cell ratio are named as different
   estimands (0.78 vs 0.87 at Ida 03Z). Named limitation: the 120 s chord is 6.7%
   (median) short of the 30 s path and shorter when slow, so a chord ratio
   **overstates** a slowdown by an unmeasured 0-10 points (the first draft had the sign
   backwards); every headline carries a chord-corrected companion until along-shape
   distance exists (pick-gated upgrade; the archive positions are OBA-projected so the
   snap is short). At 120 s cadence 18.5% of mid-trip Legs carry no Passage and about
   a third of advances are interpolated: the archive-era rain response is the Leg,
   06's `segment_excess_s` second. Live-era and archive-era Speeds are never pooled
   (08's src rule); `dt_s_sum/n_legs` rides on every aggregate.
3. **Landing: one Bronze, the daily job, two small tables.** `make nbp DATE=`
   converts one xz file to Bronze VP in 05's schema (`archiver.TYPES`; `part-nbp-
   <date>.parquet` under `date=/hour=` from `ts`; `fetched_at` NULL = the archive-era
   discriminator; `start_date` -> YYYYMMDD; occupancy NULL on one-distinct-value days;
   xz sources kept under `data/archive/nycbuspositions/`). `events DATE=D` reads
   Bronze `date IN (D, D+1)`, writes `pick_gap = true` rows until the Pick lands
   (09's schema, no abort), and calls `enrich.legs()` on the same read, aggregating to
   Silver `leg_hours (service_date=)` at (cell, hour_end_utc, route_id, route_class):
   `n_legs, n_vehicles, dist_m_sum, dt_s_sum, leg_speed_p50, n_dropped_terminal,
   n_dropped_dark` (~6 MB/day). `gold MONTH=` rolls `leg_hours` into a new
   direction-free Gold `cell_hour_speed (month=)` (sums only; reads service_date
   month_start-1..month_end, keeps the month's Hours, neighbour-partition check) -
   not columns on `cell_hour_route`, whose event rows are per direction. Gold
   `cell_hourofweek_baseline` is partitioned by window, holds the dry side only
   (`speed_dry`, `n_dry`, `n_legs_dry`) under 08's dry rule **plus a recovery guard**
   `mm_6h < 0.5` (post-Ida hours are dry by 08's rule while buses run 0.80-0.90);
   wet anomalies are scored per wet Cell-hour against the bin's dry Speed and
   aggregated per Cell at analysis time (8.7 weeks x 4-6% wet leaves ~0.35 wet
   observations per Cell x hour-of-week bin). No per-Leg Silver table (fog); precip
   for the slice is 08's tables for the five months.
4. **Acceptance tests.** T1 loader (parity, ms/s gate on real pre-2023 files, bbox,
   three route classes non-empty, convert-twice idempotence, a 2018 20-column file and
   a 2021-11-07 DST fixture); T2 the 84.28 mm fixture (08's, reused); T3 the Ida
   reproduction - hours ending 03Z/04Z at <= 0.85 of the window's own dry same-hour-
   of-week median with n_legs >= 15,000 (2023 report-only; one control day is worth
   +/- 0.05); T4 MTA benchmarks (`58t6-89vi` route x dow x hour, trip-weighted, for
   W2; `cudb-vcni` route x month x day_type summed over periods/boroughs) report-only
   on the first run; T5 Product 3 as a one-off script over the two storm days (Legs
   first, stops once `events` exists); T6 footprint/support (~1,146 Cells, 0 legs in
   AORC-NULL Cells, terminal-drop share storm vs control within 0.01); T7 partition
   idempotence incl. `leg_hours` and the Gold neighbour.

Consequences: CONTEXT.md gains **Leg** and **Speed**; `research/09-storage-schemas.md`
gains the archive Bronze note, the Bronze read rule, `leg_hours`, `cell_hour_speed`,
the baseline's partition/columns and `ref/calendar` (marked 10); comments on 05
(sources root, SSD pressure, `RAINCHECK_ARCHIVE_ROOT`), 06 (Leg first in the archive
era, no-Passage share, DST fixture), 07 (`enrich.legs()`, `nbp DATE=`, pick-gap
write, budget scope), 08 (recovery guard, rain lag, composite windows per Cell,
Product 3 on Legs, AORC gaps), 09 (schema edits), 13 (the 24 downloads), 14
(unblocked; estimands named on the artifact); map and vault corrected to 2024-11-04.
Fog: `silver/legs` if a leg-grain analysis appears; along-shape distance once picks
load; r(v) on weekday captures with a jitter guard; the full 2,278-file backfill
runtime. Build items for `/to-spec`: the converter, `enrich.legs()` + `leg_hours` in
the daily job, `cell_hour_speed` rollup, the baseline with the recovery guard,
`ref/calendar`, T1-T7, `RAINCHECK_ARCHIVE_ROOT`.

## Comments

2026-08-16, from [06 Delay metric design](06-delay-metric-design.md): archive rows
map onto the same event table as live via VP passages (the archive has NO stop-level
TU rows, positions at ~120 s cadence, `trip_start_date` populated, trip_id scheme
identical to today). Schedule metrics for 2017-2024 come from Transitland picks
(ticket 11 resolved; ticket 12 gets the key and proves one download). Ping-to-ping
speed rules remain this ticket's. Measured on 2021-09-01: 1,311,872 unique pings,
906,790 passages, 13.6% of pings on the previous service day.

2026-08-16, from [09 Storage and CRS conventions](09-storage-crs-conventions.md): 09 is resolved, so this ticket is unblocked. Archive rows land
in Silver `events` (schema in `research/09-storage-schemas.md`), batch-written per
`service_date`, ~24 B/row in the backfill era: the 120-day slice is ~2.6 GB and fits
the internal disk, the full 7 years ~56 GB (external SSD). Schedule metrics need the
per-Pick tables (`trips`, `trip_stops`, `service_days`, `shapes`) partitioned by
`pick_id` = zip sha1 (12's resolver). Speed rules: geodesic only
(`pyproj.Geod` / `ST_DistanceSpheroid`), never haversine; dt bounds and outlier
cutoffs remain yours.

2026-08-16, from [08 Weather join design](08-weather-join-design.md): precip for
the slice comes from `silver/precip_cell_hourly` (src=aorc; spec
`research/08-weather-join-features.md`), joined at read on (src, cell,
hour_end_utc) with `hour_end_utc = ceil_hour(arrival_ts)`. The dry-baseline uses
08's Gold defaults: dry = `mm_1h < 0.1 AND mm_1h_prev < 0.1`, wet = `mm_1h >= 1.0
AND t2m_c > 2` (rain, not snow), frozen counted separately, the 0.1-1.0 band
excluded from the binary contrast, onset vs sustained from `mm_6h - mm_1h`; each
with a three-cutoff sweep. Storm windows for the Ida / 2023-09-29 composites are
(t0, t1) parameters over `mm_1h`. Two things 08 asks of this slice: playbook
Product 3 (`RS_Values` at the stop on the two storm days) also reports the
rain-vs-`segment_excess_s` slope both ways (Cell mean vs stop Pixel) so the
aggregation choice is measured; and any per-Cell hotspot claim must survive a
rerun with `cell_pixel` weights aggregated to ~4 km blocks (adjacent AORC Pixels
correlate at 0.996-0.998). Fixture: Central Park's Cell `882a100895fffff` reads
84.28 mm for the hour ending 2021-09-02T02:00Z.

2026-08-16, from [07 Enrichment execution model](07-enrichment-execution-model.md): the
engine is Spark 3.5.3 + Sedona 1.9.1 running natively on the brew `openjdk@17` (no
Docker for Spark); the archive loader lands rows through the same `events DATE=` job
as live (`enrich.py` functions: `passages`, `with_delay`, `with_segments`,
`with_headways`), idempotent per `service_date=` partition by dynamic overwrite;
`ST_DistanceSpheroid` for any distance feeding a speed. Playbook Product 3's raster is
built in-db from the AORC slice (`RS_MakeEmptyRaster` + `RS_AddBandFromArray`, then
`RS_Values` at the stop) - no GeoTIFF. Sizing: session 8.9 s warm, ~0.7 GB RSS, 1.93M
pings H3'd in 1.1 s; a backfill day is the same order. Session settings, `setuptools`
(pyspark's pandas bridge on Python 3.12) and `TZ=UTC` traps are in
`research/07-execution-model.md` section 0/1.

## Comments

### 2026-08-16 — facts from the ticket 13 source sweep, for the grilling

- The `nycbuspositions` bucket also holds `<date>-bus-alerts.csv.xz` (1,429 files)
  and `<date>-bus-messages.csv.xz` (1,409) alongside positions/trip-updates, and a
  `stats/` prefix with TransitCenter's own monthly `speed/<YYYY-MM>-speed.tsv.gz` (26
  months, 2015-2019) and `bunching/` (11 months): a free independent benchmark for
  the speed rules on the same VP data. Owner: Bus-Data-NYC / Neil Freeman.
- Pick resolution for the slice: the trip_id pick code names the zip (12's v2 rule);
  Ida day = C1 (`4b8dec91`), 2023-09-29 = D3 (`61d83dfe`); both are grant-only
  (not in Wayback). Transitland calendars have a 2019 hole (313 d Bronx/Queens/busco,
  83 d Brooklyn/Manhattan/SI): if a control month lands there, `pick_gap=true`.
- data.ny.gov "MTA Bus Schedules: <year>" (2021+) gives the MTA's own bundle-in-effect
  date ranges per day for free (SODA, no key), usable as `ref/bundles` if wanted;
  its schedule times are stripped, so it is not a schedule source unless MTA fixes it.

### 2026-08-16 — measured, adversarially reviewed, round posted; awaiting Ross

Measured (`research/10-backfill-evidence.md`, scripts `10-backfill-speed-evidence.py`,
`10-aorc-wet-census.py`, `10-backfill-terminal-variants.py`): the archive is 2,278
UTC-day files 2017-07-14..2024-11-04 (not 09-06), zero duplicate Pings in 12/12
sampled days, `timestamp` = the vehicle's GTFS-RT fix time from Bus-Data-NYC's
`mta-bus-archive`, `speed`/`progress`/`dist_*` never populated, occupancy a
placeholder except 2019; Legs on the four analysis days (5.48M): dt p50 122 s, chord
p50 312 m, > 30 m/s 0.14% (4 km teleports), trip-change 6%, terminal regions 12%
of same-trip legs and rain-correlated when deleted whole; the 120 s chord is 6.7%
(median) short of the 30 s path and shorter when slow; Ida hours ending 03Z/04Z run at
0.77/0.73 of the week-earlier speed (0.80 at 06Z, 0.89 at 08Z after the rain stopped),
2023-09-29 at 0.90 for eight hours; AORC census over 96 months puts W2 (2023-09/10)
as the wettest window and 2023-09 as the wettest month; MTA `cudb-vcni` (route-month
mph) and `58t6-89vi` (timepoint segment x hour, 2023-24) exist as benchmarks; the
internal disk cannot host the slice under 05's 10 GB Bronze stop. Two opus reviews
(transit/analysis, data/Spark) reversed six parts of the first draft: the chord bias
sign (a chord ratio overstates a slowdown, it is not conservative), the terminal rule
(drop only stationary legs at run ends: R2, rule-neutral across the storm contrast),
a recovery guard on the dry baseline (`mm_6h < 0.5`), leg aggregates in their own
Gold table (direction-free), legs computed in the daily job into `silver/leg_hours`
(no month-window job), converter idempotence and schema from `archiver.TYPES`; plus
the route-class regex (BXM upper case, SBS = `+`), the gaps-and-islands run, the
`events DATE=` pick-gap write rule, T3 rebuilt on the window's own dry same-hour-of-
week distribution and T4 report-only. Round of four decisions posted in chat;
recommendations are the asset `research/10-backfill-slice-and-speed.md` as it stands.
