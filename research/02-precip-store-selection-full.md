# NYC Precipitation Store Research: AORC v1.1 vs ERA5 ARCO vs MRMS

All numbers below came from live probes run just now (2026-08-15) against the actual S3/GCS object stores (`.zarray`/`.zattrs`/`.zmetadata` fetches, bucket listings, HEAD requests for byte sizes) plus the ARCO-ERA5 GitHub README and AWS/NOAA registry pages. Anything not confirmed by a live fetch is explicitly marked **[unverified]**.

---

## 1. AORC v1.1 (`s3://noaa-nws-aorc-v1-1-1km/{year}.zarr`)

**Variables** (8 total, confirmed by listing `2025.zarr/` directly):

| Variable | Long name | Units | Level |
|---|---|---|---|
| APCP_surface | Total Precipitation | kg/m^2 | surface |
| TMP_2maboveground | Air Temperature | K | 2m |
| SPFH_2maboveground | Specific Humidity | g/g | 2m |
| DLWRF_surface | Downward Longwave Radiation | W/m^2 | surface |
| DSWRF_surface | Downward Shortwave Radiation | W/m^2 | surface |
| PRES_surface | Pressure | Pa | surface |
| UGRD_10maboveground | U-Wind | m/s | 10m |
| VGRD_10maboveground | V-Wind | m/s | 10m |

**APCP_surface, confirmed directly from `.zattrs`:**
```
units: "kg/m^2"   (numerically = mm of liquid water equivalent)
dtype: int16, scale_factor: 0.1, fill_value/missing_value: -32767
crs: "EPSG:4326"
```
Consumers reading raw Zarr (not through xarray's CF auto-decode) must multiply stored int16 by 0.1 to get kg/m^2, and treat -32767 as missing.

**Grid**: shape `[4201 lat, 8401 lon]` confirmed via `.zarray`. That's 1/120 deg (30 arc-sec) spacing, matching the registry's "~800m" description (actual: ~926m N-S, ~700m E-W at NYC's latitude). CRS is plain WGS84 lat/lon, not a projected grid.

**Temporal coverage, confirmed by live bucket listing**: per-year stores `1979.zarr` through `2025.zarr` (47 stores). **No `2026.zarr` exists** as of this probe. `2025.zarr`'s `time` array shape is exactly `8760` (365 x 24), so 2025 is a fully complete year, but its `.zmetadata` object has `Last-Modified: 2026-03-03`, meaning the year was finalized roughly two months after year-end.

**Frozen or continuous? Confirmed: batch-annual, not continuous.** AORC v1.1 does not extend to near-present. As of 2026-08-15 the newest available data is all of 2025, and none of 2026, i.e. the store is 7.5+ months stale with zero partial-year data ever appearing intra-year. The registry page's claim of a "10-day lag for input corrections" **[unverified, AI-paraphrased, and it looks like it describes intra-pipeline QC lag before a year is finalized, not overall latency]** does not match the observed ~14-month lag pattern (2025 published March 2026). Do not plan on this store for anything past December 2025.

**Chunking, confirmed from `APCP_surface/.zarray`:**
```
chunks: [144, 128, 256]   (time, lat, lon)
shape:  [8760, 4201, 8401]
compressor: zstd level 3
```
Time chunk = 144 hours (6 days). Spatial chunk = 128 x 256 cells = 1.0667 deg lat x 2.1333 deg lon, roughly 118 km x 180 km at NYC's latitude, comfortably larger than the entire NYC metro area. **Practical consequence: a single-point pull and a NYC-bbox pull cost the same, since both land inside one spatial chunk.**

**Cost profile, point/bbox time series 2020-2025** (2026 unavailable):
- Time chunks needed: ceil(8760/144) = 61 per year x 6 years (2020-2025) = **366 chunk objects / 366 S3 GETs**.
- Live-sampled compressed chunk sizes (interior-CONUS spatial chunk, 2025, HEAD requests): 410 B, 13.1 KB, 36.9 KB, 58.3 KB, 96.2 KB across five different months, versus 9.44 MB uncompressed each (144 x 128 x 256 x 2 bytes). Wide variance (up to ~230x between dry and wet months) because zstd crushes the mostly-zero precip field hard.
- Total compressed transfer for the full 2020-2025 point/bbox pull: roughly **10-25 MB**, order of magnitude, given the sampled variance.
- Decompressed working set: 366 x 9.44 MB = ~3.45 GB transient.

---

## 2. NRT complement for AORC's staleness: MRMS confirmed, Stage IV not cloud-native

**MRMS** (`s3://noaa-mrms-pds`, [registry](https://registry.opendata.aws/noaa-mrms-pds/)): bucket top level has `CONUS/`, `CONUS_5KM/`, `ALASKA/`, `CARIB/`, `GUAM/`, `HAWAII/`, `ANC/`, `ConvectProb/`, `ProbSevere/`, `unsupported/`.

Confirmed live, earliest keys under the two main hourly QPE products both start **2020-10-14**:
```
CONUS/MultiSensor_QPE_01H_Pass2_00.00/20201014/MRMS_MultiSensor_QPE_01H_Pass2_00.00_20201014-200000.grib2.gz
CONUS/RadarOnly_QPE_01H_00.00/20201014/MRMS_RadarOnly_QPE_01H_00.00_20201014-000000.grib2.gz
```
This exactly matches your "~2020-10" hint, and lines up with NOAA's documented MRMS v11 to v12 upgrade on 2020-10-14 (NOAA cautions against pre-2020 v11 data). A parallel `unsupported/` tree (CONUS, CONUSPLUS, ALASKA, CARIB, GUAM, HAWAII, FLASH, CONUS_5KM) likely holds legacy pre-v12 data but its date range was not checked.

Full CONUS QPE product list found live: `RadarOnly_QPE_{01H,03H,06H,12H,15M,24H,48H,72H,Since12Z}`, `MultiSensor_QPE_{01H,03H,06H,12H,24H,48H,72H}_Pass{1,2}`, `FLASH_QPE_*` (flash-flood ARI/FFG variants), `PrecipRate`, `PrecipFlag`, `SyntheticPrecipRateID`. Format is **GRIB2, gzipped, not Zarr**. Update cadence is 2-minute per the registry page, corroborated live by `RadarOnly_QPE_01H` filenames stepping every 2 minutes (`-000000`, `-000200`, `-000400`...).

**Stage IV**: no pre-built cloud-native/Zarr store found on AWS S3 **[searched, not found; absence is hard to prove exhaustively but nothing turned up]**. Canonical access is via [NCEP/EMC](https://www.emc.ncep.noaa.gov/mmb/SREF/pcpanl/stage4/), [NCAR EOL archive](https://data.eol.ucar.edu/dataset/21.087), or [water.noaa.gov](https://water.noaa.gov/about/precipitation-data-access) (GRIB2/NetCDF/GeoTIFF, "2016-present" per that page, **[unverified via direct fetch]**). A DIY GitLab toolkit exists ([USGS Water Mission Area](https://code.usgs.gov/wma/nhgf/geo-data-portal/stage_iv_precip)) to convert Stage IV GRIB to Zarr yourself, which itself confirms no ready-made public Zarr version exists. Bottom line: **MRMS, not Stage IV, is the usable AWS-native NRT complement.**

---

## 3. ERA5 ARCO

**Canonical/maintained store**: `gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3`. Confirmed as the flagship "analysis-ready" store, it's the one used in the README's primary getting-started snippet, and it's the only *undated* name among the ~19 stores under `ar/` (the others are frozen archival cuts baked into their names, e.g. `1959-2022-full_37-1h-0p25deg-chunk-1.zarr-v2`, `1959-2023_01_10-full_37-1h-0p25deg-chunk-1.zarr`).

Live root `.zattrs`, fetched just now:
```json
{
  "last_updated": "2026-08-15 02:48:19.501057+00:00",
  "valid_time_start": "1940-01-01",
  "valid_time_stop": "2026-04-30",
  "valid_time_stop_era5t": "2026-08-09"
}
```
`last_updated` is today, i.e. this store is being actively maintained right now. Stable ERA5 runs through 2026-04-30 (about 3.5 months behind today, matching the README's documented "monthly cadence, ~9th of month, 3-month delay"). ERA5T (preliminary) runs through 2026-08-09, 6 days behind today, matching the README's "~1 week delay."

**total_precipitation**, confirmed live: `units: "m"`, `short_name: "tp"`, ECMWF param [228228](https://codes.ecmwf.int/grib/param-db/228228). **[Unverified]**: could not confirm from the README whether this specific ARCO product stores tp as clean per-hour increments or as forecast-accumulated-since-basetime (the classic raw-ERA5 gotcha, where you must diff across the 00Z/12Z-reset base times). Verify with a real read before treating a single hourly value as an independent rate.

**Grid**: 0.25 deg equiangular, 721 x 1440, global, confirmed live.

**Chunking**, confirmed live from `total_precipitation/.zarray`:
```
chunks: [1, 721, 1440]
shape:  [1323648, 721, 1440]
compressor: blosc/lz4 clevel5
```
This exactly matches the README's documented spec (`{time:1, latitude:721, longitude:1440, level:37}` for the full 3D superset; tp is a 2D surface field so it drops the level dim). **One chunk = one full global grid at a single hour.** (Note: the array's raw shape of 1,323,648 corresponds to an allocation running out to roughly 1900+151 years; real data only starts at index ~350,640, matching `valid_time_start=1940-01-01`. A HEAD on chunk `total_precipitation/0.0.0` correctly 404s because that slot predates 1940.)

**Chunk-read cost, one NYC point (bbox is identical, since you already paid for the full globe)**:
- Live-sampled compressed chunk (a real ~2014 timestep): **1,843,816 bytes = 1.76 MiB**, versus 721 x 1440 x 4 bytes = 3.96 MiB uncompressed.
- **One year of hourly tp at one point**: 8760-8784 chunk GETs x 1.76 MiB = **~15.1-15.5 GB compressed downloaded, for 8760 scalar values.**
- **Full 2020-2026 span** (2020-01-01 through 2026-04-30 stable = 2,312 days = 55,488 hours): **~55,500 GET requests, ~95 GB compressed transferred, ~214 GB decompressed processed**, to extract one point's 6-year hourly series. Extending through ERA5T (2026-08-09) adds ~2,400 more hours, ~4 GB more.

**AORC vs ERA5 for the same job**: ~150x fewer requests (366 vs ~55,500) and roughly 3-4 orders of magnitude less data (~10-25 MB vs ~95 GB) for AORC on an equivalent NYC point/bbox 2020-2025 pull. This is entirely a chunking-shape artifact: AORC's chunks are sized to a NYC-scale region, ERA5's chunks are sized to the whole planet.

---

## 4. Recommendation

**(a) Historical NYC hourly precip 2020-2026, to join against bus/flood history: AORC v1.1 Zarr for 2020-2025, MRMS GRIB2 to bridge 2026.**
AORC gives you ~800m native resolution (fine enough to distinguish streets/blocks), EPSG:4326, kg/m^2 units, hourly, at a trivial extraction cost (~366 chunk GETs, ~10-25 MB total for the whole 6-year NYC series). The catch is it stops at end-2025 and, based on the observed ~14-month annual-batch cadence, a `2026.zarr` shouldn't be expected until roughly Q1-Q2 2027. So for any 2026 dates you need to backfill from MRMS `RadarOnly_QPE_01H` or `MultiSensor_QPE_01H_Pass2` GRIB2.gz (both live from 2020-10-14 onward, ~1km native radar resolution, reprojection required since it's not on the AORC grid). ERA5 ARCO is the wrong tool for this join even though it's more current: its point-extraction cost is 3-4 orders of magnitude worse for what is fundamentally a small-bbox query, and its native grid (0.25 deg = exactly 30x coarser in degrees than AORC's 1/120 deg) cannot resolve which block flooded.

**(b) Live nowcast forcing: MRMS `RadarOnly_QPE_01H` / `PrecipRate` from `noaa-mrms-pds`.**
Confirmed 2-minute update cadence, confirmed live and current (CONUS/ tree from 2020-10-14 to present), ~1km native radar resolution, GRIB2.gz (a GRIB2 reader like cfgrib is needed in the ingestion path, this is not `xarray.open_zarr`-able as-is). Nothing else checked here is a real candidate for "live": AORC is 7+ months stale and updates once a year; ERA5T is only 6 days stale but is 28km-resolution and, per the chunk-cost numbers above, absurdly expensive to query point-wise for a streaming pipeline; Stage IV was not found as an AWS cloud-native product at all.

---

## 5. nClimGrid-Daily and NEXRAD L3/MRMS Zarr mirrors

**nClimGrid-Daily**: exists on AWS, bucket `noaa-nclimgrid-daily-pds` ([registry](https://registry.opendata.aws/noaa-nclimgrid/)), confirmed live. It is daily-resolution data (`archive/` holds monthly-batched `.tar.gz` bundles of NetCDF back to 1951, e.g. `archive/2024/nclimgrid-daily_v1-0-0_complete_s20240101_e20240131_c20240404.tar.gz`; `access/grids/` holds one NetCDF per month per year, e.g. `access/grids/1951/ncdd-195101-grd-scaled.nc`). **Format is NetCDF, not Zarr.** A separate `noaa-nclimgrid-monthly-pds` bucket carries the monthly-resolution product, so "daily" here really does mean the daily-cadence dataset specifically, not "daily is the only granularity NOAA offers." It's a 5km, station-interpolated (GHCN-D-derived) product, too coarse for block-level flood joins regardless of format.

**NEXRAD Level-3 / MRMS Zarr mirrors**: **none found.** Checked NOAA's own Kerchunk virtual-Zarr program live (`noaa-nodd-kerchunk-pds`, [registry](https://registry.opendata.aws/noaa-nodd-kerchunk/)): it covers NOAA Operational Forecast System (OFS), Global RTOFS, and National Water Model Short-Range Forecast only. MRMS and NEXRAD Level 3 are absent from it. General web search for Pangeo-Forge or other cloud-native mirrors of NEXRAD L3/MRMS turned up nothing concrete beyond generic Zarr/Pangeo tutorial material. **[Unverified-negative]**: a thorough search was done but a from-scratch check of Pangeo-Forge's own recipe catalog was not performed, so treat "none found" as "none found by this search," not as an exhaustive proof of nonexistence.