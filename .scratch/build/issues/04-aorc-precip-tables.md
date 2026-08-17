# 04 — AORC precipitation: precip_hourly and precip_cell_hourly for the slice months

**What to build:** `make precip-hourly SRC=aorc MONTH=` and `make precip-cell SRC=aorc MONTH=` produce the
Pixel-grain and Cell-grain precipitation tables for any month, reading the AORC Zarr NYC slice
(materialised into Bronze on first touch, read from Bronze thereafter), so every Cell-hour of
the slice has mm_1h, the previous hour, 3 h / 6 h / 24 h trailing sums and temperature,
joinable on (src, cell, hour_end_utc). Spec: H; Testing 08-T2..T5, T8, 07-5.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] `silver/precip_hourly` src=aorc: partition month=, one file per partition, sorted (i, j, hour_end_utc), grain unique per partition (asserted), footprint = the crosswalk's 4,868 Pixels, negative sentinels stored as NULL rows, t2m_k carried; the Bronze Zarr copy exists after the first run
- [ ] `silver/precip_cell_hourly` src=aorc: dense over 4,113 Cells x every hour of the month, grain unique, mm_1h NULL unless the realized non-null weight sums to 1 within 1e-6 (guarded on realized weight), mm_3h/mm_6h NULL if any frame hour is NULL, mm_24h with n_hours_24h, t2m_c; built with a 24 h lookback into precip_hourly so months build in any order; the Spark spine uses explode(sequence(...)) with inline window frames
- [ ] 08-T4 / 10-T2: Central Park Cell 882a100895fffff reads 84.28 +/- 0.05 mm for the hour ending 2021-09-02T02:00Z, bbox mean 49.14 +/- 0.05, mm_24h equals an independent xarray rolling sum over the Bronze copy
- [ ] 08-T3: every Cell-hour within its Pixels' min/max; a constant field yields exactly 1.0; 08-T5: ceil_hour on the hour stays, one microsecond after rolls forward; 08-T2/T8: density and uniqueness per partition, n_hours_24h = 24 at a month's first Hour
- [ ] the five slice months (2021-08, 09, 10; 2023-09, 10; plus the lookback days) build for both tables; rebuilding one month leaves its neighbours byte-identical
