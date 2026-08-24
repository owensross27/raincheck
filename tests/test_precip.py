"""Ticket 04 / 08-T2..T5, T8, 07-5: the precip tables. Two seams: a synthetic three-cell
crosswalk for the guard/frame/boundary logic, and the committed 48-hour AORC Ida fixture
through the real crosswalk for the pinned numbers. Spark tests skip without a JVM."""
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raincheck import duck, precip, precip_flood_era

FIXTURES = Path(__file__).parent / "fixtures"
CENTRAL_PARK_CELL = int("882a100895fffff", 16)
TS = pa.timestamp("us", tz="UTC")


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


# --- synthetic seam -------------------------------------------------------------------

def synth_root(tmp: Path) -> Path:
    """Three cells over three pixels: cell 1 = {(0,0) 0.5, (0,1) 0.5}, cell 2 = {(1,0) 1.0},
    cell 3 = {(1,1) 0.6, (2,1) 0.4}."""
    root = tmp / "root"
    rows = [("aorc", 1, 0, 0, 0.5), ("aorc", 1, 0, 1, 0.5), ("aorc", 2, 1, 0, 1.0),
            ("aorc", 3, 1, 1, 0.6), ("aorc", 3, 2, 1, 0.4)]
    schema = pa.schema([("grid_id", pa.string()), ("cell", pa.int64()),
                       ("i", pa.int16()), ("j", pa.int16()), ("weight", pa.float64())])
    (root / "ref" / "cell_pixel").mkdir(parents=True)
    pq.write_table(pa.Table.from_pydict(
        {k: [r[n] for r in rows] for n, k in enumerate(schema.names)}, schema=schema),
        root / "ref" / "cell_pixel" / "part-00000.parquet")
    (root / "ref" / "cells").mkdir(parents=True)
    pq.write_table(pa.table({"cell": pa.array([1, 2, 3], pa.int64())}),
                   root / "ref" / "cells" / "part-00000.parquet")
    return root


def write_hourly(root: Path, month: str, rows: list[tuple]) -> None:
    """rows: (i, j, iso_hour, mm, t2m_k)"""
    out = root / "silver" / "precip_hourly" / "src=aorc" / f"month={month}"
    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({
        "i": pa.array([r[0] for r in rows], pa.int16()),
        "j": pa.array([r[1] for r in rows], pa.int16()),
        "hour_end_utc": pa.array([utc(r[2]) for r in rows], TS),
        "mm": pa.array([r[3] for r in rows], pa.float32()),
        "t2m_k": pa.array([r[4] for r in rows], pa.float32()),
    }), out / "part-00000.parquet", compression="zstd")


@pytest.fixture(scope="module")
def synth(spark, tmp_path_factory):
    root = synth_root(tmp_path_factory.mktemp("synth"))
    # lookback month July: all three pixels of cells 1+2 rain 1.0 for the last 24 labels,
    # cell 3's second pixel (2,1) missing at 23:00 (a NULL frame hour for cell 3)
    july = []
    for h in range(24):
        iso = f"2021-07-31T{h:02d}:00"
        july += [(0, 0, iso, 1.0, 280.0), (0, 1, iso, 1.0, 290.0), (1, 0, iso, 1.0, 285.0)]
        july += [(1, 1, iso, 1.0, 285.0)] + ([] if h == 23 else [(2, 1, iso, 1.0, 285.0)])
    write_hourly(root, "2021-07", july)
    # August: 00:00 full field with distinct values; 01:00 cell 3's (2,1) pixel NULL mm
    aug = [(0, 0, "2021-08-01T00:00", 2.0, 280.0), (0, 1, "2021-08-01T00:00", 4.0, 290.0),
           (1, 0, "2021-08-01T00:00", 6.0, 285.0), (1, 1, "2021-08-01T00:00", 5.0, 285.0),
           (2, 1, "2021-08-01T00:00", 10.0, 285.0),
           (0, 0, "2021-08-01T01:00", 1.0, 280.0), (0, 1, "2021-08-01T01:00", 1.0, 290.0),
           (1, 0, "2021-08-01T01:00", 1.0, 285.0), (1, 1, "2021-08-01T01:00", 1.0, 285.0),
           (2, 1, "2021-08-01T01:00", None, 285.0)]
    write_hourly(root, "2021-08", aug)
    precip.cell_hourly(root, spark, "aorc", "2021-08")
    con = duck.connect()
    rows = {(r[0], r[1]): dict(zip(
        ["cell", "hour_end_utc", "mm_1h", "mm_1h_prev", "mm_3h", "mm_6h", "mm_24h", "n_hours_24h", "t2m_c"], r))
        for r in con.execute(
            "SELECT cell, hour_end_utc, mm_1h, mm_1h_prev, mm_3h, mm_6h, mm_24h, n_hours_24h, t2m_c "
            "FROM read_parquet(?)", [f"{root}/silver/precip_cell_hourly/**/*.parquet"]).fetchall()}
    return root, rows


def test_synth_weighted_mean_and_guard(synth):
    root, rows = synth
    h0 = utc("2021-08-01T00:00")
    assert rows[(1, h0)]["mm_1h"] == pytest.approx(3.0)   # 0.5*2 + 0.5*4
    assert rows[(2, h0)]["mm_1h"] == pytest.approx(6.0)
    assert rows[(3, h0)]["mm_1h"] == pytest.approx(0.6 * 5 + 0.4 * 10)
    assert rows[(1, h0)]["t2m_c"] == pytest.approx(285.0 - 273.15)
    h1 = utc("2021-08-01T01:00")
    assert rows[(3, h1)]["mm_1h"] is None        # realized weight 0.6 < 1 - 1e-6
    assert rows[(1, h1)]["mm_1h"] == pytest.approx(1.0)


def test_synth_lookback_and_frames(synth):
    root, rows = synth
    h0, h1 = utc("2021-08-01T00:00"), utc("2021-08-01T01:00")
    assert rows[(1, h0)]["mm_1h_prev"] == pytest.approx(1.0)   # from the July lookback
    assert rows[(1, h0)]["n_hours_24h"] == 24                  # 23 lookback hours + this one
    assert rows[(1, h0)]["mm_24h"] == pytest.approx(23 * 1.0 + 3.0)
    assert rows[(1, h0)]["mm_3h"] == pytest.approx(1 + 1 + 3)
    assert rows[(3, h0)]["mm_3h"] is None                      # 23:00 frame hour NULL for cell 3
    assert rows[(3, h0)]["n_hours_24h"] == 23
    assert rows[(3, h1)]["mm_3h"] is None                      # current hour NULL
    assert rows[(2, h1)]["mm_6h"] == pytest.approx(5 * 1.0 + 6.0)


def test_synth_dense_unique_sorted(synth):
    root, rows = synth
    con = duck.connect()
    p = f"{root}/silver/precip_cell_hourly/**/*.parquet"
    n, uniq = con.execute("SELECT count(*), count(DISTINCT (cell, hour_end_utc)) FROM read_parquet(?)",
                          [p]).fetchone()
    assert n == uniq == 3 * 31 * 24  # dense over cells x every hour of August, unique grain
    keys = con.execute("SELECT cell, hour_end_utc FROM read_parquet(?)", [p]).fetchall()
    assert keys == sorted(keys)  # physical order (cell, hour_end_utc)
    (lookback,) = con.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE hour_end_utc < timestamp '2021-08-01 00:00:00+00'",
        [p]).fetchone()
    assert lookback == 0  # lookback hours are input, never output


def test_synth_rebuild_byte_identical_neighbour_untouched(synth, spark):
    root, _ = synth
    table = root / "silver" / "precip_cell_hourly"
    precip.cell_hourly(root, spark, "aorc", "2021-07")  # neighbour (no lookback present: fine)
    snap = lambda: {p.relative_to(table).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(table.rglob("*.parquet"))}
    before = snap()
    assert set(before) == {"src=aorc/month=2021-07/part-00000.parquet",
                           "src=aorc/month=2021-08/part-00000.parquet"}
    precip.cell_hourly(root, spark, "aorc", "2021-08")
    assert snap() == before


# --- real-fixture seam ----------------------------------------------------------------

@pytest.fixture(scope="module")
def ida(spark, tmp_path_factory):
    root = tmp_path_factory.mktemp("ida")
    (root / "archive" / "precip" / "aorc").mkdir(parents=True)
    shutil.copytree(FIXTURES / "aorc-ida.zarr", root / "archive" / "precip" / "aorc" / "2021-09.zarr")
    (root / "ref" / "cell_pixel").mkdir(parents=True)
    shutil.copy(FIXTURES / "ref-cell_pixel-aorc.parquet", root / "ref" / "cell_pixel" / "part-00000.parquet")
    (root / "ref" / "cells").mkdir(parents=True)
    shutil.copy(FIXTURES / "ref-cells-ids.parquet", root / "ref" / "cells" / "part-00000.parquet")
    (root / "ref" / "grids").mkdir(parents=True)
    pq.write_table(pa.table({"grid_id": ["aorc"], "origin_lon": [-130.0], "origin_lat": [20.0],
                             "step_deg": [0.008332999999993262]}),
                   root / "ref" / "grids" / "part-00000.parquet")
    precip.hourly(root, "aorc", "2021-09")
    precip.cell_hourly(root, spark, "aorc", "2021-09")
    return root


def test_ida_hourly_density_and_footprint(ida):
    con = duck.connect()
    p = f"{ida}/silver/precip_hourly/**/*.parquet"
    n, pixels, hours = con.execute(
        "SELECT count(*), count(DISTINCT (i, j)), count(DISTINCT hour_end_utc) FROM read_parquet(?)",
        [p]).fetchone()
    assert pixels == 4868 and hours == 48 and n == 4868 * 48  # dense; footprint = the crosswalk's
    (dupes,) = con.execute(
        "SELECT count(*) - count(DISTINCT (i, j, hour_end_utc)) FROM read_parquet(?)", [p]).fetchone()
    assert dupes == 0


def test_ida_pinned_numbers(ida):
    con = duck.connect()
    p = f"{ida}/silver/precip_cell_hourly/**/*.parquet"
    (cp,) = con.execute(
        "SELECT mm_1h FROM read_parquet(?) WHERE cell = ? AND hour_end_utc = timestamp '2021-09-02 02:00:00+00'",
        [p, CENTRAL_PARK_CELL]).fetchone()
    assert cp == pytest.approx(84.28, abs=0.05)  # 08-T4 / 10-T2
    # 08-T4's "bbox mean 49.14" is the evidence script's convention: NaN Pixels skipped,
    # all-NaN (water) Cells counted as 0.0, mean over all 4,113. The spec-guarded table
    # instead nulls partial-weight Cells; its mean is 51.18 over 3,945 non-null Cells.
    # Assert both, each computed the way its number was defined.
    mean, n = con.execute(
        "SELECT avg(mm_1h), count(mm_1h) FROM read_parquet(?) WHERE hour_end_utc = timestamp '2021-09-02 02:00:00+00'",
        [p]).fetchone()
    assert mean == pytest.approx(51.18, abs=0.05) and n == 3945
    (legacy,) = con.execute("""
        SELECT avg(coalesce(s, 0)) FROM (SELECT x.cell, sum(x.weight * p.mm) AS s
          FROM read_parquet(?) x LEFT JOIN read_parquet(?) p
            ON p.i = x.i AND p.j = x.j AND p.hour_end_utc = timestamp '2021-09-02 02:00:00+00'
          GROUP BY x.cell)""",
        [f"{ida}/ref/cell_pixel/**/*.parquet", f"{ida}/silver/precip_hourly/**/*.parquet"]).fetchone()
    assert legacy == pytest.approx(49.14, abs=0.05)


def test_ida_mm24h_equals_independent_xarray_rolling_sum(ida):
    import xarray as xr

    con = duck.connect()
    got, n24 = con.execute(
        "SELECT mm_24h, n_hours_24h FROM read_parquet(?) WHERE cell = ? AND hour_end_utc = timestamp '2021-09-02 02:00:00+00'",
        [f"{ida}/silver/precip_cell_hourly/**/*.parquet", CENTRAL_PARK_CELL]).fetchone()
    assert n24 == 24
    ds = xr.open_zarr(ida / "archive" / "precip" / "aorc" / "2021-09.zarr", consolidated=True)
    cpx = pq.read_table(FIXTURES / "ref-cell_pixel-aorc.parquet").to_pylist()
    mine = [r for r in cpx if r["cell"] == CENTRAL_PARK_CELL]
    # weighted Cell series via numpy, then a rolling 24 h sum ending at 02:00Z; origin and
    # step come from ref/grids, not re-typed literals (the builder must agree with grids)
    (g,) = pq.read_table(ida / "ref" / "grids").to_pylist()
    step = g["step_deg"]
    i0 = round((float(ds.longitude[0]) - g["origin_lon"]) / step)
    j0 = round((float(ds.latitude[0]) - g["origin_lat"]) / step)
    i_rel = [r["i"] - i0 for r in mine]
    j_rel = [r["j"] - j0 for r in mine]
    w = np.array([r["weight"] for r in mine])
    vals = ds.APCP_surface.values[:, j_rel, i_rel] @ w
    cell_series = xr.DataArray(vals, coords={"time": ds.time}, dims="time")
    want = float(cell_series.rolling(time=24).sum().sel(time=np.datetime64("2021-09-02T02:00:00")))
    assert got == pytest.approx(want, abs=0.01)  # float32 tolerance


def test_ida_envelope(ida):
    """08-T3 on the real crosswalk: every Cell-hour within its Pixels' min/max."""
    con = duck.connect()
    (bad,) = con.execute("""
        SELECT count(*) FROM (
          SELECT c.cell, c.hour_end_utc, c.mm_1h, min(p.mm) lo, max(p.mm) hi
          FROM read_parquet(?) c
          JOIN read_parquet(?) x ON x.cell = c.cell
          JOIN read_parquet(?) p ON p.i = x.i AND p.j = x.j AND p.hour_end_utc = c.hour_end_utc
          WHERE c.mm_1h IS NOT NULL
          GROUP BY 1, 2, 3
        ) WHERE mm_1h < lo - 1e-4 OR mm_1h > hi + 1e-4""", [
        f"{ida}/silver/precip_cell_hourly/**/*.parquet",
        f"{ida}/ref/cell_pixel/**/*.parquet",
        f"{ida}/silver/precip_hourly/**/*.parquet"]).fetchone()
    assert bad == 0


def test_constant_field_yields_exactly_one(ida, spark, tmp_path):
    """08-T3: all footprint Pixels 1.0 through the real crosswalk -> 1.0 per Cell."""
    root = tmp_path / "const"
    for name in ("cell_pixel", "cells"):
        shutil.copytree(ida / "ref" / name, root / "ref" / name)
    fp = pq.read_table(ida / "ref" / "cell_pixel").select(["i", "j"]).group_by(["i", "j"]).aggregate([])
    hours = [utc("2021-10-01T00:00"), utc("2021-10-01T01:00")]
    rows = [(i, j, h) for i, j in zip(fp.column("i").to_pylist(), fp.column("j").to_pylist()) for h in hours]
    out = root / "silver" / "precip_hourly" / "src=aorc" / "month=2021-10"
    out.mkdir(parents=True)
    pq.write_table(pa.table({
        "i": pa.array([r[0] for r in rows], pa.int16()),
        "j": pa.array([r[1] for r in rows], pa.int16()),
        "hour_end_utc": pa.array([r[2] for r in rows], TS),
        "mm": pa.array([1.0] * len(rows), pa.float32()),
        "t2m_k": pa.array([280.0] * len(rows), pa.float32()),
    }), out / "part-00000.parquet")
    precip.cell_hourly(root, spark, "aorc", "2021-10")
    (lo, hi, n) = duck.connect().execute(
        "SELECT min(mm_1h), max(mm_1h), count(mm_1h) FROM read_parquet(?) WHERE mm_1h IS NOT NULL",
        [f"{root}/silver/precip_cell_hourly/**/*.parquet"]).fetchone()
    assert n == 4113 * 2
    assert lo == pytest.approx(1.0, abs=1e-6) and hi == pytest.approx(1.0, abs=1e-6)


def test_ceil_hour(spark):
    """08-T5: exactly on the hour stays; one microsecond after rolls forward."""
    from pyspark.sql import functions as F

    from raincheck.enrich import ceil_hour

    df = spark.createDataFrame(
        [("2021-09-02 02:00:00.000000",), ("2021-09-02 02:00:00.000001",)], ["s"]
    ).select(ceil_hour(F.col("s").cast("timestamp")).alias("h"))
    got = [r.h.isoformat() for r in df.collect()]
    assert got == ["2021-09-02T02:00:00", "2021-09-02T03:00:00"]


# --- flood-era seam (flood-build ticket 06) -------------------------------------------

def test_window_months_derives_lookback_month(): 
    """The Cell month list holds the Window hours; the Pixel list additionally holds the
    24 h lookback, because the Cell build reads its frames out of `precip_hourly` and a
    Window opening early in a month would otherwise get silently short mm_3h/6h/24h."""
    mid = (utc("2011-08-27T00:00"), utc("2011-08-28T23:00"))          # wholly inside 2011-08
    early = (utc("2010-10-01T02:00"), utc("2010-10-02T03:00"))        # lookback reaches 2010-09
    span = (utc("2012-10-29T21:00"), utc("2012-11-01T03:00"))         # crosses the boundary
    assert precip_flood_era.window_months([mid]) == (["2011-08"], ["2011-08"])
    assert precip_flood_era.window_months([early]) == (["2010-09", "2010-10"], ["2010-10"])
    assert precip_flood_era.window_months([span]) == (["2012-10", "2012-11"], ["2012-10", "2012-11"])
    # the union of all three, deduped and sorted - the real call shape
    both = precip_flood_era.window_months([span, mid, early])
    assert both == (["2010-09", "2010-10", "2011-08", "2012-10", "2012-11"],
                    ["2010-10", "2011-08", "2012-10", "2012-11"])


def test_disk_gate_blocks_when_cold_storage_is_short(tmp_path):
    """The gate names the path before a 120-month run starts; 'blocked' is the
    window-sliced fallback's trigger, and main() refuses to build under it."""
    assert precip_flood_era.disk_gate(tmp_path, 1, 1)[0] == "full"
    path, needed, _ = precip_flood_era.disk_gate(tmp_path, 10**7, 10**7)
    assert path == "blocked" and needed > 1e5


@pytest.fixture(scope="module")
def irene(spark, tmp_path_factory):
    """2011-08, Hurricane Irene: a flood-era union-event month through the same
    per-(src, month) job, from a 48 h cut of the real Bronze Zarr."""
    root = tmp_path_factory.mktemp("irene")
    (root / "archive" / "precip" / "aorc").mkdir(parents=True)
    shutil.copytree(FIXTURES / "aorc-irene.zarr", root / "archive" / "precip" / "aorc" / "2011-08.zarr")
    (root / "ref" / "cell_pixel").mkdir(parents=True)
    shutil.copy(FIXTURES / "ref-cell_pixel-aorc.parquet", root / "ref" / "cell_pixel" / "part-00000.parquet")
    (root / "ref" / "cells").mkdir(parents=True)
    shutil.copy(FIXTURES / "ref-cells-ids.parquet", root / "ref" / "cells" / "part-00000.parquet")
    (root / "ref" / "grids").mkdir(parents=True)
    pq.write_table(pa.table({"grid_id": ["aorc"], "origin_lon": [-130.0], "origin_lat": [20.0],
                             "step_deg": [0.008332999999993262]}),
                   root / "ref" / "grids" / "part-00000.parquet")
    precip.hourly(root, "aorc", "2011-08")
    precip.cell_hourly(root, spark, "aorc", "2011-08")
    return root


IRENE_PEAK = "2011-08-28 06:00:00+00"  # Irene's Central Park peak hour, UTC hour-ending


def test_irene_flood_era_pinned_numbers(irene):
    """Known answers computed independently (xarray x the crosswalk weights, outside the
    job) on this fixture: Central Park's peak Irene hour and the 24 h storm total ending
    on it. mm_24h spends 23 hours of lookback that live inside the same fixture month."""
    con = duck.connect()
    p = f"{irene}/silver/precip_cell_hourly/**/*.parquet"
    mm1, mm24, n24, t2m = con.execute(
        f"SELECT mm_1h, mm_24h, n_hours_24h, t2m_c FROM read_parquet(?) "
        f"WHERE cell = ? AND hour_end_utc = timestamp '{IRENE_PEAK}'",
        [p, CENTRAL_PARK_CELL]).fetchone()
    assert mm1 == pytest.approx(25.01, abs=0.05)
    assert mm24 == pytest.approx(94.67, abs=0.05) and n24 == 24
    assert t2m == pytest.approx(20.76, abs=0.05)


def test_irene_window_coverage_gate(irene):
    """The ticket's headline assertion on a month that has the hours, and the same
    assertion FAILING (SystemExit, never a silent pass) on a Window hour it does not."""
    scored = [CENTRAL_PARK_CELL, CENTRAL_PARK_CELL + 1]
    (irene / "ref" / "assets").mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({
        "asset_id": [f"cell:{c:x}" for c in scored] + ["bus:1"],
        "kind": ["cell", "cell", "bus_stop"],
        "cell": pa.array(scored + [CENTRAL_PARK_CELL], pa.int64()),
        # only the Central Park Cell is scored: its neighbour is a Cell row we do not score
        "scored": [True, False, False],
    }), irene / "ref" / "assets" / "part-00000.parquet")
    window = [(utc("2011-08-28T00:00"), utc("2011-08-28T12:00"))]
    assert precip_flood_era.assert_window_coverage(irene, window, ["2011-08"]) == 13
    outside = [(utc("2011-08-20T00:00"), utc("2011-08-20T03:00"))]  # month built, hours absent
    with pytest.raises(SystemExit, match="Window coverage"):
        precip_flood_era.assert_window_coverage(irene, outside, ["2011-08"])


def test_no_mrms_rows_in_the_fit_era(irene):
    """ADR-0002 / never-pooled: an MRMS partition carrying a fit-era hour is a build
    failure, and an absent MRMS partition is not."""
    precip_flood_era.assert_no_mrms_in_fit_era(irene)  # no src=mrms yet: passes
    out = irene / "silver" / "precip_cell_hourly" / "src=mrms" / "month=2011-08"
    out.mkdir(parents=True)
    pq.write_table(pa.table({"cell": pa.array([CENTRAL_PARK_CELL], pa.int64()),
                             "hour_end_utc": pa.array([utc(IRENE_PEAK[:19])], TS),
                             "mm_1h": pa.array([1.0], pa.float32())}),
                   out / "part-00000.parquet")
    with pytest.raises(SystemExit, match="never pooled"):
        precip_flood_era.assert_no_mrms_in_fit_era(irene)
    shutil.rmtree(out.parent)
