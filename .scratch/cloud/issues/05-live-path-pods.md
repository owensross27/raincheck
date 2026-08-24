# T5 — The live path as pods, and its latency knobs

Status: done (2026-08-24, branch cloud05-live-path-pods)
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


## Close-out (2026-08-24) — what shipped, and the two things it waits on

**Shipped.** `deploy/k8s/raincheck/precip-live.yaml` (CronJob) and
`deploy/k8s/raincheck/live.yaml` (Deployment), both in the kustomize `resources:`;
`src/raincheck/live_loop.py`; +6 rows on `tests/test_cluster_manifests.py` (32 -> 38) and
`tests/test_live_loop.py` (7, new). All 18 claimed contracts mutation-checked RED.

**The catch-up contract is MEASURED, not assumed** (real NODD feed, 2026-08-24):
steady state (25 h present) **0.70 s, 384 MiB peak, one fetch**; cold start (empty table)
**10.61 s, 592 MiB peak, all 25 hours landed**. That second row IS the acceptance
criterion, observed.

**`live_loop` is one process, not three containers or a shell loop.** It ticks
`live_export.once()` -> `flood_live.live()` -> `publish.publish("live", src=...)` on one
clock with one warm DuckDB connection, which is what cloud 09's `publish()` docstring asks
of this ticket ("an interpreter start every 30 s buys nothing"). Measured over 40
full-fleet cycles: **0.159 CPU-s per cycle (~5.3 millicores averaged over 30 s), RSS
plateau 368 MiB, no leak.** Requests: 100m/384Mi, limit 768Mi.

**One knob was set, and it is not 30 s.** `live_loop.DETECT_S = 360`. CO-OPS publishes
every 6 min and KNYC hourly (flood 14's own measurement, in `flood_live`'s docstring), so a
30 s detector poll re-asks two public APIs 12x and 120x per publication and risks a 429
rendering as a false OUTAGE chip. The tick is still supervised at 30 s; only the fetch runs
at the source's rate. The streaming trigger and archiver poll were NOT touched - no
measurement was taken, so no knob was moved.

**BOTH pods are DARK until two [YOU] items clear, and neither is in this ticket's gift:**

1. **`ref/assets` is not on the cluster.** `precip_live` reads `<root>/ref/cell_pixel`
   every tick, so the CronJob pod dies on FileNotFoundError until `ref/` is archived off
   the Mac (cloud 08's [YOU], the same item blocking cloud 10). `live_loop.detect()`
   degrades gracefully instead - it logs and renders the recolor set empty.
2. **`live/` cannot be shared between pods**, so the emptyDirs are empty and the panel
   renders honestly stale. `paths.data_root()` returning a `Path` is the known blocker -
   but for `precip_live` it is **not the only one**: that module writes with
   `mkdir`/`Path.replace`/`shutil.rmtree` and reads with `Path.glob`, so an `s3a://` root
   alone does not move it. See KNOWN TRAPS.

   Measured price of the emptyDir meanwhile: the catch-up walk skips hours the table
   already has, so a table that dies with the pod makes **every** tick a cold start -
   10.61 s and 25 NODD fetches instead of 0.70 s and one, i.e. **288 cold starts and 7,200
   fetches a day, a 25x multiplier**. A PVC would fix persistence but is barred (cloud 03:
   block volumes attach only to the single-writer streaming Deployment) and would still be
   invisible to the live-export loop that has to read it.

**Floor arithmetic owed to the WAVE 2 GATE.** This ticket adds **100m + 384Mi resident**
(the Deployment) and **100m + 256Mi transient** (the CronJob, ~1-11 s of every 300 s) to
the floor. Against cloud 06's measurement (1110m free, largest single free block 690m):
the Deployment fits the 690m block and leaves 590m; the CronJob fits alongside. Neither
changes the nature of the RED that cloud 06 found - cloud 03's 1000m `raincheck-stream`
never fit in 690m - but both make it tighter, and that decision is Ross's.
