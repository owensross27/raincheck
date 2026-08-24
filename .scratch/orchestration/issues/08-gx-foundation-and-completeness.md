# 08 — Great Expectations foundation and the completeness suite

**What to build:** The first named suite, running as a checkpoint inside the nightly, with
browsable Data Docs at the end of the run. The suite expects on the check's **result
rows**, not on Bronze — it never re-derives a check that a module already implements, so
every threshold keeps exactly one home. Expecting on aggregate rows is also what makes
the report publishable: unexpected values get rendered into Data Docs, so a suite pointed
at Bronze would publish feed rows to a public host.

**Blocked by:** 02 (check-result rows), 05 (the nightly DAG).

**Status:** ready-for-agent

- [ ] Great Expectations installs as an optional extra in the one image; no pipeline module imports it
- [ ] An adapter turns check-result rows into a validation result that preserves all three outcomes — inconclusive is not flattened into pass or fail
- [ ] A named live-capture completeness suite expects on the hour-completeness rows: every kind x closed day is 24/24 or misses only allowlisted hours, no row reports a stale allowlist entry, and the unrecoverable subway positions are excluded by the check's own note
- [ ] The suite is scoped to the live-capture era and is never pointed at the backfill range
- [ ] It runs as an in-DAG checkpoint with zero retries on an `all_done` edge — loud, named, never blocking a later stage
- [ ] Data Docs build once at the end of a run
- [ ] The Great Expectations major version is pinned and recorded; suites are written against that API only, since the 0.x and 1.x context/checkpoint APIs differ substantially
- [ ] A suite test, skipping cleanly when the library is absent, validates a fixture batch holding one passing, one failing and one inconclusive subject, and asserts the inconclusive one is neither
