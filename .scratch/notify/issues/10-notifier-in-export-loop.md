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
