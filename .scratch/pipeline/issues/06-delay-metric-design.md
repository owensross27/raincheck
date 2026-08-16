# 06 Delay metric design

Type: grilling
Status: resolved
Blocked by: 01

## Question

Define "late" precisely. delay_seconds = TU arrival.time minus scheduled arrival from
the static GTFS in effect on that service date (settled). Open: which arrival.time
snapshot counts (last prediction before actual arrival vs prediction at fixed horizon,
prediction churn is itself signal); how actual arrival is inferred from VP stop_id
transitions vs trusting TU; headway-based lateness for high-frequency routes where
schedule adherence is meaningless (bunching); and the service-date boundary (MTA
service days run past midnight, trips reference the prior service date via the
EN_/EX_ trip_id prefix conventions). Ross picks the metric family, evidence from a
week of archived data.

## Answer

Resolved 2026-08-16 by grilling; evidence measured on the 2026-08-15 archive
(5.9 h Sat, VP 30 s / TU 120 s), the current static GTFS, and one nycbuspositions
day (2021-09-01), then hardened by two adversarial reviews (transit lens, data lens)
before the round. All four decisions accepted as recommended. Full numbers and the
script: [research/06-delay-metric-evidence.md](../../../research/06-delay-metric-evidence.md).

**Q1 Arrival truth = VP passage.** VP `stop_id` is the NEXT stop (measured: 94.9%
of pings sit between the previous static stop and it; the flip happens a median 71 m
before and 54 m past the stop). Per (vehicle_id, trip_id, start_date), keep the
monotone envelope of static stop_sequence; each forward advance is a **passage** of
the previous envelope stop: `pass_lo_ts` / `pass_hi_ts` bracket it, `arrival_ts` is
the midpoint, `censor_halfwidth_s` = half the ping gap (15 s live, ~60 s in the
2017-2024 archive). Ping identity for dedupe is (vehicle_id, ts, stop_id, lat, lon);
when the feed republishes a moved vehicle under a frozen `ts`, `fetched_at` is the
time axis. Multi-stop advances interpolate the skipped stops by cumulative shape
distance, flagged `interpolated` / `interp_k`. `is_first` (the flip is pull-out, not
arrival) and `is_last` (never yields a passage) flags. Identical on the 2017-2024
archive (which has NO stop-level TU rows) and live.

**TU is the prediction stream, never silently the arrival.** Last TU prediction
agrees with the VP passage within 60 s for 87.8% (120 s for 97.2%); it is kept as
`pred_last_ts` and used as arrival only with `arrival_src = tu_last`. Churn features
per event (`pred_first_horizon_s`, `pred_n_changes`, `pred_range_s`,
`pred_err_10min_s`), null pre-2024-09. No fixed-horizon delay: predictions 15-60 min
out are optimistic by 1-2.5 min and only 35-49% land within 2 min.

**delay_s = arrival_ts - sched_ts**, sched_ts = local noon of `start_date`
(America/New_York) minus 12 h plus stop_times.arrival seconds, from the static pick
in effect on `start_date` (`static_pick_id` on the row). Service date is always the
feed's `trip.start_date` (`trip_start_date` in the archive), never the poll clock;
the trip_id prefix is the depot code and the 6-digit token is origin time in
centiminutes, neither marks the service day. Needs a DST unit test (2024-03-10,
2024-11-03). Trips with no static match (1.6% today) keep the arrival row with null
sched and count toward coverage. `schedule_relationship` stored, CANCELED filtered.

**Q3 Thresholds at Gold: late = delay_s > 300 s, early = delay_s < -60 s** (on-time
performance convention). Silver keeps delay_s unclipped. Measured Sat: 35.7% late,
22.9% early, p50 +143 s.

**The rain response variable is local**: `segment_s` (arrival minus previous stop's
arrival on the same vehicle-trip), `sched_segment_s`, `segment_excess_s` (measured
p50 0 s, p10/p90 -55/+67 s). delay_s stays as the level; segment_excess_s is what
attaches to the stop's Cell and joins to rain. Dwell is not separable at 30 s
cadence: named limitation.

**Q2 Family cut = 10 min scheduled headway** (TCQSM; TfL 12, MTA none). Headway
columns on every event regardless: `headway_obs_s` (previous different-vehicle
arrival, same route/direction/stop), `headway_sched_s`, `wait_ok` (obs <= sched +
180 s, MTA Wait Assessment rule), `bunched` (obs < 0.5 sched). Gold EWT per (cell,
hour, route) = AWT - SWT with the renewal formula E[h^2]/2E[h] on both sides. The
`family` flag decides only which metric a Gold table headlines. Measured Sat: on
<= 10-min routes 26.6% of headways bunched, 15.1% under 2 min, wait_ok 65%; on
> 15-min routes 9.4% bunched.

**Q4 Backfill computes schedule metrics too**: dated static GTFS for 2017-2024
comes from Transitland (ticket 11); the signup and a download check are ticket 12.

**Silver event grain: one row per (start_date, trip_id, stop_sequence, vehicle_id)**
with route_id, direction_id, trip_type, stop_id, stop lon/lat + h3, arrival_ts,
pass_lo_ts, pass_hi_ts, censor_halfwidth_s, arrival_src, interpolated, interp_k,
is_first, is_last, sched_ts, static_pick_id, delay_s, segment_s, sched_segment_s,
segment_excess_s, headway_obs_s, headway_sched_s, wait_ok, bunched, family,
schedule_relationship, pred_*, n_vehicles_on_trip. Coverage columns at Gold
(`arrivals_obs / arrivals_sched`, `vp_coverage`); measured 0.774 overall, 93.5% of
scheduled trips seen, 6.8% never delivered/tracked.

**Validation targets on MTA's own denominators**: per route x month x peak/off-peak
`wait_ok` share vs `v4z4-2h6n`; mean positive delay at stops vs `8mkn-d32t`
additional_bus_stop_time by trip type. Tolerance tighter than the VP-vs-TU spread
(~2 points on late share). Speed stays with ticket 10.

Provisional: shares above come from 6 h of one Saturday; the ticket asked for a
week. Re-check the family cut and threshold shares on a weekday and across a
midnight crossing once the archiver has run a week (rules unchanged).

Consequences: CONTEXT.md gains Passage, Segment excess, Family, Headway terms and
the settled Delay definition; ADR-0001 records VP-passage-over-TU; new ticket 12
(Transitland key, HITL task); comments on 08 (join key = stop Cell + hour of
arrival_ts, response = segment_excess_s), 09 (Silver event grain fixed here),
10 (event table is the target for archive rows; speed rules still 10's).

2026-08-16, from [05 Archive continuity](05-archive-continuity.md) (field census of
the live feeds, 14:14 UTC): the TripUpdates feed populates a **trip-level
`trip_update.delay`** on every trip (2,731/2,731 nonzero; min -2,120 s, median +102 s,
max +4,263 s), plus `trip_update.timestamp` (median 15 s behind header, max 107 s) and
`trip.direction_id`. Only the stop-level `arrival.delay` is absent. `decode_tu` drops
all three today, so the 21 hours archived so far lack them; 05 is deciding whether the
decoder becomes census-complete. Semantics of trip-level delay (vs schedule? at which
stop?) are yours to place. VP census confirms no `current_status`,
`current_stop_sequence`, or `congestion_level` on any entity.
