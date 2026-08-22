"""`make precip-hourly SRC= MONTH=` and `make precip-cell SRC= MONTH=` (ticket 04 / spec H):
the Pixel-grain and Cell-grain precipitation tables, one (src, month) per call, months
buildable in any order (the Cell build takes its 24 h lookback from `precip_hourly`,
never from a prior month's own output).

silver/precip_hourly/src=/month=      one file, sorted (i, j, hour_end_utc), dense over
                                      footprint x published hours; negative or missing
                                      values are stored NULL rows, never dropped
silver/precip_cell_hourly/src=/month= one file, sorted (cell, hour_end_utc), dense over
                                      4,113 Cells x every hour of the month; mm_1h NULL
                                      unless the realized non-null Pixel weight sums to 1
                                      within 1e-6; mm_3h/mm_6h NULL if any frame hour is
                                      NULL; mm_24h with n_hours_24h; t2m_c (AORC only)

The AORC NYC slice is materialised into Bronze `archive/precip/aorc/<YYYY-MM>.zarr` on
first touch (the fidelity copy and the rolling-sum test oracle) and read from Bronze
thereafter. SRC=mrms lands with ticket 11.
"""
import argparse
import calendar
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from raincheck.paths import data_root

AORC_STORE = "s3://noaa-nws-aorc-v1-1-1km/{year}.zarr"
TS = pa.timestamp("us", tz="UTC")


def month_span(month: str) -> tuple[datetime, datetime]:
    """(first Hour, last Hour) of the month's hour-ending labels, UTC."""
    y, m = map(int, month.split("-"))
    last = calendar.monthrange(y, m)[1]
    return (datetime(y, m, 1, tzinfo=timezone.utc),
            datetime(y, m, last, 23, tzinfo=timezone.utc))


def footprint(root: Path, src: str) -> pa.Table:
    """The crosswalk's distinct Pixel set for one grid, sorted (i, j) - the stored footprint."""
    t = pq.read_table(root / "ref" / "cell_pixel", columns=["grid_id", "i", "j"])
    t = t.filter(pc.equal(t.column("grid_id"), src)).select(["i", "j"])
    return t.group_by(["i", "j"]).aggregate([]).sort_by([("i", "ascending"), ("j", "ascending")])


def bronze_aorc(root: Path, month: str) -> Path:
    """Materialise the Bronze AORC NYC month slice from the cloud Zarr on first touch."""
    out = root / "archive" / "precip" / "aorc" / f"{month}.zarr"
    if out.exists():
        return out
    import xarray as xr  # heavy; only on first touch

    fp = footprint(root, "aorc")
    i_lo, i_hi = pc.min(fp.column("i")).as_py(), pc.max(fp.column("i")).as_py()
    j_lo, j_hi = pc.min(fp.column("j")).as_py(), pc.max(fp.column("j")).as_py()
    lo, hi = month_span(month)
    print(f"materialising {out.name} from the cloud Zarr (i {i_lo}..{i_hi}, j {j_lo}..{j_hi})", flush=True)
    ds = xr.open_zarr(AORC_STORE.format(year=lo.year), storage_options={"anon": True}, consolidated=True)
    cut = ds[["APCP_surface", "TMP_2maboveground"]].isel(
        latitude=slice(j_lo, j_hi + 1), longitude=slice(i_lo, i_hi + 1)
    ).sel(time=slice(np.datetime64(lo.replace(tzinfo=None)), np.datetime64(hi.replace(tzinfo=None)))).compute()
    staging = root / ".staging" / out.name
    shutil.rmtree(staging, ignore_errors=True)
    staging.parent.mkdir(parents=True, exist_ok=True)
    shape = (cut.sizes["time"], cut.sizes["latitude"], cut.sizes["longitude"])
    cut.to_zarr(staging, mode="w", zarr_format=2, consolidated=True,
                encoding={v: {"chunks": shape} for v in ("APCP_surface", "TMP_2maboveground")})
    out.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(out)
    return out


def hourly(root: Path, src: str, month: str) -> None:
    if src != "aorc":
        sys.exit("precip-hourly SRC=mrms lands with ticket 11")
    import xarray as xr

    ds = xr.open_zarr(bronze_aorc(root, month), consolidated=True)
    grids = pq.read_table(root / "ref" / "grids").to_pylist()
    g = next(r for r in grids if r["grid_id"] == src)
    i_abs = np.rint((ds.longitude.values - g["origin_lon"]) / g["step_deg"]).astype(int)
    j_abs = np.rint((ds.latitude.values - g["origin_lat"]) / g["step_deg"]).astype(int)
    fp = footprint(root, src)
    i_px, j_px = fp.column("i").to_numpy(), fp.column("j").to_numpy()
    # the Bronze cut starts at the footprint's SW corner, so the slice's first coordinate
    # must map to exactly min(i)/min(j) - an absolute check, not just contiguity
    if i_abs[0] != i_px.min() or j_abs[0] != j_px.min():
        sys.exit(f"precip-hourly {src} {month}: Bronze slice origin ({i_abs[0]}, {j_abs[0]}) "
                 f"does not match the crosswalk footprint ({i_px.min()}, {j_px.min()})")
    i_rel, j_rel = i_px - i_abs[0], j_px - j_abs[0]
    assert (i_abs[i_rel] == i_px).all() and (j_abs[j_rel] == j_px).all()

    lo, hi = month_span(month)
    times = ds.time.values  # hour-ending labels (measured, ADR-0002 side)
    keep = (times >= np.datetime64(lo.replace(tzinfo=None))) & (times <= np.datetime64(hi.replace(tzinfo=None)))
    times = times[keep]
    mm = ds.APCP_surface.values[keep][:, j_rel, i_rel]      # (T, P)
    t2m = ds.TMP_2maboveground.values[keep][:, j_rel, i_rel]
    n_t, n_p = mm.shape
    # sorted (i, j, hour_end_utc): pixel-major, hours within pixel
    order_t = times.astype("datetime64[us]").astype(np.int64)
    table = pa.table({
        "i": pa.array(np.repeat(i_px, n_t), pa.int16()),
        "j": pa.array(np.repeat(j_px, n_t), pa.int16()),
        "hour_end_utc": pa.array(np.tile(order_t, n_p), TS),
        "mm": pa.array(np.where(mm.T < 0, np.nan, mm.T).ravel(), pa.float32(),
                       from_pandas=True),  # NaN -> NULL; negative sentinel -> NULL row
        "t2m_k": pa.array(t2m.T.ravel(), pa.float32(), from_pandas=True),
    })
    out = root / "silver" / "precip_hourly" / f"src={src}" / f"month={month}" / "part-00000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out, compression="zstd")
    print(f"precip_hourly src={src} month={month}: {table.num_rows} rows "
          f"({n_p} pixels x {n_t} hours)", flush=True)


def cell_hourly(root: Path, spark, src: str, month: str) -> None:
    lo, hi = month_span(month)
    ph = spark.read.parquet(str(root / "silver" / "precip_hourly")).where(
        f"src = '{src}' AND hour_end_utc BETWEEN timestamp'{lo:%Y-%m-%d %H:%M:%S}' - INTERVAL 24 HOUR "
        f"AND timestamp'{hi:%Y-%m-%d %H:%M:%S}'")
    cpx = spark.read.parquet(str(root / "ref" / "cell_pixel")).where(f"grid_id = '{src}'")
    cells = spark.read.parquet(str(root / "ref" / "cells")).select("cell")
    view = f"ph_{month.replace('-', '_')}"
    ph.createOrReplaceTempView(view + "_p")
    cpx.createOrReplaceTempView(view + "_x")
    cells.createOrReplaceTempView(view + "_c")
    # research 08 section 5, Spark text: explode(sequence(...)) spine, inline window frames
    df = spark.sql(f"""
        WITH hours AS (
          SELECT explode(sequence(timestamp'{lo:%Y-%m-%d %H:%M:%S}' - INTERVAL 24 HOUR,
                                  timestamp'{hi:%Y-%m-%d %H:%M:%S}', INTERVAL 1 HOUR)) AS hour_end_utc
        ), cell_hour AS (
          SELECT x.cell, p.hour_end_utc,
                 CASE WHEN sum(x.weight) FILTER (WHERE p.mm IS NOT NULL) < 1 - 1e-6 THEN NULL
                      ELSE sum(x.weight * p.mm) END AS mm_1h,
                 CASE WHEN sum(x.weight) FILTER (WHERE p.t2m_k IS NOT NULL) < 1 - 1e-6 THEN NULL
                      ELSE sum(x.weight * p.t2m_k) - 273.15 END AS t2m_c
          FROM {view}_p p JOIN {view}_x x ON x.i = p.i AND x.j = p.j
          GROUP BY x.cell, p.hour_end_utc
        ), dense AS (
          SELECT c.cell, h.hour_end_utc, ch.mm_1h, ch.t2m_c
          FROM {view}_c c CROSS JOIN hours h
          LEFT JOIN cell_hour ch ON ch.cell = c.cell AND ch.hour_end_utc = h.hour_end_utc
        )
        -- windows over the full spine (lookback included), the month filter OUTSIDE them:
        -- a WHERE in the same SELECT runs before window functions and would blind the
        -- frames to the lookback hours (corrects research 08's sketch, both engines)
        SELECT * FROM (
          SELECT cell, hour_end_utc,
                 cast(mm_1h AS float) AS mm_1h,
                 cast(lag(mm_1h) OVER (PARTITION BY cell ORDER BY hour_end_utc) AS float) AS mm_1h_prev,
                 cast(CASE WHEN count(mm_1h) OVER (PARTITION BY cell ORDER BY hour_end_utc ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) < 3 THEN NULL
                      ELSE sum(mm_1h) OVER (PARTITION BY cell ORDER BY hour_end_utc ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) END AS float) AS mm_3h,
                 cast(CASE WHEN count(mm_1h) OVER (PARTITION BY cell ORDER BY hour_end_utc ROWS BETWEEN 5 PRECEDING AND CURRENT ROW) < 6 THEN NULL
                      ELSE sum(mm_1h) OVER (PARTITION BY cell ORDER BY hour_end_utc ROWS BETWEEN 5 PRECEDING AND CURRENT ROW) END AS float) AS mm_6h,
                 cast(sum(mm_1h) OVER (PARTITION BY cell ORDER BY hour_end_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS float) AS mm_24h,
                 cast(count(mm_1h) OVER (PARTITION BY cell ORDER BY hour_end_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS tinyint) AS n_hours_24h,
                 cast(t2m_c AS float) AS t2m_c
          FROM dense
        )
        WHERE hour_end_utc >= timestamp'{lo:%Y-%m-%d %H:%M:%S}'
    """).coalesce(1).sortWithinPartitions("cell", "hour_end_utc")
    staging = root / ".staging" / f"precip_cell_{src}_{month}"
    df.write.mode("overwrite").parquet(str(staging))
    out = root / "silver" / "precip_cell_hourly" / f"src={src}" / f"month={month}" / "part-00000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    (part,) = staging.glob("part-*.parquet")
    shutil.move(part, out)
    shutil.rmtree(staging)
    print(f"precip_cell_hourly src={src} month={month}: wrote {out}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("table", choices=["hourly", "cell"])
    ap.add_argument("src", choices=["aorc", "mrms"])  # interpolated into SQL and paths
    ap.add_argument("month", help="YYYY-MM")
    args = ap.parse_args()
    datetime.strptime(args.month, "%Y-%m")
    if args.table == "hourly":
        hourly(data_root(), args.src, args.month)
    else:
        from raincheck.spark import session

        cell_hourly(data_root(), session(), args.src, args.month)


if __name__ == "__main__":
    main()
