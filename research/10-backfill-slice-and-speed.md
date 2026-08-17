# 10 Backfill slice and speed rules

Asset of ticket [10 Backfill slice and speed-derivation rules](../.scratch/pipeline/issues/10-backfill-slice-and-speed-rules.md).
Numbers in section 0 come from `research/10-backfill-evidence.md` (four measurement
passes on 2026-08-16: archive census 2017-2024, Leg experiments on the two storm days
and their controls, AORC wet-hour census over the whole archive span, benchmark and
archiver forensics), plus the two adversarial reviews (transit/analysis lens, data/
Spark lens) that reversed six parts of the first draft before the round: the chord
bias sign, the terminal-region rule, the dry-baseline rule, the leg columns' home in
Gold, the leg job's grain, and the converter's idempotence. Vocabulary is CONTEXT.md's;
two terms are new here (**Leg**, **Speed**) and are proposed in section 6.

## 0. Facts the decisions stand on (measured 2026-08-16)

**The archive.** `s3.amazonaws.com/nycbuspositions/YYYY/MM/YYYY-MM-DD-bus-positions.csv.xz`,
2,278 day files 2017-07-14 .. **2024-11-04** (not 2024-09-06 as the map and vault
say; corrected), ~20 MB xz each, five gaps: 2019-11-11..2020-05-23,
2020-05-25..05-31, 2020-06-02..2020-10-10, 2021-01-20..2021-03-17, 2021-03-24..03-26
(the COVID exclusion is nearly free). Producer: Bus-Data-NYC's `mta-bus-archive`
polling `gtfsrt.prod.obanyc.com/vehiclePositions` (GTFS-RT, not SIRI) every ~120 s
(poll gap p50 120 s, p10/p90 92/148). Each file is a **UTC calendar day**
(00:00:0x-23:59:5x Z, verified on 12 files 2017-2024): Ida's peak hours (ending
2021-09-02T01Z-04Z) sit in the **2021-09-02** file. `timestamp` = GTFS-RT
`VehiclePosition.timestamp` (the vehicle's own fix time; the poll clock is not
exported; `mid`, present from 2020-11, is a per-poll message id). Zero duplicate
`(vehicle_id, timestamp)` rows in 12/12 sampled days (~15.7M rows in the ten-day
census, 10.2M in the eight-day Leg pass). Rows/day 1.85M in 2017-18 (cadence p50
126 s), 1.4-1.5M from 2019 (122 s); ~5,000 vehicles; empty `trip_id`/`route_id`/
`stop_id` 0% in 2017-19, 0.2-1.6% in 2021-24. `speed` is the literal `0.00` (2017-19)
or empty (2020-24) - never a measurement. `progress`, `dist_along_route`,
`dist_from_stop`, `block_assigned`, `stop_sequence` are empty in every year (the
archiver never populated them; SIRI's `ProgressStatus=layover` is not in the GTFS-RT
feed). `occupancy_status` is `EMPTY` on 100% of rows in every sampled year except
2019-09-11 (2.96% informative). Schema break: 20 columns through 2019-09, 22 (`mid`,
`stop_sequence`) from 2020-11. The archiver added a ms/s timestamp autodetect on
2023-04-01 ("timestamps are irregular"); the two storm days are clean (0 rows outside
+/-2 days), other pre-2023 days are unchecked - a loader gate, not an assumption.
`trip_start_date` (ISO) is the Service date; trip_id pick codes as 12 (C1 = 2021Jul
on the Ida day, D3 = 2023Sep on 2023-09-29). Route ids: express routes are `BXM1`,
`X27`, `BM1`, `QM2`, `SIM1` (upper case), SBS routes carry a `+` suffix (`B44+`,
`M15+`, `BX12+`; 15-20 routes); nothing in `route_id` says "SBS".

**Legs** (consecutive Ping pairs per vehicle on the vehicle clock; 5.48M pooled over
2021-08-25, 2021-09-01, 2023-09-22, 2023-09-29 - each with its D+1 file so midnight
and the Ida hours are covered): dt p10/p50/p90 = 92/122/153 s, never <= 0, 2.2% >
300 s (vehicle went dark; the dark share is storm-neutral, 2.4% vs 2.0% at Ida 04Z),
0.6% at 2x cadence (the archive is not dropping polls); dist p50 312 m; speed p50
2.57 m/s; > 30 m/s 0.139%, > 25 m/s 0.230%, and that tail is 4 km teleports at
normal cadence (70.6% have dt 90-150 s, dist p50 3,995 m), not short-dt jitter; a
25 m/s cap hits express routes 5.7x more than local (real highway speeds), at 35 m/s
the two tails are equal (0.10-0.11%, pure error). Trip-change legs 6.05% (dt p90
4,305 s, speed p50 1.3 m/s; the ten fastest legs, 1,860-4,218 m/s, are all
trip-change and nine of ten have a null route). Within a **run** (a contiguous
stretch of one vehicle's Pings with the same trip_id and start_date; a vehicle that
comes back to a trip_id later starts a new run): **pre-departure** legs (before the
first stop_id flip) 5.96%, 30% under 25 m, median 0.40 m/s; **post-final** legs (after
the last flip) 5.71%, 72% under 25 m, median 0.00 m/s - terminal layover shows up on
both ends; runs that never flip 1.33% (a subset of pre-departure); mid-trip 88.3%. But
those shares are **rain-correlated**: at Ida 04Z never-flip runs are 4.4% of storm
legs vs 1.1% of control legs, post-final 10.0% vs 6.7%, pre-departure 8.5% vs 5.5% -
stuck buses do not reach their next stop, so a rule that deletes whole terminal regions
deletes 18.7% of the storm hour vs 12.2% of the control hour; deleting only the
**stationary** legs (< 25 m) in those regions deletes 6.7% vs 7.2% (neutral). Express
runs also carry more terminal legs (pre-departure 9.9% vs 5.5% local; never-flip 3.3%
vs 1.2%). Stationary mid-trip legs are the phenomenon (4.9% of storm legs vs 3.0% of
control at Ida 04Z). Cell: 57.6% of legs start and end in one Cell, and the midpoint
never lands in a third; hour: 4.4% straddle an Hour boundary (assigning by midpoint
instead of end moves 0.35% of legs and no ratio by more than 0.001). Support: p50 23
legs per (Cell, Hour), 24,998 non-empty (Cell, Hour) pairs on a control day (43.7%
of them, holding 87% of legs, clear 30 legs), 552 of 4,113 bbox Cells clear 30 legs
in a busy hour, 162 clear 100; only 1,146 Cells (28% of the bbox) see a leg midpoint
all day (1,115-1,121 see a Ping) - the bus network's footprint - and the 168 Cells
AORC leaves permanently NULL (sea-mask Pixels) carry 0 legs. In the archive 28.4% of
same-trip legs and 18.5% of mid-trip legs keep the same `stop_id` at both ends (no
Passage inside them).

**Chord vs path** (the project's own 30 s capture, 2026-08-15, 325,742 windows of
four 30 s legs): at the median the 120 s chord is 6.7% short of the 30 s polyline
(r p50 1.072; mean shortfall 14.5%), and the shortfall grows as speed falls (r p50
1.164 below 3 m/s, 1.025 at 3-6, 1.016 above 10 m/s). **A chord-speed ratio therefore
overstates a slowdown**: the slower arm loses more distance, measured ratio = true
ratio x (1 - s_storm)/(1 - s_control) < true. Applying the class-median r to Ida 04Z
moves 0.745 to ~0.85 (class means: ~0.88); at 2023-09-29 13Z, whose two arms straddle
the 3 m/s class edge, the same arithmetic reaches ~1.0. That is an upper bound on the
correction, not the correction: below 3 m/s the 30 s polyline is itself inflated by
GPS wander around a stopped bus, and r(v) comes from one Saturday. Sign known,
magnitude between 0 and ~10 ratio points, and it applies to every wet/dry ratio and
regression slope built on chords. In the live feed 13.5% of rows repeat a
`(vehicle_id, ts)` with a moved position (the vehicle clock stalls while OBA projects
the bus forward; `fetched_at - ts` p50 34 s) - a live-era rule, invisible in the
archive. A 120 s window in the live data spans 0 stop_id flips 26.6% of the time,
1 flip 44.6%, 2+ 28.8% (mean 1.09 flips), so about a third of archive-era stop
advances are interpolated (06's `interp_k >= 2`) and the Passage is the second
response variable in the archive era, the Leg the first.

**The signal.** Citywide bus-minute-weighted space-mean chord speed, storm hour /
same hour one week earlier, under the section-2 rules (R2): Ida hours ending
2021-09-02T01Z/02Z/03Z/04Z = 1.023 / 0.933 / **0.768 / 0.729**, still 0.80 at 06Z and
0.89 at 08Z (rain 51.2 mm citywide mean at 02Z, **0 Cells >= 1 mm from 07Z**: the
slowdown lags the rain by 1-2 h, deepens as streets flood, and outlives the rain by
5+ hours; fleet 6-9% smaller at 03Z-04Z); 2023-09-29 hours ending 12Z/13Z/14Z/19Z =
0.931 / **0.905** / 0.896 / 0.900 (rain 10-13 mm/h citywide 12Z-14Z; the month's
largest Cell-hour, 87 mm, is at 19Z with 3,029 Cells >= 1 mm - the storm ran all
afternoon; fleet matched until 16Z, 9-10% smaller after). Earlier rule sets (R0 =
whole pre-departure region dropped, R1 = both terminal regions dropped) give 0.745 /
0.763 at Ida 04Z and 0.907 / 0.894 at 2023 13Z; every variant (dt cap 180/300/600,
speed cap 25/30/35, terminal handling, stationary legs dropped) moves the highlighted
ratios by <= 0.02. Not a geographic or route-composition artefact: matched-Cell ratio
0.753 vs all-Cell 0.745, route-matched 0.772 vs 0.763 (Ida 04Z, R0/R1); vehicle-level
selection within routes is not ruled out. The bus-minute-weighted citywide ratio and
the median-Cell ratio are different estimands (0.777 vs 0.868 at Ida 03Z: the slowdown
concentrates in the busiest Cells). Per Cell, Ida 03Z-04Z pooled: 563 Cells with >=
20 legs on both days, ratio p10/p50/p90 0.50/0.88/1.10, 35% below 0.8. On the same
day pairs the non-storm hours sit at 0.998 (sd 0.015) for 2021 but drift 0.98 -> 1.04
across the day for 2023: one control day is worth about +/- 0.05.

**Rain across the archive years** (AORC Cell-hours, 4,113 Cells x 96 months): wet
(>= 1 mm) share 0.01-8.6% of Cell-hours per month; window W1 2021-08-16..10-15: 238K
wet Cell-hours (4.0%), 73 wet Hours (citywide mean >= 1 mm), 85.8% of Cell-hours dry
by 08's rule, Ida's 2021-09-02T01Z the largest Cell-hour in the whole span (97 mm);
W2 2023-09-01..10-31: 371K (6.2%), 104 wet Hours, 79.3% dry, and 2023-09 is the
wettest month of the 96 (8.6%); 2024-09/10 the driest (0.8% / 0.01%). AORC itself has
two real gaps in the span (all of 2024-06-18 and the hour ending 2024-11-27T20Z are
NaN over the whole bbox), none inside W1/W2. Post-storm hours are formally dry (Ida
08Z: 3,325 of 3,945 non-null Cells dry by 08's rule; from 09Z all) while buses run
0.80-0.90 - a dry baseline built with 08's rule alone eats the recovery. Fixture: Cell
`882a100895fffff`, hour ending 2021-09-02T02:00Z, reads 84.278 mm (08's 84.28); every
T3 control hour (2021-08-26 03Z/04Z, 2023-09-22 13Z) reads 0.000 mm citywide.

**Benchmarks that exist.** MTA `cudb-vcni` "Bus Speeds: Beginning 2015": route x
month x borough x day_type x trip_type x period (Peak / Off-Peak, hours undefined in
the metadata), `average_speed` = miles / hours, every archive month (B41 Sept 2021
off-peak 6.70 mph); MTA `58t6-89vi` "Bus Route Segment Speeds 2023-2024" (`kufs-yh3x`
from 2025): timepoint-pair x month x day-of-week x hour_of_day, road miles / minutes /
trips (B41 S, Sept 2023 Wed 14h: 6.4 mph); TransitCenter `stats/speed/<YYYY-MM>-
speed.tsv.gz` in the same bucket (2014-09..2019-10 + 2022-05): calls-based shape
distance (m) / elapsed (s) per route x dir x stop x weekend x period, imputed calls
only. All three are space-mean speeds on **route-shape** distance; ours is a chord.

**Disk.** The internal disk had 9.9-12 GiB free at two readings on 2026-08-16 (a
moving number; the rule below is what matters); the archiver adds ~0.53 GB/day and
its 10 GB loud stop counts every byte under `data/archive/` (`archiver.bronze_bytes`),
with `data/archive` hardcoded as the root. The 124-file slice needs ~2.5 GB of xz
sources, ~2.1-2.4 GB Bronze VP (measured 13.6 B/Ping, ~155-170M Pings), ~2.6 GB
Silver `events` (09), ~0.7 GB Silver `leg_hours`, Gold small; a Silver Leg table
would add ~3.5 GB. Converting the slice under `data/archive/` puts ~5 GB on the 10 GB
clock on day one and the archiver would write `STOPPED_BUDGET` and stop capturing
about nine days later. The external SSD on 05/09's list is the precondition, not a
choice.

## 1. The slice

**Two contiguous windows, 122 service days (124 day files), no separate control
months.**

| window | service dates | files | why | picks (12's code) | AORC months |
|---|---|---|---|---|---|
| W1 | 2021-08-16 .. 2021-10-15 (61) | 2021-08-16 .. 2021-10-16 (62; D+1 for the last service day) | Ida (2021-09-01/02): the largest AORC hour of the span and the deepest measured slowdown (0.73); Henri 08-22; ordinary rain (73 wet Hours); a second regime year | C1 (to 09-04), D1 (from 09-05) | 2021-08, 09, 10 (+ 24 h lookback into 07-31) |
| W2 | 2023-09-01 .. 2023-10-31 (61) | 2023-09-01 .. 2023-11-01 (62) | 2023-09-29 flood (0.90 for eight hours), Ophelia 09-23..25, the wettest month of the archive (104 wet Hours); MTA hourly segment speeds exist for validation | C3 (to 09-02), D3 (from 09-03) | 2023-09, 10 (+ 08-31) |

- The dry baseline lives inside the windows: 86% (W1) / 79% (W2) of Cell-hours are
  dry by 08's rule, so every wet Cell-hour has its own-week, same-Cell,
  same-hour-of-week comparison. A separate "dry control month" (the reality-check
  proposal) adds nothing the windows lack: the binding constraint is wet Hours, not
  dry ones. It also would not remove the calendar confounds - both windows straddle
  school start (2021-09-13, 2023-09-07), Labor Day, the High Holidays and UN General
  Assembly week (2021-09-21..27, 2023-09-18..22, Midtown East closures) - so those
  are handled as day flags (`school_in_session`, `holiday`, `unga_week` in a 124-row
  `ref/calendar`), and the wet/dry ratio is reported with and without the pre-school
  weeks. Ida falls before school start, the 2023 storm after it.
- Both storms are natural experiments and each is the other's out-of-sample check
  (playbook step 5); 2021 vs 2023 also brackets the ridership recovery, so **the two
  windows are baselined and fitted separately** (a baseline pooled across them merges
  the regimes the design keeps apart) and then compared.
- What the slice can and cannot say: citywide and borough wet-vs-dry effects, the two
  storm composites and the rain-lag structure are supported - but the independent
  unit is the storm, not the Cell-hour: 73 + 104 wet Hours arriving in a few dozen
  wet events, on a rain field whose adjacent Pixels correlate at 0.996-0.998 (08).
  Standard errors cluster by wet event / day; **per-Cell** ratios are a preview with
  wide intervals (Leg speed CV ~0.7, so 30 legs per arm is +/-35% on a Cell ratio - the
  whole measured spread) and are published only with their interval; hotspot claims
  wait for the full 7-year backfill plus 08's coarsened rerun. Say so in the artifact.
- The full backfill is the same loader over 2,278 files (~45 GB xz, ~45 GB Bronze,
  ~56 GB events); a build item after the slice validates, not part of this ticket.
- Not chosen: W2 alone (loses Ida, the fixture and the second regime for 1.2 GB); a
  benchmark month (2022-05 for TransitCenter) - MTA's `cudb-vcni` covers the slice
  months and `58t6-89vi` gives 2023 at hourly grain; 2024-09/10 as a "dry control"
  (the driest months of the span) - kept in mind for the full backfill.
- Prerequisites, in order: (1) the external SSD mounted with `data/archive/` and
  `data/silver/` on it (05's 10 GB loud stop otherwise trips ~9 days into the slice;
  `archiver.ROOT` is hardcoded, so this is a `RAINCHECK_ARCHIVE_ROOT` env var or a
  symlink - a build item, and 07's "the 10 GB budget covers all of data/" is not what
  the code does: only `data/archive/` is counted); (2) `precip_hourly` /
  `precip_cell_hourly src=aorc` for the five months (08's job); (3) picks: the Speed
  path needs none; `events` for the slice needs the four zips x six feeds = 24
  downloads from ticket 13's grant (per 13, C1/D3 are grant-only). Speed lands before
  the grant.

## 2. Leg and Speed rules

**Leg** = the movement between two consecutive Pings of one `vehicle_id`, ordered by
the vehicle clock `ts`. **Speed** = geodesic chord distance / dt on that Leg (a lower
bound on path speed; commercial speed, dwell included). The Cell-hour figure is the
**space-mean speed** `sum(dist_m) / sum(dt_s)`, never a mean of ratios; median Leg
speed rides along at day grain as the robust companion. Rule set name: **R2**.

| rule | value | measured reason |
|---|---|---|
| Ping identity | one Ping per (vehicle_id, ts); when the live feed repeats a ts with a moved position keep the **earliest** `fetched_at` (the fix nearest its clock); no-op in the archive (0 duplicates) | 13.5% stalled repeats live; dropping later copies keeps the full distance on the next advancing Ping |
| Leg key | per `vehicle_id`, consecutive after the identity collapse; keep the start Ping's trip_id, route_id, start_date, stop_id | the vehicle moves regardless of assignment |
| Same trip | keep only `trip_id0 == trip_id1` and non-null | trip-change legs are 6% and hold every absurd tail (layover, deadhead, reassignments) |
| dt | `0 < dt_s <= 300` | 2.5x cadence; drops 2.2% (vehicle dark, storm-neutral); dt <= 0 never occurs in the archive and is the stalled-repeat case live |
| Speed cap | `dist_m / dt_s <= 30 m/s` (67 mph) | above 25 m/s express buses are real (5.7x local); at 30 the local tail (0.13%) is teleports; NYS statutory max 55 mph; storm ratios move <= 0.011 across 25/30/35 |
| Run | a contiguous stretch of one vehicle's Pings with the same (trip_id, start_date), gaps-and-islands: `run_id = sum(case when (trip_id, start_date) changed then 1 else 0 end) over (partition by vehicle_id order by ts)`; never a plain group-by | a vehicle that returns to a trip_id later is a second run; the A5 shares were measured this way |
| Terminal legs | drop a leg only if it is **stationary** (`dist_m < 25`) **and** sits before the run's first stop_id flip, after its last flip, or in a run that never flips; moving legs are kept everywhere; the dropped count is carried per Cell-hour (`n_dropped_terminal`) | the whole-region rules (R0/R1) delete 18.7% of the Ida 04Z storm hour vs 12.2% of its control (stuck buses never reach the next stop: never-flip 4.4% vs 1.1%); R2 deletes 6.7% vs 7.2% - rule-neutral across the contrast - and still removes the layover it is aimed at (72% of post-final and 30% of pre-departure legs are stationary); the level moves 3% (3.23 -> 3.33 m/s on the 2021 control day) |
| Stationary mid-trip legs | **kept** | a bus in traffic or dwelling is the phenomenon (4.9% vs 3.0% at Ida 04Z); dropping them moves the Ida ratios up to 0.013 the wrong way |
| Distance | geodesic WGS84 (`ST_DistanceSpheroid` / `pyproj.Geod`), never haversine (09) | |
| Cell | H3 res 8 of the Leg **midpoint** (mean lat/lon; < 1 km legs) | 57.6% same start/end Cell; the midpoint never invents a third Cell |
| Hour | `hour_end_utc = ceil_hour(t_mid)`, `t_mid = t0 + dt/2` (08's `ceil_hour`; a Leg belongs to the Hour holding its midpoint, as a Passage belongs to the Hour holding its arrival) | 4.4% straddle; 0.35% change Hour vs the end-Ping label the measurements used, ratios move <= 0.001 |
| Route class | `express = upper(route_id) RLIKE '^(X|BM|QM|BXM|SIM)'`, `sbs = route_id LIKE '%+'`, else `local` (pick-free); 06's `trip_type` from the Pick when loaded; a converted day must show all three classes non-empty | 342 route ids on 2023-09-29: `BXM1..BXM18` upper case, 15-20 `+` routes, no `-SBS` anywhere in route_id |
| Yield | ~87-89% of same-trip legs kept | measured on the four days |

**Named limitations** (stated wherever a Speed is shown): the chord is 6.7% (median)
to 14.5% (mean) short of the 30 s polyline at 120 s cadence and shorter still when
slow, so **chord ratios overstate slowdowns** by an unmeasured 0-10 ratio points and
levels sit ~10% under MTA's shape-distance speeds; every headline ratio is shown with
a chord-corrected companion (class-median r applied by speed class) as the optimistic
edge of a band, until a path distance exists. The pick-gated upgrade is along-shape
distance (`ST_LineLocatePoint` on the trip's shape, exactly the snap TransitCenter's
`inferno` used), which fixes both the ratio bias and the T4 level gap; the archive
positions are OBA-projected, so the snap is short. No map-matching before then. The
archive's `timestamp` is the vehicle clock, irregular within the 120 s poll (dt
p10-p90 92-153 s), and its stall behaviour is unobservable in the archive; dwell is
not separable from movement at 120 s (06's limitation, restated). Live era: the same
function on 30 s Pings gives dt ~30 s and a smaller chord shortfall (r p50 1.0004 at
60 s), so archive-era and live-era Speeds are not pooled - 08's src rule already
forbids it - and `dt_s_sum / n_legs` is on every aggregate for that reason.

## 3. Landing: one Bronze, the daily job, two small tables

1. **Archive files land as Bronze VP in the live schema.** A converter (`make nbp
   DATE=`, pyarrow, one xz file per call, ~1 min) writes
   `data/archive/vp/date=<UTC date>/hour=HH/part-nbp-<source date>.parquet` with the
   schema built from `archiver.TYPES` (an all-NULL column must not become a
   null-typed Parquet column - 05's own rule) and 05's census test extended to assert
   converter columns == `decode_vp` keys and types:

   | Bronze VP (05) | archive column | note |
   |---|---|---|
   | vehicle_id | vehicle_id | same `MTA NYCT_8446` / `MTABC_...` format |
   | trip_id, route_id, stop_id | as given | empty -> NULL |
   | direction_id | - | NULL (not in the archive; a Pick fills it later if wanted) |
   | start_date | trip_start_date | ISO `2021-08-31` -> `20210831` (the live feed's YYYYMMDD) |
   | lat, lon, bearing | latitude, longitude, bearing | |
   | ts | timestamp | epoch seconds UTC |
   | occupancy | occupancy_status | NULL when the source day has exactly one distinct value (a placeholder year: every sampled year but 2019 is 100% `EMPTY`; `EMPTY` is a real enum value in the live feed); kept as given otherwise |
   | fetched_at | - | **NULL** - the archive exports no poll clock and `mid` is not a time; partitions come from `ts`; `fetched_at IS NULL` is the archive-era discriminator on the table (live partitions come from `fetched_at`; readers already scan adjacent hours) |
   | dropped | speed, congestion_level, stop_status, vehicle_label/plate, trip_start_time, progress, block_assigned, dist_*, mid, stop_sequence | never populated or constant (section 0) |

   A source file's Pings all fall in its own UTC date, so one converter call writes
   one `date=` partition (24 `hour=` dirs); rerunning it rewrites the same part files
   (idempotent by name). The xz sources stay under `data/archive/nycbuspositions/
   YYYY/MM/` (Bronze fidelity copy: 2.5 GB for the slice; the bucket is a volunteer's
   and can vanish). Both roots count toward 05's Bronze budget - which is why the SSD
   comes first.
2. **Bronze read rule for a service day**: `events DATE=D` reads Bronze
   `date IN (D, D+1)` (service day D starts 04Z/05Z on D and runs to ~08Z on D+1;
   live rows only shift forward, `fetched_at >= ts`). 09's `service_date BETWEEN
   date(t0)-1 AND date(t1)` is the Silver read rule, a different thing.
3. **Silver `events` from the same `events DATE=` job** (07): passages, delay,
   segments, headways, unchanged; archive-era rows have `censor_width_s` ~120,
   `interpolated` on about a third of advances, `pred_*` NULL, `arrival_src` never
   `tu_last`. When no Pick covers the date the job **writes rows with `pick_gap =
   true`**, `pick_id`/`delay_s`/`sched_*` NULL (09's schema; loud is a log line and a
   count in the check, not an abort), so `events` for the slice can be built before
   the 24 zips land and rebuilt after.
4. **Legs are computed by the daily job and stored as Cell-hour rows.**
   `enrich.legs()` (Bronze VP -> legs under section 2, pure function) is called by
   `events DATE=D` on the same D..D+1 read; legs whose start Ping has `start_date = D`
   are aggregated to Silver **`leg_hours`**, partition `service_date=D`, grain (cell,
   hour_end_utc, route_id, route_class): `n_legs INT32, n_vehicles INT16
   (approx_count_distinct), dist_m_sum FLOAT64, dt_s_sum INT64, leg_speed_p50
   FLOAT32, n_dropped_terminal INT32, n_dropped_dark INT32`; ~130K rows / ~6 MB per
   day (0.7 GB slice, ~13 GB full backfill). Per-day sizing is the proven class (1.4M
   Pings; 07 measured 1.93M H3'd in 1.1 s); no month-sized window job, no month
   boundary. `gold MONTH=` rolls `leg_hours` up to Gold **`cell_hour_speed`**,
   partition `month=`, same grain minus `leg_speed_p50` (an absolute Hour receives
   legs from two service days, so sums merge and the median does not; it stays at day
   grain), reading `service_date` in [month_start - 1, month_end] and keeping rows
   whose `hour_end_utc` is in the month before the write (dynamic overwrite replaces
   only that month; 07's neighbouring-partition check extends to this job). Not a
   column set on `cell_hour_route`: its event rows are per `direction_id` from the
   Pick while leg rows are direction-free, and the two would never join. A Silver Leg
   table is fog: the Cell-hour rows are a sufficient statistic for every planned
   analysis, a rules re-tune is a re-run of the daily job (`make events DATE=` over
   the slice), and 3.5 GB is not free on this disk; add `silver/legs (service_date=)`
   the day a leg-grain analysis or a second consumer appears (T5 uses a one-off
   materialisation instead, section 4).
5. **Baseline.** Gold `cell_hourofweek_baseline` (09) is partitioned by **window**
   (`W1`, `W2`, later `Y2018` ...), holds the dry side only - `speed_dry` (space-mean
   over the bin's dry Cell-hours), `n_dry`, `n_legs_dry` - and the dry rule for it is
   08's dry rule **plus a recovery guard**: `mm_1h < 0.1 AND mm_1h_prev < 0.1 AND
   mm_6h < 0.5` (swept like every other cutoff; the post-Ida hours are dry by 08's
   rule from 08Z while buses run 0.80-0.90 through 08Z and 0.94-0.95 into the next
   commute). The wet side is not a baseline column (8.7 weeks per window x 4-6% wet =
   ~0.35 wet observations per Cell x hour-of-week bin): wet Cell-hours are scored as
   anomalies against their bin's `speed_dry` and aggregated per Cell (n_wet ~100-180
   in a busy Cell) at analysis time, in DuckDB, from `cell_hour_speed` x
   `precip_cell_hourly` x the baseline; no further table.
6. **Precip for the slice** is 08's tables for the five months, nothing new.
7. `research/09-storage-schemas.md` gets: the Roots line for `nycbuspositions/`, the
   Bronze VP note (archive rows, `fetched_at` NULL, `ts` partitions, occupancy rule),
   the Bronze read rule (2), `silver/leg_hours`, Gold `cell_hour_speed`, the
   baseline's partition and columns, `ref/calendar`.

## 4. Acceptance tests (one runnable check per slice)

| # | test | pass |
|---|---|---|
| T1 loader | for each converted day: Bronze rows == xz rows; unique (vehicle_id, ts) == rows; 0 rows with ts outside [D-1, D+2) UTC (the ms/s gate - every W1 day is pre-fix, so it runs on real data); lat/lon inside the bbox; the three route classes non-empty; convert twice -> identical rows, no extra files, neighbouring `date=` untouched; one 20-column file (2018-10-10) and one DST-transition file (2021-11-07, a converter fixture for 06's unit test - neither window contains a transition) convert clean | exact; a failure names the file |
| T2 fixture precip | `precip_cell_hourly src=aorc`, Cell `882a100895fffff`, hour ending 2021-09-02T02:00Z | 84.28 mm +/- 0.05 (08's test, reused) |
| T3 the Ida signal | after W1 is loaded: citywide space-mean chord Speed for the Ida hours ending 2021-09-02T03Z and 04Z, each divided by the **median** of the same hour-of-week over the other eight weeks of W1 restricted to dry control hours (each control hour must read < 0.1 mm citywide in `precip_cell_hourly` - a stated precondition, true of 2021-08-26 03Z/04Z); n_legs >= 15,000 in each storm hour | ratio <= 0.85 for both hours (single-control measurement 0.77 / 0.73 under R2, and the non-storm hours of that day pair sit at 0.998 +/- 0.015); the 02Z hour (0.93) and every 2023-09-29 hour (0.90 for 12Z-19Z, whose control day drifts 0.98 -> 1.04) are **reported, not gated**; this is a reproduction test of the loader and rules, not the headline (which carries the chord band) |
| T4 rules benchmark | for W2: route x day-of-week x hour_of_day space-mean chord Speed vs `58t6-89vi` (segments recombined trip-weighted: sum(road_distance x trips) / sum(travel_time x trips)); for both windows: route x month x day_type vs `cudb-vcni` recombined as sum(miles)/sum(hours) over periods and boroughs (MTA's Peak/Off-Peak hours are undefined in the metadata; whole-month grain cancels them) | **report-only on the first run** (06's calibration rule): ratio distribution and Spearman rank agreement across routes, with the known biases named (chord -7..-15%, terminal handling +3%, MTA time may include layover); a gate, if one is ever set, is a band around [0.75, 1.15] and rank agreement, decided after the first run |
| T5 Product 3 | one-off evidence script (08's pattern) over the two storm days: legs materialised to `data/.staging/`, `RS_Values` at the Leg midpoint (and at the stop once `events` exists) vs the Cell mean, rain-vs-Speed slope both ways | reported, not gated; the difference goes into 08's spec |
| T6 support & footprint | Cells with >= 1 leg midpoint per day ~1,146 (Ping footprint 1,115-1,121); 0 legs in AORC-NULL Cells; `n_dropped_terminal` share storm vs control within 0.01 in the T3 hours | sanity, prints |
| T7 idempotence | `events DATE=` twice (07's check 2) now also compares `leg_hours`; `gold MONTH=` leaves the neighbouring month untouched | exact |

## 5. What the slice produces (analysis plan, downstream)

Playbook Product 2 as the baseline: `speed_dry[cell, hour_of_week]` with `n_dry`,
per window; wet Cell-hour anomalies aggregated per Cell (mean anomaly, ratio, n_wet,
interval), gated on interval width not bare n; the two storm composites with the
response window taken from the rain per Cell (08's (t0, t1) over `mm_1h`/`mm_6h`; Ida
at least 02Z-08Z, 2023-09-29 at least 10Z-21Z, not the citywide-mean eyeball) beside
the storm total; the rain-lag table (Speed ratio by hours since the wet Hour: Ida
0.93 -> 0.77 -> 0.73 -> 0.80 -> 0.89 -> 0.94 over 02Z-12Z) as the reason 08's
`mm_1h_prev` / `mm_3h` / `mm_6h` matter; per-Cell regression as a preview with
`school_in_session` / `holiday` / `unga_week` flags and errors clustered by wet event;
every per-Cell claim rerun on ~4 km blocks (08); every ratio shown as bus-minute-
weighted citywide **and** median Cell, with the chord-corrected companion. MTA-
denominator validation (06) once `events` exists.

## 6. Handed on / comments to leave

- CONTEXT.md: **Leg** (the movement between two consecutive Pings of one vehicle,
  the archive-era unit of speed; a Leg belongs to the Cell of its midpoint and the
  Hour holding its midpoint; trip changes and stationary terminal legs are excluded)
  and **Speed** (space-mean chord speed of the Legs in a Cell-hour, sum of distance
  over sum of time; a lower bound on path speed, dwell included, and a ratio of Speeds
  overstates a slowdown by an unmeasured 0-10 points).
- 05: the archive's producer and its two clocks; sources root; the SSD precondition
  now has a date pressure (~5 GB of the 10 GB budget on day one of conversion);
  `RAINCHECK_ARCHIVE_ROOT`.
- 06: at 120 s cadence 18.5% of mid-trip Legs and 28.4% of same-trip Legs carry no
  Passage and about a third of advances are interpolated; the archive-era response for
  rain is the Leg, `segment_excess_s` second; `censor_width_s` ~120 s; the DST fixture
  file 2021-11-07.
- 07: `enrich.legs()` in `events DATE=`, `leg_hours` -> `cell_hour_speed` in `gold
  MONTH=` with the month filter and the neighbour check; the converter as `make nbp
  DATE=`; the pick-gap write rule; the budget covers `data/archive/` only.
- 08: the recovery guard on the dry rule for the Speed baseline (`mm_6h < 0.5`);
  the rain-lag finding; composite windows from `mm_1h`/`mm_6h` per Cell; Product 3
  done on Legs first; the AORC-NULL Cells carry no buses; the two AORC gap hours in
  2024; `precip_cell_hourly` months for the slice.
- 09: schema edits listed in section 3.7; the map/vault date correction (2024-11-04).
- 12/13: the slice's four picks (C1, D1, C3, D3 x six feeds = 24 downloads).
- 14: unblocked by this ticket; the serving surface gets the two composites and the
  baseline map first, each with the estimand named.
- Fog: `silver/legs` if a leg-grain analysis appears; along-shape distance once picks
  are loaded (the chord's replacement; also fixes the T4 level); r(v) measured on
  weekday live captures with a jitter guard (polyline > 100 m) so the chord band can
  narrow; the full 2,278-file backfill's runtime.
