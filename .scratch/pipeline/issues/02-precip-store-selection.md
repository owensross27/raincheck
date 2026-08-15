# 02 Precipitation store selection

Type: research
Status: claimed

## Question

Which cloud Zarr precipitation store backs (a) historical NYC hourly features
2020-2026 and (b) live nowcast forcing? Candidates: AORC v1.1 1km
(`s3://noaa-nws-aorc-v1-1-1km/{year}.zarr`, verified live), ERA5 ARCO 0.25 deg
(`gs://gcp-public-data-arco-era5`, verified live), MRMS QPE GRIB2 archive
(`s3://noaa-mrms-pds`, from 2020-10). Need: AORC coverage end date and update
latency (v1.1 may be frozen), units, chunking and point-extraction cost, and the
near-real-time complement if AORC lags.
