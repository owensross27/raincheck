# 02 — Reference layer: grids, cells, zones, cell_zone, cell_pixel, calendar, current Picks

**What to build:** `make ref` builds every lookup the pipeline joins at read: `ref/grids` (aorc from the stored
Zarr coordinate arrays, mrms from a GRIB grid tuple), `ref/cells` (4,113 H3 res-8 Cells over
the NYC bbox as GeoParquet polygons built by Sedona), `ref/zones` (263 TLC taxi zones
reprojected once from EPSG:2263), `ref/cell_zone` (centroid point-in-polygon), `ref/cell_pixel`
(area-weighted Pixel shares per Cell for both grids), `ref/calendar` (one row per slice
service day with school/holiday/UNGA flags) and `ref/picks` seeded from the static zips the
archiver already captures. Every table is queryable from DuckDB. Spec: B, D (live-era Picks).

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] `ref/grids` has the aorc row (origin -130.0/20.0, step 0.008333, 8401 x 4201, centre, sha256 of the stored arrays) and the mrms row (origin -129.995/20.005, step 0.01, 7000 x 3500, centre, j flipped north-to-south, sha256 of the GRIB grid tuple)
- [ ] `ref/cells` has 4,113 rows with SRID-4326 polygons and centroids, written as GeoParquet 1.1; the DuckDB community `h3` extension oracle passes `ST_Equals(geometry, ST_GeomFromWKB(h3_cell_to_boundary_wkb(cell)))` on every row
- [ ] `ref/zones` has 263 rows with zone_id, borough, zone_name; the Times Square axis gate passes at ingest; `ref/cell_zone` assigns every Cell by centroid
- [ ] `ref/cell_pixel` for grid_id in (aorc, mrms): sum(weight) = 1 +/- 1e-9 per (grid, cell), built over the bbox padded by one Pixel; AORC has ~19.5K rows and ~4.7 Pixels per Cell
- [ ] `ref/calendar` has 122 rows (one per slice service day) with school_in_session, holiday, unga_week; `ref/picks` has one row per captured static zip (pick_id = sha1, feed, published from Last-Modified, source mta)
- [ ] `make ref` twice leaves byte-identical tables; all conventions of spec section B hold (4326 stored, geodesic only for distances, TS UTC, cell INT64)
