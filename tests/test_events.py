"""Ticket 05 / 07-2, 10-T7 and the R2 rule tests: enrich.legs on a small fixture (a
trip-change pair, a dark gap, a stationary pre-departure Leg, a teleport, dedup, the
stop-flip terminal rule), then the events -> gold -> baseline jobs through seam A (a
temp data root read back with DuckDB). Spark tests skip without a JVM."""
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raincheck import duck

T0 = int(datetime(2021, 9, 2, 2, 30, tzinfo=timezone.utc).timestamp())
H03 = datetime(2021, 9, 2, 3, tzinfo=timezone.utc)
LAT = 40.75
STEP = 3e-4   # ~33 m of latitude (moving)
NUDGE = 1e-4  # ~11 m (stationary, < 25 m)
SCHEMA = ("vehicle_id string, trip_id string, route_id string, start_date string, "
          "stop_id string, lat double, lon double, ts long, fetched_at long")


def ping(v, trip, route, lon, dt, dy, stop=None, start="20210902", fetched=None):
    return (v, trip, route, start, stop, LAT + dy, lon, T0 + dt, fetched)


def fixture_pings() -> list[tuple]:
    rows = []
    # v1: trip change - legs within each trip, none across the boundary
    rows += [ping("v1", "A", "B41", -73.95, 0, 0), ping("v1", "A", "B41", -73.95, 60, STEP),
             ping("v1", "B", "B41", -73.95, 120, 2 * STEP), ping("v1", "B", "B41", -73.95, 180, 3 * STEP)]
    # v2: dark gap (dt_s = 400 > 300)
    rows += [ping("v2", "A", "M15+", -73.94, 0, 0), ping("v2", "A", "M15+", -73.94, 400, STEP)]
    # v3: stationary pre-departure (terminal), flip, stationary mid-trip (kept), flip,
    # stationary post-arrival (terminal)
    offs = [0, NUDGE, NUDGE + STEP, 2 * NUDGE + STEP, 2 * NUDGE + 2 * STEP, 3 * NUDGE + 2 * STEP]
    stops = ["S1", "S1", "S2", "S2", "S3", "S3"]
    rows += [ping("v3", "A", "BXM1", -73.93, 60 * k, offs[k], stops[k]) for k in range(6)]
    # v4: a run that never flips, stationary -> terminal
    rows += [ping("v4", "A", "X28", -73.92, 0, 0, "S1"), ping("v4", "A", "X28", -73.92, 60, NUDGE, "S1")]
    # v5: moving pre-departure Leg (before the first flip but moving) is kept
    rows += [ping("v5", "A", "Q10", -73.80, 0, 0, "S1"), ping("v5", "A", "Q10", -73.80, 60, STEP, "S1"),
             ping("v5", "A", "Q10", -73.80, 120, 2 * STEP, "S2")]
    # v6: teleport (0.1 deg in 60 s, ~185 m/s) - no row at all
    rows += [ping("v6", "A", "B99", -73.91, 0, 0), ping("v6", "A", "B99", -73.91, 60, 0.1)]
    # v7: repeated ts with a moved position - keep the earliest fetched_at
    rows += [ping("v7", "A", "B41", -73.89, 0, 0, fetched=100),
             ping("v7", "A", "B41", -73.89, 0, 10 * STEP, fetched=50),
             ping("v7", "A", "B41", -73.89, 60, 11 * STEP, fetched=110)]
    # v8: null trip_id - no Legs
    rows += [ping("v8", None, "B44", -73.88, 0, 0), ping("v8", None, "B44", -73.88, 60, STEP)]
    return rows


@pytest.fixture(scope="module")
def r2(spark):
    from raincheck.enrich import legs

    df = spark.createDataFrame(fixture_pings(), SCHEMA)
    rows = legs(df).collect()
    by_v = {}
    for r in rows:
        by_v.setdefault(r.vehicle_id, []).append(r)
    return by_v


def test_r2_trip_change_pair(r2):
    v1 = r2["v1"]
    assert len(v1) == 2 and all(r.dropped is None for r in v1)
    assert {r.trip_id for r in v1} == {"A", "B"}  # no Leg across the trip boundary
    assert all(r.dt_s == 60 and 25 < r.dist_m < 40 for r in v1)


def test_r2_dark_gap(r2):
    (leg,) = r2["v2"]
    assert leg.dropped == "dark" and leg.dt_s == 400


def test_r2_stationary_terminal_rule(r2):
    v3 = r2["v3"]
    assert len(v3) == 5
    assert sum(r.dropped == "terminal" for r in v3) == 2  # pre-departure + post-arrival
    kept = [r for r in v3 if r.dropped is None]
    assert len(kept) == 3
    assert sum(r.dist_m < 25 for r in kept) == 1  # the stationary mid-trip Leg is kept
    (v4,) = r2["v4"]
    assert v4.dropped == "terminal"  # a run that never flips
    v5 = r2["v5"]
    assert len(v5) == 2 and all(r.dropped is None for r in v5)  # moving terminal Legs kept


def test_r2_teleport_and_null_trip(r2):
    assert "v6" not in r2 and "v8" not in r2


def test_r2_dedup_earliest_fetched_at(r2):
    (leg,) = r2["v7"]
    assert leg.dist_m < 50  # from the fetched_at=50 position, not the fetched_at=100 one


def test_r2_route_class_cell_hour(r2):
    classes = {r.route_id: r.route_class for v in r2.values() for r in v}
    assert classes == {"B41": "local", "M15+": "sbs", "BXM1": "express",
                       "X28": "express", "Q10": "local"}
    for v in r2.values():
        for r in v:
            assert r.hour_end_utc == H03.replace(tzinfo=None) or r.hour_end_utc == H03
            assert r.cell is not None and r.cell > 0


# --- seam A: the jobs against a temp data root ----------------------------------------

def write_bronze(root: Path, day: str, hour: str, rows: list[tuple]) -> None:
    from raincheck.archiver import TYPES
    from raincheck.nbp import COLUMNS

    cols = {c: [] for c in COLUMNS}
    for v, trip, route, start, stop, lat, lon, ts, fetched in rows:
        vals = dict(vehicle_id=v, trip_id=trip, route_id=route, direction_id=None,
                    start_date=start, lat=lat, lon=lon, bearing=None, stop_id=stop,
                    ts=ts, occupancy=None, fetched_at=fetched)
        for c in COLUMNS:
            cols[c].append(vals[c])
    out = root / "archive" / "vp" / f"date={day}" / f"hour={hour}" / "part-test.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols, schema=pa.schema([(c, TYPES.get(c, pa.string())) for c in COLUMNS])), out)


def read_rows(root: Path, name: str) -> list[tuple]:
    con = duck.connect()
    return sorted(con.execute(
        f"SELECT * FROM read_parquet('{root}/{name}/**/*.parquet', "
        f"hive_partitioning = true, hive_types_autocast = false)").fetchall())


def aug31_pings() -> list[tuple]:
    t = int(datetime(2021, 8, 31, 22, 0, tzinfo=timezone.utc).timestamp()) - T0
    rows = [ping("v10", "C", "B1", -73.86, t, 0, start="20210831"),
            ping("v10", "C", "B1", -73.86, t + 60, STEP, start="20210831")]
    t = int(datetime(2021, 8, 31, 23, 30, tzinfo=timezone.utc).timestamp()) - T0
    rows += [ping("v10", "D", "B1", -73.86, t, 2 * STEP, start="20210831"),
             ping("v10", "D", "B1", -73.86, t + 60, 3 * STEP, start="20210831")]
    return rows


@pytest.fixture(scope="module")
def built(spark, tmp_path_factory):
    from raincheck import events, gold

    root = tmp_path_factory.mktemp("events")
    day = fixture_pings() + [ping("v9", "A", "B41", -73.87, 0, 0, start="20210901"),
                             ping("v9", "A", "B41", -73.87, 60, STEP, start="20210901")]
    write_bronze(root, "2021-09-02", "02", day)
    aug = aug31_pings()
    write_bronze(root, "2021-08-31", "22", aug[:2])
    write_bronze(root, "2021-08-31", "23", aug[2:])
    events.leg_hours(root, spark, "2021-09-02")
    events.leg_hours(root, spark, "2021-08-31")
    gold.speed(root, spark, "2021-09")
    gold.speed(root, spark, "2021-08")

    # seed precip_cell_hourly src=aorc for September's Cell-hours: dry everywhere except
    # the Q10 Cell (recovery-guarded: mm_1h dry but mm_6h = 0.7) and the Sept-1 00Z hour (wet)
    con = duck.connect()
    g = f"{root}/gold/cell_hour_speed/**/*.parquet"
    pairs = con.execute(
        "SELECT DISTINCT cell, hour_end_utc FROM read_parquet(?, hive_partitioning = true, "
        "hive_types_autocast = false) WHERE month = '2021-09'", [g]).fetchall()
    (q10_cell,) = {c for c, in con.execute(
        "SELECT DISTINCT cell FROM read_parquet(?, hive_partitioning = true, "
        "hive_types_autocast = false) WHERE route_id = 'Q10'", [g]).fetchall()}
    wet_hour = datetime(2021, 9, 1, 0, tzinfo=timezone.utc)
    mm = [(0.05, 0.05, 0.7) if c == q10_cell else (5.0, 3.0, 10.0) if h == wet_hour
          else (0.0, 0.0, 0.0) for c, h in pairs]
    out = root / "silver" / "precip_cell_hourly" / "src=aorc" / "month=2021-09"
    out.mkdir(parents=True)
    pq.write_table(pa.table({
        "cell": pa.array([c for c, _ in pairs], pa.int64()),
        "hour_end_utc": pa.array([h for _, h in pairs], pa.timestamp("us", tz="UTC")),
        "mm_1h": pa.array([v[0] for v in mm], pa.float32()),
        "mm_1h_prev": pa.array([v[1] for v in mm], pa.float32()),
        "mm_6h": pa.array([v[2] for v in mm], pa.float32()),
    }), out / "part-00000.parquet")
    gold.baseline(root, spark, "w1")
    return root, q10_cell


def test_leg_hours_counts_and_classes(built):
    root, _ = built
    con = duck.connect()
    p = f"{root}/silver/leg_hours/**/*.parquet"
    legs, term, dark = con.execute(
        "SELECT sum(n_legs), sum(n_dropped_terminal), sum(n_dropped_dark) FROM read_parquet(?, "
        "hive_partitioning = true, hive_types_autocast = false) WHERE service_date = '2021-09-02'",
        [p]).fetchone()
    assert (legs, term, dark) == (8, 3, 1)  # v9 (start_date 20210901) contributes nothing
    row = con.execute(
        "SELECT route_class, n_legs, n_dropped_dark FROM read_parquet(?, hive_partitioning = true, "
        "hive_types_autocast = false) WHERE route_id = 'M15+'", [p]).fetchall()
    assert row == [("sbs", 0, 1)]  # counts carried on an all-dropped grain row
    n, uniq = con.execute(
        "SELECT count(*), count(DISTINCT (service_date, cell, hour_end_utc, route_id, route_class)) "
        "FROM read_parquet(?, hive_partitioning = true, hive_types_autocast = false)", [p]).fetchone()
    assert n == uniq
    (p50,) = con.execute(
        "SELECT leg_speed_p50 FROM read_parquet(?, hive_partitioning = true, "
        "hive_types_autocast = false) WHERE route_id = 'BXM1'", [p]).fetchone()
    assert p50 is not None and 0 < p50 < 1  # ~11-33 m over 60 s


def test_events_idempotent_and_stray_staging(built, spark):
    from raincheck import events

    root, _ = built
    before = read_rows(root, "silver/leg_hours")
    events.leg_hours(root, spark, "2021-09-02")
    assert read_rows(root, "silver/leg_hours") == before  # same rows and key set
    junk = root / ".staging" / "leg_hours_2021-09-02"
    junk.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"cell": pa.array([1], pa.int64())}), junk / "part-00000.parquet")
    assert read_rows(root, "silver/leg_hours") == before  # a stray staging dir changes no read


def test_gold_month_filter_and_rollup(built):
    root, _ = built
    con = duck.connect()
    p = f"{root}/gold/cell_hour_speed/**/*.parquet"
    months = dict(con.execute(
        "SELECT month, sum(n_legs) FROM read_parquet(?, hive_partitioning = true, "
        "hive_types_autocast = false) GROUP BY 1", [p]).fetchall())
    # Sept = 8 legs from 09-02 + the 00Z Sept-1 Leg of service day 08-31; Aug = its 23Z Leg
    assert months == {"2021-09": 9, "2021-08": 1}
    hours = [h for (h,) in con.execute(
        "SELECT DISTINCT hour_end_utc FROM read_parquet(?, hive_partitioning = true, "
        "hive_types_autocast = false) WHERE month = '2021-09'", [p]).fetchall()]
    assert datetime(2021, 9, 1, 0, tzinfo=timezone.utc) in hours
    assert all(h.month == 9 for h in hours)
    n, uniq = con.execute(
        "SELECT count(*), count(DISTINCT (cell, hour_end_utc, route_id, route_class)) "
        "FROM read_parquet(?, hive_partitioning = true, hive_types_autocast = false)", [p]).fetchone()
    assert n == uniq


def test_gold_rebuild_leaves_neighbour_untouched(built, spark):
    import hashlib

    from raincheck import gold

    root, _ = built
    table = root / "gold" / "cell_hour_speed"
    snap = lambda: {p.relative_to(table).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted((table / "month=2021-08").rglob("*.parquet"))}
    before = snap()
    assert before
    gold.speed(root, spark, "2021-09")
    assert snap() == before


def test_baseline_dry_mask_and_hour_of_week(built):
    root, q10_cell = built
    con = duck.connect()
    p = f"{root}/gold/cell_hourofweek_baseline/**/*.parquet"
    rows = con.execute(
        "SELECT cell, hour_of_week, speed_dry, n_dry, n_legs_dry, dist_m_sum_dry, dt_s_sum_dry "
        "FROM read_parquet(?, hive_partitioning = true, hive_types_autocast = false)", [p]).fetchall()
    assert rows
    assert len(rows) == len({(r[0], r[1]) for r in rows})  # grain (cell, hour_of_week) unique
    # 2021-09-02 03Z = Wednesday 23:00 America/New_York -> hour_of_week 2*24 + 23 = 71;
    # the wet Sept-1 00Z hour and the Aug 23Z hour (no precip row) contribute nothing
    assert {r[1] for r in rows} == {71}
    cells = {r[0] for r in rows}
    assert q10_cell not in cells  # recovery guard: mm_1h dry but mm_6h = 0.7
    for _, _, speed_dry, n_dry, n_legs_dry, dist, dt in rows:
        assert n_dry == 1 and n_legs_dry >= 0
        if dt:
            assert speed_dry == pytest.approx(dist / dt)


def test_gates_slice_not_loaded(tmp_path, monkeypatch, capsys):
    from raincheck import gates

    monkeypatch.setenv("RAINCHECK_ARCHIVE_ROOT", str(tmp_path))
    gates.main()
    assert "slice not loaded" in capsys.readouterr().out
