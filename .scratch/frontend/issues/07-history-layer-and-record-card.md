# 07 — The history layer and the record card

**What to build:** a viewer toggles on flood-history markers (violet, one per
asset with a record), clicks any of them — stop, Cell, or complex — and the
asset's flood record opens in a card that SHARES the right column with the
layer panel (flex shrink, never floating, never covering the freshness rows):
title with the id fallback for unnamed Cells, kind + id, event count, label
version, the last events newest-first with their class/cause/source-counts/
support, and the "counts are city-wide at EVENT grain" caveat. Paint comes
from notify 05's manifest (one bulk file, WITH coordinates); detail is one
per-asset fetch on click, dated reader-side, sized on the recorded tail
(~23 KB max), edge-cached.

**Blocked by:** 05 (the chassis declares the layer) + **notify 05** (the
static per-asset surface, whose manifest carries lon/lat and a freshness
budget — MUSTs already on its summary line). Wave 7 territory; check notify
05's completion entry in the RUN LOG before starting.

**Status:** ready-for-agent (gated)

- [ ] Marker layer paints from the manifest only; no per-asset fetch happens
      before a click (tested — the network discipline IS the payload rule)
- [ ] The card is in-column; a hit-test proves it never covers the freshness
      rows or the provenance strip at 375px and at desktop widths
- [ ] Unnamed assets render the id fallback; the "null"-title failure is a
      red test
- [ ] Click, not hover (touch parity); keyboard reachable; focus returns to
      the marker's toggle row on close
- [ ] Fixtures cut verbatim from notify 05's landed schema; stub fidelity
      mutation-checked
- [ ] Own-module tests only; page-as-data seam extended, not forked
