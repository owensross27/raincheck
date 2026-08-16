# 14 Serving surface for the two showcase artifacts

Type: grilling
Status: open
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
