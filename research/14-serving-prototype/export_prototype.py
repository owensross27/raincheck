"""Ticket 14: build the two views' export files from real data and measure them.

Insight view: per-Cell storm/control Speed ratios under 10's rule set R2, from the
ticket-10 leg cache (four archive days), joined to H3 polygons -> cells.geojson,
plus headline.json (citywide bus-minute-weighted and median-Cell ratios per hour).
Ground layer: TLC taxi zones (EPSG:2263) -> DuckDB spatial -> zones.geojson.
Live view: latest Ping per vehicle from Bronze VP -> live.geojson (m1 already timed).
"""
import gzip
import json
import os
import time
import urllib.request

import duckdb
import h3
import numpy as np
import pandas as pd

M2 = "/private/tmp/claude-501/-Users-ross-raincheck/28cd1004-81c9-45b0-8641-b381bbecc8c5/scratchpad/m2"
OUT = os.path.dirname(os.path.abspath(__file__))
WEB = f"{OUT}/web"
os.makedirs(f"{WEB}/files", exist_ok=True)
R = {}

COLS = ["t0", "dt_s", "dist_m", "speed_mps", "same_trip", "trip_id0", "cell_mid",
        "pre_departure", "post_final", "run_no_flip", "route_id0"]


def r2(day):
    """Legs of one archive day (with its D+1 file) under R2 -> (cell, hour) sums."""
    t = time.time()
    d = pd.read_parquet(f"{M2}/legs_{day}.parquet", columns=COLS)
    n0 = len(d)
    d = d[d.same_trip & d.trip_id0.notna() & (d.dt_s > 0) & (d.dt_s <= 300) & (d.speed_mps <= 30)]
    n1 = len(d)
    terminal = d.pre_departure | d.post_final | d.run_no_flip
    d = d[~(terminal & (d.dist_m < 25))]
    n2 = len(d)
    t_mid = d.t0 + pd.to_timedelta(d.dt_s / 2, unit="s")
    d = d.assign(hour_end=t_mid.dt.ceil("h"))
    g = d.groupby(["cell_mid", "hour_end"], as_index=False).agg(n=("dt_s", "size"), dist=("dist_m", "sum"), secs=("dt_s", "sum"))
    R[f"legs_{day}"] = {"raw": n0, "after_trip_dt_speed": n1, "after_terminal": n2, "yield": round(n2 / n0, 3), "s": round(time.time() - t, 1)}
    return g


PAIRS = {  # storm day -> control day one week earlier; hours = hour-ending UTC labels on the storm side
    "2021-09-01": ("2021-08-25", [f"2021-09-02 {h:02d}:00" for h in range(1, 9)]),
    "2023-09-29": ("2023-09-22", [f"2023-09-29 {h:02d}:00" for h in (12, 13, 14, 19)]),
}
CELLS = "/private/tmp/claude-501/-Users-ross-raincheck/14caa78f-f3a4-4465-801d-32486caca46e/scratchpad/cells_aorc.parquet"
cells = pd.read_parquet(CELLS)
props = {int(c): {} for c in cells.cell}
headline = []
for storm, (ctrl, hours) in PAIRS.items():
    gs, gc = r2(storm), r2(ctrl)
    for h in hours:
        hs = pd.Timestamp(h, tz="UTC")
        hc = hs - pd.Timedelta(days=7)
        s = gs[gs.hour_end == hs].set_index("cell_mid")
        c = gc[gc.hour_end == hc].set_index("cell_mid")
        key = h[5:7] + h[8:10] + h[11:13]  # MMDDHH
        # citywide bus-minute-weighted space-mean ratio and median-Cell ratio (n>=20 both arms)
        agg = (s.dist.sum() / s.secs.sum()) / (c.dist.sum() / c.secs.sum())
        j = s.join(c, lsuffix="_s", rsuffix="_c", how="inner")
        j = j[(j.n_s >= 20) & (j.n_c >= 20)]
        ratio = (j.dist_s / j.secs_s) / (j.dist_c / j.secs_c)
        headline.append({
            "hour_end_utc": h + "Z", "control_hour_end_utc": str(hc)[:16] + "Z",
            "n_cells_storm": int(len(s)), "n_cells_hidden": int(len(s) - len(ratio)),
            "hidden_note": "Cells with storm Legs this hour but under 20 Legs on an arm; stuck buses lose Legs, so the hidden set is storm-correlated and the median-Cell ratio is over Cells that kept service",
            "ratio_citywide": round(float(agg), 3),
            "estimand_citywide": "bus-minute-weighted citywide space-mean chord Speed, storm hour / same hour one week earlier, rule set R2",
            "ratio_median_cell": round(float(ratio.median()), 3) if len(ratio) else None,
            "estimand_median_cell": "median over Cells with >= 20 Legs on both arms of the per-Cell space-mean chord Speed ratio",
            "n_cells": int(len(ratio)), "n_legs_storm": int(s.n.sum()), "n_legs_control": int(c.n.sum()),
            "chord_band": "chord ratios overstate a slowdown by an unmeasured 0-10 points; the corrected companion is the optimistic edge",
        })
        for cell, row in j.iterrows():
            p = props.get(int(cell))
            if p is None:
                continue
            p[f"r{key}"] = round(float((row.dist_s / row.secs_s) / (row.dist_c / row.secs_c)), 3)
            p[f"n{key}"] = int(row.n_s)
            p[f"c{key}"] = int(row.n_c)

# footprint: any Cell with a leg on any of the four days
foot = set()
for day in ["2021-08-25", "2021-09-01", "2023-09-22", "2023-09-29"]:
    foot |= set(int(x) for x in pd.read_parquet(f"{M2}/legs_{day}.parquet", columns=["cell_mid"]).cell_mid.unique())
R["footprint_cells_any_day"] = len(foot & set(props))
R["bbox_cells"] = len(props)


def hex_feature(cell, p, prec=5):
    ring = h3.cell_to_boundary(h3.int_to_str(cell))  # (lat, lon) tuples
    coords = [[round(lon, prec), round(lat, prec)] for lat, lon in ring]
    coords.append(coords[0])
    return {"type": "Feature", "id": h3.int_to_str(cell),
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {"cell": h3.int_to_str(cell), **p}}


def size(obj):
    b = json.dumps(obj, separators=(",", ":")).encode()
    return len(b), len(gzip.compress(b))


fc_foot = {"type": "FeatureCollection", "features": [hex_feature(c, props[c]) for c in sorted(foot & set(props))]}
fc_all = {"type": "FeatureCollection", "features": [hex_feature(c, props[c]) for c in sorted(props)]}
fc_geom_only = {"type": "FeatureCollection", "features": [hex_feature(c, {}) for c in sorted(foot & set(props))]}
fc_prec6 = {"type": "FeatureCollection", "features": [hex_feature(c, props[c], 6) for c in sorted(foot & set(props))]}
R["cells_geojson_footprint_bytes_gz"] = size(fc_foot)
R["cells_geojson_bbox4113_bytes_gz"] = size(fc_all)
R["cells_geojson_footprint_geometry_only"] = size(fc_geom_only)
R["cells_geojson_footprint_prec6"] = size(fc_prec6)
R["props_per_cell_max"] = max(len(p) for p in props.values())
R["cells_with_any_ratio"] = sum(1 for p in props.values() if p)
json.dump(fc_foot, open(f"{WEB}/files/cells.geojson", "w"), separators=(",", ":"))
json.dump({"hours": headline, "rules": "R2 (10): same trip, 0<dt<=300 s, <=30 m/s, stationary terminal legs dropped; Cell of the midpoint; ceil_hour(t_mid); control = same hour one week earlier (single control day, +/-0.05); per-Cell shown only with >= 20 Legs on both arms (preview; the real gate is interval width)"},
          open(f"{WEB}/files/headline.json", "w"), indent=1)

# Ground layer: TLC taxi zones through DuckDB spatial (EPSG:2263 -> 4326, axis test)
con = duckdb.connect()
con.execute("INSTALL spatial; LOAD spatial;")
zip_path = f"{OUT}/taxi_zones.zip"
if not os.path.exists(zip_path):
    urllib.request.urlretrieve("https://d37ci6vzurychx.cloudfront.net/misc/taxi_zones.zip", zip_path)
R["taxi_zones_zip_bytes"] = os.path.getsize(zip_path)
ts = con.execute("select ST_AsText(ST_Transform(ST_Point(988267.1, 215436.9), 'EPSG:2263', 'EPSG:4326', always_xy := true))").fetchone()[0]
R["times_square_axis_check"] = ts
t0 = time.time()
zones_path = f"{WEB}/files/zones.geojson"
if os.path.exists(zones_path):
    os.remove(zones_path)
con.execute(f"""
  COPY (
    select LocationID::int as zone_id, borough, zone as zone_name,
           ST_SimplifyPreserveTopology(ST_Transform(geom, 'EPSG:2263', 'EPSG:4326', always_xy := true), 0.0002) as geom
    from ST_Read('{OUT}/taxi_zones/taxi_zones/taxi_zones.shp')
  ) TO '{zones_path}' WITH (FORMAT GDAL, DRIVER 'GeoJSON', LAYER_CREATION_OPTIONS 'RFC7946=YES,COORDINATE_PRECISION=5')
""")
R["zones_export_s"] = round(time.time() - t0, 2)
zb = open(zones_path, "rb").read()
R["zones_geojson_bytes_gz"] = (len(zb), len(gzip.compress(zb)))
R["zones_rows"] = con.execute(f"select count(*) from ST_Read('{zones_path}')").fetchone()[0]

# Cell polygons straight from DuckDB h3 (no ref/cells needed at export time): timing
try:
    con.execute("INSTALL h3 FROM community; LOAD h3;")
    t0 = time.time()
    n = con.execute("""
      select count(*) from (
        select h3_cell_to_boundary_wkt(cell) as w from read_parquet(?) ) where length(w) > 0""",
        [CELLS]).fetchone()[0]
    R["duckdb_h3_boundaries"] = (n, round(time.time() - t0, 3))
except Exception as e:  # noqa
    R["duckdb_h3_boundaries"] = f"FAIL {str(e)[:160]}"

json.dump(R, open(f"{OUT}/export_prototype.json", "w"), indent=1, default=str)
print(json.dumps(R, indent=1, default=str))
print(json.dumps(headline, indent=1))
