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
