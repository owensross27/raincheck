"""Ticket 05 / 07-2, 10-T7 and the R2 rule tests: enrich.legs on a small fixture (a
trip-change pair, a dark gap, a stationary pre-departure Leg, a teleport, dedup, the
stop-flip terminal rule), then the events -> gold -> baseline jobs through seam A (a
temp data root read back with DuckDB). Ticket 07: Passages and Delay - the DST noon
rule (2024-03-10 / 2024-11-03, plus the real 2021-11-07 fall-back fragment against the
mini Pick), the envelope/flap/interpolation rules, the multi-vehicle trip key, the
pick_gap path and events idempotence. Spark tests skip without a JVM."""
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from conftest import FRAG, GTFS, T1, T2, land_pick

from raincheck import duck

FIXTURES = Path(__file__).parent / "fixtures"

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
    for v, trip, route, start, stop, lat, lon, ts, fetched, *rel in rows:
        vals = dict(vehicle_id=v, trip_id=trip, route_id=route, direction_id=None,
                    start_date=start, schedule_relationship=rel[0] if rel else None,
                    lat=lat, lon=lon, bearing=None, stop_id=stop,
                    ts=ts, occupancy=None, header_ts=None, fetched_at=fetched)
        for c in COLUMNS:
            cols[c].append(vals[c])
    out = root / "archive" / "vp" / f"date={day}" / f"hour={hour}" / "part-test.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols, schema=pa.schema([(c, TYPES.get(c, pa.string())) for c in COLUMNS])), out)


def write_bronze_tu(root: Path, day: str, hour: str, rows: list[tuple]) -> None:
    """rows: (trip_id, route_id, start_date, vehicle_id, stop_id, arrival_time,
    fetched_at) in decode_tu's column order and archiver TYPES."""
    from raincheck.archiver import TYPES

    cols = ("trip_id", "route_id", "start_date", "vehicle_id", "stop_id",
            "stop_sequence", "arrival_time", "departure_time", "fetched_at")
    data = {c: [] for c in cols}
    for trip, route, start, veh, stop, arr, fetched in rows:
        vals = dict(trip_id=trip, route_id=route, start_date=start, vehicle_id=veh,
                    stop_id=stop, stop_sequence=None, arrival_time=arr,
                    departure_time=None, fetched_at=fetched)
        for c in cols:
            data[c].append(vals[c])
    out = root / "archive" / "tu" / f"date={day}" / f"hour={hour}" / "part-test.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(data, schema=pa.schema(
        [(c, TYPES.get(c, pa.string())) for c in cols])), out)


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
    events.events(root, spark, "2021-09-02")  # no ref/picks at all -> pick_gap path
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
    before_ev = read_rows(root, "silver/events")
    events.leg_hours(root, spark, "2021-09-02")
    events.events(root, spark, "2021-09-02")
    assert read_rows(root, "silver/leg_hours") == before  # same rows and key set
    assert read_rows(root, "silver/events") == before_ev
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
    with pytest.raises(SystemExit) as exc:
        gates.main()
    assert exc.value.code == 2  # the gates never ran - not a silent pass
    assert "slice not loaded" in capsys.readouterr().out


# --- ticket 07: Passages and Delay ----------------------------------------------------

def utc_s(*args) -> int:
    return int(datetime(*args, tzinfo=timezone.utc).timestamp())


def row(v, trip, route, start, stop, ts, lat=40.61, lon=-73.95, rel=None):
    return (v, trip, route, start, stop, lat, lon, ts, None, rel)


@pytest.fixture(scope="module")
def pick_built(spark, tmp_path_factory):
    """A temp root with the mini Pick loaded, the real 2021-11-07 DST fragment converted,
    and synthetic Bronze days for the noon-rule pair, the envelope rules and the pick_gap
    path; events run for each service day."""
    from raincheck import events, nbp, schedule

    root = tmp_path_factory.mktemp("passages")
    pick_id = land_pick(root)
    schedule.load(root, spark, pick_id)

    src = root / "archive" / "nycbuspositions" / "2021" / "11" / "2021-11-07-bus-positions.csv.xz"
    src.parent.mkdir(parents=True)
    shutil.copy(FIXTURES / "nbp-2021-11-07-fragment.csv.xz", src)
    nbp.convert(root, "2021-11-07")

    # the DST pair (spec F): same UTC wall times on the spring-forward and fall-back
    # Sundays; FRAG's stop 304943 is scheduled 06:50:00 local
    for day8 in ("20240310", "20241103"):
        d = f"{day8[:4]}-{day8[4:6]}-{day8[6:]}"
        write_bronze(root, d, "10", [
            row("vd", FRAG, "Q59", day8, "304943", utc_s(int(day8[:4]), int(day8[4:6]), int(day8[6:]), 10, 52)),
            row("vd", FRAG, "Q59", day8, "503476", utc_s(int(day8[:4]), int(day8[4:6]), int(day8[6:]), 10, 54))])
    # envelope day (a Tuesday, WKD): S1 S2 [flap S1] S3 S5 - passage of 1, 2, 3 and an
    # interpolated 4; a second vehicle serves the same trip (multi-vehicle key).
    # Ticket 08: ve/ve2 serve T2 (headway vs the T1 arrivals; ve2 bunched), and a TU
    # series for va feeds the pred_* features and the S5 tu_last fallback row.
    t0 = utc_s(2024, 3, 12, 12, 0)
    write_bronze(root, "2024-03-12", "12",
                 [row("va", T1, "B41", "20240312", "S1", t0),
                  row("va", T1, "B41", "20240312", "S2", t0 + 60),
                  row("va", T1, "B41", "20240312", "S1", t0 + 120),
                  row("va", T1, "B41", "20240312", "S3", t0 + 180),
                  row("va", T1, "B41", "20240312", "S5", t0 + 240),
                  row("vb", T1, "B41", "20240312", "S1", t0),
                  row("vb", T1, "B41", "20240312", "S2", t0 + 90),
                  row("ve2", T2, "B41", "20240312", "S1", t0 + 120),
                  row("ve2", T2, "B41", "20240312", "S2", t0 + 180),
                  row("ve", T2, "B41", "20240312", "S1", t0 + 300),
                  row("ve", T2, "B41", "20240312", "S2", t0 + 420),
                  # CANCELED filtered before construction; an ADDED trip (absent from the
                  # static by definition) flows through the observed path flagged verbatim
                  row("vc", T1, "B41", "20240312", "S1", t0, rel="CANCELED"),
                  row("vc", T1, "B41", "20240312", "S2", t0 + 60, rel="CANCELED"),
                  row("vd2", "MV_C1-Weekday-099999_B41_999", "B41", "20240312", "S1", t0, rel="ADDED"),
                  row("vd2", "MV_C1-Weekday-099999_B41_999", "B41", "20240312", "S2", t0 + 60, rel="ADDED")])
    write_bronze_tu(root, "2024-03-12", "12", [
        (T1, "B41", "20240312", "va", "S5", t0 + 400, t0 - 1200),
        (T1, "B41", "20240312", "va", "S5", t0 + 400, t0 - 900),
        (T1, "B41", "20240312", "va", "S5", t0 + 300, t0 - 400),
        (T1, "B41", "20240312", "va", "S5", t0 + 330, t0 + 100),
        (T1, "B41", "20240312", "va", "S2", t0 + 140, t0 - 800),
        (T1, "B41", "20240312", "va", "S2", t0 + 160, t0 - 660)])
    # pick_gap day (2021-09-02: no service in the mini Pick): flips A->B->A->C; the
    # second passage of A is a flap artifact and is dropped by the first-occurrence
    # rule. vh (a different trip) passes A later: headway_obs needs no Pick.
    t1 = utc_s(2021, 9, 2, 12, 0)
    write_bronze(root, "2021-09-02", "12",
                 [row("vg", "GAP_TRIP", "B99", "20210902", s, t1 + k * 60, lat=40.61 + k * 3e-4)
                  for k, s in enumerate(["A", "B", "A", "C"])]
                 + [row("vh", "GAP2", "B99", "20210902", "A", t1 + 300),
                    row("vh", "GAP2", "B99", "20210902", "B", t1 + 360, lat=40.6103)])
    for day in ("2021-11-07", "2024-03-10", "2024-11-03", "2024-03-12", "2021-09-02"):
        events.events(root, spark, day)
    return root, pick_id


def ev_rows(root, day, cols="*", where="TRUE"):
    con = duck.connect()
    return con.execute(
        f"SELECT {cols} FROM read_parquet('{root}/silver/events/**/*.parquet', "
        f"hive_partitioning = true, hive_types_autocast = false) "
        f"WHERE service_date = '{day}' AND {where}").fetchall()


def test_sched_span_pick_gate(spark, tmp_path):
    """Resolver v2's gate at the join (spec D): a mid-pick revision joins only from its
    fetch date forward - a day before it keeps the earlier Pick, a day on/after it takes
    the revision (greatest published <= D+1)."""
    import hashlib
    import io
    import zipfile

    from raincheck import ref, schedule
    from raincheck.events import sched_span

    pick_a = land_pick(tmp_path)  # brooklyn/2021-10-01.zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in GTFS.items():  # same trips, T1's first stop retimed
            z.writestr(name, text.replace(f"{T1},07:00:00", f"{T1},07:01:00"))
    (tmp_path / "archive" / "static" / "brooklyn" / "2024-04-01.zip").write_bytes(buf.getvalue())
    ref.build_picks(tmp_path)
    pick_b = hashlib.sha1(buf.getvalue()).hexdigest()
    for p in (pick_a, pick_b):
        schedule.load(tmp_path, spark, p)

    for d, want in ((date(2024, 3, 12), pick_a), (date(2024, 4, 1), pick_b)):
        frame = sched_span(tmp_path, spark, d, d)
        assert frame is not None
        rows = frame.where(f"trip_id = '{T1}'").collect()
        assert {r.pick_id for r in rows} == {want}, d


def test_dst_fallback_fragment(pick_built):
    """The real 2021-11-07 archive fragment: trip GA_D1-Sunday-039500_Q59_902 flips
    304943 -> 503476 at 11:37:42Z / 12:09:14Z; scheduled 06:50:00 local = 11:50:00Z
    under the noon rule (noon EST after the fall-back)."""
    root, pick_id = pick_built
    ((arr, delay, censor, first, gap, pid, src, seq),) = ev_rows(
        root, "2021-11-07", "arrival_ts, delay_s, censor_width_s, is_first, pick_gap, "
        "pick_id, arrival_src, stop_sequence",
        f"trip_id = '{FRAG}' AND vehicle_id = 'MTA NYCT_4571'")
    assert arr == datetime(2021, 11, 7, 11, 53, 28, tzinfo=timezone.utc)
    assert delay == 208 and censor == 1892 and seq == 1
    assert first and not gap and pid == pick_id and src == "vp_passage"
    # unmatched trips on a covered date: rows kept, no pick_id, pick_gap stays false
    n_unmatched = ev_rows(root, "2021-11-07", "count(*)", "pick_id IS NULL")[0][0]
    assert n_unmatched > 0
    assert ev_rows(root, "2021-11-07", "count(*)", "pick_gap")[0][0] == 0


def test_noon_rule_dst_pair(pick_built):
    """06's required unit test: identical UTC arrivals on 2024-03-10 (spring forward)
    and 2024-11-03 (fall back) differ by exactly the DST hour in delay_s."""
    root, _ = pick_built
    (spring,) = ev_rows(root, "2024-03-10", "delay_s", f"trip_id = '{FRAG}'")
    (fall,) = ev_rows(root, "2024-11-03", "delay_s", f"trip_id = '{FRAG}'")
    assert spring[0] == 180        # sched 10:50:00Z (noon EDT 16:00Z - 12 h + 24600 s)
    assert fall[0] == 180 - 3600   # sched 11:50:00Z (noon EST 17:00Z - 12 h + 24600 s)


def test_envelope_flap_interpolation_and_key(pick_built):
    root, _ = pick_built
    got = ev_rows(root, "2024-03-12", "stop_sequence, stop_id, arrival_ts, censor_width_s, "
                  "interpolated, interp_k, arrival_src, segment_s, sched_segment_s, "
                  "segment_excess_s, n_vehicles_on_trip",
                  "vehicle_id = 'va' AND arrival_src <> 'tu_last' ORDER BY stop_sequence")
    t0 = datetime(2024, 3, 12, 12, 0, tzinfo=timezone.utc)
    assert [(r[0], r[1]) for r in got] == [(1, "S1"), (2, "S2"), (3, "S3"), (4, "S4")]
    arr = {r[0]: r[2] for r in got}
    assert arr[1] == t0 + timedelta(seconds=30)
    assert arr[3] == t0 + timedelta(seconds=210)
    assert arr[4] == t0 + timedelta(seconds=225)  # halfway by shape distance
    interp = {r[0]: (r[4], r[5], r[6]) for r in got}
    assert interp[3] == (False, None, "vp_passage")
    assert interp[4] == (True, 2, "interpolated")
    assert [r[7] for r in got] == [None, 120, 60, 15]          # segment_s
    assert [r[8] for r in got] == [None, 300, 300, 300]        # sched_segment_s
    assert [r[9] for r in got] == [None, -180, -240, -285]     # segment_excess_s
    assert all(r[10] == 2 for r in got)                        # both vehicles counted
    # multi-vehicle key: vb yields its own Passage of S1; the key set is unique
    assert ev_rows(root, "2024-03-12", "count(*)", "vehicle_id = 'vb'")[0][0] == 1
    n, uniq = ev_rows(root, "2024-03-12", "count(*), count(DISTINCT (trip_id, "
                      "stop_sequence, vehicle_id))")[0]
    assert n == uniq


def test_canceled_filtered_added_flagged(pick_built):
    root, _ = pick_built
    assert ev_rows(root, "2024-03-12", "count(*)", "vehicle_id = 'vc'")[0][0] == 0
    ((rel, gap, pid),) = ev_rows(root, "2024-03-12",
                                 "schedule_relationship, pick_gap, pick_id",
                                 "vehicle_id = 'vd2'")
    assert rel == "ADDED" and not gap and pid is None


def test_pick_gap_day(pick_built):
    root, _ = pick_built
    got = ev_rows(root, "2021-09-02", "stop_sequence, stop_id, pick_gap, pick_id, delay_s, "
                  "sched_segment_s, segment_s, cell",
                  "vehicle_id = 'vg' ORDER BY stop_sequence")
    assert [(r[0], r[1]) for r in got] == [(1, "A"), (2, "B")]  # A's flap repeat dropped
    assert all(r[2] and r[3] is None and r[4] is None and r[5] is None for r in got)
    assert got[1][6] == 60 and all(r[7] for r in got)  # observed segment; midpoint Cell
    # headway_obs needs no Pick: vh's previous different-vehicle arrival at (B99, A) is
    # vg's; the Pick-side columns stay NULL
    ((obs, sched, ok, fam),) = ev_rows(
        root, "2021-09-02", "headway_obs_s, headway_sched_s, wait_ok, family",
        "vehicle_id = 'vh'")
    assert obs == 300 and sched is None and ok is None and fam is None
    assert ev_rows(root, "2021-09-02", "headway_obs_s",
                   "vehicle_id = 'vg' AND stop_sequence = 1")[0][0] is None
    view = (root / "silver" / "events_view.sql").read_text()
    assert "pass_lo_ts" in view and "pred_last_ts" in view


def test_events_cells_in_ref(pick_built):
    """08-T7: every distinct events.cell is a ref cell (the fixture id list)."""
    root, _ = pick_built
    con = duck.connect()
    (n,) = con.execute(
        f"SELECT count(*) FROM (SELECT DISTINCT cell FROM read_parquet("
        f"'{root}/silver/events/**/*.parquet', hive_partitioning = true, "
        f"hive_types_autocast = false) WHERE cell IS NOT NULL) e "
        f"ANTI JOIN read_parquet('{FIXTURES}/ref-cells-ids.parquet') r USING (cell)").fetchone()
    assert n == 0


def test_baseline_prints_and_matched_idempotence(pick_built, spark, capsys):
    """The coverage / Passage-vs-Prediction regression bounds are printed on the fixture
    day, and a rerun of a matched day writes identical rows - including the TU day,
    where the 08 headway/pred columns are non-NULL (ticket 08 review)."""
    from raincheck import events

    root, _ = pick_built
    before = ev_rows(root, "2021-11-07", "*")
    events.events(root, spark, "2021-11-07")
    assert ev_rows(root, "2021-11-07", "*") == before
    out = capsys.readouterr().out
    assert "coverage baseline" in out and "[regression bound" in out
    assert "agreement n/a" in out  # the archive fragment has no TU rows
    before = sorted(ev_rows(root, "2024-03-12", "*"), key=str)
    events.events(root, spark, "2024-03-12")
    assert sorted(ev_rows(root, "2024-03-12", "*"), key=str) == before


def test_dst_noon_rule_pure(spark):
    """sched_ts on literals: the two 2024 DST transition days against a plain EST day."""
    from raincheck.enrich import sched_ts
    from pyspark.sql import functions as F

    df = spark.createDataFrame(
        [("20240310",), ("20241103",), ("20240115",)], "start_date string")
    got = {r.start_date: r.s for r in
           df.select("start_date", sched_ts(F.col("start_date"), F.lit(28800)).alias("s")).collect()}
    assert got["20240310"] == datetime(2024, 3, 10, 12, 0)   # 08:00 EDT
    assert got["20241103"] == datetime(2024, 11, 3, 13, 0)   # 08:00 EST
    assert got["20240115"] == datetime(2024, 1, 15, 13, 0)   # 08:00 EST


# --- ticket 08: headways, predictions, gold cell_hour_route ---------------------------

def test_headway_and_family(pick_built):
    root, _ = pick_built
    # same-trip followers excluded (06 measured 9): va and vb both serve T1, so neither
    # has a previous DIFFERENT-trip arrival at S1 - the multi-vehicle trip never reads
    # as its own 0 s headway
    for v in ("va", "vb"):
        assert ev_rows(root, "2024-03-12", "headway_obs_s",
                       f"vehicle_id = '{v}' AND stop_id = 'S1'")[0][0] is None
    # ve2 (T2): previous different-vehicle+trip arrival at S1 is vb's (t0+45) -> 105 s,
    # under half the 300 s scheduled headway -> bunched
    ((obs, sched, ok, b, fam),) = ev_rows(
        root, "2024-03-12", "headway_obs_s, headway_sched_s, wait_ok, bunched, family",
        "vehicle_id = 've2'")
    assert (obs, sched, ok, b, fam) == (105, 300, True, True, "headway")
    # ve (T2): the same-trip ve2 arrival is excluded -> prev is vb's -> 315 s
    ((obs, sched, ok, b),) = ev_rows(
        root, "2024-03-12", "headway_obs_s, headway_sched_s, wait_ok, bunched",
        "vehicle_id = 've'")
    assert (obs, sched, ok, b) == (315, 300, True, False)
    # family is the scheduled hour's cut: T1's 07:00 arrival sits alone in its hour
    # (one arrival, no headway -> 'schedule'); the next hour's median is 300 s
    assert ev_rows(root, "2024-03-12", "family",
                   "vehicle_id = 'va' AND stop_id = 'S1'")[0][0] == "schedule"
    assert ev_rows(root, "2024-03-12", "family",
                   "vehicle_id = 'va' AND stop_id = 'S2'")[0][0] == "headway"
    # the ADDED trip rides the observed path: NULL direction never joins matched groups
    assert ev_rows(root, "2024-03-12", "headway_obs_s", "vehicle_id = 'vd2'")[0][0] is None


def test_pred_features_and_tu_last(pick_built):
    root, _ = pick_built
    t0 = datetime(2024, 3, 12, 12, 0, tzinfo=timezone.utc)
    # va at S2 (arr t0+150): last pred t0+160, first (t0+140 fetched t0-800), one
    # change, 20 s range; at arr-600 the t0-660 fetch is in effect
    ((off, hor, rng, err, nch),) = ev_rows(
        root, "2024-03-12", "pred_last_off_s, pred_first_horizon_s, pred_range_s, "
        "pred_err_10min_s, pred_n_changes", "vehicle_id = 'va' AND stop_id = 'S2'")
    assert (off, hor, rng, err, nch) == (10, 940, 20, 10, 1)
    # the S5 fallback row: va reached the second-to-last stop, TU's last prediction
    # (t0+330) lies after the last Passage -> arrival_src tu_last, no ping bracket
    ((seq, src, arr, censor, last, delay, seg, exc, off5, err5, nch5, fam),) = ev_rows(
        root, "2024-03-12", "stop_sequence, arrival_src, arrival_ts, censor_width_s, "
        "is_last, delay_s, segment_s, segment_excess_s, pred_last_off_s, "
        "pred_err_10min_s, pred_n_changes, family",
        "vehicle_id = 'va' AND stop_id = 'S5'")
    assert seq == 5 and src == "tu_last" and arr == t0 + timedelta(seconds=330)
    assert censor is None and last and delay == 2730
    assert (seg, exc) == (105, -195)          # segments flow through the fallback row
    assert (off5, err5, nch5) == (0, -30, 2) and fam == "headway"
    # vb never reached the second-to-last stop: no fallback row for it
    assert ev_rows(root, "2024-03-12", "count(*)",
                   "vehicle_id = 'vb' AND stop_id = 'S5'")[0][0] == 0
    # archive era: every pred_* NULL (nycbuspositions has no stop-level TU)
    assert ev_rows(root, "2021-11-07", "count(*)", "(pred_last_off_s IS NOT NULL "
                   "OR pred_n_changes IS NOT NULL)")[0][0] == 0
    # the key stays unique with the fallback row in place
    n, uniq = ev_rows(root, "2024-03-12",
                      "count(*), count(DISTINCT (trip_id, stop_sequence, vehicle_id))")[0]
    assert n == uniq


@pytest.fixture(scope="module")
def gold_route(pick_built, spark):
    from raincheck import gold

    root, _ = pick_built
    gold.route(root, spark, "2024-03")   # 2024-03-10 (FRAG) + 2024-03-12 (envelope day)
    gold.route(root, spark, "2024-11")   # 2024-11-03 (FRAG, fall back)
    return root


def gr_rows(root, cols, where):
    con = duck.connect()
    return con.execute(
        f"SELECT {cols} FROM read_parquet('{root}/gold/cell_hour_route/**/*.parquet', "
        f"hive_partitioning = true, hive_types_autocast = false) WHERE {where}").fetchall()


def test_cell_hour_route_values(gold_route):
    root = gold_route
    n, uniq = gr_rows(root, "count(*), count(DISTINCT (month, cell, hour_end_utc, "
                      "route_id, direction_id))", "TRUE")[0]
    assert n > 0 and n == uniq
    # FRAG spring day: scheduled 10:50Z and arrived 10:53Z in the same Hour ->
    # coverage 1.0; delay 180 is neither late nor early
    ((frag_cell,),) = set(ev_rows(root, "2024-03-10", "cell", "TRUE"))
    ((ne, late, early, cov, vpc),) = gr_rows(
        root, "n_events, late_share, early_share, coverage, vp_coverage",
        f"month = '2024-03' AND cell = {frag_cell} AND route_id = 'Q59'")
    assert (ne, late, early, cov, vpc) == (1, 0.0, 0.0, 1.0, 1.0)
    # FRAG fall day: same UTC arrival, EST schedule -> -3420 s (early), and the
    # scheduled hour (12Z) no longer matches the arrival hour (11Z) -> coverage NULL
    ((late, early, cov),) = gr_rows(
        root, "late_share, early_share, coverage",
        f"month = '2024-11' AND cell = {frag_cell} AND route_id = 'Q59'")
    assert (late, early, cov) == (0.0, 1.0, None)
    # the S1/S2 cell (they share an H3 res-8 hex), hour 13Z, B41 dir 0: five events
    # (va S1+S2, vb S1, ve S1, ve2 S1), all late; EWT over the two rows with both
    # headways: (105^2+315^2)/(2*420) - (300^2+300^2)/(2*600) = 131.25 - 150 = -18.75;
    # the only observed segment is va S2's -180; the schedule put no arrivals in 13Z
    ((s1_cell,),) = set(ev_rows(root, "2024-03-12", "cell",
                                "vehicle_id = 'vb' AND stop_id = 'S1'"))
    ((ne, late, mse, ewt, bsh, wsh, cov, vpc),) = gr_rows(
        root, "n_events, late_share, mean_segment_excess_s, ewt_s, bunched_share, "
        "wait_ok_share, coverage, vp_coverage",
        f"month = '2024-03' AND cell = {s1_cell} AND route_id = 'B41' "
        f"AND hour_end_utc = TIMESTAMP '2024-03-12 13:00:00'")
    assert (ne, late) == (5, 1.0)
    assert mse == pytest.approx(-180.0) and ewt == pytest.approx(-18.75)
    assert (bsh, wsh) == (0.5, 1.0) and cov is None and vpc == 1.0
    # the S4/S5 cell holds va's interpolated S4 and tu_last S5 rows: vp_coverage 0
    ((s5_cell,),) = set(ev_rows(root, "2024-03-12", "cell",
                                "vehicle_id = 'va' AND stop_id = 'S5'"))
    ((ne, vpc),) = gr_rows(
        root, "n_events, vp_coverage",
        f"month = '2024-03' AND cell = {s5_cell} AND route_id = 'B41'")
    assert (ne, vpc) == (2, 0.0)


def test_cell_hour_route_idempotent_and_neighbour(gold_route, spark):
    import hashlib

    from raincheck import gold

    root = gold_route
    table = root / "gold" / "cell_hour_route"
    # key=str: a NULL direction_id ties with 0 on the tuple prefix and None < int raises
    before = sorted(gr_rows(root, "*", "month = '2024-03'"), key=str)
    snap = lambda: {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted((table / "month=2024-11").rglob("*.parquet"))}
    nov = snap()
    assert nov
    gold.route(root, spark, "2024-03")
    assert sorted(gr_rows(root, "*", "month = '2024-03'"), key=str) == before
    assert snap() == nov  # dynamic overwrite touches only the rebuilt month
