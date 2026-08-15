"""Poll MTA bus GTFS-RT and produce decoded JSON to Kafka.

Smoke: python -m raincheck.producer --once
Loop:  python -m raincheck.producer            (VP 30s, TU 120s)
"""
import argparse
import json
import sys
import time

from confluent_kafka import Producer

from raincheck.feeds import decode_tu, decode_vp, fetch

TOPICS = {"vp": "raincheck.bus.vp", "tu": "raincheck.bus.tu"}
KEYS = {"vp": "vehicle_id", "tu": "trip_id"}


def produce_once(producer: Producer, name: str) -> int:
    feed = fetch(name)
    rows = decode_vp(feed) if name == "vp" else decode_tu(feed)
    for r in rows:
        producer.produce(
            TOPICS[name],
            key=str(r[KEYS[name]] or ""),
            value=json.dumps(r, separators=(",", ":")),
        )
    producer.flush(30)
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="one VP+TU cycle, then exit")
    ap.add_argument("--bootstrap", default="localhost:9092")
    args = ap.parse_args()

    producer = Producer({"bootstrap.servers": args.bootstrap, "linger.ms": 50})

    if args.once:
        n_vp = produce_once(producer, "vp")
        n_tu = produce_once(producer, "tu")
        print(f"produced vp={n_vp} tu={n_tu}")
        return

    last_tu = 0.0
    while True:
        started = time.time()
        try:
            n = produce_once(producer, "vp")
            print(f"vp={n}", flush=True)
            if started - last_tu >= 120:
                n = produce_once(producer, "tu")
                print(f"tu={n}", flush=True)
                last_tu = started
        except Exception as exc:  # feed hiccups are routine; keep polling
            print(f"poll error: {exc}", file=sys.stderr, flush=True)
        time.sleep(max(0.0, 30 - (time.time() - started)))


if __name__ == "__main__":
    main()
