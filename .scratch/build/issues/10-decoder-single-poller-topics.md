# 10 — Census-complete decoder, single-poller archiver, six-partition topics

**What to build:** The archiver captures the fields the live rail needs (feed header timestamp on VP/TU; TU
trip-level delay, timestamp and direction) and publishes each decoded poll to Kafka as a side
effect, so one poller feeds Bronze and both topics; the topics are recreated to spec and the
Kafka JSON schema is derived from the decoders and asserted equal to them. Spec: C, J.

**Blocked by:** 01

**Status:** resolved 2026-08-22

- [x] decode_vp/decode_tu carry header_ts; decode_tu carries trip_delay_s (the feed's trip-level trip_update.delay, never labelled Delay), trip_update timestamp and direction_id; the census test on the frozen fixtures asserts the new keys and that stop-level arrival.delay is still never set
- [x] one `StructType` per topic is derived from the decoder row shapes and a test asserts equality with the decoder key sets (07-6)
- [x] the archiver publishes VP rows to raincheck.bus.vp (key vehicle_id) and TU rows to raincheck.bus.tu (key trip_id) as a side effect of the poll it already makes; the standalone producer and `make produce` are removed; a publish test skips when no broker answers
- [x] topics are created with six partitions, zstd, delete retention 48 h, no compaction (recreated from today's one-partition topics; documented as an irreversible knob)
- [x] the LaunchAgent is restarted on the new code and a real poll lands in Bronze with the new columns and on both topics; the daemon's stop command and budget behaviour are unchanged

---

**Implementation comment (2026-08-22).** Row shapes are canonical in `feeds.VP_COLS` /
`TU_COLS`; the census test asserts every decoded row is exactly that tuple, in order.
`trip_delay_s` = the feed's `trip_update.delay` verbatim (fixture: all 1,988 trips carry
delay/timestamp/direction_id); stop-level arrival.delay still asserted absent.
`spark.topic_schema(kind)` derives the StructType from the COLS tuple + `archiver.TYPES`
(int64->Long, float64->Double, else String) - never hand-maintained. `archiver.publish()`
produces each poll's rows as a side effect (lazy Producer, zstd, 30 s message timeout);
broker-down buffers in librdkafka and surfaces as one counted stderr line per 10-min
flush window, never blocking capture; the producer drains on clean exit (`--once`,
budget stop). producer.py deleted. `make topics` (raincheck/topics.py) is the documented
irreversible knob: delete + recreate at six partitions, zstd, delete/48 h (the broker
was fresh - the old one-partition topics no longer existed, so this run only created).
nbp converter emits NULL `header_ts` so archive-era and live VP stay one schema (its
census test enforces it). Verified live: LaunchAgent kickstarted (pid 29429), messages
on both topics carry the new keys with current header_ts. The publish test targets a
scratch topic (`raincheck.test.vp`) so fixtures never land on the real ones. In passing:
`tests.conftest` import in test_picks.py made invocation-independent (bare pytest broke,
`python -m pytest` worked).
