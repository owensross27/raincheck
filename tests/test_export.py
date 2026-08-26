"""14-1 tier 1 (the fixture twin of the slice gate) and 14-4 (the page smoke), ticket 13.

Seam A: `raincheck.export.run()` runs against a pytest temp data root seeded with a
three-Cell fixture Gold, and the written files are read back as JSON. No Spark, no JVM -
the export is DuckDB only.

The fixture Cells, their geometry and their Zone assignment are copied verbatim from the
real `ref/cells` / `ref/cell_zone` / `ref/zones` so the fixture exercises the same shapes
the slice does: two Central Park Cells in Zone 43 and one Cell in no taxi zone at all
(the absent-key path for zone_id / zone_name / borough).

The invariants are 14-1's: no property value is null, every present value is finite,
every headline row carries a non-empty estimand, a numeric band pair and n_cells_hidden,
the fixture Cell 882a100895fffff has w1_dry > 0 and an Ida hour property, and a re-export
is byte-identical.
"""
import json
import math
import shutil
import re
import statistics
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from raincheck import contract, duck, export, publish, query
from raincheck.ref import WINDOWS

CP1 = "882a100895fffff"   # Central Park, Zone 43 - 14-1's named fixture Cell
CP2 = "882a100897fffff"   # its neighbour, same Zone
NOZ = "882a100b01fffff"   # a Cell in no taxi zone: zone_id / zone_name / borough absent

CELLS = {
    CP1: (613229522952650751, 43,
          "POLYGON ((-73.96788698273323 40.786544974433205, -73.974271526561 40.78549167493182, "
          "-73.976239351894 40.781030511439496, -73.97182354441321 40.77762297916075, "
          "-73.96544002797856 40.77867605891166, -73.96347129174404 40.78313689066177, "
          "-73.96788698273323 40.786544974433205))"),
    CP2: (613229522954747903, 43,
          "POLYGON ((-73.97182354441321 40.77762297916075, -73.97379126878796 40.773162293989735, "
          "-73.96937638737819 40.76975502028317, -73.96299389803004 40.77080788035517, "
          "-73.96102526311756 40.77526823378265, -73.96544002797856 40.77867605891166, "
          "-73.97182354441321 40.77762297916075))"),
    NOZ: (613229523602767871, None,
          "POLYGON ((-74.01552122403525 40.90702202551628, -74.0110905506713 40.90361037713643, "
          "-74.00469055907394 40.904666981502636, -74.00272020863859 40.909135455117955, "
          "-74.00715076643732 40.91254765611344, -74.01355179034985 40.911490830847754, "
          "-74.01552122403525 40.90702202551628))"),
}
ZONE = (43, "Central Park", "Manhattan",
        "POLYGON ((-73.9816 40.7684, -73.9582 40.8006, -73.9492 40.7969, -73.9726 40.7649, "
        "-73.9816 40.7684))")
IDA = datetime(2021, 9, 2, 3, tzinfo=timezone.utc)   # the storm hour every layer keys on
# two window bins, Monday 08:00 and Friday 14:00 America/New_York, both inside W1
WINDOW_BINS = (datetime(2021, 8, 16, 12, tzinfo=timezone.utc),
               datetime(2021, 8, 20, 18, tzinfo=timezone.utc))


def _rows():
    """(speed rows, precip rows) for the fixture window.

    Two hour-of-week bins, because the window layer and the storm layer need different
    shapes and the earlier fixture accidentally gave the window layer none:

    BIN A (Ida's own bin, Wednesday 23:00 local): nine weekly dry Hours around Ida plus the
    Ida Hour itself, wet and slow. This is what the storm-hour layer scores against.
    BINS B and C (Monday 08:00 and Friday 14:00 local): four weekly WET Hours followed by
    four weekly DRY Hours in the SAME bin, so each wet Cell-hour has a dry
    same-hour-of-week baseline to be scored against. Two bins, not one, so the eight wet
    weeks outweigh the single dramatic Ida anomaly and the per-Cell interval is narrow
    enough to clear the publish gate - otherwise the per-Cell window layer is present in
    the headline but absent from every Cell. The previous fixture put each wet Hour's dry
    counterpart one day later, in a different hour-of-week bin, so every weekly wet
    Cell-hour was dropped by the baseline join and the whole window layer was untested.

    NOZ is given a milder slowdown and heavier rain on one wet week than the two Central
    Park Cells, so the median-Cell figure and the heavy-rain lag series are not degenerate.
    """
    speed, precip = [], []
    dry = {CP1: 4.0, CP2: 5.0, NOZ: 6.0}

    def add(cell, h, n_legs, speed_mps, mm, mm_prev=0.0, mm_6h=0.0):
        speed.append((cell, h, n_legs, speed_mps * 3600, 3600))
        precip.append((cell, h, mm, mm_prev, mm_6h))

    for hexid, (cell, _, _) in CELLS.items():
        # BIN A: the Ida bin's dry side, one Hour a week, with scatter so the bin has a
        # real standard error rather than a degenerate zero
        for wk in range(9):
            h = IDA + timedelta(weeks=wk - 2)
            if h == IDA:
                continue
            add(cell, h, 40 + wk, dry[hexid] * (1 + 0.02 * ((wk % 3) - 1)), 0.0)
        # BIN A: the storm Hour itself
        add(cell, IDA, 25, dry[hexid] * (0.5 if hexid in (CP1, CP2) else 0.9), 30.0, 5.0, 40.0)
        # BINS B and C: four wet weeks then four dry weeks, all inside one hour-of-week bin
        for start in WINDOW_BINS:
            for wk in range(4):
                heavy = 12.0 if hexid == NOZ and wk == 0 else 2.0
                add(cell, start + timedelta(weeks=wk), 30,
                    dry[hexid] * (0.9 if hexid in (CP1, CP2) else 0.97), heavy)
            for wk in range(4, 8):
                add(cell, start + timedelta(weeks=wk), 30,
                    dry[hexid] * (1 + 0.03 * ((wk % 3) - 1)), 0.0)
    return speed, precip


def seed(root: Path) -> None:
    """Write the fixture Gold / Silver / ref tables with DuckDB, the way the export reads
    them: Hive-partitioned parquet, GeoParquet geometry for ref/cells and ref/zones."""
    import duckdb

    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute("LOAD spatial")
    speed, precip = _rows()

    def write(name: str, sql: str, partition: str | None = None) -> None:
        # every dataset is a DIRECTORY the export opens as <root>/<name>/**/*.parquet, so an
        # unpartitioned table still gets one part file inside its own directory
        out = root / name
        out.mkdir(parents=True, exist_ok=True)
        if partition:
            con.execute(f"COPY ({sql}) TO '{out}' (FORMAT parquet, PARTITION_BY ({partition}))")
        else:
            con.execute(f"COPY ({sql}) TO '{out / 'part-0.parquet'}' (FORMAT parquet)")

    con.execute("CREATE TABLE s(cell BIGINT, hour_end_utc TIMESTAMPTZ, n_legs BIGINT, "
                "dist_m_sum DOUBLE, dt_s_sum BIGINT)")
    con.executemany("INSERT INTO s VALUES (?, ?, ?, ?, ?)", speed)
    con.execute("CREATE TABLE p(cell BIGINT, hour_end_utc TIMESTAMPTZ, mm_1h FLOAT, "
                "mm_1h_prev FLOAT, mm_6h FLOAT)")
    con.executemany("INSERT INTO p VALUES (?, ?, ?, ?, ?)", precip)

    write("gold/cell_hour_speed",
          "SELECT cell, hour_end_utc, 'B41' AS route_id, 'local' AS route_class, n_legs, "
          "1 AS n_vehicles, dist_m_sum, dt_s_sum, 0 AS n_dropped_terminal, 0 AS n_dropped_dark, "
          "strftime(hour_end_utc, '%Y-%m') AS month FROM s", "month")
    write("silver/precip_cell_hourly",
          "SELECT cell, hour_end_utc, mm_1h, mm_1h_prev, 0.0::FLOAT AS mm_3h, mm_6h, "
          "0.0::FLOAT AS mm_24h, 24::TINYINT AS n_hours_24h, 20.0::FLOAT AS t2m_c, "
          "strftime(hour_end_utc, '%Y-%m') AS month, 'aorc' AS src FROM p", "month, src")
    # the baseline table's own grain, built from the same dry mask gold.baseline() uses
    write("gold/cell_hourofweek_baseline", """
        SELECT cell,
               -- gold.baseline() numbers Monday 00 local = 0. It gets there with Spark's
               -- (dayofweek + 5) % 7 (Spark: 1=Sunday); the same numbering in DuckDB
               -- (0=Sunday) is (dayofweek + 6) % 7. The fixture stands in for the
               -- Spark-written table, so it must carry Spark's numbering.
               (((dayofweek(timezone('America/New_York', hour_end_utc)) + 6) % 7) * 24
                 + hour(timezone('America/New_York', hour_end_utc)))::SMALLINT AS hour_of_week,
               sum(dist_m_sum) / sum(dt_s_sum) AS speed_dry,
               count(DISTINCT hour_end_utc) AS n_dry, sum(n_legs) AS n_legs_dry,
               sum(dist_m_sum) AS dist_m_sum_dry, sum(dt_s_sum) AS dt_s_sum_dry,
               'w1' AS "window"
        FROM s JOIN p USING (cell, hour_end_utc)
        WHERE mm_1h < 0.1 AND mm_1h_prev < 0.1 AND mm_6h < 0.5
        GROUP BY 1, 2""", '"window"')

    vals = ", ".join(f"({c}, '{wkt}')" for c, _, wkt in CELLS.values())
    write("ref/cells", f"SELECT cell, ST_GeomFromText(wkt) AS geometry, "
                      f"ST_X(ST_Centroid(ST_GeomFromText(wkt))) AS centroid_lon, "
                      f"ST_Y(ST_Centroid(ST_GeomFromText(wkt))) AS centroid_lat "
                      f"FROM (VALUES {vals}) t(cell, wkt)")
    cz = ", ".join(f"({c}, {'NULL' if z is None else z}, "
                   f"{'NULL' if z is None else repr(ZONE[2])})" for c, z, _ in CELLS.values())
    write("ref/cell_zone",
          f"SELECT cell, zone_id::SMALLINT AS zone_id, borough FROM (VALUES {cz}) t(cell, zone_id, borough)")
    write("ref/zones", f"SELECT {ZONE[0]}::SMALLINT AS zone_id, {ZONE[2]!r} AS borough, "
                       f"{ZONE[1]!r} AS zone_name, ST_GeomFromText({ZONE[3]!r}) AS geometry")
    lo, hi = WINDOWS[0]
    write("ref/calendar", f"SELECT d::DATE AS service_date, true AS school_in_session, "
                          f"false AS holiday, false AS unga_week "
                          f"FROM generate_series(DATE '{lo}', DATE '{hi}', INTERVAL 1 DAY) g(d)")
    con.close()


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    root = tmp_path_factory.mktemp("root")
    seed(root)
    out = tmp_path_factory.mktemp("web")
    written = export.run(root, out)
    return {name: json.loads(path.read_text()) for name, path in written.items()}, root, out


def props(cells: dict) -> dict:
    return {f["id"]: f["properties"] for f in cells["features"]}


# ------------------------------------------------------------------ 14-1, tier 1 twin
def test_windows_in_sql_match_ref_windows():
    """The export's window bounds are literals in the SQL (both files stay
    standalone-runnable); this is the guard against them drifting from raincheck.ref.WINDOWS
    - and against the two SQL files drifting from EACH OTHER, which is what would make a
    route line and the Cell under it disagree about which two months they describe."""
    for sql_path in (export.SQL, export.GEO_SQL):
        sql = sql_path.read_text()
        for start, end in WINDOWS:
            assert f"'{start} 00:00:00+00'" in sql, sql_path.name
            assert f"'{end + timedelta(days=1)} 00:00:00+00'" in sql, sql_path.name


def test_one_feature_per_footprint_cell(exported):
    files, _, _ = exported
    assert {f["id"] for f in files["cells.geojson"]["features"]} == set(CELLS)
    assert files["cells.geojson"]["type"] == "FeatureCollection"


def test_no_property_is_null_and_every_value_is_finite(exported):
    """The pure-SQL writer's whole point: unpublishable means the key is ABSENT. A null
    would make MapLibre's ["has", p] true and break the grey guard."""
    files, _, _ = exported
    for cell, p in props(files["cells.geojson"]).items():
        for key, value in p.items():
            assert value is not None, f"{cell}.{key} is null"
            if isinstance(value, float):
                assert math.isfinite(value), f"{cell}.{key} is {value}"


def test_fixture_cell_has_a_dry_level_and_an_ida_hour(exported):
    files, _, _ = exported
    p = props(files["cells.geojson"])[CP1]
    assert p["w1_dry"] > 0
    assert p["r090203"] < 1.0                    # the Ida hour, and it is a slowdown
    assert p["lo090203"] < p["r090203"] < p["hi090203"]
    assert p["mm090203"] == 30.0 and p["lag090203"] == 0
    assert p["zone_name"] == "Central Park" and p["borough"] == "Manhattan"


def test_cell_outside_a_taxi_zone_omits_the_zone_keys(exported):
    files, _, _ = exported
    p = props(files["cells.geojson"])[NOZ]
    assert "zone_id" not in p and "zone_name" not in p and "borough" not in p
    assert p["w1_dry"] > 0                        # but it still carries its own Speed


def test_a_too_wide_interval_omits_the_ratio_and_keeps_the_rain(exported):
    """The gate is interval width. Squeeze it to nothing and every ratio must vanish while
    H_mm and H_lag - which are precipitation, not a Speed claim - stay."""
    _, root, out_dir = exported
    tight = out_dir.parent / "tight"
    cells = json.loads(export.run(root, tight, gate_width=0.0001)["cells.geojson"].read_text())
    for p in props(cells).values():
        assert not [k for k in p if k.startswith(("r0", "lo0", "hi0")) or k.endswith("_ratio")]
        assert "w1_dry" in p                      # a level is not a wet/dry claim
    assert props(cells)[CP1]["mm090203"] == 30.0


def test_every_headline_row_carries_its_estimand_band_and_hidden_count(exported):
    files, _, _ = exported
    head = files["headline.json"]
    assert head["rows"], "no headline rows"
    for row in head["rows"]:
        assert row["estimand"].strip()
        assert row["median_cell_estimand"].strip()
        assert isinstance(row["band"], list) and len(row["band"]) == 2
        assert all(isinstance(b, (int, float)) for b in row["band"])
        assert isinstance(row["n_cells_hidden"], int)
        assert row["lo"] <= row["value"] <= row["hi"]
    assert head["preview_note"] and head["gate_width"] == export.GATE_WIDTH
    assert "AORC" in head["precip_src"]


def test_the_chord_band_only_moves_when_the_arms_change_speed_class(exported):
    """band[1] is ratio * r(wet)/r(dry) by research 10 B1b's class medians; two arms in one
    class must leave the ratio untouched rather than inventing a correction."""
    files, _, _ = exported
    for row in files["headline.json"]["rows"]:
        assert row["band"][0] == row["value"]
        assert row["band"][1] >= row["value"] - 1e-9   # the correction never worsens a slowdown


def test_zones_are_published_with_names(exported):
    files, _, _ = exported
    feats = files["zones.geojson"]["features"]
    assert len(feats) == 1                        # the fixture ships one zone; 263 is tier 2
    assert all(f["properties"]["zone_name"] for f in feats)
    assert feats[0]["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_re_export_is_byte_identical(exported):
    _, root, out_dir = exported
    again = out_dir.parent / "again"
    for name, path in export.run(root, again).items():
        assert path.read_bytes() == (out_dir / name).read_bytes(), f"{name} is not reproducible"


def test_property_keys_are_written_in_sorted_order(exported):
    """Byte-identity alone does not pin the writer's ORDER BY: two runs in one process pick
    the same arbitrary order, so dropping it stays green there while the real slice comes
    out unsorted (measured). Sorted keys are the actual contract - it is what makes the
    exported artifact diffable across machines."""
    files, _, _ = exported
    for feature in files["cells.geojson"]["features"]:
        keys = list(feature["properties"])
        assert keys[0] == "cell", "the Cell id is written first"
        assert keys[1:] == sorted(keys[1:]), f"{feature['id']} properties are not sorted"


def test_hour_of_week_puts_monday_00_local_at_zero():
    """The bug this pins: gold.baseline() reaches "Monday 00 local = 0" with SPARK's
    dayofweek (1=Sunday), and the identical text in DuckDB (0=Sunday) lands one local day
    out - it reproduced 0 of 178,826 real baseline rows. A fixture cannot catch that,
    because a fixture built with the same expression is self-consistent under either
    convention. So this reads the offset out of the SQL and checks it against FIXED DATES."""
    import duckdb

    pat = (r"\(\(dayofweek\(timezone\('America/New_York', s\.hour_end_utc\)\)"
           r"\s*\+\s*(\d+)\)\s*%\s*7\)")
    offs = set()
    for sql_path in (export.SQL, export.GEO_SQL):
        m = re.search(pat, sql_path.read_text())
        assert m, f"could not find the hour_of_week expression in {sql_path.name}"
        offs.add(int(m.group(1)))
    # frontend2 03 rebuilds the same baseline keyed by route, so BOTH files carry the
    # expression and a route line joined one local day out of its own Cell would be
    # invisible - the numbers would simply be somebody else's hour.
    assert len(offs) == 1, f"the two SQL files disagree about hour_of_week: {offs}"
    off = offs.pop()
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    hw = f"((dayofweek(t) + {off}) % 7) * 24 + hour(t)"
    # 2021-08-16 is a Monday and 2021-08-22 a Sunday, both EDT (UTC-4)
    got = con.execute(
        f"SELECT {hw} FROM (VALUES (TIMESTAMP '2021-08-16 00:00:00'), "
        f"(TIMESTAMP '2021-08-16 08:00:00'), (TIMESTAMP '2021-08-17 00:00:00'), "
        f"(TIMESTAMP '2021-08-22 23:00:00')) v(t)").fetchall()
    assert [r[0] for r in got] == [0, 8, 24, 167], (
        f"offset {off} gives {[r[0] for r in got]}, want Monday 00 -> 0 ... Sunday 23 -> 167")


def test_the_window_layer_publishes_per_cell_ratios_with_intervals(exported):
    """The window layer is the export's headline claim. It was entirely dead under the
    first fixture (every wet Hour's baseline bin was a day off, so the join dropped them
    all) and both a 999x interval and a null-instead-of-absent property shipped green."""
    files, _, _ = exported
    p = props(files["cells.geojson"])[CP1]
    for key in ("w1_ratio", "w1_lo", "w1_hi", "w1_nwet", "w1_nev", "w1_dry", "w1_ndry"):
        assert key in p, f"{key} missing: the window layer is not being exercised"
    assert p["w1_lo"] < p["w1_ratio"] < p["w1_hi"]
    assert p["w1_nev"] >= 2, "an interval needs at least two wet-event clusters"
    assert p["w1_ratio"] < 1.0, "the fixture's wet Hours are slower than its dry baseline"
    row = next(r for r in files["headline.json"]["rows"] if r["layer"] == "w1")
    assert row["n_cells"] > 0 and row["lo"] < row["value"] < row["hi"]
    assert row["sensitivity_day"]["lo"] < row["value"] < row["sensitivity_day"]["hi"]


def test_the_published_interval_is_the_clustered_t_interval(exported):
    """An oracle for the interval MAGNITUDE, not just its ordering: recompute CP1's window
    half-width here, independently of export.sql, from the fixture's own rows. Ordering
    assertions alone leave the whole tcrit table free - replacing every value with 1.96
    passed all twelve tests before this."""
    import duckdb

    files, root, _ = exported
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    rows = con.execute(f"""
        SELECT s.dt_s_sum, (s.dist_m_sum / s.dt_s_sum) / b.speed_dry
        FROM read_parquet('{root}/gold/cell_hour_speed/**/*.parquet', hive_partitioning = true) s
        JOIN read_parquet('{root}/silver/precip_cell_hourly/**/*.parquet', hive_partitioning = true) p
             ON p.cell = s.cell AND p.hour_end_utc = s.hour_end_utc
        JOIN read_parquet('{root}/gold/cell_hourofweek_baseline/**/*.parquet', hive_partitioning = true) b
             ON b.cell = s.cell AND b.hour_of_week =
                ((dayofweek(timezone('America/New_York', s.hour_end_utc)) + 6) % 7) * 24
                 + hour(timezone('America/New_York', s.hour_end_utc))
        WHERE s.cell = {CELLS[CP1][0]} AND p.mm_1h >= 1.0""").fetchall()

    # every fixture wet Hour is its own wet event (they are days apart, far beyond the
    # 6-dry-Hour bridge), so the cluster-robust weighted variance reduces to the ordinary
    # SEM of the anomalies - which is what makes this an independent check
    weights = [float(w) for w, _ in rows]
    anomalies = [float(a) for _, a in rows]
    assert len(anomalies) >= 5 and len(set(weights)) == 1
    mean = statistics.fmean(anomalies)
    se = statistics.stdev(anomalies) / math.sqrt(len(anomalies))
    t = {8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179}[len(anomalies) - 1]

    p = props(files["cells.geojson"])[CP1]
    assert p["w1_ratio"] == pytest.approx(mean, abs=0.001)
    assert (p["w1_hi"] - p["w1_lo"]) / 2 == pytest.approx(t * se, abs=0.002)


def test_the_chord_band_applies_the_measured_class_medians(exported):
    """band() straight from the SQL, so the class table and its lookup are pinned even
    though the fixture's two citywide arms sit in one class and cancel to 1.0."""
    import duckdb

    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute("LOAD spatial")
    con.execute("SET VARIABLE root = ?", [str(exported[1])])
    con.execute("SET VARIABLE gate_width = ?", [export.GATE_WIDTH])
    con.execute(export.split(export.SQL.read_text())[0])
    band = lambda r, vw, vd: con.execute(f"SELECT band({r}, {vw}, {vd})").fetchone()[0]
    # research 10 B1b class medians: <3 -> 1.164, 3-6 -> 1.025, 6-10 -> 1.015, >10 -> 1.016
    assert band(1.0, 2.0, 4.0) == pytest.approx(1.164 / 1.025, abs=0.001)
    assert band(1.0, 4.0, 4.0) == 1.0            # one class, no correction invented
    assert band(0.745, 2.9, 3.3) == pytest.approx(0.846, abs=0.002)  # 10 section 2's own worked case
    assert band(1.0, 2.0, 4.0) > 1.0, "the correction must never deepen a slowdown"


def test_the_rain_lag_table_is_published_per_intensity(exported):
    """spec I's rain-lag table, and the page's curve. Untested at either tier before this,
    and the first fixture made the two intensity series byte-identical."""
    files, _, _ = exported
    lag = files["headline.json"]["lag"]
    assert lag, "no rain-lag rows"
    for r in lag:
        assert r["rain"] in ("all", "heavy") and r["lag_h"] >= 0
        assert r["estimand"].strip() and r["n_legs"] > 0 and math.isfinite(r["ratio"])
    by = {(r["window"], r["rain"], r["lag_h"]): r for r in lag}
    a = by[("w1", "all", 0)]
    h = by[("w1", "heavy", 0)]
    assert h["n_legs"] < a["n_legs"], "the heavy series must be a strict subset"
    assert h["ratio"] != a["ratio"], "the two intensity series must not be the same numbers"


def test_no_headline_value_is_ever_null(exported):
    """The absent-key contract is the whole file's contract, not cells.geojson's alone."""
    files, root, out_dir = exported
    tight = json.loads(export.run(root, out_dir.parent / "nulls", gate_width=0.0001)["headline.json"].read_text())
    for row in files["headline.json"]["rows"] + tight["rows"]:
        for key, value in row.items():
            assert value is not None, f"headline row {row['layer']} has a null {key}"
        assert row["n_cells"] == 0 or "median_cell" in row
    assert all(r["n_cells"] == 0 for r in tight["rows"]), "the tight gate should publish nothing"


def test_the_default_gate_width_is_the_swept_default(exported):
    """The width-behaviour test passes its own gate, so nothing pinned the production
    constant: setting it to 100.0 shipped every unpublishable value and stayed green."""
    files, _, _ = exported
    assert export.GATE_WIDTH == 0.30
    p = props(files["cells.geojson"])[CP1]
    assert p["w1_hi"] - p["w1_lo"] < export.GATE_WIDTH


# ------------------------------------------------------------------------ 14-4 smoke
def test_the_stdlib_server_answers_200_for_the_page_and_its_files(exported, tmp_path):
    """14-4: `make web` is `python -m http.server --directory web`. The page, both vendored
    files and the exported data files must all answer 200 - the demo has no other server."""
    _, _, out_dir = exported
    web = tmp_path / "web"
    (web / "files").mkdir(parents=True)
    (web / "vendor").mkdir()
    # the page is six ES modules now (frontend2 01): serve what the `site` family names,
    # never a hand list - the vendored pair below is staged separately because it is
    # gitignored and may not be present
    page = [k for k in publish.FAMILIES["site"].files if not k.startswith("vendor/")]
    for name in page:
        (web / name).write_bytes((export.REPO / "web" / name).read_bytes())
    for name in ("cells.geojson", "headline.json", "zones.geojson"):
        (web / "files" / name).write_bytes((out_dir / name).read_bytes())
    for name in ("maplibre-gl.js", "maplibre-gl.css"):
        src = export.REPO / "web" / "vendor" / name
        if not src.exists():
            pytest.skip(f"{name} not vendored: run make vendor")
        (web / "vendor" / name).write_bytes(src.read_bytes())

    # the same stdlib handler `make web` runs, in-process on an ephemeral port: parsing the
    # subprocess banner deadlocks because http.server block-buffers it into a pipe
    handler = partial(SimpleHTTPRequestHandler, directory=str(web))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        for path in [*page, "vendor/maplibre-gl.js", "vendor/maplibre-gl.css",
                     "files/cells.geojson", "files/headline.json", "files/zones.geojson"]:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/{path}", timeout=10) as r:
                assert r.status == 200, path
                body = r.read()
            assert body, path
            if path.endswith((".json", ".geojson")):
                json.loads(body)
        with pytest.raises(urllib.error.HTTPError):   # the live files are ticket 14's
            urllib.request.urlopen(f"http://127.0.0.1:{port}/files/live.geojson", timeout=10)
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_page_loads_only_vendored_scripts():
    """No CDN at demo time (spec L): every script and stylesheet the page PULLS is local.

    Scoped to the two tags that FETCH - `<script src>` and `<link href>` - rather than to
    every attribute spelled src or href. An `<a href>` is navigation the visitor chooses,
    and frontend2 02's basemap makes one of them mandatory rather than optional: the OSMF
    attribution guidelines require the credit to link to openstreetmap.org/copyright, so a
    rule against every remote href is a rule against shipping the basemap at all. The
    demo-time property is unchanged - nothing is fetched off this box."""
    html = (export.REPO / "web" / "index.html").read_text()
    pulls = re.findall(r"""<(?:script|link)\b[^>]*?\b(?:src|href)\s*=\s*["']"""
                       r"""((?:https?:)?//[^"']+)""", html, re.I)
    assert not pulls, f"the page loads remote assets: {pulls}"
    for tag in ("vendor/maplibre-gl.js", "vendor/maplibre-gl.css", "app.js", "app.css"):
        assert tag in html


def test_a_remote_script_or_stylesheet_is_still_a_finding_but_a_link_is_not():
    """The narrowing above, driven rather than trusted: the CDN tags this rule exists to
    forbid are still findings, and the attribution anchor the basemap's licence requires is
    not. Without this, the fix reads as 'the assertion was relaxed'."""
    def pulls(html: str) -> list[str]:
        return re.findall(r"""<(?:script|link)\b[^>]*?\b(?:src|href)\s*=\s*["']"""
                          r"""((?:https?:)?//[^"']+)""", html, re.I)

    assert pulls('<script src="https://unpkg.com/maplibre-gl.js"></script>')
    assert pulls('<link href="//cdn.example/x.css" rel="stylesheet">')
    assert pulls('<SCRIPT DEFER SRC="https://cdn.example/x.js"></SCRIPT>')   # case, attrs
    assert not pulls('<a href="https://www.openstreetmap.org/copyright">OSM</a>')
    assert not pulls('<link href="app.css" rel="stylesheet">')


# ------------------------------------------------- frontend 06: the discovery document

FLOOD_FIXTURES = {"assets": ("ref", "assets"), "events": ("silver", "flood_events"),
                  "labels": ("gold", "flood_labels"),
                  "exposure": ("gold", "flood_exposure")}


@pytest.fixture(scope="module")
def stamped(tmp_path_factory):
    """A root the version seam can actually stamp: notify 02's real cut of ref/assets, the
    event spine and the labels. The `exported` fixture's Gold-only root deliberately
    cannot, which is the other half of this contract and is tested below."""
    r = tmp_path_factory.mktemp("stamped")
    for name, parts in FLOOD_FIXTURES.items():
        d = r.joinpath(*parts)
        d.mkdir(parents=True)
        shutil.copy(Path(__file__).parent / "fixtures" / f"notify_query_{name}.parquet",
                    d / "part-00000.parquet")
    return r


def test_the_export_run_that_writes_the_payloads_writes_the_index_beside_them(exported):
    """One run, four files. index.json names the three payloads beside it, so a run that
    wrote it separately could publish a contract describing a build that never landed."""
    files, _, out = exported
    assert (out / contract.NAME).is_file()
    idx = files[contract.NAME]
    keys = {k["key"] for f in idx["families"].values() for k in f["keys"]}
    assert {"files/cells.geojson", "files/headline.json", "files/zones.geojson"} <= keys


def test_the_index_covers_every_family_including_itself(exported):
    """"Discoverable" means one fetch answers everything, this file included - a discovery
    document that omits its own key cannot be re-fetched by a consumer that only has it."""
    files, _, _ = exported
    idx = files[contract.NAME]
    assert set(idx["families"]) == set(publish.FAMILIES)
    assert "files/index.json" in {k["key"] for k in idx["families"]["insight"]["keys"]}
    for name, fam in idx["families"].items():
        assert fam["keys"] and fam["cadence"] and fam["writer"] and fam["cache_control"]
        assert all(k["content_type"] for k in fam["keys"])
        assert fam["gated"] is publish.FAMILIES[name].gated


def test_the_index_carries_the_contract_integer_and_points_at_its_written_half(exported):
    files, _, _ = exported
    idx = files[contract.NAME]
    assert idx["contract"] == contract.CONTRACT and isinstance(idx["contract"], int)
    assert (Path(export.REPO) / idx["contract_doc"]).is_file()


def test_the_keys_the_index_advertises_are_exactly_what_the_publisher_would_upload(exported):
    """The document is DERIVED from publish.FAMILIES rather than typed beside it, so this
    cross-check runs against the publisher's own plan over the REAL export output - not
    against a second list, and not against a fixture that could agree for the wrong
    reason."""
    files, _, out = exported
    planned = [i.key for i in publish.plan("insight", out)]
    assert [k["key"] for k in files[contract.NAME]["families"]["insight"]["keys"]] == planned


def test_the_version_stamps_come_from_the_query_seam_and_are_not_re_derived(stamped):
    """SEAM Q resolves these for every history payload; a second copy of the rule here
    would drift silently. Asserting equality proves the values match today - patching the
    seam and watching the document follow proves it is the same code path.

    `score_version` is the fourth (notify ticket 03) and it arrives here by that seam and
    no other: this root publishes gold/flood_exposure, so the discovery document carries
    the stamp of the universe that scored it. Additive to a promise made of (family, key,
    content type) triples, so no `contract.CONTRACT` bump is owed."""
    con = duck.connect()
    idx = json.loads(contract.text(con, stamped))
    assert idx["versions"] == query.versions(duck.connect(), stamped)
    assert set(idx["versions"]) == {"assets_version", "spine_version", "label_version",
                                    "score_version"}
    assert "versions_unresolved" not in idx


def test_an_unresolvable_stamp_is_an_absent_key_and_a_named_reason(exported, monkeypatch):
    """query.py's own convention: absent, never null. A consumer that needs a stamp refuses
    on the missing key; a null or a placeholder would be read as an answer. Patching the
    seam and seeing the document change is also what proves the document goes THROUGH it."""
    _, root, _ = exported
    idx = json.loads(contract.text(duck.connect(), root))   # a Gold-only root has no spine
    assert "versions" not in idx and idx["versions_unresolved"] == "version_unresolved"

    def boom(con, root):
        raise query.QueryError("version_unresolved", table="patched")

    monkeypatch.setattr(query, "versions", boom)
    assert "versions" not in json.loads(contract.text(duck.connect(), root))


def test_the_index_carries_no_wall_clock_and_re_renders_identically(stamped):
    """A writer's own timestamp in a payload is the frozen-age trap AND it breaks
    byte-identity (test_re_export_is_byte_identical above covers index.json too, since the
    exporter returns it). Every value in here is a frozen constant or a content digest."""
    first = contract.text(duck.connect(), stamped)
    assert first == contract.text(duck.connect(), stamped)
    for banned in ("as_of_utc", "generated_at", "written_at", "timestamp"):
        assert banned not in first


# ======================= frontend2 03: web/geo.sql, the geography family ==================
# The same seam as above, one script over: `export.run_geo()` against a pytest temp root,
# and the written files read back as JSON. The root is `seed()`'s three-Cell fixture plus
# the two static-GTFS tables the route unit needs and a two-row stormwater_extent, so the
# scenario manifest's `horizon = current` filter has something to filter.
#
# S1 crosses BOTH Central Park Cells and belongs to route B41 - the one route in
# `seed()`'s gold/cell_hour_speed - so its features carry real estimands. S2 lies inside
# the Cell that is in no taxi zone, also B41. S3 lies in the same Cell but belongs to Q99,
# which has NO speed rows at all: its feature is the ABSENT-key case end to end, four
# identity properties and nothing else.
SHAPES = {
    "S1": ("B41", 0, "LINESTRING (-73.96986 40.78208, -73.96741 40.77422)"),
    "S2": ("B41", 1, "LINESTRING (-74.0100 40.9070, -74.0080 40.9090)"),
    "S3": ("Q99", 0, "LINESTRING (-74.0095 40.9075, -74.0087 40.9085)"),
}


def seed_geo(root: Path) -> None:
    """`seed()` plus silver/shapes, silver/trips and a minimal silver/stormwater_extent."""
    import duckdb

    seed(root)
    con = duckdb.connect()
    con.execute("LOAD spatial")

    def write(name: str, sql: str) -> None:
        out = root / name
        out.mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY ({sql}) TO '{out / 'part-0.parquet'}' (FORMAT parquet)")

    vals = ", ".join(f"({sid!r}, {wkt!r})" for sid, (_, _, wkt) in SHAPES.items())
    write("silver/shapes",
          f"SELECT shape_id, ST_GeomFromText(wkt) AS geometry, "
          f"ST_Length(ST_Transform(ST_GeomFromText(wkt), 'OGC:CRS84', 'EPSG:32618'))::FLOAT "
          f"AS length_m, 'pick0' AS pick_id FROM (VALUES {vals}) t(shape_id, wkt)")
    trips = ", ".join(f"({sid!r}, {r!r}, {d})" for sid, (r, d, _) in SHAPES.items())
    write("silver/trips",
          f"SELECT 'trip-' || shape_id AS trip_id, route_id, direction_id::TINYINT AS direction_id, "
          f"'svc' AS service_id, shape_id, 'regular' AS trip_type, 'pick0' AS pick_id "
          f"FROM (VALUES {trips}) t(shape_id, route_id, direction_id)")
    # two scenarios, ONE of them at the current sea level: the manifest must publish that
    # one and only that one (DESTINATION-PLAN D3 keeps the SLR horizons off the host)
    write("silver/stormwater_extent",
          "SELECT * FROM (VALUES ('moderate', 'current', 2.13, 'deep', 0), "
          "                      ('extreme', '2080', 3.66, 'deep', 0)) "
          "t(scenario, horizon, rain_in_hr, category, poly)")
    con.close()


@pytest.fixture(scope="module")
def geo_exported(tmp_path_factory):
    root = tmp_path_factory.mktemp("georoot")
    seed_geo(root)
    out = tmp_path_factory.mktemp("geoweb")
    written = export.run_geo(root, out)
    return {name: json.loads(path.read_text()) for name, path in written.items()}, root, out


def sql_code(text: str) -> str:
    """A SQL text with its COMMENTS stripped - the docstring-poisons-the-grep trap, in the
    one file family that has no AST to fall back on.

    web/geo.sql's header explains at length why it does NOT read `gold/cell_hour_route` or
    `gold/cell_hourofweek_baseline`, so `assert "cell_hour_route" not in sql` fails on the
    sentence forbidding it - exactly the shape flood 17, notify 06 and notify 05 each hit
    from a different direction. An inline `--` is only a comment OUTSIDE a string literal,
    so the quote count decides. This helper has its own oracle below, per notify 09's rule
    that a stripper nobody checked cannot prove an absence."""
    out = []
    for line in text.splitlines():
        cut, quoted = len(line), False
        for i, ch in enumerate(line):
            if ch == "'":
                quoted = not quoted
            elif ch == "-" and not quoted and line[i:i + 2] == "--":
                cut = i
                break
        head = line[:cut].rstrip()
        if head:
            out.append(head)
    return "\n".join(out)


def test_the_sql_comment_stripper_reads_code_and_not_prose():
    """Its own oracle: a table name a query really READS survives, and the same name inside
    the paragraph explaining why the file does not read it does not."""
    assert sql_code("SELECT a -- b\n-- c\nFROM t") == "SELECT a\nFROM t"
    assert sql_code("SELECT 'a--b' FROM t") == "SELECT 'a--b' FROM t"   # not a comment
    code = sql_code(export.GEO_SQL.read_text())
    assert "gold/cell_hour_speed" in code, "the table it really reads"
    assert "cell_hour_route" not in code, "the table its header explains it cannot use"
    assert "DESTINATION-PLAN D1" not in code, "the prose is gone"


def routes(files: dict) -> dict:
    """features keyed by (shape_id, cell) - the unit DESTINATION-PLAN D1 decided."""
    return {(f["properties"]["shape_id"], f["properties"]["cell"]): f
            for f in files["routes.geojson"]["features"]}


def test_a_route_feature_is_one_cell_crossing_and_its_ids_cross_as_strings(geo_exported):
    """D1's unit, and the two id rules the box froze. An H3 Cell id is an int64 past 2^53
    that JSON cannot carry (613229522952650751 loses its low bits in any double-reading
    consumer), so it crosses as the same hex string `cell:<h3>` asset ids already use; a
    route id is a route id and never a number.
    MUTATION KILLED: emitting `cell` as the raw BIGINT; keying the feature on shape alone
    (one feature per shape, which is the whole-route unit D1 rejected) or on Cell alone."""
    files, _, _ = geo_exported
    r = routes(files)
    assert files["routes.geojson"]["type"] == "FeatureCollection"
    # S1 crosses both Central Park Cells; S2 and S3 sit inside the un-zoned one
    assert {sid for sid, _ in r} == set(SHAPES)
    assert {c for _, c in r} == {CP1, CP2, NOZ}
    assert ("S1", CP1) in r and ("S1", CP2) in r
    assert len(r) == len(files["routes.geojson"]["features"]), "(shape_id, cell) is unique"
    for (sid, cell), f in r.items():
        p = f["properties"]
        assert isinstance(p["cell"], str) and p["cell"] == cell and len(cell) == 15
        assert int(cell, 16) > 2 ** 53, "the hex rule exists because the int does not fit"
        assert isinstance(p["route_id"], str) and p["route_id"] == SHAPES[sid][0]
        assert p["direction_id"] == SHAPES[sid][1]
        assert f["geometry"]["type"] in ("LineString", "MultiLineString")


def test_a_route_carries_the_same_per_window_estimand_names_cells_geojson_carries(geo_exported, exported):
    """The property NAMES are cells.geojson's, character for character. That is not tidiness:
    it is what lets the page paint the route line with the SAME `colorExpr(activeProp())` it
    paints the Cell fill with, so "one ramp on screen, restricted to one route" is true by
    construction instead of by a second mapping table that could drift.
    MUTATION KILLED: renaming a key here (`w1_r`, `ratio_w1`), which silently paints every
    route line grey on every window view because the property the page asks for is absent."""
    geo_files, _, _ = geo_exported
    cell_files, _, _ = exported
    cell_keys = {k for f in cell_files["cells.geojson"]["features"] for k in f["properties"]}
    route_keys = {k for f in geo_files["routes.geojson"]["features"] for k in f["properties"]}
    window = {k for k in route_keys if k[:3] in ("w1_", "w2_")}
    assert window, "the window estimands are not being exercised at all"
    assert window <= cell_keys, f"names cells.geojson does not use: {sorted(window - cell_keys)}"
    p = routes(geo_files)[("S1", CP1)]["properties"]
    for key in ("w1_ratio", "w1_lo", "w1_hi", "w1_nwet", "w1_nev", "w1_dry", "w1_ndry"):
        assert key in p, f"{key} missing on the one feature the fixture can publish"
    assert p["w1_lo"] < p["w1_ratio"] < p["w1_hi"]
    assert p["w1_nev"] >= 2, "an interval needs at least two wet-event clusters"
    assert p["w1_ratio"] < 1.0, "the fixture's wet Hours are slower than its dry baseline"
    # no storm-hour property has a route counterpart, so those views paint the line grey
    assert not [k for k in route_keys if re.fullmatch(r"(r|lo|hi|n|d|mm|lag)\d{6}", k)]


def test_a_route_with_no_speed_rows_is_four_keys_and_never_a_null(geo_exported):
    """The ABSENT-never-null rule, end to end on the case that exercises it hardest: Q99
    has no rows in gold/cell_hour_speed at all, so it has no dry baseline and no ratio. The
    GDAL GeoJSON writer would emit `null` for every one of those members and MapLibre's
    `["has", p]` is TRUE on a null, which is exactly what breaks the grey guard the page's
    honesty rests on.
    MUTATION KILLED: emitting nulls for the unpublishable keys, or dropping the feature
    entirely (a route with no Speed evidence is still a route, and its geometry is a fact)."""
    files, _, _ = geo_exported
    p = routes(files)[("S3", NOZ)]["properties"]
    assert list(p) == ["route_id", "direction_id", "shape_id", "cell"]
    for f in files["routes.geojson"]["features"]:
        for k, v in f["properties"].items():
            assert v is not None, f"{k} is null - the page's grey guard reads that as present"
            assert not isinstance(v, float) or math.isfinite(v), k


def test_the_route_estimand_uses_the_routes_own_dry_baseline_and_not_the_cells(geo_exported):
    """The denominator is the one design decision in this file. cells.geojson divides by
    gold/cell_hourofweek_baseline, which is keyed (cell, hour_of_week, window) and has NO
    route - so dividing a ROUTE's wet Speed by the Cell's ALL-ROUTE dry Speed would publish
    a composition difference as a rain effect: an express route that is always faster than
    the Cell's mix would read above 1.0 on a dry day. web/geo.sql rebuilds the same baseline
    with one more key, under gold.baseline()'s own dry mask.
    MUTATION KILLED: joining gold/cell_hourofweek_baseline instead (the estimand silently
    stops being about the route), or widening the dry mask."""
    sql = sql_code(export.GEO_SQL.read_text())
    assert "cell_hourofweek_baseline" not in sql, "the Cell-grain baseline is not the denominator"
    bl = sql.split("CREATE OR REPLACE TEMP TABLE bl_r AS", 1)[1].split(";", 1)[0]
    assert "GROUP BY 1, 2, 3, 4" in bl and "c.route_id" in bl
    assert "p.mm_1h < 0.1 AND p.mm_1h_prev < 0.1 AND p.mm_6h < 0.5" in bl  # gold.baseline()'s mask
    joined = sql.split("CREATE OR REPLACE TEMP TABLE wet_r AS", 1)[1].split(";", 1)[0]
    assert ("JOIN bl_r b ON b.win = c.win AND b.cell = c.cell AND b.route_id = c.route_id "
            "AND b.hw = c.hw") in joined
    # and it is NOT gold/cell_hour_route, which carries no distance, no time and no legs -
    # measured, not read: that table is (n_events, late_share, ..., vp_coverage) and spans
    # only month=2021-09 and month=2026-08, which does not even cover W1.
    assert "cell_hour_route" not in sql
    assert "gold/cell_hour_speed" in sql


def test_a_too_wide_interval_omits_the_route_ratio_and_keeps_the_identity(geo_exported):
    """The SAME publish gate cells.geojson uses, taken from export.sql rather than
    re-derived: a per-feature figure publishes only when its 95% interval is narrower than
    gate_width. Driven by re-exporting at a gate nothing can clear, so this pins the gate
    itself and not just a fixture that happens to pass one.
    MUTATION KILLED: gating on bare n; gating the dry LEVEL too (a level is not a wet/dry
    claim and publishes whenever it exists); or dropping the feature when its ratio is
    withheld, which would make the network disappear wherever the evidence is thin."""
    _, root, out_dir = geo_exported
    tight = export.run_geo(root, out_dir.parent / "tight", gate_width=1e-6)
    doc = json.loads(tight["routes.geojson"].read_text())
    keys = {k for f in doc["features"] for k in f["properties"]}
    assert not [k for k in keys if k.endswith(("_ratio", "_lo", "_hi", "_nwet", "_nev"))]
    assert {k for k in keys if k.endswith(("_dry", "_ndry"))}, "a LEVEL is not gated"
    assert len(doc["features"]) == len(routes(geo_exported[0])), "no feature was dropped"
    assert export.GATE_WIDTH == 0.30
    assert "getvariable('gate_width')" in export.GEO_SQL.read_text()


def test_the_route_segments_tile_their_shape(geo_exported):
    """The clip is the unit: the Cell crossings of one shape must add up to that shape,
    or the layer is drawing a different network from the one silver/shapes holds. Measured
    against the shape's OWN length from an independent projection of the source WKT rather
    than against the exporter's own arithmetic.
    MUTATION KILLED: ST_Difference instead of ST_Intersection; dropping the MultiLineString
    parts of a shape that re-enters a Cell; or simplifying so hard that the network shortens."""
    import duckdb

    files, _, _ = geo_exported
    con = duckdb.connect()
    con.execute("LOAD spatial")
    metres = ("ST_Length(ST_Transform(ST_GeomFromGeoJSON(?), 'OGC:CRS84', 'EPSG:32618'))")
    got = {}
    for f in files["routes.geojson"]["features"]:
        (m,) = con.execute(f"SELECT {metres}", [json.dumps(f["geometry"])]).fetchone()
        got[f["properties"]["shape_id"]] = got.get(f["properties"]["shape_id"], 0.0) + m
    for sid, (_, _, wkt) in SHAPES.items():
        (want,) = con.execute(
            "SELECT ST_Length(ST_Transform(ST_GeomFromText(?), 'OGC:CRS84', 'EPSG:32618'))",
            [wkt]).fetchone()
        assert abs(got[sid] - want) / want < 0.02, f"{sid}: {got[sid]:.1f} m of {want:.1f} m"
    con.close()


def test_the_scenario_manifest_is_derived_from_the_table_and_names_the_writers_own_files(geo_exported):
    """A browser cannot list a directory, and `geo` is a TREE family whose served set is
    DERIVED from silver/stormwater_extent - so without this manifest the page would have to
    name `stormwater-moderate.geojson` in JavaScript, and the day a second scenario becomes
    readable that is a page edit. The `horizon = current` filter is D3 (sea-level-rise
    projections stay in the table and off the host), and the KEY SPELLING is pinned against
    stormwater_extent.export()'s own f-string read out of that module's SOURCE, because
    writing the pattern down twice is exactly how the manifest starts naming files nobody
    writes.
    MUTATION KILLED: publishing the 2080 scenario; spelling the key `<scenario>.geojson`;
    or listing scenarios from a hard-coded tuple instead of from the table."""
    files, _, _ = geo_exported
    doc = files["scenarios.json"]
    assert [s["scenario"] for s in doc["scenarios"]] == ["moderate"], "current horizon only"
    row = doc["scenarios"][0]
    assert row["horizon"] == "current" and row["rain_in_hr"] == 2.13
    src = (Path(export.__file__).parent / "stormwater_extent.py").read_text()
    m = re.search(r'name = f"stormwater-\{(\w+)\}\.geojson"', src)
    assert m, "stormwater_extent.export() no longer names its files that way"
    assert row["key"] == f"stormwater-{row['scenario']}.geojson"
    assert "'stormwater-' || scenario || '.geojson'" in export.GEO_SQL.read_text()


def test_the_geo_payloads_carry_their_own_attribution_and_no_feed_row(geo_exported):
    """Two halves of one MUST. (a) The credit travels IN the payload, so the page reads it
    rather than mirroring it - the repo's rule for any string the page shares with a writer
    in src/. (b) Nothing feed-shaped is in files/geo/: the geometry is STATIC GTFS (the
    published schedule bundle, which the MTA developer terms expressly authorise hosting on
    a non-MTA server) and the numbers are the same historical 2021/2023 aggregate
    cells.geojson already publishes ungated off the same Gold table - no vehicle id, no
    vehicle position, no timestamp, no current snapshot, and no route bullet or line colour.
    MUTATION KILLED: dropping the attribution member (the page then has nothing to print);
    or leaking a vehicle-level key into a property."""
    files, _, _ = geo_exported
    attr = files["routes.geojson"]["attribution"]
    assert "static GTFS" in attr and "MTA" in attr
    assert "not affiliated with, endorsed by" in attr.lower()
    assert "no route bullet" in attr
    keys = {k for f in files["routes.geojson"]["features"] for k in f["properties"]}
    for banned in ("vehicle_id", "vp_age_s", "ts", "fetched_at", "as_of_utc", "trip_id",
                   "route_color", "alert_id", "occupancy"):
        assert banned not in keys, f"{banned} is feed-shaped and may not be in files/geo/"


def test_re_export_of_the_geo_family_is_byte_identical(geo_exported):
    """Same contract as the insight files: every aggregate ordered, every number explicitly
    rounded, no wall clock anywhere - so the artifacts diff cleanly as evidence."""
    _, root, out_dir = geo_exported
    again = out_dir.parent / "geoagain"
    for name, path in export.run_geo(root, again).items():
        assert path.read_bytes() == (out_dir / name).read_bytes(), f"{name} is not reproducible"


def test_route_property_keys_are_written_in_sorted_order(geo_exported):
    """Byte-identity alone does not pin the writer's ORDER BY - two runs in one process pick
    the same arbitrary order, so dropping it stays green there while the real slice comes out
    unsorted (measured twice in this repo). The four identity keys are a FIXED block because
    they are the feature's identity and are read together; everything after them is sorted."""
    files, _, _ = geo_exported
    for f in files["routes.geojson"]["features"]:
        keys = list(f["properties"])
        assert keys[:4] == ["route_id", "direction_id", "shape_id", "cell"]
        assert keys[4:] == sorted(keys[4:]), f"{keys[:4]} properties are not sorted"


def test_the_geo_export_writes_all_of_its_files_or_none(geo_exported, tmp_path):
    """`stage()` is shared with the insight export for exactly this: a run that died on the
    last query would leave web/files/geo holding a fresh routes.geojson beside a stale
    manifest, and the page would offer a scenario radio for a file that is not there.
    MUTATION KILLED: renaming each file as it is written instead of staging them all first."""
    _, root, _ = geo_exported
    out = tmp_path / "half"
    with pytest.raises(Exception):
        export.stage([("a.json", "{}"), ("b.json", None)], out)   # None -> write_text raises
    assert not (out / "a.json").exists(), "a.json was published while b.json was not"
