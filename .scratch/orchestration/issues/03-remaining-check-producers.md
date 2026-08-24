# 03 — Remaining check producers

**What to build:** The rest of the verification surface speaks the same row vocabulary as
ticket 02 — the cold-mirror check, the backfill census, and a new era-column presence
check. The era check exists because both engines lose Bronze bus era columns *silently*:
Spark without schema merging takes one file's schema with the row count still correct,
and DuckDB without column unioning drops columns when a narrow part sorts first. A
row-count check cannot see it, so the check has to assert columns are PRESENT.

**Blocked by:** 02 (check-result rows).

**Status:** ready-for-agent

- [ ] The cold-mirror check emits rows and reports `inconclusive` when the remote listing itself failed — distinct from a missing object
- [ ] It stays soft: it reports and never fails the run, and the re-push-once-then-warn behaviour is preserved exactly
- [ ] The backfill census emits the same row shape; its existing 0/1/2 exit contract is unchanged and its own DEAD list stays its own
- [ ] A new era-column presence check emits rows asserting each verified Bronze bus reader's schema holds the era columns
- [ ] That check fails against a reader configured without schema-union, and the ticket demonstrates that a row-count assertion does not catch the same case
- [ ] Tests cover all three outcomes for each producer
