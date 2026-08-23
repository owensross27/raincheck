# 12 — Streaming job: Kafka to live tables with checkpointed recovery

**What to build:** `make stream` runs one Spark Structured Streaming app over both topics, applies the stateless
enrichment (Cell, Zone, latest live precip Hour) inside `foreachBatch`, reduces TU to one row
per trip-vehicle-fetch with the next-stop Prediction and trip delay, appends micro-batches to
`live/vp` and `live/tu`, resumes from its checkpoint after a gap, and writes a progress file
per batch so the page can show the rail. Spec: J; Testing 07-3.

**Blocked by:** 10, 11

**Status:** resolved (2026-08-23) - **ticket 14 unblocked**: `make stream` runs, live/vp + live/tu populated and verified

- [x] one app, one readStream per topic, `foreachBatch` calling with_cell / with_zone / with_live_precip from the enrichment module (never a second implementation), coalesce(1), partitionBy(date, hour) from fetched_at, `awaitAnyTermination`, FAIR scheduler, distinct temp views; trigger 30 s; in-batch dropDuplicates(vehicle_id, ts)
- [x] with_live_precip reads the live precip table fresh inside the callback, takes max(valid_ts) <= batch time as a scalar and broadcast-joins on cell so every live VP row carries cell, mm_1h, precip_valid_ts; an absent or empty live precip table yields NULLs and never fails the batch
- [x] recovery: per-query checkpoints, failOnDataLoss=false, maxOffsetsPerTrigger=250000, startingOffsets=latest on a fresh checkpoint only, `FRESH=1` discards the checkpoint; the daily retention hook drops date=/hour= dirs older than 48 h by name
- [x] `live/_progress.json` is written after each append (batch_id, batch end timestamp, rows)
- [x] 07-3: the test publishes the fixture-decoded VP/TU rows to a throwaway topic and skips without a broker; `availableNow` from earliest on a throwaway checkpoint drains > 0 rows with cell non-null (mm_1h NULL when no precip table) into date=/hour=; a second run finds nothing new; two processingTime triggers write two files; the progress file exists

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

## Answer (2026-08-23)

`src/raincheck/stream.py` (`make stream`, on demand and foreground), three new pure functions in
`enrich.py`, one config line in `spark.py` (`spark.scheduler.mode=FAIR` - spec J requires it and
Spark reads it at SparkContext start, so the session factory is the only place it can live;
harmless for the batch jobs, which run one job at a time). `tests/test_stream.py` = 25 tests.
Nothing else touched: no `precip*`, no archiver/feeds/topics.

**Verified live**, not only under pytest (real broker, real data root, archiver publishing):
4,344 VP rows into `live/vp/date=/hour=` with 100% `cell`, 4,193 zoned (the rest are Cells in no
taxi zone, as `ref/cell_zone` stores them) and every row carrying `mm_1h` + `precip_valid_ts` from
ticket 11's `live/precip_cell` at the latest complete Hour; 2,651 `live/tu` rows, grain
(trip_id, vehicle_id, fetched_at) unique, 2,533 with a next-stop Prediction, 100% `trip_delay_s`.

**The checkpointed-recovery demo, measured:** killed the job at 13:53:56Z, restarted ~2.5 min
later. It resumed at `batch_id` 4 (not 0) and replayed every archiver poll in the gap - 13:54:26,
13:54:56, 13:55:26, 13:55:56 all present, no missing poll instant - then continued live.

**The loud rule, measured on the real path:** with a 51 h-old rail it exits 1 naming Bronze and
demanding `FRESH=1`, and leaves the checkpoints untouched.

Two design calls this ticket had to make, because the ticket text did not pin them:

1. **The TU "future" clock is the feed's own snapshot (`header_ts`, falling back to `fetched_at`),
   not our wall clock.** A post-sleep replay must judge a message's predictions in the era it was
   published. Measured on the 2026-08-11 fixture: against `header_ts`, 76 of 1,988 trips have no
   live Prediction and 344 pick a row other than the first stop row - against `fetched_at` at
   replay time the whole fixture scores zero Predictions and the test passes vacuously. (Against
   `trip_ts` the rule degenerates to "the first row" - MTA orders stop_time_updates from the next
   stop relative to that clock - so it would pin nothing either.)
2. **`live/tu` columns:** trip_id, vehicle_id, route_id, start_date, direction_id, trip_delay_s,
   trip_ts, header_ts, fetched_at, next_stop_id, next_stop_sequence, next_arrival_time. A trip
   whose every prediction has gone stale keeps its row with NULL `next_*`: the trip is alive, only
   the Prediction is not. For ticket 14.

`prune(root, now=None)` is the 48 h retention hook; it runs at stream start and ticket 15's
`make daily` should call it (`from raincheck.stream import prune`).

Measured behaviour worth knowing: `dropDuplicates(vehicle_id, ts)` is *in-batch*, so a big replay
batch (several polls at once) collapses a bus that republished a stale `ts` across polls, while
steady state (one poll per batch) does not. That is the specified Ping identity and the readers
take latest-per-key, but it means `live/vp` row counts are batch-boundary dependent - Bronze
stays the record.

Adversarial review (five opus lenses -> per-finding refutation -> completeness critic, 25 agents):
~20 findings filed, 2 survived refutation and the critic added 4. All six were real and all six
are fixed. Notably **none were production-logic bugs; four were tests that were green for the
wrong reason**, which is this project's recurring failure mode:
- the drain's partition assertion could not tell `fetched_at` from wall clock (the fixture stamps
  `fetched_at` at decode time, so they are equal) - added a direct `append` test at a fixed 2026-08-11
  epoch; mutation-checked against `F.current_timestamp()`;
- the malformed-message test never reached the `fetched_at IS NOT NULL` source filter (both junk
  messages made the batch empty, so the empty-tick guard short-circuited first) - the junk now
  shares its batch with a valid row, and a `date=__HIVE_DEFAULT_PARTITION__` dir would be one
  `prune` could never sweep (it sorts above every real date);
- `dropDuplicates` was a no-op in every test (the fixture has no duplicate (vehicle_id, ts) pair) -
  the throwaway topic now carries the fixture twice and the drain asserts `n == 1190` exactly,
  which pins the dedupe and that neither broadcast join fans a row out;
- nothing tested that the precip `spark.read` is *inside* the callback - one call cannot tell a
  fresh read from a frozen file index, so the test now calls it twice around a write.
The two real code changes: `resume_guard` now also stops when a checkpoint exists with no rail
beside it (`rm -rf <root>/live` leaves `checkpoints/` standing - the gap is then unbounded, which
is the same danger the guard exists for) and `FRESH=1` drops the rail it just invalidated; and
`FRESH` is parsed as exactly `"1"`, so `make stream FRESH=0` no longer destroys the checkpoints.

Full suite 193 passed (168 baseline + 25). Side effects on the laptop: `data/live/vp`,
`data/live/tu` and `data/checkpoints/live_{vp,tu}` now exist with a few minutes of real capture.
No daemon left running - `make stream` is on-demand foreground by design (research 07 section 3).
