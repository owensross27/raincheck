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
