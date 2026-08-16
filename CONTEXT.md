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
aggregation and the precip join. Finer resolutions are recomputed from stored
lon/lat, never stored.
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
One published version of a borough's static GTFS, identified by its
Last-Modified date; the schedule in effect from then until the next Pick.
Delay is always measured against the Pick in effect on the Service date.
_Avoid_: schedule version, GTFS dump, feed (when the static side is meant)

**Bronze / Silver / Gold**:
Capture-fidelity Parquet from the archiver / spatially-keyed GeoParquet written
by Sedona / (cell, hour, route) aggregates.
