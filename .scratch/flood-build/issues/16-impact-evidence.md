# 16 — Impact evidence: what the floods did to service

**What to build:** The offline impact record — subway service_ratio and max_gap_ratio at complex grain
from subwaydata.nyc, bus Speed ratios from the existing Gold — joined to event windows as
evidence, never as features, with the coverage honesty published. Spec: Impact signals; Testing
seam 1 for the aggregates' contracts.

**Blocked by:** 01, 04

**Status:** ready-for-agent

- [ ] subway: service_ratio and max_gap_ratio at complex grain from subwaydata.nyc per-day CSVs — trip-start-keyed, so hours 00–05 union the previous day's file (94% undercount otherwise); route-mix residuals and same-line neighbor controls accompany any flood attribution
- [ ] fixture assertion: on 2023-09-29 the combined metrics catch 5/7 of the extractor-flagged complexes
- [ ] bus: Speed ratios from the existing Gold Cell-hour tables and their window baselines, sums-merged
- [ ] coverage honesty published: subway covers 35/115 union event days, bus 6/115, 70% have neither
  - CORRECTION (2026-08-23, orchestrator): the 115-day figure is superseded by flood-04's
    landed spine — 206 events / 248 event-days (2010-03-13..2026-08-20). The 35/6/70%
    fractions were computed against the old universe; recompute all three against
    silver/flood_events at build time (same supersede recorded on 05 and 09 in e4444ad).
- [ ] no new Silver table — corpus aggregates are build assets; subwaydata snapshots live outside the archive root (never cold-pushed) and derived numbers are local-page-only (license not found)
- [ ] impact is evidence/display ONLY — asserted absent from ticket 08's matrix and never a detector input
