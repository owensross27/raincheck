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

- 2026-08-24 · ticket 01 (grilling) RESOLVED — **ONE page: the integrated map
  EXTENDS `web/index.html` with plain per-layer toggles** (the `#livetoggle`
  pattern, seven layers), no second page and no modes; the `#provenance`
  attribution strip is mode-invariant. Age is computed from HTTP response
  headers on the ORIGIN's clock (`Date` − `Last-Modified`), never a new payload
  stamp — that would break `test_re_export_is_byte_identical`; the live pair
  keeps its `vp_age_s` composite, a multi-source layer shows a row PER SOURCE on
  flood 15's frozen budgets, thresholds stay a table. Vocabulary FRESH / STALE
  (+reason) / OFF / GATED — freshness is not verdict. **The reversal: the MTA
  gate cuts by LINEAGE and runs THROUGH the flood panel** (`flood_truth.py:285`
  emits an `mta_alerts` tier beside the publishable `floodnet` one at :218), so
  flood 15 must write TWO meta files, one per gate side. No byte budget —
  nothing in the repo compresses (`publish._put` sends no `ContentEncoding`),
  so the rule is "paint from one bulk file, detail from one per-asset fetch on
  click" plus a MUST to measure `Content-Encoding` when the bucket exists.
  Two opus adversarial reviewers reversed four parts of the draft first. Full
  decision, the layer/staleness table and the MUSTs:
  `.scratch/frontend/issues/01-one-surface-or-two.md`. Ticket 02 unblocked.

- 2026-08-24 · ticket 02 (prototype) RESOLVED — **Ross picked variation A, "Stack
  (one fill)"**, from three built against real payloads (`4ac3ebe`; asset
  `.scratch/frontend/prototypes/variant-A-chosen.png`, all three still runnable on
  branch `frontend02-four-layers`). **The colour collision dissolves rather than
  resolves: the delay layer and flood 17's impact overlay are the SAME quantity over
  the same ~1,200 H3 Cells at different time-scales**, so the Cell FILL channel is a
  radio — one fill, one frozen ramp, never two. Flood tiers are point layers and
  never contest it: aqua = FloodNet water now, amber = MTA station with water on the
  tracks, violet = flood record. An "affected station" marks the COMPLEX, not the
  chip. The record opens in a card that SHARES the right column with the layer panel
  (a floating card covered the freshness rows it came from). Freshness needs a FIFTH
  state, **AGE** — only 3 of the map's 9 sources have a budget frozen anywhere.
  Mobile: the panel set does NOT collapse at 375px; the 60vh MAP is what does not
  scale, so small screens open with the fill on and every point layer off. Ten
  measurements went forward as MUSTs on flood 15/17 and notify 05 (`e61a98d`).
  Full decision: `.scratch/frontend/issues/02-four-layers-prototype.md`.

## Not yet specified (fog)

- Embeds/sharing: whether any view is embeddable elsewhere once visibility
  changes (repo is private today; the host bucket is public-by-design).
- Auth/keys and abuse control for an API, if ticket 03 decides one exists.
- Schedule-vs-actual comparison as a visual layer ("current bus slowdowns or
  schedules" — the slowdown half exists as insight exports; the schedule half is
  fog until a concrete question can be phrased).
- ~~Mobile/small-screen treatment of a four-layer map.~~ **GRADUATED
  2026-08-24 by ticket 01 — folded into ticket 02 rather than given its own
  number: 02 already builds the throwaway variations, and small-screen is the
  same prototype at a different width. `web/app.css:69` already stacks the
  panels under a 60vh map at 900px; the concrete question 02 now owes is whether
  that survives SEVEN toggles and their freshness rows, or whether the panel set
  has to collapse.**

## Out of scope

- Alerting internals (notify 08/10/12 own them; this map may only decide what an
  external consumer READS).
- The showcase (orch 13 owns static Data Docs / DAG graph / walkthrough on the
  public host).
- Served history for the live tier (spec §9 bars it structurally — versioning
  stays OFF on the bucket).
- Repo front door / README (chartered separately: .scratch/repo-docs/issues/01).
