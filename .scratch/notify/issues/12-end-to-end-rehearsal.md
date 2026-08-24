# 12 — End-to-end rehearsal

**What to build:** One command drives a flood from detector state to a rendered message to
an empty subscriber store, twice — once on a synthetic event built to trip every branch,
once on the real 2023-09-29 event — so the first real storm is not the rehearsal. Spec:
section 10.

**Blocked by:** 10, 11.

**Status:** ready-for-agent

- [ ] one make target drives: fixture detector state -> tier entry -> notify decision -> message render -> dry-run send -> unsubscribe token -> empty store. Repeatable, no network, no real subscriber
- [ ] the synthetic event trips entry, hold, INSUFFICIENT_DATA, the winter gate, quiet hours and the per-subscriber cap
- [ ] the 2023-09-29 event replays through the detector's own walk, not a hand-built state
- [ ] the rehearsal asserts message counts and rendered strings; mail transport is NOT asserted — transport is exercised once by hand when the notifier is armed, and that is a HITL step
- [ ] re-running it after any change costs one command
