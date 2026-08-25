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
