# NYC Stormwater/Sewer Exposure Geodata — Access Paths and Joinable Grain

Researched 2026-08-22. All findings below come from live HTTP requests (curl,
direct to the Socrata and ArcGIS REST endpoints), not memory. Extends and
verifies sections 3 and 6 of `~/vault/nyc-flood-history-elevation-2026-08-12.md`
— re-derived only where verification required going deeper (finding the actual
FGDB contents and the hidden ArcGIS org behind `9i7c-xyvv`); the four
already-measured layers (`df32-vzax`, MS4 services, DEC CSO layer 20, catch
basins) are reproduced to the digit or flagged where they diverge.

## Verdict

All five covariates are fetchable programmatically, with no auth, but they
split into two access shapes:

| Layer | Shape | Queryable? |
|---|---|---|
| (a) DEP Stormwater Flood Maps `9i7c-xyvv` | **File Geodatabase only for the data**; a tiled (non-queryable) ArcGIS MapServer for the map/legend | No attribute/geometry query anywhere. Download the 33.8 MB FGDB zip and read it with GDAL/OGR locally |
| (b) DEP green infrastructure `df32-vzax` | Socrata tabular resource | Yes — SODA query, point geometry |
| (c) MS4 `MS42020_DrainageAreas` / `MS42020_Outfalls` | Hosted Esri FeatureServer | Yes — full REST query, polygon + point |
| (d) DEC CSO outfalls, layer 20 | Hosted Esri FeatureServer | Yes — full REST query, point. Fetch-and-use confirmed fine; only **rehosting** the extracted data is prohibited |
| (e) Catch basins `2w2g-fk3i` | Socrata tabular resource | Yes — SODA query, point geometry, no other attributes |

The vault's prior conclusion that DEP publishes "no open sewershed boundary
polygon" stands. New in this pass: `9i7c-xyvv`'s web map is backed by a real
ArcGIS org (`at3rDjch5X7i9Bag` — the same org that hosts the MS4 layers) and
a tiled MapServer with named flood-category sublayers, which resolves the
"what exactly are the categories" half of the ticket that the vault left open
(the vault's gap-6 table listed `9i7c-xyvv` only as "categorical 1/2/3, FGDB,
not queryable" with no category names).

---

## (a) DEP Stormwater Flood Maps `9i7c-xyvv`

**Confirmed: File-Geodatabase-only for the actual data.** The Socrata
`api/views/9i7c-xyvv.json` metadata call returns `"viewType": "blobby"`,
`"displayType": "blob"`. `GET /resource/9i7c-xyvv.json` returns
**HTTP 403** `{"error":true,"message":"no row or column access to non-tabular
tables"}` — there is no SODA table behind this asset id at all, only a blob.

The blob itself: `blobFilename: "NYCFloodStormwaterFloodMaps.zip"`,
`blobFileSize: 33,785,094` bytes, `blobMimeType: application/zip`. Direct
download URL (verified 200, `Content-Length: 33785094`, `Accept-Ranges: bytes`):

```
https://data.cityofnewyork.us/api/views/9i7c-xyvv/files/6ce7b252-a38c-47ae-a823-680f443227e5?download=true
```

A range-fetch of the last 200 KB (to read the zip's central directory without
pulling the full 33.8 MB) confirms four scenario folders, each a real Esri
File Geodatabase (`.gdb` directory of `.gdbtable`/`.gdbtablx`/`.gdbindexes`
plus `.atx` index files — the binary FGDB format, not shapefiles) with a
companion `.xlsx`:

```
NYCFloodStormwaterFloodMaps/
  NYC Stormwater Flood Map - Extreme Flood (3.66 inches per hr) with 2080 Sea Level Rise/
    ....gdb/  + .xlsx
  NYC Stormwater Flood Map - Moderate Flood (2.13 inches per hr) with 2050 Sea Level Rise/
  NYC Stormwater Flood Map - Moderate Flood (2.13 inches per hr) with Current Sea Levels/
  NYC Stormwater Flood Map - Limited Flood (1.77 inches per hr) with Current Sea Levels/
```

That is **four scenario layers exactly**, named by rainfall intensity + sea
level rise horizon: Extreme (3.66 in/hr) + 2080 SLR, Moderate (2.13 in/hr) +
2050 SLR, Moderate (2.13 in/hr) + current sea level, Limited (1.77 in/hr) +
current sea level. No "3.66/2.13/1.77" categorical field inside a single
layer — each rainfall/SLR combination is its own FGDB feature dataset.

**Is there a queryable ArcGIS service instead?** The Socrata description
links out to an ArcGIS Experience Builder app
(`https://experience.arcgis.com/experience/e83a49daef8a472da4a7e34dc25ac445/`,
labeled `nyc.gov/stormwater-map`). Pulling that app's config
(`https://www.arcgis.com/sharing/rest/content/items/e83a49daef8a472da4a7e34dc25ac445/data?f=json`,
200 OK, 57,213 B) surfaces one FeatureServer reference:
`https://services.arcgis.com/at3rDjch5X7i9Bag/arcgis/rest/services/table_flood_maps_6_2_22/FeatureServer`.
Queried directly — this is **not the flood polygons**, it is a 5-row legend
table (fields `Storm_Scenario`, `Rainfall_Intensity`, `Sea_Level_Height`,
`Notes`) used to populate the app's UI.

Following the app's item graph one level further (item ids embedded in the
config: `37621ccca69744c5abcccbfccfe68e59` = web map "SWR 10 year storm map",
owner `NYCDEP_KarolinaR`, org `at3rDjch5X7i9Bag`) turns up the actual display
layer for the moderate/10-year scenario:

```
https://tiles.arcgis.com/tiles/at3rDjch5X7i9Bag/arcgis/rest/services/10yearTile_erased_6_2/MapServer
```

`?f=json` on that service returns `"capabilities": "Map,TilesOnly,Tilemap"`,
`"singleFusedMapCache": true` — **a cached tile layer, no Query capability**,
confirming there is no queryable vector service for the flood extents
themselves, only this FGDB-only, ArcGIS-org-only, and Socrata-blob-only path.
Its named sublayers do give the exact flood category taxonomy used for
display:

```
0  Buildings NYC
1  Area not included in analysis
2  Future High Tides 2050
3  National Wetlands Inventory
4  Area not included in analysis
5  Deep and Contiguous Flooding (1ft and greater)
6  Nuisance Flooding (greater or equal to 4 in and less than 1ft)
```

So the substantive flood-depth categories per scenario are exactly two:
**"Deep and Contiguous Flooding" (>=1 ft)** and **"Nuisance Flooding" (>=4 in,
<1 ft)**, plus an exclusion mask ("Area not included in analysis") and a
separate tidal layer ("Future High Tides"). This is consistent across the
four FGDB scenario datasets (verified only for the one web map found; the
other three scenario web maps were not independently located — see
Unverified).

**Join grain**: polygon-contains only, and only after downloading and opening
the FGDB locally (`ogr2ogr`/GDAL, ArcPy, or `fiona`/`geopandas` with the
`OpenFileGDB` driver — no native GDAL install was available in this sandbox
to open the file directly, so the polygon schema/attribute table inside the
`.gdb` was not read this session; the zip contents and file format were
confirmed via the zip central directory, not by opening the FGDB tables).

---

## (b) DEP Green Infrastructure `df32-vzax`

Socrata tabular resource, fully queryable via SODA. Reproduces the vault's
16,231 exactly.

- `$select=count(*)` -> `{"count":"16231"}`
- Point geometry (`the_geom`, GeoJSON Point)
- `sewer_type` breakdown (`$select=sewer_type,count(*)&$group=sewer_type`):
  **Combined 15,863, MS4 271, Non-combined 93, Separate 4** — matches the
  vault's citywide split to the digit.
- Fields that matter beyond `sewer_type`: `asset_id`, `gi_id`, `asset_type`,
  `status`/`status_gro`, `borough`, `outfall`, `nyc_waters`, `bbl`,
  `community_`/`city_counc`/`assembly_d` (district codes), `asset_area`,
  `constructed_date`. Sample row: `bbl` present (`"4051540014"`), so this
  layer joins directly to tax-lot-level covariates without a spatial op when
  a BBL match exists, and by point-buffer otherwise.
- Auth: none. `curl -sI` on the resource endpoint returns 200 with no
  App-Token requirement enforced (unthrottled at this sample size).

**Join grain**: point buffer (nearest-N or fixed-radius) to any address/BBL;
`bbl` field also supports a direct tax-lot join where populated.

---

## (c) MS4 drainage ArcGIS services

Both live on the same ArcGIS Online org as the hidden stormwater-map layer
above (`at3rDjch5X7i9Bag`), both no-auth, `capabilities: "Query"` confirmed on
both root FeatureServer resources.

**`MS42020_DrainageAreas/FeatureServer/0`**
- `geometryType: esriGeometryPolygon`
- `returnCountOnly=true` -> **1,354** (matches vault)
- Fields: `ID`, `WATERBODY`, `FLOATABLES`, `PATHOGENS`, `NITROGEN`,
  `PHOSPHORUS`, `OWNERSHIP`, `Shape__Area`, `Shape__Length` — pollutant-index
  flags per drainage area, not raw discharge volumes.

**`MS42020_Outfalls/FeatureServer/0`**
- `geometryType: esriGeometryPoint`
- `returnCountOnly=true` -> **764** (matches vault)
- Fields: `ID`, `WATERBODY`, `FLOATABLES`, `PATHOGENS`, `NITROGEN`,
  `PHOSPHORUS`, `BORO`, `TREATMENT_PLANT`, `OUTFALLTYPE`. Sample row:
  `BORO: "BROOKLYN"`, `OUTFALLTYPE: "MS4 OUTFALL"`, `WATERBODY: "SHEEPSHEAD
  BAY"` — so `BORO` gives a free borough attribute without a spatial join.
- Spatial reference is state-plane (`wkid 102718`/`2263`) natively; request
  `outSR=4326` for lon/lat.

**Join grain**: `DrainageAreas` supports polygon-contains (a point-in-polygon
test against the 1,354 drainage polygons tells you which MS4 catchment a
location sits in); `Outfalls` supports point-buffer or nearest-outfall.

---

## (d) NYSDEC CSO outfalls FeatureServer, layer 20

```
https://services6.arcgis.com/DZHaqZm9cxOD4CWM/arcgis/rest/services/Combined_Sewer_Overflow__CSO__Outfalls/FeatureServer/20
```

- No auth. Root `FeatureServer?f=json` -> `"capabilities": "Query,Extract"`.
  **Extract is explicitly enabled** — the service itself grants programmatic
  fetch/export, which is the practical confirmation the ticket asked for.
- `geometryType: esriGeometryPoint`, native SR `wkid 26918` (UTM 18N NAD83);
  fields also carry plain `LAT`/`LONG_` doubles so no reprojection is needed.
- `returnCountOnly=true` (no filter) -> **789** statewide, matches vault.
- NYC-bbox count (`geometry=-74.26,40.49,-73.68,40.92&geometryType=
  esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelIntersects`) ->
  **398**. The vault's figure was 406 (derived from a waterbody-name filter,
  not a bbox). **Flagging this delta, not resolving it** — a rectangular bbox
  clips differently than a receiving-waterbody-name allowlist near the city
  line (e.g. it can both drop a true edge point and admit an out-of-city one);
  treat 398-406 as the working range and do an actual borough-polygon
  spatial join before quoting a precise NYC count.
- Fields: `SPDES_PERMIT_NUMBER`, `OUTFALL_NUMBER`, `RECEIVING_WATERBODY_NAME`,
  `DETAIL_URL`, `MOREINFO_URL`, `EPA_CHAR__CODE`, `TREATMENT`, `LAT`,
  `LONG_`. No discharge-volume field on this layer (matches vault's note that
  volumes only exist in the unofficial Open Sewer Atlas).

**License text, fetched from the parent ArcGIS Online item
(`21c2ab88012444f69d20fbb1550e8937`), verbatim:**

> 1. The NYS DEC asks to be credited in derived products. 2. Secondary
> Distribution of the data is not allowed. 3. Any documentation provided is
> an integral part of the data set. Failure to use the documentation in
> conjunction with the digital data constitutes misuse of the data. 4.
> Although every effort has been made to ensure the accuracy of information,
> errors may be reflected in the data supplied...

**Fetch-and-use terms, confirmed**: querying/downloading via the REST API
(`Query,Extract` capability, live and working, no auth) is fine and is the
intended access path — DEC hosts this specifically for programmatic
consumption. What's prohibited is *secondary distribution*: don't rehost a
copy of the raw dataset for others to pull from raincheck's own
infrastructure. Computing derived covariates from it (e.g., a per-cell
"CSO-outfall-count-within-500m" feature) and crediting NYS DEC is consistent
with the license; re-publishing the outfall point layer itself is not.

**Join grain**: point buffer (nearest-outfall distance, or count-within-radius)
to a location or grid cell; no polygon geometry on this layer to do
contains-style joins.

---

## (e) Catch basins `2w2g-fk3i`

Socrata tabular resource, fully queryable.

- `$select=count(*)` -> `{"count":"154212"}`, matches vault exactly.
- Point geometry only. Fields: `unitid`, `latitude`, `longitude`, `point_x`,
  `point_y`, and four `:@computed_region_*` codes (Socrata's auto-generated
  point-in-polygon lookups against city boundary layers) — **no elevation,
  no install/clean date, no pipe-diameter or capacity field of any kind.**
- Borough-code ambiguity, re-verified: grouping by
  `:@computed_region_yeji_bk3q` gives `{1: 19426, 2: 37137, 3: 66388, 4:
  13357, 5: 17874, null: 30}`. Region code **3 = 66,388**, reproducing the
  vault's cited "66,388" figure for one of the two disputed groupings
  exactly. The vault's competing figure (66,399, from a UNITID-prefix
  grouping) was not re-derived this session — still resolve by spatial join
  to actual borough polygons before quoting a Brooklyn-specific count, as the
  vault already recommended.

**Join grain**: point buffer only (density-per-cell / nearest-basin-distance).
No polygon or line geometry to overlay against a street segment.

---

## Evidence

| # | Request | Result |
|---|---|---|
| 1 | `GET data.cityofnewyork.us/api/views/9i7c-xyvv.json` | 200, 4,508 B, `viewType: blobby`, lists 4 scenario names |
| 2 | `GET data.cityofnewyork.us/resource/9i7c-xyvv.json?$limit=5` | **403**, `"no row or column access to non-tabular tables"` |
| 3 | `GET data.cityofnewyork.us/api/views/9i7c-xyvv/files/6ce7b252-...?download=true` (HEAD) | 200, `Content-Length: 33,785,094`, `Accept-Ranges: bytes` |
| 4 | Range GET, last 200,000 B of the zip, parsed as ZIP central directory | 199 entries: 4x `.gdb` FGDB folders + 4x `.xlsx`, confirmed FGDB binary format |
| 5 | `GET arcgis.com/sharing/rest/content/items/e83a49daef8a472da4a7e34dc25ac445/data?f=json` | 200, 57,213 B, surfaces `table_flood_maps_6_2_22/FeatureServer` |
| 6 | `GET services.arcgis.com/at3rDjch5X7i9Bag/.../table_flood_maps_6_2_22/FeatureServer/0?f=json` | 200, table (not spatial), 5 rows, fields `Storm_Scenario/Rainfall_Intensity/Sea_Level_Height/Notes` |
| 7 | `GET arcgis.com/sharing/rest/content/items/37621ccca69744c5abcccbfccfe68e59/data?f=json` (web map) | 200, operational layers include `tiles.arcgis.com/.../10yearTile_erased_6_2/MapServer` |
| 8 | `GET tiles.arcgis.com/.../10yearTile_erased_6_2/MapServer?f=json` | 200, `capabilities: Map,TilesOnly,Tilemap`, 7 named sublayers |
| 9 | `GET data.cityofnewyork.us/resource/df32-vzax.json?$select=count(*)` | 200, `{"count":"16231"}` |
| 10 | `GET .../df32-vzax.json?$select=sewer_type,count(*)&$group=sewer_type` | 200, Combined 15863 / MS4 271 / Non-combined 93 / Separate 4 |
| 11 | `GET services.arcgis.com/at3rDjch5X7i9Bag/.../MS42020_DrainageAreas/FeatureServer/0/query?...returnCountOnly=true` | 200, `{"count":1354}` |
| 12 | `GET services.arcgis.com/at3rDjch5X7i9Bag/.../MS42020_Outfalls/FeatureServer/0/query?...returnCountOnly=true` | 200, `{"count":764}` |
| 13 | `GET services6.arcgis.com/DZHaqZm9cxOD4CWM/.../CSO.../FeatureServer/20/query?...returnCountOnly=true` (no filter) | 200, `{"count":789}` |
| 14 | same, NYC bbox envelope filter | 200, `{"count":398}` |
| 15 | `GET arcgis.com/sharing/rest/content/items/21c2ab88012444f69d20fbb1550e8937?f=json` | 200, full `licenseInfo` text captured verbatim (see above) |
| 16 | `GET data.cityofnewyork.us/resource/2w2g-fk3i.json?$select=count(*)` | 200, `{"count":"154212"}` |
| 17 | `GET .../2w2g-fk3i.json?$select=:@computed_region_yeji_bk3q,count(*)&$group=...` | 200, region 3 = 66,388 |

---

## Unverified

- The FGDB's internal polygon schema and attribute table (field names for
  the flood-depth polygons themselves, e.g. is depth stored as a category
  string or a continuous value) — not opened this session, no GDAL/OGR/fiona
  available in-sandbox to read the `OpenFileGDB` driver. Confirmed only the
  zip's file listing and format (via the ZIP central directory), not the
  in-`.gdb` schema.
- Whether the other three scenario web maps (Extreme 2080, Moderate current,
  Limited current) each have their own tiled MapServer with the same
  Deep-and-Contiguous / Nuisance category split, or a different one — only
  the "SWR 10 year storm map" (Moderate, current-adjacent) web map was
  located and inspected. The Experience Builder app config referenced only
  one FeatureServer (the legend table); the other three tile services were
  not hunted down.
- The exact reconciliation of the DEC CSO NYC-subset count: bbox gives 398,
  vault's waterbody-name method gave 406. Neither was cross-checked against
  an authoritative NYC borough-boundary polygon this session.
- Whether `df32-vzax`'s `bbl` field is consistently populated across all
  16,231 rows or only on a subset (only one sample row was inspected).
- Rate limits / App-Token requirements on sustained pulls (all queries this
  session were small samples; no throttling was hit, but none was tested at
  volume).
