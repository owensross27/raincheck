"""Ticket 15: the daily catch-up driver - which days it picks, what it leaves alone, and
the stage order the scheduling note pins. JVM-free: the standing make targets and the
Spark build are stubbed, and `prune` runs for real against seeded live dirs."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from raincheck import daily

NOW = datetime.now(timezone.utc)
CLOSED = daily.closed_through(NOW)  # the newest service day the driver may build


def day(n: int) -> str:
    """n days before the newest closed service day."""
    return (CLOSED - timedelta(days=n)).isoformat()


def seed_bronze(root: Path, d: str, hours=range(24)) -> None:
    for h in hours:
        hour = root / "archive" / "vp" / f"date={d}" / f"hour={h:02d}"
        hour.mkdir(parents=True, exist_ok=True)
        (hour / "part-00.parquet").write_bytes(b"bronze")


def seed_service_day(root: Path, d: str) -> None:
    """Every Bronze hour service day d is built from: all of D, and D+1's tail."""
    seed_bronze(root, d)
    seed_bronze(root, (date.fromisoformat(d) + timedelta(days=1)).isoformat(),
                range(daily.TAIL_H))


def seed_silver(root: Path, d: str) -> list[Path]:
    parts = []
    for table in daily.SILVER:
        part = root / "silver" / table / f"service_date={d}" / daily.PART
        part.parent.mkdir(parents=True)
        part.write_bytes(b"built")
        parts.append(part)
    return parts


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    """Two closed days with Bronze and no Silver, one neighbour already built."""
    monkeypatch.setenv("RAINCHECK_ARCHIVE_ROOT", str(tmp_path))
    for n in (2, 1, 0):
        seed_service_day(tmp_path, day(n))
    built = seed_silver(tmp_path, day(1))
    return tmp_path, built


@pytest.fixture()
def stubs(monkeypatch):
    """Record the make targets and the built days instead of shelling out / starting a JVM.
    The stub keeps build()'s contract: it fills the run's `days` record, which is what the
    rollup behind it reads (ticket 06)."""
    made, built = [], []

    def build(root, closed, days, service_date=None):
        found = [service_date] if service_date else daily.gaps(root, closed)
        days.extend(found)
        built.extend(found)

    monkeypatch.setattr(daily, "run", lambda target, **var: made.append(target) or 0)
    monkeypatch.setattr(daily, "build", build)
    return made, built


@pytest.mark.parametrize("stamp, closed", [
    ("2026-08-24T10:00", "2026-08-23"),  # the 06:00 EDT run: yesterday is closed
    ("2026-01-15T11:00", "2026-01-14"),  # the same run in EST, the other DST regime
    ("2026-08-25T01:00", "2026-08-23"),  # woken 21:00 EDT: the 24th is still on the road
    ("2026-08-24T06:00", "2026-08-22"),  # woken 02:00 EDT: yesterday's tail is still out
])
def test_closed_service_day_follows_the_local_clock(stamp, closed):
    now = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
    assert daily.closed_through(now).isoformat() == closed


def test_gaps_are_the_bronze_days_without_silver(seeded):
    root, _ = seeded
    assert daily.gaps(root, CLOSED) == [day(2), day(0)]


def test_gaps_are_bounded_and_exclude_the_open_day(tmp_path):
    seed_service_day(tmp_path, day(daily.WINDOW_DAYS))      # one day older than the window
    seed_service_day(tmp_path, day(-1))                     # the day still running
    seed_service_day(tmp_path, day(daily.WINDOW_DAYS - 1))  # the oldest day in the window
    assert daily.gaps(tmp_path, CLOSED) == [day(daily.WINDOW_DAYS - 1)]


def test_a_day_short_of_bronze_is_deferred_not_frozen_short(seeded, capsys):
    """A sleep gap in D+1's small hours is a third of the service day; building it early
    would write a short Silver partition that nothing ever revisits."""
    root, _ = seeded
    tail = root / "archive" / "vp" / f"date={day(-1)}" / "hour=03"
    for part in tail.glob("*.parquet"):
        part.unlink()
    assert daily.gaps(root, CLOSED) == [day(2)]  # day(0) waits for its tail
    assert f"{day(-1)}T03" in capsys.readouterr().out

    (tail / "_gapfill").touch()  # the next morning's fill lands it
    assert daily.gaps(root, CLOSED) == [day(2), day(0)]


def test_half_built_day_is_still_a_gap(seeded):
    """leg_hours without events (a run killed between the two writes) rebuilds."""
    root, built = seeded
    next(p for p in built if "events" in str(p)).unlink()
    assert day(1) in daily.gaps(root, CLOSED)


def test_builds_exactly_the_gaps_and_leaves_the_neighbour_alone(seeded, stubs):
    _, built = seeded
    made, days = stubs
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in built]
    daily.main()
    assert days == [day(2), day(0)]
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in built] == before
    assert "coldpush" in made


def test_second_run_the_same_day_builds_nothing(seeded, stubs):
    root, _ = seeded
    _, days = stubs
    daily.main()
    for d in days:  # the first run's builds landed
        seed_silver(root, d)
    days.clear()
    daily.main()
    assert days == []


def test_gapfill_runs_before_gapcheck(seeded, stubs):
    """Ticket 20's scheduling note: checking before filling reports gaps the fill closes."""
    made, _ = stubs
    daily.main()
    assert made.index("gapfill") < made.index("gapcheck")


def test_a_red_stage_still_leaves_the_job_running_and_exits_1(seeded, stubs, monkeypatch):
    made, built = stubs
    monkeypatch.setattr(daily, "run", lambda target, **var: made.append(target) or
                        int(target == "gapcheck"))
    with pytest.raises(SystemExit, match="gapcheck"):
        daily.main()
    assert built == [day(2), day(0)]  # the newest day or two fail gapcheck every morning


def test_coldcheck_repushes_once_then_warns(seeded, monkeypatch, capsys):
    """Mismatches that survive a re-push are the box's overlapping capture (19), not loss."""
    made = []
    monkeypatch.setattr(daily, "build", lambda root, closed, days, service_date=None: None)
    monkeypatch.setattr(daily, "run", lambda target, **var: made.append(target) or
                        int(target == "coldcheck"))
    daily.main()  # exits 0: coldcheck never fails the job
    assert made.count("coldcheck") == 2 and made.count("coldpush") == 2
    assert "coldgaps" in capsys.readouterr().out  # the loss check the warning points at


BAD, GOOD = "2026-06-30", "2026-07-01"   # two gap days either side of a month end


@pytest.fixture()
def jvm_free(monkeypatch):
    """events, gold and the session factory as recorders: (calls, stopped). BAD blows up
    the way events.py does, with its own loud exit."""
    import sys
    import types

    import raincheck

    calls, stopped = [], []

    def events(_root, _spark, d):
        calls.append(("events", d))
        if d == BAD:
            sys.exit(f"events {d}: no Bronze VP")  # events.py's own loud exit

    monkeypatch.setattr(raincheck, "events", types.SimpleNamespace(
        leg_hours=lambda _r, _s, d: calls.append(("leg_hours", d)), events=events), raising=False)
    monkeypatch.setattr(raincheck, "gold", types.SimpleNamespace(
        speed=lambda _r, _s, m: calls.append(("speed", m)),
        route=lambda _r, _s, m: calls.append(("route", m))), raising=False)
    monkeypatch.setitem(sys.modules, "raincheck.spark", types.SimpleNamespace(
        session=lambda: types.SimpleNamespace(stop=lambda: stopped.append("stopped"))))
    return calls, stopped


def test_a_poisoned_day_is_skipped_and_the_job_still_ends_red(tmp_path, jvm_free):
    """build()'s own loop: the loud day is caught so the newer one still builds, the run
    records BOTH as attempted (the rollup decides from the disk, not from this list), the
    session is released for the stages that follow, and the job still ends red."""
    calls, stopped = jvm_free
    for d in (BAD, GOOD):
        seed_service_day(tmp_path, d)
    days = []

    with pytest.raises(SystemExit, match=BAD):
        daily.build(tmp_path, date.fromisoformat(GOOD), days)
    assert ("leg_hours", GOOD) in calls  # the newer day built after the older one blew up
    assert days == [BAD, GOOD]
    assert not [c for c in calls if c[0] in ("speed", "route")]  # the rollup is a stage now
    assert stopped == ["stopped"]


def test_one_service_date_is_the_whole_of_a_mapped_build(tmp_path, jvm_free):
    """Ticket 06: the form one pod per Service date runs. It builds THAT day and never
    scans - the graph already decided which days there are - and the day it built is what
    it records."""
    calls, _ = jvm_free
    for d in (BAD, GOOD):
        seed_service_day(tmp_path, d)
    days = []

    daily.build(tmp_path, date.fromisoformat(GOOD), days, service_date=GOOD)
    assert [c for c in calls if c[0] == "events"] == [("events", GOOD)]
    assert days == [GOOD]


def test_gold_rolls_only_the_months_the_days_that_landed_touch(tmp_path, jvm_free):
    """The acceptance row: a failed day cannot pull its month into Gold. Both days were
    planned and only the newer one has Silver, so only its month rolls - and that answer
    comes from the disk, which is the only place a mapped runtime can get it (a finished
    task's record carries a map index, never a Service date)."""
    calls, stopped = jvm_free
    seed_silver(tmp_path, GOOD)

    daily.gold(tmp_path, [BAD, GOOD])
    assert [c for c in calls if c[0] in ("speed", "route")] == [("speed", "2026-07"),
                                                                ("route", "2026-07")]
    assert stopped == ["stopped"]  # released for the precip stages that follow


def test_gold_starts_no_session_when_nothing_landed(tmp_path, jvm_free):
    """A morning with nothing to build must not pay for a JVM - and neither must a night
    where every planned day failed."""
    calls, stopped = jvm_free
    daily.gold(tmp_path, [])
    daily.gold(tmp_path, [BAD])          # planned, never built: no Silver, no month
    assert calls == [] and stopped == []


def test_precip_rebuilds_the_month_just_ended_on_the_first():
    first = NOW.date().replace(day=1)
    assert daily.precip_months(first) == daily.months(
        [str(first - timedelta(days=1)), str(first)])
    assert daily.precip_months(first + timedelta(days=1)) == [f"{first:%Y-%m}"]


def test_prune_drops_live_hours_past_the_horizon(seeded, stubs):
    root, _ = seeded
    utc_today = NOW.date()
    old = root / "live" / "vp" / f"date={utc_today - timedelta(days=3)}" / "hour=00"
    fresh = root / "live" / "vp" / f"date={utc_today}" / "hour=00"
    for d in (old, fresh):
        d.mkdir(parents=True)
        (d / "part-00000.parquet").write_bytes(b"live")
    daily.main()
    assert not old.exists() and fresh.exists()


# Orchestration ticket 01: the stage contract is one declaration both runtimes read.


def test_every_declared_stage_resolves_to_an_entrypoint():
    """A stage naming a target or callable that does not exist is a dangling stage - it
    would fail at 06:00 in the driver, or at import in the DAG."""
    import re

    makefile = (daily.REPO / "Makefile").read_text()
    for s in daily.STAGES:
        kind, _, ref = s.entrypoint.partition(":")
        if kind == "make":
            assert re.search(rf"^{ref}:", makefile, re.M), f"{s.name}: no make target {ref}"
        else:
            assert callable(daily.resolve(ref)), f"{s.name}: {ref} is not callable"


def test_the_declaration_pins_gapfill_before_gapcheck():
    """The same scheduling note as above, read off the declaration so it covers the DAG
    too: checking before filling reports gaps the fill closes."""
    order = [s.name for s in daily.STAGES]
    assert order.index("gapfill") < order.index("gapcheck")


def test_the_driver_names_its_steps_from_the_declaration(seeded):
    """main()'s printed lines, in order: every declared stage once, in declared order,
    expanded ONLY over the axes this runtime supplies items for - here just precip's
    months. Asserted as that property rather than as a copy of the list: the declaration
    grows (ticket 06 added the rollup) and a literal here is a second declaration to keep
    in step with the first."""
    root, _ = seeded
    months = daily.precip_months(NOW.date())
    names = [name for name, _fn, _soft in daily.steps({"root": root, "closed": CLOSED},
                                                      {"month": months})]
    want = []
    for s in daily.STAGES:
        want += [f"{s.name} {m}" for m in months] if s.fanout == "month" else [s.name]
    assert names == want


def test_a_soft_stage_that_fails_does_not_fail_the_job(seeded, monkeypatch):
    """coldcheck is soft in the declaration, not just by returning 0 from inside itself."""
    monkeypatch.setattr(daily, "build", lambda root, closed, days, service_date=None: None)
    monkeypatch.setattr(daily, "run", lambda target, **var: 0)
    monkeypatch.setattr(daily, "coldcheck", lambda: 1)
    daily.main()  # no SystemExit


# Orchestration ticket 06: the axes a runtime may map, and the reduce that stands behind
# the pods it bought.


def test_every_declared_axis_can_name_its_items(seeded):
    """A fanout nothing can expand is a stage the DAG maps over nothing at all, at 06:00.
    Every declared axis - and every axis a reduce rolls up - resolves here instead."""
    root, _ = seeded
    axes = {s.fanout for s in daily.STAGES if s.fanout}
    assert axes == {"kind", "service_date", "month"}
    for axis in axes:
        assert daily.axis_items(axis, root, NOW), f"{axis} expands to nothing"
    for s in daily.STAGES:
        assert not s.reduces or s.reduces in axes, f"{s.name} reduces a non-axis"
        assert not (s.reduces and s.fanout), f"{s.name} is both a reduce and mappable"


def test_the_plan_is_the_list_and_lands_where_a_pod_can_hand_it_back(seeded, capsys, tmp_path):
    """The only channel a pod has: the operator reads one file back out of it. The same
    list goes to stdout for a human, and the file is JSON and nothing else."""
    root, _ = seeded
    out = tmp_path / "return.json"
    daily.plan("service_date", str(out))
    import json
    assert json.loads(out.read_text()) == daily.gaps(root, CLOSED) == [day(2), day(0)]
    assert "plan service_date - 2 item(s)" in capsys.readouterr().out


def test_the_one_item_form_runs_that_item_and_nothing_else(seeded, monkeypatch, capsys):
    """`python -m raincheck.daily <stage> <item>` is what ONE mapped pod runs: the stage's
    own axis bound to that item, named the way an expanded step is named."""
    root, _ = seeded
    ran = []
    monkeypatch.setattr(daily, "run", lambda target, **var: ran.append((target, var)) or 0)
    monkeypatch.setattr(daily, "build",
                        lambda root, closed, days, service_date=None: ran.append(service_date))

    daily.main(["events", day(2)])
    assert ran == [day(2)]
    ran.clear()
    daily.main(["gapfill", "vp"])            # a make target takes its item as ITS variable
    assert ran == [("gapfill", {"KIND": "vp"})]
    assert "daily: gapfill vp ok" in capsys.readouterr().out


def test_the_reduce_takes_the_list_its_pods_were_expanded_from(seeded, monkeypatch):
    """The other half of the same argument: a stage that reduces an axis is handed the
    whole list, as JSON, and is never itself expanded."""
    root, _ = seeded
    rolled = []
    monkeypatch.setattr(daily, "run", lambda target, **var: 0)
    monkeypatch.setattr(daily, "gold", lambda root, days: rolled.extend(days))

    daily.main(["gold", '["2026-08-20", "2026-08-21"]'])
    assert rolled == ["2026-08-20", "2026-08-21"]
