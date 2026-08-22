# 05 — Legs and Speed: enrich.legs under R2, leg_hours, cell_hour_speed, the dry baseline

**What to build:** From Bronze VP for a service day, `make events DATE=` derives Legs under rule set R2 and
writes Silver `leg_hours` (Cell-hour sums); `make gold MONTH=` rolls them into Gold
`cell_hour_speed`; `make baseline WINDOW=` builds the per-window dry hour-of-week Speed
baseline with mergeable sums and the recovery-guarded dry mask. A converted archive day flows
end to end into a Gold month readable in DuckDB. This ticket also creates the `events DATE=`
job skeleton and the `make gates` skeleton (tier-2 runner) that later tickets extend.
Spec: G, I; Testing 07-2, 10-T7 and the R2 rule tests.

**Blocked by:** 02, 04

**Status:** resolved

- [x] `enrich.legs()` is a pure DataFrame function implementing R2 exactly: one Ping per (vehicle_id, ts) keeping the earliest fetched_at, same non-null trip_id, 0 < dt_s <= 300, <= 30 m/s, gaps-and-islands runs, only stationary (< 25 m) run-end Legs dropped with counts carried, geodesic distance, Cell of the midpoint, Hour = ceil_hour(t0 + dt/2), route_class by the permanent pick-free rule
- [x] `silver/leg_hours` partition service_date=, grain (cell, hour_end_utc, route_id, route_class) unique, columns n_legs, n_vehicles, dist_m_sum, dt_s_sum, leg_speed_p50, n_dropped_terminal, n_dropped_dark; the job reads Bronze date IN (D, D+1) and keeps Legs whose start Ping has start_date = D
- [x] `gold/cell_hour_speed` partition month=, grain (cell, hour_end_utc, route_id, route_class), sums only, built from service_date in [month_start-1, month_end] keeping the month's Hours; dynamic overwrite touches only that month (neighbour check)
- [x] `gold/cell_hourofweek_baseline` partition window=, grain (cell, hour_of_week in America/New_York, DST transition hours dropped): speed_dry, n_dry, n_legs_dry, dist_m_sum_dry, dt_s_sum_dry over Cell-hours that are dry by mm_1h < 0.1, mm_1h_prev < 0.1, mm_6h < 0.5 (swept), joined from precip_cell_hourly src=aorc
- [x] 07-2 / 10-T7: `events DATE=` twice yields the same rows and key set for leg_hours; a stray staging dir changes no read; `gold MONTH=` leaves the neighbouring month untouched; unit tests pin each R2 rule on a small fixture (a trip-change pair, a dark gap, a stationary pre-departure Leg, a teleport)
- [x] `make gates` exists as the tier-2 runner (10-T3, 10-T6 wired; report-only slots for 10-T4, 10-T5) and prints a clear "slice not loaded" when Gold is empty

## Comments

**2026-08-22 (implemented).** `src/raincheck/enrich.py` (`legs`, `route_class`: R2 as a
pure DataFrame function - dedup keeping earliest `fetched_at`, gaps-and-islands runs on
(trip_id, start_date), dark/teleport gates, stationary run-end drop with counts carried,
`ST_DistanceSpheroid`, midpoint Cell via `ST_H3CellIDs`, `ceil_hour` midpoint Hour),
`src/raincheck/events.py` (`make events DATE=`: D..D+1 Bronze read, start_date = D
filter, leg_hours single sorted part via .staging move), `src/raincheck/gold.py`
(`make gold MONTH=`: sums-only rollup, service_date in [month_start-1, month_end], the
month's Hours only, dynamic partition overwrite; `make baseline WINDOW=`: dry mask
mm_1h < 0.1 AND mm_1h_prev < 0.1 AND mm_6h < 0.5 joined from precip_cell_hourly
src=aorc, America/New_York hour_of_week with the DST transition hours dropped, mergeable
dist/dt sums), `src/raincheck/gates.py` (`make gates`: 10-T3 and 10-T6 wired over
DuckDB, report-only slots for 10-T4/10-T5, "slice not loaded" guard). Tests
`tests/test_events.py` (12): each R2 rule pinned on a small fixture (trip-change pair,
dark gap, stationary pre-departure/post-arrival/never-flips vs stationary mid-trip kept
and moving terminal kept, teleport, dedup, route_class), 07-2/10-T7 (events twice ->
same rows and key set, stray staging dir changes no read, gold rebuild leaves the
neighbour month byte-identical), baseline dry mask + recovery guard + hour_of_week 71
pin. Full suite 66 passed.

Notes for ticket 06: T3's control-week dryness and T6's AORC-NULL check read
`silver/precip_cell_hourly src=aorc`, so the slice months must be built (ticket 04)
before `make gates`. The baseline's DST drop is dormant for W1/W2 (both windows end
before the November transitions) - it becomes live with later-years windows; no fixture
can reach it through the real windows, so it is reasoning-verified only.
