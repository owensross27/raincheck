# 01 — The repo front door: description, topics, README, operator links

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

**Status:** ready-for-agent

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
- [ ] `gh repo view` shows a non-empty description and topics
- [ ] README's what-runs-where table matches the runbook's STATUS on the day it
      lands (each dark row names its gate)
- [ ] Airflow access section verified live: the port-forward command and the
      password command both executed and their real names recorded
- [ ] Cadence table derived from the repo's own manifests/plists, with file
      pointers
- [ ] No new secret or private endpoint appears in the diff
- [ ] RUN LOG entry appended; this file marked done
