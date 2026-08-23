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
DEAD = {("vp", "2026-04-27"): {"04"}}


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
        rec = seen.setdefault((day, hour), {"part": 0, "marker": 0})
        rec["marker" if path.endswith("_gapfill") else "part"] += 1
    return seen


def main() -> int:
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
        stale = sorted(s for s in dead if s in seen)
        ok = not (missing or no_part or no_mark)
        bad += not ok
        print(f"{'OK ' if ok else 'BAD'} {feed:7s} {len(seen)}/{len(want)} hours"
              f"{f' (+{len(dead)} dead at source)' if dead else ''}"
              f"  parts_missing={len(no_part)} markers_missing={len(no_mark)}")
        for label, rows in (("missing", missing), ("no part", no_part), ("no marker", no_mark)):
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
