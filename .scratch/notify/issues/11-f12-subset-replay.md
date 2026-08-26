# 11 — F12-subset replay: what a real storm would have sent

**What to build:** The notify decision replayed over history, publishing how many messages
each past event would have produced — the number a human reads before the notifier is ever
armed. Spec: section 6 (test harness); Testing Decisions (replay is build-asset evidence,
not pytest).

**Blocked by:** 08 — externally on flood-build 12 (replay harness).

**Status:** DONE 2026-08-26 — branch `notify11-f12-subset-replay`, **+54 tests, 14/14 mutants killed (the FIRST round left SIX survivors and every one was a real test gap)**; assets `research/notify-11-replay.{json,md}`, `make notify-replay`. **BRANCH EXERCISED: `watch`** (read from `nd.branch(det)` at replay time; `cutpoints.provisional` is still `true`), with the `tier` branch replayed beside it as a labelled counterfactual. See the close-out below.

- [x] the decision replays over F12's replayable subset — **133 events / 4,326 cycles, the event ids READ out of `research/flood-12-replay.json`'s `per_event` block and the build refusing if its own count disagrees.** ("248 event-days" was the WHOLE 206-event union universe; the AORC-era one is 195 events / 236 event-days, 133 evaluable — corrected below)
- [x] per-event message counts by kind and by tier publish as a build asset on disk, following the F09/F12 precedent
- [x] the pytest suite asserts that the replay RUNS and the shape of its output; the volume numbers are evidence for a human, not an assertion
- [x] the report states which branch it exercised (tiers or watch mode) and which F12 outcome selected it
- [x] a run whose volume exceeds the stated per-event expectation is visible in the printed report — never silently absorbed (**55 rows**, two named expectations)
- [x] the replay uses the same pure function the loop calls, not a reimplementation

## Inherited from flood-build 12's build (2026-08-25, branch `flood12-replay-harness`)

**THE HARNESS EXISTS AND YOU CALL IT, YOU DO NOT REBUILD IT.** `make flood-replay`
(`src/raincheck/flood_replay.py`) replays `flood_detect.cycle` hour by hour over the
AORC-era union events and publishes `research/flood-12-replay.{json,md}`. Your subset
comes off that asset, counted, never re-derived — the `.json` carries `universe`,
`excluded` (cycles by walk state, events with no OK cycle) and one `per_event` row per
replayed event.

    from raincheck import flood_replay as fr, flood_detect as fd, duck
    con = duck.connect()
    evs   = fr.events(con, root)                      # AORC-era union events, oldest first
                                                      #   `in_matrix` False = walk-only
    wet   = fr.citywide(con, root, lo, hi)            # {hour_end: wet Cell COUNT}, WHOLE grid
    temp  = fr.temps(con, root, lo, hi)               # {hour_end: citywide median t2m_c}
    byh   = fr.cell_rows(con, root, lo, hi)           # {hour_end: [row]}, NULL rows KEPT
    us    = fr.units(con, root, event_id)             # gold/flood_matrix's own rows + `flooded`
    r     = fr.replay(ev, wet, temp, byh, us, art, det, score_version)
    # r: {cycles, states, union {asset_id: tier}, peak, end_flagged, revisions,
    #     winter_cycles, features, anchor, published}
    rows  = fr.slice_rows(byh, anchor, now)           # a LIST — cycle() reads it TWICE

**FOUR RULES THAT ARE NOT OPTIONAL, EACH ONE A WAY TO PUBLISH A WRONG COUNT.**
1. **`wet_by_hour` is always passed.** `cycle` defaults it off the `cell_hours` you gave
   it, which is right in production and silently redefines "citywide" as "these Cells"
   the moment you hand it a subset — the citywide-ACTIVE gate then never arms and a real
   storm replays as a quiet night. (The anchor is nearly K-inert, so this does NOT show
   up as a moved Window; it shows up as zero flags.)
2. **`cell_hours` must be a materialised LIST.** `cycle` iterates it once for the newest
   stamp and again inside `window_features`; a generator is exhausted by the first pass
   and the Window comes back with no Cells, coverage 1.0 and nothing flagged.
3. **Keep the NULL `mm_1h` rows.** AORC has 168 permanently dark Cells of 4,113; they are
   UNFORCED, not holed, and `window_features` leaves them out of the coverage denominator
   — but only if it can see them. A `WHERE mm_1h IS NOT NULL` reports identical coverage
   and zeroes `unforced_cells`.
4. **The readout is the UNION of tiers over the event's cycles, not the standing set at
   `window_end`.** A tier LATCHES within its Window and the Window ROLLS once the city
   dries: Ida's last replayed cycle stands at ZERO flags with 264 mm behind it
   (`r["end_flagged"]`). Your message count is the union — that is what a subscriber
   received — and notify 08's `(unit, window_id)` dedupe is the same union by another
   name.

**THE COUNTED SUBSET (correcting this file's "248 event-days").** 248 event-days is the
WHOLE union universe (206 events). The AORC-era universe this replay walks is **195 events
/ 236 event-days**; 133 of them have `gold/flood_matrix` rows and are evaluated, and the
other 62 are walk-only (coastal / mixed / snowmelt — the matrix is pluvial-only and
`density_311_3y` is a per-(Cell, event) covariate, so evaluating them would be a rebuild).
2026's 11 events have no AORC year at all. Take the replayable count from the asset's
`universe` / `excluded` blocks, not from any of these sentences.

**THE OUTCOME THAT SELECTS YOUR BRANCH IS `cutpoints.provisional` IN
`research/flood-11-detector.json`, READ AT RUN TIME.** flood 12 measured and recommended;
the verdict is Ross's and lands in that artifact. While `provisional` is `true` the tiers
are unconfirmed, so report which branch you exercised by reading the flag, never by
re-typing the outcome.

## FROM notify 08 (2026-08-25, branch `notify08-decision`) — THE DECISION FUNCTION EXISTS

**You replay the SAME function. Do not build a second one.** The exact call, chained the
way the loop chains it:

```python
from raincheck import flood_detect as fd
from raincheck import notify_decide as nd

det, art = fd.constants(), fe.coefficients()
p = nd.policy(det)                          # the branch comes from the ARTIFACT, per cycle
state = decision = None
for hour in fr.replay(...)-style cycles:    # your harness's own walk
    state = fd.cycle(state, now, cell_hours, units, art, det,
                     temp_c=..., table_score_version=art["score_version"],
                     wet_by_hour=wet)       # F12's four rules still apply, unchanged
    decision = nd.decide(state, decision, subs, p, now)   # SAME `now` both calls
    counts.append(decision.summary())
```

- **The branch you exercise is READ, never typed**: `nd.branch(det)` off
  `cutpoints.provisional`. Report which branch the run exercised beside every number —
  today that is `watch`, and a rank-only run and a tier run are not comparable volumes.
- **Per-event message counts by kind** — the build asset your line owes — come from
  `decision.messages` grouped by `asset_kind`, and the per-cycle counts from
  `Decision.summary()`. `drops` carries the fuse's and the cap's victims separately, so
  "this would have sent 400 emails" and "this would have DROPPED 400" are different rows.
- **Your subscription list is synthetic and it must be store-shaped**: ACTIVE rows with
  exactly `ns.COLUMNS`, `asset_kind` in `ns.KINDS`. `decide()` REFUSES anything else — a
  paused or Cell-grain row raises rather than being skipped quietly.
- **The volumes are per (unit, window), which is your union by another name.** The tier
  branch fires on the latched rise and the watch branch on first top-N entry, so both are
  once per Unit per Window — reading the standing set at `window_end` measures the morning
  after (Ida's last cycle: zero flags, 264 mm behind it), and neither branch does that.
- `nd.window_id(cyc)` is `anchor|score_version|detector_version` — the same triple
  `fd.rolled` compares. If your replay swaps artifacts mid-event the Window rolls and the
  dedupe re-arms, by construction.

## DONE 2026-08-26 — the replay ran, and the fuse survived the realistic list and not the adversarial one

Branch `notify11-f12-subset-replay`, worktree `/Users/ross/raincheck-wt/notify11`.
`make notify-replay` -> `src/raincheck/notify_replay.py` + `research/notify-11-replay.{json,md}`.
**This build touched no artifact but its own.** `research/flood-11-detector.json` is
unread except through `fd.constants()`; `cutpoints.provisional` is still `true`, so
`nd.branch(det)` returns `watch` and that is the branch this run exercised.

### What ran

**133 events / 4,326 hourly cycles**, the SAME numbers flood 12 published — the event ids
are read out of `research/flood-12-replay.json`'s `per_event` block and `build()` REFUSES
if its own resolved count disagrees. Span **2010-08-22 .. 2025-12-19, 15.33 years**.
Wall clock **1,224 s (20.4 min)**, peak RSS **720 MB**.

Per cycle: ONE `fd.cycle` chain feeding SIX `nd.decide` chains (three synthetic lists x
two branches), every call handed the same `now`, both states chained. flood 12's four rules
are honoured unchanged and each has its own test. **Independent cross-check that the walk
is the same walk: this replay counts 76 `insufficient_data` silent cycles on every chain,
which is flood 12's own 76 INSUFFICIENT_DATA, and 0 `window_capped`, which is its 0.**

### The three lists, and why there are three

| list | subs | handles | assets picked by | isolates |
| --- | ---: | ---: | --- | --- |
| `v1_list` | 25 = `ns.INGRESS_TRIGGER_ENTRIES` | 5 | most-flooded in `gold/flood_matrix` | the realistic list at v1's own ceiling |
| `post_ingress` | 60 = 6 x `ns.MAX_PER_HANDLE` | 6 | same | SIZE |
| `top_scored` | 60 | 6 | highest `score_index` in `gold/flood_exposure` | SELECTION — the adversarial case |

Every row is store-shaped (exactly `ns.COLUMNS`, ACTIVE, `asset_kind` in `ns.KINDS`) and
opted in to ELEVATED; handles are `sub<NN>@replay.invalid` and reach no published number.
The third list exists because **a rank cut is not a threshold**: an arbitrary list can
never ask a per-cycle fuse of 25 for more than 25, so the only way to test the fuse against
a real event is a list whose members ARE the Units the rank puts on top.

### The volume (messages | drops), 133 events, 15.33 years

| chain | events that sent | messages | by kind | drops | per subscription per year |
| --- | ---: | ---: | --- | ---: | --- |
| **`v1_list/watch` (LIVE)** | 23/133 | **61** | bus 51 · cx 10 | 31 (all quiet_hours) | bus **0.158** · cx 0.163 |
| `post_ingress/watch` (LIVE) | 34/133 | 100 | bus 72 · cx 28 | 46 (all quiet_hours) | bus 0.094 · cx 0.183 |
| `top_scored/watch` (LIVE) | 56/133 | 749 | bus 495 · cx 254 | 620 (618 quiet · **2 fuse**) | bus 0.646 · cx 1.657 |
| `v1_list/tier` | 56/133 | 406 | bus 349 · cx 57 | 82 (all quiet_hours) | bus 1.084 · cx 0.930 |
| `post_ingress/tier` | 68/133 | 836 | bus 712 · cx 124 | 241 (all quiet_hours) | bus 0.929 · cx 0.809 |
| `top_scored/tier` | 70/133 | 1,712 | bus 1269 · cx 443 | 748 (113 quiet · **566 fuse** · **69 handle_cap**) | bus 1.656 · cx 2.890 |

Tiers: every watch message carries `tier: None` (749 of 749 on the loudest watch chain);
the tier chains split ELEVATED/HIGH (`top_scored/tier` 185/1527, `v1_list/tier` 112/294).
**Silent cycles, identical on all six chains: 0 `version_skew` · 267 `winter_gate` ·
76 `insufficient_data` · 0 `window_capped`.**

### Five findings, and every one is arithmetic that outlives the volumes

1. **THE PER-CYCLE FUSE AND THE INGRESS TRIGGER ARE THE SAME NUMBER (25), SO A LIST INSIDE
   v1's OWN CEILING CANNOT TRIP IT.** A Unit fires at most once per cycle, so a cycle owes
   at most one message per SUBSCRIPTION. Measured: `v1_list` peaked at **5 sent / 5 wanted**
   per cycle on watch and 12/12 on tier — nowhere near 25. The fuse fired only on
   `top_scored`, which is past the trigger by construction. **A never-firing fuse is not
   evidence it is sized right; it is evidence it has not been asked.**
2. **THE PER-HANDLE CAP IS STRUCTURALLY UNREACHABLE ON THE WATCH BRANCH, AND REACHABLE ON
   TIER.** `per_handle_event_cap` IS `ns.MAX_PER_HANDLE` (10) and the store refuses a handle
   past 10 ACTIVE rows; on watch a (unit, Window) fires once, so a handle receives at most
   10 per Window and the cap triggers on the 11th, which cannot exist. **Measured: ZERO
   `handle_cap` drops across all three watch chains and 69 on `top_scored/tier`** — where an
   ELEVATED -> HIGH escalation is a second message for the same (unit, Window).
3. **`Decision.worst_case` OVERSTATES AND IS THE WRONG NUMBER TO SIZE OFF.** It is
   `handles x MAX_PER_HANDLE` — the ceiling on the STORE. `v1_list` publishes `worst_case`
   **50** against a reachable maximum of **25**. The cohort block publishes both.
4. **ON THE WATCH BRANCH NOTHING IS URGENT, SO QUIET HOURS SUPPRESS EVERYTHING.**
   `Message.tier` is None, so `urgent` is False for every message and the 22:00-07:00 rule —
   which never suppresses HIGH — suppresses all of them. **It is the single biggest drop
   reason on every chain: 618 of `top_scored/watch`'s 620 drops, 31 of 31 on `v1_list`.**
   `elevated_optin` is read on the tier branch only, so a watch subscriber is opted in to
   everything by construction.
5. **A "MORE THAN ONE MESSAGE PER SUBSCRIPTION" EVENT IS AN ESCALATION AS OFTEN AS A ROLL,
   and the row's own `windows` count is what tells them apart.** 19 such events, ALL on
   `top_scored/tier`, and **most carry `windows: 1`** (2020-11-30: owed 62 on 60
   subscriptions across ONE Window). Only `windows > 1` is a rolled Window. The first draft
   of this rule said "the Window ROLLED", which the data refuted.

### The number this was measured against, and it does not reproduce the sentence in the box

The wave-7 box states flood 12's volume as "**~1.3 alerts per subscribed stop per year at
ELEVATED+**". Recomputed from flood 12's own published `flag_volume` over this replay's own
15.33-year span, with the denominators named: **bus_stop 76,165 flags / 13,310 stops /
15.33 y = 0.373 per stop per year**; complex 5,214 / 445 = **0.764**; **cell 23,342 / 1,351
= 1.127**. The ~1.3 is the CELL-grain figure, and Cells are not subscribable. The
bus-stop number is **0.373**, and the watch branch's actual MESSAGE rate on the realistic
list is **0.158** — a flag is not a message, and the top-25-per-Window cut is roughly 2.4x
tighter than ELEVATED+. All three rows are published in the asset's
`flood_12_flag_volume` block with their denominators.

### Two named expectations, and 55 rows over them

`cycle_owed_more_than_the_fuse_allows` (a cycle owes at most 25) and
`more_than_one_message_per_subscription`. Both are recomputed by `derived()` from the
committed per-event rows, so `make notify-replay RENDER=1` re-renders a wording or
threshold change in a second instead of costing another 20-minute replay.
**The fuse rule is deliberately NOT named "the fuse fired":** `decide()` tests quiet hours
-> handle cap -> fuse in that order, so a cycle can owe more than the fuse allows while the
fuse never fires — measured on `post_ingress/tier`, 2 events at `wanted: 26` with
`fuse_dropped: 0`. Every row carries `fuse_dropped` so the two are never conflated.

### Tests

**+54** in `tests/test_notify_replay.py` (1305 -> 1359, recounted with `def test_` against
this branch's OWN merge base `5dc7666`), all on fixtures except five real-root canaries.
Module run **54 passed / 0 skipped in 0.44 s**; with the three modules it depends on
(`test_notify_decide`, `test_notify_store`, `test_flood_replay`) **183 passed / 0 skipped
in 1.54 s** (7.7 s on a cold page cache). No full suite — that is the gate's.

**14 mutations, and the FIRST round killed only 8.** The six survivors were all real test
gaps of exactly the kinds TRAPS names, and closing them is the second commit on this
branch:

- **the state-chaining test built its OWN loop**, so breaking either chain inside
  `replay()` was invisible to it — a control the test re-implements cannot see the harness
  stop chaining. The chained number now comes from `nr.replay` itself, and an ast test pins
  `fd.cycle`'s first argument and `nd.decide`'s second.
- **the per-kind/count test ran on a Decision with ZERO drops**, so folding drops into
  `messages` AND dropping the `+ drops` from `peak_cycle_wanted` both survived — the
  degenerate-fixture trap, two counters at once. It now drives a Decision that sends and
  drops.
- **the `ns.COLUMNS` row-shape guard cannot fire on any data this module produces**, so it
  is tested by moving the store's own constant — the only thing that can discriminate it.
- **the version-skew guard had no test at all**: a skewed stamp makes `nd.silent()` return
  `version_skew` on every cycle, so the run would publish a quiet decade that looks like a
  result.

Second round: **14/14 killed**, pristine control green before and after, tree clean.
