# raincheck

NYC bus GTFS-RT x rain x flood risk. Bus positions and trip updates are captured to
Bronze Parquet and produced to Kafka; Spark 3.5.3 + Sedona 1.9.1 enrich them with
spatial keys and computed Delay and join them to hourly precipitation (NOAA AORC 1 km
for the archive era, MRMS for the live era); the result lands as Hive-partitioned
GeoParquet Bronze/Silver/Gold. On top of that dataset sit a flood-event history and
per-asset exposure scoring, a live detector, and a query path that answers "has this
stop flooded before" and "is it flooding now" for an agent, a map, or a notifier.

The batch pipeline works today. The move off the laptop and onto EKS + Airflow is in
progress, and the table below says exactly how far it has got.

- **Domain vocabulary** — `CONTEXT.md` (Poll, Snapshot, Ping, Passage, Delay, Cell,
  Unit, Bronze/Silver/Gold, and what not to call them). Read it before naming anything.
- **Decisions with consequences** — `docs/adr/`
- **The public read API** — `docs/read-api-contract.md` (the static contract on the
  bucket: families, keys, cache semantics, the `contract` integer a consumer refuses
  on, and how a payload's age is dated by the reader)
- **Storage layout and schemas** — `research/09-storage-schemas.md`
- **Feed facts** — `~/vault/nyc-mta-bus-feeds-reference.md` (off-repo)

## The system

```
  MTA GTFS-RT                        NOAA AORC (Zarr)      MRMS (NODD)
  6 feed kinds, 30 s poll            archive era           live era
        |                                  |                    |
        v                                  |                    |
  raincheck.archiver                       |                    |
        |                                  |                    |
        +---> Bronze Parquet --(hourly push)--> R2 archive       |
        |                                  |                    |
        +---> Kafka (Strimzi KRaft, EKS)   |                    |
                  |                        |                    |
                  v                        |                    |
        Spark structured streaming         |                    |
        -> live/vp, live/tu ---------------|--------------------+
                  |                        |                    |
                  v                        v                    v
        Spark 3.5.3 + Sedona 1.9.1 -- precip join on (Cell, Hour)
                  |
                  v
        Silver: Passages, Delay, flood observations, asset features
                  |
                  v
        Gold: cell_hour_speed, cell_hour_route, flood_labels, flood_matrix,
              flood_exposure
                  |
        +---------+-------------------------------+
        |                                         |
        v                                         v
  flood exposure + live detector          raincheck.query (SEAM Q)
        |                                    public | local
        +--------> raincheck.publish -------------+
                          |
                          v
              public R2 bucket -> web/ map, per-stop history, notifications
```

Orchestration is Airflow on the cluster (KubernetesExecutor, DAGs baked into the
image); the nightly build is still `make daily` on the Mac until orch 05 lands it as
a DAG.

## What runs where

Measured against the live cluster and this Mac on **2026-08-24**. "Dark" means the
code and its manifest are shipped and tested but nothing is running it yet; every dark
row names what it is waiting on.

| Component | Runs on | State | Gate, if dark |
| --- | --- | --- | --- |
| GTFS-RT capture, all six feed kinds | EC2 capture box (`systemd/raincheck-archiver.service`) | running | — |
| GTFS-RT capture, second copy | this Mac (`launchd/com.raincheck.archiver.plist`) | running, deliberately redundant | retires at the fail-closed cutover: `make cutover` after 7 clean coldgaps days (date-gated 2026-08-31) |
| Bronze -> R2 push, then prune what is verified remote | capture box (`systemd/raincheck-coldpush.timer`) | running | — |
| Bronze hour-completeness check in R2 | capture box (`systemd/raincheck-coldgaps.timer`) | running | — |
| Kafka 4.3.1, Strimzi-managed KRaft, one combined controller+broker node, topics `raincheck.bus.vp` + `raincheck.bus.tu` (`deploy/k8s/kafka/kafka.yaml`, `src/raincheck/topics.py`) | EKS, ns `kafka` | running | — |
| Airflow 3.2.2, KubernetesExecutor, metadata DB on gp3 | EKS, ns `raincheck` | running | — |
| Airflow remote task logging to R2 | EKS | live | — |
| Nightly catch-up build (`make daily`) | this Mac (`launchd/com.raincheck.daily.plist`) | running | moves to Airflow at orch 05; only `raincheck_smoke` exists on the cluster today |
| Spark streaming Kafka -> `live/vp`, `live/tu` (`deploy/k8s/raincheck/streaming.yaml`) | EKS | **dark** — manifest shipped, not applied | partially closed 2026-08-24 (wave-3 gate): the writer seam exists (`RemotePath` whole-object writes; Spark writes `live/` over s3a; `stream.prune` converted — an `events` build on R2 proved parity EQUAL), so `live/`-on-R2 is unpinned for the STREAM half. Still refusing by design: `stream.receipt` — so the streaming chain is not fully converted, and applying the pod is an unowned op. |
| Live MRMS precip tick, `*/5` CronJob (`deploy/k8s/raincheck/precip-live.yaml`) | EKS | **dark** — manifest shipped, not applied | `precip_live` is POSIX-only by contract (unmodified per cloud 05) and still refuses a remote root — its writer gate did NOT move with cloud 13. Its `refpull` precondition cleared on 2026-08-24 (`ref/` is in the private bucket, `r2-build` exists), but with `live/precip_cell` in an emptyDir every tick is a cold start, and no other pod can read what it writes. The Mac LaunchAgent is still the only live precip tick. |
| Live loop: export -> detect -> publish, 30 s (`deploy/k8s/raincheck/live.yaml`) | EKS | **dark** — manifest shipped, not applied | the `r2-serve` Secret does not exist, because the public bucket does not exist. Verified live: ns `raincheck` holds `r2-build` and not `r2-serve`. |
| Publishing to the public static host (`make publish FAMILY=...`) | anywhere with the serve token | **dark** | the public R2 bucket has not been created (one dashboard step, plus minting `r2-serve`) |
| `live.geojson` — the current-fleet view | (as above) | **built and gated OFF** | `raincheck.publish.LIVE_TERMS_VERIFIED is None`. MTA redistribution terms have not been read; the gate refuses rather than defaults, and a test refuses an empty gate. Everything else in the family list publishes without it. |
| Great Expectations suites and Data Docs | EKS (Airflow) | not built | orch 08 |
| Per-stop notifications | — | not built | the notify effort, waves 5-9 |

Nothing in the cluster is reachable from the internet. That is provided by the security
groups and by the **absence of any LoadBalancer or NodePort Service** — never by subnet
placement, since there is no NAT Gateway. The Kubernetes half is a test
(`tests/test_cluster_manifests.py::test_no_loadbalancer_or_nodeport_service`); the AWS
half is `make inboundaudit`, which no test can see, so run it after any cluster change.

## Operator access

**Airflow has no public URL, by design.** Reach the UI through a port-forward:

```bash
kubectl port-forward -n raincheck svc/airflow-api-server 8080:8080
# then open http://localhost:8080
```

The user is `admin`. No password exists in this repo: `SimpleAuthManager` generates one
at api-server start and logs it, so read it back from the pod rather than storing it.

```bash
kubectl logs -n raincheck deploy/airflow-api-server | grep "Password for user"
```

Both commands were executed against the live cluster on 2026-08-24 (service
`airflow-api-server`, deployment `airflow-api-server`, both ClusterIP; `GET /` and
`/api/v2/version` answered 200 through the forward). The password is deliberately not
recorded anywhere in this repo — treat any credential printed to a terminal as exposed
and rotate it.

Other operator surfaces:

| Surface | How |
| --- | --- |
| Cluster inventory | `kubectl get pods,deploy,cronjob -n raincheck` and `-n kafka` |
| Capture-box health | `systemctl --failed` on the box — a coldgaps gap leaves its unit failed |
| Mac agents | `launchctl print gui/$(id -u)/com.raincheck.<archiver\|daily\|precip-live>`; logs under `data/logs/` |
| Cost against the $130 envelope | `make bill-review` (rc 1 = hard look, rc 2 = could not check) |
| Network posture | `make inboundaudit` vs `deploy/cloud/inbound-allowlist.yaml` |
| Escape hatch off the cluster | `make downscale DO=plan` — plans a two-EC2 fallback, touches no AWS |
| The map, locally | `make export && make vendor && make web` |

## Cadences

Every row is derived from the file that declares it; read the file for the reasoning,
which is where the number is argued.

| What | Cadence | Declared in |
| --- | --- | --- |
| GTFS-RT poll | 30 s | `src/raincheck/archiver.py` (loop tail) |
| Bronze -> R2 push + prune | hourly, up to 300 s jitter | `systemd/raincheck-coldpush.timer` |
| R2 hour-completeness check | daily 02:15 UTC | `systemd/raincheck-coldgaps.timer` |
| Catch-up build (gapfill, coldpush, events, gold, precip, prune) | daily 06:00 America/New_York | `launchd/com.raincheck.daily.plist`; stages in `src/raincheck/daily.py` |
| Live precip tick | 300 s | `launchd/com.raincheck.precip-live.plist`; cluster twin `deploy/k8s/raincheck/precip-live.yaml` (`schedule: "*/5 * * * *"`, `concurrencyPolicy: Forbid`) |
| Live export | 30 s | `live_export.INTERVAL_S` |
| Detector fetch inside that loop | 360 s | `live_loop.DETECT_S` — CO-OPS publishes every 6 min, so polling faster only invents rate-limit outages |
| Publish, per family | live 30 s · insight per build · docs per Airflow run · history per spine rebuild · site deploy-time | `raincheck.publish.FAMILIES` |
| Cloud bill review | monthly, on the 1st | `make bill-review APPEND=1` |

Live tables are kept 48 h (7 days for precip) and pruned by the daily run.

## Working in the repo

Spark 3.5.3 + Sedona 1.9.1 run in-process from the repo venv on the brew `openjdk@17`
(`brew install openjdk@17`, never `brew link`). The Makefile exports `JAVA_HOME` and
`TZ=UTC`; `.env` (gitignored) may override `JAVA_HOME` and set `RAINCHECK_ARCHIVE_ROOT`
(the data root, default `data/`) and `RAINCHECK_BRONZE_GB` (the archiver's absolute byte
budget over `<root>/archive`; moving the root does not shrink the count, so size it to
the drive). `raincheck.spark.session()` is the only place Spark is configured — steered
by environment, never forked — and `raincheck.duck` is the DuckDB read-back helper.
`raincheck.paths.data_root()` returns a local `Path` or, for an `s3://`/`s3a://` root, a
read-only `RemotePath`.

```bash
uv venv .venv && uv pip install -e .
make warm       # one session through the factory: warms the Ivy cache (~240 MB, once)
make test       # pytest; Spark tests skip when no JVM is found
```

Every target carries a `##` comment saying what it does — read the Makefile, and always
name a target. **`make` with no arguments is not a help listing: there is no
`.DEFAULT_GOAL`, so it falls through to the first target, `topics`, which drops and
recreates both Kafka topics and discards whatever they were retaining.** (Bronze keeps
the durable record, so this is recoverable, but it is never what you meant.)

The full suite is the landing gate, not a per-change habit.

### Smoke slice

```bash
docker compose up -d --wait
.venv/bin/python -m raincheck.archiver --once      # real poll -> Parquet + Kafka
.venv/bin/python -m raincheck.zarr_probe           # AORC Zarr vs Hurricane Ida
.venv/bin/pytest -q                                # frozen-fixture checks
```

The container image is built by `scripts/cloud-image.sh` — arm64, tagged by git sha,
never `:latest`, and two stages (`runtime` and `dags`), so `--target` is mandatory on
any hand-rolled build.

## Where the plans live

Each effort is a wayfinder map plus its tickets. Maps hold decisions; build work goes
through `/to-spec` -> `/to-tickets` -> `/implement` in their own sessions.

| Effort | Map | What it decides |
| --- | --- | --- |
| pipeline | `.scratch/pipeline/map.md` | capture -> Kafka -> Spark/Sedona -> GeoParquet, and the precip join |
| flood | `.scratch/flood/map.md` | flood history, per-asset exposure scoring, the live detector |
| cloud | `.scratch/cloud/map.md` | the EKS runtime, R2, cost envelope, retiring the Mac |
| orchestration | `.scratch/orchestration/map.md` | the nightly as a real Airflow DAG, GX suites, Data Docs |
| notify | `.scratch/notify/map.md` | the query path (SEAM Q) and per-stop notifications |
| frontend | `.scratch/frontend/map.md` | one map surface: live, flood risk, and history read together |

Specs live beside their maps (`.scratch/<effort>/spec.md`), tickets under
`.scratch/<effort>/issues/`. Conventions for both are in `docs/agents/`.

**The execution runbook is off-repo and private** (`~/vault/raincheck-runbook/`). It is
the only coordination surface for the build-out — wave membership, gates, the run log,
and the traps that cost someone a day. Nothing here duplicates it, because a second copy
would drift.

## Data, licence and attribution

This repo is private and carries no licence. The posture on the data matters more than
the posture on the code, and it is enforced in code rather than remembered:

- **No public re-serving of raw MTA data.** The live view is a current snapshot only —
  the live family's keys are literals, so no tick can write a dated second copy, and the
  public bucket is to be created with versioning and lifecycle rules OFF (versioning
  would silently retain every 30 s snapshot and turn the host into the served history
  this rule exists to prevent, without a line of code changing). There is no bulk or
  protobuf endpoint: `raincheck.publish.PUBLISHABLE` is an allowlist of web payload
  suffixes, so a `.pb`, a `.parquet` or a tarball is refused by construction.
- **MTA attribution on the page**, pinned by `tests/test_publish.py`.
- **The redistribution gate is fail-closed.** `LIVE_TERMS_VERIFIED` is `None` and the
  gate refuses; it takes a dated receipt naming what was read, not a boolean.
- **The licence boundary is a parameter, not a caller property.** `raincheck.query`
  defaults to `public`, which ships counts and attachment facts; `local` ships the rows
  behind them — FloodNet depths, the observation rows themselves, MTA alert rows.
  A consumer that forgets to choose is safe.
- **Sources with no data licence stay local.** subwaydata.nyc publishes an MIT *tool*
  licence and no data licence, so subway-impact numbers never cross the serving
  boundary; NYSDEC/DEP snapshots are fetch-and-use with rehosting barred.
- Claims are exactly as strong as the validation behind them. Where a number is gated,
  hidden or inconclusive, the surface says so rather than rounding it to a clean answer.
