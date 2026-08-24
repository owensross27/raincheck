# 05 — The nightly DAG

**What to build:** The whole nightly runs as one DAG: every stage in the declared order,
every edge `all_done` so a red gate still cannot cost the day's build, and a report task
that ends the run naming the stages that failed — the same sentence the driver exits with
today. Scheduled at 06:00 America/New_York with **catch-up off**, because every stage is
already a catch-up over a bounded window; replaying missed intervals would run the same
14-day scan N times and recover nothing the next single run would not.

**Blocked by:** 01 (stage declaration), 04 (DAG delivery).

**Status:** done — branch `orch05-nightly-dag`, `bd04dd4`, 2026-08-24. See the RUN LOG
entry and the close-out at the bottom of this file.

- [x] Every stage in the declaration appears as a task, in the declared order, each running its existing make target or module entrypoint
- [x] Every edge is `all_done`: a failed hour-completeness check still leaves the day's build running
- [x] A report task ends the run, prints the per-stage timing lines and fails the run naming the failed stages
- [x] Catch-up is off, at most one run is active, the schedule is 06:00 America/New_York, and run ids read `daily-YYYY-MM-DD`
- [x] The DAG never uses the run's logical date to choose a Service date — the gap scan decides, at task time, from what is on disk
- [x] Gate stages carry zero retries (re-reading the same data cannot change a verdict, and a retrying gate turns a stable red into a flapping one); transport stages retry with exponential backoff
- [x] A structure test, skipping cleanly when Airflow is absent, asserts task ids and edges equal the declaration, that every edge is `all_done`, that catch-up is off and the timezone is America/New_York, and that no task's callable is defined in the DAG file
- [x] The remote-census check that covers unrecoverable subway positions is **not** in this DAG

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

## From orch 04's landing (2026-08-24, branch `orch04-dag-delivery`) — consume, do not rebuild

The delivery seam and the task shape exist and are proved on the cluster. Build the
nightly out of these; do not write a second way to make a pod.

```python
from raincheck_stage import make, module, stage_task

stage_task("gapfill", "raincheck-stage", make("gapfill", DATE="2026-08-15"))
stage_task("gapverify", "raincheck-stage", module("gapfill", "verify"))
stage_task("events", "raincheck-spark", make("events", DATE=day))
```

- `stage_task(task_id, shape, command, **kwargs) -> KubernetesPodOperator`. `shape` is
  `"raincheck-stage"` or `"raincheck-spark"` and there is no third; the whole pod spec —
  requests, limits, the staging emptyDir, `raincheck.io/pool: burst`, the
  `raincheck-build` ServiceAccount, the optional `r2-build` envFrom — is READ from
  `deploy/k8s/raincheck/build.yaml`. **Do not pass `container_resources`,
  `node_selector`, `resources` or `image`: `tests/test_dag_delivery.py` fails the build if
  a DAG file names any of them, and so does any capacity literal.**
- `make(target, **vars)` is `make -C /opt/raincheck <target> VAR=value ...`.
  `module(name, *args)` is `python -m raincheck.<name> ...`. **Use `module()` for any task
  that must tell the three check outcomes apart** — GNU make exits 2 for ANY recipe
  failure, so a module rc of 1 arrives as 2 (orch 03 measured it both ways).
- DAG files live in `dags/` at the repo root and are baked into `<sha>-airflow`, the
  second tag `scripts/cloud-image.sh` builds. **A new DAG needs an image build and both
  pins committed before it exists on the cluster** — there is no git-sync.
- **A task is TWO burst pods**: the executor's worker (200m/512Mi) plus the operator's
  stage pod. A task mapped over N days is 2N pods, all on burst, none on the floor.
- **Node purchase, not task time, is what a short task costs.** Measured on the proof run:
  95 s to buy the worker's node, 74 s more for the stage pod's, against 87 s of work.
  `stage_task` already sets `startup_timeout_seconds=900` for this; do not lower it.
- `raincheck_smoke` (`make warm`, `schedule=None`, unpaused) stays as the platform canary.
  Trigger it before debugging a nightly failure: if it is green the platform is fine.


## Close-out (2026-08-24, `bd04dd4`)

**The DAG is `raincheck_daily`, and it is ON THE CLUSTER AND PAUSED.** Image
`d801b1462dee` / `d801b1462dee-airflow`, both pins committed, `airflow dags list` shows it.
Paused deliberately and NOT as an oversight: a task pod's `RAINCHECK_ARCHIVE_ROOT` is the
`/staging` emptyDir in cloud 03's placement table, so an unpaused nightly would gapfill
into scratch and then `coldpush` that scratch to the production bucket. Pointing the pods'
root at the object store is ticket 12's cutover (cloud 13 made writes work for the events
chain); until then this DAG is structurally complete and functionally dark, on purpose.

**Task ids, in declared order:** `gapfill · gapverify · gapcheck · coldpush · coldcheck ·
events · precip · prune · report`. Linear, every edge `all_done`, `report` last.

**Nothing here is a second copy of the contract.** Task ids, order, the soft stage and the
retry classes are READ from `daily.STAGES` — `raincheck_stage.stages()` ast-parses
`src/raincheck/daily.py`, which `docker/Dockerfile` bakes beside the DAGs as data. Parsed
and not generated, because a generated copy is a copy. The DAG image has no `raincheck`
package in it and `tests/test_dag_delivery.py` forbids a DAG importing one, so data is the
only route. WHICH POD each stage gets is likewise read, from the placement table's own
`raincheck.io/stages` annotation (`raincheck_stage.shape_of`) — cloud 03 had already
written that mapping down, so the DAG holds no opinion about it.

**`daily.Stage` gained one field, `argv`** — this stage as its own process. Every GATE
carries one and that is the orch 03 MUST made structural: `gapverify` and `gapcheck` run
`python -m raincheck.gapfill verify|check`, never `make`. `make daily` never reads the
field; its own any-non-zero rule is untouched and `tests/test_daily.py` passes unmodified.

**`python -m raincheck.daily <stage>`** runs one declared stage, expanded over its own axes
exactly as `make daily` expands it (so `precip` is 1-2 MRMS months in ONE pod here), and
exits on that stage's verdict. `events` is `daily.build`, so `gaps()` reads the disk AT
TASK TIME and `logical_date` chooses nothing.

**The report task.** `daily.report` prints the driver's own ending — one sentence, one home
(`verdict()`), used by both runtimes. A pod cannot see the run it belongs to and a callable
in a DAG file would be a stage on the scheduler, so Airflow renders
`{{ ti.get_task_breadcrumbs(ti.dag_id, ti.run_id) | tojson }}` into the pod's argument: one
row per finished task with its state and duration. Lines come out in declared order, a SOFT
stage never joins the failure list, and anything that neither succeeded nor failed prints
its STATE rather than `ok` — which is what ticket 07 needs when it renders INCONCLUSIVE as
a skip.

**Run ids read `daily-YYYY-MM-DD`, and that cost a PLUGIN.** A run id is the timetable's to
make, so `plugins/raincheck_timetable.py` subclasses `CronTriggerTimetable` and overrides
`generate_run_id` (SCHEDULED only — a manual trigger keeps Airflow's id, or two manual runs
in one day would collide). It has to be a registered `AirflowPlugin`: a custom timetable is
stored in the serialized DAG by qualified name and looked up in the plugin registry, and
without registration the DAG cannot even be SERIALIZED (measured: `SerializationError`,
"Timetable class ... is not registered"). The standing risk is on the file's docstring — if
the plugin is ever removed, `airflow dags delete -y raincheck_daily` FIRST, or every
`airflow dags list` breaks on the undecodable rows.

**Deliberately out, and each for its own reason.** `coldgaps` — unrecoverable Mac-era
subway positions, it would page forever. `eras` — a real check whose PLACE is ticket 09's
call, which is why ticket 01 left it out of the declaration. `gold` — it is the reduce
INSIDE `daily.build` over the months the built days touched; splitting it out only becomes
necessary when `events` is one pod per Service date, which is ticket 06's fan-out. Adding a
`gold` task here would double the reduce.

**Measured on the cluster, and one real defect it found.** The first stage pod stamped after
cloud 12 landed sat in `Init:ImagePullBackOff` pulling `docker.io/library/raincheck:latest`:
`raincheck_stage.pod()` rewrote the ungoverned `image: raincheck` spelling in
`spec.containers` ONLY, and cloud 12's `refpull` initContainer carries the same spelling —
so **every task pod of every raincheck DAG had been unpullable since that landing**, with
the suite green because the placement-table test walked `containers` alone. Fixed in
`pod()` (both lists), test extended (both lists, neither may lose an entry, no container may
keep the unpinned name), mutation-checked. After the fix `raincheck_smoke` ran green
(`orch05-logcheck-2`).

**TASK-POD REMOTE LOGGING IS VERIFIED WORKING** — the wave-3 gate carried it as UNVERIFIED
(the cloud 12 addendum had proved the SCHEDULER's env reached R2, not a task pod's).
Measured 2026-08-24: the prefix was EMPTY before the run, and after it holds
`s3://raincheck-bronze/airflow-logs/dag_id=raincheck_smoke/run_id=orch05-logcheck-2/task_id=warm/attempt=1.log`
(15,472 B). Debug task pods through R2 from here, not through `kubectl logs`.

**Tests:** `tests/test_dag_nightly.py`, +13 (12 passed + 1 airflow-absent skip on the Mac;
the module trio `test_dag_nightly` + `test_daily` + `test_dag_delivery` reads
**43 passed / 2 skipped**). The one Airflow-gated test is not left unrun: it passed 13/13 in
a throwaway venv pinned to the cluster's own versions (Airflow **3.2.2** +
apache-airflow-providers-cncf-kubernetes **10.17.1**), and it SERIALIZES the DAG rather than
only building it — which is a separate claim and the one that caught a real bug before the
cluster did (a `zoneinfo.ZoneInfo` timezone imports and runs fine and then refuses to
serialize, so the failure would have landed in the dag-processor). Mutation round: 9 mutants,
**9/9 killed**, pristine control run LAST from a copied backup.
