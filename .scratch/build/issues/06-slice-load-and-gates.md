# 06 — Slice load and acceptance gates: 124 files, W1/W2, the Ida reproduction

**What to build:** The two-window slice is converted, enriched and rolled up end to end on this Mac, and the
project's one gated acceptance test passes: the loader and rules alone reproduce the Ida
slowdown. Also produces the report-only benchmarks against MTA's published speeds and the
Product 3 raster comparison. Precondition (operator): external SSD mounted, the data root
pointing at it, and the archiver's byte budget set to a drive-sized number before the first
conversion. Spec: E, G, I, M steps 1-3; Testing tier 2.

**Blocked by:** 03, 05

**Status:** ready-for-agent

- [ ] all 124 archive files converted (2021-08-16..10-16, 2023-09-01..11-01) with 10-T1 green on each; `events DATE=` run for the 122 service days; `gold MONTH=` for the five months; `baseline WINDOW=` for W1 and W2
- [ ] 10-T3 passes: for each Ida hour ending 2021-09-02T03Z and 04Z, the citywide space-mean chord Speed divided by the median of the same citywide same-hour-of-week value over the other eight weeks of W1 (each control hour < 0.1 mm citywide in precip_cell_hourly src=aorc) is <= 0.85 with n_legs >= 15,000; the denominator is computed from cell_hour_speed, never from the baseline table; 02Z and the 2023 hours are printed, not gated
- [ ] 10-T6 printed: ~1,146 footprint Cells per day, 0 Legs in AORC-NULL Cells, n_dropped_terminal share within 0.01 storm vs control in the T3 hours
- [ ] 10-T4 report written: W2 route x day-of-week x hour vs Socrata 58t6-89vi (trip-weighted recombination) and both windows route x month x day_type vs cudb-vcni (sum(miles)/sum(hours)); ratio distribution and Spearman rank agreement with the known biases named; no gate set
- [ ] 10-T5 one-off script over the two storm days: RS_Values at the Leg midpoint vs the Cell mean, rain-vs-Speed slope both ways, reported into the 08 evidence notes
- [ ] runtime and disk of the slice recorded (conversion minutes per file, Bronze/Silver/Gold bytes) in the ticket's closing comment
