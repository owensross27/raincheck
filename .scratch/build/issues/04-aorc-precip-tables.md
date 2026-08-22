# 04 — AORC precipitation: precip_hourly and precip_cell_hourly for the slice months

**What to build:** `make precip-hourly SRC=aorc MONTH=` and `make precip-cell SRC=aorc MONTH=` produce the
Pixel-grain and Cell-grain precipitation tables for any month, reading the AORC Zarr NYC slice
(materialised into Bronze on first touch, read from Bronze thereafter), so every Cell-hour of
the slice has mm_1h, the previous hour, 3 h / 6 h / 24 h trailing sums and temperature,
joinable on (src, cell, hour_end_utc). Spec: H; Testing 08-T2..T5, T8, 07-5.

**Blocked by:** 02

**Status:** resolved

- [x] `silver/precip_hourly` src=aorc: partition month=, one file per partition, sorted (i, j, hour_end_utc), grain unique per partition (asserted), footprint = the crosswalk's 4,868 Pixels, negative sentinels stored as NULL rows, t2m_k carried; the Bronze Zarr copy exists after the first run
- [x] `silver/precip_cell_hourly` src=aorc: dense over 4,113 Cells x every hour of the month, grain unique, mm_1h NULL unless the realized non-null weight sums to 1 within 1e-6 (guarded on realized weight), mm_3h/mm_6h NULL if any frame hour is NULL, mm_24h with n_hours_24h, t2m_c; built with a 24 h lookback into precip_hourly so months build in any order; the Spark spine uses explode(sequence(...)) with inline window frames
- [x] 08-T4 / 10-T2: Central Park Cell 882a100895fffff reads 84.28 +/- 0.05 mm for the hour ending 2021-09-02T02:00Z, bbox mean 49.14 +/- 0.05, mm_24h equals an independent xarray rolling sum over the Bronze copy
- [x] 08-T3: every Cell-hour within its Pixels' min/max; a constant field yields exactly 1.0; 08-T5: ceil_hour on the hour stays, one microsecond after rolls forward; 08-T2/T8: density and uniqueness per partition, n_hours_24h = 24 at a month's first Hour
- [x] the five slice months (2021-08, 09, 10; 2023-09, 10; plus the lookback days) build for both tables; rebuilding one month leaves its neighbours byte-identical

## Comments

**2026-08-22 (implemented).** `src/raincheck/precip.py` (`bronze_aorc`, `hourly`,
`cell_hourly`; `make precip-hourly` / `precip-cell`), `src/raincheck/enrich.py`
(`ceil_hour`, 08-T5), `tests/test_precip.py` (10 tests: a synthetic three-cell crosswalk
for guard/frame/boundary logic and the committed 48-hour Ida fixture through the real
crosswalk), fixtures `aorc-ida.zarr` (705 KB), `ref-cell_pixel-aorc.parquet`,
`ref-cells-ids.parquet`. Real build: 7 hourly months (2021-07..10, 2023-08..10) in 65 s
including S3 materialisation (57 MB Bronze zarr + 14 MB hourly), 5 cell months in 99 s
(111 MB). Verified with DuckDB: every month dense and unique, n_hours_24h = 24 at every
month's first hour (the cross-month lookback works), 3,945 non-null cells at every hour,
Ida row mm_1h 84.278 / mm_24h 133.3 / t2m_c 18.35.

Corrections found by building (both test-pinned):
- **Research 08's section-5 build SQL is wrong on both engines**: the final
  `WHERE hour_end_utc >= :month_start` sits in the same SELECT as the window functions,
  and WHERE runs before windows, so the 24 h lookback never reaches the frames. Fixed by
  nesting the window SELECT and filtering outside. Correction comment left on ticket 11
  (mrms reuses the sketch).
- **08-T4's "bbox mean 49.14" is the evidence script's convention** (pandas skipna: NaN
  Pixels dropped, all-NaN water Cells counted 0.0, mean over all 4,113). The spec-guarded
  table nulls partial-weight Cells; its mean at the Ida hour is 51.18 over 3,945 non-null
  Cells — numerically identical to an independent pandas recomputation. The test asserts
  both numbers, each computed the way it was defined.
- **Byte-identity at real scale**: a rebuilt month is value-identical and byte-identical
  through the data pages; ~20 bytes wobble in the parquet thrift footer (parquet-mr set
  serialization order). Neighbours always untouched; the synthetic small-scale rebuild is
  fully byte-identical and stays pinned.
- AORC facts confirmed at source: time labels are hour-ending (00:00..23:00 per year),
  chunks (144, 128, 256), `TMP_2maboveground` Kelvin, `APCP_surface` kg/m^2 == mm; the
  footprint window is i 6684..6763, j 2454..2515 and the Bronze cut's origin is asserted
  against the crosswalk (an absolute check, not just contiguity - review round).
- Bronze is materialised per month (`archive/precip/aorc/<YYYY-MM>.zarr`, zarr v2, single
  chunk per var), deviating from 09's `<year>.zarr` phrasing: the slice needs 7 months,
  not whole years; ticket 17's backfill extends month-wise with the same code.
- Review round (sonnet): fixed a test that verified neither uniqueness nor order it named
  (dict-keyed rows collapse duplicates), made the xarray oracle read origin/step from
  ref/grids instead of re-typed literals, validated `src` at the CLI (it is interpolated
  into SQL and paths), dropped three no-op repartition(1) calls. bronze_aorc's S3 fetch
  path has no automated test (network); it ran seven times for the real build.
