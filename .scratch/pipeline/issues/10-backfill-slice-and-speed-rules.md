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

2026-08-16, from [09 Storage and CRS conventions](09-storage-crs-conventions.md): 09 is resolved, so this ticket is unblocked. Archive rows land
in Silver `events` (schema in `research/09-storage-schemas.md`), batch-written per
`service_date`, ~24 B/row in the backfill era: the 120-day slice is ~2.6 GB and fits
the internal disk, the full 7 years ~56 GB (external SSD). Schedule metrics need the
per-Pick tables (`trips`, `trip_stops`, `service_days`, `shapes`) partitioned by
`pick_id` = zip sha1 (12's resolver). Speed rules: geodesic only
(`pyproj.Geod` / `ST_DistanceSpheroid`), never haversine; dt bounds and outlier
cutoffs remain yours.

2026-08-16, from [08 Weather join design](08-weather-join-design.md): precip for
the slice comes from `silver/precip_cell_hourly` (src=aorc; spec
`research/08-weather-join-features.md`), joined at read on (src, cell,
hour_end_utc) with `hour_end_utc = ceil_hour(arrival_ts)`. The dry-baseline uses
08's Gold defaults: dry = `mm_1h < 0.1 AND mm_1h_prev < 0.1`, wet = `mm_1h >= 1.0
AND t2m_c > 2` (rain, not snow), frozen counted separately, the 0.1-1.0 band
excluded from the binary contrast, onset vs sustained from `mm_6h - mm_1h`; each
with a three-cutoff sweep. Storm windows for the Ida / 2023-09-29 composites are
(t0, t1) parameters over `mm_1h`. Two things 08 asks of this slice: playbook
Product 3 (`RS_Values` at the stop on the two storm days) also reports the
rain-vs-`segment_excess_s` slope both ways (Cell mean vs stop Pixel) so the
aggregation choice is measured; and any per-Cell hotspot claim must survive a
rerun with `cell_pixel` weights aggregated to ~4 km blocks (adjacent AORC Pixels
correlate at 0.996-0.998). Fixture: Central Park's Cell `882a100895fffff` reads
84.28 mm for the hour ending 2021-09-02T02:00Z.

2026-08-16, from [07 Enrichment execution model](07-enrichment-execution-model.md): the
engine is Spark 3.5.3 + Sedona 1.9.1 running natively on the brew `openjdk@17` (no
Docker for Spark); the archive loader lands rows through the same `events DATE=` job
as live (`enrich.py` functions: `passages`, `with_delay`, `with_segments`,
`with_headways`), idempotent per `service_date=` partition by dynamic overwrite;
`ST_DistanceSpheroid` for any distance feeding a speed. Playbook Product 3's raster is
built in-db from the AORC slice (`RS_MakeEmptyRaster` + `RS_AddBandFromArray`, then
`RS_Values` at the stop) - no GeoTIFF. Sizing: session 8.9 s warm, ~0.7 GB RSS, 1.93M
pings H3'd in 1.1 s; a backfill day is the same order. Session settings, `setuptools`
(pyspark's pandas bridge on Python 3.12) and `TZ=UTC` traps are in
`research/07-execution-model.md` section 0/1.
