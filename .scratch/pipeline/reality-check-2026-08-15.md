# Reality check, 2026-08-15

Asked: is this still showcase-able, are we on track, what is the budget, stream or
batch, and how do we make storage/CRS smart (GeoParquet, Iceberg, reprojection).

## 1. Against the original ask

| Original intent (2026-08-11) | Status |
|---|---|
| Free/open streaming datasets | DONE. MTA bus GTFS-RT, keyless, ~1,800 vehicles/poll |
| Kafka pipeline | RUNNING. Compose 3.9.1 KRaft, round-trip verified offset-exact |
| Geospatial boundary layer | DESIGNED, NOT BUILT. H3 + borough/taxi-zone join is ticket 07 |
| Financial data "for fun" | DROPPED on purpose. TU alone is ~60K msgs/poll, no load generator needed |
| Added later: Spark + Sedona | ZERO LINES WRITTEN. Java 11 not installed. This is the gap |
| Added later: climate Zarr | PROVEN. AORC read from S3, Ida reproduced at 84.2 mm/h |
| Added later: flood + subway | RESEARCHED, PARKED as a later phase. Correct call, it is a batch/analysis project |

Verdict: rails are real, insight is zero. Today this is a plumbing story. An SE
showcase needs one insight and one visual. See section 3 for the fastest route.

## 2. Budget

**Session spend so far (cost-tracker, estimated): $235.47.**
Opus $128.67, Fable $64.06, Sonnet $42.74. 1.30M output tokens. Three research
fan-outs (30 + 28 + 33 agents) plus two research subagents did that. The research
phase is essentially complete; the build phase is single-agent implementation and
should cost a fraction. Standing orchestration consent drove the number, and it
bought three vault reports and about a dozen refuted assumptions.

**Project run cost: $0.** Local Docker, anonymous public buckets (NOAA NODD, AWS
Open Data, S3 nycbuspositions), no cloud writes. The only paid thing on the horizon
is BigQuery GDELT if the flood phase wants news-derived events (~$13/query
unpartitioned, ~free with partition bounds), and it is not on the map.

**Time to first showcase artifact: 3 to 4 focused days**, not weeks. Reason in
section 3.

## 3. Stream or batch. Answer: both, but batch produces the insight FIRST

The headline question, "does rain slow the buses, and where", is a batch question
over history. The plan implicitly assumed we had to wait weeks for the self-archive
to accumulate rain days. That assumption is wrong:

- `s3.amazonaws.com/nycbuspositions` is dead going forward but fully readable
  backward: daily `YYYY/MM/YYYY-MM-DD-bus-{positions,trip-updates,alerts,messages}.csv.xz`
  from **2017-07-14 through 2024-09**. About 19-20 MB/day compressed. Schema:
  timestamp, trip_id, route_id, trip_start_date, vehicle_id, latitude, longitude,
  bearing, stop_id, stop_status, occupancy_status (populated, e.g. EMPTY on
  2021-09-01), congestion_level (UNKNOWN), plus empty speed/dist columns.
- AORC hourly precip is complete and frozen for the same 2017-2024 window.

So the entire "rain vs bus speed" analysis is available today: 7 years of positions
x 7 years of hourly rain, including Ida (2021-09-01) and the 2023-09-29 flood as
natural experiments. Derive speed from successive pings per vehicle (the archive's
own speed column is empty), aggregate to H3 x hour, join AORC on the same key.

The stream is justified by exactly two things:
1. **The gap and the future.** Nothing archives this feed since 2024-09-06. The
   live capture is the only way the analysis stays current. Every unpolled day is
   gone.
2. **The live product.** "Is my bus late/crowded right now, and is it raining on
   its route" is real-time by nature.

Honesty for the demo: Spark Structured Streaming is micro-batch; at a 30s feed
cadence, "streaming" means continuous incremental processing with checkpointed
recovery, not sub-second latency. Say that plainly, it is the correct architecture
for this source and undersells nothing.

**Order flip:** backfill batch job before the streaming enrich job. Same Sedona
code paths (H3 assignment, boundary join, precip join), so the batch job is also
the proof-of-Sedona for ticket 07. New ticket 10.

## 4. Storage, formats, CRS: the smart-but-not-clever version

Verified facts driving this:
- Sedona 1.9.1 writes GeoParquet 1.1.0 by default with **auto bbox covering**
  (`geoparquet.covering.mode` = `auto` produces `<geom>_bbox`), PROJJSON CRS via
  `geoparquet.crs`, and pushes `ST_BoxIntersects`/`ST_BoxContains` into Parquet
  row-group statistics (GH-2938, 1.9.1). Docs recommend sorting by
  `ST_GeoHash(geom, 5)` before writing so pruning actually skips row groups.
- quakestream, hard-won: DuckDB `ST_Intersects` does NOT prune GeoParquet row
  groups; push literal bbox constants against the bbox struct and confirm with
  `EXPLAIN ANALYZE`. Iceberg V3 geometry is readable+prunable only by Snowflake and
  Databricks; `binary` to `geometry` is not a legal type promotion.
- Sedona master writes Iceberg V3 native geometry (blog 2025-10-21) but there is
  no Iceberg tutorial at the 1.9.1 tag (page 404s at 1.9.1 and latest). Havasu's
  reader/writer is WherobotsDB-only. Treat Sedona-on-Iceberg as "works, thinly
  documented, portability narrow" for now.

**CRS discipline (this is where "reprojection" actually lives):**
- Canonical stored CRS: EPSG:4326 lon/lat (GeoParquet CRS84). MTA GTFS-RT is
  already 4326. AORC is EPSG:4326 (verified in `.zattrs`). MRMS is also geographic
  lat/lon at 0.01 deg, so MRMS to AORC is a **regrid**, not a reprojection.
- NYC city datasets (taxi zones shapefile, building footprints, LiDAR, DEM, LION,
  most DEP layers) are **EPSG:2263** NY Long Island State Plane in US survey
  feet. Reproject ONCE at ingest: `ST_Transform(geom, 'EPSG:2263', 'EPSG:4326')`.
  Trap: axis order. Verify one known point round-trips to (-73.98, 40.76) for Times
  Square, not (40.76, -73.98), before trusting any join.
- Metric math (speed between pings, buffers, areas): never in degrees. Use geodesic
  `ST_DistanceSphere` in 4326, or `ST_Transform` to EPSG:32618 (UTM 18N, metres)
  for area/buffer work. H3 as the aggregation key sidesteps CRS for the heatmap
  entirely.
- Flood phase adds vertical datums (NAVD88 vs Battery STND, 6.06 ft offset).
  Parked with the phase.

**Do the geometry once.** Precompute a static lookup: AORC cell centroid to H3
cell (about 3,500 rows for NYC). After that every precip join is on `(h3, hour)`,
no spatial predicate at query time. Same for taxi zones: one H3-to-zone table.

**Storage tiers:**
- Bronze: what the archiver writes now, hourly zstd Parquet per feed under
  `data/archive/{vp,tu}/date=/hour=`. Fidelity layer. Keep.
- Silver: Sedona-written **GeoParquet 1.1** with bbox covering, sorted by
  H3 (or geohash-5) then time, partitioned by `date=`. Both Sedona
  (`ST_BoxIntersects` pushdown) and DuckDB (bbox-struct literals) prune it.
  Backfill from nycbuspositions lands here too, same schema, so history and live
  are one table.
- Precip: the NYC AORC slice as a long table (`time, h3, mm`), ~3,500 rows/hour,
  ~30M rows/year, plain Parquet by month. Do not store it as raster.
- Gold: `(h3, hour, route)` aggregates, plain Parquet.
- **Iceberg: not now.** Real reason to add it later is compaction: hourly files
  x 2 feeds = 48/day, ~17K/year, a genuine small-files problem within months.
  Second reason is the Wherobots story (Havasu is Iceberg, so OSS-Sedona-on-Iceberg
  is a legit portfolio move). When added: geometry as WKB binary + explicit
  lon/lat/h3/bbox columns (portable everywhere), not V3 native geometry, unless
  the goal is specifically to demo V3. `# ponytail: hourly Parquet files; add
  Iceberg compaction when file count > ~5K or when the lakehouse demo is wanted.`

## 5. Showcase framing that holds up

Two artifacts, one narrative:
1. **Insight (batch, Sedona):** "Rain costs NYC buses X% speed, and here is the map
   of where it hurts most", built from 7 years of positions x 7 years of hourly
   rain, with Ida and 2023-09-29 as case studies. Validated the way the pros do it
   (Ida hour reproduced from Zarr before any modelling).
2. **Engineering (stream, Kafka + Sedona):** the same enrichment running live on
   the feed nobody else archives, with checkpointed recovery, feeding the archive
   that keeps the insight current.

That is a Solutions Engineer story: found signal in a public feed, verified every
assumption against the source, chose boring storage on purpose, and can show both
the answer and the machinery.

## Consequences recorded on the map

- New ticket 09: storage/CRS conventions (recommendation above as starting position).
- New ticket 10: historical backfill from nycbuspositions (moves ahead of 07).
- Ticket 05 (durable archiver) unchanged and still urgent: the gap since 2024-09-06
  is the one part of history no backfill can recover.
