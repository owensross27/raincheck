# 10 — The notifier inside the export loop, dry-run by default

**What to build:** The decision and the send happen inside the 30 s loop that already
computes the detector tick — so a tier entry becomes a logged (and, once armed, sent)
message without standing up a single new process. Spec: section 8; sections 7 (sending
discipline).

**Blocked by:** 09 — externally on flood-build 15 (the flood tick inside the export loop).

**Status:** ready-for-agent

- [ ] the decision and the send run inside the existing 30 s export loop, in the same tick that computes the detector state — no new daemon, so no new HITL gate opens
- [ ] DRY-RUN IS THE DEFAULT: messages render and log without being sent unless the notifier is explicitly armed
- [ ] a missing credential makes the notifier do nothing and say so — fail closed, never half-send
- [ ] each send has a hard timeout; a failure is logged to the flood NDJSON log and skipped; a mail failure never stalls a cycle and never blocks the panel
- [ ] the loop's existing rules bind the notifier: cycles cannot overlap, one cycle id spans the set, one hung socket never stalls the bus panel
- [ ] notifier state (last-notified keys per unit and Window) persists with the loop's other state; a lost state file degrades to at most one re-send per Window, never one per cycle
- [ ] email is the only channel — no SMS, push or webhook path exists in the code
- [ ] no third-party analytics touch the message or the store

## FROM notify 08 (2026-08-25, branch `notify08-decision`) — THE DECISION FUNCTION EXISTS

The decision is a pure function you call inside the existing 30 s loop. No new process,
no new clock: it takes yours.

```python
from raincheck import flood_detect as fd
from raincheck import notify_decide as nd
from raincheck import notify_store as ns

det = fd.constants()                   # the CALLER reads the artifact; decide() opens nothing
p   = nd.policy(det)                   # -> Policy; READS `cutpoints.provisional` -> branch
subs = ns.subscriptions(con)           # ACTIVE rows, (handle, asset_id) order
cyc  = fd.cycle(state, now, cell_hours, units, art, det, ...)
d    = nd.decide(cyc, d_prev, subs, p, now)      # -> Decision; d is the next call's d_prev
for m in d.messages:                   # -> Message (frozen)
    ...
```

**Wiring MUSTs.**

- **Build the policy ONCE per cycle from the artifact — `nd.policy(det)`.** Passing
  `nd.POLICY` directly is REFUSED (it carries no branch), which is deliberate: it is what
  makes shipping the wrong branch impossible to do quietly. Reading `det` is YOUR file
  read; `decide()` opens nothing.
- **Chain TWO states, not one**: `fd.cycle`'s return and `nd.decide`'s return. The
  Decision is its own `previous` and holds the ledgers a rank cannot (`latched`,
  `watched`, `sent`), so a lost state degrades to at most one re-send per Window — which
  is exactly your line's requirement, and it is a property of the ledgers rolling on
  `window_id`.
- **Pass the SAME `now` you passed `fd.cycle`.** A naive datetime is REFUSED
  (`ValueError`), because quiet hours are a local-hour rule and nothing here guesses which
  zone a naive clock is in.
- **`decide()` RAISES on an inconsistent store row** (a paused row, or a kind outside
  `ns.KINDS`) and on an unknown detector window state. Both are loud on purpose and both
  belong inside the catch your `detect()`/`ship()` shape already has — a mail failure
  never stalls a cycle, and neither should this.
- **`Decision.summary()` is the line to log**: `{branch, reason, window_id, messages,
  drops, dropped{reason: n}, worst_case}` — counts only, no handle, no payload. `reason` is
  why a whole cycle sent nothing (`version_skew`, `insufficient_data`, `window_capped`,
  `winter_gate`); `drops` is per-message with `{handle, asset_id, asset_kind, branch, tier,
  reason}` and is what "whatever the fuse dropped is logged" means.
- **NEVER re-send a drop.** The ledgers record the ENTRY, not the send, so a quiet-hours or
  cap drop is a DROP. Do not build a retry queue on top of this — the deferral is the thing
  the policy rejects.
- Dry-run stays yours: the decision decides, it never sends, and it has no credential path.

## FROM FLOOD 15 (2026-08-25, `flood15-panel-exports`, `5925813`) — SAME STRINGS, SAME LOOP

**THE STRINGS.** The panel now renders the frozen operating-truth string verbatim, and it
reads it from nowhere but `flood_panel.OPERATING_TRUTH`, which is notify 01's text
unedited. **Render the same object, not a paraphrase**: a message and the panel that
disagree is the failure notify 01's freeze exists to prevent. Everything else the panel
says is under `strings` in `files/flood.json` and comes from `display.*` in
`research/flood-11-detector.json` (`fd.constants()`) — `tier_labels`, `tiers`,
`window_states`, `precip_states`, `winter_label`, `winter_unknown_label`,
`no_complex_skill_claim`, `within_cell`, `cutpoint_basis` — plus `estimand`,
`estimand_note`, `tiers_provisional`, `gate_branch` and `panel` (flood 10's pre-selected
`headline` / `release` / `caveat`, branch MODEL). **`display.*` is deliberately OUTSIDE
`detector_version`**, so re-wording a label cannot roll a live Window — which only holds
while you READ them. `make release-check` fails if the honesty string stops riding on the
payloads, and it compares against notify 01's OWN ticket file rather than against the
exporter's copy (a `x in render(x)` check is a mirror-pin and passes whatever the string
becomes).

**`provisional` IS A TOP-LEVEL BOOLEAN, READ AT RENDER TIME.** flood 12 recommended
RANK-ONLY and the verdict is Ross's; while `cutpoints.provisional` is true the panel says
so, and recording the verdict bumps `detector_version` and rolls every open Window with
no code change. Branch on the flag, never on a remembered answer, and **never render a
tier as confirmed.**

**THE LOOP.** The flood tick is already inside cloud 05's 30 s loop as ONE call in
`live_loop.cycle()` and ONE field on `state` (`flood`). Join it the same way — no new
daemon, no second `python -m`:

    flood = flood_panel.tick(con, root, out_dir, state.get("flood"), now, detected)

It never raises (an outage is a field on its state), it SKIPS unless the forcing advanced
or the artifact's `throttles.floodnet_s` (120 s) expired, and it is handed the loop's own
`flood_live.live()` read so nothing re-fetches CO-OPS or KNYC at the render rate. Copy
that failure policy rather than inventing one. **The pod is limited to 768 MiB and the
loop now peaks at ~500 MiB** — if your notifier reads a table, put its projection and its
predicate INSIDE the read's own statement (`duck.table()` binds the path as a parameter
and blocks pushdown; that shape cost 5 GiB for six rows here — TRAPS).

**WHAT THE PANEL ALREADY PUBLISHES, so a message and a page cannot disagree:** the tier
per Unit and per Cell, `skew.model_tier` (a refusal is rendered, never a last-good
number), `window.state`, `staleness` per source with its budget in `budgets_s`
(seconds: precip 5400/10800, floodnet 600, coops 1800, nws_alerts 900, nws_knyc_obs
7200), `dim.dimmed` + `dry_hours`, and `winter`. Files: `files/flood.json` +
`files/flood-meta.json` (open) and `files/flood-mta.json` + `files/flood-mta-meta.json`
(GATED with `live.geojson`). The human-facing value is the RANK — never an eta, never a
probability, and `make release-check` fails if one appears.

## FROM notify 09 (2026-08-26, branch `notify09-message-render`, `d9e2e0a`) — THE RENDERER EXISTS

**THE EXACT SIGNATURE YOU CALL INSIDE `live_loop.cycle()`:**

    from raincheck import notify_render as nr
    body: bytes = nr.render(m)                       # m is one `nd.Message` from d.messages
    # or, passing the deployment facts rather than setting the module constants:
    body = nr.render(m, panel_url=..., unsubscribe_to=...)

`render(m: nd.Message, *, panel_url: str | None = None, unsubscribe_to: str | None = None)
-> bytes`. One plain-text RFC 5322 message, `policy=SMTP` (CRLF), `Content-Transfer-
Encoding: 8bit`. It is PURE: no clock, no socket, no database, no data root — it reads
only `research/flood-11-detector.json` and `research/flood-10-coefficients.json`, both
committed, both cheap (0.035 ms for the detector artifact), so calling it once per message
inside the 30 s tick costs nothing you need to cache.

**MUSTs this puts on you.**

- **IT RENDERS NO `From`, NO `Date` AND NO `Message-ID` — those are YOURS**, and leaving
  them out is exactly what makes the same Message render the same bytes. Add them at the
  send, beside the SES identity. A test asserts they are absent, so adding them inside the
  renderer goes red.
- **`nr.PANEL_URL` AND `nr.UNSUBSCRIBE_TO` ARE BOTH `None` AND `render()` REFUSES UNTIL
  THEY ARE SET.** They are [YOU] deployment facts this repo does not hold: no public URL
  exists anywhere in the tree (the bucket + custom domain are still open) and v1 has no
  unsubscribe mailbox (no endpoint, spec section 9). A `ValueError` naming both is the
  FIRST thing your dry-run will hit; that is the design, not a bug — a message with a dead
  link and a bouncing `List-Unsubscribe` is worse than one that was never rendered. Set
  them for real or pass them; **`tests/test_notify_render.py::test_the_deployment_facts_
  are_unset_in_the_tree` is the tripwire that goes red when you do, and updating it is part
  of that commit.**
- **A DROP IS NEVER RENDERED.** `Decision.drops` is a ledger, not a queue — render
  `d.messages` and nothing else, and log `d.summary()` (counts only, no handle).
- **THE RENDERER REFUSES A MALFORMED MESSAGE RATHER THAN RENDERING SOMETHING ODD**: a naive
  `m.now`, a branch outside `nd.BRANCHES`, a tier message whose tier is not a notifying
  one, a watch message carrying a tier or no `top_n`, an empty token. Those all raise
  `ValueError` inside your cycle, so wrap the render the way F15's tick wraps its reads —
  a message that cannot be rendered must not stall the panel beside it.
- **ASSERT ON THE DECODED BODY, NOT THE RAW BYTES, IF YOU ASSERT AT ALL:**
  `email.message_from_bytes(body, policy=email.policy.SMTP).get_content()`. (The claims DO
  survive verbatim in the bytes today, because the transfer encoding is 8bit precisely so
  they do — but the decode is what stays true if that ever changes.)

## FROM notify 11 (2026-08-26, branch `notify11-f12-subset-replay`) — THE REPLAYED VOLUME, AND FOUR THINGS THE FUSE ARITHMETIC ACTUALLY SAYS

The build asset is `research/notify-11-replay.{json,md}` (`make notify-replay`): notify
08's own `nd.decide`, replayed over flood 12's 133-event / 4,326-cycle subset on three
store-shaped synthetic lists and BOTH branches. **Read the `.md` before you size
anything** — the four findings below are its point, and every one of them is arithmetic
that survives whatever the volumes turn out to be.

**MUST 1 — THE PER-CYCLE FUSE AND THE INGRESS TRIGGER ARE THE SAME NUMBER
(`ns.INGRESS_TRIGGER_ENTRIES` = 25 = `Policy.per_cycle_fuse`), SO A LIST INSIDE v1's OWN
CEILING CAN NEVER TRIP IT.** A Unit fires at most once per cycle, so a cycle owes at most
one message per SUBSCRIPTION; while the managed list is inside the 25 entries the deferral
allows, `wanted <= 25 = fuse`. The first cycle that can trip the fuse is a cycle on a list
that has ALREADY reopened ticket 07's ingress. Do not read a never-firing fuse as evidence
it is sized right — it is evidence it has not been asked yet.

**MUST 2 — THE PER-HANDLE CAP IS STRUCTURALLY UNREACHABLE ON THE WATCH BRANCH.**
`per_handle_event_cap` IS `ns.MAX_PER_HANDLE` (10) and `notify_store.add` refuses a handle
past 10 ACTIVE rows; on the watch branch a (unit, Window) fires ONCE, so a handle receives
at most 10 messages per Window and the cap triggers on the 11th, which cannot exist. It is
a belt-and-braces guard there, not a limiter. **On the TIER branch it IS reachable** — an
ELEVATED -> HIGH escalation is a second message for the same (unit, Window), exactly as
notify 08's docstring says. Pinned by
`tests/test_notify_replay.py::test_the_per_handle_cap_cannot_fire_on_the_watch_branch`.

**MUST 3 — `Decision.worst_case` OVERSTATES, AND IT IS THE WRONG NUMBER TO SIZE OFF.** It
is `handles x ns.MAX_PER_HANDLE` — the ceiling on the STORE, not on the list in front of
it. Measured: the 25-entry `v1_list` cohort publishes `worst_case` **50** against a
reachable maximum of **25** messages in a cycle. Log it (it is the fuse's declared
ceiling), but size against the REACHABLE maximum, which is the active subscription count.

**MUST 4 — ON THE WATCH BRANCH NOTHING IS URGENT, SO QUIET HOURS SUPPRESS EVERYTHING.**
`Message.tier` is None there, so `urgent = tier == fd.HIGH` is False for EVERY message and
the 22:00-07:00 New York rule — which never suppresses HIGH — suppresses all of them. A
watch-branch storm that peaks overnight sends nothing at all and logs every entry as a
`quiet_hours` DROP. That is the policy working (the drop is not deferred), and it is the
single biggest term in the replayed volume. `elevated_optin` is read on the TIER branch
only, so a watch-branch subscriber is opted in to everything by construction.

**WHERE THE NUMBERS ARE.** Per-event message counts by kind, per-cycle counts, the drops
split by reason, and the per-subscription-per-year rate for every (cohort, branch) chain
are in the asset's `volume` block; `over_expectation` names every event that broke either
stated expectation. `flood_12_flag_volume` is flood 12's ELEVATED+ FLAG rate on the same
per-Unit-per-year scale — a flag is not a message and the two are never added.
