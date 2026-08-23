# 14 — Live export and the live panel: the fleet now, honestly stale

**What to build:** `make live-export` keeps `live.geojson` and `meta.json` fresh every 30 s from the live tables
(wall-clock window, atomic swaps, error field, stream progress copied in) and the page's live
panel shows the fleet, the rain Cells, the next-stop Predictions and the stream's own batch
progress - and turns STALE when the pipeline stops writing. `SOURCE=bronze` gives a labelled
demo fallback. Spec: L (live view); Testing 14-3, 14-4.

**Blocked by:** 12, 13

**Status:** in-progress (branch `claude/kind-dijkstra-a7c03f`)

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

## Contract notes from ticket 13 (2026-08-23, recorded by the orchestrator)

1. The page's live panel is already stubbed by ticket 13: #live / #livemeta / #delaystate /
   #rainstate / #livetoggle exist, plus an empty `live` GeoJSON source + circle layer that
   fetches nothing. Wire into those, don't rebuild.
2. MapLibre 5.9.0 SILENTLY drops a GeoJSON source whose promoteId resolves to a
   non-integer-like string — zero features, no error event. The Cell id is a hex string,
   so the cells source carries no promoteId; do not add one to the live source either
   unless vehicle_id is integer-like.
3. The tab must be visible for MapLibre to finish loading (rAF throttled when hidden) —
   headless screenshot checks are misleading.

## Build notes (2026-08-23, ticket 14 session)

**Base.** Branched off master (dc025d0) with 13's `8d3a45b` cherry-picked on top, NOT off
13's branch alone: `claude/determined-driscoll-e43969` forks from a pre-ticket-12 master
and does not contain `src/raincheck/stream.py`, which is the live/vp + live/tu contract
this ticket consumes. Only conflict was the Makefile, resolved as both-sides-additive.
Orchestrator approved the deviation. One rebase still owed when 13 formally lands.

**Shipped.** `src/raincheck/live_export.py` (`make live-export [SOURCE=bronze] [ONCE=1]`),
the live panel in `web/app.js` + `web/index.html` + `web/app.css`, `tests/test_live.py`
(19 tests). The SQL stays in the module rather than a `web/*.sql` twin of the insight
export: every tick's text is parameterised by the wall clock, so there is no
standalone-runnable script for a notebook to import and no second file to keep honest.

**Three rules, each pinned by a mutation check** (the ticket's warning taken literally —
every fixture row is hand-built at a fixed epoch `T` = 2026-03-01T12:00:00Z with `now`
injected as `T + 60 s`, so `now` and `max(fetched_at)` are different numbers and no
assertion can be green because the fixture clock is the wall clock):

| mutation applied to the production line | test that goes red |
|---|---|
| recency filter `now - 10 min` -> `max(fetched_at) - 10 min` | `test_the_newest_ping_wins`, `test_a_row_outside_the_wall_clock_window_is_excluded` |
| Prediction clock `coalesce(header_ts, fetched_at)` -> `now()` | both `..._prediction_...` tests (180 s honest vs 60 s wall-clock) |
| `max(fetched_at)` probe over the windowed rows instead of the pruned set | `test_every_age_is_the_wall_clock_...`, `test_a_dead_stream_still_reports_how_old_it_is` |
| bronze two-step TU reduce collapsed to one pooled `min()` | `test_bronze_reduces_stop_row_tu_in_two_steps` |
| bronze future filter (`arrival_time >= snap`) dropped | same |

Vehicle V2's only Ping sits at `T - 570`: inside `max(fetched_at) - 600`, outside
`now - 600`. That one row is what makes the wall-clock rule falsifiable, and it doubles as
the proof that Bronze really uses a 20-minute window (20 min reaches it, 10 does not).

**The probe subtlety.** `max(fetched_at)` runs over the pruned `date=`/`hour=` partitions
*without* the recency filter. Taken over the result set instead, a stream that died half an
hour ago returns zero rows, `vp_age_s` comes back NULL, and the panel has no age to go
STALE on — an empty map and a shrug. `test_a_dead_stream_still_reports_how_old_it_is`
pins it: 30 minutes after the last write, `n_vehicles == 0` and `vp_age_s == 1800`.

**Bug found by actually opening the page** (not by any test): clicking `#livetoggle`
before MapLibre finishes loading makes `setPaintProperty` / `getSource` throw, the tick
dies silently, and the panel sits on its "off" text under a *ticked* box — a live-looking
control over a dead panel, which is the exact failure this panel exists to prevent. The
box now ships `disabled` and app.js enables it on `load`. Not on `styledata`: that fires
while `isStyleLoaded()` is still false and `setPaintProperty` still throws "Style is not
done loading" (measured). Confirmed in a real tab that `document.visibilityState` goes
`hidden` between automated calls and MapLibre stalls until a screenshot forces a paint —
ticket 13's warning is exactly right, and it is why the JS side is covered by text
assertions plus hand verification rather than by a headless check.

**Verified in a visible tab, all five panel states:** off (nothing fetched), fresh
(`1 vehicle in the last 10 min, 1 in Cells at >= 1 mm RadarOnly, 1 with a next-stop
Prediction. Feed 60 s ago. Stream batch 7, 1234 rows, 60 s ago. source: live.`),
STALE by age (`vp_age_s` 4200 -> amber header, dimmed dots `#5d666f` @ 0.35), STALE by
missing meta.json, and STALE by `error` — the last one with a 3-feature decoy
`live.geojson` on disk that the page correctly refused to load, proving `setData` really
is gated on `error === null`.

**Not built / deferred.** No JS test runner (spec L: no npm, no build step), so the panel's
rendering is covered by text assertions on the wiring plus the hand check above; a broken
rule is caught by a human, a deleted one by the tests. `meta.stale` means "this tick
failed" only — the age thresholds (120 s live / 900 s Bronze) live on the panel, which is
where spec L puts them.
