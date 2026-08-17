# Ticket 10 evidence: backfill slice and speed rules (measured 2026-08-16)

Evidence for [research/10-backfill-slice-and-speed.md](10-backfill-slice-and-speed.md).
Four measurement passes ran in parallel: (1) an archive census on one day per year
2017-2024 plus the two storm days; (2) the Leg experiments on 2021-09-01 and
2023-09-29 with their D+1 files and the same weekdays one week earlier (script
`10-backfill-speed-evidence.py`); (3) benchmark and archiver forensics against primary
sources; (4) an AORC wet-hour census over every month 2017-01..2024-12 for the slice
choice (script `10-aorc-wet-census.py`). Section 3 adds the one variant the Leg pass
did not run (both terminal regions dropped, "R1"). Every share carries its denominator;
UNVERIFIED / NOT MEASURED are marked.

## 1. Archive census, one day per year (2017-2024)

Files: 2017-08-16, 2018-05-16, 2018-10-10, 2019-09-11, 2020-11-18, 2021-09-01,
2022-05-11, 2023-09-29, 2024-06-12, 2024-10-16 (all UTC-day files, ~1.2-1.9M rows).


| date | rows | uniq pings (veh,ts) | dup share (veh,ts) | vehicles | n mid (polls) | poll cadence p50 (s) | veh dt p50/p90 (s) | occupancy informative share (!=UNKNOWN/EMPTY) | prev-service-day share | cells touched (all) |
|---|---|---|---|---|---|---|---|---|---|---|
| 2017-08-16 | 1,815,462 | 1,815,462 | 0.000% | 5,079 | NOT MEASURED (no mid col) | NOT MEASURED | 126 / 129 | 0.000% | 2.282% | 1,120 / 4,113 bbox cells (>=100 pings: 1,018) |
| 2018-05-16 | 1,874,992 | 1,874,992 | 0.000% | 5,201 | NOT MEASURED (no mid col) | NOT MEASURED | 126 / 131 | 0.000% | 2.149% | 1,121 / 4,113 bbox cells (>=100 pings: 1,016) |
| 2018-10-10 | 1,849,584 | 1,849,584 | 0.000% | 5,190 | NOT MEASURED (no mid col) | NOT MEASURED | 126 / 156 | 0.000% | 2.107% | 1,119 / 4,113 bbox cells (>=100 pings: 1,021) |
| 2019-09-11 | 1,476,393 | 1,476,393 | 0.000% | 5,175 | NOT MEASURED (no mid col) | NOT MEASURED | 122 / 153 | 2.957% | 1.838% | 1,117 / 4,113 bbox cells (>=100 pings: 994) |
| 2020-11-18 | 1,424,285 | 1,424,285 | 0.000% | 5,117 | 720 | 120 | 122 / 152 | 0.000% | 1.714% | 1,117 / 4,113 bbox cells (>=100 pings: 984) |
| 2021-09-01 | 1,332,701 | 1,332,701 | 0.000% | 4,883 | 721 | 120 | 122 / 156 | 0.000% | 1.856% | 1,118 / 4,113 bbox cells (>=100 pings: 987) |
| 2022-05-11 | 1,416,126 | 1,416,126 | 0.000% | 5,075 | 720 | 122 | 122 / 152 | 0.000% | 1.740% | 1,116 / 4,113 bbox cells (>=100 pings: 981) |
| 2023-09-29 | 1,373,812 | 1,373,812 | 0.000% | 4,983 | 720 | 114 | 122 / 153 | 0.000% | 1.992% | 1,115 / 4,113 bbox cells (>=100 pings: 993) |
| 2024-06-12 | 1,452,907 | 1,452,907 | 0.000% | 5,053 | 721 | 123 | 122 / 152 | 0.000% | 1.838% | 1,117 / 4,113 bbox cells (>=100 pings: 998) |
| 2024-10-16 | 1,475,508 | 1,475,508 | 0.000% | 5,057 | 720 | 122 | 122 / 152 | 0.000% | 1.833% | 1,117 / 4,113 bbox cells (>=100 pings: 998) |


### Coverage and what changed across years


- total position days in listing: 2,278
- first day: 2017-07-14; true last day: 2024-11-04

Missing dates in checked windows:
- 2021-08-16..2021-10-15: no missing dates (fully present)
- 2023-09-01..2023-10-31: no missing dates (fully present)
- 2018-10-01..2018-10-31: no missing dates (fully present)
- 2022-05-01..2022-05-31: no missing dates (fully present)

Position days per calendar year:

| year | days |
|---|---|
| 2017 | 171 |
| 2018 | 365 |
| 2019 | 314 |
| 2020 | 84 |
| 2021 | 305 |
| 2022 | 365 |
| 2023 | 365 |
| 2024 | 309 |

## What changed across years

File-day coverage (constant across all 10 sampled years, not a year-over-year change): every file's timestamp min/max sits inside `<date> 00:00:0x+00 .. <date> 23:59:5x+00` and the share of rows whose UTC date differs from the file's nominal date is 0.000% in all 10 files -- day files cover the **UTC** calendar day, not the America/New_York local day. Converted to NY local time, 11.2%-16.4% of each file's rows fall on the previous NY calendar date (the UTC 00:00-04:00/05:00 window, which is 8pm-midnight the prior evening in EDT/EST); the share is highest for 2020-11-18 (16.4%, EST = UTC-5, a 5-hour window) and lowest for files in EDT (UTC-4, roughly 11-13%), consistent with the DST offset driving the spillover.

Duplicate rows: `dup share (veh,ts)` and `dup share (veh,ts,stop,lat,lon)` are 0.000% in all 10 sampled files -- unique Pings by (vehicle_id,timestamp) equal the row count in every file, so no (vehicle_id,timestamp) pair appears more than once within a day file. Consequently the "republished moved vehicle under a frozen timestamp" pattern (rows sharing vehicle_id+timestamp but differing stop_id/lat/lon) is 0 rows in all 10 files -- it cannot occur when the vehicle+timestamp pair is already unique. This is UNVERIFIED beyond the 10 sampled days; it is not asserted to hold for every day in 2017-2024.

Schema: `mid` and `stop_sequence` columns are absent in the 2017-08-16, 2018-05-16, 2018-10-10, and 2019-09-11 files (20 columns) and present from 2020-11-18 onward (22 columns) -- poll-id and stop-sequence tracking were added to the archiver's captured feed sometime between Sept 2019 and Nov 2020 (no day in that gap window was sampled here, so the exact cutover date is UNVERIFIED against this sample). `speed` is never usable in any sampled year, but the failure mode changed: in the four pre-mid files (2017-08-16 through 2019-09-11) `speed` is populated in 100% of rows but is the constant literal `0.00` in every single row (verified: min=max=0.00, one distinct value) -- a placeholder, not telemetry -- while from 2020-11-18 onward `speed` is simply empty (0% populated). Either way, speed must be derived from consecutive Pings' lat/lon/dt across the whole 2017-2024 span, not read off this column. `progress`, `block_assigned`, `dist_along_route`, `dist_from_stop` are empty in every sampled row across all 10 files -- see per-day detail sections above for the explicit per-file check. `vehicle_label` and `vehicle_license_plate` population is reported per file above.

See the per-day detail sections for cadence (poll gap p50, per-vehicle dt p50/p90), vehicle_id prefix mix (MTABC_ vs MTA NYCT_ share), trip_id pick-code scheme, and occupancy_status population trend by year -- all measured per file above rather than asserted here.

## 2. Leg experiments (2021-08-25/26, 2021-09-01/02, 2023-09-22/23, 2023-09-29/30)

## Headline numbers

| Question | Answer | Denominator |
|---|---|---|
| What is a Leg's dt? | p50 **122 s**, p10 92 s, p90 153 s; 80.1% in [90,150) | 5,476,841 pooled Legs |
| Is dt ever <= 0? | **Never** — 0.00% | 5,476,841 |
| How much of the fast tail is short-dt jitter? | speed > 25 m/s = **0.230%**, and 70.6% of that tail has a *normal* 90-150 s dt with a ~4 km jump | 5,476,841 |
| Do Legs stay in one Cell? | **57.6%** have cell_start == cell_end; 76.2% have cell_start == cell_mid | 5,476,841 |
| Do Legs straddle an Hour? | **4.36%** | 5,476,841 |
| What does R0 keep? | **87.4-88.4%** of Legs per day | 1.33-1.44 M Legs/day |
| Support per (Cell, Hour) under R0 | p50 **23** Legs; 552 of 4,113 bbox cells clear 30 in a busy hour, 162 clear 100 | 24,998 non-empty (Cell,Hour) pairs |
| How much path does a 120 s chord miss? | mean shortfall **14.5%** (r p50 1.072, mean 1.388) | 325,742 windows, chord >= 10 m |
| Stops spanned by a 120 s Leg | 0 flips 26.6%, 1 flip 44.6%, 2 flips 22.6%, 3+ 6.2% | 325,742 windows |
| Ida signal (deepest hour, ending 2021-09-02 04Z) | citywide storm/control aggregate speed **0.745** | 20,245 storm / 22,900 control Legs |
| 2023-09-29 signal (hour ending 13Z) | **0.907** | 97,569 / 96,547 Legs |
| Is that signal a fleet-composition artifact? | **No** — matched-cell ratio 0.753 vs all-cell 0.745 at Ida 04Z | 300 matched cells |
| Rule-set sensitivity of those ratios | **<= 0.012** across R0 / lax / strict / keep-pre; up to 0.023 when stationary Legs are dropped | see C3 |

## Method, and the one place this deviates from the task brief

**The day file is a calendar UTC day, not 04Z-04Z.** Verified on all eight files: the min
timestamp is 00:00:0xZ and the max is 23:59:5xZ of the file's own date (Section 0). The brief
assumed `D 04:00Z .. D+1 04:00Z`. The consequence is not cosmetic: **the Ida peak hours are not
in the 2021-09-01 file at all** — peak rain 21:00-23:00 EDT on Sep 1 is 01:00-03:00Z on Sep 2,
which lives in the 2021-09-02 file. So four extra archive days were downloaded (2021-08-26,
2021-09-02, 2023-09-23, 2023-09-30) and Legs are built over the 48 h span `[D, D+1]` for each
analysis day. Building over the pair also preserves the ~4,800 Legs/day that straddle midnight,
which per-file processing would silently drop. Hour assignment uses timestamps throughout; the
file date is never used for anything but choosing which files to open.

Controls stay weekday-aligned with the extra days included: Ida runs Wed->Thu (2021-09-01/02)
against Wed->Thu (2021-08-25/26); 2023 runs Fri->Sat (2023-09-29/30) against Fri->Sat
(2023-09-22/23). Section 0 prints each file's weekday.

Definitions, unchanged from the brief: Ping = one decoded VehiclePosition row; Leg = a
consecutive Ping pair per `vehicle_id` sorted by timestamp; Cell = H3 res-8; Hour = hour-ENDING
UTC label (`ceil`, so an exact hour stays in its own hour); dist is geodesic WGS84
(`pyproj.Geod.inv`); aggregate speed is always `sum(dist_m) / sum(dt_s)`, never a mean of ratios.

```
R0        = same_trip only; 0 < dt <= 300 s; speed <= 30 m/s; drop pre-departure Legs; keep stationary
R0-lax    = as R0 but dt <= 600 s, speed <= 35 m/s
R0-strict = as R0 but dt <= 180 s, speed <= 25 m/s
```

Two further variants are measured for sensitivity only: `R0+keep-pre` (pre-departure Legs kept)
and `R0-no-stat` (Legs with dist < 25 m dropped).

Self-checks run on every invocation: geodesic scale (0.01 deg latitude ~ 1.11 km), `ceil`
hour-boundary behaviour, the H3 helper against a direct `h3` call, the triangle inequality on
every chord/polyline window (r >= 1), and disjointness of the pre-departure / post-final regions.

---


## 0. Load, dedupe, census

| date | dow | rows_raw | uniq_full_key | uniq_vehicle_ts | kept | vehicles | polls | t_min | t_max | null_latlon | null_trip | null_stop |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2021-08-25 | Wed | 1,331,595 | 1,331,595 | 1,331,595 | 1,331,595 | 4,853 | 721 | 2021-08-25 00:00:04+00:00 | 2021-08-25 23:59:53+00:00 | 0 | 18,575 | 18,575 |
| 2021-08-26 | Thu | 1,339,331 | 1,339,331 | 1,339,331 | 1,339,331 | 4,871 | 720 | 2021-08-26 00:00:03+00:00 | 2021-08-26 23:59:42+00:00 | 0 | 18,330 | 18,330 |
| 2021-09-01 | Wed | 1,332,701 | 1,332,701 | 1,332,701 | 1,332,701 | 4,883 | 721 | 2021-09-01 00:00:04+00:00 | 2021-09-01 23:59:51+00:00 | 0 | 20,829 | 20,829 |
| 2021-09-02 | Thu | 1,206,797 | 1,206,797 | 1,206,797 | 1,206,797 | 4,733 | 721 | 2021-09-02 00:00:00+00:00 | 2021-09-02 23:59:55+00:00 | 0 | 16,468 | 16,468 |
| 2023-09-22 | Fri | 1,441,795 | 1,441,795 | 1,441,795 | 1,441,795 | 5,025 | 721 | 2023-09-22 00:00:12+00:00 | 2023-09-22 23:59:57+00:00 | 0 | 10,299 | 10,299 |
| 2023-09-23 | Sat | 1,020,734 | 1,020,734 | 1,020,734 | 1,020,734 | 3,868 | 720 | 2023-09-23 00:00:11+00:00 | 2023-09-23 23:59:42+00:00 | 0 | 6,851 | 6,851 |
| 2023-09-29 | Fri | 1,373,812 | 1,373,812 | 1,373,812 | 1,373,812 | 4,983 | 720 | 2023-09-29 00:00:04+00:00 | 2023-09-29 23:59:49+00:00 | 0 | 10,449 | 10,449 |
| 2023-09-30 | Sat | 997,233 | 997,233 | 997,233 | 997,233 | 3,803 | 720 | 2023-09-30 00:00:14+00:00 | 2023-09-30 23:59:56+00:00 | 0 | 7,396 | 7,396 |

`rows_raw == uniq_full_key == uniq_vehicle_ts == kept` on every day: the archive carries no duplicate Pings at all, so the dedupe rule (and the later-`mid`-wins tiebreak) never fires. `null_trip == null_stop` on every day: the same rows lack both.

Poll (`mid`) cadence, from the min timestamp of each `mid` group:

| date | polls | rows_per_poll_p50 | poll_gap_p10 | poll_gap_p50 | poll_gap_p90 | poll_gap_max |
|---|---|---|---|---|---|---|
| 2021-08-25 | 721 | 2144.0 | 94.0 | 120.0 | 148.0 | 181.0 |
| 2021-09-01 | 721 | 2153.0 | 96.0 | 119.0 | 145.1 | 212.0 |
| 2023-09-22 | 721 | 2282.0 | 90.0 | 120.0 | 150.1 | 210.0 |
| 2023-09-29 | 720 | 2130.0 | 92.0 | 120.0 | 145.2 | 212.0 |


## A. Legs

### A1. dt_s (all Legs, no rule applied)

| day | n_legs | p1 | p10 | p50 | p90 | p99 | dt<=0% | dt<30% | [30,90)% | [90,150)% | [150,300)% | [300,600)% | >=600% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2021-08-25 | 1,331,351 | 55.00 | 92.00 | 122.00 | 159.00 | 1299.50 | 0.00 | 0.04 | 5.76 | 77.75 | 14.24 | 0.75 | 1.46 |
| 2021-09-01 | 1,332,329 | 56.00 | 93.00 | 122.00 | 156.00 | 1324.00 | 0.00 | 0.03 | 5.79 | 78.41 | 13.51 | 0.77 | 1.49 |
| 2023-09-22 | 1,440,592 | 90.00 | 92.00 | 122.00 | 152.00 | 1113.00 | 0.00 | 0.01 | 0.28 | 83.78 | 13.83 | 0.72 | 1.38 |
| 2023-09-29 | 1,372,569 | 90.00 | 91.00 | 122.00 | 153.00 | 1529.32 | 0.00 | 0.01 | 0.27 | 80.07 | 17.37 | 0.71 | 1.57 |
| POOLED | 5,476,841 | 62.00 | 92.00 | 122.00 | 153.00 | 1315.00 | 0.00 | 0.02 | 2.95 | 80.08 | 14.74 | 0.74 | 1.47 |

**A1b. dt mass at multiples of the ~120 s poll cadence:**

| day | n_legs | 1x [110,130)% | 2x [230,250)% | 3x [350,370)% | 4x [470,490)% | off-cadence% |
|---|---|---|---|---|---|---|
| 2021-08-25 | 1,331,351 | 40.80 | 0.38 | 0.11 | 0.05 | 58.66 |
| 2021-09-01 | 1,332,329 | 41.19 | 0.41 | 0.12 | 0.05 | 58.23 |
| 2023-09-22 | 1,440,592 | 64.59 | 0.67 | 0.23 | 0.10 | 34.41 |
| 2023-09-29 | 1,372,569 | 57.23 | 0.81 | 0.22 | 0.11 | 41.63 |
| POOLED | 5,476,841 | 51.27 | 0.57 | 0.17 | 0.08 | 47.91 |

Only ~0.6% of Legs sit at 2x cadence, so the archive is not routinely dropping Pings whose vehicle timestamp went stale; the wide dt spread is the vehicle clock advancing irregularly *within* the cadence, not skipped polls.

### A2. dist_m (all Legs)

| day | n_legs | p10 | p50 | p90 | p99 | <10m% | <25m% | <50m% | >2km% | >5km% |
|---|---|---|---|---|---|---|---|---|---|---|
| 2021-08-25 | 1,331,351 | 27.41 | 320.34 | 726.74 | 2756.19 | 7.42 | 9.68 | 12.71 | 1.65 | 0.48 |
| 2021-09-01 | 1,332,329 | 27.10 | 321.86 | 727.92 | 2732.82 | 7.53 | 9.73 | 12.66 | 1.63 | 0.50 |
| 2023-09-22 | 1,440,592 | 38.33 | 306.97 | 695.31 | 2548.63 | 5.40 | 7.99 | 11.50 | 1.49 | 0.39 |
| 2023-09-29 | 1,372,569 | 44.03 | 298.43 | 695.89 | 2536.75 | 4.26 | 6.23 | 11.18 | 1.42 | 0.43 |
| POOLED | 5,476,841 | 35.78 | 311.67 | 711.07 | 2639.54 | 6.12 | 8.38 | 12.00 | 1.55 | 0.45 |

### A3. speed_mps (all Legs with dt>0)

| day | n_legs_dt_gt0 | p50 | p90 | p95 | p99 | p999 | max | >15% | >20% | >25% | >30% | >35% | >50% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2021-08-25 | 1,331,351 | 2.650 | 6.124 | 7.979 | 16.468 | 46.437 | 2431.106 | 1.211 | 0.602 | 0.299 | 0.185 | 0.150 | 0.090 |
| 2021-09-01 | 1,332,329 | 2.658 | 6.141 | 7.971 | 16.171 | 57.091 | 2403.678 | 1.190 | 0.557 | 0.292 | 0.200 | 0.167 | 0.116 |
| 2023-09-22 | 1,440,592 | 2.527 | 5.629 | 7.198 | 14.890 | 27.776 | 933.957 | 0.987 | 0.435 | 0.169 | 0.075 | 0.057 | 0.031 |
| 2023-09-29 | 1,372,569 | 2.454 | 5.644 | 7.214 | 13.984 | 30.722 | 4217.714 | 0.834 | 0.342 | 0.165 | 0.103 | 0.083 | 0.045 |
| POOLED | 5,476,841 | 2.570 | 5.879 | 7.587 | 15.360 | 38.545 | 4217.714 | 1.052 | 0.482 | 0.230 | 0.139 | 0.113 | 0.069 |

**A3b. The >25 m/s tail, pooled: n=12,590 of 5,476,841 Legs with dt>0 (0.230%). dt and dist shape of that tail:**

| dt_s | n | dist_p50 | dist_p90 | spd_p50 | spd_max | share_of_tail% |
|---|---|---|---|---|---|---|
| <30 | 797 | 1539.7 | 7921.0 | 95.0 | 4217.7 | 6.3 |
| 30-60 | 1,099 | 1771.8 | 5557.8 | 35.7 | 690.5 | 8.7 |
| 60-90 | 1,114 | 2400.0 | 7018.3 | 30.2 | 535.4 | 8.8 |
| 90-150 | 8,894 | 3994.8 | 10326.9 | 33.5 | 344.9 | 70.6 |
| 150-300 | 652 | 7444.9 | 18341.2 | 37.4 | 189.5 | 5.2 |
| 300-600 | 29 | 14826.6 | 28569.4 | 46.1 | 92.1 | 0.2 |
| >=600 | 5 | 24025.9 | 27270.4 | 29.3 | 40.3 | 0.0 |

**A3c. 10 fastest Legs in the >35 m/s tail (pooled):**

| vehicle_id | t0 | dt_s | dist_m | speed_mps | route_id0 | same_trip |
|---|---|---|---|---|---|---|
| MTA NYCT_2651 | 2023-09-29 12:25:46+00:00 | 4.0 | 16870.9 | 4217.7 |  | False |
| MTA NYCT_7157 | 2023-09-29 12:43:46+00:00 | 5.0 | 12235.6 | 2447.1 |  | False |
| MTA NYCT_6724 | 2021-08-25 01:03:45+00:00 | 4.0 | 9724.4 | 2431.1 |  | False |
| MTA NYCT_6013 | 2021-09-01 19:23:38+00:00 | 7.0 | 16825.7 | 2403.7 |  | False |
| MTA NYCT_2728 | 2021-09-01 21:17:50+00:00 | 11.0 | 26182.1 | 2380.2 |  | False |
| MTA NYCT_2679 | 2021-09-01 21:17:50+00:00 | 11.0 | 25564.6 | 2324.1 |  | False |
| MTA NYCT_2493 | 2021-09-01 10:27:44+00:00 | 15.0 | 30560.6 | 2037.4 |  | False |
| MTA NYCT_6037 | 2021-08-25 01:03:45+00:00 | 4.0 | 8017.2 | 2004.3 |  | False |
| MTA NYCT_2493 | 2021-09-01 10:33:44+00:00 | 16.0 | 31506.4 | 1969.2 |  | False |
| MTA NYCT_7712 | 2023-09-29 13:39:53+00:00 | 4.0 | 7438.6 | 1859.6 | Q58 | False |

**A3d. Fast tail, express vs local (pooled; express = route starts X/BM/QM/BXM/SIM):**

| kind | n | p50 | p99 | p999 | >25% | >30% | >35% |
|---|---|---|---|---|---|---|---|
| express | 481,556 | 3.893 | 24.738 | 35.242 | 0.922 | 0.197 | 0.103 |
| local | 4,995,285 | 2.494 | 10.870 | 39.385 | 0.163 | 0.134 | 0.114 |

### A4. Trip boundaries

| day | kind | n | share_of_day | dt_p50 | dt_p90 | dist_p50 | dist_p90 | spd_p50 | spd_p90 | dist<25m% |
|---|---|---|---|---|---|---|---|---|---|---|
| 2021-08-25 | same_trip | 1,248,214 | 93.76 | 121.00 | 155.00 | 322.72 | 707.52 | 2.72 | 6.16 | 9.69 |
| 2021-08-25 | trip_change | 83,137 | 6.24 | 127.00 | 4412.80 | 273.17 | 3535.21 | 1.32 | 4.98 | 9.49 |
| 2021-09-01 | same_trip | 1,245,422 | 93.48 | 122.00 | 155.00 | 324.38 | 708.06 | 2.73 | 6.18 | 9.79 |
| 2021-09-01 | trip_change | 86,907 | 6.52 | 126.00 | 3948.40 | 277.14 | 3456.02 | 1.41 | 5.02 | 8.95 |
| 2023-09-22 | same_trip | 1,360,686 | 94.45 | 122.00 | 152.00 | 308.59 | 676.22 | 2.59 | 5.66 | 8.11 |
| 2023-09-22 | trip_change | 79,906 | 5.55 | 124.00 | 4236.50 | 268.21 | 3302.01 | 1.23 | 4.58 | 5.94 |
| 2023-09-29 | same_trip | 1,290,998 | 94.06 | 122.00 | 152.00 | 299.37 | 674.61 | 2.52 | 5.68 | 6.30 |
| 2023-09-29 | trip_change | 81,571 | 5.94 | 129.00 | 4463.00 | 276.28 | 3528.82 | 1.25 | 4.63 | 5.06 |
| POOLED | same_trip | 5,145,320 | 93.95 | 122.00 | 153.00 | 313.51 | 691.40 | 2.64 | 5.92 | 8.45 |
| POOLED | trip_change | 331,521 | 6.05 | 126.00 | 4305.00 | 273.85 | 3460.81 | 1.30 | 4.81 | 7.40 |

### A5. Pre-departure / post-final regions (same-trip Legs only)

| day | region | n | share_of_same_trip | dist<25m% | spd_p50 | spd_p90 | dt_p50 |
|---|---|---|---|---|---|---|---|
| 2021-08-25 | pre_departure | 73,738 | 5.91 | 34.75 | 0.37 | 2.49 | 121.00 |
| 2021-08-25 | post_final | 77,350 | 6.20 | 79.49 | 0.00 | 0.86 | 120.00 |
| 2021-08-25 | mid_trip | 1,097,126 | 87.90 | 3.09 | 2.99 | 6.39 | 121.00 |
| 2021-08-25 |   (of which runs that never flip) | 15,553 | 1.25 | 52.84 | 0.18 | 1.09 | 121.00 |
| 2021-09-01 | pre_departure | 72,952 | 5.86 | 35.03 | 0.38 | 2.47 | 122.00 |
| 2021-09-01 | post_final | 78,387 | 6.29 | 80.14 | 0.00 | 0.82 | 121.00 |
| 2021-09-01 | mid_trip | 1,094,083 | 87.85 | 3.06 | 3.01 | 6.41 | 122.00 |
| 2021-09-01 |   (of which runs that never flip) | 15,002 | 1.20 | 52.68 | 0.18 | 1.18 | 122.00 |
| 2023-09-22 | pre_departure | 80,059 | 5.88 | 35.10 | 0.34 | 2.73 | 122.00 |
| 2023-09-22 | post_final | 69,481 | 5.11 | 70.54 | 0.00 | 1.47 | 122.00 |
| 2023-09-22 | mid_trip | 1,211,146 | 89.01 | 2.74 | 2.80 | 5.82 | 122.00 |
| 2023-09-22 |   (of which runs that never flip) | 16,596 | 1.22 | 50.33 | 0.21 | 1.35 | 122.00 |
| 2023-09-29 | pre_departure | 79,680 | 6.17 | 15.97 | 0.49 | 2.96 | 122.00 |
| 2023-09-29 | post_final | 68,552 | 5.31 | 53.92 | 0.09 | 2.18 | 122.00 |
| 2023-09-29 | mid_trip | 1,142,766 | 88.52 | 2.77 | 2.75 | 5.83 | 122.00 |
| 2023-09-29 |   (of which runs that never flip) | 21,346 | 1.65 | 25.17 | 0.38 | 1.52 | 122.00 |
| POOLED | pre_departure | 306,429 | 5.96 | 30.02 | 0.40 | 2.67 | 122.00 |
| POOLED | post_final | 293,770 | 5.71 | 71.58 | 0.00 | 1.33 | 122.00 |
| POOLED | mid_trip | 4,545,121 | 88.34 | 2.91 | 2.88 | 6.10 | 122.00 |
| POOLED |   (of which runs that never flip) | 68,497 | 1.33 | 43.57 | 0.27 | 1.28 | 122.00 |

### A6. Cell and Hour straddling (all Legs)

| day | n_legs | start==end% | start==mid% | all3 equal% | hour straddle% | crosscell_dist_p10 | crosscell_dist_p50 | crosscell_dist_p90 |
|---|---|---|---|---|---|---|---|---|
| 2021-08-25 | 1,331,351 | 56.82 | 75.75 | 56.82 | 4.36 | 227.54 | 476.69 | 1047.71 |
| 2021-09-01 | 1,332,329 | 56.70 | 75.73 | 56.70 | 4.37 | 229.43 | 476.87 | 1046.67 |
| 2023-09-22 | 1,440,592 | 57.96 | 76.49 | 57.96 | 4.30 | 214.46 | 457.09 | 997.25 |
| 2023-09-29 | 1,372,569 | 58.69 | 76.95 | 58.69 | 4.40 | 205.90 | 459.65 | 1014.33 |
| POOLED | 5,476,841 | 57.56 | 76.24 | 57.56 | 4.36 | 219.20 | 467.41 | 1026.69 |

### A7. Support per (Cell, Hour) under R0 on the control day 2021-08-25

- R0 Legs on 2021-08-25 (t0 within the UTC day): 1,166,524; of these 1,166,524 (100.00%) have cell_mid inside the 4,113-cell NYC bbox, 0 outside it.
- Non-empty (Cell, Hour) pairs: 24,998. Legs per pair p10/p50/p90 = 3 / 23 / 116; mean 46.7, max 1,139.
- Distinct bbox cells with any R0 Leg that day: 1,146 of 4,113 (27.9%).
- In hour ending 2021-08-25 17:00Z: 1,028 bbox cells have >=1 Leg, 552 have >=30, 162 have >=100.


## B. Chord vs path (live 30 s Bronze)

Source the 2026-08-15 Bronze VP capture (deduped, 1,533,808 rows): 1,533,808 rows -> 1,524,621 unique Pings on (vehicle_id, ts, stop_id, lat, lon); only 1,326,750 unique on (vehicle_id, ts) alone, i.e. 207,058 rows (13.5%) repeat a vehicle timestamp while carrying a different position or stop. Every row is a distinct (vehicle_id, fetched_at) pair (1,533,808). 3,121 vehicles.

Vehicle-timestamp staleness at fetch time (fetched_at - ts), all 1,533,808 rows: p50 34 s, p90 50 s, p99 61 s, max 155 s; share > 60 s = 1.2%.

30 s Legs on the `ts` clock: 1,521,500 consecutive-Ping pairs, 1,024,323 (67.3%) with dt in [20,45] s (dt p50 = 28 s). Windows are built only from runs of adjacent kept Legs.

### B1. polyline / chord ratio r by window length

`_c10` columns restrict to windows whose end-to-end chord is >= 10 m (a window where the bus returns near its start has r -> inf and no meaningful shortfall).

| k | nominal_s | n_windows | chord<10m% | r_p10 | r_p50 | r_p90 | r_p10_c10 | r_p50_c10 | r_p90_c10 | r_mean_c10 | shortfall_mean_c10 | r_p50_sametrip |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 60 | 712,345 | 11.2840 | 1.0000 | 1.0004 | 2.1621 | 1.0000 | 1.0002 | 1.6075 | 1.2168 | 0.0970 | 1.0004 |
| 3 | 90 | 481,995 | 7.0563 | 1.0000 | 1.0326 | 2.0115 | 1.0000 | 1.0243 | 1.7530 | 1.2992 | 0.1323 | 1.0309 |
| 4 | 120 | 325,742 | 5.7647 | 1.0000 | 1.0788 | 1.9948 | 1.0000 | 1.0719 | 1.7139 | 1.3876 | 0.1447 | 1.0762 |
| 6 | 180 | 186,489 | 6.3280 | 1.0001 | 1.1064 | 2.2364 | 1.0000 | 1.1000 | 1.6927 | 1.4833 | 0.1580 | 1.1031 |
| 8 | 240 | 126,148 | 4.4337 | 1.0014 | 1.1212 | 2.1718 | 1.0012 | 1.1170 | 1.8575 | 1.5366 | 0.1798 | 1.1158 |

**B1b. k=4 (nominal 120 s) by polyline speed class, chord >= 10 m:**

| cls | n | r_p50 | r_p90 | r_mean | shortfall_mean |
|---|---|---|---|---|---|
| <3 | 156,203 | 1.1642 | 2.7097 | 1.6552 | 0.2155 |
| 3-6 | 125,197 | 1.0245 | 1.2624 | 1.1123 | 0.0743 |
| 6-10 | 21,148 | 1.0150 | 1.2061 | 1.0918 | 0.0591 |
| >10 | 4,416 | 1.0159 | 1.1626 | 1.1453 | 0.0516 |

**B1c. k=4 express vs local, chord >= 10 m:**

| kind | n | r_p50 | r_p90 | r_mean | shortfall_mean |
|---|---|---|---|---|---|
| express | 20,099 | 1.0912 | 2.2963 | 1.5806 | 0.1789 |
| local | 286,865 | 1.0706 | 1.6843 | 1.3741 | 0.1424 |

**B1d. k=4 rebuilt on the poll clock (`fetched_at`) instead of the vehicle clock (`ts`), chord >= 10 m:**

| build | n_legs_kept | n_windows | r_p50 | r_p90 | r_mean | shortfall_mean | polyline_m_p50 |
|---|---|---|---|---|---|---|---|
| ts clock (B1 primary) | 1,024,323 | 325,742 | 1.0719 | 1.7139 | 1.3876 | 0.1447 | 340.8940 |
| fetched_at clock | 1,498,456 | 1,418,425 | 1.0522 | 1.7125 | 1.3805 | 0.1375 | 351.9178 |

### B2. stop_id flips inside a window (approximates Passages spanned by one 120 s archive Leg)

| window | n_windows | 0 flips% | 1% | 2% | 3+% | mean_flips |
|---|---|---|---|---|---|---|
| 4 Pings (3 legs, nominal 90 s) | 481,995 | 38.547 | 46.335 | 13.163 | 1.954 | 0.785 |
| 5 Pings (4 legs, nominal 120 s) | 325,742 | 26.578 | 44.620 | 22.597 | 6.205 | 1.091 |


## C. Storm signal

### C1. 2021-09-01 vs control 2021-08-25 (R0, hour-ending UTC; bold = highlighted hours)

| hour_end_UTC | storm_n_legs | storm_agg_mps | storm_med | storm_mean | ctrl_n_legs | ctrl_agg_mps | ctrl_med | ratio_agg | ratio_med |
|---|---|---|---|---|---|---|---|---|---|
| 2021-09-01 05:00 | 16,716 | 4.030 | 3.802 | 4.177 | 17,137 | 4.063 | 3.823 | 0.992 | 0.995 |
| 2021-09-01 06:00 | 9,395 | 4.413 | 4.203 | 4.579 | 9,524 | 4.457 | 4.277 | 0.990 | 0.983 |
| 2021-09-01 07:00 | 5,478 | 4.530 | 4.357 | 4.661 | 5,461 | 4.460 | 4.387 | 1.016 | 0.993 |
| 2021-09-01 08:00 | 5,332 | 4.394 | 4.264 | 4.588 | 5,080 | 4.453 | 4.341 | 0.987 | 0.982 |
| 2021-09-01 09:00 | 8,993 | 4.177 | 4.038 | 4.308 | 8,777 | 4.305 | 4.099 | 0.970 | 0.985 |
| 2021-09-01 10:00 | 23,675 | 4.224 | 3.844 | 4.353 | 23,572 | 4.282 | 3.910 | 0.987 | 0.983 |
| 2021-09-01 11:00 | 50,344 | 3.972 | 3.553 | 4.130 | 50,281 | 4.012 | 3.550 | 0.990 | 1.001 |
| 2021-09-01 12:00 | 79,688 | 3.547 | 3.070 | 3.660 | 80,181 | 3.599 | 3.108 | 0.986 | 0.988 |
| 2021-09-01 13:00 | 85,506 | 3.291 | 2.872 | 3.430 | 84,649 | 3.316 | 2.868 | 0.993 | 1.001 |
| 2021-09-01 14:00 | 69,080 | 3.143 | 2.804 | 3.284 | 69,372 | 3.132 | 2.806 | 1.003 | 0.999 |
| 2021-09-01 15:00 | 58,121 | 2.990 | 2.746 | 3.112 | 58,449 | 2.941 | 2.684 | 1.017 | 1.023 |
| 2021-09-01 16:00 | 56,038 | 2.940 | 2.661 | 3.036 | 56,326 | 2.903 | 2.652 | 1.013 | 1.003 |
| 2021-09-01 17:00 | 57,701 | 2.872 | 2.606 | 2.988 | 57,220 | 2.867 | 2.591 | 1.002 | 1.006 |
| 2021-09-01 18:00 | 59,556 | 2.894 | 2.597 | 2.978 | 59,538 | 2.843 | 2.561 | 1.018 | 1.014 |
| 2021-09-01 19:00 | 63,957 | 2.825 | 2.529 | 2.903 | 64,468 | 2.816 | 2.533 | 1.003 | 0.999 |
| 2021-09-01 20:00 | 72,129 | 2.804 | 2.496 | 2.927 | 72,330 | 2.803 | 2.511 | 1.000 | 0.994 |
| 2021-09-01 21:00 | 80,365 | 2.863 | 2.516 | 2.973 | 79,953 | 2.835 | 2.503 | 1.010 | 1.005 |
| 2021-09-01 22:00 | 84,552 | 2.939 | 2.559 | 3.061 | 84,150 | 2.940 | 2.526 | 0.999 | 1.013 |
| 2021-09-01 23:00 | 79,159 | 3.174 | 2.794 | 3.331 | 78,907 | 3.254 | 2.807 | 0.975 | 0.996 |
| 2021-09-02 00:00 | 63,107 | 3.284 | 2.975 | 3.419 | 62,681 | 3.306 | 2.956 | 0.993 | 1.006 |
| **2021-09-02 01:00** | 46,791 | 3.370 | 3.152 | 3.485 | 47,873 | 3.318 | 3.046 | 1.016 | 1.035 |
| **2021-09-02 02:00** | 35,923 | 3.225 | 3.104 | 3.348 | 37,244 | 3.455 | 3.235 | 0.934 | 0.960 |
| **2021-09-02 03:00** | 27,190 | 2.779 | 2.598 | 2.868 | 29,529 | 3.578 | 3.380 | 0.777 | 0.769 |
| **2021-09-02 04:00** | 20,245 | 2.807 | 2.584 | 2.925 | 22,900 | 3.768 | 3.546 | 0.745 | 0.729 |

### C1. 2023-09-29 vs control 2023-09-22 (R0, hour-ending UTC; bold = highlighted hours)

| hour_end_UTC | storm_n_legs | storm_agg_mps | storm_med | storm_mean | ctrl_n_legs | ctrl_agg_mps | ctrl_med | ratio_agg | ratio_med |
|---|---|---|---|---|---|---|---|---|---|
| 2023-09-29 05:00 | 18,160 | 3.942 | 3.707 | 4.019 | 17,906 | 3.983 | 3.735 | 0.990 | 0.992 |
| 2023-09-29 06:00 | 10,581 | 4.261 | 4.019 | 4.343 | 10,566 | 4.313 | 4.087 | 0.988 | 0.983 |
| 2023-09-29 07:00 | 6,100 | 4.319 | 4.136 | 4.423 | 6,032 | 4.354 | 4.160 | 0.992 | 0.994 |
| 2023-09-29 08:00 | 5,478 | 4.297 | 4.187 | 4.384 | 5,752 | 4.330 | 4.188 | 0.992 | 1.000 |
| 2023-09-29 09:00 | 9,049 | 4.139 | 3.926 | 4.234 | 9,650 | 4.207 | 4.027 | 0.984 | 0.975 |
| 2023-09-29 10:00 | 25,537 | 4.107 | 3.736 | 4.197 | 26,086 | 4.172 | 3.759 | 0.984 | 0.994 |
| **2023-09-29 11:00** | 55,825 | 3.768 | 3.350 | 3.843 | 56,416 | 3.870 | 3.410 | 0.974 | 0.982 |
| **2023-09-29 12:00** | 90,743 | 3.128 | 2.718 | 3.199 | 91,644 | 3.343 | 2.807 | 0.936 | 0.968 |
| **2023-09-29 13:00** | 97,569 | 2.841 | 2.407 | 2.906 | 96,547 | 3.132 | 2.636 | 0.907 | 0.913 |
| **2023-09-29 14:00** | 77,739 | 2.773 | 2.398 | 2.833 | 76,204 | 3.038 | 2.682 | 0.913 | 0.894 |
| **2023-09-29 15:00** | 60,237 | 2.710 | 2.408 | 2.773 | 62,590 | 2.892 | 2.616 | 0.937 | 0.920 |
| **2023-09-29 16:00** | 55,849 | 2.687 | 2.415 | 2.749 | 60,141 | 2.822 | 2.553 | 0.952 | 0.946 |
| 2023-09-29 17:00 | 55,709 | 2.701 | 2.406 | 2.765 | 61,219 | 2.784 | 2.497 | 0.970 | 0.964 |
| 2023-09-29 18:00 | 57,745 | 2.595 | 2.317 | 2.654 | 64,641 | 2.749 | 2.469 | 0.944 | 0.938 |
| 2023-09-29 19:00 | 64,652 | 2.358 | 2.083 | 2.415 | 72,445 | 2.585 | 2.297 | 0.912 | 0.907 |
| 2023-09-29 20:00 | 74,442 | 2.362 | 2.027 | 2.417 | 82,637 | 2.563 | 2.255 | 0.922 | 0.899 |
| 2023-09-29 21:00 | 78,359 | 2.631 | 2.280 | 2.690 | 87,230 | 2.690 | 2.326 | 0.978 | 0.980 |
| 2023-09-29 22:00 | 80,681 | 2.995 | 2.556 | 3.056 | 89,900 | 2.863 | 2.428 | 1.046 | 1.053 |
| 2023-09-29 23:00 | 74,271 | 3.224 | 2.753 | 3.287 | 83,821 | 3.121 | 2.661 | 1.033 | 1.034 |
| 2023-09-30 00:00 | 60,057 | 3.317 | 2.919 | 3.382 | 66,981 | 3.191 | 2.771 | 1.040 | 1.053 |
| 2023-09-30 01:00 | 46,553 | 3.390 | 3.119 | 3.462 | 52,195 | 3.261 | 2.945 | 1.039 | 1.059 |
| 2023-09-30 02:00 | 35,864 | 3.480 | 3.257 | 3.550 | 39,856 | 3.390 | 3.121 | 1.026 | 1.043 |
| 2023-09-30 03:00 | 27,736 | 3.597 | 3.386 | 3.673 | 31,512 | 3.470 | 3.218 | 1.037 | 1.052 |
| 2023-09-30 04:00 | 22,416 | 3.716 | 3.484 | 3.795 | 24,766 | 3.648 | 3.389 | 1.019 | 1.028 |

### C2. Per-Cell storm/control speed ratio

| window | cells_storm | cells_ctrl | cells_n20_both | p10 | p50 | p90 | <0.8% | <0.9% |
|---|---|---|---|---|---|---|---|---|
| Ida, hour ending 2021-09-02 02:00Z | 1,009 | 1,030 | 506 | 0.770 | 0.973 | 1.140 | 12.451 | 29.447 |
| Ida, hours 01-03Z pooled | 1,079 | 1,074 | 805 | 0.765 | 0.965 | 1.103 | 13.913 | 29.938 |
| Ida, hours 03-04Z pooled (the deepest hours) | 981 | 1,013 | 563 | 0.496 | 0.881 | 1.102 | 35.346 | 55.240 |
| 2023-09-29, hour ending 14:00Z | 1,076 | 1,076 | 714 | 0.689 | 0.973 | 1.148 | 18.908 | 30.952 |
| 2023-09-29, hours 13-15Z pooled | 1,109 | 1,109 | 919 | 0.731 | 0.960 | 1.113 | 15.234 | 32.862 |

**C2b. Composition control: citywide ratio over all cells vs over cells with >= 20 Legs on both days (R0):**

| hour_end_UTC | cells_matched | legs_kept_storm_pct | ratio_all_cells | ratio_matched_cells | median_cell_ratio |
|---|---|---|---|---|---|
| 2021-09-02 01:00 | 601 | 90.4747 | 1.0158 | 1.0186 | 1.0259 |
| 2021-09-02 02:00 | 506 | 86.0312 | 0.9336 | 0.9516 | 0.9728 |
| 2021-09-02 03:00 | 397 | 79.5366 | 0.7766 | 0.7876 | 0.8683 |
| 2021-09-02 04:00 | 300 | 72.2450 | 0.7451 | 0.7530 | 0.8356 |
| 2023-09-29 11:00 | 738 | 93.7716 | 0.9736 | 0.9785 | 0.9726 |
| 2023-09-29 12:00 | 798 | 96.4460 | 0.9357 | 0.9383 | 0.9577 |
| 2023-09-29 13:00 | 762 | 96.2478 | 0.9071 | 0.9051 | 0.9272 |
| 2023-09-29 14:00 | 714 | 95.5582 | 0.9127 | 0.9077 | 0.9727 |
| 2023-09-29 15:00 | 662 | 94.0983 | 0.9371 | 0.9295 | 0.9876 |
| 2023-09-29 16:00 | 639 | 92.9829 | 0.9521 | 0.9486 | 0.9882 |

`ratio_all_cells` and `ratio_matched_cells` stay within ~0.01 of each other in every highlighted hour, so the citywide drop is not an artifact of the fleet moving to different places. `median_cell_ratio` sits above both in the deepest Ida hours (0.868 vs 0.788 at 03Z), i.e. the slowdown is concentrated in the cells that carry the most Legs, which a Leg-weighted aggregate picks up and a per-cell median does not.

### C3. Rule sensitivity, 2021-09-01 storm/control aggregate-speed ratio by highlighted hour

| rule |  01:00 |  02:00 |  03:00 |  04:00 | n_legs_storm_window |
|---|---|---|---|---|---|
| R0 | 1.0158 | 0.9336 | 0.7766 | 0.7451 | 1,159,041 |
| R0-lax | 1.0145 | 0.9317 | 0.7761 | 0.7466 | 1,164,448 |
| R0-strict | 1.0224 | 0.9384 | 0.7762 | 0.7438 | 1,143,533 |
| R0+keep-pre | 1.0109 | 0.9301 | 0.7764 | 0.7346 | 1,231,321 |
| R0-no-stat | 1.0292 | 0.9395 | 0.7846 | 0.7477 | 1,062,000 |

### C3. Rule sensitivity, 2023-09-29 storm/control aggregate-speed ratio by highlighted hour

| rule |  11:00 |  12:00 |  13:00 |  14:00 |  15:00 |  16:00 | n_legs_storm_window |
|---|---|---|---|---|---|---|---|
| R0 | 0.9736 | 0.9357 | 0.9071 | 0.9127 | 0.9371 | 0.9521 | 1,191,352 |
| R0-lax | 0.9728 | 0.9364 | 0.9067 | 0.9140 | 0.9381 | 0.9512 | 1,196,059 |
| R0-strict | 0.9784 | 0.9448 | 0.9126 | 0.9148 | 0.9352 | 0.9520 | 1,182,859 |
| R0+keep-pre | 0.9811 | 0.9407 | 0.9136 | 0.9143 | 0.9352 | 0.9530 | 1,269,326 |
| R0-no-stat | 0.9577 | 0.9295 | 0.9053 | 0.9067 | 0.9151 | 0.9373 | 1,121,625 |

### C4. Ping / vehicle volume, 2021-09-01 vs 2021-08-25

| hour_end_UTC | storm_pings | storm_veh | ctrl_pings | ctrl_veh | ping_ratio | veh_ratio |
|---|---|---|---|---|---|---|
| 2021-09-01 05:00 | 18,654 | 934 | 19,187 | 949 | 0.972 | 0.984 |
| 2021-09-01 06:00 | 10,419 | 593 | 10,548 | 605 | 0.988 | 0.980 |
| 2021-09-01 07:00 | 6,185 | 287 | 6,065 | 285 | 1.020 | 1.007 |
| 2021-09-01 08:00 | 6,062 | 281 | 5,846 | 274 | 1.037 | 1.026 |
| 2021-09-01 09:00 | 10,679 | 660 | 10,458 | 642 | 1.021 | 1.028 |
| 2021-09-01 10:00 | 28,020 | 1,562 | 28,044 | 1,581 | 0.999 | 0.988 |
| 2021-09-01 11:00 | 58,286 | 2,964 | 58,446 | 2,974 | 0.997 | 0.997 |
| 2021-09-01 12:00 | 91,191 | 4,022 | 91,803 | 4,012 | 0.993 | 1.002 |
| 2021-09-01 13:00 | 96,744 | 4,059 | 95,966 | 4,023 | 1.008 | 1.009 |
| 2021-09-01 14:00 | 78,256 | 3,472 | 78,478 | 3,428 | 0.997 | 1.013 |
| 2021-09-01 15:00 | 66,175 | 2,862 | 66,375 | 2,855 | 0.997 | 1.002 |
| 2021-09-01 16:00 | 64,034 | 2,684 | 63,906 | 2,651 | 1.002 | 1.012 |
| 2021-09-01 17:00 | 65,331 | 2,690 | 64,584 | 2,659 | 1.012 | 1.012 |
| 2021-09-01 18:00 | 67,690 | 2,842 | 67,184 | 2,815 | 1.008 | 1.010 |
| 2021-09-01 19:00 | 72,780 | 3,103 | 72,927 | 3,091 | 0.998 | 1.004 |
| 2021-09-01 20:00 | 82,776 | 3,477 | 82,138 | 3,432 | 1.008 | 1.013 |
| 2021-09-01 21:00 | 92,363 | 3,845 | 91,469 | 3,755 | 1.010 | 1.024 |
| 2021-09-01 22:00 | 97,209 | 3,997 | 96,698 | 3,986 | 1.005 | 1.003 |
| 2021-09-01 23:00 | 90,638 | 3,857 | 90,144 | 3,870 | 1.005 | 0.997 |
| 2021-09-02 00:00 | 72,140 | 3,276 | 71,903 | 3,232 | 1.003 | 1.014 |
| **2021-09-02 01:00** | 54,139 | 2,456 | 54,821 | 2,469 | 0.988 | 0.995 |
| **2021-09-02 02:00** | 41,610 | 1,880 | 42,792 | 1,910 | 0.972 | 0.984 |
| **2021-09-02 03:00** | 31,448 | 1,431 | 33,692 | 1,530 | 0.933 | 0.935 |
| **2021-09-02 04:00** | 23,749 | 1,093 | 26,018 | 1,162 | 0.913 | 0.941 |

### C4. Ping / vehicle volume, 2023-09-29 vs 2023-09-22

| hour_end_UTC | storm_pings | storm_veh | ctrl_pings | ctrl_veh | ping_ratio | veh_ratio |
|---|---|---|---|---|---|---|
| 2023-09-29 05:00 | 20,358 | 998 | 20,190 | 1,001 | 1.008 | 0.997 |
| 2023-09-29 06:00 | 11,768 | 653 | 11,752 | 654 | 1.001 | 0.998 |
| 2023-09-29 07:00 | 6,950 | 316 | 6,933 | 321 | 1.002 | 0.984 |
| 2023-09-29 08:00 | 6,445 | 305 | 6,739 | 312 | 0.956 | 0.978 |
| 2023-09-29 09:00 | 10,905 | 662 | 11,795 | 702 | 0.925 | 0.943 |
| 2023-09-29 10:00 | 30,177 | 1,678 | 31,094 | 1,725 | 0.971 | 0.973 |
| **2023-09-29 11:00** | 64,602 | 3,211 | 65,654 | 3,256 | 0.984 | 0.986 |
| **2023-09-29 12:00** | 101,494 | 4,297 | 102,858 | 4,340 | 0.987 | 0.990 |
| **2023-09-29 13:00** | 107,360 | 4,370 | 106,643 | 4,368 | 1.007 | 1.000 |
| **2023-09-29 14:00** | 87,167 | 3,843 | 85,075 | 3,752 | 1.025 | 1.024 |
| **2023-09-29 15:00** | 69,463 | 3,174 | 70,818 | 3,076 | 0.981 | 1.032 |
| **2023-09-29 16:00** | 63,772 | 2,851 | 67,871 | 2,830 | 0.940 | 1.007 |
| 2023-09-29 17:00 | 63,529 | 2,785 | 68,786 | 2,834 | 0.924 | 0.983 |
| 2023-09-29 18:00 | 65,560 | 2,908 | 72,400 | 3,049 | 0.906 | 0.954 |
| 2023-09-29 19:00 | 73,855 | 3,329 | 81,807 | 3,575 | 0.903 | 0.931 |
| 2023-09-29 20:00 | 84,334 | 3,678 | 92,914 | 3,909 | 0.908 | 0.941 |
| 2023-09-29 21:00 | 90,095 | 3,933 | 99,004 | 4,114 | 0.910 | 0.956 |
| 2023-09-29 22:00 | 93,326 | 4,009 | 102,080 | 4,235 | 0.914 | 0.947 |
| 2023-09-29 23:00 | 85,976 | 3,840 | 95,147 | 4,105 | 0.904 | 0.935 |
| 2023-09-30 00:00 | 69,190 | 3,179 | 76,425 | 3,436 | 0.905 | 0.925 |
| 2023-09-30 01:00 | 53,184 | 2,429 | 59,190 | 2,639 | 0.899 | 0.920 |
| 2023-09-30 02:00 | 41,418 | 1,887 | 45,220 | 2,063 | 0.916 | 0.915 |
| 2023-09-30 03:00 | 32,025 | 1,475 | 35,678 | 1,636 | 0.898 | 0.902 |
| 2023-09-30 04:00 | 25,707 | 1,130 | 27,974 | 1,255 | 0.919 | 0.900 |


## D. Two extra facts

### D1. Per-Cell aggregate speed, 06Z-22Z, R0, cells with >= 100 Legs

| control_day | n_legs | cells_any | cells_n100 | p10 | p50 | p90 | p90_over_p10 | min | max |
|---|---|---|---|---|---|---|---|---|---|
| 2021-08-25 | 869,331 | 1,142 | 919 | 2.049 | 3.556 | 6.509 | 3.176 | 0.118 | 18.590 |
| 2023-09-22 | 959,700 | 1,132 | 933 | 2.068 | 3.286 | 6.016 | 2.908 | 0.069 | 16.881 |

### D2. occupancy_status (and bearing) fill on the start Ping of each Leg

| day | n_legs | occ_nonnull_pct | occ_not_unknown_pct | distinct_occ_values | occ_modal_value | occ_modal_pct | bearing_nonnull_pct | bearing_distinct |
|---|---|---|---|---|---|---|---|---|
| 2021-08-25 | 1,331,351 | 100.000 | 100.000 | 1 | EMPTY | 100.000 | 99.764 | 26,298 |
| 2021-09-01 | 1,332,329 | 100.000 | 100.000 | 1 | EMPTY | 100.000 | 99.762 | 26,278 |
| 2023-09-22 | 1,440,592 | 100.000 | 100.000 | 1 | EMPTY | 100.000 | 99.757 | 26,178 |
| 2023-09-29 | 1,372,569 | 100.000 | 100.000 | 1 | EMPTY | 100.000 | 99.742 | 26,222 |


---

## Surprises — measurements that contradict the hypotheses in the task brief

1. **The archive day is a calendar UTC day (00:00Z-23:59Z), not 04Z-04Z.** True on all 8 files.
   Taken at face value the brief's window would have compared the Ida hours against nothing:
   hours ending 2021-09-02 01Z-04Z, where the whole signal lives, are in the *next* file.
2. **Dedupe is a no-op.** On all 8 days, `rows == unique(vehicle_id, timestamp, stop_id,
   latitude, longitude) == unique(vehicle_id, timestamp)` exactly (e.g. 1,331,595 = 1,331,595 =
   1,331,595 on 2021-08-25; 10,043,998 rows across the 8 files). There are **zero** conflicting
   duplicates, so the "keep the row from the later `mid`" tiebreak never fires on any of these days.
3. **`dt_s <= 0` never occurs: 0 of 5,476,841 pooled Legs.** The NULL-speed branch the brief
   asks for is unreachable on this data, and the `dt > 0` guard in R0 removes nothing.
4. **The >25 m/s tail is not short-dt jitter — it is long-distance teleports at normal cadence.**
   The brief guessed "dt < 30 s with a small position jump". In fact 8,894 of the 12,590 tail
   Legs (70.6%) have a perfectly ordinary dt in [90,150) s paired with a median jump of
   **3,995 m** (p90 10,327 m). Only 797 (6.3%) have dt < 30 s — but those carry the absurd
   values (median 95 m/s, max 4,218 m/s). A dt floor would not catch the bulk of the tail; a
   distance or speed cap would.
5. **`same_trip` already removes the worst outliers, so the speed cap gets less credit than it
   looks.** All 10 of the fastest Legs (1,860-4,218 m/s) have `same_trip = False` and 9 of 10
   have a null `route_id` — vehicles between assignments. R0 drops them on the trip test before
   the speed cap is consulted.
6. **A 25 m/s cap is an express-service cap; a 30-35 m/s cap is not.** Above 25 m/s express is
   5.7x more affected than local (0.922% of 481,556 express Legs vs 0.163% of 4,995,285 local).
   Above 35 m/s the two are indistinguishable (0.103% vs 0.114%) — that regime is pure error,
   not fast buses.
7. **The terminal-approach region is a bigger stationary sink than pre-departure, and R0 keeps
   it.** Pooled, `post_final` Legs are 71.6% under 25 m with a median speed of **0.00 m/s**
   (293,770 Legs, 5.71% of same-trip), while `pre_departure` — the region R0 drops — is only
   30.0% under 25 m with median 0.40 m/s (306,429 Legs, 5.96%). Dropping pre-departure while
   keeping post-final removes the *less* stationary of the two.
8. **The 2021 and 2023 eras have measurably different dt shapes.** dt p1 is 55-56 s in 2021 but
   90 s in 2023; the [30,90) s bucket holds 5.76%/5.79% of Legs in 2021 versus 0.28%/0.27% in
   2023. A backfill spanning 2017-2024 cannot assume one dt distribution. Cause UNVERIFIED
   (archiver change, feed change, or both).
9. **The archive is not silently collapsing stale-timestamp Pings.** Only 0.57% of pooled Legs
   sit at 2x the poll cadence ([230,250) s) and 0.17% at 3x, so dt's wide spread is the vehicle
   clock advancing irregularly *inside* the ~120 s cadence, not skipped polls.
10. **In the live 30 s feed the vehicle clock stalls while the bus keeps moving.** 207,058 of
    1,533,808 rows (13.5%) repeat a `(vehicle_id, ts)` pair with a *different* position or stop;
    in 192,728 of those 202,051 groups the position differs, by a median of 67 m across a 30 s
    poll gap. Median staleness `fetched_at - ts` is 34 s (p99 61 s). So the archive's `timestamp`
    is a lagging, coarsely-quantised clock, and `dist_m / dt_s` is not exactly the travel speed
    over that interval. Rebuilding Section B on the poll clock instead changes the 120 s
    shortfall only from 14.5% to 13.8%, so the effect on aggregate speed is small — but it is
    not zero, and it is invisible in the archive itself.
11. **42.4% of Legs end in a different Cell than they start**, so cell assignment is a real
    modelling choice. Usefully, `cell_start == cell_mid == cell_end` (57.56%) is *exactly*
    `cell_start == cell_end` (57.56%): whenever the two endpoints share a hexagon the midpoint
    does too, so midpoint assignment never invents a third cell.
12. **The chord under-measures most exactly where the acceptance test needs signal.** Mean
    shortfall at 120 s is 21.6% for windows below 3 m/s but only 5.2% above 10 m/s. Slow,
    congested, flooded conditions are where the archive chord falls *shortest* of the path,
    so the slower (storm) arm loses more measured distance than the control arm and the
    storm/control ratio is pushed **away from 1** - a chord ratio overstates the slowdown.
    (The first draft of this pass wrote the opposite; corrected by the transit-lens review,
    which put the correction at up to ~10 ratio points at Ida 04Z with class-median r, an
    upper bound because low-speed r is inflated by GPS wander around stopped buses.)
13. **A 120 s Leg often spans no Passage at all**: 26.6% of 325,742 live 120 s windows contain
    zero `stop_id` flips, while 28.8% contain two or more.
14. **The NYC bbox is far larger than the bus network's footprint**: only 1,146 of 4,113 res-8
    cells (27.9%) see a single R0 Leg across a whole control day, and 100% of R0 Legs fall
    inside the bbox (0 outside).
15. **`occupancy_status` is populated but carries no information.** All four days have exactly
    **one** distinct value, `EMPTY`, on 100% of rows. The literal answer to "share populated" is
    100%; the useful answer is 0%. `bearing`, by contrast, is 99.74-99.76% non-null with ~26,200
    distinct values.
16. **Per-cell medians understate the citywide effect.** At Ida 03Z the Leg-weighted citywide
    ratio is 0.777 but the median matched-cell ratio is 0.868 — the slowdown concentrates in the
    cells carrying the most Legs.

## Caveats and what was NOT measured

- **No rain data was joined.** "Storm hour" here is wall-clock, taken from the brief. Whether
  the slow hours coincide with the *wet cells* (AORC/MRMS) is NOT MEASURED. The per-Cell tables
  in C2 are the input such a join would need, not the join itself.
- **4 analysis days of 2,278 available position days.** Nothing here generalises to other dates,
  and surprise 8 shows the eras genuinely differ.
- **Section B rests on one Saturday** of live 30 s capture (2026-08-15 13:12-19:09 EDT, 3,121
  vehicles, 1,533,808 rows). Weekday-peak chord shortfall is NOT MEASURED, and applying a 2026
  measurement to 2021/2023 archive chords is UNVERIFIED cross-era transfer.
- **No GTFS static join and no map-matching.** Stop coordinates and shapes were not used; a
  Passage is approximated purely by `stop_id` flips, and the "true path" in Section B is the
  30 s polyline, itself a lower bound on the real path.
- **The pre-departure definition is a choice.** A run whose `stop_id` never flips (1.33% of
  same-trip Legs pooled, 68,497) is treated as wholly pre-departure and therefore dropped by R0.
  A different convention moves every A5 number and shifts R0's yield.
- **Ida's deepest hours coincide with a 7-9% service reduction** (hour ending 03Z: 0.933 ping
  ratio, 0.935 vehicle ratio; 04Z: 0.913 / 0.941). C2b shows the ratio is not a *geographic*
  composition artifact, but selection on *which* buses kept running is NOT ruled out.
- **C2's matched-cell requirement drops storm-day Legs**: at Ida 03Z/04Z only 79.5%/72.2% of
  storm Legs sit in cells that clear n>=20 on both days.
- The 2023-09-29 fleet was ~9-10% smaller than its control from 17Z onward — *after* the
  highlighted flood hours, during which volume was matched (ping ratio 0.98-1.03). The evening
  ratios in that table are therefore not clean storm evidence.

## 3. Terminal-region variant R1 (both ends dropped), storm/control ratios

R1 = R0 with the post-final region dropped as well (legs after the last stop_id flip
of a (vehicle, trip_id, start_date) run). Rerun on the cached Legs of section 2:

| day pair | rule | kept | ratios by highlighted hour (n storm legs) |
|---|---|---|---|
| 2021-09-01/02 vs 08-25/26 | R0 | 87.4% | 01Z 1.016 (46,791), 02Z 0.934 (35,923), 03Z 0.777 (27,190), 04Z 0.745 (20,245) |
| | R1 | 81.6% | 01Z 1.027 (43,321), 02Z 0.944 (32,697), 03Z 0.792 (24,125), 04Z 0.763 (18,011) |
| 2023-09-29/30 vs 09-22/23 | R0 | 87.6% | 11Z 0.974, 12Z 0.936, 13Z 0.907 (97,569), 14Z 0.913, 15Z 0.937, 16Z 0.952 |
| | R1 | 82.5% | 11Z 0.969, 12Z 0.929, 13Z 0.894 (92,506), 14Z 0.910, 15Z 0.929, 16Z 0.948 |

The post-final region is 6.7% / 5.9% of R0 legs on the storm days and 75% / 60% of
those are under 25 m. On the control days the all-hours space-mean speed rises from
3.225 to 3.418 m/s (2021) and 3.161 to 3.328 m/s (2023) under R1; median Leg speed
2.844 -> 2.989 and 2.821 -> 2.943. Storm ratios move by <= 0.02.

Also checked: the 168 Cells that AORC leaves permanently NULL (sea-mask Pixels inside
the bbox) carry 0 of the 1,166,524 R0 Legs on 2021-08-25.

### R2 (adopted): drop only stationary legs at run ends

The transit-lens review measured that whole-region deletion is rain-correlated (Ida 04Z:
never-flip runs 4.4% of storm same-trip legs vs 1.1% of control; post-final 10.0% vs
6.7%; pre-departure 8.5% vs 5.5%; express runs carry more terminal legs than local,
9.9% vs 5.5% pre-departure). R2 = same-trip, 0 < dt <= 300, speed <= 30, and drop a leg
only if it is in a terminal region (pre-departure, post-final, never-flip run - the last
is a subset of pre-departure) **and** dist_m < 25. Rerun on the cached Legs
(`sens_r2.py`), R00 = no terminal rule at all:

| day pair | rule | kept (of same-trip) | ratios (n storm legs) |
|---|---|---|---|
| 2021-09-01/02 vs 08-25/26 | R00 | 92.9% | 01Z 1.011, 02Z 0.930, 03Z 0.776, 04Z 0.735 (22,147), 06Z 0.805, 08Z 0.914 |
| | R2 | 86.7% | 01Z 1.023, 02Z 0.933, 03Z 0.768 (27,038), 04Z 0.729 (20,669), 06Z 0.795, 08Z 0.890 |
| 2023-09-29/30 vs 09-22/23 | R00 | 93.3% | 12Z 0.941, 13Z 0.914, 14Z 0.914, 19Z 0.916 |
| | R2 | 89.3% | 12Z 0.931, 13Z 0.905 (98,888), 14Z 0.896, 19Z 0.900 (66,675) |

Deletion share of base-rule legs at the deepest hour: R1 storm 18.7% vs control 12.2%
(Ida 04Z), 10.3% vs 9.8% (2023 19Z); R2 6.7% vs 7.2% and 3.1% vs 4.9%. Control-day
all-hours space-mean speed under R2: 3.326 m/s (2021), 3.216 m/s (2023); median Leg
speed 2.895 / 2.840. Never-flip legs are entirely inside the pre-departure region
(69,236 of 69,236 on 2021-09-01).

## 4. AORC wet-hour census, 2017-01..2024-12 (script `10-aorc-wet-census.py`)

Cell-hour precip for all 4,113 Cells x 70,128 hours from the AORC Zarr stores through
`cell_pixel` (weights sum to 1; NULL if any Pixel is NaN); wet = >= 1.0 mm; dry = 08's
rule (mm < 0.1 AND previous hour < 0.1); "wet Hour" = citywide mean >= 1.0 mm.
Full monthly table: `10-aorc-month-cell-stats.parquet` (one row per month). 168 of
4,113 Cells are permanently NULL (AORC sea-mask Pixels; Jamaica Bay, the Rockaway
ocean side, the Sound edge) - they carry no bus Legs (section 3). Real AORC gaps: all
24 hours of 2024-06-18 and the hour ending 2024-11-27T20:00Z are NaN over the whole
bbox (no other gap hour in 2017-2024); 08's NULL-row rule covers them.

### Candidate windows


| window | dates | hours | wet cell-hrs (>=1mm) | wet share | wet hrs (city mean>=1mm) | dry cell-hrs | dry share | top-3 storm hours (citywide mean mm) |
|---|---|---|---|---|---|---|---|---|
| W5 | 2018-10-01..2018-10-31 | 744 | 101535 | 3.32% | 27 | 2647254 | 86.51% | 2018-10-03 03:00:00: 6.88mm; 2018-10-12 09:00:00: 4.67mm; 2018-10-11 22:00:00: 4.33mm |
| W9 | 2018-08-01..2018-09-30 | 1464 | 302909 | 5.03% | 91 | 4916664 | 81.65% | 2018-09-28 10:00:00: 10.57mm; 2018-08-08 00:00:00: 10.02mm; 2018-08-22 06:00:00: 8.68mm |
| W7 | 2019-09-01..2019-10-31 | 1464 | 193437 | 3.21% | 47 | 5229617 | 86.85% | 2019-10-27 17:00:00: 11.14mm; 2019-10-16 23:00:00: 10.02mm; 2019-10-27 16:00:00: 7.83mm |
| W1 | 2021-08-16..2021-10-15 | 1464 | 238337 | 3.96% | 73 | 5169024 | 85.84% | 2021-09-02 02:00:00: 51.18mm; 2021-09-02 01:00:00: 35.92mm; 2021-09-02 03:00:00: 27.57mm |
| W3 | 2021-09-01..2021-09-30 | 720 | 104097 | 3.52% | 31 | 2554769 | 86.27% | 2021-09-02 02:00:00: 51.18mm; 2021-09-02 01:00:00: 35.92mm; 2021-09-02 03:00:00: 27.57mm |
| W6 | 2022-05-01..2022-05-31 | 744 | 164241 | 5.37% | 42 | 2476870 | 80.94% | 2022-05-29 20:00:00: 22.90mm; 2022-05-20 22:00:00: 8.37mm; 2022-05-27 22:00:00: 6.61mm |
| W2 | 2023-09-01..2023-10-31 | 1464 | 370933 | 6.16% | 104 | 4773148 | 79.27% | 2023-09-29 13:00:00: 12.60mm; 2023-09-29 14:00:00: 11.09mm; 2023-09-29 12:00:00: 10.46mm |
| W4 | 2023-09-01..2023-09-30 | 720 | 254509 | 8.59% | 70 | 2200378 | 74.30% | 2023-09-29 13:00:00: 12.60mm; 2023-09-29 14:00:00: 11.09mm; 2023-09-29 12:00:00: 10.46mm |
| W8 | 2024-08-01..2024-09-30 | 1464 | 172361 | 2.86% | 47 | 5052893 | 83.92% | 2024-08-19 00:00:00: 12.79mm; 2024-08-18 14:00:00: 10.56mm; 2024-08-18 13:00:00: 9.86mm |


### Top 15 months by wet Cell-hours


| rank | month | wet cell-hrs | wet share | wet-rain cell-hrs | heavy>=5mm | heavy>=12.7mm | wet hrs (city mean>=1mm) |
|---|---|---|---|---|---|---|---|
| 1 | 2023-09 | 254509 | 8.59% | 254509 | 47973 | 10788 | 70 |
| 2 | 2019-12 | 238107 | 7.78% | 150607 | 16845 | 164 | 61 |
| 3 | 2019-05 | 225509 | 7.37% | 225509 | 23559 | 1990 | 60 |
| 4 | 2018-02 | 208133 | 7.53% | 160448 | 10263 | 0 | 51 |
| 5 | 2018-11 | 205957 | 6.95% | 174462 | 38756 | 187 | 54 |
| 6 | 2024-03 | 202929 | 6.63% | 202911 | 55373 | 4026 | 51 |
| 7 | 2018-12 | 201643 | 6.59% | 196990 | 13674 | 208 | 51 |
| 8 | 2021-07 | 187960 | 6.14% | 187033 | 51105 | 10516 | 57 |
| 9 | 2023-12 | 187629 | 6.13% | 187578 | 41004 | 1948 | 48 |
| 10 | 2018-03 | 167882 | 5.49% | 95527 | 7407 | 0 | 45 |
| 11 | 2021-02 | 167237 | 6.05% | 34160 | 2244 | 0 | 42 |
| 12 | 2023-04 | 164593 | 5.56% | 164593 | 29850 | 2687 | 45 |
| 13 | 2022-05 | 164241 | 5.37% | 164241 | 28878 | 6171 | 42 |
| 14 | 2018-09 | 163457 | 5.52% | 163457 | 26491 | 4729 | 46 |
| 15 | 2019-10 | 161352 | 5.27% | 161352 | 27905 | 2084 | 36 |


### Fixture and the storm hours at Central Park's Cell


| hour_end_utc | cell (hex) | cell-hour mm | expected mm | citywide mean mm (this hour) |
|---|---|---|---|---|
| 2021-09-02T02:00:00 | 882a100895fffff | 84.2783 | 84.28 | 51.1765 |
| 2021-09-02T03:00:00 | 882a100895fffff | 33.8009 | (not given) | 27.5680 |
| 2023-09-29T12:00:00 | 882a100895fffff | 4.9881 | (not given) | 10.4588 |
| 2023-09-29T13:00:00 | 882a100895fffff | 23.9122 | (not given) | 12.6011 |
| 2023-09-29T14:00:00 | 882a100895fffff | 41.6502 | (not given) | 11.0902 |
| 2023-09-29T15:00:00 | 882a100895fffff | 20.1352 | (not given) | 7.7275 |
| 2023-09-29T16:00:00 | 882a100895fffff | 4.2951 | (not given) | 5.2265 |



## 5. Benchmarks and archiver forensics (primary sources, 2026-08-16)

- **Producer of the archive**: Bus-Data-NYC `mta-bus-archive` (Neil Freeman /
  TransitCenter, Apache 2.0). `Makefile`: `positions = http://gtfsrt.prod.obanyc.com/vehiclePositions`
  polled by `src/gtfsrdb.py`; `timestamp` = `fromtimestamp(vp.timestamp)` (GTFS-RT
  `VehiclePosition.timestamp`, "moment at which the vehicle's position was measured");
  `mid` = the serial id of one `rt.messages` row per poll (header timestamp not
  exported); `parse_vehicle()` never fills `progress`, `block_assigned`,
  `dist_along_route`, `dist_from_stop` (100% null in every sampled file 2017-2024);
  `stop_sequence` column exists from the 2019-11-03 "overhaul scrape script" commit
  but is 100% null; `speed` is `0.00` in every row through 2019 and null after.
  Commits `6a4a3e5c` / `24d9718f` (2023-04-01) added ms/s timestamp autodetection
  ("timestamps are irregular"); the two storm days have 0 rows outside +/-2 days of
  the file date, other pre-2023 days unchecked. Poll cadence from `mid` on 2023-09-29:
  mean 120.0 s, min 32, max 212; within-poll vehicle-timestamp spread p50 102 s.
- **TransitCenter `stats/speed/<YYYY-MM>-speed.tsv.gz`** (2014-09..2019-10 and
  2022-05; 2018-10, 2019-09 inside the archive span): grain month x route_id x
  direction_id x stop_id x weekend(0/1) x period(1-5), columns distance (m),
  travel_time (s), count (from 2019). `sql/speed.sql`: distance = difference of GTFS
  `shape_dist_traveled` between consecutive **imputed** calls (`source = 'I'`),
  travel_time = elapsed between them, `WHERE elapsed > 0 AND dist > 0`, summed per
  month; periods 1 = 07-09, 2 = 10-15, 3 = 16-18, 4 = 19-22, 5 = 23-06 local;
  weekend = Sat/Sun/holiday. Whole-file space-mean speed 3.49-3.65 m/s (7.8-8.4 mph).
  Units verified by ratio 1.000 (p10-p90) of distance/count against the `stopdist`
  spacing table over 52,311 matched rows and by `inferno`'s `STOP_THRESHOLD = 30.48`
  ("100 feet"). Calls come from `inferno` (snap to shape, drop backward positions,
  interpolate call times between observations).
- **MTA `cudb-vcni` "MTA Bus Speeds: Beginning 2015"** (163,094 rows, 567 routes):
  month, borough, day_type (1 weekday / 2 weekend), trip_type (EXP, LCL/LTD, SBS),
  route_id, period (Peak / Off-Peak), total_operating_time (h), total_mileage (mi),
  average_speed (mph = mileage / time; the two descriptions are swapped in the
  metadata). No `ALL` rows despite the description. B41 LCL/LTD weekday Sept 2021:
  Off-Peak 41,341.7 mi / 6,169.6 h = 6.70 mph, Peak 6.32 mph.
- **MTA `58t6-89vi` "MTA Bus Route Segment Speeds: 2023-2024"** and `kufs-yh3x`
  (Beginning 2025): per year, month, day_of_week, hour_of_day, route_id, direction
  (N/S/E/W), route_type, timepoint pair (ids, names, lat/lon, stop_order):
  road_distance (mi), average_travel_time (min), average_road_speed (mph),
  bus_trip_count. B41 S, Sept 2023, Wednesday 14h, FLATBUSH AV/AV P -> E 70 ST/
  VETERANS AV: 1.437 mi, 13.48 min, 6.395 mph, 10 trips.
- Also resolving: `r6db-kkzj` (CBD bus speeds from 2023), `8mkn-d32t`, `v4z4-2h6n`.
- **GTFS-RT reference**: `VehiclePosition.timestamp` = "Moment at which the vehicle's
  position was measured"; `FeedHeader.timestamp` = feed creation time. **MTA SIRI docs**
  (bustime.mta.info/developers/siri/...): `ProgressStatus` = layover / prevTrip exists
  in SIRI only; `DistanceFromCall` "in meters"; "at stop" is a 100 ft display rule.
- **Speed limits**: NYS VTL 1180(b) statutory maximum 55 mph (VERIFIED); NYC 25 mph
  default (secondary source only; nyc.gov blocked); bus governed top speed NOT FOUND.

## 6. Disk (measured on this Mac, 2026-08-16)

Internal disk 228 GiB, 9.9 GiB free. Bronze VP from the live archiver: 2,758,797
Pings in 37.5 MB = 13.6 B/Ping. `data/archive/` total ~190 MB after two days of
capture; ticket 15 measured ~0.53 GB/day for the full archiver.
