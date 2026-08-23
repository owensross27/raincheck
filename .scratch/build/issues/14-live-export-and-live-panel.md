# 14 — Live export and the live panel: the fleet now, honestly stale

**What to build:** `make live-export` keeps `live.geojson` and `meta.json` fresh every 30 s from the live tables
(wall-clock window, atomic swaps, error field, stream progress copied in) and the page's live
panel shows the fleet, the rain Cells, the next-stop Predictions and the stream's own batch
progress - and turns STALE when the pipeline stops writing. `SOURCE=bronze` gives a labelled
demo fallback. Spec: L (live view); Testing 14-3, 14-4.

**Blocked by:** 12, 13

**Status:** ready-for-agent

- [ ] the loop reads live/vp with `fetched_at >= now() - 10 min` on the wall clock and `date IN (today, yesterday) AND hour IN (HH, HH-1)` literals (max probe over the same set), latest Ping per vehicle, left-joined to the latest live/tu row per (trip_id, vehicle_id); no precip join; pure-SQL JSON writer with absent keys; writes live.geojson then meta.json by atomic replace; a failed tick writes meta with error + stale and leaves live.geojson alone; Ctrl-C stops it
- [ ] meta.json carries as_of_utc, source, window_min, error, stale, vp/tu fetched_at + ages, precip_valid_ts + age, n_vehicles, n_with_prediction, n_with_trip_delay, n_in_rain_cells, stream_progress from the progress file, export_s
- [ ] `SOURCE=bronze`: reads the archive VP/TU with a 20-min window, reduces Stop-row TU in two steps (latest fetch per (trip, vehicle), then that fetch's earliest arrival), no cell/mm_1h/trip_delay_s, excludes fetched_at IS NULL rows, prints source: bronze on the page
- [ ] the live panel re-fetches meta then setData every 30 s only when error is null; STALE styling (dimmed dots, titled) at vp_age_s > 120 live / > 900 bronze, on stale/error, or missing meta; prints vehicles in the last 10 min, Cells at >= 1 mm RadarOnly with valid ts and age, Predictions count, stream batch/rows/age, source; "MTA-reported trip delay > 5 min" (never "late") shown as a gated state until trip_delay_s is present; the rain legend reads "rain: MRMS RadarOnly QPE 01H, uncalibrated, hour-ending, valid <ts>"
- [ ] 14-3 fixture (three Snapshots of one vehicle, one TU fetch with >= 3 stop rows whose earliest arrival is not the first row plus an older fetch, one precip Hour on the VP row): newest Ping wins, Prediction from the newest fetch's earliest arrival, mm_1h from the row, ages from the fixture clock, an old row excluded by the wall-clock window, deleting the live root between two ticks leaves the loop alive with meta.error set, SOURCE=bronze semantics; 14-4 extends to live.geojson and meta.json with error null after a healthy tick

## Handoff from ticket 12 (2026-08-23, recorded by the overview session)

Two design calls 12 had to make that this ticket consumes:
1. live/tu columns: next_stop_id / next_stop_sequence / next_arrival_time, plus
   trip_delay_s, trip_ts, header_ts, fetched_at, trip_id, vehicle_id, route_id,
   start_date, direction_id. Grain (trip_id, vehicle_id, fetched_at) unique.
2. "next-stop Prediction = earliest FUTURE arrival" is measured against the feed's own
   snapshot clock (header_ts, fallback fetched_at), NOT wall clock — wall clock makes
   post-sleep replays judge old messages against today and NULLs every Prediction
   (measured: the 08-11 fixture scores zero-but-green that way). Keep this rule when
   exporting; do not "simplify" to now().
Live VP rows carry mm_1h + precip_valid_ts already joined (from live/precip_cell), so
the export reads them off the row, no join needed.

## Test-side warning from ticket 12's review (2026-08-23, recorded by the orchestrator)

Any test asserting clock-derived behaviour on a decoded .pb fixture is suspect by
construction: decode_vp/decode_tu stamp fetched_at at decode time, so the fixture's
clock IS the wall clock and the assertion cannot tell them apart. This ticket's
wall-clock window and vp_age_s/precip_age_s assertions are squarely that shape (two of
ticket 12's six review findings were). Cheap check: mutate the production line to the
wall-clock version and confirm the test goes red; pin clock-derived assertions on a
hand-built row at a fixed epoch far from now (see memory fixture-clock-equals-wall-clock
and the 12-streaming-job review record).
