"""Ticket 12 / 07-3, 07-4: the streaming job and the row-point enrichment it calls.

Three tiers, all against a pytest temp root: the pure `enrich` row-point functions and the
TU reduce on the frozen fixture rows (seam B); the recovery guard, the 48 h prune and the
progress rail as plain file operations (no Spark, no broker); and 07-3's end-to-end drain
over a throwaway Kafka topic, skipped when no broker answers.

The `startingOffsets=earliest` in every drain is load-bearing: `availableNow` on a fresh
checkpoint with `latest` drains 0 rows and passes vacuously (research 07 section 0).
"""
import contextlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from google.transit import gtfs_realtime_pb2
from pyspark.sql import functions as F

from raincheck import duck, stream
from raincheck.enrich import with_cell, with_live_precip, with_zone
from raincheck.feeds import decode_tu, decode_vp

FIXTURES = Path(__file__).parent / "fixtures"
KAFKA = os.environ.get("RAINCHECK_KAFKA") or "localhost:9092"


def load(name: str) -> gtfs_realtime_pb2.FeedMessage:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString((FIXTURES / name).read_bytes())
    return feed


@pytest.fixture(scope="module")
def vp_rows():
    return decode_vp(load("vehicle_positions_2026-08-11.pb"))


@pytest.fixture(scope="module")
def tu_rows():
    return decode_tu(load("trip_updates_2026-08-11.pb"))


def seed_ref(root: Path) -> None:
    """ref/cell_zone over the 4,113 real NYC Cells (the committed ids fixture), each given
    a zone so the stream's Zone join has something to attach. The real table carries NULL
    zone_id for Cells outside every taxi zone; `with_zone`'s own test pins that case."""
    cells = pq.read_table(FIXTURES / "ref-cells-ids.parquet").column("cell").to_pylist()
    out = root / "ref" / "cell_zone"
    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"cell": pa.array(cells, pa.int64()),
                             "zone_id": pa.array([i % 263 + 1 for i in range(len(cells))], pa.int16()),
                             "borough": pa.array(["Brooklyn"] * len(cells), pa.string())}),
                   out / "part-00000.parquet")


def seed_precip(root: Path, valid_ts: str, rows: list[tuple[int, float | None]],
                fetched_at: datetime) -> None:
    """One live/precip_cell part written exactly as `precip_live.append_hour` writes it
    (same schema, same part name): a wrong-shaped stub would certify fiction."""
    d = root / "live" / "precip_cell" / f"valid_ts={valid_ts}"
    d.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"cell": pa.array([c for c, _ in rows], pa.int64()),
                             "mm_1h": pa.array([m for _, m in rows], pa.float32(), from_pandas=True),
                             "fetched_at": pa.array([fetched_at] * len(rows),
                                                    pa.timestamp("us", tz="UTC"))}),
                  d / f"part-{fetched_at:%Y%m%dT%H%M%S}.parquet")


# --- the three row-point functions (seam B) -------------------------------------------

def test_with_cell_is_the_pings_own_point(spark):
    """The Leg grain cells the leg midpoint (`enrich.legs`); a live Ping cells its own
    position. 07/08's Central Park Cell, INT64 (09)."""
    df = spark.createDataFrame([(-73.965, 40.782)], "lon double, lat double")
    (cell,) = with_cell(df).select("cell").first()
    assert f"{cell:x}" == "882a100895fffff"


def test_with_zone_left_joins_and_keeps_unzoned_cells_null(spark):
    df = spark.createDataFrame([(1,), (2,)], "cell bigint")
    cz = spark.createDataFrame([(1, 42, "Manhattan")], "cell bigint, zone_id smallint, borough string")
    got = {r["cell"]: (r["zone_id"], r["borough"]) for r in with_zone(df, cz).collect()}
    assert got == {1: (42, "Manhattan"), 2: (None, None)}  # a Cell in no taxi zone stays NULL


def pings(spark, cells: list[int]):
    return spark.createDataFrame([(c,) for c in cells], "cell bigint")


def test_with_live_precip_absent_table_yields_nulls_not_a_failed_batch(spark, tmp_path):
    """Spec J: an absent live precip table NULLs the row and never fails the batch."""
    out = with_live_precip(pings(spark, [1, 2]), tmp_path, datetime(2026, 8, 21, 20, 40, tzinfo=timezone.utc))
    assert [(r["mm_1h"], r["precip_valid_ts"]) for r in out.collect()] == [(None, None)] * 2


def test_with_live_precip_empty_dir_yields_nulls(spark, tmp_path):
    (tmp_path / "live" / "precip_cell").mkdir(parents=True)
    out = with_live_precip(pings(spark, [1]), tmp_path, datetime(2026, 8, 21, 20, 40, tzinfo=timezone.utc))
    assert out.collect()[0]["mm_1h"] is None


def test_with_live_precip_takes_the_latest_complete_hour_at_batch_time(spark, tmp_path):
    """07-4: a Ping at 20:40 carries the Hour ending 20:00 - the newest valid_ts at or
    before the batch's own clock, not the newest in the table (21:00 is still running)."""
    f = datetime(2026, 8, 21, 20, 5, tzinfo=timezone.utc)
    seed_precip(tmp_path, "2026-08-21T19", [(1, 1.0), (2, 2.0)], f)
    seed_precip(tmp_path, "2026-08-21T20", [(1, 8.5), (2, 9.5)], f)
    seed_precip(tmp_path, "2026-08-21T21", [(1, 99.0), (2, 99.0)], f)
    # research 07 section 0: collect() hands back driver-local naive datetimes, so pin the instant with
    # date_format inside the session rather than comparing Python datetimes
    out = (with_live_precip(pings(spark, [1, 2, 3]), tmp_path,
                            datetime(2026, 8, 21, 20, 40, tzinfo=timezone.utc))
           .select("cell", "mm_1h",
                   F.date_format("precip_valid_ts", "yyyy-MM-dd HH:mm").alias("vts")).collect())
    got = {r["cell"]: (r["mm_1h"], r["vts"]) for r in out}
    assert got[1] == (pytest.approx(8.5), "2026-08-21 20:00")
    assert got[2] == (pytest.approx(9.5), "2026-08-21 20:00")
    assert got[3] == (None, "2026-08-21 20:00")  # a Cell the table lacks: NULL mm, ts still stamped


def test_with_live_precip_latest_fetch_wins_and_keeps_its_nulls(spark, tmp_path):
    """Latest-fetched_at-wins per (cell, valid_ts) BEFORE the join. A re-fetch that NULLs a
    Cell (08's realized-weight guard) must null it here too, never fall back to the older
    part - the trap an aggregate that skips NULLs would walk into."""
    seed_precip(tmp_path, "2026-08-21T20", [(1, 1.0), (2, 2.0)],
                datetime(2026, 8, 21, 20, 5, tzinfo=timezone.utc))
    seed_precip(tmp_path, "2026-08-21T20", [(1, 7.0), (2, None)],
                datetime(2026, 8, 21, 20, 9, tzinfo=timezone.utc))
    out = with_live_precip(pings(spark, [1, 2]), tmp_path,
                           datetime(2026, 8, 21, 20, 40, tzinfo=timezone.utc)).collect()
    assert len(out) == 2  # the dedupe is what keeps the broadcast join 1:1
    got = {r["cell"]: r["mm_1h"] for r in out}
    assert got[1] == pytest.approx(7.0) and got[2] is None


def test_with_live_precip_sees_an_hour_written_after_the_first_call(spark, tmp_path):
    """research 07 check 4, and the reason the `spark.read` lives inside the callback: a
    DataFrame built once from a path keeps its file index. One call cannot tell a fresh read
    from a frozen one - and frozen means a storm that begins after `make stream` starts never
    reaches the map, while `precip_valid_ts` ages silently on every row."""
    def precip_at(hour: int):
        row = (with_live_precip(pings(spark, [1]), tmp_path,
                                datetime(2026, 8, 21, hour, 40, tzinfo=timezone.utc))
               .select("mm_1h", F.date_format("precip_valid_ts", "HH:mm").alias("vts")).first())
        return row["mm_1h"], row["vts"]

    seed_precip(tmp_path, "2026-08-21T20", [(1, 1.0)],
                datetime(2026, 8, 21, 20, 5, tzinfo=timezone.utc))
    assert precip_at(20) == (pytest.approx(1.0), "20:00")
    seed_precip(tmp_path, "2026-08-21T21", [(1, 4.0)],
                datetime(2026, 8, 21, 21, 5, tzinfo=timezone.utc))
    assert precip_at(21) == (pytest.approx(4.0), "21:00")  # the new Hour, not the frozen one


# --- the TU reduce --------------------------------------------------------------------

def tu_oracle(rows: list[dict]) -> dict:
    """Plain-Python next-stop Prediction per (trip_id, vehicle_id, fetched_at): the
    earliest arrival at or after the feed's own snapshot clock."""
    by: dict[tuple, list[dict]] = {}
    for r in rows:
        by.setdefault((r["trip_id"], r["vehicle_id"], r["fetched_at"]), []).append(r)
    out = {}
    for k, rs in by.items():
        clock = rs[0]["header_ts"] if rs[0]["header_ts"] is not None else k[2]
        fut = [r for r in rs if r["arrival_time"] is not None and r["arrival_time"] >= clock]
        out[k] = min(r["arrival_time"] for r in fut) if fut else None
    return out


@pytest.fixture(scope="module")
def reduced(spark, tu_rows):
    from raincheck.spark import topic_schema
    return stream.reduce_tu(spark.createDataFrame(tu_rows, topic_schema("tu"))).collect()


def test_reduce_tu_grain_is_one_row_per_trip_vehicle_fetch(reduced, tu_rows):
    keys = [(r["trip_id"], r["vehicle_id"], r["fetched_at"]) for r in reduced]
    assert len(reduced) == len(set(keys)) == 1988  # 37,697 stop rows -> 1,988 trips in the fixture


def test_reduce_tu_next_stop_is_the_earliest_future_arrival(reduced, tu_rows):
    """Not vacuous on this fixture: 344 of the 1,988 trips pick a row that is not the
    first stop row, and 76 have no future arrival left at the snapshot clock."""
    got = {(r["trip_id"], r["vehicle_id"], r["fetched_at"]): r["next_arrival_time"] for r in reduced}
    assert got == tu_oracle(tu_rows)
    assert sum(1 for v in got.values() if v is None) == 76


def test_reduce_tu_carries_the_trip_level_delay(reduced):
    """Ticket 10's census-complete decoder: trip_delay_s on every row (spec C, verbatim -
    never the project's schedule-derived Delay)."""
    assert all(r["trip_delay_s"] is not None for r in reduced)
    assert all(r["next_stop_id"] is None or r["next_stop_sequence"] is not None for r in reduced)


def test_reduce_tu_nulls_the_prediction_when_every_arrival_is_past(spark):
    """A trip whose whole prediction list has gone stale keeps its row (the trip is alive,
    the Prediction is not) rather than vanishing from the live table."""
    from raincheck.spark import topic_schema
    base = {c: None for c in topic_schema("tu").fieldNames()}
    rows = [{**base, "trip_id": "T", "vehicle_id": "V", "fetched_at": 1000, "header_ts": 1000,
             "trip_delay_s": 60, "stop_id": s, "stop_sequence": i, "arrival_time": a}
            for i, (s, a) in enumerate([("A", 900), ("B", 950)])]
    (out,) = stream.reduce_tu(spark.createDataFrame(rows, topic_schema("tu"))).collect()
    assert (out["next_stop_id"], out["next_arrival_time"]) == (None, None)
    assert out["trip_delay_s"] == 60


# --- the writer ------------------------------------------------------------------------

def test_append_partitions_by_the_rows_own_fetched_at_not_the_clock(spark, tmp_path):
    """The claim recovery rests on: a replayed sleep gap lands in its TRUE date=/hour=, not
    the hour it was replayed in. The fixture rows cannot pin this - they are decoded seconds
    before the drain, so their fetched_at IS the wall clock. 1786406400 = 2026-08-11T00:00:00Z."""
    stream.append(tmp_path, "vp", spark.createDataFrame([(1786406400,)], "fetched_at bigint"))
    assert [str(p.relative_to(tmp_path)) for p in (tmp_path / "live" / "vp").glob("date=*/hour=*")] \
        == ["live/vp/date=2026-08-11/hour=00"]


# --- recovery, retention and the progress rail (no Spark, no broker) ------------------

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def write_progress(root: Path, end: datetime) -> None:
    stream.progress(root, 7, end, 42)


def test_resume_guard_first_ever_run_proceeds(tmp_path):
    stream.resume_guard(tmp_path, fresh=False, now=NOW)  # no _progress.json: fresh, latest


def test_resume_guard_resumes_inside_the_retention_horizon(tmp_path):
    write_progress(tmp_path, NOW - timedelta(hours=40))
    stream.resume_guard(tmp_path, fresh=False, now=NOW)  # the checkpoint replays the gap


def test_resume_guard_exits_loudly_past_retention(tmp_path):
    """The design focus: with failOnDataLoss=false a stream down longer than Kafka's 48 h
    retention would silently skip the trimmed range. It must stop and name Bronze."""
    write_progress(tmp_path, NOW - timedelta(hours=50))
    (tmp_path / "checkpoints" / "live_vp").mkdir(parents=True)
    with pytest.raises(SystemExit) as e:
        stream.resume_guard(tmp_path, fresh=False, now=NOW)
    msg = str(e.value)
    assert "FRESH=1" in msg and "archive" in msg and "50.0 h" in msg
    assert (tmp_path / "checkpoints" / "live_vp").exists()  # nothing destroyed without FRESH=1


def test_resume_guard_stops_when_a_checkpoint_has_no_rail(tmp_path):
    """`rm -rf <root>/live` leaves `<root>/checkpoints/` standing, and a FRESH run killed
    before its first batch does too. Either way the committed offsets have no date on them,
    so the gap cannot be bounded - which is the same danger as an over-long one."""
    (tmp_path / "checkpoints" / "live_vp" / "offsets").mkdir(parents=True)
    with pytest.raises(SystemExit) as e:
        stream.resume_guard(tmp_path, fresh=False, now=NOW)
    assert "FRESH=1" in str(e.value) and "archive" in str(e.value)


def test_fresh_discards_the_checkpoints_and_the_rail_that_dated_them(tmp_path):
    write_progress(tmp_path, NOW - timedelta(hours=50))
    for kind in ("vp", "tu"):
        (tmp_path / "checkpoints" / f"live_{kind}" / "offsets").mkdir(parents=True)
    stream.resume_guard(tmp_path, fresh=True, now=NOW)
    assert not (tmp_path / "checkpoints" / "live_vp").exists()
    assert not (tmp_path / "checkpoints" / "live_tu").exists()
    # keeping the rail would date offsets that no longer exist - and would then read as a
    # 50 h gap on the next plain run, stopping a stream that has nothing wrong with it
    assert not (tmp_path / "live" / "_progress.json").exists()


def test_progress_file_shape(tmp_path):
    stream.progress(tmp_path, 3, datetime(2026, 8, 23, 11, 30, 15, tzinfo=timezone.utc), 91)
    assert json.loads((tmp_path / "live" / "_progress.json").read_text()) == {
        "batch_id": 3, "batch_end": "2026-08-23T11:30:15Z", "rows": 91}
    assert not list((tmp_path / "live").glob("*.tmp"))  # atomic swap leaves no partial file


def test_prune_drops_live_dirs_past_the_horizon_by_name(tmp_path):
    for kind in ("vp", "tu"):
        for back in (1, 47, 49, 300):
            h = NOW - timedelta(hours=back)
            d = tmp_path / "live" / kind / f"date={h:%Y-%m-%d}" / f"hour={h:%H}"
            d.mkdir(parents=True)
            (d / "part-00000.parquet").touch()
    stream.prune(tmp_path, now=NOW)
    for kind in ("vp", "tu"):
        kept = sorted(f"{d.parent.name}/{d.name}"
                      for d in (tmp_path / "live" / kind).glob("date=*/hour=*"))
        assert kept == ["date=2026-08-21/hour=13", "date=2026-08-23/hour=11"]  # -47 h and -1 h
    assert not list((tmp_path / "live" / "vp").glob("date=2026-08-11"))  # empty date dir swept too


# --- 07-3: the end-to-end drain over a throwaway topic --------------------------------

@pytest.fixture(scope="module")
def admin():
    from confluent_kafka.admin import AdminClient
    a = AdminClient({"bootstrap.servers": KAFKA})
    try:
        a.list_topics(timeout=2)
    except Exception:
        pytest.skip(f"no Kafka broker on {KAFKA}")
    return a


@pytest.fixture(scope="module")
def published(admin, vp_rows, tu_rows):
    """The fixture-decoded rows on throwaway topics, produced exactly as the archiver
    produces them (compact JSON, str(key or '')). Pid-suffixed so a parallel run or a
    crashed predecessor never feeds this one; the producer never auto-creates."""
    from confluent_kafka import Producer
    from confluent_kafka.admin import NewTopic

    topics = {k: f"raincheck.test.stream.{k}.{os.getpid()}" for k in ("vp", "tu")}
    for f in admin.create_topics([NewTopic(t, num_partitions=1, replication_factor=1)
                                  for t in topics.values()]).values():
        f.result()
    keep = {r["trip_id"] for r in tu_rows[:4000]}  # a slice: the whole 37,697 is the unit test's job
    p = Producer({"bootstrap.servers": KAFKA, "compression.type": "zstd"})
    # every VP row twice: the fixture holds no duplicate (vehicle_id, ts) pair of its own, so
    # without this the in-batch dropDuplicates is a no-op in every test and could be deleted
    # unnoticed. 2,380 messages are far under maxOffsetsPerTrigger, so they drain as one batch.
    for kind, rows in (("vp", vp_rows * 2), ("tu", [r for r in tu_rows if r["trip_id"] in keep])):
        key = {"vp": "vehicle_id", "tu": "trip_id"}[kind]
        for r in rows:
            p.produce(topics[kind], key=str(r[key] or ""), value=json.dumps(r, separators=(",", ":")))
    assert p.flush(60) == 0
    yield topics
    admin.delete_topics(list(topics.values()))


def drain(spark, root: Path, kind: str, topic: str, checkpoint: str = "test") -> None:
    q = stream.start(spark, root, kind, checkpoint=root / "checkpoints" / f"{checkpoint}_{kind}",
                     trigger={"availableNow": True}, subscribe=topic, startingOffsets="earliest")
    try:
        q.awaitTermination(300)
    finally:
        q.stop()


@pytest.fixture(scope="module")
def drained(spark, tmp_path_factory, published):
    root = tmp_path_factory.mktemp("live")
    seed_ref(root)
    for kind, topic in published.items():
        drain(spark, root, kind, topic)
    return root


def read(root: Path, kind: str):
    con = duck.connect()
    duck.table(con, root / "live" / kind).create_view("lv")
    return con


def test_drain_lands_enriched_vp_rows_in_date_hour(drained, vp_rows):
    """07-3: > 0 rows with cell non-null and mm_1h NULL (no live precip table under this
    root), partitioned by date=/hour= from the row's own fetched_at."""
    con = read(drained, "vp")
    n, cells, zones, mm = con.execute(
        "SELECT count(*), count(cell), count(zone_id), count(mm_1h) FROM lv").fetchone()
    # exactly the fixture, from a topic carrying it twice: the in-batch dropDuplicates
    # collapsed the copies AND neither broadcast join fanned a row out
    assert n == len(vp_rows)
    assert cells == n and mm == 0 and zones > 0
    hours = con.execute("SELECT DISTINCT date, hour FROM lv").fetchall()
    assert hours and all(len(d) == 10 and len(h) == 2 for d, h in hours)
    (same,) = con.execute(
        "SELECT count(*) FROM lv WHERE strftime(to_timestamp(fetched_at), '%Y-%m-%d %H') "
        "= date || ' ' || hour").fetchone()
    assert same == n  # the partition is the row's own fetched_at, not the clock


def test_drain_writes_the_progress_rail(drained):
    p = json.loads((drained / "live" / "_progress.json").read_text())
    assert p["rows"] > 0 and p["batch_id"] >= 0
    assert datetime.strptime(p["batch_end"], "%Y-%m-%dT%H:%M:%SZ").year >= 2026


def test_drain_reduces_tu_to_one_row_per_trip_fetch(drained):
    con = read(drained, "tu")
    n, uniq, pred = con.execute(
        "SELECT count(*), count(DISTINCT (trip_id, vehicle_id, fetched_at)), "
        "count(next_arrival_time) FROM lv").fetchone()
    assert n == uniq > 0 and pred > 0
    (stops,) = con.execute("SELECT count(*) FROM lv WHERE next_stop_id IS NOT NULL "
                           "AND next_arrival_time IS NULL").fetchone()
    assert stops == 0


def test_second_run_on_the_same_checkpoint_finds_nothing_new(spark, drained, published):
    before = {p.name for p in (drained / "live" / "vp").rglob("*.parquet")}
    drain(spark, drained, "vp", published["vp"])
    assert {p.name for p in (drained / "live" / "vp").rglob("*.parquet")} == before


def test_two_processing_time_triggers_write_two_files(spark, tmp_path_factory, published):
    """A bounded maxOffsetsPerTrigger splits the fixture across batches, so this asserts
    two real appends rather than one drain plus an empty tick."""
    root = tmp_path_factory.mktemp("ticks")
    seed_ref(root)
    q = stream.start(spark, root, "vp", checkpoint=root / "checkpoints" / "ticks_vp",
                     trigger={"processingTime": "1 second"}, subscribe=published["vp"],
                     startingOffsets="earliest", maxOffsetsPerTrigger=400)
    try:
        deadline = time.time() + 120
        while time.time() < deadline and len(list((root / "live" / "vp").rglob("*.parquet"))) < 2:
            time.sleep(0.5)
    finally:
        q.stop()
    files = list((root / "live" / "vp").rglob("*.parquet"))
    assert len(files) >= 2 and len({f.name for f in files}) == len(files)


def test_malformed_message_never_lands_as_a_null_partition(spark, tmp_path_factory, admin):
    """from_json is PERMISSIVE: a non-JSON value becomes an all-NULL row, which would append
    under date=__HIVE_DEFAULT_PARTITION__ - a partition `prune` could never sweep, since that
    name sorts above every real date. The junk MUST share a micro-batch with a well-formed
    row: on its own the batch is empty and `_batch`'s empty-tick guard short-circuits before
    the source filter is reached, which is a green test of nothing."""
    from confluent_kafka import Producer
    from confluent_kafka.admin import NewTopic

    topic = f"raincheck.test.stream.junk.{os.getpid()}"
    for f in admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)]).values():
        f.result()
    root = tmp_path_factory.mktemp("junk")
    seed_ref(root)
    try:
        p = Producer({"bootstrap.servers": KAFKA})
        p.produce(topic, key="x", value="not json at all")
        p.produce(topic, key="y", value=json.dumps({"vehicle_id": "y", "lat": 40.7, "lon": -73.9}))
        p.produce(topic, key="z", value=json.dumps(
            {"vehicle_id": "z", "trip_id": "T", "route_id": "B41", "ts": 1786406395,
             "lat": 40.782, "lon": -73.965, "fetched_at": 1786406400}))
        assert p.flush(30) == 0
        drain(spark, root, "vp", topic, checkpoint="junk")
        assert not list((root / "live" / "vp").glob("date=__HIVE_DEFAULT_PARTITION__"))
        (n,) = read(root, "vp").execute("SELECT count(*) FROM lv").fetchone()
        assert n == 1  # the well-formed row only; the two junk rows carried no fetched_at

        rail = (root / "live" / "_progress.json").read_text()
        drain(spark, root, "vp", topic, checkpoint="junk")  # nothing new: an empty tick
        assert (root / "live" / "_progress.json").read_text() == rail  # the rail freezes, as it must
    finally:
        with contextlib.suppress(Exception):
            admin.delete_topics([topic])
