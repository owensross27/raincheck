# T1 — EKS cluster + Karpenter + Graviton spot + budget alarm

Status: resolved
Type: task
Owns: spec §1 (cluster shape, capacity, envelope) and §8 (cost guardrails, executed here).

## Done — the budget alarm, before any node exists

Wired 2026-08-23, verified with `aws budgets describe-notifications-for-budget`:

| Budget | Filter | Limit | Notifications (email owensross27@gmail.com) |
|---|---|---|---|
| `raincheck-cloud` | tag `user:Project$raincheck-cloud` | $130/mo | FORECASTED 100%, ACTUAL 80% / 100% / 130% |
| `aws-account-total` | none (whole account) | $210/mo | FORECASTED 100%, ACTUAL 100% |

The 130% notification is spec §8's `$130 hard-look line`. The second budget exists
because a tag filter only sees resources that carry the tag: anything created
untagged escapes the $100 alarm silently, which is the exact failure the alarm is
supposed to prevent. $210 = ~$75 measured non-raincheck baseline + the $130 envelope.

A region filter (the house pattern used by the two `rf-coverage` budgets) was
rejected: us-east-1 already carries ~$54/mo of unrelated spend (Lightsail,
`vinylpig-staging`, VPC, Secrets Manager, CloudFront), so a $100 region budget would
be at 54% before the cluster existed.

Consequence to honour in every later ticket: **every resource this effort creates
must carry `Project=raincheck-cloud`** — cluster, nodegroup, Karpenter EC2NodeClass,
EBS StorageClass, ECR repo. Cost-allocation-tag activation lands with the first
tagged resource and takes up to 24 h to appear in Budgets.

## Preconditions — checked, both pass

- **Capture box** `i-098a6ea89c4b15502` (`44.218.135.197`, the instance still tagged
  `vinylpig-dev`) is t3.small in **us-east-1**, VPC `vpc-049a68bf6017d6ead` (default,
  172.31.0.0/16), subnet `subnet-002ac7537c7b84cdb`, AZ **us-east-1f**, SG
  `sg-0cb33dca0ac107599`. Spec §1 requires the cluster in the box's region and VPC:
  satisfiable. The box-to-broker path is same-VPC *and* same-AZ, so it is free as
  well as private.
- **Graviton spot is available and cheapest in us-east-1f** — the box's own AZ, so
  the floor NodePool's AZ pin (spec §1, EBS is AZ-bound) costs nothing to honour.
  Measured 2026-08-23, us-east-1f Linux spot: t4g.small $0.0109, t4g.medium $0.0179,
  t4g.large $0.0234, t4g.xlarge $0.0507, m7g.medium $0.0168, m7g.large $0.0424,
  c7g.large $0.0238.
- All six VPC subnets are public with `MapPublicIpOnLaunch=true`, which is what
  spec §7's no-NAT design assumes. **us-east-1e is excluded** from the cluster subnet
  set (EKS does not support it); control plane subnets are 1f + 1a + 1c, floor
  nodes pinned to 1f.

## Capacity: the requests table (spec §1 deliverable)

First-cut requests. Every number marked *measure* is a placeholder to be replaced by
the re-measurement the spec demands — the Mac's `local[6]` + 3 g is Mac-shaped and is
not copied.

| Workload | Ticket | CPU req | Mem req | Notes |
|---|---|---|---|---|
| Kafka broker (Strimzi KRaft, combined) | T2 | 500m | 1.5Gi | 1Gi heap + off-heap; ~0.5 GB/day is one-broker traffic |
| Spark streaming driver | T3 | 1000m | 2Gi | **measured** 2026-08-24 (T3): pod RSS = driver heap + ~0.93 GiB, so this row holds only with `RAINCHECK_SPARK_DRIVER_MEM=1g`, not the Mac's 3 g |
| Airflow scheduler | T6 | 500m | 1Gi | |
| Airflow webserver (1 replica) | T6 | 300m | 1Gi | no triggerer (spec §1) |
| Airflow metadata Postgres | T6 | 250m | 512Mi | |
| live-export + detector Deployment | T5 | 200m | 512Mi | two halves, one pod |
| precip-live CronJob (300 s tick) | T5 | 500m | 1Gi | burst, not steady |
| kube-system + Karpenter + EBS CSI | T1 | 600m | 1Gi | coredns x2, aws-node, kube-proxy |
| **Floor total** | | **3.85 vCPU** | **~8.5Gi** | excludes per-day build pods (Karpenter burst) |

The Spark driver row is no longer a placeholder — T3 measured it on the cluster
(2026-08-24). Two facts that row does not fit: pod RSS tracks the **driver heap plus about
0.93 GiB**, so `RAINCHECK_SPARK_DRIVER_MEM` is what sizes it; and an events-shaped batch ran
in the same wall time on a 1 g heap as on 2 g, so the heap was never the throughput knob.
Per-day build pods on burst take 1500m / 3Gi (2 g heap). Also measured, and relevant to
anything that plans to burst onto one: **the `burst` NodePool cannot provision t4g** — its
`instance-generation Gt 5` requirement excludes the whole family.

2 x t4g.large (2 vCPU / 8 GiB each) gives 4 vCPU and ~14.2Gi allocatable — fits with
headroom for one re-measured driver overshoot. 2 x t4g.medium (~5.8Gi allocatable)
does **not** fit and is not a fallback.

## The envelope does not close at $100 — decision needed

Measured monthly arithmetic for the working shape (2 x t4g.large spot floor):

| Line | $/mo |
|---|---|
| EKS control plane ($0.10/hr, fixed) | 73.00 |
| Floor: 2 x t4g.large spot @ $0.0234 | 34.16 |
| **Public IPv4: 2 x $0.005/hr** | **7.30** |
| gp3 EBS ~50 GiB @ $0.08 | 4.00 |
| Karpenter spot burst (builds) | ~1.50 |
| R2 (41.65 GB, 10 GB free) | 0.47 |
| ECR + node egress | ~1.10 |
| **Total** | **~121.5** |

Two corrections to spec §1's `~$27 remains` arithmetic:

1. **$27 never bought two Graviton spot nodes.** $27/mo for two nodes is $0.0092
   per node-hour; the cheapest Graviton in the region, t4g.small spot, is $0.0109
   and has 2 GiB of RAM. The floor the requests table actually needs costs $34.
2. **Public IPv4 addresses are billed** ($0.005/hr each since 2024-02). Spec §7
   correctly rejects the $32/mo NAT Gateway, but the alternative it chose is not
   free: $3.65/node/mo. It still wins — break-even is ~9 nodes — but it must be
   counted, and it grows with Karpenter burst.

Neither correction is recoverable by resizing: the control plane alone is 73% of the
envelope. The choices are (a) raise the envelope to the $130 hard-look line the spec
already names, (b) take the spec §8 downscale path (two plain EC2, ~$25-60/mo, no
per-day parallelism), or (c) run the floor on one t4g.large and defer Airflow — which
buys $21 and costs the T6 platform.

### Ross's decision, 2026-08-23: raise to $130, build as specced

Envelope raised to the $130 hard-look line spec §8 already names; both budgets were
raised with it ($100 -> $130, $180 -> $210) so the alarms stay meaningful instead of
sitting permanently red. Spec §1's `~$27 remains` and spec §7's implicit "public IPs
are free" should be corrected to match.

## Built

- `.scratch/cloud/cluster.yaml` — the eksctl config, checked in as the record of what
  was created. EKS 1.34, existing default VPC, subnets 1f/1a/1c (1e excluded),
  control-plane logging off ($0.50/GB ingest is not worth the envelope).
- Floor: managed nodegroup `floor`, 2 x t4g.large **spot**, AL2023 arm64, pinned to
  us-east-1f, min 2 / max 3 — the max is spec §1's "third spot node decided against
  the budget alarm", available without an edit.
- Karpenter 1.14.1 with `withSpotInterruptionQueue: true`, so a spot reclaim is a
  drained node rather than a surprise.
- `deploy/k8s/karpenter-nodepool.yaml` — the `burst` NodePool: Graviton spot only,
  any AZ (burst pods are stateless), consolidate after 1 m so a finished build stops
  costing money, `limits.cpu: 32` as the hard ceiling that stops a runaway fan-out
  outrunning the budget alarm's reporting lag.


## Verified on the cluster (2026-08-23)

Cluster `raincheck`, EKS 1.34, us-east-1, `vpc-049a68bf6017d6ead`.

| Claim | Evidence |
|---|---|
| Floor is Graviton spot, AZ-pinned | 2 nodes, `CAPACITYTYPE=SPOT`, `arch=arm64`, `zone=us-east-1f` |
| No inbound from the internet (spec §7) | node SG `sg-04b76aed2bb2fb61f` has **zero CIDR sources** — only itself and the control-plane SG. Enforced by the SG, not by subnet placement, exactly as §7 requires |
| Karpenter is live | 1.14.1, 2 replicas Running; `burst` NodePool + EC2NodeClass both Ready (subnets, SGs, AMIs resolved) |
| Burst actually bursts | a Job requesting 3 vCPU cannot fit a 2-vCPU floor node -> Karpenter provisioned `c6g.xlarge` **spot** in **us-east-1c**, pod ran (`burst node OK: aarch64`) |
| Burst costs nothing when idle | node gone at 01:15:31Z after the Job finished; `kubectl get nodes` back to the 2 floor nodes, `nodeclaims` empty |
| Spend is attributable | both floor instances and the EKS cluster carry `Project=raincheck-cloud`; `Project` activated as a cost allocation tag (Budgets backfill takes up to 24 h) |
| Cluster is clean | 16 pods Running, 0 Pending |

Burst deliberately picked a different AZ from the floor. That asymmetry is the design:
the floor is pinned because EBS is AZ-bound, burst is free to take the cheapest
capacity anywhere because build pods are stateless.

One transient seen and waited out, recorded so it is not re-diagnosed later: after the
burst node was consolidated away, four DaemonSet pods (`aws-node`, `ebs-csi-node`,
`kube-proxy`, `eks-pod-identity-agent`) sat `Pending` bound to the deleted node for
~2 min before pod-GC cleared them. Node object and NodeClaim were already gone. This
is GC lag, not a scheduling failure, and it will recur on every burst scale-down.

## Handoff to the next tickets

- **T2 (Kafka)**: broker goes on the floor NodePool, `nodeSelector: raincheck.io/pool=floor`,
  gp3 in us-east-1f. The archiver's path is same-VPC *and* same-AZ, so it is free.
- **Everything with a build pod**: `nodeSelector: raincheck.io/pool=burst` is what buys
  parallelism. Without it a pod lands on the floor and competes with Kafka and the
  streaming driver.
- **Every ticket**: tag new AWS resources `Project=raincheck-cloud` or they fall outside
  the $130 alarm. The `aws-account-total` budget is the backstop that catches the miss.
- **Still open from spec §1**: the requests table above is first-cut. The Spark driver
  row is the one that must be re-measured on t4g.large before T3 sizes anything.

## Comments
