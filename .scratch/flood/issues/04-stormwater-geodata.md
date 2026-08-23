# 04 Stormwater and sewer geodata access

Type: research
Status: resolved

## Question

Verify access paths and joinable grain for the static exposure covariates: DEP
Stormwater Flood Maps `9i7c-xyvv` (categorical moderate/extreme scenarios —
File Geodatabase only, or is there a queryable ArcGIS/Socrata service? what are
the scenario layers and categories exactly), DEP green-infrastructure
`df32-vzax` `sewer_type` points, MS4 drainage polygons
(`MS42020_DrainageAreas`/`MS42020_Outfalls` ArcGIS services), DEC CSO outfalls
(license forbids rehosting — confirm fetch-and-use is fine), and catch-basin
points `2w2g-fk3i`. For each: endpoint, auth, record count, geometry type, and
what it can attach to (point buffer, polygon contains, segment overlay). Capture
as `research/flood-04-stormwater-geodata.md` (Verdict / Evidence / Unverified).

## Answer

`9i7c-xyvv` is confirmed File-Geodatabase-only (`viewType: blobby`, `/resource`
403s) — 33.8 MB zip, 4 scenario `.gdb` folders exactly (Extreme 3.66"/hr+2080
SLR, Moderate 2.13"/hr+2050 SLR, Moderate 2.13"/hr+current, Limited 1.77"/hr+
current). Tracked its web map to a real ArcGIS org (`at3rDjch5X7i9Bag`, same
org as the MS4 layers) but the display layer is a **tiled, non-queryable**
MapServer (`capabilities: Map,TilesOnly,Tilemap`) whose sublayers name the
actual flood categories: "Deep and Contiguous Flooding (>=1ft)" and "Nuisance
Flooding (>=4in, <1ft)", plus a "Future High Tides 2050" tidal layer and an
"Area not included in analysis" mask — no queryable service exists anywhere
for this data. `df32-vzax` (16,231 pts, sewer_type Combined 15,863/MS4 271/
Non-combined 93/Separate 4), MS4 `DrainageAreas` (1,354 polygons) and
`Outfalls` (764 pts), and catch basins `2w2g-fk3i` (154,212 pts) all
reproduced the vault's prior counts to the digit via live SODA/ArcGIS REST
queries, no auth. DEC CSO layer 20: confirmed `capabilities: Query,Extract`
(fetch/query explicitly supported), license text fetched verbatim — it
prohibits *secondary distribution* (rehosting), not fetch-and-use; NYC-subset
count re-measured at 398 via bbox vs. the vault's 406 via waterbody-name
filter, flagged as an open delta pending a real borough-polygon join. Full
detail, endpoints, fields, and join grain (point buffer vs. polygon contains)
per layer in `research/flood-04-stormwater-geodata.md`.
