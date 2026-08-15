# Wayfinder map: raincheck pipeline

Label: `wayfinder:map`

## Destination

A running local test-env pipeline that answers "does rain slow the buses, and where":
MTA bus GTFS-RT streaming into Kafka, a Spark 3.5.3 + Sedona 1.9.1 job enriching
positions with spatial keys and computed delay, joined against NYC hourly precipitation
read from cloud Zarr (AORC 1km), landing in Parquet with a validation check against a
known storm. The flood-exposure score rides these same rails as a later phase.

## Notes

- Domain: NYC transit + weather. All feed facts pre-verified in
  `/Users/ross/vault/nyc-mta-bus-feeds-reference.md`,
  `/Users/ross/vault/nyc-bus-flood-pipeline-research-2026-08-11.md`,
  `/Users/ross/vault/nyc-flood-history-elevation-2026-08-12.md`. Consult before
  re-deriving anything about MTA feeds, NYC datasets, or datums.
- Execution override: this effort carries execution on the map. Task tickets build
  the test env directly; safety boundary is local-only (Docker Compose, no cloud
  writes, no daemons installed without a HITL yes).
- Reuse from `~/quakestream` (same stack, proven): Kafka 3.9 KRaft, Spark 3.5.3,
  Sedona 1.9.1, geotools-wrapper `1.9.1-33.5` (NOT -33.1), slim Sedona Dockerfile at
  `~/quakestream/stack/docker/sedona.Dockerfile`.
- Ponytail rules apply: stdlib first, fewest files, one runnable check per slice.
- Reality check 2026-08-15: `reality-check-2026-08-15.md`. Stream for capture and
  live enrichment, batch for the insight; backfill (ticket 10) builds before the
  streaming job (07). Session research spend to date ~$235; build phase is cheaper.

## Decisions so far

- [Bus feed endpoints] — keyless `gtfsrt.prod.obanyc.com/{vehiclePositions,tripUpdates,alerts}`; SIRI not needed. Detail: `/Users/ross/vault/nyc-mta-bus-feeds-reference.md`.
- [Delay is computed, not published] — 0/37,697 arrival events carry `delay`; compute vs dated static GTFS (`rrgtfsfeeds.s3.amazonaws.com/gtfs_{bx,b,m,q,si,busco}.zip`, archive per service date).
- [Occupancy is partial] — `occupancy_status` on 41% of vehicles, skewed to empty; rates must be over reporting vehicles only.
- [History must be self-captured] — no live archive exists since 2024-09-06; every day unpolled is unrecoverable.
- [Climate Zarr stores verified live] — AORC `s3://noaa-nws-aorc-v1-1-1km/{year}.zarr` (1km hourly, APCP_surface, anon) and ERA5 ARCO `gs://gcp-public-data-arco-era5` both listable 2026-08-15.
- [nycbuspositions backfill is readable] — the dead archive serves 2017-07-14 to 2024-09 daily CSV.xz (~20 MB/day) with positions + occupancy; 7 years of history x AORC 2017-2024 means the rain-vs-speed answer needs no waiting. Ticket 10.
- [Storage direction] — GeoParquet 1.1 with Sedona auto bbox covering, EPSG:4326 canonical, one-time ST_Transform of EPSG:2263 city layers, joins on precomputed (h3, hour); Iceberg deferred. Ticket 09 to confirm.
- [03 Zarr to Spark/Sedona bridge](issues/03-zarr-spark-sedona-bridge.md) — resolved 2026-08-15: Sedona reads no Zarr; bridge is xarray .sel() -> DataFrame (NYC fits in one AORC chunk); stream-static join, static side uncached; Havasu/Raster Inference are WherobotsDB-only; Java 11 not 17, and no JVM on this Mac yet.
- [02 Precipitation store selection](issues/02-precip-store-selection.md) — resolved 2026-08-15: AORC for 2020-2025 history (~366 GETs / ~25 MB for all of NYC, but frozen at 2025), MRMS GRIB2 for 2026 + nowcast (2-min cadence), ERA5 ruled out for point work (~95 GB per point series).
- [01 Scaffold + smoke slice](issues/01-scaffold-smoke-slice.md) — resolved 2026-08-15: all rails proven; vp=1,822/tu=59,900 round-trip offsets exact; AORC Ida peak 84.2 mm/h vs ~80 mm gauge; pytest 7/7. Kafka left running (48h retention).


## Not yet specified

- Flood phase: per-entrance exposure score joined to the same precip spine (elevation
  via `elevation.its.ny.gov` getSamples, labels from NFIP/311/alerts). Sharpens after
  the bus slice proves the rails.
- Occupancy/bunching analytics: bimodal occupancy as bunching signature.
- Serving/visualization: map dashboard, H3 lateness heatmap. After enrich job exists.
- Backfill semantics: joining pre-archive dates (bus segment speeds monthly datasets)
  against AORC hourly history.
- Promotion beyond laptop: EKS pattern exists in quakestream; out of the fog only if
  the local pipeline earns it.

## Out of scope

- Alerting channels of any kind (standing rule from quakestream).
- Production deployment, public hosting of MTA-derived feeds (WMATA-style license
  issues do not apply to MTA, but re-serving raw feeds is not the goal).
- SIRI endpoints (keyed, add nothing).
- Scraping amNY/Brooklyn Paper/Gothamist (ToS prohibit; GDELT/Common Crawl instead).
