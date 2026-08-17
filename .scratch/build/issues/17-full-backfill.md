# 17 — Full 7-year backfill (2017-07-14 to 2024-11-04)

**What to build:** The validated loader runs over all 2,278 archive files: Bronze VP, leg_hours per service day,
Gold cell_hour_speed per month, a dry baseline per year, and AORC precip tables for every
month of the span - with a runtime and disk report - so the per-Cell hotspot claims the slice
could not support become measurable. Spec: E, M step 7. Precondition: the SSD budget sized
for ~90 GB more under the archive root.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] every archive file 2017-07-14..2024-11-04 converts with 10-T1 green (the 20-column 2017-19 variant included); the five known archive gaps are logged, not errors
- [ ] `events DATE=` (Leg path) and `gold MONTH=` cover the span; `baseline WINDOW=` builds one window per year; precip-hourly/precip-cell src=aorc cover 2017-07..2024-11 including the two AORC NaN gaps recorded as NULL rows
- [ ] runtime per file and per month, and Bronze/Silver/Gold bytes, are recorded; the archiver keeps capturing throughout (budget not tripped)
- [ ] the export runs on the full span with per-Cell intervals narrowing; the page's preview sentence is revisited by the analyst, not by this ticket
