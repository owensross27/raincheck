# 08 — Flood tiers and the impact overlay go live

**What to build:** the map's flood half lights up: FloodNet water-now sensors
(aqua; dry/stale sensors as hollow rings), MTA affected-station dots on the
COMPLEX (amber, radius 7, coordinates from the tier payload), and flood 17's
impact overlay joining the exclusive Cell-fill radio (no ramp of its own, no
simultaneous fill — structurally impossible, as decided). The lineage gate
runs through the flood panel: the page reads TWO meta files, one per gate
side, so the MTA-derived tier stays dark on its own key while the FloodNet
side serves — and freshness rows for these sources graduate from AGE to
FRESH/STALE using the budget constants flood 15/17 froze.

**Blocked by:** 05 (chassis) + **flood 15** (panel exports: two meta files,
chip complex-coordinates, budget constants — MUSTs already on its line) +
**flood 17** (impact overlay data; consumes the no-own-ramp rule already on
its line). Wave 7+ territory; check both completion entries in the RUN LOG
before starting. The MTA-side layers additionally stay GATED until the [YOU]
terms receipt — build them gate-aware, do not wait for the receipt.

**Status:** ready-for-agent (gated)

- [ ] The radio's second option (impact) works both directions; delay XOR
      impact pinned by a mutation-checked test
- [ ] Two-meta lineage: killing one gate side darkens exactly its layers and
      flips exactly its freshness rows; the other side is untouched (tested
      both directions)
- [ ] Hollow-ring vs filled sensor vs dimmed vehicle are distinct at render
      scale; the three-meanings-one-grey failure is a red test
- [ ] Budgeted sources now render FRESH/STALE from the frozen constants —
      never from guessed thresholds; unbudgeted remainder still says AGE
- [ ] Fixtures verbatim from flood 15/17's landed schemas; stub fidelity
      mutation-checked
- [ ] Own-module tests only; page-as-data seam extended, not forked
