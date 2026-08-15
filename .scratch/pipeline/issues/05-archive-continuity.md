# 05 Archive continuity

Type: grilling
Status: open
Blocked by: 01

## Question

Nothing public archives the bus feed since 2024-09-06, so every unpolled day is
gone. What continuity policy do we commit to before any capture daemon is built:
poll cadence per feed (VP 30s and TU 120s were the smoke defaults), retention and
partitioning of Bronze Parquet, snapshotting the static GTFS zips on Last-Modified
change, and the run mode on Ross's Mac (launchd plist vs a compose sidecar vs
nothing until the pipeline is on a box that is always on)? The launchd option is a
standing background process on his machine and needs his explicit yes. The Answer
records the policy; the daemon itself is downstream build work.

## Comments

2026-08-15, inherited from [04 Topic schema and spatial keys](04-topic-schema-spatial-keys.md):
two questions land here. (a) Nothing preserves raw protobuf anywhere — the wire is
decoded-JSON-only by decision, and the archiver also writes decoded rows. Decide
whether Bronze keeps raw `.pb` snapshots (measured: VP 159 KB + TU 1.30 MB per poll
uncompressed, ~1.4 GB/day before compression). (b) Alerts capture cadence — no Kafka
topic and no polling exist for alerts; if the flood phase wants disruption labels,
capture must start here.
