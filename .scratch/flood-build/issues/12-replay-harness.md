# 12 — Replay harness: the live rules against history

**What to build:** The AORC-era spine replayed through the live Window walk and evaluation, publishing
signed live-minus-offline feature deltas and per-event flag volumes — the measurement that
confirms the tier cutpoints or drops v1 to rank-only before the panel faces a real storm.
Spec: Real-time detector (tiers, logging/replay); Testing seam 2.

**Blocked by:** 06, 11 — and externally on the pipeline build: 11 (live-precip job, as amended: each tick catches up every missing :00 stamp within MRMS's measured ~25 h retention; replay of any live-era Window is conditional on that catch-up)

**Status:** DONE 2026-08-25 — branch `flood12-replay-harness`, `adcc5dd`, +38 tests, 14/14 mutants killed; assets `research/flood-12-replay.{json,md}`, `make flood-replay`. **The SECOND acceptance box is deliberately NOT ticked and is not this ticket's to tick: the tier decision is [YOU]-Ross's.** The harness MEASURED and RECOMMENDED (v1 ships rank-only; counter-case HIGH-alone-at-Cell) and did not touch the artifact — `cutpoints.provisional` is still `true`, `confirmed_by` `None`, `detector_version` still `01197991471f`. See the close-out below and the wave-6 gate's STATUS [YOU] item 1.

- [ ] every AORC-era union event replays through the ticket-11 walk + evaluation on the flood-era precip tables; signed live-minus-offline feature deltas and per-event flag volumes (ELEVATED and HIGH counts per kind) publish as build assets
- [ ] the tier decision is recorded and applied: cutpoints confirmed, or — if per-event false-positive volume is unacceptable — v1 ships rank-only; either way the detector constants JSON updates and detector_version bumps
- [ ] capped or insufficient-data Windows are excluded from the replay and counted; the published table says how many and why (they are not replayable and say so)
- [ ] runnable check: the replay of the fixture event day reproduces ticket 11's fixture results exactly


## Inherited from flood 09's build (2026-08-24, `research/flood-09-fits.json`)

- **The gate fired MODEL** (both roles, location-blocked): the branch this ticket's replay
  reads is `gate.branch` in `research/flood-09-fits.json`, and `flood_fits.gate(summary)`
  re-evaluates it from the published tables. Shipped ids `point:l2_logistic` /
  `cell:l2_logistic`.
- **A preview of the flag-volume question this ticket owns.** At the fits' in-fold alert
  budget (1.11% of point rows) the pooled out-of-fold decisions cost **8,295 false alarms
  against 381 hits** (FAR 0.956), and the worst single event — 2021-09-01, Ida — produced
  **5,715 false positives against 195 hits at POD 0.59**. Ticket 11's provisional tiers
  (top 10% / top 2% within kind) are LOOSER than that budget, so the per-event volumes this
  replay measures should be expected in the thousands per major storm, and "unacceptable
  false-positive volume -> v1 ships rank-only" is a live branch, not a formality.
- Per-event POD and raw FP for every fit-era event are already published in
  `per_event.<role>` of that JSON (location-blocked, out of fold) — the replay's offline
  side has a comparison set without recomputing one.


## Inherited from flood 18's build (2026-08-24, `research/flood-18-replication.json`)

**The 2026 sensitivity story is settled and it has one shape: the headline is ROBUST to the
311 threshold and SENSITIVE to the label radius — and the raw CSI ranks the radius
BACKWARDS.** Four alternate universes were rebuilt end to end (04 -> 05 -> 06 -> 08 -> 09)
at 311 quantiles {0.975, 0.995} and label radii {50, 200} m around the frozen primary. Every
one re-fired the gate as **MODEL**, so nothing below changes which model ships.

- **311 threshold — mild.** +-2.5 percentiles of the daily-count distribution moves point CSI
  by at most 0.0010 (0.0300 / **0.0310** / 0.0312 at q0.975 / q0.99 / q0.995) and cell CSI
  by at most 0.0068. The event count moves a lot (243 / **206** / 196 events) and the
  headline barely does.
- **Label radius — the sensitive knob, and the trap.** Raw point CSI runs 0.0237 (50 m) /
  **0.0310 (primary, 100 m)** / 0.0667 (200 m), which reads as "wider is twice as good".
  Divided by each universe's OWN B0 — under location blocking B0 IS the base rate, B2 having
  degenerated onto it — the lift runs **11.13x / 6.05x / 4.42x**: the widest radius has the
  highest raw CSI and the LOWEST skill. 200 m nearly triples the point base rate (0.00512 ->
  0.01509; positives 4,008 -> 11,818) because a 200 m circle round a doorway catches 311
  reports from the next street. **The radius moves what "flooded" MEANS at point grain, not
  how well the model finds it.**
- **Never compare a CSI across universes without dividing by that universe's own base rate.**
  This is the same monotone-in-alert-rate trap flood 09 had to correct in fold, one level up.
  Any table you publish that ranks alternatives on raw CSI ranks them backwards.
- **The radius is structurally INERT at Cell grain** (the cell branch attaches on
  `a.cell = oe.cell`, no distance predicate): both radius universes' `fit_cell` rows are
  BYTE-IDENTICAL to the primary's, cell CSI 0.1591 to four decimals. Verified, not assumed —
  two real-root tests pin it, and their `fit_point` positives demonstrably move.
- The primary is UNTOUCHED: `research/flood-09-fits.json` still stands at `fits_version`
  **8050dfa41fc1** over `matrix_version` **8bc1e8912b1b**, point CSI 0.0310, cell 0.1591.
  No number in flood 09's asset is superseded by this ticket.

**What this means for YOUR verdict.** The threshold arm removes one live objection: the
2010-2025 event universe your replay walks is not an artefact of where the 311 cut was put
(+-2.5 percentiles barely moves the headline), so a "the events were chosen to flatter the
model" reading is answered with measurement. The radius arm does NOT let you off the
false-positive question and slightly sharpens it: at 200 m the point model looks twice as
good on raw CSI while alarming 4.2x as often (alert rate 0.01108 -> 0.04664). Your
"cutpoints confirmed, or v1 ships rank-only" call should be made on the FP volumes at the
primary's 100 m labelling, with the note that a wider labelling would have inflated every
headline you might otherwise have quoted in its favour.


## Inherited from flood 11's build (2026-08-25, branch `flood11-detector-core`)

The walk you replay is `src/raincheck/flood_detect.py`, and the rules are
`research/flood-11-detector.json`. Both are READS.

    from raincheck import flood_detect as fd
    fd.DETECTOR                                   # research/flood-11-detector.json
    fd.constants()                     -> dict    # the rule book; one file, one call
    det["detector_version"]                       # sha1 over fd.DIGESTED, NOT of the file
    fd.walk(now, wet_by_hour)          -> {anchor, state, walked_days, pad, missing_pad}
    fd.window_features(cell_hours, anchor, now)   # {cells:{...}, coverage, unforced_cells, state}
    fd.evaluate(art, units, feats)     -> [{asset_id, kind, cell, eta, rank}]
    fd.tiers(scored, feats, citywide_active) / fd.latch(prev, cur) / fd.revisions(prev, feats)
    fd.winter_gate(temp_c, now, stale) -> {suppressed, basis, temp_c, label}
    fd.staleness(newest, now) / fd.skew(art, table_score_version) / fd.rolled(...)
    fd.cycle(state, now, cell_hours, units, art, det, temp_c=, temp_stale=,
             table_score_version=, wet_by_hour=)   # one whole read; its return IS next state

Artifact keys: `window` {anchor_local_hour 21, tz, pad_hours 3, cap_days 6,
antecedent_hours 24, wet_mm 1.0, **wet_cells_k 5**, interval "(anchor, now]", states} ·
`cutpoints` {ELEVATED 0.10, HIGH 0.02, tiers, basis, **provisional true**, confirmed_by} ·
`gates` {own_cell_window_mm 2.0, citywide_active, latched_within_window,
dim_after_dry_hours 3, downward_revision_clears_a_flag **false**,
entrances_publish_a_live_number **false**, complex_rule} · `winter` {freeze_c 0.5, label,
unknown_label, unknown_fallback_months} · `staleness_budgets` {precip_fresh_min 90,
precip_stale_min 180, floodnet_min, coops_min, **nws_knyc_obs_min 120**, **nws_alerts_min
15**, clock_ahead_min} · `throttles` · `forcing` {product, rejected_products, stamp, url,
name, retention_days, **scale_band_applied false**} · `vocabularies` · `query_strings` ·
`nws_ugc_zones` **null, owed** · `canary` · `display` · `detector_version_scope`.

**THE VERSION-SKEW RULE.** `fd.skew(art, table_score_version)` compares
`art["score_version"]` against the score_version of **the table you actually read** —
the column on every row of `gold/flood_exposure` and its parquet footer key
`b"score_version"` — never a constant. An ABSENT table stamp REFUSES; "I could not tell" is
not "they match". `fd.rolled(prev_state, anchor, score_version, detector_version)` rolls the
Window when the anchor moves OR either digest moves, which is how a coefficient swap
mid-Window cannot leave latched tiers standing that the running model never produced.

**THE SETTLED STALENESS BUDGET.** The spec's 15 min is the per-cycle NWS **ALERTS** budget,
not the KNYC observation's. KNYC reports HOURLY, so at 15 min the winter gate could never
fire. The observation budget is **120 min = two report intervals**, published as
`staleness_budgets.nws_knyc_obs_min` and asserted equal to `flood_live.KNYC_STALE_MIN`.

**FIVE MEASUREMENTS THAT CHANGE HOW YOU READ YOUR OWN REPLAY.**

1. **THE LIVE WALK DOES NOT REPRODUCE THE OFFLINE WINDOW IN GENERAL, and that is the rule
   working.** It does on a fixture day (2021-09-01 mid-storm lands exactly on
   `window_start`). Population-wide it agrees on **89 of 166 AORC-era events with citywide
   rain (54%)**, and the usual disagreement is **ONE DAY EARLIER (56 cases)** because the
   evening before the storm-eve was also wet; full distribution -1 d 56 · -2 d 4 · -3 d 3 ·
   0 d 89 · +1 d 10 · +2 d 1 · insufficient 3. The live anchor is observation-derived, the
   offline window is a calendar fact. **Do not file the difference as a defect and do not
   "fix" the walk to agree** — your signed live-minus-offline feature deltas are measuring
   exactly this, and a longer Window is a LARGER total by construction, not a bias.
2. **The Window arithmetic itself is exact.** The live features reproduce
   `gold/flood_matrix`'s Ida row for **all 1,351 `fit_cell` Cells, ZERO mismatches at 1e-6**,
   and live eta at Window close equals the offline event eta to **2.3e-8**. So any delta you
   publish is the WINDOW moving, never the arithmetic.
3. **AORC has 168 permanently dark Cells of 4,113** (every hour of 2021-09 has exactly 3,945
   non-null). They are UNFORCED, not holed, and are out of the coverage denominator — counting
   them as holes would make every replay report HOLES forever. Live MRMS has all 4,113.
4. **`cycle(wet_by_hour=...)` is not optional for you.** "Citywide" means the whole grid;
   defaulting it off `cell_hours` is right in production and silently redefines citywide as
   "these Cells" the moment a replay passes a subset. Pass the real citywide series.
5. **K = 5 wet Cells is measured, and it is nearly inert for the anchor** (88 of 166 events
   at K=5 vs 89 at K=41; only 1,540 of 90,888 AORC hours hold 1-41 wet Cells at all). It is
   NOT inert for the citywide gate, which is why it is small. If your replay wants to sweep
   it, sweep the GATE, not the walk.

**THE TIER DECISION IS YOURS AND THE ARTIFACT IS WHERE IT LANDS.** `cutpoints.provisional`
is `true` and `confirmed_by` names this ticket. Either flip it with the cutpoints confirmed,
or drop `cutpoints` to rank-only — **either way `detector_version` bumps**, and a bump rolls
every open Window (`fd.rolled`), which is correct. `fd.DIGESTED` is the eleven keys the
digest covers; rewording a `_note` deliberately does NOT bump it.

**THE RADAR-ONLY-vs-AORC RATIO IS OWED TO YOU.** `scale_band.pass2_over_aorc` = [0.86, 0.92]
was measured on **Pass2**; the live forcing is **RadarOnly** and its bias against AORC is
UNMEASURED. flood 11 applied no band for exactly that reason and shipped rank-only with one
raw-total gate. You are the first build with both sides in hand — measure it and record it,
and note the direction that matters: if RadarOnly runs low, the 2.0 mm gate is CONSERVATIVE.

**Capped and insufficient Windows are already distinguishable**: `walk()` returns
`WINDOW_CAPPED` (6 days, no dry anchor) and `INSUFFICIENT_DATA` (a pad stamp missing — it
stops rather than falling through to a day it can see). Your checklist says exclude AND
count them; both states carry `walked_days` and `missing_pad` so the count is free.


### CORRECTED BY AN ADVERSARIAL REVIEW (same day, `d5e11f3`) — read this over the section above

Only items 1-3 touch what you call; item 4 is a test-shape lesson.

Six lenses raised nine findings and a skeptic pass refuted all nine. **Four were fixed
anyway, on their own merits, and two of them change the interface written above.**

1. **`detector_version` is `01197991471f`, not the `91598b86edc0` the first build printed.**
   The scoping rule is about LEAVES, not top-level keys: `display` and `*_note` were excluded
   BY NAME while `cutpoints.basis`, `cutpoints.confirmed_by`, `forcing.stamp` and
   `canary.checks` sat as pure prose INSIDE digested dicts — so fixing a typo in one of them
   moved the digest, which `rolled()` turns into a Window roll and which clears every latched
   flag mid-storm. **All human-facing strings now live under `display`** (which is not
   digested): `display.tiers`, `display.cutpoint_basis`, `display.cutpoints_confirmed_by`,
   `display.window_interval`, `display.window_states`, `display.precip_states`,
   `display.forcing_stamp`, `display.winter_label`, `display.winter_unknown_label`, beside
   the existing `display.tier_labels` / `no_complex_skill_claim` / `within_cell`. So
   `cutpoints` is now `{ELEVATED, HIGH, provisional}`, `window` drops `interval`/`states`,
   `winter` is `{freeze_c, unknown_fallback_months}`, `forcing` drops `stamp`, `vocabularies`
   drops the two state lists and `canary` is `{pattern, product}`.
   `test_the_digested_leaves_are_frozen` pins all **72** digested leaf paths, so adding a
   field inside a digested dict is a deliberate act.
2. **`cycle()` emits H3 Cell ids as HEX, and that is the whole point of `cycle` being the
   boundary.** `fd.hexcell(cell) == format(cell, "x")`, the same spelling `ref.py` writes into
   `cell:<h3>`. Every `units[].cell`, every `revisions[].cell` and every `cell_totals` KEY is
   a hex string; `state["cell_totals"]` is read back as hex. **The lower seams
   (`window_features`, `evaluate`, `tiers`, `latch`, `revisions`) keep the int64** because
   they join on it. An H3 id is past 2^53 and JSON cannot carry one.
3. **A Window with no elapsed hours reported `HOLES` / coverage 0.0.** Nothing is missing when
   nothing is expected, and a Window opens at 21:00 NY, so this painted the degrade state over
   every cycle in the first hour of every Window, nightly. Now `OK` / 1.0. (The skeptic argued
   HOLES is the safer label for an unobserved interval; recorded as a disagreement, not a
   consensus — "not yet due" is what `staleness` reports, and `coverage` should mean what it
   says.)
4. **The budget pins were mirror-pins.** `assert artifact_budget == fl.KNYC_STALE_MIN`
   compares the artifact to the module it was built FROM, so it passes whether the value is
   derived or hard-coded at the same number. A monkeypatch test now MOVES `flood_live`'s and
   `flood_truth`'s constants and asserts the artifact follows.

The five findings left unfixed were prose-substring test assertions and one docstring
wording; each was refuted with reasoning I checked and agree with.

**Test count 84. Mutation rounds: 18/18 RED on the first pass, plus 4/4 RED on the review
fixes, pristine control green both times.**

---

## DONE 2026-08-25 — the replay ran, and the verdict is [YOU]-Ross's

Branch `flood12-replay-harness`, worktree `/Users/ross/raincheck-wt/flood12`.
`make flood-replay` -> `src/raincheck/flood_replay.py` + `research/flood-12-replay.{json,md}`.
**This build did NOT touch `research/flood-11-detector.json`.** `cutpoints.provisional` is
still `true`, `confirmed_by` is untouched and `detector_version` is still `01197991471f`
— a test asserts the module cannot even name that path. Recording the verdict is Ross's
act and it bumps the digest by design, which rolls every open Window (`fd.rolled`).

### What ran

195 AORC-era union events (`day_start.year <= 2025`; 2026 has no AORC year, so its 11
events are out of this universe by arithmetic, not by choice). **133 replayed with full
evaluation** — the ones `gold/flood_matrix` has rows for — and **62 walk-only** (44
coastal, 17 mixed, 1 snowmelt: the fit universe is pluvial-only, and `density_311_3y` is a
per-(Cell, event) covariate the matrix build derives, so scoring them would be a REBUILD,
not a replay). **4,326 hourly cycles** through `fd.cycle` with the state chained exactly
as `live_loop` chains it, over the offline event window `(window_start, window_end]`.

**Excluded AND counted:** 4,250 cycles OK / **76 INSUFFICIENT_DATA** / **0 WINDOW_CAPPED**
(the six-day cap never fired on AORC). Three events carry the insufficient cycles
(2010-10-01, 2011-08-01, 2013-09-02) and **one — 2011-08-01 — has no OK cycle at all** and
contributes nothing to any number here. Those same three are the only events with no
signed feature delta, because no cycle of theirs had a live Window covering the calendar
`window_start`.

**Every OK cycle reported `coverage 1.0` and `unforced_cells 168`, and NOT ONE reported
HOLES.** That is the dark-Cell MUST paying off, visibly: had those 168 permanently dark
AORC Cells been counted as holes rather than as UNFORCED, all 4,250 cycles would have read
HOLES and the whole replay would have published the degrade state.

### The Window walk corroborates flood 11 independently

**90 of 169 events with citywide rain land exactly on the offline `window_start`**; day
deltas `-1: 58 · -2: 4 · -3: 3 · 0: 90 · +1: 10 · +2: 1 · no anchor: 3`. flood 11 measured
`89 of 166`, `-1: 56 · -2: 4 · -3: 3 · 0: 89 · +1: 10 · +2: 1 · insufficient: 3` — the same
shape on a slightly larger denominator (this universe includes the non-pluvial AORC-era
events). **Nothing was "fixed" to make the two agree**; a test asserts the calendar window
is never substituted for the live anchor.

**The signed live-minus-offline deltas say the same thing from the other side.** Over
175,630 Cells and 130 events the median of event medians is **0.0000 for all three
terms** — the arithmetic is exact and most events reproduce the offline features to the
digit. The disagreement is concentrated where the theory says it must be: 28 events have a
POSITIVE median `log1p_precip_total_mm` (a longer live Window is a larger total by
construction) and 29 have a NEGATIVE median `log1p_antecedent_mm_24h` (an earlier anchor
freezes the antecedent block earlier). 6 / 6 on the max term.

### THE FP TABLE — what the provisional cutpoints would have cost

Readout: the UNION of tiers over an event's cycles, which is what a subscriber received.
Reading only the standing set at `window_end` would have measured the morning after the
storm — Ida's last replayed cycle stands at **zero** flags with 264 mm in its peak Cell,
because the Window had already rolled.

| grain | rows | positives | base | tier | flagged | alert rate | TP | FP | POD | precision | CSI/base |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cell | 179,683 | 6,554 | 3.648% | ELEVATED+ | 23,342 | 12.99% | 2,660 | **20,682** | 0.406 | 11.40% (3.12x) | 2.68 |
| cell | | | | HIGH | 5,159 | 2.87% | 896 | **4,263** | 0.137 | 17.37% (4.76x) | 2.27 |
| bus_stop | 502,756 | 2,831 | 0.563% | ELEVATED+ | 76,165 | 15.15% | 1,032 | **75,133** | 0.365 | 1.35% (2.41x) | 2.35 |
| bus_stop | | | | HIGH | 14,521 | 2.89% | 370 | **14,151** | 0.131 | 2.55% (4.53x) | 3.87 |
| complex | 43,089 | 118 | 0.274% | ELEVATED+ | 5,214 | 12.10% | 29 | **5,185** | 0.246 | 0.56% (2.03x) | 2.00 |
| complex | | | | HIGH | 956 | 2.22% | 5 | **951** | 0.042 | 0.52% (1.91x) | 1.71 |

**flood 09's pooled out-of-fold decisions, NOT superseded** (one global cut, location-
blocked): cell 5.66% -> 2,297 TP / **7,881 FP**, POD 0.351, precision 22.6% (**6.19x**);
point **1.11% -> 381 TP / 8,295 FP**, POD 0.095, precision 4.39% (**8.57x**).

**The base-rate rule is applied and it matters here** (flood 18). The detector publishes no
entrance row, so its point universe is **bus stops** (502,756 rows, base 0.563%) while
flood 09's `per_event.point` is `fit_point` = bus stops AND entrances (783,351 rows, base
0.512%). Every rate above is divided by its own base rate; the Cell universe is identical
on both sides and needs no such care.

**WHERE THE ALERT BUDGET GOES — the finding a pooled row cannot show.** Quartiles of 33
events by positives:

* **Cell, top quartile (the events with the most flooding):** this cut alarms at **16.64%
  for POD 0.379**; flood 09's fitted cut reaches **POD 0.436 at 5.66%**. Three times the
  alarms and it catches LESS.
* **Cell, bottom quartile:** **1,514 false alarms for 11 hits**, against flood 09's **38
  for 0**.
* **bus_stop, top quartile:** 18.73% for POD 0.366 against flood 09's 0.116 — real POD,
  bought with **69,005 FP against 8,093**.
* **bus_stop, bottom quartile: 0 flags.** The two gates (own Cell >= 2.0 mm, citywide
  active) do shut: 96 of 133 events flag no bus stop at all, and 28 flag nothing anywhere.

The mechanism is structural, not a tuning miss: **a within-kind rank re-normalises to the
current vector every cycle, so it spends the same ~10% of the city on a storm that floods
nothing as on one that floods everywhere.** The eta vector knows this storm is bigger; the
rank throws that away by construction. A single global cut does the opposite.

### THE RADAR-ONLY-vs-AORC RATIO — measured, and it is a CHAIN

**A direct measurement is impossible on this root and that is arithmetic, not effort:
`src=aorc` ends 2025-12-31, `src=mrms` begins 2026-07-31, and the asset asserts the
overlap is ZERO hours.** The pair that IS on disk has never been compared before:

* **RadarOnly / Pass2 = 0.933** on **8,549 wet paired Cell-hours over 83 hours**
  (`live/precip_cell`, deduped to the newest `fetched_at`, against
  `silver/precip_cell_hourly/src=mrms`). All-pairs 0.938; median pair ratio 0.937. Both
  sides go through the SAME area-weighted `ref/cell_pixel` crosswalk with the same
  weight-sum guard, so this is the product, not the averaging.
* Pass2 / AORC = **[0.86, 0.92]**, flood 06's band via `flood_fits.SCALE_BAND`, read and
  not re-measured.
* **RadarOnly / AORC = [0.803, 0.859].** **RadarOnly runs 14-20% LOW against the forcing
  the model was fitted on, so `gates.own_cell_window_mm` = 2.0 mm of RAW RadarOnly is
  CONSERVATIVE** — a Cell needs marginally more true rain to raise a flag. flood 11 hoped
  for that direction and it holds.
* **Limit, stated:** one storm carries the wet pairs (2026-08-23, plus two hours on
  08-24). The mass-carrying hours run ~0.90 and the near-dry hours run above 1.0. This is
  a first measurement of the product ratio, not a climatology of it, and it still applies
  no band to anything.

### THE QUESTION, VERBATIM: "cutpoints confirmed, or v1 ships rank-only"

**RECOMMENDATION: v1 ships rank-only.** Four measured reasons, in order of weight.

1. **The cutpoints are the only unfitted number in the chain, and the replay says they
   cost more than the fitted one buys.** 10% / 2% within kind were chosen a priori;
   flood 09's 1.11% was the CSI-maximising cut transferred as an alert rate. At every
   grain and every cut the provisional rank is less efficient than that one operating
   point: precision lift 3.12x vs 6.19x at Cell grain, 2.41x vs 8.57x at point grain.
   Confirming would bless an unfitted cut with a measurement that shows it losing.
2. **It spends the budget on the wrong events.** POD 0.379 against 0.436 on the Cell
   quartile with the most flooding, while alarming three times as often; 1,514 false
   alarms for 11 hits on the quartile with the least. Trust in a flood product is built
   on the big events, and this cut under-covers exactly those.
3. **At complex grain a tier is a claim the artifact refuses to make.** ELEVATED+ would
   badge 5,214 complex-events for 29 hits (precision 0.56%) on a grain whose own
   disclaimer records 1 of 118 independent positives caught. `display.no_complex_skill_
   claim` and a complex badge cannot both ship.
4. **The rank is the part that IS validated, and rank-only costs nothing downstream.**
   flood 18 measured that ranks survive the base-rate moves that reverse raw-CSI
   orderings; the cutpoints were never in that evidence. notify 08's box already requires
   its policy to survive the tiers vanishing, and flood 15 reads `cutpoints.provisional`
   at render time — so rank-only blocks nothing in wave 6.

**The honest counter-case, so the call can be overruled with open eyes.** If a badge must
ship in v1, **HIGH alone at CELL grain** is the only cut this measurement supports: 2.87%
alert rate, 896 hits, **4,263 false alarms — fewer in absolute terms than flood 09's own
7,881** — precision 17.37%, lift 4.76x against the fitted cut's 6.19x. It should not be
extended to bus stops (2.55% precision, 38 false alarms per hit) and must not be extended
to complexes. ELEVATED is not defensible at any grain on these numbers.

**Either way `detector_version` bumps and every open Window rolls. That is correct and it
is the point.** notify 08 and flood 15 read the outcome from
`research/flood-11-detector.json` at run time; nobody re-types it.

### Four limits of this replay, named rather than buried

1. **The revision log is UNEXERCISED: 0 revisions across 4,250 cycles.** AORC is a
   reanalysis and never revises its series, so `fd.revisions` and the
   "a downward revision never clears a flag" rule got no live exercise here. The live
   RadarOnly product DOES revise. That path is tested only by flood 11's unit tests.
2. **The winter gate ran on a SUBSTITUTED observation.** Live it consumes flood 14's
   Central Park (KNYC) reading and there is no KNYC history on this root, so the replay
   passes the citywide MEDIAN AORC `t2m_c` for the hour. 20 events had at least one
   suppressed cycle. The alternative — passing nothing — would fall back to the calendar
   and suppress every snowmelt-month event whether or not it was freezing.
3. **62 of 195 AORC-era events are walk-only** (above). Their Window walks are in the
   `window_agreement` numbers; none of their units are in any skill number.
4. **The forcing ratio rests on one storm** (above).

### For whoever replays this function next (notify 11, wave 7)

    from raincheck import flood_replay as fr, flood_detect as fd, duck
    evs  = fr.events(con, root)              # AORC-era events; `in_matrix` False = walk-only
    wet  = fr.citywide(con, root, lo, hi)    # {hour_end: wet Cell COUNT}, the WHOLE grid
    temp = fr.temps(con, root, lo, hi)       # {hour_end: citywide median t2m_c}
    byh  = fr.cell_rows(con, root, lo, hi)   # {hour_end: [row]}, NULL rows KEPT
    us   = fr.units(con, root, event_id)     # gold/flood_matrix's rows + `flooded`
    r    = fr.replay(ev, wet, temp, byh, us, art, det, score_version)
    rows = fr.slice_rows(byh, anchor, now)   # a LIST — cycle() reads it TWICE

**A TRAP WORTH THE WHOLE TICKET: `fd.cycle` iterates `cell_hours` TWICE** — once for the
newest stamp, then again inside `window_features`. Hand it a generator and the first pass
exhausts it, the Window comes back with **no Cells, coverage 1.0 and nothing flagged**, and
it is indistinguishable from a quiet night. It cost this build one wrong 54-cycle table
before the trace showed Ida flagging zero units with 264 mm on the ground.

**Tests: `tests/test_flood_replay.py`, 38 defs; `tests/test_flood_detect.py` unchanged at
84. Mutation round 14/14 RED, pristine control green before and after.** The first round
lied — zsh does not word-split an unquoted `$VAR`, so `git checkout -- $PATHS` treated the
whole string as one pathspec, the restore was a silent no-op and mutants accumulated; the
pristine control caught it (TRAPS already carries that shape from orch 04). The harness now
uses a zsh ARRAY, refuses a dirty tree, snapshots from git, `git clean`s as well as checks
out, asserts `git status --porcelain` is EMPTY after every restore, and exports
`PYTHONDONTWRITEBYTECODE=1`. Two survivors were closed rather than explained: folding
ELEVATED into the HIGH row (the two rows are nested and NOT equal), and reading the standing
set at `window_end` instead of the union over cycles (`r["end_flagged"]` is published so
that claim can be checked rather than believed).
