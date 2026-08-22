# 11 — MRMS: the live precip table and the src=mrms batch tables

**What to build:** A small periodic job maintains `live/precip_cell` from MRMS RadarOnly at :00 stamps under its
own 300 s LaunchAgent, and the batch precip jobs gain the mrms path (Pass2 into a decoded
Bronze copy, then month rebuilds), so the live era has both the fast uncalibrated Hour for the
stream and gauge-corrected Cell-hours for analysis - never pooled with AORC. Spec: H, K;
ADR-0002; Testing 08-T6, 07-4.

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] `raincheck.precip_live` fetches the latest RadarOnly_QPE_01H :00 file, decodes CONUS once, computes the Cell mean through cell_pixel grid_id=mrms (numpy), stores negatives as NULL, appends `live/precip_cell/valid_ts=<YYYY-MM-DDTHH>/part-<fetched_at>.parquet`, drops valid_ts dirs older than 7 days, and exits within seconds; `make precip-live` runs one tick
- [ ] its LaunchAgent plist (StartInterval 300 s) is installed and a real tick is verified; the archiver loop and the stream never fetch precip
- [ ] `precip-hourly SRC=mrms` lands each new Pass2 hour into the decoded Bronze copy `precip/mrms/date=/hour=HH` (footprint only, ~1.2 MB/day) from 2026-08-14T00Z and rebuilds `silver/precip_hourly src=mrms/month=` from Bronze as one file; `precip-cell SRC=mrms` builds the month; t2m NULL for mrms
- [ ] 08-T6: the file stamped H yields hour_end_utc = H (hour-ending, no shift), negatives -> NULL rows, Central Park lands at (i 5603, j 2078), the flipped footprint matches ref/grids
- [ ] 07-4: the file stamped H produces valid_ts=H as a string key; latest fetched_at wins per (cell, valid_ts) after a re-fetch; a scalar read of max(valid_ts) <= t returns the latest complete Hour

## Comments

**2026-08-22 (from ticket 04, load-bearing for the cell build):** research 08's section-5
build sketch has a WHERE-vs-window bug on BOTH engines: the final `WHERE hour_end_utc >=
:month_start` sits in the same SELECT as the window functions, and SQL evaluates WHERE
before windows — so the 24 h lookback rows are filtered out before lag/sum ever see them
(mm_1h_prev, mm_3h/6h/24h and n_hours_24h are all wrong at the month's start). The fix in
`raincheck/precip.py::cell_hourly` nests the window SELECT and filters outside it; reuse
that job for SRC=mrms rather than re-transcribing the sketch. Also note `precip.hourly()`
currently exits on SRC=mrms (this ticket replaces that branch), and 04's tests pin the
guarded-vs-evidence "bbox mean" distinction (49.14 is the evidence script's NaN-as-zero
convention; the guarded table reads 51.18 over 3,945 non-null cells).
