"""Ticket 14 fast measurements: DuckDB export path on real Bronze VP, CDN bundle
sizes, stdlib http.server Range support, DuckDB extensions (spatial, h3)."""
import gzip
import http.server
import inspect
import json
import os
import subprocess
import time
import urllib.request

import duckdb

REPO = "/Users/ross/raincheck"
OUT = os.path.dirname(os.path.abspath(__file__))
R = {}

# 1. DuckDB version + extensions
con = duckdb.connect()
R["duckdb_version"] = duckdb.__version__
try:
    con.execute("INSTALL spatial; LOAD spatial;")
    R["spatial"] = "ok"
except Exception as e:  # noqa
    R["spatial"] = f"FAIL {e}"
try:
    con.execute("INSTALL h3 FROM community; LOAD h3;")
    R["h3_ext"] = con.execute("select h3_cell_to_boundary_wkt(h3_string_to_h3('882a100895fffff'))").fetchone()[0][:60]
except Exception as e:  # noqa
    R["h3_ext"] = f"FAIL {str(e)[:120]}"

# 2. Latest-per-vehicle over the real Bronze VP (3 days of live capture) -> GeoJSON
con.execute("SET TimeZone='UTC'")
t = time.time()
n_files = con.execute(f"select count(*) from glob('{REPO}/data/archive/vp/**/*.parquet')").fetchone()[0]
last = con.execute(f"""
  select max(fetched_at) from read_parquet('{REPO}/data/archive/vp/**/*.parquet', hive_partitioning=true)
""").fetchone()[0]
R["vp_files"] = n_files
R["vp_last_fetched_at"] = str(last) + ' ' + time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(last))
sql_latest = f"""
  with recent as (
    select * from read_parquet('{REPO}/data/archive/vp/**/*.parquet', hive_partitioning=true)
    where fetched_at >= (select max(fetched_at) from read_parquet('{REPO}/data/archive/vp/**/*.parquet', hive_partitioning=true)) - 600
  ), latest as (
    select * from recent qualify row_number() over (partition by vehicle_id order by fetched_at desc, ts desc) = 1
  )
  select vehicle_id, trip_id, route_id, stop_id, lat, lon, bearing, occupancy,
         ts, fetched_at
  from latest
"""
t0 = time.time()
df = con.execute(sql_latest).df()
R["latest_query_s"] = round(time.time() - t0, 2)
R["latest_rows"] = len(df)
# 2a. GDAL GeoJSON writer through the spatial extension
gj_path = f"{OUT}/live_gdal.geojson"
if os.path.exists(gj_path):
    os.remove(gj_path)
t0 = time.time()
try:
    con.execute(f"""
      COPY (
        with q as ({sql_latest})
        select vehicle_id, trip_id, route_id, stop_id, bearing, occupancy, ts, fetched_at,
               ST_Point(lon, lat) as geom
        from q
      ) TO '{gj_path}' WITH (FORMAT GDAL, DRIVER 'GeoJSON', LAYER_CREATION_OPTIONS 'RFC7946=YES,COORDINATE_PRECISION=5')
    """)
    R["gdal_geojson_s"] = round(time.time() - t0, 2)
    b = open(gj_path, "rb").read()
    R["live_geojson_bytes"] = len(b)
    R["live_geojson_gz"] = len(gzip.compress(b))
    R["live_geojson_head"] = b[:160].decode()
except Exception as e:  # noqa
    R["gdal_geojson"] = f"FAIL {str(e)[:200]}"
# 2b. pure-SQL GeoJSON via json functions (no GDAL) as the fallback
t0 = time.time()
try:
    fc = con.execute(f"""
      with q as ({sql_latest})
      select json_object('type','FeatureCollection','features', json_group_array(
        json_object('type','Feature',
          'geometry', json_object('type','Point','coordinates', json_array(round(lon,5), round(lat,5))),
          'properties', json_object('v', vehicle_id, 'r', route_id, 't', trip_id, 'b', bearing, 'o', occupancy, 'ts', ts))))
      from q
    """).fetchone()[0]
    R["json_geojson_s"] = round(time.time() - t0, 2)
    R["json_geojson_bytes"] = len(fc)
    R["json_geojson_gz"] = len(gzip.compress(fc.encode()))
except Exception as e:  # noqa
    R["json_geojson"] = f"FAIL {str(e)[:200]}"

# 3. CDN bundle sizes (HEAD)
def head(url):
    """GET and count bytes (unpkg/jsdelivr answer HEAD without Content-Length); raw and gzip on the wire."""
    try:
        raw = len(urllib.request.urlopen(urllib.request.Request(url), timeout=120).read())
        gz = len(urllib.request.urlopen(urllib.request.Request(url, headers={"Accept-Encoding": "gzip"}), timeout=120).read())
        return {"raw": raw, "gz": gz, "url": urllib.request.urlopen(url, timeout=60).geturl()}
    except Exception as e:  # noqa
        return f"FAIL {str(e)[:80]}"

CDN = {
    "maplibre-gl@5.9.0 js": "https://unpkg.com/maplibre-gl@5.9.0/dist/maplibre-gl.js",
    "maplibre-gl@5.9.0 css": "https://unpkg.com/maplibre-gl@5.9.0/dist/maplibre-gl.css",
    "pmtiles@4.4.1": "https://unpkg.com/pmtiles@4.4.1/dist/pmtiles.js",
    "h3-js@4 umd": "https://unpkg.com/h3-js@4/dist/h3-js.umd.js",
    "deck.gl@9 min": "https://unpkg.com/deck.gl@9/dist.min.js",
    "duckdb-wasm eh wasm": "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm/dist/duckdb-eh.wasm",
    "duckdb-wasm browser-eh worker": "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js",
    "duckdb-wasm browser js": "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm/dist/duckdb-browser.mjs",
}
R["cdn"] = {k: head(u) for k, u in CDN.items()}

# 4. stdlib http.server: does SimpleHTTPRequestHandler honour Range?
src = inspect.getsource(http.server.SimpleHTTPRequestHandler)
R["http_server_range"] = ("Range" in src, "Accept-Ranges" in src)
try:
    import RangeHTTPServer  # noqa
    R["RangeHTTPServer_installed_here"] = True
except Exception:
    R["RangeHTTPServer_installed_here"] = False

# 5. Protomaps NYC extract dry-run (size of a local basemap)
try:
    # find the latest daily build name
    latest = None  # builds.json is 403 here; probe the daily build names directly
    for k in range(0, 10):
        d = time.strftime("%Y%m%d", time.gmtime(time.time() - 86400 * k))
        code = subprocess.run(["curl", "-sI", "--max-time", "15", "-o", "/dev/null", "-w", "%{http_code}",
                               f"https://build.protomaps.com/{d}.pmtiles"], capture_output=True, text=True).stdout
        if code == "200":
            latest = f"{d}.pmtiles"
            break
    R["protomaps_latest"] = latest
    p = subprocess.run(["pmtiles", "extract", f"https://build.protomaps.com/{latest}", f"{OUT}/nyc.pmtiles",
                        "--bbox=-74.30,40.45,-73.65,40.95", "--dry-run"], capture_output=True, text=True, timeout=120)
    R["protomaps_dryrun"] = (p.stdout + p.stderr)[-600:]
except Exception as e:  # noqa
    R["protomaps_dryrun"] = f"FAIL {str(e)[:200]}"

json.dump(R, open(f"{OUT}/measure_fast.json", "w"), indent=1, default=str)
print(json.dumps(R, indent=1, default=str))
