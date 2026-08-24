# raincheck orchestration: Airflow DAG + Great Expectations — build spec

Status: ready-for-agent
Source: wayfinder map `.scratch/orchestration/map.md` (6 tickets, review round 1
applied; ticket 6 already RESOLVED in code). Written 2026-08-23. Vocabulary is
CONTEXT.md's (Poll, Snapshot, Ping, Stop row, Cell, Pixel, Service date, Hour,
Bronze/Silver/Gold); ADR-0002 binds wherever MRMS is touched. Cross-map
boundaries: the cluster, the Airflow **install**, storage and networking belong to
`.scratch/cloud/spec.md`; alerting channels to `.scratch/notify/map.md`; the flood
model chain to `.scratch/flood-build/`. This spec owns **the DAG, the suites, and
the migration off launchd** — nothing underneath them.

Two honesty notes before anything else. First, the map's ticket 1 ("deployment
shape") now overlaps the cloud spec's section 6, which was written the same day and
already owns the Helm release, KubernetesExecutor, metadata Postgres, the dropped
triggerer and remote task logs. Rather than re-own those, ticket 1 is **rewritten**
here as DAG delivery and per-task runtime. Second, three of the map's positions are
corrected rather than extended — Airflow catch-up, the shadow period's writers, and
where the showcase is actually visible from. All three are marked in Further Notes.

## Problem Statement

The nightly build is a shell script wearing a LaunchAgent. `make daily` does real
work well — eight stages in a pinned order, every stage running even when an
earlier one failed, an exit line that names the failures — but launchd gives it
nothing beyond "fire at 06:00, and if the Mac was asleep, fire once on wake". A
stage that fails on a transient network blip does not retry; it waits for tomorrow
morning. The seven service days a catch-up run has to build are built one after
another in a single Spark session (measured: 1928 s for 7 days, ~275 s/day), because
one laptop has nowhere to put the second day. The five gapfill kinds are equally
serial for no reason — they write disjoint Bronze prefixes.

The verification story is worse in a specific way. The invariants exist and are
good — `gapcheck`'s 24/24 hour completeness against a self-checking DEAD allowlist,
`gapverify`'s ratio bands, `coldcheck`'s remote census, `backfill-verify.py`'s R2
census with its deliberate third exit code — but they live as exit codes in a log
file on Ross's laptop. Nobody can see them. Nothing renders them. And the exit-code
vocabulary is not evenly applied: `backfill-verify.py` distinguishes rc=2
INCONCLUSIVE ("could not check") from rc=1 ("checked, data missing") because five
incidents were spent learning that conflating them sends someone hunting a phantom
gap — but `gapfill.verify()` still returns 0 when it found no filled/captured hour
pair to compare at all. A check that verified nothing reports OK.

And the showcase problem is the same problem: the pipeline already works, but how it
runs is legible only to the person who wrote it.

## Solution

A single self-hosted Airflow DAG on the EKS cluster that orchestrates the existing
stages without re-implementing one of them, and a set of named Great Expectations
suites that validate the existing checks' **results** rather than re-deriving them.

- **One stage contract, two runtimes.** The ordered stage list, which stages are
  soft, which fan out and over what — lifted out of `raincheck.daily`'s `main()`
  into one declaration that both the launchd job and the DAG build from. Neither
  runtime may hardcode a stage name or an edge. During the shadow period both run;
  a second hand-maintained copy of "gapfill before gapcheck" is exactly how that
  note gets lost in one of them.
- **The DAG is state-driven, not date-driven.** `gaps()` reads the data root and
  decides what to build. `logical_date` never chooses a Service date, and Airflow
  catch-up is OFF — every stage is already a catch-up over a bounded window, so
  replaying dag runs would multiply bounded-window jobs, not recover anything.
- **Fan-out where the work is genuinely independent**: one mapped task per Service
  date for `events`, one per feed kind for `gapfill` and `gapverify`, and a single
  non-mapped `gold` reduce over the union of months the built days touched. `gold`
  is not mappable and is not mapped.
- **Every edge is `all_done`.** The contract that a red `gapcheck` must not cost the
  day's build survives the move as a trigger rule, and a final report task fails the
  run naming the stages that failed — the same sentence `daily.py` exits with today.
- **A third outcome is carried end to end.** Checks return rows whose outcome is
  `ok`, `fail`, or `inconclusive`. The CLI prints them and exits 0/1/2, the DAG maps
  `inconclusive` to a visibly distinct task state, and the run summary counts it
  apart. INCONCLUSIVE never renders as a data gap and never renders as OK.
- **Great Expectations wraps, never re-derives.** The suites expect on the check
  result rows and on schema metadata. Where a canary already exists in code — the
  1,351 `cells_scored` / 496 stations frozen counts, `assets_version` content
  identity — the suite expects on that canary's row, so the number keeps exactly one
  home. Data Docs publish to the static host after every run, so the pipeline's own
  checks are browsable without cluster access.
- **The migration is proven, then taken.** The DAG shadows the launchd job into a
  shadow data root for seven clean days with two independent proofs per day (content
  equality per partition; stage-outcome equality), and only then does the 06:00
  LaunchAgent get retired.

## User Stories

### Running the nightly at all

1. As the operator, I want the nightly build supervised by a scheduler that survives
   a machine, so that the pipeline's clock is not a laptop's lid.
2. As the operator, I want a transient stage failure retried within the same run, so
   that a network blip costs minutes rather than a day.
3. As the operator, I want every stage to run even when an earlier stage failed, so
   that a red `gapcheck` still cannot cost the day's build.
4. As the operator, I want the run to end by naming which stages failed, so that the
   summary I read is the same sentence the job exits with today.
5. As the operator, I want the stage order fixed in one place, so that "gapfill
   before gapcheck" cannot be true in one runtime and false in the other.
6. As the operator, I want `coldcheck` to stay soft, so that Bronze written during a
   sync still reports as drift and never fails the run.
7. As the operator, I want `coldgaps` kept out of the nightly, so that unrecoverable
   Mac-era `subway_vp` gaps do not page forever.
8. As the operator, I want a run named `daily-YYYY-MM-DD`, so that I can read a
   month of runs without decoding timestamps.
9. As the operator, I want at most one run in flight, so that two runs can never
   build the same Service date at once.
10. As the operator, I want the schedule expressed in America/New_York, so that the
    06:00 slot tracks DST the way the LaunchAgent did.

### Not being fooled by the scheduler

11. As the operator, I want Airflow catch-up OFF, so that a paused DAG resuming does
    not stampede fourteen redundant bounded-window runs.
12. As the operator, I want the day to build chosen by `gaps()` and never by the run's
    logical date, so that the driver's own rule about a Service date still on the road
    keeps holding.
13. As the operator, I want a run with nothing to build to be a green no-op, so that
    a quiet morning is not an alert.
14. As the operator, I want a Service date short of its Bronze hours deferred out
    loud, so that the DAG cannot bury a short day behind a green board.

### Fanning out

15. As the operator, I want one task per Service date for `events`, so that a seven-day
    catch-up is bounded by the slowest day instead of the sum of all seven.
16. As the operator, I want one task per feed kind for `gapfill`, so that five disjoint
    Bronze prefixes fill in parallel.
17. As the operator, I want `gapverify` mapped the same way, so that verification does
    not re-serialise what the fill just parallelised.
18. As the operator, I want `gold` to run once behind the mapped days, so that the
    monthly reduce is not repeated per day.
19. As the operator, I want `gold` to roll only the months the **successfully built**
    days touched, so that a poisoned day cannot pull a half-built month into Gold.
20. As the operator, I want a mapped task that expands to nothing to be a clean skip,
    so that "no gaps today" is not an error state.
21. As the operator, I want each mapped task to request its own pod resources, so that
    fan-out width is a capacity decision and not a surprise.
22. As the operator, I want a killed mapped task safe to re-run, so that spot
    interruption is absorbed by idempotence.

### The third outcome

23. As the operator, I want "could not check" to be a distinct outcome from "checked,
    data missing", so that a dead endpoint never sends me hunting a phantom gap.
24. As the operator, I want INCONCLUSIVE visible as its own task state in the grid, so
    that the colour I see matches what actually happened.
25. As the operator, I want `gapverify` to report INCONCLUSIVE when it found no
    filled/captured pair to compare, so that a check that verified nothing stops
    reporting OK.
26. As the operator, I want `coldcheck` to report INCONCLUSIVE when the remote listing
    itself failed, so that an unreachable bucket is not read as a missing object.
27. As the operator, I want a real gap to outrank a not-run check in the exit code, so
    that a known hole is never masked by an unrelated INCONCLUSIVE.
28. As the operator, I want the run summary to count failures and inconclusives
    separately, so that neither number is inflated by the other.

### Checks as data

29. As the operator, I want every check to return rows rather than only print, so that
    one implementation can serve the log, the DAG and the suites.
30. As the operator, I want the printed lines to stay exactly as they read today, so
    that the log I already know how to scan does not change under me.
31. As the operator, I want the row batch to carry counts, dates, kinds and ratios and
    never feed payload, so that publishing a validation report can never publish MTA
    rows.
32. As the operator, I want each run's rows persisted, so that a suite has a batch and
    a summary has a source.
33. As the operator, I want a stale DEAD entry to fail loudly, so that an allowlist
    that outlived its hole gets removed rather than quietly protecting nothing.
34. As the operator, I want DEAD-only misses to stay reported and non-failing, so that
    hours gtfsrt.io never had do not page every morning.

### Great Expectations

35. As a reviewer, I want the invariants named as suites, so that "what this pipeline
    checks" is a list I can read rather than code I have to trace.
36. As a reviewer, I want Data Docs published after every run, so that I can see the
    checks' results without cluster access.
37. As the operator, I want the suites to expect on check results rather than re-derive
    the checks, so that a threshold has exactly one home.
38. As the operator, I want the frozen-count canaries expected through the code canary
    that already holds them, so that 1,351 and 496 are not written down twice.
39. As the operator, I want the live-capture suites scoped to the live-capture era, so
    that a same-day-pair check is never pointed at a range that has no same-day pairs.
40. As the operator, I want the backfill era asserted against R2 by its own tool and its
    own DEAD list, so that the two eras keep the two tools ticket 20 kept apart.
41. As the operator, I want the schema-era suite to assert columns are PRESENT, so that
    the silently-vanishing-column class is caught by something a row count cannot catch.
42. As the operator, I want the reference canaries to run on a `ref` rebuild and not
    nightly, so that the nightly does not grow checks that cannot change.
43. As the operator, I want INCONCLUSIVE represented in the validation result itself, so
    that Data Docs do not flatten three outcomes into pass/fail.
44. As the operator, I want GX installed as an optional extra, so that a plain dev
    checkout and the shadow-era Mac do not take a large dependency tree.
45. As the operator, I want no pipeline module to import GX, so that the pipeline's
    dependency surface is unchanged by a reporting tool.

### Migrating off launchd

46. As the operator, I want parity measured as content equality — row counts plus a sha
    over sorted rows per partition — so that parquet's cross-session footer permutation
    cannot fail an otherwise identical build.
47. As the operator, I want the shadow DAG to write to a shadow data root, so that
    shadowing never means two writers on one Bronze.
48. As the operator, I want the mutating stages disabled during shadow, so that a
    parity experiment cannot double-push or double-prune.
49. As the operator, I want it stated plainly which stages shadowing cannot prove, so
    that the cutover's real risk is on the page instead of implied.
50. As the operator, I want seven clean days and two independent proofs per day, so that
    a single broken check cannot certify the cutover.
51. As the operator, I want the LaunchAgent retirement recorded in the decommission
    checklist, so that "the Mac is not a runtime" has a line item rather than a memory.
52. As the operator, I want the launchd job runnable unchanged until the day it retires,
    so that rollback is a `launchctl` command.

### Showing the work

53. As someone showing this work, I want the fan-out demonstrated by a real run, so that
    parallelism is evidence rather than a claim.
54. As someone showing this work, I want the serial baseline stated next to it, so that
    the improvement has a denominator.
55. As someone showing this work, I want the portfolio surface to be static artifacts, so
    that showing it never requires exposing the cluster.
56. As someone showing this work, I want a short written walkthrough beside the graph and
    the Data Docs, so that a reader who will not read code still gets the story.
57. As the operator, I want the showcase artifacts to contain no raw MTA data, so that
    publishing them is never a redistribution question.

## Implementation Decisions

### 1. Ticket 1 rewritten: DAG delivery and per-task runtime

- **The Airflow install is not this effort's.** `.scratch/cloud/spec.md` §6 owns the
  Helm release, KubernetesExecutor, the in-cluster metadata Postgres on gp3, the
  dropped triggerer, the single webserver replica, remote task logs to R2 and IRSA.
  The map's ticket 1 is superseded by that section and is **rewritten** as: how DAG
  code reaches the scheduler, and what each task's pod looks like.
- **DAG code ships inside the one image**, the same git-sha-tagged image every
  raincheck pod runs. No git-sync sidecar and no separate DAG volume: the DAG imports
  `raincheck`, so the DAG and the code it orchestrates must be the same version by
  construction. *Overturn if* DAG iteration speed becomes the bottleneck — but the
  cost of overturning is that "which code produced this partition" stops having one
  answer, so it is a deliberate trade, not a convenience.
- **Per-task pod resources come from the cloud spec's stage-placement table**, applied
  through the executor's per-task pod override. The numbers themselves are cloud
  ticket 1's capacity accounting; this spec consumes them and invents none.
- **Connections and credentials** are the cluster Secrets the cloud spec already
  defines (build-read/write for build tasks, serve-read/write for the Data Docs
  upload). No credential is defined here and none is baked into the image.
- **Nothing runs on the scheduler pod.** Every stage is a task pod running an existing
  `make` target or `python -m raincheck.<module>`. A stage implemented as a Python
  callable inside the DAG file is a bug.

### 2. The stage contract as one declaration

- **Lift `raincheck.daily.main()`'s inline step list into a module-level declaration**
  that both runtimes consume. Per stage it records: the stage name, the make target or
  module entrypoint, whether the stage is soft (`coldcheck`), its fan-out axis (none /
  feed kind / Service date / MRMS month), and its retry class (transport vs gate).
- **`daily.py` keeps its behaviour exactly.** `main()` builds the same closures it
  builds today, from the declaration. The refactor's own gate is that every existing
  `tests/test_daily.py` test passes unmodified.
- **The DAG builds its task graph from the same declaration** and may not name a stage
  or an edge itself. This is the single decision that keeps the shadow period
  meaningful: two runtimes running side by side against two hand-maintained stage
  lists would drift silently, and stage order here is load-bearing (gapfill strictly
  before gapcheck, because the newest 1-2 days legitimately lag gtfsrt.io's publish).
- **No stage logic moves.** The declaration is metadata about stages; the stages stay
  where they are. Per-month `precip` expansion and `gaps()` stay functions, called by
  both runtimes.

### 3. DAG shape

- **One DAG, `daily`**, scheduled `0 6 * * *` in `America/New_York`, `catchup=False`,
  `max_active_runs=1`, `run_id` formatted `daily-YYYY-MM-DD`.
- **Catch-up is OFF and that is the correct reading of the map.** The map's "catch-up
  semantics replacing launchd's sleep-coalescing" is already satisfied by the stages
  themselves: `gaps()` scans a 14-day window, `gapfill` scans START..yesterday,
  `precip` rebuilds the current MRMS month (and the previous one on the 1st). Airflow
  catch-up would launch one bounded-window run per missed interval, each doing the
  same 14-day scan — a stampede that recovers nothing the next single run would not.
- **The DAG never uses `logical_date` to choose data.** `gaps()` decides which Service
  dates to build, from what is on disk. `daily.py`'s `closed_through()` rule — the
  newest Service date whose Legs have landed, which is *not* `utcnow() - 1 day` —
  stays the only definition, and it is evaluated at task time.
- **Edges**: the declared linear order, every edge `all_done`, terminated by a
  **report** task (also `all_done`) that reads upstream outcomes, prints the stage
  timing lines, and fails the run naming the failed stages. This reproduces
  `daily.py`'s "every stage ran; see above" exit.
- **Mapping**:
  | stage | mapped over | notes |
  |---|---|---|
  | `gapfill` | the five recoverable feed kinds | disjoint Bronze prefixes; safe to parallelise |
  | `gapverify` | the same five kinds | the module already takes one kind |
  | `gapcheck` | not mapped | one listing pass over all kinds x closed days |
  | `coldpush` | not mapped | one sync; must follow every mapped gapfill |
  | `coldcheck` | not mapped | soft |
  | `events` | the Service dates `gaps()` returns | one pod per day |
  | `gold` | **not mapped** | single reduce over the months the *built* days touched |
  | `precip` | the 1-2 MRMS months | UTC months, unlike the Service date above |
  | `prune` | not mapped | one horizon pass |
- **`gold` reads the mapped `events` results**, not the requested day list: a day that
  failed must not pull its month into the reduce, which is what `daily.py`'s
  `months(built)` already does.
- **An empty expansion is a skip, not a failure.** Zero gaps means the mapped `events`
  task expands to nothing and `gold` no-ops; the report task counts that as OK. A
  quiet morning stays green.
- **Retry classes**:
  - *transport* (`gapfill`, `coldpush`, `events`, `precip`): retries with exponential
    backoff. All are idempotent — gapfill only writes hour dirs nobody holds, coldpush
    is a one-way idempotent sync, `events` re-runs by dynamic partition overwrite.
  - *gate* (`gapverify`, `gapcheck`, `coldcheck`, every GX checkpoint): **retries 0**.
    Re-reading the same data cannot change a verdict, and a retrying gate turns a
    stable red into a flapping one.

### 4. The exit-code vocabulary as a first-class outcome

- **Three outcomes, carried end to end**: `ok`, `fail`, `inconclusive`. rc 0/1/2 is
  the CLI rendering of it; `backfill-verify.py` already speaks it and is the model.
- **DAG rendering: `inconclusive` raises a skip**, so the task lands in a state
  visually distinct from both success and failure in the grid, and the authoritative
  record is the check's own row. The non-negotiable property is the one five incidents
  bought: **INCONCLUSIVE never renders as failed and never renders as ok.** Any
  representation that preserves that is acceptable; a boolean one is not.
- **Aggregation rule**: a stage's rc is 1 if any row failed, else 2 if any row is
  inconclusive, else 0. A real gap outranks a not-run check — a known hole must never
  be masked, and an inconclusive alongside a failure is still a failure.
- **The report task counts failures and inconclusives separately** and names both.
- `daily.py`'s own semantics are unchanged (it treats any non-zero as a failed stage).
  It is being retired; changing it during the shadow period would change the thing
  being compared against.

### 5. The check-result row contract (the one new seam)

- **Every verification stage returns rows and prints from them.** A row carries: the
  check name, its subject (feed kind, day, partition — whatever identifies it), the
  outcome, the measured values behind the verdict (hours held, row counts, ratios),
  and a short detail string. The CLI prints the same lines it prints today and exits
  on the aggregation rule above.
- **Producers**: `gapcheck` (one row per kind x closed day), `gapverify` (one row per
  kind), `coldcheck`, the schema-era column-presence check, `backfill-verify.py`, and
  the `ref` canaries. One shape, one vocabulary.
- **This fixes a live bug, not just a reporting shape.** `gapfill.verify()` today
  returns 0 when it finds no filled/captured hour pair on any day — it prints "no
  filled hour with an archiver hour on the same day yet" and counts it as clean. That
  is the same false-OK class ticket 20 documented for the pre-live range, in the
  opposite direction. Under the row contract that case is exactly one `inconclusive`
  row and can never be `ok`. Same for `coldcheck` when the remote listing itself
  fails.
- **Rows carry no feed payload — ever.** Counts, hour labels, kinds, dates, ratios,
  shas. This is what makes a validation report publishable: GX renders unexpected
  values into Data Docs, so if the batch were Bronze, publishing Data Docs to a public
  host would publish MTA rows to a public host. The column set is declared and
  asserted.
- **Each run's rows are persisted under the data root** so a suite has a batch and the
  report task has a source. Retention is a bucket lifecycle rule, not a stage.

### 6. Great Expectations integration

- **Suites expect on check results and on schema metadata. They never re-derive a
  check.** Where a canary already lives in code — the frozen `ref` counts (1,351
  `cells_scored`, 496 stations, and the rest), `assets_version` content identity —
  the suite expects on the canary's result row, so the number keeps exactly one home.
- **Suites, split by era, because ticket 20 keeps the two eras' tools apart:**
  | suite | era | batch | placement |
  |---|---|---|---|
  | live capture completeness | live (START..yesterday) | `gapcheck` rows | in-DAG gate |
  | live capture fidelity | live | `gapverify` rows | in-DAG gate |
  | cold mirror | live | `coldcheck` rows | post-run report, never gates |
  | schema eras | era-neutral | reader schema rows | post-run report |
  | backfill census | backfill (2026-03-01..08-14) | `backfill-verify.py` rows | its own trigger, not nightly |
  | reference canaries | era-neutral | `ref` canary rows | on a `ref` rebuild, not nightly |
- **The completeness suite's expectations** are: every (kind, closed day) row holds
  24/24 hours or misses only DEAD-listed hours; no row reports a stale DEAD entry; and
  `subway_vp`'s unrecoverable hours are excluded by the same note the check already
  prints.
- **The fidelity suite expects what the code actually enforces**, not what the map
  quoted: non-empty filled hour, row-count ratio within the module's band, distinct-key
  coverage within its band, every archiver column present in the filled part with the
  same type (a superset, because pre-era-3 vp parts lack `schedule_relationship`), and
  **no kind inconclusive on a day that has both a filled and a captured hour** — an
  inconclusive there means the pair-finding broke, not that there was nothing to check.
  The map's "0.85-1.2x same-day band" is a **measured result** from ticket 20's
  verification run, not the gate: the enforced bands are far wider (roughly an order of
  magnitude on rows, ~3x on keys). Tightening the gate to the observed band may well be
  right, but it is a separate evidence-backed change to the module — never something a
  suite does on the side, because a suite that expects tighter than the code makes the
  suite the real gate and silently changes what passes.
- **The schema-era suite expects column presence, not counts.** Both engines lose
  Bronze bus era columns silently — Spark without `mergeSchema` takes one file's
  schema with the row count still correct, DuckDB without `union_by_name` drops
  columns when a narrow part sorts first. A row-count expectation cannot see it.
- **INCONCLUSIVE is represented in the validation result**, not flattened into
  pass/fail, so Data Docs show three outcomes.
- **Failure routing mirrors `daily.py`**: loud, named, and never blocking a later
  stage — the checkpoints hang off `all_done` edges like everything else.
- **Data Docs build once at the end of a run** and upload to the static host's Data
  Docs slot, which `.scratch/cloud/spec.md` §9 already reserves (writer: an Airflow
  task; cadence: per run). Never to the Bronze bucket.
- **Pin the GX major version at ticket time and write against that API only.** GX's
  0.x and 1.x context/checkpoint APIs differ substantially; mixing a tutorial from one
  with code from the other is the predictable way to lose a day.
- **GX is an optional extra, not a core dependency**, installed in the one image. No
  `raincheck` pipeline module imports it — the adapter that turns rows into a
  validation result is the only code that does.

### 7. Migration parity and the shadow period

- **The gate is content equality**: row counts plus a sha over sorted rows per
  partition. Byte-identity holds only within one JVM session (parquet-mr permutes
  footer encoding order across sessions, ~27 bytes, data pages identical), and a DAG
  run is by construction a different session than `make daily`. This is the same
  `assets_version` pattern already in the codebase.
- **The implementation is `raincheck.parity`, declared by `.scratch/cloud/spec.md`'s
  testing decision 4** with this effort listed as one of its three consumers. This
  spec **consumes** it. If it has not landed when the migration ticket starts, this
  effort builds it to that interface — one module, never two.
- **The shadow DAG writes to a shadow data root** (the existing archive-root
  environment variable, seeded read-only from R2). It never writes the live Silver,
  Gold or live prefixes.
- **The mutating stages are disabled during shadow**: `gapfill`, `coldpush` and
  `prune`. Each is a single-owner writer against shared Bronze / R2 / `live/`, and two
  writers is a data event, not an experiment. The map's "shadows the 06:00 job N days"
  did not say this; without it the shadow period is two writers on one Bronze.
- **What the shadow proves**: per-partition content equality for `events`,
  `leg_hours`, `gold` and `precip`, plus stage-outcome equality for the read-only
  checks — the DAG's rows and the Mac's rows agree, verdict for verdict.
- **What the shadow cannot prove, stated plainly**: `gapfill`, `coldpush` and `prune`
  parity. Those are proven the morning after cutover by their own checks — `gapcheck`
  green with the Mac stopped, `coldcheck` green after the push, the 48 h horizon
  verified by listing — with exactly one owner running.
- **Seven clean days, two independent proofs per day** (content equality; outcome
  equality), matching the discipline of the capture cutover.
- **Then retirement**: bootout the 06:00 LaunchAgent, and add the line to the Mac
  decommission checklist in `.scratch/cloud/spec.md` §10. The archiver and
  `precip-live` agents are not this effort's.

### 8. The START question — closed

- **DEFAULT: START stays 2026-08-15.** The live-era suites cover START..yesterday; the
  backfill era (2026-03-01..08-14) is asserted against R2 by `backfill-verify.py` and
  its own DEAD list, with the zero-byte-part rule and empty `_gapfill` markers exempt.
- **Overturning it has a precondition written in the code**, and it is not optional:
  moving START back means adding the probed source-dead hour `vp 2026-04-27 h04` to
  the fill-time DEAD map, which is deliberately absent today precisely because the
  check iterates from START and a pre-START key would sit there looking like
  protection it does not provide.
- **`gapverify` is never pointed at the pre-live range** under any START. With no
  same-day archiver pair it falls through to an August day and prints a false OK —
  which the row contract now surfaces as INCONCLUSIVE rather than silence.

### 9. Observability and the showcase surface

- **Task logs**: routed to R2 by the cloud spec's Airflow install; retention is a
  bucket lifecycle rule. This spec's only requirement on a log line is that it carries
  the stage name, the outcome vocabulary, and the timing line `daily.py` already
  prints.
- **The Airflow UI is not the showcase surface.** The cluster has no inbound path from
  the internet by standing decision, so the UI is reachable by port-forward only. The
  shareable surface is therefore **static artifacts on the static host**: the Data
  Docs, a rendered DAG graph, a run summary, and a short written walkthrough. Anything
  that requires cluster access is not part of the portfolio view.
- **The fan-out claim is demonstrated, not asserted**: one recorded run whose `events`
  map is at least five days wide, its per-task durations exported next to the measured
  serial baseline (1928 s for a 7-day catch-up in one session, ~275 s/day at steady
  state).
- **No raw MTA data in any published artifact**, which the row contract's no-payload
  rule already guarantees for the Data Docs.

### 10. Ticket 6 — already resolved, nothing to build

`gapfill`'s rc-0-on-empty-fill hardening landed before this spec was written, with
three tests. The recorded design decision stands and the DAG simply inherits a
truthful exit code: the bar is "nothing at all worked", **not** "something failed",
because gtfsrt.io lags 1-2 days and the newest day of a default span is routinely
unpublished — failing on that would page every 06:00 about a hole that fills itself
tomorrow. `/to-tickets` should not cut a ticket for it.

## Testing Decisions

**What makes a good test here.** Assert on external behaviour: the declared stage
contract, the outcome a check returns for a seeded state, the exit code a set of rows
aggregates to, and the graph the DAG builds from the declaration. Do not assert on
Airflow internals, on GX's rendered HTML, or on a log string's punctuation. Where a
test needs a tool that a plain checkout does not have (Airflow, GX, a renderer), it
**skips cleanly** — the discipline the existing suite already uses for optional tools.

**Seams — three reused, one new, one thin, one consumed.**

*Reused:*

1. **The `make` target / `python -m raincheck.<module>` boundary stays the unit of
   work.** No stage is re-implemented for the DAG, so the whole existing suite (356
   tests) remains the migration's safety net. This holds only as long as no ticket
   forks a module for Airflow.
2. **`tests/test_daily.py`** — stub the make targets and the Spark build, run the real
   driver, let `prune` run against seeded dirs, JVM-free. It already pins the stage
   order (`test_gapfill_runs_before_gapcheck`), the deferral behaviour, the
   red-stage-still-runs rule and the coldcheck re-push. Those tests re-point at the
   lifted declaration and keep passing unmodified — **that is the refactor's gate**,
   and after it they cover both runtimes at once.
3. **`tests/test_gapfill.py`** — the existing seam for check behaviour; the row
   contract's producer tests extend it rather than starting a parallel file.

*New:*

4. **The check-result row contract** — one module boundary, three consumers (the CLI's
   printed lines and exit code, the DAG's outcome mapping, the GX batches). Tests:
   - a seeded root with a real fillable gap yields a `fail` row naming the hours;
   - a miss covered entirely by the DEAD allowlist yields `ok`, with the dead hours
     still reported;
   - a DEAD entry whose hour is present yields `fail` (the stale-entry case the check
     already prints);
   - **a check with nothing to compare yields exactly one `inconclusive` row and never
     `ok`** — seeded as a root with a filled hour and no same-day captured hour, which
     is the current false-OK;
   - aggregation: rows to rc is 0/1/2, with 2 only when there are no `fail` rows, and
     an `inconclusive` alongside a `fail` still aggregating to 1;
   - the batch's column set equals the declared one and contains no feed payload
     column — the assertion that keeps Data Docs publishable;
   - the printed lines are unchanged for a state that produced a given line before.

*Thin, guarded:*

5. **A DAG structure test**, skipped when Airflow is not importable. Renders the DAG
   and asserts: it imports with zero errors; task ids and edges equal what the stage
   declaration says; every edge is `all_done`; `catchup` is false and max active runs
   is 1; the schedule's timezone is America/New_York; `events`, `gapfill` and
   `gapverify` are mapped and `gold` is not; gate tasks have zero retries and transport
   tasks have more than zero; no task's callable is defined in the DAG file.
6. **A GX suite test**, skipped when GX is not importable: each named suite exists and
   validates a fixture batch of rows containing one passing, one failing and one
   inconclusive subject, and the resulting validation maps to the intended DAG
   outcome — including that the inconclusive subject is neither a pass nor a fail.

*Consumed:*

7. **`raincheck.parity`** from the cloud spec. This effort adds only the migration
   gate's own test: stub the digest, assert the gate names which partitions differ,
   refuses to certify a day where a partition is present on one side and absent on the
   other, and counts a clean day only when both proofs agree.

**Prior art to follow:** `tests/test_daily.py` (stubbed make targets, real driver,
JVM-free), `tests/test_gapfill.py`, `tests/test_cloud_scripts.py` (stub binaries on
PATH, subprocess with `cwd=/` to prove cwd-independence), and the standing fixture
rule — copy real tool output verbatim into a stub rather than inventing a plausible
shape, because a wrong-format stub has already kept a data-loss bug green in this
repo.

**Not covered by tests, by design:** the shadow period's seven days of evidence, spot
eviction behaviour, Data Docs rendering, the published artifacts, and the fan-out
demonstration. Those are gates and evidence; this spec does not dress them up as test
coverage.

## Out of Scope

- **MWAA, Astronomer, any managed Airflow**, and the Celery executor. The self-hosted
  choice is the showcase; not to be re-litigated inside this effort.
- **The Airflow install itself** — Helm release, executor, metadata Postgres, remote
  logging, IRSA, capacity numbers: `.scratch/cloud/spec.md` §6 and cloud ticket 1.
- **Re-implementing any stage logic**, in DAG code or inside an expectation. A suite
  that re-derives a check is the same duplication as a DAG that re-implements a stage.
- **dbt or a second transformation framework.** Spark/DuckDB SQL own transformation,
  GX owns validation; a third tool dilutes both.
- **Alerting channels** — `.scratch/notify/map.md`. This DAG's failure surface is logs,
  Data Docs, task state and exit status.
- **`coldgaps` in the nightly DAG.** It covers unrecoverable `subway_vp` and would page
  forever on Mac-era gaps.
- **`make gates` (slice acceptance) and the in-session byte gate.** The first is
  slice-era, the second is deliberately a pytest concern; neither becomes a suite.
- **Orchestrating the 7-year backfill.** Its verification suite is defined here; its
  DAG, sizing and trigger belong to the cloud spec's backfill arm.
- **The archiver and `precip-live` LaunchAgents** — the capture cutover and cloud
  ticket 5 respectively.
- **Changing what any stage computes.** This is an orchestration move; a stage whose
  output changes has a bug, not a feature.

## Further Notes

**Four corrections this spec makes to the map, all worth reading before
implementing:**

1. **Ticket 1 is rewritten, not dropped.** The cloud spec, written the same day, already
   owns the Airflow install down to the dropped triggerer and the webserver replica
   count. Ticket 1 here becomes DAG delivery and per-task runtime; implementing both
   documents' version of "deployment shape" would produce two Helm value sets.
2. **Airflow catch-up must be OFF.** The map's phrase "catch-up semantics replacing
   launchd's sleep-coalescing" reads naturally as `catchup=True`, and that would be a
   stampede: every stage is already a bounded-window catch-up, so replaying missed
   intervals runs the same 14-day scan N times and recovers nothing the next single run
   would not. The catch-up lives in `gaps()`, not in the scheduler.
3. **`gapverify`'s "0.85-1.2x same-day band" is a measurement, not a threshold.** The
   module enforces roughly an order of magnitude on the row ratio and ~3x on key
   coverage; 0.85-1.2x is what ticket 20's run happened to observe. Writing the observed
   figure into a suite would quietly tighten the gate by a factor of ten. Section 6 keeps
   the suite at the enforced band and names tightening as its own decision.
4. **The shadow period needs a shadow root and a disabled-mutation list.** "The DAG
   shadows the 06:00 launchd job N days" is two writers on one Bronze unless the DAG
   writes elsewhere and `gapfill`/`coldpush`/`prune` are off. That also bounds what the
   shadow can prove, which section 7 states rather than implies.

**One live bug the row contract surfaces.** `gapfill.verify()` returns 0 when it finds
no filled/captured hour pair to compare — it prints that it found no pair and reports
clean. That is the pre-live false-OK class ticket 20 documented, in the opposite
direction, and it is presently reachable on any kind that has been filled but never
captured on the same day. The third outcome is not a reporting nicety here; it is the
fix.

**One leak the row contract prevents.** GX renders unexpected values into Data Docs. If
a suite expected directly on Bronze, publishing Data Docs to the static host would
publish MTA feed rows to a public host. Expecting on aggregate rows means the worst a
failing expectation can leak is a count and an hour label.

**One constraint on the showcase that the map did not name.** The cluster has no inbound
path from the internet, so the Airflow UI is port-forward-only. The portfolio view has
to be static artifacts published to the static host — Data Docs, a rendered graph, a run
summary, a walkthrough — not an invitation to log in.

**One dependency to check before starting the migration ticket:** whether
`raincheck.parity` has landed from the cloud effort. Three consumers are declared
against it; if two efforts each build their own digest, the parity gate stops being one
gate.

**The decision most worth Ross's veto:** lifting the stage list out of `daily.py`. It
touches a module that works and is currently driven by a LaunchAgent, for the DAG's
benefit. The alternative is that the DAG hardcodes its graph and a test asserts the two
agree — the same guarantee, more code, and the drift becomes something CI catches rather
than something that cannot happen. The recommendation is the lift, gated on every
existing `tests/test_daily.py` test passing unmodified.
