"""Archive MTA bus GTFS-RT to hourly Parquet. No Kafka dependency: this is the
durable history capture (nothing public archives this feed since 2024-09-06).

Smoke: python -m raincheck.archiver --once
Loop:  python -m raincheck.archiver            (VP 30s, TU 120s, flush on hour turn)
"""
import argparse
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from raincheck.feeds import decode_tu, decode_vp, fetch

ROOT = Path(__file__).resolve().parents[2] / "data" / "archive"


def flush(rows: list[dict], kind: str, hour_key: str) -> Path:
    date, hour = hour_key.split("T")
    out = ROOT / kind / f"date={date}" / f"hour={hour}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    if out.exists():  # same hour, later flush: append by concat
        table = pa.concat_tables([pq.read_table(out), table], promote_options="default")
    pq.write_table(table, out, compression="zstd")
    return out


def hour_of(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H", time.gmtime(ts))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="one poll, flush, exit")
    args = ap.parse_args()

    buf: dict[str, list[dict]] = {"vp": [], "tu": []}
    current = hour_of(time.time())
    last_tu = 0.0

    while True:
        started = time.time()
        try:
            buf["vp"].extend(decode_vp(fetch("vp")))
            if started - last_tu >= 120 or args.once:
                buf["tu"].extend(decode_tu(fetch("tu")))
                last_tu = started
        except Exception as exc:
            print(f"poll error: {exc}", file=sys.stderr, flush=True)

        turned = hour_of(time.time()) != current
        if args.once or turned:
            for kind, rows in buf.items():
                if rows:
                    out = flush(rows, kind, current)
                    print(f"wrote {len(rows)} {kind} rows -> {out}", flush=True)
                    buf[kind] = []
            current = hour_of(time.time())
            if args.once:
                return
        time.sleep(max(0.0, 30 - (time.time() - started)))


if __name__ == "__main__":
    main()
