# 13 — The showcase surface

**What to build:** The portfolio view: Data Docs, a rendered DAG graph, a run summary and
a short written walkthrough, published as **static artifacts** — because the cluster has
no inbound path from the internet, so the Airflow UI is reachable by port-forward only
and cannot be the thing anyone is shown. Plus the one recorded run that demonstrates the
fan-out rather than asserting it.

**Blocked by:** 06 (fan-out), 08 (GX foundation).

**Status:** ready-for-agent

- [ ] Data Docs, a rendered DAG graph, a run summary and a written walkthrough publish to the public static host — never to the Bronze bucket
- [ ] Nothing in the portfolio view requires cluster access
- [ ] No published artifact contains feed payload; the no-payload rule on check rows is what guarantees it for the Data Docs
- [ ] One recorded run has an events map at least five Service dates wide, with its per-task durations exported
- [ ] The serial baseline is stated next to it — 1928 s for a 7-day catch-up in one session, ~275 s/day at steady state — so the improvement has a denominator


## Forward context from frontend 06 — the showcase has a front door (2026-08-25)

Landed on branch `frontend06-discovery-contract` (`8bd82db`).

**Link the contract; do not restate it.** `files/index.json` on the public host is the
machine-readable read contract — every family with its keys, content type per key, schema
pointer, cadence, writer, `Cache-Control` and gate state, the version stamps, and
`contract`, an integer a consumer refuses on. `docs/read-api-contract.md` is its human
half. Your walkthrough links both. A hand-written second copy of the family table drifts
from the generated one on the first landing, and the generated one is derived from
`publish.FAMILIES` so it cannot.

**Your `docs/**` family is already IN that contract** — a TREE family, `public,
max-age=300`, written by "the GX checkpoint's Data Docs task [orch 08]". The file names
inside the tree are yours to make and adding them owes no contract bump. What WOULD be
breaking is renaming the `docs/` prefix or moving the family, which turns
`tests/test_publish.py::test_the_contract_integer_covers_the_surface_a_consumer_binds_to`
red and demands a bump.

**Nothing is published yet** — `raincheck-public` does not exist. That is a [YOU] item in
STATUS, not your blocker to solve.


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

**For the showcase specifically: "events mapped >=5 dates wide" is a real, renderable thing
now.** The rendered graph has one `events` box that expands to N, and the run summary can
honestly say how many pods a night bought. The graph must show the two `plan_<axis>` tasks
and the `gold` reduce — a picture of the old nine-task chain would be a picture of a graph
that no longer exists.
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

**FOR THIS TICKET SPECIFICALLY.** When you show a run: `skipped` on a GATE means COULD NOT
CHECK and must never be drawn as a pass or as a failure; `skipped` on a non-gate means there
was nothing to do. The run's closing lines already say which — `daily: <stage> INCONCLUSIVE`
and a `daily: INCONCLUSIVE - <names>` summary line, distinct from `daily: FAILED - <names>`
— and the DagRun's own state reads `success` on an inconclusive run, so do NOT source the
run's verdict from it.
## FROM ORCH 08's LANDING (2026-08-25, `orch08-gx-foundation`) — the foundation you write into

**GX IS PINNED TO MAJOR VERSION 1** (`pyproject`: `gx = ["great-expectations>=1,<2"]`,
installed in the one image by `docker/Dockerfile`; measured against **1.21.0**). Write
against the 1.x API only — 0.x's DataContext/checkpoint API is a different thing. Nothing
imports GX at module level, `raincheck.gx` included, so `import raincheck.gx` works on a
checkout without the extra and a missing library is INCONCLUSIVE rather than a crash.

**TO ADD A SUITE: APPEND ONE `Suite` TO `gx.SUITES`. That is the whole integration.**
`gx.run()` finds the batch, asserts the columns, refuses the era, splits the outcomes,
validates and renders.

    Suite(name, check, columns, expectations, era=None)
        name          becomes a Data Docs page and a URL segment -> NO SPACES
        check         the producer on disk: <root>/checks/check=<check>/run=<stamp>.jsonl
        columns       THAT producer's own CHECK_COLUMNS constant, never a literal list
        expectations  () -> list[gxe.Expectation]  (a CALLABLE: building one imports the
                      optional extra, and importing the module must not)
        era           the column holding an ISO day, if any; values before
                      `gx.ERA_START` (= gapfill.START) are REFUSED, not reported.
                      **Leave it None on the backfill census — that check IS the other era.**

    Result(suite, check, ok, failed, inconclusive, detail)   # frozen; three tuples, disjoint
        .outcome -> checks.OK | FAIL | INCONCLUSIVE  (checks.rc's precedence: a real
                    failure outranks a not-run check, a not-run check is never an ok)
    gx.batch(root, check) -> Path | None   # the NEWEST run= stamp (the cold mirror writes
                                           # one batch PER INVOCATION and daily.coldcheck()
                                           # invokes it twice on a mismatch — the later
                                           # stamp is the verdict, and both are true records)
    gx.rows(path, columns, era=None) -> list[dict]
    gx.context(docs) / gx.validate(ctx, suite, rows) / gx.run(root, suites) / gx.rc(results)

**DATA DOCS: `<data_root>/gx/data_docs`** (`gx.docs_dir(root)`), which is exactly
`publish.FAMILIES["docs"].src()` — cloud 09's target, published to `docs/**`. Built ONCE
at the end of a run by `gx.run()`.

**THE THREE-OUTCOME MAPPING, AND THE TRAP INSIDE IT.** INCONCLUSIVE rows are HELD OUT of
the frame GX sees: an expectation has exactly two answers, so anything inside the batch has
already been flattened into two. **THEREFORE EVERY EXPECTATION YOU WRITE MUST BE PER-ROW,
NEVER AGGREGATE.** The held-out rows SHORTEN the frame, so an aggregate expectation sees a
short batch and fails — rendering "could not check" as a FAILURE. This is measured, not
predicted: orch 08's first draft used `ExpectColumnDistinctValuesToEqualSet` over the kinds
and went red the moment a kind came back INCONCLUSIVE. **A batch-level claim (coverage, row
count, "four rows every run") must be made over the WHOLE batch before the split — in your
suite's own code, not as an expectation.** Mirror fact: GX's own `success` decides the
outcome and the named subjects only say WHICH, so a suite that fails without naming a row
is charged to `<check batch>` rather than reading as a pass.

**EXPECT ON THE PRODUCER'S VERDICT, NOT ON A COPY OF ITS RULE.** `gapfill.check()` is
`FAIL if fillable or stale else OK`, so orch 08's completeness suite expects
`outcome == checks.OK` and does NOT restate `fillable == "" and stale_dead == ""`. Same
discipline for yours: the thresholds keep one home in the module.
`unexpected_index_column_names=["subject"]` (already set in `gx.RESULT_FORMAT`) is what
lets a failing expectation NAME the check subjects it rejected.

**THE STAGE ALREADY EXISTS: `gxcheck`, LAST in `daily.STAGES`, a GATE with
`argv=("gx",)`** — so orch 07's `skip_rc()` maps its rc 2 onto a `skipped` task for free,
and `deploy/k8s/raincheck/build.yaml`'s `raincheck.io/stages` already lists it on the
`raincheck-stage` template. **Adding a suite therefore adds NO stage, NO annotation and NO
DAG edit** — it does not move `make daily`'s printed step list either (that assertion is
now a PROPERTY derived from `daily.STAGES`, not a literal).

**MEASURED, so you do not have to:** a Data Docs site is 23 files / ~4 MB, ten of them
`.otf` font faces — `publish.PUBLISHABLE` gained `.otf` because master's allowlist refused
the whole family on a font. `build_data_docs()` rebuilds the whole site (a retired suite's
pages disappear), so a validation page's URL carries the run's timestamp and does not exist
tomorrow; `docs/index.html` is the stable entry point. Data Docs are POSIX-ONLY —
`gx.run()` refuses an object-store root outright, the same list as `precip_live`, `export`
and `live_export`. `ExpectColumnValuesToBeBetween` cannot compare ISO date STRINGS.

**WHAT YOU ARE PUBLISHING, EXACTLY.** `<data_root>/gx/data_docs` -> `docs/**`, 23 files /
~4 MB for one suite, and it is a static site in the ordinary sense: `.html .css .otf .png
.svg .gif .ico`. It carries check-RESULT rows only — counts, dates, kinds, hour labels,
ratios — which is what makes it publishable; no feed payload can reach it, and that is
structural (`checks.write` asserts value scalarity and the suites never touch Bronze).

**LINK `docs/index.html`, NEVER A VALIDATION PAGE.** `build_data_docs()` rebuilds the whole
site every run and a validation page's URL contains that run's timestamp, so any deep link
you write into the walkthrough is dead the next night. Already written into
`docs/read-api-contract.md`.

**THE RUN'S VERDICT IS NOT THE DagRun STATE** (orch 07): a DagRun has no third state, so a
nightly whose only red is an inconclusive gate reads `success` at the run level while its
`report` task reads `skipped`. `gxcheck` is a declared GATE, so its `skipped` means COULD
NOT CHECK — a suite that could not run, e.g. no batch on disk or the optional extra absent —
and never "nothing to do". Source the verdict from the `report` task's lines, or from the
check rows.
