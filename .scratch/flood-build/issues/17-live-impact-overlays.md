# 17 — Live impact overlays: consequence beside cause

**What to build:** The bus and subway impact overlays on the flood panel — Cell-grain bus slowdowns and
complex-grain subway service beside the detector, labelled "impact — never a detector input",
rendered when present and greyed when absent. Spec: Impact signals (live), Real-time detector
(serving); Testing seam 3.

**Blocked by:** 15, 16 — and externally on the pipeline build: 12 (streaming job) + 14 (live export) for bus Gold, and the pipeline wayfinder's ticket-15 TU capture for subway; the overlay renders greyed until each lands, by design

**Status:** ready-for-agent

- [ ] the bus overlay file at Cell grain and the subway overlay file at complex grain, keyed on (Cell | complex, hour_end_utc), showing the last CLOSED Hour; rendered when present, greyed when absent, labelled "impact — never a detector input"; bus stops take the Cell fallback; never two kinds in one legend
- [ ] the conditional live-bus baseline build item activates: cell_hourofweek_baseline over a 2026-era window — never the backfill-era baselines; capture-era baselines accumulate from capture days; ratios NULL until at least two same-weekday baselines exist
- [ ] subway live: the TU-capture stop-row-disappearance inference pass, level-compared against subwaydata on overlapping days BEFORE any cross-source display (Precip-source-style discipline — sources never pooled)
- [ ] export-file seam tests: overlay files parse, absent hours grey rather than zero, the impact label renders from file data

## Inherited from frontend 02 (prototype, `4ac3ebe`, 2026-08-24) — measured against `gold/cell_hour_speed`

Frontend 02 built your bus overlay from `gold/cell_hour_speed` (your own input) because your
two export files do not exist yet, and measured two things you inherit:

- [ ] **Your grain is sparse at the head, and the panel has to say so.** The NEWEST closed
  hour in `gold/cell_hour_speed` carries **24 Cells**; the densest carries **1,169**. An
  overlay that renders "the last closed hour" will usually be a near-empty map. Painting 24
  Cells without saying they are 24 reads as a claim about the city.
- [ ] **You land on the SAME ~1,200 H3 Cells the delay layer already fills**, so a second
  Cell FILL is a direct collision on one geography. Frontend 02's variations resolve it
  either by making the fill channel EXCLUSIVE (the two are the same quantity — a Speed ratio
  — at different time-scales, so they share one frozen ramp) or by moving this overlay to
  the Cell OUTLINE channel. **Do not assume you get the fill**; the choice is Ross's on
  frontend 02 and it decides your paint channel.
- [ ] **Name your two export files and their keys in the close-out** — nothing in the tree
  freezes either today (prose only, no code). Same as flood 15's third bullet.
