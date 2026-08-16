"""Ticket 08 evidence: is the MRMS hourly QPE file stamp hour-ending? Central Park
series, MRMS (Pass2, RadarOnly) vs AORC (verified hour-ending), lag -1/0/+1
correlation, for 2023-09-29 and the Ida peak. GRIB2 headers cannot show it (PDT 0,
step 0), so this is the check. Caches GRIB files under ./cache_*. Run from any
scratch dir:

  uv run --no-project --python 3.12 --with s3fs --with eccodes --with numpy \
    --with xarray --with zarr python 08-mrms-hour-ending-check.py
"""
import gzip
from datetime import datetime, timedelta, timezone

import numpy as np
import s3fs
import xarray as xr

SCRATCH = "."
CP_LAT, CP_LON = 40.782, -73.965

# Grid facts established in step 2/3 (verified from decoded GRIB headers, identical for all 3 products)
LAT_FIRST = 54.995
LON_FIRST_360 = 230.005  # == -129.995 in -180..180
DLAT = 0.01
DLON = 0.01
NI, NJ = 7000, 3500


def mrms_ij_for(lat, lon):
    lon_360 = lon + 360 if lon < 0 else lon
    i = int(round((lon_360 - LON_FIRST_360) / DLON))
    j = int(round((LAT_FIRST - lat) / DLAT))
    return i, j


def fetch_mrms_value(f, prod, stamp, i, j, cache_dir):
    s3path = f"noaa-mrms-pds/CONUS/{prod}/{stamp[:8]}/MRMS_{prod}_{stamp}.grib2.gz"
    if not f.exists(s3path):
        return None, "missing"
    localpath = f"{cache_dir}/MRMS_{prod}_{stamp}.grib2"
    if not __import__("os").path.exists(localpath):
        try:
            with f.open(s3path, "rb") as r:
                data = r.read()
            raw = gzip.decompress(data)
            with open(localpath, "wb") as out:
                out.write(raw)
        except Exception as e:
            return None, f"download_error:{e}"
    import eccodes
    with open(localpath, "rb") as fh:
        gid = eccodes.codes_grib_new_from_file(fh)
        if gid is None:
            return None, "no_message"
        Ni = eccodes.codes_get(gid, "Ni")
        vals = eccodes.codes_get_values(gid)
        eccodes.codes_release(gid)
    idx = j * Ni + i
    v = float(vals[idx])
    return v, "ok"


def build_mrms_series(f, prod, day_start_utc, n_points, cache_dir):
    i, j = mrms_ij_for(CP_LAT, CP_LON)
    out = {}
    for h in range(n_points):
        t = day_start_utc + timedelta(hours=h)  # hour-ending timestamp label (== file stamp)
        stamp = t.strftime("%Y%m%d-%H%M%S")
        v, status = fetch_mrms_value(f, prod, stamp, i, j, cache_dir)
        out[t] = (v, status)
    return out


def build_aorc_series(year, day_start_utc, n_points):
    fs_ = s3fs.S3FileSystem(anon=True)
    store = fs_.get_mapper(f"s3://noaa-nws-aorc-v1-1-1km/{year}.zarr")
    ds = xr.open_zarr(store, consolidated=True)
    times = [day_start_utc + timedelta(hours=h) for h in range(n_points)]
    t0, t1 = times[0].replace(tzinfo=None), times[-1].replace(tzinfo=None)
    sub = ds["APCP_surface"].sel(
        latitude=CP_LAT, longitude=CP_LON, method="nearest"
    ).sel(time=slice(t0, t1))
    sub = sub.load()
    out = {}
    for tv, v in zip(sub.time.values, sub.values):
        tpy = datetime.utcfromtimestamp(tv.astype("datetime64[s]").astype(int)).replace(tzinfo=timezone.utc)
        out[tpy] = float(v)
    ds.close()
    return out


def pearson(x, y):
    x = np.array(x, dtype=float)
    y = np.array(y, dtype=float)
    if x.size < 2 or np.all(x == x[0]) or np.all(y == y[0]):
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def lag_corr_report(aorc_series, mrms_series, label):
    # aorc_series, mrms_series: dict[datetime]->value ; align by hour-ending ts, test lags -1,0,+1 (hours)
    common_times = sorted(aorc_series.keys())
    print(f"\n  Lag correlation for {label}:")
    best = None
    for lag in (-1, 0, 1):
        xs, ys = [], []
        for t in common_times:
            t_shift = t + timedelta(hours=lag)
            if t_shift in mrms_series and mrms_series[t_shift][0] is not None:
                xs.append(aorc_series[t])
                ys.append(mrms_series[t_shift][0])
        r = pearson(xs, ys) if len(xs) >= 3 else float("nan")
        print(f"    lag={lag:+d}h  n={len(xs)}  pearson_r={r:.4f}")
        if best is None or (not np.isnan(r) and (np.isnan(best[1]) or r > best[1])):
            best = (lag, r)
    print(f"    best lag: {best[0]:+d}h (r={best[1]:.4f})")
    return best


def run_day(day_start_utc, year, n_points, label, cache_subdir):
    import os
    cache_dir = f"{SCRATCH}/{cache_subdir}"
    os.makedirs(cache_dir, exist_ok=True)
    f = s3fs.S3FileSystem(anon=True)

    print(f"\n=== {label}: {day_start_utc.isoformat()} + {n_points} pts, hour-ending series ===")
    aorc = build_aorc_series(year, day_start_utc, n_points)
    pass2 = build_mrms_series(f, "MultiSensor_QPE_01H_Pass2_00.00", day_start_utc, n_points, cache_dir)
    radar = build_mrms_series(f, "RadarOnly_QPE_01H_00.00", day_start_utc, n_points, cache_dir)

    print(f"{'hour_end_utc':20s} | {'aorc_mm':>8s} | {'mrms_pass2_mm':>13s} | {'mrms_radaronly_mm':>17s}")
    times = sorted(aorc.keys())
    aorc_vals, pass2_vals, radar_vals = [], [], []
    for t in times:
        av = aorc.get(t, float("nan"))
        pv, pstat = pass2.get(t, (None, "n/a"))
        rv, rstat = radar.get(t, (None, "n/a"))
        pv_s = f"{pv:.3f}" if pv is not None else f"GAP({pstat})"
        rv_s = f"{rv:.3f}" if rv is not None else f"GAP({rstat})"
        print(f"{t.isoformat():20s} | {av:8.3f} | {pv_s:>13s} | {rv_s:>17s}")
        aorc_vals.append(av)
        if pv is not None:
            pass2_vals.append(pv)
        if rv is not None:
            radar_vals.append(rv)

    aorc_total = float(np.nansum(aorc_vals))
    pass2_total = float(np.sum(pass2_vals)) if pass2_vals else float("nan")
    radar_total = float(np.sum(radar_vals)) if radar_vals else float("nan")
    n_pass2_gaps = n_points - len(pass2_vals)
    n_radar_gaps = n_points - len(radar_vals)
    print(f"\n  daily totals: aorc={aorc_total:.3f}mm  pass2={pass2_total:.3f}mm (gaps={n_pass2_gaps})  "
          f"radaronly={radar_total:.3f}mm (gaps={n_radar_gaps})")
    if aorc_total > 0:
        print(f"  ratio pass2/aorc={pass2_total/aorc_total:.4f}  ratio radaronly/aorc={radar_total/aorc_total:.4f}")

    lag_corr_report(aorc, pass2, "AORC vs Pass2")
    lag_corr_report(aorc, radar, "AORC vs RadarOnly")
    return dict(aorc=aorc, pass2=pass2, radar=radar, aorc_total=aorc_total,
                pass2_total=pass2_total, radar_total=radar_total)


if __name__ == "__main__":
    i, j = mrms_ij_for(CP_LAT, CP_LON)
    print(f"Central Park MRMS pixel index: i={i} j={j}")

    run_day(datetime(2023, 9, 29, 0, 0, tzinfo=timezone.utc), 2023, 24,
            "2023-09-29 (Ophelia remnants)", "cache_20230929")

    run_day(datetime(2021, 9, 1, 12, 0, tzinfo=timezone.utc), 2021, 25,
            "2021-09-01 12:00 -> 2021-09-02 12:00 (Ida peak)", "cache_ida")
