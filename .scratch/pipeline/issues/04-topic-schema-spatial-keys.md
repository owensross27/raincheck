# 04 Topic schema and spatial keys

Type: grilling
Status: resolved
Blocked by: 01

## Question

Lock the Kafka topic design and spatial keying before the enrich job exists:
raw protobuf bytes vs decoded JSON on the wire (or both, raw for fidelity + decoded
for consumers); topic partitioning and keys (vehicle_id for VP, trip_id for TU);
compaction policy; H3 resolution (res 8 ~0.7 km2 vs res 9 ~0.1 km2) for lateness
aggregation; whether taxi zones (263) are a presentation layer on top of H3 or a
second first-class key. Ross decides, options come with the measured message sizes
from ticket 01.

## Answer

Resolved 2026-08-15 by grilling; all seven recommendations accepted as-is.

1. **Wire format: decoded JSON only** (current code). The dict shapes in
   `src/raincheck/feeds.py` are the schema; additive-only evolution, no registry.
   Set `compression.type=zstd` on both topics. Nothing preserves raw protobuf
   anywhere today (the archiver also writes decoded rows) — that question moves
   to ticket 05 (Bronze/archiver), not the wire.
2. **TU granularity: per-StopTimeUpdate flat rows** (current). ~233 B JSON/row,
   59,900 rows per rush poll = ~500 msg/s sustained — trivial for Kafka; zstd
   erases the ~7x inflation from repeating trip context per row.
3. **Keys confirmed: `vehicle_id` (VP), `trip_id` (TU). Partitions: 6 per topic,
   fixed at creation.** Partition count is the one irreversible knob — adding
   partitions later re-hashes keys and breaks per-vehicle/per-trip ordering,
   which speed-from-successive-pings and delay tracking depend on.
4. **No compaction, delete retention, 48h.** Compaction keeps last-per-key and
   would destroy the time series. Kafka is transport; the archiver makes wire
   loss non-fatal. A compacted `latest` topic is YAGNI until a serving layer
   exists.
5. **H3 resolution 8 is the canonical spatial key** (~0.74 km2, ~1:1 with AORC's
   1 km native cell; precip long table stays ~30M rows/year). Res 9 would claim
   precision the rain data doesn't have; it stays recomputable from Silver
   lon/lat if the heatmap ever wants it.
6. **Taxi zones are a presentation overlay**: one static H3-to-zone lookup
   (hex centroid point-in-polygon, built once), joined at Gold/serving time.
   No `zone_id` column in Silver.
7. **No alerts topic until something polls the alerts feed.** Whether alerts
   capture starts is ticket 05's cadence decision.

Measured wire sizes (fixture 2026-08-11, decoded by `feeds.py`): VP feed
159 KB pb/poll, ~132 B pb/entity, ~290 B JSON/row, ~350 KB JSON/poll. TU feed
1.30 MB pb/poll, ~594 B pb/trip, ~233 B JSON/row, ~8.8 MB JSON/poll exploded.
Uncompressed wire ~1-1.5 GB/day VP + ~6-10 GB/day TU before zstd.

Consequences: ticket 09 (storage/CRS) is now unblocked. Ticket 05 inherits the
raw-pb-preservation and alerts-cadence questions (comment added there). The
config deltas vs the smoke slice (6 partitions, zstd) are build work for
`/to-spec`, not applied in-map. Glossary terms (Cell, Zone, Ping, Stop row)
captured in `CONTEXT.md` at the repo root.
