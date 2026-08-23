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


def seed_bronze(root: Path, d: str) -> None:
    hour = root / "archive" / "vp" / f"date={d}" / "hour=12"
    hour.mkdir(parents=True)
    (hour / "part-00.parquet").write_bytes(b"bronze")


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
        seed_bronze(tmp_path, day(n))
    built = seed_silver(tmp_path, day(1))
    return tmp_path, built


@pytest.fixture()
def stubs(monkeypatch):
    """Record the make targets and the built days instead of shelling out / starting a JVM."""
    made, days = [], []
    monkeypatch.setattr(daily, "run", lambda target, **var: made.append(target) or 0)
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
    seed_bronze(tmp_path, day(daily.WINDOW_DAYS))      # one day older than the window
    seed_bronze(tmp_path, day(-1))                     # the service day still running
    seed_bronze(tmp_path, day(daily.WINDOW_DAYS - 1))  # the oldest day in the window
    assert daily.gaps(tmp_path, CLOSED) == [day(daily.WINDOW_DAYS - 1)]


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
    monkeypatch.setattr(daily, "run", lambda target, **var: int(target == "gapcheck"))
    with pytest.raises(SystemExit, match="gapcheck"):
        daily.main()
    assert days == [day(2), day(0)]  # the newest day or two fail gapcheck every morning


def test_coldcheck_repushes_once_then_warns(seeded, monkeypatch, capsys):
    """Mismatches that survive a re-push are the box's overlapping capture (19), not loss."""
    made = []
    monkeypatch.setattr(daily, "build", lambda root, closed: None)
    monkeypatch.setattr(daily, "run", lambda target, **var: made.append(target) or
                        int(target == "coldcheck"))
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
        seed_bronze(tmp_path, d)
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
