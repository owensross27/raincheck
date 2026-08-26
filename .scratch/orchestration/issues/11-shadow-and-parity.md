# 11 — Shadow mode and the parity gate

**What to build:** The DAG runs beside the LaunchAgent for a shadow period and proves it
builds the same data — **into a shadow data root**, with the mutating stages disabled.
Shadowing against the live tree would mean two writers on one Bronze, which is a data
event, not an experiment. Parity is content equality (row counts plus a sha over sorted
rows per partition), never bytes: byte-identity holds only within one JVM session, and a
DAG run is by construction a different session than the LaunchAgent's.

**Blocked by:** 05 (the nightly DAG), 06 (fan-out) — so the shadow tests the shape that
will actually run. **External:** the shared parity module declared by the cloud effort.

**Status:** ready-for-agent

- [ ] The shadow DAG writes to a shadow data root and never touches the live Silver, Gold or live prefixes
- [ ] The fill, the cold push and the live-table prune are disabled in shadow mode, and the run says so rather than silently skipping them
- [ ] Parity is content equality per partition, computed by the shared parity module; if it has not landed from the cloud effort, build it to that interface — never a second implementation
- [ ] The gate names which partitions differ and how, and refuses to certify a day where a partition exists on one side only
- [ ] Each shadow day records **two independent proofs**: per-partition content equality, and outcome equality between the two runtimes' check rows
- [ ] The ticket states in writing which stages shadowing cannot prove — the three mutating ones — and how they get proven after cutover


## From orch 06's landing (2026-08-25, `orch06-fan-out`, `0a9c4e6`) — the graph is fanned out

**Final task ids, declared order:** `plan_kind · gapfill · gapverify · gapcheck · coldpush ·
coldcheck · plan_service_date · events · gold · precip · prune · report`. Still linear,
still `all_done` on every edge, `report` last.

- **Mapped:** `gapfill` and `gapverify` over `kind` (5 pods each — `gapfill.KINDS`),
  `events` over `service_date` (one pod per gap day the scan returns). **Not mapped:
  everything else, `gold` included.** `precip` keeps its declared `month` axis and stays ONE
  pod: 1-2 MRMS months in a single Spark session. Which axes this runtime maps is
  `MAPPED = ("kind", "service_date")` in `dags/raincheck_daily.py`, the only new opinion in
  that file — it names axes, never a stage.
- **The two `plan_<axis>` tasks are not stages** (they are not in `daily.STAGES`, like
  `report`). Each runs `python -m raincheck.daily plan <axis> /airflow/xcom/return.json` with
  `do_xcom_push=True`, in the same measured shape as the first stage that maps on it.
  They exist because Airflow can expand a task only over an XCom and only a pod can read the
  data root. `plan_service_date` sits AFTER the fill on purpose.
- **`gold` is a stage now** — `daily.STAGES` gained it and `Stage` gained a `reduces` field.
  One non-mapped reduce behind the mapped days: it takes the plan's day list as its trailing
  argument and rolls the months of the days that LANDED, deciding that from the disk
  (`daily.silver(root, day)`, the same predicate `gaps()` defers on). **A breadcrumb row is
  `{task_id, map_index, state, operator, duration}` and cannot name a Service date** — that
  is measured, and it is why the reduce reads the disk rather than joining task states.
- **One item reaches a pod as the container's ARGS** (Kubernetes joins command + args), so
  every stage's process form is unchanged and the item is its trailing argument:
  `python -m raincheck.daily events 2026-08-20`, `python -m raincheck.gapfill fill vp`.
  (`gapfill` gained an `argv` and its `--feed` became the positional it always called `kind`;
  `make gapfill KIND=vp` is the make form.)
- **A zero expansion is a `skipped` task and a green run; a plan that pushed no XCom at all
  is `upstream_failed`** — so "no gaps this morning" and "the scan broke" can never be
  confused (Airflow 3.2.2 `models/taskmap.py`, cncf-kubernetes 10.17.1 `EMPTY_XCOM_RESULT`).
- **Sizing:** a task is TWO burst pods (executor worker + stage pod), so N mapped days is 2N
  pods and 2N Karpenter decisions; node purchase (95 s + 74 s measured) dominates a short
  stage. Baseline the fan-out exists to beat: **1928 s serial for 7 days.**
- **UNPROVEN, and it is on the critical path of anything that RUNS this graph:** the plan
  pod's xcom-sidecar handoff has never executed on the cluster — orch 06's helm upgrade was
  permission-denied, so the DAG image built and self-checked but never ran in front of a
  scheduler. The operator stamps an **`alpine:3.23.4` sidecar (Docker Hub, unauthenticated)**
  and `exec`s the result file out of it; `pods/exec` is granted (measured). The wave-5 gate
  carries the owed proof; read the OWED paragraph in `06-fan-out.md` before debugging a
  mapped task that never starts.

**For the shadow specifically: a shadow day is ONE MAPPED INDEX, not a run.** The cluster
side of a day is the `events` pod for that Service date plus the single `gold` behind it;
the Mac side is `daily.build(root, closed, days, service_date=D)` then `daily.gold(root,
days)`. `python -m raincheck.daily events <YYYY-MM-DD>` is the exact form both run, which is
what makes the two sides comparable at all — compare at the PARTITION level, as the ticket
already says. Note `daily.build` no longer rolls Gold: if a shadow day compares Gold, it has
to run the `gold` step too, and give it the day list.

## From orch 13's landing (2026-08-25, `orch13-showcase-surface`) — record your shadow run

**Your shadow is the FIRST real run this project will have had**, and the showcase says so
in its own words today: measured 2026-08-25, `s3://raincheck-bronze/airflow-logs/` holds
only `dag_id=raincheck_gateprobe` and `dag_id=raincheck_smoke`, so the recorded run on the
public surface is the wave-5 gate's PROBE, labelled `probe`, with the page stating that a
probe is not a nightly and that its map is three wide rather than five.

**Recording yours is two commands and no new code**, once your run's logs are on R2:

    aws s3 cp s3://raincheck-bronze/airflow-logs/dag_id=raincheck_daily/run_id=<id>/ \
        <dir>/ --recursive --endpoint-url $RAINCHECK_COLD_ENDPOINT
    python -m raincheck.showcase --logs <dir> --label shadow

That writes `research/orch-13-run-<run_id>.json` (commit it - the render must not need the
cold credential) and re-renders `web/showcase/`. `--label` is REQUIRED and is
`probe|shadow|nightly`: the label decides what the page CLAIMS, and a shadow shown as a
nightly is the one failure that surface exists to avoid.

**What the record derives, so you know what it can and cannot say.** Per instance:
`task_id · map_index · tries · started · ended · seconds · state · exit_code`, the newest
attempt winning. **State is derived from each log's own ending, in the operator's own
precedence** - a `Skipping task.` line BEFORE any `error` line, because an INCONCLUSIVE
gate logs both. Identity comes from the log LINES, never the key path, so copying the logs
anywhere is safe. `totals.widest_map` is the fan-out's claim, MEASURED: five or more is
what ticks orch 13's open checkbox, and only a real gap scan can produce it. The verdict is
`daily`'s own closing line out of the `report` task's log (`[base] daily: OK` /
`INCONCLUSIVE - ` / `FAILED - `) and **never the DagRun state**.

**A zero expansion writes NO LOG at all** (never scheduled), so it appears in the graph and
in no row of the run table - which is also why the pod count is 2 x instances that RAN.


## Close-out — what the shadow is, and what shadowing CANNOT prove (2026-08-25, `orch11-shadow-parity`)

**What shipped.** `dags/raincheck_shadow.py` (the nightly's build shape on a SHADOW data
root), `raincheck_stage.at_root()` / `stage_task(root=)` (the one difference a shadow is
allowed to have, rewritten on every container of the pod and *asserted* — a shape that
stopped binding `RAINCHECK_ARCHIVE_ROOT` raises rather than defaulting), and
`scripts/shadow-day.py`, which runs BOTH sides and records the pair. `raincheck.parity` is
consumed as-is; there is no second definition of "equal" anywhere in this ticket.

**The shadow root is `s3a://raincheck-bronze/shadow`** — a prefix of its own inside the
archive bucket, never the bucket root (that IS the cold mirror, and it holds the reference
tables every build reads) and never the Mac's tree. The Mac side builds into a LOCAL shadow
root (`~/raincheck-shadow` by default) whose `archive/`, `ref/` and the four `silver/`
reference tables are SYMLINKS to the Mac's real tree: its outputs are its own, and the live
Silver and Gold are never written. That symmetry is not tidiness — `gold` rolls a month out
of whatever Silver its root holds, so a reduce over the Mac's whole August could never equal
a reduce over the two days the shadow staged.

**Two independent proofs per shadow day, both recorded in `research/orch-11-shadow.json`:**

1. **CONTENT** — `parity.compare()` at the **PARTITION** level, on
   `silver/events/service_date=D`, `silver/leg_hours/service_date=D` and the reduce's
   `gold/cell_hour_speed|cell_hour_route/month=M`. Partition level and never the table root:
   a shadow root holds the days it staged and nothing else, so a table-rooted compare lists
   every other partition as `only_in_b` and can never be `ok` — a red verdict that says
   nothing about the day under test. Pinned by
   `tests/test_parity.py::test_a_shadow_is_compared_at_the_partition_level_and_never_at_the_table_root`.
2. **OUTCOME** — the two runtimes' own record of what happened: Airflow's task states (the
   expansion is exactly as wide as the day list, every index `success`, the reduce
   `success`) against the rc `daily.py` exits with on the Mac. Independent of every sha
   above: a build that wrote the right bytes and reported a failure, or reported success on
   a day it never expanded to, is a cutover defect no digest can see.

**A precondition the recorder enforces before it believes either proof: the two sides read
the SAME Bronze.** `parity.compare` runs over each input partition (`archive/{vp,tu}/date=D`
and `date=D+1`, because `events` reads `date IN (D, D+1)`), local against shadow, and a day
whose mirror is a part behind is INCONCLUSIVE rather than DIFFERS. Without it the comparison
is a statement about the cold mirror, not about the two runtimes. And both sides' outputs are
DELETED before either builds — cloud 13's trap encoded: its first comparison ran a fresh
remote build against a Mac partition built two days earlier and reported 1,469,145 vs
1,354,911 rows, which reads exactly like a broken writer and was sixteen `gapfill` parts
landing in between. **Build both sides, then compare** — neither side may be an artifact that
was already lying there.

### The three mutating stages — why a shadow cannot prove them, and what does

The shadow DAG's FIRST task echoes the declared stages it does not run, derived from
`daily.STAGES`, so the run says it rather than silently skipping them. Three of them mutate
state the Mac also writes; a shadow that ran them would BE the second writer it exists to
avoid.

**1. `gapfill` — writes Bronze.** Its target is the one Bronze tree both runtimes read, and
its subject is "which hours are missing *there*". Run against a shadow copy it reads the
copy's own `missing_hours()`, so it would fill hours that are already filled in the real tree
and prove nothing about the real gaps; run against the real tree it is the data event.
**Proven after cutover by its own two checks, which already exist and already write rows:**
`gapverify` compares each filled hour against its archiver neighbours (a row per kind under
`<root>/checks/check=gapverify/`, `row_ratio`/`key_ratio` inside `gapfill.ROW_BAND`/`KEY_BAND`
— the module's bands, never the measured 0.85-1.2x), and `gapcheck` reports what is still
missing per kind x closed day. On the first nights after cutover the falsifiable reading is:
`gapcheck`'s missing set equals what the Mac's last night reported minus what the fill filled,
and `gapverify` has a judgeable pair for every kind. orch 09's `fill-fidelity` suite expects on
exactly those rows, so the GX page is the standing form of this proof.
*(A weaker pre-cutover option exists and is deliberately not claimed as parity: stage a day
with one hour removed and watch the shadow's fill restore it. That is a functional test of the
fetcher, not a statement that the two runtimes fill the same tree the same way.)*

**2. `coldpush` — writes the cold mirror.** `aws s3 sync <root>/archive -> s3://<bucket>/archive`:
its destination is the bucket the shadow root is a prefix OF. From a shadow root it would push
the copied subset back over the objects it was copied from — a no-op whose green would be about
objects that were already there. And the claim changes shape at cutover: once the data root IS
the bucket, "push Bronze to R2" is local-to-itself and stops meaning what it means today, which
is a writer question **cloud 10 owns and orch 12 must not assume away**. **Proven after cutover
by `coldcheck`'s own rows** (a check straight after the push, one row per top-level `archive/`
prefix, `differing` counts) and by `make coldgaps` for the loss-versus-drift distinction that
`coldcheck` deliberately does not make; orch 09's `cold-mirror` suite expects on the row
convention and reports without gating, which is the right strength for a check whose red is
usually the capture box's overlapping write.

**3. `prune` — deletes.** `stream.prune(root)` removes `live/date=/hour=` past the 48 h
horizon. A deletion cannot be compared: two runtimes cannot both delete the same directory and
be observed doing it, and a shadow root has no `live/` at all (the streaming job writes it, and
`precip_live` still refuses an object-store root outright). It is also the only stage whose
damage is irreversible, which is why **orch 12's rollback line matters most here.** **Proven
after cutover as a property of the tree AFTER a run**, on any morning, with one listing:
`live/` holds no partition older than the horizon AND still holds the newest hour — falsifiable
in both directions (nothing pruned, or too much). Watch it on every one of the first mornings,
because a `prune` that over-deletes is not recoverable from the cluster side.

### What else a shadow does not prove, said plainly

- **The scheduler's clock.** Every shadow run is triggered by hand. That the 06:00
  America/New_York timetable fires, that `catchup=False` holds under a missed interval, and
  that DST is followed are proven only by the first unpaused nightly's own `run_id`
  (`daily-YYYY-MM-DD`) and `next_dagrun_logical_date`, and the DST boundary only by living
  through one.
- **`precip`.** Not in a shadow day: it rebuilds the current MRMS month and fetches unlanded
  Pass2 hours from outside, at month grain, off inputs the shadow root does not hold.
- **`gxcheck`.** It expects on the check rows THIS run wrote, and a shadow day writes none.
  Independently, **GX Data Docs are POSIX-only — `gx.run()` refuses an object-store root** — so
  a shadow on an `s3a://` root structurally cannot run it. The first Data Docs tree is landed by
  the first real nightly, which is orch 12's, not this ticket's.
- **The three outcomes end to end in a real nightly.** rc 2 -> `skipped`, rc 1 -> `failed` and a
  zero-length expansion -> `skipped` were all proven on the cluster at the wave-5 gate
  (`gateprobe-1`), synthetically. No real check has exercised them.
- **Contention.** Both sides ran alone. Nothing here says what a nightly does while the
  streaming job, the live loop and the capture box are all writing.

### The ledger, and how orch 12 counts seven clean days

`research/orch-11-shadow.json` is a JSON array, appended one entry per shadow DAY (a run
over N days appends N entries). Each entry carries `day`, `recorded_utc`, `run_id`,
`shadow_root`, `mac_root`, `inputs_equal`, `inputs_reconciled` (the input partitions that
had to be taken from this Mac rather than the mirror - see the finding above), `content`
(one compare per partition, with the row count and the leading 12 of the sha per partition),
`outcome`, and `clean` - the AND of both proofs. **Seven clean days is
`sum(e["clean"] for e in ledger)`, and the count starts at the first entry recorded by this
ticket.** A re-run of the same day appends a SECOND entry rather than replacing the first:
the ledger is a receipt log, not a state file, and a day that went red once and clean on a
retry is exactly the thing a cutover gate should be able to see.

`scripts/shadow-day.py DAY [DAY ...]` is the whole procedure; it exits 0 only if every day
it was given is clean, 1 if a day differs and 2 if a step could not be run (the third
outcome, as everywhere else here: could-not-check is never rendered as either verdict).
A run over several days is ONE cluster run with a mapped expansion that wide - which is
also the cheapest way to buy shadow days, because a task is two burst pods and the node
purchase, not the work, is what a short stage costs.

**The shadow DAG reaches the cluster only in the `-airflow` image**, like every other DAG:
there is no git-sync and no DAG volume. A wave gate's image build over the landed tree is
what delivers it; a ticket session that needs it before then builds the `dags` target alone
under a scratch tag and converges with a temporarily edited (never committed)
`deploy/airflow/values.yaml`, which is what this session did. **`raincheck_daily` stays
PAUSED throughout - unpausing it is orch 12's cutover, not this ticket's** - and only
`raincheck_shadow` is unpaused.

### What the first shadow runs MEASURED, and the two decisions they forced

Four runs, all on the pinned runtime `2396b26f00b0`, all against
`s3a://raincheck-bronze/shadow`, `raincheck_daily` `is_paused True` throughout.

**1. Karpenter consolidates a running batch pod out from under itself, and it reads as an
OOMKill.** Run one: an `events` stage pod seven minutes into its Spark build died with
`exit_code=137`, `reason='Error'` — and the pod events say `Evicted pod: Underutilized`.
The `burst` pool is `WhenEmptyOrUnderutilized` + `consolidateAfter: 1m`, which is right for
reclaiming a FINISHED build fast and fatal to a long one: as a fan-out's short tasks finish,
their node reads underutilized. **A task is TWO pods and both need protecting.** Annotating
only the KubernetesPodOperator's stage pod (the placement table) fixed one of two mapped
indices; the other still died, because the EXECUTOR'S WORKER pod is a different template
(`workers.kubernetes.podAnnotations`) and evicting it kills the task instance however well
the stage pod is pinned. Both now carry **`karpenter.sh/do-not-disrupt: "true"`**. The
chart's own `cluster-autoscaler.kubernetes.io/safe-to-evict: "false"` on that template is a
**no-op on this cluster** — wrong autoscaler. Filed and deliberately NOT changed here: a
pool that only ever runs batch arguably wants `WhenEmpty`, but a NodePool change means
applying manifests, which is cloud 10's sequencing.

**2. An exact sha over a distributed float aggregate cannot match across two runtimes.**
With both sides finally building to completion, `silver/events` came back **equal to the
sha on both days** and `silver/leg_hours` did not — same row count, different digest. One
column: **`dist_m_sum`, a `sum()` of DOUBLEs.** Floating-point addition is not associative
and the two runtimes split their input differently (`local[6]` over local files against
`local[2]` over s3a splits), so the addition order and the last bit move — **16,773 of
72,087 rows, max relative difference 1.24e-15, one ULP**; the whole-table total differs by
3e-8 in 2.2e8. `gold/cell_hour_speed` inherits it from the same column, `gold/cell_hour_route`
and `silver/events` are exactly equal. **So a cutover gate built only on an exact digest
could never go green on a correct build.** `raincheck.parity` is left exactly as it is —
cloud 03's T17 backfill gate reads it and wants exactness — and the SHADOW states the bound
instead: when the exact answer is no it asks which columns differ and by how much, and
certifies the partition only if the row counts match, every differing column is
floating-point, and every one is inside `FLOAT_TOL = 1e-9` (six orders above what was
measured, far below anything that could mean something about a bus). A changed row count, a
string or integer column, or a float beyond the bound stays a real difference.
**The alternative, filed and NOT taken: round the float aggregates at write time so the
artifact is bit-reproducible. That changes published values in `events.py` and `gold.py`,
and it is orch 12's / cloud 10's decision, not a shadow's.**

**3. `silver/events` IS NOT REPRODUCIBLE FROM ITS OWN INPUTS, AND THE SHADOW IS WHAT SAYS
SO. FILED, NOT FIXED — it is a change to enrichment semantics, not a shadow's to make.**
The recorded pair came back `2026-08-23` **CLEAN** and `2026-08-22` not: its `events`
partition had the same **750,226** rows on both sides and a different sha, and the differing
column was **`schedule_relationship`, a VARCHAR, on 10 rows** — not floating point, so the
bound above correctly refused to certify it. The same day had matched exactly on the
previous run, which is the tell: this flips between runs of the SAME code on the SAME input.

**Mechanism, measured rather than reasoned:** `enrich._dedupe` is
`vp.dropDuplicates(["vehicle_id", "ts", "stop_id", "lat", "lon"])`, and `dropDuplicates`
keeps an **arbitrary** row from each group — Spark defines no winner, so the survivor
follows shuffle order, which differs between runtimes AND between runs. On this Mac's own
Bronze:

| day | dedupe groups | groups whose members DISAGREE about `schedule_relationship` |
|---|---|---|
| 2026-08-22 | 16,127 | **255** |
| 2026-08-23 | 25,752 | **0** |

Which is exactly why 08-23 is clean and 08-22 is a coin flip. (The sibling dedupe in
`legs()` is NOT the source — measured: zero groups there where the earliest `fetched_at`
ties and the label disagrees.)

**The fix, named so nobody has to re-derive it:** give the survivor a TOTAL ORDER instead of
an arbitrary one — `row_number()` over the same identity ordered by `fetched_at` ascending
(which is the rule `legs()` already states in its own comment for the same situation) with
the remaining columns as tie-breaks, or the `F.min(F.struct(...))` idiom `events.py` already
uses. The file even contains the pattern: `enrich.py:168` orders on
`"ts", fetched_at, "stop_id"` with the comment `# stop_id: deterministic ties`. It changes
`silver/events` values on the ambiguous rows only, from *undefined* to *defined*, and it
cannot touch a day with zero ambiguous groups.

**Why this ticket did not take it:** it is a data-semantics change in a core enrichment
module that no wave-6 ticket owns, discovered by the shadow that exists to discover it, and
the shadow's job is to report it with the mechanism and the numbers. **orch 12 must decide
before it counts seven days**, because until it is fixed a day with ambiguous groups can go
NOT CLEAN at random — and the recorder names the offending column, so that is a diagnosis
rather than a mystery. The alternative to fixing it (widening the shadow's tolerance to
non-float columns) is NOT acceptable: it would certify exactly the class of difference the
gate exists to catch.
