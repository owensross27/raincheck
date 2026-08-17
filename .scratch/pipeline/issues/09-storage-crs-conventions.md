# 09 Storage and CRS conventions

Type: grilling
Status: resolved
Blocked by: 04

## Question

Lock the storage layout and coordinate discipline before the first Sedona job writes
anything. Starting position from `../reality-check-2026-08-15.md` section 4:
EPSG:4326 canonical, one-time ST_Transform of EPSG:2263 city layers at ingest with an
axis-order check, geodesic or UTM-18N for metric math, precomputed AORC-cell-to-H3
and H3-to-taxi-zone lookups so joins are on (h3, hour), Bronze hourly Parquet /
Silver Sedona GeoParquet 1.1 with bbox covering sorted by H3 then time / Gold
aggregates, Iceberg deferred until file count or the lakehouse demo justifies it.
Ross confirms or amends. Answer records the final table schemas and partition keys.

## Comments

2026-08-16, from [06 Delay metric design](06-delay-metric-design.md): the Silver
event table's grain and columns are decided there (one row per start_date, trip_id,
stop_sequence, vehicle_id; arrival, censor bounds, arrival_src, delay_s,
segment_excess_s, headway columns, family, static_pick_id, pred_*). 09 decides its
physical layout (GeoParquet, sort by Cell then time, partition by date) and where
`static_pick_id` resolves (a small picks table), not the columns.

### 2026-08-16 — measured, adversarially reviewed, round posted; awaiting Ross

Measured (`research/09-storage-schemas.md` carries the numbers): AORC coordinate
arrays start (-130.0, 20.0), step 0.008333 float32-truncated, no bounds (center
registration); over the NYC bbox 78 x 60 Pixels vs 4,113 H3 res-8 Cells; a Cell
overlaps a mean 4.7 Pixels and its largest Pixel covers only p50 53% (p10 36%), so
"res 8 ~1:1 with AORC" (04 #5) is true of areas, false of tessellations — nearest-
Pixel is rejected, area weights (~19.5K rows) are cheap. Silver event rows measure
~30 B/row live / ~24 B/row backfill once the three exactly-derivable timestamps are
dropped (~52 B/row if stored literally); 7-year backfill ~56 GB (external SSD),
10's 120-day slice ~2.6 GB (fits). Verified from primary docs: Sedona 1.9.1
ST_Transform expects lon/lat and normalizes authority axis order (no lenient flag);
GeoParquet writer omits `crs` when SRID=4326 (writes null when SRID=0); Spark 3.5
default timestamp type INT96, session TZ local. Two opus reviews (storage lens,
geospatial lens) reversed three parts of the starting position: Silver `events`
must be batch-rebuilt per closed service date (window-function columns cannot be
stream-appended; Hive Parquet has no snapshot isolation), the WKB point + bbox
covering on `events` prunes nothing under a cell sort (degenerate point bbox), and
precip stored only at Cell grain would decide 08's key and foreclose `RS_Values`.
Round of four decisions posted in chat; recommendations are the schemas file.

## Answer

Resolved 2026-08-16 by grilling; all four recommendations accepted as-is. Typed
schemas, partitions, sort keys and conventions are the asset
[research/09-storage-schemas.md](../../../research/09-storage-schemas.md); this
Answer is the index to it.

1. **Silver `events` is batch-rebuilt plain Parquet.** Written once per closed
   service date (D+1 06:00 America/New_York) from Bronze, rerun replaces the
   `service_date=` partition, never appended to; sorted (cell, arrival_ts), 128K-row
   groups, one file per partition; no WKB/bbox on events (a point bbox is degenerate
   and the cell sort scatters it). GeoParquet 1.1, Sedona-written with SRID 4326 so
   `crs` is omitted (= OGC:CRS84), DOUBLE bbox, is for the geometry tables: `cells`,
   `zones`, `stops`, `shapes`. Same table for 2017-2024 backfill and live; the
   streaming demo writes its own thin table (07). Iceberg deferred; real trigger is a
   second concurrent writer or reader isolation, or the lakehouse demo.
2. **One absolute timestamp per event row.** `arrival_ts` plus integer seconds
   (`censor_width_s`, `delay_s`, `pred_last_off_s`); 06's `pass_lo/hi_ts`, `sched_ts`,
   `pred_last_ts`, `censor_halfwidth_s` are a one-file view. Measured ~30 B/row live,
   ~24 backfill (52 if stored literally): live ~15 GB/yr, 7-year backfill ~56 GB (external
   SSD with Bronze), ticket 10's 120-day slice ~2.6 GB (fits the internal disk).
3. **Precip at native Pixel grain; the crosswalk carries weights.** `precip_hourly
   (i, j, hour_end_utc, mm)` partitioned `src=aorc|mrms/month=`, unique per src,
   consumers pin one src; `ref/grids` freezes each grid from its stored coordinate
   arrays (AORC measured: origin (-130.0, 20.0), step 0.008333 float32-truncated, shape
   8401 x 4201, no bounds so center registration); `ref/cell_pixel (grid_id, cell, i, j,
   weight)` area-weighted in EPSG:32618 with a sum(weight)=1 test. Nearest-Pixel is
   refuted: a Cell overlaps a mean 4.7 Pixels and its largest covers p50 53% (04's
   "~1:1" is true of areas, not tessellations; comment left on 04). Cell-grain precip
   is 08's view or sibling; the native grain keeps `RS_Values` buildable.
4. **Schedule tables and conventions.** `stops/trips/trip_stops/service_days/shapes`
   as Silver partitioned by `pick_id=` (zip sha1, aligned with 12's resolver;
   `pick_gap` flag on the event). CRS: EPSG:4326 lon/lat everywhere; EPSG:2263 layers
   reprojected once at ingest with the Times Square axis-order test (988267.1, 215436.9
   ftUS -> -73.9855, 40.7580; an axis gate, not a datum claim); geodesic-only for
   anything feeding a speed (`ST_DistanceSpheroid` / `pyproj.Geod`; haversine banned
   there, heading bias -0.25%/+0.13% at NYC); UTM 18N for areas. Time: TIMESTAMP_MICROS
   UTC (Spark default is INT96 - set it), session TZ UTC in Spark and DuckDB, precip
   hour-ending, UTC windows read `service_date BETWEEN date(t0)-1 AND date(t1)`, DST
   transition hours dropped from hour-of-week. `cell` INT64 in storage, hex string at
   JSON. Vertical datums stay with the flood map.

Consequences: 07 and 10 unblocked (comments left); 08 inherits the Pixel-grain
table, `cell_pixel`, and the MRMS grid question; CONTEXT.md: Silver redefined, Pick
identified by sha1, new term Pixel; 04 gets the 1:1 correction comment; the ~56 GB
Silver backfill joins Bronze on the external-SSD list (05). Build items for
`/to-spec`: `ref/grids` + `cell_pixel` builder with its two tests, the axis-order
test, the events view file, Spark/DuckDB session settings.

## Comments

2026-08-16, from [08 Weather join design](08-weather-join-design.md): three
in-place edits to `research/09-storage-schemas.md`, all inside what 09 handed to
08. (1) `precip_hourly`: the stored footprint per src is the crosswalk's Pixel set
(`SELECT DISTINCT i, j FROM cell_pixel WHERE grid_id = :src`, AORC 4,868 Pixels /
117K rows/day), not the bare 78 x 60 bbox: measured, 153 rim Cells carried weight
on Pixels outside the 4,680 slice (lost weight p50 0.21, max 0.93), a hole between
"crosswalk padded by one Pixel" and the bbox sizing; negative sentinels are stored
as `mm` NULL rows, never dropped; the AORC ingest also carries `t2m_k FLOAT32`
(`TMP_2maboveground`) for the rain-vs-snow rule. (2) `grids` gains the `mrms` row
(origin -129.995, 20.005; step 0.01; 7000 x 3500; centre; source rows flipped at
ingest; `coord_sha256` = sha256 of the GRIB grid tuple). (3) Gold: no precip
columns; analyses join `silver/precip_cell_hourly` on (src, cell, hour_end_utc) at
read, the way Gold joins `ref/cells`. Also: the Bronze AORC Zarr slice is the
fidelity copy; the trailing windows are SQL over `precip_hourly`, not xarray.

2026-08-16, from [07 Enrichment execution model](07-enrichment-execution-model.md): one
in-place addition to the Roots block of `research/09-storage-schemas.md`, inside what
you handed to 07: `data/live/` (the streaming job's thin tables `vp` / `tu` in your
`date=/hour=` layout, append-only, 48 h retention, plus `precip_cell/valid_ts=`, 7 d)
and the decoded MRMS Bronze copy under `data/archive/precip/mrms/date=/hour=HH.parquet`.
Batch idempotence is `mode("overwrite").partitionBy()` under
`spark.sql.sources.partitionOverwriteMode=dynamic` (added to the session settings);
one-file-per-partition and partition immutability hold for every Silver table
including `src=mrms` (month rebuilt from Bronze, never appended). Also: Spark writes a
timestamp partition key as `2026-08-16 20%3A00%3A00`, which DuckDB reads as VARCHAR - so
partition keys are strings; and `TZ=UTC` must be set process-wide (JVM default TZ is
America/New_York; PySpark `collect()` returns driver-local datetimes even with the
session TZ at UTC).

2026-08-16, from [10 Backfill slice and speed-derivation rules](10-backfill-slice-and-speed-rules.md): additions to
`research/09-storage-schemas.md`, marked (10): Roots gains `data/archive/nycbuspositions/`;
Bronze VP gets the archive note (rows converted from the xz files, `fetched_at` NULL,
partitions from `ts`, occupancy NULL on placeholder days) and the Bronze read rule for a
service day (`date IN (D, D+1)`); Silver gains `leg_hours (service_date=)`; Gold gains
`cell_hour_speed (month=)` (direction-free; not columns on `cell_hour_route`, whose
event rows are per direction) and `cell_hourofweek_baseline` becomes partitioned by
window with the dry side only (`speed_dry`, `n_dry`, `n_legs_dry`); Ref gains
`calendar`. Your Silver read rule (`service_date BETWEEN date(t0)-1 AND date(t1)`) is
unchanged. Also: the archive runs to 2024-11-04.

2026-08-17, from [14 Serving surface for the two showcase artifacts](14-serving-surface.md): `cell_hourofweek_baseline` needs `dist_m_sum_dry` and
`dt_s_sum_dry` (sums, so a window's dry space-mean Speed is mergeable across the 168
bins - `speed_dry` alone is a mean of means; 10 flagged the same for `leg_speed_p50`);
a marked "(14)" line sits under the Gold table in `research/09-storage-schemas.md`.
`silver/precip_cell_hourly` is an export input. `ref/cells` is the one source of Cell
geometry for serving; DuckDB's community `h3` extension is a test oracle
(`ST_Equals(geometry, ST_GeomFromWKB(h3_cell_to_boundary_wkb(cell)))`, all 4,113 rows;
the extension version rides the DuckDB release). `web/files/` is derived-of-derived,
not a data root. Your Times Square axis gate stays with `make ref`; the export checks
zones by count, non-empty `zone_name` and `ST_IsValid` after the 0.0002 deg simplify.
