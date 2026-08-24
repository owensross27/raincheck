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
