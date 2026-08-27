"""Cloud ticket 05: the live path's supervised cycle.

The module owns three things and nothing else - the cadence, the failure policy, and the
log line - so those are what is pinned here. The export SQL, the detector's parsing and
the publisher's ordering are tested where they live (test_live.py, test_flood_live.py,
test_publish.py) and are not re-tested through this seam.

No network and no data root: the detector and the publisher are substituted, and
`live_export.once()` runs against an empty tmp root, which is its designed
"read failed -> stale meta" path and needs nothing on disk.
"""
from datetime import datetime, timedelta, timezone

import pytest

from raincheck import duck, live_loop, publish

NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def con():
    return duck.connect()


def run(con, tmp_path, monkeypatch, detector=None, publisher=None, times=(NOW,)):
    """Cycle over `times`, recording what the detector and publisher were asked."""
    calls = {"detect": [], "publish": []}

    def fake_live(margins=None):
        calls["detect"].append(margins)
        return detector() if callable(detector) else {"coastal": {"stage": "quiet"},
                                                      "winter": {"status": "ok"}}

    def fake_publish(name, src=None, **kw):
        calls["publish"].append((name, src))
        return publisher() if callable(publisher) else [1, 2]

    monkeypatch.setattr(live_loop.flood_live, "live", fake_live)
    monkeypatch.setattr(live_loop.publish, "publish", fake_publish)
    state = {}
    states = []
    for now in times:
        state = live_loop.cycle(con, tmp_path, tmp_path / "web", "live", state, now)
        states.append(state)
    return states, calls


def test_every_cycle_exports_and_publishes(con, tmp_path, monkeypatch):
    """The 30 s cadence is the export and the publish. Both, every tick, in that order."""
    states, calls = run(con, tmp_path, monkeypatch, times=[NOW, NOW + timedelta(seconds=30)])
    assert len(calls["publish"]) == 2
    assert [s["publish"] for s in states] == ["published 2", "published 2"]
    # T14 rule 3, flowing through this loop unchanged: a tick that could not READ writes
    # meta.json with error + stale and leaves live.geojson ALONE. The root here is empty,
    # so that is the path taken - a dead exporter must look stale, never absent, never
    # fresh, and this loop must not "helpfully" write an empty fleet over the last good one.
    assert (tmp_path / "web" / "meta.json").exists()
    assert not (tmp_path / "web" / "live.geojson").exists()


def test_the_publisher_is_given_the_directory_this_loop_wrote(con, tmp_path, monkeypatch):
    """`publish("live")` defaults to the family's own REPO/web/files. If the loop does not
    pass its OWN out_dir, `--out` silently ships whatever happens to be in the repo
    instead of the pair this tick just produced."""
    _, calls = run(con, tmp_path, monkeypatch)
    assert calls["publish"] == [("live", tmp_path / "web")]


def test_the_detector_ticks_at_its_own_rate_not_the_export_rate(con, tmp_path, monkeypatch):
    """CO-OPS publishes every 6 min and KNYC hourly (flood 14, measured). Re-fetching them
    every 30 s asks two public APIs 12x and 120x per publication for an answer that cannot
    have moved, and a rate-limited 429 renders as a false OUTAGE chip on the panel. The
    tick stays SUPERVISED at 30 s; only the fetch runs at the source's rate."""
    times = [NOW + timedelta(seconds=s) for s in (0, 30, 60, live_loop.DETECT_S,
                                                  live_loop.DETECT_S + 30)]
    states, calls = run(con, tmp_path, monkeypatch, times=times)
    assert len(calls["detect"]) == 2, "fetched at t=0 and again one DETECT_S later, no more"
    # ...and the cycles in between still REPORT the detector, they just do not re-fetch it
    assert all(s["detector"]["coastal"]["stage"] == "quiet" for s in states)


def test_a_dead_detector_does_not_stop_the_fleet_publishing(con, tmp_path, monkeypatch):
    """A CO-OPS outage is a chip on the panel, never a stopped export loop."""
    def boom():
        raise RuntimeError("co-ops is down")
    states, calls = run(con, tmp_path, monkeypatch, detector=boom)
    assert "RuntimeError" in states[0]["detector"]["error"]
    assert calls["publish"], "the export half must still publish"
    assert "coastal=RuntimeError: co-ops is down" in live_loop.line(states[0]), (
        "the log line must name the outage, not render it as an absent reading")


def test_a_closed_gate_is_a_designed_state_logged_once(con, tmp_path, monkeypatch, capsys):
    """Cloud 09's rc 3: the MTA terms are unverified, so the pair is written locally and
    not published. It is a standing condition - a line every 30 s would bury the tick that
    genuinely broke, so it is logged when it CHANGES."""
    def gated():
        raise publish.GateClosed("terms unverified")
    states, _ = run(con, tmp_path, monkeypatch, publisher=gated,
                    times=[NOW, NOW + timedelta(seconds=30), NOW + timedelta(seconds=60)])
    assert [s["publish"] for s in states] == ["gated"] * 3
    assert capsys.readouterr().out.count("publish gated") == 1


def test_a_failed_upload_is_reported_and_survived(con, tmp_path, monkeypatch):
    """Distinct from the gate: something is actually broken, so it is named every tick."""
    def broken():
        raise OSError("connection reset")
    states, _ = run(con, tmp_path, monkeypatch, publisher=broken,
                    times=[NOW, NOW + timedelta(seconds=30)])
    assert all(s["publish"].startswith("failed OSError") for s in states)
    assert "publish=failed OSError" in live_loop.line(states[-1])


def test_the_export_half_carries_its_own_previous_meta(con, tmp_path, monkeypatch):
    """live_export.once() needs the last good meta to say HOW old a stale panel is. Losing
    it between cycles turns "stale, 4 minutes" into "stale, unknown"."""
    states, _ = run(con, tmp_path, monkeypatch, times=[NOW, NOW + timedelta(seconds=30)])
    assert states[1]["meta"]["stale"] is True          # empty root: the failure path
    assert "n_vehicles" in states[1]["meta"]


# --- flood 15: the flood tick joined this loop ----------------------------------------

def test_the_flood_tick_rides_this_cycle_rather_than_a_second_daemon(con, tmp_path,
                                                                     monkeypatch):
    """One process, one clock, one warm connection - so the panel's halves cannot age
    apart (spec story 28, the reason this module exists at all). The flood tick is ONE
    call inside cycle() and ONE field on state; a second Deployment would be three
    interpreters, three requests on a tight floor and three clocks."""
    seen = []

    def fake_tick(con_, root, out_dir, prev, now, detector=None, ship_=None):
        seen.append((root, out_dir, prev, now, detector))
        return {"skipped": False, "at": now, "counts": {"cells": 1}}

    monkeypatch.setattr(live_loop.flood_panel, "tick", fake_tick)
    states, _ = run(con, tmp_path, monkeypatch, times=[NOW, NOW + timedelta(seconds=30)])
    assert len(seen) == 2, "every cycle offers the tick its turn; the tick decides"
    assert seen[0][1] == tmp_path / "web", "it writes into the directory this loop wrote"
    assert seen[1][2] == states[0]["flood"], "the previous state is carried across"
    assert "flood" in states[0]


def test_the_flood_tick_is_handed_the_detector_read_this_cycle_already_made(con, tmp_path,
                                                                            monkeypatch):
    """The winter gate's Central Park temperature and the coastal chips come out of the
    read this loop already fetched on its 360 s cadence. Fetching them again inside the
    flood tick would re-ask two public APIs at the RENDER rate, which is the false-OUTAGE
    failure DETECT_S exists to prevent."""
    seen = []
    monkeypatch.setattr(live_loop.flood_panel, "tick",
                        lambda *a, **k: seen.append(a[5] if len(a) > 5 else k.get("detector")) or {})
    states, calls = run(con, tmp_path, monkeypatch,
                        times=[NOW, NOW + timedelta(seconds=30)])
    assert len(calls["detect"]) == 1, "still one fetch per DETECT_S, not one per tick"
    assert all(d is not None and d["coastal"]["stage"] == "quiet" for d in seen)


def test_a_broken_flood_tick_never_stops_the_fleet(con, tmp_path, monkeypatch):
    """Copied failure policy: an outage is a field on state. The flood tick swallows its
    own errors, so this asserts the loop does not depend on that promise being kept by
    accident - the export and the publish still happen."""
    monkeypatch.setattr(live_loop.flood_panel, "tick",
                        lambda *a, **k: {"skipped": False, "error": "Boom: it broke"})
    states, calls = run(con, tmp_path, monkeypatch)
    assert calls["publish"], "the export half must still publish"
    assert "flood=error" in live_loop.line(states[0])


def test_the_flood_tick_reports_itself_on_the_one_log_line(con, tmp_path, monkeypatch):
    monkeypatch.setattr(live_loop.flood_panel, "tick", lambda *a, **k: {"skipped": True})
    states, _ = run(con, tmp_path, monkeypatch)
    assert "flood=skipped" in live_loop.line(states[0])


# --- flood-build 17: the impact overlays MERGED INTO that same tick ----------------------

def test_the_impact_overlays_add_no_second_call_to_this_cycle(con, tmp_path, monkeypatch):
    """flood 17's two overlays ride flood 15's tick, which rides this loop. There is still
    exactly ONE flood call per cycle and exactly one `flood` field on state: a second call
    here would be a second clock and a second warm connection for the same 30 s, which is
    the thing this module exists to prevent."""
    import ast
    from pathlib import Path

    calls = [n for n in ast.walk(ast.parse(Path(live_loop.__file__).read_text()))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "tick"]
    assert len(calls) == 1, "cycle() must call the flood tick once and only once"
    src = Path(live_loop.__file__).read_text()
    assert "flood_overlay" not in src, (
        "the overlays are merged into flood_panel.tick, never called from this loop")


def test_the_overlays_report_themselves_on_the_one_log_line(con, tmp_path, monkeypatch):
    """One line per tick is the supervision surface; a layer nobody can see on it is a
    layer nobody notices going dark."""
    monkeypatch.setattr(live_loop.flood_panel, "tick", lambda *a, **k: {
        "skipped": False, "counts": {}, "window": "OK", "skew": "ok",
        "impact": {"bus": {"state": "no_baseline", "n_cells": 19},
                   "subway": {"state": "ok", "n_complexes": 438}}})
    states, _ = run(con, tmp_path, monkeypatch)
    line = live_loop.line(states[0])
    assert "impact bus=no_baseline/19 subway=ok/438" in line


def test_a_broken_overlay_read_never_reaches_this_loop(con, tmp_path, monkeypatch):
    """The overlays are a garnish on the panel. `flood_overlay.read` catches per side, so
    a dead Gold table costs a grey layer and nothing else - the fleet still exports and
    still publishes. (That the exception is swallowed AT the read is pinned next door, in
    test_flood_overlay.py; here the claim is only that this loop never sees it.)"""
    from raincheck import flood_overlay

    monkeypatch.setattr(flood_overlay, "bus",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("gold is gone")))
    states, calls = run(con, tmp_path, monkeypatch)
    assert len(calls["publish"]) == 1 and states[0]["publish"] == "published 2"
    assert "gold is gone" not in live_loop.line(states[0])


# --- flood-build 20: the design-storm sentence MERGED INTO that same tick ----------------

def test_the_design_storm_sentence_never_touches_this_loop(con, tmp_path, monkeypatch):
    """flood-build 20 rides flood 15's tick exactly as flood 17's overlays do: its data is
    computed inside `flood_panel._tick` from rows that tick already read, so this loop
    gains no call, no import and no state field of its own - the wave-8 `cycle()` union is
    notify 10's alone. Same AST pin as the overlays test above, extended to this ticket's
    name."""
    import ast
    from pathlib import Path

    src = Path(live_loop.__file__).read_text()
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "tick"]
    assert len(calls) == 1, "cycle() must call the flood tick once and only once"
    assert "design_storm" not in src, (
        "the sentence is merged into flood_panel.tick, never called from this loop")


def test_the_design_storm_reports_itself_on_the_one_log_line(con, tmp_path, monkeypatch):
    """The sentence's supervision surface is the same one line per tick."""
    monkeypatch.setattr(live_loop.flood_panel, "tick", lambda *a, **k: {
        "skipped": False, "counts": {}, "window": "OK", "skew": "ok",
        "design_storm": {"cells": 2, "max_mm_1h": 53.9}})
    states, _ = run(con, tmp_path, monkeypatch)
    assert "ds=2@53.9" in live_loop.line(states[0])
