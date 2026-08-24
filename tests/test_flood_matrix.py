"""Flood-build ticket 08: gold/flood_matrix, the (Unit, event) training table.

Seam 1 (DuckDB assertions over the written table) and seam 2 (pure functions on plain
mappings). No network and no new snapshots: the fixture root is ticket 05's — real
observations, a real spine, a real registry cut — with the three tables this ticket joins
PLANTED on top at known values, so every feature has an arithmetic answer:

  precip   for every Cell and every fixture Window: mm_1h = 2.0 everywhere, 99.0 on the
           hour STAMPED AT WINDOW OPEN (which covers the hour before the Window and must
           never reach a Window term) and 50.0 on the spike hour five hours in; mm_24h =
           7.0 at Window open and 999.0 at every other hour. So max = 50, total =
           2*(H-1)+50, antecedent = 7 — and a build that widened the Window to [open,
           close] or read the antecedent anywhere but the open hour lands 99 or 999.
  features one entrance per complex on `FALLBACK_CX` carries grade_ok = false with a ring,
           so the ring15_med fallback is the ONLY thing standing between that complex and
           an empty aggregate; `NO_DEM` carries neither and must be excluded with a count.
  cell     stormwater shares that sum to 1 per Cell.
"""
import calendar
import json
import math
import shutil
from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raincheck import (duck, features as ft, flood_labels as fl, flood_matrix as fm,
                       flood_obs as fo)
from test_flood_labels import label_root  # noqa: F401 — the fixture, reused whole

ASOF = fo.ASOF
SPIKE_H = 5              # hours after Window open; strictly inside every fixture Window
AT_OPEN_MM, SPIKE_MM, FLAT_MM = 99.0, 50.0, 2.0
ANTECEDENT_MM, OTHER_24H = 7.0, 999.0


def _plant_features(root: Path) -> tuple[str, list[str]]:
    """silver/asset_features for every point asset in the fixture registry.

    Returns (the complex whose entrances are ALL flagged, the assets with no DEM at all).
    """
    assets = pq.read_table(root / "ref" / "assets",
                           columns=["asset_id", "kind", "cell", "complex_id"]).to_pylist()
    points = sorted((a for a in assets if a["kind"] in ("entrance", "bus_stop")),
                    key=lambda a: a["asset_id"])
    by_cx: dict[str, list[dict]] = {}
    for a in points:
        if a["kind"] == "entrance" and a["complex_id"]:
            by_cx.setdefault(a["complex_id"], []).append(a)
    # a complex with several entrances, so "zero grade_ok children" is a real aggregate
    fallback_cx = sorted(c for c, kids in by_cx.items() if len(kids) >= 2)[0]
    flagged = {a["asset_id"] for a in by_cx[fallback_cx]}
    no_dem = [a["asset_id"] for a in points if a["kind"] == "bus_stop"][:3]

    rows = []
    for i, a in enumerate(points):
        ring = 3.0 + (i % 7)
        if a["asset_id"] in no_dem:      # outside the DEM footprint: no sample, no ring
            e17, e14, ring, ok = None, None, None, False
        elif a["asset_id"] in flagged:   # flagged, ring present -> the fallback fires
            e17, e14, ok = 40.0, 10.0, False
        else:
            e17, e14, ok = ring + 1.5, ring + 1.4, True
        rows.append({"asset_id": a["asset_id"], "elev_2017_m": e17, "elev_2014_m": e14,
                     "elev_ft": None if e17 is None else e17 * ft.US_SURVEY_FT,
                     "ring15_min_m": ring, "ring15_med_m": ring,
                     "ring15_n": 0 if ring is None else 8, "grade_ok": ok,
                     "stormwater_cat": ("not-analyzed" if a["asset_id"] in no_dem
                                        else ("deep", "nuisance", "analyzed-none")[i % 3]),
                     "cell": a["cell"], "src_asof": ft.SRC_ASOF,
                     "frozen_at": ft.FEATURES_FROZEN})
    schema = pa.schema([("asset_id", pa.string()), ("elev_2017_m", pa.float64()),
                        ("elev_2014_m", pa.float64()), ("elev_ft", pa.float64()),
                        ("ring15_min_m", pa.float64()), ("ring15_med_m", pa.float64()),
                        ("ring15_n", pa.int8()), ("grade_ok", pa.bool_()),
                        ("stormwater_cat", pa.string()), ("cell", pa.int64()),
                        ("src_asof", pa.date32()), ("frozen_at", ft.TS)])
    out = root / "silver" / "asset_features" / "part-00000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), out)
    # features_version names the stormwater snapshot by existence, never by fetching it
    snap = root / "snapshots" / "stormwater" / ft.SW_ZIP
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_bytes(b"")
    return fallback_cx, no_dem


def _plant_precip_and_stormwater(root: Path) -> None:
    cells = sorted({c for c in pq.read_table(root / "ref" / "assets",
                                             columns=["cell"]).column(0).to_pylist()}
                   | {c for c in pq.read_table(root / "ref" / "cells",
                                               columns=["cell"]).column(0).to_pylist()})
    pq.write_table(pa.Table.from_pylist(
        [{"cell": c, "share_deep": 0.25, "share_nuisance": 0.25,
          "share_not_analyzed": 0.5, "src_asof": ft.SRC_ASOF,
          "frozen_at": ft.FEATURES_FROZEN} for c in cells],
        schema=pa.schema([("cell", pa.int64()), ("share_deep", pa.float64()),
                          ("share_nuisance", pa.float64()),
                          ("share_not_analyzed", pa.float64()),
                          ("src_asof", pa.date32()), ("frozen_at", ft.TS)])),
        _mk(root / "silver" / "cell_stormwater" / "part-00000.parquet"))

    events = pq.read_table(root / "silver" / "flood_events").to_pylist()
    by_month: dict[str, list[dict]] = {}
    for e in events:
        ws, we = e["window_start_utc"], e["window_end_utc"]
        h = ws - timedelta(hours=24)
        while h <= we:
            mm = (AT_OPEN_MM if h == ws else
                  SPIKE_MM if h == ws + timedelta(hours=SPIKE_H) else FLAT_MM)
            mm24 = ANTECEDENT_MM if h == ws else OTHER_24H
            for c in cells:
                by_month.setdefault(f"{h:%Y-%m}", []).append(
                    {"cell": c, "hour_end_utc": h, "mm_1h": mm, "mm_1h_prev": mm,
                     "mm_3h": mm, "mm_6h": mm, "mm_24h": mm24, "n_hours_24h": 24,
                     "t2m_c": 15.0})
            h += timedelta(hours=1)
    schema = pa.schema([("cell", pa.int64()), ("hour_end_utc", ft.TS),
                        ("mm_1h", pa.float32()), ("mm_1h_prev", pa.float32()),
                        ("mm_3h", pa.float32()), ("mm_6h", pa.float32()),
                        ("mm_24h", pa.float32()), ("n_hours_24h", pa.int8()),
                        ("t2m_c", pa.float32())])
    for month, rows in by_month.items():
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), _mk(
            root / "silver" / "precip_cell_hourly" / f"src={fm.PRECIP_SRC}"
            / f"month={month}" / "part-00000.parquet"))


def _minus_years(ts, n: int):
    """DuckDB's own `- INTERVAL n YEAR`: clamp the day rather than raise on 29 February."""
    day = min(ts.day, calendar.monthrange(ts.year - n, ts.month)[1])
    return ts.replace(year=ts.year - n, day=day)


def _mk(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="module")
def matrix_root(label_root, tmp_path_factory):  # noqa: F811
    root = tmp_path_factory.mktemp("matrix")
    for name in ("ref", "silver", "gold", "archive"):
        if (label_root / name).exists():
            shutil.copytree(label_root / name, root / name)
    fallback_cx, no_dem = _plant_features(root)
    _plant_precip_and_stormwater(root)
    fm.build(root, expect=None)
    return root, fallback_cx, no_dem


@pytest.fixture(scope="module")
def con():
    return duck.connect()


@pytest.fixture(scope="module")
def matrix(con, matrix_root):
    return duck.table(con, matrix_root[0] / "gold" / "flood_matrix")


def one(rel, sql):
    return rel.query("t", sql).fetchall()


# ---- seam 2: the pure rules --------------------------------------------------------

def _event(day, klass=fm.EVENT_CLASS, **cov):
    return {"event_id": day.isoformat(), "day_start": day, "day_end": day,
            "event_class": klass,
            **{f"cov_{s}": cov.get(s, True) for s in ("311", "alert", "floodnet")}}


def _asset(kind, asset_id="x", complex_id=None, feeds=None, scored=True):
    return {"asset_id": asset_id, "kind": kind, "cell": 1, "complex_id": complex_id,
            "feeds": feeds, "scored": scored}


def test_the_era_rule_puts_2026_outside_the_fit_and_splits_it_at_mrms():
    assert fm.era(date(2025, 12, 31)) == fm.FIT
    assert fm.era(date(2010, 1, 1)) == fm.FIT
    # 2026 has no AORC year at all: the pre-MRMS gap validates, the MRMS era replicates
    assert fm.era(date(2026, 1, 5)) == fm.VALIDATION_ONLY
    assert fm.era(fm.MRMS_FROM - timedelta(days=1)) == fm.VALIDATION_ONLY
    assert fm.era(fm.MRMS_FROM) == fm.REPLICATION
    assert fm.era(date(2026, 8, 20)) == fm.REPLICATION
    assert fm.FIT_ERA_LAST_YEAR == 2025


def test_only_pluvial_fit_era_events_enter_the_matrix():
    """Sandy leaves by its event CLASS, not by a special case: one coastal event would
    mint ~250-350 of ~1,350 Cell positives."""
    assert fm.in_fit_universe(_event(date(2021, 9, 1)))
    for klass in ("coastal", "mixed", "snowmelt", "unclassified"):
        assert not fm.in_fit_universe(_event(date(2012, 10, 29), klass))
    assert not fm.in_fit_universe(_event(date(2026, 3, 11)))


def test_the_elevation_fallback_is_per_row_and_never_imputes():
    ok = {"elev_2017_m": 12.0, "ring15_med_m": 9.0, "grade_ok": True}
    assert fm.elev_source(ok) == 12.0
    assert fm.relief_m(ok) == 3.0
    flagged = {**ok, "grade_ok": False}
    assert fm.elev_source(flagged) == 9.0        # the ring, never a Cell median
    assert fm.relief_m(flagged) == 0.0           # a fallback row has NO relief information
    gone = {"elev_2017_m": None, "ring15_med_m": None, "grade_ok": False}
    assert fm.elev_source(gone) is None and fm.relief_m(gone) is None


def test_positives_run_through_the_same_pairable_rule_as_the_negatives():
    """THE symmetry this ticket owes. gold/flood_labels stores positives the negative
    rules reject on purpose — keeping a 2015 bus-stop positive while the same rule
    deletes every 2015 bus-stop negative manufactures a class imbalance out of
    bookkeeping."""
    bus = _asset("bus_stop", "bus:1", feeds=["brooklyn"])
    old, new = _event(date(2015, 6, 1)), _event(date(2021, 6, 1))
    rows, delta = fm.pairs([bus], [old, new], [("bus:1", "2015-06-01")])
    assert delta["positives_dropped_unpairable"] == 1
    assert [(r["asset_id"], r["event_id"], r["flooded"]) for r in rows] == [
        ("bus:1", "2021-06-01", False)]
    # and the drop is exactly what census() publishes, so the delta is never hidden
    assert fl.census([bus], [old, new], [("bus:1", "2015-06-01")])["positives_outside"] == 1


def test_every_candidate_pair_becomes_exactly_one_row():
    assets = [_asset("cell", "cell:1"), _asset("cell", "cell:2"),
              _asset("bus_stop", "bus:1", feeds=["queens"])]
    events = [_event(date(2021, 6, 1)), _event(date(2024, 7, 1))]
    pos = [("cell:1", "2021-06-01")]
    rows, _ = fm.pairs(assets, events, pos)
    cen = fl.census(assets, events, pos)
    assert len(rows) == cen["candidates"]
    assert sum(r["flooded"] for r in rows) == len(pos) - cen["positives_outside"]
    assert len({(r["asset_id"], r["event_id"]) for r in rows}) == len(rows)


def test_a_positive_on_an_event_outside_the_universe_is_simply_absent():
    cell = _asset("cell", "cell:1")
    rows, delta = fm.pairs([cell], [_event(date(2021, 6, 1))],
                           [("cell:1", "2012-10-29")])   # the Sandy event, not passed in
    assert delta["positives_dropped_unpairable"] == 0    # excluded by class, not by rule
    assert [r["flooded"] for r in rows] == [False]


def test_a_positive_on_a_unit_outside_the_negative_universe_is_counted_not_dropped():
    """Ticket 05 mints none of these (its Cell branch filters on `scored`), so one would
    be registry drift — and a positive that vanishes without a count is the exact bug the
    census exists to make impossible."""
    unscored = _asset("cell", "cell:1", scored=False)
    rows, delta = fm.pairs([unscored], [_event(date(2021, 6, 1))],
                           [("cell:1", "2021-06-01")])
    assert rows == [] and delta["positives_off_universe"] == 1
    assert delta["positives_dropped_unpairable"] == 0


def test_the_barred_vocabulary_names_every_channel_the_spec_bars():
    for banned in ("floodnet", "grade_ok", "epoch", "alert", "borough", "impact"):
        assert banned in fm.BARRED
    # ticket 16's impact columns are evidence on the far side of the wall
    for col in ("service_ratio", "max_gap_ratio", "resid_ratio", "nbr_ratio", "speed_ratio"):
        assert any(b in col for b in fm.BARRED), col


# ---- seam 1: the written table ------------------------------------------------------

def test_the_grain_is_one_row_per_unit_event(matrix):
    assert one(matrix, "SELECT count(*) FROM (SELECT asset_id, event_id FROM t "
                       "GROUP BY 1, 2 HAVING count(*) > 1)") == [(0,)]
    assert one(matrix, "SELECT count(*) FROM t WHERE asset_id IS NULL OR event_id IS NULL "
                       "OR cell IS NULL OR flooded IS NULL OR role IS NULL "
                       "OR matrix_version IS NULL") == [(0,)]
    assert one(matrix, "SELECT DISTINCT era FROM t") == [(fm.FIT,)]
    assert one(matrix, "SELECT count(DISTINCT matrix_version) FROM t") == [(1,)]


def test_no_barred_feature_column_exists_in_the_matrix(matrix):
    """The wall, asserted on the bytes. Includes the absence assertion ticket 16 owes this
    matrix: impact is evidence, never a feature, on both sides of the wall."""
    cols = {c.lower() for c in matrix.columns}
    assert not {c for c in cols for b in fm.BARRED if b in c}
    # named explicitly as well, so a shortened BARRED can never quietly widen the matrix
    assert not cols & {"grade_ok", "elev_2014_m", "epoch_delta_m", "borough", "n_entrances",
                       "source_mix", "label_support", "depth_mm", "service_ratio",
                       "max_gap_ratio", "resid_ratio", "nbr_ratio", "speed_ratio",
                       "floodnet_depth_mm", "by_alert"}


def test_each_role_carries_its_own_features_and_only_its_own(matrix):
    for role, cols in fm.FEATURES.items():
        for col in cols:
            assert one(matrix, f"SELECT count(*) FROM t WHERE role = '{role}' "
                               f"AND {col} IS NULL") == [(0,)], f"{role}.{col}"
    # the other grain's features are absent, not zero: a Cell has no doorway elevation
    assert one(matrix, "SELECT count(*) FROM t WHERE role != 'fit_point' AND "
                       "(elev_ft IS NOT NULL OR relief_ft IS NOT NULL "
                       "OR stormwater_cat IS NOT NULL)") == [(0,)]
    assert one(matrix, "SELECT count(*) FROM t WHERE role != 'fit_cell' AND "
                       "(share_deep IS NOT NULL OR density_311_3y IS NOT NULL)") == [(0,)]


def test_the_precip_window_opens_after_the_open_hour_and_the_antecedent_is_frozen_on_it(matrix, matrix_root):
    """The leakage contract as arithmetic. The Window is (open, close]: the hour STAMPED
    at Window open covers the hour BEFORE the Window, so its 99 mm may not reach a Window
    term — and that same row is where mm_24h is frozen, so the antecedent is 7, never the
    999 every other hour carries."""
    root = matrix_root[0]
    events = {e["event_id"]: e for e in
              pq.read_table(root / "silver" / "flood_events").to_pylist()}
    assert one(matrix, f"SELECT count(*) FROM t WHERE abs(log1p_precip_max_mm_1h "
                       f"- ln(1 + {SPIKE_MM})) > 1e-9") == [(0,)]
    assert one(matrix, f"SELECT count(*) FROM t WHERE abs(log1p_antecedent_mm_24h "
                       f"- ln(1 + {ANTECEDENT_MM})) > 1e-9") == [(0,)]
    for event_id, total in one(matrix, "SELECT event_id, "
                                       "any_value(log1p_precip_total_mm) FROM t GROUP BY 1"):
        e = events[event_id]
        hours = int((e["window_end_utc"] - e["window_start_utc"]).total_seconds() // 3600)
        assert total == pytest.approx(math.log1p(FLAT_MM * (hours - 1) + SPIKE_MM)), event_id


def test_the_311_density_reads_strictly_before_window_open(matrix, matrix_root):
    """The chronic-reporter control, recomputed independently in Python from the fixture
    observations — and the fixture must actually hold a 311 report INSIDE a Window, or the
    strictly-before cut has nothing to bite on."""
    root = matrix_root[0]
    obs = [(o["cell"], o["ts_utc"]) for o in
           pq.read_table(root / "silver" / "flood_obs",
                         columns=["source", "cell", "ts_utc"]).to_pylist()
           if o["source"] == "311"]
    events = pq.read_table(root / "silver" / "flood_events").to_pylist()
    assert any(e["window_start_utc"] <= ts < e["window_end_utc"]
               for _, ts in obs for e in events), \
        "the fixture must hold a 311 report inside an event Window"
    want = {}
    for e in (e for e in events if fm.in_fit_universe(e)):
        open_ = e["window_start_utc"]
        lo = _minus_years(open_, fm.DENSITY_YEARS)
        for cell, ts in obs:
            if lo <= ts < open_:
                want[(e["event_id"], cell)] = want.get((e["event_id"], cell), 0) + 1
    got = {(e, c): n for e, c, n in
           one(matrix, "SELECT event_id, cell, any_value(density_311_3y) FROM t "
                       "WHERE role = 'fit_cell' GROUP BY 1, 2")}
    assert got, "the fixture must hold Cell rows"
    assert sum(want.get(k, 0) for k in got) > 0, "the control must be non-zero somewhere"
    assert got == {k: want.get(k, 0) for k in got}


def test_the_stored_positives_are_exactly_the_pairable_labels(matrix, matrix_root):
    root, _, no_dem = matrix_root
    by_id = {e["event_id"]: e for e in
             pq.read_table(root / "silver" / "flood_events").to_pylist()
             if fm.in_fit_universe(e)}
    assets = {a["asset_id"]: a for a in pq.read_table(
        root / "ref" / "assets",
        columns=["asset_id", "kind", "cell", "complex_id", "feeds", "scored"]).to_pylist()}
    lab = pq.read_table(root / "gold" / "flood_labels", columns=["asset_id", "event_id"])
    want = {(a, e) for a, e in zip(lab.column("asset_id").to_pylist(),
                                   lab.column("event_id").to_pylist())
            if e in by_id and a not in set(no_dem) and fl.pairable(assets[a], by_id[e])}
    got = {(a, e) for a, e in one(matrix, "SELECT asset_id, event_id FROM t WHERE flooded")}
    assert got and got == want
    # the labels the pairable rule rejects are really there to be rejected
    dropped = {(a, e) for a, e in zip(lab.column("asset_id").to_pylist(),
                                      lab.column("event_id").to_pylist())
               if e in by_id and not fl.pairable(assets[a], by_id[e])}
    assert not dropped & got


def test_the_negatives_are_the_read_side_generators_own_answer(matrix, matrix_root):
    """Not a forked rule: what the table calls a negative is what flood_labels.negatives()
    yields, and read_negatives() over the same tables is a superset (it spans every event,
    this matrix only the pluvial fit era)."""
    root = matrix_root[0]
    stored = {(a, e) for a, e in
              one(matrix, "SELECT asset_id, event_id FROM t WHERE NOT flooded")}
    generated = {(n["asset_id"], n["event_id"]) for n in fl.read_negatives(root)}
    assert stored, "the fixture universe must yield negatives"
    assert stored <= generated


def test_a_complex_is_a_validation_row_and_never_a_fit_row(matrix):
    """Complexes are alert-only by construction (ticket 05 asserts it) — which is what
    makes them an INDEPENDENT complex-grain validation set. A point rule reaching one
    would destroy that, so no complex may carry a point feature, and no complex row may
    call itself a fit row."""
    assert one(matrix, "SELECT count(*) FROM t WHERE kind = 'complex' "
                       "AND role != 'validate_complex'") == [(0,)]
    assert one(matrix, "SELECT count(*) FROM t WHERE role = 'validate_complex' "
                       "AND kind != 'complex'") == [(0,)]
    assert one(matrix, "SELECT count(*) FROM t WHERE role LIKE 'fit_%' "
                       "AND kind = 'complex'") == [(0,)]
    # the max-over-children aggregate is a GROUP BY, not a second join into ref/assets
    assert one(matrix, "SELECT count(*) FROM t WHERE kind = 'entrance' "
                       "AND complex_id IS NULL") == [(0,)]
    linked = one(matrix, "SELECT count(*) FROM t WHERE role = 'validate_complex' "
                         "AND complex_id IN (SELECT complex_id FROM t "
                         "WHERE role = 'fit_point' AND kind = 'entrance')")
    assert linked[0][0] > 0


def test_the_ring15_fallback_reaches_a_complex_with_no_grade_ok_entrance(matrix, matrix_root):
    """The seven-complex obligation, on the fixture's own zero-grade_ok complex: filter
    children to grade_ok FIRST and its aggregate is empty, which is a NULL score in
    gold/flood_exposure, which mandates none."""
    root, fallback_cx, _ = matrix_root
    feats = {f["asset_id"]: f for f in pq.read_table(root / "silver" / "asset_features",
                                                     columns=["asset_id", "grade_ok"]).to_pylist()}
    kids = [a["asset_id"] for a in pq.read_table(
        root / "ref" / "assets", columns=["asset_id", "kind", "complex_id"]).to_pylist()
        if a["kind"] == "entrance" and a["complex_id"] == fallback_cx]
    assert kids and not any(feats[k]["grade_ok"] for k in kids)
    got = one(matrix, f"SELECT count(*), count(elev_ft) FROM t WHERE role = 'fit_point' "
                      f"AND complex_id = '{fallback_cx}'")
    assert got[0][0] > 0 and got[0][1] == got[0][0]
    # and the fallback row honestly reports no relief rather than inventing one
    assert one(matrix, f"SELECT count(*) FROM t WHERE complex_id = '{fallback_cx}' "
                       f"AND relief_ft != 0") == [(0,)]


def test_units_outside_the_dem_footprint_are_excluded_with_a_count(matrix, matrix_root):
    """The policy is EXCLUDE-WITH-COUNT — never a silent NULL, never an imputed
    elevation. The count rides in the file's own metadata."""
    root, _, no_dem = matrix_root
    present = {a for (a,) in one(matrix, "SELECT DISTINCT asset_id FROM t")}
    assert not present & set(no_dem)
    assert one(matrix, "SELECT count(*) FROM t WHERE role = 'fit_point' "
                       "AND elev_ft IS NULL") == [(0,)]
    meta = pq.read_table(root / "gold" / "flood_matrix").schema.metadata
    assert json.loads(meta[b"gates"])["out_of_footprint"] == len(no_dem)
    assert b"imputed" in meta[b"out_of_footprint_policy"]


def test_the_file_names_its_estimand_and_publishes_what_the_rules_dropped(matrix_root):
    meta = pq.read_table(matrix_root[0] / "gold" / "flood_matrix").schema.metadata
    assert meta[b"estimand"] == fl.ESTIMAND.encode() == b"flooded_reported"
    assert meta[b"event_class"] == fm.EVENT_CLASS.encode() == b"pluvial"
    assert meta[b"precip_src"] == b"aorc"
    cen = json.loads(meta[b"census"])
    assert cen["grid"] == (cen["dropped_uncovered"] + cen["dropped_anachronistic"]
                           + cen["candidates"])
    gates = json.loads(meta[b"gates"])
    assert gates["positives_dropped_unpairable"] == cen["positives_outside"]
    assert gates["positives_off_universe"] == 0
    assert set(gates["events_by_era"]) <= {fm.FIT, fm.VALIDATION_ONLY, fm.REPLICATION}


def test_matrix_version_chains_the_label_features_and_precip_identities(matrix_root, matrix):
    root = matrix_root[0]
    (label,) = set(pq.read_table(root / "gold" / "flood_labels",
                                 columns=["label_version"]).column(0).to_pylist())
    stamp = fm.matrix_version(root, label)
    assert {v for (v,) in one(matrix, "SELECT DISTINCT matrix_version FROM t")} == {stamp}
    assert fm.matrix_version(root, "another-label-set") != stamp
    # a precip month appearing or disappearing under a Window moves a feature, so it moves
    # the stamp: ticket 18's alternate universes cannot collide with this one
    before = fm.precip_identity(root)
    part = sorted((root / "silver" / "precip_cell_hourly"
                   / f"src={fm.PRECIP_SRC}").glob("month=*"))[0]
    part.rename(part.with_name(part.name + ".held"))
    try:
        assert fm.precip_identity(root) != before
        assert fm.matrix_version(root, label) != stamp
    finally:
        part.with_name(part.name + ".held").rename(part)
    assert fm.matrix_version(root, label) == stamp
