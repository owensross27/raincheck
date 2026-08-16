# 10 Backfill slice and speed-derivation rules

Type: grilling
Status: open
Blocked by: 06, 09

## Question

The `nycbuspositions` archive (2017-07-14 to 2024-09, ~20 MB/day CSV.xz, speed
column empty) is the fastest route to the headline insight. Which slice first
(Ida Sept 2021 and 2023-09-29 flood plus one dry control month each, ~120 days,
~2.4 GB, was the reality-check proposal), what are the rules for deriving speed
from successive pings (geodesic distance / dt, dt bounds, outlier cutoffs, stop
dwell handling, trip boundary resets), how do archive rows map onto the Silver
schema from ticket 09 so history and live are one table, and what is the
acceptance test (the Ida hour shows the expected signal on a fixture day)?
The Answer is the slice and the rules; loading it is downstream build work.

## Comments

2026-08-16, from [06 Delay metric design](06-delay-metric-design.md): archive rows
map onto the same event table as live via VP passages (the archive has NO stop-level
TU rows, positions at ~120 s cadence, `trip_start_date` populated, trip_id scheme
identical to today). Schedule metrics for 2017-2024 come from Transitland picks
(ticket 11 resolved; ticket 12 gets the key and proves one download). Ping-to-ping
speed rules remain this ticket's. Measured on 2021-09-01: 1,311,872 unique pings,
906,790 passages, 13.6% of pings on the previous service day.
