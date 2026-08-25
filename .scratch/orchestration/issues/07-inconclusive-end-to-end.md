# 07 — INCONCLUSIVE end to end

**What to build:** The third outcome survives the whole path. A stage that could not
check something lands in a task state visibly distinct from both success and failure, and
the run summary counts failures and inconclusives apart. This is the distinction five
incidents were spent creating: a dead endpoint rendered as a data gap sends someone
hunting a phantom, and a check that did not run rendered as OK hides a real one.

**Blocked by:** 02 (check-result rows), 05 (the nightly DAG).

**Status:** DONE (2026-08-25, branch `orch07-inconclusive`)

- [x] An rc=2 from any stage renders as a task outcome distinct from both success and failure
- [x] No configuration of this mapping renders inconclusive as failed, and none renders it as ok — that property is the ticket
- [x] The report task counts and names failures and inconclusives separately; neither number is inflated by the other
- [x] The check's own row stays the authoritative record; the task state is a rendering of it
- [x] A test drives all three outcomes through the mapping and asserts the resulting states differ

## What shipped — the exact mechanism that creates the skip

`KubernetesPodOperator(skip_on_exit_code=...)`. It is the ONLY native tri-state Airflow
has: the operator reads the BASE container's `state.terminated.exit_code` in `cleanup()`
and raises `AirflowSkipException` before it raises `AirflowException`, so the task lands in
`skipped` — neither success nor failure. Nothing else in the graph changed shape.

- `daily.INCONCLUSIVE_RC = 2` — a LITERAL in the declaration, because the DAG image has no
  raincheck package and `raincheck_stage.py` can only `literal_eval` what it parses out of
  the baked `daily.py`. `tests/test_daily.py` derives it from `checks.rc([an INCONCLUSIVE
  Row])`, so the mirror cannot drift quietly.
- `raincheck_stage.constant(name)` — a module-level literal from the declaration, read the
  way `stages()` reads `STAGES`.
- `raincheck_stage.skip_rc(stage) -> int | None` — `INCONCLUSIVE_RC` when
  `stage["retry"] == "gate" and stage["argv"]`, else `None`. The nightly passes it per
  declared stage; the `report` task passes `constant("INCONCLUSIVE_RC")` directly, because
  its own exit line IS the run's verdict.
- `daily.verdict(failed, inconclusive=())` — still the ONE home of the exit sentence, now
  with `checks.rc()`'s precedence as its exit code: 1 if anything failed, else
  `INCONCLUSIVE_RC`, else 0. `report()` feeds it from task states, `main()` from stage rcs.
- `daily.spawn(argv)` + `call()` — a gate runs its declared argv as its own process (the
  same command its task pod runs), and a BARE make target's 2 is collapsed to 1 before
  anything can read it as a verdict.
- `daily.GATES` — the declaration's own gates. Only a gate's rc 2, and only a gate's
  `skipped`, is a verdict.

## Measured, and it corrects this ticket's own inherited section

**`gapcheck` does NOT emit INCONCLUSIVE rows.** Its `check()` in `src/raincheck/gapfill.py`
has exactly one `checks.Row(...)` and its outcome expression is `FAIL if fillable or stale
else OK` — there is no third branch. The inherited "five producers" list is FOUR:
`gapverify`, `coldcheck`, `backfill`, `eras`. `gapcheck` is a gate that emits ok/fail only,
and can therefore never exit 2 today. It still carries the mapping (a gate is a gate), and
that is defensive rather than dead.

**On the nightly graph as it stands, `gapverify` is the only stage that can actually exit
2.** `coldcheck`'s task runs `python -m raincheck.daily coldcheck`, and `daily.coldcheck()`
returns 0 on every path by design (a post-push mismatch is drift, not loss). `eras` is
deliberately not in the declaration and `backfill` is a script, so their rc-2 paths are not
in this graph at all.

**The NULL-not-0 rule is untouched and was re-read on disk**, not copied: `cold.py:76`
`{"differing": None}`, `gapfill.py:389` `dict.fromkeys(CHECK_COLUMNS["gapverify"][4:])`,
`eras.py:92` `{"missing": None}`, `backfill-verify.py:116` `{"hours_seen": None}`. This
ticket renders no measure at all — only states and names — so it cannot show one as a
measured zero. The obligation passes to whatever renders the rows (orch 08/09/13).

## Two ceilings, stated rather than discovered

1. **A DagRun has no third state.** A run whose only red is an inconclusive gate leaves
   every task terminal and nothing failed, so the RUN reads `success` while the `report`
   task reads `skipped` and its log names the stage. The distinction lives on the TASK and
   in the rows. Airflow goes no further.
2. **On a GATE, a zero-length dynamic expansion and an rc-2 are the same task state.** Once
   orch 06 lands, `gapverify` maps over `kind`; an empty expansion is marked SKIPPED by
   `airflow/models/taskmap.py` with no pod at all. `report()` cannot tell that from a pod
   that exited 2 — the batch under `<root>/checks/check=gapverify/` is what tells them
   apart, which is exactly why the row and not the state is the record. (Non-gate skips are
   already excluded: without that guard a quiet morning with no Service date to build would
   report as an inconclusive nightly, every quiet morning.)

## Proved on the cluster (2026-08-25), not only in a test

Four pods built by the nightly's OWN operator (`build_pod_request_obj()` off the
`gapverify` task), applied to ns `raincheck`, same `skip_on_exit_code` on all four — only
the exit code differed:

    orch07-rc-0        phase=Succeeded  exitCode=0  container=base  -> task state success
    orch07-rc-1        phase=Failed     exitCode=1  container=base  -> task state failed
    orch07-rc-2        phase=Failed     exitCode=2  container=base  -> task state SKIPPED
    orch07-real-gate   phase=Failed     exitCode=2  container=base  -> task state SKIPPED

`orch07-real-gate` ran the real thing, `python -m raincheck.gapfill verify` on the
`/staging` emptyDir, and its log is the real INCONCLUSIVE detail — "verify vp: no filled
hour with an archiver hour on the same day yet", five kinds. The three states were produced
by feeding each REAL remote pod through `KubernetesPodOperator.cleanup()`. All four pods
deleted afterwards.

**The non-obvious fact that makes any of it work: the operator RENAMES the placement
table's container.** `build.yaml` calls it `stage`; `base_container_name` is `base`; the
operator stamping `pod_template_dict` renames it, keeping the stage's command and the
measured 250m/512Mi. If it stopped renaming, `skip_on_exit_code` would silently never fire
and every inconclusive would land as a failure. Pinned by a test.

## Inherited from orchestration 03 (landed 2026-08-24, b37a761)

- ~~**Five producers now emit inconclusive rows**, not two: `gapcheck`, `gapverify`,
  `coldcheck`, `backfill`, `eras`.~~ **CORRECTED 2026-08-25 by this ticket, measured:
  FOUR — `gapverify`, `coldcheck`, `backfill`, `eras`. `gapfill.check()` (the `gapcheck`
  producer) holds exactly one `checks.Row(...)` whose outcome is `FAIL if fillable or
  stale else OK`; it has no inconclusive branch.** The rest of this bullet stands: The new ones report INCONCLUSIVE when the remote
  listing failed (cold mirror, backfill census), when cold storage is unconfigured or
  there is nothing local to mirror, when no date dir mixes part schemas (era check —
  the run could not distinguish a union reader from a narrow one), and when the box
  has no JVM (the two `spark` era rows).
- Every one of those is "could not check", never a data gap: `differing` and
  `hours_seen` are **NULL on those rows, not 0**. A rendering that shows them as a
  measured zero is the conflation this ticket exists to prevent.
- `make <target>` cannot carry the distinction at all: GNU make exits **2 for any
  recipe failure**, so a module rc of 1 arrives as 2. Read the module's own rc or the
  persisted batch.

## From orch 05's landing (2026-08-24, `0e2dc1b`)

- **The two rc-carrying gates already invoke the module.** `daily.Stage` gained an `argv`
  field and every GATE carries one, so the nightly's `gapverify` / `gapcheck` tasks run
  `python -m raincheck.gapfill verify|check` and their pods really do exit 1 vs 2. What
  Airflow makes of that rc is still this ticket's.
- **The report task is already INCONCLUSIVE-shaped.** `daily.report` prints a task's raw
  STATE for anything that neither succeeded nor failed — never `ok` — and keeps it out of
  the failure list. So a task you land in `skipped` renders as `skipped` in the run's
  closing lines with no change to `report()`; what you have to build is the thing that
  CREATES the skip.
- **Task-pod remote logging is VERIFIED WORKING (measured, not inherited).** The prefix was
  empty before the run; after it holds
  `s3://raincheck-bronze/airflow-logs/dag_id=raincheck_smoke/run_id=orch05-logcheck-2/task_id=warm/attempt=1.log`
  (15,472 B). Debug a task pod through R2 rather than `kubectl logs` — and a SUCCEEDED stage
  pod is deleted immediately while a FAILED one is kept.

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
