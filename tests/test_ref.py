"""Ticket 02: the reference layer under a temp data root, read back with DuckDB.
The module-scoped fixture runs the whole `make ref` build once (Spark + Sedona), so the
module skips as a whole when no JVM is found."""
import hashlib
import json
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
import pytest
import shapely

from raincheck import duck, ref

FIXTURES = Path(__file__).parent / "fixtures"
CENTRAL_PARK_CELL = int("882a100895fffff", 16)


def gtfs_zip(path: Path, feed_version: str) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("calendar.txt",
                   "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                   "WKD,1,1,1,1,1,0,0,20260601,20260830\n")
        z.writestr("calendar_dates.txt", "service_id,date,exception_type\nWKD,20260901,1\n")
        z.writestr("feed_info.txt",
                   f"feed_publisher_name,feed_publisher_url,feed_lang,feed_version\nMTA,https://mta.info,en,{feed_version}\n")


@pytest.fixture(scope="module")
def ref_root(spark, tmp_path_factory):
    root = tmp_path_factory.mktemp("root")
    (root / "ref" / "src").mkdir(parents=True)
    (root / "ref" / "src" / "taxi_zones.zip").write_bytes((FIXTURES / "taxi_zones.zip").read_bytes())
    (root / "archive" / "precip" / "aorc").mkdir(parents=True)
    (root / "archive" / "precip" / "aorc" / "coords.npz").write_bytes((FIXTURES / "aorc_coords.npz").read_bytes())
    (root / "archive" / "static" / "brooklyn").mkdir(parents=True)
    (root / "archive" / "static" / "subway").mkdir(parents=True)
    gtfs_zip(root / "archive" / "static" / "brooklyn" / "2026-06-23.zip", "B20260623")
    gtfs_zip(root / "archive" / "static" / "subway" / "2026-07-01.zip", "S20260701")
    # a truncated zip (the archiver writes non-atomically): must be skipped, not abort the build
    (root / "archive" / "static" / "subway" / "2026-07-02.zip").write_bytes(b"PK\x03\x04 truncated")
    ref.build(root, spark)
    return root


@pytest.fixture(scope="module")
def con(ref_root):
    return duck.connect()


def test_grids(ref_root, con):
    rows = duck.table(con, ref_root / "ref" / "grids").order("grid_id").fetchall()
    cols = duck.table(con, ref_root / "ref" / "grids").columns
    aorc, mrms = (dict(zip(cols, r)) for r in rows)
    assert aorc["grid_id"] == "aorc" and mrms["grid_id"] == "mrms"
    assert (aorc["origin_lon"], aorc["origin_lat"]) == (-130.0, 20.0)
    assert aorc["step_deg"] == pytest.approx(0.008333, abs=1e-6)
    assert (aorc["nx"], aorc["ny"]) == (8401, 4201)
    # sha of the stored coordinate arrays, pinned to the fetch of 2026-08-22
    assert aorc["coord_sha256"] == "c2ef67bf8b5c6bb70f41a5b649467f6e90e898677b2cb5666fe9e94d07a5f243"
    assert (mrms["origin_lon"], mrms["origin_lat"]) == (-129.995, 20.005)
    assert mrms["step_deg"] == 0.01 and (mrms["nx"], mrms["ny"]) == (7000, 3500)
    assert len(mrms["coord_sha256"]) == 64
    for r in (aorc, mrms):
        assert r["registration"] == "center"
        assert r["frozen_at"].tzinfo is not None


def test_cells_count_and_geoparquet_11(ref_root):
    meta = pq.read_metadata(ref_root / "ref" / "cells" / "part-00000.parquet")
    geo = json.loads(meta.metadata[b"geo"])
    assert geo["version"] == "1.1.0"
    assert set(geo["columns"]) == {"geometry"}
    t = pq.read_table(ref_root / "ref" / "cells")
    assert t.num_rows == 4113
    cells = t.column("cell").to_pylist()
    assert len(set(cells)) == 4113 and cells == sorted(cells)
    assert CENTRAL_PARK_CELL in cells
    i = cells.index(CENTRAL_PARK_CELL)
    # the centroid sits within one hex radius (~461 m, ~6e-3 deg) of the point that hashes to it
    assert t.column("centroid_lon")[i].as_py() == pytest.approx(-73.965, abs=6e-3)
    assert t.column("centroid_lat")[i].as_py() == pytest.approx(40.782, abs=6e-3)


def test_cells_against_duckdb_h3_oracle(ref_root):
    con = duckdb.connect()
    try:
        con.execute("INSTALL h3 FROM community; LOAD h3; INSTALL spatial; LOAD spatial")
    except duckdb.Error as exc:
        pytest.skip(f"duckdb extensions unavailable (offline?): {exc}")
    # Sedona's Java H3 and DuckDB's C h3 disagree in the last double ulp (~1e-14 deg, measured
    # on every cell), so the oracle is ST_Equals after snapping both to a 1e-9 deg (~0.1 mm) grid.
    (bad,) = con.execute(  # spatial reads GeoParquet geometry as GEOMETRY already
        "SELECT count(*) FROM read_parquet(?) WHERE NOT ST_Equals("
        "  ST_ReducePrecision(geometry, 1e-9),"
        "  ST_ReducePrecision(ST_GeomFromWKB(h3_cell_to_boundary_wkb(cell)), 1e-9))",
        [f"{ref_root}/ref/cells/**/*.parquet"],
    ).fetchone()
    assert bad == 0


def test_zones(ref_root):
    t = pq.read_table(ref_root / "ref" / "zones")
    assert t.num_rows == 263
    ids = t.column("zone_id").to_pylist()
    assert sorted(ids) == list(range(1, 264))
    geo = json.loads(pq.read_metadata(ref_root / "ref" / "zones" / "part-00000.parquet").metadata[b"geo"])
    assert geo["version"] == "1.1.0"
    row = {c: t.column(c)[ids.index(230)].as_py() for c in t.column_names}
    assert row["zone_name"] == "Times Sq/Theatre District" and row["borough"] == "Manhattan"
    g = shapely.from_wkb(row["geometry"])
    assert g.covers(shapely.Point(-73.9855, 40.7580))  # axis gate held at ingest


def test_cell_zone(ref_root, con):
    rel = duck.table(con, ref_root / "ref" / "cell_zone")
    assert rel.aggregate("count(*), count(DISTINCT cell)").fetchone() == (4113, 4113)
    (cp_zone, cp_borough) = con.execute(
        "SELECT zone_id, borough FROM read_parquet(?) WHERE cell = ?",
        [f"{ref_root}/ref/cell_zone/**/*.parquet", CENTRAL_PARK_CELL],
    ).fetchone()
    assert (cp_zone, cp_borough) == (43, "Manhattan")  # Central Park
    (assigned,) = con.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE zone_id IS NOT NULL",
        [f"{ref_root}/ref/cell_zone/**/*.parquet"],
    ).fetchone()
    # most of the bbox is water: ~1,070 centroids land in a zone (cf. 10's ~1,146-Cell bus footprint)
    assert 900 < assigned < 1500


def test_cell_pixel(ref_root, con):
    path = f"{ref_root}/ref/cell_pixel/**/*.parquet"
    for grid, lo, hi in (("aorc", 19000, 20000), ("mrms", 8000, 20000)):
        cells, worst = con.execute(
            "SELECT count(*), max(abs(s - 1)) FROM ("
            "  SELECT cell, sum(weight) AS s FROM read_parquet(?) WHERE grid_id = ? GROUP BY cell)",
            [path, grid],
        ).fetchone()
        assert cells == 4113, grid
        assert worst < 1e-9, grid
        (n,) = con.execute("SELECT count(*) FROM read_parquet(?) WHERE grid_id = ?", [path, grid]).fetchone()
        assert lo <= n <= hi, (grid, n)
    (aorc_n,) = con.execute("SELECT count(*) FROM read_parquet(?) WHERE grid_id='aorc'", [path]).fetchone()
    assert aorc_n / 4113 == pytest.approx(4.7, abs=0.3)  # ~4.7 Pixels per Cell
    (w,) = con.execute(
        "SELECT weight FROM read_parquet(?) WHERE grid_id='mrms' AND cell=? AND i=5603 AND j=2078",
        [path, CENTRAL_PARK_CELL],
    ).fetchone()
    assert w > 0.1  # Central Park Pixel per research 08


def test_calendar(ref_root, con):
    rel = duck.table(con, ref_root / "ref" / "calendar")
    rows = {r[0]: dict(zip(rel.columns, r)) for r in rel.fetchall()}
    assert len(rows) == 122
    w1 = [d for d in rows if date(2021, 8, 16) <= d <= date(2021, 10, 15)]
    w2 = [d for d in rows if date(2023, 9, 1) <= d <= date(2023, 10, 31)]
    assert len(w1) == 61 and len(w2) == 61
    school = {d for d, r in rows.items() if r["school_in_session"]}
    assert date(2021, 9, 10) not in school and date(2021, 9, 13) in school  # DOE first day 2021
    assert date(2021, 9, 16) not in school  # Yom Kippur 2021
    assert date(2021, 9, 18) not in school  # Saturday
    assert date(2023, 9, 6) not in school and date(2023, 9, 7) in school  # DOE first day 2023
    assert date(2023, 9, 25) not in school and date(2023, 10, 9) not in school
    holidays = {d for d, r in rows.items() if r["holiday"]}
    assert holidays == {date(2021, 9, 6), date(2021, 10, 11), date(2023, 9, 4), date(2023, 10, 9)}
    unga = sorted(d for d, r in rows.items() if r["unga_week"])
    assert unga[0] == date(2021, 9, 21) and unga[6] == date(2021, 9, 27) and len(unga) == 15
    assert unga[7] == date(2023, 9, 19) and unga[-1] == date(2023, 9, 26)


def test_picks(ref_root, con):
    rel = duck.table(con, ref_root / "ref" / "picks")
    rows = [dict(zip(rel.columns, r)) for r in rel.order("feed").fetchall()]
    assert [r["feed"] for r in rows] == ["brooklyn", "subway"]
    bk = rows[0]
    raw = (ref_root / "archive" / "static" / "brooklyn" / "2026-06-23.zip").read_bytes()
    assert bk["pick_id"] == hashlib.sha1(raw).hexdigest()
    assert bk["published"] == datetime(2026, 6, 23, tzinfo=timezone.utc)
    assert bk["feed_version"] == "B20260623"
    assert bk["earliest_calendar_date"] == date(2026, 6, 1)
    assert bk["latest_calendar_date"] == date(2026, 9, 1)  # calendar_dates extends the span
    assert bk["source"] == "mta"
    assert bk["path"] == "archive/static/brooklyn/2026-06-23.zip"


def test_rebuild_is_byte_identical(ref_root, spark):
    def snapshot() -> dict:
        return {p.relative_to(ref_root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((ref_root / "ref").rglob("*.parquet"))}

    before = snapshot()
    ref.build(ref_root, spark)
    assert snapshot() == before
