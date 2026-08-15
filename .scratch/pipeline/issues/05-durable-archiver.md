# 05 Durable archiver

Type: task
Status: open
Blocked by: 01

## Question

The history gap grows daily (nothing archives this feed since 2024-09-06). Ticket 01
proves the archiver works; this ticket makes it durable: run continuously on the Mac
(launchd plist, restart on wake/crash), VP every 30s + TU every 120s, hourly Parquet
partitions under data/archive/, plus a daily snapshot of the static GTFS zips when
Last-Modified changes. HITL gate: installing a launchd daemon on Ross's machine needs
his explicit yes (it is a standing background process, not a test-env artifact).
Answer records: install decision, disk growth per day measured, retention policy.
