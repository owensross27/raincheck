"""Ticket 03 / 10-T1 tier-1: the nycbuspositions xz -> Bronze VP converter on committed
fragments of two real archive days (stratified: header + every 700th row, all 24 hours,
all three route classes). JVM-free (pyarrow converter, DuckDB read-back)."""
import hashlib
import shutil
import lzma
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from google.transit import gtfs_realtime_pb2

from raincheck import archiver, duck, nbp
from raincheck.feeds import decode_vp

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> gtfs_realtime_pb2.FeedMessage:
    # local copy of test_feeds.load: a cross-module test import breaks bare `pytest`
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString((FIXTURES / name).read_bytes())
    return feed
BBOX = (-74.30, 40.45, -73.65, 40.95)
FRAGMENTS = {"2018-10-10": "nbp-2018-10-10-fragment.csv.xz",   # 20-column era
             "2021-11-07": "nbp-2021-11-07-fragment.csv.xz"}   # 22-column era, DST day


def seed(root: Path, day: str) -> Path:
    y, m, _ = day.split("-")
    src = root / "archive" / "nycbuspositions" / y / m / f"{day}-bus-positions.csv.xz"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes((FIXTURES / FRAGMENTS[day]).read_bytes())
    return src


def xz_rows(path: Path) -> int:
    with lzma.open(path, "rt") as f:
        return sum(1 for _ in f) - 1


@pytest.fixture(scope="module", params=sorted(FRAGMENTS))
def converted(request, tmp_path_factory):
    day = request.param
    root = tmp_path_factory.mktemp(day)
    src = seed(root, day)
    nbp.convert(root, day)
    return root, day, src


def test_t1_rows_and_uniqueness(converted):
    root, day, src = converted
    rel = duck.table(duck.connect(), root / "archive" / "vp")
    n, uniq = rel.aggregate("count(*), count(DISTINCT (vehicle_id, ts))").fetchone()
    assert n == xz_rows(src)
    assert uniq == n


def test_t1_ts_gate_and_bbox(converted):
    root, day, src = converted
    d = date.fromisoformat(day)
    lo = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()) - 86400
    hi = lo + 3 * 86400
    con = duck.connect()
    (bad_ts,) = con.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE ts < ? OR ts >= ?",
        [f"{root}/archive/vp/**/*.parquet", lo, hi]).fetchone()
    assert bad_ts == 0
    (bad_pos,) = con.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE lon < ? OR lon > ? OR lat < ? OR lat > ?",
        [f"{root}/archive/vp/**/*.parquet", BBOX[0], BBOX[2], BBOX[1], BBOX[3]]).fetchone()
    assert bad_pos == 0


def test_t1_route_classes(converted):
    root, day, src = converted
    routes = {r[0] for r in duck.table(duck.connect(), root / "archive" / "vp")
              .aggregate("route_id").fetchall() if r[0]}
    express = {r for r in routes if re.match(r"^(X|BM|QM|BXM|SIM)", r.upper())}
    sbs = {r for r in routes if r.endswith("+")}
    local = routes - express - sbs
    assert express and sbs and local, day


def test_t1_layout_and_idempotence(converted):
    root, day, src = converted
    vp = root / "archive" / "vp"
    parts = sorted(p.relative_to(vp).as_posix() for p in vp.rglob("*.parquet"))
    assert parts == [f"date={day}/hour={h:02d}/part-nbp-{day}.parquet" for h in range(24)]
    neighbour = vp / f"date={date.fromisoformat(day).replace(day=1).isoformat()}" / "hour=00"
    neighbour.mkdir(parents=True)
    (neighbour / "part-00.parquet").write_bytes(b"sentinel")
    before = {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in vp.rglob("*.parquet")}
    nbp.convert(root, day)
    after = {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in vp.rglob("*.parquet")}
    assert after == before  # identical bytes, no extra files, neighbour untouched
    shutil.rmtree(neighbour.parent)  # the sentinel is not a real parquet; later tests read the tree


def test_columns_match_live_decoder_census(converted, tmp_path, monkeypatch):
    """Converter parquet schema == the schema the archiver writes for decode_vp rows."""
    root, day, src = converted
    monkeypatch.setattr(archiver, "ROOT", tmp_path)
    live_rows = decode_vp(load("vehicle_positions_2026-08-11.pb"))
    live_schema = pq.read_schema(archiver.flush(live_rows[:5], "vp", 1786478400))
    part = root / "archive" / "vp" / f"date={day}" / "hour=12" / f"part-nbp-{day}.parquet"
    assert pq.read_schema(part).equals(live_schema)


def test_mapping_values(converted):
    root, day, src = converted
    con = duck.connect()
    path = f"{root}/archive/vp/**/*.parquet"
    rel = duck.table(con, root / "archive" / "vp")
    row = dict(zip(rel.columns,
                   con.execute("SELECT * FROM read_parquet(?) ORDER BY vehicle_id, ts LIMIT 1", [path]).fetchone()))
    assert row["fetched_at"] is None and row["direction_id"] is None
    assert row["occupancy"] is None  # fragment day has exactly one distinct source value
    assert re.fullmatch(r"\d{8}", row["start_date"])
    assert row["vehicle_id"].startswith(("MTA NYCT_", "MTABC_"))
    (empties,) = con.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE trip_id = '' OR route_id = '' OR stop_id = ''",
        [path]).fetchone()
    assert empties == 0  # empty -> NULL, never empty string


def test_source_downloads_once_and_recovers_a_stale_part(tmp_path, monkeypatch):
    calls = []

    def fake_urlretrieve(url, dst):
        calls.append(url)
        Path(dst).write_bytes((FIXTURES / FRAGMENTS["2021-11-07"]).read_bytes())

    monkeypatch.setattr(nbp.urllib.request, "urlretrieve", fake_urlretrieve)
    stale = tmp_path / "archive" / "nycbuspositions" / "2021" / "11" / "2021-11-07-bus-positions.csv.part"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"crashed mid-download")  # a .part left behind must not block a retry
    src = nbp.source(tmp_path, "2021-11-07")
    assert calls == ["https://s3.amazonaws.com/nycbuspositions/2021/11/2021-11-07-bus-positions.csv.xz"]
    assert src.exists() and xz_rows(src) > 0
    assert nbp.source(tmp_path, "2021-11-07") == src and len(calls) == 1  # cached: no second fetch


def test_ms_era_file_fails_the_gate(tmp_path):
    """A file whose timestamps parse outside [D-1, D+2) (the ms/s era) must fail loudly."""
    root = tmp_path
    day = "2021-11-07"
    src = root / "archive" / "nycbuspositions" / "2021" / "11" / f"{day}-bus-positions.csv.xz"
    src.parent.mkdir(parents=True)
    header = ("timestamp,trip_id,route_id,trip_start_time,trip_start_date,vehicle_id,vehicle_label,"
              "vehicle_license_plate,latitude,longitude,bearing,speed,stop_id,stop_status,"
              "occupancy_status,congestion_level,progress,block_assigned,dist_along_route,dist_from_stop")
    bad = "2022-03-01 00:00:01+00,t,B1,,2021-11-07,MTA NYCT_1,,,40.7,-73.9,0.0,,s1,IN_TRANSIT_TO,EMPTY,U,,,,"
    src.write_bytes(lzma.compress(f"{header}\n{bad}\n".encode()))
    with pytest.raises(SystemExit, match="2021-11-07"):
        nbp.convert(root, day)
    assert not (root / "archive" / "vp").exists()  # nothing written for a gated file


def test_occupancy_kept_when_day_is_mixed(tmp_path):
    """The 2019-09-11 case: >1 distinct source value -> occupancy kept as given."""
    root = tmp_path
    day = "2021-11-07"
    src = root / "archive" / "nycbuspositions" / "2021" / "11" / f"{day}-bus-positions.csv.xz"
    src.parent.mkdir(parents=True)
    header = ("timestamp,trip_id,route_id,trip_start_time,trip_start_date,vehicle_id,vehicle_label,"
              "vehicle_license_plate,latitude,longitude,bearing,speed,stop_id,stop_status,"
              "occupancy_status,congestion_level,progress,block_assigned,dist_along_route,dist_from_stop")
    rows = [f"2021-11-07 0{i}:00:00+00,t{i},B1,,2021-11-07,MTA NYCT_{i},,,40.7,-73.9,,,s1,X,{occ},U,,,,"
            for i, occ in enumerate(["EMPTY", "FEW_SEATS_AVAILABLE", ""])]
    src.write_bytes(lzma.compress(("\n".join([header] + rows) + "\n").encode()))
    nbp.convert(root, day)
    occ = [r[0] for r in duck.connect().execute(
        "SELECT occupancy FROM read_parquet(?) ORDER BY ts",
        [f"{root}/archive/vp/**/*.parquet"]).fetchall()]
    assert occ == ["EMPTY", "FEW_SEATS_AVAILABLE", None]  # kept as given, empty -> NULL
