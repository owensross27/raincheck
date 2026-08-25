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
