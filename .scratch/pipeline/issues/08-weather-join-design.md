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
