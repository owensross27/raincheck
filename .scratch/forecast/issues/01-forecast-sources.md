# 01 Precipitation forecast sources

Type: research
Status: resolved

## Question

Nothing about any forecast product is known to this project (DESTINATION §3.C:
"MEASURED ABSENT"). HRRR, NBM and NWS gridded QPF are CANDIDATES, not findings. For each:
access path (NODD S3 key pattern or an API), format, native resolution, issuance cadence,
lead times, the LATENCY from issuance to availability measured on a live file, whether an
HOURLY RATE field exists or only accumulations, projection and whether `ref/cell_pixel`'s
AORC/MRMS -> Cell pattern reuses or needs a new mapping, licence, and the cost of one fetch
per hour for a month in bytes and requests. Then the two questions the destination hangs
on: (1) is a forecast hourly rate COMPARABLE to DEP's design-storm intensities; (2) what
skill do the product's own verification statistics claim for NYC-scale hourly precip at
1-6 h lead, and what does that do to a sentence with "might" in it. **Recommend one
product or none**, with placement and monthly cost. The detector's contract is NOT on the
table.

## Answer

**NONE QUALIFIES.** Full detail, every fact with its URL and date, in
`~/vault/nyc-precip-forecast-reference.md`.

**The survey collapses to one candidate.** NWS gridded QPF is **6-hourly only** — NDFD's
`ds.qpf.bin` decodes to 12 messages whose every interval is exactly 6 h, and
`api.weather.gov/gridpoints` returns `quantitativePrecipitation` in `PT6H` blocks (read
2026-08-26 15:57Z with an `updateTime` of 06:49Z — **9 h stale**), while its
`forecast/hourly` endpoint carries PoP and **no precipitation amount at all**. RRFS is
**retro output only** on NODD; `noaa-href-pds` and `noaa-sref-pds` **404**. NBM has a real
1-hour `APCP` bucket but **the blend averages the peak away** — CONUS max 18.54 mm against
HRRR's 123.84 mm on the same hour, and over NYC on two real wet hours (observed peaks
38.15 and 53.93 mm) NBM's own peak never exceeded **9.14 mm at any lead 1-6**, bias
0.01-0.19; its exceedance-probability and percentile suite lives in `qmd/`, which runs
**4x/day** and whose finest precip interval is **6 h**. That leaves HRRR.

**HRRR has the right field and the wrong skill.** `hrrr.<date>/conus/hrrr.t<HH>z.wrfsfcf<NN>.grib2`
carries `APCP:surface:(N-1)-N hour acc fcst` — `units kg m**-2`, `stepType accum` — the
same estimand as `live/precip_cell.mm_1h`. Measured over **the 24 wettest citywide NYC
hours 2014-2025** (98,712 Cell-hours per lead, 144/144 archive files, AORC as truth,
`precip_live.cell_means`' rule verbatim), CSI at DEP's Moderate intensity (54.1 mm/h) is
**0.185 at 1 h lead, 0.006 at 2 h, 0.000 at 3 h and 4 h** — at 3-4 h it scored **zero hits
in 3,482 Cell-hours** while raising 387 and 368 false alarms. The dry bias is systematic
(0.27-0.47 at every lead: on the wettest hours this city gets, HRRR forecasts a citywide
total 2-4x too low) and per-Cell correlation goes as low as **−0.719** on individual
storms at leads ≥2.

**And its one skilful lead is not a forecast.** Measured over 40 consecutive cycles:
`wrfsfcf01` publishes at **p50 53.74 min** after its cycle and `wrfsfcf02` at **55.56 min**
(max 74.98), while MRMS `RadarOnly_QPE_01H` publishes at **p50 2.80 min after the hour it
describes ends** (n=41, 2.68-3.02). So for the hour `[H-1,H]`: the observation lands at
**H + 2.80 min**; HRRR f01 — the only lead with Cell-grain skill at design-storm
intensity — lands at **H − 6.26 min**, beating the observation raincheck already ingests by
**9.06 minutes**. The first lead that genuinely precedes the hour (f02, **4.44 min** of true
lead before the hour begins) scores **CSI 0.006**. Nine minutes is not "might".

**(1) COMPARABILITY — YES on the estimand, with three qualifiers.** DEP's "in/hr" is a
**one-hour depth** read off an IDF curve, so it IS the same quantity as `mm_1h`: 1.77 in =
**44.96 mm**, 2.13 in = **54.10 mm**, 3.66 in = **92.96 mm**. Settled from the *NYC
Stormwater Resiliency Plan* itself — "precipitation intensity (inches/hour) as a function
of rainfall duration", "1.75 inches per hour for a one hour storm", "approximately two
inches of rain falling in one hour". Qualifiers: the DEP values are **climate-adjusted,
not historical** (NOAA Atlas 14 60-min at Central Park gives 10-yr **1.90** and 100-yr
**2.88**, so 2.13 is 12% and 3.66 is 27% above), the maps were driven by a **hyetograph**
whose shape and total duration the plan never states (**still open**), and the rainfall
number is identical at both sea levels. Written onto flood-build 20.

**(2) SKILL — the products claim none at this grain.** HRRR's own performance paper
(James et al. 2022, `10.1175/WAF-D-21-0130.1`) verifies QPF as **6-hour accumulations
against 6-h Stage-IV, upscaled to 20 km**, thresholds capped at **1 in/6 h** because
heavier events are too rare to score. DEP's Moderate is 2.13 in in **one** hour. So the
model publishes no skill number at the accumulation window, the spatial scale, or the
intensity the sentence would be about — which is why this ticket measured its own.

**PLACEMENT — the ticket's proposal is right in shape and wrong in cadence, and it is
moot.** Recorded for whoever revisits: an EKS CronJob in the `precip-live` shape is
correct (the tick measured **0.372 s / 169 MiB peak RSS**, *cheaper* than the MRMS tick's
0.70 s / 384 MiB), and `live/precip_forecast_cell(valid_ts, issued_ts, lead_h, cell,
mm_1h)` is the right table — but **`*/5 * * * *` is wrong**: HRRR publishes once an hour
at cycle+53.7..75.0 min, so a 5-minute tick re-asks an unchanged bucket ~12x per
publication, which is the standing "poll at the source's rate, not your render rate" trap.
`*/20` with the existing catch-up walk covers the measured spread. Two corrections beyond
cadence: **the dedupe key is the freshest `issued_ts` per `(cell, valid_ts)`, NOT the
latest `fetched_at`** (a cycle's file is immutable, so `precip_live`'s read rule is the
wrong one here), and **`valid_ts = cycle + N`** in the project's hour-ENDING convention —
an off-by-one nothing downstream can see. `lead_h` is derivable and worth keeping only if
asserted consistent. The emptyDir blocker is inherited unchanged.

**COST, if it were ever built:** one lead per hour = **1,460 requests and 0.16-0.27 GB per
month**; leads 1-6 = 8,760 requests and 0.96-1.61 GB. **$0 in AWS charges** — NODD is AWS
Open Data with no requester-pays (verified by unsigned reads) and all three buckets are
**us-east-1**, the cluster's own region. Licence is the standard NODD grant, identical to
the terms MRMS and AORC already ride on: *"NOAA data disseminated through NODD are open to
the public and can be used as desired"*, attribution requested, no implied endorsement —
**no new constraint**.

**`ref/cell_pixel`: the TABLE reuses verbatim, the BUILDER does not.**
`precip_live.cell_means` needs no edit — `(grid_id, cell, i, j, weight)` works for a
Lambert grid unchanged. But `ref/grids` is `(origin_lon, origin_lat, step_deg, nx, ny)`
and `ref.build_cell_pixel` computes `lon0 + i*step`, which cannot describe HRRR's Lambert
Conformal (`+proj=lcc +lon_0=262.5 +lat_0=38.5 +lat_1=38.5 +lat_2=38.5 +R=6371229`,
1799x1059 @ 3000 m). A new grid KIND, not a new row; the projected build is actually
simpler (regular lattice in the grid's own plane) and took **0.45 s** for **7,215 rows /
389 pixels**, every Cell summing to 1.0. **The number that matters more: 4,113 Cells map
onto 389 HRRR pixels — ~10.6 Cells share one forecast value**, against ~3,449 MRMS pixels
for the same city.

**OPEN DECISION, NOT THIS TICKET'S:** whether notify may ever say "might" belongs to
`.scratch/forecast/map.md`, which **does not exist**. Nothing here touches the detector's
contract, `detector_version`, or what notify says.

**THE ONE THING THAT WOULD RE-OPEN THIS: RRFS going operational.** It is the intended HRRR
successor and today is retro-only on NODD. Nothing else on the horizon changes the table.

## What this ticket does NOT claim

- Not a climatology. 24 hours over ~18 storms is an exhibit with real weight, not a
  seasonal skill study; the sweep cost **288 requests / 57.9 MB / ~4 min**, so a wider or
  season-stratified answer is cheap if anyone wants one.
- NBM was measured on **two** wet hours, not 24. It was dropped on a structural ground
  (the blend does not produce design-storm intensities at all) rather than on that sample.
- The DEP hyetograph's shape and total duration remain **unestablished** — see the
  reference doc §11, qualifier 2.
