# 16 — Archive-era Picks and schedule metrics on the slice (after the grant)

**What to build:** With the historic-download grant live, the 24 slice zips are pulled and loaded, the slice's
`events` are rebuilt with Delay and Headway, `cell_hour_route` exists for both windows, and
the MTA-denominator validation report is written. If the grant is refused this ticket closes
as the fallback (Delay live-era only; Speed and Headway carry the archive headline).
Spec: D, F, I, M step 6.

**Blocked by:** 06, 08, 09 (and ticket 13 of the wayfinder map: "13: grant approved")

**Status:** ready-for-agent

- [ ] `make picks WINDOW=` resolves and downloads C1, D1, C3, D3 for the six feeds (24 zips) with sha1 verification and Bronze landing; the one-zip proof output (size, latency, metering headers) is recorded
- [ ] `schedule PICK=` loads the four Picks x six feeds; `events DATE=` rerun over the 122 service days replaces the pick_gap rows with Delay/segment/headway columns (leg_hours unchanged; route_class unchanged); `gold MONTH=` builds cell_hour_route for the five months
- [ ] the exact trip_id match rate per resolved Pick is logged and ~98% on each storm day
- [ ] validation report: wait_ok share per route x month x peak/off-peak vs Socrata v4z4-2h6n and mean positive delay_s by trip_type vs 8mkn-d32t, printed as calibration (no gate) with the tolerance target named
- [ ] if refused: the ticket records the fallback decision and closes with the archive-era Delay columns NULL

Note from 09 (2026-08-22): per-day resolution over the real listing needs **31 zips,
not 24** (w1 = 13: busco has a mid-pick D1 revision; w2 = 18: every feed has the
D3-published-early zip plus its 09-18 revision, each in effect for part of September).
`make picks WINDOW=w1` then `WINDOW=w2` downloads all of them. The divergence this
note originally flagged (events.py's per-date supersede kept the greatest `published`
among loaded picks, applying a mid-pick revision retroactively while resolver v2 is
fetched_at <= D+1 per day) is resolved with 09's landing: `sched_span` now gates the
join on published <= D+1 (spec D, `test_sched_span_pick_gate`), so the September
revision pairs join correctly with no decision needed during the events rerun.
