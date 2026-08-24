# 04 — DAG delivery and per-task runtime

**What to build:** A DAG that lives in the pipeline's own image reaches the scheduler and
runs one real task on the cluster, with declared pod resources and credentials from a
cluster Secret. This is the platform seam proved on a trivial graph before the real one
depends on it. It replaces the map's ticket 1 ("deployment shape"), which the cloud
effort's spec already owns down to the executor, the metadata database and remote
logging — implementing both documents' version would produce two Helm value sets.

**Blocked by:** None in this tracker. **External precondition:** the cloud effort's
Airflow install (KubernetesExecutor, metadata database, remote task logs). If it is not
there, this ticket waits on it — it must not install a second Airflow.

**Status:** done (2026-08-24, branch `orch04-dag-delivery`)

- [x] DAG code ships inside the one git-sha-tagged image every pipeline pod runs: no git-sync sidecar, no separate DAG volume, so DAG and code are the same version by construction
- [x] A DAG in that image is picked up by the scheduler and one task pod runs an existing make target to completion
- [x] That task's pod declares CPU and memory requests taken from the cloud effort's stage-placement and capacity numbers; no capacity number is invented here
- [x] The task reads its object-store credentials from the cluster Secret bound to its ServiceAccount; nothing is baked into the image
- [x] No stage runs on the scheduler pod — a stage implemented as a callable inside the DAG file is a defect, not a shortcut
- [x] The external precondition is verified before any DAG work, and recorded

## Close-out (2026-08-24, branch `orch04-dag-delivery`, `e9323ebd540c` + the pin commit)

**PROVED ON THE CLUSTER, not argued.** DAG run `orch04-proof-1` of `raincheck_smoke`:
task `warm` **success in 87 s**, whole run 188 s including two node purchases. The stage
pod logged `make: Entering directory '/opt/raincheck'` -> `spark 3.5.3`, so a real Spark
session came up inside the pod's memory request off the baked jars. Both burst nodes were
bought by Karpenter for this run and consolidated away after it.

### What was built

- **`dags/raincheck_stage.py`** - the seam every raincheck DAG builds tasks with:
  - `pod(shape, image=None) -> dict` reads the named PodTemplate out of
    `deploy/k8s/raincheck/build.yaml` and substitutes only the image. Shapes are
    `raincheck-stage` and `raincheck-spark`; there is no third.
  - `make(target, **vars) -> list[str]` and `module(name, *args) -> list[str]` are the two
    legal command forms.
  - `stage_task(task_id, shape, command, **kwargs) -> KubernetesPodOperator` fills in the
    command and nothing else (`pod_template_dict=pod(shape)`).
- **`dags/raincheck_smoke.py`** - the trivial graph: one task, `make -C /opt/raincheck warm`,
  `schedule=None`. `warm` because it is the only stage that completes on an empty data root.
- **`docker/Dockerfile`** - the existing content is now stage `runtime`; a new stage `dags`
  is `FROM apache/airflow:3.2.2` with `dags/` at `/opt/airflow/dags`, the placement table
  at `/opt/airflow/placement/build.yaml`, and `ARG/ENV RAINCHECK_IMAGE`. Its own build
  check imports the DAG and asserts the pin resolved.
- **`scripts/cloud-image.sh`** - builds and pushes BOTH targets from one tree
  (`:<sha>` and `:<sha>-airflow`) and pins the second into `deploy/airflow/values.yaml`
  the way it pins the first into the kustomize transformer.
- **`deploy/airflow/values.yaml`** - `images.airflow` and `images.pod_template` are both
  the DAG image. `dags.persistence`/`dags.gitSync` stay false; nothing else changed.
- **`tests/test_dag_delivery.py`** - 12 tests, one per acceptance row. Eleven run
  everywhere; the twelfth needs Airflow installed and skips on the Mac (it was run against
  the cluster's exact versions, Airflow 3.2.2 / cncf-kubernetes 10.17.1, and passes).
  All seven contracts mutation-checked: dropping the resources, dropping the burst
  selector, breaking the sha coupling, a DAG passing `container_resources`, a
  `PythonOperator` in a DAG file, `gitSync: true`, and losing `optional: true` on the
  secretRef each turn exactly the intended test red.

### Measured, for whoever sizes the nightly

- **A task is TWO burst pods, not one.** The KubernetesExecutor stamps a worker
  (200m/512Mi, the DAG image, runs `airflow tasks run`) and the KubernetesPodOperator then
  creates the stage pod beside it (the placement table's request). A task mapped over N
  days is 2N pods. Nothing lands on the floor.
- **Node purchase dominates a short task.** 95 s for the worker's node (`c6gd.medium`),
  74 s more for the stage pod's (`m7g.large` - 1500m/3Gi does not fit a medium), against
  87 s of actual task time. The operator's `startup_timeout_seconds` is 900, not the
  default 120, for exactly this: at the default the task fails with an AirflowException
  that reads like the stage broke when in fact nothing had started yet.
- **Remote logging failed soft, as designed.** `NoCredentialsError` from the S3 handler in
  the worker log, task still `success`. Task logs stay dark until `r2-build` is minted.
