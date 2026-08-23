# 03 — Elevation features: doorway-scale terrain, QC as filter

**What to build:** `silver/asset_features` — NAVD88 elevations and the 15 m relief ring for every point
asset, with one `grade_ok` QC boolean that filters but never features — plus the DEP stormwater
snapshot and its two derived covariates, so terrain and drainage enter the model without data
quality leaking into it. Spec: Elevation features; Storage and engine conventions (stormwater
geodatabase); Testing seam 1.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] `silver/asset_features` is point-assets-only: 15,490 rows (2,120 entrances + 13,370 bus stops); complex and Cell aggregates are read-side GROUP BYs over grade_ok children, never stored rows
- [ ] canonical elevation = the 2017 1-m DEM ImageServer in NAVD88 US-survey feet (× 3.280833333); nearest-neighbor interpolation frozen (bilinear moves values 0.34 m); request constants pinned; the 2014 epoch is fetched as cross-check only
- [ ] the 8-point 15 m ring lands as ring15_min and ring15_med
- [ ] one `grade_ok` boolean from frozen constants (epoch delta > 2 m, elevation < −1 m); measured counts asserted (41/2,120 entrances, 4/4,557 sampled stops); the 41-count is a service-drift canary that fails the build if it moves; flagged rows fall back to ring15_med — never a Cell median
- [ ] QC flags are FILTERS, never model features; features_version chains structurally on assets_version
- [ ] the DEP stormwater geodatabase (`9i7c-xyvv`, File-Geodatabase-only) is read ONCE through DuckDB spatial's OpenFileGDB driver (verified in-venv, no new dependency) and snapshotted; the four-level stormwater category (deep / nuisance / analyzed-none / not-analyzed — never imputed) joins every point asset, and the per-Cell stormwater area shares publish alongside — ticket 08 consumes both
- [ ] license discipline: DEM and stormwater snapshots stay local, never rehosted or cold-pushed (DEC/DEP fetch-and-use; rehosting barred)
- [ ] DuckDB contract tests: grain, frozen counts, canary, version chaining, stormwater category never NULL-imputed
