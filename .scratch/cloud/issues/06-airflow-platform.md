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

## Inherited from the wave-1 landing (2026-08-24, recorded by the gate)

- **The floor is no longer empty**: cloud 02 put the Kafka broker (500m/1536Mi
  request) and the Strimzi operator (100m/256Mi) on it, ns `kafka`. Count them in
  the footprint arithmetic — `kubectl top nodes` gives the real remainder.
- **Manifest-test seam**: ONE unioned tests/test_cluster_manifests.py (23 tests,
  kustomize `rendered()` loader). Extend it, and list every manifest in
  deploy/k8s/kustomization.yaml `resources:` or no test sees it.
- **COST RULE (gate sweep)**: pin every chart image by tag/digest (no :latest —
  standing trap) and keep pull policy at IfNotPresent; nothing pip/apt-installs at
  container start — scheduler/webserver/worker pods restart routinely and a
  per-start install bills on every one. Airflow task pods run the shared sha-tagged
  image from cloud 03, which carries the repo already.
