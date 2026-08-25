# 08 — The notify decision: one pure function

**What to build:** Given what the detector says now, what it said last cycle, who is
subscribed and the policy, decide exactly which messages should exist — with no network,
no clock read and no send, so every branch can be tested on fixtures before a real storm.
Spec: section 6; SEAM N.

**Blocked by:** 07 — externally on flood-build 11 (detector core).

**Status:** DONE 2026-08-25 (branch `notify08-decision`)

- [x] one pure function: (current evaluation, previous evaluation, subscriptions, policy, injected `now`) -> list of Messages; no network, no clock read, no file read, no send
- [x] tier branch notifies on tier ENTRY only, using F11's latch as the dedupe — a held tier sends nothing, exit then re-entry sends again, and the notifier reimplements no state the detector already holds
- [x] watch mode (the rank-only branch) dedupes on (unit, window_id): one message per Unit per Window on first top-N entry, and a Window roll re-arms it
- [x] HIGH always notifies; ELEVATED only with per-subscription opt-in
- [x] INSUFFICIENT_DATA never notifies, and the winter gate suppresses notifications exactly as it suppresses the panel
- [x] version skew between the coefficient and constants digests refuses the notification, exactly as it refuses the model tier
- [x] quiet hours DROP ELEVATED rather than deferring it (an hour-grain alert delivered hours late is worse than none) and never suppress HIGH
- [x] the per-subscriber-per-event cap and the global per-cycle send fuse both hold, and whatever the fuse dropped is logged
- [x] policy constants live in one frozen artifact — notifying tiers, watch-mode top-N, quiet-hour window and timezone, caps, fuse — never as scattered literals
- [x] clock-derived behaviour is pinned on a fixed epoch, never on wall clock
- [x] every contract assertion is mutation-checked: inverting the rule it pins turns the test red
- [x] which branch v1 ships is selected by F12's outcome, and holding the notify path is an acceptable outcome — the decision never manufactures confidence the backtest refused


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

## Inherited from flood-build 12's build (2026-08-25, branch `flood12-replay-harness`)

**YOUR POLICY BRANCH IS STILL OPEN, AND THE MEASUREMENT SAYS PLAN FOR THE TIERS TO GO.**
flood 12 replayed `fd.cycle` over 133 AORC-era events / 4,326 cycles and **RECOMMENDED
that v1 ship RANK-ONLY**; the verdict is Ross's and is not recorded yet
(`cutpoints.provisional` is still `true` on master). Read the flag at run time — never
re-type an outcome — and make sure the "tiers removed entirely" branch is the one you
build first, not the fallback.

**The volumes your fuse and your per-handle cap have to survive, if the cutpoints ARE
confirmed** (union over an event's cycles, which is exactly your `(unit, window_id)`
dedupe by another name):

| grain | rows | positives | base | tier | flagged | alert rate | TP | FP | precision |
|---|---|---|---|---|---|---|---|---|---|
| bus_stop | 502,756 | 2,831 | 0.563% | ELEVATED+ | 76,165 | 15.15% | 1,032 | **75,133** | 1.35% (2.41x base) |
| bus_stop | | | | HIGH | 14,521 | 2.89% | 370 | **14,151** | 2.55% (4.53x base) |
| complex | 43,089 | 118 | 0.274% | ELEVATED+ | 5,214 | 12.10% | 29 | **5,185** | 0.56% (2.03x base) |
| complex | | | | HIGH | 956 | 2.22% | 5 | **951** | 0.52% (1.91x base) |

Against flood 09's fitted operating point, **NOT superseded**: point 1.11% -> 381 TP /
8,295 FP, precision 4.39% (8.57x base). **The base-rate rule applies to this table and is
already applied in it: your `bus_stop` universe is 502,756 rows at a 0.563% base rate while
flood 09's `point` is 783,351 rows at 0.512% — the detector publishes no entrance row — so
never compare the two raw.**

**What that means per subscription, which is the unit your cap is written in.** ELEVATED+
alarms on 15.15% of (stop, event) pairs; over 133 events in 16 years that is **~1.3 alerts
per subscribed stop per year, ~99% of them false**. HIGH alone is ~0.24/year. The volume is
NOT an inbox-flooding problem — it is a PRECISION problem, and it is bursty: **96 of the
133 events flag no bus stop at all**, and when it fires it flags ~2,000 stops at once. Size
the global per-cycle fuse for the burst, not for the average.

**Two structural facts from the replay your decision function should not fight.**
1. **A tier LATCHES within its Window and the Window ROLLS when the city dries**, so
   reading the standing set at the end of an event measures the morning after: Ida's last
   replayed cycle stands at ZERO flags with 264 mm behind it. Your first-entry dedupe is
   the right shape; a "still flagged?" poll is not.
2. **The cut is a within-kind rank with no absolute anchor**, so it spends the same ~10% of
   the city on a storm that floods nothing as on one that floods everywhere (Cell grain:
   POD 0.379 at a 16.6% alert rate on the top quartile, where flood 09's fitted cut reaches
   0.436 at 5.7%; 1,514 false alarms for 11 hits on the bottom quartile). If the verdict
   confirms the cutpoints anyway, that is the shape of what you will be sending.

**At COMPLEX grain a tier is a claim the artifact refuses to make** — 5,214 ELEVATED+
badges for 29 hits, on the grain whose own `display.no_complex_skill_claim` records 1 of
118 independent positives caught. Your store holds `bus_stop` and `complex` rows only, so
this one lands directly on you.

## From notify 04 (landed 2026-08-25) — one line, and it is a "do not"

`query.QUERIES` now holds four names (`assets_in_area` / `obs_near` joined the two you
already knew), and **none of them belongs inside your pure function**: the decision reads
no table, no file and no clock, so "how many other assets in this Cell are flagged" is a
RENDERER's question (notify 09) answered by calling `assets_in_area` outside the decision —
never a read smuggled into it. If a policy constant ever wants an area (a per-Cell blast
fuse, say), it arrives as a NUMBER in the frozen policy artifact, computed by the caller.

## DONE 2026-08-25 — branch `notify08-decision`

`src/raincheck/notify_decide.py` + `tests/test_notify_decide.py` (**70 tests, 0.18 s**;
40/40 mutations red, no survivors). THE CALL:

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

**BOTH BRANCHES SHIPPED AND BOTH PINNED, and which one runs is READ.** `nd.branch(det)`
returns `nd.WATCH` while `cutpoints.provisional` is true (it still is) and `nd.TIER` when
Ross records the verdict as false. `display.cutpoints_confirmed_by` is NOT the switch — it
already names "flood-build ticket 12" and has since flood 11 landed, so a branch keyed on
it would have shipped tiers from day one. A missing flag is WATCH: the conservative branch
is the fail-safe one. Nothing here re-types an outcome, and `nd.POLICY` alone (a Policy not
built through `policy(det)`) is REFUSED at the call.

- **TIER** — the latched tier moved UP since the previous evaluation. flood 11's latch IS
  the dedupe: a tier cannot fall inside a Window, so one entry per Unit per Window falls
  out of it, an ELEVATED -> HIGH escalation is a second entry, and a downward revision is
  never a trigger. HIGH always; every tier below it needs `elevated_optin`.
- **WATCH** — first entry into the top N of the current within-kind vector, keyed on
  `(unit, window_id)` because the rank has no latch. **N is a COUNT and not a percentage**
  (`{"bus_stop": 25, "complex": 5}`), which is the whole point: flood 12 measured a rank
  spending the same ~10% of the city on a storm that floods nothing as on one that floods
  everywhere, and a count cannot. Both Ns sit far under that kind's measured HIGH alert
  rate (2.89% of 13,370 stops = 386; 2.22% of 445 complexes = 10), so the watch branch is
  the TIGHTEST cut on flood 12's table, not a loosened one.

**THE WATCH BRANCH HAS TO RE-APPLY TWO GATES THE TIER BRANCH GETS FOR FREE, and this is
the defect the ticket was one line away from.** `fd.tiers` ANDs the own-Cell 2.0 mm total
and citywide-active into `tier`; it does NOT touch `rank`. And **the winter gate zeroes
every `tier` while leaving every `rank` untouched** — so a watch branch reading the payload
alone notifies straight through a snowstorm, and on a dry afternoon it notifies the top N
of nothing, because something is always the maximum of a vector. Both are asserted, both
mutation-checked.

**SILENT, each checked here rather than inherited** (`fd.cycle` REPORTS these and acts on
none of them): version skew — `fd.skew` refuses on skew AND on an absent table stamp, and
`nd.SKEW` is the reason on both; `INSUFFICIENT_DATA` / `WINDOW_CAPPED`; the winter gate. A
window state this module does not know RAISES rather than passing through as a send.

**QUIET HOURS DROP, THEY NEVER DEFER**, and the ledgers are what enforce it: they record
the ENTRY and not the send, so a message quiet hours or a cap dropped is logged in
`Decision.drops` and never quietly delivered on a later cycle inside the same Window.
Nothing that is not HIGH survives quiet hours — **in WATCH mode that means every message,
because watch mode claims no tier at all**. `quiet_hours_tz` is `fd.NY`, the detector's
own; "America/New_York" is not spelled twice.

**THE FUSE ARITHMETIC.** Per handle per Window the cap is `ns.MAX_PER_HANDLE` (10),
imported and never re-stated — a handle with 10 subscriptions can be owed 20 messages in
one Window once escalations count, and the cap clips at 10. The global per-cycle fuse is
`ns.INGRESS_TRIGGER_ENTRIES` (25), and the derivation is the point: a Unit fires at most
once per cycle, so a cycle can legitimately send at most one message per SUBSCRIPTION, and
the managed list is allowed 25 subscriptions before ticket 07's deferred ingress reopens.
A cycle that wants to send more than the list may hold is a defect or a list that outgrew
v1. Every Decision publishes `worst_case` = handles x MAX_PER_HANDLE beside it.

**ONE DEVIATION, NAMED.** The spec says the policy constants live in "one frozen
artifact". They live in ONE frozen place — `nd.Policy`, a frozen dataclass, with
`nd.POLICY` the frozen instance — and NOT in a new `research/*.json` beside flood 11's.
The reason is that this policy has no digest role, no consumer outside `src/`, and no
build step, so a JSON file would have bought a `build()`, a Makefile target and a path in
exchange for nothing readable — and the wave-6 collision preamble lists notify 08 as an
editor of `notify_*` ALONE, with the Makefile owned this wave by flood-build 19 and
frontend2 02. Every constant is asserted by test and the two values that could drift
(`branch`, `own_cell_window_mm`) are READ from the artifact rather than stored. If a later
ticket needs the policy on disk it is one `json.dumps(asdict(POLICY))` away.

**THE LEDGERS, and the two rules that are not obvious.** `Decision` is its own `previous`
(the `fd.cycle` idiom, one state object, no daemon): `latched` is the evaluation it saw,
`watched` the Units already entered this Window, `sent` the per-handle count. They roll on
`window_id` = `f"{anchor}|{score_version}|{detector_version}"` — **exactly the three fields
`fd.rolled` compares**, so a coefficient swap mid-Window re-arms the dedupe by construction.
(1) A cycle with NO Window (INSUFFICIENT_DATA) has no identity, so its ledgers are CARRIED
rather than cleared — an outage is not an event boundary. (2) A refused cycle carries them
too: a refusal teaches the notifier nothing, so it must forget nothing, and clearing here
re-sends every standing flag the moment the refusal lifts.

**NOT read, by contract:** `design_storm` (flood-build 20, wave 8) is DISPLAY and never a
tier — asserted by absence. Staleness is deliberately not a refusal (the panel renders it).
A complex message carries the artifact's own `display.no_complex_skill_claim` sentence,
verbatim, so ticket 09 can neither forget it nor paraphrase it; a bus_stop message carries
none.

**TWO MUTATION SURVIVORS, closed rather than argued away.** (1) "which tiers notify" was
indistinguishable from "any tier that is not NONE" under the default policy, so flood 12's
HIGH-alone counter-case could not even be expressed — `notifying_tiers` is now narrowable
and a test drives it. (2) Both pinned clocks read the SAME quiet verdict in UTC and in New
York (16:00Z/12:00 NY and 06:00Z/02:00 NY), so reading the UTC hour survived: the suite now
also pins DUSK, 01:00 UTC = 21:00 NY, where the two disagree. Sibling of the degenerate
fixture flood 11 hit.
