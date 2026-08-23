"""Gap backfill from gtfsrt.io (ticket 20): recover the Bronze hours the laptop archiver
missed while asleep, from the public keyless Parquet archive on GCS.

Source  storage.googleapis.com/parquet.gtfsrt.io/<feed_type>/date=<D>/base64url=<b64>/data.parquet
        (b64 = unpadded base64url of the polled feed URL; verified 2026-08-23: one row
        group per poll snapshot, feed_timestamp = header.timestamp constant per group)
Fill    only hour-dirs the archiver never wrote (our capture wins, hour granularity);
        snapshots thinned to the archiver's poll cadence and deduped on header.timestamp,
        written as part-gapfill-<feed>.parquet + an empty _gapfill marker per filled hour.
NULLs   subway TU NYCT-extension columns (train_id, direction, is_assigned,
        scheduled_track, actual_track) are not archived by gtfsrt.io -> NULL; bus VP
        rows keep presence as gtfsrt.io stored it (proto3 absent-vs-default is theirs).
        subway_vp is not archived there at all - those hours are unrecoverable.

Fill:   python -m raincheck.gapfill fill [--feed vp] [--date 2026-08-19[:2026-08-21]]
Check:  python -m raincheck.gapfill check   (hour completeness per kind x closed day)
Verify: python -m raincheck.gapfill verify  (filled hours vs adjacent archiver hours)
"""
import argparse
import base64
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import fsspec
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from raincheck.archiver import KEY, TYPES
from raincheck.feeds import CAUSE, EFFECT, FEEDS, OCCUPANCY, SUBWAY_FEEDS, TRIP_REL
from raincheck.paths import data_root

GCS = "https://storage.googleapis.com/parquet.gtfsrt.io"
START = date(2026, 8, 15)  # capture began; ticket 20 scope
KINDS = ("vp", "tu", "alerts", "subway_tu", "subway_alerts")
CADENCE = {"vp": 30, "tu": 120, "alerts": 300, "subway_tu": 60, "subway_alerts": 300}
RAW_COLS = {  # the gtfsrt.io columns each mapper reads (their files carry ~35-46)
    "vehicle_positions": ["entity_id", "vehicle_id", "trip_id", "route_id", "direction_id",
                          "start_date", "schedule_relationship", "latitude", "longitude",
                          "bearing", "stop_id", "timestamp", "occupancy_status",
                          "feed_timestamp", "fetch_timestamp"],
    "trip_updates": ["entity_id", "trip_id", "route_id", "start_date", "vehicle_id",
                     "stop_id", "stop_sequence", "arrival_time", "departure_time",
                     "feed_timestamp", "fetch_timestamp"],
    "service_alerts": ["entity_id", "cause", "effect", "active_period_start",
                       "active_period_end", "header_text", "description_text", "agency_id",
                       "route_id", "stop_id", "trip_id", "direction_id",
                       "feed_timestamp", "fetch_timestamp"],
}


def b64(url: str) -> str:
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def _nn(col):  # the decoders' `x or None`: empty string -> NULL
    return pc.if_else(pc.equal(col, ""), pa.scalar(None, pa.string()), col)


def _names(col, enum):  # int enum codes -> proto enum names, null-safe
    names, nums = zip(*enum.items())
    idx = pc.index_in(col.cast(pa.int64()), value_set=pa.array(nums, pa.int64()))
    return pc.take(pa.array(names, pa.string()), idx)


def _epoch(col):  # timestamp[us, tz=UTC] -> int64 epoch seconds (like the decoders' int(time.time()))
    return pc.divide(col.cast(pa.int64()), 1_000_000)


def _bronze(n: int, cols: dict) -> pa.Table:
    """Bronze table in the decoders' column order and archiver.flush's types. Values:
    arrow columns (cast), None (typed NULL column) or a python constant."""
    schema = pa.schema([(c, TYPES.get(c, pa.string())) for c in cols])
    arrays = {}
    for f in schema:
        v = cols[f.name]
        if isinstance(v, (pa.Array, pa.ChunkedArray)):
            arrays[f.name] = v.cast(f.type)
        elif v is None:
            arrays[f.name] = pa.nulls(n, f.type)
        else:
            arrays[f.name] = pa.array([v] * n, f.type)
    return pa.table(arrays, schema=schema)


def _vp(t: pa.Table) -> pa.Table:
    t = t.filter(pc.is_valid(t.column("latitude")))  # decode_vp: a position is required
    return _bronze(t.num_rows, {
        "vehicle_id": pc.coalesce(_nn(t.column("vehicle_id")), t.column("entity_id")),
        "trip_id": _nn(t.column("trip_id")),
        "route_id": _nn(t.column("route_id")),
        "direction_id": t.column("direction_id"),
        "start_date": _nn(t.column("start_date")),
        "schedule_relationship": _names(t.column("schedule_relationship"), TRIP_REL),
        "lat": t.column("latitude"),
        "lon": t.column("longitude"),
        "bearing": t.column("bearing"),
        "stop_id": _nn(t.column("stop_id")),
        "ts": t.column("timestamp"),
        "occupancy": _names(t.column("occupancy_status"), OCCUPANCY),
        "fetched_at": _epoch(t.column("fetch_timestamp")),
    })


def _stu_rows(t: pa.Table) -> pa.Table:  # decode_tu: entities without StopTimeUpdates emit no rows
    return t.filter(pc.or_(pc.or_(pc.is_valid(t.column("stop_id")),
                                  pc.is_valid(t.column("arrival_time"))),
                           pc.is_valid(t.column("departure_time"))))


def _tu(t: pa.Table) -> pa.Table:
    t = _stu_rows(t)
    return _bronze(t.num_rows, {
        "trip_id": _nn(t.column("trip_id")),
        "route_id": _nn(t.column("route_id")),
        "start_date": _nn(t.column("start_date")),
        "vehicle_id": _nn(t.column("vehicle_id")),
        "stop_id": _nn(t.column("stop_id")),
        "stop_sequence": t.column("stop_sequence"),
        "arrival_time": t.column("arrival_time"),
        "departure_time": t.column("departure_time"),
        "fetched_at": _epoch(t.column("fetch_timestamp")),
    })


def _subway_tu(t: pa.Table, feed_key: str) -> pa.Table:
    t = _stu_rows(t)
    return _bronze(t.num_rows, {
        "feed": feed_key,
        "trip_id": _nn(t.column("trip_id")),
        "route_id": _nn(t.column("route_id")),
        "start_date": _nn(t.column("start_date")),
        "train_id": None, "direction": None, "is_assigned": None,  # NYCT extension:
        "stop_id": _nn(t.column("stop_id")),                       # not archived by gtfsrt.io
        "arrival_time": t.column("arrival_time"),
        "departure_time": t.column("departure_time"),
        "scheduled_track": None, "actual_track": None,             # NYCT extension too
        "header_ts": t.column("feed_timestamp"),
        "fetched_at": _epoch(t.column("fetch_timestamp")),
    })


def _alerts(t: pa.Table, agency: str) -> pa.Table:
    return _bronze(t.num_rows, {
        "agency": agency,
        "alert_id": _nn(t.column("entity_id")),
        "cause": _names(t.column("cause"), CAUSE),
        "effect": _names(t.column("effect"), EFFECT),
        "active_start": t.column("active_period_start"),
        "active_end": t.column("active_period_end"),
        "header": _nn(t.column("header_text")),
        "description": _nn(t.column("description_text")),
        "fetched_at": _epoch(t.column("fetch_timestamp")),
        "agency_id": _nn(t.column("agency_id")),
        "route_id": _nn(t.column("route_id")),
        "stop_id": _nn(t.column("stop_id")),
        "trip_id": _nn(t.column("trip_id")),
        "direction_id": t.column("direction_id"),
    })


# kind -> (gtfsrt.io feed_type, [(feed key = FEEDS key = part suffix, mapper)])
SOURCES = {
    "vp": ("vehicle_positions", [("vp", _vp)]),
    "tu": ("trip_updates", [("tu", _tu)]),
    "alerts": ("service_alerts", [("alerts", lambda t: _alerts(t, "bus"))]),
    "subway_alerts": ("service_alerts", [("subway_alerts", lambda t: _alerts(t, "subway"))]),
    "subway_tu": ("trip_updates", [(f"subway{sfx}", lambda t, k=f"subway{sfx}": _subway_tu(t, k))
                                   for sfx in SUBWAY_FEEDS]),
}


def pick(snaps: list[tuple[float, int]], cadence: int) -> list[int]:
    """Indices of the snapshots the archiver would have kept: poll every `cadence` seconds
    (1 s jitter tolerance), skip a poll whose header.timestamp repeats the last kept one."""
    kept, last_poll, last_header = [], None, None
    for i, (fetch, header) in enumerate(snaps):
        if last_poll is not None and fetch - last_poll < cadence - 1:
            continue
        last_poll = fetch
        if header == last_header:
            continue
        last_header = header
        kept.append(i)
    return kept


def missing_hours(date_dir: Path) -> list[str]:
    """Hours the archiver never captured. An hour with any non-gapfill part is the
    archiver's (our capture wins); a _gapfill marker means already filled; gapfill
    parts without a marker are crash debris - refill."""
    out = []
    for h in range(24):
        d = date_dir / f"hour={h:02d}"
        if (d / "_gapfill").exists():
            continue
        if any(p.name.startswith("part-") and not p.name.startswith("part-gapfill")
               for p in d.glob("part-*")):
            continue
        out.append(f"{h:02d}")
    return out


def fill_day(root: Path, kind: str, day: str) -> None:
    feed_type, feed_maps = SOURCES[kind]
    date_dir = root / "archive" / kind / f"date={day}"
    hours = missing_hours(date_dir)
    if not hours:
        print(f"gapfill {kind} {day}: no missing hours", flush=True)
        return
    written: dict[str, int] = {}
    all_ok = True
    for feed_key, mapper in feed_maps:
        url = f"{GCS}/{feed_type}/date={day}/base64url={b64(FEEDS[feed_key])}/data.parquet"
        try:
            f = fsspec.open(url, "rb", cache_type="blockcache", block_size=16 << 20).open()
        except FileNotFoundError:
            print(f"gapfill {kind} {day}: {feed_key} not published yet at gtfsrt.io", flush=True)
            all_ok = False
            continue
        with f:
            pf = pq.ParquetFile(f)
            names = pf.schema_arrow.names
            i_fetch, i_feed = names.index("fetch_timestamp"), names.index("feed_timestamp")
            md, metas, no_clock = pf.metadata, [], 0
            for i in range(md.num_row_groups):
                rg = md.row_group(i)
                if rg.num_rows == 0:
                    continue
                sf, sh = rg.column(i_fetch).statistics, rg.column(i_feed).statistics
                if sf and sf.has_min_max and sh and sh.has_min_max:
                    f_lo, f_hi, h_lo, h_hi = sf.min, sf.max, sh.min, sh.max
                else:  # stats absent (seen in the wild, ~1 group/day): read the two columns
                    two = pf.read_row_groups([i], columns=["fetch_timestamp", "feed_timestamp"])
                    fc, hc = two.column("fetch_timestamp"), two.column("feed_timestamp")
                    if fc.null_count == len(fc):  # a snapshot with no poll clock: skip it,
                        no_clock += 1             # neighbours at their 20-30 s cadence cover it
                        continue
                    f_lo, f_hi = pc.min_max(fc)["min"].as_py(), pc.min_max(fc)["max"].as_py()
                    h_lo, h_hi = pc.min_max(hc)["min"].as_py(), pc.min_max(hc)["max"].as_py()
                if f_lo != f_hi or h_lo != h_hi or h_lo is None:
                    sys.exit(f"gapfill {kind} {day}: {feed_key} row group {i} is not one "
                             f"snapshot (mixed timestamps) - gtfsrt.io layout changed, "
                             f"refusing to guess")
                dt = f_lo if f_lo.tzinfo else f_lo.replace(tzinfo=timezone.utc)
                if dt.strftime("%Y-%m-%d") != day:
                    continue
                metas.append((i, dt.timestamp(), int(h_lo), dt.strftime("%H")))
            if no_clock:
                print(f"gapfill {kind} {day}: {feed_key} skipped {no_clock} snapshot(s) "
                      f"with no poll clock (fetch_timestamp all NULL)", flush=True)
            by_hour: dict[str, list[int]] = {}
            for k in pick([(m[1], m[2]) for m in metas], CADENCE[kind]):
                i, _, _, hh = metas[k]
                if hh in hours:
                    by_hour.setdefault(hh, []).append(i)
            for hh, idxs in sorted(by_hour.items()):
                out = date_dir / f"hour={hh}" / f"part-gapfill-{feed_key}.parquet"
                if hh not in missing_hours(date_dir):  # scan-to-write race: archiver won
                    print(f"gapfill {kind} {day}: hour={hh} captured since scan, skipping", flush=True)
                    written.pop(hh, None)
                    continue
                table = mapper(pf.read_row_groups(idxs, columns=RAW_COLS[feed_type]))
                table = table.sort_by([(KEY[kind], "ascending"), ("fetched_at", "ascending")])
                out.parent.mkdir(parents=True, exist_ok=True)
                pq.write_table(table, out, compression="zstd")
                written[hh] = written.get(hh, 0) + 1
    if all_ok:
        for hh in written:
            (date_dir / f"hour={hh}" / "_gapfill").touch()
    print(f"gapfill {kind} {day}: filled {len(written)}/{len(hours)} missing hours"
          + ("" if all_ok else " (partial: unpublished feeds above, no markers written)"),
          flush=True)


def days(start: date | None = None, end: date | None = None):
    d = start or START
    end = end or datetime.now(timezone.utc).date() - timedelta(days=1)
    while d <= end:
        yield d.isoformat()
        d += timedelta(days=1)


def check(root: Path) -> int:
    """Hour completeness per kind x closed day; exit 1 while any closed day has gaps."""
    gaps = 0
    for kind in KINDS:
        for day in days():
            date_dir = root / "archive" / kind / f"date={day}"
            have = {d.name[5:] for d in date_dir.glob("hour=*") if any(d.glob("*.parquet"))}
            miss = [f"{h:02d}" for h in range(24) if f"{h:02d}" not in have]
            gaps += bool(miss)
            print(f"{'GAP' if miss else 'OK '} {kind:13s} {day} {24 - len(miss):2d}/24"
                  + (f"  missing {','.join(miss)}" if miss else ""))
    print("note: subway_vp hours are unrecoverable (gtfsrt.io archives subway TU only)")
    return 1 if gaps else 0


def verify(root: Path, kind: str | None = None) -> int:
    """For each kind, one filled hour vs the fullest archiver hour of the same day (by
    bytes: startup remnants and partial hours lose): non-empty, row count and distinct-key
    coverage not wildly off (their poll cadence is thinned to ours, so ratios should be
    near 1), and every archiver column present in the filled part with the same type
    (subset, not equality: pre-ticket-07 vp parts lack schedule_relationship - era drift
    that predates the fill)."""
    fails = 0
    for k in [kind] if kind else KINDS:
        pair = None
        for date_dir in sorted((root / "archive" / k).glob("date=*")):
            filled = sorted(d for d in date_dir.glob("hour=*") if (d / "_gapfill").exists())
            captured = [d for d in date_dir.glob("hour=*")
                        if not (d / "_gapfill").exists() and any(d.glob("*.parquet"))]
            if filled and captured:
                pair = (filled[0], max(captured, key=lambda c: sum(
                    p.stat().st_size for p in c.glob("*.parquet"))))
                break
        if not pair:
            print(f"verify {k}: no filled hour with an archiver hour on the same day yet")
            continue
        tf, ta = pq.read_table(pair[0]), pq.read_table(pair[1])
        kf = len(pc.unique(tf.column(KEY[k]).drop_null())) or 1
        ka = len(pc.unique(ta.column(KEY[k]).drop_null())) or 1
        schema_ok = all(f.name in tf.schema.names and tf.schema.field(f.name).type == f.type
                        for f in ta.schema)
        bad = (tf.num_rows == 0 or not schema_ok
               or not 0.1 <= tf.num_rows / max(ta.num_rows, 1) <= 10
               or not 0.3 <= kf / ka <= 10 / 3)
        fails += bad
        print(f"{'BAD' if bad else 'OK '} {k:13s} {pair[0].parent.name}: filled {pair[0].name} "
              f"rows={tf.num_rows} keys={kf} vs {pair[1].name} rows={ta.num_rows} keys={ka} "
              f"schema={'=' if tf.schema.equals(ta.schema) else 'superset' if schema_ok else 'DIFFERS'}")
    return 1 if fails else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", nargs="?", default="fill", choices=("fill", "check", "verify"))
    ap.add_argument("--feed", choices=KINDS, help="one Bronze kind; default all five")
    ap.add_argument("--date", help="YYYY-MM-DD or START:END (UTC); default 2026-08-15..yesterday")
    args = ap.parse_args()
    root = data_root()
    if args.cmd == "check":
        sys.exit(check(root))
    if args.cmd == "verify":
        sys.exit(verify(root, args.feed))
    if args.date:
        a, _, b = args.date.partition(":")
        span = list(days(date.fromisoformat(a), date.fromisoformat(b or a)))
    else:
        span = list(days())
    for kind in [args.feed] if args.feed else KINDS:
        for day in span:
            fill_day(root, kind, day)


if __name__ == "__main__":
    main()
