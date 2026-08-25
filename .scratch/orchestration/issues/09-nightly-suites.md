# 09 — The remaining nightly suites

**What to build:** The other invariants that run every night become named suites —
fill fidelity, the cold mirror, and schema eras — each with its placement stated: a gate
inside the DAG, or a post-run report. One trap to avoid: the map quotes a 0.85-1.2x
same-day band for fidelity, but that is a **measured result** from the backfill work, not
the threshold the module enforces (which is roughly an order of magnitude on rows and ~3x
on key coverage). A suite that expects tighter than the code makes the suite the real
gate and silently changes what passes.

**Blocked by:** 03 (remaining check producers), 08 (GX foundation).

**Status:** ready-for-agent

- [ ] A fidelity suite expects on the verifier's rows at the bands the module actually enforces — non-empty filled hour, row-count ratio and distinct-key coverage in band, archiver columns present as a typed superset
- [ ] It fails when a kind is inconclusive on a day that **has** both a filled and a captured hour — an inconclusive there means the pair-finding broke
- [ ] Tightening the band to the observed figure, if wanted, is raised as its own evidence-backed change to the module; this suite does not tighten it on the side
- [ ] A cold-mirror suite reports and never gates
- [ ] A schema-era suite expects column **presence**, not counts
- [ ] Each suite records its placement explicitly: in-DAG gate or post-run report

## Inherited from orchestration 03 (landed 2026-08-24, b37a761)

Both of this ticket's non-fidelity suites now have their producers shipped — expect on
these rows, do not re-derive the checks.

- **Cold mirror**: check `coldcheck`, columns `CORE + ("kind", "differing")`, **one row
  per top-level `archive/` prefix**, read off disk — the row set grows with a new kind,
  so expect on the shape, not on a fixed kind list. `differing` is **NULL, never 0**, on
  every could-not-check path (aws non-zero, unconfigured, nothing local to mirror, no
  `archive/` at all). Reports, never gates — that placement is unchanged.
- **Schema eras**: check `eras`, columns `CORE + ("reader", "kind", "day", "era_cols",
  "missing")`, **four rows every run** — subjects `duck vp`, `spark vp`, `duck tu`,
  `spark tu`. Expect on `missing == ""` (column PRESENCE). A row whose `day` is NULL is
  INCONCLUSIVE: no date dir mixed part schemas, so the run could not tell a union reader
  from a narrow one, and it must not read as a pass. `eras.ERA_COLS` is the one home for
  the column names — expect through it, never a restated list.
- **This ticket also decides the era check's placement.** `make eras` exists; it is not
  in `daily.STAGES` today (adding it moves daily's printed stage list).
- Reading the batch: `make <check>` returns 0 or 2 for everything, because GNU make
  exits 2 on any recipe failure. Use the module or the persisted rows.

## From orch 05's landing (2026-08-24, `0e2dc1b`) — what the placement decision now costs

Adding `eras` to `daily.STAGES` puts it in the nightly DAG **automatically**:
`dags/raincheck_daily.py` loops the declaration, so a new `Stage(...)` becomes a task, an
edge and a report line with no DAG edit. Three consequences travel with that.

- **A gate MUST carry an `argv`** — `Stage("eras", "make:eras", "gate", argv=("eras",))` —
  because GNU make exits 2 for any recipe failure and `make eras` cannot tell its rc 1 from
  its rc 2. `tests/test_dag_nightly.py` fails a gate that has none.
- **The pod shape is read from `deploy/k8s/raincheck/build.yaml`'s `raincheck.io/stages`
  annotation**, so add the stage name there in the same commit or `shape_of()` raises.
- **There is no git-sync**: the change reaches the cluster only through
  `scripts/cloud-image.sh` (both tags) with both pins committed.

And the standing warning still binds: it moves `make daily`'s printed stage list, which
`tests/test_daily.py` pins.


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

**For your suites specifically:** a stage that fans out writes its check batch once PER POD.
`gapverify` now produces five batches per run (one per kind) where it produced one, so expect
over the batch SET, never on "the batch". And the standing warning about `make daily`'s
printed stage list is softer now: orch 06 rewrote
`tests/test_daily.py::test_the_driver_names_its_steps_from_the_declaration` as a PROPERTY
(declared order, only the axes this runtime supplies expanded), so adding a stage no longer
edits a literal there.
