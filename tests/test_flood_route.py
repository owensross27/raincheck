"""flood-build 21a: the route flood attribution table and its one exhibit.

Three shapes get most of the attention, because all three are ways this table could be
WRONG WHILE LOOKING RIGHT.

(1) A SHARE OF ZERO AND A SHARE OF NOTHING ARE DIFFERENT CLAIMS. `share_len_moderate = 0.0`
    says "this route is dry under a 2.13 in/hr design storm"; `share_len_limited = NULL`
    says "nobody can read the 1.77 in/hr geodatabase". A test that only counted rows would
    pass on either. Both directions are driven, and so is DEP's exclusion mask, which is a
    CATEGORY and not an absence — a route can be 100% inside `not_analyzed` and have a
    perfectly honest 0.0 flooded share, and the two columns must be read together.
(2) THE ROUTE FOOTPRINT IS A UNION, NOT A SUM. Six schedule Picks trace nearly the same
    street; summing them would multiply both the length and the flooded length by six and
    leave the SHARE looking right. A fixture where two Picks trace the identical line is
    what tells those apart.
(3) THE TABLE MUST BE REPRODUCIBLE FROM ITS OWN INPUTS. GEOS's cascaded union is
    order-dependent in the last bit and an aggregate's group is unordered, so the first
    version of this module differed between two runs of the same code (74 of 683 lengths, at
    ~1.4e-15 — one ULP, orch 11's `dist_m_sum` arithmetic in a new place). A byte-identity
    test over two builds is the gate; the `ORDER BY` inside both aggregates is the fix.

The version stamp is mutation-checked from BOTH sides: every input that can move a number
must move it, and the two columns that decide nothing (`share_not_analyzed`, `frozen_at`)
must not — a stamp that moves on everything is a stamp that tells a consumer nothing.
"""
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from raincheck import checks, duck
from raincheck import flood_route as fr
from raincheck import stormwater_extent as se
from raincheck.schedule import GEOD

REAL = os.environ.get("RAINCHECK_ARCHIVE_ROOT")
real_root = pytest.mark.skipif(not REAL, reason="RAINCHECK_ARCHIVE_ROOT is not the main root")

# A 4 x 1 strip of 0.01-degree Cells at latitude 40.70, west to east. Everything below is
# placed by hand inside it, so no assertion here is testing the identity element.
LAT0, LAT1 = 40.700, 40.710
LON = [-74.000, -73.990, -73.980, -73.970, -73.960]      # four Cells: 0..3
CELLS = [613229520649977855 + i for i in range(4)]        # int64, the h3 magnitude


def cell_wkt(i: int) -> str:
    a, b = LON[i], LON[i + 1]
    return (f"POLYGON(({a} {LAT0}, {b} {LAT0}, {b} {LAT1}, {a} {LAT1}, {a} {LAT0}))")


def band(i: int, lo: float, hi: float, y0=LAT0 + 0.002, y1=LAT0 + 0.008) -> str:
    """A rectangle inside Cell `i`, spanning the fraction [lo, hi] of its longitude."""
    a = LON[i] + (LON[i + 1] - LON[i]) * lo
    b = LON[i] + (LON[i + 1] - LON[i]) * hi
    return f"POLYGON(({a} {y0}, {b} {y0}, {b} {y1}, {a} {y1}, {a} {y0}))"


def line(i: int, j: int, y=LAT0 + 0.005) -> str:
    """A straight east-west line across Cells i..j at latitude `y`."""
    return f"LINESTRING({LON[i]} {y}, {LON[j + 1]} {y})"


# route_id, direction_id, [(pick, shape_id, wkt)] — five routes, six (route, direction) rows
ROUTES = [
    # R1 crosses Cells 0-1 and runs through a deep band and a nuisance band.
    ("R1", 0, [("p1", "s1", line(0, 1))]),
    # R2 crosses Cell 2 and ONLY a not_analyzed band: DEP excluded that ground from the
    # model, so its flooded share is an honest 0.0 and its mask share is not.
    ("R2", 0, [("p1", "s2", line(2, 2))]),
    # R3 crosses Cell 3 and nothing else at all: no extent, no flood-prone Cell, no event.
    ("R3", 0, [("p1", "s3", line(3, 3))]),
    # R4 crosses Cell 0, whose Cell carries two flood_labels events.
    ("R4", 0, [("p1", "s4", line(0, 0))]),
    # R5 is the union case: TWO Picks tracing the IDENTICAL line, plus a second direction.
    ("R5", 0, [("p1", "s5a", line(1, 2)), ("p2", "s5b", line(1, 2))]),
    ("R5", 1, [("p1", "s5c", line(1, 2, y=LAT0 + 0.006))]),
]

EXTENT = [  # scenario, category, poly, wkt
    ("moderate", "deep", 1, band(0, 0.10, 0.30)),
    ("moderate", "nuisance", 2, band(1, 0.20, 0.40)),
    ("moderate", se.MASK, 3, band(2, 0.00, 1.00)),
    ("moderate", "nuisance", 4, band(1, 0.30, 0.50)),   # OVERLAPS poly 2 on [0.30, 0.40]
]
STORMWATER = [  # cell index, share_deep, share_nuisance, share_not_analyzed
    (0, 0.20, 0.00, 0.00),      # flood-prone
    (1, 0.00, 0.05, 0.00),      # flood-prone
    (2, 0.00, 0.00, 0.90),      # NOT flood-prone: the mask is not flooding
    (3, 0.00, 0.00, 0.00),      # not flood-prone
]
LABELS = [("2021-09-01", 0), ("2023-09-29", 0), ("2023-09-29", 1)]   # event_id, cell index
EVENT_DAYS = {"2021-09-01": (date(2021, 9, 1), date(2021, 9, 2)),
              "2023-09-29": (date(2023, 9, 29), date(2023, 9, 29))}
ZIP_SHA = "z" * 64
LABEL_V, SPINE_V, FEATURES_V = "lv-fixture", "sv-fixture", "fv-fixture"

# The exhibit's Gold rows. 2021-09-02 is a THURSDAY, so hour_of_week is 72 + the local hour;
# 18:00 UTC is 14:00 EDT, i.e. 86 — the same block Ida's real 24 hours land on.
#
# R1's two event-day rows are the discriminating pair: 100 arrivals WITH a late_share and 900
# WITHOUT one. Weighted over the rows that have one it is 0.5; weighted over all n_events it
# is 0.05. On the real root only 3,161 of 1.36 M rows are NULL, so the two answers differ in
# the fourth digit and no assertion could tell them apart — here they differ tenfold.
_H = lambda d, h: f"TIMESTAMPTZ '{d} {h}:00:00+00'"      # noqa: E731
CHR_ROWS = [
    f"({CELLS[0]}::BIGINT, {_H('2021-09-02', '18')}, 'R1', 0::TINYINT, 100::BIGINT, 0.5, 60.0, '2021-09')",
    f"({CELLS[1]}::BIGINT, {_H('2021-09-02', '19')}, 'R1', 0::TINYINT, 900::BIGINT, NULL, NULL, '2021-09')",
    # 2021-09-03 is a Friday and no event covers it: the dry side of the substitute. It
    # carries the SAME discriminating pair as the event day, because `other_days` weights
    # with its own copy of the rule and a mutation to that copy alone survived a round.
    f"({CELLS[0]}::BIGINT, {_H('2021-09-03', '18')}, 'R1', 0::TINYINT, 10::BIGINT, 0.1, 10.0, '2021-09')",
    f"({CELLS[1]}::BIGINT, {_H('2021-09-03', '19')}, 'R1', 0::TINYINT, 90::BIGINT, NULL, NULL, '2021-09')",
    # 2023-09-29 is inside w2's DECLARED span and w2 is NOT planted below - the case that
    # tells "the window covers this day" from "the window is on disk"
    f"({CELLS[0]}::BIGINT, {_H('2023-09-29', '18')}, 'R1', 0::TINYINT, 5::BIGINT, 0.2, 20.0, '2023-09')",
]
CHS_ROWS = [
    f"({CELLS[0]}::BIGINT, {_H('2021-09-02', '18')}, 'R1', 1000.0, 500::BIGINT, '2021-09')",
]
BASE_ROWS = [   # speed_dry 4.0 against the event hour's 2.0: a ratio of exactly 0.5
    f"({CELLS[0]}::BIGINT, 86::SMALLINT, 1000.0, 250::BIGINT, 'w1')",
]


def _copy(con, root: Path, table: tuple[str, ...], select: str) -> None:
    out = root.joinpath(*table)
    out.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({select}) TO '{out / 'part-00000.parquet'}' (FORMAT PARQUET)")


def plant(root: Path, *, stormwater=STORMWATER, labels=LABELS, extent=EXTENT,
          routes=ROUTES, frozen="2026-08-23T00:00:00Z") -> Path:
    """The whole input tree on a scratch root, written the way the real tables are written
    (DuckDB `COPY`, so the geometry columns really are GeoParquet)."""
    con = duck.connect()
    con.execute("INSTALL spatial; LOAD spatial;")

    trips = ", ".join(f"('t{n}', '{r}', {d}::TINYINT, 'sv', '{sid}', 'x', '{pick}')"
                      for n, (r, d, shapes) in enumerate(routes)
                      for pick, sid, _ in shapes)
    _copy(con, root, ("silver", "trips"),
          "SELECT * FROM (VALUES " + trips + ") t(trip_id, route_id, direction_id, "
          "service_id, shape_id, trip_type, pick_id)")

    shapes = ", ".join(f"('{sid}', ST_GeomFromText('{wkt}'), "
                       f"ST_Length(ST_GeomFromText('{wkt}'))::FLOAT, '{pick}')"
                       for _, _, ss in routes for pick, sid, wkt in ss)
    _copy(con, root, ("silver", "shapes"),
          "SELECT * FROM (VALUES " + shapes + ") t(shape_id, geometry, length_m, pick_id)")

    cells = ", ".join(f"({c}::BIGINT, ST_GeomFromText('{cell_wkt(i)}'))"
                      for i, c in enumerate(CELLS))
    _copy(con, root, ("ref", "cells"),
          "SELECT * FROM (VALUES " + cells + ") t(cell, geometry)")

    ext = ", ".join(f"('{sc}', 'current', {fr.RAIN_IN_HR[sc]}, '{cat}', {poly}::BIGINT, "
                    f"ST_GeomFromText('{wkt}'), DATE '2026-08-23', '{ZIP_SHA}')"
                    for sc, cat, poly, wkt in extent)
    _copy(con, root, ("silver", "stormwater_extent"),
          "SELECT * FROM (VALUES " + ext + ") t(scenario, horizon, rain_in_hr, category, "
          "poly, geometry, src_asof, zip_sha256)")

    sw = ", ".join(f"({CELLS[i]}::BIGINT, {d}, {n}, {m}, DATE '2026-08-23', "
                   f"TIMESTAMPTZ '{frozen}')" for i, d, n, m in stormwater)
    _copy(con, root, ("silver", "cell_stormwater"),
          "SELECT * FROM (VALUES " + sw + ") t(cell, share_deep, share_nuisance, "
          "share_not_analyzed, src_asof, frozen_at)")

    lab = ", ".join(f"('cell:{CELLS[i]:x}', 'cell', '{ev}', {CELLS[i]}::BIGINT, "
                    f"1::SMALLINT, NULL::DOUBLE, ['x'], '{LABEL_V}')" for ev, i in labels)
    _copy(con, root, ("gold", "flood_labels"),
          "SELECT * FROM (VALUES " + lab + ") t(asset_id, kind, event_id, cell, source_mix, "
          "depth_mm, label_support, label_version)")

    evs = ", ".join(f"('{ev}', DATE '{a}', DATE '{b}', '{SPINE_V}')"
                    for ev, (a, b) in EVENT_DAYS.items())
    _copy(con, root, ("silver", "flood_events"),
          "SELECT * FROM (VALUES " + evs + ") t(event_id, day_start, day_end, spine_version)")

    # --- the EXHIBIT's inputs. Three things this half has to discriminate and the Gold
    # table's fixture cannot: a share weighted over rows that HAVE one vs over all of them,
    # a baseline window that is in range but not on disk, and a dry side made of other
    # weekdays. All three survived a mutation round until these tables existed.
    _copy(con, root, ("gold", "cell_hour_route"),
          "SELECT * FROM (VALUES " + ", ".join(CHR_ROWS) + ") t(cell, hour_end_utc, route_id, "
          "direction_id, n_events, late_share, ewt_s, month)")
    _copy(con, root, ("gold", "cell_hour_speed"),
          "SELECT * FROM (VALUES " + ", ".join(CHS_ROWS) + ") t(cell, hour_end_utc, route_id, "
          "dist_m_sum, dt_s_sum, month)")
    _copy(con, root, ("gold", "cell_hourofweek_baseline"),
          "SELECT * FROM (VALUES " + ", ".join(BASE_ROWS) + ") t(cell, hour_of_week, "
          "dist_m_sum_dry, dt_s_sum_dry, \"window\")")
    con.close()
    return root


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(fr.features, "features_version", lambda _root: FEATURES_V)
    return plant(tmp_path / "data")


@pytest.fixture
def built(root):
    con = duck.connect()
    try:
        table, counts = fr.rows(root, con)
    finally:
        con.close()
    return {(r["route_id"], r["direction_id"]): r for r in table}, counts


# --- the grain and the ids ----------------------------------------------------------------


def test_the_grain_is_one_row_per_route_and_direction(built):
    table, _ = built
    assert sorted(table) == [("R1", "0"), ("R2", "0"), ("R3", "0"), ("R4", "0"),
                             ("R5", "0"), ("R5", "1")]


def test_every_id_is_a_string(built):
    table, _ = built
    for (rid, did), row in table.items():
        assert isinstance(rid, str) and isinstance(did, str)
        assert isinstance(row["route_id"], str) and isinstance(row["direction_id"], str)
        assert did in ("0", "1")     # a TINYINT that arrived as a string, not as an int


def test_the_arrow_schema_types_both_ids_as_strings(root, built, tmp_path):
    fr.write(root, list(built[0].values()))
    got = pq.read_table(root / "gold" / fr.TABLE)
    assert got.schema.field("route_id").type == "string"
    assert got.schema.field("direction_id").type == "string"
    assert got.num_rows == 6


# --- zero is a claim; NULL is a refusal ----------------------------------------------------


def test_a_route_that_crosses_no_extent_reports_a_measured_zero(built):
    """R3 crosses Cell 3 and nothing else. Its moderate share is 0.0 — a real measurement
    against a scenario that HAS a source — while its unsourced columns stay NULL."""
    r = built[0][("R3", "0")]
    assert r["share_len_moderate"] == 0.0
    assert r["share_len_not_analyzed"] == 0.0
    assert r["n_cells"] == 1 and r["n_cells_flood_prone"] == 0
    assert r["n_flood_events"] == 0 and r["last_event_day"] is None


def test_a_cell_the_route_only_touches_is_not_a_cell_it_crosses(built):
    """Every line here ENDS on a Cell boundary, so `ST_Intersects` alone reports the
    neighbour too — and because `n_flood_events` joins through this table, a zero-length
    graze would put that neighbour's whole flood history on the route. R4 runs the width of
    Cell 0 and touches Cell 1's western edge at a point; it crosses ONE Cell.

    On the real root the two rules agree exactly (14,217 = 14,217 route-Cell pairs, measured
    2026-08-26): no bus route happens to end on an H3 boundary today. The fixture is the only
    thing that can see this, which is why it is built to."""
    assert built[0][("R4", "0")]["n_cells"] == 1
    assert built[0][("R1", "0")]["n_cells"] == 2      # Cells 0 and 1, touching Cell 2
    assert built[1]["cells_crossed"] == 4


def test_the_unsourced_scenarios_are_null_on_every_row_and_never_zero(built):
    table, _ = built
    for row in table.values():
        assert row["share_len_limited"] is None
        assert row["share_len_extreme"] is None
        assert row["share_len_moderate"] is not None      # the one that HAS a source


def test_the_two_unsourced_reasons_are_different_and_both_are_derived():
    """Not one blanket 'no data' string: a container no driver can open and a scenario DEP
    never publishes at this sea level are different facts, and both come out of flood-build
    19's own declaration rather than out of a sentence typed here."""
    assert fr.unsourced("moderate") is None
    assert fr.unsourced("limited") == se.UNREADABLE[("limited", "current")]
    assert "2080" in fr.unsourced("extreme") and "current" in fr.unsourced("extreme")
    assert fr.sourced() == ("moderate",)


def test_a_scenario_that_becomes_readable_needs_no_edit_here(monkeypatch):
    """The day a re-encoded Limited source is pinned, `UNREADABLE` loses its entry and this
    module starts measuring the column. Driven, not asserted."""
    monkeypatch.setattr(se, "UNREADABLE", {})
    assert fr.unsourced("limited") is None
    assert fr.sourced() == ("limited", "moderate")


def test_the_rain_rates_are_read_from_flood_build_19_and_never_retyped():
    assert fr.RAIN_IN_HR == {s.scenario: s.rain_in_hr for s in se.SCENARIOS}
    import ast
    tree = ast.parse(Path(fr.__file__).read_text())
    for node in ast.walk(tree):     # every docstring and string literal out; flood 17's trap
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""
    code = ast.unparse(tree)
    for rate in ("1.77", "2.13", "3.66"):
        assert rate not in code, f"{rate} is retyped in the code; read it from SCENARIOS"


# --- the mask is a category, not an absence ------------------------------------------------


def test_the_exclusion_mask_is_its_own_column_and_is_never_a_flooded_share(built):
    """R2 runs the full width of a Cell that is entirely inside DEP's exclusion mask. Its
    FLOODED share is an honest 0.0 and its MASK share is ~1.0; reading the first without the
    second would call excluded ground dry."""
    r = built[0][("R2", "0")]
    assert r["share_len_moderate"] == 0.0
    assert r["share_len_not_analyzed"] == pytest.approx(1.0, abs=1e-6)
    assert r["n_cells"] == 1                # Cell 2 alone
    assert r["n_cells_flood_prone"] == 0    # a 0.90 not-analyzed share is not flood-prone
    assert r["n_flood_events"] == 0         # and no event reaches it


def test_the_mask_category_is_flood_build_19s_and_is_not_in_the_flooded_set():
    assert fr.MASK_COLUMN == f"share_len_{se.MASK}"
    assert se.MASK not in fr.FLOODED
    assert fr.MASK_COLUMN not in fr.SHARE_COLUMNS


# --- the footprint is a union -------------------------------------------------------------


def test_two_picks_tracing_one_street_are_counted_once(built):
    """R5 direction 0 has two Picks whose shapes are the IDENTICAL line. A sum would double
    its length and its flooded length and leave the SHARE looking right, which is exactly
    why the length is asserted and not only the share."""
    r = built[0][("R5", "0")]
    one = GEOD.geometry_length(__import__("shapely").from_wkt(line(1, 2)))
    assert r["n_shapes"] == 2
    assert r["length_m"] == pytest.approx(one, rel=1e-9)


def test_a_second_direction_is_its_own_row_with_its_own_geometry(built):
    a, b = built[0][("R5", "0")], built[0][("R5", "1")]
    assert a["n_shapes"] == 2 and b["n_shapes"] == 1
    assert a["length_m"] == pytest.approx(b["length_m"], rel=1e-4)   # parallel lines
    assert a["route_flood_version"] == b["route_flood_version"]


def test_overlapping_extent_polygons_are_not_counted_twice(built):
    """`EXTENT` polys 2 and 4 overlap on [0.30, 0.40] of Cell 1. A per-polygon SUM would
    report 0.30 of that Cell's width as nuisance where the union is 0.30 — the same number —
    so the fixture is checked against the union's own arithmetic rather than against a
    hand-typed figure that could match either."""
    r = built[0][("R5", "0")]
    # R5 spans Cells 1 and 2; nuisance covers [0.20, 0.50] of Cell 1's width, and the mask
    # covers all of Cell 2. Cell widths are equal, so the flooded share is 0.30 / 2.
    assert r["share_len_moderate"] == pytest.approx(0.15, abs=2e-3)
    assert r["share_len_not_analyzed"] == pytest.approx(0.5, abs=2e-3)


def test_no_share_ever_exceeds_one(built):
    for row in built[0].values():
        for c in fr.SHARE_COLUMNS + (fr.MASK_COLUMN,):
            assert row[c] is None or 0.0 <= row[c] <= 1.0, (row["route_id"], c, row[c])


# --- cells, events, and the flood-prone rule ----------------------------------------------


def test_the_flood_prone_subset_is_cell_stormwaters_own_rule(built):
    """Cells 0 and 1 have `share_deep + share_nuisance > 0`; Cells 2 and 3 do not, and Cell
    2's 0.90 not-analyzed share is deliberately NOT counted."""
    assert built[0][("R1", "0")]["n_cells"] == 2
    assert built[0][("R1", "0")]["n_cells_flood_prone"] == 2
    assert built[0][("R2", "0")]["n_cells_flood_prone"] == 0
    assert built[0][("R5", "0")]["n_cells_flood_prone"] == 1   # Cell 1 only; Cell 2 is masked
    assert built[1]["cells_flood_prone"] == 2                  # citywide, not per route


def test_the_event_route_carries_distinct_events_and_the_last_day(built):
    """Cell 0 carries two events; the label rows are (event, cell) so a route crossing one
    Cell twice must not count one event twice."""
    r = built[0][("R4", "0")]
    assert r["n_flood_events"] == 2
    assert r["last_event_day"] == date(2023, 9, 29)


def test_a_route_over_two_labelled_cells_counts_each_event_once(built):
    """R1 crosses Cells 0 and 1. Event 2023-09-29 labels BOTH, so a naive join would count
    it twice."""
    assert built[0][("R1", "0")]["n_flood_events"] == 2
    assert built[0][("R5", "0")]["n_flood_events"] == 1    # Cell 1 only -> 2023-09-29


def test_the_stamps_ride_on_every_row(built):
    for row in built[0].values():
        assert row["label_version"] == LABEL_V
        assert row["features_version"] == FEATURES_V
        assert row["zip_sha256"] == ZIP_SHA
        assert len(row["route_flood_version"]) == 40


# --- the length is geodesic ---------------------------------------------------------------


def test_the_length_is_geodesic_and_not_a_degree_count(root, built):
    """A share is a ratio of two lengths, so a planar-degree measure would cancel out of it
    and only the LENGTH column can catch it. 0.02 degrees of longitude at 40.7N is ~1,690 m
    and not 0.02."""
    r = built[0][("R1", "0")]
    assert 1_600 < r["length_m"] < 1_800


def test_the_geodesic_measure_is_the_one_that_wrote_silver_shapes(root, built):
    """`schedule.GEOD` is imported, not re-created, so the numerator and the denominator are
    the same ellipsoid by construction. Checked against the fixture's own stored column
    computed by a different route (DuckDB's planar ST_Length is degrees, so the comparison
    is against pyproj, which is the point)."""
    import shapely
    assert fr.GEOD is GEOD
    for (rid, did), row in built[0].items():
        shapes = next(ss for r, d, ss in ROUTES if (r, str(d)) == (rid, did))
        if len(shapes) == 1:
            assert row["length_m"] == pytest.approx(
                GEOD.geometry_length(shapely.from_wkt(shapes[0][2])), rel=1e-12)


def test_geodesic_m_takes_only_the_linear_parts():
    """`ST_Intersection` hands back a POINT where a line grazes a polygon corner, and a union
    then carries it inside a collection.

    A POINT ALONE CANNOT TEST THIS AND THE FIRST VERSION OF THIS TEST USED ONE. Measured:
    `GEOD.geometry_length` of a Point is **0.0**, so dropping the filter changes nothing and
    the mutation SURVIVED — the degenerate-fixture trap, where the fixture's value for the
    term under test is the identity element. A POLYGON is what discriminates it: pyproj
    returns its PERIMETER (3,911 m for the box below against the line's 845 m, a 5.6x
    over-count), so the collection carries both a part that cannot see the guard and a part
    that can."""
    import shapely
    ls = shapely.from_wkt(line(0, 0))
    poly = shapely.box(LON[0], LAT0, LON[1], LAT1)
    assert GEOD.geometry_length(shapely.Point(LON[0], LAT0)) == 0.0     # the degenerate part
    assert GEOD.geometry_length(poly) > 3 * GEOD.geometry_length(ls)    # the one that isn't
    g = shapely.GeometryCollection([ls, shapely.Point(LON[0], LAT0), poly])
    assert fr.geodesic_m(shapely.to_wkb(g)) == pytest.approx(
        GEOD.geometry_length(ls), rel=1e-12)


# --- reproducibility ----------------------------------------------------------------------


def test_two_builds_of_one_root_are_byte_identical(root, tmp_path):
    """The gate on the defect this module shipped and fixed: GEOS's cascaded union is
    order-dependent in the last bit, so an unordered aggregate produced a table that
    DIFFERED between two runs — 74 of 683 lengths at ~1.4e-15 on the real root. Bytes, not
    a tolerance: both sides are this module, so an exact digest is the honest bar."""
    out = []
    for _ in range(2):
        con = duck.connect()
        try:
            table, _ = fr.rows(root, con)
        finally:
            con.close()
        out.append(fr.write(root, table).read_bytes())
    assert out[0] == out[1]


def test_both_union_aggregates_are_ordered():
    """The fix itself, pinned on the CALL rather than on the prose — the docstring explains
    why the ORDER BY is there, so a source-text grep for `ST_Union_Agg(` would read its own
    explanation (flood 17's docstring-poisons-the-grep trap)."""
    import ast
    src = Path(fr.__file__).read_text()
    body = ast.get_source_segment(src, next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "footprint"))
    sql = "".join(s.value for s in ast.walk(ast.parse(body))
                  if isinstance(s, ast.Constant) and isinstance(s.value, str)
                  and "ST_Union_Agg" in s.value)
    assert sql.count("ST_Union_Agg") == 2
    for chunk in sql.split("ST_Union_Agg")[1:]:
        assert "ORDER BY" in chunk.split("GROUP BY")[0]


# --- the version stamp, both directions ---------------------------------------------------


def _stamp(root) -> str:
    con = duck.connect()
    try:
        return fr.rows(root, con)[0][0]["route_flood_version"]
    finally:
        con.close()


MOVERS = {
    "a shape's geometry": lambda: dict(routes=[
        (r, d, [(p, s, w if s != "s1" else line(0, 2))]) if r == "R1" else (r, d, ss)
        for r, d, ss in ROUTES for p, s, w in [ss[0]]][:1] + ROUTES[1:]),
    "a Cell's flood-prone share": lambda: dict(
        stormwater=[(0, 0.20, 0.00, 0.00), (1, 0.00, 0.00, 0.00),
                    (2, 0.00, 0.00, 0.90), (3, 0.00, 0.00, 0.00)]),
    "an extent polygon": lambda: dict(extent=EXTENT[:3]),
    "a flood label": lambda: dict(labels=LABELS[:2]),
}
KEEPERS = {
    "the not-analyzed share, which decides no number here": lambda: dict(
        stormwater=[(i, d, n, 0.5) for i, d, n, _ in STORMWATER]),
    "cell_stormwater's frozen_at, which is read by nothing": lambda: dict(
        frozen="2020-01-01T00:00:00Z"),
}


@pytest.mark.parametrize("what", sorted(MOVERS))
def test_the_stamp_moves_when_an_input_that_decides_a_number_moves(tmp_path, monkeypatch, what):
    monkeypatch.setattr(fr.features, "features_version", lambda _root: FEATURES_V)
    base = _stamp(plant(tmp_path / "base"))
    assert _stamp(plant(tmp_path / "moved", **MOVERS[what]())) != base, what


@pytest.mark.parametrize("what", sorted(KEEPERS))
def test_the_stamp_holds_when_a_column_that_decides_nothing_moves(tmp_path, monkeypatch, what):
    """The other direction, and the one that makes the stamp worth reading: a digest that
    moves on everything tells a consumer nothing. `share_not_analyzed` and `frozen_at` are
    real columns of a hashed table that this build never reads."""
    monkeypatch.setattr(fr.features, "features_version", lambda _root: FEATURES_V)
    base = _stamp(plant(tmp_path / "base"))
    assert _stamp(plant(tmp_path / "same", **KEEPERS[what]())) == base, what


def test_the_stamp_holds_across_two_builds_of_one_root(root):
    assert _stamp(root) == _stamp(root)


def test_the_stamp_moves_when_an_upstream_identity_moves():
    a = fr.route_flood_version({"label_version": "one"})
    assert a != fr.route_flood_version({"label_version": "two"})
    assert a == fr.route_flood_version({"label_version": "one"})


def test_the_stamp_covers_the_rules_that_decide_what_a_number_means(monkeypatch):
    """Which categories count as water and what makes a Cell flood-prone are not inputs, but
    changing either changes every number — so both are in the digest (flood 10's rule:
    hash what can move a published value)."""
    base = fr.route_flood_version({})
    monkeypatch.setattr(fr, "FLOODED", ("deep",))
    assert fr.route_flood_version({}) != base
    monkeypatch.undo()
    monkeypatch.setattr(fr, "PRONE", "share_deep > 0")
    assert fr.route_flood_version({}) != base


def test_the_stamp_does_not_hash_this_modules_prose():
    """flood 10's mirror rule. The digest is a function of its argument and the four frozen
    labels; nothing reads a docstring, a check-row sentence or a column name into it."""
    import inspect
    src = inspect.getsource(fr.route_flood_version)
    body = src.split('"""')[2]
    for barred in ("__doc__", "CHECK_COLUMNS", "SCHEMA", "unsourced("):
        assert barred not in body


# --- the check batch ----------------------------------------------------------------------


def test_the_batch_writes_with_the_declared_columns(root, built, tmp_path):
    rows_out = fr.census(list(built[0].values()), built[1])
    out = checks.write(root, fr.CHECK, rows_out, fr.CHECK_COLUMNS)   # asserts order itself
    got = [json.loads(x) for x in out.read_text().splitlines()]
    assert [tuple(r) for r in got] == [fr.CHECK_COLUMNS] * len(got)


def test_the_batch_has_one_whole_batch_row_and_one_row_per_scenario(built):
    rows_out = fr.census(list(built[0].values()), built[1])
    assert [r.subject for r in rows_out] == [
        fr.BATCH, "limited current", "moderate current", "extreme current"]
    batch = rows_out[0]
    assert batch.measures["routes"] == 6
    assert batch.measures["scenario"] is None     # a batch claim carries no scenario


def test_an_unreadable_scenario_is_inconclusive_and_never_a_failure(built):
    rows_out = {r.subject: r for r in fr.census(list(built[0].values()), built[1])}
    for subject in ("limited current", "extreme current"):
        r = rows_out[subject]
        assert r.outcome == checks.INCONCLUSIVE
        assert r.detail.strip()                                  # it says why
        assert r.measures["share_len_median"] is None            # NULL, never 0.0
    assert rows_out["moderate current"].outcome == checks.OK
    assert rows_out["moderate current"].measures["share_len_median"] is not None


def test_the_rc_is_two_while_a_scenario_cannot_be_measured(built):
    """`rc` 2 is INCONCLUSIVE and it is the designed steady state of this batch, not a
    failure — two of DEP's three scenarios have no current-sea-level source. GNU make
    flattens any recipe failure to its own 2, so a caller that must tell "could not read"
    from "broke" reads the batch, never `make`."""
    assert checks.rc(fr.census(list(built[0].values()), built[1])) == 2


def test_a_route_with_no_geometry_fails_the_batch(built):
    table = list(built[0].values())
    counts = dict(built[1], routes_zero_geometry=1)
    batch = fr.census(table, counts)[0]
    assert batch.outcome == checks.FAIL and "no geometry" in batch.detail


def test_an_empty_table_fails_rather_than_reporting_nothing(built):
    rows_out = fr.census([], dict(built[1], routes_zero_geometry=0))
    assert rows_out[0].outcome == checks.FAIL and rows_out[0].measures["routes"] == 0
    assert checks.rc(rows_out) == 1
    assert all(r.measures["route_flood_version"] is None for r in rows_out)


def test_every_row_renders(built):
    for r in fr.census(list(built[0].values()), built[1]):
        assert fr.line(r).startswith(("OK ", "BAD", "??? "[:3]))


# --- hour_of_week: the cross-engine trap --------------------------------------------------


@pytest.mark.parametrize("local, want", [
    ("2021-09-06 00:00:00", 0),      # Monday 00 local is 0 - gold.baseline()'s own convention
    ("2021-09-06 13:00:00", 13),
    ("2021-09-05 23:00:00", 167),    # Sunday 23 local is the last hour of the week
    ("2021-09-02 14:00:00", 86),     # Ida: Thursday, (4-1)*24 + 14
])
def test_hour_of_week_is_monday_first(local, want):
    """`gold.baseline()` builds this in SPARK, whose `dayofweek` is 1=Sunday, as
    `((dayofweek + 5) % 7) * 24 + hour`. DuckDB's `dayofweek` is 0=Sunday, so COPYING that
    expression shifts every hour by a day — measured, Monday 00:00 reads 144 under the
    copied form. Both are driven here so a future edit cannot quietly swap them."""
    con = duck.connect()
    try:
        ours = con.execute(
            "SELECT " + fr.HOUR_OF_WEEK.format(t="ts") + " FROM (SELECT ?::TIMESTAMPTZ AS ts)",
            [f"{local}-04:00"]).fetchone()[0]
        naive = con.execute(
            "SELECT ((dayofweek(ts) + 5) % 7) * 24 + hour(ts) FROM (SELECT ?::TIMESTAMP AS ts)",
            [local]).fetchone()[0]
    finally:
        con.close()
    assert ours == want
    if want in (0, 167):
        assert naive != want, "the copied Spark expression must not be what this module uses"


def test_the_baseline_window_names_come_from_gold_and_the_spans_from_ref():
    """Neither half is typed here: `ref.WINDOWS` is imported (that module opens no JVM) and
    the names are regexed out of gold.py's own declaration, so a rename there raises rather
    than answering with a stale map."""
    got = fr.baseline_windows()
    assert set(got) == {"w1", "w2"}
    assert got["w1"] == (date(2021, 8, 16), date(2021, 10, 15))
    assert tuple(got.values()) == fr.WINDOWS


# --- the real root -------------------------------------------------------------------------


@real_root
def test_the_real_build_moves_no_detector_stamp():
    """IMPACT, NEVER A DETECTOR INPUT — driven rather than asserted in prose. The four stamps
    are read on both sides of a real build, and `features_version` has a known-good value:
    flood-build 19 proved BEFORE == AFTER across its whole build at the same digest."""
    root = Path(REAL)
    before = fr.stamps(root)
    fr.build(root)
    after = fr.stamps(root)
    assert before == after
    assert before["features_version"] == "6b6f61e0231d6237ba93e9126eeb08fc0e16de21"


@real_root
def test_the_real_exhibit_universe_is_measured_not_assumed():
    """N is the events whose days intersect the HOURS gold/cell_hour_route holds. Asserted as
    a PROPERTY, not as a 2: the day pipeline-build 17's backfill lands, N moves and this test
    must not have to be edited to stay true."""
    doc = fr.exhibit(Path(REAL))
    events = doc["events"]
    assert doc["universe"]["n_events"] == len(events)
    assert events, "no flood event intersects any month gold/cell_hour_route holds"
    for ev in events:
        assert ev["n_hours"] > 0 and ev["days_covered"]
        assert ev["late_share_available"] <= ev["n_routes"]
        # the two halves that cannot both be full today, and the asset says which is which
        assert ev["baseline_window"] is None or ev["speed_ratio_available"] > 0


@real_root
def test_the_exhibits_dry_side_holds_no_flood_event_day():
    """A comparison whose dry side contains somebody else's flood is not a dry side."""
    root = Path(REAL)
    con = duck.connect()
    try:
        every = fr.all_event_days(con, root)
        for ev in fr.universe(con, root):
            got = fr.other_days(con, root, ev, every)
            assert got, ev["event_id"]
            assert all(r["n_days"] >= 1 for r in got.values())
        # and the cut is real: every event day is in the set the predicate excludes
        assert {d for e in fr.universe(con, root) for d in e["days"]} <= every
    finally:
        con.close()


@real_root
def test_the_exhibit_renders_and_names_what_it_cannot_say():
    doc = fr.exhibit(Path(REAL))
    md = fr.markdown(doc)
    assert "no interval" in md.lower() and "CSI" in md
    assert "base rate" in md
    assert str(doc["universe"]["n_events"]) in md
    for ev in doc["events"]:
        assert ev["event_id"] in md
        if ev["baseline_window"] is None:
            assert "ABSENT" in md


@real_root
def test_the_real_table_is_reproducible_and_its_shares_are_bounded():
    root = Path(REAL)
    a = (root / "gold" / fr.TABLE / "part-00000.parquet").read_bytes() \
        if (root / "gold" / fr.TABLE / "part-00000.parquet").exists() else None
    table, rows_out = fr.build(root)
    b = (root / "gold" / fr.TABLE / "part-00000.parquet").read_bytes()
    if a is not None:
        assert a == b, "a rebuild off unchanged inputs must be byte-identical"
    batch = next(r for r in rows_out if r.subject == fr.BATCH)
    assert batch.measures["routes_zero_geometry"] == 0 and batch.outcome == checks.OK
    for row in table:
        assert row["length_m"] > 0
        assert 0.0 <= row["share_len_moderate"] <= 1.0
        assert row["share_len_limited"] is None and row["share_len_extreme"] is None
        assert row["n_cells"] >= row["n_cells_flood_prone"]


# --- the exhibit, on a fixture ------------------------------------------------------------


@pytest.fixture
def doc(root):
    return fr.exhibit(root)


def test_the_exhibit_universe_is_the_hours_held_not_the_months(doc):
    """Both planted events have hours in `cell_hour_route`, and the asset says N out loud."""
    assert doc["universe"]["n_events"] == 2 == len(doc["events"])
    assert [e["event_id"] for e in doc["events"]] == ["2021-09-01", "2023-09-29"]
    assert doc["events"][0]["days_covered"] == ["2021-09-02"]      # not 09-01, which has no hours
    assert set(doc["universe"]["months_held"]) == {"2021-09", "2023-09"}
    # n_hours is the HOURS HELD, counted, not the 24 a whole day would have. It is the number
    # that says how thin this evidence is - the real 2021-09 partition carries 29 hours across
    # two days, not a month - so a hard-coded 24 would flatter every event on the page.
    assert [e["n_hours"] for e in doc["events"]] == [2, 1]
    assert doc["events"][0]["n_routes"] == 1


def test_the_exhibit_weights_a_share_by_the_rows_that_have_one(doc):
    """100 arrivals carry a `late_share` of 0.5 and 900 carry none. The share of the hours
    that HAVE one is 0.5; dividing by all 1,000 arrivals gives 0.05 and is a different claim
    — it reads the missing rows as zero-late. A mutation doing exactly that survived the
    whole suite until this fixture existed, because on the real root only 3,161 of 1.36 M
    rows are NULL and the two answers differ in the fourth digit."""
    r = next(x for x in doc["events"][0]["routes"] if x["route_id"] == "R1")
    assert r["late_share"] == pytest.approx(0.5)
    assert r["ewt_s"] == pytest.approx(60.0)
    assert r["n_hours"] == 2 and r["n_events"] == 1000


def test_the_exhibit_reports_the_speed_ratio_against_the_window_on_disk(doc):
    """`cell_hourofweek_baseline` carries `speed_dry` and NO delay column, so the route's own
    baseline for the same hours is a SPEED — 1000 m / 250 s = 4.0 dry against 1000 m / 500 s
    = 2.0 on the event hour."""
    ev = doc["events"][0]
    r = next(x for x in ev["routes"] if x["route_id"] == "R1")
    assert ev["baseline_window"] == "w1"
    assert r["speed_mps"] == pytest.approx(2.0) and r["speed_dry"] == pytest.approx(4.0)
    assert r["speed_ratio"] == pytest.approx(0.5)


def test_a_baseline_window_in_range_but_not_on_disk_is_absent_not_named(doc):
    """2023-09-29 sits inside `w2`'s DECLARED span and no `w2` partition was planted. The
    window must read ABSENT: naming a window nothing built would put a label on a comparison
    that never happened, and the join is silently empty either way — so only the reported
    NAME can tell the two apart."""
    ev = doc["events"][1]
    assert ev["baseline_window"] is None
    assert ev["speed_ratio_available"] == 0
    assert all(x["speed_dry"] is None for x in ev["routes"])


def test_the_baseline_overlap_is_reported_where_a_window_exists(doc):
    """`gold.baseline()` masks by wetness, not by date, so an event day's own post-storm dry
    hours enter its own baseline. The asset publishes the calendar behind that rather than
    leaving a reader to assume independence."""
    o = doc["events"][0]["baseline_overlap"]
    assert o["window"] == "w1" and o["days_sharing_the_event_weekday"] == 9   # nine Thursdays
    assert o["event_days_inside_the_window"] == ["2021-09-02"]
    assert doc["events"][1]["baseline_overlap"] is None      # no window, nothing to report


def test_the_substitute_dry_side_is_other_weekdays_of_the_same_month(doc):
    """Labelled as a substitute everywhere: it is NOT the named baseline table and it is NOT
    hour-of-week matched. 2021-09-03 is the Friday that is not an event day."""
    r = next(x for x in doc["events"][0]["routes"] if x["route_id"] == "R1")
    o = r["other_weekdays"]
    # 10 arrivals with a late_share of 0.1 and 90 without: 0.1 weighted over the rows that
    # have one, 0.01 weighted over all 100. `other_days` holds its OWN copy of that rule and
    # mutating it alone survived a round until this second row existed.
    assert o["late_share"] == pytest.approx(0.1) and o["ewt_s"] == pytest.approx(10.0)
    assert o["n_days"] == 1 and o["n_hours"] == 2


def test_the_exhibit_markdown_names_what_it_cannot_say(doc):
    md = fr.markdown(doc)
    assert "N = 2 flood events" in md
    assert "no interval" in md.lower() and "CSI" in md and "base rate" in md
    assert "ABSENT" in md                       # the 2023 event's missing window
    assert "NOT the named baseline table" in md
