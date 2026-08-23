"""Archive MTA bus + subway GTFS-RT to Bronze Parquet (ticket 05 layout). No Kafka
dependency: this is the durable history capture (nothing public archives the bus feed
since 2024-09-06, and no public subway RT archive is verified).

Layout  <root>/archive/<kind>/date=YYYY-MM-DD/hour=HH/part-MM.parquet  (UTC, 10-min windows,
        rows sorted by (key, fetched_at), never deleted); static/<feed>/<Last-Modified>.zip.
        <root> is RAINCHECK_ARCHIVE_ROOT (spec A; default the repo's data/, the SSD in practice).
Kinds   vp 30 s, tu 120 s, alerts 300 s (bus); subway_tu + subway_vp 60 s (8 feeds),
        subway_alerts 300 s; each feed deduped on header.timestamp.
Budget  RAINCHECK_BRONZE_GB (default 10): an absolute count of every byte under <root>/archive
        (live capture, static zips, precip copies, xz sources, converted parts all count), so
        moving the root to the SSD does not shrink it - set it to a drive-sized number there.
        When exceeded, write STOPPED_BUDGET, say so loudly and exit 0 (launchd does not
        restart a clean exit).

Smoke: python -m raincheck.archiver --once
Loop:  python -m raincheck.archiver
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import requests

from raincheck.feeds import (SUBWAY_FEEDS, decode_alerts, decode_subway_tu, decode_subway_vp,
                             decode_tu, decode_vp, fetch)
from raincheck.paths import data_root

ROOT = data_root() / "archive"
BUDGET_BYTES = float(os.environ.get("RAINCHECK_BRONZE_GB") or "10") * 1e9  # empty = default
WINDOW = 600  # seconds per part file
KEY = {"vp": "vehicle_id", "tu": "trip_id", "alerts": "alert_id", "subway_alerts": "alert_id",
       "subway_tu": "trip_id", "subway_vp": "trip_id"}
# explicit column types: an all-None column in one window must not become a null-typed part
TYPES = {c: pa.int64() for c in ("ts", "fetched_at", "header_ts", "arrival_time", "departure_time",
                                 "active_start", "active_end", "direction_id", "stop_sequence",
                                 "current_stop_sequence", "trip_delay_s", "trip_ts")}
TYPES.update({c: pa.float64() for c in ("lat", "lon", "bearing")})
TYPES["is_assigned"] = pa.bool_()
# feed key -> (cadence seconds, [(kind, decoder(feed, feed_key) -> rows)])
PLAN = {
    "vp": (30, [("vp", lambda f, _: decode_vp(f))]),
    "tu": (120, [("tu", lambda f, _: decode_tu(f))]),
    "alerts": (300, [("alerts", lambda f, _: decode_alerts(f, "bus"))]),
    "subway_alerts": (300, [("subway_alerts", lambda f, _: decode_alerts(f, "subway"))]),
    **{f"subway{s}": (60, [("subway_tu", decode_subway_tu), ("subway_vp", decode_subway_vp)])
       for s in SUBWAY_FEEDS},
}
STATIC = {  # 05: daily conditional GET of the static zips, saved by Last-Modified date
    "bronx": "gtfs_bx", "brooklyn": "gtfs_b", "manhattan": "gtfs_m", "queens": "gtfs_q",
    "staten_island": "gtfs_si", "busco": "gtfs_busco", "subway": "gtfs_subway",
}
# 10 (spec C): Kafka is a byproduct of each poll the archiver already makes; Bronze stays
# the record. kind -> (topic, message key column). Subway topics wait for a consumer.
TOPIC = {"vp": ("raincheck.bus.vp", "vehicle_id"), "tu": ("raincheck.bus.tu", "trip_id")}
_producer = None
_kafka_err = {"n": 0, "last": ""}  # counted here, reported once per flush window


def publish(kind: str, rows: list[dict]) -> None:
    """Produce one poll's decoded rows to the kind's topic. Broker-down never blocks or
    crashes capture: librdkafka buffers and retries, errors surface via _kafka_err."""
    global _producer
    if kind not in TOPIC or not rows:
        return
    if _producer is None:
        from confluent_kafka import Producer  # lazy: tests patch _producer without a broker
        log = logging.getLogger("raincheck.kafka")
        log.setLevel(logging.CRITICAL)  # librdkafka retry chatter; errors come via error_cb
        _producer = Producer({
            "bootstrap.servers": os.environ.get("RAINCHECK_KAFKA") or "localhost:9092",
            "linger.ms": 50, "message.timeout.ms": 30000, "compression.type": "zstd",
            # never auto-create: the six-partition spec-C shape only comes from `make topics`
            "allow.auto.create.topics": False,
            "error_cb": lambda e: _kafka_err.update(n=_kafka_err["n"] + 1, last=str(e)),
        }, logger=log)
    topic, key = TOPIC[kind]
    fail = lambda err, msg: err and _kafka_err.update(n=_kafka_err["n"] + 1, last=str(err))
    for r in rows:
        try:
            _producer.produce(topic, key=str(r[key] or ""),
                              value=json.dumps(r, separators=(",", ":")), on_delivery=fail)
        except BufferError:
            _kafka_err.update(n=_kafka_err["n"] + 1, last="local queue full")
            break
    _producer.poll(0)


def flush(rows: list[dict], kind: str, window_start: int) -> Path:
    date, hour, minute = time.strftime("%Y-%m-%d %H %M", time.gmtime(window_start)).split()
    out = ROOT / kind / f"date={date}" / f"hour={hour}" / f"part-{minute}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([(c, TYPES.get(c, pa.string())) for c in rows[0]])
    table = pa.Table.from_pylist(rows, schema=schema)
    if out.exists():  # restart inside the same window: append, keep one file per window
        table = pa.concat_tables([pq.read_table(out), table], promote_options="default")
    key = KEY.get(kind, "fetched_at")
    if key in table.column_names:
        table = table.sort_by([(key, "ascending"), ("fetched_at", "ascending")])
    pq.write_table(table, out, compression="zstd")
    return out


def bronze_bytes() -> int:
    return sum(f.stat().st_size for f in ROOT.rglob("*") if f.is_file())


def fetch_static() -> None:
    cache = ROOT / "static" / "etags.json"
    etags = json.loads(cache.read_text()) if cache.exists() else {}
    for feed, name in STATIC.items():
        url = f"https://rrgtfsfeeds.s3.amazonaws.com/{name}.zip"
        try:
            r = requests.get(url, timeout=120, headers={"If-None-Match": etags.get(feed, "")})
            if r.status_code == 304:
                continue
            r.raise_for_status()
            day = time.strftime("%Y-%m-%d", time.strptime(r.headers["Last-Modified"], "%a, %d %b %Y %H:%M:%S %Z"))
            out = ROOT / "static" / feed / f"{day}.zip"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(r.content)
            etags[feed] = r.headers.get("ETag", "")
            print(f"static {feed}: wrote {out} ({len(r.content)/1e6:.1f} MB)", flush=True)
        except Exception as exc:
            print(f"static {feed}: {exc}", file=sys.stderr, flush=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(etags))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="one poll of every feed, flush, exit")
    args = ap.parse_args()
    marker = ROOT / "STOPPED_BUDGET"
    if marker.exists() and not args.once:  # exit 0: launchd must not restart us into a loop
        print(f"archiver: {marker} exists (Bronze over budget); remove it or raise RAINCHECK_BRONZE_GB",
              file=sys.stderr, flush=True)
        sys.exit(0)

    buf: dict[str, list[dict]] = {}
    last_poll: dict[str, float] = {}
    last_header: dict[str, int] = {}
    window = int(time.time()) // WINDOW * WINDOW
    cache = ROOT / "static" / "etags.json"
    last_static = cache.stat().st_mtime if cache.exists() else 0.0  # daily, across restarts
    last_budget = 0.0

    while True:
        tick = time.time()
        if tick - last_static >= 86400:
            try:
                fetch_static()
            except Exception as exc:
                print(f"static: {exc}", file=sys.stderr, flush=True)
            last_static = tick
        for feed, (cadence, kinds) in PLAN.items():
            if not args.once and tick - last_poll.get(feed, 0) < cadence:
                continue
            last_poll[feed] = tick
            try:
                msg = fetch(feed)
            except Exception as exc:
                print(f"{feed}: {exc}", file=sys.stderr, flush=True)
                continue
            if last_header.get(feed) == msg.header.timestamp:
                continue  # same snapshot as last poll (05: dedupe on header.timestamp)
            last_header[feed] = msg.header.timestamp
            for kind, decode in kinds:
                try:
                    rows = decode(msg, feed)
                    buf.setdefault(kind, []).extend(rows)
                except Exception as exc:
                    print(f"{feed} decode {kind}: {exc}", file=sys.stderr, flush=True)
                    continue
                try:
                    publish(kind, rows)  # 10: bus vp/tu only; a no-op for other kinds
                except Exception as exc:
                    print(f"kafka {kind}: {exc}", file=sys.stderr, flush=True)

        now = int(time.time())
        if args.once or now // WINDOW * WINDOW != window:
            for kind, rows in buf.items():
                if not rows:
                    continue
                try:
                    out = flush(rows, kind, window)
                    print(f"wrote {len(rows)} {kind} rows -> {out}", flush=True)
                except Exception as exc:
                    print(f"flush {kind}: {exc} ({len(rows)} rows dropped)", file=sys.stderr, flush=True)
            buf = {}
            if _kafka_err["n"]:
                print(f"kafka: {_kafka_err['n']} errors this window, last: {_kafka_err['last']}",
                      file=sys.stderr, flush=True)
                _kafka_err.update(n=0, last="")
            if now // WINDOW * WINDOW - window > WINDOW:
                print(f"stall: {(now // WINDOW * WINDOW - window) // WINDOW - 1} window(s) skipped", file=sys.stderr, flush=True)
            window = now // WINDOW * WINDOW
            if args.once or now - last_budget >= 3600:
                last_budget = now
                try:  # ponytail: full stat walk hourly; track bytes incrementally past ~100k files
                    used = bronze_bytes()
                except OSError as exc:
                    print(f"budget check: {exc}", file=sys.stderr, flush=True)
                    used = 0
                if used > BUDGET_BYTES:
                    marker.write_text(f"{used} bytes at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
                    print(f"BRONZE OVER BUDGET: {used/1e9:.2f} GB > {BUDGET_BYTES/1e9:.0f} GB; stopping. "
                          f"Point RAINCHECK_ARCHIVE_ROOT at the external SSD (the count is absolute: move "
                          f"{ROOT} with it) or raise RAINCHECK_BRONZE_GB, then rm {marker}",
                          file=sys.stderr, flush=True)
                    break
            if args.once:
                break
        time.sleep(max(0.0, 30 - (time.time() - tick)))
    if _producer is not None:  # drain the Kafka queue before a clean exit, loudly
        left = _producer.flush(10)
        if left or _kafka_err["n"]:
            print(f"kafka: {left} undelivered at exit, {_kafka_err['n']} errors, "
                  f"last: {_kafka_err['last']}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
