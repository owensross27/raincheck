# raincheck cloud runtime: build spec

Status: ready-for-agent
Source: wayfinder map `.scratch/cloud/map.md` (10 tickets to cut, review round 1
applied). Written 2026-08-23. Vocabulary is CONTEXT.md's (Poll, Snapshot, Ping,
Stop row, Cell, Pixel, Service date, Bronze/Silver/Gold); ADR-0002 is binding
wherever MRMS is touched. Cross-map boundaries: the Airflow **DAG design** belongs
to `.scratch/orchestration/map.md`, alerting channels to `.scratch/notify/map.md`,
the flood model chain to `.scratch/flood-build/`. This spec owns the **platform
underneath all three**.

One honesty note before anything else: the map lists ten tickets "to cut" and
`.scratch/cloud/issues/` was never populated, so several forks the map names
(nodegroup vs Auto Mode, 1 vs 3 brokers, operator vs submit) arrive here still
open. This spec closes each of them with a stated default and a named rule that
would overturn it, rather than shipping the fork downstream. Every such decision
is marked **DEFAULT** with its overturn trigger. Two decisions correct the map
rather than extend it; both are called out in Further Notes.

## Problem Statement

raincheck runs on Ross's Mac. The streaming job, the 06:00 daily catch-up, the
300 s precip tick and the 30 s live export are all LaunchAgents on one laptop:
close the lid and the pipeline stops, and the only reason the data survives a
sleeping Mac at all is a catch-up job that spends its morning filling the holes
the night left. Bronze capture has already escaped — a t3.small box captures all
six feed kinds 24/7 with hourly push to R2 [T19] — but everything downstream of
capture is still Mac-shaped: a single `local[6]` Spark session with a 3 g driver,
one day built at a time, no retries, no supervision, nothing restartable, and a
build backlog that can only be worked through serially. There is no headroom to
run the 7-year backfill [T17], no way to fan a 167-day rebuild out in parallel,
and no platform for the two efforts that are already planned on top of this one
(Airflow + Great Expectations, and the query/notify layer). The showcase problem
is the same problem: the pipeline works, but nothing about how it runs is legible
to anyone but Ross.

## Solution

Move everything except capture onto a single EKS cluster inside a ~$100/month
envelope, keeping every unit of work exactly as it is today.

- **The cluster carries the runtime.** Kafka (Strimzi, KRaft), the Spark
  structured-streaming driver, Airflow (self-hosted, KubernetesExecutor), the
  precip-live tick, and the live-export + detector loop all run as supervised,
  restartable Kubernetes workloads. Karpenter bursts cheap Graviton spot capacity
  so per-day `events` builds and one-off backfills fan out in parallel instead of
  queueing behind one laptop.
- **The unit of work never changes.** Every pod runs an existing `make` target or
  `python -m raincheck.<module>`. No stage is re-implemented for the cluster, which
  is what makes the existing test suite the migration's safety net and what keeps
  the documented downscale path to two plain EC2 instances real rather than
  aspirational.
- **Storage moves to the object store.** Bronze already lives in R2
  (`raincheck-bronze`, zero egress, 41.65 GB measured [T18, T20]); Silver, Gold and
  the live tables join it, read and written over `s3a://`. Only the Spark streaming
  checkpoint — single-writer by definition — stays on a block volume.
- **Capture stays where it works.** The box runs untouched through its 2026-08-31
  fail-closed cutover [T19] and, by default, keeps running afterwards: a cluster
  upgrade must never be able to take capture down.
- **Each Mac daemon retires only on proof.** Every remaining LaunchAgent gets a
  T19-style fail-closed gate — two independent proofs per day, seven clean days,
  content-equality parity against the Mac's own output — and the Mac ends as a dev
  checkout, not a runtime.
- **Freshness is bounded by the sources, not by us.** The bus chain stays ~1-2 min
  end to end (30 s poll, 30 s trigger, 30 s export). Live precip advances on hourly
  `:00` MRMS RadarOnly stamps caught by a 300 s tick, fresh to 90 min under the
  flood budget [T11, flood spec]. No cluster makes a feed publish faster, and this
  spec claims no improvement it cannot demonstrate.

## User Stories

### Running it at all

1. As the operator, I want the pipeline to keep building while my laptop is shut,
   so that a closed lid stops being a data-quality event.
2. As the operator, I want every long-running job supervised by Kubernetes, so
   that a crashed streaming driver restarts itself instead of waiting for me to
   notice.
3. As the operator, I want the streaming driver to resume from its checkpoint after
   any restart, so that a pod eviction costs latency and never costs Snapshots [T12].
4. As the operator, I want each workload to declare its resource requests, so that
   the cluster schedules against real numbers rather than hope.
5. As the operator, I want a node interruption to be a normal event, so that
   spot-first capacity is a cost decision and not a reliability gamble.
6. As the operator, I want every pod to run the same image, so that "works in the
   daily build" and "works in the backfill" mean the same thing.
7. As the operator, I want the image tagged by git sha, so that I can say exactly
   which code produced a partition.

### Building faster

8. As the operator, I want per-day `events` builds to run in parallel, so that a
   167-day rebuild is bounded by the widest day rather than by the sum of all days.
9. As the operator, I want burst capacity to cost nothing when idle, so that
   parallelism does not turn into a standing bill.
10. As the operator, I want a killed build task to re-run safely, so that spot
    interruption is absorbed by idempotence rather than by cleanup [T15, research/07].
11. As the operator, I want `gold` rolled up once behind the mapped days, so that
    the monthly reduce is not repeated per day [daily.py].
12. As the operator, I want the 7-year backfill sized and run as its own job shape,
    so that a 2,278-file one-off never borrows the nightly job's assumptions [T17].
13. As the operator, I want the backfill's precondition to be R2 headroom rather
    than a dead SSD, so that the trigger is something I can actually measure.
14. As the operator, I want the Mac-shaped `local[6]` + 3 g Spark config re-measured
    on cluster hardware, so that I size pods from evidence rather than from a laptop.
15. As the operator, I want to know that `events` is ~275 s/day at steady state and
    that the 1928 s figure was a 7-day catch-up, so that capacity planning starts
    from the right number [T15].

### Kafka and the stream

16. As the operator, I want Kafka on the cluster rather than managed, so that the
    broker fits inside the budget the control plane leaves.
17. As the operator, I want topic partition count fixed correctly at creation, so
    that I never have to drop retained messages to change it [T10, topics.py].
18. As the operator, I want 48 h delete retention and zstd preserved exactly, so
    that the topic spec the archiver was built against still holds [T10].
19. As the operator, I want exactly one owner of the topic spec, so that two systems
    never disagree about what the topics are.
20. As the archiver on the capture box, I want a private in-VPC path to the cluster's
    broker, so that producing to Kafka never requires an internet-facing listener.
21. As the operator, I want Bronze to remain the record and Kafka a byproduct, so
    that a broker loss is a latency event and never a data-loss event.

### The live path

22. As a visitor to the map, I want vehicle positions no more than ~1-2 min old, so
    that the page shows the city as it is now.
23. As a visitor, I want the page to say plainly when it is stale, so that a dead
    exporter never looks like a quiet city [T14].
24. As the flood detector, I want every missing MRMS `:00` stamp inside the ~25 h
    retention window to land, so that the replay gate keeps working after the move
    [T11, F12].
25. As the flood detector, I want the 2-min and 15-min MRMS products kept out of
    `live/precip_cell` entirely, so that the `:00` series stays the contract it is
    [F11, ADR-0002].
26. As the operator, I want the precip tick to run the existing module unmodified,
    so that the catch-up contract is preserved by construction rather than by review.
27. As the operator, I want two precip ticks never to overlap, so that a slow fetch
    cannot race its own successor.
28. As the operator, I want the live export and the detector tick supervised
    together, so that the panel's two halves never age apart.
29. As the operator, I want the streaming trigger interval and the archiver poll
    interval treated as knobs with costs, so that tightening either is a measured
    decision and not a reflex.
30. As the operator, I want to know that 30 s polling misses ~10-15% of Snapshots and
    that tightening it grows Bronze, so that I can price the trade before taking it.

### Storage and state

31. As the operator, I want Silver and Gold in R2 beside Bronze, so that any pod on
    any node can read them without a shared filesystem.
32. As the operator, I want the live tables in R2 too, so that pruning them is not
    pinned to whichever node holds a volume.
33. As the operator, I want the 48 h live horizon enforced by the same one
    implementation as today, so that the horizon cannot drift between runtimes
    [spec J, stream.prune].
34. As the operator, I want block storage used only where a single writer is
    guaranteed, so that I never debug a two-writer volume.
35. As the operator, I want gapfill's staging disk sized for its ~1.24 GB/day, so
    that push-then-prune has room to work [T20].
36. As the operator, I want R2 to stay the durable home with zero egress, so that
    read-back for backfills stays free [T18].

### Airflow platform

37. As the DAG author, I want a working Airflow with KubernetesExecutor already
    underneath me, so that the orchestration effort designs DAGs and not a platform.
38. As the DAG author, I want the metadata database to survive a pod restart, so
    that run history is not a per-restart fiction.
39. As the DAG author, I want task logs off pod disk, so that log retention is not a
    slow-motion disk-full incident.
40. As the DAG author, I want Airflow's full footprint counted in the cluster's
    capacity number, so that adding the DAG does not evict the pipeline.

### Security, network, cost

41. As the operator, I want no inbound path from the internet to the cluster, so
    that the attack surface is the static host and nothing else.
42. As the operator, I want separate least-privilege credentials for capture-write,
    build-read/write and serve-read, so that one leaked token cannot rewrite Bronze.
43. As the operator, I want credentials out of images and in cluster secrets with a
    written rotation procedure, so that rotating is a task and not an archaeology
    project.
44. As the operator, I want a budget alarm wired before the first node exists, so
    that the first surprise is an email and not a statement.
45. As the operator, I want the monthly bill reviewed against the envelope, so that
    drift is caught in a month rather than a quarter.
46. As the operator, I want a written, exercised downscale path to two plain EC2
    instances, so that reversing this decision is a maintenance task.
47. As the operator, I want no stage to depend on a cluster-only feature, so that
    the downscale path stays real instead of decaying into a paragraph.

### Serving

48. As a visitor, I want the map, the live tick, and the insight exports served from
    a static host, so that the page is fast and the cluster is not exposed.
49. As the operator, I want the public bucket to be a new bucket, never
    `raincheck-bronze`, so that "public" and "the archive" can never be the same
    mistake [T18].
50. As the operator, I want each served payload's writer and cadence enumerated, so
    that a stale file has an owner.
51. As a reviewer, I want the Great Expectations Data Docs browsable after each run,
    so that the pipeline's own checks are visible without cluster access.
52. As the operator, I want an explicit, defensible decision about whether
    `live.geojson` counts as re-serving an MTA-derived feed, so that the standing
    rule is applied rather than quietly stepped around [T14].

### Retiring the Mac

53. As the operator, I want each Mac daemon retired only against proven cluster
    parity, so that "it seems to work" never ends a capture path.
54. As the operator, I want parity measured as content equality — row counts plus a
    sha over sorted rows per partition — so that parquet's cross-session footer
    permutation cannot fail an otherwise identical build [F01, T02].
55. As the operator, I want two independent proofs per clean day, so that a single
    broken check cannot certify a cutover.
56. As the operator, I want the no-backstop caveat stated for every gate after
    2026-08-31, so that the higher bar is deliberate.
57. As the operator, I want the T16 Transitland grant submitted or closed by a named
    date, so that an eight-month-old outstanding request stops blocking the
    decommission checklist [T16].
58. As the operator, I want the Mac to end as a dev checkout, so that "my laptop is
    part of the pipeline" stops being true.

### Demonstrating it

59. As someone showing this work, I want the ops story to be inspectable — pods,
    DAG runs, Data Docs, budget — so that the pipeline's quality is legible to
    someone who will not read the code.
60. As someone showing this work, I want the parallel fan-out visible in a run, so
    that the claim of distribution is demonstrated rather than asserted.

## Implementation Decisions

### 1. Cluster shape, capacity, and the budget envelope

- **EKS, one cluster, one region — the region and VPC the capture box already lives
  in.** The box-to-broker path must be private in-VPC networking; if the box cannot
  share a VPC with the cluster, that is a precondition failure to surface before any
  node exists, not something to route around with a public listener.
- **DEFAULT: managed nodegroup + Karpenter, not EKS Auto Mode.** Auto Mode's
  management fee scales with the always-on floor, which is exactly the part of this
  cluster that never scales to zero; hand-run Karpenter is also the stronger
  showcase. *Overturn if* the per-pod arithmetic run on the day (both priced against
  the measured floor below) puts Auto Mode inside the envelope with the operational
  saving counted.
- **DEFAULT: the always-on floor is spot-first with no on-demand node.** Every floor
  workload is restartable by design — Bronze is the record, the streaming driver
  checkpoints, Airflow's state is on a volume — so eviction costs latency, not data.
  *Overturn if* measured interruption frequency costs more rebuild time per month
  than one on-demand node costs in dollars.
- **The floor NodePool is pinned to one availability zone.** EBS volumes are
  AZ-bound; a spot replacement in another AZ cannot attach the Kafka, Postgres or
  checkpoint volume. Burst capacity for stateless build pods is not AZ-constrained.
- **Capacity accounting is a deliverable, not a guess.** Before the first node,
  produce a requests table covering: Kafka broker JVM (heap plus off-heap), the
  Spark streaming driver and its executors, Airflow scheduler, webserver, metadata
  Postgres, the live-export + detector Deployment, and the precip-live CronJob's
  burst. This ticket owns that number; the orchestration map defers to it.
- **Two footprint reductions are taken up front:** no Airflow triggerer (nothing
  here uses deferrable operators) and one webserver replica. The Mac's `local[6]` +
  3 g driver config is Mac-shaped and is re-measured, not copied [spark.py].
- **Envelope arithmetic on the table.** EKS control plane ~$73/mo fixed. *Corrected
  on measurement [T1, T8]: the original `~$27 remains` was arithmetic that never
  bought the floor. $27/mo across two nodes is $0.0092/node-hour; the cheapest
  Graviton in the region, t4g.small spot, is $0.0109 and carries 2 GiB. The floor the
  requests table actually needs — 2 x t4g.large spot at $0.0234 — is **$34.16/mo**,
  and the envelope was raised to the $130 hard-look line rather than resized down to
  fit a number.* Working shape: 2 Graviton spot nodes as the floor, Karpenter spot
  burst for builds (~$1-2/mo), gp3 for Kafka + checkpoints + Airflow Postgres (~$4/mo
  at ~50 GB), R2 under $1 (41.65 GB measured, first 10 GB free) [T18, T20]. If the
  measured requests table does not fit the floor, the resolution is a smaller
  streaming driver or a third spot node decided against the budget alarm — never a
  silent overrun.
- **MSK is rejected on budget** (~$65/mo two-broker floor cannot coexist with the
  control plane inside the envelope — $73 + $65 overruns $130 as surely as it
  overran $100). Recorded, not re-litigated.
- **The budget alarm is wired before the first node.**

### 2. Kafka on the cluster

- **Strimzi, KRaft mode**, on the floor NodePool, gp3 storage.
- **DEFAULT: one combined-role broker, RF=1, min.insync.replicas=1.** ~0.5 GB/day is
  one-broker territory; Bronze is the record and the archiver's producer already
  fails loud rather than auto-creating topics. *Overturn* — grow to 3 brokers — once
  the floor is three nodes and the AZ-pinning constraint above is resolved; that is a
  Strimzi replica change plus partition reassignment, not a redesign.
- **Six partitions per topic, fixed at creation.** This is the one irreversible knob:
  partition count cannot be changed without dropping the topic and every retained
  message. Six matches the spec the archiver was built against [T10, topics.py], and
  it is what lets broker count grow later without a second destructive step.
- **48 h delete retention, zstd, no compaction** — carried over exactly [T10].
- **`python -m raincheck.topics` stays the single owner of the topic spec**, run as a
  Kubernetes Job. Strimzi's Topic Operator is disabled so there is exactly one owner;
  two declarative sources for the same six partitions is how an irreversible knob gets
  flipped by accident.
- The archiver reaches the broker over a private in-VPC listener; no external
  listener, no public bootstrap.

### 3. Spark on Kubernetes, and the stage-placement table

- **DEFAULT: no spark-operator.** Job shape decides the execution mode:
  - **Per-day work runs as one pod per day with in-pod Spark.** `events` is ~275 s
    per day and each Service date is independent; a cluster-mode driver plus executor
    scheduling per day would spend more on scheduling than on work. Parallelism comes
    from Airflow dynamic task mapping over days on Karpenter spot capacity — which is
    what "per-day parallel builds" actually means here.
  - **Genuinely wide work runs cluster-mode `spark-submit --master k8s://`**: the
    `gold` monthly reduce over touched months, and the T17 one-off backfill.
  - **The streaming job is a Deployment** running a client-mode driver with its
    checkpoint on a dedicated block volume, recovering on restart [T12].
  *Overturn the no-operator default if* declarative SparkApplication status inside
  Airflow, or a shared Spark history UI, becomes something the showcase needs.
- **One image for every raincheck pod**, built from the existing in-house slim Sedona
  Dockerfile (`~/quakestream/stack/docker/sedona.Dockerfile`, geotools-wrapper
  1.9.1-33.5), extended with eccodes (precip), DuckDB (exports) and the repo package;
  pushed to ECR and tagged by git sha. Five specialised images would be five drifting
  runtimes.
- **Every table is read and written over `s3a://` against R2** with the endpoint
  override. No local Bronze mirror on the cluster.
- **`live/` moves to R2.** It has multiple writers and readers across pods
  (streaming writes `live/vp` + `live/tu`, precip-live writes `live/precip_cell`,
  live-export and the detector read all three), which a single-attach block volume
  cannot serve. This is what unpins `prune`: it becomes an object-prefix operation
  any pod can run, still through the one `stream.prune` implementation of the 48 h
  horizon [spec J].
- **Block storage is used only for single-writer state**: the Spark streaming
  checkpoint, Kafka's log dirs, Airflow's Postgres.
- **Stage placement for the eight `daily.py` stages** [T15]:

  | stage | where it runs | notes |
  |---|---|---|
  | `gapfill` | own pod per feed kind, ephemeral staging volume ≥ 3 GB | stages ~1.24 GB/day before push-then-prune [T20]; network-bound, no Spark |
  | `gapverify` | own pod, no Spark | reads filled hours against archiver neighbours |
  | `gapcheck` | own pod, minimal | listing only; strictly after `gapfill` [T20] |
  | `coldpush` | own pod | scoped to the gapfill staging area — capture already pushes hourly from the box [T19], so this stage now means "push what the cluster just wrote" |
  | `coldcheck` | own pod | stays soft: reports, never fails the run [T15] |
  | `events` (+`gold`) | one pod per Service date on spot burst; `gold` as a single reduce behind them | dynamic partition overwrite makes re-runs idempotent [research/07] |
  | `precip` | own pod (eccodes image), Spark in-pod | MRMS months are UTC, unlike the Service date above |
  | `prune` | any pod | unpinned by the `live/`-on-R2 decision above |

  The all-stages-always-run contract and the failure-naming exit are preserved as
  written; how they are expressed as DAG edges belongs to the orchestration map.
- **The parity gate is content equality, never bytes**: row counts plus a sha over
  sorted rows per partition. Byte-identity holds only within one JVM session —
  parquet-mr permutes footer encoding order across sessions (~27 bytes, data pages
  identical) [F01, T02] — and a cluster run is by construction a different session
  than `make daily`.
- **T17 arm.** The dead-SSD precondition is replaced by measured R2 headroom. The
  backfill is a separately sized one-off (2,278 files, not the nightly shape), run
  cluster-mode. **Trigger: the first day the `events` parity gate passes on the
  cluster** — the backfill is the first thing the cluster is trusted with, and not
  before it is trusted.

### 4. Capture placement

- The box runs **untouched** through the 2026-08-31 fail-closed cutover. This spec
  never touches that gate or its task [T19].
- **DEFAULT after the cutover: capture stays on the box.** The blast-radius rule is
  decisive — a cluster upgrade must never be able to take capture down, and a small
  box that only captures is a legitimate, cheap answer.
- *Overturn* only through a T19-style gate of its own: two independent proofs per
  day, seven clean days, plus an explicit blast-radius argument. The bar is higher
  than T19's because the Mac backstop is gone by then.
- Lambda, ECS and Fargate remain rejected for the capture shape [T19].

### 5. The live path as pods, and its latency knobs

- **precip-live: a CronJob every 5 minutes** (cron's 1-minute granularity is what
  makes 300 s expressible), `concurrencyPolicy: Forbid`, running
  `python -m raincheck.precip_live` **unmodified**.
  - **Acceptance criterion is the catch-up contract**: every missing `:00` stamp
    within MRMS's ~25 h retention lands. A latest-only reimplementation silently
    re-blocks the flood replay gate [T11, F12] — which is precisely why the pod runs
    the module rather than a shell equivalent of it.
  - The 2-min and 15-min MRMS products are **rejected detector inputs by contract**
    and may never enter `live/precip_cell`'s `:00` series. If ever used, they are a
    distinct feature and table [F11, ADR-0002].
- **live-export + the detector tick are one supervised Deployment**, beside the
  streaming driver, publishing to the static host on the existing 30 s cadence.
  STALE semantics are unchanged [T14].
- **Latency knobs are adopted only with a measured win, recorded before/after**:
  - streaming trigger: 30 s today; 10 s is a config change, not an improvement until
    measured.
  - archiver poll interval: 30 s misses ~10-15% of Snapshots [vault feeds ref];
    tightening costs Bronze volume. A real trade, priced before taken.

### 6. Airflow platform prerequisites

- Official Airflow Helm chart, **KubernetesExecutor**.
- **Metadata DB: in-cluster Postgres** (StatefulSet on a gp3 volume). A managed
  instance does not fit what the control plane leaves.
- **No triggerer; one webserver replica** — see the capacity decision above.
- **Task logs to R2** (remote logging), so retention is a bucket lifecycle rule and
  not pod disk.
- IRSA for the pods that touch AWS; R2 credentials as cluster secrets (see 7).
- This ticket guarantees the platform only. DAG structure, mapping, trigger rules and
  the Great Expectations suites are `.scratch/orchestration/map.md`'s.

### 7. Secrets, IAM, network

- **The least-privilege split is R2 API tokens, not IAM.** R2 is Cloudflare; IRSA
  cannot scope it. Three tokens: **capture-write** (the box, already in place),
  **build-read/write** (cluster batch and streaming), **serve-read/write** (the
  export path, scoped to the public bucket only). Each lands as a Kubernetes Secret
  bound to exactly one ServiceAccount, never baked into the image, with a written
  rotation procedure.
- **IRSA covers the AWS side**: ECR pull, EBS CSI, CloudWatch/budgets. One role per
  workload, no shared node role for application permissions.
- **No inbound from the internet.** No LoadBalancer or NodePort Service. The two
  named exceptions: (a) the static host, which is outside the cluster entirely (see
  9), so it is not cluster ingress at all; (b) whatever minimal subscribe ingress
  `.scratch/notify/map.md` ticket 4 decides, which must arrive as its own reviewed
  decision.
- **No NAT Gateway.** At ~$32/mo it would consume more than the entire non-control-plane
  budget. Nodes sit in public subnets with public IPs, security groups that permit no
  inbound rules, and egress allowed. *Corrected [T8]: a public IPv4 is **not** free —
  AWS has charged $0.005/hr for every one, attached or not, since 2024-02. That is
  $3.65/node/mo, $7.30 for the floor, and it grows with every Karpenter burst node.
  No-NAT still wins by a wide margin (break-even is ~9 simultaneous nodes), but it is
  a cost line in the envelope, not an absence of one.* "No inbound" is enforced by
  security groups and
  the absence of a load balancer — write it that way in the manifests and assert it in
  the manifest test, because subnet placement is not what is providing it here.
- The box-to-cluster Kafka path is a security-group-scoped in-VPC path: private
  networking, not an internet port.

### 8. Cost guardrails and kill criteria

- AWS Budgets alarm at **$130/mo** — raised from $100 by Ross on 2026-08-23 once the
  floor was measured at ~$121.5/mo [T1] — alerting at ACTUAL 80% / 100% / 130% and
  FORECASTED 100%; **$130 is the hard-look line**, so the 130% notification is the
  alarm that means it. Wired before the first node, plus an untagged `aws-account-total`
  backstop at $210 for anything created without `Project=raincheck-cloud`.
- Monthly bill review, recorded in the repo alongside the effort:
  `scripts/cloud-bill-review.sh [YYYY-MM] --append` writes one dated entry into
  `.scratch/cloud/issues/08-cost-guardrails.md` — per-service lines, the run rate
  scaled from closed days, and the delta against $130. It exits **2 INCONCLUSIVE**
  when Cost Explorer has no tag data (a $0 tagged total is an artefact, never an
  under-budget verdict) and **1 HARD LOOK** on a crossing, stamping
  `Decision: REQUIRED - not yet recorded`. `--check` re-reads the log and keeps
  failing while any crossing carries that stamp, which is what makes silent
  continuation impossible without also making it an auto-stop.
- **The documented downscale path** is the two-EC2 alternative the map recorded: an
  always-on t4g.large-class instance plus a scheduled build instance, ~$25-60/mo,
  same freshness, no per-day parallelism. Reversibility is design, not admission.
- **What keeps the downscale path real: no stage may depend on a cluster-only
  feature.** Every stage stays runnable as `make <target>` inside the same image on
  one box. This is a standing constraint on every ticket below, not a note.

### 9. Serving cutover

- **A new public bucket** (R2 public bucket or a Pages-class static host) — **never
  `raincheck-bronze`** [T18]. This supersedes the bus map's "public hosting"
  out-of-scope for the map page only.
- **Payloads, writers and cadences:**

  | payload | writer | cadence |
  |---|---|---|
  | `live.geojson` + `meta.json` | live-export Deployment | 30 s |
  | insight exports — `cells.geojson`, `headline.json`, `zones.geojson` | `make export` behind the daily build | per build |
  | Great Expectations Data Docs | Airflow task | per run |
  | per-asset flood history | flood spine rebuild | per rebuild |
  | the page (`index.html`, `app.js`, `app.css`), vendored MapLibre | deploy-time | rare |

  **Corrected 2026-08-24 [T9, measured against `src/raincheck/export.py`]:** `cells.geojson`
  is per-BUILD, not deploy-time. `make export` writes it in the same all-three-or-none run
  as `headline.json`, carrying per-window and per-storm-hour PROPERTIES, so publishing it
  on the page's rare cadence would strand the map's colours a build behind its own
  headline numbers. The deploy-time family is the page itself plus the vendored MapLibre.

- **`live.geojson` falls on the derived side of the MTA line and is published**, with
  three constraints that keep it a view rather than a feed: current snapshot only
  with no served history, no bulk or protobuf endpoint, and MTA attribution on the
  page. It carries per-vehicle fields and is feed-shaped [T14], so this is a genuine
  judgement call, not a technicality — it is flagged in Further Notes as the decision
  most worth vetoing. **Verify MTA's actual redistribution terms before go-live**;
  this spec does not assert what they say.
- STALE semantics unchanged [T14].

### 10. Mac decommission gate

- A **T19-style fail-closed checklist per remaining Mac daemon** — `precip-live`,
  `daily`, the export loop. Each retires only on: proven cluster parity by content
  equality, **two independent proofs per day**, **seven clean days** (matching T19),
  and an explicit acknowledgement that the Mac backstop is gone.
- The Mac ends as a **dev checkout, not a runtime**.
- **Includes T16 submit-or-close**: the Interline/Transitland grant, outstanding since
  2026-08-16, is submitted or closed by **2026-09-30**, defaulting to its recorded
  fallback (archive-era Delay columns NULL) [T16].

## Testing Decisions

**What makes a good test here.** Test external behaviour: what a pod is configured to
do, what a digest says about two builds, what a script does to a directory. Do not test
that a YAML key exists for its own sake — test the invariants that would actually hurt
if they broke (a public listener, a partition count, a re-implemented tick). Most of
this effort is infrastructure and operational gates, so the honest position is stated
up front: **the live cutover gates are evidence, not tests, and are not claimed as
test coverage.**

**Seams — three reused, two new.**

*Reused:*

1. **The `make` target / `python -m raincheck.<module>` boundary stays the unit of
   work.** Because no stage is re-implemented for the cluster, every existing module
   test in `tests/` still covers the behaviour after the move. This is the migration's
   real safety net, and it only holds as long as no ticket forks a module for the
   cluster.
2. **`tests/test_cloud_scripts.py`'s pattern** — stub binaries on `PATH`, run the
   script in a subprocess with `cwd=/` to prove cwd-independence — is the seam for any
   new shell gate (cutover checklists, parity runners). Stub `kubectl` the way that
   file stubs `aws`, and copy real tool output verbatim into the stub.
3. **`tests/test_precip_live.py::test_live_catchup_lands_missing_hours_once`** already
   pins the ~25 h catch-up contract. The CronJob calls the same module, so the contract
   needs no new test — only an assertion (below) that the pod really does call the
   module.

*New:*

4. **`raincheck.parity`** — one module, one seam, three consumers (the cluster parity
   gate, the Airflow migration gate, the ticket 4 and 10 cutover gates). Interface:
   a digest over a partitioned table that returns, per partition, the row count and a
   sha over its sorted rows; plus a comparison that names which partitions differ and
   how. Tests:
   - the same data written by two different Spark sessions digests **equal** (the
     parquet footer-permutation case that byte comparison fails) [F01, T02];
   - a single changed value changes the digest;
   - row order and column order do not change the digest;
   - a partition present on one side and absent on the other is reported loudly rather
     than skipped;
   - an empty partition is distinguishable from a missing one.
5. **`tests/test_cluster_manifests.py`** — render the cluster manifests
   (`helm template` / `kustomize build`) and assert on the rendered YAML. One seam
   covering tickets 1, 2, 3, 5, 6 and 7. Skip cleanly when the renderer binary is
   absent, the way the shell tests guard on their tools. Assertions:
   - no Service of type `LoadBalancer` or `NodePort`, and no security group rule
     granting inbound from `0.0.0.0/0`, except the named exceptions;
   - Kafka `retention.ms` equals 48 h and topic partitions equal 6;
   - Strimzi's Topic Operator is disabled;
   - the precip CronJob's command **is** `python -m raincheck.precip_live`, with
     `concurrencyPolicy: Forbid` — this is the assertion that keeps the catch-up
     contract from being reimplemented in a shell one-liner;
   - every ServiceAccount maps to exactly one R2 token Secret, and no Secret value
     appears in a container image or a plain env literal;
   - every container image is the one ECR repository, pinned by tag, with no `:latest`;
   - the sum of container resource requests for the floor workloads fits the declared
     floor capacity;
   - the floor NodePool declares a single availability zone;
   - block-volume claims are only attached to single-writer workloads.

**Prior art to follow:** `tests/test_cloud_scripts.py` (stub binaries, subprocess,
cwd-independence), `tests/test_daily.py` (stub the make targets and the Spark build,
run the driver for real, let `prune` run against seeded dirs — JVM-free), and the
fixture discipline of copying real tool output verbatim rather than inventing a
plausible shape.

**Not covered by tests, by design:** node provisioning, spot interruption behaviour,
the AWS budget alarm firing, and every cutover gate. Those are proven by the gates
themselves — two independent proofs per day, seven clean days — and this spec does not
dress them up as tests.

## Out of Scope

- **MSK, Glue, Lambda, Fargate-for-capture, MWAA** — rejections recorded above and in
  [T19]; not to be re-litigated inside this effort.
- **The Airflow DAG design** — task structure, dynamic mapping, trigger rules, the
  Great Expectations suites: `.scratch/orchestration/map.md`. This spec delivers only
  the platform underneath.
- **Alerting and notification channels, and the subscribe path's shape** —
  `.scratch/notify/map.md`. This spec reserves the ingress exception and decides
  nothing about it.
- **The flood model chain** (F05, F10, F11, F12 and the rest of `.scratch/flood-build/`).
  Those builds run as cluster jobs once the capacity exists; their content is not this
  effort's.
- **The 2026-08-31 cutover task and its gate** — untouched, by rule.
- **Multi-region, service mesh, GitOps operators** beyond what the tickets name; no
  ArgoCD until something needs it.
- **Re-serving raw MTA feed bytes or a bulk protobuf endpoint** — standing rule; the
  one derived-file boundary case is decided in section 9.
- **Changing what any pipeline stage computes.** This is a runtime move. Any stage
  whose output changes has a bug, not a feature.

## Further Notes

**Two corrections this spec makes to the map, both worth reading before implementing:**

1. **NAT Gateway would have broken the envelope.** The map's "no inbound from the
   internet" is right, but the default way to achieve it — private subnets behind a
   NAT Gateway — costs roughly the entire non-control-plane budget on its own. This
   spec puts nodes in public subnets with no inbound security-group rules instead, and
   makes the manifest test assert the property directly, because subnet placement is no
   longer what provides it.
2. **The map conflated IRSA with the R2 credential split.** IRSA cannot scope
   Cloudflare R2. The capture-write / build-read/write / serve-read split is three R2
   API tokens as Kubernetes Secrets; IRSA covers only ECR, EBS CSI and
   CloudWatch/budgets.

**Two decisions this spec closed that the map left open**, both with overturn triggers
written into the relevant section: one Kafka broker rather than three (with six
partitions fixed at creation so growing later stays non-destructive), and no
spark-operator, with per-day work as one pod per day and only genuinely wide work in
cluster mode.

**One decision most worth Ross's veto:** publishing `live.geojson`. It carries
per-vehicle fields — vehicle, trip, route, stop, bearing, occupancy, timestamps — and a
consumer polling it every 30 s could reconstruct a position stream. This spec publishes
it, constrained to a current-snapshot view with no history, no bulk endpoint and MTA
attribution, because it is the live panel's entire content and the standing rule is
about re-serving raw feeds. If the call goes the other way, the fallback is a
Cell-aggregated live layer and the per-vehicle panel does not ship — that is a
materially different page, which is why it is flagged here rather than buried.

**A precondition to check first, before any node exists:** that the capture box can
share a VPC with the cluster. The private box-to-broker path is assumed throughout
section 2 and section 7; if it does not hold, ticket 4's default (capture stays on the
box) needs re-deciding rather than working around.

**The constraint that keeps the escape hatch real** is worth repeating because it binds
every ticket: no stage may depend on a cluster-only feature. Every stage stays runnable
as `make <target>` inside the same image on a single box. The moment that stops being
true, the documented downscale path becomes a paragraph rather than a plan, and the
$130/month decision becomes irreversible in practice. *[T8] this is now enforced
rather than repeated: `tests/test_cloud_cost.py` asserts that no `make` recipe shells
out to cluster-only tooling and that no stage module reaches for a Kubernetes client,
and `scripts/downscale.sh plan|up|run|down` is the path itself.*
