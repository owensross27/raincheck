"""`make daily` (ticket 15 / spec K): the once-a-day catch-up, run by the 06:00
America/New_York LaunchAgent (`launchd/com.raincheck.daily.plist`).

launchd coalesces the intervals a sleeping Mac missed, so the unit of work is "every
gap", not "yesterday": each stage is a catch-up over a bounded window, and a second run
the same day is a no-op.

  gapfill    the Bronze hours the archiver slept through, from gtfsrt.io (ticket 20)
  gapverify  those filled hours against their archiver neighbours (20). Exits 2 -
             INCONCLUSIVE - for a kind with no filled/captured pair to compare (02), and
             the job counts that apart from a failure and exits 2 for it (ticket 07)
  gapcheck   what is still missing, per kind x closed day. Strictly AFTER the fill (20):
             the newest day or two legitimately fail until gtfsrt.io publishes them, and
             that exit 1 is the actionable signal - never allowlist it (gapfill.DEAD is
             hand-added, after probing the source shows zero snapshots)
  coldpush   push Bronze, including the hours just filled, to R2 (ticket 18)
  coldcheck  soft - see coldcheck() below
  events     every closed service day of the last 14 that has no Silver partition and
             does hold all the Bronze VP it is built from (Legs + Passages); a day still
             short of Bronze is deferred out loud rather than frozen short
  gold       the months those days touch, rolled once behind them - the days that landed
             only, which is what keeps a failed day's month out of Gold (ticket 06)
  precip     the current MRMS month rebuilt from Bronze, unlanded Pass2 hours fetched on
             the way (ticket 11); on the 1st, the month just ended as well - its tail
             publishes after that month's last run
  prune      live date=/hour= dirs past the 48 h horizon (stream.prune, spec J)
  eras       every verified Bronze bus reader still surfaces the era columns (orch 03).
             Exits 2 - INCONCLUSIVE - when no date dir mixes part schemas (a union reader
             is indistinguishable from a narrow one there) or this box has no JVM; its
             rows are what the schema-era suite below expects on (orchestration 09)
  gxcheck    the Great Expectations suites over the check-result rows THIS run wrote,
             and the Data Docs the public host serves (orchestration 08). Last on
             purpose: it reads the batches the stages above persisted, and the docs are
             built once, at the end. Exits 2 - INCONCLUSIVE - when a suite could not run
             at all (no batch, or the optional GX extra is not installed)

Every stage runs even when an earlier one failed - a red gapcheck must not cost the day's
build - and the job exits 1 naming the stages that failed, or INCONCLUSIVE_RC naming the
ones that could not check. Three outcomes, never two: a check that did not run tells you
nothing about the data, and reporting it as either a pass or a gap sends someone hunting a
phantom (ticket 07). The standing pieces run as their own make targets, so the Makefile
stays the one place that knows JAVA_HOME, TZ=UTC and the .env credentials.

Run: make daily   (python -m raincheck.daily)
One stage: python -m raincheck.daily <stage>   - the form every task pod of the
nightly DAG runs (ticket 05), where Airflow owns the ordering this driver owns here.
One item: python -m raincheck.daily <stage> <item>   - one Service date, one feed kind:
the form a runtime that gives every item its own pod runs (ticket 06). The reduce
behind those pods takes the whole list the same way: daily gold '["2026-08-20", ...]'.
"""
import json
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from importlib import import_module
from inspect import signature
from pathlib import Path
from typing import Callable, NamedTuple
from zoneinfo import ZoneInfo

from raincheck import paths
from raincheck.paths import REPO, data_root

WINDOW_DAYS = 14  # spec K: the gap scan is bounded
# The rc a stage exits with when it COULD NOT CHECK - checks.rc()'s own third value
# (1 any row failed, else 2 any row is inconclusive, else 0). A literal and not an
# import: raincheck_stage.py READS this file (the DAG image has no raincheck package)
# and can only literal_eval what it finds. tests/test_daily.py pins it against
# checks.rc() of a real INCONCLUSIVE row, so the two cannot drift apart quietly.
INCONCLUSIVE_RC = 2  # orchestration ticket 07
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
    argv: tuple[str, ...] = () # `python -m raincheck.<argv>`: this stage as its OWN
                               # PROCESS, for a runtime that gives it a container instead
                               # of a function call (ticket 05). () means "run the make
                               # target in entrypoint". Every GATE carries one, and that is
                               # not a preference: GNU make exits 2 for ANY recipe failure,
                               # so a module rc of 1 arrives as 2 and INCONCLUSIVE stops
                               # being distinguishable from broken (orch 03, measured both
                               # ways). BOTH runtimes read it now (ticket 07): call() runs
                               # this process instead of the make target, so a gate's rc is
                               # the module's here too, and the DAG maps INCONCLUSIVE_RC to
                               # a skipped task with skip_on_exit_code. main() below reads
                               # the rc that comes back. A MAPPED stage takes one item of
                               # its axis as this form's trailing argument (ticket 06)
    reduces: str | None = None # the axis this stage rolls up ONCE, behind the pods that
                               # mapped it. A reduce is never itself mapped: a runtime that
                               # gives every item its own pod hands this stage the whole
                               # list those pods were expanded from, as its own trailing
                               # argument, and the disk says which of them landed (06)


STAGES = (
    Stage("gapfill", "make:gapfill", "transport", fanout="kind", argv=("gapfill", "fill")),
    Stage("gapverify", "make:gapverify", "gate", fanout="kind", argv=("gapfill", "verify")),
    # ticket 20: strictly after the fill
    Stage("gapcheck", "make:gapcheck", "gate", argv=("gapfill", "check")),
    Stage("coldpush", "make:coldpush", "transport"),
    Stage("coldcheck", "py:raincheck.daily:coldcheck", "gate", soft=True, argv=("daily", "coldcheck")),
    Stage("events", "py:raincheck.daily:build", "transport", fanout="service_date", argv=("daily", "events")),
    # ticket 06: the reduce that used to be the tail of build(). It is a stage of its own the
    # moment `events` can be one pod per Service date, and it is never mapped - one session
    # rolling N months beats N sessions rolling one, and the days it rolls are not its own.
    Stage("gold", "py:raincheck.daily:gold", "transport", argv=("daily", "gold"),
          reduces="service_date"),
    Stage("precip", "py:raincheck.daily:precip", "transport", fanout="month", argv=("daily", "precip")),
    Stage("prune", "py:raincheck.daily:prune_live", "transport", argv=("daily", "prune")),
    # ticket 01 left this out of the declaration because its PLACE was ticket 09's call.
    # It is here, second to last: it reads Bronze, so it stands behind every stage that
    # writes any (gapfill), and it PRODUCES a check batch, so it stands in front of the one
    # stage that reads batches. A GATE with an argv, because both of its non-verdicts are
    # INCONCLUSIVE rather than red - no date dir mixes part schemas, or this box has no JVM
    # - and `make` would flatten that 2 into the same 2 a broken recipe exits with.
    Stage("eras", "make:eras", "gate", argv=("eras",)),
    # LAST, and a GATE: it expects on the rows the stages above just wrote, so it has
    # nothing to say until they have run, and re-reading a batch cannot change a verdict.
    # The argv is not optional - `make` exits 2 for ANY recipe failure, which is the one
    # number this stage needs to mean INCONCLUSIVE (orch 03/05).
    Stage("gxcheck", "make:gxcheck", "gate", argv=("gx",)),
)

FAILED_STATES = ("failed", "upstream_failed")  # Airflow's, for report() below
# Airflow's rendering of a stage that could not check (ticket 07). A task state carries no
# rc: the operator maps the pod's own INCONCLUSIVE_RC onto `skipped` (KubernetesPodOperator's
# skip_on_exit_code), which is the only terminal state Airflow has that is neither success
# nor failure. This is a RENDERING - the persisted batch under <root>/checks/check=<name>/
# is the record.
INCONCLUSIVE_STATES = ("skipped",)
# ...and it counts as one only ON A GATE, which is where the mapping was wired (the DAG
# gives skip_on_exit_code to gates alone, for the same reason). `skipped` is ALSO what a
# zero-length dynamic expansion lands in - "there was nothing to do" (ticket 06) - so
# reading every skip as "could not check" would report a quiet morning with no service day
# to build as an inconclusive nightly, every quiet morning. Same guard on the driver's own
# rc: a gate's 2 is a verdict, but `precip` returns a make rc straight out, where 2 only
# ever means the recipe broke. Both are the conflation this ticket exists to prevent,
# pointing the other way.
GATES = frozenset(s.name for s in STAGES if s.retry == "gate")


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


def silver(root: Path, day: str) -> bool:
    """Both Silver partitions present - what makes a service day BUILT rather than a gap.
    Read forwards by gaps() (skip it) and backwards by gold() (roll its month)."""
    return all((root / "silver" / t / f"service_date={day}" / PART).exists() for t in SILVER)


def gaps(root: Path, closed: date) -> list[str]:
    """The WINDOW_DAYS closed service days ending at `closed` that have Bronze VP, are
    missing a Silver partition, and hold every Bronze hour they are built from.

    That last test is what keeps a sleep gap from freezing: `events` writes both partitions
    from whatever Bronze exists, and a day with both partitions is never revisited, so
    building one hour early buries a short day behind a green board. Deferring instead
    costs a morning - gapfill runs first, and the same scan retries every day of the
    window - and it says so out loud each time.

    This scan is a pure read of ~200 filesystem predicates per day, which on a POSIX root
    is free and on an object store is one listing each. MEASURED against raincheck-bronze
    [cloud 13]: the 14-day window is 1,960 store list calls / 231.1 s uncached. It runs
    inside `paths.cached_listing`, which is a no-op on a local root and ONE recursive
    listing on a remote one; nothing in here writes, so nothing can go stale under it."""
    out = []
    with paths.cached_listing(root):
        for n in range(WINDOW_DAYS - 1, -1, -1):
            day = (closed - timedelta(days=n)).isoformat()
            if not any((root / "archive" / "vp" / f"date={day}").glob("hour=*/*.parquet")):
                continue  # before capture, or a day we never saw at all - not ours to build
            if silver(root, day):
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


def build(root: Path, closed: date, days: list[str], service_date: str | None = None) -> None:
    """Build the gap days. One session for the lot, and no session at all when there is
    nothing to build.

    `service_date` is ONE day: the form a runtime that gives every day its own pod runs
    (ticket 06), and the reason the monthly rollup is gold() below rather than the tail of
    this function - N pods cannot share the reduce that used to sit inside the one that
    looped. `days` is the run's own record of what it set out to build; gold() rolls the
    months of the ones that landed, and in a mapped runtime the graph hands it the same
    list instead of this one."""
    todo = [service_date] if service_date else gaps(root, closed)
    print(f"daily: {len(todo)} service day(s) to build: {', '.join(todo) or '-'}", flush=True)
    if not todo:
        return
    days.extend(todo)
    from raincheck import events
    from raincheck.spark import session

    spark = session()
    failed = []
    try:
        for day in todo:
            try:
                events.leg_hours(root, spark, day)
                events.events(root, spark, day)
            except (Exception, SystemExit) as e:  # one poisoned day must not starve the newer ones
                print(f"daily: events {day} FAILED: {e}", flush=True)
                failed.append(day)
    finally:
        spark.stop()  # gold and the precip stages that follow start their own JVM
    if failed:
        raise SystemExit(f"events failed for {', '.join(failed)}")


def gold(root: Path, days: list[str]) -> None:
    """Roll the months the days that actually BUILT touch - one session, once, behind them.

    A failed day cannot pull its month into Gold, and the disk is what says so: silver() is
    the same predicate gaps() defers on, read after the fact. That is why both runtimes hand
    this the days they set out to build rather than a verdict - in a mapped one the days are
    pods, whose task states carry a map index and no Service date at all."""
    rolled = months([d for d in days if silver(root, d)])
    print(f"daily: gold rolls {len(rolled)} month(s): {', '.join(rolled) or '-'}", flush=True)
    if not rolled:
        return
    from raincheck import gold as tables
    from raincheck.spark import session

    spark = session()
    try:
        for month in rolled:
            tables.speed(root, spark, month)
            tables.route(root, spark, month)
    finally:
        spark.stop()  # the precip stages that follow start their own JVM


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


def stage(name: str, fn) -> int:
    """Run one step and return its rc in checks.rc()'s vocabulary - 0 ok, INCONCLUSIVE_RC
    could not check, anything else failed. `name` is the expanded step's name, whose first
    word is its stage's. A crash is a FAILURE and never an inconclusive: a stage that died
    told us nothing it could persist a row about."""
    t0, err = time.monotonic(), None
    try:
        rc = fn() or 0
    except (Exception, SystemExit) as e:  # a module's own loud exit ends its stage, not the job
        rc, err = 1, e
    if rc == INCONCLUSIVE_RC and name.split()[0] not in GATES:
        rc = 1   # only a GATE's rc is a verdict; precip hands back a make rc, whose 2 only
                 # ever means the recipe broke. Collapsed HERE so the line and the summary
                 # cannot say different things about the same stage.
    label = "ok" if not rc else ("INCONCLUSIVE" if rc == INCONCLUSIVE_RC else "FAILED")
    print(f"daily: {name} {label} in {time.monotonic() - t0:.0f}s"
          + (f" - {err}" if err else ""), flush=True)
    return rc


def resolve(ref: str) -> Callable:
    """`<module>:<callable>`, looked up per call - tests and the DAG replace these
    attributes, so a reference captured at import time would run the wrong function."""
    mod, _, attr = ref.rpartition(":")
    return getattr(import_module(mod), attr)


def axis_items(axis: str, root: Path, now: datetime) -> list[str]:
    """The items ONE declared fanout axis expands to. The single home for that question:
    `make daily` expands precip's months from here, and the DAG's plan pod (ticket 06)
    prints these for Airflow to hand one pod each."""
    # Imported per axis and not up front: this runs on the way into EVERY `make daily`, and
    # gapfill pulls pyarrow and fsspec behind it for a list of five strings.
    return {"kind": lambda: list(import_module("raincheck.gapfill").KINDS),
            "service_date": lambda: gaps(root, closed_through(now)),
            "month": lambda: precip_months(now.date())}[axis]()


def plan(axis: str, out: str | None = None) -> None:
    """The items a MAPPING runtime expands one stage's axis over, as JSON.

    Not a stage: it is the answer to "how many pods", and only a pod can answer it - the
    scan is a read of the data root, which no scheduler has. Airflow can expand a task only
    over an XCom, and a pod's only XCom is the file the operator's sidecar reads back, so
    the graph hands this the path to write and takes the list from there (ticket 06)."""
    items = axis_items(axis, data_root(), datetime.now(timezone.utc))
    print(f"daily: plan {axis} - {len(items)} item(s): {', '.join(items) or '-'}", flush=True)
    if out:
        Path(out).write_text(json.dumps(items))
    else:
        print(json.dumps(items), flush=True)
def spawn(argv: tuple[str, ...]) -> int:
    """This stage as its OWN PROCESS, the way a task pod runs it - `python -m raincheck.<argv>`
    on this interpreter, in the repo, inheriting the env `make daily` exported."""
    print(f"daily: + python -m raincheck.{argv[0]} {' '.join(argv[1:])}", flush=True)
    return subprocess.call([sys.executable, "-m", f"raincheck.{argv[0]}", *argv[1:]], cwd=REPO)


def call(s: Stage, ctx: dict):
    """Run one stage's entrypoint, handing it only the ctx values its own signature names.
    That binding is why the runtime below dispatches without naming a single stage.

    EVERY rc that leaves here is the MODULE's own number, which is what lets main() below
    read INCONCLUSIVE_RC as a verdict rather than as a broken recipe (ticket 07):

      a stage with an `argv` runs that process, so its rc is the module's - and a GATE
      always carries one, because GNU make exits 2 for ANY recipe failure and a gate
      reached through make cannot say "could not check" apart from "broke" (orch 03,
      measured both ways). The DAG's task pods run exactly this command; now so does this
      runtime, so the two cannot disagree about a verdict either.

      a bare make target's rc is NOT the module's, so its 2 is collapsed to 1 here. It
      means "some recipe failed", and reading it as INCONCLUSIVE is that conflation
      inverted - a broken transport stage reported as a check that could not run.
    """
    kind, _, ref = s.entrypoint.partition(":")
    if kind == "make":
        # a make target takes one axis item as the axis's OWN make variable; the module
        # form (argv) takes it as a trailing argument (ticket 06) - and a stage that has an
        # argv runs THAT process here, so its rc is the module's own (ticket 07), which is
        # also exactly the command its task pod runs
        item = ctx.get(s.fanout) if s.fanout else None
        if s.argv:
            return spawn(s.argv + ((item,) if item else ()))
        return 1 if run(ref, **({s.fanout.upper(): item} if item else {})) else 0
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


def verdict(failed: list[str], inconclusive: list[str] = ()) -> None:
    """The job's last line, and the ONE place it is written. `make daily` exits with it
    after running the stages itself; the DAG's report task prints the SAME sentence from
    Airflow's own record of a run whose stages were pods. Two copies of it is how the two
    runtimes start disagreeing about what a nightly failure reads like.

    THREE outcomes, counted apart, and the exit code is checks.rc()'s own rule - 1 if
    anything failed, else INCONCLUSIVE_RC if anything could not check, else 0 (ticket 07).
    A real gap outranks a not-run check, so an inconclusive beside a failure still exits 1
    and its names are still printed; neither list is ever inflated by the other. A run that
    only could not check must not exit like a run that broke - that is the conflation five
    incidents bought the rule against - and it must not exit 0 either."""
    if inconclusive:
        print(f"daily: INCONCLUSIVE - {', '.join(inconclusive)} (could not check; nothing is "
              "known about that data either way - the rows under <root>/checks/ are the "
              "record, and this line is only a rendering of them)", flush=True)
    if failed:
        sys.exit(f"daily: FAILED - {', '.join(failed)} (every stage ran; see above)")
    if inconclusive:
        sys.exit(INCONCLUSIVE_RC)
    print("daily: OK", flush=True)


def report(crumbs: str) -> None:
    """The nightly DAG's last task (ticket 05): this driver's own ending, rebuilt from the
    run's finished task states.

    A pod cannot see the run it belongs to, and a callable in the DAG file would be a stage
    running inside the scheduler on the floor (orch 04) - so Airflow renders
    `ti.get_task_breadcrumbs()` into this argument: one JSON object per finished task,
    carrying its state and its duration, which is exactly what stage() prints here.

    Lines come out in DECLARED order, the order this driver prints them in. A task id the
    declaration does not name keeps its own place at the end, and a mapped index (ticket
    06) prints beside its stage the way steps() names an expanded step. A SOFT stage never
    joins the failed list, for the same reason it does not here."""
    order = {s.name: i for i, s in enumerate(STAGES)}
    soft = {s.name for s in STAGES if s.soft}
    rows = sorted(json.loads(crumbs),
                  key=lambda r: (order.get(r["task_id"], len(order)), r["task_id"],
                                 r.get("map_index", -1)))
    failed, inconclusive = [], []
    for r in rows:
        name = r["task_id"] if r.get("map_index", -1) < 0 else f"{r['task_id']} {r['map_index']}"
        broke = r["state"] in FAILED_STATES
        # `state` and not "ok" for anything that neither succeeded nor failed: ticket 07
        # renders INCONCLUSIVE as a skip, and a skip printed as ok is the one rendering
        # five incidents bought the rule against.
        outcome = "FAILED" if broke else ("ok" if r["state"] == "success" else r["state"])
        print(f"daily: {name} {outcome} in {r.get('duration') or 0:.0f}s", flush=True)
        if r["task_id"] in soft:
            continue
        if broke:
            failed.append(name)
        elif r["state"] in INCONCLUSIVE_STATES and r["task_id"] in GATES:
            inconclusive.append(name)
    verdict(failed, inconclusive)


def main(argv: list[str] | None = None) -> None:
    """No argument: the whole nightly, as launchd has always run it. One stage name: that
    stage alone, expanded over its axes exactly as it would be here, exiting on ITS
    outcome - which is what a scheduler that owns the ordering needs, and what every task
    pod in the nightly DAG runs."""
    args = list(argv or [])
    if args and args[0] == "report":       # not a stage: the DAG's ending, from Airflow
        return report(args[1])
    if args and args[0] == "plan":         # nor is this: how many pods one axis is worth
        return plan(*args[1:])
    root, now = data_root(), datetime.now(timezone.utc)
    # Every declared axis starts unbound - steps() binds the ones THIS runtime supplies, and
    # a stage whose axis nobody supplied fans out inside itself exactly as it always has.
    ctx = {"root": root, "closed": closed_through(now), "days": [],
           **{s.fanout: None for s in STAGES if s.fanout}}
    # MRMS months are UTC, unlike the service day above
    axes = {"month": axis_items("month", root, now)}
    if len(args) > 1:
        # A runtime that gives a stage a container of its own hands it its own share of the
        # work: ONE item of the axis it maps over, or - for the reduce standing behind those
        # containers - the whole list they were expanded from.
        one = next((s for s in STAGES if s.name == args[0]), None)
        if one and one.fanout:
            axes[one.fanout] = [args[1]]
        elif one and one.reduces:
            ctx["days"] = json.loads(args[1])
    todo = steps(ctx, axes)
    if args:
        todo = [s for s in todo if s[0] == args[0] or s[0].startswith(f"{args[0]} ")]
        if not todo:
            sys.exit(f"daily: {args[0]} is not a declared stage "
                     f"({', '.join(s.name for s in STAGES)})")
    failed, inconclusive = [], []
    for name, fn, soft in todo:
        rc = stage(name, fn)
        if not rc or soft:       # a soft stage joins neither list, exactly as in report()
            continue
        (inconclusive if rc == INCONCLUSIVE_RC else failed).append(name)
    verdict(failed, inconclusive)


if __name__ == "__main__":
    main(sys.argv[1:])
