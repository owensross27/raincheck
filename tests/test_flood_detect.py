"""Flood-build ticket 11, testing seam 2: the live detector as pure functions on fixtures.

No network and no live table. The precip fixture is REAL AORC output for flood event
2021-09-01 (Ida) — the citywide wet-Cell series, four Cells' hourly mm, and those Cells'
own rows from `gold/flood_matrix` — so "the live Window reproduces the offline features"
is an assertion about the shipped numbers rather than about a hand-shaped stub.

Two real-root canaries at the bottom re-derive the fixture and the committed artifact and
skip where there is no data root, which is the normal shape in a worktree.
"""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from raincheck import flood_detect as fd
from raincheck import flood_exposure as fe
from raincheck import flood_live as fl
from raincheck import flood_truth as ftr
from raincheck.paths import data_root

FIX = Path(__file__).parent / "fixtures" / "flood_detect_ida.json"
NY = ZoneInfo("America/New_York")
UTC = timezone.utc


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


@pytest.fixture(scope="module")
def ida() -> dict:
    f = json.loads(FIX.read_text())
    f["ws"], f["we"] = _dt(f["window_start_utc"]), _dt(f["window_end_utc"])
    f["peak"] = _dt(f["peak_hour_utc"])
    f["wet"] = {_dt(k): v for k, v in f["wet_counts"].items()}
    f["hours"] = [{"cell": c["cell"], "hour_end_utc": _dt(h), "mm_1h": mm}
                  for c in f["cells"] for h, mm in c["hourly"].items()]
    f["mx"] = {c["cell"]: c["matrix"] for c in f["cells"]}
    return f


@pytest.fixture(scope="module")
def wet_ante(ida) -> dict:
    """A SECOND real event, and the reason it exists is a mutation survivor: Ida's
    antecedent is exactly 0.0 for every Cell, so the Ida slice cannot test that term and a
    'frozen antecedent' assertion over it passes on zeros."""
    e = dict(ida["wet_antecedent_event"])
    e["ws"], e["we"] = _dt(e["window_start_utc"]), _dt(e["window_end_utc"])
    e["hours"] = [{"cell": c["cell"], "hour_end_utc": _dt(h), "mm_1h": mm}
                  for c in e["cells"] for h, mm in c["hourly"].items()]
    e["mx"] = {c["cell"]: c["matrix"] for c in e["cells"]}
    return e


@pytest.fixture(scope="module")
def art() -> dict:
    return fe.coefficients()


@pytest.fixture(scope="module")
def det() -> dict:
    return fd.artifact()


# ---- the forcing: MRMS RadarOnly :00 stamps ONLY --------------------------------------

def test_the_forcing_accepts_a_radaronly_stamp_on_the_hour():
    assert fd.accepts("MRMS_RadarOnly_QPE_01H_00.00_20260821-000000.grib2.gz")
    assert fd.accepts("https://x/CONUS/RadarOnly_QPE_01H_00.00/20260821/"
                      "MRMS_RadarOnly_QPE_01H_00.00_20260821-130000.grib2.gz")


def test_the_forcing_rejects_the_two_minute_trailing_stamps():
    # they converge from ABOVE and would break the converges-from-below contract
    for mm in ("000200", "005800", "001400"):
        assert not fd.accepts(f"MRMS_RadarOnly_QPE_01H_00.00_20260821-{mm}.grib2.gz")


def test_the_forcing_rejects_pass2_even_on_the_hour():
    # Pass2 lags 60-90 min and is the BATCH product; it never feeds the live path
    assert not fd.accepts("MRMS_MultiSensor_QPE_01H_Pass2_00.00_20260821-000000.grib2.gz")
    assert fd.LIVE_PRODUCT != fd.REJECTED_PRODUCTS[0]


def test_the_frozen_url_pattern_builds_a_name_our_own_filter_accepts():
    # the canary's precondition: a pattern that built a rejected name would probe nothing
    url = fd.MRMS_URL.format(product=fd.LIVE_PRODUCT, d=datetime(2026, 8, 21, 13, tzinfo=UTC))
    assert fd.accepts(url) and "20260821-130000" in url


def test_the_live_product_is_read_from_precip_live_and_not_respelled():
    from raincheck import precip_live as pl
    assert fd.LIVE_PRODUCT is pl.RADAR and fd.REJECTED_PRODUCTS == (pl.PASS2,)


# ---- the backward Window walk ---------------------------------------------------------

def test_the_walk_reproduces_the_offline_window_on_the_fixture_event_day(ida):
    """THE reproduction assert: mid-storm, the observation-driven walk lands on exactly the
    calendar window_start flood_spine derived for the same event."""
    w = fd.walk(ida["peak"], ida["wet"])
    assert w["state"] == fd.OK and w["anchor"] == ida["ws"] and w["walked_days"] == 0


def test_the_anchor_is_a_twenty_one_hundred_new_york_boundary(ida):
    w = fd.walk(ida["peak"], ida["wet"])
    assert w["anchor"].astimezone(NY).hour == fd.ANCHOR_LOCAL_H
    assert w["anchor"].astimezone(NY).minute == 0


def test_a_missing_pad_stamp_is_insufficient_data_and_never_an_older_anchor(ida):
    """'we cannot see whether that evening was dry' is a different answer from 'it was
    wet' — the walk stops rather than falling through to a day it can see."""
    w = fd.walk(ida["peak"], ida["wet"])
    holed = dict(ida["wet"])
    del holed[fd.pad_hours(w["anchor"])[1]]
    got = fd.walk(ida["peak"], holed)
    assert got["state"] == fd.INSUFFICIENT_DATA and got["anchor"] is None
    assert got["missing_pad"] == [fd.pad_hours(w["anchor"])[1]]


def test_a_none_pad_value_is_missing_and_not_dry(ida):
    w = fd.walk(ida["peak"], ida["wet"])
    holed = dict(ida["wet"]) | {fd.pad_hours(w["anchor"])[0]: None}
    assert fd.walk(ida["peak"], holed)["state"] == fd.INSUFFICIENT_DATA


def test_the_walk_walks_back_a_day_when_a_pad_hour_reaches_k():
    """The cut is BELOW K, so a pad hour that reaches K exactly is wet and the walk moves."""
    now = datetime(2026, 8, 25, 12, tzinfo=UTC)
    cands = fd.anchors(now)
    wet = {h: 0 for a in cands for h in fd.pad_hours(a)}
    assert fd.walk(now, wet)["anchor"] == cands[0]
    wet |= {h: fd.WET_CELLS_K for h in fd.pad_hours(cands[0])}
    got = fd.walk(now, wet)
    assert got["state"] == fd.OK and got["walked_days"] == 1 and got["anchor"] == cands[1]


def test_the_walk_caps_at_six_days_and_says_so():
    now = datetime(2026, 8, 25, 12, tzinfo=UTC)
    wet = {h: 999 for h in (a - timedelta(hours=k)
                            for a in fd.anchors(now) for k in range(fd.PAD_H))}
    got = fd.walk(now, wet)
    assert got["state"] == fd.WINDOW_CAPPED and got["anchor"] is None
    assert got["walked_days"] == fd.CAP_DAYS == 6


def test_the_pad_is_the_three_hours_before_the_anchor_and_none_is_in_the_window():
    a = datetime(2026, 8, 25, 1, tzinfo=UTC)
    pad = fd.pad_hours(a)
    assert pad == [a - timedelta(hours=2), a - timedelta(hours=1), a]
    assert not (set(pad) & set(fd.hour_ends(a, a + timedelta(hours=6))))


def test_the_anchor_holds_local_twenty_one_hundred_across_both_dst_switches():
    """DST is resolved from the NY-LOCAL date, not by subtracting 24 h — the two differ by
    an hour exactly twice a year, which is precisely when a walk would slip."""
    for now in (datetime(2026, 3, 9, 12, tzinfo=UTC),    # after spring forward
                datetime(2026, 11, 2, 12, tzinfo=UTC)):  # after fall back
        for a in fd.anchors(now):
            assert a.astimezone(NY).hour == 21, a
        offsets = {a.astimezone(NY).utcoffset() for a in fd.anchors(now)}
        assert len(offsets) == 2, "the fixture week must straddle the switch"


def test_the_walk_is_stateless(ida):
    """Same inputs, same anchor, whether or not a previous cycle ever ran."""
    assert fd.walk(ida["peak"], ida["wet"]) == fd.walk(ida["peak"], dict(ida["wet"]))


# ---- citywide dryness -----------------------------------------------------------------

def test_the_citywide_measure_is_a_count_and_never_a_max(ida):
    hours = [{"cell": 1, "hour_end_utc": ida["ws"], "mm_1h": 500.0},
             {"cell": 2, "hour_end_utc": ida["ws"], "mm_1h": 0.0}]
    assert fd.wet_counts(hours) == {ida["ws"]: 1}   # one hot Pixel is not a wet city


def test_a_null_cell_hour_is_not_counted_wet(ida):
    hours = [{"cell": 1, "hour_end_utc": ida["ws"], "mm_1h": None}]
    assert fd.wet_counts(hours) == {ida["ws"]: 0}


def test_the_dry_run_counts_back_from_the_newest_hour():
    now = datetime(2026, 8, 25, 12, 30, tzinfo=UTC)
    h = now.replace(minute=0)
    wet = {h - timedelta(hours=k): 0 for k in range(4)} | {h - timedelta(hours=4): 99}
    assert fd.dry_run_hours(wet, now) == 4
    assert fd.dry_run_hours(wet | {h: 99}, now) == 0


def test_an_unknown_newest_hour_is_never_counted_dry():
    now = datetime(2026, 8, 25, 12, 30, tzinfo=UTC)
    assert fd.dry_run_hours({}, now) is None


# ---- Window features ------------------------------------------------------------------

def test_the_window_features_reproduce_the_offline_matrix_terms(ida):
    """The live Window and gold/flood_matrix's event window are the same object measured
    at different times — (anchor, now], antecedent frozen at the anchor hour."""
    f = fd.window_features(ida["hours"], ida["ws"], ida["we"])
    for cell, want in ida["mx"].items():
        got = fd.precip_terms(f["cells"][cell])
        for k in ("log1p_precip_max_mm_1h", "log1p_precip_total_mm",
                  "log1p_antecedent_mm_24h"):
            assert got[k] == pytest.approx(want[k], abs=1e-6), (cell, k)


def test_the_anchor_hour_is_antecedent_and_never_in_the_window(ida):
    f = fd.window_features(ida["hours"], ida["ws"], ida["we"])
    assert f["window_hours_expected"] == len(fd.hour_ends(ida["ws"], ida["we"]))
    assert ida["ws"] not in set(fd.hour_ends(ida["ws"], ida["we"]))


def test_deleting_one_interior_hour_trips_holes(ida):
    mid = ida["ws"] + timedelta(hours=10)
    thin = [r for r in ida["hours"] if r["hour_end_utc"] != mid]
    f = fd.window_features(thin, ida["ws"], ida["we"])
    assert f["state"] == fd.HOLES and f["coverage"] < 1.0
    assert fd.window_features(ida["hours"], ida["ws"], ida["we"])["state"] == fd.OK


def test_holes_is_a_state_distinct_from_the_walk_and_from_staleness(ida):
    """A holed Window is still a Window: the walk stays OK and the anchor stands."""
    mid = ida["ws"] + timedelta(hours=10)
    thin = [r for r in ida["hours"] if r["hour_end_utc"] != mid]
    assert fd.window_features(thin, ida["ws"], ida["we"])["state"] == fd.HOLES
    assert fd.walk(ida["peak"], ida["wet"])["state"] == fd.OK
    assert fd.staleness(ida["we"], ida["we"])["state"] == fd.FRESH


def test_a_null_hour_counts_as_missing_and_never_as_zero(ida):
    cell = next(iter(ida["mx"]))
    mid = ida["ws"] + timedelta(hours=10)
    nulled = [dict(r) | ({"mm_1h": None} if (r["cell"] == cell and r["hour_end_utc"] == mid)
                         else {}) for r in ida["hours"]]
    full = fd.window_features(ida["hours"], ida["ws"], ida["we"])["cells"][cell]
    thin = fd.window_features(nulled, ida["ws"], ida["we"])["cells"][cell]
    assert thin["window_hours"] == full["window_hours"] - 1
    assert thin["window_coverage"] < full["window_coverage"]
    assert thin["total_mm"] == pytest.approx(full["total_mm"] - (
        next(r["mm_1h"] for r in ida["hours"]
             if r["cell"] == cell and r["hour_end_utc"] == mid)), abs=1e-9)


def test_a_cell_with_no_value_at_all_is_unforced_and_not_a_hole(ida):
    """AORC has 168 permanently dark Cells of 4,113; counting them as holes would make
    every offline replay report HOLES forever."""
    dark = [{"cell": -1, "hour_end_utc": h, "mm_1h": None}
            for h in fd.hour_ends(ida["ws"], ida["we"])]
    f = fd.window_features(ida["hours"] + dark, ida["ws"], ida["we"])
    assert f["state"] == fd.OK and f["unforced_cells"] == 1 and -1 not in f["cells"]


def test_the_antecedent_is_frozen_at_the_anchor_and_does_not_move(wet_ante):
    for cell in wet_ante["mx"]:
        seen = {fd.window_features(wet_ante["hours"], wet_ante["ws"],
                                   wet_ante["ws"] + timedelta(hours=k)
                                   )["cells"][cell]["antecedent_mm_24h"] for k in (1, 6, 24, 48)}
        assert len(seen) == 1 and seen.pop() > 0.0, cell


def test_the_antecedent_block_is_the_twenty_four_hours_ending_at_the_anchor(wet_ante):
    """[anchor-23h, anchor] inclusive — the same rows flood_matrix reads at `at_open`. Not
    the 24 h before `now`, which for a grown Window sits INSIDE it and sums to nothing."""
    f = fd.window_features(wet_ante["hours"], wet_ante["ws"], wet_ante["we"])
    for cell, want in wet_ante["mx"].items():
        c = f["cells"][cell]
        assert c["antecedent_hours"] == fd.ANTECEDENT_H == 24
        assert c["antecedent_coverage"] == 1.0
        assert fd.precip_terms(c)["log1p_antecedent_mm_24h"] == pytest.approx(
            want["log1p_antecedent_mm_24h"], abs=1e-6), cell
    assert min(w["log1p_antecedent_mm_24h"] for w in wet_ante["mx"].values()) > 1.0, \
        "this fixture is useless if its antecedent is zero — Ida's is"


def test_an_antecedent_hour_is_never_also_a_window_hour(wet_ante):
    a, n = wet_ante["ws"], wet_ante["we"]
    ante = {a - timedelta(hours=h) for h in range(fd.ANTECEDENT_H)}
    assert not (ante & set(fd.hour_ends(a, n))) and a in ante


def test_the_wet_antecedent_event_also_reproduces_the_offline_matrix(wet_ante):
    f = fd.window_features(wet_ante["hours"], wet_ante["ws"], wet_ante["we"])
    for cell, want in wet_ante["mx"].items():
        got = fd.precip_terms(f["cells"][cell])
        for k in ("log1p_precip_max_mm_1h", "log1p_precip_total_mm",
                  "log1p_antecedent_mm_24h"):
            assert got[k] == pytest.approx(want[k], abs=1e-6), (cell, k)


def test_the_precip_terms_are_log1p_once(ida):
    c = {"max_mm_1h": 10.0, "total_mm": 40.0, "antecedent_mm_24h": 3.0}
    t = fd.precip_terms(c)
    assert t["log1p_precip_total_mm"] == pytest.approx(math.log1p(40.0))
    assert math.expm1(t["log1p_precip_max_mm_1h"]) == pytest.approx(10.0)


# ---- live evaluation ------------------------------------------------------------------

def _units(ida):
    us = [dict(p) for p in ida["points"]]
    cell = next(iter(ida["mx"]))
    for c, m in ida["mx"].items():
        us.append({"asset_id": f"cell:{c:x}", "kind": "cell", "cell": c} | {
            k: m[k] for k in ("share_deep", "share_nuisance", "share_not_analyzed",
                              "density_311_3y")})
    us.append({"asset_id": ida["complex_asset_id"], "kind": "complex",
               "complex_id": ida["complex_id"], "cell": cell})
    return us


def test_live_eta_at_window_close_equals_the_offline_event_eta(ida, art):
    """The converges-from-below contract as an assert. eta() is THE function that built
    gold/flood_exposure, so this is the same model reaching the same number."""
    f = fd.window_features(ida["hours"], ida["ws"], ida["we"])
    m = art["models"]["cell"]
    for cell, want in ida["mx"].items():
        live = fe.eta(m, fd.unit_feats({"kind": "cell"} | want, fd.precip_terms(f["cells"][cell])))
        assert live == pytest.approx(fe.eta(m, want), abs=1e-6), cell


def test_live_eta_never_falls_as_the_window_grows(ida, art):
    m = art["models"]["cell"]
    for cell, stat in ida["mx"].items():
        prev = -math.inf
        for k in (1, 6, 12, 24, 36, 54):
            f = fd.window_features(ida["hours"], ida["ws"], ida["ws"] + timedelta(hours=k))
            c = f["cells"].get(cell)
            if c is None:
                continue
            e = fe.eta(m, fd.unit_feats({"kind": "cell"} | stat, fd.precip_terms(c)))
            assert e >= prev - 1e-12, (cell, k)
            prev = e


def test_a_score_is_the_linear_predictor_and_is_not_squashed(ida, art):
    f = fd.window_features(ida["hours"], ida["ws"], ida["we"])
    out = fd.evaluate(art, _units(ida), f)
    assert out and any(s["eta"] < 0 for s in out), "real etas are negative for most Units"
    assert art["score"]["is_probability"] is False


def test_the_display_value_is_a_within_kind_rank_of_the_current_vector(ida, art):
    f = fd.window_features(ida["hours"], ida["ws"], ida["we"])
    out = fd.evaluate(art, _units(ida), f)
    for kind in {s["kind"] for s in out}:
        grp = sorted((s for s in out if s["kind"] == kind), key=lambda s: s["eta"])
        assert all(0 < s["rank"] <= 1 for s in grp)
        assert [s["rank"] for s in grp] == sorted(s["rank"] for s in grp)
        assert grp[-1]["rank"] == 1.0


def test_the_live_rank_spreads_where_the_static_cdf_would_read_zero(ida, art):
    """cdf.by_kind is the STATIC view for dormant weather. Fed a LIVE eta in light rain it
    reads ~0 for everything, which is exactly why the display value is a current-vector
    rank instead: in a drizzle the ranks still span (0, 1] and order the city."""
    drizzle = [dict(r) | {"mm_1h": None if r["mm_1h"] is None else r["mm_1h"] * 0.001}
               for r in ida["hours"]]
    f = fd.window_features(drizzle, ida["ws"], ida["we"])
    out = fd.evaluate(art, _units(ida), f)
    cells = [s for s in out if s["kind"] == "cell"]
    assert len(cells) > 1 and len({s["rank"] for s in cells}) == len(cells)
    assert max(s["rank"] for s in cells) == 1.0 and min(s["rank"] for s in cells) < 1.0
    knots = art["cdf"]["by_kind"]["cell"]
    floor = knots["score_ref"][1]                     # the published 1st-percentile knot
    assert all(s["eta"] < floor for s in cells), "the static view would flatten these to ~0"


def test_entrances_publish_no_row_and_the_complex_takes_their_max(ida, art):
    f = fd.window_features(ida["hours"], ida["ws"], ida["we"])
    out = fd.evaluate(art, _units(ida), f)
    assert not [s for s in out if s["kind"] == "entrance"]
    cx = next(s for s in out if s["kind"] == "complex")
    ents = [u for u in _units(ida) if u["kind"] == "entrance"]
    assert len(ents) >= 3
    m = art["models"]["point"]
    best = max(fe.eta(m, fd.unit_feats(u, fd.precip_terms(f["cells"][u["cell"]]))) for u in ents)
    assert cx["eta"] == pytest.approx(best, abs=1e-12)


def test_an_entrance_scores_as_an_entrance_and_not_as_a_bus_stop(ida):
    ent = next(u for u in _units(ida) if u["kind"] == "entrance")
    assert fd.role_of("entrance") == "point"
    assert fd.unit_feats(ent, {"log1p_precip_max_mm_1h": 0.0, "log1p_precip_total_mm": 0.0,
                               "log1p_antecedent_mm_24h": 0.0})["is_bus_stop"] == 0.0


def test_a_missing_feature_raises_rather_than_scoring_as_zero(art):
    with pytest.raises(KeyError):
        fe.eta(art["models"]["point"], {"elev_ft": 1.0})


def test_a_cell_with_no_forcing_gets_no_live_number(ida, art):
    f = fd.window_features(ida["hours"], ida["ws"], ida["we"])
    units = _units(ida) + [{"asset_id": "bus:none", "kind": "bus_stop", "cell": -7,
                            "elev_ft": 10.0, "relief_ft": 1.0,
                            "stormwater_cat": "analyzed-none"}]
    assert "bus:none" not in {s["asset_id"] for s in fd.evaluate(art, units, f)}


# ---- tiers ----------------------------------------------------------------------------

def test_the_tiers_are_the_top_ten_and_two_percent_of_the_current_vector(ida, art):
    f = fd.window_features(ida["hours"], ida["ws"], ida["we"])
    out = fd.tiers(fd.evaluate(art, _units(ida), f), f, citywide_active=True)
    for s in out:
        if s["gate_own_cell_mm"] < fd.CELL_WINDOW_MM:
            assert s["tier"] == fd.NONE
        elif s["rank"] >= 0.98:
            assert s["tier"] == fd.HIGH
        elif s["rank"] >= 0.90:
            assert s["tier"] == fd.ELEVATED


def test_the_own_cell_rain_gate_blocks_a_tier(ida, art):
    f = fd.window_features(ida["hours"], ida["ws"], ida["we"])
    dry = dict(f) | {"cells": {c: dict(v) | {"total_mm": fd.CELL_WINDOW_MM - 0.01}
                               for c, v in f["cells"].items()}}
    assert all(s["tier"] == fd.NONE
               for s in fd.tiers(fd.evaluate(art, _units(ida), f), dry, True))


def test_a_quiet_city_tiers_nothing_even_though_something_is_always_the_maximum(ida, art):
    f = fd.window_features(ida["hours"], ida["ws"], ida["we"])
    out = fd.tiers(fd.evaluate(art, _units(ida), f), f, citywide_active=False)
    assert out and all(s["tier"] == fd.NONE for s in out)


def test_a_tier_latches_within_a_window_and_never_falls(ida, art):
    f = fd.window_features(ida["hours"], ida["ws"], ida["we"])
    hot = fd.tiers(fd.evaluate(art, _units(ida), f), f, True)
    was = {s["asset_id"]: s["tier"] for s in hot if s["tier"] != fd.NONE}
    assert was, "the fixture must flag something"
    cold = fd.tiers(fd.evaluate(art, _units(ida), f), f, citywide_active=False)
    for s in fd.latch(was, cold):
        assert s["tier"] == was.get(s["asset_id"], fd.NONE)
        assert s["latched"] is (s["asset_id"] in was)


def test_a_fresh_window_is_the_only_thing_that_clears_a_latch(ida, art):
    f = fd.window_features(ida["hours"], ida["ws"], ida["we"])
    cold = fd.tiers(fd.evaluate(art, _units(ida), f), f, citywide_active=False)
    assert all(s["tier"] == fd.NONE for s in fd.latch(None, cold))


def test_a_downward_series_revision_is_logged(ida):
    f = fd.window_features(ida["hours"], ida["ws"], ida["we"])
    cell = next(iter(ida["mx"]))
    prev = {c: v["total_mm"] for c, v in f["cells"].items()}
    prev[cell] += 5.0
    got = fd.revisions(prev, f)
    assert [r["cell"] for r in got] == [cell] and got[0]["delta_mm"] < 0


def test_a_downward_revision_never_clears_a_flag(ida, art):
    f = fd.window_features(ida["hours"], ida["ws"], ida["we"])
    hot = fd.tiers(fd.evaluate(art, _units(ida), f), f, True)
    was = {s["asset_id"]: s["tier"] for s in hot if s["tier"] != fd.NONE}
    revised = dict(f) | {"cells": {c: dict(v) | {"total_mm": 0.0} for c, v in f["cells"].items()}}
    after = fd.latch(was, fd.tiers(fd.evaluate(art, _units(ida), f), revised, True))
    assert {s["asset_id"] for s in after if s["tier"] != fd.NONE} == set(was)


def test_the_tier_vocabulary_is_ordered_and_closed():
    assert fd.TIERS == ("NONE", "ELEVATED", "HIGH")
    assert fd.TIERS.index(fd.HIGH) > fd.TIERS.index(fd.ELEVATED) > fd.TIERS.index(fd.NONE)


def test_the_tiers_say_they_are_provisional():
    assert "provisional" in fd.TIERS_PROVISIONAL and "12" in fd.TIERS_PROVISIONAL
    assert fd.artifact()["cutpoints"]["provisional"] is True


# ---- the winter gate ------------------------------------------------------------------

JULY = datetime(2026, 7, 15, 12, tzinfo=UTC)
JAN = datetime(2026, 1, 15, 12, tzinfo=UTC)


def test_the_winter_gate_suppresses_at_or_below_the_freezing_cut():
    for t in (0.5, 0.0, -3.0):
        g = fd.winter_gate(t, JAN)
        assert g["suppressed"] and g["basis"] == "observed" and g["label"] == fd.WINTER_LABEL


def test_the_winter_gate_renders_above_the_cut():
    g = fd.winter_gate(0.6, JAN)
    assert not g["suppressed"] and g["label"] is None


def test_a_missing_temperature_is_never_coerced_to_zero():
    assert fd.winter_gate(None, JULY)["temp_c"] is None
    assert not fd.winter_gate(None, JULY)["suppressed"], "a dead endpoint is not a snowstorm"


def test_an_unknown_temperature_falls_back_to_the_calendar():
    assert fd.winter_gate(None, JAN)["suppressed"] and fd.winter_gate(None, JAN)["basis"] == "calendar"
    assert not fd.winter_gate(None, JULY)["suppressed"]
    assert fd.winter_gate(None, JAN)["reason"] == "absent"


def test_a_stale_temperature_is_not_treated_as_observed():
    g = fd.winter_gate(20.0, JAN, stale=True)
    assert g["basis"] == "calendar" and g["reason"] == "stale" and g["suppressed"]
    assert fd.winter_gate(20.0, JAN, stale=False)["suppressed"] is False


def test_the_winter_fallback_months_are_flood_spines_and_not_a_second_copy():
    from raincheck.flood_spine import SNOWMELT_MONTHS
    assert fd.artifact()["winter"]["unknown_fallback_months"] == list(SNOWMELT_MONTHS)


# ---- staleness and version skew --------------------------------------------------------

def test_staleness_is_dated_at_the_reader_against_the_stamp():
    now = datetime(2026, 8, 25, 12, tzinfo=UTC)
    assert fd.staleness(now - timedelta(minutes=30), now)["state"] == fd.FRESH
    assert fd.staleness(now - timedelta(minutes=120), now)["state"] == fd.STALE
    assert fd.staleness(now - timedelta(minutes=200), now)["state"] == fd.DOWN


def test_a_missing_or_future_stamp_reads_down_and_never_fresh():
    now = datetime(2026, 8, 25, 12, tzinfo=UTC)
    assert fd.staleness(None, now)["state"] == fd.DOWN
    assert fd.staleness(now + timedelta(minutes=30), now)["state"] == fd.DOWN


def test_version_skew_refuses_the_model_tier(art):
    assert fd.skew(art, art["score_version"])["model_tier"] == "ok"
    assert fd.skew(art, "0" * 40)["model_tier"] == "refused"
    assert fd.skew(art, None)["model_tier"] == "refused"


def test_the_skew_check_compares_the_table_it_read_and_not_a_compiled_constant(art):
    src = (Path(__file__).parent.parent / "src" / "raincheck" / "flood_detect.py").read_text()
    assert art["score_version"] not in src, "a pinned digest only proves this file agrees " \
                                            "with itself"


def test_a_coefficient_swap_mid_window_forces_a_window_roll(art, det):
    a = datetime(2026, 8, 25, 1, tzinfo=UTC)
    state = {"anchor": a.isoformat(), "score_version": art["score_version"],
             "detector_version": det["detector_version"]}
    assert not fd.rolled(state, a, art["score_version"], det["detector_version"])
    assert fd.rolled(state, a, "different", det["detector_version"])
    assert fd.rolled(state, a, art["score_version"], "different")
    assert fd.rolled(state, a + timedelta(days=1), art["score_version"], det["detector_version"])
    assert fd.rolled(None, a, art["score_version"], det["detector_version"])


# ---- the detector constants artifact ----------------------------------------------------

def test_the_detector_version_moves_when_a_decision_moves(det):
    moved = dict(det)
    moved["cutpoints"] = dict(det["cutpoints"]) | {"HIGH": 0.03}
    assert fd.detector_version(moved) != det["detector_version"]


def test_the_detector_version_does_not_move_when_only_prose_moves(det):
    """A reworded sentence must never roll a live Window — the same rule flood 10's
    score_version follows, and the reason it does not hash the whole file."""
    same = dict(det) | {"window_note": "reworded", "display": {"tier_labels": {}}}
    assert fd.detector_version(same) == det["detector_version"]


def test_the_digest_scope_is_published_so_the_claim_can_be_audited(det):
    assert det["detector_version_scope"] == list(fd.DIGESTED)
    assert set(fd.DIGESTED) <= set(det)
    assert "display" not in fd.DIGESTED and not any(k.endswith("_note") for k in fd.DIGESTED)


def test_the_stamp_says_what_it_does_not_cover(det):
    assert "VALUES" in det["detector_version_note"]


def test_the_staleness_budgets_are_read_from_the_modules_that_fetch(det):
    """One number or a failed build — a mirrored constant is one that drifts."""
    b = det["staleness_budgets"]
    assert b["nws_knyc_obs_min"] == fl.KNYC_STALE_MIN
    assert b["coops_min"] == fl.OBS_STALE_MIN
    assert b["floodnet_min"] == ftr.MAX_AGE_MIN
    assert det["throttles"]["fetch_timeout_s"] == fl.TIMEOUT


def test_the_settled_nws_budget_is_two_knyc_report_intervals_and_not_fifteen_minutes(det):
    """SETTLED BY THIS TICKET. KNYC reports HOURLY; at 15 min the winter gate never fires,
    so the spec's 15 min belongs to the per-cycle ALERTS call, not to the observation."""
    b = det["staleness_budgets"]
    assert b["nws_knyc_obs_min"] == 120 == 2 * 60
    assert b["nws_alerts_min"] == 15 and b["nws_knyc_obs_min"] != 15
    assert "ALERTS" in det["staleness_budgets_note"]


def test_the_query_strings_are_derived_from_the_fetchers(det):
    q = det["query_strings"]
    assert q["coops_hilo"] == fl.HILO_QUERY and q["nws_knyc_obs"] == fl.NWS_OBS
    assert q["floodnet_graphql"] == ftr.GRAPHQL_URL


def test_the_remove_water_vocabulary_is_ticket_02s_and_not_a_second_copy(det):
    from raincheck import flood_alerts as fa
    assert det["vocabularies"]["remove_water_live"] == fa.LIVE_ANCHOR


def test_the_ugc_zone_list_is_null_with_a_reason_rather_than_invented(det):
    assert det["nws_ugc_zones"] is None
    assert "OWED" in det["nws_ugc_zones_note"]


def test_the_artifact_carries_no_skill_metric_of_any_grain(det):
    """flood 10's precedent, and the complex rule's own null result is why."""
    blob = json.dumps(det).lower()
    for metric in ("csi", "pod", "far", "pr_auc", "auc", "precision", "recall", "tp", "fp"):
        assert f'"{metric}"' not in blob
    assert "never a measured complex" in det["display"]["no_complex_skill_claim"] or \
           "aggregate of doorway scores" in det["display"]["no_complex_skill_claim"]


def test_no_code_applies_the_informational_scale_band(det):
    src = (Path(__file__).parent.parent / "src" / "raincheck" / "flood_detect.py").read_text()
    code = "\n".join(ln for ln in src.split("\n")
                     if not ln.lstrip().startswith("#"))
    code = code.split('"""', 2)[2]          # past the module docstring, where the band IS named
    assert "0.86" not in code and "0.92" not in code
    assert det["forcing"]["scale_band_applied"] is False


def test_the_window_rule_is_flood_spines_boundary_and_says_so(det):
    from raincheck.flood_spine import PAD_H
    assert det["window"]["pad_hours"] == PAD_H == 3
    assert det["window"]["anchor_local_hour"] == 24 - PAD_H == 21
    assert det["window"]["interval"] == "(anchor, now]"


def test_the_frozen_k_is_a_count_of_cells_and_is_small_on_purpose(det):
    assert det["window"]["wet_cells_k"] == fd.WET_CELLS_K == 5
    assert det["window"]["wet_mm"] == 1.0
    assert "K = 5 Cells of 4,113" in det["window_note"]


# ---- one cycle --------------------------------------------------------------------------

def test_a_cycle_stamps_both_digests(ida, art, det):
    out = fd.cycle(None, ida["peak"], ida["hours"], _units(ida), art, det, temp_c=22.0,
                   wet_by_hour=ida["wet"])
    assert out["score_version"] == art["score_version"]
    assert out["detector_version"] == det["detector_version"]
    assert out["window"]["anchor"] == ida["ws"] and out["units"]


def test_a_cycle_that_produces_nothing_still_says_which_model_it_was(ida, art, det):
    out = fd.cycle(None, ida["peak"], [], _units(ida), art, det)
    assert out["window"]["state"] == fd.INSUFFICIENT_DATA and out["units"] == []
    assert out["score_version"] == art["score_version"] and out["detector_version"]


def test_the_winter_gate_suppresses_a_whole_cycles_tiers(ida, art, det):
    warm = fd.cycle(None, ida["peak"], ida["hours"], _units(ida), art, det, temp_c=22.0,
                   wet_by_hour=ida["wet"])
    cold = fd.cycle(None, ida["peak"], ida["hours"], _units(ida), art, det, temp_c=0.0,
                   wet_by_hour=ida["wet"])
    assert any(s["tier"] != fd.NONE for s in warm["units"])
    assert all(s["tier"] == fd.NONE for s in cold["units"])
    assert cold["winter"]["label"] == fd.WINTER_LABEL
    assert cold["window"]["anchor"] == ida["ws"], "the Window still exists; the tiers do not"


def test_a_cycle_is_pure(ida, art, det):
    a = fd.cycle(None, ida["peak"], ida["hours"], _units(ida), art, det, temp_c=22.0,
                   wet_by_hour=ida["wet"])
    b = fd.cycle(None, ida["peak"], ida["hours"], _units(ida), art, det, temp_c=22.0,
                   wet_by_hour=ida["wet"])
    assert a["latched"] == b["latched"] and a["cell_totals"] == b["cell_totals"]


def test_a_second_cycle_in_the_same_window_carries_the_latch(ida, art, det):
    one = fd.cycle(None, ida["peak"], ida["hours"], _units(ida), art, det, temp_c=22.0,
                   wet_by_hour=ida["wet"])
    assert one["latched"] and one["rolled"] is True
    two = fd.cycle(one, ida["peak"], ida["hours"], _units(ida), art, det, temp_c=22.0,
                   wet_by_hour=ida["wet"])
    assert two["rolled"] is False and set(two["latched"]) >= set(one["latched"])


# ---- real-root canaries (skipped without a data root) ------------------------------------

def test_the_fixture_still_matches_the_landed_precip_and_matrix(ida):
    root = data_root()
    if not (root / "gold" / "flood_matrix").exists():
        pytest.skip(f"no built gold/flood_matrix under {root}")
    import duckdb
    con = duckdb.connect()
    m = str(root / "gold" / "flood_matrix" / "part-00000.parquet")
    rows = con.execute(f"""SELECT cell, log1p_precip_total_mm FROM read_parquet('{m}')
        WHERE event_id = ? AND role = 'fit_cell' AND cell IN
        ({','.join(str(c) for c in ida['mx'])})""", [ida["event_id"]]).fetchall()
    assert len(rows) == len(ida["mx"])
    for cell, total in rows:
        assert ida["mx"][cell]["log1p_precip_total_mm"] == pytest.approx(total, abs=1e-9)


def test_the_committed_artifact_still_matches_a_rebuild():
    if not fd.DETECTOR.exists():
        pytest.skip("no committed detector constants artifact")
    on_disk = fd.constants()
    assert on_disk["detector_version"] == fd.detector_version(on_disk)
    fresh = fd.artifact()
    assert {k: fresh[k] for k in fd.DIGESTED if k != "canary"} == \
           {k: on_disk[k] for k in fd.DIGESTED if k != "canary"}
