# flood-build 12 — the replay gate

Detector `01197991471f` over score `dda793c2c8c7` (table read: `dda793c2c8c7`, model tier **ok**). Forcing replayed: `aorc`; live forcing `RadarOnly_QPE_01H_00.00`; scale band applied: `False`.

Cutpoints under test: ELEVATED top 10% / HIGH top 2% within kind, `provisional: True`.

## Universe

- 195 AORC-era union events (day_start.year <= 2025 (precip_flood_era))
- 133 replayed with evaluation; 62 walk-only ({'coastal': 44, 'mixed': 17, 'snowmelt': 1}) — not in gold/flood_matrix — the fit universe is pluvial only, and density_311_3y is a per-(Cell, event) covariate the matrix build derives, so evaluating these would be a rebuild rather than a replay
- readout: the UNION of tiers over an event's cycles — a tier latches within its Window and the Window rolls when the city dries, so the set standing at window_end is the morning after the storm

## Window agreement (live walk vs the offline calendar window)

90 of 169 events with citywide rain land on the offline `window_start`. Day deltas: `{'-1': 58, '-2': 4, '-3': 3, '0': 90, '1': 10, '2': 1, 'None': 3}`. a negative delta is the live anchor landing EARLIER than the calendar window_start, because the evening before the storm-eve was also wet; the live anchor is observation-derived and this is the rule working

## Excluded and counted

- cycles: 4326 total, by walk state `{'INSUFFICIENT_DATA': 76, 'OK': 4250}`
- Window feature state over the OK cycles: `{'OK': 4250}`
- events with no OK cycle at all: 1

## Flag volume at the provisional cutpoints

| grain | rows | positives | base rate | tier | flagged | alert rate | TP | FP | POD | FAR | CSI | CSI/base |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cell | 179,683 | 6,554 | 3.648% | ELEVATED | 23,342 | 12.99% | 2,660 | 20,682 | 0.4059 | 0.8860 | 0.0977 | 2.68 |
| cell | 179,683 | 6,554 | 3.648% | HIGH | 5,159 | 2.87% | 896 | 4,263 | 0.1367 | 0.8263 | 0.0828 | 2.27 |
| bus_stop | 502,756 | 2,831 | 0.563% | ELEVATED | 76,165 | 15.15% | 1,032 | 75,133 | 0.3645 | 0.9865 | 0.0132 | 2.35 |
| bus_stop | 502,756 | 2,831 | 0.563% | HIGH | 14,521 | 2.89% | 370 | 14,151 | 0.1307 | 0.9745 | 0.0218 | 3.87 |
| complex | 43,089 | 118 | 0.274% | ELEVATED | 5,214 | 12.10% | 29 | 5,185 | 0.2458 | 0.9944 | 0.0055 | 2.00 |
| complex | 43,089 | 118 | 0.274% | HIGH | 956 | 2.22% | 5 | 951 | 0.0424 | 0.9948 | 0.0047 | 1.71 |

### flood 09's pooled out-of-fold decisions, NOT superseded

| grain | rows | positives | base rate | alert rate | TP | FP | POD | FAR | CSI | CSI/base |
|---|---|---|---|---|---|---|---|---|---|---|
| cell | 179,683 | 6,554 | 3.648% | 5.66% | 2,297 | 7,881 | 0.3505 | 0.7743 | 0.1591 | 4.36 |
| point | 783,351 | 4,008 | 0.512% | 1.11% | 381 | 8,295 | 0.0951 | 0.9561 | 0.0310 | 6.05 |

Precision (TP / flagged) and its lift over the universe's own base rate:

- `cell` base 3.648% — ELEVATED precision 11.40% (3.12x) · HIGH precision 17.37% (4.76x)
- `bus_stop` base 0.563% — ELEVATED precision 1.35% (2.41x) · HIGH precision 2.55% (4.53x)
- `complex` base 0.274% — ELEVATED precision 0.56% (2.03x) · HIGH precision 0.52% (1.91x)

**Where the alert budget goes — `cell` grain, ELEVATED-and-above, vs flood 09's `cell` (quartiles of 33 events each).**
- TOP quartile by positives: this cut alarms at 16.64% for POD 0.379; flood 09 reaches POD 0.436 there. 5,795 FP against flood 09's 4,956.
- BOTTOM quartile: 1,514 false alarms for 11 hits at 3.42%, against flood 09's 38 for 0.
- a within-kind rank has no absolute anchor, so it spends the same share of the city on a storm that floods nothing as on one that floods everywhere; a single global cut spends where the rain is.

**Where the alert budget goes — `bus_stop` grain, ELEVATED-and-above, vs flood 09's `point` (quartiles of 33 events each).**
- TOP quartile by positives: this cut alarms at 18.73% for POD 0.366; flood 09 reaches POD 0.116 there. 69,005 FP against flood 09's 8,093.
- BOTTOM quartile: 0 false alarms for 0 hits at 0.00%, against flood 09's 44 for 0.
- a within-kind rank has no absolute anchor, so it spends the same share of the city on a storm that floods nothing as on one that floods everywhere; a single global cut spends where the rain is.

the detector publishes no entrance row (gates.entrances_publish_a_live_number = false), so its point-grain universe is bus stops; flood 09's per_event.point is fit_point = bus stops AND entrances. Different base rates, so every rate here is published with its own.

Complex rows are VOLUMES, never skill: a complex score is an aggregate of doorway scores; the independent complex-grain set caught 1 of 118 positives, so no complex-grain skill is claimed anywhere

## Per-event POD and raw FP, beside flood 09's own per-event table

This replay's columns are the ELEVATED-and-above union over the event's cycles;
flood 09's are its out-of-fold decisions at one global cut. `cell` is the SAME
universe on both sides; `bus_stop` and `point` are not (see the note above).

| event | class | delta d | cell POD | cell FP | F09 cell POD | F09 cell FP | stop POD | stop FP | F09 point POD | F09 point FP |
|---|---|---|---|---|---|---|---|---|---|---|
| 2010-08-22 | pluvial | 0 | 0.643 | 328 | 0.321 | 13 | - | 0 | 0.000 | 0 |
| 2010-10-01 | pluvial | None | 0.000 | 0 | 0.165 | 69 | - | 0 | 0.000 | 7 |
| 2010-10-11 | pluvial | 0 | 0.594 | 149 | 0.000 | 1 | - | 0 | 0.000 | 0 |
| 2010-12-01 | pluvial | 0 | 0.329 | 230 | 0.024 | 10 | - | 0 | 0.000 | 0 |
| 2011-01-18 | pluvial | 0 | 0.338 | 166 | 0.000 | 1 | - | 0 | 0.000 | 0 |
| 2011-02-02 | pluvial | 0 | 0.276 | 133 | 0.000 | 0 | - | 0 | 0.000 | 0 |
| 2011-08-01 | pluvial | None | 0.000 | 0 | 0.000 | 7 | - | 0 | - | 0 |
| 2011-08-14 | pluvial | -1 | 0.685 | 280 | 0.907 | 737 | - | 0 | 0.000 | 103 |
| 2011-08-19 | pluvial | -1 | 0.500 | 231 | 0.111 | 5 | - | 0 | 0.000 | 0 |
| 2011-08-21 | pluvial | 0 | 0.818 | 301 | 0.091 | 22 | - | 0 | 0.000 | 0 |
| 2012-05-21 | pluvial | 0 | 0.543 | 317 | 0.054 | 20 | - | 0 | 0.000 | 0 |
| 2012-06-22 | pluvial | 0 | 0.409 | 229 | 0.045 | 5 | - | 0 | 0.000 | 0 |
| 2012-07-18 | pluvial | 0 | 0.481 | 229 | 0.296 | 50 | - | 0 | 0.000 | 2 |
| 2012-08-01 | pluvial | 0 | 0.667 | 299 | 0.000 | 9 | - | 0 | 0.000 | 0 |
| 2012-08-15 | pluvial | 0 | 0.520 | 233 | 0.120 | 18 | - | 0 | 0.000 | 0 |
| 2012-09-08 | pluvial | -1 | 0.529 | 213 | 0.088 | 16 | - | 0 | - | 0 |
| 2013-05-08 | pluvial | 0 | 0.458 | 255 | 0.307 | 98 | - | 0 | 0.000 | 4 |
| 2013-05-23 | pluvial | 0 | 0.435 | 168 | 0.043 | 11 | - | 0 | 0.000 | 0 |
| 2013-06-02 | pluvial | 0 | 0.500 | 152 | 0.000 | 2 | - | 0 | - | 0 |
| 2013-06-07 | pluvial | -1 | 0.481 | 209 | 0.580 | 304 | - | 0 | 0.077 | 16 |
| 2013-09-02 | pluvial | 1 | 0.500 | 141 | 0.125 | 2 | - | 0 | - | 0 |
| 2014-02-05 | pluvial | 0 | 0.000 | 0 | 0.043 | 24 | - | 0 | 0.000 | 0 |
| 2014-02-13 | pluvial | 0 | 0.364 | 151 | 0.064 | 16 | - | 0 | 0.000 | 0 |
| 2014-05-10 | pluvial | 1 | 0.667 | 318 | 0.111 | 6 | - | 0 | - | 0 |
| 2014-05-16 | pluvial | 0 | 0.577 | 297 | 0.269 | 40 | - | 0 | 0.000 | 0 |
| 2014-06-13 | pluvial | 0 | 0.519 | 267 | 0.192 | 22 | - | 0 | 0.000 | 0 |
| 2014-07-02 | pluvial | 0 | 0.556 | 224 | 0.167 | 66 | - | 0 | 0.000 | 6 |
| 2014-07-15 | pluvial | -1 | 0.333 | 153 | 0.349 | 83 | - | 0 | 0.000 | 1 |
| 2014-08-31 | pluvial | 0 | 0.500 | 171 | 0.083 | 7 | - | 0 | 0.000 | 0 |
| 2014-10-22 | pluvial | -1 | 0.600 | 217 | 0.150 | 17 | - | 0 | 0.000 | 0 |
| 2014-11-17 | pluvial | -1 | 0.395 | 174 | 0.105 | 18 | - | 0 | 0.000 | 0 |
| 2014-12-09 | pluvial | 0 | 0.396 | 169 | 0.372 | 155 | - | 0 | 0.000 | 0 |
| 2015-05-31 | pluvial | 0 | 0.462 | 234 | 0.354 | 78 | - | 0 | 0.000 | 1 |
| 2015-07-15 | pluvial | -1 | 0.526 | 183 | 0.053 | 8 | - | 0 | 0.000 | 0 |
| 2015-07-30 | pluvial | 0 | 0.618 | 318 | 0.206 | 26 | - | 0 | - | 0 |
| 2015-12-17 | pluvial | 0 | 0.444 | 167 | 0.148 | 14 | - | 0 | 0.000 | 0 |
| 2016-02-16 | pluvial | -1 | 0.337 | 170 | 0.072 | 10 | - | 0 | 0.000 | 0 |
| 2016-05-30 | pluvial | 0 | 0.444 | 208 | 0.111 | 40 | - | 0 | - | 1 |
| 2016-06-01 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | 0.000 | 0 |
| 2016-06-09 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | - | 0 |
| 2016-07-25 | pluvial | 0 | 0.593 | 241 | 0.237 | 40 | - | 0 | 0.000 | 1 |
| 2016-08-29 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | - | 0 |
| 2016-09-13 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | - | 0 |
| 2016-10-15 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | - | 0 |
| 2016-10-19 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | - | 0 |
| 2016-11-15 | pluvial | 0 | 0.449 | 197 | 0.056 | 18 | - | 0 | 0.000 | 0 |
| 2016-11-29 | pluvial | 0 | 0.333 | 164 | 0.043 | 24 | - | 0 | 0.000 | 0 |
| 2016-12-15 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | - | 0 |
| 2017-01-09 | pluvial | 2 | 0.000 | 147 | 0.000 | 0 | - | 0 | - | 0 |
| 2017-01-17 | pluvial | 0 | 0.462 | 185 | 0.077 | 7 | - | 0 | 0.000 | 0 |
| 2017-01-19 | pluvial | 1 | 0.167 | 138 | 0.000 | 0 | - | 0 | - | 0 |
| 2017-02-13 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | - | 0 |
| 2017-02-21 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | - | 0 |
| 2017-03-02 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | - | 0 |
| 2017-03-20 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | 0.000 | 0 |
| 2017-04-06 | pluvial | 0 | 0.416 | 203 | 0.079 | 7 | - | 0 | 0.000 | 0 |
| 2017-05-05 | pluvial | 0 | 0.415 | 163 | 0.449 | 199 | - | 0 | 0.000 | 16 |
| 2017-06-14 | pluvial | 0 | 0.412 | 177 | 0.059 | 6 | - | 0 | 0.000 | 0 |
| 2017-06-19 | pluvial | -3 | 0.378 | 173 | 0.081 | 21 | - | 0 | 0.000 | 0 |
| 2017-07-07 | pluvial | 0 | 0.427 | 202 | 0.360 | 110 | - | 0 | 0.000 | 1 |
| 2017-07-11 | pluvial | -1 | 0.500 | 211 | 0.000 | 1 | - | 0 | - | 0 |
| 2017-07-20 | pluvial | 0 | 0.000 | 81 | 0.000 | 0 | - | 0 | - | 0 |
| 2017-08-02 | pluvial | -1 | 0.471 | 176 | 0.059 | 0 | - | 0 | 0.000 | 0 |
| 2017-08-04 | pluvial | -3 | 0.235 | 237 | 0.000 | 16 | - | 0 | - | 0 |
| 2017-08-12 | pluvial | -1 | 0.429 | 182 | 0.000 | 2 | - | 0 | - | 0 |
| 2017-08-18 | pluvial | 0 | 0.441 | 221 | 0.206 | 63 | - | 0 | 0.000 | 0 |
| 2017-09-01 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | - | 0 |
| 2017-10-29 | pluvial | 0 | 0.500 | 168 | 0.500 | 177 | - | 0 | 0.000 | 6 |
| 2018-01-10 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | - | 0 |
| 2018-05-02 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | - | 0 |
| 2018-06-28 | pluvial | -1 | 0.548 | 299 | 0.119 | 39 | - | 0 | 0.000 | 0 |
| 2018-07-17 | pluvial | 0 | 0.538 | 167 | 0.115 | 41 | - | 0 | 0.000 | 7 |
| 2018-07-27 | pluvial | 0 | 0.634 | 275 | 0.341 | 41 | - | 0 | 0.000 | 1 |
| 2018-08-04 | pluvial | 0 | 0.333 | 198 | 0.048 | 8 | - | 0 | 0.000 | 0 |
| 2018-08-06 | pluvial | 1 | 0.395 | 166 | 0.263 | 29 | - | 0 | 0.000 | 1 |
| 2018-08-11 | pluvial | -1 | 0.333 | 299 | 0.140 | 95 | - | 0 | 0.000 | 11 |
| 2018-09-25 | pluvial | 0 | 0.509 | 254 | 0.245 | 78 | - | 0 | 0.000 | 5 |
| 2018-09-28 | pluvial | -3 | 0.396 | 186 | 0.226 | 75 | - | 0 | 0.000 | 1 |
| 2018-12-21 | pluvial | -1 | 0.333 | 162 | 0.115 | 48 | - | 0 | 0.000 | 0 |
| 2019-01-17 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | - | 0 |
| 2019-01-28 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | - | 0 |
| 2019-03-26 | pluvial | 0 | 0.000 | 0 | 0.000 | 0 | - | 0 | - | 0 |
| 2019-05-29 | pluvial | -1 | 0.321 | 192 | 0.107 | 23 | - | 0 | 0.000 | 0 |
| 2019-07-17 | pluvial | 0 | 0.480 | 254 | 0.200 | 95 | - | 0 | 0.000 | 4 |
| 2019-07-22 | pluvial | -1 | 0.438 | 260 | 0.656 | 338 | - | 0 | 0.000 | 5 |
| 2019-07-31 | pluvial | 0 | 0.556 | 160 | 0.222 | 13 | - | 0 | 0.000 | 0 |
| 2019-08-07 | pluvial | 0 | 0.529 | 251 | 0.353 | 105 | - | 0 | 0.000 | 2 |
| 2019-09-26 | pluvial | 0 | 0.000 | 1 | 0.000 | 2 | - | 0 | - | 0 |
| 2019-12-22 | pluvial | 0 | 0.000 | 0 | 0.000 | 2 | - | 0 | - | 0 |
| 2020-03-04 | pluvial | 0 | 0.250 | 143 | 0.000 | 6 | 0.400 | 1,024 | 0.000 | 0 |
| 2020-05-28 | pluvial | 0 | 0.000 | 0 | 0.000 | 1 | - | 0 | - | 0 |
| 2020-07-10 | pluvial | 0 | 0.365 | 180 | 0.385 | 207 | 0.240 | 1,686 | 0.056 | 81 |
| 2020-11-30 | pluvial | 0 | 0.440 | 159 | 0.160 | 24 | 0.397 | 1,576 | 0.000 | 0 |
| 2021-06-04 | pluvial | -1 | 0.415 | 195 | 0.098 | 13 | 0.250 | 1,782 | 0.000 | 0 |
| 2021-06-08 | pluvial | 0 | 0.535 | 210 | 0.279 | 47 | 0.370 | 1,717 | 0.000 | 26 |
| 2021-07-02 | pluvial | -2 | 0.400 | 186 | 0.143 | 15 | 0.391 | 1,427 | 0.000 | 1 |
| 2021-07-08 | pluvial | 0 | 0.719 | 178 | 0.439 | 77 | 0.611 | 1,736 | 0.000 | 18 |
| 2021-07-12 | pluvial | 0 | 0.444 | 147 | 0.074 | 10 | 0.133 | 1,081 | 0.000 | 5 |
| 2021-07-26 | pluvial | 0 | 0.727 | 250 | 0.091 | 3 | 0.000 | 1,656 | 0.000 | 0 |
| 2021-08-21 | pluvial | -1 | 0.443 | 264 | 0.904 | 573 | 0.412 | 2,784 | 0.254 | 969 |
| 2021-08-27 | pluvial | -1 | 0.731 | 265 | 0.269 | 37 | 0.444 | 2,186 | 0.000 | 28 |
| 2021-09-01 | pluvial | 0 | 0.319 | 118 | 0.944 | 543 | 0.282 | 1,744 | 0.595 | 5,715 |
| 2021-09-24 | pluvial | -1 | 0.182 | 150 | 0.091 | 25 | 0.000 | 1,091 | 0.000 | 0 |
| 2021-10-26 | pluvial | -1 | 0.477 | 238 | 0.719 | 351 | 0.396 | 2,786 | 0.071 | 134 |
| 2022-03-02 | pluvial | 0 | 0.000 | 0 | 0.000 | 2 | - | 0 | - | 0 |
| 2022-07-16 | pluvial | 0 | 0.760 | 218 | 0.120 | 17 | 0.385 | 2,931 | 0.000 | 2 |
| 2022-07-18 | pluvial | 0 | 0.618 | 152 | 0.164 | 21 | 0.477 | 1,799 | 0.036 | 16 |
| 2022-08-18 | pluvial | 0 | 0.167 | 138 | 0.000 | 2 | 0.000 | 1,256 | 0.000 | 0 |
| 2022-09-13 | pluvial | 0 | 0.563 | 305 | 0.471 | 144 | 0.458 | 3,388 | 0.015 | 43 |
| 2022-11-21 | pluvial | 0 | 0.000 | 0 | 0.000 | 2 | 0.000 | 0 | 0.000 | 0 |
| 2023-01-26 | pluvial | -1 | 0.346 | 138 | 0.038 | 15 | 0.182 | 1,525 | 0.000 | 0 |
| 2023-04-30 | pluvial | -2 | 0.259 | 129 | 0.349 | 167 | 0.210 | 1,680 | 0.012 | 14 |
| 2023-07-08 | pluvial | 0 | 0.000 | 93 | 0.000 | 2 | 0.000 | 1,083 | 0.000 | 0 |
| 2023-07-16 | pluvial | -2 | 0.400 | 210 | 0.200 | 53 | 0.327 | 2,029 | 0.000 | 1 |
| 2023-08-29 | pluvial | 0 | 0.000 | 0 | 0.000 | 2 | - | 0 | - | 0 |
| 2023-09-11 | pluvial | -1 | 0.333 | 185 | 0.271 | 176 | 0.216 | 2,163 | 0.000 | 13 |
| 2023-09-18 | pluvial | -1 | 0.387 | 214 | 0.161 | 43 | 0.229 | 2,759 | 0.000 | 1 |
| 2023-09-29 | pluvial | -1 | 0.425 | 134 | 0.819 | 400 | 0.426 | 2,937 | 0.143 | 467 |
| 2023-10-10 | pluvial | 0 | 0.000 | 0 | 0.000 | 2 | 0.000 | 0 | 0.000 | 0 |
| 2023-11-24 | pluvial | 0 | 0.000 | 0 | 0.000 | 2 | 0.000 | 0 | 0.000 | 0 |
| 2023-12-02 | pluvial | -1 | 0.000 | 140 | 0.000 | 2 | 1.000 | 1,290 | 0.000 | 0 |
| 2024-02-16 | pluvial | 1 | 0.000 | 0 | 0.000 | 4 | 0.000 | 0 | 0.000 | 0 |
| 2024-03-06 | pluvial | 0 | 0.394 | 158 | 0.296 | 81 | 0.263 | 2,261 | 0.000 | 0 |
| 2024-03-23 | pluvial | 0 | 0.318 | 141 | 0.589 | 401 | 0.394 | 2,994 | 0.042 | 179 |
| 2024-07-24 | pluvial | 0 | 0.364 | 84 | 0.000 | 2 | 0.400 | 625 | 0.000 | 0 |
| 2024-08-06 | pluvial | 0 | 0.607 | 266 | 0.500 | 144 | 0.357 | 2,773 | 0.000 | 46 |
| 2024-08-19 | pluvial | -2 | 0.271 | 141 | 0.104 | 37 | 0.444 | 1,258 | 0.000 | 0 |
| 2025-07-08 | pluvial | -1 | 0.429 | 231 | 0.000 | 8 | 0.200 | 2,499 | 0.000 | 0 |
| 2025-07-14 | pluvial | 0 | 0.494 | 217 | 0.469 | 179 | 0.381 | 3,246 | 0.029 | 144 |
| 2025-07-31 | pluvial | -1 | 0.549 | 213 | 0.363 | 70 | 0.542 | 2,942 | 0.038 | 21 |
| 2025-08-13 | pluvial | 0 | 0.286 | 208 | 0.057 | 24 | 0.308 | 2,124 | 0.000 | 0 |
| 2025-10-30 | pluvial | 0 | 0.345 | 71 | 0.607 | 148 | 0.400 | 2,864 | 0.070 | 167 |
| 2025-12-19 | pluvial | 0 | 0.400 | 139 | 0.168 | 46 | 0.265 | 2,431 | 0.000 | 2 |

## Signed live-minus-offline feature deltas

- `log1p_precip_max_mm_1h`: 175,630 Cells over 130 events, median of event medians 0.0000, event medians 6- / 1180 / 6+
- `log1p_precip_total_mm`: 175,630 Cells over 130 events, median of event medians 0.0000, event medians 10- / 920 / 28+
- `log1p_antecedent_mm_24h`: 175,630 Cells over 130 events, median of event medians 0.0000, event medians 29- / 970 / 4+
- 3 events had NO cycle whose live Window covers the calendar `window_start`, so they contribute no delta

positive = the LIVE Window is longer than the calendar one, which is a larger total by construction; the antecedent term moves the other way because an earlier anchor freezes it earlier

## The RadarOnly-vs-AORC ratio

- direct measurement impossible: 0 hours shared between `src=aorc` and `src=mrms`. src=aorc ends 2025-12-31 and src=mrms begins 2026-07-31: the two forcings share no hour on this root, so RadarOnly-vs-AORC is a CHAIN through Pass2 and is published as one.
- **RadarOnly / Pass2 = 0.933** on 8,549 wet paired Cell-hours (83 hours, 2026-08-22 02:00:00+00:00 .. 2026-08-25 12:00:00+00:00); all-pairs 0.938, median pair ratio 0.937.
- Pass2 / AORC = `[0.86, 0.92]` (flood 06, via flood_fits.SCALE_BAND, not measured here).
- **RadarOnly / AORC = [0.802, 0.858]** (ratio_wet_pairs x pass2_over_aorc). below 1.0 -> the raw 2.0 mm own-Cell gate asks for MORE true rain than the offline fit saw, i.e. it is conservative.
- limit: one storm carries the wet pairs (the live table holds ~90 hours and only one of its hours-blocks rained), so this is a first measurement of the product ratio and not a climatology of it.

## The verdict

**cutpoints confirmed, or v1 ships rank-only** — [YOU] Ross, in his own session. this harness measures; it does not edit cutpoints.provisional, cutpoints.confirmed_by or detector_version.
