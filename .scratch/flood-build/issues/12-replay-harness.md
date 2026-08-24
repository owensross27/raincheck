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
