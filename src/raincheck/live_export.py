"""`make live-export` (ticket 14 / spec L): the live view's two files, on a 30 s loop.

Every tick DuckDB reads the last `window_min` minutes of the VP and TU tables, takes the
latest Ping per vehicle, left-joins the next-stop Prediction, and swaps

    web/files/live.geojson    one Point Feature per vehicle, unknown value = ABSENT key
    web/files/meta.json       what the panel needs to call itself stale, and why

Three rules the panel's honesty rests on, none of which may be "simplified":

1. **The recency filter is the WALL CLOCK** (`fetched_at >= now() - window`), never
   `max(fetched_at) - window`: against the table's own max a dead stream still returns a
   full fleet, and the page shows a frozen city as a live one. The partition prune is
   `date IN (today, yesterday) AND hour IN (HH, HH-1)` literals off the same wall clock,
   and the `max(fetched_at)` probe runs over that pruned set *without* the recency filter -
   that probe is what dates a dead table, so it must not be filtered by it.
2. **The Prediction is measured against the feed's own SNAPSHOT CLOCK** (`header_ts`,
   falling back to `fetched_at`), never `now()` - ticket 12's handoff. A post-sleep replay
   judges old messages against the era they were published in; wall clock NULLs every
   Prediction and the panel scores zero-but-green (measured on the 08-11 fixture).
3. **A failed tick writes `meta.json` with `error` + `stale` and leaves `live.geojson`
   alone.** A dead exporter must look stale on the page, never absent, and never fresh.

Sources (`SOURCE=`):

    live      <root>/live/vp + /live/tu, 10-min window. The stream already reduced TU to
              one row per (trip, vehicle, fetched_at) and already joined Cell + mm_1h +
              precip_valid_ts onto the VP row, so this path does no precip join.
    bronze    <root>/archive/vp + /archive/tu, 20-min window (Bronze flushes in 10-min
              parts). Stop-row TU is reduced in two steps - latest fetch per (trip,
              vehicle), then that fetch's earliest future arrival. No Cell, no mm_1h, no
              trip_delay_s; `fetched_at IS NULL` archive-era rows drop out on the recency
              filter. A labelled demo fallback: the page prints `source: bronze`.

The SQL stays in this module rather than a `web/*.sql` twin of the insight export: every
tick's text is parameterised by the wall clock, so there is no standalone-runnable script
to keep honest.

Run: make live-export                 (30 s loop, Ctrl-C stops it)
     make live-export SOURCE=bronze   (the labelled demo fallback)
     make live-export ONCE=1          (one tick, for a smoke check)
"""
import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from raincheck import duck
from raincheck.paths import REPO, data_root

OUT = REPO / "web" / "files"
INTERVAL_S = 30
STAMP = "%Y-%m-%dT%H:%M:%SZ"
RAIN_MM = 1.0        # the live rain flag: RadarOnly mm_1h, uncalibrated (spec L)
# window per source, and the table each reads. Bronze's 20 min covers its 10-min flush lag.
SOURCES = {"live": ("live", 10), "bronze": ("archive", 20)}

# duck.table()'s reader: hive keys as strings (never autocast), union_by_name for Bronze's
# three column eras (CONTEXT.md) - a pre-era part missing header_ts must read NULL, not fail.
READ = ("read_parquet('{path}/**/*.parquet', hive_partitioning = true, "
        "hive_types_autocast = false, union_by_name = true)")

# the properties every Feature may carry (spec L). json_merge_patch('{}', ...) drops the
# null members, so an unknown value is an ABSENT key - the same writer discipline as the
# insight export, for the same reason (MapLibre's ["has", p] is true on a null).
PROPS = ("vehicle_id", "trip_id", "route_id", "stop_id", "bearing", "occupancy", "ts",
         "fetched_at", "cell", "next_stop_id", "pred_next_s", "mm_1h", "precip_valid_ts",
         "trip_delay_s")


def _stamp(epoch: float | None) -> str | None:
    return None if epoch is None else datetime.fromtimestamp(epoch, timezone.utc).strftime(STAMP)


def prune(now: datetime) -> str:
    """`date IN (...) AND hour IN (...)` literals for this hour and the previous one, off
    the WALL clock. Both keys are strings (`hive_types_autocast = false`). Two hours is
    enough for a 10- or 20-minute window and is midnight- and year-boundary safe because
    both literals come from real datetimes rather than arithmetic on the parts."""
    hours = [now, now - timedelta(hours=1)]
    dates = ", ".join(sorted({f"'{h:%Y-%m-%d}'" for h in hours}))
    hh = ", ".join(sorted({f"'{h:%H}'" for h in hours}))
    return f"date IN ({dates}) AND hour IN ({hh})"


def _next_stop_sql(source: str, t0: int) -> str:
    """The `nxt` CTE: one next-stop Prediction per (trip_id, vehicle_id).

    `snap` is the feed's own snapshot clock - `coalesce(header_ts, fetched_at)`. "Future"
    and the seconds-to-arrival are both measured against it, never against `now()`.
    """
    if source == "bronze":
        # two steps, because Bronze TU is still one row per stop: the LATEST fetch for the
        # (trip, vehicle), and then the earliest future arrival *of that fetch*. Pooling
        # both steps into one min() would pick an older fetch's stale earlier arrival.
        return f"""
        tu_win AS (SELECT *, coalesce(header_ts, fetched_at) AS snap FROM tu_pruned
                   WHERE fetched_at >= {t0}),
        tu_fetch AS (SELECT * FROM tu_win
                     QUALIFY fetched_at = max(fetched_at) OVER (PARTITION BY trip_id, vehicle_id)),
        nxt AS (SELECT trip_id, vehicle_id, max(fetched_at) AS tu_fetched_at,
                       arg_min(stop_id, arrival_time) AS next_stop_id,
                       min(arrival_time) - max(snap) AS pred_next_s,
                       NULL::BIGINT AS trip_delay_s
                FROM tu_fetch WHERE arrival_time >= snap GROUP BY 1, 2)"""
    # the stream already reduced live/tu to one row per (trip, vehicle, fetched_at) under
    # this same snapshot-clock rule, so the latest such row is the Prediction. A trip whose
    # every prediction went stale keeps its row with NULL next_* - alive, but not predicted.
    return f"""
        tu_win AS (SELECT * FROM tu_pruned WHERE fetched_at >= {t0}),
        nxt AS (SELECT trip_id, vehicle_id, fetched_at AS tu_fetched_at, next_stop_id,
                       next_arrival_time - coalesce(header_ts, fetched_at) AS pred_next_s,
                       trip_delay_s
                FROM tu_win
                QUALIFY row_number() OVER (PARTITION BY trip_id, vehicle_id
                                           ORDER BY fetched_at DESC) = 1)"""


def prepare(con, root: Path, source: str, now: datetime) -> None:
    """Materialise the two pruned partition sets, then `q` - the latest Ping per vehicle
    left-joined to its Prediction - off them.

    The pruned sets are a table rather than an inlined CTE because the `max(fetched_at)`
    probe reads them WITHOUT the recency filter: a table nobody has written to for an hour
    has no rows in the window, and how old it is is exactly what the panel needs to know.
    """
    table, window_min = SOURCES[source]
    t0 = int(now.timestamp()) - window_min * 60
    for kind in ("vp", "tu"):
        con.execute(f"CREATE OR REPLACE TEMP TABLE {kind}_pruned AS SELECT * FROM "
                    f"{READ.format(path=f'{root}/{table}/{kind}')} WHERE {prune(now)}")
    # bronze carries none of the stream's enrichment; the keys go absent rather than null
    extra = ("l.cell, l.mm_1h, l.precip_valid_ts" if source == "live" else
             "NULL::BIGINT AS cell, NULL::FLOAT AS mm_1h, NULL::TIMESTAMP AS precip_valid_ts")
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE q AS
    WITH latest AS (SELECT * FROM vp_pruned WHERE fetched_at >= {t0}
                    QUALIFY row_number() OVER (PARTITION BY vehicle_id
                                               ORDER BY fetched_at DESC, ts DESC) = 1),
         {_next_stop_sql(source, t0)}
    SELECT l.vehicle_id, l.trip_id, l.route_id, l.stop_id, round(l.bearing, 1) AS bearing,
           l.occupancy, l.ts, l.fetched_at, n.next_stop_id, n.pred_next_s, n.trip_delay_s,
           round(l.lon, 5) AS lon, round(l.lat, 5) AS lat, {extra}
    FROM latest l LEFT JOIN nxt n USING (trip_id, vehicle_id)""")


def geojson(con) -> str:
    """The FeatureCollection, written in SQL so an unknown value is an absent key.

    `string_agg(... ORDER BY vehicle_id)` rather than `json_group_array`, for the same two
    reasons as the insight export: the ordering makes two ticks over the same rows produce
    the same bytes, and `json_group_array` is a macro in DuckDB 1.5.5, so it takes no
    ORDER BY at all.
    """
    members = ", ".join(f"'{p}', {_prop_expr(p)}" for p in PROPS)
    (text,) = con.execute(f"""
        SELECT '{{"type":"FeatureCollection","features":[' ||
               coalesce(string_agg(feature, ',' ORDER BY vehicle_id), '') || ']}}'
        FROM (SELECT vehicle_id, json_object(
                  'type', 'Feature',
                  'geometry', json_object('type', 'Point', 'coordinates', json_array(lon, lat)),
                  'properties', json_merge_patch('{{}}', json_object({members}))
              )::VARCHAR AS feature FROM q)""").fetchone()
    return text


def _prop_expr(prop: str) -> str:
    if prop == "cell":
        return "lower(to_hex(cell))"          # the hex Cell string cells.geojson keys on
    if prop == "precip_valid_ts":
        return f"strftime(precip_valid_ts, '{STAMP}')"
    return prop


def stream_progress(root: Path, now: datetime) -> dict | None:
    """The stream's liveness rail, copied in with its age, so the panel can tell a dead
    stream from a dead exporter. Absent, torn or unparseable reads as None - the rail is
    evidence, not a dependency."""
    try:
        rail = json.loads((root / "live" / "_progress.json").read_text())
        end = datetime.strptime(rail["batch_end"], STAMP).replace(tzinfo=timezone.utc)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return {**rail, "age_s": int((now - end).total_seconds())}


def tick(con, root: Path, source: str, now: datetime) -> tuple[str, dict]:
    """One tick's (live.geojson text, meta). Raises on any read failure; `once` is what
    turns that into a meta with `error` set."""
    started = time.monotonic()
    epoch = int(now.timestamp())
    prepare(con, root, source, now)
    text = geojson(con)
    n, n_pred, n_delay, n_rain, precip = con.execute(f"""
        SELECT count(*), count(pred_next_s), count(trip_delay_s),
               count(*) FILTER (WHERE mm_1h >= {RAIN_MM}), epoch(max(precip_valid_ts))::BIGINT
        FROM q""").fetchone()
    vp_max, tu_max = con.execute(
        "SELECT (SELECT max(fetched_at) FROM vp_pruned), "
        "(SELECT max(fetched_at) FROM tu_pruned)").fetchone()
    meta = {
        "as_of_utc": _stamp(epoch),
        "source": source,
        "window_min": SOURCES[source][1],
        "error": None,
        "stale": False,          # this TICK failed; the panel owns the age thresholds
        "vp_fetched_at_utc": _stamp(vp_max),
        "vp_age_s": None if vp_max is None else epoch - vp_max,
        "tu_fetched_at_utc": _stamp(tu_max),
        "tu_age_s": None if tu_max is None else epoch - tu_max,
        "precip_valid_ts": _stamp(precip),
        "precip_age_s": None if precip is None else epoch - precip,
        "n_vehicles": n,
        "n_with_prediction": n_pred,
        "n_with_trip_delay": n_delay,
        "n_in_rain_cells": n_rain,
        "stream_progress": stream_progress(root, now),
        "export_s": round(time.monotonic() - started, 2),
    }
    return text, meta


def swap(path: Path, text: str) -> None:
    """Atomic replace: the page reads these files while we write them."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def once(con, root: Path, out_dir: Path, source: str, prev: dict | None = None,
         now: datetime | None = None) -> dict:
    """One tick, written. Never raises: a dead exporter must look stale on the page."""
    now = now or datetime.now(timezone.utc)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        text, meta = tick(con, root, source, now)
        swap(out_dir / "live.geojson", text)
    except Exception as exc:  # noqa: BLE001 - any read failure is a stale panel, not a crash
        # carry the last good numbers so the panel can say how old they are, and say why
        meta = {**(prev or {"as_of_utc": None, "n_vehicles": None}),
                "source": source, "window_min": SOURCES[source][1],
                "error": f"{type(exc).__name__}: {str(exc)[:200]}", "stale": True,
                "checked_utc": now.strftime(STAMP)}
    swap(out_dir / "meta.json", json.dumps(meta))
    return meta


def loop(root: Path, out_dir: Path, source: str, interval: float = INTERVAL_S,
         once_only: bool = False) -> dict:
    """The foreground loop. Ctrl-C stops it; a failing tick does not."""
    con = duck.connect()
    meta = once(con, root, out_dir, source)
    print(json.dumps(meta), flush=True)
    while not once_only:
        time.sleep(interval)
        meta = once(con, root, out_dir, source, meta)
        print(f"{meta.get('as_of_utc')} n={meta.get('n_vehicles')} "
              f"vp_age_s={meta.get('vp_age_s')} error={meta.get('error')}", flush=True)
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=sorted(SOURCES), default=os.environ.get("SOURCE") or "live",
                    help="live tables (default) or the labelled Bronze demo fallback")
    ap.add_argument("--once", action="store_true", default=bool(os.environ.get("ONCE")),
                    help="one tick, then exit")
    ap.add_argument("--out", type=Path, default=OUT, help=f"output directory (default {OUT})")
    args = ap.parse_args()
    root = data_root()
    print(f"live-export: root={root} source={args.source} "
          f"window={SOURCES[args.source][1]} min -> {args.out} (Ctrl-C stops)", flush=True)
    try:
        loop(root, args.out, args.source, once_only=args.once)
    except KeyboardInterrupt:
        print("live-export: stopped", flush=True)


if __name__ == "__main__":
    main()
