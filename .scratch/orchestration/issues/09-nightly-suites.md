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

**FOR YOUR THREE SUITES SPECIFICALLY.** The fidelity suite expects on `gapverify` rows at
`gapfill.ROW_BAND` / `gapfill.KEY_BAND` (the constants, never the observed 0.85-1.2x). Its
acceptance row — "fails when a kind is inconclusive on a day that HAS a comparable pair" —
is a claim about a row that reads INCONCLUSIVE, and those rows are HELD OUT of the frame,
so **an expectation cannot make it: check it in your suite's own code over the whole batch
and set the Result yourself, or expect on a column the producer already distinguishes.**
Same shape for the era suite's "four rows every run" and the cold mirror's "one row per
`archive/` prefix" — both are batch-level claims, both must be made before the split.
`differing` and `hours_seen` are NULL on could-not-check rows: never write an expectation
that reads a null as a measured 0.

**If you decide `eras` belongs in the nightly, that IS a stage** — the three-part change,
and note orch 08 already added `gxcheck` LAST, so an `eras` stage must sit BEFORE it or its
batch is a run behind. `gxcheck` reading a stale batch is not an error; it is just old news.
