# Draft — 07 Elevation feature set

Status: DRAFT for adversarial review, 2026-08-22. All numbers below measured
today unless cited to the vault doc.

## Measured today (probe results)

- **No queryable DSM exists.** All 63 services on `elevation.its.ny.gov` are
  bare-earth DEMs (full directory enumerated). The vault doc verified only the
  DEM side; the 2017 Highest-Hit DSM is a 30.1 GB zip or per-tile pulls from
  finder.nyc.gov. The DSM-minus-DEM headhouse signal has no cheap path.
- **No 2024 epoch for NYC.** `DEM_2024_Long_Island` extent starts east of
  Queens (UTM xmin 603000 ≈ lon −73.78); `USGS_2024_1_meter` is upstate.
  NYC epochs remain 2017 (canonical) + 2014 (cross-check) + 2010 (offline only).
- **getSamples works at full scale.** All 2,120 entrances sampled against both
  epochs: 100% match, 0 NoData, ~3 s per 500-point batch, ~31 POSTs per epoch
  for the full 15,490-point universe. Responses are location-keyed, not
  order-keyed — duplicate coords collapse (this explains the vault's 933/1000;
  join by rounded (x,y), never by index).
- **Units are meters** on both 1-m services (EPQS cross-check ratio 3.28, 6
  points). US-survey vs international foot conversion differs < 0.001 ft at NYC
  elevations — use 3.28084, note it, move on.
- **Epochs agree to ~10 cm typically** (median Δ +0.075 m, σ 0.88 m), but
  **41/2,120 entrances (1.9%) disagree by > 2 m**, in four structured clusters:
  WTC Cortlandt construction pit (2017 reads −10.5 m — the DEM froze a
  2017 excavation), Grand Central easements (Park Ave viaduct interpolation,
  Δ −13 m), 174-175 Sts rock cuts, and Bensonhurst elevated-line station
  houses (2017 reads the el structure, Δ +6 m).
- **Ring-median does not repair bad points.** 15 m octagon probes: at WTC the
  entire neighborhood is in the pit (ring median −10.38 m); at Grand Central
  and 174-175 Sts the ring straddles two real terrain levels. Flag, don't fix.
- **`entrance_type` already carries the headhouse signal**: Stair 1,629,
  Easement-Street 164, **Station House 112**, Elevator 102, Easement-Passage
  57, Escalator 18, rest < 20 each. (i9wp-a4ja snapshot written to
  `data/archive/subway/i9wp-a4ja_2026-08-22.json`, 2,120 rows — 06's
  designated path.)
- **Building footprints rejected as a proxy.** Schema drifted since the vault
  doc (`ground_elevation`/`height_roof` now, not `groundelev`/`heightroof`);
  values are whole-foot quantized; semantics are building-minimum, not
  entrance-point (+16.3 ft error at Cortelyou Rd); point-in-footprint
  discriminates Station House vs Stair only imperfectly (4/6 vs 0/10 in the
  probe) and adds nothing over `entrance_type`.
- **Bus stops sample clean**: 500-stop probe, 0 NoData, min −0.59 m (real
  waterfront grade, not seafloor). `silver/stops` already carries
  lon/lat/cell per pick.
- **Datum trap quantified**: 103 entrances sit "below" Battery nws_minor if
  you compare NAVD88 ft against the 10.49 STND number; in the correct datum
  (10.49 − 6.06 = 4.43 ft NAVD88) it is **3**, two of which are the WTC
  artifacts. 100 entrances sit below 10 ft NAVD88.

## Proposal

**One table: `silver/asset_features`** at `data/silver/asset_features/` —
plain Parquet per pipeline-09 Silver conventions (no geometry column;
asset_id is the FK to `ref/assets`, which stays immutable per 06).

**Rows: 19,603** = 15,490 point assets (2,120 entrances + 13,370 bus stops)
+ 4,113 cells. Complexes/stations get no rows: complex elevation is a
read-side aggregate over child entrances (min = ingress logic), and whether
min or median is a modeling call that belongs to 08.

**Columns**

| column | type | rule |
|---|---|---|
| asset_id | STRING pk | FK to ref/assets |
| kind | STRING | {entrance, bus_stop, cell} |
| elev_2017_m | DOUBLE | raw getSamples value, NYC_TopoBathymetric_2017_1_meter |
| elev_2014_m | DOUBLE | raw getSamples value, USGS_NYC2014_1_meter |
| elev_ft | DOUBLE | elev_2017_m × 3.28084 — canonical NAVD88 ft |
| d_epoch_m | DOUBLE | elev_2017_m − elev_2014_m |
| grade_qc | STRING | {ok, epoch_disagree, suspect_water} — see rules |
| rel_elev_ft | DOUBLE | elev_ft − median(elev_ft of grade_qc='ok' point assets in same cell); NULL for cell rows |
| cell | INT64 | h3 res 8, copied from ref/assets |
| elev_min_ft / elev_med_ft / elev_max_ft / n_assets | DOUBLE×3, INT | cell rows only: aggregates over member ok point assets |
| src_asof | DATE | snapshot date |

**grade_qc rules (frozen constants, not tuned):**
`epoch_disagree` = |d_epoch_m| > 2.0 (catches all four measured failure
clusters, 41/2,120 entrances; bus-stop count measured at build).
`suspect_water` = elev_2017_m < −1.0 (topobathy seafloor; −0.59 m real
waterfront grade stays ok). Flags are never silently repaired — canonical
elev_ft is always the raw 2017 sample. The read-side fallback for flagged
rows (cell median of ok assets) is 08's to apply, and cross-epoch agreement
still does not prove correctness (both epochs could class the same el
structure as ground) — accepted residual risk, upgrade path below.

**Cell rows** sample the ref/cells centroid for elev_ft (both epochs, same
QC rules) and add the member-asset aggregates. Every cell has ≥ 1 member
point asset by construction (06: cells in ref/assets are the cells of the
point assets).

**Derived terms stop at rel_elev_ft.** Low-point flags, below-threshold
margins (e.g. elevation vs per-station nws_minor in NAVD88 via 05's
offsets), and any binning are score-side features — 08 composes them from
elev_ft + rel_elev_ft + 05's offsets. This table stores measurements, not
modeling choices.

**Build: a build ticket, not an in-map task.** The probes de-risked the API
mechanics end-to-end; the build needs ref/assets to exist first (bus-stop
asset_ids come from the cross-feed dedupe), so it lands as a build ticket
beside the ref builder. Mechanics: raw API responses snapshotted to
`data/archive/elevation/<service>_<date>.json` (batch 500, location-keyed
join, fetch-only-when-missing — same pattern as 06's Socrata snapshots);
`make features` builds from snapshots only, never calls the API;
byte-identical rebuild gate; blocking assertions — every point asset
matched in both epochs (2,120 + 13,370), every cell centroid matched,
row count 19,603, asset_id unique, zero NULL elev_ft. `features_version` =
sha1 over sorted (asset_id, elev_2017_m, elev_2014_m), recorded like 06's
assets_version. ~40 POSTs per epoch total, minutes of wall clock, one-shot
— no daemon.

## Skipped, with reasons and upgrade paths

- **DSM − DEM headhouse flag**: no queryable DSM (measured); entrance_type
  already labels Station House / Easement / Elevator. Upgrade: per-tile 1-ft
  DSM pulls from finder.nyc.gov for specific stations if 08's residuals
  point at canopied stairs.
- **Building-footprint ground_elevation**: quantized + wrong semantics
  (measured above); the DEM sample is strictly better at the point.
- **LiDAR class-25 stairwell sills** (109 GB), **InSAR subsidence**,
  **2010 epoch** (26.6 GB, pre-Sandy terrain only), **slope / flow
  accumulation / HAND**: all stay in the map's fog with their existing
  triggers (08 CSI poor; entrance-grade DEM too coarse).
- **EPQS/3DEP third opinion**: probe-only unit sanity, not a feature.

## Decision points for the numbered round

1. Table shape: 19,603 rows (point assets + cell rows), no complex/station
   rows — complex aggregation stays read-side in 08.
2. grade_qc frozen constants: |Δepoch| > 2.0 m, elev < −1.0 m.
3. rel_elev_ft materialized in-table (cell medians are computed anyway for
   the cell aggregates).
4. Canonical elevation = raw 2017 always; flags never silently repaired.
5. Skip DSM/footprints/class-25/InSAR/2010 with recorded upgrade paths.
6. Elevation sampling is a build ticket (post-ref/assets), snapshots
   fetch-only-when-missing, ~40 POSTs/epoch, no daemon.
