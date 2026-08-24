# T3 — Spark on Kubernetes, the image, and the stage-placement table

Status: open
Type: task
Blocked by: 01, 02, 11
Owns: spec §3, including the T17 backfill arm.

## Work

**Execution mode is decided by job shape — no spark-operator (DEFAULT).**

- **Per-day work: one pod per Service date, Spark in-pod.** `events` is ~275 s/day and
  each Service date is independent; cluster-mode scheduling per day would cost more
  than the work. Parallelism comes from Airflow dynamic task mapping over days onto
  Karpenter burst — `nodeSelector: raincheck.io/pool=burst`. **Without that selector a
  build pod lands on the floor and competes with Kafka and the streaming driver.**
- **Genuinely wide work: cluster-mode `spark-submit --master k8s://`** — the `gold`
  monthly reduce over touched months, and the T17 backfill.
- **Streaming: a Deployment** running a client-mode driver, checkpoint on a dedicated
  block volume, recovering on restart [T12].
- *Overturn the no-operator default if* declarative SparkApplication status inside
  Airflow, or a shared Spark history UI, becomes something the showcase needs.

**One image for every raincheck pod.** Built from the in-house slim Sedona Dockerfile
(`~/quakestream/stack/docker/sedona.Dockerfile`, geotools-wrapper 1.9.1-33.5), extended
with eccodes (precip), DuckDB (exports) and the repo package. Pushed to ECR, **tagged by
git sha, never `:latest`**. Five specialised images would be five drifting runtimes.
Image must be arm64 — the whole cluster is Graviton.

**Storage.** Every table read and written over `s3a://` against R2 with the endpoint
override; no local Bronze mirror. `live/` moves to R2 because it has multiple writers
and readers across pods (streaming writes `live/vp` + `live/tu`, precip-live writes
`live/precip_cell`, live-export and the detector read all three) — which a single-attach
block volume cannot serve. That is what unpins `prune`. Block storage only for
single-writer state: the streaming checkpoint, Kafka log dirs, Airflow's Postgres.

**Stage placement for the eight `daily.py` stages** [T15]:

| stage | where it runs | notes |
|---|---|---|
| `gapfill` | own pod per feed kind, ephemeral staging volume >= 3 GB | stages ~1.24 GB/day before push-then-prune [T20]; network-bound, no Spark |
| `gapverify` | own pod, no Spark | reads filled hours against archiver neighbours |
| `gapcheck` | own pod, minimal | listing only; strictly after `gapfill` [T20] |
| `coldpush` | own pod | scoped to the gapfill staging area — capture already pushes hourly from the box [T19], so this now means "push what the cluster just wrote" |
| `coldcheck` | own pod | stays soft: reports, never fails the run [T15] |
| `events` (+`gold`) | one pod per Service date on spot burst; `gold` a single reduce behind them | dynamic partition overwrite makes re-runs idempotent [research/07] |
| `precip` | own pod (eccodes image), Spark in-pod | MRMS months are UTC, unlike the Service date above |
| `prune` | any pod | unpinned by the `live/`-on-R2 decision above |

The all-stages-always-run contract and the failure-naming exit are preserved as written;
expressing them as DAG edges belongs to `.scratch/orchestration/map.md`.

**Re-measure before sizing.** The requests table in `01-eks-cluster.md` carries the Spark
driver row as a placeholder. The Mac's `local[6]` + 3 g is Mac-shaped [`spark.py`]. Measure
on t4g.large and replace the row before anything else sizes against it.

**T17 arm.** The dead-SSD precondition is replaced by measured R2 headroom. The backfill is
a separately sized one-off (2,278 files, not the nightly shape), run cluster-mode.
**Trigger: the first day the `events` parity gate passes on the cluster** — the backfill is
the first thing the cluster is trusted with, and not before it is trusted.

## Acceptance

- Parity against `make daily` by **content equality** via `raincheck.parity` (ticket 11) —
  row counts plus a sha over sorted rows per partition. **Never bytes:** byte-identity holds
  only within one JVM session, since parquet-mr permutes footer encoding order across
  sessions (~27 bytes, data pages identical) [F01, T02], and a cluster run is by construction
  a different session.
- A killed per-day build re-runs clean — spot interruption absorbed by idempotence.

## Tests

Every existing module test in `tests/` still covers behaviour after the move, because no
stage is re-implemented. **That safety net holds only as long as no ticket forks a module
for the cluster.** Extends `tests/test_cluster_manifests.py`: every image is the one ECR
repo pinned by tag with no `:latest`; block-volume claims attach only to single-writer
workloads.

## Inherited from the wave-1 landing (2026-08-24, recorded by the gate)

- **The image build is unblocked**: the `eccodes>=2.47` fix (02404e6) is on master
  at `7b7bfc8`. The old `>=2.48` pin resolved on NO platform (2.48.0 is the C
  library's version, not the python package's) and would have failed this ticket's
  first `pip install -e .` inside the image.
- **The manifest-test seam is settled**: ONE unioned tests/test_cluster_manifests.py
  (23 tests). Cloud 02's kustomize `rendered()` is the single loader; `docs()`
  returns `list(rendered())`. Extend that file, and add EVERY manifest you write to
  deploy/k8s/kustomization.yaml `resources:` — an unlisted file is a file no test
  sees.
- **COST RULE (from the gate's cost-driver sweep): nothing installs at pod start.**
  Every recurring pod second is billed; setup belongs in the image layer, once per
  git sha, not in the entrypoint, once per run. Concretely for this ticket:
  (1) BAKE the Sedona/Kafka jars INTO the image — the repo's local session uses
  `spark.jars.packages`, which only looks free on the Mac because ~/.ivy2 is warm;
  on the cluster a fresh pod re-resolves against Maven Central per pod (slow starts,
  repeated egress, and one Maven outage stops the nightly). `spark.jars` pointing at
  baked paths, or jars copied into $SPARK_HOME/jars, never `spark.jars.packages` in
  a pod. (2) Replace deploy/k8s/kafka/topics-job.yaml's `pip install confluent-kafka`
  on a stock python image with this ticket's sha-tagged ECR image (already tasked —
  now also a standing cost rule, since anything that reruns that Job pays the
  install every time). (3) Close cloud 08's recorded deviation: downscale.sh's
  `bootstrap()` venv-installs the repo on AL2023 per exercise; once the ECR tag
  exists it becomes `docker run <ecr>:<sha> make <target>`.
