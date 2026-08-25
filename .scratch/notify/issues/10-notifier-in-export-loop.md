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
