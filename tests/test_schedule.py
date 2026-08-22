"""Ticket 07: `schedule PICK=` on the mini GTFS zip through seam A (a temp data root
read back with DuckDB) - table shapes, GTFS time parsing past 24:00, cumulative geodesic
shape_dist_m, calendar x calendar_dates flattening, the trip_id scheme check."""
from datetime import date

import pyarrow as pa
import pytest
from conftest import FRAG, T1, land_pick

from raincheck import duck
from raincheck.schedule import hms_to_s, scheme_check, trip_type


def test_hms_to_s():
    got = hms_to_s(pa.chunked_array([pa.array(["07:00:00", "25:04:00", "", None])]))
    assert got.to_pylist() == [25200, 90240, None, None]


def test_trip_type():
    assert [trip_type(r) for r in ("B41", "M15+", "BXM1", "X28", "SIM4", "Q50")] == \
        ["local", "sbs", "express", "express", "express", "local"]


def test_scheme_check_fails():
    with pytest.raises(SystemExit):
        scheme_check(["nonsense", "also-nonsense"], "brooklyn")


@pytest.fixture(scope="module")
def loaded(spark, tmp_path_factory):
    from raincheck import schedule

    root = tmp_path_factory.mktemp("schedule")
    pick_id = land_pick(root)
    schedule.load(root, spark, pick_id)
    return root, pick_id


def q(sql, *params):
    return duck.connect().execute(sql.replace("READ", "read_parquet(?, "
                                  "hive_partitioning = true, hive_types_autocast = false)"),
                                  list(params)).fetchall()


def test_trip_stops(loaded):
    root, pick_id = loaded
    p = f"{root}/silver/trip_stops/**/*.parquet"
    rows = q("SELECT stop_sequence, stop_id, arrival_s, shape_dist_m FROM READ "
             "WHERE trip_id = ? ORDER BY stop_sequence", p, T1)
    assert [(r[0], r[1], r[2]) for r in rows] == [
        (1, "S1", 25200), (2, "S2", 25500), (3, "S3", 25800), (4, "S4", 26100), (5, "S5", 26400)]
    dists = [r[3] for r in rows]
    assert dists[0] == pytest.approx(0.0, abs=1.0)
    assert all(b > a for a, b in zip(dists, dists[1:]))  # cumulative, monotone
    # four ~555 m geodesic hops of 0.005 deg latitude
    assert dists[-1] == pytest.approx(4 * 555, rel=0.02)
    (over24,) = q("SELECT arrival_s FROM READ WHERE stop_sequence = 1 AND trip_id LIKE '%SDon%'", p)
    assert over24[0] == 24 * 3600 + 59 * 60
    ((pick,),) = q("SELECT DISTINCT pick_id FROM READ", p)
    assert pick == pick_id


def test_service_days(loaded):
    root, _ = loaded
    p = f"{root}/silver/service_days/**/*.parquet"
    days = {d for (d,) in q("SELECT service_date FROM READ WHERE service_id = 'SUN'", p)}
    assert date(2021, 11, 7) in days and date(2024, 3, 10) in days and date(2024, 11, 3) in days
    assert date(2024, 6, 2) not in days          # calendar_dates removal
    assert all(d.weekday() == 6 for d in days)
    wkd = {d for (d,) in q("SELECT service_date FROM READ WHERE service_id = 'WKD'", p)}
    assert date(2024, 6, 1) in wkd               # calendar_dates addition (a Saturday)
    assert date(2021, 9, 2) not in wkd           # the pick_gap day stays uncovered


def test_stops_trips_shapes(loaded):
    root, _ = loaded
    rows = q("SELECT stop_id, cell, lon, lat FROM READ ORDER BY stop_id",
             f"{root}/silver/stops/**/*.parquet")
    assert len(rows) == 7 and all(r[1] > 0 for r in rows)
    types = dict(q("SELECT trip_id, trip_type FROM READ",
                   f"{root}/silver/trips/**/*.parquet"))
    assert types[T1] == "local" and types[FRAG] == "local"
    assert types["MV_C1-Weekday-SDon-040000_M15+_102"] == "sbs"
    assert types["MV_C1-Weekday-050000_BXM1_103"] == "express"
    shapes = q("SELECT shape_id, length_m FROM READ ORDER BY shape_id",
               f"{root}/silver/shapes/**/*.parquet")
    assert [s for s, _ in shapes] == ["SH1", "SHF"]
    assert shapes[0][1] == pytest.approx(4 * 555, rel=0.02)
