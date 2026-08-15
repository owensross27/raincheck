"""Frozen-fixture tests. Fixtures captured 2026-08-11 from gtfsrt.prod.obanyc.com."""
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from google.transit import gtfs_realtime_pb2

from raincheck import archiver
from raincheck.feeds import decode_tu, decode_vp

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
    out = archiver.flush(vp_rows[:100], "vp", "2026-08-11T20")
    assert out.exists()
    assert pq.read_table(out).num_rows == 100
    out2 = archiver.flush(vp_rows[100:150], "vp", "2026-08-11T20")
    assert out2 == out
    assert pq.read_table(out).num_rows == 150  # same-hour flushes append


def test_alerts_fixture_decodes():
    assert len(load("alerts_2026-08-11.pb").entity) == 78
