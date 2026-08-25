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


def stub_stages(monkeypatch, made: list, rc=lambda name: 0) -> None:
    """Stub BOTH seams a stage reaches the outside through, recording each under the STAGE's
    own name: `run` is the make target, and `spawn` is the module a GATE runs as its own
    process (ticket 07 - GNU make exits 2 for any recipe failure, so a gate reached through
    make cannot report INCONCLUSIVE apart from broken). A test that stubs only `run` shells
    out for real on every gate."""
    by_argv = {s.argv: s.name for s in daily.STAGES if s.argv}
    monkeypatch.setattr(daily, "run", lambda target, **var: made.append(target) or rc(target))
    monkeypatch.setattr(daily, "spawn", lambda argv: (lambda name: made.append(name) or rc(name))(
        by_argv[tuple(argv)]))


@pytest.fixture()
def stubs(monkeypatch):
    """Record the stages instead of shelling out / starting a JVM."""
    made, days = [], []
    stub_stages(monkeypatch, made)
    monkeypatch.setattr(daily, "build", lambda root, closed: days.extend(daily.gaps(root, closed)))
    return made, days


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


def test_a_red_stage_still_leaves_the_job_running_and_exits_1(seeded, monkeypatch):
    days = []
    monkeypatch.setattr(daily, "build", lambda root, closed: days.extend(daily.gaps(root, closed)))
    stub_stages(monkeypatch, [], lambda name: int(name == "gapcheck"))
    with pytest.raises(SystemExit, match="gapcheck"):
        daily.main()
    assert days == [day(2), day(0)]  # the newest day or two fail gapcheck every morning


def test_coldcheck_repushes_once_then_warns(seeded, monkeypatch, capsys):
    """Mismatches that survive a re-push are the box's overlapping capture (19), not loss."""
    made = []
    monkeypatch.setattr(daily, "build", lambda root, closed: None)
    stub_stages(monkeypatch, made, lambda name: int(name == "coldcheck"))
    daily.main()  # exits 0: coldcheck never fails the job
    assert made.count("coldcheck") == 2 and made.count("coldpush") == 2
    assert "coldgaps" in capsys.readouterr().out  # the loss check the warning points at


def test_a_poisoned_day_is_skipped_and_gold_rolls_only_the_built_months(tmp_path, monkeypatch):
    """build()'s own loop, on two gap days either side of a month end: the loud day is
    caught so the newer one still builds, gold rolls only the month that built, the
    session is released for the precip stages, and the job still ends red."""
    import sys
    import types

    import raincheck

    bad, good = "2026-06-30", "2026-07-01"
    for d in (bad, good):
        seed_service_day(tmp_path, d)
    calls, stopped = [], []

    def events(_root, _spark, d):
        calls.append(("events", d))
        if d == bad:
            sys.exit(f"events {d}: no Bronze VP")  # events.py's own loud exit

    monkeypatch.setattr(raincheck, "events", types.SimpleNamespace(
        leg_hours=lambda _r, _s, d: calls.append(("leg_hours", d)), events=events), raising=False)
    monkeypatch.setattr(raincheck, "gold", types.SimpleNamespace(
        speed=lambda _r, _s, m: calls.append(("speed", m)),
        route=lambda _r, _s, m: calls.append(("route", m))), raising=False)
    monkeypatch.setitem(sys.modules, "raincheck.spark", types.SimpleNamespace(
        session=lambda: types.SimpleNamespace(stop=lambda: stopped.append("stopped"))))

    with pytest.raises(SystemExit, match=bad):
        daily.build(tmp_path, date.fromisoformat(good))
    assert ("leg_hours", good) in calls  # the newer day built after the older one blew up
    assert [c for c in calls if c[0] in ("speed", "route")] == [("speed", "2026-07"),
                                                                ("route", "2026-07")]
    assert stopped == ["stopped"]


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
    """main()'s printed lines, in order: every declared stage once, precip expanded per
    month - the only axis this runtime maps."""
    root, _ = seeded
    months = daily.precip_months(NOW.date())
    names = [name for name, _fn, _soft in daily.steps({"root": root, "closed": CLOSED},
                                                      {"month": months})]
    assert names == ["gapfill", "gapverify", "gapcheck", "coldpush", "coldcheck", "events",
                     *[f"precip {m}" for m in months], "prune"]


def test_a_soft_stage_that_fails_does_not_fail_the_job(seeded, monkeypatch):
    """coldcheck is soft in the declaration, not just by returning 0 from inside itself."""
    monkeypatch.setattr(daily, "build", lambda root, closed: None)
    stub_stages(monkeypatch, [])
    monkeypatch.setattr(daily, "coldcheck", lambda: 1)
    daily.main()  # no SystemExit


# --- the third outcome (orchestration ticket 07) ---------------------------------------
#
# A check that could not run tells you nothing about the data. Reporting that as a pass
# hides a real gap and reporting it as a failure sends someone hunting a phantom, so the
# driver counts it apart and exits apart. The pinned property is a NEGATIVE one: no path
# through here renders INCONCLUSIVE as failed, and none renders it as ok.


def test_the_inconclusive_rc_is_the_check_vocabularys_own_number():
    """`INCONCLUSIVE_RC` is a literal in the declaration because raincheck_stage.py READS
    that file (the DAG image has no raincheck package to import from). Derived here from a
    real Row through checks.rc() rather than compared to a 2, so the copy cannot drift:
    move the rule in checks.py and this goes red instead of the nightly going quiet."""
    from raincheck import checks

    could_not = checks.Row("gapverify", "vp", checks.INCONCLUSIVE, "no pair to compare")
    a_gap = checks.Row("gapcheck", "vp 2026-08-15", checks.FAIL, "3 hours missing")
    assert daily.INCONCLUSIVE_RC == checks.rc([could_not])
    assert daily.INCONCLUSIVE_RC != checks.rc([a_gap]) != checks.rc([])
    # and a batch that could not check does not become a gap by standing next to one
    assert checks.rc([could_not, a_gap]) == checks.rc([a_gap])


def test_a_gate_that_could_not_check_exits_apart_from_one_that_found_a_gap(capsys):
    """The whole ticket in one assertion: three rcs in, three different endings out."""
    ends = {}
    for rc, names in ((0, ([], [])), (1, (["gapcheck"], [])), (2, ([], ["gapverify"]))):
        try:
            daily.verdict(*names)
            ends[rc] = 0
        except SystemExit as e:
            ends[rc] = 1 if isinstance(e.code, str) else e.code
    assert ends == {0: 0, 1: 1, 2: daily.INCONCLUSIVE_RC}
    assert len(set(ends.values())) == 3


def test_an_inconclusive_beside_a_failure_is_still_a_failure_and_still_named(capsys):
    """checks.rc()'s own precedence: a real gap outranks a not-run check. But the exit
    line must not swallow the names - neither list is inflated by the other."""
    with pytest.raises(SystemExit) as exit:
        daily.verdict(["gapcheck"], ["gapverify"])
    assert str(exit.value) == "daily: FAILED - gapcheck (every stage ran; see above)"
    out = capsys.readouterr().out
    assert "INCONCLUSIVE - gapverify" in out and "gapcheck" not in out


def test_a_gate_runs_its_module_so_make_cannot_flatten_its_verdict(monkeypatch):
    """GNU make exits 2 for ANY recipe failure (orch 03, measured), so a gate reached
    through `make` reports a module rc of 1 as 2. Every gate declares the same argv its
    task pod runs, and this runtime runs THAT - which is what makes the rc below a
    verdict rather than "some recipe broke"."""
    spawned = []
    monkeypatch.setattr(daily, "spawn", lambda argv: spawned.append(argv) or 2)
    monkeypatch.setattr(daily, "run", lambda t, **v: pytest.fail(f"{t} reached through make"))
    gate = next(s for s in daily.STAGES if s.name == "gapverify")
    assert daily.call(gate, {}) == daily.INCONCLUSIVE_RC
    assert spawned == [("gapfill", "verify")]
    for s in daily.STAGES:
        if s.retry == "gate":
            assert s.argv, f"{s.name} is a gate with no process form"


def test_a_bare_make_targets_two_is_a_broken_recipe_and_never_an_inconclusive(monkeypatch):
    """The conflation inverted, and the one this rendering could newly cause. A transport
    stage has no argv and goes through make, whose 2 means "a recipe failed" - reading it
    as "could not check" would file a broken gapfill as a quiet morning."""
    monkeypatch.setattr(daily, "run", lambda target, **var: 2)
    transport = next(s for s in daily.STAGES if s.entrypoint.startswith("make:") and not s.argv)
    assert daily.call(transport, {}) == 1


def test_the_job_counts_a_gate_that_could_not_check_apart_from_a_failure(seeded, monkeypatch):
    """End to end through main(): a gate exiting 2 lands in the inconclusive list, exits
    with INCONCLUSIVE_RC and never appears as FAILED."""
    root, _ = seeded
    monkeypatch.setattr(daily, "build", lambda root, closed: None)
    monkeypatch.setattr(daily, "precip", lambda month: 0)
    stub_stages(monkeypatch, [], lambda name: daily.INCONCLUSIVE_RC * (name == "gapverify"))
    with pytest.raises(SystemExit) as exit:
        daily.main()
    assert exit.value.code == daily.INCONCLUSIVE_RC


def test_a_py_stage_that_returns_a_make_rc_is_a_failure_and_never_an_inconclusive(
        seeded, monkeypatch, capsys):
    """`precip` hands back `run()`'s rc unchanged, and GNU make exits 2 for ANY recipe
    failure - so a broken precip arrives looking exactly like a gate that could not check.
    Only a declared GATE's 2 is a verdict; everything else's is a failure."""
    root, _ = seeded
    monkeypatch.setattr(daily, "build", lambda root, closed: None)
    stub_stages(monkeypatch, [], lambda name: 0)
    monkeypatch.setattr(daily, "run", lambda target, **var: 2 * target.startswith("precip"))
    with pytest.raises(SystemExit) as exit:
        daily.main()
    assert "daily: FAILED - precip" in str(exit.value)
    assert "INCONCLUSIVE" not in capsys.readouterr().out
