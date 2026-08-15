# raincheck raster playbook

Working reference. Everything below is either verified against a primary source (URL/tag given) or explicitly marked UNVERIFIED. Sedona claims are pinned to tag `sedona-1.9.1` (commit `5d4b8608f14c87bea7a610dbbe9373bb8dbabfb8`).

---

## 1. Eight ways to think about a mosaic

**1. Spatial tile mosaic (tiles to one surface).** Adjacent, different-extent tiles stitched into one continuous grid. In raincheck this is the NYC 2017 bare-earth DEM: LAS 1.4 point tiles at 2,500 x 2,500 ft, DEM/DSM rasters reassembled to 25,000 x 25,000 ft tiles, EPSG:2263 ftUS, NAVD88 Geoid12B. Sedona cannot do this (see section 4), so it happens in GDAL before Spark sees anything. One call: `gdalbuildvrt -r bilinear -srcnodata -9999 -vrtnodata -9999 -input_file_list dem_tiles.txt nyc_dem_2017.vrt` (zero-copy XML index, no pixel duplication).

**2. Temporal composite (frames to one summary).** Same footprint, many timestamps, reduced along time. This is every rolling accumulation and storm total in raincheck: 1/3/6/24h rolling rain, Ida storm total, per-cell dry-hour median speed. Because AORC and MRMS hourly QPE store depth already accumulated over the hour, the reduction is a moving SUM, never a moving mean and never rate x N. One call: `da.rolling(time=N, min_periods=N).sum()`.

**3. Multi-sensor blend.** Two instrument families reconciled into one field. NOAA already ships this: `MultiSensor_QPE_01H_Pass1` (about 20 min latency, fewer gauges) and `_Pass2` (about 60 min latency, more gauges, more accurate) are the radar-plus-gauge merge, versus `RadarOnly_QPE_01H` with no gauge correction. Do not rebuild a bias correction from ASOS/Mesonet/CoCoRaHS; use those only as an independent validation check. One call: choose the prefix, `aws s3 ls s3://noaa-mrms-pds/CONUS/MultiSensor_QPE_01H_Pass2/ --no-sign-request`.

**4. Multi-resolution pyramid, and the H3 hierarchy as its DGGS twin.** A COG's overview levels and H3's aperture-7 resolution ladder are the same idea: precomputed coarser views so a query reads only what it needs. H3 cell counts confirm the ratio: res 7 = 98,825,162 cells, res 8 = 691,776,122, res 9 = 4,842,432,842 (ratio approx 7.0 per step). H3's index-level hierarchy (`cell_to_parent`, `compact_cells`) is exact and lossless; only the boundary polygons are approximate across resolutions, so never do area-weighted overlay on `ST_H3ToGeom` output at two different res levels. One call: `gdal_translate -of COG -co COMPRESS=DEFLATE -co OVERVIEWS=IGNORE_EXISTING in.vrt out_cog.tif`.

**5. Attribute / dasymetric mosaic.** Redistributing a value from coarse zones onto a finer ancillary surface. Relevant for pushing block-group NFIP claim rates or zone-level ridership onto building footprints (1,083,024 NYC polygons, `5zhs-2jue`). Deliberately NOT used for flood labels: disaggregating block-group claims to H3 cells fabricates precision the source lacks. One call: PySAL `tobler` binary dasymetric (exact function signature UNVERIFIED, check the installed version's docstring before writing kwargs).

**6. Analytical layer cake (per-cell feature cube).** Heterogeneous variables stacked as data variables on one shared grid, so a single `.sel()` returns a full per-cell-hour feature vector. This is the flood exposure stack (rain, HAND, depression depth, imperviousness, distance-to-CSO, sewer type, freeboard) and the bus regression design matrix. The whole cost is grid alignment, not the arithmetic. One call: `xr.Dataset({"rain": da_rain, "hand": da_hand, ...})` after every layer is snapped to one transform.

**7. Vector-as-raster.** Turning polygons and points into aligned arrays so intersection becomes array indexing instead of geometric overlay. Borough masks, MS4 drainage polygons (n=1,354), `sewer_type`, DEP `Flooding_Category`. Sedona's `RS_AsRaster` is the wrong tool for many differently-valued features (one geometry, one scalar per call, all five overloads). One call: `rasterio.features.rasterize(shapes=[(geom, code), ...], out_shape=..., transform=..., merge_alg=MergeAlg.replace)`; switch to `MergeAlg.add` to get counts.

**8. Discrete global grid as the raster substitute.** Skip the pixel grid entirely and key everything by H3 cell id, which sidesteps CRS, alignment, and NoData in one move. At NYC latitude an AORC cell is roughly 0.70 km x 0.93 km, about 0.65 km2; H3 res 8 averages 0.737 km2, so res 8 is close to 1:1 with AORC (a relabeling, not a disaggregation) and res 9 gives about 6 hexes per AORC cell. Use res 8 as the join key for the bus analysis. One call: `ST_H3CellIDs(geom, 8, false)` in Sedona, or `h3.latlng_to_cell(lat, lon, 8)` in Python.

---

## 2. Raster inventory

| Layer | Source | Res | CRS / units | Native format | Role |
|---|---|---|---|---|---|
| AORC v1.1 precip | `s3://noaa-nws-aorc-v1-1-1km/{year}.zarr` | 1/120 deg (approx 703 x 925 m at 40.7N), hourly | EPSG:4326; `APCP_surface` kg/m2 = mm, int16 scale 0.1, fill -32767 | Zarr, chunks [144h,128,256] | rain (historical) |
| MRMS RadarOnly / MultiSensor QPE | `s3://noaa-mrms-pds/CONUS/{RadarOnly_QPE_01H,MultiSensor_QPE_01H_Pass2,PrecipRate,RadarOnly_QPE_15M}/` | 0.01 deg (approx 844 x 1110 m at 40.7N), 2 min files | EPSG:4326; mm depth or mm/hr | GRIB2.gz | rain (live/2026) |
| MRMS FLASH, 19 prefixes | `s3://noaa-mrms-pds/CONUS/FLASH_QPE_ARI{30M,01H,03H,06H,12H,24H,MAX}_00.00/YYYYMMDD/`, `FLASH_QPE_FFG{01H,03H,06H,MAX}_00.00/`, `FLASH_{CREST,SAC}_MAX{SOILSAT,STREAMFLOW,UNITSTREAMFLOW}_00.00/`, `FLASH_HP_MAX{STREAMFLOW,UNITSTREAMFLOW}_00.00/` | 1 km, 2 min | ARI in years; FFG dimensionless ratio; streamflow m3/s, unit streamflow m3 s-1 km-2 | GRIB2.gz, e.g. `MRMS_FLASH_QPE_ARI01H_00.00_20260815-000000.grib2.gz` | rain severity (precomputed) |
| NOAA Atlas 14 Vol 10 v3 grids | `https://hdsc.nws.noaa.gov/pub/hdsc/data/ne/ne{RETURN}yr{DUR}{a\|al\|au}[_ams].zip`, e.g. `ne2yr60ma.zip` | grid, 19 durations x 10 ARIs | UNVERIFIED: `.prj` present but not opened; depth units reported as thousandths of an inch, confirm before use | zip of `.asc` + `.prj` + `.xml` | rain severity denominator |
| HRRR nowcast | `s3://hrrrzarr/sfc/{YYYYMMDD}/{YYYYMMDD}_{HH}z_fcst.zarr/surface/APCP_1hr_acc_fcst/` | UNVERIFIED, commonly cited approx 3 km Lambert Conformal | mm (kg/m2) | Zarr | rain (forecast) |
| NYC 2017 LiDAR classified LAZ + DEM + DSM | NYC Open Data `7sc8-jtbz` | 1 ft; DEM 15.6 GB, DSM 30.1 GB, LAZ 109.5 GB | EPSG:2263 ftUS, NAVD88 Geoid12B | LAS 1.4 / GeoTIFF | terrain; class 25 = Subway/Transit stairwells |
| NYS ImageServer DEMs | `elevation.its.ny.gov/arcgis/rest/services/NYC_TopoBathymetric_2017_1_meter/ImageServer` | 1 m | metres, NAVD88 | ImageServer `getSamples`, approx 1,000 pts/POST | terrain |
| InSAR subsidence velocity | `zenodo.org/records/8436658` | UNVERIFIED (res, units, sign convention all unchecked) | UNVERIFIED, assumed mm/yr | GeoTIFF | terrain (dynamic) |
| NYC Land Cover 2017 | `data.cityofnewyork.us/Environment/Land-Cover-Raster-Data-2017-6in-Resolution/he6d-2qns` | 6 in, 8 classes | EPSG:2263 (per nyc-geo-metadata, not read from header) | zip raster, 1.27 GB | land cover |
| NYC Land Cover 2010 | `data.cityofnewyork.us/.../9auy-76zt` | UNVERIFIED: title says 3 ft, a data.gov mirror says 6 in and cites `landcover_2010_nyc_05ft.zip`; 3 sq ft is the minimum mapping unit, not pixel size | presumed EPSG:2263 | zip raster, 101 MB | land cover (change) |
| Tree Canopy Change 2010-2017 | `data.cityofnewyork.us/d/by9k-vhck` | 6 in | EPSG:2263 | zip | land cover (change) |
| NLCD 2021 impervious + descriptor | DOI `10.5066/P9JZ7AO3` (the commonly cited `s3-us-west-2.amazonaws.com/mrlc/...` zip returned HTTP 403, do not hardcode) | 30 m | Albers Conical Equal Area, WGS84, SP 29.5/45.5N, CM -96.0, lat0 23.0 | GeoTIFF zip | land cover; note the "2021" impervious release is unchanged 2019 data |
| gSSURGO NY | `https://nrcs.app.box.com/v/soils` (UNVERIFIED, 4 fetch attempts to NRCS domains failed) | `MapunitRaster_10m`, 10 m | UNVERIFIED, reported Albers | ESRI File GDB | soils (HSG via `HYDGRPDCD` in `MUAGGATT`, join on `MUKEY`; NYC "Urban land" units often have no HSG) |
| Sentinel-2 L2A | `https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a` | 10 m / 20 m | UTM per tile | COG via STAC; assets incl. `red`, `nir`, `scl` | land cover (staleness check only, 800-1600x coarser by area than the 6in layer) |
| NYC orthoimagery | `https://gisdata.ny.gov/ortho/nysdop12/new_york_city/spcs/zips/boro_bronx_sp24.zip` (pattern `.../nysdopNN/new_york_city/spcs/zips/boro_{borough}_sp{YY}.zip`) | 6 in, 2006-2024 biennial | EPSG:2263/6539 capture, EPSG:3857 web service | zip | land cover / QA |
| DEP GI points, MS4 polygons | `df32-vzax`; MS4 n=1,354 | vector | EPSG:2263 | Socrata | infrastructure (`sewer_type`, 97.7% combined) |
| NYSDEC CSO outfalls | NYSDEC, 406 NYC points | vector | - | point | infrastructure |
| Citywide Catch Basins | `data.cityofnewyork.us/Environment/Citywide-Catch-Basins/2c5m-rke8` (use this id; `2w2g-fk3i` and `rc6s-3xkv` are UNVERIFIED possible duplicates) | vector | - | Socrata | infrastructure |
| NYC Building Footprints | `5zhs-2jue`, 1,083,024 rows | vector | `groundelev` ft NAVD88, 99.93% populated | Socrata | infrastructure (local grade proxy, NOT entrance elevation) |
| Bus position archive | `s3.amazonaws.com/nycbuspositions` daily CSV.xz | per-ping, 2017-07-14 to 2024-09 | WGS84 | CSV.xz, `speed` column empty | bus-as-raster |
| MTA Bus GTFS-RT | live feed, approx 1,800 vehicles per 30 s poll | per-ping | WGS84 | protobuf | bus-as-raster |
| FloodNet events / sensors | `aq7i-eu5q` / `kb2e-tjy3`, 2,776 events, 286 sensors | point | - | Socrata | label |
| 311 flooding complaints | `76ig-c548` (2010-2019, 252,151) + `9qq5-d465` (2020-2026, 142,727) | point | - | Socrata | label |
| NFIP claims v3 | OpenFEMA, 44,110 NYC rows | block group | - | tabular | label (coarse validation only) |
| USGS STN Sandy HWMs | USGS Short-Term Network, 111 in-city | point | NAVD88 | tabular | label (spot check, small N) |
| NYC Sandy Inundation Zone | `5xsi-dfpx`, 492 polygons | vector | EPSG:2263 | Socrata | label (single event) |
| DEP Stormwater Flood Maps | `9i7c-xyvv` | raster/vector, `Flooding_Category` 1/2/3 | EPSG:2263 | file GDB | reference model (comparison, not training label) |
| CO-OPS 8518750 (The Battery) | NOAA CO-OPS | station | NAVD88 = STND + 6.06 ft | API | datum bridge |
| IEM ASOS (KNYC, KLGA, KJFK) | `https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?data=p01i&station=KNYC&sts=...&ets=...&tz=UTC&format=onlycomma` | hourly | inches (`p01i`) | CSV | gauge validation (1 s/IP throttle) |
| NYS Mesonet NYC Micronet | `nysmesonet.org/networks/nyc`, 29 stations (21 Con Ed, 8 NYSM) | 5 min | - | web request form, no public API | gauge validation |

---

## 3. Calculation catalog

Ranked by insight per unit of effort, best first. "Runs in" names the engine that should actually execute it.

### Two standing rules first

**Regridding MRMS onto the AORC grid.** Direction correction: at 40.7N, MRMS cells (approx 844 x 1110 m) are COARSER than AORC cells (approx 703 x 925 m), so this is refinement, not coarsening. Precipitation is an extensive quantity, so area-weighted conservative regridding is still the theoretically correct choice in either direction. Preferred: `xesmf.Regridder(src, dst, method="conservative")` and note it requires cell-corner arrays (`lon_b`/`lat_b`) on both grids, not just centers. Lighter substitute when exact corner-polygon overlap is overkill: `rasterio.warp.reproject(..., resampling=Resampling.average)`, or `Resampling.sum` (GDAL >= 3.1) when a total rather than a density must survive. Build the weight matrix once, cache it, reuse per timestep.

**Resampling method by variable type.** Categorical (`sewer_type`, `Flooding_Category`, land cover class, HSG): nearest neighbour, always. Continuous surfaces (elevation, HAND, imperviousness fraction, InSAR velocity): bilinear, or bicubic for smooth fields. Precipitation aggregated in time: straight sum, inherently mass conserving. Precipitation resampled in space where volume matters: conservative/area-weighted. Precipitation resampled in space only to point-sample for a join: bilinear is fine. Sedona's `RS_Resample` takes a method string; `Bilinear`, `Bicubic`, `NearestNeighbor` are the documented set, default `NearestNeighbor`; it does not support skewed input rasters.

### The catalog

**1. Dry-baseline hour-of-week speed raster, plus wet-minus-dry anomaly and wet/dry ratio.** Value 5/5.
```
baseline[cell, how] = median(speed | AORC < 0.1 mm/hr, hour_of_week = how)
anomaly[cell, t]    = speed[cell, t] - baseline[cell, hour_of_week(t)]
ratio[cell]         = median(speed | wet) / median(speed | dry)
```
Inputs: per-ping derived speed joined to H3 res-8 cell x 168 hour-of-week bins (local America/New_York), AORC wet/dry mask per cell-hour. Tool: PySpark `groupBy` + `percentile_approx`; `ST_H3ToGeom` for rendering. Runs in: Spark for the ping join, plain pandas is enough for the 3,500 x 168 reduction. Effort: 0.5 to 1 day. Buys: the entire "does rain slow buses, and where" question with zero model fitting.

**2. Per-cell support raster N.** Value 4/5. `n[cell, how] = count(pings) group by (cell, hour_of_week)`, split `n_dry` / `n_wet`. Same Spark job as item 1, one extra `count()` column, effectively free. Buys: the gate on trusting every other raster here. Threshold it (say n >= 30) before publishing anything.

**3. Extract rain at each bus position (the core join).** Value 5/5.
```sql
-- Sedona's own RS_Values doc pattern, applied verbatim
SELECT r.rast, collect_list(p.geom) AS pts
FROM bus p JOIN precip r ON ST_Within(p.geom, RS_Envelope(r.rast))
GROUP BY r.rast
-- then
SELECT RS_Values(rast, pts, 1) FROM ...
```
`RS_Values(raster, points: ARRAY[Geometry][, band])`, since v1.4.0, auto-reprojects points to the raster CRS since v1.5.1, documented as significantly faster than repeated `RS_Value` because the raster decodes once per row. Runs in: Sedona, fully distributed. Effort: low. Buys: the only place in this project where Sedona rasters are unambiguously the right tool.

**4. Per-cell regression.** Value 5/5.
```
speed_it = b0 + b1*rain_t + b2*rain_{t-1} + b3*antecedent_24h_sum
         + hour_dummies + dow_dummies + school_flag + cbd_pricing_flag + e_it
```
Fit once per H3 cell. Tool: `statsmodels.OLS` (or `linearmodels.PanelOLS` with cell fixed effects if pooling). Runs in: plain numpy/pandas on the M4; approx 3,500 tiny independent fits, Spark is unnecessary. Effort: 1 to 2 days, almost all of it the confounder join. Buys: a coefficient with a standard error instead of an eyeballed difference. Sanity-check magnitudes against, do not target, two published figures: each added mm/hr of rain raised the odds a driver slows by about 5.8% on instrumented freeways (doi 10.3390/vehicles5010009), and urban arterial capacity fell 1,554 to 1,497 to 1,283 veh/hr/lane going dry to light rain to heavy rain (Mejia et al., NCTS UP Diliman).

**5. Rolling mass-consistent accumulation, 1/3/6/24h.** Value 5/5. `da.rolling(time=N, min_periods=N).sum()` on AORC `APCP_surface` or MRMS `*_QPE_01H`. Runs in: Python xarray, driver-side, seconds for a 3,500-cell NYC bbox. Do this in xarray, not Sedona: Sedona 1.9.1 cannot read Zarr at all and ships no GRIB2 constructor. Buys: every downstream intensity and severity metric.

**6. Median speed (or any stat) per grid cell.** Value 5/5. `scipy.stats.binned_statistic_2d(x=lon, y=lat, values=speed, statistic='median', bins=[x_edges, y_edges])`. Runs in: single-node Python. One call, arbitrary reducer, unlike `rasterize` which burns a constant. Prefer this over any Sedona rasterization path for the bus-as-raster step.

**7. Per-ping speed derivation with outlier rules.** Value 5/5 (prerequisite for 1, 4, 6). `pyproj.Geod(ellps='WGS84').inv(lon1, lat1, lon2, lat2)` between successive pings within the same `vehicle_id` AND `trip_id`, divided by dt. Drop: dt <= 0 or dt > 600 s; implied speed > 35 m/s; pairs crossing a vehicle or trip boundary; pings within approx 50 m of a GTFS `stop_id` (dwell inflation is a different phenomenon from link slowdown and biases the coefficient). Thresholds are physically derived bounds, not literature values; tune against the ping speed distribution. Note the archive's `speed` column is empty, so this is mandatory, not optional.

**8. Severity ratio raster.** Value 5/5. `severity = accum_duration_mm / atlas14_mm[duration, ARI=2yr]`, after a one-time regrid of the Atlas 14 grid onto the working grid. 1-hour 2-year mean PDS grid is exactly `https://hdsc.nws.noaa.gov/pub/hdsc/data/ne/ne2yr60ma.zip`. For anything after 2020 it is cheaper to consume NOAA's precomputed `FLASH_QPE_ARI01H_00.00` (recurrence interval in years) than to rebuild this. Runs in: xarray/numpy. Effort: light after the regrid; the regrid is the cost.

**9. Antecedent Precipitation Index.** Value 4/5. `API_t = k * API_{t-1} + P_t`, an unnormalized leaky integrator that stays in mm and grows without bound. Use `scipy.signal.lfilter([1], [1, -k], P)`, NOT `pandas.ewm()`, which computes a normalized weighted average with different math. Sub-daily: `k_step = k_day ** (step_hours / 24)`. k = 0.90/day (Kohler and Linsley 1951) with a 0.80 to 0.98 range in secondary sources; no primary NWS document confirmed and no NYC calibration found. Runs in: Python, milliseconds per series.

**10. Storm-total vs speed-anomaly composites (Ida 2021-09-01, 2023-09-29).** Value 4/5. `storm_total[cell] = AORC.sel(time=slice(t0,t1)).sum('time')` next to `mean(speed anomaly)` over the same window. Both dates sit inside the CSV.xz archive (ends 2024-09) and the frozen AORC Zarr, so both are buildable today with no live-capture wait. Runs in: xarray plus pandas, single process. Buys: the artifact a non-technical reader understands, and an out-of-sample check on item 4.

**11. HAND (Height Above Nearest Drainage).** Value 4/5. `HAND[cell] = DEM[cell] - DEM[nearest downslope drainage cell along the D8 flow path]`. Tool: WhiteboxTools `elevation_above_stream(--dem, --streams)`, documented as essentially equivalent to HAND per Renno et al. 2008 (there is no tool literally named HAND in WBT); or GRASS `r.watershed` for the accumulation, thresholded into a stream network. `pysheds.grid.compute_hand(...)` exists but two sources disagreed on its current call shape, check `help()` on the installed version. Runs in: compiled CLI, not Spark; downsample the DEM to 3 m first. Effort: 1 day, mostly the mosaic and the stream-initiation threshold. Same descriptor NOAA-OWP uses for national FIM, so results stay comparable to the literature.

**12. Intensity metrics.** Value 5/5. `storm_total = precip.sel(time=slice(t0,t1)).sum('time')`; `hours_above = (hourly_mm_per_hr >= 12.7).sum('time')`; `max_60min = accum_1h.sel(...).max('time')`; for 15-minute intensity read `RadarOnly_QPE_15M` directly rather than rebuilding from 2-minute `PrecipRate`. 12.7 mm/hr (0.50 in/hr) is the one threshold read from a primary source, Gerard et al. 2021 BAMS, doi 10.1175/BAMS-D-19-0273.1, where it synchronizes six urban flash-flood case studies. A full NWS light/moderate/heavy table could not be confirmed (AMS Glossary and a NOAA repository page both returned HTTP 403), so do not cite one.

**13. Curve number runoff, incremental form.** Value 4/5.
```
S = 1000/CN - 10            (inches)
F(x) = (x - 0.2S)^2 / (x + 0.8S)   for x > 0.2S, else 0
Q(t) = F(P_cum(t)) - F(P_cum(t-1))
```
where `P_cum` is the running sum since event start (6 consecutive dry hours ends an event). Do NOT apply the closed-form Q to each hour's raw P independently: that treats every hour as its own storm and double-counts Ia = 0.2S every hour, badly undercounting runoff. This is the form SWMM and HEC-HMS use internally. Formula is TR-55 / NEH-630-10, corroborated across secondary sources; the primary PDF at `https://directives.nrcs.usda.gov/sites/default/files2/1712930818/31754.pdf` downloaded but its text was not extractable, so treat the specific Table 2-2 CN values as UNVERIFIED until spot-checked. CN crosswalk from the 8 NYC land cover classes: Buildings/Roads/Other Impervious/Railroads to the impervious row (CN 98); Water excluded from CN runoff entirely; Tree Canopy/Grass-Shrubs/Bare Soil to woods/open-space/fallow rows, each varying by HSG. Runs in: xarray cumsum plus vectorized arithmetic.

**14. Pond depth proxy.** Value 4/5. `pond_depth = filled_dem - dem`, zero everywhere except inside a filled depression, where it equals the standing-water depth needed to overtop that basin's outlet. Fill with `richdem.FillDepressions(dem, epsilon=True)` (epsilon adds a per-cell gradient so no flat cells remain for routing) or WhiteboxTools `breach_depressions_least_cost` (Lindsay and Dhun 2015, breaching is generally preferable to filling in urban terrain). The subtraction itself is plain elementwise arithmetic, not a named function anywhere.

**15. Flood exposure weighted linear index.** Value 5/5.
```
exposure = w1*rain_severity_pctile + w2*(1 - HAND_norm) + w3*pond_depth_norm
         + w4*impervious_frac + w5*(1 - dist_to_cso_norm)
         + w6*combined_sewer_flag + w7*(1 - entrance_freeboard_norm)
```
All terms min-max normalized 0 to 1. Runs in: xarray/numpy after every layer is snapped to one grid, or Sedona map algebra if the layers already live as Sedona rasters. Effort: 2 to 3 days, almost all of it aligning seven heterogeneous layers. Buys: the cheapest thing that produces a real per-cell number, and the correct first rung before any fitted model.

**16. TWI and SPI.** Value 3/5. `TWI = ln(SCA / tan(slope_radians))`, `SPI = accumulation * tan(slope)`. GRASS `r.watershed` emits both alongside accumulation in one call (`tci=` and `spi=` outputs), which is the lazy path. WhiteboxTools `wetness_index` takes an SCA raster (not log-transformed) plus a slope raster in degrees and writes sentinel 32767 at zero-slope cells. xarray-spatial, pysheds, and RichDEM have neither; build manually from their accumulation and slope outputs.

**17. nDSM for subway headhouse detection.** Value 3/5. `ndsm = dsm - dem` after both are warped onto one identical grid. NYC stair headhouses are a few metres across, so this needs 1 ft or at most 1 m, never 3 m. Cheaper and more precise cross-check: extract the points directly, since NYC's 2017 classification has a custom class 25 for subway/transit stairwells.
```json
["tile.laz",
 {"type":"filters.range","limits":"Classification[25:25]"},
 {"type":"writers.las","filename":"tile_class25.laz"}]
```

**18. Point value sampling at many locations.** Value 4/5. Python: `dataset.sample(xy, indexes=None, masked=False)` (nearest pixel, not interpolated; `rasterio.sample.sort_xy` measurably improves IO on large rasters), or vectorized xarray `da.sel(x=xr.DataArray(xs, dims="points"), y=xr.DataArray(ys, dims="points"), method="nearest")`. CLI: `gdallocationinfo -geoloc -valonly -E -field_sep , file.tif x y` (`-E` and `-field_sep` added in GDAL 3.9).

**19. Route x rain exposure sampling.** Value 4/5. Sedona-native chain: `RS_Values(precip_raster, ST_DumpPoints(ST_Segmentize(route_geom, 50.0)), 1)`. Note `ST_LineInterpolatePoints` (plural) does not exist; only the singular `ST_LineInterpolatePoint` (since v1.6.0) which returns one point per call. Python fallback: `shapely.segmentize(route_geom, 50.0)` then `dataset.sample(...)`.

**20. Getis-Ord Gi* hotspots on the coefficient raster.** Value 4/5. `esda.G_Local(y=coef_array, w=h3_neighbor_weights, transform='B', permutations=999, star=True)`, mask by the support raster first. Build weights from H3's native adjacency (`h3.grid_disk` / `h3.grid_ring`), not derived polygon contiguity. Cheaper first pass: a 3x3 or 5x5 focal mean, z-scored against the global distribution. Runs in: single process, 3,500 cells is trivial.

**21. Ping-count raster.** Value 4/5. `rasterio.features.rasterize(shapes=[(pt, 1) for pt in pings], out_shape=(rows, cols), transform=affine, merge_alg=rasterio.enums.MergeAlg.add, dtype='int32')`. The default `MergeAlg.replace` silently keeps only the last point per pixel and loses the count. Full signature: `rasterize(shapes, out_shape=None, fill=0, nodata=None, masked=False, out=None, transform=identity, all_touched=False, merge_alg=MergeAlg.replace, default_value=1, dtype=None, skip_invalid=True, dst_path=None, dst_kwds=None)`.

**22. Late-bus KDE surface.** Value 4/5. `xrspatial.kde.kde(x, y, weights=None, bandwidth='silverman', kernel='gaussian', x_range=..., y_range=..., width=W, height=H)` returns an `xr.DataArray` directly, so it composites into the same Dataset as the rain layers with no separate rasterize step. `scipy.stats.gaussian_kde(dataset, bw_method=None, weights=None)` returns a callable you must evaluate over a meshgrid yourself. For 311 and FloodNet KDE: work in a projected metric CRS, fix an explicit bandwidth around 50 to 250 m (block/street scale), sweep two or three values; Scott/Silverman defaults will oversmooth at NYC scale.

**23. Building footprint coverage fraction per cell.** Value 3/5. `pip install exactextract` now works directly (v0.3.0, released 2025-12-01, prebuilt wheels for macOS 11+ ARM64, so Apple Silicon is covered; the 2024 issue saying Python needed a from-source build is stale). Plain `rasterize` with `all_touched` gives a 0/1 mask, not a fraction. Zero-new-dependency fallback: supersample and block-average.

**24. Proximity rasters (CSO outfalls, coastline).** Value 3/5. `scipy.ndimage.distance_transform_edt(~source_mask) * cell_size`, or the GDAL CLI `gdal_proximity.py`. Prefer either over `xrspatial.proximity`, whose plain Euclidean function name was never confirmed.

**25. Multi-epoch DEM differencing noise floor.** Value 3/5. `RMSEz = NVA95 / 1.96`; `sigma_diff = sqrt(RMSEz_a^2 + RMSEz_b^2)`; detectable change at 95% is approx `1.96 * sigma_diff`. UNRESOLVED CONFLICT: project context gives 2017 NVA95 = 7.4 cm (implying RMSEz approx 3.8 cm), but a live fetch of the NYS GIS Clearinghouse XML reported "0.007/0.010 meters raw average", which does not reconcile. Pull the primary accuracy report before trusting either. With both epochs near the 2017 class, sigma_diff is approx 5.4 cm and the 95% detection band is approx 10 to 11 cm, so treat any change under roughly 10 to 15 cm as survey noise. Also confirm the geoid revision matches across epochs before differencing.

**26. InSAR age correction to 2026.** Value 3/5. `dem_2026 = dem_2017 + (velocity_mm_per_yr / 1000) * 9`, after reprojecting the coarser velocity raster onto the DEM grid with bilinear. Capped at 3/5 until the Zenodo raster's units and sign convention are confirmed; a sign error silently flips every corrected elevation.

**27. Sentinel-2 cloud-free median composite plus NDVI.** Value 2/5. STAC search on `https://earth-search.aws.element84.com/v1`, collection `sentinel-2-l2a`, mask with the `scl` asset (drop cloud shadow, cloud medium/high probability, thin cirrus), `np.nanmedian` across time, `NDVI = (nir - red)/(nir + red)`. Adds no spatial detail over the 6 in land cover. Its only real value is a temporal staleness check on the 2017-vintage land cover. Skip for a first pass.

### Memory budget, decides tiling before any of this gets written

| Res | Land cells | float32, one band, land | Verdict |
|---|---|---|---|
| 1 ft | approx 8.44e9 | 33.8 GB (int16: 16.9 GB) | Does not fit in any dtype. Tiled or windowed COG reads only. |
| 1 m | 783.8e6 | 3.14 GB | Fits. But five live float32 bands (DEM, filled, direction, accumulation, HAND) is approx 15.7 GB, the entire realistic 16 to 17 GB budget with zero headroom for numpy temporaries. Stream intermediates through COG. |
| 3 m | 87.1e6 | 0.35 GB | Sane default for every citywide flow-routing derivative. |

Sanity check: land-area int16 at 1 ft (16.9 GB) and float32 at 1 ft (33.8 GB) bracket the delivered DEM (15.6 GB) and DSM (30.1 GB) within 8 to 11%. Replace these estimates with `gdalinfo -stats nyc_dem_2017.vrt` once tiles are staged. Land/water area figures (783.8 km2 land, 1,213.4 km2 total) are widely published secondary numbers, fine for capacity planning, not survey grade.

---

## 4. Sedona 1.9.1 raster reality

**Worth using here.**
- `RS_Values(raster, points: ARRAY[Geometry][, band])` and `RS_Value(raster, point[, band])`, since v1.4.0. The single best fit in the whole catalog: the doc's own worked example is exactly raincheck's shape. Auto-reprojects points to the raster CRS since v1.5.1.
- `RS_ZonalStats(raster, zone[, band], statType[, allTouched[, excludeNoData[, lenient]]])` and `RS_ZonalStatsAll(...)`, both since v1.5.1. `statType` in {count, sum, mean/average/avg, median, mode, stddev/sd, variance, min, max}. Null on non-intersection unless `lenient=false`, then throws.
- `RS_SummaryStatsAll` (since v1.5.0, struct of 6) and the scalar `RS_SummaryStats` (since v1.6.0, {count, sum, mean, stddev, min, max}, no median/mode/variance).
- `RS_ReprojectMatch(raster, reference, algorithm)`, since v1.6.0, documented as the equivalent of rioxarray's `reproject_match`. This is the grid-alignment primitive. Use it before any two-raster arithmetic.
- `RS_Resample`, since v1.5.0, three overloads; algorithms `NearestNeighbor` (default), `Bilinear`, `Bicubic`. Does not support skewed inputs.
- `RS_Clip(raster, band, geom[, allTouched[, noDataValue[, crop[, lenient]]]])`, since v1.5.1. Auto-reprojects geom, defaults both to EPSG:4326 if neither declares a CRS.
- `RS_MakeEmptyRaster` (v1.5.0) plus `RS_MakeRaster(refRaster, bandDataType, data: ARRAY[Double])` (v1.6.0). This, not `RS_AsRaster`, is how a groupBy-aggregated flat array becomes a Raster. Band count is inferred as `data.length / (width*height)`, row major.
- `RS_Tile` (v1.5.1, returns `Array<Raster>`) and `RS_TileExplode` (v1.5.0, returns `Struct<x, y, tile>` already exploded).
- `RS_AsGeoTiff` (v1.4.1), `RS_AsPNG` (v1.5.0, unsigned integer pixel types only, float/double bands silently produce an empty byte array, 1 or 3 bands only), `RS_AsCOG` (v1.9.0).
- Data source `format("raster")`, new in v1.9.0, options `retile` (default true), `tileWidth`/`tileHeight` (default: the file's own internal tile scheme, so COGs are the recommended input), `padWithNoData` (default false), `fileExtension` (default `.tiff`), `rasterField`, `pathField`, `useDirectCommitter` (default true). Same format name reads and writes. Built specifically to route around Spark's 2 GB single-record ceiling.
- Data sources `format("geotiff.metadata")` and `format("netcdf.metadata")`, both new in v1.9.1 (not 1.9.0). Header-only, read-only, no write and no `CREATE TABLE USING`. On S3 they use ranged reads and pull only kilobytes per file. Use `geotiff.metadata` to inventory or filter a large collection (detect COGs via `isTiled AND size(overviews) > 0`) before loading pixels.
- H3: `ST_H3CellIDs(geom, level, fullCover)`, `ST_H3KRing(cell, k, exactRing)`, `ST_H3CellDistance(cell1, cell2)` all since v1.5.0; `ST_H3ToGeom(cells)` since v1.6.0.

**Deprecated.** `RS_MapAlgebra` is deprecated since v1.9.1 with no numbered removal version, replaced by a Raster UDF. Verbatim from the docs: "`RS_MapAlgebra` is deprecated since `v1.9.1` and **will be removed in a future version**." The deprecation is narrow: the array-based map algebra family (`RS_BandAsArray`, `RS_Add`, `RS_NormalizedDifference`, `RS_AddBandFromArray`, and 18 siblings, all since v1.1.0) is explicitly NOT deprecated. Note `RS_NormalizedDifference(Band1: ARRAY[Double], Band2: ARRAY[Double]) -> Array<Double>` takes flat band arrays from `RS_BandAsArray`, not a Raster.

**The replacement.** Raster input to Python UDFs since v1.6.0; returning a raster is new in v1.9.1. `from sedona.spark.sql.types import RasterType`, then `@udf(returnType=RasterType())`, build with `raster.with_bands(array, nodata=...)`. Inside the UDF: `.as_numpy()` (CHW, raw NoData sentinels), `.as_numpy_masked()` (NoData as NaN, may upcast), `.as_rasterio()` (read-only `DatasetReader`, `src.nodata` is always None). Grid-locked by design: `with_bands()` requires the same height/width as the input and always inherits the input's CRS and transform, so wrap with `RS_Resample`/`RS_ReprojectMatch`/`RS_Clip` for anything else. dtype gotchas: uint32 stored signed (silent overflow above 2^31-1), int8 stored unsigned (-2 reads back as 254), int64/uint64 rejected.

**What does not exist.**
- No mosaic function, at all. `RS_Union(raster1..raster7)` and `RS_Union_Aggr(rasterCol, indexCol)` are band stacking and both throw `IllegalArgumentException` on mismatched shapes; `RS_Union_Aggr` additionally requires the index column to be a unique, gapless arithmetic sequence. A repo-wide grep for "mosaic" across all 1,606 docs files at the tag returns one hit, a coffee shop name in sample data. Implementation confirms it: `RasterBandEditors.rasterUnion` calls `RasterUtils.isRasterSameShape` then appends bands, with no extent union.
- No GRIB or GRIB2 constructor. The complete documented constructor set is exactly six: `RS_FromArcInfoAsciiGrid`, `RS_FromGeoTiff`, `RS_FromNetCDF`, `RS_MakeEmptyRaster`, `RS_MakeRaster`, `RS_NetCDFInfo`. Zero paths in the 4,573-path source tree match "grib". (A seventh, `RS_MakeRasterForTesting`, is registered in the Spark catalog but is test-only and undocumented.)
- No Zarr reader.
- `RS_AsRaster` has no attribute-column or shapes-list overload. All five overloads take one Geometry and one scalar double. It is not `rasterio.features.rasterize`.
- `RS_Interpolate` (v1.6.0) fills NaN/NoData cells inside an existing raster using that raster's own valid pixels as IDW samples. It does not ingest a separate point table, so it is not a point-cloud-to-raster function.

**WherobotsDB-only.** Havasu (Iceberg-based spatial table format with first-class raster columns, ACID, time travel) and Distributed Raster Inference are Wherobots-only, confirmed absent from both Sedona 1.9.1 and SedonaDB 0.4.0. RasterFlow ("Build mosaics from satellite imagery, run ML model inference, and vectorize results") is Wherobots and is Private Preview, not GA. Out-DB raster is Wherobots-only relative to the Sedona 1.9.1 Spark/Flink line, but keep the version qualifier: Apache SedonaDB 0.4.0 ships out-db raster natively via the registered `rs_frompath` UDF and the `Raster.lazy` (OutDb) constructor, so "out-db is proprietary" is false across the project as a whole.

**Honest verdict for raincheck.** Sedona rasters earn their place in exactly one place: extracting values at many points from a raster, `RS_Values` and `RS_ZonalStats(All)`, distributed across Spark. Everything else in this project is better in Python. The DEM mosaic must be GDAL (no mosaic function exists). The rolling precipitation sums must be xarray (no Zarr, no GRIB2). The bus-speed grid must be `binned_statistic_2d` (no bin-and-reduce raster function). The flow-routing derivatives must be WhiteboxTools or GRASS (compiled, disk-cached, and GRASS exposes `memory=` and a `-m` disk-swap flag for larger-than-RAM regions). Reaching for Sedona anyway would fail the "would a practitioner do it this way" test, which is the opposite of what a Wherobots portfolio piece wants. Use Sedona where a Sedona practitioner would: the distributed point-to-raster join, and the H3 keying around it.

---

## 5. Analysis designs

### A. Rain x bus speed

**Step 1, derive speed.** Catalog item 7. Geodesic, per `vehicle_id` and `trip_id`, with the four outlier rules and the 50 m near-stop exclusion.

**Step 2, bin.** Space: H3 res 8 (`ST_H3CellIDs(geom, 8, false)`), the closest standard match to AORC's approx 0.65 km2 cell. Res 9 buys positional precision on the bus side but not on the rain side, which is pseudo-precision. Time: 168 hour-of-week bins on the local America/New_York clock for the baseline (preserves peak/off-peak and weekday/weekend structure), UTC hour-ending for the regression time index.

**Step 3, three rasters from one pipeline.** Baseline (dry-hour median per cell per hour-of-week), anomaly (observed minus matching baseline), ratio (median wet / median dry). Plus the support raster N as a free byproduct. Gate everything on N.

**Step 4, per-cell regression.** Catalog item 4. The actual deliverable.

**Step 5, storm composites.** Ida 2021-09-01 and 2023-09-29, both inside the archive window. Storm-total rain raster beside mean speed-anomaly raster. Doubles as an out-of-sample check on step 4.

**Step 6, hotspots.** Gi* on the coefficient raster, masked by N.

**Confounders, in grid form.**
- Time of day and day of week are not spatial. Their grid form is the 168-layer baseline stack itself, plus dummies in the regression. No separate raster.
- School year: a calendar-day boolean joined by date (NYC DOE session calendar). Not currently in the dataset catalog, needs pulling.
- COVID: the archive spans 2017-07 to 2024-09. Simplest defensible move is to exclude 2020-03 through reopening entirely, 2 of about 9 years, and document why. Do not model a regime you do not need.
- Congestion pricing (CBD tolling from 2025-01-05) is a structural break that lands in the gap between the archive's end (2024-09) and live capture's start (2026-08-15). No archive data is simultaneously post-pricing and historical. Build the CBD-zone (south of 60th St) baseline from live 2026 data only; never pool pre- and post-pricing CBD data into one baseline. The CBD boundary polygon is not yet in the catalog.
- Route-level dwell is handled by the 50 m stop-buffer exclusion in step 1. If dwell effects are independently wanted, build a separate near-stop raster; do not leave them in the link-speed raster.
- `occupancy_status` is populated on only about 41% of pings, a weak covariate given the majority missing.

### B. Flood exposure raster with validation

**Feature cube.** Rain severity (catalog item 8, or `FLASH_QPE_ARI*` directly for post-2020); HAND (item 11); pond depth (item 14); imperviousness fraction (NLCD, or CN via item 13 if gSSURGO lands); distance to nearest CSO outfall and to coast (item 24); `sewer_type` rasterized; entrance elevation minus local grade. For entrance elevation use the 2017 LAZ class 25 points, not Building Footprints `groundelev`, because a stair entrance is not at the building footprint's elevation; sample local grade from the bare-earth DEM in a 2 to 5 m buffer.

**Combine, climbing only as far as the data demands.**
1. Weighted linear index (item 15). Cheapest, most interpretable, correct starting point.
2. `sklearn.linear_model.LogisticRegression(class_weight='balanced', penalty='l2')` on the same cube against rasterized labels. Same features, weights fit from data, coefficients read as odds ratios. Escalate here only after the linear index is built and scored.
3. XGBoost/LightGBM. Captures interactions (imperviousness only matters when HAND is also low) but needs enough distinct labeled events and is harder to explain. Escalate only if logistic residuals show a spatial or interaction pattern it demonstrably cannot capture, not by default.

**Label rasterization.** 311 complaints and FloodNet events are points whose timestamps lag flood onset by minutes to hours, so aggregate to (cell x storm window), never (cell x exact hour). NFIP claims are block-group resolution: use them as an independent coarser check (above-median claim rate, yes/no), do not disaggregate to H3 cells. DEP Stormwater Flood Maps `9i7c-xyvv` is an independently modelled surface, good as a comparison, not as a training label. Sandy HWMs (n=111) are for spot checks only.

**Class imbalance.** Restrict the candidate population to cell-hours when it was actually raining. "Does it flood at all" is trivially imbalanced and not the operationally useful question; "given rain, where does it flood" is. Within that restricted set still expect imbalance: `class_weight='balanced'`, or `scale_pos_weight` if tier 3 is ever reached. Report POD/FAR/CSI, never accuracy.

**Validation.**
```
POD = TP/(TP+FN)     FAR = FP/(TP+FP)     CSI = TP/(TP+FP+FN)
```
Sweep across exposure-score thresholds for a performance curve, plus AUC. Split with spatial blocks, not a random split, because flood labels are spatially autocorrelated and a random split leaks information between adjacent correlated cells: `verde.BlockKFold(spacing=...)`, or `sklearn.model_selection.GroupKFold` with manually assigned block labels as the sklearn-only fallback. Block size must exceed the spatial-autocorrelation range of the residuals; start at 1 to 2 km given NYC scale and combined-sewer flooding's block-by-block drivers, and check sensitivity at two or three sizes.

**On FIM benchmarks.** The "CSI 0.26 to 0.45 in mixed conditions" figure was NOT confirmed from any live source. What was found spans 0.29 (small basins under 50 km2) to 0.87 (gauged HWM events), a range too wide to converge on 0.26 to 0.45. Treat any CSI target as a soft prior only, and report the curve rather than a single number.

**Operational reference points from Gerard et al. 2021 (doi 10.1175/BAMS-D-19-0273.1, read directly).** CREST unit streamflow >= 2.00 m3 s-1 km-2 as a warning-guidance reference; FFG ratio of 1.00 as a warning-guidance reference, computed at 1, 3, and 6 hours. There is no consensus ARI threshold: the same paper cites Martinaitis et al. 2020 (ARIs of roughly 10 to 20 years begin influencing warnings, no influence below 6 years), Gourley and Vergara 2021 (75 to 100 years at 3h, 50 to 75 at 6h best matched actual reports), and Lincoln and Thomason 2018 (a 2-year ARI at 3h already corresponded to 90% of local storm reports, while 25-year correlated better with significant flooding). That is a genuinely unresolved calibration question in the literature, not a gap in this research.

---

## 6. Pitfalls to encode as rules

1. **Grid alignment before any map algebra.** Two rasters "in the same CRS" do not necessarily share an origin or cell size. Snap every secondary layer to the primary layer's exact grid with `RS_ReprojectMatch` (Sedona) or `rasterio.warp.reproject` against an explicit destination transform (Python) before any cell-by-cell arithmetic. No exceptions.
2. **Resampling by variable type.** Categorical to nearest, continuous to bilinear/bicubic, precipitation summed in time, precipitation regridded in space conservatively when volume matters. Full rule in section 3.
3. **NoData propagation.** Set AORC's fill value -32767 as the band's actual NoData before any sum or mean. One unmasked -32767 poisons an average. Verify whichever engine runs the arithmetic honours NoData metadata rather than treating the sentinel as a real number. In Sedona Python UDFs, `.as_rasterio()` does NOT attach NoData (`src.nodata` is always None); use `.as_numpy_masked()` when NoData matters.
4. **Seams and overlap precedence.** `gdalbuildvrt`: the LAST-listed file wins on overlap. `rasterio.merge.merge`: `method='first'` (the default) means the FIRST-listed wins. Opposite conventions. If both tools appear in one pipeline, sort the input list deliberately or pass `method='last'`. Neither blends or feathers; GDAL 3.12 adds `-pixel-function` to `gdalbuildvrt` (min/mean/median across overlaps) as a coarse alternative to ordering. Separately, any focal operation computed per tile without a halo shows seams: NYC's AORC footprint is smaller than one Zarr chunk (approx 3,500 cells vs a 128x256 chunk), so load the whole NYC bbox as one array for rain; for the LiDAR DEM, which must be tiled, buffer each tile by the kernel radius and crop after.
5. **CRS and datum mixing.** Do every area and distance computation in a projected metric CRS (EPSG:32618, or EPSG:2263 converted to metres), never raw EPSG:4326 degrees. Vertical: NAVD88 (DEMs, `groundelev`, USGS HWMs) is not STND (tide gauge raw datum); at CO-OPS 8518750, NAVD88 = STND + 6.06 ft. Apply before any subtraction. The entrance-freeboard calculation is exactly this kind of subtraction, and a silently mixed datum is a 6 ft error dressed as a real number. Sedona-specific: `RS_Clip`, `RS_Value(s)`, `RS_ZonalStats(All)`, and `RS_AsRaster` all silently reproject their input geometry to the raster CRS, falling back to EPSG:4326 if neither side declares one, which matters given this project mixes EPSG:4326 (AORC, MRMS) with EPSG:2263 (taxi zones, LiDAR). Also, Sedona stores raster CRS internally as WKT1; importing WKT2/PROJ/PROJJSON via `RS_SetCRS` round-trips through proj4sedona and can silently lose the EPSG SRID for projected CRS. Test for "no CRS" with `RS_CRS(raster) IS NULL`, not `RS_SRID = 0`, which can also mean a custom non-EPSG CRS.
6. **AORC int16 scale and fill.** Let CF decoding do it: `xr.open_zarr(..., decode_cf=True)` (the default when the Zarr's attrs carry `scale_factor` and `_FillValue`). Manually multiplying raw int16 by 0.1 is exactly where a fill value becomes a fake -3276.7 mm reading before anyone notices.
7. **Unit mixing, standardized once at ingest.** Millimetres for precipitation (AORC and MRMS are kg/m2, numerically equal to mm). Metres for elevation. Convert every feet-based NAVD88 source by `* 0.3048` at the same ingest boundary, never scattered through analysis code. Atlas 14 has historically published in inches; confirm its units before combining with mm-denominated AORC/MRMS. NLCD is Albers, not 4326.
8. **Hour-ending vs hour-beginning.** VERIFIED for AORC: `registry.opendata.aws/noaa-nws-aorc/` states "APCP ending at the top of each hour", so the timestamp marks the END of the 60-minute window. NOT primary-confirmed for MRMS: dynamical.org phrases the 1-hour QPE as an average rate over the previous hour, which implies the same hour-ending convention, but no NOAA primary document was reached. Definitive 10-minute check: `wgrib2 -v` on one real `MultiSensor_QPE_01H_Pass2` file. Store everything UTC with an explicit hour-ending semantic end to end; convert to America/New_York only at the final hour-of-week bucketing, and re-check that the two DST transitions per year do not create a duplicate or missing hour bin in the ping join.
9. **The dry threshold is a project decision, not a standard.** AORC < 0.1 mm/hr equals AORC's own reporting quantum; it is NOT a named meteorological convention. The nearest named conventions are ETCCDI's 1.0 mm/day and NWS's 0.254 mm measurable-precipitation floor, both daily, not hourly. Document the choice and sensitivity-test the dry baseline at two or three cutoffs to confirm hotspot conclusions do not depend on it.
10. **Do not disaggregate coarse labels onto a fine grid.** NFIP block-group claim rates stay at block-group resolution. Pushing them to H3 cells fabricates precision the source data does not have, a well-known failure mode in flood-index work.

---

## 7. Build first

Three products, in this order. Each slots into an existing ticket.

**Product 1: the canonical NYC analysis grid and its H3 res-8 keying.** Freeze one target grid definition (AORC's native 1/120 deg NYC bbox, approx 53 x 67 cells) plus the `ST_H3CellIDs(geom, 8, false)` mapping from every point source onto it. Store the AORC-cell-centroid to res-8-hex crosswalk as a small parquet lookup once, since it never changes. Everything else in the project joins through this.
Ticket 09 (storage/CRS): this IS the CRS decision made concrete. EPSG:4326 for rain-native storage, EPSG:32618 (or 2263 in metres) as the metric CRS for every area and distance computation, NAVD88 in metres as the single vertical datum with the 6.06 ft STND offset applied at ingest, H3 res 8 as the universal join key. Encode pitfall rules 5, 7, and 8 as ingest-time assertions here, not as comments.

**Product 2: the dry-baseline speed raster with its support raster.** Catalog items 7, 2, and 1 as one pipeline: derive per-ping speed from the archive, bin to (H3 res-8 cell, hour-of-week), emit `baseline`, `n_dry`, `n_wet`. Wet/dry ratio and anomaly fall out for free.
Ticket 10 (backfill): this is the backfill's reason to exist. The archive (2017-07-14 to 2024-09) plus the frozen AORC Zarr are both already static, so the whole thing is one batch job with no live dependency. Exclude 2020-03 through reopening. Do not backfill CBD cells past 2025-01-05 into the same baseline as pre-pricing data; the archive ends before that date anyway, so the rule is really "CBD baseline comes from live 2026 data only, keep it in a separate table."

**Product 3: rain-at-bus-position via `RS_Values`, on the two storm windows.** Catalog items 3 and 10, scoped to Ida 2021-09-01 and 2023-09-29 rather than the full archive. This is the smallest thing that exercises the Sedona path end to end (convert one AORC hour to GeoTIFF, load via `format("raster")` or `RS_FromGeoTiff`, join on `ST_Within(point, RS_Envelope(raster))`, `collect_list` per raster row, one `RS_Values` call) and produces the storm composite artifact at the same time.
Ticket 10: run this as the backfill's first slice. If the Sedona path has CRS or NoData surprises on a real local-mode 1.9.1 job (M4, Java 11), better to find out on two days of data than on nine years. If it does not hold up, the Python fallback (`dataset.sample` or vectorized `xr.sel(method="nearest")`) is a two-line swap and nothing downstream changes.

Deliberately not first: the DEM mosaic and everything in the flood stack. None of it is needed for question A, all of it is GDAL/Whitebox work outside Spark, and the 1 ft memory wall means it needs a tiling decision that Product 1 does not depend on. Start it after Product 3 lands, at 3 m citywide, and reserve 1 ft for the headhouse nDSM only.

Open items worth 15 minutes each before the corresponding code gets written: MRMS hour-ending via `wgrib2 -v`; Atlas 14 grid units and `.prj` by opening `ne2yr60ma.zip`; the 2017 NVA conflict (7.4 cm vs "0.007/0.010 m") from the primary accuracy report; the Zenodo 8436658 velocity raster's units and sign; `pysheds.grid.compute_hand` signature via `help()`; and the 2010 land cover's actual pixel size from its raster header.