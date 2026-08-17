# 14 Serving surface for the two showcase artifacts

Type: grilling
Status: resolved
Blocked by: 10

## Question

Graduated from the fog line "Serving/visualization" once 07 fixed the execution model
(Spark writes Gold and the live tables; DuckDB reads; live tables are Hive Parquet
under `data/live/`, 48 h horizon). The reality check names two artifacts: the insight
(an H3 lateness/rain map from Gold - where rain costs the most speed, Ida and 2023-09-29
as case studies) and the engineering view (the live "late and raining now" read over
`live/vp` + `live/tu` + `live/precip_cell`, latest-per-key). Decide the serving
surface for both: a static MapLibre page reading Parquet/PMTiles (DuckDB-WASM or a
pre-baked GeoJSON/PMTiles export from `ref/cells` x Gold), a notebook, or a small
local API; how the Cell geometry reaches the page (`ref/cells` join at export vs H3 in
the browser); what refresh the live view gets (a re-export per micro-batch vs a
reader hitting the live tables); and what is deliberately not built (no public hosting
- out of scope). The Answer is the surface and the two views' contracts; the page is
downstream build work.

## Answer

Resolved 2026-08-17 by grilling; measured first (DuckDB export path on the real Bronze
VP/TU, GeoJSON sizes for the footprint hexes and the full Gold property set, CDN bundle
sizes, stdlib `http.server` Range support, a Protomaps NYC extract dry-run, R2 per-Cell
storm ratios reproduced from ticket 10's leg cache), a prototype with the real numbers,
then two opus adversarial reviews (showcase/domain honesty; data/web/ops mechanics) and
a sonnet primary-source check (12/12 confirmed) reversed four parts of the first draft
before the round. All four recommendations accepted as-is ("all rec"). Full detail and
the two contracts: `research/14-serving-surface.md`; evidence and the throwaway page:
`research/14-serving-prototype/` (`python3 -m http.server 8140` there, plus
`uv run --no-project --with duckdb python live_export.py` for the 30 s live refresh).

1. **Surface** = one static page (`web/index.html` + `web/app.js`; MapLibre GL JS 5.9.0
   UMD, v6 is ESM-only), both artifacts as two panels of the same page, reading plain
   GeoJSON/JSON files under `web/files/` that DuckDB exports (`make export` runs
   `web/export.sql`; `make live-export` is a 30 s foreground loop), served by stdlib
   `python -m http.server` from `web/` (`make web`; nothing on the page needs Range
   requests). The writer is pure SQL JSON (`json_object` / `json_group_array` /
   `json_merge_patch('{}', ...)` so an unpublishable value is an ABSENT key - the GDAL
   GeoJSON writer emits `null` for every missing value and MapLibre's `has` is true on
   a null key, which breaks the grey guard); every export query `ORDER BY` so re-export
   is byte-identical; a provenance strip names the rail and pins. Rejected with the
   measured reason: DuckDB-WASM (8 MB gz wasm to move ~2 MB; no directory listing over
   HTTP; the story is Spark + Sedona wrote it, DuckDB reads it), PMTiles/tippecanoe for
   ~1,400 polygons (599 KB / 96 KB gz footprint file; 2.1-2.5 MB uncompressed for the
   full property set - still no tiling), deck.gl (flat choropleth + points), a local API
   (not for process count - the API would be one process to our two; the file is the
   evidence artifact, replayable with nothing running, no framework on the demo path,
   DuckDB stays a batch reader), a notebook deliverable (the analysis SQL *is* the export
   SQL; a notebook may import it).
2. **Cell geometry** reaches the page **joined at export from `ref/cells`** (polygons
   50 KB gz for the footprint; one Sedona-built source); DuckDB's community `h3`
   extension is a test oracle only (`ST_Equals(geometry,
   ST_GeomFromWKB(h3_cell_to_boundary_wkb(cell)))`, all 4,113 rows; its version rides
   the DuckDB release). Not h3-js in the browser (65 KB gz + a second H3
   implementation), not tiles.
3. **Live refresh** = the reader (DuckDB loop) hits `data/live/vp` + `data/live/tu`
   every 30 s with a **wall-clock** window (`fetched_at >= now() - 10 min`, never
   `max(fetched_at) - 600` - a dead pipeline must drain the map to zero), `date=`/`hour=`
   literal pruning (today/yesterday, HH/HH-1; 0.065 s over a synthetic 48 h, 5,760-file
   tree), latest Ping per vehicle joined at read to the latest TU row per (trip,
   vehicle) (07's TU table is already reduced), **no precip join** (`cell`, `mm_1h`,
   `precip_valid_ts` are on the VP row from the stream's `with_live_precip`), atomic
   `os.replace` of `live.geojson` then `meta.json`, a failed tick writes `meta.json`
   with `error` + `stale` and leaves `live.geojson` alone; the page re-fetches both on
   the same 30 s clock, only `setData`s when `error` is null, and **styles STALE**
   (dimmed dots, "STALE: the pipeline is not writing") at `vp_age_s > 120` (live) /
   `> 900` (Bronze) or on `stale`/`error`/missing meta; the stream writes
   `data/live/_progress.json` per micro-batch (batch_id, end ts, rows - three lines in
   `foreachBatch`, 07 build item) which meta.json copies so the panel shows the Kafka
   -> Spark -> Parquet rail and separates a dead stream from a dead exporter.
   `SOURCE=bronze` fallback over `data/archive/vp|tu` for a demo with the stream down:
   20-min window (10-min flush parts), Stop-row TU reduced in two steps (latest fetch
   per (trip, vehicle), then that fetch's earliest arrival - the one-step reduction
   gave a 1,109 s median horizon vs 46 s), no `cell`/`mm_1h`/`trip_delay_s`, safe
   against the backfill because archive-era rows have `fetched_at IS NULL`; labelled
   `source: bronze` on the page, never silent. **What the live view claims today**:
   N vehicles now (last 10 min), M in Cells at >= 1 mm RadarOnly in the latest complete
   Hour (valid ts + age), P with a next-stop prediction, occupancy colouring.
   "MTA-reported trip delay > 5 min" (never "late"; the 300 s cut is 06's Delay cutoff
   borrowed for an agency-computed quantity, unvalidated) is a **gated upgrade** with an
   explicit page state until 05's census-complete decoder lands `trip_update.delay`;
   the live rain flag is a RadarOnly threshold, not CONTEXT's Wet hour (no temperature
   guard live), and both legends name their src.
4. **Ground layer, JS delivery, prototype**: taxi zones (`ref/zones` -> `zones.geojson`,
   263, simplified 0.0002 deg) are the ground and the tooltip's place name (from
   `ref/cell_zone` joined to `ref/zones`, 04's centroid rule; the prototype's hover
   hit-test is a stand-in); no basemap now (Protomaps NYC extract measured at 112 MB,
   needs a Range server and three-licence attribution -> optional `make basemap`);
   MapLibre **vendored** by `make vendor` into gitignored `web/vendor/` (deviation from
   s2's CDN pin: a demo must not be two unpkg requests from a black screen); the 1.2 MB
   prototype stays under `research/14-serving-prototype/` as evidence (the only durable
   copy of the real per-Cell numbers; the ticket-10 leg cache is in an ephemeral
   scratchpad).

**Insight view contract** (files `cells.geojson`, `headline.json`, `zones.geojson`;
inputs Gold `cell_hour_speed` + `cell_hourofweek_baseline`, Silver
`precip_cell_hourly src=aorc`, `ref/cells`, `ref/cell_zone` + `ref/zones`,
`ref/calendar`): per-Cell wide properties, absent when unpublishable - identity
(`cell`, `zone_id`, `zone_name`, `borough`); per window `W_dry` (space-mean dry Speed -
needs `dist_m_sum_dry`/`dt_s_sum_dry` on the baseline table, 09/10 comment), `W_ratio`,
`W_lo`/`W_hi` (**95% interval clustered by wet event/day**), `W_nwet`, `W_ndry`,
published only when the interval is narrower than a swept width (default 0.30); per
storm hour (Ida 02Z-08Z, 2023-09-29 10Z-21Z, fixed citywide hours; the per-Cell response
window is analysis-only and the page says so) `H_ratio` (vs the window's dry
hour-of-week baseline), `H_lo`/`H_hi` (**same gate** - the composite map is the hotspot
claim), `H_n`, `H_ndry`, `H_mm` (AORC), `H_lag` (required: the rain-lag story).
`headline.json` carries for every number its literal estimand ("bus-minute-weighted
citywide space-mean chord Speed in the storm hour over the same Cells' dry
same-hour-of-week space-mean Speed for that window (dry = mm_1h < 0.1, mm_1h_prev <
0.1, mm_6h < 0.5), rule set R2, AORC hourly" - space-mean, not 10's T3 median), the
median-Cell companion ("over publishable Cells, 95% CI clustered by wet event"),
`n_legs`, `n_cells`, `n_cells_hidden` (storm-correlated: stuck buses lose Legs - the
median is over Cells that kept service; measured 78% of the footprint hidden at Ida
04Z, 99% at 07Z/08Z under a >= 20-Legs gate), `band` as a numeric pair `[ratio,
ratio_chord_upper]` rendered as a range (the 2023-09-29 band reaches ~1.0 and the page
says that storm's slowdown is not separable from chord bias), `W_ratio_ex_preschool`
beside `W_ratio` (10's with/without pre-school weeks, from `ref/calendar`). Required
page elements: the precip source in every legend; the sentence "this slice supports
citywide and borough effects and the two composites; per-Cell colour is a preview with
wide intervals; hotspot claims wait for the 7-year backfill and 08's coarsened rerun";
headline = citywide + median Cell + the rain-lag curve, the hex map titled as a preview.

**Checks** (asset section 5): export invariants (no null property, estimand + numeric
band + hidden count on every headline row, fixture Cell `882a100895fffff`, 263 valid
zones, byte-identical re-export), the `ref/cells` vs `h3` oracle, the live-export
fixture (multi-stop TU fetch, wall-clock exclusion, delete-the-root-between-ticks ->
`error` set and loop alive, `SOURCE=bronze` semantics), page smoke over the five files.

**Not built**: public hosting (out of scope; the static shape makes Pages a one-step
thing only if the destination is redrawn), basemap, CDN JS at demo time, route pages,
animation, trails, replay, auth, DuckDB-WASM, deck.gl, PMTiles, tippecanoe, API,
notebook deliverable, Kafka output topic, GDAL in the export.

**Handed on**: 07 (`vendor`/`export`/`live-export [SOURCE=bronze]`/`web` targets, the
live read pattern, `_progress.json`, gitignore lines for `web/files/` and
`web/vendor/`), 09/10 (`dist_m_sum_dry`/`dt_s_sum_dry` on `cell_hourofweek_baseline`;
`precip_cell_hourly` as an export input; the h3 oracle; `web/export.sql` as the one
analysis text; clustered intervals; `n_cells_hidden`; `W_ratio_ex_preschool`), 05/06
(the live "late" waits on the decoder; labelled MTA-reported trip delay), 08 (live rain
is a RadarOnly threshold, both legends name src), CONTEXT.md (Cell geometry served from
`ref/cells`, never recomputed in a browser). No new fog; the map's remaining open ticket
is 13 (HITL grant form).

## Comments

2026-08-16, from [10 Backfill slice and speed-derivation rules](10-backfill-slice-and-speed-rules.md): 10 is resolved, so this ticket is
unblocked. What the slice hands you: Gold `cell_hour_speed` (cell, hour_end_utc,
route_id, route_class; space-mean chord Speed) per month, `cell_hourofweek_baseline`
per window (dry side), and at analysis time per-Cell wet anomalies with intervals; the
two storm composites (Ida 02Z-08Z, 2023-09-29 10Z-21Z, response windows from the rain
per Cell); every ratio shown as bus-minute-weighted citywide **and** median Cell, with
its chord-corrected companion (a chord ratio overstates a slowdown by an unmeasured
0-10 points); the bus footprint is ~1,146 of the 4,113 bbox Cells. Name the estimand
next to every number on the artifact.

2026-08-17 (session working this ticket): claimed; AFK half done. Measured (DuckDB
export path on the real Bronze VP/TU, GeoJSON sizes for the footprint hexes vs the full
Gold property set, CDN bundle sizes, stdlib http.server Range support, a Protomaps NYC
extract dry-run, R2 per-Cell storm ratios reproduced from ticket 10's leg cache) and
drafted `research/14-serving-surface.md`; prototype with the real numbers under
`research/14-serving-prototype/` (`python3 -m http.server 8140` there, then
http://localhost:8140; `uv run --no-project --with duckdb python live_export.py` beside
it for the 30 s live refresh from Bronze). Two opus adversarial reviews + a sonnet
primary-source check reversed four parts of the first draft (wall-clock live window and
STALE state; "late and raining" cannot paint today - name what the live view claims;
storm-hour choropleth needs the same interval gate as the window layers; GDAL writer
emits nulls - pure-SQL JSON writer required) and caught a TU reduction bug in the
prototype (median next-stop horizon 1,109 s -> 46 s). Awaiting the human round (four
numbered decisions, recommendations first) before resolution.
