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
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from raincheck import export
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
W1_START = datetime(2021, 8, 16, 12, tzinfo=timezone.utc)


def _rows():
    """(speed rows, precip rows) for the fixture window.

    Ten weekly Thursdays at the same hour-of-week as the Ida hour build each Cell's dry
    baseline bin; five of them are also made wet at a different hour-of-week so every Cell
    clears the two-wet-event minimum the interval needs. The Ida hour itself is wet and
    slow (half the dry Speed) for CP1 and CP2 and only mildly slow for NOZ.
    """
    speed, precip = [], []
    dry = {CP1: 4.0, CP2: 5.0, NOZ: 6.0}
    # the baseline bin: the same hour-of-week as Ida, once a week across the window
    for wk in range(10):
        h = IDA + timedelta(weeks=wk - 2)
        if h == IDA:
            continue
        for hexid, (cell, _, _) in CELLS.items():
            dt_s = 3600
            # a little scatter so the bin has a real standard error, not a degenerate 0
            v = dry[hexid] * (1 + 0.02 * ((wk % 3) - 1))
            speed.append((cell, h, 40 + wk, v * dt_s, dt_s))
            precip.append((cell, h, 0.0, 0.0, 0.0))
    # wet Hours on their own hour-of-week bin, spread over separate wet events
    for wk in range(6):
        h = W1_START + timedelta(weeks=wk)
        for hexid, (cell, _, _) in CELLS.items():
            dt_s = 3600
            speed.append((cell, h, 30, dry[hexid] * 0.95 * dt_s, dt_s))
            precip.append((cell, h, 2.0, 0.0, 0.0))
            # that bin's dry side, so the wet Hour has a baseline to be scored against
            hd = h + timedelta(days=1)
            speed.append((cell, hd, 30, dry[hexid] * dt_s, dt_s))
            precip.append((cell, hd, 0.0, 0.0, 0.0))
    # the Ida storm hour: wet, and slow where the Cells are on the map
    for hexid, (cell, _, _) in CELLS.items():
        factor = 0.5 if hexid in (CP1, CP2) else 0.9
        speed.append((cell, IDA, 25, dry[hexid] * factor * 3600, 3600))
        precip.append((cell, IDA, 30.0, 5.0, 40.0))
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
               (((dayofweek(timezone('America/New_York', hour_end_utc)) + 5) % 7) * 24
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
    """The export's window bounds are literals in the SQL (it stays standalone-runnable);
    this is the guard against them drifting from raincheck.ref.WINDOWS."""
    sql = export.SQL.read_text()
    for start, end in WINDOWS:
        assert f"'{start} 00:00:00+00'" in sql
        assert f"'{end + timedelta(days=1)} 00:00:00+00'" in sql


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


# ------------------------------------------------------------------------ 14-4 smoke
def test_the_stdlib_server_answers_200_for_the_page_and_its_files(exported, tmp_path):
    """14-4: `make web` is `python -m http.server --directory web`. The page, both vendored
    files and the exported data files must all answer 200 - the demo has no other server."""
    _, _, out_dir = exported
    web = tmp_path / "web"
    (web / "files").mkdir(parents=True)
    (web / "vendor").mkdir()
    for name in ("index.html", "app.js", "app.css"):
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
        for path in ("index.html", "app.js", "app.css", "vendor/maplibre-gl.js",
                     "vendor/maplibre-gl.css", "files/cells.geojson", "files/headline.json",
                     "files/zones.geojson"):
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
    """No CDN at demo time (spec L): every script and stylesheet the page pulls is local."""
    html = (export.REPO / "web" / "index.html").read_text()
    assert "http://" not in html and "https://" not in html.split("<!--")[0]
    for tag in ("vendor/maplibre-gl.js", "vendor/maplibre-gl.css", "app.js", "app.css"):
        assert tag in html
