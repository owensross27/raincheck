-- web/export.sql - ticket 13 / spec L (serving), spec I (analysis outputs, wet event).
--
-- ONE text: the insight export. Run by `make export` (raincheck/export.py) and importable
-- by a notebook - it needs only `LOAD spatial`, `SET VARIABLE root` (the data root) and
-- `SET VARIABLE gate_width` (the swept interval-width gate, default 0.30).
--
-- Three outputs, each one row of one JSON column, marked by a `-- @@out <file>` line.
-- Every output uses the PURE-SQL JSON WRITER: properties are aggregated from a long
-- (cell, key, value) table with `string_agg(... ORDER BY key)`, so a value that cannot be
-- published is an ABSENT KEY, never `null`. The GDAL GeoJSON writer emits `null` for
-- unknown members and MapLibre's `["has", p]` is true on a null key, which breaks the
-- grey guard (research 14 section 0). Every aggregate that reaches a file carries an
-- ORDER BY and every number an explicit round(), so a re-export is byte-identical.
--
-- Estimands: the wet/dry contrast is always a Cell's Speed against ITS OWN dry
-- same-hour-of-week space-mean Speed for that window (gold/cell_hourofweek_baseline;
-- dry = mm_1h < 0.1 AND mm_1h_prev < 0.1 AND mm_6h < 0.5, AORC). Intervals are 95%:
--   * window layers - errors CLUSTERED BY WET EVENT over the wet Cell-hours (spec I: the
--     independent unit is the storm; an i.i.d. interval would be several times too narrow
--     and launder the gate). Service-day clustering is the sensitivity check, reported
--     beside it in headline.json.
--   * storm-hour layers - a single Hour has NO within-hour scatter in Gold (sums only),
--     so the interval is the DRY BASELINE's sampling scatter, recomputed from
--     cell_hour_speed x the dry mask and propagated through the ratio by the delta
--     method. It therefore understates total uncertainty and every storm-hour estimand
--     string says so.
-- t multipliers throughout, never 1.96 at small cluster counts (1.96 only from df 31 up).

-- ---------------------------------------------------------------- constants and inputs
CREATE OR REPLACE TEMP TABLE win AS
  -- raincheck.ref.WINDOWS as UTC Hour bounds (hour_end_utc > lo AND <= hi), matching
  -- gold.baseline()'s filter exactly. tests/test_export.py pins these to ref.WINDOWS.
  SELECT * FROM (VALUES
    ('w1', TIMESTAMPTZ '2021-08-16 00:00:00+00', TIMESTAMPTZ '2021-10-16 00:00:00+00'),
    ('w2', TIMESTAMPTZ '2023-09-01 00:00:00+00', TIMESTAMPTZ '2023-11-01 00:00:00+00')
  ) t(win, lo, hi);

CREATE OR REPLACE TEMP TABLE storm AS
  -- the two composites' fixed citywide hours (spec L: Ida 02Z-08Z, 2023-09-29 10Z-21Z).
  -- `key` is the compact per-hour property suffix MMDDHH, unique across the two storms.
  -- `on_map` is false for Ida's recovery tail 09Z-12Z: those are not spec L's map layers
  -- and carry no Cell properties, but the headline's rain-lag curve is Ida's own
  -- hour-by-hour trajectory (a lag curve pooled over a whole window is flat - most wet
  -- Hours are drizzle) and the recovery is exactly those four Hours.
  SELECT 'ida' AS layer, TIMESTAMPTZ '2021-09-02 00:00:00+00' + INTERVAL 1 HOUR * h AS hour_end_utc,
         strftime(TIMESTAMPTZ '2021-09-02 00:00:00+00' + INTERVAL 1 HOUR * h, '%m%d%H') AS key,
         h <= 8 AS on_map
  FROM range(2, 13) r(h)
  UNION ALL
  SELECT 'f23', TIMESTAMPTZ '2023-09-29 00:00:00+00' + INTERVAL 1 HOUR * h,
         strftime(TIMESTAMPTZ '2023-09-29 00:00:00+00' + INTERVAL 1 HOUR * h, '%m%d%H'), true
  FROM range(10, 22) r(h);

CREATE OR REPLACE TEMP TABLE tcrit AS
  -- two-sided 95% Student t; df = clusters - 1. Row 31 carries the normal 1.96.
  SELECT * FROM (VALUES
    (1,12.706),(2,4.303),(3,3.182),(4,2.776),(5,2.571),(6,2.447),(7,2.365),(8,2.306),
    (9,2.262),(10,2.228),(11,2.201),(12,2.179),(13,2.160),(14,2.145),(15,2.131),
    (16,2.120),(17,2.110),(18,2.101),(19,2.093),(20,2.086),(21,2.080),(22,2.074),
    (23,2.069),(24,2.064),(25,2.060),(26,2.056),(27,2.052),(28,2.048),(29,2.045),
    (30,2.042),(31,1.960)
  ) t(df, t);

CREATE OR REPLACE TEMP TABLE chord_r AS
  -- class-median polyline/chord ratio r by polyline speed class, research
  -- 10-backfill-evidence.md B1b (k=4 windows, chord >= 10 m, n = 306,964). A chord Speed
  -- ratio overstates a slowdown because the slower arm loses more distance; the
  -- chord-corrected companion is ratio * r(wet) / r(dry) - the OPTIMISTIC edge of a band.
  SELECT * FROM (VALUES (0.0, 1.164), (3.0, 1.025), (6.0, 1.015), (10.0, 1.016)) t(lo_mps, r);

CREATE OR REPLACE TEMP VIEW chs_raw AS
  SELECT * FROM read_parquet(getvariable('root') || '/gold/cell_hour_speed/**/*.parquet',
                             hive_partitioning = true, hive_types_autocast = false);
CREATE OR REPLACE TEMP VIEW pc_raw AS
  SELECT cell, hour_end_utc, mm_1h, mm_1h_prev, mm_6h
  FROM read_parquet(getvariable('root') || '/silver/precip_cell_hourly/**/*.parquet',
                    hive_partitioning = true, hive_types_autocast = false)
  WHERE src = 'aorc';
CREATE OR REPLACE TEMP VIEW bl AS
  SELECT cell, hour_of_week, speed_dry, n_dry, n_legs_dry, dist_m_sum_dry, dt_s_sum_dry,
         "window" AS win
  FROM read_parquet(getvariable('root') || '/gold/cell_hourofweek_baseline/**/*.parquet',
                    hive_partitioning = true, hive_types_autocast = false);
CREATE OR REPLACE TEMP VIEW cal AS
  SELECT service_date, school_in_session
  FROM read_parquet(getvariable('root') || '/ref/calendar/**/*.parquet');
CREATE OR REPLACE TEMP VIEW cz AS
  SELECT cell, zone_id, borough
  FROM read_parquet(getvariable('root') || '/ref/cell_zone/**/*.parquet');
CREATE OR REPLACE TEMP VIEW zn AS
  SELECT zone_id, zone_name, borough, geometry
  FROM read_parquet(getvariable('root') || '/ref/zones/**/*.parquet');

-- Cell-hour grain: cell_hour_speed is (cell, hour, route_id, route_class) and Speed is
-- route-free here. hour_of_week is America/New_York, Monday 00 local = 0, matching
-- gold.baseline()'s NUMBERING - which is not the same as matching its TEXT. gold.py:142
-- runs `(dayofweek + 5) % 7` on Spark, where dayofweek is 1=Sunday; DuckDB's dayofweek is
-- 0=Sunday, so the identical text here would put Monday at 144 and every baseline join one
-- local day out (measured: it reproduced 0 of 178,826 w1 baseline rows, `+ 6` reproduces
-- them). tests/test_export.py pins Monday 00 local -> 0 against fixed dates, NOT against a
-- fixture built with this same expression - a self-consistent fixture cannot catch this.
CREATE OR REPLACE TEMP TABLE chs AS
  SELECT w.win, s.cell, s.hour_end_utc,
         ((dayofweek(timezone('America/New_York', s.hour_end_utc)) + 6) % 7) * 24
           + hour(timezone('America/New_York', s.hour_end_utc)) AS hw,
         timezone('America/New_York', s.hour_end_utc)::DATE AS local_date,
         sum(s.n_legs) AS n_legs, sum(s.dist_m_sum) AS dist, sum(s.dt_s_sum) AS dt
  FROM chs_raw s JOIN win w ON s.hour_end_utc > w.lo AND s.hour_end_utc <= w.hi
  GROUP BY 1, 2, 3, 4, 5;

-- Footprint: a Cell with at least one Leg in the slice (spec L). Cells that only ever saw
-- dropped Legs (n_legs 0, terminal/dark drops only) carry no Speed and are not on the map.
CREATE OR REPLACE TEMP TABLE foot AS
  SELECT cell FROM chs GROUP BY cell HAVING sum(n_legs) > 0;

CREATE OR REPLACE TEMP TABLE pc AS   -- precip over the footprint and the two windows only
  SELECT p.* FROM pc_raw p JOIN foot f USING (cell)
  JOIN win w ON p.hour_end_utc > w.lo - INTERVAL 48 HOUR AND p.hour_end_utc <= w.hi;

-- Hours since the Cell's last wet Hour (mm_1h >= 1.0, AORC), 0 = this Hour is wet.
-- precip_cell_hourly is dense and unique per (cell, Hour) within a partition (08-T2), so a
-- 48-row window is exactly a 48-hour lookback.
-- last_mm is that wet Hour's own depth: pooled over a whole window the lag curve is flat
-- (most wet Hours are drizzle), so the curve is reported by the wet Hour's intensity and
-- the flat all-rain series stays visible beside the heavy-rain one.
CREATE OR REPLACE TEMP TABLE lag_all AS
  SELECT cell, hour_end_utc, datediff('hour', last_wet, hour_end_utc) AS lag_h, last_mm
  FROM (SELECT cell, hour_end_utc,
               max(CASE WHEN mm_1h >= 1.0 THEN hour_end_utc END) OVER w AS last_wet,
               arg_max(mm_1h, CASE WHEN mm_1h >= 1.0 THEN hour_end_utc END) OVER w AS last_mm
        FROM pc
        WINDOW w AS (PARTITION BY cell ORDER BY hour_end_utc
                     ROWS BETWEEN 48 PRECEDING AND CURRENT ROW))
  WHERE last_wet IS NOT NULL;

-- Wet event (spec I): a maximal run of Hours in which at least one footprint Cell is wet,
-- gaps of up to 6 dry Hours bridged - so consecutive wet Hours up to 7 h apart are one
-- event. Each wet Cell-hour belongs to the event containing its Hour.
CREATE OR REPLACE TEMP TABLE ev AS
  SELECT hour_end_utc, sum(is_new) OVER (ORDER BY hour_end_utc) AS event_id
  FROM (SELECT hour_end_utc,
               CASE WHEN hour_end_utc - lag(hour_end_utc) OVER (ORDER BY hour_end_utc)
                    <= INTERVAL 7 HOUR THEN 0 ELSE 1 END AS is_new
        FROM (SELECT DISTINCT p.hour_end_utc FROM pc p
              JOIN win w ON p.hour_end_utc > w.lo AND p.hour_end_utc <= w.hi
              WHERE p.mm_1h >= 1.0));

-- ------------------------------------------------------- window layers: wet anomalies
-- One row per wet Cell-hour: its anomaly against its own dry hour-of-week bin, its
-- bus-seconds weight, its wet event and its service day (the sensitivity cluster).
CREATE OR REPLACE TEMP TABLE wet AS
  SELECT c.win, c.cell, c.hour_end_utc, e.event_id, c.local_date, c.n_legs,
         c.dist, c.dt AS w, (c.dist / c.dt) / b.speed_dry AS a
  FROM chs c
  JOIN foot f ON f.cell = c.cell
  JOIN pc p ON p.cell = c.cell AND p.hour_end_utc = c.hour_end_utc
  JOIN ev e ON e.hour_end_utc = c.hour_end_utc
  JOIN bl b ON b.cell = c.cell AND b.win = c.win AND b.hour_of_week = c.hw
  WHERE p.mm_1h >= 1.0 AND c.dt > 0 AND c.n_legs > 0 AND b.speed_dry > 0;

-- Every window-level figure is the same weighted mean with the same cluster-robust
-- interval, so they share one long table (scope, group key, cluster key) and one
-- computation. Var = G/(G-1) * sum_g (sum_i w_i (a_i - m))^2 / (sum_i w_i)^2.
CREATE OR REPLACE TEMP TABLE wobs AS
  SELECT 'cell' AS scope, win || '|' || cell AS gk, event_id::VARCHAR AS ck, w, a, n_legs FROM wet
  UNION ALL SELECT 'city', win, event_id::VARCHAR, w, a, n_legs FROM wet
  UNION ALL SELECT 'city_day', win, local_date::VARCHAR, w, a, n_legs FROM wet
  UNION ALL SELECT 'exschool', win, event_id::VARCHAR, w, a, n_legs
  FROM wet JOIN cal ON cal.service_date = wet.local_date WHERE cal.school_in_session;

CREATE OR REPLACE TEMP TABLE wagg AS
  SELECT m.scope, m.gk, m.ratio, m.n_wet, m.n_legs, m.g,
         t.t * sqrt((m.g::DOUBLE / (m.g - 1)) * s.ss) / m.sw AS half
  FROM (SELECT scope, gk, sum(w * a) / sum(w) AS ratio, sum(w) AS sw, count(*) AS n_wet,
               sum(n_legs) AS n_legs, count(DISTINCT ck) AS g
        FROM wobs GROUP BY 1, 2) m
  JOIN (SELECT x.scope, x.gk, sum(pow(x.se_sum, 2)) AS ss
        FROM (SELECT o.scope, o.gk, o.ck, sum(o.w * (o.a - y.ratio)) AS se_sum
              FROM wobs o
              JOIN (SELECT scope, gk, sum(w * a) / sum(w) AS ratio FROM wobs GROUP BY 1, 2) y
                   USING (scope, gk)
              GROUP BY 1, 2, 3) x
        GROUP BY 1, 2) s USING (scope, gk)
  JOIN tcrit t ON t.df = least(m.g - 1, 31)
  WHERE m.g >= 2;   -- one cluster is no interval, so the figure is not publishable

CREATE OR REPLACE TEMP TABLE w_cell AS
  SELECT split_part(gk, '|', 1) AS win, split_part(gk, '|', 2)::BIGINT AS cell,
         ratio, n_wet, n_legs, g, half
  FROM wagg WHERE scope = 'cell' AND isfinite(ratio) AND isfinite(half);

-- The Cell's own dry space-mean Speed for the window: mergeable across the 168 bins only
-- through dist_m_sum_dry / dt_s_sum_dry (speed_dry alone is not - 09/10 comment).
CREATE OR REPLACE TEMP TABLE w_dry AS
  SELECT b.win, b.cell, sum(b.dist_m_sum_dry) / sum(b.dt_s_sum_dry) AS dry,
         sum(b.n_dry) AS n_dry, sum(b.n_legs_dry) AS n_legs_dry
  FROM bl b JOIN foot f ON f.cell = b.cell
  WHERE b.dt_s_sum_dry > 0 GROUP BY 1, 2;

-- ---------------------------------------------------- storm layers: hour vs dry bin
-- The dry bin's own scatter, recomputed from cell_hour_speed x the dry mask
-- (cell_hourofweek_baseline stores pooled sums only, so the scatter is not in Gold).
CREATE OR REPLACE TEMP TABLE dry_hour AS
  SELECT c.win, c.cell, c.hw, c.hour_end_utc, c.dt AS w, c.dist / c.dt AS d
  FROM chs c
  JOIN foot f ON f.cell = c.cell
  JOIN pc p ON p.cell = c.cell AND p.hour_end_utc = c.hour_end_utc
  WHERE p.mm_1h < 0.1 AND p.mm_1h_prev < 0.1 AND p.mm_6h < 0.5 AND c.dt > 0 AND c.n_legs > 0;

CREATE OR REPLACE TEMP TABLE dry_se AS
  SELECT m.win, m.cell, m.hw, m.dd, m.n, sqrt((m.n::DOUBLE / (m.n - 1)) * s.ss) / m.sw AS se
  FROM (SELECT win, cell, hw, sum(w * d) / sum(w) AS dd, sum(w) AS sw, count(*) AS n
        FROM dry_hour GROUP BY 1, 2, 3) m
  JOIN (SELECT h.win, h.cell, h.hw, sum(pow(h.w * (h.d - q.dd), 2)) AS ss
        FROM dry_hour h
        JOIN (SELECT win, cell, hw, sum(w * d) / sum(w) AS dd FROM dry_hour GROUP BY 1, 2, 3) q
             USING (win, cell, hw)
        GROUP BY 1, 2, 3) s USING (win, cell, hw)
  WHERE m.n >= 2 AND m.dd > 0;

-- Per (Cell, storm hour): the ratio and its delta-method interval. Var(S/D) with S a
-- single Hour is S^2 Var(D)/D^4, so half = t * ratio * se(D)/D.
CREATE OR REPLACE TEMP TABLE h_cell AS
  SELECT st.layer, st.key, st.hour_end_utc, c.win, c.cell, c.n_legs,
         (c.dist / c.dt) / d.dd AS ratio,
         t.t * ((c.dist / c.dt) / d.dd) * d.se / d.dd AS half,
         t.t * d.se / d.dd AS rel_half,   -- the gate's quantity: the baseline's own precision
         d.n AS n_dry
  FROM storm st
  JOIN chs c ON c.hour_end_utc = st.hour_end_utc
  JOIN foot f ON f.cell = c.cell
  JOIN dry_se d ON d.win = c.win AND d.cell = c.cell AND d.hw = c.hw
  JOIN tcrit t ON t.df = least(d.n - 1, 31)
  WHERE c.dt > 0 AND c.n_legs > 0;

-- H_mm and H_lag are precipitation, not a Speed claim: they publish whenever they are
-- known, for every footprint Cell in every storm hour. The gate applies to the ratio only.
CREATE OR REPLACE TEMP TABLE h_rain AS
  SELECT st.key, f.cell, p.mm_1h, l.lag_h
  FROM storm st CROSS JOIN foot f
  LEFT JOIN pc p ON p.cell = f.cell AND p.hour_end_utc = st.hour_end_utc
  LEFT JOIN lag_all l ON l.cell = f.cell AND l.hour_end_utc = st.hour_end_utc;

-- The citywide storm-hour denominator and its interval: the same Cells' dry bins pooled,
-- with the dry Cell-hours clustered by their own citywide Hour (one dry Hour = one draw).
CREATE OR REPLACE TEMP TABLE h_city_obs AS
  SELECT st.key, d.hour_end_utc AS ck, d.w, d.d
  FROM storm st
  JOIN chs c ON c.hour_end_utc = st.hour_end_utc
  JOIN foot f ON f.cell = c.cell
  JOIN dry_hour d ON d.win = c.win AND d.cell = c.cell AND d.hw = c.hw
  WHERE c.dt > 0 AND c.n_legs > 0;

CREATE OR REPLACE TEMP TABLE h_city AS
  SELECT st.key, st.layer, st.hour_end_utc, num.v_wet, num.n_legs, m.dd AS v_dry,
         num.v_wet / m.dd AS ratio,
         t.t * (num.v_wet / m.dd) * (sqrt((m.g::DOUBLE / (m.g - 1)) * s.ss) / m.sw) / m.dd AS half
  FROM storm st
  JOIN (SELECT st.key, sum(c.dist) / sum(c.dt) AS v_wet, sum(c.n_legs) AS n_legs
        FROM storm st JOIN chs c ON c.hour_end_utc = st.hour_end_utc
        JOIN foot f ON f.cell = c.cell
        WHERE c.dt > 0 AND c.n_legs > 0 GROUP BY 1) num USING (key)
  JOIN (SELECT key, sum(w * d) / sum(w) AS dd, sum(w) AS sw, count(DISTINCT ck) AS g
        FROM h_city_obs GROUP BY 1) m USING (key)
  JOIN (SELECT key, sum(pow(se_sum, 2)) AS ss FROM (
          SELECT o.key, o.ck, sum(o.w * (o.d - y.dd)) AS se_sum
          FROM h_city_obs o
          JOIN (SELECT key, sum(w * d) / sum(w) AS dd FROM h_city_obs GROUP BY 1) y USING (key)
          GROUP BY 1, 2) GROUP BY 1) s USING (key)
  JOIN tcrit t ON t.df = least(m.g - 1, 31);

-- Citywide wet/dry Speed levels per window, for the chord band's speed classes.
CREATE OR REPLACE TEMP TABLE w_arms AS
  SELECT w.win, sum(w.dist) / sum(w.w) AS v_wet, d.v_dry
  FROM wet w
  JOIN (SELECT b.win, sum(b.dist_m_sum_dry) / sum(b.dt_s_sum_dry) AS v_dry
        FROM bl b JOIN foot f ON f.cell = b.cell
        WHERE b.dt_s_sum_dry > 0 GROUP BY 1) d ON d.win = w.win
  GROUP BY 1, 3;

-- rain-lag: citywide space-mean Speed ratio by hours since the Cell's last wet Hour.
-- Two named series, written as two grouped passes: joining a (name, floor) VALUES list
-- on `last_mm >= floor` is an inequality join and DuckDB nested-loops it - measured 53 s
-- against 0.7 s for the union.
CREATE OR REPLACE TEMP MACRO lag_series(rain, floor_mm) AS TABLE
  SELECT c.win, rain AS rain, l.lag_h,
         sum(c.dist) / sum(c.dt) / (sum(b.dist_m_sum_dry) / sum(b.dt_s_sum_dry)) AS ratio,
         sum(c.n_legs) AS n_legs, count(DISTINCT c.cell) AS n_cells
  FROM chs c
  JOIN foot f ON f.cell = c.cell
  JOIN lag_all l ON l.cell = c.cell AND l.hour_end_utc = c.hour_end_utc
  JOIN bl b ON b.win = c.win AND b.cell = c.cell AND b.hour_of_week = c.hw
  WHERE c.dt > 0 AND c.n_legs > 0 AND b.dt_s_sum_dry > 0 AND l.lag_h <= 12
    AND l.last_mm >= floor_mm
  GROUP BY 1, 2, 3;

CREATE OR REPLACE TEMP TABLE lagtab AS
  SELECT * FROM lag_series('all', 1.0) UNION ALL SELECT * FROM lag_series('heavy', 10.0);

-- r of the arm's OWN class (arg_max on the class floor, never max(r) - the classes are
-- not monotone in r and max would pick the <3 m/s value for every arm).
CREATE OR REPLACE TEMP MACRO band(ratio, v_wet, v_dry) AS
  round(ratio * (SELECT arg_max(r, lo_mps) FROM chord_r WHERE lo_mps <= v_wet)
              / (SELECT arg_max(r, lo_mps) FROM chord_r WHERE lo_mps <= v_dry), 3);

-- ------------------------------------------------------------------- publish gates
CREATE OR REPLACE TEMP TABLE w_pub AS
  SELECT * FROM w_cell WHERE 2 * half < getvariable('gate_width');
-- The storm-hour half-width is t * ratio * se(D)/D, i.e. PROPORTIONAL TO THE ESTIMATE, so
-- gating it on absolute width would censor on the answer: it would keep slow Cells and drop
-- fast ones at the same baseline precision, biasing every published median downward, and it
-- would wave through a Cell whose storm Speed is 0 with a degenerate [0, 0] interval.
-- The gate is therefore the same width applied to the DENOMINATOR's own relative interval,
-- which is what the storm-hour interval actually measures and is independent of the ratio.
CREATE OR REPLACE TEMP TABLE h_pub AS
  SELECT * FROM h_cell
  WHERE 2 * rel_half < getvariable('gate_width') AND half > 0
    AND isfinite(ratio) AND isfinite(half);

-- ------------------------------------------------------ cells.geojson (long -> wide)
CREATE OR REPLACE TEMP TABLE cell_prop AS
            SELECT f.cell, 'zone_id' AS key, to_json(z.zone_id) AS val
              FROM foot f JOIN cz z USING (cell) WHERE z.zone_id IS NOT NULL
  UNION ALL SELECT f.cell, 'borough', to_json(z.borough)
              FROM foot f JOIN cz z USING (cell) WHERE z.borough IS NOT NULL
  UNION ALL SELECT f.cell, 'zone_name', to_json(n.zone_name)
              FROM foot f JOIN cz z USING (cell) JOIN zn n USING (zone_id)
              WHERE n.zone_name IS NOT NULL
  -- per window: the dry level and its support always (a level is not a wet/dry claim);
  -- the ratio and its interval only through the width gate
  UNION ALL SELECT cell, win || '_dry', to_json(round(dry, 3)) FROM w_dry WHERE isfinite(dry)
  UNION ALL SELECT cell, win || '_ndry', to_json(n_dry) FROM w_dry WHERE isfinite(dry)
  UNION ALL SELECT cell, win || '_ratio', to_json(round(ratio, 3)) FROM w_pub
  UNION ALL SELECT cell, win || '_lo', to_json(round(ratio - half, 3)) FROM w_pub
  UNION ALL SELECT cell, win || '_hi', to_json(round(ratio + half, 3)) FROM w_pub
  UNION ALL SELECT cell, win || '_nwet', to_json(n_wet) FROM w_pub
  UNION ALL SELECT cell, win || '_nev', to_json(g) FROM w_pub
  -- per storm hour
  UNION ALL SELECT cell, 'r' || key, to_json(round(ratio, 3)) FROM h_pub
  UNION ALL SELECT cell, 'lo' || key, to_json(round(ratio - half, 3)) FROM h_pub
  UNION ALL SELECT cell, 'hi' || key, to_json(round(ratio + half, 3)) FROM h_pub
  UNION ALL SELECT cell, 'n' || key, to_json(n_legs) FROM h_pub
  UNION ALL SELECT cell, 'd' || key, to_json(n_dry) FROM h_pub
  UNION ALL SELECT cell, 'mm' || key, to_json(round(mm_1h::DOUBLE, 2)) FROM h_rain
              WHERE mm_1h IS NOT NULL AND isfinite(mm_1h::DOUBLE)
  UNION ALL SELECT cell, 'lag' || key, to_json(lag_h) FROM h_rain WHERE lag_h IS NOT NULL;
DELETE FROM cell_prop WHERE key SIMILAR TO '(r|lo|hi|n|d|mm|lag)[0-9]{6}'
  AND right(key, 6) IN (SELECT key FROM storm WHERE NOT on_map);

-- @@out cells.geojson
SELECT '{"type":"FeatureCollection","features":[' ||
       string_agg(feature, ',' ORDER BY cell) || ']}'
FROM (
  SELECT c.cell,
         json_object('type', 'Feature', 'id', lower(to_hex(c.cell)),
                     'geometry', ST_AsGeoJSON(ST_ReducePrecision(g.geometry, 0.00001))::JSON,
                     'properties', ('{"cell":' || to_json(lower(to_hex(c.cell))) ||
                                    coalesce(',' || p.props, '') || '}')::JSON)::VARCHAR AS feature
  FROM foot c
  JOIN read_parquet(getvariable('root') || '/ref/cells/**/*.parquet') g USING (cell)
  LEFT JOIN (SELECT cell, string_agg(to_json(key) || ':' || val, ',' ORDER BY key) AS props
             FROM cell_prop GROUP BY cell) p USING (cell)
);

-- ------------------------------------------------------------------- headline.json
-- @@out headline.json
SELECT json_object(
  'gate_width', getvariable('gate_width'),
  'gate', 'a per-Cell figure publishes only when its 95% interval is narrower than gate_width; the gate is interval width, never bare n. For the storm-hour layers the width tested is the DRY BASELINE''s own relative 95% interval, because the storm-hour half-width is proportional to the ratio and gating that directly would censor on the answer - keeping slow Cells and dropping fast ones at equal baseline precision. A Cell whose storm-hour interval is degenerate (zero width) is never published.',
  'precip_src', 'AORC hourly, hour-ending',
  'preview_note', 'this slice supports citywide and borough effects and the two composites; per-Cell colour is a preview with wide intervals; hotspot claims wait for the 7-year backfill and 08''s coarsened rerun',
  'hidden_note', 'n_cells_hidden counts EVERY footprint Cell with Legs in this layer that did not publish - the interval too wide, or no interval at all (too few wet-event clusters, or no dry same-hour-of-week baseline) - so n_cells + n_cells_hidden reconciles with the coloured and grey Cells on the map; stuck buses lose Legs, so the hidden set is storm-correlated and every median-Cell figure is over Cells that kept service',
  'chord_note', 'band = [measured chord ratio, chord-corrected companion]; the companion applies research 10 B1b''s class-median polyline/chord r (1.164 under 3 m/s, 1.025 at 3-6, 1.015 at 6-10, 1.016 above 10) to each arm and is an UPPER BOUND on the correction, not the correction. B1b''s classes are POLYLINE speed classes and the arms here are chord speeds, which are lower, so an arm can be assigned one class low - that inflates the correction, which is the conservative direction for an upper edge and reproduces 10 section 2''s own worked arithmetic (Ida 04Z 0.745 -> ~0.85). Where the band reaches ~1.0 that storm''s slowdown is not separable from chord bias.',
  'cell_property_keys', json_object(
     'window', '<w1|w2>_dry, _ndry, _ratio, _lo, _hi, _nwet, _nev',
     'storm_hour', '<r|lo|hi|n|d|mm|lag><MMDDHH>, e.g. r090203 = the Ida 03Z ratio',
     'absent', 'a key is ABSENT (never null) when the value is unpublishable'),
  'rows', json(rows), 'lag', json(lag))
FROM
 (SELECT '[' || string_agg(r, ',' ORDER BY ord, layer, sort_key) || ']' AS rows FROM (
    SELECT 1 AS ord, a.gk AS layer, '' AS sort_key, json_merge_patch('{}', json_object(
      'layer', a.gk, 'label', upper(a.gk) || ' wet Hours',
      'value', round(a.ratio, 3),
      'lo', round(a.ratio - a.half, 3), 'hi', round(a.ratio + a.half, 3),
      'estimand', 'bus-seconds-weighted citywide mean over wet Cell-hours (mm_1h >= 1.0, AORC) of each Cell-hour''s space-mean chord Speed over that Cell''s dry same-hour-of-week space-mean Speed for ' || upper(a.gk) || ' (dry = mm_1h < 0.1, mm_1h_prev < 0.1, mm_6h < 0.5), rule set R2, AORC hourly; 95% CI clustered by wet event',
      'sensitivity_day', json_object(
         'lo', round(d.ratio - d.half, 3), 'hi', round(d.ratio + d.half, 3), 'n_days', d.g,
         'estimand', 'the same figure with errors clustered by service day instead of wet event'),
      'value_ex_preschool', round(x.ratio, 3),
      'lo_ex_preschool', round(x.ratio - x.half, 3),
      'hi_ex_preschool', round(x.ratio + x.half, 3),
      'estimand_ex_preschool', 'the same figure over school-in-session service days only (ref/calendar, joined on the Hour''s America/New_York calendar date)',
      'band', json_array(round(a.ratio, 3), band(a.ratio, arm.v_wet, arm.v_dry)),
      'median_cell', m.med,   -- json_merge_patch below drops it when no Cell is publishable
      'median_cell_estimand', 'median over publishable Cells of the per-Cell bus-seconds-weighted mean wet anomaly (each Cell''s own 95% CI clustered by wet event, gate on interval width)',
      'n_events', a.g, 'n_legs', a.n_legs, 'n_cell_hours', a.n_wet,
      'n_cells', m.n_cells, 'n_cells_hidden', m.n_cells_hidden))::VARCHAR AS r
    FROM wagg a
    JOIN wagg d ON d.scope = 'city_day' AND d.gk = a.gk
    LEFT JOIN wagg x ON x.scope = 'exschool' AND x.gk = a.gk
    JOIN w_arms arm ON arm.win = a.gk
    JOIN (SELECT e.win, m.med, coalesce(m.n_cells, 0) AS n_cells,
                 e.n_with_legs - coalesce(m.n_cells, 0) AS n_cells_hidden
          FROM (SELECT win, count(DISTINCT cell) AS n_with_legs FROM wet GROUP BY 1) e
          LEFT JOIN (SELECT win, round(median(ratio), 3) AS med, count(*) AS n_cells
                     FROM w_pub GROUP BY 1) m USING (win)) m ON m.win = a.gk
    WHERE a.scope = 'city'
    UNION ALL
    SELECT 2, s.layer, s.key, json_merge_patch('{}', json_object(
      'layer', s.layer, 'label', strftime(s.hour_end_utc, '%Y-%m-%d %HZ'),
      'hour_end_utc', strftime(s.hour_end_utc, '%Y-%m-%dT%H:%M:%SZ'), 'key', s.key,
      -- explicit, so the page never has to infer the layer list from which properties
      -- survived the gate: an Hour gated to all-grey is still an Hour with a map
      'on_map', st.on_map,
      'value', round(s.ratio, 3),
      'lo', round(s.ratio - s.half, 3), 'hi', round(s.ratio + s.half, 3),
      'estimand', 'bus-minute-weighted citywide space-mean chord Speed in the storm hour over the same Cells'' dry same-hour-of-week space-mean Speed for that window (dry = mm_1h < 0.1, mm_1h_prev < 0.1, mm_6h < 0.5), rule set R2, AORC hourly; the 95% interval is the DRY BASELINE''s sampling interval (clustered by dry Hour) propagated through the ratio - one storm Hour has no within-hour scatter in Gold, so it understates total uncertainty',
      'band', json_array(round(s.ratio, 3), band(s.ratio, s.v_wet, s.v_dry)),
      'median_cell', c.med,
      'median_cell_estimand', 'median over publishable Cells of the per-Cell storm-hour Speed ratio against that Cell''s own dry same-hour-of-week baseline; over publishable Cells only, which are the Cells that kept service',
      'n_legs', s.n_legs, 'n_cells', c.n_cells, 'n_cells_hidden', c.n_cells_hidden,
      'mm_1h_scored_cells_mean', c.mm,
      'mm_1h_estimand', 'mean AORC mm_1h over the Cells scored in this Hour (those with Legs and a dry same-hour-of-week baseline), not over the whole footprint'))::VARCHAR
    FROM h_city s
    JOIN storm st ON st.key = s.key
    JOIN (SELECT e.key, p.med, coalesce(p.n_cells, 0) AS n_cells,
                 e.n_with_legs - coalesce(p.n_cells, 0) AS n_cells_hidden, e.mm
          FROM (SELECT st.key, count(DISTINCT c.cell) AS n_with_legs,
                       round(avg(r.mm_1h)::DOUBLE, 2) AS mm
                FROM storm st JOIN chs c ON c.hour_end_utc = st.hour_end_utc
                JOIN foot f ON f.cell = c.cell
                LEFT JOIN h_rain r ON r.key = st.key AND r.cell = c.cell
                WHERE c.dt > 0 AND c.n_legs > 0 GROUP BY 1) e
          LEFT JOIN (SELECT key, round(median(ratio), 3) AS med, count(*) AS n_cells
                     FROM h_pub GROUP BY 1) p USING (key)) c ON c.key = s.key))
CROSS JOIN
 (SELECT '[' || string_agg(l, ',' ORDER BY win, rain, lag_h) || ']' AS lag FROM (
    SELECT win, rain, lag_h, json_object('window', win, 'rain', rain, 'lag_h', lag_h,
      'ratio', round(ratio, 3), 'n_legs', n_legs, 'n_cells', n_cells,
      'estimand', 'bus-minute-weighted citywide space-mean chord Speed of the Cell-hours lag_h Hours after that Cell''s last wet Hour (' || CASE rain WHEN 'heavy' THEN 'mm_1h >= 10' ELSE 'mm_1h >= 1' END || ' mm, AORC), over the same Cells'' dry same-hour-of-week space-mean Speed. NO interval is published for this curve: read its shape, not any single point')::VARCHAR AS l
    FROM lagtab));

-- ---------------------------------------------------------------------- zones.geojson
-- 263 TLC taxi zones, already 4326 (09), simplified 0.0002 deg: the ground layer, no basemap.
-- @@out zones.geojson
SELECT '{"type":"FeatureCollection","features":[' ||
       string_agg(feature, ',' ORDER BY zone_id) || ']}'
FROM (
  SELECT zone_id,
         json_object('type', 'Feature', 'id', zone_id,
                     'geometry', ST_AsGeoJSON(ST_ReducePrecision(
                         ST_SimplifyPreserveTopology(geometry, 0.0002), 0.00001))::JSON,
                     'properties', json_object('zone_id', zone_id, 'zone_name', zone_name,
                                               'borough', borough))::VARCHAR AS feature
  FROM zn
);
