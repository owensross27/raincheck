# 07 Elevation feature set

Type: grilling
Status: resolved
Blocked by: 06

## Answer

Resolved 2026-08-22 (measured live; 3-lens adversarial review in
`../assets/07-adversarial-verdicts.json` — 58 verdicts, 36 missing items;
Ross: yes to all seven round points). Draft history:
`../assets/07-elevation-draft.md`. All numbers measured, not estimated.

**One table, point assets only.** `silver/asset_features` at
`data/silver/asset_features/` — plain Parquet, **15,490 rows** = 2,120
entrances + 13,370 bus stops, single sorted part file ordered by asset_id
(ref-style exception, declared: rebuilt whole, byte-identical gate). NO
cell/complex/station rows: the draft's 4,113 cell rows were refuted by
measurement (ref/cells is a bbox tiling; ~2,759 of 4,113 cells touch no NYC
land; centroid sampling returned ~1,127 of 4,113, the rest NoData or
hard-400 batches reading seafloor). Cell and complex elevation are one-line
read-side GROUP BYs in 08 (over `cell` / ref/assets `parent_asset_id`),
where min-vs-median is decided once by the modeling owner. Stations inherit
their complex aggregate; every one of the 445 complexes has >= 1 child
entrance (measured; 30 have exactly one).

**Columns.** asset_id STRING pk (FK to ref/assets), elev_2017_m DOUBLE,
elev_2014_m DOUBLE (raw getSamples values), elev_ft DOUBLE = elev_2017_m x
**3.280833333** (NAVD88 **US survey ft** — 3.28084 is the international
foot; difference < 0.001 ft, but the map's canonical unit gets the right
constant), ring15_min_m DOUBLE, ring15_med_m DOUBLE, grade_ok BOOLEAN,
cell INT64 (copied from ref/assets), src_asof DATE, frozen_at
TIMESTAMP_MICROS. Dropped from the draft as pure derivations: kind,
d_epoch_m, rel_elev_ft, cell aggregates, the grade_qc enum.

**Sources.** Canonical: `NYC_TopoBathymetric_2017_1_meter/ImageServer` on
elevation.its.ny.gov (keyless; metadata documents NAVD88, Geoid 12B,
meters, flown **2017-05-03..2017-07-26** — acquisition windows are frozen
constants). Cross-check: `USGS_NYC2014_1_meter` — its service metadata is
EMPTY; units/datum inferred from agreement with 2017 (median Δ +0.075 m,
σ 0.88 m over all 2,120 entrances), recorded as a provenance caveat. No
queryable DSM exists anywhere on the host (71 services enumerated: 54
bare-earth elevation ImageServers + index/extent/hillshade/GP).
`DEM_2024_Long_Island` covers only the eastern Rockaways (4 entrances
measured; Beach 25 St grade dropped 1.29 m in the post-Sandy rebuild) —
upgrade path, not a third epoch.

**Ring sampling (the pluvial term).** 8 points on a 15 m octagon around
every point asset, 2017 epoch only, stored raw as ring15_min_m /
ring15_med_m. 01's spine is 311-dominated (pluvial ponding, governed by
doorway-scale depressions); measured within-cell relief (p50 2.6 m over
cells with >= 3 entrances) shows hex-grain anomaly carries no doorway
signal. 08 composes "local low" from elev vs ring; ring15_med is also the
sanctioned fallback grade for flagged rows. +248 POSTs, one-shot.

**QC.** `grade_ok = NOT (|elev_2017_m - elev_2014_m| > 2.0 OR
elev_2017_m < -1.0)` — one boolean, frozen constants, reasons always
recoverable from the raw columns in the same row. Measured base rates:
entrances 41/2,120 (1.9%, spread over 30 stations in all five boroughs —
the four named mechanisms cover only 9 rows); bus stops 4/4,557 (0.09%)
plus exactly one NoData (stop 308410 Cropsey Av/Hart Pl, clipped by the
topobathy) and one real -1.80 m waterfront stop. NoData => NULL elevations
+ grade_ok=false, counted, never a build failure. Binding: **grade_ok and
epoch deltas are QC filters, never model features** (the 41 flagged rows
concentrate on alert-heavy complexes inside the Sandy polygon — a
memorization channel). Known blind class, measured at Kings Hwy: both
epochs contain the same el deck, so one Station House row passes QC at a
wrong-high grade — cross-epoch agreement != correctness (named 08
obligation). Canonical elev_ft is always the raw 2017 sample; flags are
never silently repaired (no cross-epoch repair works: 2017 is wrong-low at
WTC, wrong-high at the Bensonhurst el — min() picks the pit, max() picks
the el).

**Sampling mechanics (probe conclusions corrected by review).** Join
responses on **batch_offset + locationId** (within-batch input index) —
NEVER by coordinate (06 keeps 9 shared doorways as 2-3 rows at identical
coords; a coordinate join fans samples and erases the NoData diagnostic).
A mixed batch silently omits out-of-footprint points (skipped
locationIds — this, not dedupe, produced the vault's 933/1000); an
all-outside batch hard-400s. `value` arrives as a JSON STRING — explicit
float parse. Sample at **ref/assets coordinates** (entrances 6-dp key
coords, bus stops cross-feed means). Frozen request constants:
`interpolation=RSP_NearestNeighbor` explicit (server default matches
today, but bilinear differs by up to 0.342 m — a third of the water
threshold), wkid 4326, returnFirstValueOnly=true, batch 500.

**Build.** Step 2 of the same build ticket as the ref/assets builder
(samples land at ref coordinates; assets_version change => features
rebuild, the reciprocal of 06's orphan-is-failure contract). Raw responses
snapshot to `data/archive/elevation/<service>_<date>.json`,
write-temp-then-rename, fetch-only-when-missing; the build never calls the
API when snapshots exist. Blocking assertions (rewritten — the draft's
"zero NULL" version fails on day one): asset_id unique 15,490; every point
asset covered by a locationId response OR a counted NULL under a frozen
ceiling; entrance flag count == 41 asserted as a free service-drift
canary; byte-identical rebuild. `features_version` = sha1 over sorted
(asset_id, f"{elev_2017_m:.4f}", f"{elev_2014_m:.4f}",
f"{ring15_min_m:.4f}", f"{ring15_med_m:.4f}") + assets_version + the
frozen constants (2.0 / -1.0 / 3.280833333 / RSP_NearestNeighbor) — pinned
float formatting, chained like label_version. Named check:
`tests/test_features.py` with a frozen 6-coord fixture with expected
values (catches silent interpolation/datum/republish drift). Total POST
budget ~310 one-shot (~15 min), no daemon.

**Skips, true reasons, upgrade paths.**
- DSM-minus-DEM: no cheap path (measured) — NOT "entrance_type
  substitutes": Station House explains almost nothing (median +0.58 m vs
  station-mates; only 10/69 above +3 m) and 76.8% of entrances are
  type=Stair, exactly the class a DSM would split. entrance_type is a
  covariate for 08, not a QC rule. Trigger: 08 names <= N suspect
  stations => pull their finder.nyc.gov 1-ft DSM tiles.
- 2024 LI epoch: eastern-Rockaways-only coverage; re-sample if 08's
  Rockaway residuals demand post-2017 terrain.
- InSAR subsidence: ruled out for v1 by MAGNITUDE (cm vs a 2 m threshold;
  the file is 9 MB, not bulk) — not fog, "never for v1".
- 2010 epoch: pre-Sandy terrain is its value, not its flaw; real reason is
  26.6 GB non-COG ERDAS. Trigger: pre-2014 events score materially worse
  than post-2014.
- Building-footprint ground_elevation: whole-foot quantized, building-min
  semantics (+16.3 ft at Cortelyou Rd), schema drifted
  (ground_elevation/height_roof now).
- Class-25 sills: 109 GB LAS (free 3DEP copy lacks the custom class).
  Trigger sharpened: complex-grain CSI no better than Cell-grain.

**Datum discipline, demonstrated.** Battery nws_minor 10.49 ft STND =
4.43 ft NAVD88. Against the naive STND number, 103 entrances sit "below
minor flood"; in the correct datum, **3** — two of which are the WTC 2017
construction-pit artifacts (really one: Richmond Valley, 4.4 ft). 100
entrances sit below 10 ft NAVD88.

**Handed to 08** (comment posted there): temporal validity of a 2017
surface across the 2010-2026 era; complex aggregation over grade_ok only;
flagged-row fallback rules; the unowned asset->CO-OPS gauge assignment
(nearest of 05's six by geodesic, read-side); the polluted cell negative
universe (2,759/4,113 cells touch no NYC land); relative-elevation
definition and sweep; ring columns as the pluvial inputs. Display
obligations recorded for the eventual serving panel: export drops elev_ft
when NOT grade_ok (else the page paints WTC as a -34 ft city low point
inside the Sandy polygon); legend names datum AND epoch ("NAVD88 US ft,
2017 LiDAR").

## Question

Which elevation features attach to each asset, from the verified stack: 2017
1-m TopoBathymetric ImageServer getSamples (meters — unit conversion rule),
2014 epoch as a cross-check, building-footprint `groundelev` as proxy, DSM
minus DEM at entrances as the headhouse-vs-open-stairwell flag, plus derived
terms (relative elevation vs neighborhood, low-point flags). Units and datum
(NAVD88 ft canonical), where the sampled values live (a Silver asset-features
table?), and whether sampling ~3 POSTs per epoch happens as an in-map task or a
build ticket. Class-25 stairwell sills and InSAR subsidence stay in the fog
unless this discussion pulls them in.

## Comments

2026-08-22 — flagged by 06's resolution: the sampling universe is ALL
radius-target assets (entrances + bus stops, ~15,500 points = ~16 getSamples
POSTs per epoch), not the 2,120 entrances this ticket budgets. Sampled values
land in a sibling `silver/asset_features` keyed by asset_id — `ref/assets` is
immutable. Cell-grain terrain stats (if any) are this ticket's call.
