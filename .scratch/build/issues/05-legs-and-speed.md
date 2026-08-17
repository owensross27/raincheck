# 05 — Legs and Speed: enrich.legs under R2, leg_hours, cell_hour_speed, the dry baseline

**What to build:** From Bronze VP for a service day, `make events DATE=` derives Legs under rule set R2 and
writes Silver `leg_hours` (Cell-hour sums); `make gold MONTH=` rolls them into Gold
`cell_hour_speed`; `make baseline WINDOW=` builds the per-window dry hour-of-week Speed
baseline with mergeable sums and the recovery-guarded dry mask. A converted archive day flows
end to end into a Gold month readable in DuckDB. This ticket also creates the `events DATE=`
job skeleton and the `make gates` skeleton (tier-2 runner) that later tickets extend.
Spec: G, I; Testing 07-2, 10-T7 and the R2 rule tests.

**Blocked by:** 02, 04

**Status:** ready-for-agent

- [ ] `enrich.legs()` is a pure DataFrame function implementing R2 exactly: one Ping per (vehicle_id, ts) keeping the earliest fetched_at, same non-null trip_id, 0 < dt_s <= 300, <= 30 m/s, gaps-and-islands runs, only stationary (< 25 m) run-end Legs dropped with counts carried, geodesic distance, Cell of the midpoint, Hour = ceil_hour(t0 + dt/2), route_class by the permanent pick-free rule
- [ ] `silver/leg_hours` partition service_date=, grain (cell, hour_end_utc, route_id, route_class) unique, columns n_legs, n_vehicles, dist_m_sum, dt_s_sum, leg_speed_p50, n_dropped_terminal, n_dropped_dark; the job reads Bronze date IN (D, D+1) and keeps Legs whose start Ping has start_date = D
- [ ] `gold/cell_hour_speed` partition month=, grain (cell, hour_end_utc, route_id, route_class), sums only, built from service_date in [month_start-1, month_end] keeping the month's Hours; dynamic overwrite touches only that month (neighbour check)
- [ ] `gold/cell_hourofweek_baseline` partition window=, grain (cell, hour_of_week in America/New_York, DST transition hours dropped): speed_dry, n_dry, n_legs_dry, dist_m_sum_dry, dt_s_sum_dry over Cell-hours that are dry by mm_1h < 0.1, mm_1h_prev < 0.1, mm_6h < 0.5 (swept), joined from precip_cell_hourly src=aorc
- [ ] 07-2 / 10-T7: `events DATE=` twice yields the same rows and key set for leg_hours; a stray staging dir changes no read; `gold MONTH=` leaves the neighbouring month untouched; unit tests pin each R2 rule on a small fixture (a trip-change pair, a dark gap, a stationary pre-departure Leg, a teleport)
- [ ] `make gates` exists as the tier-2 runner (10-T3, 10-T6 wired; report-only slots for 10-T4, 10-T5) and prints a clear "slice not loaded" when Gold is empty
