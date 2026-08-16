# 15 Subway capture in the archiver

Type: task
Status: resolved
Blocked by: none

## Question

Ross (2026-08-16): "can we also do the MTA train stuff ... flood detection based on
train delays ... we can also kafka in the live subway stuff ... eventually it would be
cool to combine." The subway flood signal is a second map (see Out of scope on the
map), but capture is cheap and compounds, and no public subway GTFS-RT archive is
verified, so: start capturing the keyless subway feeds now inside the ticket 05
archiver. Decide feeds, cadence, decoded schema (census-complete per 05, including
the NYCT extension), Bronze budget impact, and deploy the 05 LaunchAgent (its daemon
yes was given in 05; Ross's "trust you do all of this" covers the change). Executed
in-map at Ross's request, like ticket 01.

## Answer

Resolved 2026-08-16, measured and running.

- **Feeds**: the eight keyless `api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs{,-ace,-bdfm,-g,-jz,-l,-nqrw,-si}`
  (TripUpdates + VehiclePositions in one message each) at **60 s**, and
  `camsys%2Fsubway-alerts` at 300 s; bus alerts (05 item 4) start at 300 s in the same
  daemon. Every feed deduped on `header.timestamp` (05).
- **Decoded schema** (`feeds.py`, NYCT extension vendored as `nyct_subway_pb2.py`,
  MIT descriptor from nyct-gtfs 2.1.0 rebuilt for protobuf >= 4.21; the package
  itself pins protobuf 4.25 so it is not a dependency). Census on the 1-7/S feed
  (148 trips, 2,845 stop_time_updates, 89 trains): `train_id` 100%, `is_assigned`
  68%, `direction` 49% (also the `..N/..S` in trip_id), `scheduled_track` 100%,
  `actual_track` 3% (near-term stops only), arrival 98%, departure 95%; **no**
  stop_sequence, delay, schedule_relationship or vehicle on TUs; VPs have `stop_id`
  100%, `current_stop_sequence` 100%, `timestamp` 100%, `current_status` 63%, never
  a position. `subway_tu` rows: feed, trip_id, route_id, start_date, train_id,
  direction, is_assigned, stop_id, arrival_time, departure_time, scheduled_track,
  actual_track, header_ts, fetched_at. `subway_vp`: feed, trip..., stop_id,
  current_status, current_stop_sequence, ts, fetched_at. `alerts`/`subway_alerts`:
  one row per alert x informed_entity (agency, alert_id, cause, effect, active
  start/end, header, description, agency_id, route_id, stop_id, trip_id,
  direction_id, fetched_at); subway alerts are 196 alerts -> ~2,000 rows per poll.
- **Bronze impact** (measured on one poll, Sunday-night service, upper bound):
  subway_tu ~85 MB/day, subway_vp ~16, subway_alerts ~9; bus vp ~162, tu ~252, alerts
  ~7: **~0.53 GB/day total, subway ~20% of it**; the 10 GB budget lasts ~2-3 weeks
  (weekday service will be higher), then the loud stop (below). External SSD or a
  higher `RAINCHECK_BRONZE_GB` is the follow-up.
- **Archiver** (`archiver.py`, 05 shape): `data/archive/<kind>/date=/hour=/part-MM.parquet`
  UTC 10-min windows sorted by (key, fetched_at), same-window restart appends; daily
  conditional GET of the seven static zips (six bus + subway, 05 excluded subway,
  now included) to `static/<feed>/<Last-Modified>.zip` with an ETag cache; budget
  check at every flush -> `STOPPED_BUDGET` marker + loud stderr + exit 0. The
  ticket-01 smoke files were moved into the new layout (`hour=HH.parquet` ->
  `hour=HH/part-00.parquet`, same bytes).
- **Deployed**: `launchd/com.raincheck.archiver.plist` (caffeinate -s, RunAtLoad,
  KeepAlive on crash only, ThrottleInterval 60, log `data/logs/archiver.log`),
  installed to `~/Library/LaunchAgents` and bootstrapped 2026-08-16 23:10 UTC; the
  stale ticket-01 smoke loop that had been running in a terminal since 08-15 13:00
  (undocumented) was stopped so two writers do not collide. Stop:
  `launchctl bootout gui/$(id -u)/com.raincheck.archiver`.
- **Not done here** (build items): Kafka topics for subway (07's producer is
  bus-only; add when a consumer exists), any Silver for subway, the historic subway
  RT archive question and the flood-label census (research fired 2026-08-16, assets
  `research/subway-rt-archives.md`, `research/subway-flood-labels.md` when they land).

Tests: `tests/test_feeds.py` 9/9 (subway census on a frozen 2026-08-16 fixture, alerts
flat rows, part-file roundtrip). Smoke `python -m raincheck.archiver --once` wrote all
six kinds + seven zips.

### 2026-08-16 — code review applied, daemon restarted on the fixed code

code-reviewer findings fixed before leaving it unattended: the budget-marker start
path now exits 0 (it exited 1, which `KeepAlive SuccessfulExit=false` would have
restarted into a 60 s loop forever); decode, flush, static fetch and the budget walk
are each guarded so one bad tick cannot kill the process and drop a whole window's
buffer; the daily static fetch is seeded from the ETag cache mtime (it re-ran on every
restart); the budget walk runs hourly; a stall that skips a window is logged; an
explicit column type map replaces pyarrow inference (an all-None column in a window
became a null-typed Parquet column: measured on the first two alerts parts, recast).
Log rotation is the one item left to Ross (needs root: the newsyslog one-liner is in
the plist comment). Restarted with `launchctl kickstart -k` right after the 23:30 UTC
flush; first real window measured 2.3 MB per 10 min = ~0.33 GB/day (Sunday night).
Also from the groundwork research: gtfsrt.io archives the bus feeds and all subway TU
+ alerts as keyless Parquet since 2026-03-01 (05 corrected), subwaydata.nyc holds
per-trip/per-station subway arrivals daily from 2021-04-01, and the alerts datasets
give 99 distinct post-2020 station-named subway flood events. Tests 11/11.
