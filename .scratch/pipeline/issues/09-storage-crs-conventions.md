# 09 Storage and CRS conventions

Type: grilling
Status: open
Blocked by: 04

## Question

Lock the storage layout and coordinate discipline before the first Sedona job writes
anything. Starting position from `../reality-check-2026-08-15.md` section 4:
EPSG:4326 canonical, one-time ST_Transform of EPSG:2263 city layers at ingest with an
axis-order check, geodesic or UTM-18N for metric math, precomputed AORC-cell-to-H3
and H3-to-taxi-zone lookups so joins are on (h3, hour), Bronze hourly Parquet /
Silver Sedona GeoParquet 1.1 with bbox covering sorted by H3 then time / Gold
aggregates, Iceberg deferred until file count or the lakehouse demo justifies it.
Ross confirms or amends. Answer records the final table schemas and partition keys.
