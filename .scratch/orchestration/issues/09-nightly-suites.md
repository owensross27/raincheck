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

## From orchestration 07's landing (2026-08-25, `orch07-inconclusive`, `8822ed8`) — the exact mechanism that creates the skip

**The three outcomes now survive the whole path, and the mechanism is one operator kwarg.**
A task state carries no rc, so the rendering is `KubernetesPodOperator(skip_on_exit_code=N)`
— the operator reads the BASE container's `state.terminated.exit_code` in `cleanup()` and
raises `AirflowSkipException` BEFORE it raises `AirflowException`, landing the task in
`skipped`: the only terminal state Airflow has that is neither success nor failure.

    daily.INCONCLUSIVE_RC = 2            # a LITERAL in the declaration - the DAG image has
                                         # no raincheck package to import it from
    raincheck_stage.constant("INCONCLUSIVE_RC") -> 2     # ast-read from the baked daily.py
    raincheck_stage.skip_rc(stage) -> int | None         # the constant iff
                                         #   stage["retry"] == "gate" and stage["argv"]
    daily.verdict(failed, inconclusive=()) -> exits 1 / INCONCLUSIVE_RC / 0
    daily.GATES                          # frozenset of the declaration's own gate names

**Only a GATE's rc 2 and only a GATE's `skipped` is a verdict — both directions matter.**
A bare `make` target exits 2 for ANY recipe failure, so wiring the skip onto one would file
a broken recipe as "could not check"; and `skipped` is also where a ZERO-LENGTH dynamic
expansion lands, so counting every skip would report a quiet morning as an inconclusive
nightly. `daily.report()` and `daily.main()` both apply `GATES`.

**MEASURED, and it corrects the "five producers" line every orchestration ticket carries:
`gapcheck` does NOT emit INCONCLUSIVE rows.** `gapfill.check()` holds exactly one
`checks.Row(...)` and its outcome is `FAIL if fillable or stale else OK` — no third branch.
The producers that can emit an inconclusive row are FOUR: **`gapverify`, `coldcheck`,
`backfill`, `eras`.** A suite that expects `gapcheck` inconclusives is expecting rows that
cannot exist. (On the nightly graph as it stands, `gapverify` is also the only STAGE that
can exit 2: `coldcheck`'s task returns 0 on every path by design, and `eras`/`backfill` are
not in the declaration at all.)

**The row stays the record and the task state is only a rendering — and here is where that
stops being a slogan.** On a gate, a zero-length expansion and an rc-2 produce the SAME
task state; `<root>/checks/check=<name>/run=<ts>.jsonl` is the only thing that tells them
apart. Also: this ticket renders no MEASURE at all, only states and names, so the
"could not check is a NULL, never a 0" obligation on `differing` / `hours_seen` lands
squarely on whatever renders the rows next. Re-read on disk, not copied: `cold.py:76`
`{"differing": None}` · `gapfill.py:389` `dict.fromkeys(CHECK_COLUMNS["gapverify"][4:])` ·
`eras.py:92` `{"missing": None}` · `backfill-verify.py:116` `{"hours_seen": None}`.

**Two ceilings, so nobody rediscovers them.** (1) A DagRun has no third state: a run whose
only red is an inconclusive gate reads `success` at the RUN level while its `report` task
reads `skipped`. (2) `skip_on_exit_code` does NOT appear in the serialized DAG (nor do
`startup_timeout_seconds`, `on_finish_action` or `retries`) — Airflow 3.2.2 serializes a
whitelist and the worker re-parses the DAG file, so you cannot verify this mapping by
reading the serialized form. Assert it on the BUILT operator.

**And the fact that makes the whole thing work, which is not obvious and is one rename
away from silent failure:** the placement table calls its container `stage`,
`base_container_name` is `base`, and the operator stamping `pod_template_dict` RENAMES it
while keeping the stage's command and its measured 250m/512Mi. If that rename stopped, the
exit-code lookup would return `None` and every inconclusive would land as a failure with no
test noticing. Verified on the cluster 2026-08-25: real pods report `container=base`.

**FOR THIS TICKET SPECIFICALLY.** Expect FOUR inconclusive-capable producers, not five —
`gapcheck` has no such row and never will unless someone adds the branch. Write the suite
against `checks.INCONCLUSIVE` in the rows; a suite keyed on task state cannot distinguish a
gate that could not check from a gate whose expansion was empty.
