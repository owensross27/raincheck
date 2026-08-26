-- web/geo.sql - frontend2 03: the ROUTE LINES, one Feature per (shape_id, Cell crossing).
--
-- ONE text, the sibling of web/export.sql. Run by `make geo` (raincheck.export --geo) and
-- importable by a notebook - it needs only `LOAD spatial`, `SET VARIABLE root` (the data
-- root) and `SET VARIABLE gate_width` (the same swept interval-width gate export.sql uses,
-- default 0.30). Output is marked by a `-- @@out <file>` line, exactly as export.sql's is,
-- and goes to web/files/geo/ - the `geo` publish family flood-build 19 opened, which is a
-- TREE and so needs no publish.py edit to gain a file.
--
-- Every rule export.sql states applies here and is not restated: the PURE-SQL JSON WRITER
-- (properties aggregated from a long (feature, key, value) table with
-- `string_agg(... ORDER BY key)`, so an unpublishable value is an ABSENT KEY and never
-- `null` - MapLibre's `["has", p]` is true on a null and would break the grey guard), every
-- aggregate carries an ORDER BY, every number an explicit round(), so a re-export is
-- byte-identical.
--
-- ============================================================================ THE UNIT
-- DESTINATION-PLAN D1: a route SEGMENT is a Cell crossing. `ST_Intersection(shape, cell)`
-- over silver/shapes x ref/cells gives one Feature per (shape_id, cell), keyed to
-- (route_id, direction_id) through silver/trips - which is a LOOKUP and not a build:
-- measured 2026-08-26, all 1,189 shape_ids resolve, each to exactly one (route_id,
-- direction_id), and no shape_id appears under two `pick_id` partitions. Stop-to-stop is
-- the rider-legible unit and is D1's NAMED UPGRADE (it needs silver/trip_stops, a new join
-- and a decision about what a segment's Speed IS between two stops); shape vertices are too
-- fine to carry a number.
--
-- ================================================================== THE ESTIMAND SOURCE
-- **THE BOX SAID `gold/cell_hour_route` AND THAT TABLE CANNOT ANSWER. MEASURED, not read.**
-- `gold/cell_hour_route` is (cell, hour_end_utc, route_id, direction_id) x
-- `n_events, late_share, early_share, mean_segment_excess_s, ewt_s, bunched_share,
-- wait_ok_share, coverage, vp_coverage` - SCHEDULE ADHERENCE. It holds no distance, no
-- time and no leg count, so the wet/dry Speed ratio cells.geojson publishes cannot be
-- computed from it at all; and it spans only `month=2021-09` and `month=2026-08`, which
-- does not even cover W1 (2021-08-16..2021-10-16) and covers none of W2 (2023-09..11).
-- **`gold/cell_hour_speed` is the table that carries route_id AND the Speed sums**
-- (cell, hour_end_utc, route_id, route_class, n_legs, n_vehicles, dist_m_sum, dt_s_sum,
-- ...), over 2021-08/09/10 and 2023-09/10 - both windows, whole. It is the SAME table
-- export.sql reads for cells.geojson, which is what makes "the same estimand, restricted to
-- this route" true by construction rather than by resemblance. DESTINATION.md 3.A calls
-- cell_hour_route "speed evidence already keyed by route"; that sentence is wrong and is
-- corrected on this ticket's file.
--
-- ================================================== THE DENOMINATOR, AND WHY IT IS BUILT
-- cells.geojson's window estimand is a Cell's wet Speed over ITS OWN dry same-hour-of-week
-- Speed, and that denominator comes from `gold/cell_hourofweek_baseline` - which is keyed
-- (cell, hour_of_week, window) and has NO route. Dividing a ROUTE's wet Speed by the
-- Cell's ALL-ROUTE dry Speed would publish a composition difference as a rain effect: an
-- express route that is always faster than the Cell's mix would read > 1.0 on a dry day.
-- So `bl_r` below rebuilds the same baseline keyed by route as well, from
-- `gold/cell_hour_speed` under gold.baseline()'s own dry mask
-- (mm_1h < 0.1 AND mm_1h_prev < 0.1 AND mm_6h < 0.5, AORC). Same definition, one more key.
-- The consequence is thinner support per (Cell, route) than per Cell, which is exactly what
-- the interval gate is for: a pair that cannot carry an interval publishes NO ratio and the
-- line paints grey. Measured on the real root: 17,156 (window, Cell, route) triples have a
-- dry baseline, 14,800 clear two wet-event clusters, and 8,734 clear the 0.30 gate.
--
-- The estimand is per (window, Cell, route_id) and NOT per direction: cell_hour_speed
-- carries no direction_id, so the two directions of a route through one Cell share one
-- number, and the two Features carry the same properties. Said here rather than implied.
--
-- ================================================================== WHAT IS NOT IN HERE
-- No vehicle position, no vehicle id, no timestamp, no current snapshot, no route colour
-- and no route bullet. The geometry is STATIC GTFS (the published schedule bundle
-- ref/picks resolves, not the GTFS-Realtime feeds), and the numbers are the same
-- historical 2021/2023 aggregate cells.geojson already publishes ungated, at the same
-- gate width, off the same table. See docs/read-api-contract.md.

-- ---------------------------------------------------------------- constants and inputs
CREATE OR REPLACE TEMP TABLE win AS
  -- raincheck.ref.WINDOWS as UTC Hour bounds, byte-for-byte export.sql's block:
  -- tests/test_export.py pins BOTH files against ref.WINDOWS, so the two cannot drift.
  SELECT * FROM (VALUES
    ('w1', TIMESTAMPTZ '2021-08-16 00:00:00+00', TIMESTAMPTZ '2021-10-16 00:00:00+00'),
    ('w2', TIMESTAMPTZ '2023-09-01 00:00:00+00', TIMESTAMPTZ '2023-11-01 00:00:00+00')
  ) t(win, lo, hi);

CREATE OR REPLACE TEMP TABLE tcrit AS
  -- two-sided 95% Student t; df = clusters - 1. Row 31 carries the normal 1.96.
  SELECT * FROM (VALUES
    (1,12.706),(2,4.303),(3,3.182),(4,2.776),(5,2.571),(6,2.447),(7,2.365),(8,2.306),
    (9,2.262),(10,2.228),(11,2.201),(12,2.179),(13,2.160),(14,2.145),(15,2.131),
    (16,2.120),(17,2.110),(18,2.101),(19,2.093),(20,2.086),(21,2.080),(22,2.074),
    (23,2.069),(24,2.064),(25,2.060),(26,2.056),(27,2.052),(28,2.048),(29,2.045),
    (30,2.042),(31,1.960)
  ) t(df, t);

CREATE OR REPLACE TEMP VIEW chs_raw AS
  SELECT * FROM read_parquet(getvariable('root') || '/gold/cell_hour_speed/**/*.parquet',
                             hive_partitioning = true, hive_types_autocast = false);
CREATE OR REPLACE TEMP VIEW pc_raw AS
  SELECT cell, hour_end_utc, mm_1h, mm_1h_prev, mm_6h
  FROM read_parquet(getvariable('root') || '/silver/precip_cell_hourly/**/*.parquet',
                    hive_partitioning = true, hive_types_autocast = false)
  WHERE src = 'aorc';

-- shape_id -> (route_id, direction_id). DISTINCT, not an aggregate: measured, every
-- shape_id maps to exactly one pair across all six pick_id partitions, so a GROUP BY that
-- silently picked one would be hiding a fact rather than resolving one.
CREATE OR REPLACE TEMP TABLE sr AS
  SELECT DISTINCT shape_id, route_id, direction_id
  FROM read_parquet(getvariable('root') || '/silver/trips/**/*.parquet',
                    hive_partitioning = true, hive_types_autocast = false);

-- ------------------------------------------------------------------- the segment unit
-- ST_Intersection of a LINESTRING with a Cell polygon returns whatever the clip leaves:
-- one line, several lines where the shape re-enters the Cell (1,331 of 21,869 features do),
-- or a POINT where it only grazes a vertex. ST_Dump + a LINESTRING filter keeps the lines
-- and drops the grazes; ST_Collect over the survivors is a MultiLineString and never the
-- GEOMETRYCOLLECTION that MapLibre refuses to draw (TRAPS, flood-build 19's own export).
--
-- **`length_m` IS NOT A PROPERTY HERE, AND THAT IS THE SIZE LEVER THE BOX NAMED, TAKEN.**
-- Every lever was PRICED against the built file before one was chosen (21,868 features,
-- 8,536,212 B with it):
--
--     drop length_m                     8,162,311   -4.4%   derivable from the shipped geometry
--     drop length_m + shape_id          7,690,179   -9.9%   the decided unit's own id
--     drop the support counts           7,293,077  -14.6%   the honesty payload
--     drop the intervals                7,799,263   -8.6%   the gate's own evidence
--     one Feature per (route,dir,cell)  5,753,793  -32.6%   D1's DECIDED unit, and shape_id
--     split by borough                  8,536,212    0.0%   a citywide toggle fetches all of them
--
-- So: `length_m` goes (it is the one property nothing on the page reads and the one a
-- consumer can recompute from the LineString it sits on), the borough split is refused on
-- flood-build 19's own arithmetic, and **the only lever worth more than 15% would overturn
-- D1's decided segment unit, which is not a renderer's call** - it is filed with its price
-- on this ticket's file instead. The whole network's in-grid length is 16,117 km either way
-- and is recorded in the RUN LOG, not in 21,868 copies of a number.
--
-- SIMPLIFIED AFTER the clip and never before: Douglas-Peucker preserves the first and last
-- vertex of every part, so two Cells' segments still meet exactly on the Cell boundary and
-- the network has no seams. TOLERANCE is degrees, the same knob and the same value
-- zones.geojson already uses for the taxi zones - see the sweep in this ticket's RUN LOG
-- entry (raw 9,713,704 B of geometry; 0.0001 -> 2,556,776; 0.0002 -> 2,337,584 and 0.32%
-- of network length; 0.001 -> 1,980,759 and 2.1%, which starts cutting real corners).
CREATE OR REPLACE TEMP TABLE seg AS
  SELECT g.shape_id, g.cell,
         ST_ReducePrecision(ST_SimplifyPreserveTopology(g.geometry, 0.0002), 0.00001) AS geometry
  FROM (SELECT s.shape_id, c.cell, ST_Collect(list(d.geom)) AS geometry
        FROM read_parquet(getvariable('root') || '/silver/shapes/**/*.parquet',
                          hive_partitioning = true, hive_types_autocast = false) s
        JOIN read_parquet(getvariable('root') || '/ref/cells/**/*.parquet') c
             ON ST_Intersects(s.geometry, c.geometry)
        CROSS JOIN LATERAL (SELECT UNNEST(ST_Dump(ST_Intersection(s.geometry, c.geometry))) AS d) u
        WHERE ST_GeometryType(d.geom) = 'LINESTRING' AND NOT ST_IsEmpty(d.geom)
        GROUP BY 1, 2) g
  -- a crossing that collapses to nothing at 5 dp (measured: one, 0.6 m long) is DROPPED
  -- rather than emitted empty, the same rule flood-build 19's export applies to a polygon
  -- narrower than the grid. An empty geometry is not a shorter line, it is an undrawable one.
  WHERE ST_NPoints(ST_ReducePrecision(ST_SimplifyPreserveTopology(g.geometry, 0.0002), 0.00001)) >= 2;

-- ----------------------------------------------------------- the route-grain Cell-hours
-- cell_hour_speed is (cell, hour, route_id, route_class); route_class is a second dimension
-- and is summed away here, exactly as export.sql sums route_id away for the Cell grain.
-- hour_of_week: America/New_York, Monday 00 local = 0, matching gold.baseline()'s
-- NUMBERING and not its TEXT - gold.py runs `(dayofweek + 5) % 7` on Spark, where dayofweek
-- is 1=Sunday, while DuckDB's dayofweek is 0=Sunday, so the identical text here would put
-- Monday at 144 and every baseline join one local day out. tests/test_export.py reads this
-- offset out of BOTH sql files and checks it against fixed dates.
CREATE OR REPLACE TEMP TABLE chr AS
  SELECT w.win, s.cell, s.route_id, s.hour_end_utc,
         ((dayofweek(timezone('America/New_York', s.hour_end_utc)) + 6) % 7) * 24
           + hour(timezone('America/New_York', s.hour_end_utc)) AS hw,
         sum(s.n_legs) AS n_legs, sum(s.dist_m_sum) AS dist, sum(s.dt_s_sum) AS dt
  FROM chs_raw s JOIN win w ON s.hour_end_utc > w.lo AND s.hour_end_utc <= w.hi
  GROUP BY 1, 2, 3, 4, 5;

-- Footprint: a Cell with at least one Leg in the slice (spec L). Summing over routes gives
-- the SAME set export.sql's `foot` gives (measured: 1,200 either way), which is what keeps
-- the wet-event clustering below identical to cells.geojson's.
CREATE OR REPLACE TEMP TABLE foot AS
  SELECT cell FROM chr GROUP BY cell HAVING sum(n_legs) > 0;

CREATE OR REPLACE TEMP TABLE pc AS   -- precip over the footprint and the two windows only
  SELECT p.* FROM pc_raw p JOIN foot f USING (cell)
  JOIN win w ON p.hour_end_utc > w.lo - INTERVAL 48 HOUR AND p.hour_end_utc <= w.hi;

-- Wet event (spec I): a maximal run of Hours in which at least one footprint Cell is wet,
-- gaps of up to 6 dry Hours bridged. The independent unit for the interval is the STORM.
CREATE OR REPLACE TEMP TABLE ev AS
  SELECT hour_end_utc, sum(is_new) OVER (ORDER BY hour_end_utc) AS event_id
  FROM (SELECT hour_end_utc,
               CASE WHEN hour_end_utc - lag(hour_end_utc) OVER (ORDER BY hour_end_utc)
                    <= INTERVAL 7 HOUR THEN 0 ELSE 1 END AS is_new
        FROM (SELECT DISTINCT p.hour_end_utc FROM pc p
              JOIN win w ON p.hour_end_utc > w.lo AND p.hour_end_utc <= w.hi
              WHERE p.mm_1h >= 1.0));

-- ------------------------------------------ the ROUTE's own dry same-hour-of-week Speed
-- gold.baseline()'s definition with one more key. See the header for why the Cell-grain
-- table cannot be the denominator here.
CREATE OR REPLACE TEMP TABLE bl_r AS
  SELECT c.win, c.cell, c.route_id, c.hw,
         sum(c.dist) / sum(c.dt) AS speed_dry, count(*) AS n_dry,
         sum(c.n_legs) AS n_legs_dry, sum(c.dist) AS dist_dry, sum(c.dt) AS dt_dry
  FROM chr c
  JOIN foot f ON f.cell = c.cell
  JOIN pc p ON p.cell = c.cell AND p.hour_end_utc = c.hour_end_utc
  WHERE p.mm_1h < 0.1 AND p.mm_1h_prev < 0.1 AND p.mm_6h < 0.5 AND c.dt > 0 AND c.n_legs > 0
  GROUP BY 1, 2, 3, 4;

-- One row per wet (Cell, route, Hour): its anomaly against that route's own dry bin in
-- that Cell, its bus-seconds weight and its wet event.
CREATE OR REPLACE TEMP TABLE wet_r AS
  SELECT c.win, c.cell, c.route_id, c.hour_end_utc, e.event_id, c.n_legs,
         c.dt AS w, (c.dist / c.dt) / b.speed_dry AS a
  FROM chr c
  JOIN foot f ON f.cell = c.cell
  JOIN pc p ON p.cell = c.cell AND p.hour_end_utc = c.hour_end_utc
  JOIN ev e ON e.hour_end_utc = c.hour_end_utc
  JOIN bl_r b ON b.win = c.win AND b.cell = c.cell AND b.route_id = c.route_id AND b.hw = c.hw
  WHERE p.mm_1h >= 1.0 AND c.dt > 0 AND c.n_legs > 0 AND b.speed_dry > 0;

-- The same weighted mean and the same cluster-robust interval export.sql's `wagg` computes,
-- over one more key. Var = G/(G-1) * sum_g (sum_i w_i (a_i - m))^2 / (sum_i w_i)^2.
CREATE OR REPLACE TEMP TABLE wobs_r AS
  SELECT win || '|' || cell || '|' || route_id AS gk, event_id::VARCHAR AS ck, w, a, n_legs
  FROM wet_r;

CREATE OR REPLACE TEMP TABLE wagg_r AS
  SELECT m.gk, m.ratio, m.n_wet, m.n_legs, m.g,
         t.t * sqrt((m.g::DOUBLE / (m.g - 1)) * s.ss) / m.sw AS half
  FROM (SELECT gk, sum(w * a) / sum(w) AS ratio, sum(w) AS sw, count(*) AS n_wet,
               sum(n_legs) AS n_legs, count(DISTINCT ck) AS g
        FROM wobs_r GROUP BY 1) m
  JOIN (SELECT x.gk, sum(pow(x.se_sum, 2)) AS ss
        FROM (SELECT o.gk, o.ck, sum(o.w * (o.a - y.ratio)) AS se_sum
              FROM wobs_r o
              JOIN (SELECT gk, sum(w * a) / sum(w) AS ratio FROM wobs_r GROUP BY 1) y USING (gk)
              GROUP BY 1, 2) x
        GROUP BY 1) s USING (gk)
  JOIN tcrit t ON t.df = least(m.g - 1, 31)
  WHERE m.g >= 2;   -- one cluster is no interval, so the figure is not publishable

CREATE OR REPLACE TEMP TABLE w_route AS
  SELECT split_part(gk, '|', 1) AS win, split_part(gk, '|', 2)::BIGINT AS cell,
         split_part(gk, '|', 3) AS route_id, ratio, n_wet, n_legs, g, half
  FROM wagg_r WHERE isfinite(ratio) AND isfinite(half);

-- THE PUBLISH GATE, taken from export.sql rather than re-derived: a per-feature figure
-- publishes only when its 95% interval is narrower than gate_width. The gate is interval
-- WIDTH, never bare n.
CREATE OR REPLACE TEMP TABLE w_pub_r AS
  SELECT * FROM w_route WHERE 2 * half < getvariable('gate_width');

-- The route's own dry Speed LEVEL for the window - mergeable across the 168 bins only
-- through dist/dt, never by averaging speed_dry. A level is not a wet/dry claim, so it
-- publishes whenever it exists, exactly as cells.geojson's `<win>_dry` does.
CREATE OR REPLACE TEMP TABLE w_dry_r AS
  SELECT win, cell, route_id, sum(dist_dry) / sum(dt_dry) AS dry,
         sum(n_dry) AS n_dry, sum(n_legs_dry) AS n_legs_dry
  FROM bl_r WHERE dt_dry > 0 GROUP BY 1, 2, 3;

-- --------------------------------------------------- routes.geojson (long -> wide)
-- The property NAMES are cells.geojson's, character for character (`w1_ratio`, `w1_lo`,
-- `w1_hi`, `w1_nwet`, `w1_nev`, `w1_dry`, `w1_ndry`, and the same for w2). That is what
-- lets the page paint the route line with the SAME expression it paints the Cell fill with
-- - one ramp, one estimand, restricted to one route (D1) - instead of a second mapping
-- table that could drift. A storm-hour view has no route counterpart, so its property is
-- simply ABSENT on these features and the line paints grey, which is the honest answer.
CREATE OR REPLACE TEMP TABLE seg_prop AS
            SELECT g.shape_id, g.cell, r.win || '_dry' AS key,
                   to_json(round(r.dry, 3)) AS val
              FROM seg g JOIN sr t USING (shape_id)
              JOIN w_dry_r r ON r.cell = g.cell AND r.route_id = t.route_id
              WHERE isfinite(r.dry)
  UNION ALL SELECT g.shape_id, g.cell, r.win || '_ndry', to_json(r.n_dry)
              FROM seg g JOIN sr t USING (shape_id)
              JOIN w_dry_r r ON r.cell = g.cell AND r.route_id = t.route_id
              WHERE isfinite(r.dry)
  UNION ALL SELECT g.shape_id, g.cell, r.win || '_ratio', to_json(round(r.ratio, 3))
              FROM seg g JOIN sr t USING (shape_id)
              JOIN w_pub_r r ON r.cell = g.cell AND r.route_id = t.route_id
  UNION ALL SELECT g.shape_id, g.cell, r.win || '_lo', to_json(round(r.ratio - r.half, 3))
              FROM seg g JOIN sr t USING (shape_id)
              JOIN w_pub_r r ON r.cell = g.cell AND r.route_id = t.route_id
  UNION ALL SELECT g.shape_id, g.cell, r.win || '_hi', to_json(round(r.ratio + r.half, 3))
              FROM seg g JOIN sr t USING (shape_id)
              JOIN w_pub_r r ON r.cell = g.cell AND r.route_id = t.route_id
  UNION ALL SELECT g.shape_id, g.cell, r.win || '_nwet', to_json(r.n_wet)
              FROM seg g JOIN sr t USING (shape_id)
              JOIN w_pub_r r ON r.cell = g.cell AND r.route_id = t.route_id
  UNION ALL SELECT g.shape_id, g.cell, r.win || '_nev', to_json(r.g)
              FROM seg g JOIN sr t USING (shape_id)
              JOIN w_pub_r r ON r.cell = g.cell AND r.route_id = t.route_id;

-- @@out routes.geojson
SELECT '{"type":"FeatureCollection","attribution":' || to_json(
         'Bus route geometry and route identity: MTA static GTFS (the scheduled service '
      || 'bundle in effect on the analysed dates), via silver/shapes and silver/trips. '
      || 'Speed figures: raincheck''s own aggregate of MTA GTFS-Realtime vehicle positions '
      || 'over 2021-08-16..2021-10-16 and 2023-09-01..2023-11-01, the same estimand and the '
      || 'same 95% interval gate cells.geojson publishes. Not affiliated with, endorsed by '
      || 'or a service of the MTA; no route bullet, roundel, line colour or MTA map styling '
      || 'is reproduced here.')
    || ',"features":[' || string_agg(feature, ',' ORDER BY shape_id, cell) || ']}'
FROM (
  -- No Feature `id` member, deliberately: the identity is (shape_id, cell) and both are
  -- properties, so an id would be ~0.5 MB of the same two strings again on a file this
  -- ticket is already cutting for size. cells.geojson has one because a Cell id IS one key.
  SELECT g.shape_id, g.cell,
         json_object('type', 'Feature',
                     'geometry', ST_AsGeoJSON(g.geometry)::JSON,
                     'properties', ('{"route_id":' || to_json(t.route_id) ||
                                    ',"direction_id":' || to_json(t.direction_id) ||
                                    ',"shape_id":' || to_json(g.shape_id) ||
                                    -- an H3 Cell id is an int64 past 2^53 and JSON cannot
                                    -- carry it: it crosses as the same hex string
                                    -- `cell:<h3>` asset ids carry (TRAPS, notify 02).
                                    ',"cell":' || to_json(lower(to_hex(g.cell))) ||
                                    coalesce(',' || p.props, '') || '}')::JSON)::VARCHAR AS feature
  FROM seg g
  JOIN sr t USING (shape_id)
  LEFT JOIN (SELECT shape_id, cell, string_agg(to_json(key) || ':' || val, ',' ORDER BY key) AS props
             FROM seg_prop GROUP BY shape_id, cell) p USING (shape_id, cell)
);

-- ------------------------------------------------------------------ scenarios.json
-- WHY THIS FILE EXISTS. `geo` is a TREE family: its served set is DERIVED from
-- `silver/stormwater_extent` (flood-build 19), which is what lets a scenario appear with no
-- code change. A browser cannot list a directory, so without a manifest the page would have
-- to name `stormwater-moderate.geojson` in JavaScript - and the day a second scenario is
-- readable that is a page edit, i.e. exactly the rewrite this ticket is told not to require.
-- One tiny JSON, derived from the SAME table and the SAME `horizon = current` rule the
-- extents writer derives its own file list from, and the page builds its radio from this.
--
-- The KEY spelling `stormwater-<scenario>.geojson` is `stormwater_extent.export()`'s, and
-- the two are pinned against each other in tests/test_export.py by reading the pattern out
-- of that module's SOURCE rather than by writing it down twice.
-- @@out scenarios.json
SELECT '{"scenarios":[' || coalesce(string_agg(row, ',' ORDER BY scenario), '') || ']}'
FROM (
  SELECT scenario,
         json_object('scenario', scenario, 'horizon', horizon, 'rain_in_hr', rain_in_hr,
                     'key', 'stormwater-' || scenario || '.geojson')::VARCHAR AS row
  FROM (SELECT scenario, horizon, min(rain_in_hr) AS rain_in_hr
        FROM read_parquet(getvariable('root') || '/silver/stormwater_extent/**/*.parquet')
        WHERE horizon = 'current'
        GROUP BY scenario, horizon)
);
