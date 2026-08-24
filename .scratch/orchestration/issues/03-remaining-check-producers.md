# 03 — Remaining check producers

**What to build:** The rest of the verification surface speaks the same row vocabulary as
ticket 02 — the cold-mirror check, the backfill census, and a new era-column presence
check. The era check exists because both engines lose Bronze bus era columns *silently*:
Spark without schema merging takes one file's schema with the row count still correct,
and DuckDB without column unioning drops columns when a narrow part sorts first. A
row-count check cannot see it, so the check has to assert columns are PRESENT.

**Blocked by:** 02 (check-result rows).

**Status:** done (2026-08-24, branch `orch03-remaining-check-producers`)

- [x] The cold-mirror check emits rows and reports `inconclusive` when the remote listing itself failed — distinct from a missing object
- [x] It stays soft: it reports and never fails the run, and the re-push-once-then-warn behaviour is preserved exactly
- [x] The backfill census emits the same row shape; its existing 0/1/2 exit contract is unchanged and its own DEAD list stays its own
- [x] A new era-column presence check emits rows asserting each verified Bronze bus reader's schema holds the era columns
- [x] That check fails against a reader configured without schema-union, and the ticket demonstrates that a row-count assertion does not catch the same case
- [x] Tests cover all three outcomes for each producer

## Inherited from the wave-1 landing (2026-08-24, recorded by the gate)

- **Gate satisfied**: orch 02 is landed (6a43e84, in the 557/0/0 suite at
  `7b7bfc8`); consume `raincheck.checks` exactly as its RUN LOG entry states.
- **DuckDB read-path trap (the era-column check reads Bronze with `duck`)**:
  `rel.arrow()` is a LAZY RecordBatchReader on the relation's own connection —
  registering unconsumed readers back and querying deadlocks at 0% CPU. Consume
  with `.read_all()` or use `rel.select(...).create_view(name)`; two lazy
  `rel.query("t", ...)` relations on one connection cross-bind. Mechanism in the
  runbook's KNOWN TRAPS.

## Close-out (2026-08-24) — what shipped, and what a consumer must honour

Three producers, all on `raincheck.checks` (ticket 02's vocabulary, imported, not
re-derived). `checks.py` was NOT widened.

- **Cold mirror** — `src/raincheck/cold.py`. `mirror(root, bucket=None, endpoint=None)
  -> list[checks.Row]`, `line(row) -> str`, `CHECK = "coldcheck"`,
  `CHECK_COLUMNS = checks.CORE + ("kind", "differing")`. One row per top-level
  `archive/` prefix, read off disk (never a hardcoded kind list). `make coldcheck` now
  runs `python -m raincheck.cold`; batch at `<root>/checks/check=coldcheck/`.
  INCONCLUSIVE (`differing` NULL) covers all four "could not check" cases: aws exited
  non-zero, cold storage unconfigured, nothing local to mirror, and — because a batch
  must never be empty — a root with no `archive/` at all (one row, subject `archive`).
  **This fixed a live false OK**: the old shell recipe captured the sync's stdout and
  never looked at its exit status, so a failed listing printed "OK - local Bronze fully
  present remotely" and exited 0. Soft is untouched: `daily.coldcheck()` still
  re-pushes once then warns and returns 0, and daily's stage list is unchanged.
- **Backfill census** — `scripts/backfill-verify.py`, same 0/1/2 meanings, now rendered
  by `checks.rc`. `CHECK = "backfill"`, columns `CORE + (feed, lo, hi, hours_seen,
  hours_want, dead, missing, no_part, no_marker, zero_byte, stale_dead)`, one row per
  feed ALWAYS. Its `DEAD` stays in the script and never touches `gapfill.DEAD` (a test
  asserts the two are disjoint). Two deliberate changes, both mutation-checked: a
  failed listing no longer aborts the remaining feeds (it emits that feed's
  inconclusive row and continues), so a real gap beside a failed listing now exits **1,
  not 2** — the aggregation rule, reaching a case the old early return hid; and a
  stale DEAD entry now prints `BAD` for its feed instead of `OK ` (same verdict
  gapcheck reached in ticket 02; the exit code was already 1). Honours
  `RAINCHECK_AWS`.
- **Era-column presence (NEW)** — `src/raincheck/eras.py`. `check(root, spark=None)
  -> list[checks.Row]`, `mixed_day(root, kind) -> str | None`, `line(row)`,
  `CHECK = "eras"`, `ERA_COLS = {"vp": ("schedule_relationship", "header_ts"),
  "tu": ("direction_id", "trip_delay_s", "trip_ts", "header_ts")}` (the one home for
  those columns), columns `CORE + (reader, kind, day, era_cols, missing)`, subjects
  `"duck vp" | "spark vp" | "duck tu" | "spark tu"` — one row per (reader, kind) every
  run. `make eras`. Placement is ticket 09's call; it is deliberately NOT in
  `daily.STAGES`.
  - It reads the newest date dir whose parts DISAGREE about their columns, because a
    uniform day cannot tell a union reader from a narrow one. **No mixed day ->
    INCONCLUSIVE, never ok** (same false-OK class as gapverify with no pair). No JVM ->
    the two spark rows are INCONCLUSIVE.
  - The verified readers are called for real: `duck.table` and `events.bronze_vp` /
    **`events.bronze_tu`** — the latter extracted here from the two identical
    mergeSchema reads inside `events.tu_rows` and `events.baselines`, which now both
    call it. `duck.table(...).columns` is metadata only, so this check never touches
    the lazy-reader deadlock.
- **The blindness proof the ticket asked for** (`tests/test_check_producers.py`, both
  engines, measured not quoted): with a NARROW part sorting first, DuckDB 1.5.5 without
  `union_by_name` and Spark without `mergeSchema` both return the right row count with
  the era columns simply gone — the tests assert the counts are EQUAL across the union
  and non-union reads while the check flips OK -> FAIL. A row-count expectation passes
  on both reads and sees nothing. (Wide part first, DuckDB raises instead; that is why
  the silent case is the one that has to be tested.)
- **Real-data run**, not just fixtures: `make eras` on `/Users/ross/raincheck/data`
  found the mixed day at **date=2026-08-23** (the ticket-10 daemon restart, exactly the
  boundary CONTEXT.md records) and returned 4/4 OK in 8.9 s, batch written.
- **`make` cannot carry the three outcomes** (measured both ways): GNU make exits **2
  for ANY recipe failure**, so `make coldcheck` / `make gapverify` / `make eras` return
  0 or 2 and a module rc of 1 arrives as 2. A runtime that must tell fail from
  inconclusive has to call the module (`python -m raincheck.<mod>`) or read the
  persisted batch. `daily.py` treats any non-zero as failed and is unaffected.
