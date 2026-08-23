"""Probe gtfsrt.io for the hours it actually holds, so a gap can be classified.

A backfilled hour can come up missing for two very different reasons: the fill failed, or
gtfsrt.io never stored that hour. Only the second is acceptable, and ticket 20's rule is
that an hour goes on a DEAD list ONLY after probing the source and finding zero snapshots
- never to quiet a fill that merely failed. This is that probe, so the rule is a command
rather than a good intention.

It reads only Parquet metadata (row-group stats), so it costs a footer read, not the
1.2 GB file, and it derives the hour exactly the way gapfill.fill_day does - same
fetch_timestamp, same same-day filter - so its answer is the one the fill would give.

Usage: backfill-probe.py <kind> <day> [<day>...]     kind in vp|tu|alerts
Prints snapshots per hour, the zero-snapshot hours, and a paste-ready DEAD entry.
Exit 1 if any probed day has zero-snapshot hours (i.e. real dead hours exist).
"""
import sys
from datetime import timezone

import fsspec
import pyarrow.compute as pc
import pyarrow.parquet as pq

from raincheck.feeds import FEEDS
from raincheck.gapfill import GCS, SOURCES, b64


def probe(kind: str, day: str) -> list[str]:
    feed_type, pairs = SOURCES[kind]
    feed_key = pairs[0][0]
    url = f"{GCS}/{feed_type}/date={day}/base64url={b64(FEEDS[feed_key])}/data.parquet"
    with fsspec.open(url, "rb", cache_type="blockcache", block_size=16 << 20).open() as fh:
        pf = pq.ParquetFile(fh)
        names = pf.schema_arrow.names
        i_fetch = names.index("fetch_timestamp")
        md = pf.metadata
        hours: dict[str, int] = {}
        no_clock = 0
        for i in range(md.num_row_groups):
            rg = md.row_group(i)
            if rg.num_rows == 0:
                continue
            stats = rg.column(i_fetch).statistics
            if stats and stats.has_min_max:
                lo = stats.min
            else:   # stats absent, seen in the wild ~1 group/day
                col = pf.read_row_groups([i], columns=["fetch_timestamp"]).column("fetch_timestamp")
                if col.null_count == len(col):
                    no_clock += 1       # snapshot with no poll clock; fill skips these too
                    continue
                lo = pc.min_max(col)["min"].as_py()
            dt = lo if lo.tzinfo else lo.replace(tzinfo=timezone.utc)
            if dt.strftime("%Y-%m-%d") != day:
                continue                # belongs to a neighbouring day's partition
            hours[dt.strftime("%H")] = hours.get(dt.strftime("%H"), 0) + 1
    dead = [f"{h:02d}" for h in range(24) if f"{h:02d}" not in hours]
    print(f"{kind} {day}: {md.num_row_groups} row groups, "
          f"{sum(hours.values())} snapshots, {no_clock} without a poll clock")
    print("  per hour:", {h: hours[h] for h in sorted(hours)})
    if dead:
        print(f"  ZERO SNAPSHOTS AT SOURCE ({len(dead)} hours): {', '.join(dead)}")
        print(f'  DEAD entry:  ("{kind}", "{day}"): {{{", ".join(chr(34) + h + chr(34) for h in dead)}}},')
    else:
        print("  no dead hours - every hour has snapshots, so a gap here is a FILL failure")
    return dead


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    kind, days = sys.argv[1], sys.argv[2:]
    if kind not in SOURCES:
        raise SystemExit(f"unknown kind {kind!r}; expected one of {', '.join(SOURCES)}")
    raise SystemExit(1 if any(probe(kind, d) for d in days) else 0)
