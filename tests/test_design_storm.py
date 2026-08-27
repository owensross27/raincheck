"""Flood-build ticket 20: the design-storm sentence's data module.

Everything here is pure (no network, no data root), so every claim is a data assertion.
The intensity literals appear in THIS file as the independent side (flood 17's rule: a
literal in the test, the value read from the module under test) - and an AST test asserts
they appear nowhere in the shipped code, which must derive them from
`stormwater_extent.SCENARIOS`.
"""
import ast
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from raincheck import design_storm as ds

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


# ---- the scenario table, derived and never retyped -----------------------------------

def test_the_three_intensities_are_dep_values_in_mm():
    """1.77 / 2.13 / 3.66 in/hr are 44.96 / 54.10 / 92.96 mm in one hour (forecast 01,
    measured from DEP's own methodology source). The literals live HERE, as the oracle."""
    rows = ds.scenarios()
    assert [(s["scenario"], s["rain_in_hr"], s["mm_1h"]) for s in rows] == [
        ("limited", 1.77, 44.96), ("moderate", 2.13, 54.1), ("extreme", 3.66, 92.96)]


def test_exactly_one_extent_is_openable_and_it_is_moderate_at_current_sea_level():
    """1.77 is an unreadable compressed FGDB and 3.66 exists only at 2080 SLR - a bracket
    that implied three drawable rungs would be pointing at maps nobody can open."""
    rows = ds.scenarios()
    assert [s["scenario"] for s in rows if s["extent_open"]] == ["moderate"]
    by = {s["scenario"]: s for s in rows}
    assert "unreadable" in by["limited"]["reason"]
    assert "2080" in by["extreme"]["reason"]
    assert "reason" not in by["moderate"]


def test_a_scenario_with_two_horizons_folds_to_one_rate(monkeypatch):
    """Qualifier 3: the rainfall figure is identical at both sea levels, so Moderate is
    ONE row with both horizons - and the fold RAISES rather than picking a side if DEP
    ever breaks that."""
    by = {s["scenario"]: s for s in ds.scenarios()}
    assert by["moderate"]["horizons"] == ["2050", "current"]
    from raincheck import stormwater_extent as se
    broken = tuple(se.Scenario(s.scenario, s.horizon,
                               s.rain_in_hr + (1.0 if s.horizon == "2050" else 0.0),
                               s.dataset) for s in se.SCENARIOS)
    monkeypatch.setattr(se, "SCENARIOS", broken)
    ds.scenarios.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="rates across horizons"):
            ds.scenarios()
    finally:
        monkeypatch.undo()
        ds.scenarios.cache_clear()


def test_the_rates_are_read_from_flood_build_19_and_never_retyped():
    """21a's AST pattern: strip every string literal, then the inch figures - and the
    25.4 conversion, whose one home is `flood_obs.MM_PER_INCH` - must not survive in the
    code of this module or of the writer that threads it."""
    from raincheck import flood_panel as fp

    for mod in (ds, fp):
        tree = ast.parse(Path(mod.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                node.value = ""
        code = ast.unparse(tree)
        for lit in ("1.77", "2.13", "3.66", "44.96", "54.1", "92.96", "25.4"):
            assert lit not in code, f"{lit} is retyped in {mod.__name__}; derive it"


def test_importing_this_module_does_not_import_the_heavy_batch_module():
    """The live pod is limited to 768 Mi; `stormwater_extent` builds a pyproj Transformer
    at import time and pulls `features` with it. The import is paid lazily, once per
    process, inside `scenarios()` - never at module import. (pyproj itself is NOT in the
    pin: `query` -> `ref` already imports it, so it is on flood_panel's existing graph.)"""
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; import raincheck.design_storm; "
         "bad = {m for m in ('raincheck.stormwater_extent', 'raincheck.features') "
         "if m in sys.modules}; sys.exit(1 if bad else 0)"],
        capture_output=True)
    assert r.returncode == 0, r.stderr.decode()


# ---- the bracket ----------------------------------------------------------------------

def test_the_bracket_is_the_highest_intensity_reached_and_absent_below_limited():
    """The live base rate (456,543 Cell-hours measured): below Limited essentially
    always - 53.93 mm was the whole window's maximum. The wording is sized for that:
    below every scenario there is NO bracket, not a fourth label."""
    assert ds.bracket(0.5) is None
    assert ds.bracket(44.95) is None
    assert ds.bracket(44.96) == "limited"
    assert ds.bracket(53.93) == "limited"
    assert ds.bracket(54.1) == "moderate"
    assert ds.bracket(92.95) == "moderate"
    assert ds.bracket(92.96) == "extreme"
    assert ds.bracket(200.0) == "extreme"


def test_a_dry_or_unread_cell_has_no_design_storm_dict():
    """Absent-never-null, and 'it is raining 0 mm/h here' is not a sentence."""
    assert ds.cell(None) is None
    assert ds.cell(0.0) is None
    got = ds.cell(12.4)
    assert got == {"mm_1h": 12.4}, "below Limited there is no bracket key at all"
    assert ds.cell(60.0) == {"mm_1h": 60.0, "bracket": "moderate"}


# ---- the rates ------------------------------------------------------------------------

def _rows():
    old, new, future = NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW + timedelta(hours=1)
    return [
        {"cell": 0x8a2a100d2c47fff, "hour_end_utc": old, "mm_1h": 9.0},
        {"cell": 0x8a2a100d2c47fff, "hour_end_utc": new, "mm_1h": 2.5},
        {"cell": 0x8a2a100d2d67fff, "hour_end_utc": new, "mm_1h": None},
        {"cell": 0x8a2a100d2d67fff, "hour_end_utc": future, "mm_1h": 99.0},
        {"cell": 0x8a2a100d2ce7fff, "hour_end_utc": new, "mm_1h": 0.0},
    ]


def test_rates_are_the_newest_landed_hour_keyed_by_hex():
    """Newest hour <= now (a future hour has not landed); a NULL mm_1h is missing, not
    dry, so it carries no rate; a MEASURED 0.0 is dry and DOES carry one (`cell()` is
    what turns dry into an absent key); keys are the hex spelling the serving boundary
    uses."""
    got, newest = ds.rates(_rows(), NOW)
    assert newest == NOW - timedelta(hours=1)
    assert got == {format(0x8a2a100d2c47fff, "x"): 2.5,
                   format(0x8a2a100d2ce7fff, "x"): 0.0}


def test_no_hours_is_no_rates_and_no_asof():
    got, newest = ds.rates([], NOW)
    assert got == {} and newest is None
    assert "asof" not in ds.block(newest)


# ---- the block and its strings --------------------------------------------------------

def test_the_sentence_anchors_on_the_open_scenario_with_derived_numbers():
    b = ds.block(NOW)
    assert b["asof"] == NOW.isoformat()
    s = b["display"]["sentence"]
    assert "{mm_1h}" in s and "Moderate" in s and "54.10 mm/h" in s
    assert "{bracket}" in b["display"]["bracket_sentence"]
    assert [r["scenario"] for r in b["scenarios"]] == ["limited", "moderate", "extreme"]


def test_the_bracket_note_names_why_the_other_two_cannot_be_drawn():
    note = ds.block(None)["display"]["bracket_note"]
    assert "Moderate" in note and "Limited" in note and "Extreme" in note
    assert "unreadable" in note and "2080" in note


def test_the_strings_quote_no_frequency_and_do_not_restate_the_page_honesty_line():
    """Qualifier 1: DEP's values are climate-adjusted, sitting above the Atlas 14
    frequencies whose names they carry - quote DEP's label OR the frequency, never both.
    These strings quote labels only. And frontend2 03's zone legend already carries the
    planning-grade caveat; saying it again in different words would put two slightly
    different versions of one claim on one page."""
    blob = " ".join(ds.block(NOW)["display"].values())
    for banned in ("-year", "Atlas", "return period",
                   "not an observation of water", "site-specific"):
        assert banned not in blob, f"{banned!r} does not belong in these strings"
    assert "climate-adjusted" in blob


def test_the_extent_note_bounds_the_claim_to_intensity_versus_intensity():
    """Qualifier 2: the hyetograph's shape and duration are never stated, so reaching
    54.10 mm in an hour must not be read as reproducing the drawn extent."""
    note = ds.block(NOW)["display"]["extent_note"]
    assert "does not reproduce" in note


# ---- the snapshot and the log fragment ------------------------------------------------

def test_read_summarises_only_the_cells_actually_raining():
    got = ds.read(_rows(), NOW)
    assert set(got) == {"block", "rates", "summary"}
    assert got["summary"] == {"cells": 1, "max_mm_1h": 2.5}
    dry = ds.read([], NOW)
    assert dry["summary"] == {"cells": 0} and dry["rates"] == {}


def test_the_log_fragment_is_one_field_on_the_one_line():
    assert ds.line(None) == "ds=0"
    assert ds.line({"cells": 0}) == "ds=0"
    assert ds.line({"cells": 3, "max_mm_1h": 12.4}) == "ds=3@12.4"
