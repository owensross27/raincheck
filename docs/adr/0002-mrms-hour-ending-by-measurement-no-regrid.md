# MRMS conventions are established by measurement: hour-ending stamps, no regrid onto AORC

MRMS hourly QPE GRIB2 files declare themselves as instantaneous fields (product
definition template 0, step 0, no time-range keys), so the header cannot say which
60 minutes a file covers, and a reader who opens one will conclude "instant". We
tested it instead: matching each file's stamp to AORC's verified hour-ending label
gives Pearson r 0.97-0.999 at lag 0 on two storm days and two products, and 0.46-
0.82 at either one-hour shift, so the stamp is the END of the accumulation hour and
MRMS rows carry the same `hour_end_utc` semantic as AORC with no shift. Separately,
MRMS is not regridded onto the AORC grid, though ticket 02 and the raster playbook
both said it should be (xesmf conservative): each grid gets its own area-weighted
Cell crosswalk and the two sources meet at Cell grain, because the area-weighted
mean of a depth field over a Cell already is the conservative remap, and regridding
first would compose two such maps for no gain. Sources are never pooled in one fit
either way. Decided 2026-08-16 in wayfinder ticket 08.

Status: accepted
