# 08 Weather join: feature spec

Asset of ticket [08 Weather join design](../.scratch/pipeline/issues/08-weather-join-design.md).
Resolved 2026-08-16; all four recommendations accepted. Types are Parquet logical types;
`TS` = TIMESTAMP(us, UTC). Inherits 06 (event grain; key = Cell of the stop + hour
of `arrival_ts`; response = `segment_excess_s`), 09 (`precip_hourly (i, j,
hour_end_utc, mm)` at Pixel grain per `src`, `ref/grids`, `ref/cell_pixel`
area-weighted crosswalk, Gold grains), 02/03 (AORC history, MRMS live,
xarray/cfgrib readers, stream-static join with an uncached static side).
Evidence: [08-weather-join-evidence.md](08-weather-join-evidence.md).

## 0. Facts the decisions stand on (measured 2026-08-16)

- **MRMS timestamps are hour-ending, same as AORC.** The GRIB2 header cannot show
  it (PDT 0 "instant", step 0, no time-range keys), so it was tested: Central Park
  hourly series, MRMS file stamp matched 1:1 to AORC's verified hour-ending label,
  Pearson r at lag 0 = 0.971 (Pass2) / 0.943 (RadarOnly) on 2023-09-29 and 0.999 /
  0.998 on Ida; at +/-1 h r collapses to 0.46-0.82. Peak hour agrees: hour ending
  2021-09-02T02:00Z AORC 84.2 / Pass2 75.0 / RadarOnly 85.9 mm at Central Park.
- **One MRMS grid for all products**: first point lon 230.005 (0-360; = -129.995),
  lat 54.995, step 0.01, Ni 7000, Nj 3500, `jScansPositively=0` (row 0 = north),
  Pixel-centre registration (offset exactly 0.5). Pass1/Pass2: one file per hour
  at :00 (~0.45 MB gz). `RadarOnly_QPE_01H`: a file every 2 min, each a ROLLING
  60-min total ending at its own stamp; only the :00 stamps are Hours.
- **Sentinels**: `missingValue=9999` declared, never present. RadarOnly carries -3
  on ~40% of CONUS (inferred: no radar coverage; -1 never observed, so the -1/-3
  split is unverified and nothing here depends on it); MultiSensor none; NYC bbox
  fully covered. Rule: any negative value -> null.
- **Pass2 vs AORC at Central Park**: daily-total ratio 0.92 (2023-09-29) and 0.86
  (Ida); RadarOnly 0.59 and 1.02 (event-dependent sign). AORC precip is Stage IV +
  NLDAS based (registry page), so AORC-vs-MRMS compares two separately produced
  QPEs. Latency observed 2026-08-16T19:32Z: Pass2 1 h 33 min, Pass1 33 min,
  RadarOnly 5 min behind wall clock (NOAA WDTD: Pass1 20 min / ~10% gauges, Pass2
  60 min / ~60% gauges).
- **Cell mean vs single Pixel (AORC, three storm hours, cells >= 1 mm)**: centroid
  Pixel and largest-share Pixel are indistinguishable; vs the area-weighted Cell
  mean, relative error p50 0.8-1.3%, p90 3.1-4.0%, max 0.67-0.72 in gradient-
  straddling cells; > 25% off in 0.08-0.13% of cells. Crosswalk: 4,113 Cells,
  19,512 rows, 4.74 Pixels/Cell, largest share p10/p50/p90 0.38/0.53/0.73, zero
  Cells >= 0.9, sum(weight) = 1 in 4,113/4,113. Its footprint is 4,868 distinct
  Pixels (i 6684..6763, j 2454..2515), i.e. one Pixel wider than 09's 78 x 60 =
  4,680 sizing: 153 Cells carry weight on Pixels outside that slice (lost weight
  p50 0.21, max 0.93). Central Park's Cell (882a100895fffff): four Pixels
  84.4/87.1/84.2/83.4 mm, weights .17/.02/.77/.03, mean 84.28 mm on the Ida hour.
- **AORC epoch**: 2025.zarr ends 2025-12-31T23:00Z; no 2026.zarr; registry update
  frequency "To be determined". AORC ships `TMP_2maboveground` on the same grid.
- **Field smoothness / phase / class sizes, AORC 2021 NYC bbox**: adjacent Pixels
  correlate at r 0.996-0.998 (a Stage IV ~4 km field lives under the 800 m array);
  a Pixel is >= 0.1 mm in 10.2% of hours, >= 1.0 mm in 3.65%; of Pixel-hours >= 1
  mm, 11.0% fall at 2 m temperature <= 2 C (7.2% of annual depth); with the
  defaults below: dry 87.6%, wet 3.65%, neither 8.7% of hours; of hours meeting
  the dry rule only 0.38% had >= 1 mm in the previous 3 h; corr(mm_1h, mm_1h_prev)
  = 0.48 on non-dry hours; VIFs of the five nested windows reach 12.5 (mm_3h).
- **Lag literature** is thin and unverified (one connected-vehicle study reports
  ~17 min from first rain to speed impact, snippet only). Nothing there overrides
  the design; it does say the sub-hour position matters (section 3).

## 1. Join key, grain, landing

- Precip reaches the analysis at **Cell-hour grain** through a sibling table
  `silver/precip_cell_hourly` keyed **(src, cell, hour_end_utc)**, never per event
  via `RS_Values`. Not because a Pixel is wrong (median 1% off the Cell mean) but
  for coherence: the response is attached to the stop's Cell (06); Gold is (cell,
  hour_end_utc, route) (09); a Cell-keyed feature is comparable across `src` while
  a Pixel-keyed one is not (the two grids differ); one code path for backfill,
  live, and both sources. The area-weighted mean IS the conservative remap of a
  depth field onto the Cell (volume = depth x area), not an approximation of one.
- `RS_Values` stays buildable (native Pixel grain kept by 09) and is used **once**,
  on the two storm days (playbook Product 3, ticket 10): report the rain-vs-
  `segment_excess_s` slope both ways, Cell mean vs stop Pixel, and record the
  difference here. If they agree the aggregation question is retired; if not the
  attenuation is quantified rather than assumed. It is not on the feature path.
- Sibling table, not a view: the windows are window functions over a dense hourly
  spine per (src, cell); a view would sort 36M rows to answer one Cell-hour.
- **No precip columns on Silver `events` and none on Gold.** Consumers join
  `precip_cell_hourly` at read on (src, cell, hour_end_utc) with `src` pinned
  explicitly, the way Gold already joins `ref/cells` for geometry (09). One copy
  of each feature; a new window or a re-keyed year rebuilds one ~0.2 GB/yr table,
  never the ~56 GB `events` or Gold. (Reviewers split on Gold; the read-time join
  wins on fewer copies and on keeping the src pin at read.)
- **Where the join runs**: a batch job per (src, month), idempotent, replaces the
  partition. It reads a 24 h lookback from `precip_hourly` (the input, not the
  previous month's output), so months build and rebuild in any order and a
  correction to month M never cascades. The Silver rebuild at D+1 06:00 (09) has
  Pass2 for the whole day by then. The streaming demo (07) does the documented
  stream-static join (03) against a small live Cell-grain table (section 2),
  static side uncached; no in-stream broadcast grid.

## 2. Sources, epochs, the MRMS bridge

- `src = aorc` for every hour AORC publishes (today hour_end_utc <=
  2025-12-31T23:00Z): the whole 2017-07..2024-09 backfill. `src = mrms` for the
  live era, **ingested from 2026-08-14T00:00Z** (24 h before the bus archiver's
  first Snapshot); 2026-01-01..08-13 has no bus data and is deliberately not
  ingested. When 2026.zarr lands, 2026 gains src=aorc rows: a src-pin change and
  the real overlap year (section 2, last bullet), not a schema change.
- **Srcs are never pooled in one fit.** The measured difference is a scale
  difference in the regressor (Pass2 ~0.86-0.92 of AORC), which biases a slope, and
  `src` is perfectly collinear with era (bus data 2017-2024 vs 2026+, no overlap;
  congestion pricing 2025-01-05 sits in the gap). The MRMS-era fit is an
  out-of-sample replication of the AORC-era coefficient, read against the expected
  scale ratio, not extra n.
- MRMS product for the batch table: **`MultiSensor_QPE_01H_Pass2`** (gauge-
  corrected, hourly at :00; the only product with a stable relationship to AORC:
  0.86-0.92 vs RadarOnly's 0.59-1.02 swing). Latency is irrelevant at D+1.
- **Live table (07's)**: read `RadarOnly_QPE_01H` at its **:00 stamps only** (a
  true Hour, ~5 min behind, one file per hour, same grid so the same crosswalk) so
  the live `mm_1h` is the same feature at lower latency, labelled fast /
  uncalibrated (RadarOnly read 0.59 of AORC on 2023-09-29). If 07 wants the 2-min
  files, that is a distinct feature `mm_60min` with `window_end_utc` (a rolling
  60-min total ending at the stamp, NOT an Hour), never joined to the batch
  features. Live-table writes are append-only per `valid_ts=` partition, latest
  wins, no overwrite (Hive Parquet has no snapshot isolation, 09); retention 07's.
- MRMS reaches Cell grain the way AORC does: a second `ref/grids` row and a second
  `cell_pixel` set. **No regridding of MRMS onto the AORC grid** (xesmf /
  rasterio.reproject is YAGNI and strictly worse: it composes two conservative
  maps where one suffices). This overturns 02's closing line ("one canonical grid
  to resample onto") and the playbook's standing rule; comment left on 02.
- `ref/grids` convention: origin = SW Pixel CENTRE, i east, j north, every grid;
  MRMS ingest flips rows (`j = 3499 - row`), converts lon from 0-360, and freezes
  `coord_sha256` = sha256 of the GRIB grid tuple actually read (Ni, Nj, first and
  last lat/lon, i/j increments, jScansPositively); `frozen_at` = ingest time of
  that file. `grids.grid_id` and `precip_hourly.src` are the same strings by
  invariant (`aorc`, `mrms`).
- **Stored footprint = the crosswalk's Pixel set**, per grid: `precip_hourly`
  holds exactly `SELECT DISTINCT i, j FROM ref/cell_pixel WHERE grid_id = :src`
  (AORC 4,868 Pixels, 117K rows/day; MRMS measured at build), not a bbox. Closes
  the hole 09 left (crosswalk padded by one Pixel, table sized on the bare bbox).
- Sentinels: any negative value -> **a stored row with `mm` NULL** (never dropped),
  one rule for both srcs (covers MRMS -1/-3 and AORC -32767 alike; CF decoding
  handles AORC's fill first). `precip_hourly` is therefore dense over footprint x
  published hours; an absent row means only "the source hour is missing".
- Bronze: no raw MRMS GRIB2 archived; NODD is the archive (public, complete from
  2020-10-14T20:00Z, listing verified), so `precip_hourly src=mrms` (NYC footprint,
  float32 mm, lossless) is the first landing, 24 GETs/day. The AORC Zarr NYC slice
  stays as 09 decided, as the fidelity copy (the windows are SQL, section 5, not
  xarray).
- **Overlap comparison**: not a 2023 full-year MRMS ingest (8,760 GETs, ~4 GB,
  hours of CONUS decodes for a ratio two storms already bracket). The instrument is
  (a) the two-storm ratio above now, (b) the 2026 overlap when 2026.zarr lands,
  which coincides with real bus observations. Until then MRMS-era coefficients
  carry "expected scale 0.86-0.92 of AORC" as a caveat.

## 3. Time alignment and the feature vector

- **Hour**: hour-ending UTC label H covers (H-1h, H]. An event with `arrival_ts =
  t` joins `hour_end_utc = ceil_hour(t)` (t exactly on the hour stays in H).
- **Lag rule, per grain.** `mm_1h` includes rain after the arrival within the
  hour (a :01 arrival: nearly all of it; :59: none), `mm_1h_prev` is fully
  elapsed. At Gold grain (cell, hour_end_utc, route) the within-hour position
  averages out, so (mm_1h, mm_1h_prev) is a valid two-term distributed lag. At
  event grain the model must carry `minute_of_hour` (derived from `arrival_ts`,
  no storage) interacted with `mm_1h`, or use the trailing-60-min estimate
  `f*mm_1h + (1-f)*mm_1h_prev` with `f = minute/60`. The **headline causal
  estimate is the leakage-free one** (`mm_1h_prev` + longer lags, no `mm_1h`);
  `mm_1h` is the concurrent-plus-lead term. Leakage attenuates a rain coefficient
  toward zero, so a null result on `mm_1h` alone is not evidence of no effect.
- **Stored per (src, cell, hour_end_utc)**: `mm_1h`, `mm_1h_prev`, `mm_3h`, `mm_6h`,
  `mm_24h` FLOAT32 (trailing windows ending at H, inclusive), `n_hours_24h` INT8,
  and `t2m_c` FLOAT32 (area-weighted Cell mean of AORC `TMP_2maboveground`;
  temperature is intensive so the same weights are the right remap; NULL for
  src=mrms until a live-era phase source is wired, before winter 2026-27).
- **Models consume disjoint lags**, derived at read by subtraction, no schema
  change: `mm_1h`, `mm_1h_prev`, `mm_3h - mm_1h - mm_1h_prev` (t-2), `mm_6h - mm_3h`
  (t-3..t-5), `mm_24h - mm_6h` (t-6..t-23). The nested sums are the right thing to
  store (one window function each) and the wrong thing to regress on (VIF 12.5).
- **Null policy, one rule**: a Cell-hour is NULL unless the weight of its non-null
  Pixels sums to 1 (within 1e-6); `mm_3h` and `mm_6h` are NULL if any hour in
  their frame is NULL (a value present is a value complete); `mm_24h` alone keeps
  the count-and-decide treatment via `n_hours_24h`, because nulling a whole day
  per gap is too expensive there. `# ponytail: any-null-pixel nulls the
  cell-hour; renormalize weights if MRMS gaps prove material.`
- **Gold parameters (defaults, not columns)**, all with a required three-cutoff
  sensitivity sweep (playbook pitfall 9):
  - dry hour = `mm_1h < 0.1 AND mm_1h_prev < 0.1` (deviates from the playbook's
    one-hour rule on purpose: wet roads outlast the rain; measured clean, 0.38% of
    dry hours had >= 1 mm in the previous 3 h; costs ~2 points of baseline hours);
  - wet hour = `mm_1h >= 1.0 AND t2m_c > 2` (rain, not snow); frozen = `mm_1h >=
    0.1 AND t2m_c <= 2`, excluded from both classes and counted separately;
  - the band 0.1 <= mm_1h < 1.0 (8.7% of hours, ~70% of hours with any measurable
    precip) is excluded from the binary contrast; the continuous features do not
    pay this cost;
  - onset hour = `mm_1h >= 1.0 AND (mm_6h - mm_1h) < 0.1`, sustained hour = `mm_1h
    >= 1.0 AND (mm_6h - mm_1h) >= 1.0` (first rain after a dry spell vs the eighth
    hour of a soaking; the front-loaded surface effect).
  Sample size at the wet default: ~320 wet Cell-hours per Cell-year (~285 after
  frozen), from the 2021 census.
- **Not in the spec**: sub-hourly features (AORC is hourly and covers 7 of the ~8
  bus years; MRMS 15M / 2-min products are 07's live add) - so the study measures a
  response to hourly accumulation, not to rain rate: 5 mm of drizzle and a 6-min
  cloudburst are the same feature value, a named limitation; the leaky-integrator
  API (a soil-moisture instrument, deferred to the flood map; `mm_24h` is the
  antecedent term here); a per-Cell precip-type product for the live era
  (`PrecipFlag` or ASOS temperature - decide before winter 2026-27).
- **Effective spatial resolution, a named limitation**: adjacent AORC Pixels
  correlate at r 0.996-0.998 and the field decimates to ~2 km with ~3.5% error, so
  4,113 Cells see tens, not thousands, of independent rain series; per-Cell
  coefficients are spatially pseudo-replicated and Cell-scale hotspots can be
  artefacts of rain-field smoothness. Any per-Cell hotspot claim must survive a
  rerun with `cell_pixel` weights aggregated to ~4 km blocks, alongside the
  support-count gate (playbook item 2).

## 4. Tables

### `silver/precip_cell_hourly`

Partition `src=aorc|mrms / month=YYYY-MM` (month of the hour-ending label, so
hour_end 2021-09-01T00:00Z is in month=2021-09 though its rain fell on 08-31);
plain Parquet, zstd, sorted (cell, hour_end_utc) to match `events`; grain (src,
cell, hour_end_utc) unique; **dense**: every Cell in `ref/cells` x every hour of
the month, NULL where the source hour is missing.

| column | type | notes |
|---|---|---|
| cell | INT64 | H3 res 8, every row of `ref/cells` |
| hour_end_utc | TS | the Hour |
| mm_1h | FLOAT32 | area-weighted Cell mean via `cell_pixel[grid_id = src]`; NULL unless non-null weight sums to 1 |
| mm_1h_prev | FLOAT32 | mm_1h of the previous Hour |
| mm_3h, mm_6h | FLOAT32 | trailing sums ending at H inclusive; NULL if any hour in the frame is NULL |
| mm_24h | FLOAT32 | trailing sum; consumers gate on n_hours_24h |
| n_hours_24h | INT8 | non-null hours in the 24 h frame (24 = complete) |
| t2m_c | FLOAT32 | Cell mean 2 m temperature, AORC only; NULL for src=mrms for now |

Size: 4,113 x 8,760 = 36.0M rows/yr; ~0.2 GB/yr zstd (186 MB/yr measured on a
synthetic field before `t2m_c`); the 7.2-year backfill ~1.5 GB. Measure at build.

### `ref/grids` (09's columns exactly; MRMS row added)

| grid_id | source_url | origin_lon | origin_lat | step_deg | nx | ny | registration | coord_sha256 | frozen_at |
|---|---|---|---|---|---|---|---|---|---|
| aorc | s3://noaa-nws-aorc-v1-1-1km | -130.0 | 20.0 | 0.008333 (float32-truncated, from the arrays) | 8401 | 4201 | center | sha256 of the stored coordinate arrays (09) | build time |
| mrms | s3://noaa-mrms-pds/CONUS/MultiSensor_QPE_01H_Pass2_00.00 | -129.995 | 20.005 | 0.01 | 7000 | 3500 | center | sha256 of the GRIB grid tuple (Ni, Nj, first/last lat/lon, increments, jScansPositively) | ingest time of the file read |

MRMS source rows run north-to-south; ingest stores `j = 3499 - row`. NYC
footprint: `cell_pixel[grid_id='mrms']` Pixels (Central Park at i 5603, j 2078;
the bbox spans i 5569..5635, j 2045..2095 before padding). Pixels per Cell:
measure at build (an MRMS Pixel is ~0.94 km2 at 40.7N, larger than a Cell).

### `silver/precip_hourly` (09's table; two clarifications)

Footprint per src = the crosswalk's Pixel set (not the bbox); negative sentinels
are stored as `mm` NULL rows, never dropped.

### Gold

Unchanged by 08: no precip columns. Analyses join `precip_cell_hourly` on (src,
cell, hour_end_utc) with `src` pinned.

## 5. Build sketch (one job per (src, month); parses on Spark 3.5 and DuckDB)

```sql
-- :month_start = first Hour of the month (YYYY-MM-01T00:00:00Z),
-- :month_end   = last Hour of the month (last day T23:00:00Z)
WITH hours AS (
  SELECT h AS hour_end_utc
  FROM generate_series(:month_start - INTERVAL 24 HOUR, :month_end, INTERVAL 1 HOUR) AS t(h)
), cell_hour AS (
  SELECT x.cell, p.hour_end_utc,
         CASE WHEN sum(x.weight) FILTER (WHERE p.mm IS NOT NULL) < 1 - 1e-6 THEN NULL
              ELSE sum(x.weight * p.mm) END AS mm_1h,
         CASE WHEN sum(x.weight) FILTER (WHERE p.t2m_k IS NOT NULL) < 1 - 1e-6 THEN NULL
              ELSE sum(x.weight * p.t2m_k) - 273.15 END AS t2m_c
  FROM precip_hourly p
  JOIN cell_pixel x ON x.grid_id = p.src AND x.i = p.i AND x.j = p.j
  WHERE p.src = :src
    AND p.hour_end_utc BETWEEN :month_start - INTERVAL 24 HOUR AND :month_end
  GROUP BY x.cell, p.hour_end_utc
), dense AS (
  SELECT c.cell, h.hour_end_utc, ch.mm_1h, ch.t2m_c
  FROM cells c CROSS JOIN hours h
  LEFT JOIN cell_hour ch ON ch.cell = c.cell AND ch.hour_end_utc = h.hour_end_utc
)
SELECT cell, hour_end_utc, mm_1h,
       lag(mm_1h) OVER (PARTITION BY cell ORDER BY hour_end_utc) AS mm_1h_prev,
       CASE WHEN count(mm_1h) OVER (PARTITION BY cell ORDER BY hour_end_utc ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) < 3 THEN NULL
            ELSE sum(mm_1h)  OVER (PARTITION BY cell ORDER BY hour_end_utc ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) END AS mm_3h,
       CASE WHEN count(mm_1h) OVER (PARTITION BY cell ORDER BY hour_end_utc ROWS BETWEEN 5 PRECEDING AND CURRENT ROW) < 6 THEN NULL
            ELSE sum(mm_1h)  OVER (PARTITION BY cell ORDER BY hour_end_utc ROWS BETWEEN 5 PRECEDING AND CURRENT ROW) END AS mm_6h,
       sum(mm_1h)   OVER (PARTITION BY cell ORDER BY hour_end_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS mm_24h,
       count(mm_1h) OVER (PARTITION BY cell ORDER BY hour_end_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS n_hours_24h,
       t2m_c
FROM dense
WHERE hour_end_utc >= :month_start;
```

Notes: `precip_hourly` gains `t2m_k FLOAT32` (AORC `TMP_2maboveground`, Kelvin as
stored) for src=aorc, NULL for src=mrms - the only change to 09's Pixel table
besides the two clarifications above. Window specs are written inline because
Spark 3.5's grammar does not accept `OVER (w ROWS ...)` on a named window (DuckDB
does). `sum(FLOAT)` promotes to DOUBLE on both engines, so 24-term sums never
accumulate in float32. Engine choice is 07's.

## 6. Tests (one runnable check per slice)

1. `cell_pixel`: sum(weight) = 1 +/- 1e-9 per (grid_id, cell), both grids; and
   anti-join `cell_pixel` against the stored `precip_hourly` footprint = 0 rows.
2. Density and uniqueness per built partition: `count(*) = |cells| x hours_in_month`
   and `count(*) = count(DISTINCT (cell, hour_end_utc))`; at the first Hour of any
   month after the first, `n_hours_24h = 24` wherever the previous month's source
   hours are complete.
3. Remap: for every Cell-hour, min(Pixel mm) <= mm_1h <= max(Pixel mm) over its
   Pixels; a constant field (all footprint Pixels 1.0) through the real crosswalk
   yields exactly 1.0 per Cell.
4. Ida fixture, hour ending 2021-09-02T02:00Z, src=aorc: Central Park's Cell
   `882a100895fffff` mm_1h = 84.28 +/- 0.05; bbox mean of mm_1h over the 4,113
   Cells = 49.14 +/- 0.05; mm_24h at that Cell equals an independent xarray
   `rolling(time=24).sum()` on the Bronze Zarr slice (float32 tolerance).
5. Hour: `ceil_hour('2021-09-02T02:00:00.000000Z') = 02:00`,
   `ceil_hour('...T02:00:00.000001Z') = 03:00`.
6. MRMS ingest (deterministic): the file stamped H produces rows with hour_end_utc
   = H; negatives -> NULL rows; Central Park lands at (i 5603, j 2078); the flipped
   footprint matches `grids`. The lag-0 correlation script is kept as evidence
   (network-dependent), not as a build check.
7. Events coverage: anti-join distinct `events.cell` against `ref/cells` = 0 rows
   (a stop outside the 4,113 Cells would silently drop out of every contrast).
8. Read discipline: any consumer query pinning one src sees exactly one row per
   (cell, hour_end_utc) - the uniqueness check in 2 restricted to the pinned src.

## 7. Handed on / fog

- 07: engine for the SQL above; the live Cell-grain table (RadarOnly :00 stamps as
  `mm_1h`; `mm_60min`/`window_end_utc` only as a distinct feature), append-only
  `valid_ts=` partitions, its retention and refresh cadence; how often the
  src=mrms batch job runs in live mode.
- 10: the dry/wet/frozen/onset defaults above feed the baseline; storm windows for
  the Ida / 2023-09-29 composites are (t0, t1) parameters over `mm_1h`, not
  features; Product 3 (`RS_Values` on the two storm days) also reports the
  Cell-mean vs stop-Pixel slope difference (section 1); the coarsened-rain
  robustness rerun gates any hotspot claim.
- Fog: sub-hourly live features; API for the flood map; live-era precip-type
  source before winter 2026-27; AORC 2026 re-keying and the real overlap year.
