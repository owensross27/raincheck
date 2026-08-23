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
