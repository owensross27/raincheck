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
