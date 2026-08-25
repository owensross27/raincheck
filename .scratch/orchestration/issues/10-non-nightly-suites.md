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

**FOR THIS TICKET SPECIFICALLY.** `backfill` and `eras` are the two inconclusive-capable
producers that are NOT in the nightly declaration, so their rc 2 never reaches a task state
at all — for them the persisted row is not merely authoritative, it is the only record.
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

## Forward-context from DESTINATION-PLAN.md (copied verbatim by the WAVE 5 GATE PART 2, 2026-08-25, from this ticket's summary line in waves/wave-3-plus.md)

**FROM DESTINATION-PLAN (2026-08-25) — TWO NEW CHECK-ROW PRODUCERS ARE COMING, and the second lands after you.** flood-build 19 (wave 6, same wave as you) emits batch `stormwater_extent` (polygon counts per scenario x category, the zip sha) — expect on it if its entry exists when you write; flood-build 21a (wave 7) emits `route_flood` — NOT yours; write it forward to orch 13 or a later suite ticket rather than reopening this one. Both are Mac-runnable `make` targets, not nightly stages, until the wave-8 gate registers 21b.
