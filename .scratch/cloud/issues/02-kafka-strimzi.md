# T2 — Kafka on the cluster (Strimzi, KRaft)

Status: open
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
