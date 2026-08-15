# 02 Precipitation store selection

Type: research
Status: resolved

## Question

Which cloud Zarr precipitation store backs (a) historical NYC hourly features
2020-2026 and (b) live nowcast forcing? Candidates: AORC v1.1 1km
(`s3://noaa-nws-aorc-v1-1-1km/{year}.zarr`, verified live), ERA5 ARCO 0.25 deg
(`gs://gcp-public-data-arco-era5`, verified live), MRMS QPE GRIB2 archive
(`s3://noaa-mrms-pds`, from 2020-10). Need: AORC coverage end date and update
latency (v1.1 may be frozen), units, chunking and point-extraction cost, and the
near-real-time complement if AORC lags.

## Answer

Resolved 2026-08-15 by research subagent (full report with live-probed numbers:
[research/02-precip-store-selection-full.md](../../../research/02-precip-store-selection-full.md)).

**Verdict: AORC for history, MRMS for now, ERA5 for neither.**

- (a) Historical 2020-2025: **AORC v1.1**. 1/120 deg (~800 m) WGS84, APCP_surface in
  kg/m^2 (== mm), int16 scale 0.1, fill -32767. Chunks [144h, 128, 256] mean all of
  NYC sits in ONE spatial chunk: the whole 6-year NYC hourly series costs ~366 GETs,
  ~10-25 MB compressed. TRAP: store is batch-annual and frozen; no 2026.zarr exists,
  2025.zarr landed 2026-03-03. Expect 2026 data ~Q1-Q2 2027.
- 2026 bridge + (b) live nowcast: **MRMS** GRIB2.gz on s3://noaa-mrms-pds
  (RadarOnly_QPE_01H / MultiSensor_QPE_01H_Pass2 / PrecipRate), 2-min cadence,
  coverage from exactly 2020-10-14 (v12 upgrade). Needs cfgrib in the ingest path,
  and reprojection: it is not on the AORC grid.
- **ERA5 ARCO is the wrong tool for point extraction**: chunks are one full globe per
  hour (1.76 MiB compressed each), so one NYC point 2020-2026 costs ~55,500 GETs /
  ~95 GB. Actively maintained (root .zattrs last_updated was fetch-day; stable
  through 2026-04-30, ERA5T to 2026-08-09) and fine for global/pre-1979 context.
  tp units are metres; per-hour vs forecast-accumulated semantics UNVERIFIED, check
  before treating one hourly value as a rate.
- Stage IV: no cloud-native Zarr exists (DIY converters only). nClimGrid-Daily:
  NetCDF not Zarr, 5 km, daily, too coarse. No NEXRAD L3/MRMS Zarr mirrors found.

Consequence for ticket 08: the weather join is AORC-Zarr for history and
MRMS-GRIB2 for live, two readers, one canonical grid to resample onto (AORC's).
