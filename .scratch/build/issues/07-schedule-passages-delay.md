# 07 — Schedule tables, Passages and Delay in Silver events

**What to build:** `make schedule PICK=` loads a Pick's schedule tables, and `make events DATE=` now also
writes Passages with Delay: for a live-era captured service day joined to the current Pick,
Silver `events` holds one row per Passage with arrival, censor width, interpolation flags,
scheduled time by the DST-safe noon rule, delay_s and segment excess, with `pick_gap` rows
when no Pick covers the date. Spec: D (schedule tables), F; ADR-0001.

**Blocked by:** 02, 05

**Status:** resolved 2026-08-22

- [x] `schedule PICK=` writes stops (with Cell and GeoParquet point), trips (with trip_type), trip_stops (arrival/departure seconds and cumulative geodesic shape_dist_m), service_days, shapes (GeoParquet) partitioned by pick_id, from a captured static zip; the current Brooklyn zip loads and passes the trip_id scheme check
- [x] Passages per (vehicle_id, trip_id, start_date): monotone envelope of stop_sequence, pass_lo/pass_hi/arrival midpoint, censor_width_s, multi-stop advances interpolated by shape distance with interpolated/interp_k, is_first/is_last flagged, arrival_src set; Silver `events` partition service_date=, key (start_date, trip_id, stop_sequence, vehicle_id) unique, sorted (cell, arrival_ts), one file per partition
- [x] sched_ts = local noon of start_date in America/New_York - 12 h + the Pick's arrival seconds; unit test on 2024-03-10 and 2024-11-03 (spring-forward/fall-back) with the 2021-11-07 archive fragment as fixture; delay_s unclipped; segment_s, sched_segment_s, segment_excess_s; no static match keeps the row with sched_ts NULL; CANCELED filtered, ADDED/DUPLICATED flagged
- [x] when no Pick covers the date the job writes pick_gap = true rows with pick_id/delay_s/sched_* NULL and logs a count instead of aborting; the events view exposes 06's names over the physical columns
- [x] `events DATE=` twice -> identical rows and key set (leg_hours and events); anti-join of distinct events.cell against ref/cells is empty; the Passage-vs-Prediction agreement and coverage baselines are printed as regression bounds on the fixture day

---

**Implementation comment (2026-08-22).** `make schedule PICK=` is `src/raincheck/schedule.py`:
pyarrow parses the zip, numpy/shapely/pyproj compute cumulative geodesic `shape_dist_m`
(UTM projection onto the shape mapped back to per-vertex geodesic distance, per-trip
cummax so loop stops keep non-negative interpolation weights, unplaceable stops stay
NULL), Spark/Sedona writes the two GeoParquet tables (stops with Cell, shapes). The real
Brooklyn zip: 46,115 trips, scheme check 1.000, 1.9M trip_stops, 0 non-monotone pairs,
all six feeds' grammars verified against the live zips (busco P-form 1.000, boroughs
0.998-1.000; gate >= 0.98).

Passages are `enrich.passages_matched` (envelope of static stop_sequence; a multi-stop
advance interpolates its intermediates INSIDE the advance's own ping gap, from the anchor
midpoint toward the gap end, by shape distance with linear-in-index fallback) and
`enrich.passages_observed` (no static match: observed stop_id flips, ordinal
stop_sequence, first-occurrence-per-stop flap absorption, Cell from the flip midpoint,
is_first/is_last NULL - unknowable without a Pick; rebuilt wholesale when Picks land,
ticket 16). `events DATE=` writes both leg_hours and events; pick selection is
service_days-driven with greatest-published winning a multi-Pick trip_id; a registered
Pick covering the date but not loaded prints a loud WARNING (operator gap vs a real
archive-era pick_gap). `sched_ts` is the noon rule in `enrich.sched_ts`; the DST pair is
unit-tested on 2024-03-10/2024-11-03 and end-to-end on the real 2021-11-07 fragment
(delay_s = 208 on trip GA_D1-Sunday-039500_Q59_902 against the mini-Pick fixture).
`schedule_relationship` is now captured by `decode_vp` (verbatim; it was being dropped -
live Bronze before today has it NULL), CANCELED filtered before construction,
ADDED/DUPLICATED ride the verbatim column; `events_view.sql` exposes 06's names, with
pass_lo/hi NULL on interpolated rows (their arrival is off-centre in the crossing gap).

Slice acceptance on the live root, Ida day 2021-09-02: 799,386 rows, all pick_gap (no
2021 Pick yet), key unique, cell anti-join vs ref/cells empty, 0 sort inversions, censor
width mean 129 s, 0 negative segments, 12.1 MB. `make slice` now resumes into events
partitions (~12 MB/day estimated in its disk check). Adversarially reviewed (4 lenses,
17 findings): fixed the clamped-shape interpolation collapse, the segment-window tie
nondeterminism, the schedule_relationship capture gap, the coverage denominator
(per (trip, vehicle)), the unloaded-Pick conflation, observed-path is_first honesty,
interpolated pass_lo/hi in the view, NaN preservation in the cummax, plus dead-code
cleanups; rejected as not worth it: ref.py helper generalization, regex loosening
(measured 0.998+ vs the 0.98 gate), a shapes.txt guard, sub-second view sched_ts
(documented instead). Tests: 87 pass.
