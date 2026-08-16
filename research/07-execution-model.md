# 07 Enrichment execution model

Asset of ticket [07 Enrichment execution model](../.scratch/pipeline/issues/07-enrichment-execution-model.md).
Draft 2026-08-16, measured and adversarially reviewed (two opus lenses: streaming/JVM,
data/ops; a sonnet pass against primary docs), awaiting the human round. Inherits 04
(topics/keys, H3 res 8), 05 (archiver LaunchAgent, Bronze), 06 (passage/delay rules),
08 (precip spec, live table handed here), 09 (schemas, batch-rebuilt Silver, session
settings), 03 (stream-static join, no Zarr in Sedona).

## 0. Facts the decisions stand on (measured 2026-08-16 on this Mac)

- **A JDK is already here.** `brew list` has `openjdk@17` (17.0.20, keg-only, so
  `/usr/bin/java` does not see it). Ticket 03's "Java 11 not 17" is wrong for Spark:
  the 3.5.3 docs say "Spark runs on Java 8/11/17" and PySpark's launcher adds the JDK 17
  `--add-opens` module options itself (`JavaModuleOptions`, since 3.3; 15 of them seen
  in the JVM cmdline). Sedona 1.9.1's own platform page pairs "Spark 3.4 & 3.5: Java
  11" and "binary releases are compiled by Java 11/17"; on 17 here every ST_/RS_
  function, the GeoParquet writer and the Kafka source ran clean, and quakestream ran
  the same pins on `eclipse-temurin:17-jre`. Fallback if a Sedona op ever misbehaves:
  `brew install openjdk@11` and flip `JAVA_HOME` - nothing else changes.
- **Spark 3.5.3 + Sedona 1.9.1 stand up natively, no container**, from a plain venv
  (`pyspark==3.5.3`, `apache-sedona==1.9.1`) with `JAVA_HOME=/opt/homebrew/opt/openjdk@17`
  and three Maven coordinates on `spark.jars.packages`
  (`sedona-spark-shaded-3.5_2.12:1.9.1`, `geotools-wrapper:1.9.1-33.5`,
  `spark-sql-kafka-0-10_2.12:3.5.3`). First start 56.6 s (Maven downloads: ~240 MB
  into `~/.ivy2`, jars + Ivy's second copy; the cache is shared with quakestream's
  962 MB), every later start 8.9 s; driver RSS 0.56-0.71 GB on a `local[4]` / 3 g
  session. `ST_H3CellIDs(ST_Point(-73.965, 40.782), 8, false)[0]` = `882a100895fffff`
  (Central Park's Cell, matches 08; type LongType = 09's INT64),
  `ST_DistanceSpheroid` Central Park -> Times Square 3,177.8 m, `ST_Transform(EPSG:2263
  -> 4326)` of Times Square = (-73.98550, 40.75800): 09's axis gate passes on this
  stack. GeoParquet writer emits version 1.1.0, no `crs` key, bbox covering on by
  default (09 confirmed). `SedonaKryoRegistrator` class present in the 1.9.1 shaded jar.
  102 `RS_` functions including `RS_MakeEmptyRaster` / `RS_AddBandFromArray` /
  `RS_MakeRaster` / `RS_Values` / `RS_ZonalStats`: 10's Product 3 raster can be built
  in-db from the AORC slice, no GeoTIFF round trip (03's "constructors are
  RS_FromGeoTiff / RS_FromNetCDF only" is incomplete; comment for 03).
- **Two Python-side traps found by review, both one line**: (a) the repo venv is Python
  3.12 and pyspark 3.5.3's pandas bridge imports `distutils` -> `createDataFrame(pandas)`
  / `toPandas()` die unless `setuptools` is installed (03's xarray -> pandas -> Spark
  bridge is exactly that path); (b) `import sedona.spark` hard-imports pandas.
  (c) The JVM default TZ is America/New_York even with `spark.sql.session.timeZone=UTC`,
  so PySpark `collect()` hands back driver-local naive datetimes (20:00Z reads as
  16:00): set `TZ=UTC` next to `JAVA_HOME` and assert on `date_format` strings.
- **Bronze reads and H3 at laptop scale are trivial**: 1.93M archived VP pings (~9 h of
  capture over 31 h wall clock; 05's sleep gap) read + counted in 0.4 s; `ST_H3CellIDs`
  over all of them, grouped, 1.1 s. A rush TU poll is 62,077 rows (measured over 266
  polls), a VP poll ~2,017.
- **The streaming rail works on the local JVM**: `readStream.format("kafka")` on
  `raincheck.bus.vp` with `trigger(availableNow=True)` + `foreachBatch` drained the
  1,822 messages on the topic in 2.8 s and stopped; the second run against the same
  checkpoint found nothing new (0.2 s). `spark.driver.memory` set on the builder does
  reach the JVM (`-Xmx` in the cmdline). Measured traps: a DataFrame built once from a
  path keeps its file index, so a `spark.read` hoisted out of the callback freezes the
  static side (held df 3 rows vs fresh read 13); two `foreachBatch` callbacks in one
  session collide on a shared temp-view name (VP thread read TU rows); Spark's default
  `partitionOverwriteMode=static` deletes the whole table on a partitioned overwrite;
  `os.rename` over a non-empty dir is ENOTEMPTY on APFS; `availableNow` +
  `startingOffsets=latest` on a fresh checkpoint drains 0 rows (a green, vacuous test).
- **08's build SQL does not parse on Spark 3.5 as written**: `generate_series` is not a
  Spark table-valued function (`explode(sequence(...))` is); `FILTER (WHERE)`, `INTERVAL
  24 HOUR` and the inline window specs are fine. So the spine is two texts, one per
  engine; comment for 08.
- **Machine**: 16 GiB, 10 cores (M4); Docker Desktop's VM claims 8.2 GB and all 10
  vCPUs, Kafka its only tenant; swap 95% used before any Spark; internal SSD ~14 GiB
  free and falling (05's Bronze budget presses on it). Kafka today: `raincheck.bus.vp` /
  `.tu`, one partition each (04's six-partition/zstd creation is a build item), 48 h
  retention.
- Rules of the road below: local-only, no cloud writes, no new standing process without
  a HITL yes (map Notes); Spark and DuckDB sessions both UTC / TIMESTAMP_MICROS (09);
  DuckDB 1.5.5 reads Spark's output through `**/*.parquet` or the dataset root (the
  `_SUCCESS`/`.crc` sidecars are harmless there; only `**/*` breaks) and needs `pytz`
  for tz-aware timestamps.

## 1. Runtime: local JVM, one session factory, Kafka stays the only container

- Spark and Sedona run **in-process from the repo venv** on the brew JDK 17;
  `pyproject.toml` gains `pyspark==3.5.3` (exact pin, per 03), `apache-sedona==1.9.1`,
  `setuptools`, `shapely`, `duckdb`, `pytz`; `JAVA_HOME` and `TZ=UTC` come from the
  Makefile / `.env`, never `brew link`.
- **One `SparkSession` factory** (`raincheck/spark.py::session()`), the only place these
  are written: the three coordinates; Kryo + `SedonaKryoRegistrator`; 09's
  `spark.sql.session.timeZone=UTC`, `outputTimestampType=TIMESTAMP_MICROS`;
  `spark.sql.sources.partitionOverwriteMode=dynamic` (the idempotence mechanism,
  section 2); `spark.driver.extraJavaOptions=-Duser.timezone=UTC`; `local[6]`;
  `spark.driver.memory=3g` (every workload here fit under 0.7 GB RSS; 6 g + the 8.2 GB
  VM would not fit in 16 GiB); `spark.sql.shuffle.partitions=16`;
  `spark.ui.enabled=false` (`--ui` to turn on; also what lets pytest run without port
  fights). Batch jobs, the streaming job and pytest all call it.
- **Kafka stays the one container** (compose as today). Optional, Ross's call: shrink
  the Docker VM to 4 GB in Docker Desktop settings, since Kafka is its only tenant. No
  Sedona image locally: the slim `~/quakestream/stack/docker/sedona.Dockerfile`
  (Temurin 17 JRE, same three pins, jars baked) is the **promotion path** for the
  always-on box / EKS in the fog. Rejected: Spark inside Docker Desktop - the VM is
  8.2 GB total with Kafka in it, so a Spark heap cannot coexist there, and there is a
  2 GB image to maintain for zero local benefit (VirtioFS is fine; the RAM is the
  reason).
- Ivy cache is warmed once (`make warm`, or the first job); tests skip Spark cases when
  no JVM is found rather than fail. Disk: 05's 10 GB loud-stop byte budget covers all of
  `data/` (Bronze, live, Silver), not Bronze alone; the external SSD is the real fix.

## 2. One enrichment module, three callers, idempotence by partition overwrite

- **`raincheck/enrich.py`: pure functions `DataFrame -> DataFrame`, DataFrame API only
  (`F.expr("ST_H3CellIDs(...)")`, no temp views), no I/O except the one `spark.read`
  inside `with_live_precip` (must stay inside the callback, section 4).** Stateless
  per-row functions shared by batch and stream: `with_cell` (Cell of a point),
  `with_zone` (join `ref/cell_zone`), `with_live_precip`. Batch-only, because they need
  the whole service day (09): `passages` (06's VP flip + envelope + interpolation),
  `with_delay` (dated Pick), `with_segments`, `with_headways`, `precip_cell_hourly`
  (08's SQL with the Spark spine), Gold aggregates. The Kafka JSON schema is one
  `StructType` per topic derived from `feeds.py`'s dict shapes (04: those ARE the
  schema), asserted equal to `decode_vp`/`decode_tu` output keys by 05's census test.
- **Batch jobs are thin entrypoints over those functions**, one Makefile target each,
  **idempotent by `df.write.mode("overwrite").partitionBy(...)` under
  `partitionOverwriteMode=dynamic`**: Spark replaces exactly the partitions the job
  wrote and leaves siblings intact (measured 0.2 s; the rename scheme in the first
  draft is refuted - `rename` over a non-empty dir fails on APFS and a leftover
  staging sibling is read as data). Any staging dir lives outside the dataset root
  (`data/.staging/`). Targets: `ref` (grids, cells, zones, cell_zone, cell_pixel,
  picks), `schedule PICK=`, `events DATE=` (one closed service_date from Bronze),
  `precip-hourly SRC= MONTH=`, `precip-cell SRC= MONTH=`, `gold MONTH=`. Months and
  days build in any order (08's 24 h lookback reads the input table). Backfill (10) is
  `events DATE=` fed by the archive loader, same function, same table.
- **`make daily` builds every missing closed service_date**, not "yesterday": it
  lists `service_date=` partitions under `silver/events` against the dates present in
  Bronze (bounded, last 14 days) and builds each gap, then runs `precip-hourly` /
  `precip-cell` for `src=mrms` on the current month. launchd's `StartCalendarInterval`
  replays a run missed during sleep but coalesces several missed intervals into one
  event (man page verbatim; power-off/logout are not covered), so the job's unit of
  work has to be "all gaps" for the schedule to be irrelevant. On demand now; a
  06:00 America/New_York calendar agent is a build item (10:00Z clears Pass2's 09:33Z
  tail for the last service-day hour by 27 min in both DST regimes - the reason for
  06:00 rather than 05:00).
- **The streaming job (`make stream`) is the third caller of the same functions**,
  never a second implementation: one Spark app, one Kafka `readStream` per topic,
  `foreachBatch` on each calling `with_cell` / `with_zone` / `with_live_precip` and
  appending its micro-batch, `coalesce(1)`, `partitionBy(date, hour)` from the row's
  `fetched_at` (Bronze's exact layout), to `data/live/<topic>/date=YYYY-MM-DD/hour=HH/`.
  `awaitAnyTermination()` so a dead query surfaces (quakestream's
  `q1.awaitTermination(); q2.awaitTermination()` hides q2's death);
  `spark.scheduler.mode=FAIR` so a 62K-row TU batch does not starve VP. It never
  writes Silver (09) and never computes passages or delay: the live tables are the raw
  rows plus stateless enrichment. On the TU stream the batch reduces per-stop rows to
  one row per (trip_id, vehicle_id, fetched_at) with the next-stop prediction; the
  feed's trip-level `trip_update.delay` joins that row **once 05's census-complete
  decoder lands** (today's `decode_tu` drops it - the TU live table is blocked on
  that build item). VP and TU stay two tables **joined at read** (latest per vehicle /
  trip) - no stream-stream join, no state store, no watermark. `make stream` depends on
  the producer running (`make produce`); until spec settles topology (05 deferred it),
  the archiver and the producer both poll VP every 30 s - the single-poller (archiver
  publishing to Kafka as a side effect) is the recommended spec shape.
- **Spark writes the derived tables; DuckDB never writes one.** Not a "one writer"
  purity claim (the ref layer has a Python builder for `cell_pixel`, the live precip
  table has a numpy writer): the reason is the map's destination, which names Spark +
  Sedona as the enrichment engine, and the reality check's framing, which needs the
  batch job to be the Sedona proof. DuckDB-owns-batch is genuinely leaner (single-node
  sizes, no JVM, no 9 s starts, `COPY ... PARTITION_BY ... OVERWRITE`; 08's SQL is in its
  dialect) and loses on that one axis only. DuckDB is the read/analysis engine (Gold
  queries, notebooks, test assertions on written Parquet - 09 already assumed it) and
  the reader every layout must stay honest to.

## 3. Sedona vs plain Spark; recovery guarantees worth paying for

- **Sedona is on the path exactly where a spatial primitive is needed**:
  `ST_H3CellIDs` (Cell of a stop per Pick, Cell of a ping in the live tables;
  `ST_H3ToGeom` for `cells.geometry`), `ST_Transform` for the EPSG:2263 layers,
  `ST_Contains` for `cell_zone`, `ST_DistanceSpheroid` for `shape_dist_m` along
  `shapes` and any distance feeding a speed, the GeoParquet 1.1 writer for `cells` /
  `zones` / `stops` / `shapes`, and `RS_Values` **once** (10's Product 3, raster built
  in-db from the AORC slice via `RS_MakeEmptyRaster` + `RS_AddBandFromArray`).
  Everything else - passages, delay, segments, headways, 08's weighting and windows,
  Gold - is plain Spark SQL window functions; no pandas UDFs unless SQL proves unable
  (`# ponytail: interpolation by shape distance is SQL first; pandas UDF only if it
  cannot be expressed`).
- **`cell_pixel` keeps its Python builder** (shapely + pyproj, written and verified
  under 08: sum(weight) = 1 in 4,113/4,113 Cells). A Sedona port is optional polish,
  not on the route.
- **Recovery, paid for**: Kafka offsets in the per-query checkpoint
  (`data/checkpoints/<query>/`, local disk); `failOnDataLoss=false` (retention 48 h and
  the Mac sleeps - a gap must not kill the query; Spark logs the skip);
  `maxOffsetsPerTrigger=250000` (must exceed one TU poll, 62,077, several times over; it
  exists for the post-wake backlog, not steady state); `startingOffsets=latest` on a
  fresh checkpoint only - resume always continues from the checkpoint, so after a
  long sleep `make stream` replays the gap into the live tables at bounded pace (a
  13 h gap: ~13 VP batches, ~100 TU batches, ~10-15 min) - that replay *is* the
  checkpointed-recovery demo, and the rows land in their true `date=/hour=`; `make
  stream FRESH=1` discards the checkpoint when the gap exceeds the live horizon; the
  streaming test uses `trigger(availableNow=True)` with `startingOffsets=earliest`
  and a throwaway checkpoint (drain, stop, assert rows > 0 and `cell` non-null; a
  second run finds nothing new; two consecutive `processingTime` triggers write two
  distinct files).
- **Not paid for**: exactly-once on the live tables. `foreachBatch` is at-least-once;
  a crash-replayed micro-batch appends the same rows twice, and the reader already
  takes latest-per-key with `QUALIFY row_number() OVER (PARTITION BY vehicle_id ORDER BY
  ts DESC) = 1` (DuckDB) - exact duplicates change nothing, so batchId-keyed dirs (which
  also break when a fresh checkpoint restarts batchId at 0) buy nothing. Also not paid
  for: a Kafka output topic (`raincheck.bus.enriched` is one `writeStream.format("kafka")`
  line when a consumer exists; Parquet is the sink); Kafka transactional sinks; Spark's
  file sink with its `_spark_metadata` log (only Spark reads that directory correctly);
  Iceberg/Delta (09 deferred); stream-stream joins, watermarks, continuous processing;
  a Spark history server.
- **Trigger** `processingTime='30 seconds'` (the feed cadence, 05); in-batch
  `dropDuplicates(vehicle_id, ts)` is cheap. **Live retention 48 h** = Kafka's, so the
  live tables' horizon equals the source's: the daily job drops `date=/hour=` dirs older
  than 48 h by name; with `coalesce(1)` that is ~2,880 files/day/table (measured: 10 part
  files per batch without it, 2.7x the bytes; per-hour compaction is the upgrade if TU
  files get fat). DuckDB over 28.8K such files still answers in ~1.3 s, so read speed is
  not the constraint; inodes and disk are. Checkpoint rule from the Spark guide: sink or
  source changes need a new checkpoint dir; adding columns does not.
- **Run mode: on demand, foreground, not a daemon.** `make stream` runs while Ross
  wants the live product on screen; Ctrl-C stops it; the checkpoint resumes it. 05's
  LaunchAgent yes covers the archiver only; a permanent JVM on a 16 GiB laptop that is
  already swapping buys nothing while capture is opportunistic. Revisit with the
  always-on box.

## 4. The live precip table and the src=mrms cadence (handed here by 08)

- **`data/live/precip_cell/valid_ts=YYYY-MM-DDTHH/part-<fetched_at>.parquet`**
  (string partition key - Spark writes a timestamp key as `2026-08-16 20%3A00%3A00`,
  which DuckDB reads back as VARCHAR), columns (cell, mm_1h, fetched_at):
  `RadarOnly_QPE_01H` at its :00 stamps only, Cell mean through
  `cell_pixel[grid_id='mrms']` (numpy dot with the crosswalk; 4,868 -> 4,113, no
  Spark), any negative -> NULL, 08's weight guard. Append-only, latest `fetched_at` wins
  per (cell, valid_ts) at read; **retention 7 days**, the writer drops older
  `valid_ts=` dirs.
- **Written by a small periodic job, not inside the archiver's poll loop**:
  `python -m raincheck.precip_live` on a `StartInterval` LaunchAgent every 300 s
  (runs for seconds: one HEAD/GET at ~:05-:10 past the hour, one CONUS decode ~1-3 s,
  exits). Review refuted the first draft's "fourth kind inside the archiver": the
  archiver loop is single-threaded and self-clocking on a 30 s budget (`archiver.py`
  line 64), so a GRIB2 decode of 24.5M points inside it stalls VP capture and misses
  Snapshots - the one thing capture exists to prevent - and it would give the capture
  daemon a build-order dependency on `ref/cell_pixel` plus a *deleting* retention
  policy inside a process whose rule is "Bronze is never auto-deleted" (05). A second
  LaunchAgent is a standing background thing and needs Ross's yes (round, decision 4);
  the no-yes fallback is a `threading.Thread` with its own clock inside the archiver
  process. Rejected either way: the streaming job fetching HTTP inside foreachBatch.
- **The stream joins it as the latest complete Hour, scalar form**: `with_live_precip`
  reads the table fresh every micro-batch (the `spark.read` is inside the callback -
  a hoisted DataFrame keeps its file index and freezes, measured), takes
  `precip_valid_ts = max(valid_ts) <= batch time` as a scalar, and broadcast-equi-joins
  on `cell` (measured 1.1 s over a 7-day, 1.38M-row table vs 1.8 s for the range-join
  form; Spark 3.5 rejects the `LATERAL ... LIMIT 1` form). Every row in a batch carries
  the same `precip_valid_ts`, which is what "the latest complete Hour" means; a ping at
  20:40 carries the 19:00-20:00 Hour and the reader sees the age. Never joined to the
  batch features (08's rule; RadarOnly is the fast, uncalibrated product).
- **Pass2 lands in Bronze first, then the month partition is rebuilt from it**:
  `precip-hourly SRC=mrms` fetches each new hourly Pass2 file (24 GETs/day) into
  `data/archive/precip/mrms/date=YYYY-MM-DD/hour=HH.parquet` (NYC footprint only,
  float32, ~1.2 MB/day, ~35 MB/yr; 08 forbade archiving GRIB2 *bytes*, not a decoded
  Bronze copy) and then **rebuilds `silver/precip_hourly/src=mrms/month=` from Bronze as
  one file** - 09's one-file-per-partition, partition-immutable rule holds, the same
  overwrite idempotence as every other job, and a crash mid-write cannot poison a
  month (the first draft's `part-DD` append could: a footerless part makes the whole
  partition unreadable, and overlapping appends double `mm_1h` with no test to catch
  it). `precip-cell SRC=mrms MONTH=` then rebuilds the month (08's SQL; ~3M rows,
  seconds). Both chained in `make daily`; the same job with `DATE=` ranges backfills
  `src=mrms` from 2026-08-14 (08 §2). A uniqueness assertion on `precip_hourly`'s grain
  (src, i, j, hour_end_utc) per built partition is added to the checks (09 declares it,
  nothing asserted it).

## 5. Checks (one runnable check per slice)

1. Session: `session()` starts, `ST_H3CellIDs(ST_Point(-73.965, 40.782), 8, false)[0]` =
   `882a100895fffff`, 09's Times Square axis gate passes, and
   `spark.createDataFrame(pandas.DataFrame(...))` round-trips (the setuptools trap).
   Session-scoped pytest fixture: forced (one JVM per process), ~9 s, `ui` off.
2. Batch idempotence: `events DATE=` twice yields the same row count and the same
   (trip_id, stop_sequence, vehicle_id) set (determinism), and a neighbouring
   `service_date=` partition is untouched (dynamic overwrite); a stray dir under
   `data/.staging/` changes no read.
3. Stream: `availableNow` with `startingOffsets=earliest` on a throwaway checkpoint
   drains > 0 rows with `cell` non-null into `date=/hour=`; a second run finds nothing
   new; two `processingTime` triggers write two files.
4. Live precip: the file stamped H produces `valid_ts=<H as string>`; latest-wins read
   returns one row per (cell, valid_ts) after a re-fetch; `with_live_precip` on a ping
   at 20:40 attaches `precip_valid_ts` 20:00 by `date_format` string, and an Hour
   written *after* the query starts is seen by the next micro-batch.
5. Precip tables: `precip_hourly` unique on (src, i, j, hour_end_utc) per partition;
   08's tests 3-4 (Pixel min/max envelope, constant field = 1.0, Ida fixture 84.28 at
   Central Park) are 08's and run against Spark's output; the Spark-vs-DuckDB run of
   the two spine texts is a one-off evidence script next to 08's evidence, not a job
   step (agreement between engines is weaker than the absolute Ida fixture).
6. Schema: the two Kafka `StructType`s equal `decode_vp` / `decode_tu` output keys (05's
   census test, extended).

## 6. Handed on / comments to leave

- 08: `generate_series` is not a Spark 3.5 TVF - the dense spine is
  `explode(sequence(:start, :end, INTERVAL 1 HOUR))` on Spark; the rest of section 5's
  SQL parses. 03: 102 RS_ functions in 1.9.1 including in-db constructors
  (`RS_MakeEmptyRaster`, `RS_AddBandFromArray`, `RS_MakeRaster`); Java 17 runs Spark 3.5
  + Sedona 1.9.1 (Sedona's matrix says 11 for Spark 3.5; measured fine on 17). 09: live
  tables under `data/live/` as a fourth root, `data/archive/precip/mrms/` Bronze copy.
- 10: engine is Spark; the backfill loader lands rows via `events DATE=`; `RS_Values`
  Product 3 raster is built in-db from the AORC slice.
- `/to-spec` build items: pyproject pins (+ setuptools, pytz) + `JAVA_HOME`/`TZ`
  wiring, `spark.py` session factory, `enrich.py`, job entrypoints + Makefile (`warm`,
  `ref`, `schedule`, `events`, `precip-hourly`, `precip-cell`, `gold`, `daily`, `stream`,
  `produce`), six-partition/zstd topic creation (04), live tables + checkpoints layout +
  48 h retention, `precip_live` job + its LaunchAgent plist, `make daily` calendar
  plist, `data/` byte budget, checks 1-6.
- Fog unchanged: always-on box + object storage (the daemonized stream and the Sedona
  image live there); a Kafka output topic when a consumer exists; single-poller
  topology is spec's.
