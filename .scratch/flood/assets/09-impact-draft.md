# Draft — 09 Impact signals: bus slowdowns and subway delays

Status: DRAFT for adversarial review, 2026-08-22. Numbers measured today.

## Measured today

- **subwaydata.nyc CSVs verified end-to-end**: two day-files fetched
  (2023-09-29 storm 0.99 MB, 2023-09-22 baseline Friday 1.39 MB — the
  storm file is smaller because service collapsed). Schema: `stop_times`
  (trip_uid, stop_id platform-suffixed GTFS id, track, arrival_time /
  departure_time as unix epoch, last_observed, marked_past) + `trips`
  (trip_uid, trip_id, route_id, direction_id, start_time, vehicle_id,
  ...). Joins to the stations table by stripping the N/S suffix ->
  gtfs_stop_id -> complex_id. Citywide 2023-09-29: 163,339 stop_time rows
  vs 239,921 baseline (-32%), 6,814 trips vs 8,894 (-23%).
- **The arrivals-ratio metric discriminates**: per-complex arrivals
  (storm/baseline, 445 complexes with >=20 baseline arrivals) — citywide
  median 0.692, p10 0.505. The 02-extractor's flagged stations for
  2023-09-29 land in the deep tail: Newkirk Plaza 0.395 (p5), Botanic
  Garden/Franklin Av 0.492 (p8), Canal St (325) 0.497 (p8). The ten
  deepest drops independently rediscover the reported flooded corridor —
  the entire Nostrand Av 2/5 line (President St, Sterling St, Winthrop
  St, Church Av, Flatbush Av, Newkirk Av 0.38x) plus the Franklin Av
  shuttle (Park Pl 0.245, Prospect Park 0.361, Botanic Garden) — with no
  flood data as input.
- **Bus tables need nothing new**: `gold/cell_hour_speed` (cell,
  hour_end_utc, route_id grain; dist_m_sum/dt_s_sum) +
  `gold/cell_hourofweek_baseline` (speed_dry) exist for 2021-08..10 and
  2023-09..10 — the two reference storms are fully covered.
- **Coverage boundaries** (from research/subway-rt-archives.md, verified
  2026-08-16): subwaydata.nyc = 2021-04-01..present (~1 MB/day CSV,
  keyless, hash-suffixed 302 URLs, no constructible raw-tarball URL, data
  license NOT FOUND — local use only, no rehosting); ticket-15 TU capture
  = 2026-08-16+; pre-2021-04 events have NO subway RT source (kenyoneda
  archive 500s on most dates).

## Proposal

**Role (binding, restated).** Impact signals VALIDATE and DISPLAY — they
are never detector inputs and never model features (destination + 01).
They answer: "when the labels/score said flooding, did transit actually
degrade there?"

**Subway metric: `service_ratio` at complex-hour grain.**
`arrivals(complex, hour)` / `baseline_median(complex, hour_of_week)`,
baseline = median over the K=4 prior same-weekdays excluding union-event
days (mirrors the bus `cell_hourofweek_baseline` convention). Arrival =
stop_times row with non-null coalesce(arrival_time, departure_time),
platform stripped to parent, joined to complex. One metric only for v1 —
headway/gap statistics (max gap per route-direction) are the recorded
upgrade, not built (the ratio already separates flagged stations at
p5-p8, measured above). Timestamps stay unix-UTC; rows carry
hour_end_utc + service_date; the day-file service-day span is verified at
build (files appear to run ~04:00-04:00 local).

**Bus metric: reuse `cell_hour_speed` verbatim.** Impact ratio =
(sum dist_m_sum / sum dt_s_sum over routes per cell-hour) / speed_dry
from the existing baseline. No new bus tables, no re-decisions —
pipeline-06/10 own the semantics.

**Storage.**
- `silver/impact_subway_hourly` (src, service_date, complex_id,
  hour_end_utc, arrivals, baseline_med, service_ratio) — plain Parquet,
  partitioned by src (src=subwaydata | src=capture, NEVER pooled —
  mirrors pipeline-08's src discipline; capture rows computed from
  ticket-15 TU stop-time events with the same definitions).
- Event-impact validation views = **build assets, not Gold** (08's
  precedent): per event x flagged/labeled unit — service_ratio and bus
  speed ratio during the window vs the citywide same-window distribution
  (the probe's analysis, systematized): median ratio at labeled units,
  citywide median, percentile rank of each labeled unit. Impact never
  joins the score fit.

**Backfill scope: event-scoped, a build item.** Union-spine events with
first_day >= 2021-04-01, fetch day files for window days + K=4 baseline
same-weekdays each (deduped, event days excluded from baselines) —
estimated ~250-350 day-files, ~400 MB, snapshot to
`data/archive/subway/subwaydata/date=YYYY-MM-DD/` fetch-only-when-missing
(the hash suffix comes from the 302 redirect; store the resolved URL in a
manifest). NOT the full 1,963-day mirror (disk: ~2.5 GB against ~9 GB
free; YAGNI). Pre-2021-04 events: subway impact honestly ABSENT (stated
in every validation table); bus impact limited to months where
cell_hour_speed exists — extending bus coverage rides the pipeline
backfill decision (ticket 17, other map), not this ticket.

**Live counterpart (for 10).** The detector's display panel computes the
SAME service_ratio from the ticket-15 TU capture (src=capture) and the
live bus pipeline's speed tables, with the same baseline convention
(baselines for src=capture accumulate as capture days accrue; until
K=4 same-weekdays exist per complex, the ratio is NULL — never a
cross-src baseline). Display only; staleness and thresholds are 10's.

**Circularity guard.** Alert-derived labels come from alert TEXT; the
subway impact metric is realized arrivals. A suspended-service alert can
name a station AND zero its arrivals — the validation tables therefore
report impact for 311/FloodNet-labeled units separately from alert-labeled
units, so "alerts predict the delays the same alerts announced" cannot
masquerade as validation.

## Decision points for the numbered round

1. Subway metric = service_ratio (arrivals vs K=4 same-weekday median),
   complex-hour grain; headway/gap = recorded upgrade only.
2. Bus = existing cell_hour_speed / speed_dry, no new tables.
3. Storage: silver/impact_subway_hourly with src partition discipline;
   validation views as build assets.
4. Backfill = event-scoped (~250-350 files), not the full mirror;
   pre-2021-04 subway absence stated; bus extension deferred to
   pipeline ticket 17.
5. Live = same metric from ticket-15 capture (src=capture, own
   baselines), display-only for 10.
6. Circularity guard: alert-labeled vs non-alert-labeled impact reported
   separately.
