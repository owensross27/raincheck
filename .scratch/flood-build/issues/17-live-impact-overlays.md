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
