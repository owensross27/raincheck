# 06 — Fan-out

**What to build:** The independent work runs in parallel. One task per Service date for
the events build, one per feed kind for the fill and its verifier, and the monthly rollup
stays a single reduce behind the mapped days — it is not mappable and is not mapped. The
measured case this exists for: a 7-day catch-up that ran serially in one session in
1928 s, ~275 s/day at steady state.

**Blocked by:** 05 (the nightly DAG).

**Status:** DONE (2026-08-25, `orch06-fan-out`)

- [x] The events build maps over the Service dates the gap scan returns, one pod per day
- [x] The fill and its verifier map over the five recoverable feed kinds (disjoint Bronze prefixes, safe to parallelise)
- [x] The monthly rollup is a single non-mapped reduce over the months the **successfully built** days touched — a failed day cannot pull its month into Gold
- [x] The cold push runs only after every mapped fill has finished (the chain is linear and a mapped task's downstream waits for every index)
- [x] An expansion to zero days is a clean skip and the run stays green — a morning with no gaps is not an alert
- [x] A killed mapped events task is safe to re-run (`spark.sql.sources.partitionOverwriteMode=dynamic`, spark.py:80)
- [x] The structure test asserts the three mapped stages are mapped and the rollup is not

## What it landed as (2026-08-25)

**Task ids, declared order:** `plan_kind · gapfill · gapverify · gapcheck · coldpush ·
coldcheck · plan_service_date · events · gold · precip · prune · report`. Still linear,
still `all_done` on every edge, `report` last. **Mapped: `gapfill` and `gapverify` over
`kind` (5 pods each), `events` over `service_date` (one per gap day). Not mapped:
everything else, `gold` included.** `precip` keeps its declared `month` axis and stays ONE
pod: it rebuilds 1-2 MRMS months in a single Spark session, and a second pod would buy a
second node and a second JVM to save nothing.

**The plan pods are the answer to "how many pods".** Airflow can expand a task only over an
XCom, the Service dates come from a scan of the data root that no scheduler has, and a pod's
only XCom is the file the operator's sidecar reads back — so each mapped axis gets ONE plan
task in front of the first stage that maps on it, in that stage's own measured shape
(`python -m raincheck.daily plan <axis> /airflow/xcom/return.json`). `plan_service_date` sits
AFTER the fill for the reason gaps() prints out loud: a day the fill just completed is
buildable tonight, and a scan taken before it would defer that day by a day.

**How one item reaches a pod:** Kubernetes joins container command + args, so `stage_task`
maps `arguments` and never `cmds` — the stage's process form is untouched and the item is
its trailing argument (`... daily events 2026-08-20`, `... gapfill fill vp`). That is why
`gapfill` gained an `argv` (its kind was `--feed`, now the positional every mapped module
takes) and why the make form takes the axis as its own variable (`make gapfill KIND=vp`).

**MEASURED, not assumed (Airflow 3.2.2 + cncf-kubernetes 10.17.1, in a throwaway venv):**
- `XComArg.map(f)` serializes the callable as its own SOURCE TEXT, so the map function must
  be a module-level `def` — a lambda is not safe here.
- A mapped task carries `trigger_rule` as the plain string it was given, an unmapped one as
  the enum; `== "all_done"` is true of both, `.value` only of the second.
- **A zero-length expansion is SKIPPED** (`models/taskmap.py`: "Marking %s as SKIPPED since
  the map has %d values to expand"), and a MISSING XCom is `upstream_failed` — the operator
  turns an empty result file into no XCom at all. So `[]` reads as a quiet morning and a
  broken scan never can.
- `ti.get_task_breadcrumbs` returns exactly `{task_id, map_index, state, operator, duration}`
  (`execution_api/routes/task_instances.py`), **so it cannot name a Service date.** The
  "gold rolls only the successfully built days" row is therefore answered by the disk —
  `silver(root, day)`, the same predicate `gaps()` defers on — over the list the plan
  expanded, and NOT by joining breadcrumb states to map indexes. That correction supersedes
  the "answerable from those rows with no XCom" line in the wave-4 forward context.

## From orch 05's landing (2026-08-24, `orch05-nightly-dag`, `0e2dc1b`) — extend, do not rebuild

`dags/raincheck_daily.py` already exists and already builds its nine tasks by LOOPING the
declaration. Map by expanding that loop; write no second graph.

- The three readers, all in `dags/raincheck_stage.py`: **`stages()`** returns
  `daily.STAGES` as dicts (`name, entrypoint, retry, soft, fanout, argv`) by ast-parsing
  `src/raincheck/daily.py`, which `docker/Dockerfile` bakes beside the DAGs — the DAG image
  has no `raincheck` package and a DAG may not import one. **`command(stage)`** is the
  stage's process form (`argv` -> `module(*argv)`, else its make target).
  **`shape_of(name)`** is the pod shape, read from the placement table's own
  `raincheck.io/stages` annotation. Your fan-out axis is already in the dict:
  `stage["fanout"]` is `kind` / `service_date` / `month` / None.
- **Task ids today, in declared order:** `gapfill · gapverify · gapcheck · coldpush ·
  coldcheck · events · precip · prune · report`. Linear, every edge `all_done`, `report`
  last, `trigger_rule="all_done"` on every task.
- **`gold` is YOURS to add.** Ticket 05 deliberately did not add it: there `events` runs
  `python -m raincheck.daily events` = `daily.build`, which already reduces over
  `months(built)` inside the one pod. The moment `events` is one pod per Service date, that
  reduce has to come out — and `daily.build`'s own day loop is exactly what you replace.
- **The report task already reads mapped tasks; do not invent a channel.** It runs
  `module("daily", "report", "{{ ti.get_task_breadcrumbs(ti.dag_id, ti.run_id) | tojson }}")`.
  That SDK call returns one row per FINISHED task —
  `{task_id, map_index, state, operator, duration}` — so a mapped index arrives with its own
  `map_index`, and `daily.report` already prints it as `<stage> <index>`. "Only the
  successfully built days" is therefore answerable from those rows (`state == "success"`),
  with no XCom.
- **Retry classes are `RETRIES` in the DAG file**, keyed by the declaration's `retry`:
  transport is 3 with exponential backoff (2 min -> 20 min cap), gate is 0.
- **`raincheck_daily` is PAUSED on the cluster and must stay paused** until the pods'
  `RAINCHECK_ARCHIVE_ROOT` stops being the `/staging` emptyDir (ticket 12's cutover). Prove
  the fan-out with a manual run of a smoke-shaped DAG, never by unpausing the nightly.
- **A DAG change is an IMAGE BUILD**: `scripts/cloud-image.sh` (both tags) plus both pins
  committed. There is no git-sync.

## From the wave-4 gate (2026-08-25) — the image pin is a SINGLE-WRITER resource this wave

`scripts/cloud-image.sh` rewrites the tag in `deploy/k8s/kustomization.yaml`'s `images:`
transformer AND both `images.airflow` / `images.pod_template` sites in
`deploy/airflow/values.yaml`. Wave 4 landed cleanly partly by luck — its gate MEASURED
that `dags/` and `kustomization.yaml` were touched by orch 05 alone, so the
images:-transformer merge trap never fired. **Wave 5 runs orchestration tickets 06, 07 and
08 in parallel.** Two branches that each build an image write different shas into the same
three sites, every landing conflicts, and the last pin to land silently leaves the other
branch's image unreferenced.

**So: BUILD an image in your worktree if you need to prove your work on the cluster, but
do NOT commit the pin rewrite.** Revert those three sites before committing and name the
sha you proved against in your RUN LOG entry. The wave gate does one image build over the
landed tree and commits the pin once. Tests do not force a bump — they require only a bare
hex sha and the two `-airflow` sites agreeing, which the existing pin `d801b1462dee`
(landed on master at `b056ecb`) already satisfies.

The other files this wave's three orchestration tickets share, so you can shape your diff
to be unionable: `src/raincheck/daily.py`'s `STAGES` tuple (06 adds `gold`, 08 adds a
checkpoint stage) · the literal step list asserted at `tests/test_daily.py:240-241` ·
`dags/raincheck_daily.py` and `dags/raincheck_stage.py` · `tests/test_dag_nightly.py`.
Assert PROPERTIES, not literal lists, wherever you can.

**OWED, cluster-side (permission-blocked in this session; encoded as a MUST on the WAVE 5
GATE).** Everything above is proved in the repo and against the real Airflow/provider
versions. What no test can prove is the live sidecar handoff: the plan pod writing
`/airflow/xcom/return.json`, the operator `exec`ing it out through the `alpine:3.23.4`
sidecar it stamps (Docker Hub, unauthenticated — the ONE new external pull this ticket
adds; `pods/exec` is already granted to `raincheck-build`, verified with
`kubectl auth can-i`), and the expansion that follows. The DAG image built and self-checked
in `docker/Dockerfile`'s `dags` stage against runtime sha `d801b1462dee`; the helm upgrade
that would put it in front of a scheduler was denied. `raincheck_daily` stays PAUSED —
the proof is a manual run of a smoke-shaped DAG, never the nightly.
