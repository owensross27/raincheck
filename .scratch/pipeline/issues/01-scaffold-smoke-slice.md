# 01 Scaffold + smoke slice

Type: task
Status: resolved

## Question

Stand up the isolated test env and prove every rail with the thinnest vertical slice:
Docker Compose Kafka (3.9 KRaft, single node), a producer pushing one real poll of MTA
bus VehiclePositions into a topic, a consumer count proving round-trip, the archiver
writing one Parquet file, and a Zarr probe reading AORC precipitation at Central Park
for Hurricane Ida's peak hour (2021-09-01/02) and getting a value consistent with the
known ~80 mm/h event. pytest green on frozen fixtures. No Spark yet (ticket 07).

Done means: `docker compose up -d` + `make smoke` (or equivalent commands) all pass,
with measured numbers recorded in the Answer.

## Answer

Resolved 2026-08-15. All rails proven with measured numbers:

- Kafka: apache/kafka:3.9.1 KRaft single node via compose, healthcheck green.
- Producer round-trip: one real poll produced vp=1,822, tu=59,900; broker offsets
  confirm exactly raincheck.bus.vp:0:1822 and raincheck.bus.tu:0:59900.
  (Friday 13:47 UTC rush; the 2026-08-11 22:00 ET fixture had 1,190 vehicles.)
- Archiver: 1,822 VP + 59,703 TU rows to zstd Parquet;
  TU hour file is 387,625 bytes for ~60K rows (~6.5 B/row compressed).
- Zarr rail: AORC 2021.zarr read anonymously from S3; Ida peak at the Central Park
  cell = 84.2 mm/h at 2021-09-02T02:00Z vs ~80 mm gauge record. PASS.
- pytest 7/7 on frozen fixtures (1,190 VP / 100% positions / 485 occupancy;
  37,697 TU arrivals / 0 delay fields; Parquet append roundtrip).

Traps hit: none new. kafka-get-offsets.sh (not GetOffsetShell) confirmed again on 3.9.
Env left running: raincheck-kafka container, 48h retention, `docker compose down` to stop.
