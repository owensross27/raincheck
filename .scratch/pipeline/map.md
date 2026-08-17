# Wayfinder map: raincheck pipeline

Label: `wayfinder:map`

## Destination

A build-ready spec for the pipeline that answers "does rain slow the buses, and
where": MTA bus GTFS-RT into Kafka, Spark 3.5.3 + Sedona 1.9.1 enrichment (spatial
keys, computed delay), joined to NYC hourly precipitation from cloud Zarr (AORC 1 km)
plus MRMS for 2026, landing in GeoParquet, validated against a known storm, with the
7-year nycbuspositions backfill on the same schema. The map is done when nothing is
left to decide before `/to-spec` collapses it and `/to-tickets` slices the build.
Flood-exposure scoring is a later map, not this one.

## Notes

- Domain: NYC transit + weather. All feed facts pre-verified in
  `/Users/ross/vault/nyc-mta-bus-feeds-reference.md`,
  `/Users/ross/vault/nyc-bus-flood-pipeline-research-2026-08-11.md`,
  `/Users/ross/vault/nyc-flood-history-elevation-2026-08-12.md`. Consult before
  re-deriving anything about MTA feeds, NYC datasets, or datums.
- Plan, don't do. Ticket 01 was executed in-map on 2026-08-15 at Ross's explicit
  request ("start executing on it safely in test env"); its measurements unblocked
  04/06/08 and the code stays. From here the map holds decisions only; build work
  goes through `/to-spec` -> `/to-tickets` -> `/implement` in separate sessions.
  Safety boundary for anything downstream: local-only, no cloud writes, no daemons
  without a HITL yes.
  Second exception, ticket 15 (2026-08-16, "trust you do all of this"): the 05
  archiver now runs as the LaunchAgent `com.raincheck.archiver` capturing bus VP/TU/
  alerts, the eight subway feeds + subway alerts, and the seven static zips daily
  into `data/archive/` (10 GB loud stop). It is the only capture process; stop with
  `launchctl bootout gui/$(id -u)/com.raincheck.archiver`.
- Settled facts (not tickets, sourced from the vault docs above): bus feeds are
  keyless at `gtfsrt.prod.obanyc.com`; delay is computed vs dated static GTFS
  (0/37,697 arrivals carry `delay`; trip-level `trip_update.delay` is populated,
  semantics per 06); `occupancy_status` covers 41% of vehicles,
  skewed to empty; `s3.amazonaws.com/nycbuspositions` is readable 2017-07-14 to
  2024-11-04 (UTC-day files; corrected 2026-08-16 by 10, was 2024-09-06) and gtfsrt.io holds keyless Parquet of bus VP/TU/alerts and all subway TU
  + alerts from 2026-03-01 (gap 2024-11-05..2026-02-28; corrected 2026-08-16); AORC
  and ERA5 ARCO Zarr are live and anonymous.
- Reuse from `~/quakestream` (same stack, proven): Kafka 3.9 KRaft, Spark 3.5.3,
  Sedona 1.9.1, geotools-wrapper `1.9.1-33.5` (NOT -33.1), slim Sedona Dockerfile at
  `~/quakestream/stack/docker/sedona.Dockerfile`.
- Ponytail rules apply: stdlib first, fewest files, one runnable check per slice.
- Raster playbook (2026-08-15): `research/raster-playbook.md`, also in the vault. Read
  before ticket 10; its Build-first section maps onto 09 and 10. Two of its rules
  were overturned by 08 with evidence: MRMS is not regridded onto AORC (the
  crosswalk is the conservative remap), and the MRMS hour-ending item is closed by
  measurement, not `wgrib2` (the header is PDT 0 "instant"). See ADR-0002.
- Spec published 2026-08-17: `.scratch/pipeline/spec.md` (`ready-for-agent`), collapsed
  from tickets 01-15 by `/to-spec`; only ticket 13 (HITL grant) remains open and its
  outcome toggles one build step (archive-era Picks). Build tickets published 2026-08-17
  by `/to-tickets`: 17 tracer bullets under `.scratch/build/issues/` (spec symlinked at
  `.scratch/build/spec.md`); frontier = 01. Next: `/implement` per ticket in fresh
  sessions.
- Reality check 2026-08-15: `reality-check-2026-08-15.md`. Stream for capture and
  live enrichment, batch for the insight; the backfill route is decided before the
  streaming route. Session research spend to date ~$235; build phase is cheaper.

## Decisions so far

- [14 Serving surface for the two showcase artifacts](issues/14-serving-surface.md) — resolved 2026-08-17: one static page (MapLibre 5.9.0 UMD vendored by `make vendor`, no build step) with the insight and engineering views as two panels, reading plain GeoJSON/JSON under `web/files/` that DuckDB exports (`make export` = `web/export.sql`; `make live-export` = a 30 s foreground loop) and stdlib `python -m http.server` serves (`make web`); the writer is pure SQL JSON with `json_merge_patch` so unpublishable values are absent keys (the GDAL writer emits nulls and breaks MapLibre's grey guard); Cell geometry joined at export from `ref/cells` (DuckDB `h3` is a test oracle via `ST_Equals`); live view = wall-clock 10-min window over `data/live/vp` + `tu` (date/hour literal pruning, latest per key, precip already on the VP row from `with_live_precip`), atomic swap, `meta.json` with ages/error/`stream_progress` (a per-micro-batch `_progress.json` from `foreachBatch`, 07 build item), STALE styling at `vp_age_s > 120`, `SOURCE=bronze` fallback labelled (20-min window, two-step Stop-row TU reduction, no enrichment); the live view claims only what exists (vehicles, Cells at >= 1 mm RadarOnly, next-stop prediction); "MTA-reported trip delay > 5 min" (never "late") is a gated upgrade on 05's decoder; insight contract = per-Cell wide props with 95% intervals clustered by wet event and an interval-width gate on both the window layers and the storm-hour composites, `headline.json` with a literal space-mean estimand per number, `n_cells_hidden`, a numeric chord band rendered as a range (2023's reaches ~1.0), `W_ratio_ex_preschool`, precip src in every legend, the "per-Cell colour is a preview; hotspot claims wait for the backfill" sentence, headline = citywide + median Cell + rain-lag curve; taxi zones are the ground, no basemap (Protomaps NYC extract 112 MB, optional); not built: public hosting, DuckDB-WASM, PMTiles, deck.gl, local API, notebook deliverable. Measured: footprint hex GeoJSON 599 KB / 96 KB gz (full property set 2.1-2.5 MB), live read 0.06-0.25 s, duckdb-wasm 8 MB gz, http.server has no Range. Hands 09/10 `dist_m_sum_dry`/`dt_s_sum_dry` on the baseline table. Asset `research/14-serving-surface.md`, prototype with real numbers `research/14-serving-prototype/`.
- [10 Backfill slice and speed-derivation rules](issues/10-backfill-slice-and-speed-rules.md) — resolved 2026-08-16: slice = two contiguous windows, service days 2021-08-16..10-15 (Ida, picks C1/D1) and 2023-09-01..10-31 (the 09-29 flood, the archive's wettest month; C3/D3), 124 UTC-day xz files, no separate control months, windows baselined and fitted separately, errors clustered by wet event; Speed = pick-free chord speed on Legs (consecutive Pings per vehicle, same trip, 0 < dt <= 300 s, <= 30 m/s, only stationary legs at run ends dropped - R2, rule-neutral across the storm contrast), Cell of the midpoint, `ceil_hour(t_mid)`, space-mean per Cell-hour; measured Ida hours 03Z/04Z at 0.77/0.73 of the week before and 0.89 six hours after the rain, 2023-09-29 at 0.90 for eight hours; a chord ratio overstates a slowdown by an unmeasured 0-10 points (headline carries a band; along-shape distance is the pick-gated upgrade); landing = xz -> Bronze VP in 05's schema (`fetched_at` NULL, `ts` partitions), `events DATE=` unchanged (pick_gap rows) plus `enrich.legs()` into Silver `leg_hours` -> Gold `cell_hour_speed` (direction-free), baseline per window with a `mm_6h < 0.5` recovery guard; tests T1-T7 (Ida reproduction <= 0.85 vs the window's dry same-hour-of-week median, MTA benchmarks report-only). Precondition: the external SSD (05's 10 GB Bronze stop trips ~9 days into the conversion). Archive corrected: runs to 2024-11-04, UTC-day files, vehicle-clock timestamps, zero duplicates. Asset `research/10-backfill-slice-and-speed.md`, evidence `research/10-backfill-evidence.md`.
- [15 Subway capture in the archiver](issues/15-subway-capture.md) — resolved 2026-08-16 (executed in-map): eight keyless subway feeds at 60 s (TU + VP, NYCT extension vendored: train_id 100%, scheduled_track 100%, actual_track near-term only, VPs carry stop_id + current_stop_sequence and never a position) plus subway alerts and bus alerts at 300 s, all in the 05 archiver deployed as `com.raincheck.archiver` (10-min sorted parts, header.timestamp dedupe, seven static zips daily incl. subway, 10 GB loud stop); measured ~0.53 GB/day total of which subway ~20%; Kafka topics for subway and any subway Silver stay build items; the subway flood signal itself is a second map (Out of scope).
- [07 Enrichment execution model](issues/07-enrichment-execution-model.md) — resolved 2026-08-16: Spark 3.5.3 + Sedona 1.9.1 run natively from the repo venv on the brew `openjdk@17` already installed (Spark 3.5 supports Java 17; 03 corrected), one `session()` factory (3 g, `local[6]`, UTC, `partitionOverwriteMode=dynamic`), Kafka the only container, quakestream's slim image = promotion path; one `enrich.py` of pure DataFrame functions called by batch `make` targets (idempotent by dynamic partition overwrite) and by the streaming job's `foreachBatch` (stateless subset only; passages/delay batch-only), Sedona only where a spatial primitive is needed, Spark writes every derived table (destination + Sedona proof), DuckDB reads; streaming = one app, two Kafka queries appending `coalesce(1)` micro-batches to `data/live/<topic>/date=/hour=` with 48 h retention, no exactly-once (latest-per-key reads), `failOnDataLoss=false`, `maxOffsetsPerTrigger=250000`, on demand not a daemon; live precip via a 300 s `StartInterval` LaunchAgent (`precip_live`, RadarOnly `:00` -> `live/precip_cell/valid_ts=` string key, 7 d), Pass2 daily into a decoded MRMS Bronze copy + month rebuild, `make daily` builds every missing day (launchd coalesces) with a 06:00 America/New_York calendar agent as a build item; both agents and the Docker VM -> 4 GB approved. Asset `research/07-execution-model.md`.
- [08 Weather join design](issues/08-weather-join-design.md) — resolved 2026-08-16: precip attaches at Cell-hour grain via `silver/precip_cell_hourly (src, cell, hour_end_utc)`, batch per (src, month) on a dense spine, joined at read with `src` pinned (no precip columns on `events` or Gold; `RS_Values` off the feature path, run once on the two storm days as the aggregation check); `src=aorc` for the whole backfill, `src=mrms` = Pass2 from 2026-08-14 through a second `cell_pixel` set, never regridded onto AORC and never pooled with it (MRMS proven hour-ending by lag-0 r 0.97-0.999; the header cannot show it); `hour_end_utc = ceil_hour(arrival_ts)`; stored `mm_1h/1h_prev/3h/6h/24h`, `n_hours_24h`, `t2m_c` (rain not snow), models use disjoint lags and the leakage-free headline; wet/dry/frozen/onset are Gold parameters with a sweep; footprint = the crosswalk's Pixels (closes a 09 hole); ADR-0002; four glossary terms. Spec `research/08-weather-join-features.md`, evidence `research/08-weather-join-evidence.md`.
- [09 Storage and CRS conventions](issues/09-storage-crs-conventions.md) — resolved 2026-08-16: Silver `events` is batch-rebuilt plain Parquet per closed `service_date`, sorted (cell, arrival_ts), one absolute timestamp per row (~30 B/row; 7-year backfill ~56 GB on the external SSD, 10's slice ~2.6 GB); GeoParquet 1.1 (SRID 4326, crs omitted) only on geometry tables; precip at native Pixel grain per `src` with `ref/grids` frozen from AORC's real coordinate arrays and an area-weighted `cell_pixel` (nearest-Pixel refuted: largest Pixel covers p50 53% of a Cell); schedule tables per `pick_id` = zip sha1; EPSG:4326 canonical, 2263 layers transformed once with a Times Square axis test, geodesic-only distances, TIMESTAMP_MICROS UTC; Iceberg deferred. Schemas: `research/09-storage-schemas.md`.
- [12 Transitland key and dated-pick download check](issues/12-transitland-historical-picks.md) — resolved 2026-08-16: free key in gitignored `.env` (`TRANSITLAND_API_KEY`) lists all 93 Brooklyn versions in one call (67 in the backfill window, 10k REST/month); resolver keyed by `sha1`, corrected 2026-08-16 by the 13 sweep to v2: the trip_id pick code (`C1` = 2021Jul, letter A/B/C/D + year digit = the MTA bundle) selects the zip, greatest `fetched_at` < D+1 among versions carrying that code (the fetched_at-only rule chose the early-published 2021Sep `c244b822` for the Ida day; the C1 zip is `4b8dec91`); historic download is 401 on Free and Pro, so the bytes need the free Hobbyist/Academic grant (500 downloads, 423 in-window versions), split out as ticket 13; trip_id scheme unchanged 2021 -> 2026 (service segment carries optional `-SDon`/`-BM` modifiers).
- [05 Archive continuity](issues/05-archive-continuity.md) — resolved 2026-08-16: live capture is opportunistic (backfill holds the evidence), LaunchAgent + `caffeinate -s` with no power-setting changes (explicit yes), VP 30s deduped on header.timestamp / TU 120s / alerts 300s / static GTFS daily conditional GET; no raw pb, decoder census-complete with a census test (feed populates trip-level `trip_update.delay`, handed to 06); Bronze Hive UTC 10-min sorted part files, never auto-deleted, 10 GB budget with loud stop until an external SSD; always-on box and object storage stay in the fog.
- [06 Delay metric design](issues/06-delay-metric-design.md) — resolved 2026-08-16: arrival truth is the VP passage (stop_id is the next stop, measured; flip midpoint, envelope on stop_sequence, keyed by vehicle), TU is the prediction stream with churn features and a flagged fallback; delay_s vs the dated static pick using the feed's start_date and the noon-minus-12h rule; late > 300 s / early < -60 s at Gold; segment_excess_s is the local rain response variable; headway columns everywhere, family flag at 10-min scheduled headway headlines EWT/bunching; backfill computes schedule metrics from Transitland picks; Silver event grain (start_date, trip_id, stop_sequence, vehicle_id) fixed. Evidence in `research/06-delay-metric-evidence.md`.
- [11 Historical static GTFS for the backfill window](issues/11-historical-static-gtfs.md) — resolved 2026-08-16: Transitland v2 holds dated versions of all six MTA bus feeds from 2016-02 (Brooklyn: 93 versions), API key needed (download tier corrected by 12); Mobility Database is current-only. Corrected by the 13 sweep: Wayback holds 9-12 captures per feed 2020-2024 (25 byte-identical to Transitland versions, mostly 2021; ~35 unverified), Transitland calendars leave a 2019 hole (313 d Bronx/Queens/busco, 83 d Brooklyn/Manhattan/SI), data.ny.gov "MTA Bus Schedules" 2021+ has timepoint schedules with times stripped; nothing else public holds the bytes (`research/13-historic-gtfs-sources.md`). Schedule delay in the backfill is a choice, not a wall.
- [04 Topic schema and spatial keys](issues/04-topic-schema-spatial-keys.md) — resolved 2026-08-15: decoded JSON only on the wire (zstd), TU stays per-stop flat rows, keys vehicle_id/trip_id with 6 partitions fixed at creation, delete retention 48h no compaction, H3 res 8 canonical, taxi zones a Gold-time overlay, no alerts topic yet; raw-pb preservation and alerts cadence handed to ticket 05.
- [03 Zarr to Spark/Sedona bridge](issues/03-zarr-spark-sedona-bridge.md) — resolved 2026-08-15: Sedona reads no Zarr; bridge is xarray .sel() -> DataFrame (NYC fits in one AORC chunk); stream-static join, static side uncached; Havasu/Raster Inference are WherobotsDB-only; Java 11 not 17, and no JVM on this Mac yet.
- [02 Precipitation store selection](issues/02-precip-store-selection.md) — resolved 2026-08-15: AORC for 2020-2025 history (~366 GETs / ~25 MB for all of NYC, but frozen at 2025), MRMS GRIB2 for 2026 + nowcast (2-min cadence), ERA5 ruled out for point work (~95 GB per point series).
- [01 Scaffold + smoke slice](issues/01-scaffold-smoke-slice.md) — resolved 2026-08-15: all rails proven; vp=1,822/tu=59,900 round-trip offsets exact; AORC Ida peak 84.2 mm/h vs ~80 mm gauge; pytest 7/7. Kafka left running (48h retention).


## Not yet specified

- After 10: a per-Leg Silver table if a leg-grain analysis or second consumer appears
  (the Cell-hour `leg_hours` rows are the sufficient statistic today); along-shape
  path distance for Speed once Picks are loaded (`ST_LineLocatePoint` on the trip's
  shape, replaces the chord and its 0-10 point ratio bias, fixes the level gap to MTA's
  shape-distance speeds); r(v) measured on weekday live captures with a jitter guard so
  the chord band narrows; the full 2,278-file backfill's runtime and the 2017-19
  20-column variant; `RAINCHECK_ARCHIVE_ROOT` and the SSD move (with 05's box/object
  storage line below).
- Live-era precipitation extras (after 08): a phase source for `src=mrms` Cell-hours
  (MRMS `PrecipFlag` at Cell grain vs a city-wide ASOS temperature) so `t2m_c` is
  not NULL before winter 2026-27; sub-hourly features from the 2-min/15-min MRMS
  products for the live table only (`mm_60min`/`window_end_utc`, a distinct
  feature); the AORC-vs-MRMS overlap comparison and the 2026 src re-key once
  `2026.zarr` lands (~2027).
- Occupancy analytics: bimodal occupancy at a stop as a bunching signature (the bunched flag itself is defined by 06; the occupancy side is still fog).
- Backfill semantics: joining pre-archive dates (bus segment speeds monthly datasets)
  against AORC hourly history.
- Promotion beyond laptop: EKS pattern exists in quakestream; out of the fog only if
  the local pipeline earns it. Includes an always-on capture box (Oracle Always-Free
  ARM / Hetzner / Pi) plus object storage for Bronze — the only route to 2026 storm
  continuity, since the Mac sleeps on lid close (05); needs the cloud-writes yes. The
  daemonized streaming job and the slim Sedona image (07) live there too; single-poller
  process topology (archiver publishing to Kafka) is spec's, not fog.
- Kafka output topic (`raincheck.bus.enriched`): one `writeStream.format("kafka")` line
  when a consumer exists (07); nothing consumes it today.
- Grant-free schedule source for 2021+: data.ny.gov "MTA Bus Schedules: <year>" is the
  per-date timepoint schedule stamped with the MTA bundle, but `schedule_time` is
  published date-only; if MTA fixes it (opendata@mtahq.org), it is a no-grant path at
  timepoint grain with no trip_id (rebuild the key from service_id, block, origin
  time). Also the ~35 unverified Wayback captures 2020/2022-2024 (`research/13-historic-gtfs-sources.md`).

## Out of scope

- **The flood map (second effort; Ross 2026-08-16: "isn't the goal to map past flood
  events, then use weather to detect specific areas and stations that could flood").**
  Destination draft: (1) a mapped history of NYC flood events at point/segment/station
  grain from the ranked sources in `~/vault/nyc-flood-history-elevation-2026-08-12.md`
  (NFIP claims, 311 unioned 2010-2026, USGS high-water marks, MTA flood alerts — 99
  distinct station-named subway events post-2020 per `research/subway-flood-labels.md`
  — CO-OPS exceedances, Sandy zone, FloodNet 2020+); (2) an exposure/likelihood score
  per subway entrance / station, bus stop and street segment from precipitation
  (AORC history and MRMS nowcast on the same Cell-hour spine as this map, 08),
  elevation (DoITT DEM, LiDAR stairwell class), tide/surge (Battery), DEP stormwater
  categories, distance to CSO; (3) a real-time detector that flags areas and stations
  under an active rain event (MRMS + FloodNet + NWS + CO-OPS), with bus slowdowns
  (this map) and train delays (ticket 15 capture, subwaydata.nyc history) as impact
  signals, not the detector. Out of this map because it needs its own labels, its own
  units and its own validation; it reuses this map's rails wholesale (Kafka capture,
  precip spine, Cell grain, Silver conventions) and combines with the bus Gold at
  Cell-hour. Chart it with `/wayfinder` (chart mode) once this map reaches spec, or in
  parallel now that its groundwork research exists (`research/subway-rt-archives.md`,
  `research/subway-flood-labels.md`, the two vault docs).
- Alerting channels of any kind (standing rule from quakestream).
- Production deployment, public hosting of MTA-derived feeds (WMATA-style license
  issues do not apply to MTA, but re-serving raw feeds is not the goal).
- SIRI endpoints (keyed, add nothing).
- Scraping amNY/Brooklyn Paper/Gothamist (ToS prohibit; GDELT/Common Crawl instead).
