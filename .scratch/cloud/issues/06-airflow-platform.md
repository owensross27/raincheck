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

## From cloud 03's landing (2026-08-24, `c4be751`) — consume, do not rebuild

- The image exists and has been run on the cluster:
  `384555717200.dkr.ecr.us-east-1.amazonaws.com/raincheck:<12-char git sha>`,
  arm64, tags IMMUTABLE, built by `scripts/cloud-image.sh`. **Every manifest
  writes the bare string `image: raincheck`**; `deploy/k8s/kustomization.yaml`'s
  `images:` transformer is the one place a repo/tag appears, and the manifest test
  fails a direct reference, a `:latest` tag or a non-sha tag.
- A pod's entry point is `make -C /opt/raincheck <target>` or
  `python -m raincheck.<module>` — the repo is installed EDITABLE at
  /opt/raincheck so `paths.REPO` resolves and the Makefile works unchanged.
- Placement already exists in `deploy/k8s/raincheck/build.yaml`: PodTemplates
  `raincheck-stage` (no Spark, 4Gi staging emptyDir, burst) and `raincheck-spark`
  (Spark in-pod, burst, 1500m/3Gi, `RAINCHECK_SPARK_MASTER=local[2]`,
  `RAINCHECK_SPARK_DRIVER_MEM=2g`), plus the Role that lets a cluster-mode driver
  create executors. The streaming Deployment is `deploy/k8s/raincheck/streaming.yaml`.
- `spark.session()` is steered by environment only — `RAINCHECK_SPARK_MASTER`,
  `RAINCHECK_SPARK_DRIVER_MEM`, and s3a configured automatically when
  `AWS_ENDPOINT_URL` is set. Never fork it.
- **Measured, do not re-derive**: pod RSS = driver heap + ~0.93 GiB; an
  events-shaped batch ran in the same wall time on a 1 g heap as on 2 g. And the
  `burst` NodePool **cannot provision t4g** — `instance-generation Gt 5` excludes
  the whole family, so burst capacity is m6g/c7g-class.
- New manifest-test rows that apply to anything you add: no installer
  (`pip install`, `apt`, `curl`, `spark.jars.packages`) in a container's command or
  args; every workload declares `raincheck.io/pool`; a PersistentVolumeClaim may
  only be mounted by a single-writer Deployment (replicas 1 + strategy Recreate).
- **BLOCKER: `paths.data_root()` returns a `Path`, which cannot hold an `s3a://`
  root** (`Path("s3a://b/x")` -> `s3a:/b/x`), and the obvious `Path`-subclass fix
  makes `.exists()`/`.glob()` silently answer about the local disk. So no pod reads
  or writes R2 TABLES yet — `live/` cannot move there and `prune` stays pinned.
  Write manifests for the R2 world, expect the staging volume today, and do not
  invent a second path abstraction inside a stage module.
