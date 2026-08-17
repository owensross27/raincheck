"""Ticket 14 prototype: the live-view export loop.

Every 30 s DuckDB reads the last WINDOW minutes (wall clock, never max(fetched_at))
of the VP and TU tables, pruned to today's/yesterday's date= and the current/previous
hour= partitions by literal, takes the latest Ping per vehicle, joins the TU next-stop
prediction, and writes web/files/live.geojson + web/files/meta.json (atomic swap).
A failed tick writes meta.json with error + stale and leaves live.geojson alone.
SOURCE=bronze reads data/archive/vp|tu (Stop-row TU, 10-min flush lag -> 20 min
window, no cell/precip); SOURCE=live reads data/live/vp|tu (07's reduced TU, cell +
mm_1h + precip_valid_ts already on the VP row). ONCE=1 runs one tick."""
import json
import os
import sys
import time

import duckdb

REPO = "/Users/ross/raincheck"
OUT = os.environ.get("OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "files"))
SOURCE = os.environ.get("SOURCE", "bronze")
ROOTS = {"bronze": (f"{REPO}/data/archive/vp", f"{REPO}/data/archive/tu", 20),
         "live": (f"{REPO}/data/live/vp", f"{REPO}/data/live/tu", 10)}
VP_ROOT, TU_ROOT, WINDOW_MIN = ROOTS[SOURCE]

con = duckdb.connect()
con.execute("SET TimeZone='UTC'")


def prune(now):
    """date=/hour= literals covering the last two hours (UTC midnight-safe)."""
    hs = [time.gmtime(now - 3600 * k) for k in (0, 1)]
    dates = ",".join(sorted({f"DATE '{time.strftime('%Y-%m-%d', h)}'" for h in hs}))
    hours = ",".join(sorted({f"'{time.strftime('%H', h)}'" for h in hs}))
    return f"date IN ({dates}) AND hour IN ({hours})"


def sql(now):
    p, t0 = prune(now), now - WINDOW_MIN * 60
    if SOURCE == "bronze":  # Stop-row grain: latest fetch per (trip, vehicle), then the earliest arrival of THAT fetch
        tu = f"""
        tu as (select * from read_parquet('{TU_ROOT}/**/*.parquet', hive_partitioning=true)
               where {p} and fetched_at >= {t0}),
        tu_fetch as (select * from tu qualify fetched_at = max(fetched_at) over (partition by trip_id, vehicle_id)),
        nxt as (select trip_id, vehicle_id, max(fetched_at) as tu_fetched_at,
                       arg_min(stop_id, arrival_time) as next_stop_id, min(arrival_time) - max(fetched_at) as pred_next_s
                from tu_fetch where arrival_time >= fetched_at group by 1, 2)"""
        extra = "NULL::VARCHAR as cell, NULL::DOUBLE as mm_1h, NULL::VARCHAR as precip_valid_ts, NULL::BIGINT as trip_delay_s"
    else:  # 07's live TU is already one row per (trip, vehicle, fetched_at) with the next-stop prediction
        tu = f"""
        tu as (select * from read_parquet('{TU_ROOT}/**/*.parquet', hive_partitioning=true)
               where {p} and fetched_at >= {t0}),
        nxt as (select trip_id, vehicle_id, fetched_at as tu_fetched_at, next_stop_id, pred_next_s, trip_delay_s
                from tu qualify row_number() over (partition by trip_id, vehicle_id order by fetched_at desc) = 1)"""
        extra = "l.cell, l.mm_1h, l.precip_valid_ts, n.trip_delay_s"
    return f"""
    with vp as (select * from read_parquet('{VP_ROOT}/**/*.parquet', hive_partitioning=true)
                where {p} and fetched_at >= {t0}),
    latest as (select * from vp qualify row_number() over (partition by vehicle_id order by fetched_at desc, ts desc) = 1),
    {tu}
    select l.vehicle_id, l.trip_id, l.route_id, l.stop_id, round(l.bearing, 1) as bearing, l.occupancy, l.ts, l.fetched_at,
           n.pred_next_s, n.next_stop_id, n.tu_fetched_at, round(l.lon, 5) as lon, round(l.lat, 5) as lat, {extra}
    from latest l left join nxt n using (trip_id, vehicle_id)
    order by l.vehicle_id"""


def swap(name, text):
    tmp = f"{OUT}/{name}.tmp"
    open(tmp, "w").write(text)
    os.replace(tmp, f"{OUT}/{name}")


def once(prev_meta=None):
    now, t0 = int(time.time()), time.time()
    try:
        con.execute("create or replace temp table q as " + sql(now))
        # pure-SQL GeoJSON: json_merge_patch('{}', ...) drops null members, so an unknown value is an ABSENT key
        fc = con.execute("""
          select json_object('type', 'FeatureCollection', 'features', coalesce(json_group_array(
            json_object('type', 'Feature',
              'geometry', json_object('type', 'Point', 'coordinates', json_array(lon, lat)),
              'properties', json_merge_patch('{}', json_object(
                 'vehicle_id', vehicle_id, 'trip_id', trip_id, 'route_id', route_id, 'stop_id', stop_id,
                 'bearing', bearing, 'occupancy', occupancy, 'ts', ts, 'fetched_at', fetched_at,
                 'pred_next_s', pred_next_s, 'next_stop_id', next_stop_id, 'cell', cell, 'mm_1h', mm_1h,
                 'precip_valid_ts', precip_valid_ts, 'trip_delay_s', trip_delay_s)))), '[]'::JSON))
          from q""").fetchone()[0]
        n, vp_max, tu_max, n_pred, n_delay, n_rain, pv = con.execute("""
          select count(*), max(fetched_at), max(tu_fetched_at), count(pred_next_s), count(trip_delay_s),
                 count(*) filter (where mm_1h >= 1), max(precip_valid_ts) from q""").fetchone()
        swap("live.geojson", fc)
        meta = {"as_of_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "source": SOURCE, "window_min": WINDOW_MIN, "error": None, "stale": False,
                "vp_fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(vp_max)) if vp_max else None,
                "vp_age_s": now - vp_max if vp_max else None,
                "tu_fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(tu_max)) if tu_max else None,
                "n_vehicles": n, "n_with_prediction": n_pred, "n_with_trip_delay": n_delay, "n_in_rain_cells": n_rain,
                "precip_valid_ts": pv, "stream_progress": None,
                "export_s": round(time.time() - t0, 2)}
    except Exception as e:  # noqa - a dead exporter must look stale on the page, never absent
        meta = dict(prev_meta or {"as_of_utc": None, "source": SOURCE, "n_vehicles": None})
        meta.update({"error": f"{type(e).__name__}: {str(e)[:200]}", "stale": True,
                     "checked_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))})
    swap("meta.json", json.dumps(meta))
    return meta


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    m = once()
    print(json.dumps(m))
    if os.environ.get("ONCE"):
        sys.exit(0)
    while True:
        time.sleep(30)
        m = once(m)
        print(m.get("as_of_utc"), m.get("n_vehicles"), m.get("vp_age_s"), m.get("error"), flush=True)
