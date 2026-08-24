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
