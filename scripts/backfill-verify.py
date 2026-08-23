"""Verify a backfilled date range in R2, hour by hour.

Why this exists: `make gapverify` compares a filled hour against an archiver-captured
hour ON THE SAME DAY. The backfilled range (2026-03-01..08-14) predates live capture
entirely, so no such pair exists there - verify() finds the first day that HAS both,
which is always an August day, and reports OK without ever looking at the backfill.
Running it after a backfill chunk therefore proves nothing about that chunk.

Once a chunk is pushed and pruned, R2 is the only copy, so the check has to run against
R2. This censuses the remote range and names every missing hour.

Usage: backfill-verify.py <LO> <HI> [--feeds vp,tu,alerts]
Exit 1 if any hour is missing or any hour lacks its part or its _gapfill marker.
"""
import os
import subprocess
import sys
from datetime import date, timedelta

FEEDS = ("vp", "tu", "alerts")
# Hours gtfsrt.io itself never stored, confirmed by probing the source for zero snapshots.
# Same rule as gapfill.DEAD: add ONLY after probing, never to quiet a fill that failed.
# Every entry below was produced by scripts/backfill-probe.py, which prints a paste-ready
# line and exits 1 only when real dead hours exist - use it rather than adding by hand.
DEAD = {
    # gtfsrt.io outage near 03:50-05:00Z; tu and alerts kept 8 and 4 snapshots in h04 and
    # so are deliberately absent here.
    ("vp", "2026-04-27"): {"04"},
    # A sparse alerts day: 490 snapshots unevenly spread, several hours holding 1-2 and
    # seven holding none. alerts is event-driven at a 300 s cadence, so a quiet day can
    # legitimately leave whole hours unstored - expect more of these in alerts, and probe
    # each one rather than assuming.
    ("alerts", "2026-05-28"): {"04", "05", "06", "08", "09", "11", "13"},
    # One contiguous alerts outage, 2026-06-24 17:00Z -> 2026-06-25 00:59Z. Split across
    # two keys only because the DEAD map is keyed by day; it is a single 8-hour hole, and
    # the day boundary in the middle is an artifact of the layout, not of the outage.
    ("alerts", "2026-06-24"): {"17", "18", "19", "20", "21", "22", "23"},
    ("alerts", "2026-06-25"): {"00"},
    # First dead hours seen in tu, and the only ones: a gtfsrt.io tu outage covering
    # 00:00-01:59Z. h02 comes back at 100 snapshots against the ~120 norm, i.e. tapering
    # recovery, which is what a source outage ending mid-hour looks like. vp and alerts
    # both filled 24/24 that day, so it hit tu alone - same shape as 2026-04-27, where
    # only vp lost an hour.
    ("tu", "2026-07-30"): {"00", "01"},
}


def days(lo: str, hi: str):
    a, b = date.fromisoformat(lo), date.fromisoformat(hi)
    while a <= b:
        yield a.isoformat()
        a += timedelta(days=1)


def census(bucket: str, endpoint: str, feed: str, lo: str, hi: str):
    """-> {(day, hour): {"part": n, "marker": n}} for the range, from one remote listing."""
    out = subprocess.run(
        ["aws", "s3", "ls", f"s3://{bucket}/archive/{feed}/",
         "--endpoint-url", endpoint, "--recursive"],
        capture_output=True, text=True, check=True).stdout
    seen: dict[tuple[str, str], dict[str, int]] = {}
    lo_key, hi_key = f"date={lo}", f"date={hi}"
    for line in out.splitlines():
        if "/date=" not in line:
            continue
        path = line.split()[-1]
        try:
            day = path.split("date=", 1)[1].split("/", 1)[0]
            hour = path.split("hour=", 1)[1].split("/", 1)[0]
        except IndexError:
            continue
        if not (lo_key <= f"date={day}" <= hi_key):
            continue
        rec = seen.setdefault((day, hour), {"part": 0, "marker": 0, "bytes": 0})
        if path.endswith("_gapfill"):
            rec["marker"] += 1          # markers are legitimately zero-byte
        else:
            rec["part"] += 1
            # Size matters: an object can exist and still be useless. A truncated or
            # zero-byte part would otherwise count as present and the range would verify
            # OK, which is the same false-OK trap that makes gapverify useless here.
            fields = line.split()
            if len(fields) >= 3 and fields[2].isdigit():
                rec["bytes"] += int(fields[2])
    return seen


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    lo, hi = sys.argv[1], sys.argv[2]
    feeds = FEEDS
    if "--feeds" in sys.argv:
        feeds = tuple(sys.argv[sys.argv.index("--feeds") + 1].split(","))
    bucket, endpoint = os.environ["RAINCHECK_COLD_BUCKET"], os.environ["RAINCHECK_COLD_ENDPOINT"]
    want = [(d, f"{h:02d}") for d in days(lo, hi) for h in range(24)]
    bad = 0
    for feed in feeds:
        seen = census(bucket, endpoint, feed, lo, hi)
        dead = {(d, h) for (k, d), hs in DEAD.items()
                if k == feed and lo <= d <= hi for h in hs}
        missing = [s for s in want if s not in seen and s not in dead]
        no_part = [s for s, r in seen.items() if r["part"] == 0]
        no_mark = [s for s, r in seen.items() if r["marker"] == 0]
        empty = [s for s, r in seen.items() if r["part"] > 0 and r["bytes"] == 0]
        stale = sorted(s for s in dead if s in seen)
        ok = not (missing or no_part or no_mark or empty)
        bad += not ok
        print(f"{'OK ' if ok else 'BAD'} {feed:7s} {len(seen)}/{len(want)} hours"
              f"{f' (+{len(dead)} dead at source)' if dead else ''}"
              f"  parts_missing={len(no_part)} markers_missing={len(no_mark)}"
              f" zero_byte_parts={len(empty)}")
        for label, rows in (("missing", missing), ("no part", no_part),
                            ("no marker", no_mark), ("zero-byte part", empty)):
            if rows:
                head = ", ".join(f"{d} h{h}" for d, h in sorted(rows)[:8])
                print(f"     {label}: {head}{' ...' if len(rows) > 8 else ''}")
        if stale:
            # Mirrors gapcheck's stale-DEAD note: a listed hour that turns up means the
            # allowlist is wrong, and a wrong allowlist hides real gaps.
            print(f"     STALE DEAD ENTRY - hour(s) present after all: {stale}")
            bad += 1
    print("backfill-verify:", "OK - range complete in R2" if not bad else "GAPS - see above")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
