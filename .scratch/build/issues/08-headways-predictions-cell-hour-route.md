# 08 — Headways, Family, Predictions and Gold cell_hour_route

**What to build:** Silver `events` gains the headway and prediction columns and Gold gains `cell_hour_route`,
so a live-era month yields late/early shares, mean Segment excess, excess wait by the renewal
formula, bunching, wait_ok share and coverage per Cell-hour-route, readable in DuckDB.
Spec: F, I.

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] per event: headway_obs_s (gap to the previous different-vehicle Passage at the same route/direction/stop), headway_sched_s from the Pick, wait_ok = obs <= sched + 180 s, bunched = obs < 0.5 x sched, family = headway when the route-direction-hour's scheduled headway <= 600 s else schedule
- [ ] TU Prediction stream per event: pred_last_ts (arrival fallback only, tagged tu_last), pred_first_horizon_s, pred_n_changes, pred_range_s, pred_err_10min_s; NULL for archive-era rows
- [ ] `gold/cell_hour_route` partition month=, grain (cell, hour_end_utc, route_id, direction_id): n_events, late_share (> 300 s) and early_share (< -60 s) applied here only, mean_segment_excess_s, ewt_s = E[h^2]/2E[h] observed minus scheduled, bunched_share, wait_ok_share, coverage (arrivals_obs/arrivals_sched, vp_coverage); no precip columns
- [ ] `gold MONTH=` builds cell_hour_route beside cell_hour_speed with the same month filter and neighbour check; idempotence tests extend to the new columns and table
- [ ] the multi-vehicle trip key check: no join downstream keys on trip_id alone (a fixture with one trip served by two vehicles yields two Passage sets)
