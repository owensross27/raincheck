# raincheck

NYC bus movement joined to precipitation: does rain slow the buses, and where.

## Language

**Poll**:
One HTTP fetch of a GTFS-RT feed; the unit of capture.
_Avoid_: scrape, pull

**Snapshot**:
One generation of a GTFS-RT feed, identified by its header timestamp. Several
Polls can return the same Snapshot; Bronze stores each Snapshot once, and a
missed Snapshot is a gap, never reconstructed.
_Avoid_: frame, tick, poll (when the feed generation is meant)

**Ping**:
One decoded VehiclePosition row — one vehicle at one moment.
_Avoid_: position, point, observation

**Stop row**:
One decoded StopTimeUpdate — one trip's prediction for one stop. The unit TU
data ships and stores in, flat, never nested per trip.
_Avoid_: stop time update, prediction record

**Cell**:
An H3 resolution-8 hexagon (~0.74 km2), the canonical spatial key for
aggregation and the precip join; stored as an int64 H3 index in a column named
`cell`, a hex string at any JSON boundary. Finer resolutions are recomputed from
stored lon/lat, never stored. Cell geometry for serving comes from `ref/cells`, never
recomputed in a browser.
_Avoid_: hex, bin, tile

**Zone**:
One of the 263 NYC taxi zones. A presentation overlay reached through a static
Cell-to-Zone lookup at serving time — never a first-class key.
_Avoid_: district, area

**Passage**:
The moment a bus passes a stop, bracketed by the last Ping naming that stop as
next and the first Ping naming the one after; its midpoint is the arrival. The
only arrival definition that spans the 2017-2024 archive and the live feed.
_Avoid_: arrival event, transition, visit

**Prediction**:
A Stop row's predicted arrival time. A stream of Predictions precedes every
Passage; the last one is a cross-check on the Passage, never the arrival itself.
_Avoid_: TU arrival, ETA

**Leg**:
The movement between two consecutive Pings of one vehicle, on the vehicle's own
clock; the archive-era unit of speed (~120 s and ~310 m in the 2017-2024 archive,
~30 s live). A Leg belongs to the Cell of its midpoint and the Hour holding its
midpoint. Legs that change trip and stationary Legs at the ends of a run (before the
first stop change, after the last) are not counted; stationary Legs mid-run are.
_Avoid_: segment (that is between stops), hop, ping pair

**Speed**:
Space-mean chord speed of the Legs in a Cell-hour: total geodesic distance over total
time, dwell included, in m/s. A lower bound on path speed, and a ratio of Speeds
overstates a slowdown (the chord falls shortest of the path when buses are slow), so a
headline ratio is shown with its band. Never a mean of per-Leg speeds.
_Avoid_: velocity, pace, average speed (say space-mean)

**Delay**:
Seconds a Passage is late versus the scheduled arrival from the static GTFS pick
in effect on the trip's service date; positive is late. Late means more than
300 s, early means more than 60 s ahead. The feed's stop-level delay field is
never populated; its trip-level `trip_update.delay` is captured in Bronze but is
not this Delay. Delay is a level: how late the bus is by the time it reaches a
stop.
_Avoid_: lateness, on-time (use late / early / on-time as the three labels)

**Segment excess**:
Seconds a bus took between two consecutive Passages beyond the scheduled time
for that stop pair. Local to the segment, so it is what rain gets attributed to.
_Avoid_: incremental delay, delta delay

**Headway**:
Seconds between consecutive different-vehicle Passages of the same route and
direction at one stop; scheduled headway is the same gap in the static GTFS.
Excess wait is the renewal-formula wait on observed minus on scheduled headways.
Bunched means observed under half of scheduled.
_Avoid_: gap, interval, spacing

**Family**:
Which metric a route-direction-hour headlines: headway (excess wait, bunching)
where the scheduled Headway is 10 min or less, otherwise schedule (Delay). Every
event carries both; Family only chooses the headline.
_Avoid_: metric mode, route class

**Service date**:
The operating day a trip belongs to, as the feed's `start_date`; runs past
midnight, so a 02:00 Ping can belong to the previous Service date.
_Avoid_: calendar day, poll date

**Pick**:
One published version of a borough's static GTFS, identified by the sha1 of its
zip (Transitland's key) and ordered by its publish date; the schedule in effect
from then until the next Pick.
Delay is always measured against the Pick in effect on the Service date.
_Avoid_: schedule version, GTFS dump, feed (when the static side is meant)

**Pixel**:
One grid square of a precipitation grid (AORC 1/120 deg, MRMS 0.01 deg), addressed
by integer indices into the frozen grid definition. Precip is stored at Pixel
grain; a Cell overlaps several Pixels (mean 4.7 for AORC), so Cell-grain precip is
an area-weighted mean through the `cell_pixel` crosswalk, never a nearest lookup.
_Avoid_: cell (when the raster unit is meant), grid cell, AORC cell

**Hour**:
The hour-ending UTC label H covering (H-1h, H]. Every precipitation value in the
project is an Hour total, and a Passage belongs to the Hour containing its
arrival; an arrival exactly on the hour stays in that Hour.
_Avoid_: timestamp, hour-beginning, wall-clock hour

**Precip source**:
Which store a Cell-hour's rain came from: AORC for the years it publishes (all of
the archive), MRMS for the live era. Pinned by every reader and never pooled in one
fit; the MRMS era replicates the AORC-era result rather than extending its sample.
_Avoid_: dataset, product, feed (when the rain side is meant)

**Trailing window**:
Precipitation summed over the N Hours ending at and including an Hour (1, 3, 6,
24). Models take the differences between windows, never the nested sums.
_Avoid_: rolling, lookback, lag window

**Wet hour / Dry hour**:
Labels a Cell-hour takes for the wet-versus-dry contrast: dry when the Hour and
the one before each hold less than 0.1 mm; wet when the Hour holds at least 1.0 mm
of rain, not snow (2 m air temperature above 2 C). Hours between the two are
neither and sit out of the contrast; frozen hours are counted apart. The cutoffs
are analysis parameters, always swept.
_Avoid_: rainy, raining, precipitating

**Live table**:
A thin Hive-Parquet table under `data/live/` written by the streaming job or the
live-precip job: raw rows plus stateless enrichment (Cell, Zone, latest complete
Hour of rain), append-only, read latest-per-key, kept 48 h (7 days for precip). Never
Silver: no Passages, no Delay, no window functions; the durable record is Bronze and
the batch-rebuilt Silver.
_Avoid_: real-time table, streaming sink, cache

**Bronze / Silver / Gold**:
Capture-fidelity Parquet from the archiver plus raw static zips and the AORC slice /
derived tables (Passage events, Pixel-grain precip, Cell-hour precip features,
per-Pick schedule tables) as Hive-partitioned Parquet, batch-rebuilt, GeoParquet
only where a geometry is the payload / (cell, hour, route) aggregates. Layout in
`research/09-storage-schemas.md`.
