# Wayfinder map: cloud runtime (de-Mac, distributed on EKS)

Label: `wayfinder:map`

## Destination

raincheck runs with the Mac closed, on the fastest and most distributed
runtime ~$100/month buys: an EKS cluster carrying Kafka (Strimzi, KRaft),
Spark 3.5.3 + Sedona structured streaming, Airflow, the flood-detector tick,
and the live-export loop as supervised pods — with Karpenter bursting cheap
Graviton spot capacity so daily and backfill Spark builds fan out per-day
executors in parallel. Bronze/Silver/Gold live in R2; the map is served from
a static host; the proven t3.small capture box stays until its own
fail-closed gates pass. Freshness is bounded by what the sources publish —
the bus chain is ~1-2 min end to end (30 s poll, 30 s trigger, 30 s export);
live precip advances at hourly `:00` RadarOnly stamps caught by a 300 s
tick, fresh to 90 min under the flood budget [T11, flood spec] — and by
nothing we run. The map is done when nothing is left to decide before
`/to-spec` collapses it and `/to-tickets` slices the build.

## Notes

- **The decision (2026-08-23, Ross, recorded verbatim in spirit):** plan for
  the fastest and most distributed way to run this; quakestream is not
  happening, so raincheck is the cluster showcase; ~$100/month is accepted,
  "especially if this is something that isn't really built out." This
  supersedes the orchestrator's same-day EC2-two-instance lean, which is
  kept below as the considered alternative because its physics still shape
  the design.
- **What distribution buys and doesn't (kept honest):** sources publish at
  their own cadence — MTA ~every 30 s (and 30 s polling misses ~10-15% of
  snapshots, so the poll interval itself is a knob, ticket 5); MRMS live
  precip is an hourly product whose `:00` stamps the tick catches within
  ~25 h retention. No cluster makes the feeds faster. What the cluster
  buys: per-day parallel Spark builds, elastic burst with no idle cost
  (Karpenter + spot), no single-box RAM ceiling on streaming + Kafka +
  Airflow coexisting, restartable supervised everything, and the ops story
  itself.
- **The ~$100 envelope, arithmetic on the table:** EKS control plane
  ~$73/mo is the fixed cost of choosing EKS. That leaves ~$25-30:
  2-3 Graviton spot nodes (t4g/m7g class, ~$5-12/mo each on spot) as the
  always-on floor (Kafka, streaming driver+executors, Airflow, exports/
  detector pods), Karpenter spot burst for builds (~$1-2/mo), EBS gp3 for
  Kafka + checkpoints (~$3-5/mo), R2 <$1 (41.65 GB measured [T18, T20]).
  Total ~$95-110. Consequences accepted to fit: **MSK is out** (its
  ~$65/mo 2-broker floor cannot coexist with the control plane inside
  $100 — Strimzi on the cluster instead, the stronger showcase anyway);
  node capacity is spot-first (a killed executor re-runs; dynamic
  partition overwrite makes builds idempotent [T15, research/07]).
- **Build-runtime facts for sizing (qualifiers matter):** `events` measured
  ~275 s/day steady state — the oft-quoted 1928 s (~32 min) was a 7-day
  catch-up in one session — at the Mac's committed `local[6]` + 3 g driver
  config [T15, spark.py]. That config is Mac-shaped; on K8s the
  driver/executor topology and memory are ticket 3 decisions, and
  per-task memory x fan-out width is a capacity input to ticket 1.
- Recorded base, already shipped (do not re-decide): vinylpig-dev
  (t3.small, shared) captures all six feed kinds 24/7 with hourly
  push-then-prune to R2 [T19]; the 2026-08-31 fail-closed cutover retires
  the Mac archiver on seven proven-clean days, two proofs per day — this
  map never touches that gate [T19]. R2 bucket `raincheck-bronze` is
  Bronze's durable home, zero egress [T18]. Lambda/ECS remain rejected for
  the capture shape [T19]; Glue never fit anything here; MWAA stays out
  (self-hosted Airflow on the cluster is the point).
- The slim Sedona Docker image already exists as in-house knowledge
  (`~/quakestream/stack/docker/sedona.Dockerfile`, geotools-wrapper
  1.9.1-33.5) [pipeline map] — the container path is pre-proven even
  though quakestream itself is shelved.
- Considered alternative (recorded, not chosen): two plain EC2 instances
  (always-on t4g.large-class + a scheduled build instance) at ~$25-60/mo.
  Cheaper, simpler, same freshness; loses per-day parallelism, elastic
  burst, and the cluster showcase. Reopen only via ticket 8's kill
  criteria.
- Standing safety rules inherited: fail-closed gates before any capture or
  Mac daemon moves; two independent proofs of parity; explicit-path
  commits; no public re-serving of raw MTA feeds.

## Tickets to cut (decisions this map must close)

1. **Cluster shape and capacity.** EKS managed nodegroup + Karpenter vs
   EKS Auto Mode (run the per-pod-pricing arithmetic on the day);
   Graviton spot default with one small on-demand fallback node; capacity
   accounting must include Kafka JVM, streaming driver+executors, Airflow
   scheduler/webserver/metadata-DB/task-log retention, exports/detector
   pods (this ticket owns the number — the orchestration map defers to
   it); the $100/mo budget alarm wired before the first node.
2. **Kafka on the cluster.** Strimzi, KRaft; broker count (1 vs 3 —
   ~0.5 GB/day is one-broker territory, 3 is the showcase; choose with
   eyes open); EBS gp3 class/size; 48 h delete retention preserved [T10];
   topic parity with `make topics` spec; MSK recorded as rejected on
   budget.
3. **Spark on Kubernetes + stage placement.** spark-operator vs
   spark-submit k8s; the Sedona image in ECR (reuse the quakestream
   Dockerfile); streaming as a long-running driver pod with checkpointed
   recovery [T12]; daily `events` as mapped per-day jobs on spot burst
   with `gold` as a single reduce over the touched months (the rollup is
   not per-day [daily.py]); **an explicit stage-placement table for
   T15's eight stages** — `prune` operates on `data/live/` and is pinned
   to wherever that PVC lives; `gapfill` stages ~1.24 GB/day locally
   before push-then-prune and needs pod disk sized for it [T20]; parity
   gate vs `make daily` by content equality (counts + sorted-row sha),
   not bytes. **T17 arm:** the 7-year backfill's dead SSD precondition is
   replaced by R2 headroom + a one-off cluster run sized separately
   (2,278 files, not the nightly shape), with a named trigger.
4. **Capture placement.** The box runs untouched through the 2026-08-31
   gate. After it, capture-as-Deployment vs staying on the box is decided
   by a T19-style gate of its own (two independent proofs, N clean days —
   note the Mac backstop is gone by then, so the bar is higher) plus
   blast-radius (a cluster upgrade must never take capture down; a $7/mo
   box that only captures is a legitimate answer).
5. **The live path as pods, and its latency knobs.** precip-live as a
   300 s CronJob (eccodes image) whose migration acceptance criterion is
   the catch-up contract: **every missing `:00` stamp within MRMS's
   ~25 h retention** — a latest-only reimplementation silently re-blocks
   the flood replay gate [T11, F12]. The 2-min/15-min MRMS products are
   rejected detector inputs by contract and may never enter
   `live/precip_cell`'s `:00` series — if ever used, a distinct
   feature/table [F11, pipeline map]. live-export + detector tick as one
   supervised Deployment beside the streaming driver; push-based export
   to the static host; knobs adopted only with a measured win: streaming
   trigger (30 s today, 10 s is config), archiver poll interval (30 s
   misses ~10-15% of snapshots [vault feeds ref]; tightening costs
   Bronze volume — a real decision, not a freebie).
6. **Airflow platform prerequisites.** Helm release, KubernetesExecutor,
   IRSA for its pods, node headroom — the DAG design belongs to
   `.scratch/orchestration/map.md`; this ticket only guarantees the
   platform underneath it.
7. **Secrets, IAM, network.** IRSA per workload (capture-write,
   build-read/write, serve-read split); R2 credentials as cluster
   secrets with rotation noted; ECR for images; **no inbound from the
   internet** except (a) the static host and (b) whatever minimal
   subscribe ingress `.scratch/notify/map.md` ticket 4 decides —
   in-VPC broker path from the capture box to the cluster's Kafka is
   private networking, not an internet port.
8. **Cost guardrails and kill criteria.** Budget alarm at $100, hard look
   at $130; monthly bill review; the documented downscale path to the
   two-EC2 alternative (reversibility is design, not admission).
9. **Serving cutover.** Static host for the map + exports (R2 public
   bucket / Pages-class host) — supersedes the bus map's "public hosting"
   out-of-scope for the map page only. **Enumerate the payloads and
   cadences:** live tick (30 s), insight exports (batch), GX Data Docs
   (per run), per-asset flood history (per spine rebuild). **Decide
   which side of the "MTA-derived feeds" line `live.geojson` falls on**
   (per-vehicle positions, feed-shaped [T14; pipeline map l.135]) — and
   the public host is a NEW bucket, never `raincheck-bronze` [T18].
   STALE semantics unchanged [T14].
10. **Mac decommission gate.** T19-style fail-closed checklist per
    remaining Mac daemon (precip-live, daily, exports): each retires only
    on proven cluster parity, two independent proofs, N clean days; the
    Mac ends as a dev checkout, not a runtime. **Includes: submit-or-close
    build T16** (Interline/Transitland grant, outstanding since
    2026-08-16) by a named date, defaulting to its recorded fallback
    (archive-era Delay columns NULL) [T16].

## Review round 1 (2026-08-23, adversarial panel — corrections applied)

1. BLOCKER precip freshness: "~2-5 min MRMS" corrected to hourly `:00`
   RadarOnly on a 300 s catch-up tick, fresh <= 90 min [T11, flood spec];
   the 2-min stamps are rejected detector inputs by contract, not an
   option to evaluate (ticket 5 rewritten; notify map corrected too).
2. Stage placement: T15's eight stages now have a placement table
   requirement; `prune` pinned to `data/live/`'s home; gapfill pod disk
   sized (ticket 3).
3. Build numbers qualified: ~275 s/day steady state vs 1928 s 7-day
   catch-up, at `local[6]` + 3 g — config named as Mac-shaped (Notes,
   ticket 3).
4. Capture-relocation gets its own T19-style gate with the no-backstop
   caveat (ticket 4).
5. Network rule amended: internet-ingress exceptions named (static host +
   notify's subscribe ingress); box-to-cluster Kafka is in-VPC (ticket 7).
6. precip-live migration carries the ~25 h catch-up contract as an
   acceptance criterion — F12 depends on it (ticket 5).
7. Poll-interval knob added with the 10-15% missed-snapshot measurement
   (Notes, ticket 5).
8. T17 (7-year backfill) given an explicit arm — dead SSD precondition
   replaced, one-off run sized separately, named trigger (ticket 3).
9. T16 submit-or-close added to the decommission checklist (ticket 10).
10. Serving payloads enumerated; `live.geojson`'s MTA-derived status made
    an explicit decision; public host separated from `raincheck-bronze`
    (ticket 9).
11. Cluster capacity accounting now includes Airflow's full footprint;
    ownership of the sizing number pinned here, not split across maps
    (ticket 1).
12. The pre-pivot ">100x cost" multiplier is gone with the EC2 framing;
    absolute numbers kept (Notes).

## Out of scope

- MSK, Glue, Lambda, Fargate-for-capture (rejections recorded above and
  in [T19]); MWAA; multi-region; service mesh; GitOps operators beyond
  what the tickets name (no ArgoCD until something needs it).
- Re-serving raw MTA feeds publicly (standing rule; ticket 9 decides the
  one derived-file boundary case).
- Touching the 2026-08-31 cutover task or its gate.
- Alerting/notification channels — `.scratch/notify/map.md` owns those.

## Build progress

- **T1 resolved 2026-08-23** — EKS `raincheck` (1.34, us-east-1, the capture box's own
  VPC and AZ) with a 2 x t4g.large spot floor pinned to us-east-1f, Karpenter 1.14.1
  with a scale-to-zero Graviton-spot `burst` NodePool, and the budget alarm wired
  before the first node. Burst provisioning and consolidation both verified on the
  cluster. The $100 envelope did not survive measurement — control plane $73, public
  IPv4 $3.65/node/mo, floor $34 — so Ross raised it to the $130 hard-look line spec §8
  already named. Details and the corrected arithmetic: `issues/01-eks-cluster.md`.
- **Tickets published 2026-08-23** — `issues/01`-`issues/11`. Numbering follows the
  spec's Implementation Decisions (ticket NN = spec §NN) except `11-raincheck-parity`,
  cut separately because tickets 03, 04 and 10 all block on that one module and burying
  it inside 03 would have hidden the dependency. Ticket 08's budget-alarm half was
  executed inside 01; 08 keeps the monthly review and the downscale path.
  Frontier after 01: **02, 07, 08, 11** are unblocked (11 first — it needs no cluster).
