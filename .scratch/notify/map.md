# Wayfinder map: query + notify (the end state)

Label: `wayfinder:map`

## Destination

One full queryable dataset and two consumers on top of it. The dataset —
landed today: `silver/flood_events` (206 events / 248 event-days,
2010-2026), `silver/flood_obs` (52,014 observations), `silver/
asset_features` (15,490 point assets inside the 20,544-row registry),
`gold/cell_hour_speed` + baselines as impact evidence; unbuilt and gating
this map: `gold/flood_labels` (F05), `gold/flood_exposure` (F10) with
scores per **complex** and bus stop, and the detector (F11/F12). The
consumers: (a) a QUERY path — an agentic agent and the map frontend answer
"find historic flooding for any stop, complex, or area" and "how exposed
is this doorway" directly from the dataset; (b) a NOTIFY path — when the
live detector's tier for a Unit crosses into ELEVATED/HIGH during an
active rain window, people subscribed to that stop or complex hear about
it while the window is still open. Done when nothing is left to decide
before `/to-spec` / `/to-tickets`.

## Notes

- Hard predecessors, named: F05 -> F08/F09 -> F10 (exposure artifact),
  F11 (detector), F12 (replay gate), F15 (panel/export tick). Fifteen of
  eighteen flood-build tickets are unbuilt; this map plans the layer ABOVE
  them and ships nothing until they land. Sequencing: the remaining flood
  chain builds run as cluster Spark jobs (cloud map ticket 3's capacity),
  so the Mac's retirement does not depend on flood-build finishing, and
  vice versa.
- Upstream gates this map RESPECTS and never overrides: tiers ship only
  through F12's replay gate — "cutpoints confirmed, or v1 ships
  rank-only." A rank-only v1 launches the notify path in watch mode or
  holds it (ticket 6 decides with F12's outcome on the table); it never
  manufactures confidence the backtest refused. INSUFFICIENT_DATA never
  notifies. The winter gate suppresses as designed [F11, F14].
- **Cadence honesty (corrected in review):** the detector's forcing
  advances once per hour — MRMS RadarOnly `:00` stamps only (the 2-min
  trailing stamps are rejected inputs by contract [F11]), caught by a
  300 s tick, fresh to 90 min under F15's budget. So "imminent" means:
  a notification lands minutes after a new hourly stamp flips a tier,
  and the evidence behind it is hour-grain. The ~1-2 min end-to-end
  figure is the BUS live chain's, not the detector's. Claim language
  states the hour-grain window, never second-scale urgency.
- The no-alerting standing rule is restated in three places — the bus
  map's out-of-scope, the flood map (l.125), and the ready-for-agent
  flood spec (l.485). The flood map's recorded destination is a detector
  that FLAGS; warning subscribers is Ross's 2026-08-23 extension of that
  destination (this map). Ticket 5 is where he formally lifts the rule,
  and the lift must amend all three documents, not just the bus map.
- Query economics start static: the shipped insight surface measures
  ~2.6 MB on disk (`web/files/`: cells.geojson 2.3 MB + zones 257 KB +
  headline 48 KB [pipeline map decision 14]). A per-asset flood-history
  export over the 20,544-row registry at a few KB each is static-host
  territory; DuckDB-over-R2-parquet and any hosted query service are the
  escalation path, not the start. Measure before escalating.
- **License boundary (which tables may leave the box):** flood_events,
  flood_labels, exposure scores — yes. FloodNet-derived rows (2,927 in
  flood_obs; NYU/CUNY non-commercial agreement), MTA-derived alert rows,
  and subwaydata-derived impact numbers — local-page-only until a
  license says otherwise [flood map l.66, F13, F16, flood spec].
- The agentic consumer wants a tool, not a database login: a read-only
  MCP server over the dataset (local first, hosted only if a remote
  agent needs it) whose tools speak CONTEXT.md's vocabulary —
  events_for_asset(), exposure_of(), assets_in_area(), obs_near() —
  returning the same numbers the map shows, versioned against
  spine_version/score_version so an agent can cite which universe
  answered.
- Privacy/blast-radius stance: store the minimum (contact handle +
  asset ids + consent timestamp), never location history; unsubscribe in
  every message; no third-party analytics on the subscriber store.

## Tickets to cut

1. **Query surface v1 (static).** Per-asset flood-history export — reads
   `gold/flood_labels` (F05's frozen 100 m attachment) joined to
   `silver/flood_events` for windows, **never re-attaching flood_obs to
   ref/assets** (that join has one owner: F05); ships through `make
   export`'s batch path, NOT F15's 30 s live tick — the history changes
   only when the spine rebuilds, and its cadence is the spine's [build
   T13 pattern]; file layout (per-asset keys vs sharded files); size
   measured over the 20,544-row registry before any escalation.
2. **Area queries.** Cell is the area key; a Zone query resolves through
   the static Cell-to-Zone lookup at serving time and is never stored as
   a key [CONTEXT.md]; polygon-ad-hoc only via the MCP tool reading
   parquet locally — decide whether v1 needs it at all.
3. **The MCP tool layer.** Read-only server over R2/local parquet
   (DuckDB); tool vocabulary pinned to CONTEXT.md terms; versioned
   against spine_version/score_version; license boundary from Notes
   enforced at the tool layer (FloodNet/MTA-derived rows never leave);
   local-first, hosting deferred until a remote consumer exists.
4. **Subscription model and its ingress.** Subscriptions at asset_id
   grain, Unit kinds only — bus_stop and **complex** (a station resolves
   to its complex; stations are Carriers and carry no score [CONTEXT.md,
   F10]); signup on the map page requires a write path a static host
   cannot provide, so this ticket DECIDES THE INGRESS: one minimal
   subscribe/unsubscribe endpoint on the cluster (the single internet
   ingress cloud ticket 7 carves out) vs a hosted form/queue — either
   way email-verified handles, no accounts; storage one small table
   (SQLite/DuckDB) beside the notifier; subscription caps and abuse
   guard.
5. **Channel + policy decision (Ross's call, recorded here).** Formally
   lift the no-alerting rule for flood tiers only — amending the bus
   map, the flood map (l.125), AND the flood spec (l.485) — corrected
   to FIVE documents by the spec's Further Notes, and all five amended
   2026-08-23 by notify 01; choose
   channel(s) — email first (SES-class, cheap, unsubscribable);
   recommend against SMS v1 (cost + consent burden); quiet hours;
   per-event max-messages; claim language reuses F15's fixed strings
   EXCEPT the one a notification service falsifies — the storm-page
   claim, retired 2026-08-23 and replaced by the frozen operating-truth
   string quoted in full in the spec's section 7, which the flood spec's
   honesty clause now carries; message wording states the hour-grain
   evidence window.
6. **Trigger semantics.** Tier branch: notify on tier ENTRY only — the
   latch dedupes [F11]. Watch mode (rank-only v1): the rank is
   recomputed every cycle and has NO latch, so watch mode needs its own
   dedupe rule — one message per Unit per Window on first top-N entry —
   decided here with F12's outcome on the table; which tiers notify
   (HIGH always; ELEVATED per-subscription opt-in); test harness = the
   notify decision replayed over **F12's replayable subset** (AORC-era
   union events minus capped/INSUFFICIENT_DATA Windows — a subset of
   the 248 event-days, counted by F12 itself).
7. **End-to-end rehearsal.** One synthetic event + one replayed
   historical event (2023-09-29) driven through detector -> tier entry
   -> notification render -> unsubscribe, repeatable before any real
   subscriber exists.

## Review round 1 (2026-08-23, adversarial panel — corrections applied)

1. BLOCKER signup ingress: no map provided a write path (static host +
   no-inbound rule made signup impossible as written); ticket 4 now
   decides the ingress and cloud ticket 7 carves the exception.
2. BLOCKER F15 fixed string: the storm-page claim is falsified by a
   notifier — ticket 5 records its retirement + spec amendment;
   verbatim-reuse claim dropped. DONE 2026-08-23 (notify 01): retired
   everywhere, replaced by the frozen operating-truth string in the
   spec's section 7.
3. Cadence honesty: "~2-5 min precip / imminent means minutes" corrected
   to hourly `:00` forcing, <= 90 min freshness, hour-grain claims
   (Notes; tickets 5/6) — the minutes figure belongs to the bus chain.
4. No-alerting rule: attribution corrected (three documents, not one);
   "flood map's destination is warning people" dropped — warning is
   Ross's 2026-08-23 extension; ticket 5 amends all three docs.
5. "35 k assets" corrected to the 20,544-row registry (both places);
   "~2 MB insight surface" corrected to the measured ~2.6 MB with the
   right citation.
6. "per station" corrected to per complex everywhere (stations are
   Carriers, unscored [CONTEXT.md]); ticket 4's grain fixed to match.
7. Ticket 1 rebased onto gold/flood_labels + make export's batch path
   (was re-deriving F05's join inside F15's 30 s tick).
8. Zone demoted to serving-time lookup (never a key); winter-gate cite
   fixed to [F11, F14]; F12 fixture source corrected to its replayable
   subset; landed-vs-unbuilt inventory split in the destination; license
   boundary added; flood-chain-vs-cloud sequencing stated.

## Out of scope

- Public write APIs beyond the single subscribe/unsubscribe ingress
  ticket 4 defines; user accounts; OAuth.
- Non-flood notifications (bus delay alerts etc.) — different
  validation, different map if ever.
- SMS in v1; paid tiers; mobile apps.
- Any claim stronger than the shipped model's validation (F09/F12
  discipline carries through verbatim).
