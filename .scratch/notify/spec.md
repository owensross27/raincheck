# raincheck query + notify: build spec

Status: ready-for-agent
Source: wayfinder map `.scratch/notify/map.md` (7 tickets to cut, review round 1
applied). Written 2026-08-23. Vocabulary is CONTEXT.md's — **Unit** (a scored
asset: complex, bus_stop, Cell), **Carrier** (station/entrance: located and
aggregated, never scored), **Cell** (H3 r8, the spatial key), **Zone**
(presentation overlay reached through the static Cell-to-Zone lookup at serving
time, never a key), **Hour** (hour-ending UTC), **Precip source**. ADR-0002 is
binding wherever MRMS is touched. Cross-effort boundaries: the flood model chain
(F05, F10, F11, F12, F15) belongs to `.scratch/flood-build/`; the cluster
platform and its network rules to `.scratch/cloud/`; the DAG to
`.scratch/orchestration/`. This spec owns **the two consumers on top of the
dataset** and nothing underneath them.

Three forks the map left open were closed with Ross on 2026-08-23 before this
spec was written, and every one of them shrank the build:

- **Seams**: three, two of them existing repo seams. Marked **SEAM Q / N / S**.
- **Ingress**: DEFERRED. v1 has no public write path at all (section 4).
- **Runtime**: the notifier rides the existing 30 s export loop. No new daemon,
  so no new HITL gate (section 6).

Two places this spec CORRECTS the map rather than extending it; both are in
Further Notes.

## Problem Statement

The flood dataset is about to be complete and nobody can ask it anything.
`silver/flood_events` (206 events over 248 event-days, 2010-2026),
`silver/flood_obs` (52,014 observations), `silver/asset_features` (15,490 point
assets inside the 20,544-row `ref/assets` registry) and the Gold speed evidence
have all landed, and the only way to consume any of it is to open DuckDB and
write a join by hand. Ross can do that. Nobody else can, no agent can, and the
map page can only show what the batch exporter happened to pre-compute into
three citywide files.

Two specific things are impossible today:

1. **"Has this stop ever flooded?"** A viewer standing at a bus stop, or a
   presenter being asked about one complex, cannot get an answer. The data to
   answer it exists — `gold/flood_labels` attaches observations to assets under
   one frozen 100 m rule, `silver/flood_events` dates the windows — but there is
   no per-asset artifact, no area query, and no tool an agent can call. An
   agentic consumer's only options are a database login it should not have, or
   inventing SQL against tables whose vocabulary and version stamps it cannot
   see.
2. **Hearing about a flood while it is still happening.** The detector (F11)
   computes a tier per Unit every cycle and the panel (F15) shows it — to
   whoever happens to have the page open. That is a page you must remember to
   open during a storm. Someone who cares about one bus stop or one complex has
   no way to be told that its tier crossed into ELEVATED or HIGH while the rain
   window is still open, which is the only time the information is worth
   anything.

Both consumers also have a constraint the current code has nowhere to put: some
of this data may not leave the box. FloodNet rows (2,927 of `flood_obs`, under a
non-commercial NYU/CUNY agreement), MTA-derived alert rows, and
subwaydata-derived impact numbers are local-page-only until a license says
otherwise. Today that boundary lives in prose in a spec. The moment a query tool
or a static export exists, it has to live in code, in one place, or it will be
crossed by accident.

## Solution

One query function with three consumers, and one notify decision with one
channel.

**The query path.** A single read-only function — `query(name, params, ...)` —
answers four questions in CONTEXT.md's own vocabulary: `events_for_asset`,
`exposure_of`, `assets_in_area`, `obs_near`. Every consumer is a thin renderer
over that one function: the static per-asset flood-history export is it,
batch-run through `make export` and written to `web/files/`; the MCP tool layer
is it, exposed over stdio to an agent; the map page reads the files the batch
run wrote. The license boundary is a parameter of that one function, so there is
exactly one place where "may this row leave the box" is decided, and one test
that proves it. Every payload carries the version stamps of the universe that
answered it, so an agent can cite which spine and which score it read.

**The notify path.** When the detector's tier for a subscribed Unit crosses into
ELEVATED or HIGH during an active rain window, subscribers to that Unit get one
email while the window is still open. The decision to send is a pure function of
(current evaluation, previous evaluation, subscriptions, policy, clock) — no
network, no I/O — which means it can be replayed over F12's replayable subset
before it ever faces a real storm, and tested exhaustively on fixtures. It runs
inside the export loop that already computes the detector tick, so nothing new
is standing up and nothing new is being approved. v1 sends to a list Ross
maintains by hand: no signup endpoint, no internet ingress, no abuse surface, no
account system.

Both paths are honest about the same thing: the detector's forcing advances once
per hour (MRMS RadarOnly `:00` stamps only), caught by a 300 s tick, fresh to
90 min under F15's budget. A notification lands minutes after a new hourly stamp
flips a tier, and the evidence behind it is hour-grain. No message ever implies
second-scale urgency, and no message claims water was seen — the estimand is
`flooded_reported` in the notification exactly as it is on the panel.

## User Stories

Analyst = Ross doing the analysis; presenter = Ross showing the page; viewer =
anyone the page is shown to; agent = an agentic consumer holding the MCP tools;
subscriber = someone on the notify list; operator = Ross running the list and
the notifier; implementer = the agent building a slice.

### The query surface

1. As a viewer, I want to ask whether one bus stop has ever flooded, so that I
   can judge a route I actually use.
2. As a viewer, I want the dated windows of every flood event attached to that
   stop, so that "it flooded" comes with when.
3. As a viewer, I want the same answer for a subway complex, so that the station
   entrance I use is answerable the same way the stop is.
4. As a viewer, I want a complex's answer to be the max over its child
   entrances, so that a complex is not called dry because the one entrance I did
   not use stayed dry.
5. As a viewer, I want an asset with no flood history to say "no events on
   record" rather than returning nothing, so that absence is legible as absence
   and not as a broken page.
6. As a presenter, I want the per-asset answer to state which sources saw the
   flooding, so that a question about credibility has an answer on the screen.
7. As a presenter, I want every answer stamped with the spine and score versions
   that produced it, so that a number quoted today can be reproduced later.
8. As an analyst, I want the per-asset history to read `gold/flood_labels`
   joined to `silver/flood_events`, never re-attaching `flood_obs` to
   `ref/assets`, so that the 100 m attachment rule has exactly one owner (F05)
   and cannot drift between the map and the model.
9. As an analyst, I want the history export to ship on the spine's cadence
   through `make export`'s batch path, not on the 30 s live tick, so that a file
   that only changes when the spine rebuilds is not rewritten 2,880 times a day.
10. As an analyst, I want the exporter to print the measured size of what it
    wrote over the registry, so that "is this static-host territory" is answered
    by a number and not by a guess.
11. As a viewer, I want to ask what flooded inside an area, so that a
    neighbourhood question does not require knowing an asset id.
12. As an analyst, I want Cell to be the area key and Zone to resolve through
    the static Cell-to-Zone lookup at serving time, so that the presentation
    overlay never becomes a stored key.
13. As an agent, I want tools rather than a database login, so that I can answer
    questions about this dataset without holding credentials or inventing SQL.
14. As an agent, I want the tool names and their arguments to be CONTEXT.md's
    terms, so that the vocabulary I answer in is the project's vocabulary.
15. As an agent, I want every tool response to carry the version stamps, so that
    I can cite which universe answered and detect when it moved.
16. As an agent, I want a tool that reports which asset kinds are scored Units
    and which are Carriers, so that I do not ask a station for a score it does
    not have.
17. As an agent, I want tool errors to name the reason (unknown asset, area too
    large, restricted source), so that I can recover rather than retry blindly.
18. As Ross, I want the MCP server to run locally against local parquet first,
    so that hosting is a decision I make when a remote consumer exists, not a
    thing I built speculatively.
19. As Ross, I want FloodNet-derived, MTA-derived and subwaydata-derived rows to
    be incapable of leaving the box through any exported file, so that a
    non-commercial licence is honoured by construction and not by memory.
20. As Ross, I want the local MCP server to be able to see those rows while the
    public export cannot, so that the licence boundary constrains distribution
    rather than my own analysis.
21. As an implementer, I want one query function behind the export and the MCP
    tools, so that fixing an answer fixes it in both places.

### The notify path

22. As a subscriber, I want to be told when a stop I care about crosses into a
    high flood tier, so that I hear about it while the storm is still on.
23. As a subscriber, I want that message to arrive minutes after the hourly rain
    stamp that caused it, so that it is timely by the standard the data can
    actually support.
24. As a subscriber, I want the message to state the hour-grain evidence window,
    so that I am not misled into treating it as a second-by-second warning.
25. As a subscriber, I want the message to say plainly that it ranks where a
    flood REPORT is likely, not where water is, so that the claim matches the
    estimand.
26. As a subscriber, I want one message per Unit per tier entry, so that a
    storm that flickers does not fill my inbox.
27. As a subscriber, I want to opt in to ELEVATED separately from HIGH, so that
    I can choose how loud my subscription is.
28. As a subscriber, I want quiet hours honoured for ELEVATED, so that a
    non-urgent tier does not wake me.
29. As a subscriber, I want HIGH to reach me regardless of quiet hours, so that
    the one tier worth waking for is not suppressed by a preference.
30. As a subscriber, I want a hard cap on how many messages one event can send
    me, so that a long storm cannot become a flood of mail.
31. As a subscriber, I want every message to carry an unsubscribe instruction
    that works, so that leaving is as easy as joining.
32. As a subscriber, I want my stored record to be a contact handle, the asset
    ids I asked for, and when I consented — nothing else, and never location
    history — so that subscribing costs me the minimum.
33. As a subscriber, I want no third-party analytics on the message or the
    store, so that being on this list is not a tracking event.
34. As a subscriber, I want an INSUFFICIENT_DATA state to send nothing, so that
    silence means "we do not know" and not "we know it is fine".
35. As a subscriber, I want the winter gate's suppression to hold for
    notifications exactly as it holds for the panel, so that a frozen hour does
    not generate a rain alert.
36. As Ross, I want to formally lift the no-alerting standing rule for flood
    tiers only, amending every document that records it, so that the rule's
    lift is auditable and non-flood alerting stays barred.
37. As Ross, I want the F15 claim string that a notifier falsifies to be retired
    and replaced everywhere it appears, so that the page and the message do not
    contradict each other.
38. As Ross, I want email as the only v1 channel, so that consent and cost stay
    small and unsubscribe is a solved problem.
39. As Ross, I want SMS explicitly rejected for v1, so that nobody builds it by
    default.
40. As Ross, I want the notifier to run inside the existing export loop, so that
    it introduces no new standing process and reopens no HITL gate.
41. As Ross, I want a send failure to be logged and skipped, never to stall the
    panel's cycle, so that the mail path cannot take down the map.
42. As Ross, I want the notifier to default to dry-run, so that arming it is a
    deliberate act and every rehearsal is safe by construction.
43. As Ross, I want a missing credential to make the notifier do nothing and say
    so, so that it fails closed rather than half-sending.
44. As an operator, I want the subscriber list to be a small table I edit through
    one command, so that v1 needs no public write path.
45. As an operator, I want an unsubscribe request to be processable without an
    HTTP endpoint, so that leaving works even though joining is manual.
46. As an operator, I want a named trigger that says when the manual list stops
    being enough, so that deferring the ingress is a decision with an expiry and
    not an omission.
47. As an analyst, I want the notify decision to be a pure function of its
    inputs and an injected clock, so that quiet hours, caps and dedupe are
    testable without waiting for a Tuesday at 3am.
48. As an analyst, I want the decision replayed over F12's replayable subset
    before launch, so that the message volume a real storm would produce is
    measured rather than discovered.
49. As an analyst, I want the replay to publish per-event message counts by kind
    as a build asset, so that "this would have sent 400 emails" is caught by a
    number on disk.
50. As an analyst, I want tier ENTRY to be the trigger and the F11 latch to be
    the dedupe, so that the notifier does not reimplement state the detector
    already holds.
51. As an analyst, I want watch mode (the rank-only branch) to carry its own
    dedupe rule — one message per Unit per Window on first top-N entry — so that
    an unlatched rank cannot notify every cycle.
52. As an analyst, I want the choice between tiers and watch mode to be made with
    F12's outcome on the table, so that v1 never manufactures confidence the
    backtest refused.
53. As an analyst, I want version skew between the coefficient and constants
    artifacts to refuse the notification exactly as it refuses the model tier,
    so that a mid-storm artifact swap cannot mail a stale universe.
54. As Ross, I want one synthetic event and one replayed historical event
    (2023-09-29) driven end to end — detector to tier entry to rendered message
    to unsubscribe — repeatable before any real subscriber exists, so that the
    first real storm is not the rehearsal.
55. As an implementer, I want the rehearsal to be a make target, so that
    re-running it after any change costs one command.

## Implementation Decisions

Each numbered section closes one map ticket. A decision marked **DEFAULT**
carries the rule that would overturn it.

### 1. The query function: one entry point, three consumers (map ticket 1, 3)

- **SEAM Q.** One module in `src/raincheck/` owns every read: a single entry
  point taking a query name, a params dict, a data root and a boundary mode, and
  returning a JSON-able dict. Nothing else in the codebase reads the flood
  tables for serving. The static export and the MCP server are both renderers
  over it, and they are the only two renderers v1 has.
- **Four query names, CONTEXT.md vocabulary, no others in v1:**
  `events_for_asset` (one Unit's dated flood history), `exposure_of` (one Unit's
  scores from `gold/flood_exposure`), `assets_in_area` (Units inside a Cell set
  or a Cell-snapped bbox), `obs_near` (observations within a radius of a point,
  local boundary only — see 3).
- **No SQL passthrough tool, ever.** A generic "run this SQL" tool defeats the
  licence boundary, the version stamping and the attachment-ownership rule in
  one move. If an answer needs a fifth shape, it becomes a fifth named query.
- **Source of truth for history:** `gold/flood_labels` (F05's frozen 100 m
  attachment, positives only) joined to `silver/flood_events` for the windows.
  The function NEVER re-attaches `flood_obs` to `ref/assets` — that join has one
  owner and it is F05. `obs_near` reads `flood_obs` directly by geometry, which
  is a different question (what was observed near here) and is not an
  attachment.
- **Complex grain:** a complex's history and score are the aggregate over its
  child entrances (max, matching F10's rule). Stations are **Carriers** and
  carry no score; asking `exposure_of` for a station returns a typed error
  naming the complex to ask instead.
- **Version stamps on every payload:** `assets_version` (from `ref.assets_version`),
  the spine's version, `label_version`, and `score_version` / `model_id` where a
  score is returned. A payload whose stamps cannot be resolved is an error, not
  an unstamped answer.
- **Absent, never null.** The repo's pure-SQL JSON convention carries through
  verbatim: an unpublishable value is an ABSENT KEY. An asset with no flood
  history returns a payload with an explicit empty event list and a stated
  reason, which is not the same thing as an absent key and must not be conflated
  with one.
- **Engine:** DuckDB over the parquet roots, through the existing `duck.connect`
  / `duck.table` helpers (UTC session, `union_by_name`, hive types as strings).
  No Spark on the read path; no new engine.

### 2. The licence boundary, enforced in one place (map ticket 3)

- The boundary is a **mode parameter of the query function**, not a property of
  its callers: `public` (default) and `local`. Every caller states its mode; the
  default is the restrictive one, so a new caller that forgets is safe.
- **`public` may return:** `flood_events` rows, `flood_labels` attachments,
  `flood_exposure` scores and index, asset identity and geometry from
  `ref/assets`, and per-source **counts** of the observations behind an event.
- **`public` may NOT return:** any FloodNet-derived row or depth (2,927 rows in
  `flood_obs`, NYU/CUNY non-commercial), any MTA-derived alert row or its prose,
  any subwaydata-derived impact number. These are local-page-only until a
  licence says otherwise [flood map l.66, F13, F16, flood spec].
- **Counts are not rows.** "3 FloodNet detections during this event" is a count
  and ships; the detection rows, their depths and their sensor ids do not. If
  the count itself later proves to be a licence problem, the mode gains a third
  level rather than the callers gaining a special case.
- `obs_near` is **`local`-only in v1** — it returns observation rows by
  definition. The public export never calls it. **DEFAULT**; overturned only by
  a licence change, and if it is ever made public it must filter to the
  permitted sources inside the same one function.
- The static export runs `public`. The MCP server defaults to `public` and takes
  an explicit local flag; a hosted MCP server (if it ever exists) may not set
  it.

### 3. The static query surface (map ticket 1)

- **Ships through `make export`'s batch path**, alongside the three existing
  insight files, on the spine's cadence — NOT F15's 30 s live tick. The history
  changes only when the spine rebuilds [build T13 pattern].
- **Layout: a manifest plus per-asset files, emitted only for assets with
  history.** The manifest is one file listing every asset id that has at least
  one attached event (with its kind and its event count); the page and the tools
  read the manifest to know whether to fetch, and an asset absent from the
  manifest is rendered as "no events on record" without a request. **DEFAULT**;
  overturned by the measurement in the next bullet — if per-asset files land
  under a few thousand and the manifest is small, this is right; if the file
  count is unwieldy for the static host's sync, shard by asset kind and H3
  prefix instead, which is a change to this renderer alone and touches no query.
- **Measure before escalating.** The exporter prints the file count, the total
  bytes and the largest single file, in the style of `export.report`. Today's
  shipped insight surface measures 2,606,072 bytes across three files
  (cells.geojson 2,300,263 + zones.geojson 257,488 + headline.json 48,321,
  measured 2026-08-23). If the history surface lands in that order of magnitude
  it is static-host territory and the decision is closed. DuckDB-over-R2-parquet
  and any hosted query service are the escalation path, not the start, and no
  ticket may take that path without the printed number.
- **Byte-identical re-export**, matching the existing export contract: every
  aggregate ordered, every number explicitly rounded, staged writes replaced
  atomically, all files or none.
- The export is a renderer: it calls the query function once per asset in the
  manifest and writes what comes back. It contains no joins of its own.

### 4. Area queries (map ticket 2)

- **Cell is the area key.** `assets_in_area` takes Cell ids, or a bbox that is
  resolved to a Cell set before anything is read.
- **Zone is resolved at serving time** through the static Cell-to-Zone lookup and
  is never stored as a key, never a parameter alias for a stored column
  [CONTEXT.md].
- **Arbitrary polygons are NOT in v1.** The map asked whether v1 needs them; it
  does not. An agent with a polygon can resolve it to Cells itself, and the
  spatial join for an ad-hoc polygon is a local-only DuckDB spatial query that
  no shipped consumer has asked for. **DEFAULT**; overturned by a named consumer
  that has a polygon and cannot resolve it — at which point it is a fifth query
  name, `local`-first, not a generic geometry parameter on the existing four.
- **Area queries are bounded.** A request resolving to more Cells than a stated
  cap returns a typed `area_too_large` error naming the cap, so a tool call
  cannot accidentally ask for the city.

### 5. The MCP tool layer (map ticket 3)

- **Read-only stdio server, local-first**, exposing exactly the four query names
  as tools with the same argument names the query function takes. Hosting is
  deferred until a remote agent exists; nothing in v1 opens a port.
- **The server is a wrapper and nothing else**: argument validation, mode
  selection, call, return. No query logic lives in it, which is why the tests
  live at seam Q and not at the protocol.
- **Dependency:** the official MCP Python SDK, pinned in `pyproject.toml`. This
  is the one new dependency this spec adds. Hand-rolling JSON-RPC framing and
  capability negotiation to save a dependency is a bad trade, and because the
  server is a thin wrapper the SDK can be swapped without touching a query.
- **Tool descriptions state the universe**: each tool's description names the
  tables it reads and the version stamps it returns, so an agent choosing
  between tools has the vocabulary in front of it.
- **Errors are typed and named** — `unknown_asset`, `not_a_scored_unit`,
  `area_too_large`, `restricted_source`, `version_unresolved` — never bare
  tracebacks, so an agent can recover.

### 6. Trigger semantics: the notify decision (map ticket 6)

- **SEAM N.** One pure function: given the current evaluation (per Unit: tier,
  rank, Window id, flags, the version stamps), the previous evaluation, the
  subscriptions, the policy constants and an injected `now`, it returns a list
  of Messages. No network, no clock read, no file read, no send.
- **Tier branch: notify on tier ENTRY only.** The F11 latch is the dedupe; the
  notifier does not reimplement it. Entry means the Unit's latched tier moved up
  into a notifying tier since the previous evaluation. A tier that holds sends
  nothing further.
- **Watch mode (the rank-only branch) has its own dedupe:** the rank is
  recomputed every cycle and has NO latch, so the rule is **one message per Unit
  per Window on first top-N entry**, keyed on (unit, window_id). The Window id
  is the dedupe key precisely because the rank is not stateful.
- **Which tiers notify:** HIGH always; ELEVATED per-subscription opt-in.
  INSUFFICIENT_DATA never notifies — silence means "we do not know". The winter
  gate suppresses notifications exactly as it suppresses the panel [F11, F14].
- **Version skew refuses the notification.** F15 already refuses the model tier
  when the coefficient and constants digests disagree; a refused tier cannot
  notify, and a coefficient swap mid-Window forces a Window roll, which resets
  the watch-mode dedupe key by construction.
- **Which branch ships is decided with F12's outcome on the table.** If F12
  confirms the cutpoints, v1 notifies on tiers. If F12 drops v1 to rank-only,
  the notify path launches in watch mode or holds — and holding is an acceptable
  answer. It never manufactures confidence the backtest refused.
- **Caps and quiet hours are policy constants in one frozen artifact**, not
  scattered literals: notifying tiers, top-N for watch mode, quiet-hour window
  and timezone, per-subscriber-per-event message cap, and a global per-cycle
  send cap as a blast-radius fuse. Quiet hours suppress ELEVATED and are DROPPED
  rather than deferred (an hour-grain alert delivered hours late is worse than
  no alert); HIGH always sends. **DEFAULT** on the drop-vs-defer choice;
  overturned only by a subscriber who asks for a digest, which is a different
  feature.
- **Test harness = the decision replayed over F12's replayable subset** —
  AORC-era union events minus capped and INSUFFICIENT_DATA Windows, a subset of
  the 248 event-days counted by F12 itself. The replay publishes per-event
  message counts by kind as a build asset (see Testing Decisions).

### 7. Channel, policy, and lifting the standing rule (map ticket 5)

- **The rule lift is explicit and scoped:** the no-alerting standing rule is
  lifted **for flood tiers only**. Non-flood notifications (bus delay and
  everything else) remain barred and stay out of scope.
- **The lift must amend every document that records the rule.** The map said
  three; the measured count is **five distinct documents** (see Further Notes).
  Each gets the same amendment: the rule now reads as barred except for flood
  tiers under this spec, with a pointer here.
- **The falsified claim string is retired everywhere.** "a page you open during
  a storm, not a service that watches" is false the moment a notifier exists. It
  appears **six times across two files** (measured; see Further Notes) — in each
  spec's destination bullet, its fixed-strings list, and its honesty clause. All
  six are replaced by a string that survives a notifier and keeps the honesty
  the original carried: the page and the message both rank where a flood REPORT
  is likely, on hour-grain evidence that trails the storm, and neither observes
  water. The replacement text is frozen in the same constants artifact as the
  other claim strings and is asserted by test, exactly as F15's strings are.
- **Every other F15 fixed string is reused verbatim** — the reporting-propensity
  sentence, the estimand name, the Window in the tier label, the degraded-state
  strings, the B2-branch alternates selected by the shipped model id. The
  message is not allowed its own vocabulary.
- **Channel: email only in v1** (SES-class transactional sending). **SMS is
  rejected for v1** on cost and consent burden. No push, no webhooks.
- **Message content, fixed:** the Unit's name and kind, the tier entered, the
  Window, the hour-grain evidence statement, the estimand sentence, a link to
  the panel, and the unsubscribe instruction. The message states the evidence
  window in hours and never implies second-scale urgency; the ~1-2 min
  end-to-end figure belongs to the bus live chain and may not appear.
- **Sending rides the export loop** (section 8) with a hard timeout per send,
  matching F15's fetch discipline. Failures are logged to the flood NDJSON log
  and skipped; a mail failure never stalls a cycle and never blocks the panel.
- **Dry-run is the default.** The notifier renders messages and logs them
  without sending unless explicitly armed. Missing credentials means it does
  nothing and says so — fail closed, never half-send.
- **Privacy stance, binding:** the store holds a contact handle, the asset ids
  subscribed, the tier opt-in, and a consent timestamp. No location history, no
  IP logging, no third-party analytics in the message or on the store. An
  unsubscribe deletes the rows.

### 8. Runtime placement: no new daemon (Ross's decision, 2026-08-23)

- The notify decision and the send run **inside the existing 30 s export loop**,
  in the same tick that already computes the detector state (F15). The loop's
  existing rules bind the notifier: cycles cannot overlap, every outbound call
  has a hard timeout, one hung socket never stalls the bus panel, one cycle id
  spans the set.
- **No new standing process is created, so no new HITL gate opens.** The flood
  spec's rule stands: any new capture poller or standing process reopens the
  gate by rule, and this spec deliberately avoids one.
- The notifier's state is small and lives beside the loop: last-notified keys
  per (unit, window) for watch mode, and the loop's own tier state for the
  latched branch. It survives a restart by being persisted with the loop's other
  state, and a lost state file degrades to "may re-send once per Window", never
  to "sends every cycle" — the Window key bounds the failure.
- When the cluster lands, this moves as part of the live-export/detector
  Deployment that `.scratch/cloud/` ticket 5 already owns. It is not a separate
  workload there either.

### 9. Subscriptions and their (deferred) ingress (map ticket 4)

- **SEAM S.** One small SQLite table beside the notifier: contact handle, asset
  id, asset kind, tier opt-in, consent timestamp, unsubscribe token, state.
  Subscriptions are at **asset_id grain, Unit kinds only — `bus_stop` and
  `complex`**. A station resolves to its complex before storage; Cells are not
  subscribable in v1 (nobody subscribes to a hexagon).
- **The public ingress is DEFERRED.** v1 has no HTTP write path of any kind. The
  list is maintained by the operator through one command (add, remove, list),
  and the map page's flood section links to that fact rather than to a signup
  form. This removes the internet-ingress exception, the email-verification
  flow, the abuse guard and the rate limiting from v1 entirely.
- **Cloud ticket 7's reserved exception therefore stays unused.** No
  NetworkPolicy exception is opened, and `.scratch/cloud/`'s reservation remains
  a reservation. That reservation does not expire — it is simply not drawn on.
- **Named trigger for building the endpoint** (so the deferral has an expiry):
  the first person who is neither Ross nor an invited tester asks to subscribe,
  OR the managed list passes 25 entries, OR the map page is publicly announced.
  Any one of those reopens the ingress as its own ticket, and it lands with the
  map's original requirements intact — email-verified handles, no accounts, one
  minimal endpoint, caps and abuse guard.
- **Unsubscribe works without an endpoint.** Every message carries an opaque
  per-subscriber unsubscribe token in a `List-Unsubscribe` mailto header and in
  the body. A token presented to the operator command removes the rows; the
  handler that verifies the token and deletes is a function, tested directly
  (seam S), and is the same handler an HTTP endpoint would call if one is ever
  built. The message states the processing expectation honestly rather than
  implying instant one-click removal.
- **Caps even on a managed list:** a stated maximum subscriptions per handle, so
  the per-cycle fuse in section 6 has a bounded worst case.

### 10. The end-to-end rehearsal (map ticket 7)

- One make target drives: fixture detector state -> tier entry -> notify decision
  -> message render -> (dry-run) send -> unsubscribe token -> store empty.
  Repeatable, no real subscriber, no network.
- **Two events:** one synthetic event constructed to trip every branch (entry,
  hold, INSUFFICIENT_DATA, winter gate, quiet hours, cap), and the real
  2023-09-29 event replayed through the detector's own walk.
- The rehearsal asserts the message COUNT and the rendered strings, not the mail
  transport. Transport is exercised once by hand when the notifier is first
  armed, and that is a HITL step, not a test.

## Testing Decisions

A good test asserts external behavior at a seam — a written file read back from
disk, a payload returned by a function, a store read back with SQL — never
implementation internals. Fixtures with known answers beat synthetic data. This
spec adds no new seam pattern to the repo: seams Q and N are the existing
written-artifact and pure-function seams, and S is a handler called directly.

### SEAM Q — the query function and its two renderers

Prior art: `tests/test_export.py` (a temp data root seeded with a fixture Gold,
files read back as JSON, byte-identical re-export) and `tests/test_flood.py`
(fixture snapshots cut from the real sources, keeping their real quirks).

- Payload contracts: `events_for_asset` on a fixture asset with known events
  returns those events with their windows; on an asset with none it returns an
  explicit empty list with a reason; on an unknown id it raises the typed error.
- Complex aggregation: a fixture complex whose entrances disagree returns the
  max, and a station returns `not_a_scored_unit` naming its complex.
- Attachment ownership: the fixture is built so that a wrong join (flood_obs to
  ref/assets instead of flood_labels) returns a DIFFERENT and detectable answer.
  A test that both joins would pass proves nothing.
- Version stamps present on every payload; a fixture with an unresolvable stamp
  raises rather than returning an unstamped answer.
- **Licence boundary, non-vacuously:** the fixture MUST contain FloodNet,
  MTA-alert and subwaydata-derived rows that the local mode returns and the
  public mode does not. A boundary test over a fixture with no restricted rows
  passes for the wrong reason — the failure mode recorded in
  `stub-fidelity-over-convenience`.
- Export renderer: files parsed from disk, manifest matches the emitted files,
  no null values anywhere (absent keys only), re-export byte-identical, and the
  size report printed.
- Area queries: Zone resolves through the lookup at serving time and appears in
  no key; an over-large area returns `area_too_large`.
- The MCP server is NOT tested at the protocol level. Its tools are asserted to
  dispatch to the four query names with the arguments they received, and that is
  all — the SDK is not ours to test.

### SEAM N — the notify decision

Prior art: `tests/test_flood.py`'s pure-function tests; the discipline is F11's
(pure functions, fixtures, no network, no live table).

- Clock is injected. Quiet hours, Window boundaries and staleness are pinned on
  a **fixed epoch**, never on wall clock — the failure recorded in
  `fixture-clock-equals-wall-clock`.
- Branch coverage as behavior: entry fires once; a held tier fires nothing; exit
  then re-entry fires again; watch mode fires once per (unit, window) and not
  per cycle; a Window roll re-arms it; ELEVATED without opt-in is silent; HIGH
  in quiet hours sends; ELEVATED in quiet hours drops; INSUFFICIENT_DATA is
  silent; the winter gate is silent; version skew is silent.
- Caps: per-subscriber-per-event and the global per-cycle fuse both assert the
  count, and the fuse asserts what it dropped is logged.
- Rendered strings: the F15 strings appear verbatim, the retired string appears
  NOWHERE (asserted by absence across the rendered corpus), and the hour-grain
  evidence sentence is present in every message.
- **Contract tests are mutation-checked**: each assertion is confirmed to fail
  when the rule it pins is inverted. A green suite that stays green under a
  broken rule is the failure mode this repo has already been bitten by.
- **Replay is build-asset evidence, not pytest** — following F09/F12's
  precedent. The replay over F12's replayable subset publishes per-event message
  counts by kind and by tier as a build asset; the pytest suite asserts the
  replay RUNS and its output shape, while the volume numbers are read by a human
  before the notifier is armed.

### SEAM S — the store and unsubscribe handler

Prior art: `tests/test_cloud_scripts.py` (scripts asserted without standing up
infrastructure).

- Round trip: add -> the decision sees the subscription -> unsubscribe token
  verifies -> rows gone, asserted by reading the store back with SQL.
- A bad or reused token changes nothing and returns the typed refusal.
- Cap enforcement: a handle past the maximum is refused at add time.
- Stored columns are exactly the permitted set — a test asserts the schema has
  no column outside it, so the privacy stance is enforced by the schema and not
  by review.

### What is deliberately not tested

Mail transport (a HITL step at arming), the MCP SDK's protocol, and the static
host's sync behavior. Each is stated here so its absence is a decision rather
than a gap.

## Out of Scope

- **Any public write path in v1** — no signup endpoint, no hosted form, no
  queue. Deferred with the named trigger in section 9. Cloud ticket 7's reserved
  ingress exception stays undrawn.
- **User accounts, OAuth, sessions, profiles.** A subscription is a handle and
  a list of asset ids.
- **SMS, push, webhooks, digests, paid tiers, mobile apps.**
- **Non-flood notifications** (bus delay and everything else). The rule lift in
  section 7 is scoped to flood tiers; everything else stays barred and would
  need its own validation and its own map.
- **A hosted MCP server** and any hosted query service. Local-first; hosting is
  reopened by a remote consumer existing.
- **DuckDB-over-R2-parquet serving and any query API.** The escalation path, not
  the start, and not takeable without the printed size measurement.
- **Arbitrary-polygon area queries** in v1 (section 4).
- **A SQL-passthrough tool** — permanently out, not deferred.
- **Cell subscriptions**, and subscriptions at Carrier grain.
- **Changing anything upstream.** F05's attachment rule, F10's exposure object,
  F11's latch and winter gate, F12's replay verdict and F15's tick and claim
  strings are inputs. This spec reads them; it does not amend them, with the
  single exception of the retired claim string in section 7, which F15's own
  fixed-string list must be edited to match.
- **Any claim stronger than the shipped model's validation.** F09/F12 discipline
  carries through verbatim into every message.
- **Building anything before its predecessor lands.** See Further Notes.

## Further Notes

**Two corrections to the map.** Both were measured on 2026-08-23, not reasoned.

1. *The no-alerting rule lives in five documents, not three.* The map's ticket 5
   says the lift must amend "the bus map, the flood map (l.125), AND the flood
   spec (l.485)". Grepping every effort directory finds the standing rule
   recorded in: `.scratch/pipeline/map.md:134`, `.scratch/pipeline/spec.md:706`
   (which `.scratch/build/spec.md` symlinks to, so it is one document, not two),
   `.scratch/flood/map.md:125`, `.scratch/flood/spec.md:485`, and
   `.scratch/flood-build/spec.md:495` — the last being a diverged copy of the
   flood spec that the map's count missed entirely. Amending three of five
   leaves the rule contradicting itself in two live documents.
2. *The falsified claim string appears six times across two files, not once.*
   "a page you open during a storm, not a service that watches" occurs in
   `.scratch/flood/spec.md` at lines 56, 412 and 541-542, and in
   `.scratch/flood-build/spec.md` at lines 56, 422 and 551-552 — the destination
   bullet, the fixed-strings list and the honesty clause of each. Line numbers
   are as of 2026-08-23 and will drift; the string is the key, not the line.

**Hard predecessors.** This spec ships nothing until the flood chain lands:
F05 (`gold/flood_labels`) gates every query; F10 (`gold/flood_exposure`) gates
`exposure_of`; F11 (detector core) gates the notify decision's inputs; F12
(replay harness) gates whether v1 notifies on tiers or in watch mode, or holds;
F15 (panel and export tick) gates the runtime the notifier rides in. Fifteen of
eighteen flood-build tickets are unbuilt. The query path (sections 1-5) is
buildable as soon as F05 and F10 land and does not wait for the detector; the
notify path (sections 6-10) waits for F11/F12/F15. `/to-tickets` should slice
along that line: query first, notify second.

**Sequencing against the cluster.** The remaining flood-chain builds run as
cluster Spark jobs under `.scratch/cloud/` ticket 3's capacity, so neither
effort blocks the other. Nothing in this spec requires the cluster; the static
export runs wherever `make export` runs, and the MCP server runs on the Mac.

**Why the ingress deferral is not a narrowing.** The map framed ticket 4 as
"DECIDE THE INGRESS", and "not yet, here is the trigger" is one of its valid
answers. It removes the only piece of this effort that needed a new internet
port, a verification flow and an abuse guard — and it removes them from the
critical path of a feature whose first subscriber is Ross. The endpoint's
requirements are preserved verbatim in section 9 so that building it later is a
lookup, not a redesign.

**What "imminent" is allowed to mean.** The detector's forcing advances once per
hour on MRMS RadarOnly `:00` stamps (the 2-min trailing stamps are rejected
inputs by contract [F11]), caught by a 300 s tick, fresh to 90 min under F15's
budget. So a notification lands minutes after a new hourly stamp flips a tier,
and its evidence is hour-grain. Every message says so. The ~1-2 min end-to-end
figure belongs to the bus live chain and may never appear in a flood message.

**HITL gates.** Two open, both Ross's, neither blocking the build:
(a) arming the notifier out of dry-run for the first real send, and
(b) the formal rule lift in section 7, which is a decision he records by
amending the five documents. Nothing in this spec adds a standing process, so no
daemon approval is required.
