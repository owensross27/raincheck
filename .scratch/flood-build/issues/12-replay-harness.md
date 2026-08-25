# 12 — Replay harness: the live rules against history

**What to build:** The AORC-era spine replayed through the live Window walk and evaluation, publishing
signed live-minus-offline feature deltas and per-event flag volumes — the measurement that
confirms the tier cutpoints or drops v1 to rank-only before the panel faces a real storm.
Spec: Real-time detector (tiers, logging/replay); Testing seam 2.

**Blocked by:** 06, 11 — and externally on the pipeline build: 11 (live-precip job, as amended: each tick catches up every missing :00 stamp within MRMS's measured ~25 h retention; replay of any live-era Window is conditional on that catch-up)

**Status:** ready-for-agent

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
