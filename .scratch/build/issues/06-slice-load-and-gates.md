# 06 — Slice load and acceptance gates: 124 files, W1/W2, the Ida reproduction

**What to build:** The two-window slice is converted, enriched and rolled up end to end on this Mac, and the
project's one gated acceptance test passes: the loader and rules alone reproduce the Ida
slowdown. Also produces the report-only benchmarks against MTA's published speeds and the
Product 3 raster comparison.

**Precondition changed 2026-08-22 (Ross; ticket 18 scope change):** there is no external
SSD and will not be one — the SSD/RAINCHECK_ARCHIVE_ROOT precondition is dead. Replacement:
**disk headroom verified + cold storage landed** (either arm suffices to start the load).
Low-disk rules for the slice runner: process day-by-day; delete each nycbuspositions xz
immediately after its Bronze day converts and its T1 passes (re-downloadable; deletion
strictly follows a green T1, so a converted day with no xz counts as verified on resume);
keep only Silver/Gold plus Bronze not yet pushed to ticket 18's bucket; the driver refuses
to start without headroom for the remaining peak footprint. `--keep-xz` retains sources
for the bucket push. Spec: E, G, I, M step 3; Testing tier 2.

**Blocked by:** 03, 05

**Status:** loaded — one open call (T6 terminal gate threshold), see closing comment

- [x] all 124 archive files converted (2021-08-16..10-16, 2023-09-01..11-01) with 10-T1 green on each; `events DATE=` run for the 122 service days; `gold MONTH=` for the five months; `baseline WINDOW=` for W1 and W2
- [x] 10-T3 passes: for each Ida hour ending 2021-09-02T03Z and 04Z, the citywide space-mean chord Speed divided by the median of the same citywide same-hour-of-week value over the other eight weeks of W1 (each control hour < 0.1 mm citywide in precip_cell_hourly src=aorc) is <= 0.85 with n_legs >= 15,000; the denominator is computed from cell_hour_speed, never from the baseline table; 02Z and the 2023 hours are printed, not gated
- [ ] 10-T6 printed: ~1,146 footprint Cells per day, 0 Legs in AORC-NULL Cells, n_dropped_terminal share within 0.01 storm vs control in the T3 hours
- [x] 10-T4 report written: W2 route x day-of-week x hour vs Socrata 58t6-89vi (trip-weighted recombination) and both windows route x month x day_type vs cudb-vcni (sum(miles)/sum(hours)); ratio distribution and Spearman rank agreement with the known biases named; no gate set
- [x] 10-T5 one-off script over the two storm days: RS_Values at the Leg midpoint vs the Cell mean, rain-vs-Speed slope both ways, reported into the 08 evidence notes
- [x] runtime and disk of the slice recorded (conversion minutes per file, Bronze/Silver/Gold bytes) in the ticket's closing comment

---

## Closing comment (2026-08-22, agent)

**Load.** `make slice` ran end to end on this Mac in low-disk mode, surviving one
sleep and one machine crash via resume-at-every-stage (converted days and built
`leg_hours` partitions skip; staging junk is inert). Runtime: conversion ~3-5 s per
file (~10 min for all 124, dominated by download; the ~1 min/file estimate was 10x
pessimistic), events 11-16 s per day (~25 min for 122 days across the interrupted
runs; a clean run's stage timings: convert walk 0.4 min cached, final 62 events
days 5.2 min, gold+baseline 0.4 min). Disk: archive/vp 2.83 GB, silver/leg_hours
0.26 GB (vs 0.7 GB estimated), gold 0.19 GB; peak headroom never threatened
(gate passed at 8.2 GB free initially, 51.6 GB after the crash-reboot purged APFS
snapshots). All 124 files T1 green; xz sources deleted after green T1 per the
low-disk rule.

**10-T3 (gated): PASS.** 03Z ratio 0.760 (n_legs 27,051, 8 controls), 04Z 0.716
(n_legs 20,694, 7 controls) vs gate <= 0.85 — and vs the research's measured
0.77/0.73. Report hours behave as researched: 2023-09-29 hours 0.90-0.97 (weak,
heterogeneous), Ida 02Z/06Z/08Z printed.

**10-T6: 2 of 3 pass; terminal-drop sub-gate FAIL, cause diagnosed.** Footprint
1,141 Cells/day (expect ~1,146); AORC-NULL legs 0 [PASS]. Terminal-drop share
storm 0.0690 vs control 0.0802, |diff| 0.0112 > 0.01 [FAIL]. Diagnosis: the
implementation faithfully reproduces the research's calibration contrast (research
10-backfill-slice-and-speed.md:215 measured Ida 04Z 6.7% vs adjacent dry week
7.2%; production measures 6.59% and 7.18% for the same hours). The gate however
pools 2 storm hours vs all 16 dry control hours, and per-hour measurement shows
the research's control hour is the *lowest* of the sixteen (pool runs 7.2-8.6%,
no outlier week), widening the pooled diff to 1.1 points. The gap is uniform and
physically real (run completion collapses during the flood peak; the research's
never-flip evidence 4.4% vs 1.1%). Immaterial to T3 (~1-point composition shift
vs the sensitivity table's <= 3% bound on all rule variants and T3's 9-13 point
margins). **Open call for Ross** — options: (a) widen pooled gate to <= 0.02
(recommended: still catches the R0/R1 pathology's 6.5-point gap at 3x margin);
(b) adjacent-dry-week contrast at 0.01 (matches the calibration evidence, passes
today at 0.0086/0.0059, fragile when that week is wet); (c) report-only.

**10-T4 (report-only): strong.** A (W2 route x DOW x hour vs 58t6-89vi): n=43,769
matched keys, ratio p50 0.864 (p10 0.735, p90 0.941), Spearman 0.952 across 340
routes. B (route x month x day_type vs cudb-vcni): n=2,914, p50 0.871, Spearman
0.969 across 333 routes. Medians sit where the named biases predict (chord -7..-15%).
Report: research/10-t4-benchmark-report.md. (First execution caught a GROUP BY
alias syntax error the static review missed — fixed with GROUP BY ALL.)

**10-T5 (report-only): the rain join is validated.** Pixel-at-midpoint vs Cell
mean mm: corr 0.9999 (Ida) / 0.9995 (2023), p50 delta 0.03 mm. Speed-vs-rain
slope identical both ways: -0.0146 vs -0.0147 m/s per mm (Ida, r=-0.13);
-0.0402 both ways (2023, r=-0.10). The Cell crosswalk loses nothing vs direct
raster sampling.
