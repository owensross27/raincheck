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
- Settled facts (not tickets, sourced from the vault docs above): bus feeds are
  keyless at `gtfsrt.prod.obanyc.com`; delay is computed vs dated static GTFS
  (0/37,697 arrivals carry `delay`); `occupancy_status` covers 41% of vehicles,
  skewed to empty; no public archive since 2024-09-06 but `s3.amazonaws.com/
  nycbuspositions` is readable 2017-07-14 to 2024-09; AORC and ERA5 ARCO Zarr are
  live and anonymous.
- Reuse from `~/quakestream` (same stack, proven): Kafka 3.9 KRaft, Spark 3.5.3,
  Sedona 1.9.1, geotools-wrapper `1.9.1-33.5` (NOT -33.1), slim Sedona Dockerfile at
  `~/quakestream/stack/docker/sedona.Dockerfile`.
- Ponytail rules apply: stdlib first, fewest files, one runnable check per slice.
- Raster playbook (2026-08-15): `research/raster-playbook.md`, also in the vault. Read
  before tickets 08 and 09; its Build-first section maps onto 09 and 10.
- Reality check 2026-08-15: `reality-check-2026-08-15.md`. Stream for capture and
  live enrichment, batch for the insight; the backfill route is decided before the
  streaming route. Session research spend to date ~$235; build phase is cheaper.

## Decisions so far

- [06 Delay metric design](issues/06-delay-metric-design.md) — resolved 2026-08-16: arrival truth is the VP passage (stop_id is the next stop, measured; flip midpoint, envelope on stop_sequence, keyed by vehicle), TU is the prediction stream with churn features and a flagged fallback; delay_s vs the dated static pick using the feed's start_date and the noon-minus-12h rule; late > 300 s / early < -60 s at Gold; segment_excess_s is the local rain response variable; headway columns everywhere, family flag at 10-min scheduled headway headlines EWT/bunching; backfill computes schedule metrics from Transitland picks; Silver event grain (start_date, trip_id, stop_sequence, vehicle_id) fixed. Evidence in `research/06-delay-metric-evidence.md`.
- [11 Historical static GTFS for the backfill window](issues/11-historical-static-gtfs.md) — resolved 2026-08-16: Transitland v2 holds dated versions of all six MTA bus feeds continuously from 2016-02 (Brooklyn: 93 versions), free API key needed to download; Mobility Database starts 2025-12, transitfeeds/Wayback is pre-2017 only. Schedule delay in the backfill is a choice, not a wall.
- [04 Topic schema and spatial keys](issues/04-topic-schema-spatial-keys.md) — resolved 2026-08-15: decoded JSON only on the wire (zstd), TU stays per-stop flat rows, keys vehicle_id/trip_id with 6 partitions fixed at creation, delete retention 48h no compaction, H3 res 8 canonical, taxi zones a Gold-time overlay, no alerts topic yet; raw-pb preservation and alerts cadence handed to ticket 05.
- [03 Zarr to Spark/Sedona bridge](issues/03-zarr-spark-sedona-bridge.md) — resolved 2026-08-15: Sedona reads no Zarr; bridge is xarray .sel() -> DataFrame (NYC fits in one AORC chunk); stream-static join, static side uncached; Havasu/Raster Inference are WherobotsDB-only; Java 11 not 17, and no JVM on this Mac yet.
- [02 Precipitation store selection](issues/02-precip-store-selection.md) — resolved 2026-08-15: AORC for 2020-2025 history (~366 GETs / ~25 MB for all of NYC, but frozen at 2025), MRMS GRIB2 for 2026 + nowcast (2-min cadence), ERA5 ruled out for point work (~95 GB per point series).
- [01 Scaffold + smoke slice](issues/01-scaffold-smoke-slice.md) — resolved 2026-08-15: all rails proven; vp=1,822/tu=59,900 round-trip offsets exact; AORC Ida peak 84.2 mm/h vs ~80 mm gauge; pytest 7/7. Kafka left running (48h retention).


## Not yet specified

- Flood phase: per-entrance exposure score joined to the same precip spine (elevation
  via `elevation.its.ny.gov` getSamples, labels from NFIP/311/alerts). Sharpens after
  the bus slice proves the rails.
- Occupancy analytics: bimodal occupancy at a stop as a bunching signature (the bunched flag itself is defined by 06; the occupancy side is still fog).
- Serving/visualization: map dashboard, H3 lateness heatmap. After the execution model (07) is decided.
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
