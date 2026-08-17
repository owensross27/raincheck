"""
Ticket 10 / M4: AORC hourly precip -> Cell-hour matrix -> monthly coverage stats,
for every AORC year 2017-2024, over the 4,113 H3 res-8 cells in cells_aorc.parquet.

Cell-hour precip = sum(weight * mm) over a cell's pixels, using the crosswalk in
cell_pixel_aorc.parquet (cell, i, j, weight; weight sums to 1 per cell). NaN in any
weighted pixel propagates to NaN for that cell-hour for free, via plain float
multiply-accumulate (sparse-matrix dot with a NaN operand yields NaN) -- no special
masking code needed.

Run:
  RAINCHECK_SCRATCH=<dir> uv run --no-project --with xarray,zarr,s3fs,pandas,pyarrow,h3,numpy python research/10-aorc-wet-census.py
"""
import gc
import json
import time
import warnings

import h3
import numpy as np
import pandas as pd
import s3fs
import scipy.sparse as sp
import os
import xarray as xr

warnings.filterwarnings("ignore")

SCRATCH = os.environ.get("RAINCHECK_SCRATCH", os.path.expanduser("~/raincheck-scratch"))  # cells_aorc.parquet + cell_pixel_aorc.parquet (09/08 builders) live here
CELLS_PATH = f"{SCRATCH}/cells_aorc.parquet"
XWALK_PATH = f"{SCRATCH}/cell_pixel_aorc.parquet"
OUT_PARQUET = f"{SCRATCH}/m4/aorc_month_cell_stats.parquet"
OUT_LOG = f"{SCRATCH}/m4/run_log.json"

YEARS = list(range(2017, 2025))
LON_BBOX = (-74.30, -73.65)
LAT_BBOX = (40.45, 40.95)
WET_MM = 1.0
HEAVY5_MM = 5.0
HEAVY127_MM = 12.7
DRY_MM = 0.1
RAIN_NOT_SNOW_K = 275.15  # 08's rule
WET_HOUR_MM_A = 1.0
WET_HOUR_MM_B = 0.1
WET_DAY_MM_A = 1.0
WET_DAY_MM_B = 10.0

FIXTURES = [
    ("2021-09-02T02:00:00", "882a100895fffff", 84.28),
    ("2021-09-02T03:00:00", "882a100895fffff", None),
    ("2023-09-29T12:00:00", "882a100895fffff", None),
    ("2023-09-29T13:00:00", "882a100895fffff", None),
    ("2023-09-29T14:00:00", "882a100895fffff", None),
    ("2023-09-29T15:00:00", "882a100895fffff", None),
    ("2023-09-29T16:00:00", "882a100895fffff", None),
]

WINDOWS = [
    ("W1", "2021-08-16", "2021-10-15"),
    ("W2", "2023-09-01", "2023-10-31"),
    ("W3", "2021-09-01", "2021-09-30"),
    ("W4", "2023-09-01", "2023-09-30"),
    ("W5", "2018-10-01", "2018-10-31"),
    ("W6", "2022-05-01", "2022-05-31"),
    ("W7", "2019-09-01", "2019-10-31"),
    ("W8", "2024-08-01", "2024-09-30"),
    ("W9", "2018-08-01", "2018-09-30"),
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def open_year(fs, year, retries=1):
    store = s3fs.S3Map(root=f"s3://noaa-nws-aorc-v1-1-1km/{year}.zarr", s3=fs, check=False)
    for attempt in range(retries + 1):
        try:
            return xr.open_zarr(store, consolidated=True)
        except Exception as e:
            if attempt == retries:
                raise
            log(f"  open_zarr {year} failed ({e!r}), retrying once")
            time.sleep(3)


def bbox_indices(ds):
    lons = ds.longitude.values
    lats = ds.latitude.values
    i0 = max(0, int(np.searchsorted(lons, LON_BBOX[0])) - 1)
    i1 = min(len(lons), int(np.searchsorted(lons, LON_BBOX[1])) + 1)
    j0 = max(0, int(np.searchsorted(lats, LAT_BBOX[0])) - 1)
    j1 = min(len(lats), int(np.searchsorted(lats, LAT_BBOX[1])) + 1)
    return i0, i1, j0, j1


def build_W(pixel_df, cell_order, i0, j0, ni, nj):
    cell_idx = {c: k for k, c in enumerate(cell_order)}
    rows = pixel_df["cell"].map(cell_idx).values
    cols = (pixel_df["j"].values - j0) * ni + (pixel_df["i"].values - i0)
    W = sp.csr_matrix(
        (pixel_df["weight"].values.astype(np.float64), (rows, cols)),
        shape=(len(cell_order), ni * nj),
    )
    return W


def load_year_slab(ds, var, i0, i1, j0, j1, retries=1):
    for attempt in range(retries + 1):
        try:
            arr = ds[var].isel(
                latitude=slice(j0, j1), longitude=slice(i0, i1)
            ).load().values.astype(np.float32)
            return arr
        except Exception as e:
            if attempt == retries:
                log(f"  whole-year load of {var} failed twice ({e!r}); falling back to month chunks")
                return load_year_slab_by_month(ds, var, i0, i1, j0, j1)
            log(f"  load {var} failed ({e!r}), retrying once")
            time.sleep(3)


def load_year_slab_by_month(ds, var, i0, i1, j0, j1):
    tvals = pd.DatetimeIndex(ds.time.values)
    parts = []
    for mm in range(1, 13):
        mask = tvals.month == mm
        idxs = np.where(mask)[0]
        if len(idxs) == 0:
            continue
        sub = ds[var].isel(
            time=slice(idxs[0], idxs[-1] + 1), latitude=slice(j0, j1), longitude=slice(i0, i1)
        ).load().values.astype(np.float32)
        parts.append(sub)
    return np.concatenate(parts, axis=0)


def to_cellhour(slab, W, T, nj, ni):
    flat = slab.reshape(T, nj * ni).astype(np.float64).T  # (npix, T)
    out = W.dot(flat).T  # (T, ncell)
    return out.astype(np.float32)


def month_stats(ym, apcp_m, tmp_m, prev_m, citywide_mean_m, dates_m):
    n_hours, ncell = apcp_m.shape
    total_cellhours = n_hours * ncell

    wet_mask = apcp_m >= WET_MM
    wet_cellhours = int(np.sum(wet_mask))

    rain_mask = wet_mask & (tmp_m > RAIN_NOT_SNOW_K)
    wet_rain_cellhours = int(np.sum(rain_mask))

    heavy5 = int(np.sum(apcp_m >= HEAVY5_MM))
    heavy127 = int(np.sum(apcp_m >= HEAVY127_MM))

    dry_mask = (apcp_m < DRY_MM) & (prev_m < DRY_MM)
    dry_cellhours = int(np.sum(dry_mask))

    wet_hours_1mm = int(np.sum(citywide_mean_m >= WET_HOUR_MM_A))
    wet_hours_0p1mm = int(np.sum(citywide_mean_m >= WET_HOUR_MM_B))

    flat_idx = int(np.nanargmax(apcp_m))
    hi, ci = np.unravel_index(flat_idx, apcp_m.shape)
    max_val = float(apcp_m[hi, ci])

    day_totals = pd.Series(citywide_mean_m).groupby(dates_m).sum()
    n_days = day_totals.shape[0]
    wet_days_1mm = int((day_totals >= WET_DAY_MM_A).sum())
    wet_days_10mm = int((day_totals >= WET_DAY_MM_B).sum())

    null_cellhours = int(np.sum(np.isnan(apcp_m)))

    return dict(
        year_month=ym,
        n_hours=n_hours,
        n_days=n_days,
        total_cellhours=total_cellhours,
        null_cellhours=null_cellhours,
        null_share=null_cellhours / total_cellhours,
        wet_cellhours=wet_cellhours,
        wet_share=wet_cellhours / total_cellhours,
        wet_rain_cellhours=wet_rain_cellhours,
        wet_rain_share=wet_rain_cellhours / total_cellhours,
        heavy5_cellhours=heavy5,
        heavy127_cellhours=heavy127,
        dry_cellhours=dry_cellhours,
        dry_share=dry_cellhours / total_cellhours,
        wet_hours_1mm=wet_hours_1mm,
        wet_hours_0p1mm=wet_hours_0p1mm,
        max_cellhour_mm=max_val,
        max_cell_idx=int(ci),
        max_hour_pos=int(hi),
        wet_days_1mm=wet_days_1mm,
        wet_days_10mm=wet_days_10mm,
    )


def main():
    t_start = time.time()
    cells = pd.read_parquet(CELLS_PATH)
    pixel_df = pd.read_parquet(XWALK_PATH)
    cell_order = cells["cell"].values
    ncell = len(cell_order)
    log(f"cells={ncell} pixel_rows={len(pixel_df)}")

    fs = s3fs.S3FileSystem(anon=True)

    month_rows = []
    fixture_results = []
    window_rows = []
    window_top_hours = {}
    timings = {}
    nan_report = {}

    carry_prev_row = None  # last hour's apcp cell-hour row from previous year, for dry-rule continuity
    carry_prev_year = None

    windows_by_year = {}
    for wname, wstart, wend in WINDOWS:
        y = pd.Timestamp(wstart).year
        assert pd.Timestamp(wend).year == y, f"{wname} spans two years, code assumes single-year windows"
        windows_by_year.setdefault(y, []).append((wname, pd.Timestamp(wstart).date(), pd.Timestamp(wend).date()))

    for year in YEARS:
        ty0 = time.time()
        log(f"=== year {year} ===")
        ds = open_year(fs, year, retries=1)
        i0, i1, j0, j1 = bbox_indices(ds)
        ni, nj = i1 - i0, j1 - j0
        log(f"  bbox indices i0={i0} i1={i1} j0={j0} j1={j1} (ni={ni} nj={nj})")

        xwalk_ok = (
            pixel_df["i"].min() >= i0 and pixel_df["i"].max() < i1
            and pixel_df["j"].min() >= j0 and pixel_df["j"].max() < j1
        )
        assert xwalk_ok, "crosswalk pixel range falls outside computed bbox slice"

        W = build_W(pixel_df, cell_order, i0, j0, ni, nj)

        time_vals = ds.time.values
        T = len(time_vals)
        tidx = pd.DatetimeIndex(time_vals)
        log(f"  T={T} hours, loading APCP_surface slab...")
        t0 = time.time()
        apcp_slab = load_year_slab(ds, "APCP_surface", i0, i1, j0, j1)
        t_apcp = time.time() - t0
        log(f"  APCP loaded shape={apcp_slab.shape} in {t_apcp:.1f}s, nan_count={int(np.isnan(apcp_slab).sum())}")

        t0 = time.time()
        tmp_slab = load_year_slab(ds, "TMP_2maboveground", i0, i1, j0, j1)
        t_tmp = time.time() - t0
        log(f"  TMP loaded shape={tmp_slab.shape} in {t_tmp:.1f}s, nan_count={int(np.isnan(tmp_slab).sum())}")

        apcp_ch = to_cellhour(apcp_slab, W, T, nj, ni)  # (T, ncell) mm
        tmp_ch = to_cellhour(tmp_slab, W, T, nj, ni)  # (T, ncell) K
        del apcp_slab, tmp_slab
        gc.collect()

        always_null_cells = int(np.sum(np.all(np.isnan(apcp_ch), axis=0)))
        any_null_cells = int(np.sum(np.any(np.isnan(apcp_ch), axis=0)))
        # full-grid-NaN hours = an actual source data gap (every cell NaN that hour),
        # distinct from the permanent 168-cell land/sea mask which is always/any-equal.
        full_gap_mask = np.all(np.isnan(apcp_ch), axis=1)
        full_gap_hours = [str(pd.Timestamp(t)) for t in time_vals[full_gap_mask]]
        nan_report[year] = dict(
            always_null_cells=always_null_cells,
            any_null_cells=any_null_cells,
            total_cells=ncell,
            full_grid_gap_hours=full_gap_hours,
        )
        log(f"  cells with NaN cell-hour: always={always_null_cells} any={any_null_cells} of {ncell}; full-grid gap hours={len(full_gap_hours)}")

        # prev-hour array for the dry rule, carrying the last hour of the previous
        # processed year across the boundary. First hour of 2017 (no prior year
        # loaded) gets NaN prev -> excluded from the dry count for that one hour.
        prev_ch = np.empty_like(apcp_ch)
        if carry_prev_row is not None and carry_prev_year == year - 1:
            prev_ch[0] = carry_prev_row
        else:
            prev_ch[0] = np.nan
        prev_ch[1:] = apcp_ch[:-1]
        carry_prev_row = apcp_ch[-1].copy()
        carry_prev_year = year

        citywide_mean = np.nanmean(apcp_ch, axis=1)  # (T,)
        dates = tidx.date  # calendar date of the hour-ending label

        # fixture checks for this year
        for ts_str, hexid, expected in FIXTURES:
            ts = pd.Timestamp(ts_str)
            if ts.year != year:
                continue
            pos = np.searchsorted(time_vals, np.datetime64(ts_str))
            if pos >= T or time_vals[pos] != np.datetime64(ts_str):
                fixture_results.append(dict(ts=ts_str, hex=hexid, found=False))
                continue
            target_cell = h3.str_to_int(hexid)
            ci = int(np.where(cell_order == target_cell)[0][0])
            val = float(apcp_ch[pos, ci])
            fixture_results.append(
                dict(
                    ts=ts_str,
                    hex=hexid,
                    cell_hour_mm=val,
                    expected_mm=expected,
                    citywide_mean_mm=float(citywide_mean[pos]),
                )
            )

        # monthly aggregation
        months = sorted(set(zip(tidx.year, tidx.month)))
        for yy, mm in months:
            mask = (tidx.year == yy) & (tidx.month == mm)
            idxs = np.where(mask)[0]
            ym = f"{yy:04d}-{mm:02d}"
            stats = month_stats(
                ym,
                apcp_ch[idxs],
                tmp_ch[idxs],
                prev_ch[idxs],
                citywide_mean[idxs],
                dates[idxs],
            )
            max_cell_id = int(cell_order[stats.pop("max_cell_idx")])
            max_hour_pos = idxs[stats.pop("max_hour_pos")]
            stats["max_cell_h3"] = h3.int_to_str(max_cell_id)
            stats["max_hour_end_utc"] = str(pd.Timestamp(time_vals[max_hour_pos]))
            month_rows.append(stats)

        # window stats (this year's windows only)
        for wname, wstart, wend in windows_by_year.get(year, []):
            wmask = (dates >= wstart) & (dates <= wend)
            widxs = np.where(wmask)[0]
            wet_ch = int(np.sum(apcp_ch[widxs] >= WET_MM))
            dry_ch = int(np.sum((apcp_ch[widxs] < DRY_MM) & (prev_ch[widxs] < DRY_MM)))
            wet_hr = int(np.sum(citywide_mean[widxs] >= WET_HOUR_MM_A))
            total_ch = len(widxs) * ncell
            top3_pos = widxs[np.argsort(citywide_mean[widxs])[::-1][:3]]
            top3 = [
                dict(hour_end_utc=str(pd.Timestamp(time_vals[p])), citywide_mean_mm=float(citywide_mean[p]))
                for p in top3_pos
            ]
            window_rows.append(
                dict(
                    window=wname,
                    start=str(wstart),
                    end=str(wend),
                    n_hours=len(widxs),
                    total_cellhours=total_ch,
                    wet_cellhours=wet_ch,
                    wet_share=wet_ch / total_ch if total_ch else float("nan"),
                    wet_hours=wet_hr,
                    dry_cellhours=dry_ch,
                    dry_share=dry_ch / total_ch if total_ch else float("nan"),
                )
            )
            window_top_hours[wname] = top3

        del apcp_ch, tmp_ch, prev_ch, citywide_mean
        gc.collect()
        timings[year] = dict(apcp_load_s=round(t_apcp, 1), tmp_load_s=round(t_tmp, 1), total_s=round(time.time() - ty0, 1))
        log(f"  year {year} done in {timings[year]['total_s']}s")

    total_time = time.time() - t_start
    log(f"all years done in {total_time:.1f}s")

    month_df = pd.DataFrame(month_rows).sort_values("year_month").reset_index(drop=True)
    month_df.to_parquet(OUT_PARQUET, index=False)
    log(f"wrote {OUT_PARQUET} rows={len(month_df)}")

    window_df = pd.DataFrame(window_rows)

    with open(OUT_LOG, "w") as f:
        json.dump(
            dict(
                timings=timings,
                nan_report=nan_report,
                fixture_results=fixture_results,
                total_time_s=round(total_time, 1),
            ),
            f,
            indent=2,
            default=str,
        )
    log(f"wrote {OUT_LOG}")

    # stash for the report-writing step
    month_df.to_json(f"{SCRATCH}/m4/month_df.json", orient="records")
    window_df.to_json(f"{SCRATCH}/m4/window_df.json", orient="records")
    with open(f"{SCRATCH}/m4/window_top_hours.json", "w") as f:
        json.dump(window_top_hours, f, indent=2, default=str)

    log("DONE")


if __name__ == "__main__":
    main()
