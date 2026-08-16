# 08 Weather join design

Type: grilling
Status: open
Blocked by: 02, 03

## Question

How precip attaches to bus observations: at what key (H3 cell-hour vs point sample),
from which store per epoch (AORC historical vs MRMS near-real-time, per ticket 02),
via which bridge (per ticket 03), and the lag structure (precip in trailing 15/60/180
min windows, antecedent wetness). Also where the join runs: inside the streaming job
(broadcast grid) vs a batch feature table the streaming output joins later. Output of
this ticket is the feature spec the analysis stands on.

Asset (2026-08-15): raster playbook, [research/raster-playbook.md](../../../research/raster-playbook.md).
Pre-loads this decision with: MRMS-to-AORC regridding is refinement (MRMS is the
coarser grid at 40.7N) and precip is extensive, so conservative/area-weighted;
resampling method by variable type; H3 res 8 is about 1:1 with an AORC cell so it
is the join key; rolling sums live in xarray (Sedona reads no Zarr/GRIB2); the
one place Sedona rasters belong is RS_Values point extraction, distributed.
Six 15-minute open items are listed at the end of the playbook (MRMS hour-ending
convention, Atlas 14 units, 2017 NVA figure, InSAR units/sign, pysheds HAND
signature, 2010 land cover pixel size).

## Comments

2026-08-16, from [06 Delay metric design](06-delay-metric-design.md): the bus side
of the join is now fixed. Event = one arrival (passage) per (start_date, trip_id,
stop_sequence, vehicle_id) with the stop's Cell and `arrival_ts`; the response
variable for rain is `segment_excess_s` (actual minus scheduled stop-to-stop time,
local to the segment ending at that stop), not the cumulative `delay_s`. Natural
join key is (Cell of the stop, hour of arrival_ts); trailing-window precip attaches
to the arrival hour. Headway/EWT lives at (cell, hour, route) in Gold.

2026-08-16, from [09 Storage and CRS conventions](09-storage-crs-conventions.md): precip is stored at native Pixel grain, `precip_hourly (i, j,
hour_end_utc, mm)` partitioned `src=aorc|mrms/month=`, unique per src; `ref/grids`
freezes each grid from its stored coordinate arrays (AORC: origin (-130.0, 20.0), step
0.008333 float32-truncated, center registration; MRMS row is yours) and
`ref/cell_pixel (grid_id, cell, i, j, weight)` is the area-weighted crosswalk
(sum = 1 per cell). Yours to decide: whether the join uses Cell-grain precip (a view
or sibling table through `cell_pixel`) or `RS_Values` at the bus position; the MRMS
bridge (own crosswalk vs conservative regrid onto the AORC grid) and its hour-ending
check; the trailing windows. Bronze keeps the AORC NYC slice as local Zarr for the
xarray rolling sums.
