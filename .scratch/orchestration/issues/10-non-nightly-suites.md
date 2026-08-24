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
