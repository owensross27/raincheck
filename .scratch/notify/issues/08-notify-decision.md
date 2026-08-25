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


## Inherited from flood 11's build (2026-08-25, branch `flood11-detector-core`)

Your decision function consumes flood 11's tiers. **The tier vocabulary is closed and
ordered**, and it is `fd.TIERS` — read it, do not re-spell it:

    from raincheck import flood_detect as fd
    fd.TIERS        == ("NONE", "ELEVATED", "HIGH")     # ordered; index() is the comparison
    fd.NONE, fd.ELEVATED, fd.HIGH
    fd.constants()["cutpoints"]  # {ELEVATED 0.10, HIGH 0.02, basis, provisional, confirmed_by}
    fd.constants()["display"]["tier_labels"]  # {"ELEVATED": "elevated", "HIGH": "high", ...}

**A tier is a WITHIN-KIND RANK of the current live score vector, not a probability and not a
threshold on a depth.** ELEVATED is the top 10% and HIGH the top 2% of the Units of that kind
being scored right now, ANDed with two gates that are both latched inside a Window: the
Unit's own Cell must have taken >= 2.0 mm this Window, and the city must be actively raining.

**FOUR PROPERTIES YOUR DECISION MUST NOT FIGHT.**

- **Tiers LATCH within a Window and only a Window roll clears them** (`fd.latch`,
  `fd.rolled`). A Unit's tier never falls mid-Window, so a notifier that fires on a
  transition fires ONCE per Unit per Window — which is the property that makes per-stop
  messaging bearable. A downward series revision is LOGGED (`fd.revisions`) and never clears
  a flag.
- **THE CUTPOINTS ARE PROVISIONAL** until flood-build ticket 12's replay, whose verdict is
  **[YOU]-Ross's to read**. flood 09's preview of the volume: at the fits' 1.11% point-row
  alert budget the pooled out-of-fold decisions cost 8,295 false alarms against 381 hits, and
  Ida alone cost 5,715 FP against 195 hits. **flood 11's tiers are LOOSER than that budget**,
  so "v1 ships rank-only" is a live branch and your policy must survive the tiers being
  removed entirely.
- **ENTRANCES NEVER PUBLISH A LIVE NUMBER.** Only `bus_stop`, `complex` and `cell` rows come
  out of `fd.evaluate`. A complex's number is the max over its child doorway scores and
  carries **no complex-grain skill claim** — the independent complex set caught 1 of 118.
  Never word a message as though a complex tier were measured.
- **The winter gate can zero every tier while the Window still exists.**
  `fd.winter_gate(temp_c, now, stale)` suppresses at or below 0.5 C and falls back to the
  CALENDAR (flood_spine's snowmelt months) when the temperature is absent or stale — so a
  dead NWS endpoint is not a citywide outage in July and not a rendered rain tier in
  February. A suppressed cycle still returns its Window and its two digests.

**THE MODEL TIER CAN REFUSE ITSELF.** `fd.skew(art, table_score_version)` compares the
artifact's `score_version` against the table you read, and an ABSENT stamp refuses. A refused
cycle must send nothing, not a last-good tier.

### CORRECTED (same day, `d5e11f3`) — an adversarial review moved two artifact keys

`fd.TIERS` and the module constants are unchanged, so your vocabulary is unchanged. What
moved: **the tier NAME list and the cutpoint prose are now under `display`, not under
`cutpoints`** — `display.tiers`, `display.tier_labels`, `display.cutpoint_basis`,
`display.cutpoints_confirmed_by`; `cutpoints` is now `{ELEVATED, HIGH, provisional}`.
`display` is deliberately OUT of `detector_version`, for flood 10's reason: renaming a tier
must never roll a live Window and clear every latched flag. `detector_version` is
**`01197991471f`**. Also: `cycle()` now emits H3 Cell ids as HEX strings
(`fd.hexcell`) because an int64 past 2^53 cannot cross JSON — irrelevant to your
subscriptions, which are `bus_stop`/`complex` only, but it is what a shared payload carries.

## Forward-context from DESTINATION-PLAN.md (copied verbatim by the WAVE 5 GATE PART 2, 2026-08-25, from this ticket's summary line in waves/wave-3-plus.md)

**FROM DESTINATION-PLAN (2026-08-25), one line:** flood-build 20 (wave 8) adds a `design_storm` bracket to the flood export. It is DISPLAY, never a tier, and your decision function never reads it — the tier vocabulary stays `fd.TIERS`.
