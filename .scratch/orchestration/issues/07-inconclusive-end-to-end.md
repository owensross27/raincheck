# 07 — INCONCLUSIVE end to end

**What to build:** The third outcome survives the whole path. A stage that could not
check something lands in a task state visibly distinct from both success and failure, and
the run summary counts failures and inconclusives apart. This is the distinction five
incidents were spent creating: a dead endpoint rendered as a data gap sends someone
hunting a phantom, and a check that did not run rendered as OK hides a real one.

**Blocked by:** 02 (check-result rows), 05 (the nightly DAG).

**Status:** ready-for-agent

- [ ] An rc=2 from any stage renders as a task outcome distinct from both success and failure
- [ ] No configuration of this mapping renders inconclusive as failed, and none renders it as ok — that property is the ticket
- [ ] The report task counts and names failures and inconclusives separately; neither number is inflated by the other
- [ ] The check's own row stays the authoritative record; the task state is a rendering of it
- [ ] A test drives all three outcomes through the mapping and asserts the resulting states differ

## Inherited from orchestration 03 (landed 2026-08-24, b37a761)

- **Five producers now emit inconclusive rows**, not two: `gapcheck`, `gapverify`,
  `coldcheck`, `backfill`, `eras`. The new ones report INCONCLUSIVE when the remote
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
