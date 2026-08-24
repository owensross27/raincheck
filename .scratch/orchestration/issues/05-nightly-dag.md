# 05 — The nightly DAG

**What to build:** The whole nightly runs as one DAG: every stage in the declared order,
every edge `all_done` so a red gate still cannot cost the day's build, and a report task
that ends the run naming the stages that failed — the same sentence the driver exits with
today. Scheduled at 06:00 America/New_York with **catch-up off**, because every stage is
already a catch-up over a bounded window; replaying missed intervals would run the same
14-day scan N times and recover nothing the next single run would not.

**Blocked by:** 01 (stage declaration), 04 (DAG delivery).

**Status:** ready-for-agent

- [ ] Every stage in the declaration appears as a task, in the declared order, each running its existing make target or module entrypoint
- [ ] Every edge is `all_done`: a failed hour-completeness check still leaves the day's build running
- [ ] A report task ends the run, prints the per-stage timing lines and fails the run naming the failed stages
- [ ] Catch-up is off, at most one run is active, the schedule is 06:00 America/New_York, and run ids read `daily-YYYY-MM-DD`
- [ ] The DAG never uses the run's logical date to choose a Service date — the gap scan decides, at task time, from what is on disk
- [ ] Gate stages carry zero retries (re-reading the same data cannot change a verdict, and a retrying gate turns a stable red into a flapping one); transport stages retry with exponential backoff
- [ ] A structure test, skipping cleanly when Airflow is absent, asserts task ids and edges equal the declaration, that every edge is `all_done`, that catch-up is off and the timezone is America/New_York, and that no task's callable is defined in the DAG file
- [ ] The remote-census check that covers unrecoverable subway positions is **not** in this DAG

## Inherited from orchestration 03 (landed 2026-08-24, b37a761)

- **A stage that must tell FAIL from INCONCLUSIVE calls the module, not the make
  target.** GNU make exits **2 for any recipe failure**, so `make gapcheck` /
  `make gapverify` / `make coldcheck` / `make eras` return 0 or 2 and a module rc of
  1 arrives as 2 (measured both ways). Call `python -m raincheck.<mod>`, or read the
  batch at `<root>/checks/check=<name>/run=<ts>.jsonl`. `daily.py` is unaffected — it
  treats any non-zero as a failed stage, deliberately.
- The cold mirror is now `python -m raincheck.cold` behind `make coldcheck`, and it
  stays SOFT exactly as before: `daily.coldcheck()` re-pushes once, warns, returns 0.
- `make eras` (`raincheck.eras`) is a new check and is deliberately **NOT** in
  `daily.STAGES` — adding it there moves daily's printed stage list, which
  `tests/test_daily.py` pins. Its placement is ticket 09's call.
