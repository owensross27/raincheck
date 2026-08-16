"""Ticket 08 evidence: Cell-grain (H3 res-8, area-weighted) vs single-Pixel AORC
precip lookup on three storm hours, plus the wet-hour census and the AORC epoch
check. Read-only, anonymous S3. Writes cell_pixel_aorc.parquet / cells_aorc.parquet
into the working directory. Run from any scratch dir:

  uv run --no-project --python 3.12 --with h3 --with shapely --with pyproj \
    --with s3fs --with xarray --with zarr --with numpy --with pandas --with pyarrow \
    python 08-cell-pixel-compare.py
"""
import time
import numpy as np
import pandas as pd
import s3fs
import xarray as xr
import h3
from shapely.geometry import Polygon
from pyproj import Transformer

SCRATCH = "."
BBOX = dict(lon_min=-74.30, lon_max=-73.65, lat_min=40.45, lat_max=40.95)
TRANSFORMER = Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)


def retry(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        print(f"  [retry] first attempt failed: {e!r}; retrying once...")
        time.sleep(2)
        return fn(*args, **kwargs)


def open_year(fs, year):
    store = s3fs.S3Map(root=f"s3://noaa-nws-aorc-v1-1-1km/{year}.zarr", s3=fs, check=False)
    return retry(xr.open_zarr, store, consolidated=True)


def to_xy(lons, lats):
    x, y = TRANSFORMER.transform(np.asarray(lons), np.asarray(lats))
    return x, y


def poly_area_xy(lons, lats):
    x, y = to_xy(lons, lats)
    return Polygon(zip(x, y))


# ---------------------------------------------------------------------------
# Step 1: AORC grid facts
# ---------------------------------------------------------------------------
def step1_grid(fs):
    print("\n=== STEP 1: AORC grid (2021.zarr) ===")
    ds = open_year(fs, 2021)
    lat = ds.latitude.values
    lon = ds.longitude.values
    print(f"latitude dtype={lat.dtype} first2={lat[:2]} step={lat[1]-lat[0]:.9f} size={lat.size}")
    print(f"longitude dtype={lon.dtype} first2={lon[:2]} step={lon[1]-lon[0]:.9f} size={lon.size}")
    print(f"longitude min={lon.min():.6f} max={lon.max():.6f} -> domain is {'-180..180' if lon.max() < 180 else '0..360'}")
    bound_vars = [v for v in ds.variables if "bnd" in v.lower() or "bound" in v.lower()]
    print(f"bounds variables present: {bound_vars} (none expected -> center registration)")
    lat_diffs = np.diff(lat)
    lon_diffs = np.diff(lon)
    print(f"lat step uniform: min={lat_diffs.min():.9f} max={lat_diffs.max():.9f}")
    print(f"lon step uniform: min={lon_diffs.min():.9f} max={lon_diffs.max():.9f}")
    return ds, lat, lon


# ---------------------------------------------------------------------------
# Step 2: H3 res-8 cells over NYC bbox
# ---------------------------------------------------------------------------
def step2_cells():
    print("\n=== STEP 2: H3 res-8 cells over NYC bbox ===")
    outer = [
        (BBOX["lat_min"], BBOX["lon_min"]),
        (BBOX["lat_min"], BBOX["lon_max"]),
        (BBOX["lat_max"], BBOX["lon_max"]),
        (BBOX["lat_max"], BBOX["lon_min"]),
    ]
    poly = h3.LatLngPoly(outer)
    cells = sorted(h3.polygon_to_cells(poly, 8))
    print(f"cell count: {len(cells)} (expected ~4,113)")
    return cells


# ---------------------------------------------------------------------------
# Step 3: cell x pixel crosswalk
# ---------------------------------------------------------------------------
def step3_crosswalk(cells, lat, lon):
    print("\n=== STEP 3: cell-pixel crosswalk ===")
    lon0 = lon[0]
    lat0 = lat[0]
    lon_step = lon[1] - lon[0]
    lat_step = lat[1] - lat[0]
    nlon = lon.size
    nlat = lat.size

    rows = []  # cell_int, i, j, weight
    cell_meta = []  # cell_int, lon, lat (centroid), i_ctr, j_ctr, i_max, j_max, cell_area_m2, max_share
    sum_check_fail = 0

    for hexid in cells:
        boundary = h3.cell_to_boundary(hexid)  # (lat, lng) tuples
        b_lons = [p[1] for p in boundary]
        b_lats = [p[0] for p in boundary]
        cell_poly = poly_area_xy(b_lons, b_lats)
        cell_area = cell_poly.area

        minlon, maxlon = min(b_lons), max(b_lons)
        minlat, maxlat = min(b_lats), max(b_lats)

        i_lo = int(np.floor((minlon - lon0) / lon_step)) - 1
        i_hi = int(np.ceil((maxlon - lon0) / lon_step)) + 1
        j_lo = int(np.floor((minlat - lat0) / lat_step)) - 1
        j_hi = int(np.ceil((maxlat - lat0) / lat_step)) + 1
        i_lo = max(0, i_lo)
        j_lo = max(0, j_lo)
        i_hi = min(nlon - 1, i_hi)
        j_hi = min(nlat - 1, j_hi)

        candidates = [(i, j) for i in range(i_lo, i_hi + 1) for j in range(j_lo, j_hi + 1)]

        weights = []
        for (i, j) in candidates:
            plon, plat = lon[i], lat[j]
            corner_lons = [plon - lon_step / 2, plon + lon_step / 2, plon + lon_step / 2, plon - lon_step / 2]
            corner_lats = [plat - lat_step / 2, plat - lat_step / 2, plat + lat_step / 2, plat + lat_step / 2]
            pix_poly = poly_area_xy(corner_lons, corner_lats)
            inter = cell_poly.intersection(pix_poly).area
            if inter <= 0:
                continue
            w = inter / cell_area
            weights.append((i, j, w))
            rows.append((h3.str_to_int(hexid), i, j, w))

        wsum = sum(w for _, _, w in weights)
        if abs(wsum - 1.0) >= 1e-9:
            sum_check_fail += 1

        # centroid pixel (nearest) and largest-share pixel
        clat, clon = h3.cell_to_latlng(hexid)
        i_ctr = int(round((clon - lon0) / lon_step))
        j_ctr = int(round((clat - lat0) / lat_step))
        i_max, j_max, w_max = max(weights, key=lambda t: t[2])

        cell_meta.append(
            dict(
                cell=h3.str_to_int(hexid),
                lon=clon,
                lat=clat,
                i_ctr=i_ctr,
                j_ctr=j_ctr,
                i_max=i_max,
                j_max=j_max,
                cell_area_m2=cell_area,
                max_share=w_max,
                n_pixels=len(weights),
            )
        )

    xwalk = pd.DataFrame(rows, columns=["cell", "i", "j", "weight"])
    cells_df = pd.DataFrame(cell_meta)

    print(f"crosswalk row count: {len(xwalk)}")
    print(f"mean pixels per cell: {cells_df['n_pixels'].mean():.4f}")
    p10, p50, p90 = cells_df["max_share"].quantile([0.10, 0.50, 0.90])
    print(f"largest single-pixel share distribution: p10={p10:.4f} p50={p50:.4f} p90={p90:.4f}")
    n_ge90 = int((cells_df["max_share"] >= 0.9).sum())
    print(f"cells with largest share >= 0.9: {n_ge90} / {len(cells_df)}")
    print(f"cells failing sum(weight)==1 assert (tol 1e-9): {sum_check_fail}")
    assert sum_check_fail == 0, "weight-sum assertion failed for some cells"

    xwalk.to_parquet(f"{SCRATCH}/cell_pixel_aorc.parquet", index=False)
    cells_df[["cell", "lon", "lat"]].to_parquet(f"{SCRATCH}/cells_aorc.parquet", index=False)
    print(f"saved {SCRATCH}/cell_pixel_aorc.parquet ({len(xwalk)} rows)")
    print(f"saved {SCRATCH}/cells_aorc.parquet ({len(cells_df)} rows)")

    return xwalk, cells_df, dict(lon0=lon0, lat0=lat0, lon_step=lon_step, lat_step=lat_step)


# ---------------------------------------------------------------------------
# Step 4: value comparison on real storm hours
# ---------------------------------------------------------------------------
def bbox_indices(lon, lat, pad=1):
    i0 = int(np.searchsorted(lon, BBOX["lon_min"]))
    i1 = int(np.searchsorted(lon, BBOX["lon_max"]))
    j0 = int(np.searchsorted(lat, BBOX["lat_min"]))
    j1 = int(np.searchsorted(lat, BBOX["lat_max"]))
    return i0, i1, j0, j1


def load_hour_slice(da, i0, i1, j0, j1, time_val, pad=1):
    sub = da.sel(time=time_val).isel(
        latitude=slice(max(0, j0 - pad), j1 + pad),
        longitude=slice(max(0, i0 - pad), i1 + pad),
    )
    return retry(sub.load)


def pick_max_hour(da, i0, i1, j0, j1, t_start, t_end):
    window = da.sel(time=slice(t_start, t_end)).isel(
        latitude=slice(j0, j1), longitude=slice(i0, i1)
    )
    means = retry(lambda: window.mean(dim=("latitude", "longitude")).load())
    idx = int(means.argmax().values)
    return means.time.values[idx], float(means.values[idx])


def compare_hour(label, da, i0, i1, j0, j1, time_val, xwalk, cells_df, grid, lon, lat):
    print(f"\n--- {label}: {np.datetime_as_string(time_val, unit='m')} UTC ---")
    pad = 1
    j_lo = max(0, j0 - pad)
    i_lo = max(0, i0 - pad)
    hour = load_hour_slice(da, i0, i1, j0, j1, time_val, pad=pad)
    vals = hour.values  # shape (jlen, ilen), indices offset by j_lo/i_lo

    def pix_val(i, j):
        jj = j - j_lo
        ii = i - i_lo
        if jj < 0 or ii < 0 or jj >= vals.shape[0] or ii >= vals.shape[1]:
            return np.nan
        return vals[jj, ii]

    # A: area-weighted mean per cell from crosswalk
    xw = xwalk.copy()
    xw["v"] = [pix_val(i, j) for i, j in zip(xw["i"], xw["j"])]
    xw["wv"] = xw["weight"] * xw["v"]
    a = xw.groupby("cell")["wv"].sum().rename("A")

    cdf = cells_df.set_index("cell").join(a)
    cdf["B"] = [pix_val(i, j) for i, j in zip(cdf["i_ctr"], cdf["j_ctr"])]
    cdf["C"] = [pix_val(i, j) for i, j in zip(cdf["i_max"], cdf["j_max"])]

    bbox_mean = float(np.nanmean(vals[pad:-pad if pad else None, pad:-pad if pad else None])) if pad else float(np.nanmean(vals))
    print(f"bbox mean precip (core box, this hour): {bbox_mean:.4f} mm")

    sub = cdf[cdf["A"] >= 1.0].copy()
    print(f"cells with A >= 1mm: {len(sub)} / {len(cdf)}")

    results = {}
    for name in ("B", "C"):
        rel = (sub[name] - sub["A"]).abs() / sub["A"]
        absdiff = (sub[name] - sub["A"]).abs()
        p50r, p90r = rel.quantile([0.5, 0.9])
        maxr = rel.max()
        p50a, p90a = absdiff.quantile([0.5, 0.9])
        maxa = absdiff.max()
        share10 = float((rel > 0.10).mean())
        share25 = float((rel > 0.25).mean())
        results[name] = dict(
            p50_rel=p50r, p90_rel=p90r, max_rel=maxr,
            p50_abs=p50a, p90_abs=p90a, max_abs=maxa,
            share_gt10=share10, share_gt25=share25,
        )
        print(
            f"  {name} vs A: rel |diff|/A  p50={p50r:.4f} p90={p90r:.4f} max={maxr:.4f} | "
            f"abs mm p50={p50a:.4f} p90={p90a:.4f} max={maxa:.4f} | "
            f">10%: {share10:.4f}  >25%: {share25:.4f}"
        )

    # mass check: sum(A * cell_area) vs sum(mm * pixel_area) over pixels fully inside union of cells
    cdf_full = cdf.dropna(subset=["A"])
    mass_cells = float((cdf_full["A"] * cdf_full["cell_area_m2"]).sum())

    # pixel_area per unique j (varies with latitude only, negligible lon variation within a UTM zone)
    lon_step, lat_step = grid["lon_step"], grid["lat_step"]
    pixel_area_cache = {}

    bbox_center_lon = (BBOX["lon_min"] + BBOX["lon_max"]) / 2

    def pixel_area(j):
        if j not in pixel_area_cache:
            plat = lat[j]
            plon = bbox_center_lon  # NYC-local lon; lon offset barely matters for area *within* the bbox span
            corner_lons = [plon - lon_step / 2, plon + lon_step / 2, plon + lon_step / 2, plon - lon_step / 2]
            corner_lats = [plat - lat_step / 2, plat - lat_step / 2, plat + lat_step / 2, plat + lat_step / 2]
            pixel_area_cache[j] = poly_area_xy(corner_lons, corner_lats).area
        return pixel_area_cache[j]

    # intersection area per (i,j) pixel across all cells = weight * cell_area_m2, summed
    xw2 = xw.merge(cells_df[["cell", "cell_area_m2"]], on="cell")
    xw2["inter_area"] = xw2["weight"] * xw2["cell_area_m2"]
    pix_cov = xw2.groupby(["i", "j"])["inter_area"].sum().reset_index()
    pix_cov["pix_area"] = [pixel_area(j) for j in pix_cov["j"]]
    pix_cov["frac_covered"] = pix_cov["inter_area"] / pix_cov["pix_area"]
    fully_inside = pix_cov[pix_cov["frac_covered"] >= 1.0 - 1e-6]
    fully_inside = fully_inside.merge(
        pd.DataFrame({"i": xw["i"], "j": xw["j"], "v": xw["v"]}).drop_duplicates(["i", "j"]),
        on=["i", "j"], how="left",
    )
    mass_pixels_fully_inside = float((fully_inside["v"] * fully_inside["pix_area"]).sum())

    cell_footprint_area = float(cdf_full["cell_area_m2"].sum())
    pixel_footprint_area = float(fully_inside["pix_area"].sum())
    print(f"mass check: sum(A * cell_area) over bbox cells = {mass_cells:,.1f} mm*m^2 (footprint {cell_footprint_area:,.1f} m^2, {len(cdf_full)} cells)")
    print(
        f"mass check: sum(mm * pixel_area) over the {len(fully_inside)}/{len(pix_cov)} pixels "
        f"fully inside the union of cells = {mass_pixels_fully_inside:,.1f} mm*m^2 (footprint {pixel_footprint_area:,.1f} m^2)"
    )
    if pixel_footprint_area > 0 and cell_footprint_area > 0:
        mean_cells = mass_cells / cell_footprint_area
        mean_pixels = mass_pixels_fully_inside / pixel_footprint_area
        print(f"  area-normalized mean intensity: cells={mean_cells:.4f} mm, pixels(fully-inside)={mean_pixels:.4f} mm, ratio={mean_cells/mean_pixels:.4f}")
    print(
        "  note: raw totals are NOT directly comparable -- the cell footprint is the full hex tiling of "
        "the bbox (~all cells), the pixel footprint is only the subset of pixels with zero area cut by any "
        "hex boundary (interior pixels only, a smaller area); the area-normalized means above are the fair comparison."
    )

    return results, bbox_mean


def step4_values(fs, lat, lon, xwalk, cells_df, grid):
    print("\n=== STEP 4: value comparison on real AORC storm hours ===")
    i0, i1, j0, j1 = bbox_indices(lon, lat)

    ds21 = open_year(fs, 2021)
    da21 = ds21["APCP_surface"]

    ida_time = np.datetime64("2021-09-02T01:00:00")
    r_ida, bm_ida = compare_hour("Ida hour (2021-09-02T01:00Z)", da21, i0, i1, j0, j1, ida_time, xwalk, cells_df, grid, lon, lat)

    t_max, v_max = pick_max_hour(da21, i0, i1, j0, j1, "2021-09-01T12:00", "2021-09-02T12:00")
    print(f"\nlargest bbox-mean hour in 2021-09-01T12:00..2021-09-02T12:00: {t_max} bbox-mean={v_max:.4f} mm")
    r_ida_max, bm_ida_max = compare_hour(
        f"Ida-window max-mean hour", da21, i0, i1, j0, j1, t_max, xwalk, cells_df, grid, lon, lat
    )

    ds23 = open_year(fs, 2023)
    da23 = ds23["APCP_surface"]
    t23_max, v23_max = pick_max_hour(da23, i0, i1, j0, j1, "2023-09-29T00:00", "2023-09-29T23:00")
    print(f"\nlargest bbox-mean hour in 2023-09-29: {t23_max} bbox-mean={v23_max:.4f} mm")
    r_2023, bm_2023 = compare_hour(
        "2023-09-29 max-mean hour", da23, i0, i1, j0, j1, t23_max, xwalk, cells_df, grid, lon, lat
    )

    return dict(
        ida=(ida_time, r_ida, bm_ida),
        ida_max=(t_max, r_ida_max, bm_ida_max),
        y2023=(t23_max, r_2023, bm_2023),
    )


# ---------------------------------------------------------------------------
# Step 5: wet-hour census, AORC 2021, NYC bbox
# ---------------------------------------------------------------------------
def step5_wet_census(fs, lat, lon):
    print("\n=== STEP 5: wet-hour census, AORC 2021, NYC bbox ===")
    ds = open_year(fs, 2021)
    da = ds["APCP_surface"]
    i0, i1, j0, j1 = bbox_indices(lon, lat)
    print(f"loading full year bbox slice: lat[{j0}:{j1}] ({j1-j0} px) lon[{i0}:{i1}] ({i1-i0} px), 8760 hours...")
    t0 = time.time()
    sub = retry(lambda: da.isel(latitude=slice(j0, j1), longitude=slice(i0, i1)).load())
    print(f"loaded in {time.time()-t0:.1f}s, shape={sub.shape}")

    vals = sub.values  # (time, lat, lon)
    n_hours = vals.shape[0]
    bbox_max = np.nanmax(vals, axis=(1, 2))
    bbox_mean = np.nanmean(vals, axis=(1, 2))

    for thresh in (0.1, 1.0, 12.7):
        frac = float((bbox_max >= thresh).mean())
        print(f"fraction of {n_hours} hours where bbox max >= {thresh} mm: {frac:.6f} ({int((bbox_max>=thresh).sum())} hours)")

    n_mean_ge1 = int((bbox_mean >= 1.0).sum())
    print(f"count of hours with bbox-mean >= 1 mm: {n_mean_ge1}")

    wet01 = (vals >= 0.1)
    per_pixel_frac = wet01.mean(axis=0)  # (lat, lon)
    med_frac = float(np.nanmedian(per_pixel_frac))
    print(f"per-pixel median wet-hour fraction at >= 0.1 mm (pixels as proxy for cells): {med_frac:.6f}")

    return dict(n_hours=n_hours, bbox_max=bbox_max, bbox_mean=bbox_mean, med_frac=med_frac)


# ---------------------------------------------------------------------------
# Step 6: epoch boundary facts
# ---------------------------------------------------------------------------
def step6_epoch(fs):
    print("\n=== STEP 6: epoch boundary facts ===")
    for year in (2024, 2025):
        ds = open_year(fs, year)
        t = ds.time.values
        print(f"{year}.zarr: time[0]={t[0]} time[-1]={t[-1]} len={len(t)}")

    exists_2026 = fs.exists("noaa-nws-aorc-v1-1-1km/2026.zarr/.zmetadata")
    exists_2026_prefix = fs.exists("noaa-nws-aorc-v1-1-1km/2026.zarr")
    print(f"2026.zarr/.zmetadata exists: {exists_2026}")
    print(f"2026.zarr prefix exists: {exists_2026_prefix}")

    print("bucket top-level listing:")
    listing = fs.ls("noaa-nws-aorc-v1-1-1km")
    for p in listing:
        print(" ", p)
    return listing, exists_2026, exists_2026_prefix


# ---------------------------------------------------------------------------
def main():
    fs = s3fs.S3FileSystem(anon=True)

    ds1, lat, lon = step1_grid(fs)
    cells = step2_cells()
    xwalk, cells_df, grid = step3_crosswalk(cells, lat, lon)
    step4_results = step4_values(fs, lat, lon, xwalk, cells_df, grid)
    step5_results = step5_wet_census(fs, lat, lon)
    step6_results = step6_epoch(fs)

    print("\n=== DONE ===")
    return dict(
        lat=lat, lon=lon, cells=cells, xwalk=xwalk, cells_df=cells_df,
        step4=step4_results, step5=step5_results, step6=step6_results,
    )


if __name__ == "__main__":
    main()
