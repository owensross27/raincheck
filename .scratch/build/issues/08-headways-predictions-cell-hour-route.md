# 08 — Headways, Family, Predictions and Gold cell_hour_route

**What to build:** Silver `events` gains the headway and prediction columns and Gold gains `cell_hour_route`,
so a live-era month yields late/early shares, mean Segment excess, excess wait by the renewal
formula, bunching, wait_ok share and coverage per Cell-hour-route, readable in DuckDB.
Spec: F, I.

**Blocked by:** 07

**Status:** resolved 2026-08-22

- [x] per event: headway_obs_s (gap to the previous different-vehicle Passage at the same route/direction/stop), headway_sched_s from the Pick, wait_ok = obs <= sched + 180 s, bunched = obs < 0.5 x sched, family = headway when the route-direction-hour's scheduled headway <= 600 s else schedule
- [x] TU Prediction stream per event: pred_last_ts (arrival fallback only, tagged tu_last), pred_first_horizon_s, pred_n_changes, pred_range_s, pred_err_10min_s; NULL for archive-era rows
- [x] `gold/cell_hour_route` partition month=, grain (cell, hour_end_utc, route_id, direction_id): n_events, late_share (> 300 s) and early_share (< -60 s) applied here only, mean_segment_excess_s, ewt_s = E[h^2]/2E[h] observed minus scheduled, bunched_share, wait_ok_share, coverage (arrivals_obs/arrivals_sched, vp_coverage); no precip columns
- [x] `gold MONTH=` builds cell_hour_route beside cell_hour_speed with the same month filter and neighbour check; idempotence tests extend to the new columns and table
- [x] the multi-vehicle trip key check: no join downstream keys on trip_id alone (a fixture with one trip served by two vehicles yields two Passage sets)

---

**Implementation comment (2026-08-22).** Headways ride the events job: `sched_for` (now a
one-day view of the shared `sched_span`) computes `headway_sched_s` as the lag over
(route, direction, stop) scheduled arrivals and `family` as the median scheduled headway
of the route-direction-hour (the hour of the SCHEDULED arrival, a pure function of the
Pick) against the 600 s cut. `headway_obs_s` is a per-(route, direction-null-safe, stop)
self-join taking the max prior arrival with a DIFFERENT vehicle AND trip - 06 measured 9
excludes same-trip followers, so an OBA double-publish never reads as 0 s bunching; the
observed path carries the feed's own direction_id (review find - forcing NULL there
split live matched/unmatched rows into disjoint headway populations), archive rows stay
NULL-direction and pool by (route, stop). TU: `pred_feats` aggregates the deduped
per-fetch stream into pred_last_off_s (physical; the view exposes pred_last_ts),
first-horizon, transition count, range, and the error of the prediction in effect at
arr - 600 s; `tu_last_rows` adds the final-stop fallback arrival (arrival_src tu_last,
censor NULL) gated on the vehicle having reached the second-to-last scheduled stop with
the prediction after its last Passage - 06 measured 6's vanished-trip series yield no
row. `gold.route` (in `gold month` beside speed) rolls (cell, arrival-hour, route,
direction): EWT by the renewal formula on both sides over rows where both headways
exist, late/early cutoffs applied here only, coverage = n_events / scheduled arrivals
binned by their own scheduled hour (delayed buses shift bins; can exceed 1; NULL where
the schedule put none), vp_coverage as the arrival-quality knob.

Adversarially reviewed (4 lenses, 17 agents, 20 findings, 13 verified): fixed the
observed-path direction split (HIGH, A/B-probed on real Bronze), gold.route aborting on
a pre-08-only events tree (HIGH, reproduced with `make gold MONTH=2021-09`), slice's
existence-only resume keeping pre-08 partitions (HIGH; a partition without
headway_obs_s is now stale), the view breaking over mixed schemas (union_by_name), the
coverage baseline counting tu_last rows against a non-terminal denominator, the 50M-row
schedule fan-out per gold month (filter to built days - provably output-identical), and
the idempotence test never exercising non-NULL 08 columns. Rejected with verifier
repros: coverage hour-binning (intended, documented), tu_last in segment/gold metrics
(a Passage by 06 decision 1/2; vp_coverage is the visibility), sort-order and TU-tie
nondeterminism claims (refuted empirically), loop-trip stop_id pred keying (rare),
family's NULL-direction median (harmless), stale-empty-month partition (pre-existing
cell_hour_speed behavior).

Acceptance on the live root, all six current Picks loaded (scheme checks 0.998-1.000):
2026-08-20 events = 1,354,911 rows, 0 pick_gap, key unique; coverage baseline 0.860,
Passage-vs-Prediction agreement 0.871 (evidence: 0.878); headway_obs 98.4% populated,
wait_ok 68.2% / bunched 17.1% among both-headway rows (evidence bands 60-65% / 9-27%);
38,982 tu_last terminal rows; pred_err_10min p50 -26 s, pred_range p50 281 s (evidence
301 s); family 54% headway / 46% schedule. Ida day rebuilt to the identical 799,386
rows with headway_obs 96.7% populated and every Pick-side column NULL.
gold/cell_hour_route: 2026-08 = 129,250 rows, grain unique, mean coverage 0.895, EWT
p50 99 s, vp_coverage 0.848; 2021-09 = 86,914 rows with every sched-derived metric NULL.
Tests: 91 pass. The archiver was restarted onto post-07 code tonight (verified pid 8070,
19:30), so live Bronze now captures schedule_relationship as it arrives.
