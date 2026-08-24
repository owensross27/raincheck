# T6 — Airflow platform prerequisites

Status: open
Type: task
Blocked by: 01, 07
Owns: spec §6. **Platform only** — DAG structure, mapping, trigger rules and the Great
Expectations suites belong to `.scratch/orchestration/map.md`.

## Work

- Official Airflow Helm chart, **KubernetesExecutor**.
- **Metadata DB: in-cluster Postgres** (StatefulSet on a gp3 volume, floor NodePool,
  us-east-1f). A managed instance does not fit what the control plane leaves of the
  envelope. The volume is what makes run history survive a pod restart.
- **No triggerer** (nothing here uses deferrable operators) and **one webserver replica** —
  both footprint reductions are already counted in `01-eks-cluster.md`'s requests table.
- **Task logs to R2** (remote logging), so retention is a bucket lifecycle rule rather
  than a slow-motion disk-full incident on pod disk.
- IRSA for the pods that touch AWS; R2 credentials as cluster secrets (ticket 07).

## Acceptance

- Airflow's full footprint is counted against the floor before it is installed — adding
  the DAG platform must not evict the pipeline. If the measured total no longer fits two
  t4g.large, the resolution is the third spot node (`maxSize: 3` is already in place)
  decided against the budget alarm, **never a silent overrun**.
- Run history survives deleting the scheduler pod.

## Tests

Extends `tests/test_cluster_manifests.py`: the sum of container resource requests for the
floor workloads fits the declared floor capacity.
