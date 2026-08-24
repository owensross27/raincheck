# T6 — Airflow platform prerequisites

Status: done (2026-08-24, branch `cloud06-airflow-platform`)
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
  **CORRECTED at build: shipped on Airflow 3.2.2, where the webserver was split into an
  API server. "One webserver replica" is `apiServer.replicas: 1`, and Airflow 3 also makes
  the DAG processor a REQUIRED standalone component — a fourth floor pod the requests
  table has no row for. See the close-out below.**
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

## Close-out (2026-08-24)

Built, installed on the live cluster, and verified. Worktree
`/Users/ross/raincheck-wt-cloud06`, branch `cloud06-airflow-platform`.

### What shipped

| File | What |
|---|---|
| `/Users/ross/raincheck/deploy/k8s/airflow/postgres.yaml` | metadata DB: headless Service + StatefulSet, `postgres:17.6-alpine`, gp3-1f (us-east-1f), floor, 8Gi PVC, password by `secretKeyRef` |
| `/Users/ross/raincheck/deploy/airflow/values.yaml` | the Helm values — chart **1.22.0**, Airflow **3.2.2**, KubernetesExecutor |
| `/Users/ross/raincheck/deploy/cloud/floor-capacity.yaml` | measured floor allocatable + the floor workloads no manifest in this repo declares |
| `/Users/ross/raincheck/scripts/airflow-install.sh` | idempotent installer: 4 Secrets (once), the StatefulSet, `helm upgrade --install` |
| `/Users/ross/raincheck/tests/test_cluster_manifests.py` | +9 tests (23 -> 32) |

Install/repair, from the repo root — there is deliberately **no `make` target** (a stage
recipe may not shell out to kubectl/helm; `tests/test_cloud_cost.py` enforces it):

    bash scripts/airflow-install.sh

### The acceptance criteria, measured

- **Run history survives deleting the scheduler pod — PROVEN, not argued.** A DAG run
  (`cloud06-proof-3`) was driven to `success` through the KubernetesExecutor, then
  scheduler pod `airflow-scheduler-7946f54d9c-gvpql` was deleted. After the replacement
  (`-qv95j`) came up, the run count (4) and all seven task-instance states with their
  start/end timestamps were byte-identical, and `airflow-metadata-db-0` showed 0 restarts.
  The history is in the 8Gi gp3 PVC, not in a pod.
- **Every task pod ran on burst, none on the floor.** The six task pods of the proof run
  landed on `ip-172-31-35-238` and `ip-172-31-73-163`, both labelled
  `raincheck.io/pool=burst`; Karpenter provisioned them and consolidated them away
  afterwards (the floor was back to two nodes minutes later).
- **The footprint fits two t4g.large — measured after install, not projected.**
  node `-77-125` 1510m (78%) / 2852Mi (40%), node `-78-113` 1240m (64%) / 3352Mi (47%).
  Free: **1110m CPU and 7934Mi across the two nodes**, and this reconciles exactly with
  `deploy/cloud/floor-capacity.yaml`. No third node was bought.
- `scripts/inbound-audit.py` still green (rc 0, three SGs, zero CIDR sources). No Service
  of type LoadBalancer/NodePort and no Ingress was added; the UI is `kubectl port-forward`.

### What a later ticket must know

- **The floor's largest single free CPU block is 690m** (node `-78-113`; node `-77-125`
  has 420m). Totals mislead here: a pod is scheduled whole. T1's placeholder
  **Spark streaming driver at 1000m does not fit anywhere on the floor today** — cloud 03
  must land under ~690m or the third spot node becomes the decision, at **~$20.73/mo**
  ($17.08 t4g.large spot + $3.65 public IPv4), which does not fit the $130 envelope and is
  therefore Ross's call. cloud 05's live-export (200m/512Mi) does fit.
- **Before buying that node, right-size instead.** Idle actuals against requests:
  scheduler 30m/407Mi (requests 500m/1Gi), api-server 3m/239Mi (300m/1Gi), dag-processor
  9m/223Mi (200m/512Mi), postgres 17m/50Mi (250m/512Mi). The requests are T1's table and
  were kept so the arithmetic stays comparable; ~59m of real CPU is holding 1070m of floor.
  **RESOLVED at the wave-2 gate (Ross, 2026-08-24): right-size taken.** Requests are now
  scheduler 250m, api-server 100m, dag-processor 50m, postgres 50m in
  `deploy/airflow/values.yaml` + `deploy/k8s/airflow/postgres.yaml`; floor total 3350m vs
  3860m allocatable with cloud 05's two workloads counted, and the streaming driver fits.
  T1's table corrected in the same commit. The LIVE cluster still carries the old requests
  until `bash scripts/airflow-install.sh` re-runs (idempotent) — harmless while no floor
  workload beyond Airflow is applied, but re-converge BEFORE applying raincheck-stream.
- Airflow runs as **`raincheck-build`** (ticket 07's existing SA) with
  `envFrom: [{secretRef: {name: r2-build, optional: true}}]`. `optional` is load-bearing:
  the token does not exist yet, and without it every pod would sit in
  `CreateContainerConfigError`. **ZERO new IAM roles** — R2 is Cloudflare, nothing here
  calls an AWS API, so ticket 07's "pause and ask Ross" gate did not fire.
- **Remote logging is configured and dark.** `remote_logging=True`,
  `s3://raincheck-bronze/airflow-logs`, `remote_log_conn_id=""` (the amazon provider then
  uses boto3's default chain, which reads exactly the four keys `r2-build` carries). Upload
  fails soft until the token exists — the provider's `write()` "fails silently and returns
  False" — so tasks succeed and their logs simply die with the pod. When Ross mints it:
  `kubectl rollout restart -n raincheck deploy/airflow-scheduler deploy/airflow-api-server deploy/airflow-dag-processor`.
- **DAG delivery is NOT here** and that is deliberate: `dags.persistence` and
  `dags.gitSync` are both off, so the DAG folder is empty and `airflow dags list` returns
  nothing. orch 04 chooses between baking DAGs into cloud 03's sha-tagged image and
  gitSync; either is one values edit.
- No admin password exists in this repo. `SimpleAuthManager` generates one at api-server
  start and logs it (`kubectl logs deploy/airflow-api-server | grep "Password for user"`);
  the chart's `createUserJob` is off because it passes admin/admin **on the command line**.

### Traps this ticket paid for

1. **`helm ... --wait` DEADLOCKS the official Airflow chart.** The migration Job is a
   `post-install,post-upgrade` HOOK; helm with `--wait` waits for the Deployments to be
   Ready *before* running post-install hooks, and every Airflow Deployment has a
   `wait-for-airflow-migrations` init container. 15 minutes, then "Progress deadline
   exceeded". The installer omits `--wait` and does `kubectl rollout status` instead.
2. **`kubectl set env` on a Helm-managed Deployment is not undone by `helm upgrade`.**
   Helm's rendered manifest had zero occurrences while the live Deployment still carried
   the variable and `airflow config get-value` still returned it. Unset it explicitly
   (`kubectl set env ... VAR-`).
3. **Env set on the Deployments does not reach TASK pods.** The KubernetesExecutor pod
   template is a separate document inside the `airflow-config` ConfigMap, rendered from
   the chart's global `env`/`extraEnvFrom`. A DAG bundle configured only on the scheduler
   fails in the worker with `ValueError: Requested bundle ... is not configured`. Directly
   relevant to orch 04.
4. **`set -o pipefail` + `head -c` on `/dev/urandom` kills the script with 141.** `head`
   closes the pipe, the upstream reader takes SIGPIPE, and the script dies having printed
   nothing. Use a reader that consumes to EOF (`cut`).
