"""flood-build 19: the scenario extents survive.

Two shapes get most of the attention here, because both are ways this table could be
WRONG WHILE LOOKING RIGHT. The first is a scenario that reads as empty — the repo's only
GDAL does exactly that to DEP's Limited geodatabase on an extracted copy — which would
publish "1.77 in/hr floods nothing". The second is the transform: a lon/lat pair wired
backwards produces a plausible map of nowhere and never an error (notify 04's axis trap,
one level up). Both are gated rather than reviewed.

No `.gdb` is a fixture: GDAL is read-only here (there is no FGDB writer in this stack), so
the reader's guards are driven through a stubbed connection and every geometry rule is
driven through hand polygons in the FGDB's own CRS.
"""
import json
import zipfile
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import shapely

from raincheck import checks, contract, features, publish, stormwater_extent as sx
from raincheck.paths import data_root

# Hand geometry in EPSG:2263 (NY Long Island ftUS), around Times Square. A square 500 ft on
# a side is ~2.3 hectares - big enough that nothing here is testing the identity element.
X, Y = 989_000.0, 214_000.0


def box(dx: float = 0.0, dy: float = 0.0, w: float = 500.0):
    """A square with ONE redundant vertex on its south edge, half a tolerance off true.

    A plain `shapely.box` has five coordinates and simplification cannot remove any of
    them, so every vertex-count assertion would pass on `5 == 5` and a simplify that did
    nothing would look identical to one that worked - the degenerate-fixture trap. This
    shape loses exactly one vertex at the shipped tolerance."""
    x0, y0 = X + dx, Y + dy
    return shapely.Polygon([(x0, y0), (x0 + w / 2, y0 + 0.5 * sx.TOLERANCE), (x0 + w, y0),
                            (x0 + w, y0 + w), (x0, y0 + w)])


@pytest.fixture
def parts():
    """One scenario's classes as `scenario_parts` would return them."""
    return {"nuisance": [box()], "deep": [box(1000)]}


@pytest.fixture
def built(tmp_path, monkeypatch, parts):
    """A three-scenario table on a scratch root, built through the real `rows`/`write` with
    only the two SNAPSHOT readers stubbed - so the mask rule, the simplify, the transform,
    the row grain and the GeoParquet write are all the shipped ones."""
    scenarios = (sx.Scenario("moderate", "current", 2.13, "moderate-current"),
                 sx.Scenario("moderate", "2050", 2.13, "moderate-2050"),
                 sx.Scenario("limited", "current", 1.77, "limited-current"))

    def fake_parts(zip_path, s):
        if s.scenario == "limited":
            raise sx.Unreadable("stub: the CDF container")
        out = dict(parts)
        if s.horizon == "2050":
            out = out | {"future_high_tides": [box(2000)]}
        return out

    monkeypatch.setattr(sx.features, "stormwater_zip", lambda root: Path("/nowhere.zip"))
    # the mask overlaps `nuisance` by half, so the disjointness rule has something to do
    monkeypatch.setattr(sx.features, "mask_polygons",
                        lambda root: [shapely.box(X + 250, Y, X + 750, Y + 500)])
    monkeypatch.setattr(sx, "scenario_parts", fake_parts)
    table, counts = sx.rows(tmp_path, scenarios)
    sx.write(tmp_path, table)
    return tmp_path, counts, scenarios


# --- the datasets and the coded domain ---------------------------------------------------


def zip_names():
    z = data_root() / "snapshots" / "stormwater" / features.SW_ZIP
    if not z.exists():
        pytest.skip(f"no {features.SW_ZIP} under {z.parent}: point RAINCHECK_ARCHIVE_ROOT "
                    "at a data root that has the snapshot")
    with zipfile.ZipFile(z) as f:
        return set(f.namelist())


def test_all_four_dataset_paths_are_literal_entries_in_the_pinned_zip():
    """The paths are copied from `unzip -l`, and this is what says so. DEP's naming is not
    a rule: the 2050 dataset is spelled `..._2_13_per_hr_...` with NO "inches" while its
    three siblings all have it, so anything derived from a sibling by substitution names a
    file that does not exist."""
    names = zip_names()
    for s in sx.SCENARIOS:
        assert s.dataset + "/" in names, f"{s.scenario}/{s.horizon} names a path not in the zip"
    (mod2050,) = [s for s in sx.SCENARIOS if s.horizon == "2050"]
    assert "_2_13_per_hr_with_2050_" in mod2050.dataset
    assert "inches" not in mod2050.dataset.rsplit("/", 1)[1]
    # and the trap that spelling sets: the "obvious" name is absent from the zip
    assert mod2050.dataset.replace("_2_13_per_hr_", "_2_13_inches_per_hr_") + "/" not in names


def test_the_moderate_current_dataset_is_features_own_constant_and_not_a_fifth_copy():
    (mod,) = [s for s in sx.SCENARIOS if s.key == ("moderate", "current")]
    assert mod.dataset == features.SW_SCENARIO


def test_the_coded_domain_extends_features_own_rather_than_retyping_it():
    """`features.SW_CATEGORY` is the whole domain of the current-sea-level scenarios; the
    SLR ones add code 3. Deriving 1 and 2 FROM that constant is what stops the two homes
    drifting - a retyped {1: "nuisance", 2: "deep"} could be edited on one side only."""
    for code, name in features.SW_CATEGORY.items():
        assert sx.CATEGORY[code] == name
    assert sx.CATEGORY[3] == "future_high_tides"
    assert sx.MASK == "not_analyzed" and sx.MASK not in sx.CATEGORY.values()


def test_the_four_scenarios_are_distinct_and_carry_deps_three_intensities():
    assert len({s.key for s in sx.SCENARIOS}) == len(sx.SCENARIOS) == 4
    assert sorted({s.rain_in_hr for s in sx.SCENARIOS}) == [1.77, 2.13, 3.66]
    assert {s.horizon for s in sx.SCENARIOS} == {"current", "2050", "2080"}
    # DEP publishes Extreme at 2080 ONLY - the reason `geo` is derived from the table and
    # not from the three file names the ticket box asked for.
    assert {s.scenario for s in sx.SCENARIOS if s.horizon == sx.CURRENT} == {"limited", "moderate"}


# --- the unreadable guard ----------------------------------------------------------------


class FakeCon:
    def __init__(self, rows=(), raise_on_read=None):
        self.rows, self.raise_on_read, self.closed = list(rows), raise_on_read, False

    def execute(self, sql, params=None):
        if "ST_Read" in sql and self.raise_on_read:
            raise self.raise_on_read
        return self

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True


def test_a_dataset_that_opens_and_yields_nothing_is_refused_not_published(monkeypatch):
    """GDAL 3.8.5 does exactly this to the Limited geodatabase on an extracted copy: opens
    it, returns zero features, raises nothing. Without this guard the scenario would be
    written with no polygons and render as "1.77 in/hr floods nothing"."""
    con = FakeCon(rows=[])
    monkeypatch.setattr(sx.duck, "connect", lambda: con)
    with pytest.raises(sx.Unreadable, match="returned NO features"):
        sx.scenario_parts(Path("/z.zip"), sx.SCENARIOS[0])
    assert con.closed


def test_a_dataset_that_will_not_open_is_the_same_refusal(monkeypatch):
    """The other half of the same fact: through /vsizip the SAME file raises instead. A
    reader that handled only one of the two arrivals still ships the other."""
    import duckdb

    monkeypatch.setattr(sx.duck, "connect",
                        lambda: FakeCon(raise_on_read=duckdb.IOException("Could not open")))
    with pytest.raises(sx.Unreadable, match="would not open"):
        sx.scenario_parts(Path("/z.zip"), sx.SCENARIOS[0])


def test_an_unknown_flooding_category_stops_the_build(monkeypatch):
    """A fifth coded value means DEP republished with a class nobody has decided how to
    draw. Silently dropping it is how `not_analyzed` would have become absence."""
    monkeypatch.setattr(sx.duck, "connect",
                        lambda: FakeCon(rows=[(9, shapely.to_wkb(box()))]))
    with pytest.raises(RuntimeError, match="unknown Flooding_Category 9"):
        sx.scenario_parts(Path("/z.zip"), sx.SCENARIOS[1])


def test_only_the_scenario_unreadable_names_may_go_missing(tmp_path, monkeypatch):
    """`UNREADABLE` is a named, measured exception for one container, not a blanket
    tolerance: any other scenario that cannot be read fails the whole build."""
    monkeypatch.setattr(sx.features, "stormwater_zip", lambda root: Path("/nowhere.zip"))
    monkeypatch.setattr(sx.features, "mask_polygons", lambda root: [])
    monkeypatch.setattr(sx, "scenario_parts",
                        lambda z, s: (_ for _ in ()).throw(sx.Unreadable("stub")))
    (limited,) = [s for s in sx.SCENARIOS if s.key in sx.UNREADABLE]
    table, counts = sx.rows(tmp_path, (limited,))
    assert table == [] and counts == {}
    (extreme,) = [s for s in sx.SCENARIOS if s.horizon == "2080"]
    assert extreme.key not in sx.UNREADABLE
    with pytest.raises(sx.Unreadable):
        sx.rows(tmp_path, (extreme,))


def test_the_one_named_exception_is_the_limited_scenario_and_it_says_why():
    assert set(sx.UNREADABLE) == {("limited", "current")}
    why = sx.UNREADABLE["limited", "current"]
    assert "CDF" in why and "OpenFileGDB" in why and "not a retry" in why


# --- the transform and the simplify ------------------------------------------------------


def test_the_axis_gate_passes_as_shipped_and_catches_a_transform_wired_backwards(monkeypatch):
    """A lon/lat pair swapped end for end lands in the Indian Ocean and raises nothing
    anywhere downstream - notify 04 measured the same class of silence one level down, in
    DuckDB's (lat, lon) distance arguments. Gate the direction on a known pair."""
    sx.check_axis()                                    # the shipped transformer

    real = sx.FROM_SW               # captured BEFORE the patch, or Swapped calls itself

    class Swapped:
        def transform(self, x, y):
            lon, lat = real.transform(x, y)
            return lat, lon

    monkeypatch.setattr(sx, "FROM_SW", Swapped())
    with pytest.raises(RuntimeError, match="wired wrong"):
        sx.check_axis()


def test_the_transform_lands_nyc_geometry_inside_nyc(parts):
    g = sx.to_wgs(parts["nuisance"][0])
    lon, lat = g.centroid.x, g.centroid.y
    assert -74.3 < lon < -73.6 and 40.4 < lat < 41.0


def test_simplify_runs_in_the_source_crs_so_the_tolerance_is_metres_and_not_degrees():
    """The knob is metres of ground. A vertex nudged well INSIDE the tolerance is removed
    and one well outside survives - which no degree-valued tolerance could reproduce, since
    5.0 degrees would flatten the whole city and 5.0 e-5 degrees would keep both."""
    near = 0.5 * sx.TOLERANCE                          # ~2.5 m off a straight edge
    far = 8.0 * sx.TOLERANCE                           # ~40 m off it
    ring = lambda off: shapely.Polygon([                        # noqa: E731
        (X, Y), (X + 250, Y + off), (X + 500, Y), (X + 500, Y + 500), (X, Y + 500)])
    kept, counts = sx.simplify({"a": [ring(near)], "b": [ring(far)]})
    assert counts["a"][0] == counts["b"][0] == 6       # both start with five corners + close
    assert counts["a"][1] == 5                         # the near nudge is inside 5 m: gone
    assert counts["b"][1] == 6                         # the far one is real relief: kept
    assert all(not g.is_empty for v in kept.values() for g in v)


def test_the_recorded_tolerance_is_the_one_the_geometry_moved_by():
    """`tolerance_m` on every check row has to be the constant the build actually used, or
    the recorded provenance is decoration."""
    assert sx.TOLERANCE == pytest.approx(sx.TOLERANCE_M * features.US_SURVEY_FT)
    assert 0 < sx.TOLERANCE_M <= 25.0                  # a display knob, not a redefinition


# --- "not analyzed" is a category, never an absence --------------------------------------


def test_the_mask_is_its_own_category_on_every_scenario(parts):
    out = sx.with_mask(parts, shapely.box(X + 250, Y, X + 750, Y + 500))
    assert sx.MASK in out, "the exclusion mask must always be considered, per scenario"
    assert out["nuisance"] and out["deep"]             # the modelled classes are untouched


def test_the_mask_never_claims_ground_a_modelled_class_claims(parts):
    """`features.build()`'s rule, reused: the 0.19%-of-flood-area overlap resolves toward
    flooded. Disjoint categories are what let a renderer draw them in any order."""
    mask = shapely.box(X + 250, Y, X + 750, Y + 500)   # half over `nuisance`
    out = sx.with_mask(parts, mask)
    na = shapely.union_all(out[sx.MASK])
    for name in ("nuisance", "deep"):
        for g in out[name]:
            assert na.intersection(g).area == pytest.approx(0.0, abs=1e-6)
    overlap = mask.intersection(parts["nuisance"][0]).area
    assert na.area == pytest.approx(mask.area - overlap, rel=1e-9)
    assert 0 < overlap < mask.area, "the fixture must overlap, or this assertion proves nothing"


def test_a_mask_wholly_under_a_flood_class_leaves_no_polygon_rather_than_a_zero_row(parts):
    out = sx.with_mask(parts, shapely.box(X + 100, Y + 100, X + 200, Y + 200))
    assert out[sx.MASK] == []


# --- the table ---------------------------------------------------------------------------


def test_the_table_is_geoparquet_and_the_crs_travels_with_the_file(built):
    root, _, _ = built
    md = pq.ParquetFile(root / "silver" / sx.TABLE / "part-00000.parquet").schema_arrow.metadata
    geo = json.loads(md[b"geo"])
    assert geo["primary_column"] == "geometry"
    assert geo["columns"]["geometry"]["encoding"] == "WKB"
    w, s, e, n = geo["columns"]["geometry"]["bbox"]
    assert -74.3 < w < e < -73.6 and 40.4 < s < n < 41.0   # lon/lat, not feet


def test_the_grain_is_one_row_per_polygon_with_its_scenario_and_intensity(built):
    root, _, _ = built
    t = pq.read_table(root / "silver" / sx.TABLE).to_pylist()
    assert [c for c in pq.read_table(root / "silver" / sx.TABLE).column_names] == [
        "scenario", "horizon", "rain_in_hr", "category", "poly", "geometry",
        "src_asof", "zip_sha256"]
    assert all(r["src_asof"] == features.SRC_ASOF for r in t)
    assert {r["zip_sha256"] for r in t} == {features.SW_ZIP_SHA256}
    assert {(r["scenario"], r["horizon"], r["rain_in_hr"]) for r in t} == {
        ("moderate", "current", 2.13), ("moderate", "2050", 2.13)}
    # `poly` is 0-based and dense within its (scenario, horizon, category) - the total order
    # the byte-identical export leans on
    for key in {(r["scenario"], r["horizon"], r["category"]) for r in t}:
        polys = sorted(r["poly"] for r in t
                       if (r["scenario"], r["horizon"], r["category"]) == key)
        assert polys == list(range(len(polys)))


def test_the_table_keeps_the_horizons_the_host_will_never_be_shown(built):
    """D3 is an EXPORT rule, not a build rule: a later climate view is a toggle on this
    table, not a rebuild."""
    root, _, _ = built
    t = pq.read_table(root / "silver" / sx.TABLE).to_pylist()
    assert any(r["horizon"] == "2050" for r in t)
    assert any(r["category"] == "future_high_tides" for r in t)
    assert all(r["horizon"] != sx.CURRENT for r in t if r["category"] == "future_high_tides")


def test_the_build_writes_only_its_own_table_and_its_own_check_batch(built, monkeypatch):
    """`features_version` hashes silver/asset_features, ref/assets and frozen constants.
    Nothing here may touch any of them: a moved stamp rolls matrix_version and demands a
    refit while flood 12's replay verdict is pending. This watches the whole root rather
    than trusting the reading."""
    root, counts, scenarios = built
    for owed in ("silver/asset_features", "ref/assets", "silver/cell_stormwater"):
        (root / owed).mkdir(parents=True, exist_ok=True)
        (root / owed / "part-00000.parquet").write_bytes(b"untouched")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    monkeypatch.setattr(sx.features, "stormwater_zip", lambda r: Path("/nowhere.zip"))
    monkeypatch.setattr(sx.features, "mask_polygons", lambda r: [])
    monkeypatch.setattr(sx, "scenario_parts", lambda z, s: {"deep": [box()]})
    table, _ = sx.rows(root, scenarios[:1])
    sx.write(root, table)
    checks.write(root, sx.CHECK, sx.census(root), sx.CHECK_COLUMNS)
    after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    touched = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
    allowed = (root / "silver" / sx.TABLE, root / "checks")
    assert touched and all(any(p.is_relative_to(a) for a in allowed) for p in touched), \
        f"wrote outside its own table: {sorted(str(p) for p in touched)}"


def test_a_moved_features_version_stops_the_run(tmp_path, monkeypatch):
    stamps = iter(["aaaa", "bbbb"])
    monkeypatch.setattr(sx.features, "features_version", lambda root: next(stamps))
    monkeypatch.setattr(sx, "data_root", lambda: tmp_path)
    monkeypatch.setattr(sx, "build", lambda root: [])
    with pytest.raises(SystemExit, match="features_version MOVED"):
        sx.main([])


# --- the check batch ---------------------------------------------------------------------


def test_every_row_carries_the_declared_columns_in_order(built):
    root, counts, scenarios = built
    rows = sx.census(root, counts, scenarios)
    assert checks.write(root, sx.CHECK, rows, sx.CHECK_COLUMNS).exists()
    assert sx.CHECK_COLUMNS[:4] == checks.CORE
    for r in rows:
        assert tuple(r.flat()) == sx.CHECK_COLUMNS
        assert r.measures["zip_sha256"] == features.SW_ZIP_SHA256
        assert r.measures["tolerance_m"] == sx.TOLERANCE_M


def test_a_scenario_that_built_gets_a_row_per_category_with_both_vertex_counts(built):
    root, counts, scenarios = built
    rows = {r.subject: r for r in sx.census(root, counts, scenarios)}
    r = rows["moderate current nuisance"]
    assert r.outcome == checks.OK and r.measures["polygons"] > 0
    assert r.measures["vertices_src"] > r.measures["vertices_kept"] > 0
    assert rows["moderate current not_analyzed"].outcome == checks.OK
    assert "moderate 2050 future_high_tides" in rows


def test_a_declared_scenario_the_table_does_not_hold_is_reported_every_run(built):
    """A suite has to be able to expect on the SHAPE - one row per declared scenario - and
    not on whichever scenarios happened to build (orch 08's rule: batch-level claims go over
    the whole batch)."""
    root, counts, scenarios = built
    rows = sx.census(root, counts, scenarios)
    for s in scenarios:
        assert any(r.measures["scenario"] == s.scenario
                   and r.measures["horizon"] == s.horizon for r in rows)


def test_the_unreadable_container_is_inconclusive_and_anything_else_missing_is_a_failure(built):
    """"OpenFileGDB cannot decompress this container" says nothing about the data, which is
    what INCONCLUSIVE means here. A scenario absent for no known reason is a real gap."""
    root, counts, scenarios = built
    (limited,) = [s for s in scenarios if s.scenario == "limited"]
    row = [r for r in sx.census(root, counts, scenarios) if r.subject.startswith("limited")]
    assert len(row) == 1 and row[0].outcome == checks.INCONCLUSIVE
    assert "CDF" in row[0].detail and row[0].measures["rain_in_hr"] == 1.77
    assert row[0].measures["category"] is None
    assert checks.rc(sx.census(root, counts, scenarios)) == 2

    ghost = sx.Scenario("extreme", "2080", 3.66, "not-built")
    assert ghost.key not in sx.UNREADABLE
    rows = sx.census(root, counts, scenarios + (ghost,))
    (bad,) = [r for r in rows if r.subject == "extreme 2080"]
    assert bad.outcome == checks.FAIL and "absent from the table" in bad.detail
    assert checks.rc(rows) == 1


# --- the export --------------------------------------------------------------------------


def test_only_the_current_sea_level_scenarios_reach_the_host(built, tmp_path):
    """D3, and the reason is in DESTINATION §3.C: a 2080 climate projection drawn beside a
    live rain rate reads as a forecast of tonight."""
    root, _, _ = built
    out = tmp_path / "geo"
    written = sx.export(root, out)
    assert set(written) == {"stormwater-moderate.geojson"}
    assert not any("2050" in p.read_text() for p in out.iterdir())


def test_the_served_set_is_derived_from_the_table_not_from_a_list_of_file_names(built, tmp_path):
    """`stormwater-limited.geojson` is absent because its geodatabase is unreadable, not
    because a list omits it - so it appears with no code change the day the table has it."""
    root, counts, scenarios = built
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    part = root / "silver" / sx.TABLE / "part-00000.parquet"
    con.execute(f"""COPY (SELECT * FROM read_parquet('{part}')
                          UNION ALL BY NAME
                          SELECT * REPLACE ('limited' AS scenario, 1.77 AS rain_in_hr)
                          FROM read_parquet('{part}') WHERE horizon = 'current')
                    TO '{part}.new' (FORMAT PARQUET)""")
    con.close()
    Path(f"{part}.new").replace(part)
    out = tmp_path / "geo2"
    assert set(sx.export(root, out)) == {"stormwater-moderate.geojson",
                                         "stormwater-limited.geojson"}


def test_every_category_is_one_multipolygon_a_map_can_draw(built, tmp_path):
    """`ST_Collect` over a mixed Polygon/MultiPolygon list returns a GeometryCollection,
    which MapLibre does not render - measured, and it was the first shape this exporter
    produced. Reducing a polygon's precision can split it, so the parts are dumped back to
    polygons before they are collected."""
    root, _, _ = built
    (path,) = sx.export(root, tmp_path / "geo").values()
    doc = json.loads(path.read_text())
    assert doc["type"] == "FeatureCollection"
    for f in doc["features"]:
        assert f["geometry"]["type"] == "MultiPolygon", f["properties"]["category"]
        assert len(f["geometry"]["coordinates"]) == f["properties"]["n_polygons"] > 0


def test_not_analyzed_survives_all_the_way_to_the_file(built, tmp_path):
    """The refusal `features.sample()` documents, kept end to end: a consumer must be ABLE
    to draw "DEP did not model here", because painting it dry is the one imputation this
    encoding exists to forbid."""
    root, _, _ = built
    (path,) = sx.export(root, tmp_path / "geo").values()
    cats = {f["properties"]["category"] for f in json.loads(path.read_text())["features"]}
    assert sx.MASK in cats and {"deep", "nuisance"} <= cats


def test_the_payload_carries_the_intensity_and_the_licence_credit(built, tmp_path):
    root, _, _ = built
    (path,) = sx.export(root, tmp_path / "geo").values()
    doc = json.loads(path.read_text())
    assert "NYC Department of Environmental Protection" in doc["attribution"]
    assert "not an observation of water" in doc["attribution"]
    assert str(features.SRC_ASOF) in doc["attribution"]
    assert all(f["properties"]["rain_in_hr"] == 2.13 for f in doc["features"])
    assert all(f["properties"]["horizon"] == sx.CURRENT for f in doc["features"])


def test_coordinates_are_reduced_to_five_decimal_places(built, tmp_path):
    root, _, _ = built
    (path,) = sx.export(root, tmp_path / "geo").values()
    for f in json.loads(path.read_text())["features"]:
        for poly in f["geometry"]["coordinates"]:
            for ring in poly:
                for lon, lat in ring:
                    assert round(lon, 5) == lon and round(lat, 5) == lat


def test_re_export_is_byte_identical(built, tmp_path):
    """`tests/test_export.py`'s rule: every aggregate ORDER BY'd and every coordinate
    explicitly reduced, so these files diff cleanly as evidence artifacts."""
    root, _, _ = built
    first = {n: p.read_bytes() for n, p in sx.export(root, tmp_path / "a").items()}
    again = {n: p.read_bytes() for n, p in sx.export(root, tmp_path / "b").items()}
    assert first and first == again


def test_an_export_from_an_empty_table_refuses_rather_than_writing_an_empty_map(tmp_path,
                                                                               monkeypatch):
    sx.write(tmp_path, [])
    monkeypatch.setattr(sx, "data_root", lambda: tmp_path)
    with pytest.raises(SystemExit, match="nothing exported"):
        sx.main(["--geo"])


# --- the publish family ------------------------------------------------------------------


def test_geo_is_a_tree_family_under_files_geo_and_is_not_gated():
    fam = publish.FAMILIES["geo"]
    assert fam.files == () and fam.prefix == "files/geo/"
    assert fam.cache == publish.BUILD_CACHE and not fam.gated
    assert fam.src() == publish.WEB / "files" / "geo"


def test_the_publisher_accepts_a_geo_tree_and_types_it_for_a_browser(built, tmp_path):
    root, _, _ = built
    out = tmp_path / "geo"
    sx.export(root, out)
    (item,) = publish.plan("geo", out)
    assert item.key == "files/geo/stormwater-moderate.geojson"
    assert item.content_type == "application/geo+json"
    assert item.cache == publish.BUILD_CACHE


def test_a_new_family_is_additive_and_demanded_no_contract_bump():
    assert ("geo", "files/geo/**", contract.TREE) in contract.surface()
    assert not contract.PROMISE[contract.CONTRACT] - contract.surface()
    assert contract.SCHEMA["files/geo/**"].endswith("(flood-build 19)")


def test_the_contract_document_carries_the_two_limits_this_family_ships_with():
    """Both are shipped FACTS, and a doc that quietly drops them turns a measured absence
    into an unexplained hole for the next reader."""
    doc = (Path(publish.REPO) / contract.DOC).read_text()
    assert "files/geo/**" in doc and "not_analyzed" in doc
    assert "cdf" in doc.lower(), "the doc must say why the 1.77 in/hr scenario is absent"
    assert "sea-level-rise" in doc or "sea level rise" in doc


# --- the real snapshot -------------------------------------------------------------------


def real_codes(z: Path, s: sx.Scenario) -> set[int] | None:
    """Every `Flooding_Category` one real dataset holds, WITHOUT materialising 4.7 M
    vertices - the geometry path is exercised once below, on the scenario that ships."""
    from raincheck import duck

    con = duck.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    try:
        return {r[0] for r in con.execute(
            "SELECT DISTINCT Flooding_Category FROM ST_Read(?)",
            [f"/vsizip/{z}/{s.dataset}"]).fetchall()} or None
    except Exception:
        return None
    finally:
        con.close()


def test_the_real_geodatabases_hold_exactly_the_coded_domain_this_module_declares():
    """The canary over DEP's real files: every code the four datasets contain is in
    CATEGORY, code 3 appears on the SLR horizons ONLY, and the one dataset that yields
    nothing is the one UNREADABLE names."""
    zip_names()                                        # skips when the snapshot is absent
    z = data_root() / "snapshots" / "stormwater" / features.SW_ZIP
    seen = {s.key: real_codes(z, s) for s in sx.SCENARIOS}
    assert {k for k, v in seen.items() if v is None} == set(sx.UNREADABLE)
    for key, codes in seen.items():
        if codes is None:
            continue
        assert codes <= set(sx.CATEGORY), f"{key} holds a code outside the declared domain"
        assert {1, 2} <= codes                          # nuisance and deep, every scenario
        assert (3 in codes) == (key[1] != sx.CURRENT)   # Future High Tides: SLR only


def test_the_shipped_scenario_reads_through_the_real_driver_into_real_polygons():
    """One end-to-end read of the geodatabase that actually exports, through the shipped
    `scenario_parts` - the codes canary above says nothing about the geometry path."""
    zip_names()
    z = data_root() / "snapshots" / "stormwater" / features.SW_ZIP
    (mod,) = [s for s in sx.SCENARIOS if s.key == ("moderate", sx.CURRENT)]
    parts = sx.scenario_parts(z, mod)
    assert set(parts) == {"deep", "nuisance"}
    assert all(len(v) > 1000 for v in parts.values())
    assert all(g.geom_type == "Polygon" and not g.is_empty
               for v in parts.values() for g in v)


def test_the_snapshot_is_read_through_features_own_sha_pinned_path():
    """One sha check per run: `stormwater_zip` re-reads and re-hashes 33.8 MB on every call,
    so the path is taken once in `rows()` and carried."""
    r = data_root()
    if not (r / "snapshots" / "stormwater" / features.SW_ZIP).exists():
        pytest.skip("no stormwater snapshot under this data root")
    assert features.stormwater_zip(r).name == features.SW_ZIP
    src = Path(sx.__file__).read_text()
    assert src.count("stormwater_zip(") == 1, "the digest is checked in exactly one place"
