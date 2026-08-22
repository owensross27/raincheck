# 02 — Reference layer: grids, cells, zones, cell_zone, cell_pixel, calendar, current Picks

**What to build:** `make ref` builds every lookup the pipeline joins at read: `ref/grids` (aorc from the stored
Zarr coordinate arrays, mrms from a GRIB grid tuple), `ref/cells` (4,113 H3 res-8 Cells over
the NYC bbox as GeoParquet polygons built by Sedona), `ref/zones` (263 TLC taxi zones
reprojected once from EPSG:2263), `ref/cell_zone` (centroid point-in-polygon), `ref/cell_pixel`
(area-weighted Pixel shares per Cell for both grids), `ref/calendar` (one row per slice
service day with school/holiday/UNGA flags) and `ref/picks` seeded from the static zips the
archiver already captures. Every table is queryable from DuckDB. Spec: B, D (live-era Picks).

**Blocked by:** 01

**Status:** resolved

- [x] `ref/grids` has the aorc row (origin -130.0/20.0, step 0.008333, 8401 x 4201, centre, sha256 of the stored arrays) and the mrms row (origin -129.995/20.005, step 0.01, 7000 x 3500, centre, j flipped north-to-south, sha256 of the GRIB grid tuple)
- [x] `ref/cells` has 4,113 rows with SRID-4326 polygons and centroids, written as GeoParquet 1.1; the DuckDB community `h3` extension oracle passes `ST_Equals(geometry, ST_GeomFromWKB(h3_cell_to_boundary_wkb(cell)))` on every row — **after snapping both sides to a 1e-9 deg grid** (see Comments: last-ulp Java-vs-C H3 difference)
- [x] `ref/zones` has 263 rows with zone_id, borough, zone_name; the Times Square axis gate passes at ingest; `ref/cell_zone` assigns every Cell by centroid
- [x] `ref/cell_pixel` for grid_id in (aorc, mrms): sum(weight) = 1 +/- 1e-9 per (grid, cell), built over the bbox padded by one Pixel; AORC has ~19.5K rows and ~4.7 Pixels per Cell
- [x] `ref/calendar` has 122 rows (one per slice service day) with school_in_session, holiday, unga_week; `ref/picks` has one row per captured static zip (pick_id = sha1, feed, published from Last-Modified, source mta)
- [x] `make ref` twice leaves byte-identical tables; all conventions of spec section B hold (4326 stored, geodesic only for distances, TS UTC, cell INT64)

## Comments

**2026-08-22 (implemented).** `src/raincheck/ref.py` (`build(root, spark)` + one builder per
table; `make ref` runs `main()`), `tests/test_ref.py` (module-scoped fixture runs the whole
build once against a temp root seeded with committed fixtures `aorc_coords.npz` (79 KB) and
`taxi_zones.zip` (1 MB) plus two synthetic GTFS zips; 9 tests, whole module skips without a
JVM). Real build under `data/ref` (4.9 MB, 20 s): grids 2, cells 4,113, zones 263, cell_zone
4,113 (1,070 with a zone — the bbox is mostly water; cf. 10's ~1,146-Cell bus footprint),
cell_pixel **19,512 aorc rows (4.74 Pixels/Cell — exactly research 08's independently
measured numbers)** + 16,232 mrms (3.95), calendar 122 (4 holidays, 15 UNGA days, 60 school
days), picks 7 (all captured zips, real MTA feed_versions, spans from calendar+calendar_dates).

Corrections found by building:
- **The plain `ST_Equals` oracle is unpassable as written**: Sedona's Java H3 and DuckDB's C
  h3 emit boundary vertices that differ in the last double ulp (~1e-14 deg, measured on all
  4,113 cells, sym-diff area ~2e-16). The oracle snaps both sides with
  `ST_ReducePrecision(g, 1e-9)` (0.1 mm) first — still vertex-for-vertex agreement.
- `ST_H3CellIDs(bbox, 8, fullCover=false)` gives the 4,113; `true` gives 4,472.
  `ST_H3ToGeom(array(cell))[0]` is the per-cell polygon (it returns an array).
- aorc coord sha256 pinned: `c2ef67bf...a5f243`; coords stored once at
  `<root>/archive/precip/aorc/coords.npz` (fetched from the cloud Zarr when missing);
  `frozen_at` = the npz mtime, mrms `frozen_at` = 2026-08-16 (the tuple's measurement date)
  so rebuilds stay byte-identical.
- Byte-identical rebuild holds with Spark parquet output too (single sorted partition,
  part file moved from `.staging/` to the stable name `part-00000.parquet`).
- Calendar facts verified against the NYC DOE calendars and UN GA session pages 2026-08-22:
  first days 2021-09-13 / 2023-09-07; closures 2021-09-16, 2021-10-11, 2023-09-25,
  2023-10-09; holidays Labor Day + Indigenous Peoples' Day both years; UNGA general debate
  2021-09-21..27 and 2023-09-19..26.
- `published` on live-era Picks is date-precision (the archiver names zips by Last-Modified
  date; the time of day is not kept).
