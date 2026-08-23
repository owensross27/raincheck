# 11 — MRMS: the live precip table and the src=mrms batch tables

**What to build:** A small periodic job maintains `live/precip_cell` from MRMS RadarOnly at :00 stamps under its
own 300 s LaunchAgent, and the batch precip jobs gain the mrms path (Pass2 into a decoded
Bronze copy, then month rebuilds), so the live era has both the fast uncalibrated Hour for the
stream and gauge-corrected Cell-hours for analysis - never pooled with AORC. Spec: H, K;
ADR-0002; Testing 08-T6, 07-4.

**Blocked by:** 04

**Status:** resolved (2026-08-23) - **ticket 12 unblocked**: live/precip_cell is live and populated

- [x] `raincheck.precip_live` fetches the latest RadarOnly_QPE_01H :00 file, decodes CONUS once, computes the Cell mean through cell_pixel grid_id=mrms (numpy), stores negatives as NULL, appends `live/precip_cell/valid_ts=<YYYY-MM-DDTHH>/part-<fetched_at>.parquet`, drops valid_ts dirs older than 7 days, and exits within seconds; `make precip-live` runs one tick
- [x] its LaunchAgent plist (StartInterval 300 s) is installed and a real tick is verified; the archiver loop and the stream never fetch precip
- [x] `precip-hourly SRC=mrms` lands each new Pass2 hour into the decoded Bronze copy `precip/mrms/date=/hour=HH` (footprint only, ~1.2 MB/day) from 2026-08-14T00Z and rebuilds `silver/precip_hourly src=mrms/month=` from Bronze as one file; `precip-cell SRC=mrms` builds the month; t2m NULL for mrms
- [x] 08-T6: the file stamped H yields hour_end_utc = H (hour-ending, no shift), negatives -> NULL rows, Central Park lands at (i 5603, j 2078), the flipped footprint matches ref/grids
- [x] 07-4: the file stamped H produces valid_ts=H as a string key; latest fetched_at wins per (cell, valid_ts) after a re-fetch; a scalar read of max(valid_ts) <= t returns the latest complete Hour

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

**2026-08-22 (flood spec amendment, load-bearing for the live job):** the flood build spec
(`.scratch/flood/spec.md`, Real-time detector) AMENDS `raincheck.precip_live`: each tick
fetches EVERY missing :00 RadarOnly stamp within the source's measured ~25 h retention, not
just the latest — so laptop-sleep holes heal on wake. The flood detector's Window walk and
replay harness (flood-build tickets 11–12) depend on this catch-up; a latest-only tick
leaves permanent HOLES the panel must then display forever. Same job, one extra loop over
the missing-stamp list; the MRMS directory path is `mrms.ncep.noaa.gov/2D/...` (the old
/data/2D path 301s).

**2026-08-23 (resolution):** landed as 60cbc58 on master. `raincheck.precip_live` implements
the flood-spec catch-up amendment above: each tick fetches the latest published :00 stamp
unconditionally (re-fetch, latest-fetched_at-wins) plus every missing stamp of the trailing
25 h, so sleep holes heal. Source stays NOAA NODD S3 (noaa-mrms-pds, per spec H and
ref/grids.source_url) - NOT the note's `mrms.ncep.noaa.gov/2D/...` path: that host appears in
no committed spec, and NODD was verified serving RadarOnly stamps >= 2 days old (retention is
not a constraint on NODD; the 25 h window is the spec bound). If the flood build really wants
the ncep LDM mirror, that is its own decision to record.

Verified live: LaunchAgent com.raincheck.precip-live bootstrapped, first launchd tick healed
all 25 trailing hours (4,113 cells each, all non-null) and exited 0; `make precip-live` = one
tick. Batch: Bronze `archive/precip/mrms` holds 218 Pass2 hours from 2026-08-14T00Z (904 KB,
footprint-only, raw negatives kept); `silver/precip_hourly src=mrms/month=2026-08` = 751,882
rows (3,449 pixels x 218 hours, unique grain, t2m_k NULL); `silver/precip_cell_hourly
src=mrms/month=2026-08` dense 3,060,072 = 4,113 x 744 (ticket 04's cell_hourly reused
unchanged - the WHERE-vs-window fix carries over). Central Park storm hour 2026-08-21T00Z:
mm_1h 6.65, mm_24h 54.97, n_hours_24h 24. Tests: 9 new in tests/test_precip_live.py (08-T6
decode/flip/CP-pixel/negatives/hour-ending, 07-4 string key/latest-wins/scalar read/retention/
catch-up); fixtures = real Pass2 + RadarOnly files for 2026-08-21T00Z + the mrms crosswalk.
Full suite 144 passed pre-merge (formal /code-review skipped: session usage limit - flag if
wanted). eccodes>=2.48 is a new dependency, installed in the venv.

The stream (12) consumes: `duck.table` over `live/precip_cell` with hive_types_autocast=false
(valid_ts VARCHAR), scalar `max(valid_ts) <= t`, latest fetched_at per (cell, valid_ts).
Note for 12: do NOT bind valid_ts as a prepared parameter directly inside `read_parquet` in
DuckDB 1.5.5 - it hits an optimizer INTERNAL error; create the view first (duck.table), then
filter (the tested pattern).
