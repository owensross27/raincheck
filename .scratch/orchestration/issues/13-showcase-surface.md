# 13 — The showcase surface

**What to build:** The portfolio view: Data Docs, a rendered DAG graph, a run summary and
a short written walkthrough, published as **static artifacts** — because the cluster has
no inbound path from the internet, so the Airflow UI is reachable by port-forward only
and cannot be the thing anyone is shown. Plus the one recorded run that demonstrates the
fan-out rather than asserting it.

**Blocked by:** 06 (fan-out), 08 (GX foundation).

**Status:** DONE (2026-08-25, `orch13-showcase-surface`) - see the close-out at the bottom.

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

## Forward-context from DESTINATION-PLAN.md (copied verbatim by the WAVE 5 GATE PART 2, 2026-08-25, from this ticket's summary line in waves/wave-3-plus.md)

**FROM DESTINATION-PLAN (2026-08-25), one line:** two more static families reach the host — `files/geo/**` (flood-build 19 / frontend2 03) and `files/summary/**` (frontend2 04) — both listed in `index.json` automatically; the showcase links them when they exist and re-describes neither.

## CLOSE-OUT — DONE (2026-08-25, branch `orch13-showcase-surface`)

**Status: DONE.** Landed as `src/raincheck/showcase.py` + `tests/test_showcase.py` (+35),
a sixth `publish.FAMILIES` entry, `make showcase`, and one committed run record.

**THE THREE ARTIFACTS, and what each is rendered FROM.**

    web/showcase/index.html   the walkthrough      <- the declaration + the record + FAMILIES
    web/showcase/graph.svg    the task graph       <- daily.STAGES + the DAG file's MAPPED
    web/showcase/run.json     one recorded run     <- that run's own Airflow task logs

They publish as family **`showcase`** (`showcase/**`, a TREE, `public, max-age=300`,
prefix `showcase/`), which is why the file names above are this writer's to make and a
fourth artifact owes no `contract.CONTRACT` bump. `files/index.json` lists the family
automatically (`test_the_index_covers_every_family_including_itself` passes unchanged),
`docs/read-api-contract.md` gained its row, and `contract.SCHEMA` points the tree at this
module. `publish.plan("showcase")` accepts the rendered tree - 3 objects, the right
content types - and **nothing was published**: `raincheck-public` does not exist ([YOU]).

**THE SURFACE, for whoever records the next run.**

    showcase.tasks() -> list[Task(id, kind, stage, axis)]   kind: plan | stage | report
    showcase.mapped_axes() -> tuple[str, ...]               ast-read from dags/raincheck_daily.py
    showcase.graph_svg() -> str                             self-contained, `rc-`-prefixed CSS
    showcase.run_record(log_dir, label) -> dict             label: probe | shadow | nightly
    showcase.record(path=None) -> dict                      newest research/orch-13-run-*.json
    showcase.build(rec, out=None) -> list[Path]             out defaults to the family's src()

    make showcase                                           re-render from the newest record
    python -m raincheck.showcase --logs <dir> --label shadow    record a run, then render

**THE GRAPH IS RENDERED FROM `declared()`, AND THE DERIVATION IS CHECKED RATHER THAN
TRUSTED.** `tasks()` repeats the DAG file's own loop (it has to - importing that file means
importing Airflow), and `test_the_rendered_graph_is_the_graph_airflow_builds` asserts
`[t.task_id for t in dag.tasks] == [t.id for t in showcase.tasks()]` against the DAG object
Airflow really builds. RUN FOR REAL in a throwaway venv on Airflow 3.2.2 +
cncf-kubernetes 10.17.1: **35 passed / 0 skipped**. The picture is the 14-task graph -
`plan_kind · gapfill · gapverify · gapcheck · coldpush · coldcheck · plan_service_date ·
events · gold · precip · prune · eras · gxcheck · report` - with the two mapped stages and
`events` drawn as stacks, `gold` labelled the reduce, `precip`'s declared `month` axis
labelled as deliberately one pod, the five gates outlined apart, and `plan_*`/`report`
dashed because they are in the graph and not in the declaration.

**THE VERDICT IS NEVER THE DagRun STATE.** `run.json` carries no run state at all. The
verdict is the closing line `daily.verdict()` wrote, lifted out of the report task's log
(the stage pod's stdout arrives under a `[base] ` prefix); a per-stage `daily: <name>
<outcome> in Ns` line is deliberately not matched. A run with no `report` task says so
rather than inventing one.

**ONE RECORDED RUN, AND IT IS A PROBE - MEASURED, NOT ASSUMED.** `raincheck_daily` has
NEVER RUN: `s3://raincheck-bronze/airflow-logs/` holds exactly `dag_id=raincheck_gateprobe`
and `dag_id=raincheck_smoke` and nothing else, and orch 11's shadow has no RUN LOG entry.
So the record is the wave-5 gate's probe, labelled `probe`, and the page says in its own
words that a probe is not a nightly. From its nine kept logs:
**9 task instances / 18 burst pods / 275 s wall / 336 s of task time**, `gate_rc2` skipped
with `exit_code 2` beside `gate_rc1` failed with `exit_code 1` (orch 07's rendering, on a
real scheduler), `mapped_a` three wide, and `mapped_empty` in NO row because a zero
expansion is never scheduled and writes no log. **The "events mapped >= 5 Service dates
wide" checkbox is NOT ticked**: the widest map is measured into the record
(`totals.widest_map`) and the page says the declared width is not what this run shows.

- [x] Data Docs, a rendered DAG graph, a run summary and a written walkthrough publish to
      the public static host, never to Bronze — the family is `showcase` on
      `raincheck-public`; `docs/**` was already cloud 09's and the walkthrough LINKS
      `docs/index.html`, never a validation page
- [x] Nothing in the portfolio view requires cluster access — three static files, and the
      page says why that is structural
- [x] No published artifact contains feed payload — `run.json`'s instances are a frozen
      eight-field list (a test pins it), so no pod name, node address or log prose reaches
      the host; the Data Docs half is orch 08's structural argument, restated as a link
- [x] **One recorded run has an events map at least five Service dates wide** — **MET
      2026-08-26 by orch 12**, and measured from the logs rather than typed:
      `research/orch-13-run-shadow-2026-08-12-6d-125210.json` has **`totals.widest_map` 6**
      (9 task instances / 18 pods / 1365.9 s wall / 5705.9 s of task time), from
      `raincheck_shadow` run `shadow-2026-08-12-6d-125210` — six real Service dates
      (2026-08-12..08-17), one `events` pod each, all six `success`. `verdict.lines` is
      eight `daily: OK`s taken from `daily.verdict()`, never from the DagRun state.
      **RECORDED AS `--label shadow`, NOT `--label nightly`, and that was deliberate.**
      orch 12's box said `--label nightly` "is the only label that lets the page drop its
      width caveat". True, and it is the wrong label: this module refuses the substitution
      in its own words (`showcase: --logs needs --label probe|shadow|nightly - a run that
      is not a nightly must not be shown as one`), and `SCOPE["nightly"]` renders "This is
      the nightly.", which a shadow is not.
      **SO A DEFECT IS LEFT FOR YOU, and it is one line.** `page()` computes
      `width = ("." if run["label"] == "nightly" and tot["widest_map"] >= 5 else ...)`, so
      this record — six Service dates wide, from the nightly's own build shape over the
      nightly's own gap scan — still prints "the fan-out at its declared width … is not
      what this run shows", which is now FALSE. The caveat is keyed on the LABEL when the
      claim it guards is about the WIDTH; `SCOPE[label]` already says separately what a
      shadow is, so the two do not need to be welded together. The comment above it — "only
      a real nightly's gap scan can produce five" — is what has been disproved: the shadow's
      `plan_service_date` pod runs the identical `daily plan service_date` scan and produced
      six. **Fix the predicate, not the label.**
      **FIXED — WAVE 8 GATE, PART 1 (2026-08-26, `32176c4`):** `showcase.page()` now keys
      the caveat on `tot["widest_map"] >= 5` alone (label conjunct dropped; the disproved
      only-a-nightly comment corrected). `tests/test_showcase.py` 34 passed / 1 skipped;
      the three-wide fixture's both-labels caveat assertion still holds. Nothing on this
      ticket remains open.
- [x] The serial baseline is stated next to it — `SERIAL = 1928 s / 7 service days /
      ~275 s/day`, on the page beside the run, with the reason both numbers travel together

**THE TWO SUITE HAND-OFFS ORCH 10 LEFT: I TOOK NEITHER, AND THE REASON IS MEASURED RATHER
THAN INHERITED.** `flood-build 19`'s `stormwater_extent` cannot be expected on because it
does not exist: branch `floodbuild19-stormwater-extents` has **ZERO commits** (its tip IS
master `90ce33d`), it is not pushed, `git grep stormwater_extent` over its `src/` returns
nothing, and it has no RUN LOG entry - so there is no batch, no `CHECK_COLUMNS` constant
and no shape to write a `Suite` against. Inventing one is the exact thing orch 10 refused.
`flood-build 21a`'s `route_flood` is wave 7 and has no ticket file at all. **Both are still
owed, and the recipe is unchanged**: one `Suite(...)` appended to `gx.NON_NIGHTLY` plus a
`make gx<name>` target; `Suite.whole` is the seam for a batch-level claim and a named run
already renders into `<root>/gx/docs-<suite>`. The wave-8 gate should read this paragraph
as the gap, not as a decision.

**MUTATION ROUND: 22 mutants, 22 KILLED**, pristine control green before AND after, tree
empty after every restore. One of them earned the round on its own: **"read identity off
`rows[0]` instead of the first line that HAS a `task_id`" killed 15 tests only because the
fixture was fixed first to open the way a real log opens.** A real Airflow task log's first
line is the runner's `::group::Pre Execute`, which carries no `task_id`, no `map_index` and
no `dag_id`; the first draft of the fixture started with an identity-carrying line, and
under that fixture the mutant was invisible while the parser would have died on every real
log. Also killed: the skip/error precedence swapped (an INCONCLUSIVE gate logs BOTH, so
reading the error first turns every could-not-check into a failure), `MAPPED` ignored, the
plan task moved behind its stage, the report dropped from the picture, the gate outline
dropped, the stack dropped, the first attempt preferred to the newest, `widest_map` faked,
2 pods per instance flattened to 1, every `daily:` line read as a verdict, INCONCLUSIVE
dropped from the verdict pattern, a probe described as a nightly, the width caveat
suppressed, the non-nightly suites shown as published, the baseline dropped, the family
table restated, the whole log head published, the tree turned into a fixed file list, and
the renderer writing somewhere the publisher does not read.

**WHAT I DID NOT DO, and why.** No image was built and **the image pin was not touched**
(single-writer for the wave). Nothing was published (no bucket). `docs/read-api-contract.md`
is named on the page by its repo path rather than linked, because `.md` is not in
`publish.PUBLISHABLE` and the repo is not public (measured: github.com/owensross27/raincheck
returns 404) - a dead link would be worse than a citation, and widening rule 2's allowlist
for one link is a decision, not a fix. `files/geo/**` and `files/summary/**` are not
mentioned by name: the "what is on the host" list is DERIVED from `publish.FAMILIES`, so
they appear the moment they land and are re-described never.
## FROM flood-build 19 (2026-08-25, branch `floodbuild19-stormwater-extents`) — THE MISSING HALF OF THE PARAGRAPH ABOVE

**Read this beside orch 13's own "I TOOK NEITHER" paragraph, which is correct as written
and is not being contradicted.** When orch 13 measured, this branch had ZERO commits and
its tip WAS master `90ce33d` — so there was no batch, no `CHECK_COLUMNS` and nothing to
write a `Suite` against, exactly as it says. That is no longer true: the batch exists, it
has been run on the real root, and the shape below is measured rather than proposed.

**Nobody is being asked to reopen orch 13.** This section exists because its file is where
anyone re-opening the suite question looks, and because the wave-8 gate was told to read
that paragraph as the gap — it should now read this one as the gap CLOSED on the input
side and still OPEN on the suite side. flood-build 21a's `route_flood` is the other half
and is untouched: wave 7, no ticket file, still owed.

**IT IS NOT NIGHTLY.** `make stormwater-extent` reads a sha-pinned snapshot that changes
only when DEP republishes and the pin is re-cut, so a nightly suite over it would judge
last night's file every night forever. It belongs in **`gx.NON_NIGHTLY`** beside
`backfill-census` and `ref-canaries`, fired by its own `make gx<name>` target, rendering
into **`<root>/gx/docs-<suite>`** and published nowhere.

**THE BATCH.** `<root>/checks/check=stormwater_extent/run=<ts>.jsonl`, written once per
`make stormwater-extent`. `stormwater_extent.CHECK_COLUMNS`, in order — this is the
constant `gx.rows()` asserts against, so read it from the module rather than retyping it:

```
check · subject · outcome · detail                      (checks.CORE)
scenario · horizon · rain_in_hr · category · polygons
vertices_src · vertices_kept · tolerance_m · zip_sha256
```

`subject` is `"<scenario> <horizon> <category>"` for a built category and
`"<scenario> <horizon>"` for a declared scenario the table does not hold.

**THE MEASURED SHAPE, on the real root 2026-08-25** — 12 rows, and every one of the four
DECLARED scenarios appears every run whether or not it built:

| subject | outcome | polygons | vertices_src | vertices_kept |
| --- | --- | --- | --- | --- |
| `moderate current deep` | ok | 7,272 | 222,512 | 53,719 |
| `moderate current nuisance` | ok | 17,726 | 502,602 | 135,599 |
| `moderate current not_analyzed` | ok | 1,420 | 404,228 | 33,603 |
| `moderate 2050 deep` | ok | 8,158 | — | 60,351 |
| `moderate 2050 nuisance` | ok | 20,650 | — | 153,788 |
| `moderate 2050 future_high_tides` | ok | 5,949 | — | 76,670 |
| `moderate 2050 not_analyzed` | ok | 4,367 | — | 52,445 |
| `extreme 2080 deep` | ok | 40,224 | — | 363,400 |
| `extreme 2080 nuisance` | ok | 98,629 | — | 742,566 |
| `extreme 2080 future_high_tides` | ok | 7,122 | — | 158,140 |
| `extreme 2080 not_analyzed` | ok | 6,208 | — | 62,768 |
| **`limited current`** | **inconclusive** | 0 | null | null |

(the `vertices_src` column is populated on every row of a real run; the dashes above are
just table width.) `rain_in_hr` is one of `1.77 · 2.13 · 3.66`; `tolerance_m` is `5.0`;
`zip_sha256` is `5effe9bc…` on every row including the inconclusive one.

**THE THIRD OUTCOME IS PERMANENT HERE, AND IT IS THE ROW A SUITE MOST EASILY GETS WRONG.**
`limited current` is INCONCLUSIVE on **every run and will stay that way** until somebody
supplies a differently-encoded source: DEP's Limited geodatabase stores its feature class
in Esri's compressed CDF container, which the open `OpenFileGDB` driver cannot decompress
(GDAL 3.8.5 reads ZERO features with no error; 3.12.4 refuses the dataset). It is not a
flake and it is not a retry. Two consequences, both of them orch 08's own rule:

- **`Suite.era` is None** and every PER-ROW expectation goes to the judged subset. The
  inconclusive row is held out of the frame, so the frame is **11 rows, not 12** —
  and an `ExpectColumnDistinctValuesToEqualSet` over the four scenarios would go RED for
  exactly the reason orch 08's first suite did. Do not write one.
- **Every BATCH-LEVEL claim goes to `Suite.whole` over the WHOLE batch**: "one row per
  declared scenario" (four keys), "the zip sha is one value across the batch", "every
  category row carries both vertex counts". `census()` emits a row for every declared
  scenario every run precisely so that claim is expressible.

Per-row claims worth having: `polygons > 0` and `vertices_kept > 0` (paired with a not-null
each — an in-set expectation ignores nulls and succeeds without them, orch 10's survivor);
`vertices_kept <= vertices_src`; `tolerance_m` equal to the module's constant;
`category` in `deep · nuisance · not_analyzed · future_high_tides`; and
`future_high_tides` never on `horizon = current`.

**FOR THE WALKTHROUGH, NOT FOR A SUITE:** `files/geo/**` is on the host as of this
landing — one key, `files/geo/stormwater-moderate.geojson`, 4,607,370 raw bytes. Link it,
do not re-describe it; `docs/read-api-contract.md` carries its row, its three categories
and the two limits it ships with.
