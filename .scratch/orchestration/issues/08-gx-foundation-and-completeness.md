# 08 — Great Expectations foundation and the completeness suite

**What to build:** The first named suite, running as a checkpoint inside the nightly, with
browsable Data Docs at the end of the run. The suite expects on the check's **result
rows**, not on Bronze — it never re-derives a check that a module already implements, so
every threshold keeps exactly one home. Expecting on aggregate rows is also what makes
the report publishable: unexpected values get rendered into Data Docs, so a suite pointed
at Bronze would publish feed rows to a public host.

**Blocked by:** 02 (check-result rows), 05 (the nightly DAG).

**Status:** ready-for-agent

- [ ] Great Expectations installs as an optional extra in the one image; no pipeline module imports it
- [ ] An adapter turns check-result rows into a validation result that preserves all three outcomes — inconclusive is not flattened into pass or fail
- [ ] A named live-capture completeness suite expects on the hour-completeness rows: every kind x closed day is 24/24 or misses only allowlisted hours, no row reports a stale allowlist entry, and the unrecoverable subway positions are excluded by the check's own note
- [ ] The suite is scoped to the live-capture era and is never pointed at the backfill range
- [ ] It runs as an in-DAG checkpoint with zero retries on an `all_done` edge — loud, named, never blocking a later stage
- [ ] Data Docs build once at the end of a run
- [ ] The Great Expectations major version is pinned and recorded; suites are written against that API only, since the 0.x and 1.x context/checkpoint APIs differ substantially
- [ ] A suite test, skipping cleanly when the library is absent, validates a fixture batch holding one passing, one failing and one inconclusive subject, and asserts the inconclusive one is neither

## Inherited from orchestration 03 (landed 2026-08-24, b37a761)

- The batches to point suites at, with their declared column constants (assert against
  the CONSTANT, never a literal list): `gapfill.CHECK_COLUMNS["gapcheck"]` and
  `["gapverify"]` (orch 02), `cold.CHECK_COLUMNS`, `eras.CHECK_COLUMNS`, and
  `CHECK_COLUMNS` inside `scripts/backfill-verify.py`.
- Check names on disk: `gapcheck`, `gapverify`, `coldcheck`, `backfill`, `eras` —
  each at `<root>/checks/check=<name>/run=<YYYYmmddTHHMMSSZ>.jsonl`, one JSON object
  per row. `checks.write` already asserts the flat column tuple and value scalarity,
  so a suite that drifts from the constant is a crash upstream of GX, not a leak.
- Note the cold mirror writes a batch **per invocation**, and `daily.coldcheck()`
  invokes it twice on a mismatch (check, re-push, re-check). The later `run=` stamp is
  the authoritative one; both are true records of a run that happened.

## From orch 05's landing (2026-08-24, `orch05-nightly-dag`, `0e2dc1b`) — adding a stage is a THREE-part change

`dags/raincheck_daily.py` LOOPS `daily.STAGES`, so a new `Stage(...)` becomes a task, an
edge and a report line with no DAG edit at all. Three consequences, and none is optional:

- **A GATE stage MUST carry an `argv`** — `Stage("<name>", "make:<target>", "gate",
  argv=("<module>",))`. GNU make exits **2 for ANY recipe failure**, so a module rc of 1
  arrives as 2 and INCONCLUSIVE stops being distinguishable from broken (orch 03, measured
  both ways). A test in `tests/test_dag_nightly.py` fails a gate that has no `argv`.
- **The pod shape is READ from the `raincheck.io/stages` annotation in
  `deploy/k8s/raincheck/build.yaml` — add your stage name there in the SAME commit or
  `raincheck_stage.shape_of()` raises.** Verified on master: the stage template lists
  `gapfill, gapverify, gapcheck, coldpush, coldcheck, prune` and the spark template lists
  `events, gold, precip`. Yours is on neither.
- **It moves `make daily`'s printed stage list**, which the assertion at
  `tests/test_daily.py:240-241` pins as a LITERAL. Ticket 06 moves the same line in the
  same wave (it adds `gold`), so expect the wave gate to union it — assert the PROPERTY you
  care about rather than a longer literal.

There is **no git-sync**: a DAG or stage reaches the cluster only through
`scripts/cloud-image.sh` (both tags, `:<sha>` and `:<sha>-airflow`) with both pins
committed. **Wave-5 rule: do NOT commit the pin rewrite** — two branches doing so write
different shas into the same three sites and every landing conflicts. Build in your
worktree, revert the pin, name the sha you proved against in your RUN LOG entry; the gate
builds and pins once over the landed tree.

**`raincheck_daily` is PAUSED on the cluster and must stay paused** until the pods'
`RAINCHECK_ARCHIVE_ROOT` stops being the `/staging` emptyDir (ticket 12's cutover). Prove
the checkpoint with a manual run of a smoke-shaped DAG.

**Ticket 07 is live in the same wave** building the DAG-side half of the three-outcome
distinction (what an rc-2 pod BECOMES). Read its ticket file before shaping the adapter and
write your side into it — the check row stays authoritative either way, and "could not
check" is a NULL, never a 0.

## From frontend 06's landing (2026-08-25, `frontend06-discovery-contract`, `8bd82db`) — you are named in the published read contract

`src/raincheck/contract.py` renders `files/index.json`, the machine-readable discovery
document for the public read surface. Its `SCHEMA` table names this ticket verbatim:

    "docs/**": "Great Expectations Data Docs (orchestration ticket 08)"

and `contract.PROMISE[1]` freezes the `docs` family as `("docs", "docs/**", "*")` — a TREE
family, promised by its **PREFIX**, not by file names. What that means for you:

- **Adding, renaming or resharding files INSIDE `docs/**` is additive and owes NO
  `contract.CONTRACT` bump.** The file names in a tree family are the writer's to make.
- **Renaming the prefix itself, or re-homing the family, IS breaking** — the contract test
  in `tests/test_publish.py` (it asserts `PROMISE ⊆ contract.surface()`) goes red and
  demands a new frozen `PROMISE` entry beside the old one plus the Status line of
  `docs/read-api-contract.md`, all in one commit.
- **Read `docs/read-api-contract.md` before you shape the output tree** — it is the written
  contract your Data Docs are published under.

This composes with cloud 09's publish target rather than replacing it: build Data Docs into
`<data_root>/gx/data_docs`, which is where `publish --family docs` reads, and remember the
publisher's suffix **ALLOWLIST refuses anything that is not a web payload** — a Docs site
that emits a `.pickle` or a `.parquet` fails the publish loudly.

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

**FOR THIS TICKET SPECIFICALLY.** Your suites read the batch, which is authoritative, so
the three outcomes you render into Data Docs are `checks.OK` / `checks.FAIL` /
`checks.INCONCLUSIVE` off the rows themselves — never the task state, which is downstream of
them and lossy in both ways above. Your checkpoint stage will be a `daily.STAGES` entry: if
you declare it `retry="gate"` with an `argv`, it inherits the skip mapping automatically
(`skip_rc()` reads the declaration, names no stage) and a checkpoint that could not run
lands in `skipped` for free. If you declare it `transport`, it cannot say INCONCLUSIVE at
all. That is a real choice and it is yours.
