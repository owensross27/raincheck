# 10 Historical backfill from nycbuspositions

Type: task
Status: open
Blocked by: 04, 09

## Question

Load a first slice of the 2017-07-14 to 2024-09 archive at
`https://s3.amazonaws.com/nycbuspositions/YYYY/MM/YYYY-MM-DD-bus-positions.csv.xz`
(~19-20 MB/day, columns include timestamp, trip_id, route_id, vehicle_id,
latitude, longitude, bearing, stop_id, occupancy_status; speed column is empty,
derive from successive pings per vehicle) into the Silver schema from ticket 09,
using the same Sedona code paths ticket 07 will stream with. First slice: Sept 2021
(Ida) and Sept 2023 (2023-09-29 flood) plus one dry control month each, ~120 days,
~2.4 GB compressed. Join AORC hourly precip on (h3, hour). Output: one map and one
number, "speed drop per mm/h by H3 cell". This is the first showcase artifact and
the proof-of-Sedona; it moves ahead of ticket 07 in build order.
Done means: the map renders, the number is reproducible from a pytest fixture day,
and the Ida hour shows the expected signal.
