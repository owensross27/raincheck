# 08 — Great Expectations foundation and the completeness suite

**What to build:** The first named suite, running as a checkpoint inside the nightly, with
browsable Data Docs at the end of the run. The suite expects on the check's **result
rows**, not on Bronze — it never re-derives a check that a module already implements, so
every threshold keeps exactly one home. Expecting on aggregate rows is also what makes
the report publishable: unexpected values get rendered into Data Docs, so a suite pointed
at Bronze would publish feed rows to a public host.

**Blocked by:** 02 (check-result rows), 05 (the nightly DAG).

**Status:** ✅ DONE 2026-08-25 (branch `orch08-gx-foundation`) — see the close-out at the bottom

- [x] Great Expectations installs as an optional extra in the one image; no pipeline module imports it
- [x] An adapter turns check-result rows into a validation result that preserves all three outcomes — inconclusive is not flattened into pass or fail
- [x] A named live-capture completeness suite expects on the hour-completeness rows: every kind x closed day is 24/24 or misses only allowlisted hours, no row reports a stale allowlist entry, and the unrecoverable subway positions are excluded by the check's own note
- [x] The suite is scoped to the live-capture era and is never pointed at the backfill range
- [x] It runs as an in-DAG checkpoint with zero retries on an `all_done` edge — loud, named, never blocking a later stage
- [x] Data Docs build once at the end of a run
- [x] The Great Expectations major version is pinned and recorded; suites are written against that API only, since the 0.x and 1.x context/checkpoint APIs differ substantially
- [x] A suite test, skipping cleanly when the library is absent, validates a fixture batch holding one passing, one failing and one inconclusive subject, and asserts the inconclusive one is neither

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


---

# CLOSE-OUT — landed 2026-08-25, branch `orch08-gx-foundation`

Worktree `/Users/ross/raincheck-wt/orch08`, off master `909739b`. **GX PINNED TO MAJOR
VERSION 1; measured against 1.21.0.** Own-module tests only; never the full suite.

## What shipped, as a surface (this is what tickets 09/10/13 build on)

`src/raincheck/gx.py`, plus `make gxcheck` / `python -m raincheck.gx` / the `gxcheck`
stage. `import raincheck.gx` works WITHOUT the library - every GX import is inside a
function.

    ERA_START: str                     # gapfill.START.isoformat(); the live-capture boundary
    DATASOURCE = "checks"  SITE = "raincheck"  DOCS = ("gx", "data_docs")
    RESULT_FORMAT                      # COMPLETE + unexpected_index_column_names=["subject"]

    Suite(name, check, columns, expectations, era=None)          # NamedTuple
        name          the suite's own name; it becomes a Data Docs page and a URL segment,
                      so NO SPACES (they arrive %20-encoded on the public host)
        check         the producer's name on disk: checks/check=<check>/
        columns       THAT producer's own CHECK_COLUMNS constant, never a literal list
        expectations  () -> list[gxe.Expectation]; a CALLABLE, because building one
                      imports the optional extra and importing this module must not
        era           the column holding an ISO day, if the batch has one; values before
                      ERA_START are REFUSED

    Result(suite, check, ok=(), failed=(), inconclusive=(), detail="")   # frozen dataclass
        .outcome -> checks.OK | FAIL | INCONCLUSIVE   (checks.rc's precedence)
        .row()   -> checks.Row                        (not persisted; rc() uses it)
        .line()  -> the printed line

    available()                 -> bool               # is the extra installed
    docs_dir(root)              -> Path               # <root>/gx/data_docs
    batch(root, check)          -> Path | None        # the NEWEST run= stamp
    rows(path, columns, era=None) -> list[dict]       # + column and era refusals
    context(docs)               -> an ephemeral GX context writing its one site into `docs`
    validate(ctx, suite, rows)  -> Result             # THE ADAPTER
    run(root, suites=SUITES)    -> (list[Result], docs_path)
    rc(results)                 -> int                # checks.rc over Result.row()

    SUITES = (Suite("live-capture-completeness", "gapcheck",
                    gapfill.CHECK_COLUMNS["gapcheck"], _completeness, era="day"),)

**To add a suite: append a `Suite` to `SUITES`.** Nothing else - `run()` finds the batch,
asserts the columns, refuses the era, splits the outcomes, validates and renders.

## The three-outcome mapping, and the trap inside it

**INCONCLUSIVE rows are HELD OUT of the frame GX sees.** An expectation has exactly two
answers, so any row inside the batch has already been flattened into two by the time the
suite runs. They come back on `Result.inconclusive`, they decide the outcome when nothing
failed, and they are in neither `ok` nor `failed` by construction. Mutation-checked in
both directions (rows entering the frame -> rendered as a FAILURE; rows dropped -> rendered
as a PASS; and both flattenings of `Result.outcome`).

**THE TRAP, and it is not theoretical - a test caught it during this build. EVERY
EXPECTATION IN A SUITE HERE MUST BE PER-ROW, NEVER AGGREGATE.** The held-out rows SHORTEN
the frame, so an aggregate expectation sees a short batch and fails - which renders "could
not check" as a FAILURE, the exact conflation this ticket exists to prevent. The first
draft used `ExpectColumnDistinctValuesToEqualSet` over the kinds and went red the moment a
kind came back INCONCLUSIVE. **A batch-level claim has to be made over the WHOLE batch,
before the split, in the adapter - not as an expectation.** Pinned by
`test_an_inconclusive_row_never_makes_an_expectation_fail` and by a mutation that puts the
aggregate back.

Beside it, the mirror: **GX's own `success` decides the outcome, and the named subjects
only say WHICH.** An aggregate expectation (or a per-row one over an all-null column) fails
without naming anybody, so a failing suite that named nobody is charged to `<check batch>`.
Without that fallback a failed suite would read INCONCLUSIVE or OK.

**The DAG side is free.** The stage is `Stage("gxcheck", "make:gxcheck", "gate",
argv=("gx",))`, so ticket 07's `skip_rc()` - which reads the declaration and names no
stage - maps this module's rc 2 onto a `skipped` task with no coordination between the two
branches. Nothing in `dags/` was edited.

## Decisions worth not re-deriving

- **The suite reads the producer's VERDICT, never a copy of its rule.** `gapfill.check()`
  is `FAIL if fillable or stale else OK`; the suite expects `outcome == checks.OK`.
  Expecting on `fillable`/`stale_dead` instead would put that expression in a second home.
  So "24/24 or only allowlisted hours, and no stale allowlist entry" is ONE expectation.
- **The unrecoverable subway positions** are excluded by `kind ∈ gapfill.KINDS`:
  `subway_vp` is not a kind (gtfsrt.io archives subway TU only), so a batch that grew one
  reports a 0/24 gap nobody can fill. The check's note says it in words; this says it in an
  expectation, read from the constant.
- **The era refusal is a REFUSAL, not an expectation.** A suite pointed at the backfill
  range is pointed at the wrong data - a defect, not a finding - so `rows(..., era="day")`
  raises. `ERA_START` is `gapfill.START`, read not retyped.
- **Ephemeral context.** No `great_expectations.yml`, no expectations/ tree, no
  uncommitted/ tree on the data root. The suites are in the module, the batches are on
  disk, and the only durable output is the rendered site.
- **Analytics OFF explicitly** (`ctx.enable_analytics(False)`) and progress bars off.
  1.21.0 does not bundle the posthog client; that is not a promise about 1.22.

## MEASURED FACTS a later ticket should not have to re-find (GX 1.21.0)

1. **A Data Docs site is 23 files / ~4 MB, and TEN of them are `.otf` font faces.**
   `publish.PUBLISHABLE` had `.woff` and `.woff2` and no OTF, so **`make publish
   FAMILY=docs` refused the whole family on a font** - proven by re-running `plan()` with
   master's allowlist. `.otf` was added to the allowlist (one format, not a category;
   `mimetypes` already answers `font/otf`, so no TYPES entry was needed). The suffixes a
   Docs site emits, measured: `.html .css .otf .png .svg .gif .ico` - and nothing else.
2. **`build_data_docs()` REBUILDS THE WHOLE SITE.** A re-validated suite's page is replaced
   and a RETIRED suite's pages disappear entirely. An `rmtree` of the site was written and
   then **deleted** - it survived every mutation because nothing could observe it. A test
   pins the behaviour instead; that is where a future GX that stops cleaning shows up.
3. **A validation page's URL carries the run's timestamp**
   (`validations/<suite>/__none__/<ts>/checks-<suite>.html`), so it does not exist
   tomorrow. `docs/index.html` is the stable entry point. Written into
   `docs/read-api-contract.md`.
4. **`unexpected_index_column_names` is what lets a failing expectation NAME check
   subjects.** It needs `result_format: COMPLETE` and a column in the frame; `subject` is
   in `checks.CORE`, so every batch has one.
5. **`TupleFilesystemStoreBackend` refuses a relative `base_directory`** without a project
   root ("must be an absolute path if root_directory is not provided").
6. **Data Docs are POSIX-ONLY.** `run()` refuses an object-store root outright - the same
   list as `precip_live`, `export` and `live_export` (cloud 12/13). Relevant to cloud 10
   and to orch 12's cutover: the pods' root is the `/staging` emptyDir today, which is
   POSIX, so nothing is blocked now.
7. **`ExpectColumnValuesToBeBetween` cannot compare ISO date STRINGS** - it fails with no
   unexpected index rather than working. That is half of why the era check is a refusal.
8. Core GX 1.21 pulls altair, cryptography, jinja2, jsonschema, marshmallow, mistune,
   numpy, pandas, pydantic, pyparsing, python-dateutil, requests, ruamel.yaml, scipy, tqdm,
   tzlocal - and **no sqlalchemy**: the pandas path needs no engine. `pandas>=1.3.0` on
   py3.12, so it does not move the repo's pinned pandas.

## The three-part stage change, as landed

- `daily.STAGES` gained `Stage("gxcheck", "make:gxcheck", "gate", argv=("gx",))`, **LAST**
  (it expects on the rows the stages above wrote, and Data Docs build once at the end).
  Not `soft`: a red suite is named in the run's own ending.
- `deploy/k8s/raincheck/build.yaml`'s `raincheck.io/stages` gained `gxcheck` on the
  `raincheck-stage` template, in the same commit.
- `tests/test_daily.py:240-241`'s literal step list became a PROPERTY derived from
  `daily.STAGES` - **byte-identical to the change ticket 06 makes on its own branch**, so
  the wave gate's union of that hunk is trivial.
- **`tests/test_dag_nightly.py` NEEDED NO EDIT.** Its tests iterate `declared()`, so the
  new stage is covered automatically: the gate-carries-an-argv test, the
  command-exists/shape-resolves test and the graph test all pick it up. Verified for real
  in an Airflow 3.2.2 + cncf-kubernetes 10.17.1 venv.

## What is NOT done

- **No cluster proof.** `raincheck_daily` is PAUSED and was not touched. The runtime image
  with the extra was built locally to prove `pip install -e '.[gx]'` resolves and
  `import great_expectations` succeeds in the image; nothing was pushed to ECR and **no
  image pin was committed** (`deploy/k8s/kustomization.yaml` and `deploy/airflow/values.yaml`
  are untouched on this branch).
- **Ticket 07's own file was deliberately NOT edited.** Its branch already rewrites it, so
  an edit here would be a guaranteed conflict on a landed branch for no gain. This side of
  the distinction is written into 07's summary line in the runbook instead.
- **Nobody owns a `ref`-canary check-row producer** - still open, still ticket 10's.
