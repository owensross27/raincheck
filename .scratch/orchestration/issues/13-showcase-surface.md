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
