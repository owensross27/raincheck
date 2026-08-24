# T2 — Kafka on the cluster (Strimzi, KRaft)

Status: resolved
Type: task
Blocked by: 01
Owns: spec §2.

## Work

- Strimzi operator, **KRaft mode**, one combined-role broker on the floor NodePool
  (`nodeSelector: raincheck.io/pool=floor`), gp3 in **us-east-1f** — the floor's AZ
  pin exists because this volume cannot follow a broker into another AZ.
- **RF=1, `min.insync.replicas=1`.** ~0.5 GB/day is one-broker territory and Bronze is
  the record, so a broker loss is a latency event, not data loss. Growing to 3 brokers
  is a Strimzi replica change plus partition reassignment once the floor is three
  nodes — not a redesign.
- **Six partitions per topic, fixed at creation.** This is the one irreversible knob:
  changing it means dropping the topic and every retained message. Six matches what
  the archiver was built against [T10, `topics.py`].
- **48 h delete retention, zstd, no compaction**, carried over exactly [T10].
- **Disable Strimzi's Topic Operator.** `python -m raincheck.topics` stays the single
  owner of the topic spec, run as a Kubernetes Job. Two declarative sources for the
  same six partitions is how an irreversible knob gets flipped by accident.
- **Private in-VPC listener only.** No external listener, no public bootstrap. The
  archiver on the capture box reaches the broker through a security-group-scoped path;
  the box is in the same VPC *and* the same AZ as the floor, so this traffic is free.
  Add an SG rule from `sg-0cb33dca0ac107599` (the box) to the broker port — that is the
  only permitted inbound addition to the cluster's SGs.

## Acceptance

- `make topics` (i.e. `python -m raincheck.topics`) run as a Job reports six partitions
  and 48 h retention against the cluster broker.
- The archiver on the box produces to the cluster broker over the private path, with no
  public bootstrap address anywhere in the config.
- MSK stays rejected on budget (~$65/mo two-broker floor). Recorded, not re-litigated.

## Tests

Creates `tests/test_cluster_manifests.py` (spec Testing Decisions seam 5) — later
tickets extend the same file. Assertions this ticket owns: `retention.ms` equals 48 h,
partitions equal 6, Topic Operator disabled, no `LoadBalancer`/`NodePort` Service, no
SG rule granting inbound from `0.0.0.0/0`. Skip cleanly when the renderer binary is
absent, the way the shell tests guard on their tools.

## Delivered (2026-08-24)

Strimzi **1.2.0** (KRaft-only since 1.0 - there is no ZooKeeper mode left to choose),
operator in ns `kafka`, Kafka **4.3.1**, one combined-role node from `KafkaNodePool/broker`
on a 10Gi gp3 volume in us-east-1f. `deploy/k8s/` is now a kustomize seam; deploy with
`scripts/cloud-kafka-install.sh` (idempotent apart from step 4, which recreates the topics
and therefore drops retained messages, exactly as `make topics` always has).

Verified on the broker, not inferred:

    Topic: raincheck.bus.vp  PartitionCount: 6  ReplicationFactor: 1
    Configs: compression.type=zstd,min.insync.replicas=1,cleanup.policy=delete,retention.ms=172800000

and the box is producing across all six partitions of both topics over the private path.

### The private path, and the one thing that was not obvious

Pod IPs under the VPC CNI **are** VPC addresses, so an in-VPC client reaches the broker pod
directly - no external listener, no NodePort, no load balancer, no public bootstrap. The
part that does not follow: the box cannot resolve cluster DNS, and Strimzi advertises an
internal listener as `raincheck-broker-0.raincheck-kafka-brokers.kafka.svc`. Bootstrap would
succeed and every produce would then fail on an unresolvable advertised host.

So there are two internal listeners: `plain` on 9092 (advertised as cluster DNS, in-cluster
clients only) and `box` on 9094, whose `advertisedHost` is the fixed name
`kafka0.raincheck.internal`. The box resolves that name from its own `/etc/hosts`, pointed at
the current pod IP by `scripts/cloud-kafka-endpoint.sh`. Setting `advertisedHost` to the pod
IP instead does not work and cannot be made to work: patching it rolls the broker, which
gives it a new IP.

`RAINCHECK_KAFKA=kafka0.raincheck.internal:9094` on the box is therefore permanent. When the
broker moves (spot reclaim, node roll) only the `/etc/hosts` line changes, and the archiver
is **not** restarted for it - librdkafka re-resolves on reconnect, and a restart is a capture
gap.

- Security group: exactly one rule, `sgr-06a813c9433a3ce6d` - tcp/9094 from
  **`sg-032f4467f24e8d773` (`raincheck-capture-box`, created here)** to
  `sg-04b76aed2bb2fb61f` (the EKS cluster SG, which is what pod ENIs carry). Tagged
  `Project=raincheck-cloud`. 9092 never leaves the cluster.
- **The Work section above is wrong about the source group and stays as written for the
  record.** `sg-0cb33dca0ac107599` ("lewis-signs-dev-sg") is NOT the box's own group: an
  unrelated staging instance (`i-0a924268a565ad38a`) carries it too, and it allows
  0.0.0.0/0 on tcp/443 (measured by cloud 07, same day). A rule sourced from it would have
  handed Kafka to staging. So the box got its own empty security group,
  `sg-032f4467f24e8d773`, attached to `eni-098f5f2acbc73fe7d` ALONGSIDE the dev group
  (`modify-network-interface-attribute` replaces the whole set - list every existing group
  or the box loses them), the rule was re-sourced from it, and the first rule was revoked.
  cloud 07's `deploy/cloud/inbound-allowlist.yaml` needs this group added to
  `allowed_source_security_groups`, and its `pending:` cloud-02 entry removed.
- Strimzi's pod template has **no `nodeSelector` field**: the floor pin is `nodeAffinity`
  on `KafkaNodePool.spec.template.pod`. Plain pods (the topics Job) still use `nodeSelector`.
- The gp3 StorageClass carries `tagSpecification_1: Project=raincheck-cloud` - the CSI driver
  creates the volume, so eksctl's cluster tags never reach it and it would otherwise fall
  outside the $130 budget filter.
- Cost delta: 10Gi gp3 = $0.80/mo. No load balancer, no extra public IP, and box-to-broker is
  same-VPC same-AZ, so it is free. MSK stays rejected on budget (~$65/mo two-broker floor).
