# 14 Serving surface for the two showcase artifacts

Asset of ticket [14 Serving surface](../.scratch/pipeline/issues/14-serving-surface.md).
Draft 2026-08-16/17, measured (section 0) and adversarially reviewed by two opus
lenses (showcase/domain honesty; data/web/ops mechanics) plus a sonnet primary-source
check (12/12 claims confirmed) before the human round. The reviews reversed four parts
of the first draft: the live window was anchored to the data's own clock (a dead
pipeline rendered a full, live-looking fleet), "late and raining now" could not paint
on any path that exists today, the storm-hour choropleth had lost its publish gate,
and the GDAL GeoJSON writer emits `null` for every unpublishable property (breaking the
grey guard) - plus a TU reduction bug in the prototype (median prediction horizon
1,109 s vs a correct 46-96 s). All folded in below. Inherits 07 (Spark writes Gold and
the live tables, DuckDB reads; live VP rows already carry `cell`, `mm_1h`,
`precip_valid_ts` from `with_live_precip`; TU live table reduced to one row per (trip,
vehicle, fetch)), 09 (`ref/cells` is serving-time geometry; Gold has none), 10 (what
the slice hands the surface; estimand next to every number; citywide *and* median
Cell; chord band; interval-width gate on per-Cell claims; composites against the
window's dry hour-of-week baseline; errors clustered by wet event), CONTEXT.md (Zone
= presentation overlay via a static Cell-to-Zone lookup at serving time; Delay is not
the feed's trip-level delay; Wet hour has a temperature guard). Precedent reused:
`~/s2-field-ndvi/web` (MapLibre 5.9.0 UMD, no build step, deck.gl rejected, wide
props + `setPaintProperty` switch) and quakestream Phase 0 ("one static HTML file
reading a JSON dump of the DuckDB table").

## 0. Facts the decisions stand on (measured 2026-08-16/17 on this Mac; evidence in `research/14-serving-prototype/measure_fast.json` and `export_prototype.json`)

- **The insight data is small.** Under 10's rule set R2, reproduced from ticket 10's leg
  cache (four archive days) to within 0.001 of 10's numbers (0.767 vs 0.768 at Ida
  03Z; 1.023 / 0.933 / 0.729 at 01Z/02Z/04Z; 0.905 at 2023-09-29 13Z), the per-Cell
  storm/control ratios for 12 storm hours land on 828 Cells; the four-day bus
  footprint is 1,391 of the 4,113 bbox Cells (10: ~1,146 per day). A GeoJSON of the
  footprint's H3 polygons with 36 numeric properties per Cell (5-dp coordinates, 3-dp
  values) is **599 KB (96 KB gz)**; all 4,113 Cells 1.35 MB / 192 KB; polygons alone
  383 KB / 50 KB. The full section-2 property set (73-92 properties) built on the same
  geometry is **2.1-2.5 MB uncompressed (0.42-0.47 MB gz), 1.4-1.7 MB at a 60% publish
  rate** (reviewer measurement). `python -m http.server` sends no `Content-Encoding`, so
  the local wire size is the uncompressed one. Still no tiling, no quantization, no
  browser-side H3; if 2.5 MB ever matters, the two storm composites go into their own
  file loaded on view switch.
- **Publishable Cells thin out fast in the storm.** With a ">= 20 Legs on both arms"
  gate the per-hour publishable count is 592/499/396/303/205/87/13/13 for Ida 01Z-08Z
  (hidden: 469/513/559/604/679/736/692/647) and 806/765/718/696 for 2023-09-29
  12Z/13Z/14Z/19Z. The hidden set is storm-correlated (stuck buses lose Legs), so any
  median-Cell figure is over Cells that kept service and must say so, and the storm
  hours 07Z/08Z have no per-Cell map at all.
- **DuckDB does the whole export path in-process.** DuckDB 1.5.5 + `spatial`: reads
  the TLC taxi-zone shapefile, `ST_Transform(EPSG:2263 -> 4326, always_xy)` passes 09's
  Times Square gate ((-73.98550, 40.75800) -> zone 230 Times Sq/Theatre District),
  `ST_SimplifyPreserveTopology(0.0002)`, writes GeoJSON through GDAL in 0.09 s (263
  zones, 345 KB / 89 KB gz). **But GDAL is a fixed-schema writer: every feature carries
  every key and an unknown value is `"h_ratio": null`** (reviewer reproduced it, and the
  first prototype's GDAL-written `live.geojson` had `pred_next_s: null` on 279/875
  features); MapLibre's `["has", p]` is true on a null-valued key and `interpolate`
  errors on null. The pure-SQL writer - `json_object` / `json_group_array` with
  `json_merge_patch('{}', json_object(...))`, which **drops null members** - is
  therefore the required writer for every file (verified: 0 null values in the
  rewritten `live.geojson`; 174 KB vs GDAL's 270 KB for the same 813 points). The
  community `h3` extension exists (`h3_cell_to_boundary_wkt` / `_wkb`,
  `h3_string_to_h3`; 4,113 boundaries in 18 ms once the projection is forced - the
  first "1 ms" measured DuckDB eliding the call) and its version rides the DuckDB
  release (`duckdb_extensions()` reports v1.5.5), so it cannot be pinned apart from the
  engine.
- **The live read is sub-second, wall-clock anchored, partition-pruned.** Latest Ping
  per vehicle over the last 20 min (Bronze) with `date IN (today, yesterday) AND hour
  IN (HH, HH-1)` literals: 0.06-0.25 s over 34-35 real Bronze files; 813-875 vehicles on
  a Sunday night -> 175 KB GeoJSON. Reviewer timing on a synthetic 48 h live tree at
  07's shape (5,760 coalesce(1) files): 0.34 s unpruned, **0.065 s pruned**, so a 30 s
  loop has > 100x headroom and the pruned form does not grow with the horizon. Three
  facts for the contract: (a) TU Bronze has no `delay` column tonight (05's
  census-complete decoder is a build item; 07 said so), so "late" is not available
  until it lands; (b) Bronze lags the feed by the archiver's 10-min flush window
  (latest `fetched_at` 04:00:00Z read at 04:08:25Z) - the streaming job's
  `data/live/*` (30 s micro-batches) is the live source, Bronze a stand-in with a
  20-min window; (c) Bronze TU is Stop-row grain (p50 18 rows per fetch): the
  prototype's first reduction kept one arbitrary stop row per (trip, vehicle) and
  reported a median next-stop horizon of 1,109 s with 596/875 vehicles covered; the
  correct two-step (latest fetch, then the earliest arrival *of that fetch*) gives
  46 s and 748/845. Archive-era Bronze rows carry `fetched_at IS NULL` (09/10), so a
  recency filter excludes the whole backfill from the fallback by construction.
- **Bundle sizes (bytes on the wire, measured by GET):** maplibre-gl 5.9.0 js 250 KB gz
  (955 KB raw) + css 10 KB; pmtiles 4.4.1 8 KB; h3-js 4.5.0 UMD 65 KB gz (216 KB raw);
  deck.gl 9.3 470 KB gz (1.65 MB raw); duckdb-wasm eh **8.1 MB gz (35.9 MB raw wasm)** +
  189 KB worker. MapLibre v6 is ESM-only (`package.json` exports only `import`,
  `dist/maplibre-gl.js` 404s) - 5.9.0 stays the pin.
- **stdlib `http.server` serves the page but honours no Range request** (no "Range" in
  `SimpleHTTPRequestHandler`); PMTiles needs range reads, so a basemap tileset would
  need `RangeHTTPServer` (pip; s2's `make web-serve`) or `pmtiles serve`. A Protomaps
  NYC extract (bbox -74.30..-73.65 x 40.45..40.95, all zooms, build 20260816) is
  **112 MB** (`pmtiles extract --dry-run`: 4,323 tiles, 46 range requests) - over
  GitHub's 100 MiB push cap if ever committed; attribution must name OSM (ODbL), ESA
  WorldCover (CC-BY 4.0) and the Mapzen icons (MIT).
- **Prototype** (`research/14-serving-prototype/`: `index.html`, `export_prototype.py`,
  `live_export.py`, `measure_fast.py`, the two `.json` evidence files, `files/` with the
  real cells/zones/headline/live/meta): served by `python3 -m http.server` it renders
  the footprint hexes coloured by ratio, a 12-hour selector, the citywide and
  median-Cell headline with estimand strings and the hidden-Cell count, the preview
  disclaimer, zone-named tooltips (Woodside, Queens: ratio 0.84, storm 53 Legs, control
  69), and the live fleet layer refreshing every 30 s from Bronze with a STALE state
  (dimmed dots, "STALE: the pipeline is not writing", the exporter error when the
  live root is missing). No console errors. Throwaway: the built page is spec's.

## 1. Surface: one static page, DuckDB-exported files, stdlib server

**Both artifacts are one static page** (`web/index.html` + `web/app.js`, MapLibre GL JS
5.9.0 UMD, vendored by `make vendor` into gitignored `web/vendor/` so a demo is never
two unpkg requests from a black screen; no npm, no bundler, no framework) reading
**plain GeoJSON / JSON under `web/files/`** that a DuckDB job exports from Gold, Silver
precip, ref and the live tables. Served locally by **`python -m http.server`** from
`web/` (`make web`; stdlib - possible only because nothing on the page needs Range
requests). Two panels of one page, not two pages: the reality check's narrative is one
story. A **provenance strip** on the page names the rail and the pins (Kafka 3.9,
Spark 3.5.3, Sedona 1.9.1, DuckDB 1.5.5, AORC / MRMS) - the viewer must be able to
tell what wrote what.

Rejected, with the measured reason:

- **DuckDB-WASM reading Parquet in the browser** - 8 MB of wasm to move ~2 MB of
  data; the live tables are ~2,880 files/day/table under Hive dirs and a browser
  cannot list a directory over HTTP (it would need the manifest the exporter writes
  anyway); the story is "Spark + Sedona wrote it, DuckDB reads it", not "the browser
  queries Parquet". A later toy if wanted.
- **PMTiles / tippecanoe for the Cells** - ~1,400 polygons is two orders of magnitude
  under tile territory (s2 tiled 279K fields); a GeoJSON source is one line and needs
  no Range server.
- **deck.gl** - a flat choropleth and a point layer need no second renderer (s2's
  finding, kept); MapLibre's `fill` and `circle` layers cover both views.
- **A local API** (FastAPI/Flask over DuckDB). Not for process count - the chosen
  design runs two foreground processes (`http.server` + the export loop) and an API
  would run one. The real reasons: no framework on the demo path; the exported file
  *is* the evidence artifact (diffable, committable beside the measurements,
  replayable with nothing running); the same page works against a static dump when
  the pipeline is down; DuckDB stays a batch reader, never request-scoped.
- **A notebook as the deliverable** - 10 §5's "in DuckDB at analysis time" *is* the
  export SQL; a notebook may import the same `web/export.sql` for exploration
  (marimo/Jupyter, optional, off the route) but the artifact is reproduced by `make
  export`, not by re-running cells.

## 2. The insight view: contract

Inputs: Gold `cell_hour_speed`, `cell_hourofweek_baseline`, Silver `precip_cell_hourly`
(`src=aorc`; needed for `H_mm`, `H_lag`, and the dry mask), `ref/cells`, `ref/cell_zone`
+ `ref/zones` (for `zone_name`), `ref/calendar`. Files written by `make export` (one
DuckDB script `raincheck/export.py` running `web/export.sql`; every query `ORDER BY
cell` / `zone_id` so a re-export is byte-identical; explicit `round(x, 3)` in SQL - no
writer option rounds properties):

| file | grain | content |
|---|---|---|
| `web/files/cells.geojson` | one Feature per footprint Cell (>= 1 Leg in the slice; ~1,150-1,400) | geometry = `ref/cells.geometry` (5 dp); `id` = hex Cell string; properties below, **absent when not publishable** (pure-SQL writer, `json_merge_patch` strips nulls) |
| `web/files/headline.json` | one row per (window, layer, hour) | every number on the panel with its estimand, n, band, hidden count |
| `web/files/zones.geojson` | 263 taxi zones | `zone_id`, `zone_name`, `borough`; from `ref/zones` (already 4326 per 09), simplified 0.0002 deg |

Properties per Cell (wide, one property per layer x hour, 3 dp; a missing property
renders grey - the paint expression is `["case", ["!", ["has", p]], GREY,
["interpolate", ...]]` and the writer guarantees `has` is false, never null):

- identity: `cell`, `zone_id`, `zone_name`, `borough` (from `ref/cell_zone` joined to
  `ref/zones`; 04's centroid rule - the prototype's hover-time `queryRenderedFeatures`
  is a stand-in, a hit-test is not the centroid rule);
- per window W (`w1`, `w2`): `W_dry` (space-mean dry Speed, m/s, over the window's dry
  Cell-hours by 10's recovery-guarded rule - **computable only if
  `cell_hourofweek_baseline` gains `dist_m_sum_dry` / `dt_s_sum_dry`** (09/10 comment;
  `speed_dry` alone is not mergeable across the 168 bins), otherwise derived in
  `export.sql` from `cell_hour_speed` x the dry mask), `W_ratio` (wet/dry Speed ratio,
  wet Cell-hours scored against their hour-of-week bin), `W_lo`, `W_hi` (**95%
  interval, errors clustered by wet event / day** - 10: the independent unit is the
  storm; an i.i.d. interval would be several times too narrow and launder the gate),
  `W_nwet`, `W_ndry`; published only when `W_hi - W_lo` < a swept width (default 0.30) -
  the gate is interval width, never bare n;
- per storm hour H (Ida 02Z-08Z, 2023-09-29 10Z-21Z, fixed citywide hour buttons; the
  per-Cell response window is analysis-only and the page says so): `H_ratio`
  (storm-hour Speed / the Cell's dry hour-of-week baseline for that window), `H_lo`,
  `H_hi` (same clustered 95% interval and the **same width gate** - the composite map
  is the hotspot claim, so it gets the same gate as `W_*`), `H_n` (storm Legs),
  `H_ndry` (baseline support), `H_mm` (the Cell's `mm_1h`, AORC), `H_lag` (hours since
  the Cell's last wet Hour; **required**, it is the rain-lag story);
- nothing else: no route breakdown per Cell (route x Cell is a Gold query, a second
  export if a route view is ever wanted).

`headline.json` rows carry, for every number on the panel: `value`, `estimand` - the
literal sentence, e.g. **"bus-minute-weighted citywide space-mean chord Speed in the
storm hour over the same Cells' dry same-hour-of-week space-mean Speed for that window
(dry = mm_1h < 0.1, mm_1h_prev < 0.1, mm_6h < 0.5), rule set R2, AORC hourly"** (space-
mean, not median: 10's T3 median is the acceptance-test construction and gets its own
string if ever shown), the median-Cell companion with its own estimand and the words
"over publishable Cells, 95% CI clustered by wet event", `n_legs`, `n_cells`,
`n_cells_hidden` (Cells with storm Legs but no publishable value; the hidden set is
storm-correlated and the page says so), and **`band` as a numeric pair `[ratio,
ratio_chord_upper]`** (10 §2's class-median r applied by speed class) - the panel
renders a **range**, never a value plus a sentence, and for the 2023-09-29 composite it
states that the band reaches ~1.0, so that storm's slowdown is not separable from
chord bias. Per window it also carries `W_ratio_ex_preschool` (+ interval) beside
`W_ratio` (10 §1: reported with and without the pre-school weeks; the flags come from
`ref/calendar`). Layers: W1 wet/dry, W2 wet/dry, Ida hour-by-hour, 2023-09-29
hour-by-hour, each window's dry baseline Speed; one `setPaintProperty` per switch, a
fixed ramp (0.5 .. 1.2), the legend naming the estimand and **the precip source
("rain: AORC hourly, hour-ending")**. Required page element (10 §1, verbatim in
spirit): *this slice supports citywide and borough effects and the two composites;
per-Cell colour is a preview with wide intervals; hotspot claims wait for the 7-year
backfill and 08's coarsened rerun.* The defensible headline is citywide + median Cell +
the rain-lag curve (0.93 -> 0.77 -> 0.73 -> 0.80 -> 0.89 -> 0.94 over Ida 02Z-12Z);
the hex map is the visual, titled as a preview.

**How Cell geometry reaches the page: joined at export from `ref/cells`.** Polygons
cost 50 KB gzipped for the footprint; h3-js in the browser costs 65 KB gz plus a second
H3 implementation to keep in step with Sedona's, and hides the Sedona-built table the
storage design put there for exactly this. `ref/cells` is the one source of Cell
geometry; DuckDB's `h3` extension is a **test oracle**
(`ST_Equals(ref_cells.geometry, ST_GeomFromWKB(h3_cell_to_boundary_wkb(cell)))` -
`ST_Equals`, not a vertex-by-vertex tolerance: start vertex and winding differ between
writers), never a second producer.

## 3. The live view: contract

Files, written by **`make live-export`**: a foreground DuckDB loop
(`raincheck/live_export.py`, 30 s = the feed cadence; each tick materialises one temp
table, writes `live.geojson` then `meta.json` by `os.replace` so the page never reads
a torn file; a failed tick writes `meta.json` with `error` + `stale: true` and leaves
`live.geojson` alone - **a dead exporter looks stale on the page, never absent**;
Ctrl-C stops it; on demand like `make stream`, not a daemon):

| file | content |
|---|---|
| `web/files/live.geojson` | one Point per vehicle: latest Ping per `vehicle_id` with **`fetched_at >= now() - 10 min` on the wall clock** (never `max(fetched_at) - 600`: a dead pipeline must drain the map to zero inside 10 minutes) over `data/live/vp` pruned by literal `date IN (today, yesterday) AND hour IN (HH, HH-1)` (UTC-midnight safe; the `max(fetched_at)` probe runs over the same pruned set), joined at read to the latest `data/live/tu` row per (trip_id, vehicle_id) - 07's table is already one row per (trip, vehicle, fetch) with the next-stop prediction, so latest-row is the whole reduction. **No precip join: `cell`, `mm_1h`, `precip_valid_ts` are already on the VP row from the stream's `with_live_precip` (07 §4)** - one producer, no hour-boundary disagreement, and the value on screen is the one Spark + Sedona wrote |
| `web/files/meta.json` | `as_of_utc`, `source` (`live` / `bronze`), `window_min`, `error` (null when healthy), `stale`, `vp_fetched_at_utc` + `vp_age_s`, `tu_fetched_at_utc`, `precip_valid_ts` + age, `n_vehicles`, `n_with_prediction`, `n_with_trip_delay`, `n_in_rain_cells`, **`stream_progress`** (copied from `data/live/_progress.json`: `batch_id`, batch end timestamp, rows - three lines in the streaming job's `foreachBatch`, 07 build item; it is what makes Kafka -> Spark -> Parquet visible and separates a dead stream from a dead exporter), `export_s` |

Properties per vehicle (absent when unknown): `vehicle_id`, `route_id`, `trip_id`,
`stop_id`, `bearing`, `occupancy` (as reported; absent on ~60% tonight), `ts`,
`fetched_at`, `cell`, `pred_next_s` + `next_stop_id`, `mm_1h` + `precip_valid_ts` (the
Cell's **RadarOnly QPE 01H** total for the latest complete Hour), `trip_delay_s` (**the
feed's trip-level `trip_update.delay`, labelled "MTA-reported trip delay" - not the
project's Delay, CONTEXT.md; absent until 05's census-complete decoder lands**).

**What the live view claims today, with the fields that exist:** "N vehicles now
(last 10 min, wall clock); M in Cells at >= 1 mm RadarOnly in the last complete Hour
(valid <ts>, K min old); P with a next-stop prediction" plus the occupancy colouring.
**"Late and raining" is a gated upgrade, not an unpainted class**: the panel shows an
explicit state ("MTA-reported trip delay: unavailable - decoder build item") until
`trip_delay_s` arrives; then the layer is labelled "MTA-reported trip delay > 5 min",
never "late" - the 300 s cut is 06's Delay cutoff *borrowed* for an agency-computed
quantity nobody has compared to Delay yet, and the legend says so. The live rain flag
is a RadarOnly threshold, **not CONTEXT's Wet hour** (no temperature guard exists live:
`t2m_k` is NULL for src=mrms, 09), and the two panels' "rain" are named as different
measurements in both legends ("rain: MRMS RadarOnly QPE 01H, uncalibrated, hour-ending,
valid <ts>" vs "rain: AORC hourly, hour-ending").

**Refresh: the reader hits the live tables and re-exports on a 30 s clock; the page
re-fetches on the same clock** (`fetch(meta.json?t=)`, then `source.setData
(live.geojson?t=)` only when `meta.error` is null) and **styles STALE** - dimmed dots and
a "STALE: the pipeline is not writing" title - when `vp_age_s > 120` (live) / `> 900`
(Bronze), when `stale`/`error` is set, or when `meta.json` is missing; the viewer never
has to read a timestamp to know the stream stopped. Not chosen: an export inside the
streaming job's `foreachBatch` (VP + TU are joined at read by 07's design; the read
product must not depend on the JVM being up or on the TU stream, which is blocked on
the decoder build item; DuckDB is the reader every layout stays honest to); the browser
reading the live tables (no listing over HTTP, 2,880 files/day/table, 8 MB wasm); a push
channel (SSE/WebSocket) - a 30 s poll of a ~200 KB file needs none.

**Bronze fallback, explicit.** `make live-export SOURCE=bronze` reads
`data/archive/vp|tu` for the demo when the stream is not running: a **20-min** wall-clock
window (two flush windows; the archiver writes 10-min parts), the Stop-row TU reduced
in two steps (latest `fetched_at` per (trip, vehicle) via `qualify fetched_at = max(...)
over (...)`, then `min(arrival_time)` / `arg_min(stop_id, arrival_time)` over that
fetch's rows), `cell` / `mm_1h` / `trip_delay_s` absent (Bronze carries no enrichment),
the same `date=`/`hour=` literal pruning (0.06 s over 35 files tonight; the prune is
what keeps it fast after 10's ~3,000-file slice lands in the same root), and safe
against the backfill because archive-era rows have `fetched_at IS NULL` and the recency
filter drops them. `meta.json.source = "bronze"` and the page prints it. Never silent:
the engineering view's claim is "the stream wrote this", and the label keeps it true.
The two paths are two reductions over one shared tail, not "the same SQL".

## 4. Deliberately not built

- Public hosting of any kind (map: out of scope). The static shape means GitHub Pages
  would be one workflow later *if the destination were redrawn* - a note, not a step.
- A basemap. The zones layer is the ground (borough silhouettes, zone names in the
  tooltip; water is the background) - already a ref table and the glossary's own
  presentation overlay. A Protomaps NYC extract (112 MB, Range server, three-licence
  attribution) is optional polish behind a `make basemap` target; not on the route.
- CDN-loaded JS at demo time: `make vendor` fetches the two pinned files once (a
  deviation from s2's CDN pin, on the reviewer's point that the demo must not depend
  on unpkg being up).
- Route-level pages, animation/playback, a time scrubber beyond the hour buttons, 3D
  extrusion, per-vehicle trails, historic replay of the live view, auth, analytics.
- DuckDB-WASM, deck.gl, PMTiles for the Cells, tippecanoe, a local API, a notebook
  deliverable, a Kafka consumer or output topic for the page (07: nothing consumes it),
  a GDAL dependency in the export (the pure-SQL JSON writer covers points and polygons
  via `ST_AsGeoJSON`).

## 5. Checks (one runnable check per slice)

1. `make export` on the slice: `cells.geojson` feature count == footprint Cells with a
   publishable value in at least one layer; **no property value is null** (absent
   instead) and every present value is finite; every `headline.json` row has a
   non-empty `estimand`, a numeric `band` pair, `n_cells_hidden`; the fixture Cell
   `882a100895fffff` carries `w1_dry` > 0 and an Ida hour property; `zones.geojson` has
   263 features, `zone_name` non-empty on all, every simplified geometry `ST_IsValid`
   (the Times Square axis gate belongs to `make ref`, 09); export twice -> byte-identical
   files (`ORDER BY` in every query).
2. `ref/cells` vs the DuckDB `h3` oracle: `ST_Equals(geometry,
   ST_GeomFromWKB(h3_cell_to_boundary_wkb(cell)))` for all 4,113 rows (the export
   never computes geometry; a DuckDB bump can break this without a data change - the
   check exists to say so).
3. `make live-export` on a fixture (three Snapshots of one vehicle; **one TU fetch with
   >= 3 stop rows whose earliest arrival is not the first row**, plus an older fetch;
   one precip Hour on the VP row): one Feature per vehicle with the newest `fetched_at`,
   `pred_next_s` from the newest fetch's earliest arrival, `mm_1h` from the row,
   `meta.json` ages computed from the fixture clock; a row older than the wall-clock
   window is excluded; a torn write is impossible (files replaced, never appended);
   **delete the live root between two ticks -> the loop survives with `meta.json.error`
   set and `stale: true`**; `SOURCE=bronze` yields `source: bronze`, no `cell`, and
   excludes rows with `fetched_at IS NULL`.
4. Page smoke: `python -m http.server` from `web/` answers 200 for `index.html`, the two
   vendored files and the five data files (`cells`, `headline`, `zones`, `live`,
   `meta`); a headless fetch asserts `cells.geojson` parses with the
   `id`/`properties.cell` pair and `meta.json` has `error: null` after a healthy tick.
   No browser automation - a manual load is the visual check; the prototype is the
   reference.

## 6. Handed on / comments to leave

- 07: Makefile targets `vendor`, `export`, `live-export [SOURCE=bronze]`, `web`; the
  live read pattern (last 10 min by wall clock, `date=`/`hour=` literals, latest per key,
  VP + TU joined at read, precip already on the row) is the reader every live layout
  must satisfy; **`data/live/_progress.json` written by `foreachBatch`** (batch_id, end
  timestamp, rows) is a three-line build item; `web/files/` and `web/vendor/` are
  gitignored derived output (the repo `data/` rule does not cover them - explicit
  lines).
- 09/10: `cell_hourofweek_baseline` gains `dist_m_sum_dry` / `dt_s_sum_dry` so the
  window's dry space-mean Speed is mergeable across bins (10 flagged the same for
  `leg_speed_p50`); `silver/precip_cell_hourly` is an export input; the DuckDB `h3`
  extension as a test oracle for `ref/cells` (via `ST_Equals`, `_wkb` function).
- 10: the "at analysis time in DuckDB" anomalies and composites become
  `web/export.sql` - one text, run by the export job and importable by a notebook;
  intervals are 95% clustered by wet event; the composite ratio on the page is against
  the window's dry hour-of-week baseline (the prototype's single-control-day ratio is a
  stand-in and says so); the `n_cells_hidden` line and the "preview; hotspot claims
  wait" sentence are required page elements; `W_ratio_ex_preschool` from
  `ref/calendar`.
- 05/06: the live "late" waits on the census-complete decoder (`trip_update.delay`);
  the page labels it MTA-reported trip delay > 5 min, never Delay/late; the 300 s cut is
  borrowed and unvalidated until `events` and the live feed coexist.
- 08: the live panel's rain is a RadarOnly threshold, not Wet hour (no temperature
  guard live); both legends name their src.
- CONTEXT.md: no new term; a one-line note under Cell that its geometry is served from
  `ref/cells`, never recomputed in a browser.
- Fog: none new; the basemap is a build-time option, not a decision.
