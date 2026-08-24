# 08 — The notify decision: one pure function

**What to build:** Given what the detector says now, what it said last cycle, who is
subscribed and the policy, decide exactly which messages should exist — with no network,
no clock read and no send, so every branch can be tested on fixtures before a real storm.
Spec: section 6; SEAM N.

**Blocked by:** 07 — externally on flood-build 11 (detector core).

**Status:** ready-for-agent

- [ ] one pure function: (current evaluation, previous evaluation, subscriptions, policy, injected `now`) -> list of Messages; no network, no clock read, no file read, no send
- [ ] tier branch notifies on tier ENTRY only, using F11's latch as the dedupe — a held tier sends nothing, exit then re-entry sends again, and the notifier reimplements no state the detector already holds
- [ ] watch mode (the rank-only branch) dedupes on (unit, window_id): one message per Unit per Window on first top-N entry, and a Window roll re-arms it
- [ ] HIGH always notifies; ELEVATED only with per-subscription opt-in
- [ ] INSUFFICIENT_DATA never notifies, and the winter gate suppresses notifications exactly as it suppresses the panel
- [ ] version skew between the coefficient and constants digests refuses the notification, exactly as it refuses the model tier
- [ ] quiet hours DROP ELEVATED rather than deferring it (an hour-grain alert delivered hours late is worse than none) and never suppress HIGH
- [ ] the per-subscriber-per-event cap and the global per-cycle send fuse both hold, and whatever the fuse dropped is logged
- [ ] policy constants live in one frozen artifact — notifying tiers, watch-mode top-N, quiet-hour window and timezone, caps, fuse — never as scattered literals
- [ ] clock-derived behaviour is pinned on a fixed epoch, never on wall clock
- [ ] every contract assertion is mutation-checked: inverting the rule it pins turns the test red
- [ ] which branch v1 ships is selected by F12's outcome, and holding the notify path is an acceptable outcome — the decision never manufactures confidence the backtest refused
