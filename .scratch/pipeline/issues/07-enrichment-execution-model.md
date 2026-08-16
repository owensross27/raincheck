# 07 Enrichment execution model

Type: grilling
Status: open
Blocked by: 04, 09

## Question

Where and how does Sedona enrichment run: one code path that serves both the batch
backfill and the Kafka stream (Structured Streaming with `foreachBatch` reusing the
batch functions), or two jobs? Local JVM (Java 11 via Temurin) vs the containerized
Sedona image from quakestream? What are the checkpoint, recovery, and exactly-once
requirements worth paying for on a laptop? Which spatial ops run in Sedona (H3
assignment, ST_ joins to boroughs/taxi zones, precip lookup on (h3, hour)) versus
plain PySpark? The Answer is the execution model; the job is downstream build work.

## Comments

2026-08-16, from [09 Storage and CRS conventions](09-storage-crs-conventions.md): 09 is resolved, so this ticket is unblocked. Constraints it
inherits: Silver `events` is batch-only (window-function columns; rebuilt per closed
service_date), so "one code path for batch and stream" means the streaming job
reuses the batch functions on micro-batches but writes its own thin live table, never
Silver; Sedona is on the write path for the geometry tables (`cells`, `zones`,
`stops`, `shapes`, GeoParquet 1.1 with SRID 4326) and for `ST_H3CellIDs` /
`ST_Transform` / `ST_DistanceSpheroid` / `RS_Values`, while `events` and
`precip_hourly` are plain Parquet either engine can write. Session settings
(TIMESTAMP_MICROS, UTC) are in `research/09-storage-schemas.md`.

2026-08-16, from [08 Weather join design](08-weather-join-design.md): the precip
side is fixed (spec `research/08-weather-join-features.md`). Constraints you
inherit: the batch job is one SQL per (src, month) over `precip_hourly` x
`cell_pixel` on a dense spine (window specs written inline; it parses on Spark 3.5
and DuckDB, the engine is yours); the analysis join is at read on (src, cell,
hour_end_utc) with `src` pinned, no precip columns on `events` or Gold; the live
thin table reads `RadarOnly_QPE_01H` at its :00 stamps only (a true Hour, ~5 min
behind wall clock; the 2-min files are rolling 60-min totals ending at the stamp,
so they are a distinct feature `mm_60min`/`window_end_utc`, never joined to the
batch features), through the same `cell_pixel[grid_id='mrms']`, written as
append-only `valid_ts=` partitions with latest-wins reads (no overwrite: Hive
Parquet has no snapshot isolation), stream-static side uncached (03). Cadence of
the src=mrms batch job in live mode and the live table's retention are yours.
Playbook Product 3 (`RS_Values` on the two storm days) is 10's, and it doubles as
the Cell-mean vs stop-Pixel slope report.
