"""`make stream` (ticket 12 / spec J): Kafka -> the live tables, one Spark app.

One session, one `readStream` per bus topic, `foreachBatch` on each. VP batches get the
stateless row-point enrichment from `enrich` (Cell, Zone, the latest live precip Hour) and
nothing else; TU batches are reduced from per-stop rows to one row per
(trip_id, vehicle_id, fetched_at) carrying the next-stop Prediction and the feed's own
trip-level delay. Both append their micro-batch, `coalesce(1)`, to

    <root>/live/<vp|tu>/date=YYYY-MM-DD/hour=HH/     (from the row's own fetched_at, UTC)

and tick `<root>/live/_progress.json` after each append so the page can tell a dead stream
from a dead exporter. VP and TU stay two tables joined at read (latest per key): no
stream-stream join, no state store, no watermark. `foreachBatch` is at-least-once and the
readers take latest-per-key, so a replayed batch's exact duplicates change nothing.

Recovery (research 07 section 3): per-query checkpoints under `<root>/checkpoints/live_<kind>/`;
`failOnDataLoss=false` so a sleep gap does not kill the query; `maxOffsetsPerTrigger`
bounds the post-wake replay (one rush TU poll is ~62k rows); `startingOffsets=latest`
applies to a fresh checkpoint only, so a resume replays the gap into its true date=/hour=.
Past Kafka's 48 h retention that replay would *silently* skip the trimmed range, so
`resume_guard` stops the job and demands `FRESH=1` instead - the gap's rows are in Bronze,
which is the record.

Run mode: on demand, foreground, not a daemon (research 07 section 3). Ctrl-C stops it; the checkpoint
resumes it.

    make stream            resume from the checkpoint (or start at latest when there is none)
    make stream FRESH=1    discard the checkpoints and start at latest
"""
import json
import os
import shutil
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pyspark.sql import DataFrame, Window, functions as F

from raincheck import paths
from raincheck.enrich import with_cell, with_live_precip, with_zone
from raincheck.paths import data_root
from raincheck.spark import session, topic_schema

KAFKA = os.environ.get("RAINCHECK_KAFKA") or "localhost:9092"
TOPIC = {"vp": "raincheck.bus.vp", "tu": "raincheck.bus.tu"}
MAX_OFFSETS = 250000  # several rush TU polls over; it exists for the post-wake backlog
RETENTION_H = 48      # the live tables' horizon = Kafka's retention (spec J)
STAMP = "%Y-%m-%dT%H:%M:%SZ"


def reduce_tu(df: DataFrame) -> DataFrame:
    """Per-stop TU rows -> one row per (trip_id, vehicle_id, fetched_at) with the next-stop
    Prediction and the feed's trip-level delay (spec J).

    "Future" is measured against the feed's own snapshot clock (`header_ts`, falling back to
    `fetched_at` on archive-era rows that carry none), not our wall clock: a post-sleep
    replay must judge a message's predictions in the era the message was published. On the
    2026-08-11 fixture that clock leaves 76 of 1,988 trips with no live Prediction and picks
    a row other than the first for 344 - against `fetched_at` at replay time the whole
    fixture would score zero Predictions and pass vacuously.

    A trip whose every prediction has gone stale keeps its row with NULL `next_*`: the trip
    is alive, only the Prediction is not.
    """
    clock = F.coalesce(F.col("header_ts"), F.col("fetched_at"))
    future = F.col("arrival_time") >= clock
    first = Window.partitionBy("trip_id", "vehicle_id", "fetched_at").orderBy(
        F.when(future, F.col("arrival_time")).asc_nulls_last(),
        F.col("stop_sequence").asc_nulls_last())
    return (df.withColumn("rn", F.row_number().over(first)).where(F.col("rn") == 1)
            .select("trip_id", "vehicle_id", "route_id", "start_date", "direction_id",
                    "trip_delay_s", "trip_ts", "header_ts", "fetched_at",
                    F.when(future, F.col("stop_id")).alias("next_stop_id"),
                    F.when(future, F.col("stop_sequence")).alias("next_stop_sequence"),
                    F.when(future, F.col("arrival_time")).alias("next_arrival_time")))


def progress(root: Path, batch_id: int, batch_end: datetime, rows: int) -> None:
    """The liveness rail (spec J), written after each append. Both queries write it and
    last-writer-wins is fine - it says the app is alive, not which table moved. The swap is
    atomic (the page reads it while we write) and the temp name is unique per writer, so the
    two query threads cannot tear each other's file."""
    out = root / "live" / "_progress.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # each query owns a micro-batch thread, so (pid, thread) is the writer identity;
    # batch_id is NOT unique across the two queries (both count from 0)
    tmp = out.with_name(f"_progress.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps({"batch_id": batch_id,
                               "batch_end": batch_end.strftime(STAMP), "rows": rows}))
    tmp.replace(out)


def append(root: Path, kind: str, df: DataFrame) -> None:
    """One coalesced file per (date, hour) per micro-batch, appended - never overwritten -
    under live/<kind>, partitioned by the row's own fetched_at (Bronze's exact layout), so
    a replayed sleep gap lands in its true hour rather than the hour it was replayed in."""
    ts = F.timestamp_seconds("fetched_at")
    (df.coalesce(1)
       .withColumn("date", F.date_format(ts, "yyyy-MM-dd"))
       .withColumn("hour", F.date_format(ts, "HH"))
       .write.mode("append").partitionBy("date", "hour").parquet(str(root / "live" / kind)))


def _batch(root: Path, kind: str):
    """The foreachBatch callback. Pure DataFrame API throughout: two callbacks in one
    session collide on a shared temp-view name (measured, research 07 section 0)."""
    def run(df: DataFrame, batch_id: int) -> None:
        batch = (df.dropDuplicates(["vehicle_id", "ts"]) if kind == "vp" else reduce_tu(df)).persist()
        try:
            rows, end = batch.agg(F.count(F.lit(1)), F.max("fetched_at")).first()
            if not rows or end is None:
                return  # an empty tick is not an append: the rail must freeze when the feed dies
            batch_end = datetime.fromtimestamp(end, timezone.utc)
            out = batch
            if kind == "vp":
                # read fresh per batch: a hoisted ref DataFrame keeps its file index (research 07 section 0)
                zones = df.sparkSession.read.parquet(str(root / "ref" / "cell_zone"))
                out = with_live_precip(with_zone(with_cell(batch), zones), root, batch_end)
            append(root, kind, out)
            progress(root, batch_id, batch_end, rows)
        finally:
            batch.unpersist()
    return run


def start(spark, root: Path, kind: str, *, checkpoint: Path | None = None,
          trigger: dict | None = None, **options):
    """Start one query. `options` override the Kafka source defaults - 07-3 points
    `subscribe` at a throwaway topic and reads from `earliest`, which is load-bearing:
    `availableNow` with `startingOffsets=latest` on a fresh checkpoint drains 0 rows."""
    opts = {"kafka.bootstrap.servers": KAFKA, "subscribe": TOPIC[kind],
            "startingOffsets": "latest",   # a fresh checkpoint only; a resume continues from it
            "failOnDataLoss": "false",     # retention + a sleeping Mac must not kill the query
            "maxOffsetsPerTrigger": MAX_OFFSETS, **options}
    rows = (spark.readStream.format("kafka")
            .options(**{k: str(v) for k, v in opts.items()}).load()
            .select(F.from_json(F.col("value").cast("string"), topic_schema(kind)).alias("r"))
            .select("r.*")
            # from_json is PERMISSIVE: an unparseable value is an all-NULL row, which would
            # otherwise append under date=__HIVE_DEFAULT_PARTITION__
            .where(F.col("fetched_at").isNotNull()))
    return (rows.writeStream
            .queryName(f"live_{kind}")
            .option("checkpointLocation", str(checkpoint or root / "checkpoints" / f"live_{kind}"))
            .trigger(**(trigger or {"processingTime": "30 seconds"}))
            .foreachBatch(_batch(root, kind))
            .start())


def _demand_fresh(root: Path, why: str) -> None:
    sys.exit(f"stream: {why} Kafka cannot serve the gap; Bronze can ({root}/archive/vp and "
             f"/tu) - it is the record. Run `make stream FRESH=1` to discard the checkpoints "
             f"and start at latest, accepting the hole in the live tables.")


def resume_guard(root: Path, fresh: bool, now: datetime | None = None) -> None:
    """Refuse to resume across a gap Kafka can no longer serve (the design focus).

    `failOnDataLoss=false` is what keeps a sleep gap from killing the query, and it is also
    what would make a gap longer than the broker's retention a *silent* skip. So: bound the
    gap between the committed offsets and now, and stop rather than skip.

    The rail dates the offsets, so the two have to agree. A checkpoint with no rail beside it
    (someone cleared `live/`, or a FRESH run died before its first batch) is a gap of unknown
    length, which is the same danger, so it stops too. FRESH=1 drops the rail along with the
    checkpoints it described - keeping it would date offsets that no longer exist.
    """
    rail = root / "live" / "_progress.json"
    if fresh:
        for kind in TOPIC:
            shutil.rmtree(root / "checkpoints" / f"live_{kind}", ignore_errors=True)
        rail.unlink(missing_ok=True)
        print("stream: FRESH=1 - checkpoints discarded, starting at latest", flush=True)
        return
    if not rail.exists():
        if any((root / "checkpoints" / f"live_{k}").exists() for k in TOPIC):
            _demand_fresh(root, f"{root}/checkpoints/live_* exists but {rail} does not, so "
                                f"there is no way to date the committed offsets and a resume "
                                f"could skip trimmed hours SILENTLY (failOnDataLoss=false).")
        return  # first ever run: no checkpoint either, so startingOffsets=latest applies
    end = datetime.strptime(json.loads(rail.read_text())["batch_end"], STAMP).replace(
        tzinfo=timezone.utc)
    gap = (now or datetime.now(timezone.utc)) - end
    if gap > timedelta(hours=RETENTION_H):
        _demand_fresh(root, f"the last live batch ended {end.strftime(STAMP)}, "
                            f"{gap.total_seconds() / 3600:.1f} h ago - past the topics' "
                            f"{RETENTION_H} h retention, so resuming would skip those hours "
                            f"SILENTLY (failOnDataLoss=false).")


def prune(root: Path, now: datetime | None = None) -> None:
    """48 h live retention = Kafka's (spec J): drop date=/hour= dirs older than the horizon
    by name. Runs at stream start; `make daily` (ticket 15) calls it too.

    CONVERTED for an object-store root [cloud 13], because `stream.py` already writes
    live/ over s3a and retention that only runs on the Mac would let an R2 live/ grow
    without bound. The comparison is on NAMES, so it never needed a filesystem; the two
    calls that did now go through paths, where an hour is a prefix delete and the empty-day
    sweep is a no-op out there (an object store cannot hold an empty directory - the day
    stopped existing with its last hour). `precip_live` still writes live/precip_cell with
    POSIX-only calls and is deliberately OUT of scope, so a shared live/ on R2 is this half
    only."""
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(hours=RETENTION_H)).strftime(
        "date=%Y-%m-%d/hour=%H")
    for kind in TOPIC:
        table = root / "live" / kind
        for hour in table.glob("date=*/hour=*"):
            if f"{hour.parent.name}/{hour.name}" < cutoff:
                paths.rmtree(hour)
        for day in table.glob("date=*"):
            paths.rmdir_if_empty(day)  # swept empty; a non-empty day stays


def main() -> None:
    root = data_root()
    # exactly "1": FRESH=0 must not mean "yes, delete the checkpoints"
    resume_guard(root, fresh=os.environ.get("FRESH") == "1")
    if not (root / "ref" / "cell_zone").exists():
        sys.exit(f"stream: no {root}/ref/cell_zone - run `make ref` first")
    prune(root)
    spark = session()
    for kind in TOPIC:
        start(spark, root, kind)
    print(f"stream: live_vp + live_tu -> {root}/live (checkpoints under {root}/checkpoints); "
          f"Ctrl-C stops, the checkpoint resumes", flush=True)
    try:
        spark.streams.awaitAnyTermination()  # never q1.await(); q2.await(): that hides q2's death
    except KeyboardInterrupt:
        print("stream: stopping (the checkpoint holds the offsets)", flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
