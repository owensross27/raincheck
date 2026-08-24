# 01 — The repo front door: description, topics, README, operator links  ✅ DONE 2026-08-24

**What to build:** anyone opening github.com/owensross27/raincheck (or the local
checkout) understands in one screen what the whole system is, what is running right
now, what is deliberately dark and why, how to reach the operator surfaces
(Airflow, the maps, the runbook), and what comes next. Today the repo has an EMPTY
description, no topics, and a README frozen in the laptop-only era ("Does rain slow
the buses?" + venv instructions) — measured 2026-08-24.

**Decided by Ross (2026-08-24): the repo KEEPS the name `raincheck`.** No rename;
the description/topics/README carry the story.

**Blocked by:** None — can start immediately. Parallel-safe with wave-3 tickets
(touches README.md, repo metadata, and docs/ only).

**Status:** done (2026-08-24, `795bf69`, branch `repodocs01-front-door`)

Work notes (verified facts to build on, not to re-derive):
- Repo is PRIVATE; visibility is not this ticket's to change.
- Description: one sentence covering the whole system, e.g. "NYC bus performance x
  rain x flood risk - GTFS-RT capture through Kafka/Spark/Sedona to GeoParquet,
  flood detection, per-stop history and notifications, on EKS + Airflow". Topics
  from the real stack (gtfs-realtime, kafka, spark, sedona, duckdb, geoparquet,
  kubernetes, airflow, nyc). Set via `gh repo edit`.
- README sections the current one lacks: (1) system overview — capture box ->
  cluster Kafka -> Spark/Sedona -> GeoParquet Bronze/Silver/Gold -> flood
  detection -> public host; (2) a WHAT-RUNS-WHERE table, honest about dark
  components and WHY each is dark (the runbook's STATUS is the source: live.geojson
  gated on MTA terms; raincheck-stream/precip-live/raincheck-live dark on ref/ +
  tokens; publish dark on the bucket; Airflow remote logging dark on the token);
  (3) operator access — Airflow has NO public URL by design (no
  LoadBalancer/NodePort is a tested invariant): document the port-forward and the
  admin-password-from-logs commands, verifying the exact service/deployment names
  with kubectl in-session rather than trusting this file; (4) cadences — derive
  the schedule table from the repo (CronJob schedules, loop intervals, launchd
  plists, the monthly bill review) instead of restating numbers from memory;
  (5) where the plans live — the wayfinder maps under .scratch/*/map.md, the
  runbook at ~/vault/raincheck-runbook/ (note it is OFF-repo, private), and the
  wave roadmap one-liner; (6) licence/attribution posture — no public re-serving
  of raw MTA data, the honesty string's spirit.
- The README must not leak operator secrets or private infrastructure details
  beyond what a private repo's own docs already carry (account id appears in
  manifests already; add nothing new).
- Re-run this ticket's box whenever a wave gate closes if the table has drifted —
  cheap by design, so keep the README's claims derivable (point at sources rather
  than duplicating numbers where possible).

Acceptance:
- [x] `gh repo view` shows a non-empty description and topics
- [x] README's what-runs-where table matches the runbook's STATUS on the day it
      lands (each dark row names its gate)
- [x] Airflow access section verified live: the port-forward command and the
      password command both executed and their real names recorded
- [x] Cadence table derived from the repo's own manifests/plists, with file
      pointers
- [x] No new secret or private endpoint appears in the diff
- [x] RUN LOG entry appended; this file marked done

---

## Close-out (2026-08-24, `795bf69`, branch `repodocs01-front-door`)

Description and topics set with `gh repo edit`; `README.md` rewritten (206 insertions,
10 deletions). No tests exist for docs — nothing in `tests/`, `src/` or the `Makefile`
references `README.md`, so nothing was run and nothing could have been.

**Verified live, not from memory** (this is the part a re-run must redo, because names
and state drift):

- Airflow UI: `kubectl port-forward -n raincheck svc/airflow-api-server 8080:8080`.
  Executed; `GET /` and `/api/v2/version` both answered 200 through the forward, the
  latter reporting Airflow **3.2.2**. Service and Deployment are both named
  `airflow-api-server`; the Service is ClusterIP.
- Admin password: `kubectl logs -n raincheck deploy/airflow-api-server | grep "Password
  for user"` — executed, exactly one match, user `admin`. **The value was deliberately
  redacted before it reached the terminal** (`sed` over the match), because a token
  printed to a terminal during cloud 12's session became a real rotation item.
- No public URL: zero Services of type LoadBalancer or NodePort exist **cluster-wide**
  (`kubectl get svc -A`), matching
  `tests/test_cluster_manifests.py::test_no_loadbalancer_or_nodeport_service`.
- Applied workloads in ns `raincheck`: the three Airflow Deployments plus the metadata
  DB StatefulSet, and nothing else. `precip-live`, `raincheck-stream` and
  `raincheck-live` are **not applied at all** — their manifests are shipped and tested,
  nothing is running them.
- Secrets in ns `raincheck`: `r2-build` exists, `r2-serve` does not. ServiceAccounts
  `raincheck-build` and `raincheck-serve` both exist.
- `airflow dags list` on the scheduler: exactly one row, `raincheck_smoke`, bundle
  `dags-folder`, fileloc `/opt/airflow/dags/raincheck_smoke.py`.
- Mac LaunchAgents: `com.raincheck.archiver` running, `com.raincheck.daily` and
  `com.raincheck.precip-live` loaded.

**Found while writing the "Working in the repo" section — a real footgun, now in the
README and in KNOWN TRAPS:** the Makefile declares no `.DEFAULT_GOAL` and has no `help`
target, so bare `make` falls through to the first target, `topics` — which DROPS and
recreates both Kafka topics. Confirmed without running it: `make -n` prints
`.venv/bin/python -m raincheck.topics`, and `make -p -n` reports
`.DEFAULT_GOAL := topics`. An earlier draft of this README claimed `make` with no target
lists the targets; it does not.

**STATUS corrections carried back** (the README's table contradicted STATUS's opening
paragraph, which contradicted STATUS's own later text): Airflow remote logging is LIVE,
not "dark until `r2-build` is minted"; and cloud 05's two pods are no longer waiting on
`ref/` reaching the cluster or on tokens — `ref/` is in the bucket and `r2-build` exists
as of cloud 12's addendum. What actually holds them dark is the WRITER gap (R2 writes
refuse by design) plus, for `raincheck-live`, the missing `r2-serve`/public bucket.

**Re-running this ticket after a gate:** re-check the six live probes above, the dark
rows and their gates, and the cadence table's source files. The claims are all pointed
at their source file rather than restated, so most drift shows up as a wrong pointer
rather than a wrong number.
