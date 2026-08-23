# 12 — Streaming job: Kafka to live tables with checkpointed recovery

**What to build:** `make stream` runs one Spark Structured Streaming app over both topics, applies the stateless
enrichment (Cell, Zone, latest live precip Hour) inside `foreachBatch`, reduces TU to one row
per trip-vehicle-fetch with the next-stop Prediction and trip delay, appends micro-batches to
`live/vp` and `live/tu`, resumes from its checkpoint after a gap, and writes a progress file
per batch so the page can show the rail. Spec: J; Testing 07-3.

**Blocked by:** 10, 11

**Status:** ready-for-agent

- [ ] one app, one readStream per topic, `foreachBatch` calling with_cell / with_zone / with_live_precip from the enrichment module (never a second implementation), coalesce(1), partitionBy(date, hour) from fetched_at, `awaitAnyTermination`, FAIR scheduler, distinct temp views; trigger 30 s; in-batch dropDuplicates(vehicle_id, ts)
- [ ] with_live_precip reads the live precip table fresh inside the callback, takes max(valid_ts) <= batch time as a scalar and broadcast-joins on cell so every live VP row carries cell, mm_1h, precip_valid_ts; an absent or empty live precip table yields NULLs and never fails the batch
- [ ] recovery: per-query checkpoints, failOnDataLoss=false, maxOffsetsPerTrigger=250000, startingOffsets=latest on a fresh checkpoint only, `FRESH=1` discards the checkpoint; the daily retention hook drops date=/hour= dirs older than 48 h by name
- [ ] `live/_progress.json` is written after each append (batch_id, batch end timestamp, rows)
- [ ] 07-3: the test publishes the fixture-decoded VP/TU rows to a throwaway topic and skips without a broker; `availableNow` from earliest on a throwaway checkpoint drains > 0 rows with cell non-null (mm_1h NULL when no precip table) into date=/hour=; a second run finds nothing new; two processingTime triggers write two files; the progress file exists

## Consumer notes from the ticket-10 session (2026-08-23, recorded by the overview session)

Live flow re-verified post-restart with a real consumer (fresh group, end-1 on all
partitions): vp newest message age 2 s, tu 34 s; 6 partitions each; end offsets
92,553 / 765,229. Daemon pid 69034.

For whoever builds this ticket:
- `spark.topic_schema("vp"/"tu")` is the ready-made StructType for `from_json` — do not
  hand-write one.
- The producer sets `allow.auto.create.topics=False`: on a fresh broker `make topics`
  MUST run before the stream starts (and before the archiver publishes).
- Message keys can be the empty string (`str(r[key] or "")`); values are compact JSON
  with explicit nulls for absent fields.
- `events.py` Bronze TU readers need `mergeSchema` (mixed pre/post-ticket-10 parts);
  the live-topic JSON path has no such issue.

## Prep notes (2026-08-23, ticket-10 session's prep hold; sources: spec J/K, research 07 §0-4, enrich.py, ticket 11's live table)

- **The three stateless functions do not exist yet.** `with_cell` / `with_zone` /
  `with_live_precip` appear nowhere in `src/` — this ticket authors them in `enrich.py`
  (pure `DataFrame -> DataFrame`, DataFrame API only, no temp views, per the module's
  header contract). `events.py:297` computes its cell inline at the *leg midpoint* —
  different grain; write new row-point functions, do not refactor events.
  `with_cell` = `ST_H3CellIDs(ST_Point(lon, lat), 8, false)[0]` (LongType);
  `with_zone` = join `ref/cell_zone` on cell (zone_id, borough).
- **`with_live_precip` join contract** (must match what ticket 11 lands):
  `live/precip_cell/valid_ts=<YYYY-MM-DDTHH>/part-<fetched_at>.parquet`, `valid_ts` a
  STRING partition key, columns cell int64 / mm_1h float / fetched_at int64. The
  `spark.read` goes INSIDE the foreachBatch callback — a hoisted DataFrame freezes its
  file index (measured, research 07 §0). Take `precip_valid_ts = max(valid_ts) <= batch
  time` as a scalar; dedupe latest-fetched_at-wins per (cell, valid_ts) BEFORE the
  broadcast-equi-join on cell. Absent dir, empty dir, or empty table -> NULL
  mm_1h/precip_valid_ts on every row, never a failed batch (guard the read).
- **Recovery-past-retention must be loud** (the design focus). Normal resume replays a
  sleep gap from the checkpoint at bounded pace (`maxOffsetsPerTrigger=250000`; one rush
  TU poll ~62k rows) — that replay IS the checkpointed-recovery demo. But with
  `failOnDataLoss=false`, a stream down longer than Kafka's 48 h retention would
  *silently* skip the trimmed range. Enforce: at startup read `live/_progress.json`'s
  batch-end timestamp; if the gap exceeds 48 h, exit loudly demanding `FRESH=1` and
  naming Bronze as where the gap's rows live (they are not recoverable from Kafka).
  `FRESH=1` deletes the checkpoint dirs -> fresh checkpoint -> `startingOffsets=latest`.
  No `_progress.json` yet (first ever run) -> proceed as fresh.
- **Traps already measured** (research 07 §0): two foreachBatch callbacks collide on a
  shared temp-view name (distinct names or pure DataFrame API); `availableNow` +
  `startingOffsets=latest` on a fresh checkpoint drains 0 rows — a green, vacuous test,
  so 07-3 must use `earliest` on its throwaway checkpoint; `partitionOverwriteMode`
  and TZ are already handled by `spark.session()` — the stream appends, never overwrites.
- **TU reduce**: per-stop rows -> one per (trip_id, vehicle_id, fetched_at); next-stop
  Prediction = the earliest future arrival among that fetch's rows; trip-level delay =
  `trip_delay_s`, on every row since ticket 10 (100% coverage measured on the fixture).
- **`live/_progress.json`**: written after each append — batch_id, batch end timestamp,
  rows; both queries write it, last-writer-wins is fine (it is a liveness rail, spec J).

**Caveat on the prep notes (from their author, signing off 2026-08-23):** they were
written BEFORE ticket 11 landed. Verify the with_live_precip column expectations
(valid_ts string key, cell/mm_1h/fetched_at, latest-fetched_at-wins) against what
60cbc58 actually writes under live/precip_cell — prefer disk over the notes on any
mismatch.
