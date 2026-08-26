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

## FROM notify 11 (2026-08-26, branch `notify11-f12-subset-replay`) — THE FIXTURE SHAPES AND THE BRANCH LIST

**THE BRANCH LIST, MEASURED RATHER THAN LISTED.** notify 11 replayed BOTH branches over
flood 12's 133-event subset by building two policies from the artifact —
`nd.policy(det)` and `nd.policy(dict(det, cutpoints=dict(det["cutpoints"],
provisional=False)))` — and running one `nd.decide` chain per branch off ONE `fd.cycle`
chain. **That is how your rehearsal reaches the branch that is not shipping: flip
`cutpoints.provisional` on a COPY of `fd.constants()` and ask `nd.policy` again. Never
construct a `Policy(branch=...)`; `decide()` refuses a Policy that did not come from
`nd.policy(det)`.** The live branch is still `watch`.

**FOUR OF YOUR SIX SYNTHETIC BRANCHES ARE REACHABLE FROM A REAL HISTORICAL EVENT and two
are not — measured, so you do not have to discover it:**

- **entry / hold / Window roll** — reachable. A real event's cycles produce entries and
  holds on their own, and a multi-day event ROLLS its Window mid-storm (the city dries and
  the storm returns), which re-arms the dedupe with no artifact swap. `notify-11-replay
  .json`'s `over_expectation` rows under `more_than_one_message_per_subscription` are
  exactly the events where that happened; take your roll fixture from one of them rather
  than from a `score_version` swap, which tests the key and not the walk.
- **INSUFFICIENT_DATA** — reachable: 76 of flood 12's 4,326 cycles are that state, and
  `nd.silent()` renders them as `insufficient_data` on every chain.
- **quiet hours** — reachable, and on the WATCH branch it is not an edge case at all:
  `Message.tier` is None there, so `urgent` is False for EVERY message and quiet hours
  suppress ALL of them. A watch-branch storm that peaks between 22:00 and 07:00 New York
  sends nothing.
- **the per-cycle fuse** — reachable ONLY with a list whose members are the Units the rank
  puts on top (`notify_replay`'s `top_scored` cohort, picked off `gold/flood_exposure`'s
  `score_index`). An arbitrary list cannot reach it; see the MUST on notify 10.
- **the winter gate** — reachable, and not rare: **267 of the 4,326 cycles were
  winter-suppressed** and `nd.silent()` renders every one as `winter_gate`. (The replay
  substitutes the citywide AORC median temperature for flood 14's KNYC reading, which has
  no history on this root — the gate stays observation-derived, but a rehearsal that wants
  the LIVE observation still has to inject one.)
- **WINDOW_CAPPED** — **NOT reachable from history: flood 12 measured ZERO capped cycles in
  4,326, and this replay's silent-cycle table confirms zero on every chain.** It is the one
  detector state that has to be synthetic.
- **the per-handle cap** — **structurally unreachable on the watch branch**, and this is
  arithmetic, not a gap in the fixture. See the MUST on notify 10; your rehearsal has to
  build it with an escalation on the TIER branch or with a `per_handle_event_cap` override.

**THE SUBSCRIPTION FIXTURE SHAPE, and it is the store's or `decide()` raises.** Exactly
`ns.COLUMNS` in order, `state` = `ns.STATES[0]`, `asset_kind` in `ns.KINDS`,
`elevated_optin` in (0, 1). `notify_replay.subscribers(rows, handles)` builds them from
`[(asset_id, kind), ...]` round-robin and REFUSES a list that puts more than
`ns.MAX_PER_HANDLE` rows on one handle — reuse it rather than hand-shaping dicts. Its
handles are `sub<NN>@replay.invalid` (RFC 2606 `.invalid`, which can never resolve to a
real mailbox); do the same, and keep handles out of any published artifact — every number
notify 11 publishes comes from `Decision.summary()` or `Message.asset_kind`.

**THE 2023-09-29 EVENT YOUR LINE NAMES IS IN THE SUBSET** and it replays through the
detector's own walk with no hand-built state: `notify_replay.inputs(con, root, ev)`
returns `(wet, temp, by_hour, units)` for one event exactly as flood 12 reads them, and
`notify_replay.replay(ev, wet, temp, by_hour, us, art, det, score_version, chains)`
walks it. Both are two lines from a rehearsal.

**NAMES, so this file does not end up with two `nr`s:** notify 09 ships
`raincheck.notify_render` and this ticket ships `raincheck.notify_replay`. Both read
naturally as `nr`. Spell them out here — every module name in this block is written in
full for that reason.
