"""THROWAWAY. Cuts the prototype's payloads from the REAL data root and the REAL
code paths, so no field on the prototype map is invented.  Run from the repo root:

    RAINCHECK_ARCHIVE_ROOT=$PWD/data PYTHONPATH=src .venv/bin/python \
        .scratch/frontend/prototypes/make-data.py

Provenance, per file (see README.md for the licence/gate reading of each):
  truth.json     flood_truth.truth() verbatim -- real FloodNet + real MTA tier
  history/*.json raincheck.query('events_for_asset', mode='public') verbatim
  markers.geojson  ref/assets JOIN gold/flood_labels -- notify 05's manifest, PLUS the
                 lon/lat ticket 01 priced at +65,549 B gz.  KEY NAMES ARE NOT FROZEN:
                 notify 05 has shipped no code, so these are a PROPOSAL, not a copy.
  impact.json    gold/cell_hour_speed at (cell, hour_end_utc) -- flood 17's own input.
                 flood 17 has shipped no exporter, so the WRAPPER keys are a proposal;
                 the cell/hour/speed values are real.
  chips-demo.json  the ONE fixture: flood_truth.chips()' verbatim dict shape filled with
                 real complex_id/name pairs from ref/assets.  No MTA alert prose, no real
                 alert_ids -- today's real tier returns chips: [] (no water alerts in the
                 last 6 h), and a dark layer cannot be designed against.
"""
import json, os, pathlib, duckdb

OUT = pathlib.Path(__file__).parent / "data"
ROOT = pathlib.Path(os.environ.get("RAINCHECK_ARCHIVE_ROOT", "data"))
OUT.mkdir(exist_ok=True)
(OUT / "history").mkdir(exist_ok=True)
w = lambda name, obj: (OUT / name).write_text(json.dumps(obj, default=str) + "\n")

# ---------------------------------------------------------------- 1. the truth tiers
from raincheck import flood_truth
w("truth.json", flood_truth.truth(ROOT))

con = duckdb.connect()
A = f"'{ROOT}/ref/assets/*.parquet'"
L = f"'{ROOT}/gold/flood_labels/*.parquet'"

# ------------------------------------------- 2. the history-marker layer (notify 05 + coords)
rows = con.execute(f"""
    SELECT a.asset_id, a.kind, a.name, a.lon, a.lat, count(DISTINCT l.event_id) AS n_events
    FROM {A} a JOIN {L} l USING (asset_id)
    WHERE a.lon IS NOT NULL AND a.lat IS NOT NULL
    GROUP BY 1,2,3,4,5 ORDER BY 1""").fetchall()
w("markers.geojson", {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(r[3], 5), round(r[4], 5)]},
     "properties": {"asset_id": r[0], "kind": r[1], "name": r[2], "n_events": r[5]}}
    for r in rows]})
print(f"markers.geojson  {len(rows)} assets")

# ------------------------------------------------ 3. per-asset history detail (click-time)
from raincheck import query
picks = [r[0] for r in con.execute(f"""
    SELECT a.asset_id FROM {A} a JOIN {L} l USING (asset_id)
    WHERE a.lon IS NOT NULL GROUP BY 1 ORDER BY count(DISTINCT l.event_id) DESC, 1
    LIMIT 40""").fetchall()]
for aid in picks:
    p = query.query("events_for_asset", {"asset_id": aid}, data_root=ROOT, mode="public")
    w(f"history/{aid.replace(':', '_')}.json", p)
print(f"history/         {len(picks)} payloads")

# --------------------------------------- 4. flood 17's bus overlay, at its own grain
# the DENSEST hour, not max(): the newest closed hour carries 24 cells, which cannot show
# the collision this prototype exists to test (both this overlay and the delay-cell layer
# paint the SAME ~1,200 H3 Cells).  The sparse tail is real and is noted on the ticket.
hour = con.execute(f"""SELECT hour_end_utc FROM '{ROOT}/gold/cell_hour_speed/**/*.parquet'
    GROUP BY 1 ORDER BY count(DISTINCT cell) DESC, 1 DESC LIMIT 1""").fetchone()[0]
cells = con.execute(f"""
    SELECT lower(to_hex(cell)) AS cell, sum(dist_m_sum) / nullif(sum(dt_s_sum), 0) AS speed_mps,
           sum(n_legs) AS n_legs, sum(n_vehicles) AS n_vehicles
    FROM '{ROOT}/gold/cell_hour_speed/**/*.parquet' WHERE hour_end_utc = ?
    GROUP BY 1 HAVING sum(n_legs) > 0 ORDER BY 1""", [hour]).fetchall()
w("impact.json", {"grain": "cell", "hour_end_utc": hour,
                  "cells": [{"cell": c[0], "speed_mps": round(c[1], 3),
                             "n_legs": c[2], "n_vehicles": c[3]} for c in cells]})
print(f"impact.json      {len(cells)} cells at {hour}")

# --------------- 4b. the complex lookup a chip CANNOT do without.  FINDING, not a nicety:
# flood_truth.chips() puts {complex_id, name, state} on a chip and NO lon/lat, exactly the
# defect notify 05's manifest has -- neither payload can be placed on a map by itself.
w("complexes.json", {r[0]: {"name": r[1], "lon": round(r[2], 5), "lat": round(r[3], 5)}
    for r in con.execute(f"""SELECT complex_id, name, lon, lat FROM {A}
        WHERE kind = 'complex' AND lon IS NOT NULL ORDER BY 1""").fetchall()})
print("complexes.json   445 complexes")

# ------------------------------- 5. the ONE fixture: chips() shape, real complexes, no prose
names = con.execute(f"""SELECT complex_id, name FROM {A} WHERE kind = 'complex'
    AND complex_id IN ('611','409','1','100') ORDER BY 1""").fetchall()
w("chips-demo.json", {"source": "mta_alerts", "vocabulary": flood_truth.fa.LIVE_ANCHOR,
    "hours": 6, "asof": "2026-08-24T10:23:58.197706+00:00", "status": "ok", "rows": 4, "active": 2,
    "chips": [
      {"event_id": "2026-08-24", "stations": [{"complex_id": names[i][0], "name": names[i][1],
        "state": st} for i in idx], "alert_ids": [f"FIXTURE-{n}"], "first_seen": fs,
       "last_seen": ls, "state": st, "age_min": age}
      for n, (idx, st, fs, ls, age) in enumerate([
        ([0, 1], "active",  "2026-08-24T09:41:00Z", "2026-08-24T10:19:00Z", 42.9),
        ([2],    "active",  "2026-08-24T10:02:00Z", "2026-08-24T10:19:00Z", 21.9),
        ([3],    "cleared", "2026-08-24T06:12:00Z", "2026-08-24T07:48:00Z", 251.9)])]})
print("chips-demo.json  3 chips (FIXTURE)")
