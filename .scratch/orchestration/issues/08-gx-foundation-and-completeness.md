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
