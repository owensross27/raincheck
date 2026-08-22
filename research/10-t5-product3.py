"""10-T5 (ticket 06, report-only): Product 3 - the raster path exercised once. Over the
two storm composites (Ida 2021-09-02 02Z-08Z, 2023-09-29 10Z-21Z): AORC read at each
kept Leg's midpoint through Sedona rasters (RS_MakeEmptyRaster + RS_MakeRaster per hour,
one grouped RS_Values call per hour - the playbook pattern), versus the area-weighted
Cell mean from silver/precip_cell_hourly. Reports the pixel-vs-cell difference
distribution and the rain-vs-Speed slope both ways (per Cell-hour OLS). Numbers go into
research/08-weather-join-evidence.md; the raster path then retires (spec H).

Run after the slice is loaded:  .venv/bin/python research/10-t5-product3.py
"""
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from raincheck.enrich import legs
from raincheck.paths import data_root

STORMS = {  # composite label -> (bronze dates to read, hour-ending labels UTC)
    "ida-2021-09-02-02Z-08Z": (
        ["2021-09-01", "2021-09-02", "2021-09-03"],
        [datetime(2021, 9, 2, h, tzinfo=timezone.utc) for h in range(2, 9)], "2021-09"),
    "2023-09-29-10Z-21Z": (
        ["2023-09-28", "2023-09-29", "2023-09-30"],
        [datetime(2023, 9, 29, h, tzinfo=timezone.utc) for h in range(10, 22)], "2023-09"),
}


def hour_rasters(root: Path, spark, month: str, hours: list[datetime]):
    """One north-up EPSG:4326 raster per hour from the Bronze AORC month slice."""
    import xarray as xr

    ds = xr.open_zarr(root / "archive" / "precip" / "aorc" / f"{month}.zarr", consolidated=True)
    lon, lat = ds.longitude.values, ds.latitude.values
    step = float(lon[1] - lon[0])
    ulx, uly = float(lon[0]) - step / 2, float(lat[-1]) + step / 2  # NW pixel corner
    rows = []
    for h in hours:
        arr = ds.APCP_surface.sel(time=np.datetime64(h.replace(tzinfo=None))).values
        arr = np.where(arr < 0, np.nan, arr)[::-1]  # negatives NULL; flip to north-up
        rows.append((h, [float(v) for v in arr.ravel()]))
    df = spark.createDataFrame(rows, "hour_end_utc timestamp, band array<double>")
    df.selectExpr(
        "hour_end_utc",
        f"RS_MakeRaster(RS_MakeEmptyRaster(1, {lon.size}, {lat.size}, {ulx}, {uly}, "
        f"{step}, {-step}, 0, 0, 4326), 'D', band) AS rast",
    ).createOrReplaceTempView("rasters")


def storm_legs(root: Path, spark, dates: list[str], hours: list[datetime]) -> None:
    vp = root / "archive" / "vp"
    paths = [str(vp / f"date={d}") for d in dates if (vp / f"date={d}").exists()]
    lg = legs(spark.read.option("basePath", str(vp)).parquet(*paths))
    hour_set = ", ".join(f"timestamp'{h:%Y-%m-%d %H:%M:%S}'" for h in hours)
    (lg.where(f"dropped IS NULL AND hour_end_utc IN ({hour_set})")
       .select("cell", "hour_end_utc", "dist_m", "dt_s", "mid_lon", "mid_lat")
       .createOrReplaceTempView("storm_legs"))


def slope(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    b, _ = np.polyfit(x, y, 1)
    r = float(np.corrcoef(x, y)[0, 1])
    return float(b), r


def report(root: Path, spark, name: str) -> None:
    # one grouped RS_Values call per hour (raster decodes once), zipped back to rows
    per_leg = spark.sql("""
        WITH pts AS (
          SELECT hour_end_utc, collect_list(ST_Point(mid_lon, mid_lat)) AS pts,
                 collect_list(struct(cell, dist_m, dt_s)) AS meta
          FROM storm_legs GROUP BY hour_end_utc
        ), joined AS (
          SELECT p.hour_end_utc, p.meta, RS_Values(r.rast, p.pts, 1) AS vals
          FROM pts p JOIN rasters r USING (hour_end_utc)
        )
        SELECT hour_end_utc, meta[pos].cell AS cell, meta[pos].dist_m AS dist_m,
               meta[pos].dt_s AS dt_s, val AS pixel_mm
        FROM joined LATERAL VIEW posexplode(vals) t AS pos, val
    """)
    per_leg.createOrReplaceTempView("per_leg")
    pc = str(root / "silver" / "precip_cell_hourly")
    cell_hour = spark.sql(f"""
        SELECT l.cell, l.hour_end_utc,
               sum(l.dist_m) / sum(l.dt_s) AS speed_ms,
               avg(l.pixel_mm) AS mm_pixel, first(p.mm_1h) AS mm_cell,
               count(*) AS n_legs
        FROM per_leg l
        JOIN parquet.`{pc}` p ON p.src = 'aorc' AND p.cell = l.cell
                             AND p.hour_end_utc = l.hour_end_utc
        WHERE l.pixel_mm IS NOT NULL AND NOT isnan(l.pixel_mm) AND p.mm_1h IS NOT NULL
        GROUP BY 1, 2
    """).toPandas()
    if cell_hour.empty:
        print(f"\n== {name}: no matched Cell-hours (raster/crosswalk mismatch?) - skipped")
        return
    d = (cell_hour.mm_pixel - cell_hour.mm_cell).to_numpy()
    speed = cell_hour.speed_ms.to_numpy()
    b_px, r_px = slope(cell_hour.mm_pixel.to_numpy(), speed)
    b_cl, r_cl = slope(cell_hour.mm_cell.to_numpy(), speed)
    print(f"\n== {name}: {len(cell_hour)} Cell-hours, {int(cell_hour.n_legs.sum())} legs")
    print(f"pixel - cell mm: p50={np.percentile(np.abs(d), 50):.3f} "
          f"p90={np.percentile(np.abs(d), 90):.3f} mean={d.mean():+.3f} "
          f"corr={np.corrcoef(cell_hour.mm_pixel, cell_hour.mm_cell)[0, 1]:.4f}")
    print(f"speed ~ mm at Leg midpoint (RS_Values): slope={b_px:+.4f} m/s per mm  r={r_px:+.3f}")
    print(f"speed ~ Cell mean mm (crosswalk):       slope={b_cl:+.4f} m/s per mm  r={r_cl:+.3f}")


def main() -> None:
    from raincheck.spark import session

    root = data_root()
    spark = session()
    for name, (dates, hours, month) in STORMS.items():
        hour_rasters(root, spark, month, hours)
        storm_legs(root, spark, dates, hours)
        report(root, spark, name)


if __name__ == "__main__":
    main()
