"""Flood-build ticket 13: the two display-only truth tiers.

Seam 2 (pure functions on captured responses, no network). Fixtures are verbatim API
bodies, cut down to a handful of deployments but never reshaped:
  flood_floodnet_unbounded.json    an UNBOUNDED `order_by time desc` read — 50 rows, all
                                   of them deployment only_wise_mule stamped year 2080.
  flood_floodnet_window.json       one bounded [now-60m, now+2m] read on a dry night:
                                   standing offsets (372, 331, 17 mm), dry sensors, rows
                                   with a null deployment_id, and null depths.
  flood_floodnet_deployments.json  the matching deployments/flood records, including a
                                   noisy, a hardware_issue, a dead and a date_down one.
  flood_alerts_water.parquet       ticket 02's 410 captured water rows (reused).
The window capture's newest sample is 2026-08-24T00:31Z; NOW is pinned just after it, so
freshness is a property of the fixture and not of the day the suite runs.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from raincheck import flood_alerts as fa, flood_truth as ft

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 8, 24, 0, 32, tzinfo=timezone.utc)
STANDING = {"ugliest_cyan_elephant": 371, "noticeably-safe-swine": 331}
BLIP = "scarcely-elegant-emu"  # 17 -> 11 -> 0 mm: FloodNet's own "blip" noise category


def _load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(scope="module")
def payload():
    return _load("flood_floodnet_window.json")


@pytest.fixture(scope="module")
def deployments():
    return ft.by_deployment(_load("flood_floodnet_deployments.json"))


def _rising(now, depths, step_min=1):
    """A synthetic series in the captured row shape: the live API had no flood to capture."""
    n = len(depths)
    return {"data": {"depth_data": [
        {"deployment_id": "sadly_calm_cattle",
         "time": (now - timedelta(minutes=(n - 1 - i) * step_min)).isoformat(),
         "depth_proc_mm": d}
        for i, d in enumerate(depths)]}}


# ---- the bounded window ----------------------------------------------------------

def test_the_2080_clock_never_survives_parsing():
    """M3: an unbounded read is topped by a sensor stamping year 2080. The window drops
    every one of its samples, so a widened query cannot re-poison the tier."""
    rows = _load("flood_floodnet_unbounded.json")["data"]["depth_data"]
    assert rows and all(r["time"][:4] == "2080" for r in rows)
    by_dep, report = ft.series(_load("flood_floodnet_unbounded.json"), NOW)
    assert by_dep == {}
    assert report["dropped"]["out_of_window"] == len(rows)


def test_null_deployment_rows_are_dropped(payload):
    raw = payload["data"]["depth_data"]
    assert sum(1 for r in raw if not r["deployment_id"]) > 0  # they really exist
    by_dep, report = ft.series(payload, NOW)
    assert report["dropped"]["null_id"] == sum(1 for r in raw if not r["deployment_id"])
    assert all(by_dep)


def test_the_window_query_is_bounded_and_null_filtered():
    lo, hi = ft.window(NOW)
    assert lo == "2026-08-23T23:32:00Z" and hi == "2026-08-24T00:34:00Z"
    assert "_gte: $lo" in ft.DEPTH_QUERY and "_lte: $hi" in ft.DEPTH_QUERY
    assert "_is_null: false" in ft.DEPTH_QUERY
    assert "$cap" in ft.DEPTH_QUERY and ft.ROW_CAP == 10_000


def test_the_capture_is_fresh_against_the_pinned_clock(payload):
    """Guard on the fixture itself: if a re-capture moves the window, every freshness
    assertion below would quietly become vacuous."""
    by_dep, report = ft.series(payload, NOW)
    newest = datetime.fromisoformat(report["newest"])
    assert timedelta(0) <= NOW - newest <= timedelta(minutes=ft.MAX_AGE_MIN)


# ---- the water rule --------------------------------------------------------------

def test_standing_offsets_are_not_water(payload):
    """The dry-night measurement: sensors parked at 331 and 371 mm all window long.
    Absolute depth would call both of them a flood; there is no rise and no onset."""
    by_dep, _ = ft.series(payload, NOW)
    for dep, mm in STANDING.items():
        s = ft.sensor_state(by_dep[dep], NOW)
        assert s["depth_mm"] == mm >= ft.MIN_DEPTH_MM and s["fresh"]
        assert not s["water"] and s["rise_mm"] < ft.MIN_RISE_MM and s["onset"] is None
        assert s["run"] == s["samples"]  # above for the whole window: nothing began


def test_a_blip_is_not_water(payload):
    """The same capture holds a 17 -> 11 -> 0 mm blip. It clears the depth floor for one
    sample, which is what the run clause is for — checked at the blip's own peak, not
    only after it has fallen back."""
    by_dep, _ = ft.series(payload, NOW)
    samples = by_dep[BLIP]
    peak = max(range(len(samples)), key=lambda i: samples[i][1])
    assert samples[peak][1] == 17
    s = ft.sensor_state(samples[:peak + 1], samples[peak][0])
    assert s["depth_mm"] >= ft.MIN_DEPTH_MM and s["rise_mm"] >= ft.MIN_RISE_MM
    assert not s["water"] and s["run"] < ft.MIN_RUN
    assert not ft.sensor_state(samples, NOW)["water"]


def test_nothing_on_a_dry_night_is_water(payload, deployments):
    rows, report = ft.sensors(payload, deployments, NOW)
    assert rows and not [r for r in rows if r["water"]]
    assert {r["state"] for r in rows} == {"dry"}
    assert all(r["label"] == ft.DRY_LABEL for r in rows)


def test_a_rise_with_a_run_and_an_onset_is_water(deployments):
    got = ft.sensor_state(ft.series(_rising(NOW, [0, 0, 2, 18, 24, 31]), NOW)[0]
                          ["sadly_calm_cattle"], NOW)
    assert got["water"] and got["run"] == 3 and got["rise_mm"] == 31 and got["onset"]


@pytest.mark.parametrize("depths,why", [
    ([0, 0, 2, 4, 9, 14], "latest below the depth floor"),
    ([0, 0, 0, 0, 2, 31], "only one sample above — no run"),
    ([40, 41, 40, 42, 41, 43], "above all window — a standing offset, no onset"),
    ([0, 0, 0, 20, 21, 22.0], "rise of 22 mm clears; sanity check the clauses are AND-ed"),
])
def test_each_clause_of_the_rule_is_load_bearing(depths, why):
    s = ft.sensor_state(ft.series(_rising(NOW, depths), NOW)[0]["sadly_calm_cattle"], NOW)
    assert s["water"] is (depths == [0, 0, 0, 20, 21, 22.0]), why


def test_a_stale_sensor_is_never_water():
    old = NOW - timedelta(minutes=ft.MAX_AGE_MIN + 5)
    s = ft.sensor_state(ft.series(_rising(old, [0, 0, 2, 18, 24, 31]), NOW)[0]
                        ["sadly_calm_cattle"], NOW)
    assert not s["water"] and not s["fresh"] and s["run"] == 3


# ---- what the tier refuses to render ---------------------------------------------

def test_sensors_absent_from_the_metadata_are_dropped(payload, deployments):
    """Measured: 10 of 422 reporting sensors are absent from deployments/flood, and the
    two largest standing offsets are among them. No point, no status, no caveat."""
    by_dep, _ = ft.series(payload, NOW)
    absent = set(by_dep) - set(deployments)
    assert {"ugliest_cyan_elephant", "noticeably-safe-swine"} <= absent
    rows, report = ft.sensors(payload, deployments, NOW)
    assert report["unknown"] == len(absent)
    assert not {r["deployment_id"] for r in rows} & absent


def test_the_status_blacklist_mutes_sensors(payload, deployments):
    blocked = {d for d, m in deployments.items()
               if m["sensor_status"] in ft.BLOCKED_STATUS or m["date_down"]}
    assert blocked  # noisy + hardware_issue in the fixture
    rows, report = ft.sensors(payload, deployments, NOW)
    assert not {r["deployment_id"] for r in rows} & blocked
    assert report["muted"] == len(blocked & set(ft.series(payload, NOW)[0]))


def test_an_unknown_status_is_not_muted(payload, deployments):
    """A new status string must not silently hide detections: only the measured bad
    vocabulary mutes. non-ota is not on it."""
    rows, _ = ft.sensors(payload, deployments, NOW)
    assert "basically-equipped-amoeba" in {r["deployment_id"] for r in rows}


def test_concurrent_own_cell_rain_gates_the_display(deployments):
    payload = _rising(NOW, [0, 0, 2, 18, 24, 31])
    cell_of = {"sadly_calm_cattle": "882a1072d9fffff"}
    dry, _ = ft.sensors(payload, deployments, NOW, wet_cells=set(), cell_of=cell_of)
    wet, _ = ft.sensors(payload, deployments, NOW,
                        wet_cells={"882a1072d9fffff"}, cell_of=cell_of)
    ungated, _ = ft.sensors(payload, deployments, NOW)
    assert dry[0]["water"] and not dry[0]["display"] and dry[0]["gate"] == ft.NO_RAIN
    assert wet[0]["display"] and wet[0]["gate"] == "rain"
    # no wet-cell set supplied: the gate is not evaluated, and the tier says so
    assert ungated[0]["display"] and ungated[0]["gate"] is None


def test_an_api_error_greys_the_tier(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise TimeoutError("hard 3 s timeout")
    monkeypatch.setattr(ft, "fetch_depth", boom)
    tier = ft.floodnet(tmp_path, NOW)
    assert tier["status"] == "error" and tier["detected"] == 0 and tier["sensors"] == []
    assert "TimeoutError" in tier["error"]
    assert tier["citation"] == ft.CITATION  # the citation renders with the tier, always


def test_the_citation_and_caveats_render_with_the_tier(payload, deployments):
    assert "Mydlarz" in ft.CITATION and "non-commercial" in ft.CITATION
    assert any("snow" in c for c in ft.CAVEATS)
    assert "never absolute depth" in ft.RULE


# ---- MTA chips -------------------------------------------------------------------

@pytest.fixture(scope="module")
def water_rows():
    return pq.read_table(FIXTURES / "flood_alerts_water.parquet").to_pylist()


@pytest.fixture(scope="module")
def aliases():
    stations = json.loads((FIXTURES / "flood_alerts_stations.json").read_text())
    by = fa.build_aliases(stations)
    return by, fa.build_pattern(by)


@pytest.fixture(scope="module")
def mta_chips(water_rows, aliases):
    by, pat = aliases
    return ft.chips(water_rows, by, pat, NOW)


def test_one_chip_per_incident(mta_chips, water_rows, aliases):
    by, pat = aliases
    obs = fa.observations(water_rows, by, pat)
    assert {c["event_id"] for c in mta_chips} == {o["event_id"] for o in obs}
    assert len(mta_chips) == len({o["event_id"] for o in obs}) < len(obs)


def test_chips_carry_first_seen_and_state(mta_chips):
    assert all(c["first_seen"] and c["age_min"] > 0 for c in mta_chips)
    assert {c["state"] for c in mta_chips} <= {fa.ACTIVE, fa.CLEARED_STATE}
    assert any(c["state"] == fa.CLEARED_STATE for c in mta_chips)


def test_events_that_disagree_about_one_complex_render_separately(mta_chips):
    """264048 says active on Utica Av while 264063 says cleared. Reconciling across
    events is the spine's job (04); this tier renders each event's own truth."""
    at = {c["event_id"]: c for c in mta_chips}
    shared = {s["complex_id"] for s in at["264048"]["stations"]} & \
             {s["complex_id"] for s in at["264063"]["stations"]}
    assert shared
    assert at["264048"]["state"] != at["264063"]["state"]


def test_only_the_live_remove_water_vocabulary_makes_a_chip(water_rows, aliases):
    by, pat = aliases
    for c in ft.chips(water_rows, by, pat, NOW):
        for alert_id in c["alert_ids"]:
            row = next(r for r in water_rows if r["alert_id"] == alert_id)
            text = fa.norm(f"{row['header'] or ''} {row['description'] or ''}")
            assert fa.LIVE.search(text)


def test_chip_state_follows_the_newest_revision(water_rows, aliases):
    """alert_id is not a stable text key: the MTA rewrites the prose in place, so a chip
    that has gone to 'after we removed' must not be dragged back by an older revision."""
    by, pat = aliases
    obs = {o["event_id"]: o for o in fa.observations(water_rows, by, pat)}
    for c in ft.chips(water_rows, by, pat, NOW):
        if c["state"] == fa.CLEARED_STATE:
            assert all(s["state"] == fa.CLEARED_STATE for s in c["stations"])
        assert c["last_seen"] >= obs[c["event_id"]]["first_seen"]


def test_the_mta_tier_greys_on_a_missing_root(tmp_path):
    tier = ft.mta(tmp_path, NOW)
    assert tier["status"] == "error" and tier["chips"] == []
