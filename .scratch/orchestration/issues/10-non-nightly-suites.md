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
