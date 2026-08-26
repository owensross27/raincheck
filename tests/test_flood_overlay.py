"""Flood-build ticket 17, testing seam 3: the two live impact overlays.

Three things here are contracts rather than behaviour, and each gets a test that FAILS
when the contract is broken rather than when the numbers move:

  * the ratio may only come from a CAPTURE-ERA baseline. The two partitions that exist on
    the real root are the 2021/2023 backfill windows, so the fixtures carry BOTH and the
    test asserts the backfill one produces no `ratio` even though its row would join.
  * `hour_of_week` is Monday-00-local = 0. Spark's `dayofweek` is 1=Sunday and DuckDB's is
    0=Sunday, so the two engines disagree about the same text (TRAPS) - this is pinned
    against `gold.baseline`'s grain on hand-checked dates, DST included.
  * the reads keep their projection and predicate INSIDE the read's own statement. That is
    a memory contract for a 768 MiB pod, so it is asserted on the module SOURCE: a
    `duck.table(...).filter(...)` here cost flood 15 five gigabytes.

Fixtures are written as real parquet with pyarrow and read through DuckDB exactly as the
module does, because the thing under test is a SQL statement, not a python loop.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raincheck import duck, flood_overlay as fo
from raincheck.paths import data_root

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
HOUR = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)   # a closed hour before NOW
MAIN = Path("/Users/ross/raincheck/data")
CELL_A, CELL_B = 613229524038975487, 613229524043169791


@pytest.fixture
def con():
    return duck.connect()


def _write(path: Path, rows: list[dict], schema: pa.Schema | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def speed_table(root: Path, rows: list[dict], month: str = "month=2026-08") -> None:
    _write(root / fo.BUS_TABLE / month / "part-0.parquet", rows, pa.schema([
        ("cell", pa.int64()), ("hour_end_utc", pa.timestamp("us", tz="UTC")),
        ("dist_m_sum", pa.float64()), ("dt_s_sum", pa.int64()),
        ("n_legs", pa.int64()), ("n_vehicles", pa.int64())]))


def base_table(root: Path, by_window: dict[str, list[dict]]) -> None:
    schema = pa.schema([("cell", pa.int64()), ("hour_of_week", pa.int16()),
                        ("speed_dry", pa.float64()), ("n_dry", pa.int64())])
    for window, rows in by_window.items():
        _write(root / fo.BASE_TABLE / f"window={window}" / "part-0.parquet", rows, schema)


def hours(root: Path, cells=(CELL_A, CELL_B)) -> None:
    """One dense earlier hour and one thin newest hour - the shape frontend 02 measured."""
    speed_table(root, [
        {"cell": c, "hour_end_utc": HOUR - timedelta(hours=1), "dist_m_sum": 1000.0,
         "dt_s_sum": 200, "n_legs": 3, "n_vehicles": 2} for c in cells
    ] + [{"cell": CELL_A, "hour_end_utc": HOUR, "dist_m_sum": 500.0, "dt_s_sum": 100,
          "n_legs": 1, "n_vehicles": 1}])


# ---- the grain -------------------------------------------------------------------------

def test_hour_of_week_is_monday_zero_local_the_grain_gold_wrote():
    """Monday 00:00 America/New_York = 0. Pinned on hand-checked dates rather than on a
    re-implementation of either engine's dayofweek."""
    # 2026-08-24 is a MONDAY. 04:00 UTC = 00:00 EDT -> 0.
    assert fo.hour_of_week(datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)) == 0
    assert fo.hour_of_week(datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)) == 6
    # Sunday is LAST, not first: 2026-08-23 23:00 EDT -> 6*24 + 23 = 167.
    assert fo.hour_of_week(datetime(2026, 8, 24, 3, 0, tzinfo=timezone.utc)) == 167
    # and it is a LOCAL grain: the same UTC hour in January is one hour off in EST
    assert fo.hour_of_week(datetime(2026, 1, 26, 10, 0, tzinfo=timezone.utc)) == 5


def test_hour_of_week_never_exceeds_the_week():
    t = datetime(2026, 8, 24, tzinfo=timezone.utc)
    got = {fo.hour_of_week(t + timedelta(hours=k)) for k in range(24 * 14)}
    assert got == set(range(168))


# ---- the bus overlay -------------------------------------------------------------------

def test_bus_keys_cells_by_the_h3_hex_string(con, tmp_path):
    hours(tmp_path)
    got = fo.bus(con, tmp_path, NOW)
    assert set(got["cells"]) == {format(CELL_A, "x")}
    assert got["hour_end_utc"] == HOUR
    # an int64 H3 id past 2^53 must never cross the boundary as a number
    assert all(isinstance(k, str) and not k.isdigit() or int(k, 16) > 2**53
               for k in got["cells"])


def test_bus_says_how_thin_the_newest_hour_is(con, tmp_path):
    """frontend 02: the newest closed hour is usually near-empty and painting it without
    saying so is a claim about the city."""
    hours(tmp_path)
    got = fo.bus(con, tmp_path, NOW)
    assert got["n_cells"] == 1 and got["densest_cells"] == 2
    assert got["densest_hour_end_utc"] == HOUR - timedelta(hours=1)


def test_bus_ships_no_ratio_without_a_capture_era_baseline(con, tmp_path):
    hours(tmp_path)
    base_table(tmp_path, {"w1": [{"cell": CELL_A, "hour_of_week": fo.hour_of_week(HOUR),
                                  "speed_dry": 2.5, "n_dry": 9}]})
    got = fo.bus(con, tmp_path, NOW)
    assert got["state"] == "no_baseline"
    # ABSENT, never null: MapLibre's ["has", p] is true on a null and interpolate errors
    assert "ratio" not in got["cells"][format(CELL_A, "x")]
    assert got["baseline"]["present"] is False
    assert "BACKFILL" in got["baseline"]["reason"]


def test_bus_ratio_comes_from_the_live_window_only(con, tmp_path):
    """The backfill row would join and is deliberately not read: `window` is a predicate
    inside the statement, so the 2021/2023 partitions are never opened."""
    hours(tmp_path)
    how = fo.hour_of_week(HOUR)
    base_table(tmp_path, {
        "w1": [{"cell": CELL_A, "hour_of_week": how, "speed_dry": 1.0, "n_dry": 9}],
        fo.LIVE_WINDOW: [{"cell": CELL_A, "hour_of_week": how, "speed_dry": 2.5,
                          "n_dry": fo.MIN_BASE_DAYS}]})
    got = fo.bus(con, tmp_path, NOW)
    assert got["state"] == "ok"
    cell = got["cells"][format(CELL_A, "x")]
    assert cell["speed_mps"] == 5.0                      # 500 m / 100 s
    assert cell["ratio"] == 2.0                          # 5.0 / 2.5, NOT 5.0 / 1.0
    assert cell["baseline_days"] == fo.MIN_BASE_DAYS


def test_bus_ratio_needs_two_same_weekday_baselines(con, tmp_path):
    """One day is not a baseline - the ticket's own rule, and `n_dry` is the count of
    distinct same-weekday hours behind that (cell, hour_of_week)."""
    hours(tmp_path)
    base_table(tmp_path, {fo.LIVE_WINDOW: [
        {"cell": CELL_A, "hour_of_week": fo.hour_of_week(HOUR), "speed_dry": 2.5,
         "n_dry": fo.MIN_BASE_DAYS - 1}]})
    got = fo.bus(con, tmp_path, NOW)
    assert got["state"] == "no_baseline"
    assert "ratio" not in got["cells"][format(CELL_A, "x")]


def test_bus_reads_only_hours_that_have_closed(con, tmp_path):
    hours(tmp_path)
    got = fo.bus(con, tmp_path, HOUR - timedelta(minutes=1))
    assert got["hour_end_utc"] == HOUR - timedelta(hours=1)


def test_bus_is_down_not_broken_when_the_table_is_absent(con, tmp_path):
    got = fo.bus(con, tmp_path, NOW)
    assert got["state"] == "down" and fo.BUS_TABLE in got["reason"]


# ---- the subway overlay ----------------------------------------------------------------

TU_SCHEMA = pa.schema([("feed", pa.string()), ("trip_id", pa.string()),
                       ("train_id", pa.string()), ("start_date", pa.string()),
                       ("stop_id", pa.string()), ("arrival_time", pa.int64()),
                       ("fetched_at", pa.int64())])
T0 = 1787709600      # 2026-08-26 02:00 UTC


def tu_table(root: Path, rows: list[dict], day="2026-08-26", hour="02") -> None:
    _write(root / fo.SUBWAY_TABLE / f"date={day}" / f"hour={hour}" / "part-00.parquet",
           rows, TU_SCHEMA)


def assets(root: Path, pairs=(("A01", "1"), ("A02", "2"))) -> None:
    rows = [{"asset_id": f"sta:{s}", "kind": "station", "name": f"station {s}",
             "complex_id": c, "lon": None, "lat": None, "cell": None,
             "gtfs_stop_id": [s]} for s, c in pairs]
    rows += [{"asset_id": f"stn:{c}", "kind": "complex", "name": f"complex {c}",
              "complex_id": c, "lon": -73.9, "lat": 40.7, "cell": CELL_A,
              "gtfs_stop_id": None} for _, c in pairs]
    _write(root / "ref" / "assets" / "part-0.parquet", rows, pa.schema([
        ("asset_id", pa.string()), ("kind", pa.string()), ("name", pa.string()),
        ("complex_id", pa.string()), ("lon", pa.float64()), ("lat", pa.float64()),
        ("cell", pa.int64()), ("gtfs_stop_id", pa.list_(pa.string()))]))


def _run(train: str, stop: str, arrival: int, seen: list[int], feed="subway") -> list[dict]:
    return [{"feed": feed, "trip_id": f"t{train}", "train_id": train,
             "start_date": "20260826", "stop_id": stop, "arrival_time": arrival,
             "fetched_at": t} for t in seen]


def test_subway_counts_only_rows_that_vanished_while_the_run_was_still_reported(con, tmp_path):
    """Three shapes, one of which is a dropped stop:
      A01N vanishes at T0+60 with its arrival still ahead, and the run is still there  -> DROPPED
      A02N vanishes with the run itself (the train finished)                           -> not
      A02S vanishes after its arrival had passed (the train made the stop)             -> not
    """
    assets(tmp_path)
    tu_table(tmp_path,
             _run("1", "A01N", T0 + 900, [T0, T0 + 60])            # gone at +120, arrival ahead
             + _run("1", "A02N", T0 + 900, [T0, T0 + 60, T0 + 120])
             + _run("2", "A02S", T0 + 30, [T0, T0 + 60])           # arrival passed before it went
             + _run("2", "A01N", T0 + 900, [T0, T0 + 60, T0 + 120]))
    got = fo.subway(con, tmp_path, datetime(2026, 8, 26, 4, 0, tzinfo=timezone.utc))
    assert got["state"] == "ok"
    assert got["dropped"] == 1 and got["planned"] == 4
    assert got["complexes"]["1"]["dropped"] == 1
    assert got["complexes"]["2"]["dropped"] == 0


def test_subway_places_every_complex_it_names(con, tmp_path):
    """A payload that names an asset a consumer cannot locate is a defect this repo has
    shipped twice - the point and the H3 hex Cell ride along."""
    assets(tmp_path)
    tu_table(tmp_path, _run("1", "A01N", T0 + 900, [T0, T0 + 60]))
    got = fo.subway(con, tmp_path, datetime(2026, 8, 26, 4, 0, tzinfo=timezone.utc))
    c = got["complexes"]["1"]
    assert c["lon"] == -73.9 and c["lat"] == 40.7
    assert c["cell"] == format(CELL_A, "x")     # the hex string, never the int64
    assert c["name"] == "complex 1"


def test_subway_counts_unresolved_stops_rather_than_hiding_them(con, tmp_path):
    assets(tmp_path)
    tu_table(tmp_path, _run("1", "Z99N", T0 + 900, [T0, T0 + 60]))
    got = fo.subway(con, tmp_path, datetime(2026, 8, 26, 4, 0, tzinfo=timezone.utc))
    assert got["unresolved_stops"] == 1 and got["n_complexes"] == 0


def test_subway_withholds_rel_under_the_planned_floor(con, tmp_path):
    """A complex the feed barely mentioned gets counts and NO colour."""
    assets(tmp_path, pairs=[("A01", "1"), ("A02", "2")])
    rows = []
    for k in range(fo.MIN_PLANNED + 2):     # complex 2: plenty of rows, some dropped
        rows += _run(f"b{k}", "A02N", T0 + 900, [T0, T0 + 60] + ([T0 + 120] if k % 2 else []))
    rows += _run("a1", "A01N", T0 + 900, [T0, T0 + 60])   # complex 1: one row only
    tu_table(tmp_path, rows)
    got = fo.subway(con, tmp_path, datetime(2026, 8, 26, 4, 0, tzinfo=timezone.utc))
    assert got["complexes"]["1"]["planned"] == 1
    assert "rel" not in got["complexes"]["1"]
    assert got["complexes"]["2"]["planned"] >= fo.MIN_PLANNED


def test_subway_reads_only_a_closed_hour(con, tmp_path):
    assets(tmp_path)
    tu_table(tmp_path, _run("1", "A01N", T0 + 900, [T0, T0 + 60]))
    inside = datetime(2026, 8, 26, 2, 59, tzinfo=timezone.utc)
    assert fo.subway(con, tmp_path, inside)["state"] == "no_rows"
    assert fo.subway(con, tmp_path, inside + timedelta(minutes=1))["state"] == "ok"


def test_subway_is_down_not_broken_when_the_capture_is_absent(con, tmp_path):
    got = fo.subway(con, tmp_path, NOW)
    assert got["state"] == "down" and fo.SUBWAY_TABLE in got["reason"]


def test_level_check_counts_overlapping_days_and_never_reads_a_control_number(tmp_path):
    tu_table(tmp_path, _run("1", "A01N", T0 + 900, [T0]), day="2026-08-26")
    agg = tmp_path / fo.CONTROL_AGG / "2026-08"
    agg.mkdir(parents=True)
    (agg / "2026-08-10.parquet").write_bytes(b"not parquet, and never opened")
    assert fo.level_check(tmp_path) | {} == fo.level_check(tmp_path)
    got = fo.level_check(tmp_path)
    assert got["overlapping_days"] == 0 and got["state"] == "no_overlap"
    (agg / "2026-08-26.parquet").write_bytes(b"still never opened")
    got = fo.level_check(tmp_path)
    assert got["overlapping_days"] == 1 and got["state"] == "compared"


def test_level_check_is_no_overlap_where_the_control_tree_does_not_exist(tmp_path):
    """On the cluster it never does - snapshots sit outside <root>/archive, the only tree
    `make coldpush` mirrors - and zero overlapping days is the honest answer there too."""
    tu_table(tmp_path, _run("1", "A01N", T0 + 900, [T0]))
    assert fo.level_check(tmp_path)["state"] == "no_overlap"


# ---- the documents ---------------------------------------------------------------------

def test_both_documents_carry_the_label_twice_and_the_never_input_sentence(tmp_path):
    docs = fo.docs(None, NOW)
    assert set(docs) == set(fo.FILES)
    for doc in docs.values():
        assert doc["label"] == fo.LABEL
        assert doc["strings"]["label"] == fo.LABEL
        assert "never" in doc["strings"]["never_a_detector_input"]
        assert doc["lineage"] == "mta-vehicles"
        assert doc["cycle_id"] == NOW.isoformat()


def test_a_cycle_that_read_nothing_still_publishes_an_honest_pair():
    """A family is all-or-none at publish time, and a reader must be able to tell "not read
    this cycle" from "read and empty"."""
    docs = fo.docs(None, NOW)
    for doc in docs.values():
        assert doc["state"] == "down" and doc["staleness"]["state"] == "DOWN"
        assert doc["reason"] == "not read this cycle"


def test_the_caveats_are_the_panels_text_and_carry_no_control_numbers():
    """The three readability claims ship as SENTENCES. Their counts are subwaydata-derived
    and stay in <root>/snapshots/subwaydata/impact/coverage.json - off every host."""
    text = " ".join(fo.CAVEATS_SUBWAY).lower()
    assert "median event day is indistinguishable" in text
    assert "weekend event days are unreadable" in text
    assert "only the tail reads" in text
    assert "ida" in text
    bus = " ".join(fo.CAVEATS_BUS).lower()
    assert "sparse" in bus and "one channel shared with the delay layer" in bus


def test_staleness_is_dated_at_the_reader_and_a_future_stamp_reads_down():
    fresh = fo._stale(NOW - timedelta(seconds=10), NOW, 3600)
    stale = fo._stale(NOW - timedelta(seconds=3601), NOW, 3600)
    ahead = fo._stale(NOW + timedelta(hours=1), NOW, 3600)
    assert (fresh["state"], stale["state"], ahead["state"]) == ("FRESH", "STALE", "DOWN")
    assert fo._stale(None, NOW, 3600)["state"] == "DOWN"


def test_the_subway_budget_still_agrees_with_the_archivers_part_window():
    """Pinned rather than imported: `archiver` pulls the protobuf decoders and this tick
    has no other reason to hold them in a 768 MiB pod."""
    from raincheck import archiver

    assert fo.SUBWAY_BUDGET_S == 3600 + archiver.WINDOW


def test_the_bus_budget_is_derived_from_the_nightly_tail():
    from raincheck import daily

    assert fo.BUS_BUDGET_S == (fo.NIGHTLY_H + daily.TAIL_H) * 3600


# ---- the memory contract ----------------------------------------------------------------

def test_every_read_keeps_its_projection_and_predicate_in_one_statement():
    """A memory contract, not style: `duck.table()` binds the path as a PARAMETER, so a
    filter applied outside the statement cannot be pushed into the scan - which cost
    flood 15's alert read 5,000 MiB and 9.4 s for six rows."""
    import ast

    # the AST and not the text: this module's own docstring NAMES `duck.table()` and the
    # relation chain in order to forbid them, and a substring check reads that sentence as
    # the violation (TRAPS: anchor on the call, not on the prose - release_check's retired
    # claim is a regex for exactly this reason).
    calls = [n.func.attr for n in ast.walk(ast.parse(Path(fo.__file__).read_text()))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert not {"table", "filter", "project"} & set(calls), calls
    for sql in (fo.BUS_HOURS_SQL, fo.BUS_CELLS_SQL, fo.BUS_BASE_SQL, fo.SUBWAY_SQL,
                fo.COMPLEX_SQL):
        assert "{read}" in sql and "WHERE" in sql.upper()


def test_the_module_never_imports_the_subwaydata_reader():
    """subwaydata.nyc publishes no data licence, so its derived numbers are local-only.
    `release_check` asserts this for flood_panel; the same rule holds one module out."""
    import re

    src = Path(fo.__file__).read_text()
    assert re.search(r"^\s*(?:from\s+raincheck\s+import|import)\s+.*flood_impact",
                     src, re.M) is None
    assert not hasattr(fo, "flood_impact")


def test_read_never_raises_and_reports_the_reason(con, tmp_path):
    """The tick this rides inside is a panel, not a job: an outage is a field."""
    got = fo.read(con, tmp_path, NOW)
    assert set(got) == {"bus", "subway"}
    assert got["bus"]["state"] == "down" and got["subway"]["state"] == "down"


def test_read_survives_a_reader_that_throws(con, tmp_path, monkeypatch):
    monkeypatch.setattr(fo, "bus", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    got = fo.read(con, tmp_path, NOW)
    assert got["bus"]["state"] == "down" and "boom" in got["bus"]["error"]
    assert got["subway"]["state"] == "down"          # the other side is untouched


# ---- against the real root ---------------------------------------------------------------

@pytest.mark.skipif(not (MAIN / "gold" / "cell_hour_speed").exists(),
                    reason="needs the main data root (RAINCHECK_ARCHIVE_ROOT)")
def test_the_real_bus_read_is_sparse_at_the_head_and_greyed(con):
    got = fo.bus(con, data_root(), datetime.now(timezone.utc))
    assert got["state"] in ("ok", "no_baseline")
    assert 0 < got["n_cells"] <= got["densest_cells"]
    if got["state"] == "no_baseline":
        assert all("ratio" not in c for c in got["cells"].values())
    assert all(int(k, 16) > 2**53 for k in got["cells"])


@pytest.mark.skipif(not (MAIN / "archive" / "subway_tu").exists(),
                    reason="needs the main data root (RAINCHECK_ARCHIVE_ROOT)")
def test_the_real_subway_read_runs_on_the_newest_closed_hour(con):
    root = data_root()
    days = fo._partitions(root, fo.SUBWAY_TABLE, "date")
    newest = max(datetime.fromisoformat(f"{d[len('date='):]}T00:00:00+00:00")
                 for d in days) + timedelta(days=2)
    got = fo.subway(con, root, newest)
    assert got["state"] == "ok" and got["n_complexes"] > 0
    assert got["dropped"] <= got["planned"]
    assert got["level"]["state"] in ("no_overlap", "compared")
    assert json.dumps(got, default=str)          # every leaf is JSON-encodable
