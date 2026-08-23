"""`make daily` (ticket 15 / spec K): the once-a-day catch-up, run by the 06:00
America/New_York LaunchAgent (`launchd/com.raincheck.daily.plist`).

launchd coalesces the intervals a sleeping Mac missed, so the unit of work is "every
gap", not "yesterday": each stage is a catch-up over a bounded window, and a second run
the same day is a no-op.

  gapfill    the Bronze hours the archiver slept through, from gtfsrt.io (ticket 20)
  gapverify  those filled hours against their archiver neighbours (20)
  gapcheck   what is still missing, per kind x closed day. Strictly AFTER the fill (20):
             the newest day or two legitimately fail until gtfsrt.io publishes them, and
             that exit 1 is the actionable signal - never allowlist it (gapfill.DEAD is
             hand-added, after probing the source shows zero snapshots)
  coldpush   push Bronze, including the hours just filled, to R2 (ticket 18)
  coldcheck  soft - see coldcheck() below
  events     every closed service day of the last 14 with Bronze VP and no Silver
             partition (Legs + Passages), then gold for the months those days touch
  precip     the current MRMS month rebuilt from Bronze, unlanded Pass2 hours fetched on
             the way (ticket 11); on the 1st, the month just ended as well - its tail
             publishes after that month's last run
  prune      live date=/hour= dirs past the 48 h horizon (stream.prune, spec J)

Every stage runs even when an earlier one failed - a red gapcheck must not cost the day's
build - and the job exits 1 naming the stages that failed. The standing pieces run as
their own make targets, so the Makefile stays the one place that knows JAVA_HOME, TZ=UTC
and the .env credentials.

Run: make daily   (python -m raincheck.daily)
"""
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from raincheck.paths import REPO, data_root

WINDOW_DAYS = 14  # spec K: the gap scan is bounded
SILVER = ("leg_hours", "events")
PART = "part-00000.parquet"
NY = ZoneInfo("America/New_York")  # a service day is a local date, and runs past midnight


def run(target: str, **var: str) -> int:
    argv = ["make", "-C", str(REPO), target, *(f"{k}={v}" for k, v in var.items())]
    print(f"daily: + make {' '.join(argv[3:])}", flush=True)
    return subprocess.call(argv)


def closed_through(now: datetime) -> date:
    """The newest service day whose Legs have all landed: local yesterday, or the day
    before it when the run fires before 04:00 local, while yesterday's tail is still out
    on the road. Not `utcnow() - 1 day`: launchd fires a slept-through 06:00 interval at
    wake, at whatever hour that is, and at 21:00 local that subtraction names the service
    day still in progress - whose truncated Silver partition gaps() would never revisit."""
    local = now.astimezone(NY)
    return local.date() - timedelta(days=1 if local.hour >= 4 else 2)


def gaps(root: Path, closed: date) -> list[str]:
    """The WINDOW_DAYS closed service days ending at `closed` that have Bronze VP and are
    missing a Silver partition."""
    out = []
    for n in range(WINDOW_DAYS - 1, -1, -1):
        day = (closed - timedelta(days=n)).isoformat()
        if not any((root / "archive" / "vp" / f"date={day}").glob("hour=*/*.parquet")):
            continue
        if all((root / "silver" / t / f"service_date={day}" / PART).exists() for t in SILVER):
            continue
        out.append(day)
    return out


def months(days: list[str]) -> list[str]:
    return sorted({d[:7] for d in days})


def build(root: Path, closed: date) -> None:
    """Build each gap day and roll the months those days touch. One session for the lot,
    and no session at all when there is nothing to build."""
    days = gaps(root, closed)
    print(f"daily: {len(days)} service day(s) to build: {', '.join(days) or '-'}", flush=True)
    if not days:
        return
    from raincheck import events, gold
    from raincheck.spark import session

    spark = session()
    built, failed = [], []
    try:
        for day in days:
            try:
                events.leg_hours(root, spark, day)
                events.events(root, spark, day)
                built.append(day)
            except (Exception, SystemExit) as e:  # one poisoned day must not starve the newer ones
                print(f"daily: events {day} FAILED: {e}", flush=True)
                failed.append(day)
        for month in months(built):
            gold.speed(root, spark, month)
            gold.route(root, spark, month)
    finally:
        spark.stop()  # the precip stages that follow start their own JVM
    if failed:
        raise SystemExit(f"events failed for {', '.join(failed)}")


def precip_months(today: date) -> list[str]:
    return months([today.isoformat(), (today - timedelta(days=1)).isoformat()])


def precip(month: str) -> int:
    rc = run("precip-hourly", SRC="mrms", MONTH=month)
    return rc or run("precip-cell", SRC="mrms", MONTH=month)  # Cell reads the month just written


def coldcheck() -> int:
    """A check straight after a push lists the parts the archiver wrote during the sync
    (ticket 18) - re-push once and re-check. What survives that is the EC2 box's own
    capture of the same window (ticket 19): different bytes, not a missing object, and
    `make coldgaps` is the check that can tell loss from overlap. So: never fails the job."""
    if run("coldcheck") == 0:
        return 0
    run("coldpush")
    if run("coldcheck") == 0:
        return 0
    print("daily: coldcheck still differs after a re-push - expected while the box and the "
          "Mac both capture (19: same window, different bytes). `make coldgaps` is the "
          "loss check.", flush=True)
    return 0


def prune_live(root: Path) -> None:
    from raincheck import stream  # spec J's 48 h horizon, one implementation of it

    stream.prune(root)


def stage(name: str, fn) -> bool:
    t0, err = time.monotonic(), None
    try:
        rc = fn() or 0
    except (Exception, SystemExit) as e:  # a module's own loud exit ends its stage, not the job
        rc, err = 1, e
    print(f"daily: {name} {'FAILED' if rc else 'ok'} in {time.monotonic() - t0:.0f}s"
          + (f" - {err}" if err else ""), flush=True)
    return not rc


def main() -> None:
    root, now = data_root(), datetime.now(timezone.utc)
    steps = [("gapfill", lambda: run("gapfill")),
             ("gapverify", lambda: run("gapverify")),
             ("gapcheck", lambda: run("gapcheck")),  # ticket 20: strictly after the fill
             ("coldpush", lambda: run("coldpush")),
             ("coldcheck", coldcheck),
             ("events", lambda: build(root, closed_through(now))),
             # MRMS months are UTC, unlike the service day above
             *[(f"precip {m}", lambda m=m: precip(m)) for m in precip_months(now.date())],
             ("prune", lambda: prune_live(root))]
    failed = [name for name, fn in steps if not stage(name, fn)]
    if failed:
        sys.exit(f"daily: FAILED - {', '.join(failed)} (every stage ran; see above)")
    print("daily: OK", flush=True)


if __name__ == "__main__":
    main()
