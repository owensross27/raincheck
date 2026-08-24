"""`make daily` (ticket 15 / spec K): the once-a-day catch-up, run by the 06:00
America/New_York LaunchAgent (`launchd/com.raincheck.daily.plist`).

launchd coalesces the intervals a sleeping Mac missed, so the unit of work is "every
gap", not "yesterday": each stage is a catch-up over a bounded window, and a second run
the same day is a no-op.

  gapfill    the Bronze hours the archiver slept through, from gtfsrt.io (ticket 20)
  gapverify  those filled hours against their archiver neighbours (20). Exits 2 -
             INCONCLUSIVE - for a kind with no filled/captured pair to compare (02);
             daily's own semantics are unchanged, so that counts as a failed stage
  gapcheck   what is still missing, per kind x closed day. Strictly AFTER the fill (20):
             the newest day or two legitimately fail until gtfsrt.io publishes them, and
             that exit 1 is the actionable signal - never allowlist it (gapfill.DEAD is
             hand-added, after probing the source shows zero snapshots)
  coldpush   push Bronze, including the hours just filled, to R2 (ticket 18)
  coldcheck  soft - see coldcheck() below
  events     every closed service day of the last 14 that has no Silver partition and
             does hold all the Bronze VP it is built from (Legs + Passages), then gold
             for the months those days touch; a day still short of Bronze is deferred
             out loud rather than frozen short
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
from importlib import import_module
from inspect import signature
from pathlib import Path
from typing import Callable, NamedTuple
from zoneinfo import ZoneInfo

from raincheck.paths import REPO, data_root

WINDOW_DAYS = 14  # spec K: the gap scan is bounded
TAIL_H = 10       # UTC hours of D+1 a service day's Legs run into (03:00 local, either regime)
SILVER = ("leg_hours", "events")
PART = "part-00000.parquet"
NY = ZoneInfo("America/New_York")  # a service day is a local date, and runs past midnight


class Stage(NamedTuple):
    """One nightly stage as METADATA - no stage logic lives here, only the name of where
    it already lives. Both runtimes build their steps from STAGES below: main() here, and
    the Airflow DAG, so the order and the soft/retry rules cannot drift between them."""
    name: str
    entrypoint: str            # "make:<target>" or "py:<module>:<callable>"
    retry: str                 # transport: idempotent, retry with backoff | gate: 0 retries
    soft: bool = False         # reports, never fails the job
    fanout: str | None = None  # the axis a runtime MAY map over; None = never mapped


STAGES = (
    Stage("gapfill", "make:gapfill", "transport", fanout="kind"),
    Stage("gapverify", "make:gapverify", "gate", fanout="kind"),
    Stage("gapcheck", "make:gapcheck", "gate"),  # ticket 20: strictly after the fill
    Stage("coldpush", "make:coldpush", "transport"),
    Stage("coldcheck", "py:raincheck.daily:coldcheck", "gate", soft=True),
    Stage("events", "py:raincheck.daily:build", "transport", fanout="service_date"),
    Stage("precip", "py:raincheck.daily:precip", "transport", fanout="month"),
    Stage("prune", "py:raincheck.daily:prune_live", "transport"),
)


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


def unheld(root: Path, day: str) -> list[str]:
    """The Bronze VP hours this service day is built from that nobody holds: all of D, plus
    D+1's first TAIL_H (`events` reads date IN (D, D+1), and a Leg that started on D can
    still be running at 03:00 local). gapfill's own marker convention decides what counts
    as held; hours dead at source do not count against it."""
    from raincheck import gapfill

    vp = root / "archive" / "vp"
    nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    out = [f"{day}T{h}" for h in gapfill.missing_hours(vp / f"date={day}")
           if h not in gapfill.DEAD.get(("vp", day), ())]
    return out + [f"{nxt}T{h}" for h in gapfill.missing_hours(vp / f"date={nxt}")
                  if int(h) < TAIL_H and h not in gapfill.DEAD.get(("vp", nxt), ())]


def gaps(root: Path, closed: date) -> list[str]:
    """The WINDOW_DAYS closed service days ending at `closed` that have Bronze VP, are
    missing a Silver partition, and hold every Bronze hour they are built from.

    That last test is what keeps a sleep gap from freezing: `events` writes both partitions
    from whatever Bronze exists, and a day with both partitions is never revisited, so
    building one hour early buries a short day behind a green board. Deferring instead
    costs a morning - gapfill runs first, and the same scan retries every day of the
    window - and it says so out loud each time."""
    out = []
    for n in range(WINDOW_DAYS - 1, -1, -1):
        day = (closed - timedelta(days=n)).isoformat()
        if not any((root / "archive" / "vp" / f"date={day}").glob("hour=*/*.parquet")):
            continue  # before capture, or a day we never saw at all - not ours to build
        if all((root / "silver" / t / f"service_date={day}" / PART).exists() for t in SILVER):
            continue
        missing = unheld(root, day)
        if missing:
            print(f"daily: {day} deferred - {len(missing)} Bronze VP hour(s) not held yet "
                  f"({missing[0]} .. {missing[-1]}); gapfill first, or hand-DEAD them if "
                  f"gtfsrt.io never had them", flush=True)
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
    """A check straight after a push lists whatever Bronze was written during the sync -
    the archiver's next part, another session's backfill (both seen) - so re-push once and
    re-check. What survives that is the EC2 box's own capture of the same window (ticket
    19): different bytes for an object that is present, not a missing one. Either way it is
    drift, not loss, and `make coldgaps` is the check that tells them apart. So: this stage
    reports and never fails the job."""
    if run("coldcheck") == 0:
        return 0
    run("coldpush")
    if run("coldcheck") == 0:
        return 0
    print("daily: coldcheck still differs after a re-push - expected while anything else is "
          "writing Bronze (the box's overlapping capture, ticket 19; a concurrent backfill) "
          "- those objects are present, just not byte-identical. `make coldgaps` is the "
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


def resolve(ref: str) -> Callable:
    """`<module>:<callable>`, looked up per call - tests and the DAG replace these
    attributes, so a reference captured at import time would run the wrong function."""
    mod, _, attr = ref.rpartition(":")
    return getattr(import_module(mod), attr)


def call(s: Stage, ctx: dict):
    """Run one stage's entrypoint, handing it only the ctx values its own signature names.
    That binding is why the runtime below dispatches without naming a single stage."""
    kind, _, ref = s.entrypoint.partition(":")
    if kind == "make":
        return run(ref)
    fn = resolve(ref)
    return fn(**{p: ctx[p] for p in signature(fn).parameters})


def steps(ctx: dict, axes: dict) -> list[tuple[str, Callable, bool]]:
    """(name, thunk, soft) per declared stage, expanded over the axes THIS runtime maps -
    for `make daily` only precip's months, exactly as before. A declared axis nobody
    supplies items for stays one step that fans out inside itself (events loops gaps(),
    gapfill sweeps all five kinds); the DAG supplies those axes and gets pods instead."""
    out = []
    for s in STAGES:
        for item in axes.get(s.fanout) or [None]:
            name = s.name if item is None else f"{s.name} {item}"
            bound = ctx if item is None else ctx | {s.fanout: item}
            out.append((name, lambda s=s, c=bound: call(s, c), s.soft))
    return out


def main() -> None:
    root, now = data_root(), datetime.now(timezone.utc)
    ctx = {"root": root, "closed": closed_through(now)}
    # MRMS months are UTC, unlike the service day above
    axes = {"month": precip_months(now.date())}
    failed = [name for name, fn, soft in steps(ctx, axes) if not stage(name, fn) and not soft]
    if failed:
        sys.exit(f"daily: FAILED - {', '.join(failed)} (every stage ran; see above)")
    print("daily: OK", flush=True)


if __name__ == "__main__":
    main()
