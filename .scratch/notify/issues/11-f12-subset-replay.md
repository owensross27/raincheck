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
