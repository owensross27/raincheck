# raincheck pipeline: build spec

Status: ready-for-agent
Source: wayfinder map `.scratch/pipeline/map.md` (15 tickets, 14 resolved; ticket 13 is a
HITL task whose outcome toggles one build item, see Further Notes). Written 2026-08-17.
Vocabulary is CONTEXT.md's (Poll, Snapshot, Ping, Stop row, Cell, Zone, Passage,
Prediction, Leg, Speed, Delay, Segment excess, Headway, Family, Service date, Pick,
Pixel, Hour, Precip source, Wet/Dry hour, Trailing window). ADR-0001 (the arrival is
the VP Passage) and ADR-0002 (MRMS hour-ending by measurement, no regrid) are binding.

Where a ticket's original Answer was later corrected by a comment, this spec carries
the correction; a table of the load-bearing corrections is in Further Notes so an
implementer who opens a ticket for detail is not misled by its first text.

## Problem Statement

Ross wants to answer, with public data and a defensible method, "does rain slow NYC
buses, and where" - and to show the answer and the machinery in a Solutions-Engineer
showcase: one insight (a map of where and how much rain costs bus speed, with Ida
2021-09-01/02 and the 2023-09-29 flood as case studies, validated against a known
storm) and one engineering view (the same enrichment running live on the MTA feed
nobody else archives, with checkpointed recovery). Today the rails exist (a LaunchAgent
archiver captures bus and subway GTFS-RT and the static zips into Bronze; a Kafka
round trip is proven; AORC precipitation was read from Zarr and reproduced the Ida
peak) but no Spark/Sedona code, no Silver/Gold, no backfill loader, no precip tables,
no page. Every design decision needed to build those has been made and measured on the
wayfinder map; nothing is left to decide before building.

## Solution

A local, laptop-scale pipeline with three callers of one enrichment module:

- **Batch (the insight).** The 2017-2024 `nycbuspositions` archive is converted into
  Bronze VP in the live archiver's schema; a daily job derives Silver `events`
  (Passages, Delay, Segment excess, Headway) and Silver `leg_hours` (Legs aggregated to
  Cell-hours under rule set R2) from Bronze; NOAA AORC (history) and MRMS (live era)
  land as Pixel-grain `precip_hourly` and Cell-grain `precip_cell_hourly`; Gold rolls
  Cell-hour Speed and route metrics up per month plus a per-window dry hour-of-week
  baseline. First slice: two windows (2021-08-16..10-15 and 2023-09-01..10-31, 124
  archive files) that hold both storms and their own dry baselines; the acceptance
  test reproduces the Ida slowdown from the loader and rules alone.
- **Stream (the engineering view).** The archiver publishes decoded VP/TU rows to
  Kafka as a side effect of its polls; one Spark Structured Streaming app reads both
  topics, applies the stateless subset of the same enrichment (Cell, Zone, latest live
  precip Hour) and appends micro-batches to thin live tables with a 48 h horizon and
  checkpointed recovery; a small periodic job maintains the live precip table from
  MRMS RadarOnly.
- **Serving (both artifacts).** One static MapLibre page, two panels: the insight
  (footprint hexes coloured by wet/dry Speed ratio per window and by storm hour, with
  intervals, gates and estimands) and the live fleet (vehicles now, rain Cells now,
  staleness made visible), reading GeoJSON/JSON that a DuckDB export writes; served by
  the stdlib HTTP server. No hosting, no framework, no tiles.

Everything runs from the repo venv on the brew JDK 17 with Kafka as the only container,
writes plain Parquet / GeoParquet 1.1 under one data root (external SSD), and is read
back by DuckDB, which is also the test oracle for every layout.

## User Stories

Analyst = Ross doing the analysis; presenter/viewer = Ross showing the page or someone
watching it; operator = Ross running the pipeline on this Mac; consumer = anyone
querying the tables with DuckDB; implementer = the agent building this.

1. As an analyst, I want the two storm windows of the archive converted into Bronze VP in the same schema as the live feed, so that history and live rows are one table with one read rule.
2. As an analyst, I want a per-Cell-hour space-mean chord Speed derived from consecutive Pings under a fixed, published rule set (R2), so that the storm/control ratio is reproducible and rule-neutral across the storm contrast.
3. As an analyst, I want the Ida hours reproduced by the loader and rules alone (ratio <= 0.85 at the 03Z and 04Z hours against the window's dry same-hour-of-week median), so that the pipeline is validated against a known storm before any modelling.
4. As an analyst, I want AORC hourly precipitation for the whole archive span at Pixel grain and as an area-weighted Cell mean, so that every Cell-hour has rain features (mm_1h, previous hour, 3 h, 6 h, 24 h, temperature) joinable on (src, cell, hour_end_utc).
5. As an analyst, I want a dry hour-of-week Speed baseline per window with a recovery guard, so that post-storm hours that are formally dry but still slow do not pollute the denominator.
6. As an analyst, I want wet Cell-hour anomalies scored against that baseline and aggregated per Cell with a 95% interval clustered by wet event, so that per-Cell claims carry honest uncertainty and are published only when the interval is narrow enough.
7. As an analyst, I want the two storm composites hour by hour (Ida 02Z-08Z, 2023-09-29 10Z-21Z) with per-Cell rain, hours since the last wet Hour, and the same interval gate, so that the rain-lag structure is visible and the map does not overclaim.
8. As an analyst, I want every headline ratio as bus-minute-weighted citywide and median-Cell, each with its chord-corrected companion as a numeric range, so that a chord ratio's known optimism (0-10 points) is shown, never hidden.
9. As an analyst, I want the wet/dry ratio reported with and without the pre-school weeks (day flags for school session, holidays, UNGA week), so that calendar confounds are visible.
10. As an analyst, I want Silver `events` (Passages with Delay, Segment excess, Headway, Family, prediction churn) built from Bronze once a service day is closed, so that schedule-based metrics exist for the live era and, once Picks are loaded, for the archive.
11. As an analyst, I want Gold `cell_hour_route` (late/early shares, mean Segment excess, excess wait by the renewal formula, bunching, wait_ok share, coverage) per Cell-hour-route once Picks are loaded, so that schedule- and headway-based effects of rain are measurable beside Speed.
12. As an analyst, I want the events job to write rows with `pick_gap` set when no Pick covers the date instead of aborting, so that the slice can be built before the historic zips arrive and rebuilt after.
13. As an analyst, I want dated static GTFS Picks resolved by the pick code embedded in that day's own VP trip_ids (v2 rule), so that the Ida day joins the July 2021 bundle and not the early-published September one.
14. As an analyst, I want schedule tables (stops, trips, trip_stops, service_days, shapes) loaded per Pick with cumulative geodesic shape distance, so that scheduled arrival, scheduled headway and multi-stop interpolation are computable.
15. As an analyst, I want MTA's own published speed and wait-assessment datasets compared against mine report-only on the first run, so that the known biases (chord, terminal handling, layover) are named before any gate is set.
16. As an analyst, I want a one-off script that reads the AORC raster at the Leg midpoint versus the Cell mean on the two storm days, so that the "Product 3" question is answered with numbers and then retired.
17. As an analyst, I want every table readable by DuckDB from its root with `src` pinned and one row per key, so that ad-hoc analysis needs no Spark session.
18. As an analyst, I want the analysis-time SQL (anomalies, composites, baselines) to be one text that both the export job and a notebook can run, so that the page's numbers and my exploration cannot diverge.
19. As a presenter, I want one static page with the insight map and the live view as two panels, so that the story is told once, in one place, from local files.
20. As a presenter, I want the map's hexes to be real H3 res-8 Cells with taxi-zone names in the tooltip and taxi zones as the ground layer, so that a viewer can place a Cell without a basemap.
21. As a presenter, I want the page to name the estimand next to every number, the precip source in every legend, and the sentence that per-Cell colour is a preview and hotspot claims wait for the 7-year backfill, so that nothing on screen can be read as more than it is.
22. As a presenter, I want the storm-hour composite to grey out Cells whose interval is too wide and to print how many Cells are hidden, so that a thinning map during the storm is visible as such (the hidden set is storm-correlated).
23. As a presenter, I want the 2023-09-29 headline to state that its chord band reaches ~1.0, so that the second storm's slowdown is not presented as separable from chord bias.
24. As a viewer, I want the live panel to show how many vehicles are on the map in the last ten minutes, how many are in Cells with at least 1 mm in the latest complete Hour, how many carry a next-stop Prediction, and how old the data is, so that I see the stream is alive and what it claims.
25. As a viewer, I want the live layer to turn STALE (dimmed, titled) when the pipeline stops writing, and to drain to zero within ten minutes, so that a dead pipeline never looks live.
26. As a viewer, I want the live panel to show the stream's own progress (last micro-batch id, rows, age) beside the exporter's clock, so that I can tell a dead stream from a dead exporter and see the Kafka -> Spark -> Parquet rail.
27. As a viewer, I want "MTA-reported trip delay > 5 min" shown as an explicit unavailable state until the decoder carries the field, and never labelled "late", so that the agency's number is not confused with the project's Delay.
28. As a viewer, I want the live rain flag labelled as MRMS RadarOnly, uncalibrated, hour-ending, with its valid time and age, so that it is not read as the analysis's AORC Wet hour.
29. As an operator, I want one Spark session factory and one enrichment module with pure DataFrame functions called by batch jobs, the streaming job and the tests, so that there is never a second implementation of Cell, Zone or precip attachment.
30. As an operator, I want every batch job idempotent by dynamic partition overwrite and runnable in any order (months and days independent), so that reruns replace exactly what they wrote and a crash cannot poison a partition.
31. As an operator, I want a `daily` target that builds every missing closed service day and the current MRMS month, so that a launchd calendar agent that coalesces missed runs still catches up.
32. As an operator, I want the archiver to publish decoded rows to Kafka as a side effect of its polls (single poller), so that VP is not polled twice every 30 s by two processes.
33. As an operator, I want the streaming job to run on demand in the foreground, resume from its checkpoint after a sleep gap at bounded pace, and be discardable with a FRESH flag when the gap exceeds the live horizon, so that "checkpointed recovery" is a thing I can demonstrate.
34. As an operator, I want the live precip table maintained by a small 300 s LaunchAgent job (not inside the archiver loop and not inside the stream), so that a GRIB2 decode never stalls capture.
35. As an operator, I want the archive converter, Bronze, Silver and Gold to live under a data root on the external SSD selected by an environment variable, so that the archiver's 10 GB loud stop does not trip nine days into the slice.
36. As an operator, I want a vendored MapLibre and a stdlib server behind two Makefile targets, so that a demo does not depend on a CDN or a framework.
37. As an operator, I want the live export to be a foreground loop with atomic file swaps and an error field, so that a failed tick looks stale on the page rather than absent, and Ctrl-C stops it.
38. As an operator, I want a Bronze fallback for the live export that is labelled on the page, so that a demo with the stream down is still honest.
39. As a consumer, I want GeoParquet 1.1 only on geometry tables (cells, zones, stops, shapes) with SRID 4326 and plain Parquet everywhere else, so that both Sedona and DuckDB read every table.
40. As a consumer, I want timestamps in UTC as TIMESTAMP_MICROS, `service_date` as DATE, `cell` as INT64, ids as strings, and Hive partition keys as strings, so that Spark and DuckDB agree on every column.
41. As a consumer, I want precip Cell-hours NULL when their non-null Pixel weight does not sum to one, and trailing sums NULL when any hour in the frame is missing, so that a partial Pixel set can never masquerade as a measured value.
42. As a consumer, I want disjoint precip lags derived at read time by subtraction rather than stored nested sums regressed on directly, so that the models are not fed collinear features.
43. As an implementer, I want the Kafka JSON schema per topic derived from the decoder's row shapes and asserted equal to them, so that the wire schema cannot drift from Bronze.
44. As an implementer, I want the census-complete TU decoder (feed header timestamp, trip-level delay, trip-level timestamp, direction) landed with a census test, so that the TU live table and the live "MTA-reported trip delay" state can be built.
45. As an implementer, I want the two Kafka topics created with six partitions and zstd at creation, so that the irreversible knob is set once.
46. As an implementer, I want the DuckDB `h3` extension as a test oracle for `ref/cells` geometry, so that Sedona's polygons are checked without becoming a second producer.
47. As an implementer, I want the tests to run against a temp data root with small frozen fixtures and DuckDB read-back, skipping Spark cases when no JVM is present, so that the suite is fast and honest on any machine.
48. As an implementer, I want the full 7-year backfill (2,278 files) sequenced after the slice validates, so that the loader is proven before ~45 GB is converted.
49. As an implementer, I want the build order and preconditions (SSD, grant, Docker VM memory) stated, so that I do not start a step whose input does not exist yet.

## Implementation Decisions

### A. Runtime, repo layout, environment (tickets 07, 03, 01)

- Spark 3.5.3 + Sedona 1.9.1 run in-process from the repo venv on the brew `openjdk@17`
  (Java 17 measured clean for every ST_/RS_ path, GeoParquet writer and Kafka source;
  fallback is `openjdk@11` and a `JAVA_HOME` flip, nothing else). Dependencies added:
  `pyspark==3.5.3` (exact pin), `apache-sedona==1.9.1`, `setuptools` (pyspark's pandas
  bridge imports distutils on Python 3.12), `shapely`, `pyproj`, `duckdb`, `pytz`
  (no Python h3 package: the only H3 oracle is DuckDB's community `h3` extension,
  installed for tests). Maven coordinates on `spark.jars.packages`: Sedona spark-shaded 3.5 / 2.12
  1.9.1, geotools-wrapper 1.9.1-33.5 (not 33.1), spark-sql-kafka-0-10 2.12 3.5.3. A
  `warm` target warms the Ivy cache once (~240 MB).
- Environment: `JAVA_HOME` and `TZ=UTC` come from the Makefile / `.env`, never `brew
  link` (the JVM default TZ is otherwise America/New_York and `collect()` returns
  driver-local naive datetimes). `RAINCHECK_ARCHIVE_ROOT` selects the data root (default
  the repo's `data/`; the external SSD in practice); the archiver's hardcoded root
  becomes this variable. `RAINCHECK_BRONZE_GB` (default 10) is the archiver's loud-stop
  budget: an absolute count of every byte under the archive root as coded (live
  capture, static zips, the decoded precip copies, the xz sources and the converted
  `part-nbp-*` files all count; Silver and live tables sit on the same SSD by
  convention and are not counted). **Moving the root to the SSD does not shrink the
  count**, so step 1 of the sequencing sets `RAINCHECK_BRONZE_GB` explicitly to a
  number sized to the drive (the slice adds ~5 GB, the full backfill ~90 GB, live
  capture ~0.5 GB/day; a value of the SSD's capacity minus 20% headroom, Ross's number)
  before any conversion; the counting rule itself is unchanged. `TRANSITLAND_API_KEY`
  lives in the gitignored `.env`.
- Modules (Python module names, not paths): `raincheck.spark` (the `session()`
  factory), `raincheck.enrich` (pure DataFrame functions), `raincheck.jobs` (thin
  batch entrypoints), `raincheck.stream`, `raincheck.precip_live`, `raincheck.nbp`
  (the archive converter), `raincheck.picks` (resolver + puller), `raincheck.export`,
  `raincheck.live_export`; the archiver, feeds and producer modules exist. Canonical
  detail for this section: research assets 07 (execution model) and 09 (storage
  schemas, exact column/type lists).
- One `SparkSession` factory, the only place these are written: the three coordinates;
  Kryo + `SedonaKryoRegistrator`; `spark.sql.session.timeZone=UTC`;
  `spark.sql.parquet.outputTimestampType=TIMESTAMP_MICROS`;
  `spark.sql.sources.partitionOverwriteMode=dynamic`; driver `-Duser.timezone=UTC`;
  `local[6]`; driver memory 3 g; shuffle partitions 16; UI off (flag to enable). Batch
  jobs, the streaming job and pytest all call it.
- Kafka stays the only container (compose as today; optional: shrink Docker Desktop's
  VM to 4 GB, Ross's setting). No Sedona image locally; quakestream's slim image is
  the promotion path (fog).
- Data roots (all under the data root): `archive/` (Bronze: `vp|tu|alerts|subway_*`
  as `date=/hour=/part-MM.parquet` UTC; `static/<feed>/<date>.zip`; `precip/aorc/`
  Zarr NYC slice; `precip/mrms/date=/hour=HH.parquet` decoded Pass2 footprint;
  `nycbuspositions/YYYY/MM/*.csv.xz` sources), `ref/`, `silver/`, `gold/`, `live/`,
  `checkpoints/`, `.staging/` (outside every dataset root). Readers open dataset roots
  (`**/*.parquet`), never single parts; partition keys are strings.
- Makefile targets: `warm`, `ref`, `schedule PICK=`, `nbp DATE=`, `events DATE=`,
  `precip-hourly SRC= MONTH=`, `precip-cell SRC= MONTH=`, `gold MONTH=`, `baseline
  WINDOW=`, `daily`, `stream [FRESH=1]`, `precip-live` (one tick), `export`,
  `live-export [SOURCE=bronze]`, `vendor`, `web`, `gates` (the slice-scale acceptance
  checks, Testing Decisions). `produce` is retired by the single-poller decision (C
  below).

### B. Reference layer and CRS (tickets 09, 04, 08, 14)

- `ref/grids`: one row per precip grid; `aorc` (origin -130.0/20.0, step 0.008333
  float32-truncated, 8401 x 4201, centre registration, coordinates from the stored
  arrays never `arange`, coord sha256 of the arrays) and `mrms` (origin
  -129.995/20.005, step 0.01, 7000 x 3500, centre; source rows north-to-south so ingest
  stores `j = 3499 - row` and converts lon from 0-360; coord sha256 of the GRIB grid
  tuple). `grid_id` equals `precip_hourly.src` by invariant.
- `ref/cells`: H3 res 8 over bbox -74.30..-73.65 x 40.45..40.95, 4,113 rows, GeoParquet
  polygon + centroid; built with Sedona `ST_H3CellIDs` / `ST_H3ToGeom`; the serving-time
  geometry for every cell-keyed table (never recomputed in a browser).
- `ref/zones`: 263 TLC taxi zones, EPSG:2263 -> 4326 once at ingest, gated by the Times
  Square axis test ((988267.1, 215436.9) ftUS -> (-73.9855, 40.7580) within 1e-4 and
  not swapped); `zone_id`, `borough`, `zone_name`. `ref/cell_zone`: Cell -> zone by
  centroid point-in-polygon (Zone is a presentation overlay, never a Silver key).
- `ref/cell_pixel`: area share of each Pixel inside each Cell, per `grid_id`, computed in
  EPSG:32618 over the bbox padded by one Pixel; sum(weight) = 1 +/- 1e-9 per (grid,
  cell) (AORC: ~19.5K rows, 4.7 Pixels per Cell, largest share p50 0.53 - nearest-Pixel
  lookup is refuted). Python builder (shapely + pyproj) stays; a Sedona port is optional.
- `ref/picks`: `pick_id` = sha1 of the zip (Transitland's key), feed, published,
  feed_version, calendar span, source, path. `ref/calendar`: one row per service day
  with `school_in_session`, `holiday`, `unga_week` (122 rows for the slice - one per
  service day; 124 is the file count, not the day count; extended with the backfill).
- CRS/time conventions: EPSG:4326 lon/lat stored everywhere; 2263 layers reprojected
  once; geodesic distances only where a speed or segment is fed (`ST_DistanceSpheroid`
  / pyproj Geod; haversine banned there); areas/buffers in 32618; TS UTC everywhere;
  `service_date` DATE; precip hour-ending; local time on read only; `cell` INT64 (hex
  string at any JSON boundary); `*_ts` TS; `*_s` INT32; booleans not ints; snake_case
  glossary names. Iceberg not now.

### C. Capture and Kafka (tickets 04, 05, 15) - built; three items remain

- Built and running: the archiver LaunchAgent (`caffeinate -s`, RunAtLoad, KeepAlive on
  crash only) polls bus VP 30 s / TU 120 s / alerts 300 s, the eight subway feeds 60 s
  (TU + VP with the NYCT extension) and subway alerts 300 s, dedupes on the feed header
  timestamp, flushes 10-min sorted parts to Bronze, fetches the seven static zips daily
  by conditional GET, and stops loudly at the byte budget with a marker file (exit 0).
- Remaining: (1) **census-complete TU decoder** - capture the feed header timestamp on
  VP and TU rows, and on TU the trip-level `trip_update.delay`, `trip_update.timestamp`
  and `trip.direction_id` (today dropped), guarded by the census test extended to assert
  the Kafka `StructType`s equal the decoder key sets; the trip-level delay is captured as
  the feed's own number, never as the project's Delay. (2) **Single-poller topology**:
  the archiver publishes each decoded VP/TU row set to `raincheck.bus.vp` (key
  vehicle_id) / `raincheck.bus.tu` (key trip_id) as a side effect of the poll it already
  makes; the standalone producer is retired. Kafka stays a byproduct of capture, Bronze
  the record. (3) **Topic creation** with six partitions and zstd at creation, delete
  retention 48 h, no compaction; the two topics running today have one partition each
  and are recreated. Subway topics wait for a consumer (fog).
- Bronze is never auto-deleted; the SSD root plus an explicitly sized
  `RAINCHECK_BRONZE_GB` (A) is the fix for the budget - the count is absolute and the
  backfill counts.

### D. Static schedule Picks (tickets 11, 12, 13, 06)

- Source: Transitland v2 (the only holder of dated MTA bus GTFS across the window; six
  onestop ids: bronx, brooklyn, manhattan, queens, staten_island, busco). Listing and
  resolution use the free key; historic bytes need the Hobbyist/Academic grant (HITL,
  submitted; ticket 13). Coverage holes exist (2019 for all six feeds, a few days in
  2018/2020/2021) and produce `pick_gap` rows regardless of the grant.
- **Resolver v2** (the v1 fetched_at/calendar rule is wrong and is not built): the pick
  code embedded in that service date's own VP trip_ids selects the zip. Depot trips
  `<depot>_<pick>-<service>[-<modifier>...]-<start>_<route>_<run>` (pick = letter
  A/B/C/D for the Jan/Apr/Jul/Sep MTA bundle + year digit; the service segment carries
  optional modifiers such as `-SDon`, `-BM`; parsers split on the six-digit start token,
  never a fixed token count); MTA Bus Company trips carry the code in the `-..P<code>-`
  form. Among in-window versions whose trips carry that code, take the greatest
  fetched_at <= D+1 (mid-pick revisions supersede). Self-check: an exact trip_id join
  matches ~98% against the right zip and ~0% against the wrong one; the resolver logs
  the match rate per resolved Pick.
- The bulk puller downloads a resolved version by sha1, asserts the bytes hash to
  Transitland's sha1, lands it as Bronze `static/<feed>/<fetched_at date>.zip`, and
  registers the Pick. The slice needs 24 downloads (C1, D1, C3, D3 x six feeds); the
  full window would need 423 (under the 500 grant). The one-zip proof script exists
  and is the reference for the download/verify path.
- **Live-era Picks need no grant**: the archiver already lands the seven current zips
  daily under Bronze `static/<feed>/<date>.zip`; `ref` registers each captured zip as a
  Pick (sha1, feed, Last-Modified as published, source `mta`) and `schedule PICK=` loads
  the in-effect Pick per feed, so live-era `events` carry Delay and Headway from step 5
  and `pick_gap` rows are an archive-era condition only. (Transitland's
  `download_latest_feed_version` is a grant-free alternative source of the same bytes.)
  Canonical detail: research assets 11, 12, 13 (resolver v2, grammar, sources sweep).
- `schedule PICK=` loads per-Pick tables partitioned by `pick_id`: `stops` (with Cell
  and GeoParquet point), `trips` (with `trip_type` local/sbs/express), `trip_stops`
  (arrival/departure seconds and cumulative geodesic `shape_dist_m` computed at
  ingest), `service_days` (calendar x calendar_dates flattened), `shapes` (GeoParquet
  linestring, length). Loaded only for Picks a slice needs. No cross-Pick dedupe.
- If the grant is refused: backfill without schedule Delay (Speed and Headway carry
  the headline; `delay_s` / `segment_excess_s` become live-era-only) rather than an
  Enterprise quote unless trivial.

### E. Backfill loader (ticket 10)

- Source `s3.amazonaws.com/nycbuspositions/YYYY/MM/YYYY-MM-DD-bus-positions.csv.xz`
  (UTC-day files, 2017-07-14..2024-11-04, ~20 MB each; 20 columns through 2019-09, 22
  from 2020-11; `timestamp` is the vehicle clock; zero duplicate (vehicle_id, ts)).
  Slice = W1 files 2021-08-16..2021-10-16 and W2 2023-09-01..2023-11-01 (124 files;
  service days 2021-08-16..10-15 and 2023-09-01..10-31), no separate control months;
  the xz sources are kept under the archive root (a volunteer's bucket can vanish).
- `nbp DATE=` (pyarrow, one xz file per call, ~1 min) writes Bronze VP
  `vp/date=<UTC date>/hour=HH/part-nbp-<date>.parquet` with the schema built from the
  archiver's explicit type map (an all-NULL column never becomes a null-typed Parquet
  column), idempotent by part name. Column mapping: vehicle_id, trip_id/route_id/
  stop_id as given (empty -> NULL), direction_id NULL, start_date from
  `trip_start_date` reformatted to YYYYMMDD, lat/lon/bearing, `ts` from `timestamp`
  (epoch s), occupancy NULL when the source day has exactly one distinct value (a
  placeholder year) else as given, **`fetched_at` NULL** (no poll clock in the archive;
  `fetched_at IS NULL` is the archive-era discriminator; partitions come from `ts`);
  speed, congestion, stop_status, labels, progress, dist_*, mid, stop_sequence dropped.
  Gate: rows with `ts` outside [D-1, D+2) UTC fail the file (the ms/s autodetect era).
- Bronze read rule for a service day: `events DATE=D` reads Bronze `date IN (D, D+1)`
  (a service day starts 04Z/05Z on D and ends ~08Z on D+1; live rows only shift
  forward). Silver's read rule is different: a UTC window scans `service_date BETWEEN
  date(t0)-1 AND date(t1)`.
- The full 2,278-file backfill is the same loader after the slice validates. Canonical
  detail: research asset 10 (slice, rules, landing, tests) and its evidence file.

### F. Silver events: Passage, Delay, Segment excess, Headway (tickets 06, 09, 10)

- Grain: one row per Passage, key (start_date, trip_id, stop_sequence, vehicle_id) -
  vehicle_id is part of the key (16.9% of trip_ids are served by more than one vehicle).
  Partition `service_date=` (the feed's start_date), plain Parquet zstd, sorted (cell,
  arrival_ts), one file per partition, batch-rebuilt from Bronze when the service day
  is closed (D+1 06:00 America/New_York), never appended.
- Passage construction per (vehicle_id, trip_id, start_date): Pings sorted by time
  (identity (vehicle_id, ts, stop_id, lat, lon); when the live feed republishes a moved
  vehicle under a frozen ts, `fetched_at` is the time axis); keep the monotone envelope
  of static `stop_sequence` (backward flaps absorbed); every forward advance is a
  Passage of the previous envelope stop; `pass_lo_ts` = last Ping before the flip,
  `pass_hi_ts` = first after, `arrival_ts` = midpoint, `censor_width_s` = full gap
  (~30 s live, ~120 s archive); multi-stop advances interpolate intermediate arrivals
  proportional to cumulative shape distance (`interpolated`, `interp_k`; SQL first,
  pandas UDF only if SQL cannot express it); `is_first` (pull-out, not a scheduled
  arrival) and `is_last` (the final stop never yields a VP Passage) flagged;
  `arrival_src` in {vp_passage, tu_last, interpolated}; TU is the Prediction stream -
  `pred_last_ts` (fallback arrival only, tagged), `pred_first_horizon_s`,
  `pred_n_changes`, `pred_range_s`, `pred_err_10min_s` (NULL pre-2024-09 and
  throughout the archive).
- Delay: `sched_ts` = local noon of start_date in America/New_York minus 12 h plus the
  Pick's `arrival_s` (DST-safe noon anchor; unit test on 2024-03-10 / 2024-11-03 with
  the 2021-11-07 archive file as fixture); `delay_s = arrival_ts - sched_ts`, unclipped
  in Silver; late > 300 s / early < -60 s applied at Gold only. `pick_id` per row; no
  static match -> row kept with `sched_ts` NULL, counted in coverage; CANCELED trips
  filtered, ADDED/DUPLICATED flagged; `schedule_relationship` verbatim.
- Segments and headways: `segment_s`, `sched_segment_s`, `segment_excess_s` (the
  local rain response variable) between consecutive Passages of the same
  (vehicle_id, trip_id); `headway_obs_s` = gap to the previous different-vehicle
  Passage at the same route/direction/stop, `headway_sched_s` from the Pick, `wait_ok`
  = obs <= sched + 180 s, `bunched` = obs < 0.5 x sched; `family` = headway when the
  route-direction-hour's scheduled headway <= 600 s, else schedule (selects the Gold
  headline only; every event carries both). Denormalized stop lon/lat and Cell of the
  stop; `n_vehicles_on_trip`. A one-file view exposes 06's names (`pass_lo_ts`,
  `pass_hi_ts`, `sched_ts`, `pred_last_ts`, `censor_halfwidth_s`) over the physical
  columns (an `events_view` SQL text). Canonical detail: research asset 06 evidence and
  ADR-0001; exact columns in asset 09.
- Archive era: at 120 s cadence about a third of stop advances are interpolated and
  18.5% of mid-trip Legs carry no Passage, so the archive-era rain response is the Leg's
  Speed first (G) and `segment_excess_s` second, Pick-gated; `events DATE=` writes
  `pick_gap = true` rows (`pick_id`, `delay_s`, `sched_*` NULL) when no Pick covers the
  date - a log line and a count, not an abort.

### G. Legs and Speed (ticket 10; glossary Leg, Speed)

- `enrich.legs()` is a pure function called by `events DATE=D` on the same D..D+1 Bronze
  read; Legs whose start Ping has `start_date = D` aggregate to Silver `leg_hours`
  (partition `service_date=`, grain (cell, hour_end_utc, route_id, route_class):
  n_legs, n_vehicles (approx distinct), dist_m_sum, dt_s_sum, leg_speed_p50 (day grain
  only, not mergeable), n_dropped_terminal, n_dropped_dark; ~130K rows / 6 MB per
  day). Per-Leg rows are not stored (fog).
- Rule set **R2**: one Ping per (vehicle_id, ts) - on a live-feed repeated ts with a
  moved position keep the earliest `fetched_at`; Legs are consecutive Pings per
  vehicle keeping the start Ping's trip_id/route_id/start_date/stop_id; keep only same,
  non-null trip_id; `0 < dt_s <= 300`; `dist_m / dt_s <= 30 m/s`; a run = a contiguous
  stretch of one vehicle's Pings with the same (trip_id, start_date) by gaps-and-islands
  (a vehicle returning to a trip_id later is a new run); drop a Leg only if it is
  stationary (< 25 m) **and** before the run's first stop_id flip, after its last, or in
  a run that never flips - moving terminal Legs and all stationary mid-trip Legs are
  kept (whole-region deletion is storm-correlated: 18.7% vs 12.2%; R2 6.7% vs 7.2%);
  geodesic distance; Cell of the midpoint (mean lat/lon); Hour = `ceil_hour(t0 + dt/2)`;
  `route_class` express if upper(route_id) matches `^(X|BM|QM|BXM|SIM)`, sbs if
  route_id ends with `+`, else local - **permanently the pick-free rule** (it is part of
  the `leg_hours` / `cell_hour_speed` key, so it must not change when a Pick lands;
  06's `trip_type` is a separate column on `events`, never a Leg key); yield ~87-89%.
  `n_dropped_dark` counts Ping pairs dropped by the dt gate (dt_s > 300 s),
  `n_dropped_terminal` those dropped by the stationary run-end rule.
- Speed = space-mean `sum(dist_m) / sum(dt_s)` per Cell-hour, never a mean of ratios;
  `dt_s_sum / n_legs` rides on every aggregate; archive-era (120 s) and live-era (30 s)
  Speeds are never pooled. Named limitation on every Speed shown: the chord is 6.7%
  (median) to 14.5% (mean) short of the path at 120 s and shorter when slow, so **a
  chord ratio overstates a slowdown** by an unmeasured 0-10 points and levels sit ~10%
  under MTA's shape-distance speeds; every headline ratio carries a chord-corrected
  companion (class-median r by speed class) as the optimistic edge of a band, until
  along-shape distance exists (fog, Pick-gated).

### H. Precipitation (tickets 02, 03, 08, 09, 07; ADR-0002)

- Sources: AORC v1.1 Zarr (anonymous S3) for every published hour of the archive span
  and beyond (frozen at 2025; the NYC slice is copied to Bronze `precip/aorc/<year>`
  as the fidelity copy); MRMS `MultiSensor_QPE_01H_Pass2` from NOAA NODD from
  2026-08-14T00Z for the live era, landed daily as a decoded footprint-only Bronze copy
  (no GRIB2 bytes archived); `RadarOnly_QPE_01H` at its :00 stamps only for the live
  table. Never regridded onto each other; each grid has its own `cell_pixel`; sources
  meet at Cell grain and are never pooled in one fit (`src` is collinear with era).
  MRMS stamps are hour-ending (by measurement, ADR-0002); ERA5, Stage IV, nClimGrid
  are out.
- The Zarr bridge is xarray `.sel()` -> pandas -> Spark (NYC fits in one AORC chunk);
  Sedona reads no Zarr; the raster path (`RS_MakeEmptyRaster` + `RS_AddBandFromArray`
  + `RS_Values`) is used once for Product 3, not on the feature path. `precip-hourly
  SRC=aorc MONTH=` materialises the Bronze `precip/aorc/<year>` NYC slice from S3 on
  first touch and reads from Bronze thereafter (the Bronze copy is the oracle for the
  rolling-sum test). Canonical detail: research asset 08 (features, section 5 build
  SQL, tests) and ADR-0002.
- `silver/precip_hourly`: partition `src=aorc|mrms / month=`, one file per partition,
  sorted (i, j, hour_end_utc), grain (src, i, j, hour_end_utc) unique per partition
  (asserted); columns i, j INT16, hour_end_utc TS, mm FLOAT32 (a negative sentinel is
  stored as a NULL row, never dropped), t2m_k FLOAT32 (AORC only). Footprint per src =
  the crosswalk's distinct Pixel set (AORC 4,868 Pixels), not the bbox. `precip-hourly
  SRC=mrms` fetches each new Pass2 file into the Bronze copy and rebuilds the month
  partition from Bronze as one file; `SRC=aorc` reads the Zarr slice.
- `silver/precip_cell_hourly`: partition `src / month=` (month of the hour-ending
  label), sorted (cell, hour_end_utc), grain (src, cell, hour_end_utc) unique, **dense**
  over every Cell x every hour of the month; columns mm_1h (area-weighted Cell mean;
  NULL unless the realized non-null Pixel weight sums to 1 within 1e-6 - guard on
  realized weight, not a null count), mm_1h_prev, mm_3h, mm_6h (NULL if any hour in
  the frame is NULL), mm_24h with n_hours_24h (count-and-decide), t2m_c (AORC only,
  NULL for mrms). Built per (src, month) with a 24 h lookback into `precip_hourly`
  (never the prior month's output), so months build in any order; the dense spine is
  `explode(sequence(...))` on Spark (the DuckDB text of the same job uses
  `generate_series`; window frames written inline). ~36M rows/yr, ~0.2 GB/yr.
- Time alignment: `hour_end_utc = ceil_hour(arrival_ts)`; an arrival exactly on the
  hour stays in that Hour; every consumer joins on (src, cell, hour_end_utc) with `src`
  pinned; **no precip columns on `events` or on Gold** (joined at read). The two-term
  lag (mm_1h, mm_1h_prev) is valid only at Cell-hour / Gold grain; an event-grain model
  carries `minute_of_hour` derived from `arrival_ts` (never stored) interacted with
  mm_1h, or the trailing-60-min estimate f x mm_1h + (1 - f) x mm_1h_prev with f =
  minute / 60. Models consume
  disjoint lags derived at read by subtraction (mm_1h; mm_1h_prev; mm_3h - mm_1h -
  mm_1h_prev; mm_6h - mm_3h; mm_24h - mm_6h); the leakage-free headline uses
  mm_1h_prev and longer lags. Wet/dry/frozen/onset/sustained are Gold analysis
  parameters with a required three-cutoff sweep: dry = mm_1h < 0.1 and mm_1h_prev < 0.1
  (Speed baseline adds the recovery guard mm_6h < 0.5); wet = mm_1h >= 1.0 and t2m_c >
  2; frozen = mm_1h >= 0.1 and t2m_c <= 2 (counted apart, excluded from both classes);
  onset = mm_1h >= 1.0 and (mm_6h - mm_1h) < 0.1; sustained = mm_1h >= 1.0 and (mm_6h -
  mm_1h) >= 1.0; the band 0.1 <= mm_1h < 1.0 excluded from the binary contrast.
- Live precip table `live/precip_cell/valid_ts=<YYYY-MM-DDTHH>/` (string key, columns
  cell, mm_1h, fetched_at): RadarOnly at :00 stamps only, Cell mean through the mrms
  crosswalk (numpy dot, no Spark), negatives NULL, append-only, latest `fetched_at`
  wins per (cell, valid_ts) at read, retention 7 days by directory name. Written by a
  small periodic job on a 300 s `StartInterval` LaunchAgent (approved) that runs for
  seconds and exits - never inside the archiver loop, never inside the stream.
- Named limitations: hourly accumulation only (no rain rate); adjacent AORC Pixels
  correlate at 0.996-0.998 (a few dozen independent rain series over the city; every
  per-Cell claim reruns with the crosswalk aggregated to ~4 km blocks); live-era phase
  (rain vs snow) has no source until winter 2026-27 (fog).

### I. Gold and the analysis products (tickets 06, 10, 08, 14)

- `gold/cell_hour_route` (month=): grain (cell, hour_end_utc, route_id, direction_id);
  n_events, late_share, early_share, mean_segment_excess_s, ewt_s (renewal-formula
  E[h^2]/2E[h] on observed minus scheduled headways), bunched_share, wait_ok_share,
  coverage (arrivals_obs / arrivals_sched, vp_coverage). No precip columns.
- `gold/cell_hour_speed` (month=), grain (cell, hour_end_utc, route_id, route_class):
  rollup of `leg_hours` by `gold MONTH=` reading
  `service_date` in [month_start - 1, month_end] and keeping the month's Hours before a
  dynamic overwrite of that month only; sums only (n_legs, n_vehicles, dist_m_sum,
  dt_s_sum, n_dropped_terminal, n_dropped_dark); direction-free, so not columns on
  `cell_hour_route`.
- `gold/cell_hourofweek_baseline` (partition `window=` W1, W2, later years), grain
  (cell, hour_of_week INT16 in America/New_York): dry side only - `speed_dry` (space-mean over the bin's dry Cell-hours), `n_dry`,
  `n_legs_dry`, **`dist_m_sum_dry`, `dt_s_sum_dry`** (so a window's dry Speed is
  mergeable across the 168 America/New_York hour-of-week bins; the two DST transition
  hours per year dropped); dry = 08's rule plus the recovery guard, swept; no wet
  columns (~0.35 wet observations per bin per window). `mean_segment_excess` dry
  baseline from `events` alongside once Picks are loaded. Windows are baselined and
  fitted separately, then compared.
- Analysis outputs (one SQL text run by the export job and importable by a notebook):
  wet Cell-hour anomalies scored against their bin and aggregated per Cell (mean
  anomaly, ratio, n_wet, 95% interval clustered by wet event / day); the two storm
  composites with the response window from the rain per Cell (analysis) and fixed
  citywide hours (page); the rain-lag table (Speed ratio by hours since the wet Hour);
  per-Cell regression as a preview with the calendar flags; every per-Cell claim rerun
  on ~4 km blocks; every ratio as bus-minute-weighted citywide and median Cell with the
  chord-corrected companion; the wet/dry ratio with and without the pre-school weeks.
  Per-Cell hotspot claims wait for the full backfill; the artifact says so.
- **Wet event** (the cluster unit for every published interval): a maximal run of
  Hours in which at least one footprint Cell is wet (mm_1h >= 1.0, AORC), with gaps of
  up to 6 dry Hours bridged (a storm with a lull is one event); each wet Cell-hour
  belongs to the event containing its Hour. Published intervals are 95% with errors
  clustered by wet event; clustering by service day is the sensitivity check reported
  beside it. The interval-width gate (default 0.30, swept) applies to that interval.
- Benchmarks (report-only on the first run): Speed vs MTA Socrata `58t6-89vi` (2023-24
  route segment speeds; W2 route x day-of-week x hour, segments recombined
  trip-weighted as sum(road_distance x trips) / sum(travel_time x trips)) and
  `cudb-vcni` (route x month x day_type, recombined as sum(miles) / sum(hours) over
  periods and boroughs; both windows); Delay/Headway vs `v4z4-2h6n` (Wait Assessment:
  wait_ok share per route x month x peak/off-peak) and `8mkn-d32t` (Customer Journey
  additional bus stop time: mean positive delay_s by trip_type). Ratio distribution and
  Spearman rank agreement across routes with the known biases named (chord -7..-15%,
  terminal handling +3%, MTA time may include layover); a band [0.75, 1.15] plus rank
  agreement is the candidate gate after the first run; the first month is calibration.

### J. Streaming and the live tables (ticket 07)

- One Spark app (`stream`): one Kafka `readStream` per topic, `foreachBatch` on each
  calling only the stateless enrichment (`with_cell`, `with_zone`, `with_live_precip`)
  and appending its micro-batch, `coalesce(1)`, `partitionBy(date, hour)` from the row's
  `fetched_at`, to `live/vp/` and `live/tu/`; the TU batch reduces per-stop rows to one
  row per (trip_id, vehicle_id, fetched_at) with the next-stop Prediction and, once the
  census-complete decoder lands, the trip-level delay; VP and TU are two tables joined
  at read (latest per key); no stream-stream join, no state store, no watermark, no
  exactly-once (`foreachBatch` is at-least-once; readers take latest-per-key and exact
  duplicates change nothing). `with_live_precip` reads the live precip table fresh
  inside the callback (a hoisted DataFrame freezes its file index), takes
  `precip_valid_ts = max(valid_ts) <= batch time` as a scalar and broadcast-joins on
  `cell`, so every live VP row carries `cell`, `mm_1h`, `precip_valid_ts` (the exporter
  never re-joins precip); **an absent or empty live precip table yields NULL `mm_1h` /
  `precip_valid_ts` on the row and never fails the batch**. Trigger 30 s; in-batch `dropDuplicates(vehicle_id, ts)`;
  `awaitAnyTermination()`; FAIR scheduler; distinct temp-view names per query.
- Recovery: per-query checkpoints under `checkpoints/`; `failOnDataLoss=false`;
  `maxOffsetsPerTrigger=250000`; `startingOffsets=latest` on a fresh checkpoint only;
  resume replays a sleep gap at bounded pace into the true `date=/hour=` (that replay is
  the checkpointed-recovery demo); `FRESH=1` discards the checkpoint when the gap
  exceeds the 48 h horizon. Live retention 48 h = Kafka's: the daily job drops
  `date=/hour=` dirs older than 48 h by name. **Progress file**: `foreachBatch` writes
  `live/_progress.json` (batch id, batch end timestamp, rows) after each append - three
  lines - so the page can show the rail and separate a dead stream from a dead
  exporter. On demand, foreground, not a daemon (revisit with an always-on box).
- The Kafka JSON schema is one `StructType` per topic derived from the decoder's row
  shapes and asserted equal to them; a Kafka output topic is not built (nothing
  consumes it).

### K. Daily job and LaunchAgents (ticket 07)

- `daily`: lists `service_date=` partitions under `silver/events` against Bronze-present
  dates (bounded, last 14 days) and builds each gap (`events DATE=`, which also writes
  `leg_hours`), then runs `precip-hourly` / `precip-cell` for `src=mrms` on the current
  month, then drops live dirs older than 48 h. A 06:00 America/New_York
  `StartCalendarInterval` LaunchAgent runs it (launchd coalesces missed intervals; the
  unit of work is "all gaps"). The `precip_live` job runs on its own 300 s
  `StartInterval` agent. Both agents are approved; the archiver agent is unchanged.
  Log rotation for the archiver log needs root and stays with Ross.

### L. Serving (ticket 14)

- One static page (MapLibre GL JS 5.9.0 UMD - v6 is ESM-only - vendored by `vendor`
  into a gitignored directory; no npm, bundler or framework), two panels, served by
  `python -m http.server` from the web directory (`web`; nothing needs Range requests),
  a provenance strip naming the rail and pins. Rejected with measured reasons:
  DuckDB-WASM (8 MB gz to move ~2 MB; no directory listing over HTTP), PMTiles/
  tippecanoe (~1,400 polygons), deck.gl, a local API (the file is the evidence artifact
  and works with nothing running), a notebook deliverable.
- **Export** (`export`, one DuckDB script running one SQL text; every query ordered so
  re-export is byte-identical; explicit `round(x, 3)`; **pure-SQL JSON writer**
  (`json_object` / `json_group_array` with `json_merge_patch('{}', ...)` so an
  unpublishable value is an ABSENT key - the GDAL GeoJSON writer emits `null` and
  MapLibre's `has` is true on a null key, which breaks the grey guard)). Files:
  `cells.geojson` (one Feature per footprint Cell, geometry from `ref/cells` at 5 dp,
  id = hex Cell string, wide properties: identity `cell`, `zone_id`, `zone_name`,
  `borough` from `ref/cell_zone` + `ref/zones`; per window `W_dry`, `W_ratio`,
  `W_lo`/`W_hi` (95%, clustered by wet event), `W_nwet`, `W_ndry`, published only when
  the interval is narrower than a swept width (default 0.30); per storm hour `H_ratio`
  (vs the window's dry hour-of-week baseline), `H_lo`/`H_hi` (same gate), `H_n`,
  `H_ndry`, `H_mm` (AORC), `H_lag` (required); no route breakdown), `headline.json`
  (per number: value, literal estimand - e.g. "bus-minute-weighted citywide space-mean
  chord Speed in the storm hour over the same Cells' dry same-hour-of-week space-mean
  Speed for that window (dry = mm_1h < 0.1, mm_1h_prev < 0.1, mm_6h < 0.5), rule set
  R2, AORC hourly" - the median-Cell companion "over publishable Cells, 95% CI
  clustered by wet event", `n_legs`, `n_cells`, `n_cells_hidden`, `band` as a numeric
  pair [ratio, ratio_chord_upper] rendered as a range, `W_ratio_ex_preschool`),
  `zones.geojson` (263, simplified 0.0002 deg). Inputs: Gold `cell_hour_speed`,
  `cell_hourofweek_baseline`, Silver `precip_cell_hourly src=aorc`, `ref/cells`,
  `ref/cell_zone` + `ref/zones`, `ref/calendar`.
- Page rules: a missing property paints grey (`["!", ["has", p]]`); one
  `setPaintProperty` per layer/hour switch, fixed ramp 0.5..1.2; layers W1 wet/dry, W2
  wet/dry, Ida hour-by-hour (02Z-08Z), 2023-09-29 hour-by-hour (10Z-21Z), each
  window's dry baseline; the legend names the estimand and the precip source ("rain:
  AORC hourly, hour-ending"); required sentence: "this slice supports citywide and
  borough effects and the two composites; per-Cell colour is a preview with wide
  intervals; hotspot claims wait for the 7-year backfill and 08's coarsened rerun";
  headline = citywide + median Cell + the rain-lag curve; the hex map is titled as a
  preview; the 2023-09-29 panel states its band reaches ~1.0; `n_cells_hidden` prints
  beside every median-Cell figure (the hidden set is storm-correlated).
- **Live export** (`live-export`, a foreground DuckDB loop, 30 s): latest Ping per
  vehicle with `fetched_at >= now() - 10 min` on the **wall clock** (never
  `max(fetched_at) - 600`), reading `live/vp` pruned by literal `date IN (today,
  yesterday) AND hour IN (HH, HH-1)` (the max probe over the same pruned set), joined
  at read to the latest `live/tu` row per (trip_id, vehicle_id) (already reduced by
  the stream), no precip join; writes `live.geojson` (per vehicle, absent when unknown:
  vehicle_id, route_id, trip_id, stop_id, bearing, occupancy, ts, fetched_at, cell,
  pred_next_s + next_stop_id, mm_1h + precip_valid_ts, trip_delay_s) then `meta.json`
  (as_of_utc, source, window_min, error, stale, vp_fetched_at_utc + vp_age_s,
  tu_fetched_at_utc, precip_valid_ts + age, n_vehicles, n_with_prediction,
  n_with_trip_delay, n_in_rain_cells, stream_progress copied from the progress file,
  export_s) by atomic replace; a failed tick writes `meta.json` with `error` +
  `stale: true` and leaves `live.geojson` alone. `SOURCE=bronze` reads the archive
  VP/TU instead: 20-min window (10-min flush parts), Stop-row TU reduced in two steps
  (latest fetch per (trip, vehicle), then that fetch's earliest arrival), no
  cell/mm_1h/trip_delay_s, `fetched_at IS NULL` rows excluded by the recency filter,
  `source: bronze` printed on the page.
- Live panel rules: re-fetch `meta.json` then `setData` the GeoJSON every 30 s only when
  `error` is null; STALE styling (dimmed, "STALE: the pipeline is not writing") when
  `vp_age_s > 120` (live) / `> 900` (Bronze), on `stale`/`error`, or when meta is
  missing; the panel prints "N vehicles in the last 10 min, M in Cells at >= 1 mm
  RadarOnly (valid ts, age), P with a next-stop Prediction", the stream batch id/rows/
  age, and the source. "MTA-reported trip delay > 5 min" (never "late"; the 300 s cut
  is 06's Delay cutoff borrowed for an agency-computed, unvalidated quantity) is a
  gated state until `trip_delay_s` arrives; the live rain flag is a RadarOnly threshold
  labelled "rain: MRMS RadarOnly QPE 01H, uncalibrated, hour-ending, valid <ts>" - not
  CONTEXT's Wet hour (no temperature guard live).
- Canonical detail: research asset 14 and the read-only prototype under
  `research/14-serving-prototype/` (reference for shape and numbers, never reused
  verbatim - it has no test coverage beyond rendering).
- Ground layer = taxi zones; no basemap (a Protomaps NYC extract is 112 MB, needs a
  Range server and three-licence attribution: optional `basemap` target, off the route).
  Not built: public hosting, CDN JS at demo time, route pages, animation, trails,
  replay, auth, output topics for the page.

### M. Sequencing and preconditions

1. Runtime: pins, `warm`, session factory, `ref` (grids, cells, zones, cell_zone,
   cell_pixel for both grids, calendar, the captured current zips registered as
   Picks), the DuckDB h3 oracle test, the Times Square gate. Preconditions: external
   SSD mounted, `RAINCHECK_ARCHIVE_ROOT` pointing at it (Bronze, Silver, live all
   there) **and `RAINCHECK_BRONZE_GB` set to a drive-sized number** (the archiver's
   count is absolute and the backfill counts); Docker VM at 4 GB is optional.
2. Precip for the slice months: `precip-hourly SRC=aorc` (2021-08..10 incl. lookback,
   2023-08-31..10) and `precip-cell`; the Ida fixture test.
3. Loader: `nbp DATE=` over the 124 files (T1), `events DATE=` producing `leg_hours`
   (with `pick_gap` rows), `gold MONTH=`, `baseline WINDOW=` for W1/W2; T3 (Ida <= 0.85),
   T6, T7; T4 report-only; T5 one-off. The Speed route needs no Pick.
4. Serving: `export`, `vendor`, `web`; the page over Gold. `live-export SOURCE=bronze`
   works from step 1 (real Bronze exists today).
5. Live rail: census-complete decoder + census test, six-partition topics, single-poller
   archiver, `precip_live` + its agent (before the stream: its table is the stream's
   input, and an absent table must yield NULLs, J), `stream` with `_progress.json`,
   `live-export` against the live tables; `schedule PICK=` for the in-effect current
   Picks (grant-free, D) so live-era `events` carry Delay/Headway and
   `cell_hour_route` builds; `daily` + its 06:00 agent.
6. Archive-era Picks: on "13: grant approved" - the puller (24 zips), `schedule
   PICK=`, rebuild `events` for the slice with Delay/Headway (`route_class` on Legs
   does not change), `cell_hour_route` for the windows, the MTA-denominator validation
   (calibration month, not a gate). If refused: F's Delay columns stay NULL for the
   archive era; live era unaffected.
7. Full backfill (2,278 files, ~45 GB xz + ~45 GB Bronze + ~56 GB events) after the
   slice validates; the 2017-19 20-column variant is covered by the T1 fixture.

## Testing Decisions

- **What makes a good test here**: it exercises a job or function through its public
  entry (a Makefile target's Python entrypoint, or a pure DataFrame/decoder function)
  against small frozen fixtures, and asserts on external behaviour - the rows written
  under a temp data root read back with **DuckDB**, or the rows returned - using
  values pinned to primary sources (the Ida Cell reads 84.28 mm; Times Square lands at
  (-73.9855, 40.7580); the fixture VP file has 1,190 Pings). Never on internals
  (Spark plan shape, file counts unless the count is the contract, private helpers).
  Idempotence and grain uniqueness are asserted on every table a job writes.
- **Seams** (confirmed by Ross): (A) the data root - each job entrypoint runs against a
  pytest temp root seeded with fixtures and the written tables are read back with
  DuckDB; (B) pure functions on fixtures - `enrich.*` DataFrame functions and the
  decoders - with one session-scoped Spark fixture (one JVM per process, ~9 s), tests
  skipping when no JVM is found. Not seams: the browser page (a fetch smoke over the
  stdlib server only; visual check manual, the prototype is the reference), Kafka
  beyond a single `availableNow` drain, launchd plists (verified by a real flush at
  deploy).
- **Fixtures** (frozen, committed, small): the existing 2026-08-11 VP/TU/alerts and
  2026-08-16 subway `.pb`; a Bronze VP/TU slice of a few 10-min parts; fragments of two
  archive xz days (the 20-column 2018-10-10 file and the DST 2021-11-07 file) plus the
  head of 2021-09-02; one static GTFS zip (the current Brooklyn zip passes the scheme
  check today); the AORC NYC slice for the Ida day (+24 h lookback) and one control
  hour; one MRMS Pass2 and one RadarOnly file for a known stamp; a three-Snapshot / one
  multi-stop-TU-fetch / one precip Hour fixture for the live export.
- **Two tiers.** Tier 1 = fixture-level pytest: runs on any machine against a temp
  data root, skips (never fails) when no JVM or no Kafka broker is reachable. Tier 2 =
  slice-scale acceptance gates run once against the built slice by `make gates`
  (10-T3, 10-T4, 10-T5, 10-T6, 14-1, 06's MTA-denominator validation); they are the
  loader's and rules' proof and are not shrunk into fixtures.
- **Checks by layer** (the tickets' numbering kept for traceability; tier 2 marked):
  runtime 07-1 (session starts, `ST_H3CellIDs` of Central Park =
  `882a100895fffff`, axis gate, pandas round trip); ref: `cell_pixel` sum(weight) = 1
  +/- 1e-9 per (grid, cell) for both grids and anti-join against the stored footprint
  empty (08-T1), `ref/cells` vs the DuckDB `h3` oracle by `ST_Equals` on all 4,113 rows
  (14-2), zones count/valid/axis; loader 10-T1 (rows == xz rows, unique (vehicle_id,
  ts), ts gate, bbox, three route classes, convert twice identical and neighbour
  untouched, both fixture files clean); events 07-2 / 10-T7 (`events DATE=` twice ->
  same rows and key set incl. `leg_hours`; neighbour partition untouched; a stray
  staging dir changes no read), 06 (DST unit test for `sched_ts`; the multi-vehicle
  trip key; Passage-vs-Prediction agreement bounds and coverage baselines as
  regression bounds; anti-join `events.cell` vs `ref/cells` empty (08-T7)); Legs
  10-T3 (tier 2, the acceptance gate: for each Ida hour ending 03Z and 04Z, the
  **citywide** space-mean chord Speed sum(dist_m)/sum(dt_s) over the hour, divided by
  the **median of the same citywide same-hour-of-week value over the other eight weeks
  of W1**, each control hour required to read < 0.1 mm citywide in `precip_cell_hourly
  src=aorc` (true of 2021-08-26 03Z/04Z); n_legs >= 15,000 per storm hour; pass = ratio
  <= 0.85 for both hours; T3 computes its own denominator from `gold/cell_hour_speed`
  and never reads `cell_hourofweek_baseline`, whose space-mean is the page's estimand,
  not this gate's; 02Z and the 2023 hours reported not gated), 10-T6 (tier 2:
  footprint ~1,146 Cells/day, 0 legs in AORC-NULL Cells, `n_dropped_terminal` share
  within 0.01 storm vs control); precip 08-T2 (dense and unique per partition; `n_hours_24h` = 24
  at a month's first Hour), 08-T3 (Cell mean within Pixel min/max; a constant field
  gives 1.0), 08-T4 / 10-T2 (Ida fixture 84.28 +/- 0.05 at the Cell, bbox mean 49.14,
  mm_24h equals an independent xarray rolling sum), 08-T5 (`ceil_hour` on and after
  the hour), 08-T6 (MRMS ingest: stamp H -> `hour_end_utc` H, negatives NULL, Central
  Park at (5603, 2078), footprint matches `ref/grids`), 07-5 (`precip_hourly` unique on
  its grain), 07-4 (live precip: string `valid_ts` key, latest-wins read, a ping at
  20:40 gets `precip_valid_ts` 20:00, a Hour written after the query starts is seen
  next batch); stream 07-3 (the test publishes the fixture-decoded VP/TU rows to a throwaway topic
  with a small test producer and skips when no broker answers; `availableNow` from
  earliest on a throwaway checkpoint drains > 0 rows with `cell` non-null and NULL
  `mm_1h` when no live precip table exists into `date=/hour=`; second run finds nothing;
  two triggers write two files; `_progress.json` written); schema 07-6 (`StructType`s
  equal decoder key sets; census test extended for the census-complete decoder);
  serving 14-1 (tier 2 on the built slice: feature count, no null property, estimand
  + numeric band + hidden count on every row, fixture Cell has `w1_dry` > 0 and an Ida
  hour, 263 valid zones, byte-identical re-export; a tier-1 twin runs the same
  invariants on a three-Cell fixture Gold), 14-3 (live-export fixture: newest Ping,
  Prediction from the newest fetch's earliest arrival, wall-clock exclusion, atomic
  files, delete-the-root-between-ticks -> `error` set and loop alive, `SOURCE=bronze`
  semantics), 14-4 (server answers 200 for the page, two vendored files and five data
  files; `meta.json` has `error: null` after a healthy tick). Report-only (tier 2): 10-T4
  (the four Socrata benchmarks in I), 10-T5 (Product 3), 06's MTA-denominator
  validation (first month calibration).
- **Prior art**: the existing decoder/archiver test suite (frozen `.pb` fixtures ->
  decoders; archiver flush under a monkeypatched temp root read back with pyarrow; the
  census tests). New tests follow its shape and its module-scoped fixtures; DuckDB
  replaces pyarrow for read-back where partitions matter.

## Out of Scope

- The flood map (second effort per the map: flood-event history, exposure scores per
  entrance/stop/segment, a real-time detector); alerting channels of any kind; public
  hosting or re-serving of MTA feeds (GitHub Pages is a note, not a step); SIRI
  endpoints; scraping news sites.
- Promotion beyond the laptop: always-on capture box, object storage for Bronze, the
  daemonized streaming job, the slim Sedona image / EKS; a Kafka output topic; subway
  Kafka topics and any subway Silver; Iceberg (revisit at a concurrent writer or the
  lakehouse demo).
- A per-Leg Silver table; along-shape path distance for Speed (the chord's Pick-gated
  replacement); r(v) re-measured on weekdays with a jitter guard; the full 2,278-file
  backfill's runtime tuning beyond step 7; MRMS sub-hourly features and a live-era
  precipitation phase source; the AORC-vs-MRMS overlap comparison and the 2026 src
  re-key once `2026.zarr` lands; occupancy bunching signatures; a data.ny.gov schedule
  path if MTA ever restores times.
- Serving extras: a basemap (optional target), CDN-loaded JS, DuckDB-WASM, deck.gl,
  PMTiles, a local API, a notebook as the deliverable, route pages, animation, replay,
  auth, analytics.
- Power-setting changes on the Mac; log rotation (Ross, root); Docker VM resize (Ross).

## Further Notes

**Corrections that supersede a ticket's first text (latest wins):**

| if you read | note |
|---|---|
| 02 / raster playbook: regrid MRMS onto AORC | overturned by 08 / ADR-0002: no regrid, per-grid crosswalk |
| 03: Java 11 not 17; RS constructors are FromGeoTiff/FromNetCDF only | 07: Java 17 measured clean; 102 RS_ functions incl. in-db constructors |
| 04: H3 res 8 ~1:1 with AORC | 09: a Cell overlaps 4.7 Pixels; area-weighted crosswalk, never nearest |
| 05: subway zip excluded; immutable parts; "delay never populated" | 15: subway zip included; same-window restart appends; trip-level `trip_update.delay` IS populated (06) - it is not the project's Delay |
| 07 asset: the 10 GB budget covers all of `data/` | 10: the archiver counts the archive root only; the SSD is the fix |
| 08 build SQL uses `generate_series` | 07: Spark 3.5 uses `explode(sequence(...))`; two texts, one per engine |
| 09/10: baseline = speed_dry, n_dry, n_legs_dry | 14: add `dist_m_sum_dry`, `dt_s_sum_dry` |
| 10 T3 "median" | the acceptance test's construction; the page's estimand is the space-mean baseline |
| 12: resolver = greatest fetched_at whose calendar covers D | 13 sweep: resolver v2 = pick code from that day's VP trip_ids (Ida day = C1 `4b8dec91`, not `c244b822`) |
| 12: five-token trip_id | optional modifier segments; split on the six-digit start token |
| 11: Wayback 2014-16 only; ~65 versions per feed | 13: 9-12 captures per feed 2016-2024 (25 byte-identical); 423 in-window versions |
| 14 first draft: GDAL writer; data-anchored live window; "late and raining" paint class | pure-SQL writer; wall clock + STALE; gated "MTA-reported trip delay" |
| map/vault: archive runs to 2024-09-06 | 10: 2024-11-04, UTC-day files |

**Preconditions and human steps**: the external SSD and `RAINCHECK_ARCHIVE_ROOT`
before step 3; ticket 13's grant reply (Ross says "13: grant approved" / "refused")
before step 6; Docker VM 4 GB (optional); log rotation (root). The archiver
LaunchAgent keeps running throughout; stop with `launchctl bootout` if ever needed;
its 10 GB loud stop trips on the archive root.

**Known limitations to state wherever the numbers appear**: chord ratios overstate
slowdowns (0-10 points; levels ~10% under MTA); the two windows hold a few dozen wet
events (cluster errors by event; per-Cell claims are previews); dwell is not separable
at 120 s; the archive's vehicle clock is irregular within the 120 s poll and its stall
behaviour is unobservable; live rain has no phase guard; the 2023-09-29 band reaches
~1.0.

**Cost**: local only, no cloud writes; the only paid thing on the horizon is nothing in
this spec.
