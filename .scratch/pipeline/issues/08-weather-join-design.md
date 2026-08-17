# 08 Weather join design

Type: grilling
Status: resolved
Blocked by: 02, 03

## Question

How precip attaches to bus observations: at what key (H3 cell-hour vs point sample),
from which store per epoch (AORC historical vs MRMS near-real-time, per ticket 02),
via which bridge (per ticket 03), and the lag structure (precip in trailing 15/60/180
min windows, antecedent wetness). Also where the join runs: inside the streaming job
(broadcast grid) vs a batch feature table the streaming output joins later. Output of
this ticket is the feature spec the analysis stands on.

Asset (2026-08-15): raster playbook, [research/raster-playbook.md](../../../research/raster-playbook.md).
Pre-loads this decision with: MRMS-to-AORC regridding is refinement (MRMS is the
coarser grid at 40.7N) and precip is extensive, so conservative/area-weighted;
resampling method by variable type; H3 res 8 is about 1:1 with an AORC cell so it
is the join key; rolling sums live in xarray (Sedona reads no Zarr/GRIB2); the
one place Sedona rasters belong is RS_Values point extraction, distributed.
Six 15-minute open items are listed at the end of the playbook (MRMS hour-ending
convention, Atlas 14 units, 2017 NVA figure, InSAR units/sign, pysheds HAND
signature, 2010 land cover pixel size).

## Comments

2026-08-16, from [06 Delay metric design](06-delay-metric-design.md): the bus side
of the join is now fixed. Event = one arrival (passage) per (start_date, trip_id,
stop_sequence, vehicle_id) with the stop's Cell and `arrival_ts`; the response
variable for rain is `segment_excess_s` (actual minus scheduled stop-to-stop time,
local to the segment ending at that stop), not the cumulative `delay_s`. Natural
join key is (Cell of the stop, hour of arrival_ts); trailing-window precip attaches
to the arrival hour. Headway/EWT lives at (cell, hour, route) in Gold.

2026-08-16, from [09 Storage and CRS conventions](09-storage-crs-conventions.md): precip is stored at native Pixel grain, `precip_hourly (i, j,
hour_end_utc, mm)` partitioned `src=aorc|mrms/month=`, unique per src; `ref/grids`
freezes each grid from its stored coordinate arrays (AORC: origin (-130.0, 20.0), step
0.008333 float32-truncated, center registration; MRMS row is yours) and
`ref/cell_pixel (grid_id, cell, i, j, weight)` is the area-weighted crosswalk
(sum = 1 per cell). Yours to decide: whether the join uses Cell-grain precip (a view
or sibling table through `cell_pixel`) or `RS_Values` at the bus position; the MRMS
bridge (own crosswalk vs conservative regrid onto the AORC grid) and its hour-ending
check; the trailing windows. Bronze keeps the AORC NYC slice as local Zarr for the
xarray rolling sums.

## Answer

Resolved 2026-08-16 by grilling; measured first (MRMS GRIB2 forensics on two
storms, Cell-vs-Pixel on three storm hours, wet-hour and phase census, AORC epoch),
verified against primary docs, then two adversarial reviews (hydromet lens, data
lens) reversed nine parts of the first draft before the round. All four
recommendations accepted as-is. The feature spec is the asset
[research/08-weather-join-features.md](../../../research/08-weather-join-features.md);
the numbers are in [research/08-weather-join-evidence.md](../../../research/08-weather-join-evidence.md);
this Answer is the index.

1. **Key, grain, landing.** Precip attaches at Cell-hour grain via a sibling table
   `silver/precip_cell_hourly (src, cell, hour_end_utc)`, built per (src, month)
   from `precip_hourly` x `cell_pixel` on a dense hourly spine (24 h lookback read
   from the input, so months build in any order). No precip columns on Silver
   `events` or on Gold: consumers join at read with `src` pinned. `RS_Values` at the
   bus position is off the feature path (a Pixel is ~1% off the Cell mean; the Cell
   wins on cross-grid comparability and one code path) but is run once on the two
   storm days (Product 3, ticket 10) to report the Cell-mean vs stop-Pixel slope
   difference. Stored `precip_hourly` footprint = the crosswalk's Pixel set (4,868
   for AORC), not the bbox: 153 rim Cells otherwise carried weight on Pixels with no
   rows (hole left by 09, closed here).
2. **Sources and epochs.** `src=aorc` for the whole 2017-2024 backfill (AORC ends
   2025-12-31T23:00Z, no 2026.zarr); `src=mrms` = `MultiSensor_QPE_01H_Pass2`
   (0.86-0.92 of AORC on both storms; RadarOnly swings 0.59-1.02), ingested from
   2026-08-14T00:00Z. Srcs are never pooled in one fit (`src` is collinear with era
   and with congestion pricing); the MRMS era is an out-of-sample replication read
   against the expected scale ratio. MRMS is hour-ending (proven by lag-0
   correlation r 0.97-0.999; the GRIB header cannot show it), reaches Cells through
   a second `cell_pixel` set, and is NOT regridded onto the AORC grid (overturns
   02's closing line and the playbook's xesmf rule; ADR-0002). Any negative
   sentinel -> a stored NULL row; no raw GRIB2 in Bronze (NODD is the archive).
   07's live table reads RadarOnly at its :00 stamps (a true Hour, ~5 min behind);
   the 2-min files are a distinct rolling feature. Overlap comparison deferred to
   2026 when 2026.zarr lands (a 2023 full-year MRMS ingest was judged YAGNI).
3. **Time alignment and features.** `hour_end_utc = ceil_hour(arrival_ts)`; lag
   rule per grain (Gold: mm_1h + mm_1h_prev is a valid two-term lag; event grain
   carries minute-of-hour or the trailing-60-min estimate); the headline causal
   estimate is leakage-free (`mm_1h_prev` + longer lags). Stored: `mm_1h,
   mm_1h_prev, mm_3h, mm_6h, mm_24h, n_hours_24h, t2m_c` (AORC 2 m temperature via
   the same crosswalk; NULL in the MRMS era until a live-era phase source is
   chosen). Models consume disjoint lags by subtraction (nested sums have VIF up to
   12.5). One null rule: Cell-hour NULL unless non-null weight sums to 1; mm_3h/6h
   NULL if any frame hour is NULL; mm_24h gated by `n_hours_24h`. Gold parameter
   defaults with a three-cutoff sweep: dry = mm_1h < 0.1 AND mm_1h_prev < 0.1; wet =
   mm_1h >= 1.0 AND t2m_c > 2; frozen counted separately; the 0.1-1.0 band excluded
   from the binary contrast; onset vs sustained from existing columns. No
   sub-hourly features, no API (flood map), both with named limitations, plus the
   effective-resolution caveat (adjacent AORC Pixels r 0.996-0.998: hotspot claims
   must survive a ~4 km-aggregated rerun).
4. **Recorded.** CONTEXT.md gains Hour, Wet hour / Dry hour, Precip source,
   Trailing window; ADR-0002 records the two measurement-established MRMS
   conventions.

Consequences: comments on 02 (regrid overturned), 09 (Gold precip columns dropped,
footprint rule, `t2m_k` on `precip_hourly`, MRMS `grids` row, Zarr slice is the
fidelity copy), 07 (live-table constraints, engine, SQL parses on both), 10
(defaults, Product 3 slope report, coarsened rerun); `research/09-storage-schemas.md`
updated in place for those three lines. Fog: live-era precip-type source before
winter 2026-27; sub-hourly live features; the 2026 overlap year and AORC re-key.
Build items for `/to-spec`: MRMS ingest (Pass2 :00 files -> `precip_hourly
src=mrms` with the row flip, negatives -> NULL, `grids` row with its sha256),
`cell_pixel` for `grid_id='mrms'`, `t2m_k` on the AORC ingest, the per-(src, month)
`precip_cell_hourly` job with tests 1-8, `ceil_hour`.

## Comments

2026-08-16, from [07 Enrichment execution model](07-enrichment-execution-model.md):
engine for section 5's SQL is Spark 3.5 (DuckDB reads only). Measured: `generate_series`
is not a Spark 3.5 table-valued function, so the dense spine is
`explode(sequence(:month_start - INTERVAL 24 HOUR, :month_end, INTERVAL 1 HOUR))` on
Spark; `FILTER (WHERE)`, `INTERVAL 24 HOUR` and the inline window specs parse as written.
The note under section 5 of `research/08-weather-join-features.md` is corrected in place
(one line); the Spark-vs-DuckDB run of the two spine texts is a one-off evidence script,
not a job step. Live table decided: `live/precip_cell/valid_ts=<YYYY-MM-DDTHH>` string
key, RadarOnly `:00` only, 7 d retention, written by a 300 s LaunchAgent job; the
stream joins the scalar latest complete Hour <= batch time. `src=mrms` in live mode:
Pass2 lands daily in a decoded Bronze copy `data/archive/precip/mrms/date=/hour=HH`
(footprint only, ~1.2 MB/day - your rule forbade GRIB2 bytes, not a decoded copy) and
the month partition is rebuilt from it as one file; a uniqueness check on
`precip_hourly (src, i, j, hour_end_utc)` per partition is added.

2026-08-16, from [10 Backfill slice and speed-derivation rules](10-backfill-slice-and-speed-rules.md): three things for your spec.
(1) The dry rule for the Speed baseline gets a recovery guard, `mm_1h < 0.1 AND
mm_1h_prev < 0.1 AND mm_6h < 0.5` (swept): after Ida the rain ends at 07Z and 84% of
Cells are dry by your rule from 08Z, all by 09Z, while buses run at 0.80-0.90 of normal
through 08Z and 0.94-0.95 into the next commute - the response outlives the rain by 5+
hours, which is also the measured reason `mm_1h_prev`/`mm_3h`/`mm_6h` matter (Ida
ratios 0.93 -> 0.77 -> 0.73 -> 0.80 -> 0.89 -> 0.94 over 02Z-12Z). (2) Composite
windows are taken from the rain per Cell (`mm_1h`/`mm_6h`), not off the citywide mean:
the 2023-09-29 storm's largest Cell-hour (87 mm) is at 19Z with 3,029 Cells >= 1 mm.
(3) Product 3 runs on Legs first (one-off script over the two storm days), stops once
`events` exists. Facts: the 168 permanently-NULL AORC Cells carry no bus Legs; AORC has
two real gaps in the span (all of 2024-06-18 and 2024-11-27T20Z), covered by your
NULL-row rule; `precip_hourly`/`precip_cell_hourly src=aorc` for 2021-08..10 and
2023-09..10 (+24 h lookback) are the slice's precip build items.
