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

## FROM notify 08 (2026-08-25, branch `notify08-decision`) — THE DECISION FUNCTION EXISTS

The synthetic fixture has to trip EVERY branch, and this is the list of branches that
exist, with the shape each one needs:

- tier ENTRY fires; the same tier held fires nothing; a Window roll re-arms (roll it by
  swapping `score_version` — `nd.window_id` is `anchor|score_version|detector_version`);
- ELEVATED with `elevated_optin` 1 sends and with 0 is silent; HIGH sends either way;
- watch mode fires once per (unit, window) and not per cycle;
- silent: version skew (including an ABSENT `table_score_version`), INSUFFICIENT_DATA,
  WINDOW_CAPPED, the winter gate;
- quiet hours: HIGH sends, everything else DROPS and is logged — and the drop is not
  delivered late on the next cycle;
- the per-handle cap and the per-cycle fuse both clip and both log.

Two fixture traps this ticket already paid for, so you do not have to:

- **A four-stop vector cannot produce an ELEVATED** — the top 10% and the top 2% of four
  Units are the same Unit — so an ELEVATED case is built by re-tiering a REAL cycle
  payload (`tests/test_notify_decide.py::_retier`), never by inventing one.
- **Pin a clock where UTC and New York DISAGREE.** 16:00Z/12:00 NY and 06:00Z/02:00 NY
  give the same quiet-hours verdict in both zones, so a suite pinned only on those cannot
  see a timezone bug; 01:00Z = 21:00 NY can.

The rehearsal's own end state is unchanged: `ns.unsubscribe(con, token)` then a SQL
read-back of `subscriptions` (0 rows) against a throwaway db — the token in every message
is `Message.unsubscribe_token`, the handle's own.
