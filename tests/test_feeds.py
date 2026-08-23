"""Frozen-fixture tests. Fixtures captured 2026-08-11 from gtfsrt.prod.obanyc.com."""
import contextlib
import os
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from google.transit import gtfs_realtime_pb2

from raincheck import archiver
from raincheck.feeds import (TU_COLS, VP_COLS, decode_alerts, decode_subway_tu, decode_subway_vp,
                             decode_tu, decode_vp)

FIXTURES = Path(__file__).parent / "fixtures"


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


def test_vp_every_row_has_position(vp_rows):
    assert len(vp_rows) == 1190
    assert all(-75 < r["lon"] < -72 and 40 < r["lat"] < 41.5 for r in vp_rows)


def test_vp_occupancy_partial_not_universal(vp_rows):
    with_occ = [r for r in vp_rows if r["occupancy"] is not None]
    assert 0 < len(with_occ) < len(vp_rows)  # 485/1190 in fixture; never assume 100%
    assert len(with_occ) == 485


def test_vp_keys_present(vp_rows):
    assert all(r["vehicle_id"] for r in vp_rows)


def test_tu_no_delay_field_ever(tu_rows):
    """MTA publishes absolute times only. If delay ever appears, the decode and
    the delay-computation design (ticket 06) both need revisiting."""
    feed = load("trip_updates_2026-08-11.pb")
    with_delay = sum(
        1 for e in feed.entity if e.HasField("trip_update")
        for s in e.trip_update.stop_time_update
        if s.HasField("arrival") and s.arrival.HasField("delay")
    )
    assert with_delay == 0
    assert sum(1 for r in tu_rows if r["arrival_time"]) == 37697


def test_tu_row_count(tu_rows):
    assert len(tu_rows) == 37697


def test_census_bus_row_shapes(vp_rows, tu_rows):
    """Ticket 10: every bus row carries exactly the declared keys, in order, and the
    feed header timestamp lands on both kinds."""
    assert {tuple(r) for r in vp_rows} == {VP_COLS}
    assert {tuple(r) for r in tu_rows} == {TU_COLS}
    assert all(r["header_ts"] == 1786501912 for r in vp_rows)
    assert all(r["header_ts"] == 1786501913 for r in tu_rows)


def test_tu_trip_level_fields(tu_rows):
    """All 1,988 trips in the fixture carry trip_update.delay/timestamp/direction_id;
    trip_delay_s is the feed's own number (spec C), stop-level delay stays absent
    (test_tu_no_delay_field_ever)."""
    assert all(r["trip_delay_s"] is not None for r in tu_rows)
    assert all(r["trip_ts"] > 0 and r["direction_id"] in (0, 1) for r in tu_rows)


def test_kafka_schema_equals_decoder_keys(vp_rows, tu_rows):
    """07-6: one StructType per topic, derived from and equal to the decoder key sets."""
    from raincheck.spark import topic_schema
    vp_s, tu_s = topic_schema("vp"), topic_schema("tu")
    assert tuple(vp_s.fieldNames()) == VP_COLS == tuple(vp_rows[0])
    assert tuple(tu_s.fieldNames()) == TU_COLS == tuple(tu_rows[0])
    types = {f.name: f.dataType.typeName() for f in list(vp_s) + list(tu_s)}
    assert types["lat"] == "double" and types["trip_delay_s"] == "long"
    assert types["trip_id"] == "string" and types["header_ts"] == "long"


def test_publish_reaches_broker(vp_rows, monkeypatch):
    """Ticket 10: the archiver's poll side effect lands on the topic. Skips when no
    broker answers on localhost:9092; a scratch topic (created and deleted here - the
    producer never auto-creates) keeps fixture rows off the real ones."""
    from confluent_kafka.admin import AdminClient, NewTopic
    admin = AdminClient({"bootstrap.servers": "localhost:9092"})
    try:
        admin.list_topics(timeout=2)
    except Exception:
        pytest.skip("no Kafka broker on localhost:9092")
    scratch = "raincheck.test.vp"
    for f in admin.create_topics([NewTopic(scratch, num_partitions=1, replication_factor=1)]).values():
        with contextlib.suppress(Exception):  # exists from a crashed run: fine
            f.result()
    monkeypatch.setattr(archiver, "TOPIC", {"vp": (scratch, "vehicle_id")})
    monkeypatch.setattr(archiver, "_producer", None)  # never leak a live producer to later tests
    archiver._kafka_err.update(n=0, last="")
    try:
        archiver.publish("vp", vp_rows[:5])
        assert archiver._producer.flush(10) == 0  # every message delivered
        assert archiver._kafka_err["n"] == 0
    finally:
        admin.delete_topics([scratch])


def test_archiver_parquet_roundtrip(tmp_path, vp_rows, monkeypatch):
    monkeypatch.setattr(archiver, "ROOT", tmp_path)
    window = 1786478400  # 2026-08-11T20:00:00Z, a 10-min window start
    out = archiver.flush(vp_rows[:100], "vp", window)
    assert out == tmp_path / "vp" / "date=2026-08-11" / "hour=20" / "part-00.parquet"
    t = pq.read_table(out)
    assert t.num_rows == 100
    ids = t.column("vehicle_id").to_pylist()
    assert ids == sorted(ids)  # 05: parts sorted by (key, fetched_at)
    out2 = archiver.flush(vp_rows[100:150], "vp", window)
    assert out2 == out and pq.read_table(out).num_rows == 150  # same window: append


def test_alerts_fixture_decodes():
    assert len(load("alerts_2026-08-11.pb").entity) == 78


def test_bus_alerts_decode_flat_rows():
    rows = decode_alerts(load("alerts_2026-08-11.pb"), "bus")
    assert len(rows) >= 78 and all(r["agency"] == "bus" for r in rows)
    assert all(r["header"] for r in rows) and any(r["route_id"] for r in rows)


def test_subway_decode_census():
    feed = load("subway_1234567S_2026-08-16.pb")
    tu = decode_subway_tu(feed, "subway")
    vp = decode_subway_vp(feed, "subway")
    assert len(tu) > 1000 and len(vp) > 50
    assert all(r["train_id"] and r["trip_id"] and r["scheduled_track"] for r in tu)
    assert all(r["stop_id"] and r["current_stop_sequence"] is not None for r in vp)
    assert any(r["actual_track"] for r in tu) and all(r["header_ts"] > 0 for r in tu)
    assert all(r["feed"] == "subway" for r in tu + vp)


def test_flush_types_all_none_column(tmp_path, monkeypatch):
    monkeypatch.setattr(archiver, "ROOT", tmp_path)
    rows = [{"trip_id": "t", "actual_track": None, "is_assigned": None, "arrival_time": None, "fetched_at": 1}]
    t = pq.read_table(archiver.flush(rows, "subway_tu", 1786478400))
    assert t.schema.field("actual_track").type == "string"
    assert t.schema.field("arrival_time").type == "int64" and t.schema.field("is_assigned").type == "bool"


def test_archive_root_and_budget_from_env(tmp_path):
    """Spec A: RAINCHECK_ARCHIVE_ROOT is the data root (archive/ under it; default the repo's
    data/), RAINCHECK_BRONZE_GB the absolute byte budget over that root. Fresh interpreter:
    both are read at import."""
    code = "from raincheck import archiver; print(archiver.ROOT, int(archiver.BUDGET_BYTES))"

    def run(env: dict) -> list[str]:
        return subprocess.run([sys.executable, "-c", code], env={**os.environ, **env},
                              capture_output=True, text=True, check=True).stdout.split()

    assert run({"RAINCHECK_ARCHIVE_ROOT": str(tmp_path), "RAINCHECK_BRONZE_GB": "2"}) == [
        str(tmp_path / "archive"), str(2 * 10**9)]
    repo = Path(archiver.__file__).resolve().parents[2]
    assert run({"RAINCHECK_ARCHIVE_ROOT": "", "RAINCHECK_BRONZE_GB": ""}) == [
        str(repo / "data" / "archive"), str(10 * 10**9)]  # unset or empty: defaults unchanged


def test_budget_marker_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(archiver, "ROOT", tmp_path)
    (tmp_path / "STOPPED_BUDGET").write_text("x")
    monkeypatch.setattr(sys, "argv", ["archiver"])
    with pytest.raises(SystemExit) as e:
        archiver.main()
    assert e.value.code == 0  # launchd KeepAlive(SuccessfulExit=false) must not restart it
