# raincheck

NYC bus movement joined to precipitation: does rain slow the buses, and where.

## Language

**Poll**:
One HTTP fetch of a GTFS-RT feed; the unit of capture.
_Avoid_: scrape, pull

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

**Delay**:
Seconds late versus the dated static GTFS schedule, computed by us — the feed's
own delay field is never populated. Precise definition pending (ticket 06).
_Avoid_: lateness (until 06 settles the terms)

**Bronze / Silver / Gold**:
Capture-fidelity Parquet from the archiver / spatially-keyed GeoParquet written
by Sedona / (cell, hour, route) aggregates.
