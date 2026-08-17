# 07 — Schedule tables, Passages and Delay in Silver events

**What to build:** `make schedule PICK=` loads a Pick's schedule tables, and `make events DATE=` now also
writes Passages with Delay: for a live-era captured service day joined to the current Pick,
Silver `events` holds one row per Passage with arrival, censor width, interpolation flags,
scheduled time by the DST-safe noon rule, delay_s and segment excess, with `pick_gap` rows
when no Pick covers the date. Spec: D (schedule tables), F; ADR-0001.

**Blocked by:** 02, 05

**Status:** ready-for-agent

- [ ] `schedule PICK=` writes stops (with Cell and GeoParquet point), trips (with trip_type), trip_stops (arrival/departure seconds and cumulative geodesic shape_dist_m), service_days, shapes (GeoParquet) partitioned by pick_id, from a captured static zip; the current Brooklyn zip loads and passes the trip_id scheme check
- [ ] Passages per (vehicle_id, trip_id, start_date): monotone envelope of stop_sequence, pass_lo/pass_hi/arrival midpoint, censor_width_s, multi-stop advances interpolated by shape distance with interpolated/interp_k, is_first/is_last flagged, arrival_src set; Silver `events` partition service_date=, key (start_date, trip_id, stop_sequence, vehicle_id) unique, sorted (cell, arrival_ts), one file per partition
- [ ] sched_ts = local noon of start_date in America/New_York - 12 h + the Pick's arrival seconds; unit test on 2024-03-10 and 2024-11-03 (spring-forward/fall-back) with the 2021-11-07 archive fragment as fixture; delay_s unclipped; segment_s, sched_segment_s, segment_excess_s; no static match keeps the row with sched_ts NULL; CANCELED filtered, ADDED/DUPLICATED flagged
- [ ] when no Pick covers the date the job writes pick_gap = true rows with pick_id/delay_s/sched_* NULL and logs a count instead of aborting; the events view exposes 06's names over the physical columns
- [ ] `events DATE=` twice -> identical rows and key set (leg_hours and events); anti-join of distinct events.cell against ref/cells is empty; the Passage-vs-Prediction agreement and coverage baselines are printed as regression bounds on the fixture day
