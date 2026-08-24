"""Flood-build ticket 07: the coastal rule layer.

Two seams, the same split ticket 03's tests use. The arithmetic — the STND -> NAVD88
conversion, the geodesic assignment, the QC fallback, the min-over-children aggregate —
is tested on hand-checked values with no network and no data root. The Unit table and the
datum-sanity pair are tested against the REAL root and skip where there is none: 3 and 103
were measured on the real DEM, and a temp root has no elevations to reproduce them from.

The Sandy validation deliberately has no test. It is descriptive — one coastal event, its
labels barred from the fits — and `research/flood-07-coastal.md` is where it is published.
"""
from pathlib import Path

import pytest

from raincheck import flood_coastal as fc
from raincheck import flood_spine
from raincheck.paths import data_root


# ---- the frozen constants and the arithmetic -----------------------------------


def test_the_three_thresholds_convert_to_navd88():
    """The hand-checked margin: the Battery's published minor stage is 10.49 ft on station
    datum and its NAVD88 datum sits 6.06 ft above that same zero, so minor flood is 4.43 ft
    NAVD88 — the number ticket 03 independently found exactly 3 entrances below."""
    assert fc.minor_navd88_ft("8518750") == pytest.approx(4.43)
    assert fc.minor_navd88_ft("8516945") == pytest.approx(5.80)
    assert fc.minor_navd88_ft("8531680") == pytest.approx(3.88)
    # every threshold is BELOW its published stage: an offset applied with the wrong sign
    # would raise all three by twice the offset and quietly make every asset look safe
    for s, g in fc.GAUGES.items():
        assert fc.minor_navd88_ft(s) < g["nws_minor_stnd_ft"]


def test_kings_point_inversion_is_recorded_where_the_constant_lives():
    """The NOS/NWS inversion is real published data. It has to stay written down next to
    the constants, or the next cross-station rule 'fixes' it into a bug."""
    src = Path(fc.__file__).read_text()
    head = src[:src.index("def minor_navd88_ft")]
    assert "23.39" in head and "23.55" in head


def test_assignment_is_the_geodesic_nearest_gauge():
    """Three anchors, one per gauge, each unambiguous: South Ferry is on top of the
    Battery, Flushing sits under Kings Point, Tottenville is the Staten Island tip."""
    assert fc.assign(-74.013, 40.702)[0] == "8518750"    # South Ferry
    assert fc.assign(-73.830, 40.759)[0] == "8516945"    # Flushing-Main St
    assert fc.assign(-74.252, 40.512)[0] == "8531680"    # Tottenville
    # a gauge is nearest to itself, at zero distance
    for s, g in fc.GAUGES.items():
        station, km = fc.assign(g["lon"], g["lat"])
        assert station == s and km == pytest.approx(0.0, abs=1e-6)


def test_the_stage_is_frozen_once_and_shared_with_the_spine():
    fc.check_shared_thresholds()
    assert set(flood_spine.NWS_MINOR_STND_FT) <= set(fc.GAUGES)
    for station, stnd in flood_spine.NWS_MINOR_STND_FT.items():
        assert fc.GAUGES[station]["nws_minor_stnd_ft"] == stnd


def test_a_split_threshold_fails_the_build(monkeypatch):
    """The whole point of the shared-constant check: moving ONE copy has to be loud."""
    bent = {s: dict(g) for s, g in fc.GAUGES.items()}
    bent["8518750"]["nws_minor_stnd_ft"] = 10.50
    monkeypatch.setattr(fc, "GAUGES", bent)
    with pytest.raises(RuntimeError, match="threshold split at 8518750"):
        fc.check_shared_thresholds()


def test_elevation_applies_the_ring_fallback_only_to_flagged_rows():
    good = {"grade_ok": True, "elev_ft": 12.5, "ring15_med_m": 0.0}
    assert fc.elevation_ft(good) == 12.5  # a passing row keeps its canonical sample
    flagged = {"grade_ok": False, "elev_ft": -34.4, "ring15_med_m": 3.0}
    assert fc.elevation_ft(flagged) == pytest.approx(3.0 * fc.features.US_SURVEY_FT)
    nodata = {"grade_ok": True, "elev_ft": None, "ring15_med_m": 2.0}
    assert fc.elevation_ft(nodata) == pytest.approx(2.0 * fc.features.US_SURVEY_FT)
    assert fc.elevation_ft({"grade_ok": False, "elev_ft": 1.0, "ring15_med_m": None}) is None


# ---- the Unit table, against the real root -------------------------------------


@pytest.fixture(scope="module")
def root() -> Path:
    r = data_root()
    if not (r / "silver" / "asset_features").exists():
        pytest.skip(f"no built silver/asset_features under {r}: run make features, or point "
                    "RAINCHECK_ARCHIVE_ROOT at a data root that has one")
    return r


@pytest.fixture(scope="module")
def margins(root) -> list[dict]:
    return fc.unit_margins(root)


def test_grain_is_one_row_per_scored_unit(margins):
    ids = [m["asset_id"] for m in margins]
    assert len(ids) == len(set(ids)) == fc.EXPECT["units"] == 15166
    assert ids == sorted(ids)
    kinds = {k: sum(m["kind"] == k for m in margins) for k in {m["kind"] for m in margins}}
    assert kinds == {"complex": 445, "bus_stop": 13370, "cell": 1351}  # no Carriers


def test_margin_is_the_subtraction_and_nothing_else(margins):
    for m in margins:
        assert m["threshold_navd88_ft"] == fc.minor_navd88_ft(m["gauge"])
        if m["surge_margin_ft"] is None:
            assert m["elev_navd88_ft"] is None and m["n_support"] == 0
        else:
            assert m["surge_margin_ft"] == pytest.approx(
                m["elev_navd88_ft"] - m["threshold_navd88_ft"], abs=5e-4)


def test_datum_sanity_is_three_not_one_hundred_and_three(root):
    """The check the ticket pins here, where elevations and thresholds first meet. 3 is
    ticket 03's independently measured count; 103 is what the same data says if the
    published STND stage is compared straight against a NAVD88 elevation."""
    d = fc.datum_sanity(root)
    assert d == {"navd88": fc.EXPECT["datum_navd88"], "naive_stnd": fc.EXPECT["datum_naive_stnd"]}
    assert d["navd88"] == 3 and d["naive_stnd"] == 103


def test_a_complex_is_the_minimum_over_its_own_entrances(root, margins):
    """The worst doorway, not the average one — and drawn from that complex's OWN
    entrances, which is the join a parent_asset_id typo would silently break."""
    import pyarrow.parquet as pq
    feats = {r["asset_id"]: r for r in pq.read_table(
        root / "silver" / "asset_features",
        columns=["asset_id", "elev_ft", "ring15_med_m", "grade_ok"]).to_pylist()}
    assets = pq.read_table(root / "ref" / "assets",
                           columns=["asset_id", "kind", "parent_asset_id"]).to_pylist()
    kids: dict[str, list] = {}
    for a in assets:
        if a["kind"] == "entrance":
            e = fc.elevation_ft(feats[a["asset_id"]])
            if e is not None:
                kids.setdefault(a["parent_asset_id"], []).append(e)
    checked = 0
    for m in margins:
        if m["kind"] != "complex":
            continue
        want = min(kids[m["asset_id"]]) if kids.get(m["asset_id"]) else None
        assert m["elev_navd88_ft"] == (None if want is None else pytest.approx(want))
        checked += 1
    assert checked == 445


def test_no_fitted_terms_anywhere():
    """The ticket's standing constraint: this layer is arithmetic. Nothing here may learn
    a coefficient from the ~15 coastal events."""
    src = Path(fc.__file__).read_text().lower()
    for banned in ("sklearn", "logistic", "coef", "fit(", "regress"):
        assert banned not in src, banned


def test_units_without_elevation_are_null_never_zero(margins):
    """A Cell with no point child inside it has NO margin. Publishing 0.0 would put it
    exactly at minor flood stage — the single most alarming value the column can take."""
    empty = [m for m in margins if m["n_support"] == 0]
    assert empty and all(m["surge_margin_ft"] is None for m in empty)
    assert {m["kind"] for m in empty} == {"cell", "bus_stop"}  # every complex has entrances
