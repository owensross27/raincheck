# 04 Topic schema and spatial keys

Type: grilling
Status: open
Blocked by: 01

## Question

Lock the Kafka topic design and spatial keying before the enrich job exists:
raw protobuf bytes vs decoded JSON on the wire (or both, raw for fidelity + decoded
for consumers); topic partitioning and keys (vehicle_id for VP, trip_id for TU);
compaction policy; H3 resolution (res 8 ~0.7 km2 vs res 9 ~0.1 km2) for lateness
aggregation; whether taxi zones (263) are a presentation layer on top of H3 or a
second first-class key. Ross decides, options come with the measured message sizes
from ticket 01.
