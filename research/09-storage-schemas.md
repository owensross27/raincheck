# 09 Storage layout and table schemas

Asset of ticket [09 Storage and CRS conventions](../.scratch/pipeline/issues/09-storage-crs-conventions.md).
Types are Parquet logical types. `TS` = TIMESTAMP(us, UTC). All lon/lat are
EPSG:4326 x=lon, y=lat. Every geometry column carries SRID 4326 so Sedona's
GeoParquet 1.1 writer omits `crs` (= OGC:CRS84).

## Roots

```
data/archive/   Bronze  (05: vp|tu|alerts/date=/hour=/part-MM.parquet UTC; static/<feed>/<date>.zip; precip/aorc/<year>.zarr NYC slice; 07: precip/mrms/date=/hour=HH.parquet decoded Pass2, footprint only; 10: nycbuspositions/YYYY/MM/<date>-bus-positions.csv.xz sources, and vp/date=/hour=/part-nbp-<date>.parquet converted from them)
data/ref/       small lookups, rebuilt whole, GeoParquet where a geometry is the payload
data/silver/    derived tables, Hive-partitioned, one file per partition, batch-written
data/gold/      aggregates, plain Parquet, partition month=YYYY-MM
data/live/      07: the streaming job's thin tables vp|tu/date=/hour=/ (append-only, coalesce(1) per micro-batch, 48 h retention, dedupe at read) and precip_cell/valid_ts=YYYY-MM-DDTHH/ (string key, latest fetched_at wins, 7 d); never Silver
data/checkpoints/  07: one Structured Streaming checkpoint per query
```

Readers open a dataset root, never a `part-*.parquet` (partition columns live in
the path); DuckDB globs `**/*.parquet` or the root (never `**/*`: Spark's `.crc`
sidecars). Partition keys are strings (a timestamp key is written URL-encoded and read
back as VARCHAR). Every DuckDB session runs `SET TimeZone='UTC'`; Spark runs with
`spark.sql.session.timeZone=UTC`, `spark.sql.parquet.outputTimestampType=TIMESTAMP_MICROS`
and `spark.sql.sources.partitionOverwriteMode=dynamic` (07: batch idempotence is
`mode("overwrite").partitionBy()`), with `TZ=UTC` in the process environment.

Archive-era Bronze VP (10): rows converted from the nycbuspositions xz files carry
`decode_vp`'s columns and types (`archiver.TYPES`), `start_date` as YYYYMMDD,
`direction_id` NULL, `occupancy` NULL on a source day with one distinct value (a
placeholder year), and **`fetched_at` NULL** - the archive exports no poll clock, so
their `date=/hour=` come from `ts` and `fetched_at IS NULL` is the archive-era
discriminator; a converter call rewrites exactly one `date=` partition (idempotent by
part name). Bronze read rule for a service day: `events DATE=D` reads `date IN (D,
D+1)` (service day D starts 04Z/05Z on D and ends ~08Z on D+1; live rows shift only
forward). Silver's read rule below is a different thing.

## Ref

| table | columns | notes |
|---|---|---|
| `grids` | grid_id STRING pk, source_url STRING, origin_lon DOUBLE, origin_lat DOUBLE, step_deg DOUBLE, nx INT32, ny INT32, registration STRING ('center'), coord_sha256 STRING, frozen_at TS | one row per precip grid; origin = the SW Pixel centre, i east, j north for every grid. AORC measured 2026-08-16: origin (-130.0, 20.0), step 0.008333 (float32-truncated, not 1/120), shape 8401 x 4201, no bounds variable -> CF center registration, edges at center +/- step/2. Coordinates come from the stored arrays, never `arange`. MRMS (08, measured from GRIB2 headers): origin (-129.995, 20.005), step 0.01, 7000 x 3500, centre; source rows run north-to-south so ingest stores `j = 3499 - row` and converts lon from 0-360; `coord_sha256` = sha256 of the grid tuple read from the file (Ni, Nj, first/last lat/lon, increments, jScansPositively). `grid_id` equals `precip_hourly.src` by invariant. |
| `cells` | cell INT64 pk, geometry POLYGON (GeoParquet, DOUBLE bbox), centroid_lon DOUBLE, centroid_lat DOUBLE | H3 res 8 over the NYC bbox (-74.30..-73.65, 40.45..40.95): 4,113 rows. Serving-time geometry for every cell-keyed table. |
| `zones` | zone_id INT16 pk, borough STRING, zone_name STRING, geometry POLYGON | TLC taxi zones, EPSG:2263 -> 4326 once at ingest, axis-order test on Times Square. |
| `cell_zone` | cell INT64 pk, zone_id INT16, borough STRING | hex-centroid point-in-polygon (04). |
| `cell_pixel` | grid_id STRING, cell INT64, i INT16, j INT16, weight DOUBLE; pk (grid_id, cell, i, j) | area share of the Pixel inside the Cell, computed in EPSG:32618; built over the bbox padded by one Pixel; test asserts sum(weight) = 1 +/- 1e-9 per (grid_id, cell). AORC: ~19.5K rows, mean 4.7 Pixels per Cell, largest share p50 0.53. |
| `picks` | pick_id STRING pk (sha1 of the zip bytes; equals Transitland's `sha1`), feed STRING, published TS (MTA Last-Modified or Transitland fetched_at), feed_version STRING, earliest_calendar_date DATE, latest_calendar_date DATE, source STRING ('mta' or 'transitland'), path STRING | resolver rule per ticket 12; `pick_gap` is a flag on the event, not here. |
| `calendar` | service_date DATE pk, school_in_session BOOL, holiday BOOL, unga_week BOOL | (10) NYC DOE session calendar + major holidays + UN General Assembly high-level week; one row per slice service day (124 rows for the slice), extended with the backfill. |

## Silver

### `events` (one row per Passage; grain per 06)

Partition `service_date=YYYY-MM-DD` (the feed's start_date). Plain Parquet, zstd,
sorted by (cell, arrival_ts), row groups 128K rows, one file per partition.
Batch-only: written once from Bronze when the service day is closed (D+1 06:00
America/New_York), rerun replaces the directory; never appended to. Same table for
2017-2024 backfill and live.

| column | type | notes |
|---|---|---|
| service_date | DATE | partition column, in the path |
| trip_id, vehicle_id, route_id, stop_id | STRING | as the feed gives them |
| stop_sequence | INT16 | |
| direction_id | INT8 | |
| trip_type | STRING | local / sbs / express |
| stop_lon, stop_lat | DOUBLE | denormalized from `stops` |
| cell | INT64 | H3 res 8 of the stop; hex string at any JSON boundary |
| arrival_ts | TS | the one absolute timestamp on the row (Passage midpoint) |
| censor_width_s | INT16 | full ping gap; pass_lo_ts / pass_hi_ts = arrival_ts -/+ width/2 |
| arrival_src | STRING | vp_passage / tu_last / interpolated |
| interpolated | BOOL | |
| interp_k | INT8 | |
| is_first, is_last | BOOL | |
| pick_id | STRING | -> ref/picks; null with pick_gap when no pick covers the date |
| pick_gap | BOOL | |
| delay_s | INT32 | null when no static match; sched_ts = arrival_ts - delay_s |
| segment_s, sched_segment_s, segment_excess_s | INT32 | |
| headway_obs_s, headway_sched_s | INT32 | |
| wait_ok, bunched | BOOL | |
| family | STRING | headway / schedule |
| schedule_relationship | STRING | |
| pred_last_off_s | INT32 | pred_last_ts = arrival_ts + off; null pre-2024-09 |
| pred_first_horizon_s, pred_range_s, pred_err_10min_s | INT32 | null pre-2024-09 |
| pred_n_changes | INT16 | |
| n_vehicles_on_trip | INT8 | |

06's names `pass_lo_ts`, `pass_hi_ts`, `sched_ts`, `pred_last_ts`, `censor_halfwidth_s`
are exposed by a one-file view (`silver/events_view.sql`) over the physical columns.

Read rules: a UTC time window must scan `service_date BETWEEN date(t0)-1 AND date(t1)`
(service days run to ~28:00; 13.6% of a day's Pings belong to the previous
service date). Route-over-time queries are Gold's; Silver's sort gives them no
pruning.

Measured (synthetic realistic cardinalities, zstd, cell sort, N=1M): ~30 B/row live,
~24 B/row backfill era. Live ~40 MB/day, ~15 GB/yr; 7-year backfill ~56 GB (external
SSD, with Bronze); ticket 10's 120-day slice ~2.6 GB (fits internal disk).

### `leg_hours` (10: Legs aggregated to Cell-hours, per service day)

Partition `service_date=YYYY-MM-DD` (the start Ping's start_date). Written by the same
`events DATE=` job from `enrich.legs()` under 10's rule set R2. Plain Parquet, sorted
(cell, hour_end_utc). Grain (cell, hour_end_utc, route_id, route_class) unique per
partition; an absolute Hour receives legs from two service days.

| column | type | notes |
|---|---|---|
| service_date | DATE | partition column |
| cell | INT64 | H3 res 8 of the Leg midpoint |
| hour_end_utc | TS | `ceil_hour(t_mid)` |
| route_id | STRING | of the start Ping |
| route_class | STRING | express / sbs / local from route_id (10); 06's trip_type when a Pick is loaded |
| n_legs | INT32 | Legs kept |
| n_vehicles | INT16 | approx_count_distinct(vehicle_id) |
| dist_m_sum | FLOAT64 | geodesic chord metres; Speed = dist_m_sum / dt_s_sum |
| dt_s_sum | INT64 | seconds |
| leg_speed_p50 | FLOAT32 | median Leg speed of this partition's legs (not mergeable across partitions) |
| n_dropped_terminal | INT32 | stationary legs dropped at run ends (rain-correlated selection audit) |
| n_dropped_dark | INT32 | legs dropped by dt > 300 s |

~130K rows / ~6 MB per day; the slice ~0.7 GB, the full backfill ~13 GB. Per-Leg rows
are not stored (fog: `silver/legs (service_date=)` if a leg-grain analysis appears).

### `precip_hourly`

Partition `src=aorc|mrms` / `month=YYYY-MM`. Plain Parquet, sorted (i, j, hour_end_utc).
Grain (src, i, j, hour_end_utc) unique; consumers pin exactly one `src`.

| column | type | notes |
|---|---|---|
| i, j | INT16 | Pixel indices into `grids[src]` (lon index, lat index) |
| hour_end_utc | TS | hour-ENDING (AORC verified; MRMS verified by 08, lag-0 correlation) |
| mm | FLOAT32 | depth in the hour; NULL for a negative sentinel (row stored, never dropped) |
| t2m_k | FLOAT32 | AORC `TMP_2maboveground` (Kelvin) for src=aorc; NULL for src=mrms (08) |

Footprint per src = the crosswalk's Pixel set (`SELECT DISTINCT i, j FROM cell_pixel
WHERE grid_id = :src`), not the bbox: AORC 4,868 Pixels, 117K rows/day, ~43M
rows/yr (08; the bare 78 x 60 bbox left 153 rim Cells short of weight). Cell-grain
precip is the sibling `precip_cell_hourly` in `research/08-weather-join-features.md`
(area-weighted mean = conservative remap of a depth field); the native grain stays
so `RS_Values` at the bus position (playbook Product 3) remains buildable.

### Schedule tables (from Bronze static zips; one partition per Pick)

Partition `pick_id=<sha1>` on each. Loaded only for picks a slice needs.

| table | columns |
|---|---|
| `stops` | stop_id STRING, stop_name STRING, lon DOUBLE, lat DOUBLE, cell INT64, geometry POINT (GeoParquet) |
| `trips` | trip_id STRING, route_id STRING, direction_id INT8, service_id STRING, shape_id STRING, trip_type STRING |
| `trip_stops` | trip_id STRING, stop_sequence INT16, stop_id STRING, arrival_s INT32, departure_s INT32, shape_dist_m FLOAT32 (cumulative geodesic along the shape, computed at ingest); sorted (trip_id, stop_sequence) |
| `service_days` | service_id STRING, service_date DATE (calendar x calendar_dates flattened) |
| `shapes` | shape_id STRING, geometry LINESTRING (GeoParquet), length_m FLOAT32 |

Sizing: stop_times.txt is ~124 MB uncompressed per pick (ticket 12); ~15 MB Parquet
per pick, ~6 GB if all ~390 historical picks are ever loaded. No cross-pick dedupe.

## Gold

Plain Parquet, partition `month=YYYY-MM`, no geometry (join `ref/cells` at serving).
Grains fixed here; metric columns are 06's and 08's:

| table | grain | metric columns (owned by) |
|---|---|---|
| `cell_hour_route` | cell INT64, hour_end_utc TS, route_id STRING, direction_id INT8 | n_events, late_share, early_share, mean_segment_excess_s, ewt_s, bunched_share, wait_ok_share, coverage (06); no precip columns: joined at read from `silver/precip_cell_hourly` on (src, cell, hour_end_utc) with `src` pinned (08) |
| `cell_hour_speed` | cell INT64, hour_end_utc TS, route_id STRING, route_class STRING; partition month= | (10) rollup of `silver/leg_hours` by `gold MONTH=` (reads service_date month_start-1..month_end, keeps the month's Hours; sums only: n_legs, n_vehicles, dist_m_sum, dt_s_sum, n_dropped_terminal, n_dropped_dark); direction-free by construction, so not columns on `cell_hour_route` |
| `cell_hourofweek_baseline` | cell INT64, hour_of_week INT16 (America/New_York; the two DST transition hours per year dropped); partition window= (W1, W2, later years) | (10) dry side only: speed_dry (space-mean over the bin's dry Cell-hours), n_dry, n_legs_dry; dry = 08's rule plus the recovery guard `mm_6h < 0.5`, swept; wet anomalies are scored per wet Cell-hour against the bin and aggregated per Cell at analysis time (no wet columns here: ~0.35 wet observations per bin per window); mean_segment_excess dry baseline from `events` alongside when Picks are loaded |

## Conventions

- CRS: EPSG:4326 lon/lat stored everywhere. City layers in EPSG:2263 reprojected
  once at ingest (`ST_Transform(geom, 'EPSG:2263', 'EPSG:4326')`, Sedona expects
  lon/lat and normalizes authority axis order; pyproj `always_xy=True`), gated by a
  test: Times Square (988267.1, 215436.9) ftUS -> (-73.9855, 40.7580) within 1e-4 deg
  and not swapped. The gate is an axis-order check, not a datum claim (NAD83 vs
  WGS84 ~1 m is ignored).
- Distances feeding a speed or a segment: geodesic only (`ST_DistanceSpheroid`,
  `pyproj.Geod(ellps='WGS84').inv`); haversine/`ST_DistanceSphere` is banned there
  (heading-dependent bias -0.25%/+0.13% at NYC). Buffers/areas in EPSG:32618 (UTM 18N,
  -309 ppm at NYC, immaterial; area ratios cancel).
- Time: TS UTC everywhere; `service_date` DATE; precip hour-ending; local time
  derived on read only.
- Columns: `cell` INT64 (bit 63 is 0, exact in signed 64); `*_ts` TS; `*_s` INT32
  seconds; ids as strings; booleans not ints; snake_case; glossary names.
- Iceberg: not now. Silver is batch-rebuilt and partition-immutable, so there is no
  concurrent writer and no reader-isolation need; add Iceberg when either appears
  (or for the lakehouse demo), with WKB + explicit lon/lat/cell columns, not V3 geometry.
