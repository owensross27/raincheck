# Draft: flood-event label set design (ticket 01, raincheck flood map)

Context docs (read before judging): /Users/ross/raincheck/.scratch/flood/map.md
(Notes = reused rails + measured caveats), /Users/ross/raincheck/research/
subway-flood-labels.md, flood-03-floodnet.md, flood-04-stormwater-geodata.md,
flood-05-tide-surge.md, /Users/ross/vault/nyc-flood-history-elevation-2026-08-12.md,
and the pipeline conventions gisted in /Users/ross/raincheck/.scratch/pipeline/map.md
(decisions 08 weather join, 09 storage/CRS).

Fresh measurements backing this draft (2026-08-22, SODA live):
- 311 "Street Flooding (SJ)" + "Highway Flooding (SH)" unioned 2010-2026: 50,605
  complaints over 5,462 days with >=1 (median 4/day, p99 96/day, max 912 on
  2025-10-30). Top days = known storms: 2025-10-30 (912), 2023-09-29 (634), Ida
  2021-09-01/02 (351/364), 2022-12-23 (314), 2021-10-26, 2021-08-22 (Henri).
- 311 "Sewer Backup (SA)": median 28/day chronic background; top-20 days hold
  only 5.7% of volume (vs 10.8% for street flooding); same storms top the list
  (Ida 2,372 on 09-02).
- Naive LIKE '%FLOOD%' on 311 catches ~8,700 "Flood Light Lamp ..." street-light
  rows — descriptors must be enumerated, never pattern-matched.
- MTA subway alerts post-2020: 99 distinct flood event_ids collapse to 36
  distinct first-seen days; 49 of 99 events sit on two days (Ida 29, 2023-09-29
  20). Station-grain labels are rare-event data.

## D1 Three-layer shape

- `silver/flood_obs`: union of per-source observations at native grain —
  (source, source_id, ts_utc, geo_kind [point|station|block_group|zone|polygon],
  geometry/ref, severity fields where the source has them: depth_mm FloodNet,
  waterDepth NFIP). Plain Parquet per pipeline-09 conventions, partitioned by
  source. Raw kept; no cross-source normalization of severity.
- `ref/flood_events`: the event spine — event_id, window_start/end (UTC, hour
  aligned), event_class (pluvial|coastal|mixed), per-source coverage flags.
- `gold/flood_labels`: asset x event grain, derived at build time by explicit
  per-source attachment rules; binary `flooded` + severity tier + source mix.

## D2 Event spine (resolves the "historical event spine" fog here, no new ticket)

A calendar day (America/New_York) is an event-day if ANY of:
(a) 311 street+highway flooding count >= per-era p99 (96/day measured on the
    union; era split 2010-2019 / 2020+ to absorb report-rate drift);
(b) >=1 subway-alert flood event (event_id post-2020, status_id-deduped
    pre-2020, both phrasings "flood"/"water condition");
(c) NOAA Storm Events flash-flood/flood/coastal-flood row for the five boroughs
    (CZ_NAME filter, zone-coded coastal rows included);
(d) CO-OPS observed exceedance of NWS minor threshold at Battery or Kings Point
    (NAVD88 series via datum=NAVD).
Contiguous event-days merge into one event. Window = union of contributing
observation timestamps padded to whole hours +/-3h. Class: coastal if (d) fires
without (a); pluvial if (a)/(b)/(c) without (d); mixed if both (Sandy=coastal,
Ida=pluvial). GDELT is dropped from the spine entirely (Storm Events covers
1996+; GDELT stays out unless a gap shows).

## D3 Source roles

- Label-grade (may set `flooded` on an asset): 311 street+highway points
  (buffered attachment), subway-alert station labels (via ticket 02's measured
  extractor), FloodNet depth exceedances (2020-10+), USGS high-water marks,
  Sandy inundation polygons (that event only).
- Spine-only (define events, never attach to assets): Storm Events
  (county/zone grain), CO-OPS exceedances (also set event_class).
- Covariate/validation-only (never labels): NFIP claims (block-group support
  mismatch -> chronic exposure prior for the 08 score), 311 sewer backup +
  catch basin (chronic background, measured), MyCoast photos (garnish).
- Coverage honesty: every event carries per-source availability flags (FloodNet
  exists only 2020-10+, alerts 2012+, etc.); labels table starts 2010-01-01.

## D4 Dedupe and attachment

- Alerts: dedupe to event_id (post-2020) / status_id (pre-2020); station set =
  union across all updates of the event (19% of events gain flood wording late).
- 311: keep every unique_key row in silver (no dedupe; same-block density is
  signal); attachment uses count-weighted presence, not row identity.
- Attachment radii (defaults, sensitivity-swept in 08's validation): 311 point
  -> asset within 100 m; HWM -> 100 m; FloodNet sensor -> its own street
  segment/Cell + assets within 50 m; alert station label -> that station's
  entrances directly; Sandy polygon -> contains.

## D5 The label

`flooded(asset, event)` = any label-grade observation attached within window and
radius. Severity tier = max(FloodNet depth exceedance > HWM > alert station >
311 presence), stored as an ordinal + the underlying numbers. Negatives are
asset-event pairs with no attached observation — explicitly documented as
"no report" not "dry"; the 08 validation ticket owns tiered-truth handling
(FloodNet/HWM subset as high-confidence truth, 311 as dense-noisy).

## D6 Units and conventions

Pipeline-09 wholesale: plain Parquet silver sorted by (source, ts), GeoParquet
1.1 only for geometry tables, EPSG:4326, TIMESTAMP_MICROS UTC. Depth stays mm
(FloodNet native); elevations NAVD88 US ft (map Notes); event windows hour-
aligned with ceil_hour semantics so `ref/flood_events` joins
`silver/precip_cell_hourly` for free. Event-day defined in America/New_York
(storms are local-day phenomena) but stored as UTC window bounds.
