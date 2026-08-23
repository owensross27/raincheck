# Wayfinder map: orchestration showcase (Airflow + Great Expectations)

Label: `wayfinder:map`

## Destination

The nightly build is a real Airflow DAG — self-hosted on the EKS cluster
(Helm, KubernetesExecutor), never MWAA — that preserves `daily.py`'s
hard-won semantics (every stage runs even when an earlier one fails; the
run ends by naming its failures) while adding what launchd cannot: dynamic
task mapping that fans out per-day `events` builds and per-kind gapfills in
parallel on Karpenter spot capacity, retries with backoff instead of "wait
for tomorrow's 06:00", and `gold` rolled up once behind the mapped days.
The existing verification invariants run as named Great Expectations suites
whose results publish as browsable Data Docs after every run. This phase is
explicitly a skills showcase as much as an ops upgrade: the pipeline
already works; this makes the working *legible*. Done when nothing is left
to decide before `/to-spec` / `/to-tickets`.

## Notes

- The contract being preserved, not reinvented [build T15]: stage order
  gapfill -> gapverify -> gapcheck -> coldpush -> coldcheck -> events(+gold)
  -> precip -> prune; all-stages-always-run means Airflow edges carry
  `trigger_rule="all_done"`, not the default all-success; `coldcheck` stays
  soft (reports, never fails the run); `coldgaps` stays OUT of the daily run
  (it covers unrecoverable subway_vp and would page forever on Mac-era
  gaps) [T15, T19]; gapfill runs before gapcheck because the newest 1-2
  days legitimately lag gtfsrt.io's publish delay [T20]. The MRMS monthly
  true-up is INSIDE this contract (a daily.py stage), not a separate
  scheduled task; the Mac's standing agents outside it are the archiver
  (cutover-owned [T19]) and `com.raincheck.precip-live`, whose move is
  cloud map ticket 5's — not claimed here.
- The unit of work stays the make target / module entrypoint. The DAG
  orchestrates; it never re-implements a stage. The migration gate is
  **content equality, not bytes**: row counts plus a sha over sorted rows
  per partition (the `assets_version` pattern) — byte-identity only holds
  within one JVM session (parquet-mr permutes footer encoding order
  across sessions, ~27 bytes, data pages identical [F01, T02]), and a DAG
  run is by construction a different session than `make daily`.
- Exit-code vocabulary the DAG must carry: ticket 20's close-out created a
  deliberate THIRD state — rc=2 INCONCLUSIVE ("could not check") distinct
  from rc=1 ("checked, data missing") [T20, backfill-verify.py]. Airflow
  task states and GX results are binary by default; the DAG design must
  represent INCONCLUSIVE distinctly so a dead endpoint never renders as a
  data gap (the exact conflation five incidents were spent removing).
- Dynamic task mapping material already exists: `gaps()` returns the day
  list (14-day scan, D+1 tail rule) [T15]; the five recoverable kinds are
  gapfill's fan-out axis [T20]; the 7-day catch-up that ran serially in
  one 1928 s session (~275 s/day) is the measured case for mapped per-day
  `events` tasks. The `gold` rollup is NOT mappable — daily.py builds the
  days then rolls the union of touched months once; the DAG mirrors that
  as a single reduce task, and per-task Spark memory x fan-out width
  feeds cloud ticket 1's capacity accounting [daily.py, T15].
- The invariant families GX wraps, split by ERA because ticket 20 keeps
  their tools deliberately apart [T20]:
  - Live-capture era (START 2026-08-15): gapcheck 24/24 hour-completeness
    with the self-checking `gapfill.DEAD` allowlist; gapverify's
    0.85-1.2x same-day band; coldcheck/coldgaps remote census [T18, T19].
    **gapverify is never pointed at the pre-live range** — with no
    same-day archiver pair it silently falls through to an August day and
    prints a false OK [T20].
  - Backfill era (2026-03-01..08-14): `scripts/backfill-verify.py`'s R2
    census with its own `backfill-verify.DEAD` list and the
    zero-byte-part rule (empty `_gapfill` markers exempt) [T20].
  - Era-neutral: schema-era column presence (the silently-vanishing
    column class both engines exhibit [CONTEXT.md]); frozen-count
    canaries — 1,351 cells_scored [F01], the 496-row stations fixture vs
    the live registry, `ref` content identity via `assets_version` + the
    key-stability diff (the in-session byte gate stays a pytest concern,
    not a GX suite [T02, F01]), the re-measured 311 p99 thresholds 97/85
    [F04].
- Inherited open item: gapcheck's GX suite is scoped to the live era
  pending Ross's answer on the START question (ticket 20's closing
  recommendation: leave START at 2026-08-15; the backfill era is asserted
  against R2 by backfill-verify) — the suite universe follows his call.
- Ross's explicit choices, not open questions: Airflow (his named tool),
  self-hosted, never MWAA; Great Expectations for the suites; the
  distributed EKS runtime (2026-08-23 decision, `.scratch/cloud/map.md`);
  showcase intent stated in the architecture artifact
  (https://claude.ai/code/artifact/635f56e8-d973-4339-a472-95db1874bcbd)
  and here.

## Tickets to cut

1. **Deployment shape.** Helm release on the EKS cluster,
   **KubernetesExecutor** — each task its own pod (the correct executor
   on a cluster and the showcase-grade one; the pre-pivot
   compose-on-a-box/LocalExecutor default was superseded 2026-08-23);
   Airflow metadata DB as a postgres pod + EBS (no RDS inside the $100
   envelope — record the arithmetic); platform prerequisites (IRSA, node
   headroom, capacity accounting) are cloud map tickets 1/6 — this
   ticket consumes their answer, it does not re-own the sizing number.
2. **DAG design.** The stage graph with `all_done` rules; mapped per-day
   `events` tasks + a single non-mapped `gold` reduce over the union of
   touched months; mapped per-kind gapfill tasks; retry/backoff per stage
   (a network-flavored gapfill failure retries; a gate failure does not);
   **rc=2 INCONCLUSIVE surfaced as its own task outcome** (branch/skip
   state or a dedicated marker task — never rendered as "failed/data
   gap"); build capacity requested per-task via pod resources (Karpenter
   provisions spot; the platform decision is the cloud map's); the 06:00
   America/New_York schedule with catch-up semantics replacing launchd's
   sleep-coalescing; run-naming a human can read a month of.
3. **Great Expectations integration.** Checkpoint placement per invariant
   family (gates in-DAG vs post-run reports); suites named by the era
   split above; INCONCLUSIVE represented in GX results distinctly from
   failure; where Data Docs publish (the static host, next to the map —
   cloud ticket 9 owns the payload slot); failure routing mirrors
   daily.py (loud, named, never silently blocking later stages).
4. **Migration parity.** Content-equality gate (counts + sorted-row sha
   per partition, the assets_version pattern — not bytes); the DAG
   shadows the 06:00 launchd job N days before replacing it (same
   two-proof discipline as T19's gate); the launchd retirement entry in
   cloud ticket 10's checklist.
5. **Observability and the showcase surface.** Task-log retention on
   cluster storage; the "portfolio view" (Data Docs + the DAG graph + a
   short written walkthrough); where that lives so it is shareable
   without shipping MTA raw data (cloud ticket 9's boundary decision
   applies).
6. **gapfill rc-0-on-empty-fill hardening.** RESOLVED 2026-08-23, ahead
   of the map, by the ticket-20 close-out session (landed 66044a1 as
   3429309 with 3 tests). Design decision recorded there: the bar is
   "nothing at all worked", NOT "something failed" — gtfsrt.io lags 1-2
   days, so the newest day of a default span is routinely unpublished
   and failing on it would page every 06:00 about a hole that fills
   itself tomorrow; verified against daily.py's actual default span.
   The DAG inherits a truthful exit code; nothing left to build here.

## Review round 1 (2026-08-23, adversarial panel — corrections applied)

1. BLOCKER deployment target: destination retargeted from "the always-on
   box" to the EKS cluster per Ross's same-day pivot; sizing ownership
   pinned to cloud ticket 1 (was split across maps, so no ticket owned
   the number).
2. Parity gate corrected byte-equivalence -> content equality (counts +
   sorted-row sha); byte-identity is in-session-only [F01].
3. GX inventory era-split (live vs backfill tools; gapverify never aimed
   pre-live; backfill-verify.py named); "byte-identical ref rebuilds"
   replaced with `assets_version` content identity.
4. rc=2 INCONCLUSIVE made a first-class DAG/GX outcome (Notes, tickets
   2/3) — binary states would re-conflate what five incidents separated.
5. MRMS true-up removed from "absorbed scheduled tasks" (it is a daily.py
   stage); precip-live's move correctly attributed to cloud ticket 5.
6. `gold` marked non-mappable — mapped `events` + single gold reduce
   (Notes, ticket 2); build-instance start/stop language replaced by
   per-task pod resources + Karpenter.
7. The rc-0 hardening got its own ticket (6) so /to-tickets produces it.
8. gapcheck-START recorded as an inherited open item scoping the GX
   suite universe (Ross's pending call).
9. The un-checkable "the artifact" citation now carries the URL.

## Out of scope

- MWAA, Astronomer, any managed Airflow (the self-hosted choice IS the
  showcase).
- Celery executor, standalone worker autoscaling beyond Karpenter.
- Re-implementing any stage logic inside DAG code.
- dbt or a second transformation framework (Spark/DuckDB SQL own
  transformation; GX owns validation; a third tool dilutes both).
- Alerting channels (notify map's territory; the DAG's failure surface is
  logs + Data Docs + exit status for now).
