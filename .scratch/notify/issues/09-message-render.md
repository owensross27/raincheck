# 09 — Message render and the fixed strings

**What to build:** A decided Message becomes an email a person can read, act on and leave —
one that states the hour-grain evidence behind it and claims nothing the panel does not
claim. Spec: section 7 (message content, claim strings); SEAM N.

**Blocked by:** 01, 08 — externally on flood-build 15 (the fixed-string list and constants
artifact).

**Status:** ready-for-agent

- [ ] rendering a Message produces: the Unit's name and kind, the tier entered, the Window, the hour-grain evidence sentence, the estimand sentence, a link to the panel, and the unsubscribe instruction
- [ ] F15's fixed strings are reused verbatim — the reporting-propensity sentence, the estimand name `flooded_reported`, the Window in the tier label, the degraded-state strings, and the B2-branch alternates selected by the shipped model id; the message gets no vocabulary of its own
- [ ] ticket 01's replacement string is used where the retired one would have gone, and the retired string appears NOWHERE in the rendered corpus (asserted by absence)
- [ ] the message states its evidence window in hours and never implies second-scale urgency; the ~1-2 min end-to-end figure belongs to the bus live chain and appears nowhere
- [ ] the message never claims water was observed — it ranks where a flood REPORT is likely
- [ ] every message carries the subscriber's opaque unsubscribe token in a `List-Unsubscribe` mailto header AND in the body, and states the processing expectation honestly rather than implying instant one-click removal
- [ ] render is a pure function of the Message: same Message, same bytes

## FROM notify 08 (2026-08-25, branch `notify08-decision`) — THE DECISION FUNCTION EXISTS

You render `nd.Message`, and it is FROZEN. The decision produces no prose at all — the
only string it hands you is flood 11's own disclaimer — so every word is yours.

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

`Message`: `handle · asset_id · asset_kind · branch · tier · rank · top_n · window_id ·
anchor · now · unsubscribe_token · score_version · detector_version · no_skill_claim`.

**MUSTs this puts on you.**

- **`tier` IS `None` ON THE WATCH BRANCH, which is the branch shipping today** (flood 12
  recommended rank-only and `cutpoints.provisional` is still true). A renderer that reads
  `m.tier` for its headline renders `None` for every real message v1 sends. On watch,
  `m.top_n` is the N in force for that kind and `m.rank` is the within-kind rank — word it
  as a WATCH ("among the N most exposed right now"), never as a tier, and never as a
  measured depth. Where `m.tier` IS set it is a member of `fd.TIERS` and its label is
  `fd.constants()["display"]["tier_labels"][m.tier]` — read it, never re-spell it.
- **`m.no_skill_claim` is flood 11's `display.no_complex_skill_claim`, verbatim, and it is
  present on exactly the messages that owe it** (complex grain: the number is a max over
  child doorway scores and the independent complex set caught 1 of 118). Render it or you
  word a claim the artifact refuses to make. It is `None` on a bus_stop and nothing is owed.
- **The Window for the hour-grain evidence sentence is `(m.anchor, m.now]`** — the
  detector's own half-open convention. `m.anchor` is an ISO string, `m.now` the injected
  clock the decision ran at.
- `m.unsubscribe_token` is the handle's token straight off the store row — PER HANDLE and
  shared by every row that handle owns, exactly as your own summary line says.
- `m.score_version` / `m.detector_version` are the stamps the message was produced under;
  a message always says which model and which rules made it.

The frozen operating-truth string, the retired claim and the fixed-strings list are
UNCHANGED by this ticket — notify 08 renders nothing, so it retired nothing and added no
vocabulary of its own.

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
