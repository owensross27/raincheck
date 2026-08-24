# Wayfinder map: raincheck frontend

Charted 2026-08-24 at Ross's directive, in the wave-2 gate follow-up session —
this was the runbook's last uncharted phase ("chart the frontend map", STATUS
[YOU] item, now resolved by this file). Charted leaner than a full wayfinder
round: the destination and fog come from Ross's own words plus the measured
facts already in the runbook; the decisions themselves are the tickets'.

## Destination

One place to SEE the system: a map of NYC where near-real-time updates (bus
positions, current slowdowns), flood risk (station/stop tiers, areas affected),
and history (per-stop flood record, past events) read together — plus a decided
answer on a unified read API that future apps and alerting integrations could
consume. The map is done when nothing is left to decide before `/to-spec`
collapses it and `/to-tickets` slices the build (those build tickets are
expected to slot around wave 8, after flood 15/17 and notify 05 land their
layers).

## Notes

- **PLAN-ONLY. This map carries no execution.** Build work goes through
  `/to-spec` -> `/to-tickets` -> `/implement` in their own sessions, exactly as
  the pipeline map did. A ticket here that starts reading like "build the X" is
  mis-typed — retype it or move it downstream.
- Much of the destination ALREADY EXISTS as parts: `web/` is a live MapLibre
  page (30 s vehicles + flood panel, dark until the [YOU] bucket + MTA terms);
  the insight exports (cells/headline/zones) render delay-by-cell per build;
  notify 02's SEAM Q serves per-stop history (public mode, licence boundary by
  construction); notify 05 will write the per-asset static files; flood 10/15/17
  will produce the risk tiers and overlays. The fog is INTEGRATION and the API,
  not the layers.
- Constraints that bound every decision here (measured/frozen, do not
  re-litigate): live tier serves CURRENT SNAPSHOT ONLY — no served history for
  live (spec §9); no public re-serving of raw MTA data; live.geojson stays rc 3
  until Ross writes the terms receipt; the cluster accepts NO inbound (no
  LoadBalancer/NodePort — a tested invariant), so any API is edge/static, never
  cluster ingress; a Cell id crosses any boundary as its H3 hex string, never
  int64; STALE is computed by the READER dating the file.
- In-repo alerting is NOT this map's problem: notify 08/10/12 own the decision
  function and notifier, in-process on the 30 s loop. The API question is about
  EXTERNAL consumers (Ross's future apps).

## Decisions so far

- 2026-08-24 · ticket 04 (research) RESOLVED — Cloudflare Worker/R2 facts:
  Workers free tier 100k req/day / 10 ms CPU; CORS + per-object cache-control
  work on a public bucket WITHOUT a Worker; the edge cache fronts a
  custom-domain bucket automatically but never r2.dev and never a Worker
  (Worker runs first, pays Class B on binding reads); custom domains free on
  both; WAF rate limiting exists on the Free plan (1 IP-keyed rule). Full
  cited findings: `.scratch/frontend/research/04-worker-r2.md`; gist on the
  ticket. Ticket 03 unblocked.

## Not yet specified (fog)

- Embeds/sharing: whether any view is embeddable elsewhere once visibility
  changes (repo is private today; the host bucket is public-by-design).
- Auth/keys and abuse control for an API, if ticket 03 decides one exists.
- Schedule-vs-actual comparison as a visual layer ("current bus slowdowns or
  schedules" — the slowdown half exists as insight exports; the schedule half is
  fog until a concrete question can be phrased).
- Mobile/small-screen treatment of a four-layer map.

## Out of scope

- Alerting internals (notify 08/10/12 own them; this map may only decide what an
  external consumer READS).
- The showcase (orch 13 owns static Data Docs / DAG graph / walkthrough on the
  public host).
- Served history for the live tier (spec §9 bars it structurally — versioning
  stays OFF on the bucket).
- Repo front door / README (chartered separately: .scratch/repo-docs/issues/01).
