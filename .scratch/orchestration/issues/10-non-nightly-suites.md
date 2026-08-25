# 10 — The non-nightly suites

**What to build:** The two invariant families that do not belong in a nightly run get
suites and their own triggers: the backfill-era census, which fires when a backfill chunk
lands, and the reference canaries, which fire on a reference rebuild. Keeping them out of
the nightly is deliberate — nightly runs should not grow checks over data that cannot
change — and keeping the two eras' tools apart is the standing rule from the backfill
work.

**Blocked by:** 03 (remaining check producers), 08 (GX foundation).

**Status:** ready-for-agent

- [ ] A backfill census suite expects on the census rows for the backfill era, with its own dead-hour list and the zero-byte-part rule (empty fill markers exempt)
- [ ] It is not in the nightly DAG; its trigger is a backfill chunk landing
- [ ] A reference-canary suite expects **through** the frozen-count canary that already exists in code rather than restating the numbers, so each count keeps one home
- [ ] It covers reference content identity and the key-stability diff, and triggers on a reference rebuild rather than nightly
- [ ] The in-session byte gate stays a pytest concern and does not become a suite
- [ ] The slice-era acceptance gates do not become suites

## Inherited from orchestration 03 (landed 2026-08-24, b37a761)

- **The backfill census half is shipped**: check `backfill`, columns `CORE + ("feed",
  "lo", "hi", "hours_seen", "hours_want", "dead", "missing", "no_part", "no_marker",
  "zero_byte", "stale_dead")`, **one row per feed always**. Its DEAD list stays inside
  `scripts/backfill-verify.py` and a test asserts it is disjoint from `gapfill.DEAD` —
  the two eras' tools stay apart, as this ticket requires. Zero-byte PARTS are counted
  in `zero_byte`; empty `_gapfill` markers are exempt by construction (they are counted
  as markers, never as parts). The 0/1/2 meanings are unchanged, now rendered by
  `checks.rc`, so a real gap beside a failed listing exits 1 and every feed still gets
  its row.
- **OPEN QUESTION THIS TICKET MUST SETTLE FIRST — nobody owns a `ref`-canary check-row
  PRODUCER.** Spec §5 lists the ref canaries among the producers; orch 03's scope was
  exactly three (cold mirror, backfill census, era columns) and it did not build them;
  this ticket writes only the SUITE. So either the reference-canary suite expects
  through `ref`'s existing in-code canary with no batch on disk, or the producer has to
  be built here. Decide before writing the suite, not during.

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

**FOR YOUR TWO SUITES SPECIFICALLY.** The backfill census is the OTHER ERA: leave
`Suite.era` as None on it. Setting `era="lo"` (or any date column) would refuse the whole
batch, because `gx.ERA_START` is `gapfill.START` and the backfill range ends the day
before. That refusal is deliberate — orch 08's live-capture suite must never be pointed at
your range, and yours must never inherit its boundary.

**`backfill` and `eras` are NOT in `daily.STAGES`**, so their rc 2 never reaches a task
state at all and the persisted row is the only record (orch 07). `gxcheck` runs inside the
nightly, so **a suite over a non-nightly batch will read whatever run last landed on disk —
`gx.batch()` takes the newest `run=` stamp and asks no questions about its age.** If a
stale batch would be misleading for your triggers, that is yours to decide and to say out
loud; the foundation deliberately does not date batches.

**YOUR OPEN QUESTION IS STILL OPEN AND ORCH 08 DID NOT CLOSE IT: nobody owns a `ref`-canary
check-row PRODUCER.** Decide before writing the suite. Note the foundation gives you a
third option the ticket text does not name: a suite whose batch does not exist reports
INCONCLUSIVE with `<no batch>` rather than failing or passing, so "the producer is not built
yet" is a state the surface can already carry honestly.
