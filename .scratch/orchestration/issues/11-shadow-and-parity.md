# 11 — Shadow mode and the parity gate

**What to build:** The DAG runs beside the LaunchAgent for a shadow period and proves it
builds the same data — **into a shadow data root**, with the mutating stages disabled.
Shadowing against the live tree would mean two writers on one Bronze, which is a data
event, not an experiment. Parity is content equality (row counts plus a sha over sorted
rows per partition), never bytes: byte-identity holds only within one JVM session, and a
DAG run is by construction a different session than the LaunchAgent's.

**Blocked by:** 05 (the nightly DAG), 06 (fan-out) — so the shadow tests the shape that
will actually run. **External:** the shared parity module declared by the cloud effort.

**Status:** ready-for-agent

- [ ] The shadow DAG writes to a shadow data root and never touches the live Silver, Gold or live prefixes
- [ ] The fill, the cold push and the live-table prune are disabled in shadow mode, and the run says so rather than silently skipping them
- [ ] Parity is content equality per partition, computed by the shared parity module; if it has not landed from the cloud effort, build it to that interface — never a second implementation
- [ ] The gate names which partitions differ and how, and refuses to certify a day where a partition exists on one side only
- [ ] Each shadow day records **two independent proofs**: per-partition content equality, and outcome equality between the two runtimes' check rows
- [ ] The ticket states in writing which stages shadowing cannot prove — the three mutating ones — and how they get proven after cutover


## From orch 06's landing (2026-08-25, `orch06-fan-out`, `0a9c4e6`) — the graph is fanned out

**Final task ids, declared order:** `plan_kind · gapfill · gapverify · gapcheck · coldpush ·
coldcheck · plan_service_date · events · gold · precip · prune · report`. Still linear,
still `all_done` on every edge, `report` last.

- **Mapped:** `gapfill` and `gapverify` over `kind` (5 pods each — `gapfill.KINDS`),
  `events` over `service_date` (one pod per gap day the scan returns). **Not mapped:
  everything else, `gold` included.** `precip` keeps its declared `month` axis and stays ONE
  pod: 1-2 MRMS months in a single Spark session. Which axes this runtime maps is
  `MAPPED = ("kind", "service_date")` in `dags/raincheck_daily.py`, the only new opinion in
  that file — it names axes, never a stage.
- **The two `plan_<axis>` tasks are not stages** (they are not in `daily.STAGES`, like
  `report`). Each runs `python -m raincheck.daily plan <axis> /airflow/xcom/return.json` with
  `do_xcom_push=True`, in the same measured shape as the first stage that maps on it.
  They exist because Airflow can expand a task only over an XCom and only a pod can read the
  data root. `plan_service_date` sits AFTER the fill on purpose.
- **`gold` is a stage now** — `daily.STAGES` gained it and `Stage` gained a `reduces` field.
  One non-mapped reduce behind the mapped days: it takes the plan's day list as its trailing
  argument and rolls the months of the days that LANDED, deciding that from the disk
  (`daily.silver(root, day)`, the same predicate `gaps()` defers on). **A breadcrumb row is
  `{task_id, map_index, state, operator, duration}` and cannot name a Service date** — that
  is measured, and it is why the reduce reads the disk rather than joining task states.
- **One item reaches a pod as the container's ARGS** (Kubernetes joins command + args), so
  every stage's process form is unchanged and the item is its trailing argument:
  `python -m raincheck.daily events 2026-08-20`, `python -m raincheck.gapfill fill vp`.
  (`gapfill` gained an `argv` and its `--feed` became the positional it always called `kind`;
  `make gapfill KIND=vp` is the make form.)
- **A zero expansion is a `skipped` task and a green run; a plan that pushed no XCom at all
  is `upstream_failed`** — so "no gaps this morning" and "the scan broke" can never be
  confused (Airflow 3.2.2 `models/taskmap.py`, cncf-kubernetes 10.17.1 `EMPTY_XCOM_RESULT`).
- **Sizing:** a task is TWO burst pods (executor worker + stage pod), so N mapped days is 2N
  pods and 2N Karpenter decisions; node purchase (95 s + 74 s measured) dominates a short
  stage. Baseline the fan-out exists to beat: **1928 s serial for 7 days.**
- **UNPROVEN, and it is on the critical path of anything that RUNS this graph:** the plan
  pod's xcom-sidecar handoff has never executed on the cluster — orch 06's helm upgrade was
  permission-denied, so the DAG image built and self-checked but never ran in front of a
  scheduler. The operator stamps an **`alpine:3.23.4` sidecar (Docker Hub, unauthenticated)**
  and `exec`s the result file out of it; `pods/exec` is granted (measured). The wave-5 gate
  carries the owed proof; read the OWED paragraph in `06-fan-out.md` before debugging a
  mapped task that never starts.

**For the shadow specifically: a shadow day is ONE MAPPED INDEX, not a run.** The cluster
side of a day is the `events` pod for that Service date plus the single `gold` behind it;
the Mac side is `daily.build(root, closed, days, service_date=D)` then `daily.gold(root,
days)`. `python -m raincheck.daily events <YYYY-MM-DD>` is the exact form both run, which is
what makes the two sides comparable at all — compare at the PARTITION level, as the ticket
already says. Note `daily.build` no longer rolls Gold: if a shadow day compares Gold, it has
to run the `gold` step too, and give it the day list.

## From orch 13's landing (2026-08-25, `orch13-showcase-surface`) — record your shadow run

**Your shadow is the FIRST real run this project will have had**, and the showcase says so
in its own words today: measured 2026-08-25, `s3://raincheck-bronze/airflow-logs/` holds
only `dag_id=raincheck_gateprobe` and `dag_id=raincheck_smoke`, so the recorded run on the
public surface is the wave-5 gate's PROBE, labelled `probe`, with the page stating that a
probe is not a nightly and that its map is three wide rather than five.

**Recording yours is two commands and no new code**, once your run's logs are on R2:

    aws s3 cp s3://raincheck-bronze/airflow-logs/dag_id=raincheck_daily/run_id=<id>/ \
        <dir>/ --recursive --endpoint-url $RAINCHECK_COLD_ENDPOINT
    python -m raincheck.showcase --logs <dir> --label shadow

That writes `research/orch-13-run-<run_id>.json` (commit it - the render must not need the
cold credential) and re-renders `web/showcase/`. `--label` is REQUIRED and is
`probe|shadow|nightly`: the label decides what the page CLAIMS, and a shadow shown as a
nightly is the one failure that surface exists to avoid.

**What the record derives, so you know what it can and cannot say.** Per instance:
`task_id · map_index · tries · started · ended · seconds · state · exit_code`, the newest
attempt winning. **State is derived from each log's own ending, in the operator's own
precedence** - a `Skipping task.` line BEFORE any `error` line, because an INCONCLUSIVE
gate logs both. Identity comes from the log LINES, never the key path, so copying the logs
anywhere is safe. `totals.widest_map` is the fan-out's claim, MEASURED: five or more is
what ticks orch 13's open checkbox, and only a real gap scan can produce it. The verdict is
`daily`'s own closing line out of the `report` task's log (`[base] daily: OK` /
`INCONCLUSIVE - ` / `FAILED - `) and **never the DagRun state**.

**A zero expansion writes NO LOG at all** (never scheduled), so it appears in the graph and
in no row of the run table - which is also why the pod count is 2 x instances that RAN.
