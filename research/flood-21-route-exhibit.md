# flood-build 21a — the route flood exhibit

**N = 2 flood events.** N is the flood events whose days intersect the HOURS gold/cell_hour_route holds, not the events inside those months: the 2021-09 partition holds 29 hours across two days.

every number below is a level beside a level with its own n. No interval, no CSI, and no cross-universe comparison without its base rate (flood 18).

**Gated:** the statistical table is gated on the full backfill (pipeline-build 17) landing gold/cell_hour_route for the event months — and, measured here, on two things beyond row count: the backfilled months must carry SCHEDULE-MATCHED delay columns (2021-09's late_share and ewt_s are NULL on every one of its 86,914 rows) and an AORC-era cell_hourofweek_baseline window must cover them (AORC ends 2025-12-31, so no capture-era window exists).

## What `gold/cell_hour_route` holds today

| month | days |
| --- | --- |
| `2021-09` | 2021-09-02 .. 2021-09-03 (2 day(s)) |
| `2026-08` | 2026-08-15 .. 2026-08-25 (11 day(s)) |

## event `2021-09-01` (2021-09-01 .. 2021-09-02, `month=2021-09`)

- days covered: 2021-09-02 — **23 hours**, 329 routes
- `late_share` present on **0** of 329 routes; `ewt_s` on **0**
- `cell_hourofweek_baseline` window: **w1** — a speed ratio is available on **329** routes
- baseline independence: `w1` spans 2021-08-16 .. 2021-10-15 and holds **9** days of this event's weekday, of which the event's own 1 (2021-09-02) are inside it. gold.baseline() masks by wetness, not by date, so an event day's own post-storm dry hours enter its baseline. Measured for Ida: 9.59% of w1's Thursday dry Cell-hours are 2021-09-02 itself. It dilutes toward no difference.

| route | n_hours | n_events | late_share | ewt_s | speed_mps | speed_dry | ratio | other weekdays late_share (n hours) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `B70` | 19 | 2097 | - | - | 2.535 | 4.097 | 0.619 | - (4) |
| `Q47` | 18 | 2904 | - | - | 2.156 | 3.131 | 0.689 | - (3) |
| `M22` | 18 | 1082 | - | - | 2.055 | 2.922 | 0.703 | - (3) |
| `B37` | 19 | 1548 | - | - | 2.968 | 4.157 | 0.714 | - (2) |
| `B63` | 23 | 4706 | - | - | 2.349 | 3.255 | 0.722 | - (4) |
| `M8` | 18 | 794 | - | - | 1.984 | 2.725 | 0.728 | - (3) |
| `M42` | 18 | 1823 | - | - | 1.960 | 2.683 | 0.731 | - (2) |
| `Q23` | 19 | 4656 | - | - | 2.176 | 2.975 | 0.732 | - (4) |
| `M86+` | 19 | 1932 | - | - | 1.968 | 2.627 | 0.749 | - (3) |
| `Q18` | 19 | 2647 | - | - | 2.348 | 3.127 | 0.751 | - (4) |

The ten LOWEST `speed_mps / speed_dry` — slowest against their own dry baseline; the JSON carries every route.
`other weekdays` is NOT the named baseline table and is NOT hour-of-week matched, and every flood event day is cut out of it — see the module docstring for both.


## event `2026-08-20` (2026-08-20 .. 2026-08-20, `month=2026-08`)

- days covered: 2026-08-20 — **23 hours**, 346 routes
- `late_share` present on **345** of 346 routes; `ewt_s` on **345**
- `cell_hourofweek_baseline` window: **ABSENT** — a speed ratio is available on **0** routes

| route | n_hours | n_events | late_share | ewt_s | speed_mps | speed_dry | ratio | other weekdays late_share (n hours) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `S84` | 6 | 286 | 0.8322 | 93.4 | 5.684 | - | - | 0.2631 (31) |
| `BM5` | 19 | 717 | 0.6332 | 196.9 | 5.191 | - | - | 0.6100 (94) |
| `S81` | 5 | 280 | 0.5929 | 139.3 | 4.601 | - | - | 0.4259 (21) |
| `BM3` | 19 | 1673 | 0.5523 | 69.7 | 4.977 | - | - | 0.5017 (95) |
| `BM2` | 20 | 1646 | 0.5437 | 179.8 | 4.955 | - | - | 0.5755 (98) |
| `B37` | 19 | 3393 | 0.5187 | 270.9 | 3.122 | - | - | 0.3868 (100) |
| `BM1` | 19 | 2087 | 0.5141 | 151.2 | 5.056 | - | - | 0.4897 (94) |
| `QM5` | 20 | 1995 | 0.5123 | 211.6 | 5.644 | - | - | 0.4671 (106) |
| `B24` | 20 | 2952 | 0.5051 | 196.6 | 3.170 | - | - | 0.3410 (102) |
| `QM8` | 10 | 687 | 0.4862 | 128.0 | 6.255 | - | - | 0.1297 (42) |

The ten largest `late_share`; the JSON carries every route.
`other weekdays` is NOT the named baseline table and is NOT hour-of-week matched, and every flood event day is cut out of it — see the module docstring for both.

