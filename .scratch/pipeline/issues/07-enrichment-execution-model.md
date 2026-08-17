# 07 Enrichment execution model

Type: grilling
Status: resolved
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

### 2026-08-16 — measured, adversarially reviewed, round posted; awaiting Ross

Measured (`research/07-execution-model.md` section 0): brew `openjdk@17` is already on
this Mac and Spark 3.5.3 + Sedona 1.9.1 stand up natively from a venv on it (Spark 3.5
docs: Java 8/11/17; ticket 03's "Java 11 not 17" corrected) - session 8.9 s warm,
`ST_H3CellIDs` / `ST_DistanceSpheroid` / `ST_Transform` axis gate / GeoParquet 1.1
writer / 102 RS_ functions all correct, 1.93M Bronze pings H3'd in 1.1 s, Kafka
`availableNow` + `foreachBatch` drain and checkpoint resume proven, ~0.7 GB RSS. Sonnet
research pass confirmed the Spark/Kafka/launchd/DuckDB facts against primary docs (one
nuance: Sedona's platform matrix pairs Spark 3.5 with Java 11). Two opus reviews
(streaming/JVM, data/ops) reversed nine parts of the first draft: replace-by-rename
(ENOTEMPTY on APFS, staging siblings read as data) -> `partitionOverwriteMode=dynamic`;
`part-DD` append into a month partition -> decoded MRMS Bronze copy + month rebuild;
`hour=/batch=<batchId>` dirs -> Bronze-identical `date=/hour=` in append mode with
`coalesce(1)`, dedupe at read, 48 h retention; 6 g driver -> 3 g / `local[6]`; `make
daily` builds every missing day (launchd coalesces missed intervals); Pass2-tail NULL
sentence deleted (06:00 ET clears by 27 min); MRMS live fetch out of the archiver's
30 s loop; two callbacks in one session must not share temp views; 08's
`generate_series` spine does not parse on Spark 3.5. Round of four decisions posted in
chat; recommendations are the asset as it stands.

## Answer

Resolved 2026-08-16 by grilling; all four recommendations accepted as-is, plus both
sub-yeses (Docker VM to 4 GB - Ross's setting to change; two scheduled LaunchAgents
beyond 05's archiver agent). The execution model, measurements, review reversals and
checks are the asset [research/07-execution-model.md](../../../research/07-execution-model.md);
this Answer is the index to it.

1. **Runtime: local JVM, one session factory, Kafka the only container.** Spark 3.5.3
   + Sedona 1.9.1 run natively from the repo venv (`pyspark==3.5.3`,
   `apache-sedona==1.9.1`, `setuptools`, `shapely`, `duckdb`, `pytz`) on the brew
   `openjdk@17` already installed (Spark 3.5 docs: Java 8/11/17 - 03's "Java 11 not 17"
   corrected; Sedona's matrix says 11 for Spark 3.5, measured clean on 17, fallback
   `brew install openjdk@11`). `JAVA_HOME` + `TZ=UTC` from Makefile/`.env`. One
   `raincheck/spark.py::session()` holds the three Maven coordinates, Kryo +
   `SedonaKryoRegistrator`, UTC / TIMESTAMP_MICROS, `partitionOverwriteMode=dynamic`,
   `-Duser.timezone=UTC`, `local[6]`, `spark.driver.memory=3g`, shuffle partitions 16,
   UI off. Kafka stays in compose; Ross shrinks the Docker VM to 4 GB; quakestream's
   slim Sedona image is the promotion path only (fog). Measured: session 8.9 s warm,
   ~0.7 GB RSS, ~240 MB Ivy, every ST_/RS_/GeoParquet/Kafka path correct on JDK 17.
2. **One enrichment module, three callers, Spark writes, DuckDB reads.**
   `raincheck/enrich.py` = pure DataFrame-API functions (no temp views, no I/O except
   the `spark.read` inside `with_live_precip`); batch jobs are thin `make` targets
   (`ref`, `schedule`, `events DATE=`, `precip-hourly`, `precip-cell`, `gold`, `daily`)
   idempotent by `mode("overwrite").partitionBy()` under dynamic overwrite (rename-based
   replacement refuted: ENOTEMPTY on APFS, staging siblings read as data); the streaming
   job calls the same stateless functions in `foreachBatch`; passages/delay stay
   batch-only (09). Sedona exactly where a spatial primitive is needed (`ST_H3CellIDs`,
   `ST_H3ToGeom`, `ST_Transform`, `ST_Contains`, `ST_DistanceSpheroid`, GeoParquet 1.1
   writer, one `RS_Values` built in-db via `RS_MakeEmptyRaster`/`RS_AddBandFromArray`);
   `cell_pixel` keeps its Python builder; everything else plain Spark SQL. Spark writes
   every derived table because the destination names Spark + Sedona enrichment and the
   batch job is the Sedona proof (DuckDB-owns-batch is leaner and loses on that axis
   only); DuckDB is the read/analysis engine. `make daily` builds every missing closed
   service_date (launchd coalesces missed calendar runs) plus the current `src=mrms`
   month; 06:00 America/New_York clears Pass2's tail by 27 min.
3. **Streaming contract: no exactly-once, on demand, not a daemon.** One app, two Kafka
   queries, `foreachBatch` appends `coalesce(1)` micro-batches to
   `data/live/<topic>/date=/hour=` (Bronze's layout from `fetched_at`), 48 h retention =
   Kafka's; `awaitAnyTermination()`, FAIR scheduler; per-query checkpoint under
   `data/checkpoints/`, `failOnDataLoss=false`, `maxOffsetsPerTrigger=250000` (a TU poll
   is 62,077 rows), `startingOffsets=latest` on a fresh checkpoint, resume replays a
   sleep gap at bounded pace into true hours (the recovery demo), `make stream FRESH=1`
   discards. Reads are latest-per-key so a replayed batch's duplicates change nothing;
   batchId-keyed dirs, Spark's file sink, Kafka output topic, transactional sinks,
   stream-stream joins, watermarks all not paid for. Trigger 30 s; VP and TU are two
   thin tables joined at read (TU's trip-level delay waits on 05's decoder change).
   `make stream` runs foreground on demand and depends on `make produce`; single-poller
   topology is spec's. Test: `availableNow` + `startingOffsets=earliest` on a throwaway
   checkpoint, rows > 0, `cell` non-null.
4. **Live precip and `src=mrms` cadence (yes given for two scheduled agents).**
   `raincheck.precip_live` on a `StartInterval` 300 s LaunchAgent (runs seconds:
   RadarOnly `:00` -> Cell means via `cell_pixel[mrms]` -> `live/precip_cell/valid_ts=
   <YYYY-MM-DDTHH>/part-<fetched_at>.parquet`, string key, latest-wins, 7 d retention);
   the stream joins it as the scalar latest complete Hour <= batch time, `spark.read`
   inside the callback (a hoisted DataFrame freezes its file index). Pass2 daily into a
   decoded Bronze copy `data/archive/precip/mrms/date=/hour=HH.parquet` (~1.2 MB/day)
   and `silver/precip_hourly/src=mrms/month=` rebuilt from it as one file (09's rule
   holds; the `part-DD` append was refuted); `precip-cell SRC=mrms` rebuilds the month;
   both in `make daily`, `DATE=` ranges backfill from 2026-08-14. Not inside the
   archiver's 30 s loop (a CONUS decode would stall VP capture). `make daily` gets a
   06:00 America/New_York `StartCalendarInterval` LaunchAgent as a build item.

Consequences: 10 unblocked on engine (comment left: Spark, `events DATE=`, in-db raster
for Product 3); comments on 03 (Java 17; 102 RS_ functions incl. in-db constructors),
05 (two more scheduled agents approved; single-poller to spec), 08 (`generate_series`
is not a Spark 3.5 TVF - spine is `explode(sequence())`; asset note corrected in place),
09 (`data/live/` root and the MRMS Bronze copy added to the Roots line). CONTEXT.md gains
**Live table**. Fog "Serving/visualization" graduates to ticket 14 (blocked by 10). Build
items for `/to-spec` in asset section 6; Ross's own item: Docker Desktop memory -> 4 GB.
Python traps for the build: `setuptools` (pyspark 3.5 pandas bridge on 3.12), `TZ=UTC`
(collect() returns driver-local datetimes), `pytz` for DuckDB tz-aware reads.

2026-08-16, from [10 Backfill slice and speed-derivation rules](10-backfill-slice-and-speed-rules.md): `enrich.legs()` (pure
function, section 2 rules) is called by `events DATE=D` on its Bronze read `date IN (D,
D+1)` and aggregated to Silver `leg_hours (service_date=)`; `gold MONTH=` rolls it up to
Gold `cell_hour_speed (month=)`, reading service_date month_start-1..month_end and
keeping the month's Hours before the write (your neighbouring-partition check extends
to this job); the converter is `make nbp DATE=` (pyarrow, one xz file, schema from
`archiver.TYPES`, idempotent by part name); `events DATE=` writes `pick_gap = true` rows
rather than aborting; the 10 GB budget covers `data/archive/` only (asset section 3
says all of `data/`); `RAINCHECK_ARCHIVE_ROOT` is a build item.
