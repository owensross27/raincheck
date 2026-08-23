# 03 — Elevation features: doorway-scale terrain, QC as filter

**What to build:** `silver/asset_features` — NAVD88 elevations and the 15 m relief ring for every point
asset, with one `grade_ok` QC boolean that filters but never features — plus the DEP stormwater
snapshot and its two derived covariates, so terrain and drainage enter the model without data
quality leaking into it. Spec: Elevation features; Storage and engine conventions (stormwater
geodatabase); Testing seam 1.

**Blocked by:** 01

**Status:** resolved 2026-08-23

- [x] `silver/asset_features` is point-assets-only: 15,490 rows (2,120 entrances + 13,370 bus stops); complex and Cell aggregates are read-side GROUP BYs over grade_ok children, never stored rows
- [x] canonical elevation = the 2017 1-m DEM ImageServer in NAVD88 US-survey feet (× 3.280833333); nearest-neighbor interpolation frozen (bilinear moves values 0.34 m); request constants pinned; the 2014 epoch is fetched as cross-check only
- [x] the 8-point 15 m ring lands as ring15_min and ring15_med
- [x] one `grade_ok` boolean from frozen constants (epoch delta > 2 m, elevation < −1 m); measured counts asserted (41/2,120 entrances, 4/4,557 sampled stops); the 41-count is a service-drift canary that fails the build if it moves; flagged rows fall back to ring15_med — never a Cell median
- [x] QC flags are FILTERS, never model features; features_version chains structurally on assets_version
- [x] the DEP stormwater geodatabase (`9i7c-xyvv`, File-Geodatabase-only) is read ONCE through DuckDB spatial's OpenFileGDB driver (verified in-venv, no new dependency) and snapshotted; the four-level stormwater category (deep / nuisance / analyzed-none / not-analyzed — never imputed) joins every point asset, and the per-Cell stormwater area shares publish alongside — ticket 08 consumes both
- [x] license discipline: DEM and stormwater snapshots stay local, never rehosted or cold-pushed (DEC/DEP fetch-and-use; rehosting barred)
- [x] DuckDB contract tests: grain, frozen counts, canary, version chaining, stormwater category never NULL-imputed

## Comments

**2026-08-23 (resolution).** Built as `src/raincheck/features.py` + `make features`, tested in
`tests/test_features.py` (32 tests, all passing; full suite 309 passed / 8 skipped — the 8 are
the pre-existing Kafka and vendored-maplibre environment skips, 7 of which passed in the 285-test
baseline before the Mac crash took the broker down, so the delta this ticket adds is +32 passing
and 0 new skips). Two
tables land: `silver/asset_features` (15,490 rows) and `silver/cell_stormwater` (4,113 rows).
The whole fetch is one-shot — 310 elevation POSTs (~14 min) plus 9 mask pages; every rerun reads
snapshots and takes ~50 s with no network at all, and rebuilds byte-identical (measured, both
parts, sha256, before and after the review round).

**Measured on the real root** (frozen in `features.EXPECT`, asserted blocking):

| | count |
|---|---|
| rows / entrances / bus stops | 15,490 / 2,120 / 13,370 |
| entrances flagged (`grade_ok=false`) | **41** — the canary, reproduced exactly |
| bus stops flagged | 89 |
| elevation NoData | 61 (all bus stops) |
| flagged rows with no ring15_med fallback | 60 (all bus stops) |
| stormwater: analyzed-none / not-analyzed / nuisance / deep | 13,945 / 745 / 592 / 208 |

`features_version = 6b6f61e0231d6237ba93e9126eeb08fc0e16de21`.

Four independent cross-checks reproduced the wayfinder's own measurements from a completely
separate code path, which is the real evidence the chain is wired right: 100 entrances below
10 ft NAVD88; exactly **3** below the Battery minor threshold (4.43 ft NAVD88) — the two WTC
construction-pit rows and Richmond Valley; the single in-city NoData stop is 308410 Cropsey
Av/Hart Pl, exactly the one the design named; and the 2014-vs-2017 agreement that the 2014
epoch's units and datum are *inferred* from (its service metadata is empty) re-measures at
median +0.0752 m, sigma 0.8781 m over all 2,120 entrances against the design's +0.075 / 0.88.
That inference is still an inference — it rides on every `grade_ok` as a provenance caveat — but
it is the same inference the design made, on the same numbers.

The stormwater join was also checked against a second engine: DuckDB's own `ST_Contains`, with
DuckDB's own `ST_Transform` doing the 4326 → 2263 move, classifies all 15,490 assets identically
to the shapely/pyproj path — 800 flooded either way, **zero disagreements**. Since the DuckDB
side resolves ties toward nuisance and this builder resolves them toward deep, that agreement
also proves the two flood classes never overlap at an asset. That full-universe run costs ~114 s
(unindexed point-in-polygon against two 500k-vertex MultiPolygons), so the suite keeps a
deterministic stratified 400 — 100 per level — and this paragraph is the record of the full one.

**Decisions taken here (not in the design):**

1. **Snapshots live at `<root>/snapshots/`, not `<root>/archive/`.** The wayfinder text said
   `data/archive/elevation/`, but `make coldpush` (and `make daily`) sync `<root>/archive` to the
   R2 bucket — writing DEM and DEP snapshots there would have rehosted exactly what both licences
   bar, through a target nobody re-reads. `snapshots/` is a sibling of `archive/`, so it is
   outside the sync by construction; `data/` is already gitignored. A test asserts the builder
   never writes under `archive/`, so a later path edit fails loudly rather than quietly shipping.
2. **The fourth stormwater level was recovered, not imputed.** The FGDB holds only the two flood
   classes (`Flooding_Category` 1 nuisance / 2 deep — confirmed from its own data dictionary and
   its layer, 2 features, 25k parts), and research flood-04 concluded no queryable service exists
   for this data. True for the flood extents — but DEP's exclusion mask is published separately
   and IS queryable: `Area_not_included_in_analysis/FeatureServer/1`, 16,856 PLUTO lots
   (Railroad Buffer 11,688, Intersects Rail Line 3,320, Open Space >100K 1,139, Larger than
   250K/500K 674, LTCP Boundary Gap 35). Without it, 673 point assets (4.3%) would have been
   silently labelled "modelled, no flooding" — the exact imputation 08 barred. Page sum is
   checked against the service's own count so a truncation cannot read as "no flooding".
3. **The FGDB is read in place, through `/vsizip/`** — `ST_Read('/vsizip/<zip>/<...>.gdb')` on
   DuckDB spatial's OpenFileGDB driver. No unzip, no new dependency, one read per build.
   (Aside for whoever reads the other three scenarios: `st_read_meta` on the *Limited Flood*
   scenario segfaulted the process. Moderate-current, the one 08 specified, reads clean.)
4. **Everything spatial is computed in EPSG:2263**, the geodatabase's own CRS, so the two big
   flood MultiPolygons are never reprojected; the 15,490 assets, 4,113 Cells and 16,856 mask lots
   move instead. No area is ever computed in degrees.
5. **Category precedence: flood classes beat the mask.** A point inside both a flood polygon and
   the exclusion mask is reported flooded — the model plainly ran there. The mask only answers
   for points no flood class claims.
6. **Area shares clamp the last ULP and fail on a real overlap.** Six Cells lie wholly inside the
   mask and summed to 1 + 2 ULP. Summing per-part intersections is exact only while parts stay
   disjoint, so a sum above 1 + 1e-6 now aborts the build and only the floating-point hair is
   clamped — the failure that matters stays a failure.
7. **The ring15_med fallback stays read-side.** The design is explicit that flags are never
   silently repaired and canonical `elev_ft` is always the raw 2017 sample, so this table
   publishes the raw columns and 08 applies the fallback. What the table owes is the column being
   there — asserted for every flagged entrance, and the 60 rows without one are frozen as a count.
8. **`features_version` covers `asset_features` only.** It is sha1 over the sorted rows (pinned
   float formatting) + `assets_version` + the frozen constants + the stormwater zip's sha256, so
   a moved asset, a republished DEM, a re-cut stormwater snapshot or a changed threshold all move
   it. `cell_stormwater` carries no separate stamp — it is derived from the same snapshot, and its
   identity rides in that sha256. Flagged as an explicit boundary rather than a second hash.
9. **`ring15_n` is published** (see the review round): the count of ring points that answered,
   0–8. Not in the design's column list, added because the fallback's trustworthiness depends on
   it and six assets have a partial ring.
10. **Six frozen elevation values** (`features.ELEV_PROBE`) are asserted at build and in the tests.
   The 41-count canary catches a service that moved QC-relevant values; the probe catches one that
   changed interpolation, datum or raster without moving a single flag.

**Review round (2026-08-23, after the first green build).** A four-lens adversarial pass
(contract fidelity / data correctness / licence and operational discipline / test adequacy, each
finding then put to a refutation agent) found three defects worth the pass, all fixed here and
all of the silent-wrong-number class rather than the crash class:

- **Elevation snapshots were not bound to the coordinates they were sampled at** (three lenses
  found this independently). `sample()` keyed its snapshot on service + tag + date and guarded
  only the total count, so a registry rebuild that MOVES an asset without changing the asset_id
  set — a re-pinned bus Pick shifts a cross-feed mean, which ticket 01's key-diff calls "moved",
  not "added" — would have republished the old elevations under a features_version chained to the
  NEW assets_version. That is the exact reciprocal of 01's orphan-is-failure contract, which the
  design asked for and the first cut missed. Snapshots now carry `sampled_at`, a digest of the
  exact coordinates plus the request constants, and refuse to answer for any others; flipping
  INTERPOLATION to bilinear now forces a re-sample instead of reusing nearest-neighbour bytes.
  The existing snapshots were migrated rather than re-fetched, but only after checking all
  154,281 locations the service itself echoed back against the current coordinates — 0 mismatches.
- **72 out-of-city assets were being imputed to `analyzed-none`** (two lenses). DEP's exclusion
  mask is a PLUTO layer that stops at the city line, so MTA Bus Company stops in Nassau fell
  through the default and were published as "DEP modelled here and found no flooding" — the one
  imputation the four-level encoding exists to forbid. Points outside the study area (the non-EWR
  taxi zones, the same oracle `ref/assets` uses for cells_scored) are now `not-analyzed`, which
  moved 72 assets and is the whole difference between the first build's 673 and this one's 745.
  The same rule now applies at Cell grain, where a Cell over Nassau or open water previously
  published three zero shares and implied DEP had looked.
- **The Cell shares could double-count.** The mask and the flood extents genuinely overlap
  (225,078 ft², 0.19% of flood area — measured), so `share_not_analyzed` and the flood shares
  claimed the same ground while the point grain resolved that overlap by precedence. The mask is
  now differenced against the flood union before the shares are computed: same precedence at both
  grains, and the shares partition by construction.

Also from that round, smaller: the DEP geodatabase is now dated in its filename and pinned by
sha256 (`5effe9bc…`), so a republish under the same URL cannot quietly become what `src_asof`
already names; `features_version()` reads that pin instead of fetching, so a consumer calling it
to chain `score_version` can never trigger a 33.8 MB download; both tables are written only after
every gate passes, so an interrupted run cannot leave a mismatched pair; a hard 400 from
getSamples fails immediately rather than burning three retries; and `ring15_n` now records how
many of the 8 ring points answered, because six assets have a partial ring and a half-ring median
otherwise reads exactly like the full octagon 08 asked for — including for `bus:308410`, whose
5-of-8 ring IS its fallback grade.

**Corrections to the design's measured numbers.** The design's bus-stop QC rates came from a
4,557-stop sample that held no out-of-city stops. Over all 13,370: **89 flagged, not ~12**, and
**61 have no elevation at all** because they sit outside the NYC DEM footprint — MTA Bus Company
routes crossing into Nassau County (Green Acres Mall, Lakeville Rd/LIJ). 60 of those 61 have no
ring fallback either; the 61st is Cropsey Av, whose 15 m ring reaches back into the raster. The
two epochs' NoData sets are also not the same set: 57 stops are NoData in both, 4 only in 2017,
4 only in 2014 — the footprints differ at the edges, and `grade_ok` flags a row when either epoch
is missing. Six assets have a partial ring (median taken over the points that returned).

## Handed to 08 (and 09/16)

1. **Seven complexes have entrances but ZERO grade_ok entrances** — `stn:134` Sutter Av,
   `stn:299` Dyckman St, `stn:59` 9 Av, `stn:74` 18 Av, `stn:75` 20 Av, `stn:78` Avenue U,
   `stn:79` 86 St (mostly the Brooklyn els — the wrong-high el class 07 named). A read-side
   "GROUP BY over grade_ok children" returns **nothing** for these, and `gold/flood_exposure`
   mandates NO NULL scores. The two rules only reconcile one way: **apply the ring15_med fallback
   before the aggregate, not after.** Every one of the 445 complexes then has a usable child
   (measured — all seven have children with a ring15_med).
2. **60 bus stops have neither elevation nor ring fallback.** They are in Nassau County, outside
   both the DEM footprint and the city the labels describe. 08 owes them an explicit policy:
   a floor value, or removal from the score universe (which is a registry question, not a
   features one — `ref/assets` scores them today).
3. **Never impute not-analyzed.** 745 point assets (4.8%) are not-analyzed — 673 inside DEP's
   exclusion mask, which is overwhelmingly rail lines and their buffers (precisely where transit
   assets are), plus the 72 outside the study area entirely. The level is real, populated, and
   correlated with the asset kind being scored, so imputing it to "no flooding" would push a
   structured error straight into the point model's stormwater term.
4. **The mask endpoint is queryable** (item 2 above), so 08's Cell model gets
   `share_not_analyzed` as a genuine "the model never ran here" covariate rather than a hole.
   Cell-grain shape: 803 of 4,113 Cells carry modelled flooding, max flooded share 0.206; 2,825
   Cells are wholly not-analyzed (the bbox tiling's no-NYC-land majority, now labelled as such
   rather than implied to be "modelled, dry"); 327 scored Cells hold no point asset at all; 20
   scored Cells hold point assets that are ALL flagged.
5. **The relief term is `(elev_2017_m − ring15_med_m) × 3.280833333`**, computed read-side from
   the two raw metre columns — the table deliberately does not publish a derived relief column,
   so the unit bug 08 already caught cannot come back through a stored value.
6. The 2017 acquisition window (2017-05-03..2017-07-26) is a frozen constant in the module, for
   08's temporal-validity note about a 2017 surface across a 2010–2026 era.

## Debt

- `cell_stormwater` has no version stamp of its own (decision 8). If 08 wants one, the honest
  form is a second sha1 over its rows plus the same snapshot sha256.
- Only the Moderate-current scenario is read. The other three FGDB scenarios are in the same
  snapshot; a sensitivity sweep over them is an 08 outer-replication question, not a rebuild.
- The Limited-Flood scenario segfaults `st_read_meta` (decision 3). Not on any path we use;
  recorded so nobody rediscovers it under time pressure.
- The byte-identical rebuild is measured by hand, not by the suite: an end-to-end rebuild needs
  the real snapshots (a temp-root fixture cannot fake a binary geodatabase) and costs ~50 s, so
  the suite asserts the write path's determinism and the ticket records the end-to-end result.
  Re-measure with two `make features` runs and `shasum -a 256` on both parts.
- The elevation snapshot is written only after all 248 ring batches return, so one hard failure
  late in a 14-minute run discards it. Per-batch page files (the shape the stormwater mask
  already uses) would make it resumable; not worth it until it actually bites.
