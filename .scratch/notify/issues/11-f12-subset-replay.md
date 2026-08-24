# 11 — F12-subset replay: what a real storm would have sent

**What to build:** The notify decision replayed over history, publishing how many messages
each past event would have produced — the number a human reads before the notifier is ever
armed. Spec: section 6 (test harness); Testing Decisions (replay is build-asset evidence,
not pytest).

**Blocked by:** 08 — externally on flood-build 12 (replay harness).

**Status:** ready-for-agent

- [ ] the decision replays over F12's replayable subset: AORC-era union events minus capped and INSUFFICIENT_DATA Windows — a subset of the 248 event-days, counted by F12 itself, never re-derived here
- [ ] per-event message counts by kind and by tier publish as a build asset on disk, following the F09/F12 precedent
- [ ] the pytest suite asserts that the replay RUNS and the shape of its output; the volume numbers are evidence for a human, not an assertion
- [ ] the report states which branch it exercised (tiers or watch mode) and which F12 outcome selected it
- [ ] a run whose volume exceeds the stated per-event expectation is visible in the printed report — never silently absorbed
- [ ] the replay uses the same pure function the loop calls, not a reimplementation
