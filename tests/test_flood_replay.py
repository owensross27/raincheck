"""Flood-build ticket 12, testing seam 2: the replay harness on ticket 11's own fixture.

No network and no data root for anything above the canaries at the bottom. The precip
fixture is the SAME real AORC slice ticket 11 shipped (`flood_detect_ida.json`: Ida's
citywide wet-Cell series, four Cells' hourly mm and those Cells' `gold/flood_matrix` rows),
so "the replay of the fixture event day reproduces ticket 11's results exactly" is an
assertion about the shipped numbers rather than about a stub this file shaped to agree.

The four traps this ticket's checklist turns on each get a test that FAILS if the harness
stops honouring them: the citywide series is always passed, a permanently dark Cell is
unforced and never a hole, a capped or insufficient Window is excluded AND counted, and the
live walk is never bent into agreeing with the calendar window.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from raincheck import flood_detect as fd
from raincheck import flood_exposure as fe
from raincheck import flood_replay as fr
from raincheck.paths import data_root

FIX = Path(__file__).parent / "fixtures" / "flood_detect_ida.json"
SRC = Path(__file__).parent.parent / "src" / "raincheck" / "flood_replay.py"
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
def art() -> dict:
    return fe.coefficients()


@pytest.fixture(scope="module")
def det() -> dict:
    return fd.constants()


def _by_hour(rows) -> dict:
    out: dict = {}
    for r in rows:
        out.setdefault(r["hour_end_utc"], []).append(r)
    return out


def _units(ida, flooded=()) -> list[dict]:
    """The fixture's Units in the shape `gold/flood_matrix` hands the harness, with an
    explicit `flooded` label so the skill arithmetic has something to score against."""
    us = [dict(p) | {"flooded": p["asset_id"] in flooded} for p in ida["points"]]
    cell = next(iter(ida["mx"]))
    for c, m in ida["mx"].items():
        us.append({"asset_id": f"cell:{c:x}", "kind": "cell", "cell": c,
                   "complex_id": None, "flooded": f"cell:{c:x}" in flooded}
                  | {k: m[k] for k in ("share_deep", "share_nuisance",
                                       "share_not_analyzed", "density_311_3y")})
    us.append({"asset_id": ida["complex_asset_id"], "kind": "complex",
               "complex_id": ida["complex_id"], "cell": cell,
               "flooded": ida["complex_asset_id"] in flooded})
    return us


def _event(ida) -> dict:
    return {"event_id": ida["event_id"], "window_start_utc": ida["ws"],
            "window_end_utc": ida["we"], "event_class": "pluvial", "n_days": 2,
            "day_start": ida["ws"].date(), "in_matrix": True}


def _replay(ida, art, det, **kw):
    return fr.replay(_event(ida), kw.pop("wet", ida["wet"]), kw.pop("temp", {}),
                     _by_hour(kw.pop("hours", ida["hours"])),
                     kw.pop("units", _units(ida)), art, det,
                     kw.pop("score_version", art["score_version"]))


# ---- the runnable check the checklist names ---------------------------------------------

def test_the_fixture_event_day_reproduces_ticket_elevens_window_features_exactly(ida):
    """CHECKLIST ITEM 4. Through the harness's OWN slice — not a hand-built row list — the
    live Window at the offline anchor rebuilds `gold/flood_matrix`'s Ida row for every
    fixture Cell. Ticket 11 measured zero mismatches at 1e-6 over all 1,351 fit Cells; this
    is that claim, on the four Cells the fixture carries, asserted through this module."""
    rows = fr.slice_rows(_by_hour(ida["hours"]), ida["ws"], ida["we"])
    f = fd.window_features(rows, ida["ws"], ida["we"])
    assert set(f["cells"]) == set(ida["mx"])
    for cell, want in ida["mx"].items():
        got = fd.precip_terms(f["cells"][cell])
        for term in ("log1p_precip_max_mm_1h", "log1p_precip_total_mm",
                     "log1p_antecedent_mm_24h"):
            assert got[term] == pytest.approx(want[term], abs=1e-6), (cell, term)


def test_the_fixture_day_replays_to_a_zero_delta_because_its_anchor_is_the_calendar_one(ida, art, det):
    """Ida is the clean case ticket 11 named: mid-storm the live walk lands exactly on
    `window_start`, so every signed live-minus-offline delta is 0. An event whose anchor
    moved would show non-zero deltas, which is the measurement, not a defect."""
    r = _replay(ida, art, det)
    assert r["anchor"] == ida["ws"]
    d = fr.deltas(r["features"], ida["mx"])
    for term, s in d.items():
        assert s["n"] == len(ida["mx"])
        assert s["share_zero"] == 1.0, (term, s)


def test_live_eta_at_the_replayed_window_equals_the_offline_event_eta(ida, art):
    """The converges-from-below contract, asserted through the harness's slice: `fe.eta` is
    THE function that built `gold/flood_exposure`, so the offline and live numbers cannot
    drift apart and any delta this build publishes is the WINDOW moving."""
    f = fd.window_features(fr.slice_rows(_by_hour(ida["hours"]), ida["ws"], ida["we"]),
                           ida["ws"], ida["we"])
    m = art["models"]["cell"]
    for cell, want in ida["mx"].items():
        live = fe.eta(m, fd.unit_feats({"kind": "cell"} | want,
                                       fd.precip_terms(f["cells"][cell])))
        assert live == pytest.approx(fe.eta(m, want), abs=1e-6), cell


# ---- MUST: the citywide series is always passed -----------------------------------------

def test_every_cycle_is_handed_the_citywide_series_and_never_defaults_it(ida, art, det, monkeypatch):
    """`cycle(wet_by_hour=None)` counts wet Cells off the `cell_hours` it was given, which
    is right in production and redefines "citywide" as "these four Cells" here. Every call
    this harness makes must carry the real series."""
    seen = []
    real = fd.cycle
    monkeypatch.setattr(fd, "cycle", lambda *a, **k: (seen.append(k), real(*a, **k))[1])
    _replay(ida, art, det)
    assert seen and all(k.get("wet_by_hour") is ida["wet"] for k in seen)


def test_defaulting_the_citywide_series_off_a_cell_subset_shuts_the_citywide_gate(ida):
    """Why the test above is not decoration — and WHERE the damage lands, which is not
    where it looks. Ticket 11 measured the anchor as nearly K-inert (88 of 166 events at
    K = 5, 89 at K = 41), so a subset can walk to the SAME anchor and look fine; the
    citywide-ACTIVE gate is what K is frozen small for, and off four Cells it never arms.
    A replay that let `cycle` default would tier nothing and report it as a quiet storm."""
    subset = fd.wet_counts(ida["hours"])
    assert max(subset.values()) < fd.WET_CELLS_K <= max(ida["wet"].values())
    assert fd.dry_run_hours(ida["wet"], ida["peak"]) == 0, "the city IS raining at the peak"
    assert fd.dry_run_hours(subset, ida["peak"]) != 0, "counted off four Cells it is not"


# ---- MUST: the dark Cells are UNFORCED, not holes ----------------------------------------

def test_a_permanently_dark_cell_is_unforced_and_never_a_hole(ida):
    """AORC's 168 dark Cells carry NULL mm_1h in every hour of every month. Counting them
    as holes reports HOLES on a complete table forever, so the harness passes the NULL rows
    through rather than filtering them out in SQL — filtering would report `unforced_cells:
    0` and look identical otherwise."""
    dark = [{"cell": -7, "hour_end_utc": h, "mm_1h": None}
            for h in sorted(_by_hour(ida["hours"]))]
    f = fd.window_features(fr.slice_rows(_by_hour(ida["hours"] + dark), ida["ws"], ida["we"]),
                           ida["ws"], ida["we"])
    assert f["unforced_cells"] == 1 and -7 not in f["cells"]
    assert f["state"] == fd.OK and f["coverage"] == 1.0


def test_dropping_the_null_rows_hides_the_unforced_count(ida):
    """The mirror: the same Window built WITHOUT the NULL rows is byte-identical except that
    it can no longer say the dark Cell exists. That is the quiet lie the SQL avoids."""
    kept = fd.window_features(fr.slice_rows(_by_hour(ida["hours"] + [
        {"cell": -7, "hour_end_utc": h, "mm_1h": None}
        for h in sorted(_by_hour(ida["hours"]))]), ida["ws"], ida["we"]),
        ida["ws"], ida["we"])
    dropped = fd.window_features(fr.slice_rows(_by_hour(ida["hours"]), ida["ws"], ida["we"]),
                                 ida["ws"], ida["we"])
    assert kept["cells"] == dropped["cells"] and kept["coverage"] == dropped["coverage"]
    assert kept["unforced_cells"] == 1 and dropped["unforced_cells"] == 0


# ---- the generator trap ------------------------------------------------------------------

def test_the_slice_is_a_list_because_cycle_reads_cell_hours_twice(ida, art, det):
    """`cycle` takes the newest stamp off `cell_hours` and THEN hands the same object to
    `window_features`. A generator is empty by the second pass and the Window comes back
    with no Cells, coverage 1.0 and nothing flagged — indistinguishable from a quiet night.
    This pins both halves: the harness returns a list, and the generator really does lie."""
    rows = fr.slice_rows(_by_hour(ida["hours"]), ida["ws"], ida["peak"])
    assert isinstance(rows, list) and rows
    good = fd.cycle(None, ida["peak"], rows, _units(ida), art, det, temp_c=22.0,
                    wet_by_hour=ida["wet"])
    lazy = fd.cycle(None, ida["peak"], (r for r in rows), _units(ida), art, det,
                    temp_c=22.0, wet_by_hour=ida["wet"])
    assert good["features"]["cells"] and not lazy["features"]["cells"]
    assert good["latched"] and not lazy["latched"]


# ---- MUST: capped / INSUFFICIENT Windows are excluded AND counted -------------------------

def test_an_insufficient_pad_stops_the_walk_and_the_cycle_is_counted_not_scored(ida, art, det):
    """A missing pad stamp is INSUFFICIENT_DATA: `cycle` returns before `window_features`,
    so nothing is evaluated. The harness must still COUNT the cycle — an unreplayable hour
    that vanishes from the denominator flatters every rate above it."""
    holed = {h: v for h, v in ida["wet"].items() if h != ida["ws"]}
    r = _replay(ida, art, det, wet=holed)
    assert r["states"].get(fd.INSUFFICIENT_DATA), r["states"]
    assert sum(v for k, v in r["states"].items()
               if not k.startswith("feature_")) == r["cycles"]


def test_a_capped_window_is_its_own_state_and_is_counted_too(ida, art, det):
    """Six days walked with no citywide-dry 21:00 pad. Distinct from INSUFFICIENT_DATA,
    which is "we cannot see", and both are excluded from the skill numbers."""
    lo = min(ida["wet"]) - timedelta(days=fd.CAP_DAYS + 2)
    soaked = {h: 99 for h in fr.hours(lo, ida["we"])}
    r = _replay(ida, art, det, wet=soaked)
    assert r["states"].get(fd.WINDOW_CAPPED) == r["cycles"]
    assert not r["union"], "a capped Window evaluates nothing and can flag nothing"


def test_the_excluded_table_reports_both_states_with_a_reason():
    why = fr.excluded([], [])["why"]
    assert set(why) == {fd.WINDOW_CAPPED, fd.INSUFFICIENT_DATA, fd.HOLES}
    assert "still" in why[fd.HOLES], "a holed Window is still a Window and is evaluated"


# ---- MUST: the walk is never bent into agreeing with the calendar window ------------------

def test_the_harness_never_substitutes_the_calendar_window_for_the_live_anchor():
    """The one edit that would quietly destroy this ticket's measurement: handing
    `window_features` the offline `window_start` instead of the anchor `walk` returned. The
    only place `window_start_utc` reaches an anchor slot in this module is the CHECK that
    the live Window still covers the event."""
    src = SRC.read_text()
    assert "fd.walk(" in src
    for bad in ("slice_rows(by_hour, ws,", "window_features(rows, ws",
                'anchor = ev["window_start_utc"]', 'w["anchor"] = '):
        assert bad not in src, bad


def test_a_disagreeing_anchor_is_recorded_as_a_signed_day_delta_and_not_an_error(ida):
    """Population-wide the live anchor is usually one day EARLIER, because the evening
    before the storm-eve was also wet. The harness reports the sign; it does not correct."""
    a = fr.agreement(_event(ida), ida["wet"])
    assert a["day_delta"] == 0 and a["citywide_rain"] is True
    shifted = dict(_event(ida)) | {
        "window_start_utc": ida["ws"] + timedelta(days=1),
        "window_end_utc": ida["we"]}
    assert fr.agreement(shifted, ida["wet"])["day_delta"] == -1


def test_the_agreement_note_says_the_disagreement_is_the_rule_working():
    rows = [{"agreement": {"citywide_rain": True, "day_delta": -1, "state": fd.OK}},
            {"agreement": {"citywide_rain": True, "day_delta": 0, "state": fd.OK}},
            {"agreement": {"citywide_rain": False, "day_delta": None, "state": fd.OK}}]
    w = fr.window_agreement(rows)
    assert w["events"] == 3 and w["with_citywide_rain"] == 2
    assert w["day_delta"] == {"-1": 1, "0": 1} and w["agree_exactly"] == 1
    assert "observation-derived" in w["note"]


# ---- the readout: the union over cycles, not the last one ---------------------------------

def test_the_readout_is_the_union_over_cycles_and_not_the_standing_set_at_the_end(ida, art, det):
    """A tier LATCHES within its Window and the Window ROLLS once the city has been dry
    long enough, so the set standing at `window_end` is the morning after the storm. Ida's
    last replayed cycle stands at zero flags with 264 mm behind it; the union is what a
    subscriber actually received."""
    r = _replay(ida, art, det)
    assert r["union"], "the storm flagged something"
    assert r["published"], "the last cycle still publishes rows"
    assert r["states"].get(fd.OK) == r["cycles"]
    assert r["end_flagged"] == 0, "Ida's Window has rolled by window_end"
    assert len(r["union"]) > r["end_flagged"], \
        "reading the standing set at window_end measures the morning after the storm"
    assert max(r["peak"].values()) <= len(r["union"])


def test_a_cycle_that_flags_nothing_contributes_nothing_to_the_union(ida, art, det):
    """A citywide-dry replay: every gate is shut, so no Window in it can raise a tier."""
    dry = {h: 0 for h in ida["wet"]}
    r = _replay(ida, art, det, wet=dry)
    assert r["states"].get(fd.OK) == r["cycles"] and not r["union"]


# ---- the arithmetic ------------------------------------------------------------------------

def test_skill_counts_hits_and_false_alarms_against_the_matrix_label(ida, art, det):
    us = _units(ida, flooded={f"cell:{c:x}" for c in ida["mx"]})
    r = _replay(ida, art, det, units=us)
    s = fr.skill(us, r["union"], "cell")
    assert s["rows"] == len(ida["mx"]) and s["positives"] == len(ida["mx"])
    assert s["base_rate"] == 1.0
    e = s[fd.ELEVATED]
    assert e["tp"] + e["fp"] == e["flagged"] and e["fp"] == 0
    assert e["pod"] == pytest.approx(e["tp"] / s["positives"])


def test_the_high_row_counts_the_high_band_alone_and_the_elevated_row_counts_both(ida):
    """`tiers` puts HIGH inside the ELEVATED cut, so the two rows are nested and NOT equal:
    an ELEVATED Unit belongs to the ELEVATED-and-above row only. Folding ELEVATED into the
    HIGH row would publish the top-2% cut alarming at the top-10% volume, which is the one
    number in this table a reader would use to argue the cut is affordable."""
    us = [u for u in _units(ida) if u["kind"] == "bus_stop"]
    a, b = us[0]["asset_id"], us[1]["asset_id"]
    s = fr.skill(us, {a: fd.ELEVATED, b: fd.HIGH}, "bus_stop")
    assert s[fd.ELEVATED]["flagged"] == 2 and s[fd.HIGH]["flagged"] == 1


def test_high_is_a_subset_of_elevated_and_above(ida, art, det):
    us = _units(ida)
    r = _replay(ida, art, det, units=us)
    for kind in ("cell", "bus_stop"):
        s = fr.skill(us, r["union"], kind)
        assert s[fd.HIGH]["flagged"] <= s[fd.ELEVATED]["flagged"]
        assert s[fd.HIGH]["tp"] <= s[fd.ELEVATED]["tp"]


def test_pooling_sums_the_counts_and_recomputes_the_rates():
    """Averaging per-event PODs weights a three-positive event the same as Ida, which is a
    statement about the event-size distribution and not about the model."""
    ev = [{"skill": {"cell": {"rows": 100, "positives": 4, "base_rate": 0.04,
                              fd.ELEVATED: {"flagged": 10, "tp": 4, "fp": 6},
                              fd.HIGH: {"flagged": 2, "tp": 2, "fp": 0}}}},
          {"skill": {"cell": {"rows": 900, "positives": 36, "base_rate": 0.04,
                              fd.ELEVATED: {"flagged": 90, "tp": 6, "fp": 84},
                              fd.HIGH: {"flagged": 18, "tp": 1, "fp": 17}}}}]
    p = fr.pooled(ev, "cell")
    assert p["rows"] == 1000 and p["positives"] == 40 and p["base_rate"] == 0.04
    assert p[fd.ELEVATED]["tp"] == 10 and p[fd.ELEVATED]["fp"] == 90
    assert p[fd.ELEVATED]["pod"] == 0.25 and p[fd.ELEVATED]["alert_rate"] == 0.1
    assert p[fd.ELEVATED]["csi"] == pytest.approx(10 / (100 + 40 - 10))
    mean_of_pods = (4 / 4 + 6 / 36) / 2
    assert p[fd.ELEVATED]["pod"] != pytest.approx(mean_of_pods), \
        "a mean of PODs weights a four-positive event like a thirty-six-positive one"


def test_the_lift_divides_by_that_universes_own_base_rate():
    """FLOOD 18'S RULE. Under location blocking B0's CSI IS the base rate, so CSI/base is
    the lift — and the same CSI in a universe with three times the base rate is a THIRD of
    the skill. A table that ranks alternatives on raw CSI ranks them backwards."""
    thin = fr.pooled([{"skill": {"cell": {"rows": 1000, "positives": 10, "base_rate": 0.01,
                                          fd.ELEVATED: {"flagged": 100, "tp": 5, "fp": 95},
                                          fd.HIGH: {"flagged": 0, "tp": 0, "fp": 0}}}}], "cell")
    fat = fr.pooled([{"skill": {"cell": {"rows": 1000, "positives": 30, "base_rate": 0.03,
                                         fd.ELEVATED: {"flagged": 100, "tp": 15, "fp": 85},
                                         fd.HIGH: {"flagged": 0, "tp": 0, "fp": 0}}}}], "cell")
    assert fat[fd.ELEVATED]["csi"] > thin[fd.ELEVATED]["csi"]
    assert fat[fd.ELEVATED]["lift_over_base_rate"] < thin[fd.ELEVATED]["lift_over_base_rate"]
    assert thin[fd.ELEVATED]["lift_over_base_rate"] == pytest.approx(
        thin[fd.ELEVATED]["csi"] / 0.01)


def test_the_signed_deltas_keep_their_sign():
    """Live MINUS offline. A longer live Window is a bigger total, and the sign is the
    whole content of the measurement."""
    feats = {"cells": {1: {"max_mm_1h": 4.0, "total_mm": 9.0, "antecedent_mm_24h": 0.0}}}
    off = {1: {"log1p_precip_max_mm_1h": 0.0, "log1p_precip_total_mm": 0.0,
               "log1p_antecedent_mm_24h": 1.0}}
    d = fr.deltas(feats, off)
    assert d["log1p_precip_total_mm"]["median"] > 0
    assert d["log1p_antecedent_mm_24h"]["median"] < 0
    assert fr.deltas(None, off) == {}


def test_summarise_reports_the_tails_and_the_sign_split():
    s = fr.summarise([-2.0, -1.0, 0.0, 1.0, 2.0])
    assert s["n"] == 5 and s["median"] == 0.0 and s["mean"] == 0.0
    assert s["share_positive"] == 0.4 and s["share_zero"] == 0.2
    assert fr.summarise([]) == {"n": 0}


# ---- the two point universes ---------------------------------------------------------------

def test_both_point_universes_are_named_because_their_base_rates_differ():
    """The detector publishes no entrance row, so its point universe is bus stops; flood
    09's `per_event.point` is bus stops AND entrances. Comparing a rate across the two
    without their base rates is exactly the trap flood 18 measured."""
    ref = fr.fits_reference()
    assert ref["pooled"]["point"]["rows"] == 783351
    assert "entrance" in fr.POINT_NOTE and "base rate" in fr.POINT_NOTE
    p = ref["pooled"]["point"]
    assert p["lift_over_base_rate"] == pytest.approx(p["csi"] / p["base_rate"])


def test_flood_nines_numbers_are_read_and_never_recomputed():
    """They are not superseded by this replay: one global out-of-fold cut is a different
    question from a per-cycle within-kind rank, and the comparison only works if both sides
    are quoted as their authors published them."""
    ref = fr.fits_reference()
    published = json.loads(fr.FITS.read_text())
    assert ref["fits_version"] == published["fits_version"]
    assert ref["gate_branch"] == "MODEL" and ref["split"] == "location_blocked"
    assert ref["pooled"]["point"]["tp"] == 381 and ref["pooled"]["point"]["fp"] == 8295
    assert ref["pooled"]["point"]["alert_rate"] == pytest.approx(0.0111, abs=5e-5)
    assert len(ref["per_event"]["cell"]) == len(published["per_event"]["cell"])


# ---- the verdict is Ross's ------------------------------------------------------------------

def test_this_module_never_writes_the_detector_artifact():
    """THE SHIPPING GATE'S OWN GUARD RAIL. Confirming the cutpoints or dropping v1 to
    rank-only bumps `detector_version`, which rolls every open Window — a decision this
    harness measures and Ross records. `fd.DETECTOR` must not appear here at all."""
    src = SRC.read_text()
    assert "DETECTOR" not in src, "the artifact's path is not even reachable from here"
    for bad in ("fd.build(", "fd.artifact(", "fd.detector_version(",
                'cutpoints"] =', 'provisional"] ='):
        assert bad not in src, bad
    writers = [ln.strip() for ln in src.split("\n") if ".write_text(" in ln]
    assert writers, "the harness does write its own two artifacts"
    assert all(ln.startswith(("out.write_text(", "doc.write_text(", "DOC.write_text("))
               for ln in writers), writers


def test_the_committed_detector_artifact_still_says_provisional(det):
    """If this ever reads False, the verdict has been recorded and this ticket's own
    framing is stale — which is a thing to notice, not to route around."""
    assert det["cutpoints"]["provisional"] is True
    assert det["display"]["cutpoints_confirmed_by"] == "flood-build ticket 12"


def test_the_published_verdict_block_states_who_records_it():
    """Rendered into the asset so a later reader cannot mistake a measurement for a
    decision."""
    v = {"question": "cutpoints confirmed, or v1 ships rank-only",
         "recorded_by": "[YOU] Ross, in his own session",
         "this_build_wrote_the_artifact": False, "note": "n"}
    assert v["question"] == "cutpoints confirmed, or v1 ships rank-only"
    assert SRC.read_text().count(v["question"]) == 1


# ---- the RadarOnly-vs-AORC chain -------------------------------------------------------------

def test_the_scale_band_is_read_from_flood_fits_and_not_retyped():
    from raincheck import flood_fits as ff
    src = SRC.read_text().split('"""', 2)[2]
    assert "ff.SCALE_BAND" in src
    assert "0.86" not in src and "0.92" not in src
    assert ff.SCALE_BAND == (0.86, 0.92)


# ---- real-root canaries (skipped without a data root) -------------------------------------

def _root_or_skip(*parts):
    root = data_root()
    if not Path(str(root)).joinpath(*parts).exists():
        pytest.skip(f"no {'/'.join(parts)} under {root}")
    return root


def test_the_event_universe_is_the_aorc_era_and_stops_where_aorc_does():
    """2026 has no AORC year, so its 11 union events cannot take this forcing at all. The
    era rule is `precip_flood_era`'s constant, imported rather than re-typed."""
    root = _root_or_skip("silver", "flood_events")
    from raincheck import duck
    evs = fr.events(duck.connect(), root)
    assert evs and all(e["day_start"].year <= fr.FIT_ERA_LAST_YEAR for e in evs)
    assert any(e["in_matrix"] for e in evs) and any(not e["in_matrix"] for e in evs)
    assert {e["event_class"] for e in evs if not e["in_matrix"]} and \
        {e["event_class"] for e in evs if e["in_matrix"]} == {"pluvial"}


def test_the_citywide_series_is_counted_over_the_whole_grid():
    """CITYWIDE MEANS THE WHOLE GRID. Not the fit Cells, not the scored Cells — the count
    has to be able to reach 4,113 or K = 5 is measuring something else."""
    root = _root_or_skip("silver", "precip_cell_hourly", "src=aorc")
    from raincheck import duck
    con = duck.connect()
    lo = datetime(2021, 9, 1, 20, tzinfo=UTC)
    wet = fr.citywide(con, root, lo, lo + timedelta(hours=4))
    assert len(wet) == 5 and max(wet.values()) > 3000
    n = con.execute(f"""SELECT count(DISTINCT cell) FROM read_parquet(
        '{root}/silver/precip_cell_hourly/src=aorc/month=2021-09/*.parquet')""").fetchone()[0]
    assert n == 4113


def test_the_live_table_is_deduped_to_the_newest_fetch_before_any_ratio():
    """`precip_live` re-fetches the newest stamp every tick and catches up on missing ones,
    so `live/precip_cell` holds several rows per (Cell, hour). Reading it without the
    newest-`fetched_at` rule multiplies every count by the tick frequency and turns the
    product ratio into a statement about how often the pod ran."""
    _root_or_skip("live", "precip_cell")
    root = _root_or_skip("silver", "precip_cell_hourly", "src=mrms")
    from raincheck import duck
    con = duck.connect()
    r = fr.forcing_ratio(con, root)
    assert r["measurable_directly"] is False
    assert r["aorc_mrms_overlapping_hours"] == 0
    rp = r["radaronly_over_pass2"]
    assert rp["paired_cell_hours"] == rp["paired_hours"] * 4113
    assert 0.5 < rp["ratio_wet_pairs"] < 1.5
    band = r["radaronly_over_aorc"]["band"]
    assert band[0] == pytest.approx(rp["ratio_wet_pairs"] * 0.86)
    assert band[1] == pytest.approx(rp["ratio_wet_pairs"] * 0.92)


def test_the_cell_hour_read_keeps_the_null_rows_so_unforced_can_be_counted():
    """The SQL half of the dark-Cell MUST. Every AORC hour has exactly 4,113 Cell rows and
    168 of them are NULL; a `WHERE mm_1h IS NOT NULL` in this read would leave `cells` and
    `coverage` untouched and silently zero `unforced_cells`, which is how a replay stops
    being able to tell UNFORCED from HOLED."""
    root = _root_or_skip("silver", "precip_cell_hourly", "src=aorc")
    from raincheck import duck
    lo = datetime(2021, 9, 1, 20, tzinfo=UTC)
    by_hour = fr.cell_rows(duck.connect(), root, lo, lo + timedelta(hours=1))
    assert len(by_hour) == 2
    for h, rows in by_hour.items():
        assert len(rows) == 4113, h
        assert sum(1 for r in rows if r["mm_1h"] is None) == 168, h
    f = fd.window_features(fr.slice_rows(by_hour, lo, lo + timedelta(hours=1)),
                           lo, lo + timedelta(hours=1))
    assert f["unforced_cells"] == 168 and len(f["cells"]) == 3945


def test_the_replayed_units_are_the_matrix_rows_and_carry_their_label():
    """The offline unit set, read rather than rebuilt: same assets, same static terms, same
    `flooded`. Only the three precip terms are recomputed live."""
    root = _root_or_skip("gold", "flood_matrix")
    from raincheck import duck
    us = fr.units(duck.connect(), root, "2021-09-01")
    assert us and {u["kind"] for u in us} == {"cell", "bus_stop", "entrance", "complex"}
    assert all("flooded" in u for u in us)
    cells = [u for u in us if u["kind"] == "cell"]
    assert cells and all(u["share_deep"] is not None for u in cells)


def test_the_published_asset_matches_this_modules_own_shape():
    """The committed artifact is the thing Ross reads; if it predates the code it is a
    stale ticket file with a version number."""
    if not fr.OUT.exists():
        pytest.skip("no built research/flood-12-replay.json")
    d = json.loads(fr.OUT.read_text())
    assert d["verdict"]["this_build_wrote_the_artifact"] is False
    assert d["detector_version"] == fd.constants()["detector_version"]
    assert d["cutpoints"]["provisional"] is True
    assert set(d["flag_volume"]) == {"cell", "bus_stop", "complex"}
    assert d["universe"]["replayed_with_evaluation"] >= 1
