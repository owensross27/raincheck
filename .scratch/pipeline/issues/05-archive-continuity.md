# 05 Archive continuity

Type: grilling
Status: resolved
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

2026-08-16, observed while working [06 Delay metric design](06-delay-metric-design.md):
the foreground `raincheck.archiver` (pid 27870, started 2026-08-15 13:12 EDT) lost
~13 h overnight, not to a crash but to laptop sleep: last flush 20:27 EDT, `pmset`
wake at 09:41 EDT, next file `date=2026-08-16/hour=13.parquet` at 10:00. Poll gaps
inside the archive are otherwise a clean 30 s / 120 s (713 VP polls, one 3.4 h gap
before the run proper). Run-mode evidence: on this Mac, capture continuity means
`caffeinate`/`pmset` or an always-on box, not just launchd.

## Answer

Resolved 2026-08-16 by grilling; all seven recommendations and both glossary terms
accepted as-is. Evidence measured live at 14:10-14:20 UTC on the feeds, the Mac, and
the archive on disk.

1. **Live capture is opportunistic; run mode is a LaunchAgent (explicit yes given).**
   The 2017-2024 backfill holds the headline evidence (Ida, 2023-09-29); 2026 capture
   feeds the streaming demo and the MRMS-era sample, so gaps are expected and never
   fought. Policy: a per-user LaunchAgent (RunAtLoad + KeepAlive, stderr to a log file)
   wrapping `caffeinate -s` so capture also survives overnight when plugged in; **no
   `pmset` or power-setting changes**. An always-on box (Oracle Always-Free ARM,
   Hetzner ~EUR 4/mo, a Pi) plus object storage stays in the fog ("promotion beyond
   laptop") until the backfill proves the rails. Evidence: PID 27870 ran 21 h and
   captured 6.5 h (polls stop 23:09 UTC, resume 13:43 UTC, one Power Nap wake at
   00:27); the Mac sleeps on lid close, so a daemon alone never gives continuity.
   Precedent: four LaunchAgents already run on this Mac.
2. **Cadence: VP 30 s, TU 120 s, alerts 300 s, static GTFS daily.** The feed
   regenerates every 20-31 s (VP header deltas 31/21/20/31; TU header ~21 s apart), so
   30 s misses ~10-15% of Snapshots and sometimes returns the same one twice: the
   archiver drops any Poll whose `header.timestamp` equals the previous one (each
   Snapshot stored once; missed ones accepted). TU keeps 120 s: 86% of stop rows change
   every poll so every poll carries signal, but TU is 76% of the bytes and 06's actual
   arrival comes from VP. Both are knobs 06 may turn without touching anything else.
3. **No raw `.pb` in Bronze; the decoder becomes census-complete, guarded by a test.**
   Raw would cost ~410 MB/day zstd (VP 55 KB + TU 350 KB per poll), doubling Bronze.
   Instead the decoder captures every populated field: today it drops
   `header.timestamp` (both feeds) and, on TU, `trip_update.delay` (nonzero on 100% of
   trips: min -2,120 s, median +102 s, max +4,263 s), `trip_update.timestamp` (median
   15 s behind header, max 107 s) and `trip.direction_id`; `entity.id` equals
   vehicle_id / trip_id on 100% of entities, so it is redundant. VP populates no
   `current_status`, `current_stop_sequence`, or `congestion_level`. A pytest walks
   every populated field of a fixture/live feed and fails when the decoder does not
   map one. The 21 hours archived so far lack the three TU fields; accepted loss.
4. **Alerts capture starts now**, a third `kind` in the same archiver at 300 s: flat
   rows per alert x informed_entity (alert_id, header, description, cause, effect,
   active start/end, agency, route_id, direction). Measured 109 entities / 90 KB per
   poll, informed_entity at agency/route/trip level only, no stops; under 5 MB/day.
5. **Static GTFS: daily conditional GET of the six bus zips** (`If-None-Match` on the
   ETag; Last-Modified varies per feed: four at 2026-06-23, Staten Island 2026-07-28;
   ~42 MB per full set) from the same daemon, saved as
   `data/static/<feed>/<Last-Modified date>.zip`, never deleted. Subway zip excluded.
   Versions before today are ticket 11's answer (Transitland: 93 Brooklyn versions
   since 2016).
6. **Bronze layout: Hive `data/archive/<kind>/date=YYYY-MM-DD/hour=HH/` in UTC**
   (service-date semantics belong to Silver, tickets 06/09), flushed every 10 min as
   immutable `part-MM.parquet` files sorted by (key, fetched_at), rows carrying
   `header_ts`. Replaces the hour-in-RAM buffer and read-concat-rewrite (a crash loses
   up to an hour today); sorted files are 25% smaller measured (VP 3.5 -> 2.7 MB, TU
   11.0 -> 8.2 MB per hour; zstd level 19 adds only ~5%). No capture manifest:
   completeness is distinct `header_ts` per hour vs ~138 expected, a query.
7. **Retention: Bronze is never auto-deleted.** Volume ~250 MB/day sorted (VP ~82 +
   TU ~260 MB/day unsorted today); the internal disk has 16 GB free of 228 GB, about
   two months. Bronze root moves to an external SSD when one is available; until then a
   10 GB byte budget at which the archiver **stops and logs** rather than deleting.
   Object storage is a cloud write and stays behind the same yes as the always-on box.

Glossary: **Snapshot** and **Pick** added to `CONTEXT.md`. Ticket 06 owns **Delay**;
the glossary sentence "the feed's own delay field is never populated" is true only at
stop level (`arrival.delay`), and the trip-level finding is on 06 as a comment.

Consequences: the archiver as it runs today keeps dropping the three TU fields until
the build lands (a six-line decoder change; in-map execution was not requested).
Build items for `/to-spec`: LaunchAgent plist + `caffeinate -s`, header-ts dedupe,
census-complete decoder + census test, alerts kind, static-GTFS conditional GET,
10-min sorted part files, byte budget with loud stop. Process topology (one poller
feeding Kafka and Bronze vs the two independent pollers that exist) is a spec detail;
cadence is per feed either way. Fog line "promotion beyond laptop" sharpened on the map.
