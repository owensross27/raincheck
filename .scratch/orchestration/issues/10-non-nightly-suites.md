# 10 — The non-nightly suites

**What to build:** The two invariant families that do not belong in a nightly run get
suites and their own triggers: the backfill-era census, which fires when a backfill chunk
lands, and the reference canaries, which fire on a reference rebuild. Keeping them out of
the nightly is deliberate — nightly runs should not grow checks over data that cannot
change — and keeping the two eras' tools apart is the standing rule from the backfill
work.

**Blocked by:** 03 (remaining check producers), 08 (GX foundation).

**Status:** ready-for-agent

- [ ] A backfill census suite expects on the census rows for the backfill era, with its own dead-hour list and the zero-byte-part rule (empty fill markers exempt)
- [ ] It is not in the nightly DAG; its trigger is a backfill chunk landing
- [ ] A reference-canary suite expects **through** the frozen-count canary that already exists in code rather than restating the numbers, so each count keeps one home
- [ ] It covers reference content identity and the key-stability diff, and triggers on a reference rebuild rather than nightly
- [ ] The in-session byte gate stays a pytest concern and does not become a suite
- [ ] The slice-era acceptance gates do not become suites

## Inherited from orchestration 03 (landed 2026-08-24, b37a761)

- **The backfill census half is shipped**: check `backfill`, columns `CORE + ("feed",
  "lo", "hi", "hours_seen", "hours_want", "dead", "missing", "no_part", "no_marker",
  "zero_byte", "stale_dead")`, **one row per feed always**. Its DEAD list stays inside
  `scripts/backfill-verify.py` and a test asserts it is disjoint from `gapfill.DEAD` —
  the two eras' tools stay apart, as this ticket requires. Zero-byte PARTS are counted
  in `zero_byte`; empty `_gapfill` markers are exempt by construction (they are counted
  as markers, never as parts). The 0/1/2 meanings are unchanged, now rendered by
  `checks.rc`, so a real gap beside a failed listing exits 1 and every feed still gets
  its row.
- **OPEN QUESTION THIS TICKET MUST SETTLE FIRST — nobody owns a `ref`-canary check-row
  PRODUCER.** Spec §5 lists the ref canaries among the producers; orch 03's scope was
  exactly three (cold mirror, backfill census, era columns) and it did not build them;
  this ticket writes only the SUITE. So either the reference-canary suite expects
  through `ref`'s existing in-code canary with no batch on disk, or the producer has to
  be built here. Decide before writing the suite, not during.
