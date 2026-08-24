# T5 — The live path as pods, and its latency knobs

Status: open
Type: task
Blocked by: 01, 03, 07
Owns: spec §5.

## Work

- **precip-live: a CronJob every 5 minutes** (cron's 1-minute granularity is what makes
  300 s expressible), **`concurrencyPolicy: Forbid`** so two ticks can never overlap,
  running `python -m raincheck.precip_live` **unmodified**.
  - **Acceptance is the catch-up contract**: every missing `:00` stamp within MRMS's
    ~25 h retention lands. A latest-only reimplementation silently re-blocks the flood
    replay gate [T11, F12] — which is exactly why the pod runs the module rather than a
    shell equivalent of it.
  - The **2-min and 15-min MRMS products are rejected detector inputs by contract** and
    may never enter `live/precip_cell`'s `:00` series. If ever used, they are a distinct
    feature and table [F11, ADR-0002].
- **live-export + the detector tick are one supervised Deployment**, beside the streaming
  driver, publishing to the static host on the existing 30 s cadence. The panel's two
  halves must never age apart. STALE semantics unchanged [T14].

## Latency knobs — adopted only with a measured win, recorded before/after

| knob | today | note |
|---|---|---|
| streaming trigger | 30 s | 10 s is a config change, not an improvement until measured |
| archiver poll | 30 s | misses ~10-15% of Snapshots [vault feeds ref]; tightening costs Bronze volume — a real trade, priced before taken |

## Tests

`tests/test_precip_live.py::test_live_catchup_lands_missing_hours_once` already pins the
~25 h contract and the CronJob calls the same module, so the contract needs **no new
test**. What is needed is the manifest assertion that the pod really does call the module:
extends `tests/test_cluster_manifests.py` with the CronJob's command **being**
`python -m raincheck.precip_live` and `concurrencyPolicy: Forbid`. That assertion is the
thing standing between this design and a shell one-liner that quietly drops catch-up.

## Inherited from the wave-1 landing (2026-08-24, recorded by the gate)

- **Manifest-test seam**: ONE unioned tests/test_cluster_manifests.py (23 tests,
  kustomize `rendered()` loader). Your CronJob/Deployment assertions extend it, and
  every manifest goes into deploy/k8s/kustomization.yaml `resources:`.
- **COST RULE (gate sweep) — this ticket owns the highest-frequency workloads, so
  it wears it hardest**: a 5-min CronJob fires ~8,640 times a month; NOTHING may
  happen per tick that belongs in the image (no pip, no jar resolution, no
  downloads — the sha-tagged image carries everything, `imagePullPolicy:
  IfNotPresent` so a cached node never re-pulls). The same for the 30 s
  export/detector loop: setup once at container start, work only per tick. A
  per-tick install is a permanent, silent, recurring bill.
- **Kafka addresses are frozen** (cloud 02, LIVE): in-cluster pods bootstrap
  `raincheck-kafka-bootstrap.kafka.svc:9092`; 9094 is the capture box's listener
  and advertises a name only the box resolves.

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
