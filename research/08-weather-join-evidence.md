# 08 Weather join: evidence

Measured 2026-08-16 for ticket [08 Weather join design](../.scratch/pipeline/issues/08-weather-join-design.md);
the decisions are in [08-weather-join-features.md](08-weather-join-features.md).
Anonymous public-bucket reads only. Scripts: [08-mrms-hour-ending-check.py](08-mrms-hour-ending-check.py),
[08-cell-pixel-compare.py](08-cell-pixel-compare.py) (run with `uv run --no-project
--with ...`, commands in their docstrings; the GRIB header dump used a throwaway
eccodes script whose output is summarized below).

## 1. MRMS GRIB2 forensics (`s3://noaa-mrms-pds/CONUS/`)

**Products and cadence (2023-09-29):** `MultiSensor_QPE_01H_Pass2_00.00` 24 files,
hourly at `:00:00`, 0.31-0.55 MB gz; `..._Pass1_00.00` 24 files, hourly, 0.36-0.62 MB;
`RadarOnly_QPE_01H_00.00` 719 files, every 2 min (`20230929-102400` missing), each a
rolling 60-min total ending at its own stamp. All products listed 2020-10-14 (from
20:00Z) through today.

**Header keys (file `20230929-140000`, all three products):** `dataDate=20230929
dataTime=1400 validityTime=1400 stepType=instant stepRange=0m forecastTime=0
productDefinitionTemplateNumber=0` (instantaneous, no PDT-8 time-range keys:
`typeOfStatisticalProcessing`, `lengthOfTimeRange`, `*OfEndOfOverallTimeInterval`
all absent); `shortName/name/units=unknown` (discipline 209 local table;
parameterCategory/Number Pass2 6/37, Pass1 6/30, RadarOnly 6/2); `missingValue=9999`
(never present in data). **The accumulation window is not decodable from the
header**; the playbook's `wgrib2 -v` check would also have shown "instant".

**Grid (identical for all three):** `gridType=regular_ll Ni=7000 Nj=3500`, first
point lon 230.005 (0-360; = -129.995), lat 54.995; last point lon 299.995 (=
-60.005), lat 20.005; `iDirectionIncrement=jDirectionIncrement=0.01`;
`jScansPositively=0` (row 0 = north); Pixel-centre registration (fractional offset
exactly 0.5). NYC bbox (-74.30..-73.65, 40.45..40.95) = source i 5569..5635, rows
1404..1454 = 67 x 51 = 3,417 Pixels; Central Park (40.782, -73.965) = i 5603, row
1421 (flipped j = 2078).

**Sentinels (full CONUS, 24.5M cells, the 14:00 files):** Pass1/Pass2: no negative
values; RadarOnly: 9,864,194 cells = -3 (~40% of CONUS), 0 cells = -1, none inside
the NYC bbox. -3 = no radar coverage is an inference (RadarOnly-only, absent from
the gauge-blended products); -1 was never observed, so the -1/-3 split is
UNVERIFIED. The decision (any negative -> null) does not depend on it.

**Hour-ending, empirically:** Central Park series, MRMS stamp matched 1:1 to
AORC's hour-ending label.

| window | AORC total | Pass2 total (ratio) | RadarOnly total (ratio) | r at lag -1 / 0 / +1 h, Pass2 | RadarOnly |
|---|---|---|---|---|---|
| 2023-09-29 00:00-23:00Z (24 h) | 134.7 mm | 124.5 (0.924) | 79.0 (0.587) | 0.779 / **0.971** / 0.524 | 0.824 / **0.943** / 0.508 |
| 2021-09-01 12:00 - 09-02 12:00Z (25 h) | 184.2 mm | 158.3 (0.859) | 188.4 (1.023) | 0.480 / **0.999** / 0.458 | 0.519 / **0.998** / 0.463 |

No file gaps in either series. Peak hour ending 2021-09-02T02:00Z: AORC 84.2 /
Pass2 75.0 / RadarOnly 85.9 mm. Lag 0 wins on both days and both products: **the
MRMS stamp is the end of the accumulation hour, same convention as AORC.** The
Pass2/AORC ratio is 0.86-0.92; RadarOnly's flips sign between events.

**Latency (single observation, 2026-08-16T19:32:51Z):** Pass2 latest stamp 18:00Z
(1 h 33 min behind), Pass1 19:00Z (33 min), RadarOnly 19:28Z (5 min). NOAA WDTD
(vlab.noaa.gov/web/wdtd/-/multi-sensor-qpe): Pass1 20 min latency / ~10% of
gauges; Pass2 60 min / ~60% of gauges.

## 2. Cell grain vs single Pixel (AORC)

**AORC grid, read from the store's coordinate arrays (2021.zarr):** latitude
[20.0, 20.008333, ...] and longitude [-130.0, -129.991667, ...], step 0.008333
uniform, 4201 x 8401, longitude already -180..180, no bounds variable (centre
registration). Chunks (144, 128, 256).

**Crosswalk (EPSG:32618 areas, bbox padded one Pixel):** 4,113 H3 res-8 Cells,
19,512 rows, 4.744 Pixels per Cell, largest single-Pixel share p10/p50/p90 =
0.377/0.530/0.725, zero Cells >= 0.9, |sum(weight) - 1| < 1e-9 for all 4,113.
Footprint of referenced Pixels: 4,868 distinct, i 6684..6763 x j 2454..2515 (80 x
62 slots), i.e. one Pixel beyond 09's 78 x 60 = 4,680 sizing: 300 rows / 153 Cells
carry weight on Pixels outside that slice, lost weight p50 0.205, p90 0.696, max
0.926 (reviewer probe). Hence the spec's "footprint = the crosswalk's Pixel set".

**Values, Cells with A >= 1 mm** (A = area-weighted mean, B = centroid Pixel,
C = largest-share Pixel; B and C nearly identical):

| hour | bbox mean | p50 rel | p90 rel | max rel | p50 abs | p90 abs | max abs | share > 10% | share > 25% |
|---|---|---|---|---|---|---|---|---|---|
| Ida, hour ending 2021-09-02T01:00Z | 35.7 mm | 0.0105 | 0.037 | 0.67 | 0.26 mm | 1.14 | 3.27 | 0.25% | 0.08% |
| Ida max, hour ending 2021-09-02T02:00Z | 51.1 mm | 0.0078 | 0.031 | 0.72 | 0.35 | 1.10 | 3.37 | 0.30% | 0.13% |
| 2023-09-29 max, hour ending 13:00Z | 12.6 mm | 0.0130 | 0.040 | 0.72 | 0.12 | 0.56 | 3.07 | 0.35% | 0.13% |

Central Park's Cell `882a100895fffff` on the Ida max hour: Pixels 84.4 / 87.1 /
84.2 / 83.4 mm, weights 0.173 / 0.024 / 0.772 / 0.031, area-weighted mean **84.28
mm** (nearest Pixel 84.20); Cell-mean of the bbox that hour 49.14 mm (raw Pixel
bbox mean 51.11). A mass check over mismatched footprints was attempted and is not
meaningful (a spatially biased interior-Pixel subset vs the full hex tiling); the
per-Cell weight-sum assertion is the conservation test.

**Wet-hour census, 2021, NYC bbox (60 x 78 Pixels x 8,760 h, 24.5 s to load):**
bbox max >= 0.1 mm in 21.1% of hours (1,847), >= 1 mm 11.3% (988), >= 12.7 mm 1.4%
(119); bbox mean >= 1 mm in 351 h; per-Pixel median wet fraction (>= 0.1 mm) 10.2%.
Reviewer probes at one NYC Pixel / the bbox: >= 1.0 mm in 3.65% of Pixel-hours;
with the defaults dry 87.6% / wet 3.65% / neither 8.73%; of dry-rule hours only
0.38% had >= 1 mm in the previous 3 h (3.59% within 6 h); corr(mm_1h, mm_1h_prev)
0.477 on non-dry hours (n = 948); nested-window VIFs mm_1h 2.9, mm_1h_prev 4.4,
mm_3h 12.5, mm_6h 4.9, mm_24h 2.1; adjacent-Pixel r 0.996-0.998 (decimation to
~1.9 km reconstructs wet Pixels within 3.5%, ~4.6 km within 11.8%).

**Phase (AORC `TMP_2maboveground`, 2021 bbox):** of Pixel-hours >= 1.0 mm, 7.0% at
T <= 0 C, 11.0% at <= 2 C, 13.7% at <= 4 C; 4.3% / 7.2% of annual depth at <= 0 /
<= 2 C. Bbox-mean view: of 351 wet bbox-hours (mean >= 1 mm), 30 (8.5%) at bbox-mean
T <= 1 C carrying 50 of 1,116 mm. AORC data_vars: APCP_surface, DLWRF_surface,
DSWRF_surface, PRES_surface, SPFH_2maboveground, TMP_2maboveground,
UGRD_10maboveground, VGRD_10maboveground.

**Epoch:** 2024.zarr 2024-01-01T00:00 .. 2024-12-31T23:00 (8,784 rows); 2025.zarr
2025-01-01T00:00 .. 2025-12-31T23:00 (8,760); `2026.zarr` absent (`.zmetadata` and
prefix); bucket lists 1979.zarr .. 2025.zarr and index.html.

## 3. Documents (primary reads; UNVERIFIED items named)

- AORC v1.1 (registry.opendata.aws/noaa-nws-aorc, direct read): CONUS precip from
  Stage IV + NLDAS; "one-hour Accumulated Surface Precipitation (APCP) ending at
  the top of each hour"; production "runs with a 10-day lag"; update frequency
  "To be determined". Stage IV's historical link to MRMS QPE (2013-14) is from a
  search summary of the AORC v1.1 documentation PDF, unverified.
- MRMS (vlab.noaa.gov/web/wdtd/-/multi-sensor-qpe, direct read): Pass1 "less
  latency, but less gauges" (20 min, ~10%), Pass2 "more latency, but more gauges"
  (60 min, ~60%); v11 -> v12 on 2020-10-14 (registry.opendata.aws/noaa-mrms-pds).
  The NSSL GRIB2 tables page (grid spec, valid-time wording, -1/-3 semantics) was
  unreachable (TLS error) - those facts come from the files themselves above.
- Lag literature: nothing read end to end; one connected-vehicle study (MDPI
  vehicles 5(1):9) reports ~17 min from first rain to speed impact within a 1 h
  window (snippet only). Springer 2024 bus-delay paper: "an additional millimeter
  of precipitation during the peak period ... approximately 8 seconds" (snippet).
- Spark 3.5: `RANGE BETWEEN INTERVAL ... PRECEDING` on a timestamp ORDER BY is
  documented in general terms; a named window cannot take a frame in `OVER (w ROWS
  ...)` (grammar `windowSpec` at tag v3.5.3, reviewer read). DuckDB documents both.

## 4. Adversarial reviews (two opus lenses, 2026-08-16)

Reversed from the first draft: (1) the any-null guard must be on realized weight
(`sum(weight) FILTER (WHERE mm IS NOT NULL) < 1 - 1e-6`), since an INNER join drops
absent Pixel-hours before a null count can see them (DuckDB probe: a Cell with one
of three Pixels present reported 2.0 mm from a 4.0 mm Pixel); (2) stored footprint
= the crosswalk's Pixel set, not the bbox (153 rim Cells otherwise deflated
forever); (3) RadarOnly's off-:00 files are rolling windows, not Hours; (4) no
precip columns on Gold (join at read, src pinned) - one reviewer disagreed, the
fewer-copies argument won; (5) `OVER (w ROWS ...)` is a Spark parse error; (6)
precipitation phase was missing (`t2m_c` added); (7) nested windows are collinear
regressors (disjoint lags at read); (8) `src` as a regression term is collinear
with era (srcs never pooled); (9) mm_3h/mm_6h need the same poison rule as the
Cell-hour. Gaps filled: spine definition and month-by-label partitioning, store-
null-never-drop, density test, 09's exact `grids` columns and an MRMS
`coord_sha256` definition, src=mrms ingest from 2026-08-14 not 2026-01-01, append-
only live table, onset/sustained contrast, effective-resolution caveat, glossary
terms and ADR-0002. Confirmed against direct attack: hour-ending, area-weighted
mean as the conservative remap, no regridding, dense spine over sparse+RANGE, Pass2,
negatives -> null, the two-condition dry rule, sibling table over view, no
sub-hourly, per-(src, month) idempotence with no cross-partition dependency, no
lookback off-by-one, FLOAT32 storage (sums promote to DOUBLE).
