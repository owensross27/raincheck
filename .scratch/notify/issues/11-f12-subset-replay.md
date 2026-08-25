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
