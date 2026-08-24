# flood-09 — fits, baselines, validation, and the headline gate

`fits_version` **8050dfa41fc1** over `matrix_version` **8bc1e8912b1b**.
Estimand: **flooded_reported** — where flooding was REPORTED, not where water necessarily stood.

Two L2 logistic fits (point, cell), unweighted, lambda by inner CV; four baselines; two
deterministic sha1 group splits; every published number is OUT OF FOLD. The operating point
is chosen IN FOLD — the CSI-maximising cut on that fold's training rows — and what transfers
to the held-out rows is its ALERT BUDGET, applied as a quantile of the held-out scores (no
held-out label is read). Transferring the raw probability instead is published as a sweep
row; it moves nothing here, and it is what stops a constant-scored baseline from reading
CSI 0.0 for a reason that is about its score's scale rather than about the baseline.

## HEADLINE GATE — location_blocked: **MODEL**

| role | model CSI | B2 CSI | B3 CSI | beats B2 | beats B3 | SHIPPED |
|---|---|---|---|---|---|---|
| cell | 0.1591 | 0.0365 | 0.0819 | yes | yes | `cell:l2_logistic` |
| point | 0.0310 | 0.0051 | 0.0130 | yes | yes | `point:l2_logistic` |

The gate is a pure function of the table above (`flood_fits.gate`), re-evaluable from the
published JSON — so whichever branch fired is CHECKABLE rather than remembered. The checking
itself is owed downstream: ticket 10 builds the release artifacts and is where the assertion
lands. Nothing in this repo asserts it today. The branch also SELECTS THE STRINGS, which is the spec's
if-the-baseline-wins-ship-the-baseline clause carried through to the panel: headline
"modelled flood exposure", caveat "fitted on reported flooding, 2010-2025 rain events", release
"v1 ships the fitted L2 logistic exposure score" (`gate.panel_strings` in the JSON; ticket 15 and notify 09
render them, and `flood_fits.PANEL_STRINGS` holds the alternates the other branches select).

**Read B2 under this split with its degeneracy in mind:** location blocking puts every
held-out Unit's entire history inside the held-out fold, so B2 has no in-fold history for
any Unit it scores and falls back to the training prior — under this split B2 IS the base
rate. That is what the split is for, and it is why the event-grouped column below (where
B2 keeps its history and is a real competitor) is published beside it.

## cell model

179,683 rows · 6,554 positives · base rate 3.648% ·
133 events · 1,351 Units · 1,351 Cells.
By kind: cell 179,683/6,554 pos.

### event_grouped (primary)

| model | CSI | CSI 95% CI | POD | FAR | PR-AUC | TP | FP | FN | alert rate |
|---|---|---|---|---|---|---|---|---|---|
| **L2 logistic (this ticket's fit)** | 0.1516 | 0.110-0.193 | 0.326 | 0.779 | 0.1935 | 2136 | 7536 | 4418 | 0.0538 |
| B0 base rate | 0.0365 | 0.029-0.045 | 1.000 | 0.964 | 0.0331 | 6554 | 173129 | 0 | 1.0000 |
| B1 precip-only | 0.0844 | 0.058-0.114 | 0.295 | 0.894 | 0.1019 | 1931 | 16319 | 4623 | 0.1016 |
| B2 unit climatology | 0.0827 | 0.070-0.096 | 0.278 | 0.895 | 0.0938 | 1824 | 15503 | 4730 | 0.0964 |
| B3 density-only | 0.0801 | 0.065-0.097 | 0.282 | 0.899 | 0.0947 | 1848 | 16512 | 4706 | 0.1022 |

### location_blocked (the gate's split)

| model | CSI | CSI 95% CI | POD | FAR | PR-AUC | TP | FP | FN | alert rate |
|---|---|---|---|---|---|---|---|---|---|
| **L2 logistic (this ticket's fit)** | 0.1591 | 0.117-0.203 | 0.350 | 0.774 | 0.2030 | 2297 | 7881 | 4257 | 0.0566 |
| B0 base rate | 0.0365 | 0.029-0.045 | 1.000 | 0.964 | 0.0351 | 6554 | 173129 | 0 | 1.0000 |
| B1 precip-only | 0.1026 | 0.071-0.136 | 0.399 | 0.879 | 0.1125 | 2614 | 18929 | 3940 | 0.1199 |
| B2 unit climatology | 0.0365 | 0.029-0.045 | 1.000 | 0.964 | 0.0351 | 6554 | 173129 | 0 | 1.0000 |
| B3 density-only | 0.0819 | 0.066-0.100 | 0.328 | 0.902 | 0.0968 | 2149 | 19678 | 4405 | 0.1215 |

CSI reference band: published FIM systems run **0.26-0.45**. The
comparison is ORDER-OF-MAGNITUDE ONLY — those systems predict inundation extent from
hydraulics against a different estimand (water present), on a different support, at a
different positive rate. It is a sanity band, never a target and never a claim of parity.

## point model

783,351 rows · 4,008 positives · base rate 0.512% ·
133 events · 15,430 Units · 1,007 Cells.
By kind: bus_stop 502,756/2,831 pos, entrance 280,595/1,177 pos.

### event_grouped (primary)

| model | CSI | CSI 95% CI | POD | FAR | PR-AUC | TP | FP | FN | alert rate |
|---|---|---|---|---|---|---|---|---|---|
| **L2 logistic (this ticket's fit)** | 0.0286 | 0.014-0.041 | 0.084 | 0.958 | 0.0207 | 336 | 7725 | 3672 | 0.0103 |
| B0 base rate | 0.0051 | 0.003-0.007 | 1.000 | 0.995 | 0.0045 | 4008 | 779343 | 0 | 1.0000 |
| B1 precip-only | 0.0173 | 0.006-0.023 | 0.155 | 0.981 | 0.0157 | 620 | 31732 | 3388 | 0.0413 |
| B2 unit climatology | 0.0340 | 0.021-0.048 | 0.112 | 0.953 | 0.0191 | 448 | 9172 | 3560 | 0.0123 |
| B3 density-only | 0.0132 | 0.007-0.021 | 0.083 | 0.985 | 0.0083 | 334 | 21363 | 3674 | 0.0277 |

### location_blocked (the gate's split)

| model | CSI | CSI 95% CI | POD | FAR | PR-AUC | TP | FP | FN | alert rate |
|---|---|---|---|---|---|---|---|---|---|
| **L2 logistic (this ticket's fit)** | 0.0310 | 0.017-0.038 | 0.095 | 0.956 | 0.0231 | 381 | 8295 | 3627 | 0.0111 |
| B0 base rate | 0.0051 | 0.003-0.007 | 1.000 | 0.995 | 0.0050 | 4008 | 779343 | 0 | 1.0000 |
| B1 precip-only | 0.0213 | 0.001-0.027 | 0.162 | 0.976 | 0.0173 | 648 | 26427 | 3360 | 0.0346 |
| B2 unit climatology | 0.0051 | 0.003-0.007 | 1.000 | 0.995 | 0.0050 | 4008 | 779343 | 0 | 1.0000 |
| B3 density-only | 0.0130 | 0.007-0.020 | 0.090 | 0.985 | 0.0087 | 361 | 23702 | 3647 | 0.0307 |

CSI reference band: published FIM systems run **0.26-0.45**. The
comparison is ORDER-OF-MAGNITUDE ONLY — those systems predict inundation extent from
hydraulics against a different estimand (water present), on a different support, at a
different positive rate. It is a sanity band, never a target and never a claim of parity.

## Complex grain — the independent validation set

A complex is never fitted. Its score is the max over its child entrances' out-of-fold
scores and it alarms when any child alarms at that child's own in-fold operating point, so
the alert-sourced complex-event pairs never touch training.

| split | pairs | positives | events | CSI | CSI 95% CI | POD | FAR | PR-AUC | pairs without children |
|---|---|---|---|---|---|---|---|---|---|
| event_grouped | 43,089 | 118 | 97 | 0.0108 | 0.003-0.018 | 0.034 | 0.984 | 0.0055 | 0 |
| location_blocked | 43,089 | 118 | 97 | 0.0025 | 0.000-0.009 | 0.008 | 0.996 | 0.0057 | 0 |

At a matched ALERT BUDGET instead of the union rule — alarm the top
1.11% of complex-event pairs by max score, the
same in-fold budget the row-grain metrics use — the same set reads CSI
0.0034 (POD 0.017,
TP 2 of 118). The best single
cut anyone could have chosen ON this set reaches 0.0094 —
printed for scale, not a result, and not an upper bound on the union rule (which cuts per
fold and can beat any one global cut).

The measured complex label count is **118** pluvial fit-era pairs
— the drafted 155 was superseded by flood 08's measurement against the landed labels.

**Read this set as the ticket intended it — as the independent check, and as the weakest
number here.** The point model was fitted on 311/FloodNet/HWM-derived labels at doorway
grain; these pairs are MTA-alert-derived at complex grain, and nothing about them entered
training. The result is a PR-AUC of 0.0057 against a base rate of
0.0027 — a lift, but a small one, and the
operating point that works at row grain barely alarms here. Whatever ships, a complex-grain
number is not a validated claim on this evidence.

## Per-event POD and raw false-positive count

Per-event CSI is NOT published: the positives per event are too thin for it to mean
anything. Measured on this matrix — cell: 7 of 133 events with a positive have exactly one; point: 6 of 100 events with a positive have exactly one. complex: 55 of
71 — the grain where the drafted "61% of events are
single-positive" was closest to true, and still not what it said. All three counts are
measured here and superseded it. The full per-event table is in the JSON; the ten events
with the most positives:


**cell** (location_blocked)

| event | positives | TP | raw FP | POD |
|---|---|---|---|---|
| `2025-10-30` | 440 | 267 | 148 | 0.607 |
| `2021-09-01` | 354 | 334 | 543 | 0.944 |
| `2023-09-29` | 299 | 245 | 400 | 0.819 |
| `2017-05-05` | 176 | 79 | 199 | 0.449 |
| `2014-02-13` | 173 | 11 | 16 | 0.064 |
| `2021-08-21` | 167 | 151 | 573 | 0.904 |
| `2023-04-30` | 166 | 58 | 167 | 0.349 |
| `2014-12-09` | 164 | 61 | 155 | 0.372 |
| `2013-05-08` | 153 | 47 | 98 | 0.307 |
| `2019-07-22` | 128 | 84 | 338 | 0.656 |

**point** (location_blocked)

| event | positives | TP | raw FP | POD |
|---|---|---|---|---|
| `2025-10-30` | 743 | 52 | 167 | 0.070 |
| `2023-09-29` | 385 | 55 | 467 | 0.143 |
| `2021-09-01` | 328 | 195 | 5715 | 0.595 |
| `2021-08-21` | 189 | 48 | 969 | 0.254 |
| `2023-04-30` | 166 | 2 | 14 | 0.012 |
| `2025-07-31` | 130 | 5 | 21 | 0.038 |
| `2025-12-19` | 120 | 0 | 2 | 0.000 |
| `2021-10-26` | 112 | 8 | 134 | 0.071 |
| `2025-07-14` | 103 | 3 | 144 | 0.029 |
| `2024-03-23` | 95 | 4 | 179 | 0.042 |

## Contrasts

### History covariate, cell (location_blocked)

CSI **0.1591** with the own-source 311 trailing density, **0.1343**
without it (delta +0.0248). The contrast reports under the
location-blocked split by design: it is the split that asks whether the history term
generalises to neighbourhoods the fit never saw, rather than whether it memorises the ones
it did.

### Pre/post-2014, cell (location_blocked)

| era | rows | positives | events | CSI | POD | FAR | realized alert rate |
|---|---|---|---|---|---|---|---|
| pre_2014 | 28,371 | 1033 | 21 | 0.0818 | 0.193 | 0.876 | 0.0564 |
| post_2014 | 151,312 | 5521 | 112 | 0.1748 | 0.380 | 0.755 | 0.0567 |

Same caveat as any masked row here: one budget is spent over the whole population, so the
two eras alarm at different realized rates and the CSI gap carries that as well as the
confound below.
CONFOUND, stamped on the split: LABEL AVAILABILITY, not physics: the sources that mint positives do not reach back equally. Bus stops enter the universe in 2020 (flood 05's era rule), so every pre-2014 row here is an entrance or a Cell, and the 311/DEP record itself thins with age. A pre/post gap is at least as much a difference in who was reporting as a difference in what flooded.

### Bus-stop churn delta, point (location_blocked)

| cut | CSI | realized alert rate |
|---|---|---|
| pooled fit, all point rows | 0.0310 | 0.0111 |
| pooled fit, scored on entrance rows only | 0.0152 | 0.0111 |
| pooled fit, scored on bus rows only | 0.0341 | 0.0111 |
| fit WITHOUT any bus row, scored on entrance rows | 0.0129 | 0.0126 |

**Every subset row here is CUT ON THE ROWS IT SCORES** — each fold spends its declared
in-fold budget within the subset, which is why the realized rates in the last column sit
close together. That is deliberate: with one cut spread over the whole point population the
two arms of the churn delta landed at 0.43% and 1.26%, and CSI is monotone in alert rate at
a 0.5% base rate, so the delta would have been measuring the budget. The top row (all point
rows) is the operational read — one deployed cut over everything — and the rate column is
what lets the two readings be told apart.
502,756 bus rows, 2,831 positives, 44 events.
the original churn sensitivity — refit on the bus-stop registry as it stood in each era — is DROPPED: no historical Picks exist locally (flood 08's build), so the era restriction is all there is. What is published instead is the delta between the pooled fit and the same fit without any bus row.

**The symmetry any bus-stop sentence has to carry:** running the positives through
`flood_labels.pairable()` dropped **4,069 of 14,749** pluvial fit-era positives,
against **2,831** bus-stop positives KEPT. All three are read off the matrix's own
metadata rather than typed here: `matrix_gates.positives_dropped_unpairable`,
`matrix_census.candidates - matrix_census.negatives + that drop`, and
`census.point.by_kind.bus_stop.positives`. The one number this asset cannot re-derive —
**4,068** of the drop being pre-2020 bus stops — is flood 08's measurement, quoted here as
inherited, not as measured by this run. The same era rule already deletes
those rows' negatives, so this is a symmetry rather than a loss; but every base rate and
every bus-stop number above is computed on the kept side of it.

### Pre/post-2014, point (location_blocked)

| era | rows | positives | events | CSI | POD | FAR | realized alert rate |
|---|---|---|---|---|---|---|---|
| pre_2014 | 44,016 | 182 | 21 | 0.0032 | 0.005 | 0.992 | 0.0030 |
| post_2014 | 739,335 | 3826 | 112 | 0.0317 | 0.099 | 0.956 | 0.0116 |

Same caveat as any masked row here: one budget is spent over the whole population, so the
two eras alarm at different realized rates and the CSI gap carries that as well as the
confound below.
CONFOUND, stamped on the split: LABEL AVAILABILITY, not physics: the sources that mint positives do not reach back equally. Bus stops enter the universe in 2020 (flood 05's era rule), so every pre-2014 row here is an entrance or a Cell, and the 311/DEP record itself thins with age. A pre/post gap is at least as much a difference in who was reporting as a difference in what flooded.

## Sensitivity sweeps — one at a time around the frozen primary


**cell** (location_blocked, lambda held at the modal CV choice)

| config | CSI | delta CSI | POD | FAR | PR-AUC |
|---|---|---|---|---|---|
| REFERENCE: the primary at the frozen modal lambda=100.0 | 0.1591 | +0.0000 | 0.350 | 0.774 | 0.2030 |
| lambda=0.01 | 0.1553 | -0.0038 | 0.339 | 0.777 | 0.2022 |
| lambda=0.1 | 0.1553 | -0.0039 | 0.339 | 0.777 | 0.2022 |
| lambda=1.0 | 0.1553 | -0.0038 | 0.339 | 0.777 | 0.2022 |
| lambda=10.0 | 0.1560 | -0.0032 | 0.341 | 0.777 | 0.2023 |
| lambda=100.0 | 0.1591 | +0.0000 | 0.350 | 0.774 | 0.2030 |
| lambda=1000 (beyond the selection grid) | 0.1570 | -0.0021 | 0.345 | 0.776 | 0.2016 |
| drop precip_max_1h | 0.1517 | -0.0074 | 0.407 | 0.805 | 0.1953 |
| drop precip_total | 0.1453 | -0.0139 | 0.287 | 0.772 | 0.1907 |
| drop antecedent_24h | 0.1586 | -0.0005 | 0.351 | 0.776 | 0.2030 |
| drop stormwater_shares | 0.1431 | -0.0160 | 0.383 | 0.814 | 0.1839 |
| drop history_311_density | 0.1343 | -0.0248 | 0.346 | 0.820 | 0.1664 |
| operating point: in-fold threshold (not in-fold alert rate) | 0.1586 | -0.0005 | 0.350 | 0.775 | 0.2030 |
| weighted 1/fan-out — DEGENERATE at this grain, NOT RUN (one row per event x Cell: the proxy has nothing to collapse) | - | - | - | - | - |

**point** (location_blocked, lambda held at the modal CV choice)

| config | CSI | delta CSI | POD | FAR | PR-AUC |
|---|---|---|---|---|---|
| REFERENCE: the primary at the frozen modal lambda=100.0 | 0.0304 | +0.0000 | 0.106 | 0.959 | 0.0230 |
| lambda=0.01 | 0.0314 | +0.0010 | 0.077 | 0.949 | 0.0228 |
| lambda=0.1 | 0.0314 | +0.0010 | 0.077 | 0.949 | 0.0228 |
| lambda=1.0 | 0.0314 | +0.0010 | 0.077 | 0.949 | 0.0228 |
| lambda=10.0 | 0.0327 | +0.0023 | 0.070 | 0.942 | 0.0228 |
| lambda=100.0 | 0.0304 | +0.0000 | 0.106 | 0.959 | 0.0230 |
| lambda=1000 (beyond the selection grid) | 0.0327 | +0.0023 | 0.081 | 0.948 | 0.0232 |
| drop precip_max_1h | 0.0301 | -0.0003 | 0.098 | 0.958 | 0.0219 |
| drop precip_total | 0.0294 | -0.0010 | 0.128 | 0.963 | 0.0215 |
| drop antecedent_24h | 0.0326 | +0.0021 | 0.091 | 0.952 | 0.0229 |
| drop elevation | 0.0320 | +0.0015 | 0.075 | 0.947 | 0.0220 |
| drop relief | 0.0299 | -0.0006 | 0.103 | 0.960 | 0.0230 |
| drop stormwater | 0.0236 | -0.0069 | 0.202 | 0.974 | 0.0191 |
| drop kind_indicator | 0.0308 | +0.0003 | 0.081 | 0.953 | 0.0227 |
| operating point: in-fold threshold (not in-fold alert rate) | 0.0304 | -0.0001 | 0.093 | 0.957 | 0.0231 |
| weighted 1/fan-out (proxy: positives per event x Cell; 3,475 rows down-weighted) | 0.0287 | -0.0017 | 0.099 | 0.961 | 0.0236 |

Read the lambda rows before trusting the shipped penalty:

- **cell**: shipped lambda 100 (the modal inner-CV choice across the outer folds). On the GATE metric the best rung is `lambda=100.0` at CSI 0.1591 — the shipped one is which IS the shipped rung. PR-AUC, the metric lambda is actually selected on, moves by 0.0014 across the whole grid including the rung beyond its top.
- **point**: shipped lambda 100 (the modal inner-CV choice across the outer folds). On the GATE metric the best rung is `lambda=10.0` at CSI 0.0327 — the shipped one is the WORST of the rungs. PR-AUC, the metric lambda is actually selected on, moves by 0.0004 across the whole grid including the rung beyond its top.

A CSI ordering that flips while the selection metric moves in the fourth decimal is noise rather than a preference — the honest reading in both directions, including where the shipped rung is the lowest-CSI one.

**Deferred, with the reason — not run here and not silently dropped:** the label radius
sweep {50, 100, 200} m and the p99-union 311 threshold sweep both REDEFINE THE EVENT
UNIVERSE. The radius lives inside ticket 05's Sedona `ST_DWithin` label join and the
threshold inside ticket 04's spine derivation, both upstream of `gold/flood_matrix`, which
this ticket reads and never rebuilds. They run as ticket 18's outer replication, whose
shape is exactly "re-derive the universe, rebuild 05/06/08, re-run 09's fits, publish the
delta beside the frozen primary".

## Honest strings — where these numbers are weaker than the gate

- **cell optimism, measured**: the same cut scored CSI 0.1594 on the rows its fold was FITTED on against 0.1591 out of fold. A small gap says the fit is not memorising its training rows — with this few features under a heavy ridge it is not free to. It says nothing about whether the score is USEFUL; the baselines and the independent set above are what answer that.
- **cell operating point**: 7,881 false alarms against 2,297 hits at a 5.66% alert budget over 179,683 rows — FAR 0.774, POD 0.350. The tier cutpoints ticket 11 provisionally ships (top 10% / top 2%) are far LOOSER than this budget, so ticket 12's replay is where per-event flag volume gets decided, not here.
- **point / event_grouped**: model CSI 0.0286 is BEATEN by B2 unit climatology, and its 95% CI 0.014-0.041 OVERLAPS B2, B3.
- **point / location_blocked**: model CSI 0.0310 wins outright, but its 95% CI 0.017-0.038 OVERLAPS B3.
- **point optimism, measured**: the same cut scored CSI 0.0326 on the rows its fold was FITTED on against 0.0310 out of fold. A small gap says the fit is not memorising its training rows — with this few features under a heavy ridge it is not free to. It says nothing about whether the score is USEFUL; the baselines and the independent set above are what answer that.
- **point operating point**: 8,295 false alarms against 381 hits at a 1.11% alert budget over 783,351 rows — FAR 0.956, POD 0.095. The tier cutpoints ticket 11 provisionally ships (top 10% / top 2%) are far LOOSER than this budget, so ticket 12's replay is where per-event flag volume gets decided, not here.
- **the independent set is the weak one**: 1 of 118 complex-event positives caught under the union rule, CSI 0.0025. Everything above it is measured on the grain the model was FITTED on.

## MRMS-era out-of-sample replication — NOT COMPUTED

the matrix carries era='fit' rows only (AORC has no 2026 year), and the replication era holds 1 event as of the matrix build — replication needs MRMS-era feature rows and more than one storm. Events by era in the landed spine: {'fit': 195, 'validation_only': 10, 'replication': 1}.
Band caveat, stamped for when it does run: when it runs, every MRMS number is read under the measured 0.86-0.92 Pass2/AORC scale band, never like-for-like against an AORC-fit number.

## Coverage honesty (recomputed, not inherited)

The landed spine `silver/flood_events` carries **206 events over
248 event-days**, 2010-03-13..2026-08-20 — by class
{'pluvial': 141, 'coastal': 44, 'mixed': 18, 'snowmelt': 3}. The pluvial fit-era universe these fits read is **133
events over 147 event-days**. The drafted 115 union event days is
SUPERSEDED; any coverage fraction quoted downstream is against 248
event-days, never 115.

## What the fits publish for ticket 10

`research/flood-09-fits.json` carries, per role: the shipped model id, the CV-selected
lambda, coefficients on BOTH the standardised and the raw feature scale (with the
standardisation constants), the feature list and the stormwater base level, and the fit-era
precip percentiles in log1p AND raw mm — the columns are stored already-log1p'd, so a
consumer that transforms again ships a silent bug.
