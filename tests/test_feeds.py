"""Frozen-fixture tests. Fixtures captured 2026-08-11 from gtfsrt.prod.obanyc.com."""
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from google.transit import gtfs_realtime_pb2

from raincheck import archiver
from raincheck.feeds import decode_alerts, decode_subway_tu, decode_subway_vp, decode_tu, decode_vp

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


def test_budget_marker_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(archiver, "ROOT", tmp_path)
    (tmp_path / "STOPPED_BUDGET").write_text("x")
    monkeypatch.setattr(sys, "argv", ["archiver"])
    with pytest.raises(SystemExit) as e:
        archiver.main()
    assert e.value.code == 0  # launchd KeepAlive(SuccessfulExit=false) must not restart it
