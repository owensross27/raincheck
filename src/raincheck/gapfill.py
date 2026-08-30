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

Fill:   python -m raincheck.gapfill fill [vp] [--date 2026-08-19[:2026-08-21]]
Check:  python -m raincheck.gapfill check   (hour completeness per kind x closed day)
Verify: python -m raincheck.gapfill verify [vp]  (filled hours vs adjacent archiver hours)
The optional kind is POSITIONAL, and that is the seam a scheduler maps on: one pod per
kind runs `<the stage's process form> <kind>` with nothing else changed (orch 06).
Both return checks.Row batches (ticket 02): printed as today, persisted under
<root>/checks/, exit 1 any fail / 2 any inconclusive / 0.
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

from raincheck import checks
from raincheck.archiver import KEY, TYPES
from raincheck.feeds import CAUSE, EFFECT, FEEDS, OCCUPANCY, SUBWAY_FEEDS, TRIP_REL
from raincheck.paths import data_root

GCS = "https://storage.googleapis.com/parquet.gtfsrt.io"
START = date(2026, 8, 15)  # capture began; ticket 20 scope
KINDS = ("vp", "tu", "alerts", "subway_tu", "subway_alerts")
CADENCE = {"vp": 30, "tu": 120, "alerts": 300, "subway_tu": 60, "subway_alerts": 300}
# Hours gtfsrt.io itself never stored - zero snapshots at source, so no fill can ever
# produce them and gapcheck must not fail forever on them. "Zero snapshots" means zero
# DISTINCT ones: every hour listed so far had all ~60 raw polls present but
# header.timestamp frozen across them, so pick() - and an awake archiver, same dedup -
# keeps nothing. Add an entry ONLY after probing the source and confirming that; never
# to quiet a fill that merely failed. gapcheck prints a stale note when a listed hour
# turns up.
DEAD = {
    ("subway_alerts", "2026-08-15"): ("07", "12"),
    ("subway_alerts", "2026-08-16"): ("13",),
    ("subway_alerts", "2026-08-22"): ("18",),
    ("subway_alerts", "2026-08-24"): ("08",),  # probed 2026-08-30: 60 polls, 1 header_ts
    ("subway_alerts", "2026-08-29"): ("02",),  # probed 2026-08-30: 60 polls, 1 header_ts
    # Backfilled bus history has one known source-dead hour, vp 2026-04-27 h04 (probed
    # 2026-08-23; see ticket 20). It is deliberately NOT listed: check() iterates from
    # START, so a pre-START key would never match and would sit here looking like
    # protection it does not provide. Add it if and when START moves back.
}
# The bands verify() actually enforces - deliberately an order of magnitude wider than
# ticket 20's MEASURED 0.85-1.2x same-day result. A GX suite expects on these, never on
# the observed number: a suite that expects tighter than the code makes the suite the real
# gate and silently changes what passes.
ROW_BAND = (0.1, 10.0)
KEY_BAND = (0.3, 10 / 3)
# The declared column set of each check's batch, asserted by checks.write. Counts, dates,
# kinds, hour labels and ratios only - never a feed column, because GX renders unexpected
# values into Data Docs and publishing Data Docs would then publish MTA rows.
CHECK_COLUMNS = {
    "gapcheck": checks.CORE + ("kind", "day", "hours_held", "fillable", "dead", "stale_dead"),
    "gapverify": checks.CORE + ("kind", "day", "filled_hour", "captured_hour", "filled_rows",
                                "captured_rows", "filled_keys", "captured_keys", "row_ratio",
                                "key_ratio", "schema"),
}
RAW_COLS = {  # the gtfsrt.io columns each mapper reads (their files carry ~35-46)
    "vehicle_positions": ["entity_id", "vehicle_id", "trip_id", "route_id", "direction_id",
                          "start_date", "schedule_relationship", "latitude", "longitude",
                          "bearing", "stop_id", "timestamp", "occupancy_status",
                          "feed_timestamp", "fetch_timestamp"],
    "trip_updates": ["entity_id", "trip_id", "route_id", "start_date", "direction_id",
                     "vehicle_id", "trip_delay", "trip_timestamp", "stop_id",
                     "stop_sequence", "arrival_time", "departure_time",
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
        "header_ts": t.column("feed_timestamp"),
        "fetched_at": _epoch(t.column("fetch_timestamp")),
    })


def _stu_rows(t: pa.Table) -> pa.Table:  # decode_tu: entities without StopTimeUpdates emit no rows
    return t.filter(pc.or_(pc.or_(pc.is_valid(t.column("stop_id")),
                                  pc.is_valid(t.column("arrival_time"))),
                           pc.is_valid(t.column("departure_time"))))


def _tu(t: pa.Table) -> pa.Table:
    t = _stu_rows(t)
    return _bronze(t.num_rows, {  # ticket 10's TU_COLS shape
        "trip_id": _nn(t.column("trip_id")),
        "route_id": _nn(t.column("route_id")),
        "start_date": _nn(t.column("start_date")),
        "direction_id": t.column("direction_id"),
        "vehicle_id": _nn(t.column("vehicle_id")),
        "trip_delay_s": t.column("trip_delay"),
        "trip_ts": t.column("trip_timestamp"),
        "stop_id": _nn(t.column("stop_id")),
        "stop_sequence": t.column("stop_sequence"),
        "arrival_time": t.column("arrival_time"),
        "departure_time": t.column("departure_time"),
        "header_ts": t.column("feed_timestamp"),
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
        # gtfsrt.io grew service_alerts from 20 to 50 columns mid-2026; their
        # historical files have no direction_id at all -> NULL, exactly as the
        # NYCT extension columns above. Absent-column, not absent-value.
        "direction_id": t.column("direction_id") if "direction_id" in t.column_names
        else None,
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


def fill_day(root: Path, kind: str, day: str) -> bool:
    feed_type, feed_maps = SOURCES[kind]
    date_dir = root / "archive" / kind / f"date={day}"
    hours = missing_hours(date_dir)
    if not hours:
        print(f"gapfill {kind} {day}: no missing hours", flush=True)
        return True
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
                out.parent.mkdir(parents=True, exist_ok=True)   # remote: nothing to create
                buf = pa.BufferOutputStream()                   # one whole-object write, so
                pq.write_table(table, buf, compression="zstd")  # an R2 root gets one PUT
                out.write_bytes(buf.getvalue())
                written[hh] = written.get(hh, 0) + 1
    if all_ok:
        # THE MARKER IS LAST, and this ordering is the contract, not tidiness (cloud 09's
        # frozen pattern, and the reason cloud 13 did not need a lock on an object store):
        # missing_hours() treats a marker-less hour as still missing, so an interrupted
        # fill leaves parts behind that the next run overwrites, while a marker written
        # first would retire an hour that was never filled. Pinned, mutation-checked, by
        # tests/test_object_store_writes.py.
        for hh in written:
            (date_dir / f"hour={hh}" / "_gapfill").touch()
    print(f"gapfill {kind} {day}: filled {len(written)}/{len(hours)} missing hours"
          + ("" if all_ok else " (partial: unpublished feeds above, no markers written)"),
          flush=True)
    return all_ok


def days(start: date | None = None, end: date | None = None):
    d = start or START
    end = end or datetime.now(timezone.utc).date() - timedelta(days=1)
    while d <= end:
        yield d.isoformat()
        d += timedelta(days=1)


def check(root: Path) -> list[checks.Row]:
    """Hour completeness per kind x closed day, one row each. Fails on fillable gaps and on
    a stale DEAD entry (an hour listed dead at source that is actually here: the allowlist
    is now protecting nothing and must be pruned, so it is a defect and not a note). DEAD
    hours that really are missing are reported but never fail - a scheduled run pages on
    real gaps instead of forever on holes gtfsrt.io never had."""
    rows = []
    for kind in KINDS:
        for day in days():
            date_dir = root / "archive" / kind / f"date={day}"
            have = {d.name[5:] for d in date_dir.glob("hour=*") if any(d.glob("*.parquet"))}
            miss = {f"{h:02d}" for h in range(24)} - have
            dead = set(DEAD.get((kind, day), ()))
            fillable, covered, stale = sorted(miss - dead), sorted(dead & miss), sorted(dead - miss)
            note = f"  missing {','.join(fillable)}" if fillable else ""
            if covered:
                note += f"  [dead at source: {','.join(covered)}]"
            if stale:
                note += f"  [stale DEAD entry - hour(s) present: {','.join(stale)}]"
            rows.append(checks.Row(
                "gapcheck", f"{kind} {day}",
                checks.FAIL if fillable or stale else checks.OK, note,
                {"kind": kind, "day": day, "hours_held": 24 - len(miss),
                 "fillable": ",".join(fillable), "dead": ",".join(covered),
                 "stale_dead": ",".join(stale)}))
    return rows


def verify(root: Path, kind: str | None = None) -> list[checks.Row]:
    """One row per kind: a filled hour vs the fullest archiver hour of the same day (by
    bytes: startup remnants and partial hours lose): non-empty, row count and distinct-key
    coverage not wildly off (their poll cadence is thinned to ours, so ratios should be
    near 1), and every archiver column present in the filled part with the same type
    (subset, not equality: pre-ticket-07 vp parts lack schedule_relationship - era drift
    that predates the fill).

    A kind with no filled/captured pair on any day is INCONCLUSIVE, never ok. It used to
    return 0 - the same false-OK class ticket 20 documented for the pre-live range, in the
    opposite direction: a check that compared nothing reported clean."""
    rows = []
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
            rows.append(checks.Row(
                "gapverify", k, checks.INCONCLUSIVE,
                "no filled hour with an archiver hour on the same day yet",
                dict.fromkeys(CHECK_COLUMNS["gapverify"][len(checks.CORE):]) | {"kind": k}))
            continue
        tf, ta = pq.read_table(pair[0]), pq.read_table(pair[1])
        kf = len(pc.unique(tf.column(KEY[k]).drop_null())) or 1
        ka = len(pc.unique(ta.column(KEY[k]).drop_null())) or 1
        schema_ok = all(f.name in tf.schema.names and tf.schema.field(f.name).type == f.type
                        for f in ta.schema)
        row_ratio, key_ratio = tf.num_rows / max(ta.num_rows, 1), kf / ka
        bad = (tf.num_rows == 0 or not schema_ok
               or not ROW_BAND[0] <= row_ratio <= ROW_BAND[1]
               or not KEY_BAND[0] <= key_ratio <= KEY_BAND[1])
        rows.append(checks.Row(
            "gapverify", k, checks.FAIL if bad else checks.OK, "",
            {"kind": k, "day": pair[0].parent.name[5:],
             "filled_hour": pair[0].name[5:], "captured_hour": pair[1].name[5:],
             "filled_rows": tf.num_rows, "captured_rows": ta.num_rows,
             "filled_keys": kf, "captured_keys": ka,
             "row_ratio": round(row_ratio, 4), "key_ratio": round(key_ratio, 4),
             "schema": "=" if tf.schema.equals(ta.schema) else "superset" if schema_ok
             else "DIFFERS"}))
    return rows


def line(r: checks.Row) -> str:
    """The row rendered as the line these checks have always printed."""
    m = r.measures
    if r.check == "gapcheck":
        return (f"{'GAP' if r.outcome == checks.FAIL else 'OK '} {m['kind']:13s} {m['day']} "
                f"{m['hours_held']:2d}/24{r.detail}")
    if r.outcome == checks.INCONCLUSIVE:
        return f"verify {m['kind']}: {r.detail}"
    return (f"{'BAD' if r.outcome == checks.FAIL else 'OK '} {m['kind']:13s} "
            f"date={m['day']}: filled hour={m['filled_hour']} rows={m['filled_rows']} "
            f"keys={m['filled_keys']} vs hour={m['captured_hour']} rows={m['captured_rows']} "
            f"keys={m['captured_keys']} schema={m['schema']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", nargs="?", default="fill", choices=("fill", "check", "verify"))
    ap.add_argument("kind", nargs="?", choices=KINDS, help="one Bronze kind; default all five")
    ap.add_argument("--date", help="YYYY-MM-DD or START:END (UTC); default 2026-08-15..yesterday")
    args = ap.parse_args()
    root = data_root()
    if args.cmd in ("check", "verify"):
        name = "gapcheck" if args.cmd == "check" else "gapverify"
        rows = check(root) if args.cmd == "check" else verify(root, args.kind)
        for r in rows:
            print(line(r))
        if args.cmd == "check":
            print("note: subway_vp hours are unrecoverable "
                  "(gtfsrt.io archives subway TU only)")
        checks.write(root, name, rows, CHECK_COLUMNS[name])
        sys.exit(checks.rc(rows))
    if args.date:
        a, _, b = args.date.partition(":")
        span = list(days(date.fromisoformat(a), date.fromisoformat(b or a)))
    else:
        span = list(days())
    # A run that accomplished NOTHING must not exit 0. On 2026-08-23 a fill of
    # 2026-08-01..14 reported every one of its 42 day-feed combinations as "not published
    # yet" within the same second - the machine had no network after a crash - and still
    # exited 0, so its driver logged the chunk as done. Only a separate check against R2
    # caught it (ticket 20; orchestration map ticket 6).
    #
    # The bar is deliberately "nothing at all worked", not "something failed": gtfsrt.io
    # lags 1-2 days, so the newest day in a default span is routinely unpublished, and
    # failing on that would page every morning about a hole that fills itself tomorrow -
    # the failure mode gapfill.DEAD exists to avoid. One good day in the span is enough to
    # prove the source was reachable.
    attempted = failed = 0
    for kind in [args.kind] if args.kind else KINDS:
        for day in span:
            attempted += 1
            failed += not fill_day(root, kind, day)
    if attempted and failed == attempted:
        sys.exit(f"gapfill: FAILED - nothing filled across all {attempted} day-feed "
                 f"attempt(s); source unreachable or unpublished, not a partial run")


if __name__ == "__main__":
    main()
