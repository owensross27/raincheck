# 10 — Census-complete decoder, single-poller archiver, six-partition topics

**What to build:** The archiver captures the fields the live rail needs (feed header timestamp on VP/TU; TU
trip-level delay, timestamp and direction) and publishes each decoded poll to Kafka as a side
effect, so one poller feeds Bronze and both topics; the topics are recreated to spec and the
Kafka JSON schema is derived from the decoders and asserted equal to them. Spec: C, J.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] decode_vp/decode_tu carry header_ts; decode_tu carries trip_delay_s (the feed's trip-level trip_update.delay, never labelled Delay), trip_update timestamp and direction_id; the census test on the frozen fixtures asserts the new keys and that stop-level arrival.delay is still never set
- [ ] one `StructType` per topic is derived from the decoder row shapes and a test asserts equality with the decoder key sets (07-6)
- [ ] the archiver publishes VP rows to raincheck.bus.vp (key vehicle_id) and TU rows to raincheck.bus.tu (key trip_id) as a side effect of the poll it already makes; the standalone producer and `make produce` are removed; a publish test skips when no broker answers
- [ ] topics are created with six partitions, zstd, delete retention 48 h, no compaction (recreated from today's one-partition topics; documented as an irreversible knob)
- [ ] the LaunchAgent is restarted on the new code and a real poll lands in Bronze with the new columns and on both topics; the daemon's stop command and budget behaviour are unchanged
