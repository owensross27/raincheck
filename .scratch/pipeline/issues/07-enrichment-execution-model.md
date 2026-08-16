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
