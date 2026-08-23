"""Flood-build ticket 03: silver/asset_features + silver/cell_stormwater.

Two seams. The pure functions (ring geometry, the locationId join, the QC rule, the
four-level stormwater precedence, area shares) are tested on fixtures with known answers —
no network, matching the decode-census precedent. The written tables are tested against
the REAL data root and skip where there is none, the same seam test_assets uses for the
live registry: the frozen counts here (15,490 rows, the 41-entrance canary) were measured
on the real DEM service, so a temp-root rebuild could not assert them.
"""
import hashlib
import inspect
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely
from pyproj import Geod

from raincheck import features, ref
from raincheck.duck import connect, table
from raincheck.paths import data_root

CATEGORIES = {"deep", "nuisance", "analyzed-none", "not-analyzed"}


# ---- pure functions ------------------------------------------------------------


def test_ring_is_eight_points_at_fifteen_metres():
    lon, lat = -73.9866, 40.7306
    ring = features.ring_points(lon, lat)
    assert len(ring) == features.RING_N == 8
    geod = Geod(ellps="WGS84")
    for x, y in ring:
        assert geod.inv(lon, lat, x, y)[2] == pytest.approx(features.RING_M, abs=1e-6)
    assert len(set(ring)) == 8


def test_parse_samples_omits_out_of_footprint_points():
    """The join is locationId + batch offset. A point outside the raster is SILENTLY
    dropped (its locationId skips) — the diagnostic that must survive as NULL, not shift
    every later value up by one."""
    payload = {"samples": [{"locationId": 0, "value": "9.619487762"},
                           {"locationId": 2, "value": "-1.5"}]}
    assert features.parse_samples(payload, 3) == [9.619487762, None, -1.5]
    assert features.parse_samples({"samples": []}, 2) == [None, None]


def test_parse_samples_rejects_errors_and_stray_ids():
    with pytest.raises(RuntimeError, match="getSamples error"):
        features.parse_samples({"error": {"code": 400, "message": "Unable to complete"}}, 5)
    with pytest.raises(RuntimeError, match="outside a batch"):
        features.parse_samples({"samples": [{"locationId": 7, "value": "1.0"}]}, 3)


def test_grade_ok_is_the_two_frozen_constants():
    assert features.EPOCH_DELTA_M == 2.0 and features.ELEV_FLOOR_M == -1.0
    assert features.grade_ok(5.0, 3.0) is True      # delta exactly at the threshold
    assert features.grade_ok(5.0, 2.999) is False   # over it
    assert features.grade_ok(-1.0, -1.0) is True    # elevation exactly at the floor
    assert features.grade_ok(-1.001, -1.0) is False
    assert features.grade_ok(None, 4.0) is False    # NoData flags, never crashes
    assert features.grade_ok(4.0, None) is False


PTS = [(-73.9, 40.7), (-73.8, 40.7)]


def snapshot(tmp_path, batches, points=PTS, sampled_at=None):
    path = (tmp_path / "snapshots" / "elevation" /
            f"{features.DEM_2017}_points_{features.SRC_ASOF}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "sampled_at": features.sampled_at(points) if sampled_at is None else sampled_at,
        "batches": batches}))
    return path


def test_sample_reads_the_snapshot_and_never_calls_the_service(tmp_path, monkeypatch):
    monkeypatch.setattr(features, "post_samples",
                        lambda *a: pytest.fail("a present snapshot must not call the API"))
    snapshot(tmp_path, [{"offset": 0,
                         "response": {"samples": [{"locationId": 1, "value": "3.25"}]}}])
    assert features.sample(tmp_path, features.DEM_2017, "points", PTS) == [None, 3.25]


def test_sample_refuses_a_snapshot_taken_at_other_coordinates(tmp_path):
    """The defect this guards: ticket 01's key-diff calls a re-pinned bus Pick's shifted
    cross-feed mean a MOVED asset, not an added one — same asset_id, same 15,490 count, same
    sort order. Every frozen gate would pass while the elevations belonged to the old
    coordinates, republished under a features_version chained to the NEW assets_version."""
    snapshot(tmp_path, [{"offset": 0, "response": {"samples": []}}])
    moved = [(PTS[0][0] + 0.0001, PTS[0][1]), PTS[1]]
    with pytest.raises(RuntimeError, match="different coordinates"):
        features.sample(tmp_path, features.DEM_2017, "points", moved)


def test_sample_refuses_a_snapshot_taken_under_other_request_constants(tmp_path, monkeypatch):
    """Same guard, the other half: bilinear moves values up to 0.342 m, so a flipped
    interpolation must re-sample rather than reuse nearest-neighbour bytes."""
    snapshot(tmp_path, [{"offset": 0, "response": {"samples": []}}])
    monkeypatch.setattr(features, "INTERPOLATION", "RSP_BilinearInterpolation")
    with pytest.raises(RuntimeError, match="request constants"):
        features.sample(tmp_path, features.DEM_2017, "points", PTS)


def test_sample_rejects_a_snapshot_whose_batches_do_not_line_up(tmp_path):
    snapshot(tmp_path, [{"offset": 9, "response": {"samples": []}}])
    with pytest.raises(RuntimeError, match="batch offset"):
        features.sample(tmp_path, features.DEM_2017, "points", PTS)


def square(x0, y0, side):
    return shapely.box(x0, y0, x0 + side, y0 + side)


def test_categorize_never_imputes_and_ranks_flooded_over_unanalyzed():
    parts = {"deep": [square(0, 0, 10)], "nuisance": [square(10, 0, 10)],
             "not-analyzed": [square(0, 0, 30)]}  # the mask covers the first three points
    study = [square(0, 0, 50)]
    pts = [shapely.Point(5, 5),      # flooded deep, and masked -> flooded wins
           shapely.Point(15, 5),     # flooded nuisance, and masked -> flooded wins
           shapely.Point(25, 25),    # masked only
           shapely.Point(40, 40),    # inside the study area, nothing claims it
           shapely.Point(100, 100)]  # outside the study area entirely
    assert features.categorize(pts, parts, study) == [
        "deep", "nuisance", "not-analyzed", "analyzed-none", "not-analyzed"]


def test_categorize_never_calls_an_out_of_study_point_analyzed():
    """The imputation this encoding exists to forbid: DEP's mask is a PLUTO layer that stops
    at the city line, so a Nassau bus stop is outside every source. Defaulting it to
    "analyzed, no flooding" would hand 08 a fact DEP never asserted."""
    parts = {"deep": [], "nuisance": [], "not-analyzed": [square(0, 0, 10)]}
    assert features.categorize([shapely.Point(500, 500)], parts, [square(0, 0, 10)]) == \
        ["not-analyzed"]


def test_area_shares_are_exact_fractions_of_the_cell():
    parts = {"deep": [square(0, 0, 5)], "nuisance": [square(5, 0, 5), square(0, 5, 5)],
             "not-analyzed": []}
    shares = features.area_shares([square(0, 0, 10)], parts)
    assert shares["deep"] == [pytest.approx(0.25)]
    assert shares["nuisance"] == [pytest.approx(0.5)]   # two disjoint parts summed
    assert shares["not-analyzed"] == [pytest.approx(0.0)]
    # a Cell wholly inside one class is 1.0 exactly, not 1 + 2 ULP
    assert features.area_shares([square(0, 0, 4)], {"deep": [square(0, 0, 2), square(2, 0, 2),
                                                             square(0, 2, 4)]})["deep"] == [1.0]


def test_area_shares_refuse_to_publish_overlapping_parts():
    """Summing per-part intersections is only exact while the parts stay disjoint. If they
    ever overlap, the number stops being a fraction — fail, never clamp it into looking
    fine."""
    with pytest.raises(RuntimeError, match="over 1"):
        features.area_shares([square(0, 0, 10)], {"deep": [square(0, 0, 10), square(0, 0, 10)]})


def test_snapshots_stay_out_of_the_cold_pushed_archive(tmp_path, monkeypatch):
    """Licence boundary, not tidiness: DEC/DEP are fetch-and-use with rehosting barred, and
    `make coldpush` syncs <root>/archive to R2. A snapshot written under archive/ would be
    republished to a public-ish bucket by a target nobody re-reads."""
    monkeypatch.setattr(features, "post_samples", lambda *a: {"samples": []})
    features.sample(tmp_path, features.DEM_2017, "points", [(-73.9, 40.7)])
    written = list(tmp_path.rglob("*.*"))
    assert written, "the snapshot should have been written"
    for p in written:
        assert "archive" not in p.relative_to(tmp_path).parts, p
    # and the two DEP artifacts, whose licence is the one that actually bars rehosting,
    # are addressed off the same snapshots/ root rather than a second hard-coded path
    for path in (features.stormwater_zip, features.mask_polygons):
        src = inspect.getsource(path)
        assert '"snapshots"' in src and '"archive"' not in src, path.__name__


def test_write_is_deterministic(tmp_path):
    """The byte-identical-rebuild mechanism: identical rows in, identical bytes out."""
    t = pa.table({"asset_id": ["a", "b"], "elev_ft": [1.5, None]})
    digests = []
    for _ in range(2):
        features.write(tmp_path, "asset_features", t)
        digests.append(hashlib.sha256(
            (tmp_path / "silver" / "asset_features" / "part-00000.parquet").read_bytes()).hexdigest())
    assert digests[0] == digests[1]


# ---- the written tables, against the real root ---------------------------------


@pytest.fixture(scope="module")
def root() -> Path:
    r = data_root()
    if not (r / "silver" / "asset_features").exists():
        pytest.skip(f"no built silver/asset_features under {r}: run make features, or point "
                    "RAINCHECK_ARCHIVE_ROOT at a data root that has one")
    return r


@pytest.fixture(scope="module")
def feats(root) -> pa.Table:
    return pq.read_table(root / "silver" / "asset_features")


def test_grain_is_point_assets_only(root, feats):
    ids = feats.column("asset_id").to_pylist()
    assert len(ids) == features.EXPECT["rows"] == 15490
    assert len(set(ids)) == len(ids) and ids == sorted(ids)
    assets = pq.read_table(root / "ref" / "assets", columns=["asset_id", "kind"]).to_pylist()
    kind = {a["asset_id"]: a["kind"] for a in assets}
    assert set(ids) <= set(kind)  # FK to ref/assets
    kinds = {kind[i] for i in ids}
    assert kinds == {"entrance", "bus_stop"}  # no complex, station or cell rows
    assert sum(kind[i] == "entrance" for i in ids) == features.EXPECT["entrance"]
    assert sum(kind[i] == "bus_stop" for i in ids) == features.EXPECT["bus_stop"]


def test_entrance_flag_count_is_the_service_drift_canary(root, feats):
    """41/2,120 was measured on the 2017 and 2014 services. If it moves, the services
    republished under us and every elevation in this table needs re-reading — the build
    fails on it, and so does this."""
    kind = {a["asset_id"]: a["kind"] for a in
            pq.read_table(root / "ref" / "assets", columns=["asset_id", "kind"]).to_pylist()}
    flagged = [r["asset_id"] for r in feats.to_pylist()
               if not r["grade_ok"] and kind[r["asset_id"]] == "entrance"]
    assert len(flagged) == features.EXPECT["entrance_flagged"] == 41


def test_elevation_columns_and_the_us_survey_foot(feats):
    assert features.US_SURVEY_FT == 3.280833333  # not the international foot
    for r in feats.to_pylist():
        if r["elev_2017_m"] is None:
            assert r["elev_ft"] is None and r["grade_ok"] is False
        else:
            assert r["elev_ft"] == pytest.approx(r["elev_2017_m"] * features.US_SURVEY_FT)


def test_grade_ok_reproduces_from_the_raw_columns_in_the_same_row(feats):
    """QC reasons stay recoverable: nothing is repaired on the way into the table."""
    for r in feats.to_pylist():
        assert r["grade_ok"] == features.grade_ok(r["elev_2017_m"], r["elev_2014_m"])


def test_flagged_rows_keep_their_ring15_med_fallback(root, feats):
    """08's sanctioned fallback for a flagged row is ring15_med — never a Cell median
    (measured strictly worse). The fallback is applied read-side, so what this table owes
    is the column being there — and it is, for every flagged ENTRANCE. The 60 rows without
    one are all bus stops outside the DEM footprint (their ring is out there too), a frozen
    count rather than a warning, because a drift means either the registry or the service
    moved."""
    kind = {a["asset_id"]: a["kind"] for a in
            pq.read_table(root / "ref" / "assets", columns=["asset_id", "kind"]).to_pylist()}
    missing = [r["asset_id"] for r in feats.to_pylist()
               if not r["grade_ok"] and r["ring15_med_m"] is None]
    assert len(missing) == features.EXPECT["no_fallback"] == 60
    assert {kind[i] for i in missing} == {"bus_stop"}


def test_every_complex_can_still_be_aggregated_from_its_children(root, feats):
    """08 aggregates a complex from its child entrances. Seven complexes (the Brooklyn els
    and friends) have entrances but ZERO grade_ok ones, so a GROUP BY that simply filters on
    grade_ok returns nothing for them — the fallback has to be applied BEFORE the aggregate,
    not after. What this table owes is that the fallback exists for every child."""
    assets = pq.read_table(root / "ref" / "assets",
                           columns=["asset_id", "kind", "parent_asset_id"]).to_pylist()
    f = {r["asset_id"]: r for r in feats.to_pylist()}
    kids: dict[str, list[str]] = {}
    for a in assets:
        if a["kind"] == "entrance":
            kids.setdefault(a["parent_asset_id"], []).append(a["asset_id"])
    complexes = [a["asset_id"] for a in assets if a["kind"] == "complex"]
    assert all(kids.get(c) for c in complexes)  # every complex has at least one entrance
    for c in complexes:
        assert any(f[e]["grade_ok"] or f[e]["ring15_med_m"] is not None for e in kids[c]), c


def test_ring_columns_are_ordered_and_present(feats):
    for r in feats.to_pylist():
        if r["ring15_min_m"] is not None:
            assert r["ring15_min_m"] <= r["ring15_med_m"]


def test_stormwater_category_is_four_levels_and_never_null(feats):
    cats = feats.column("stormwater_cat").to_pylist()
    assert None not in cats
    assert set(cats) <= CATEGORIES
    # not-analyzed must be populated, not imputed away: DEP's exclusion mask is mostly rail
    # lines and their buffers, which is exactly where transit assets sit
    assert cats.count("not-analyzed") > 0
    assert cats.count("deep") > 0 and cats.count("nuisance") > 0


def test_cell_stormwater_covers_every_cell_with_shares_in_range(root):
    cells = pq.read_table(root / "ref" / "cells", columns=["cell"]).column("cell").to_pylist()
    t = pq.read_table(root / "silver" / "cell_stormwater")
    rows = t.to_pylist()
    assert [r["cell"] for r in rows] == cells
    for r in rows:
        shares = [r["share_deep"], r["share_nuisance"], r["share_not_analyzed"]]
        assert all(0.0 <= s <= 1.0 for s in shares), r["cell"]
        assert sum(shares) <= 1.0 + 1e-9, r["cell"]


def test_duckdb_reads_the_grain_back(root):
    con = connect()
    rel = table(con, root / "silver" / "asset_features")
    assert rel.aggregate("count(*) AS n, count(DISTINCT asset_id) AS u").fetchone() == (15490, 15490)
    assert rel.filter("stormwater_cat IS NULL").aggregate("count(*) AS n").fetchone() == (0,)


def test_features_version_chains_on_assets_version_and_the_constants(root, monkeypatch):
    base = features.features_version(root)
    assert len(base) == 40
    assert features.features_version(root) == base  # stable across calls
    monkeypatch.setattr(ref, "assets_version", lambda _root: "0" * 40)
    assert features.features_version(root) != base  # structural chain on the registry
    monkeypatch.undo()
    monkeypatch.setattr(features, "EPOCH_DELTA_M", 3.0)
    assert features.features_version(root) != base  # and on the frozen constants


def test_frozen_elevation_probe_matches_the_table(feats):
    """Six values frozen from the first full build: a silent interpolation, datum or
    republish change moves them without moving a single QC flag."""
    assert features.ELEV_PROBE, "the probe must not be empty"
    by_id = {r["asset_id"]: r for r in feats.to_pylist()}
    for asset_id, expected in features.ELEV_PROBE.items():
        assert by_id[asset_id]["elev_2017_m"] == pytest.approx(expected, abs=1e-9)


def test_every_frozen_count_re_derives_from_the_written_table(root, feats):
    """EXPECT is what the build asserts against; nothing re-derived it from the table the
    build actually wrote. bus_stop_flagged=89, elev_null=61 and no_fallback=60 were measured
    at first full build and are the numbers a service drift or a registry change would move."""
    kind = {a["asset_id"]: a["kind"] for a in
            pq.read_table(root / "ref" / "assets", columns=["asset_id", "kind"]).to_pylist()}
    rows = feats.to_pylist()
    got = {
        "rows": len(rows),
        "entrance": sum(kind[r["asset_id"]] == "entrance" for r in rows),
        "bus_stop": sum(kind[r["asset_id"]] == "bus_stop" for r in rows),
        "entrance_flagged": sum(not r["grade_ok"] and kind[r["asset_id"]] == "entrance"
                                for r in rows),
        "bus_stop_flagged": sum(not r["grade_ok"] and kind[r["asset_id"]] == "bus_stop"
                                for r in rows),
        "elev_null": sum(r["elev_2017_m"] is None for r in rows),
        "no_fallback": sum(not r["grade_ok"] and r["ring15_med_m"] is None for r in rows),
    }
    assert got == features.EXPECT


def test_ring15_n_records_how_many_of_the_eight_answered(feats):
    """A half-ring median reads exactly like the 15 m octagon 08 asked for unless the
    denominator rides along — and the clipped assets are precisely the ones whose fallback
    grade it becomes."""
    rows = feats.to_pylist()
    for r in rows:
        assert 0 <= r["ring15_n"] <= features.RING_N
        assert (r["ring15_med_m"] is None) == (r["ring15_n"] == 0)
        assert (r["ring15_min_m"] is None) == (r["ring15_n"] == 0)
    partial = [r for r in rows if 0 < r["ring15_n"] < features.RING_N]
    assert len(partial) == 6  # measured; a move means the raster footprint changed
    # the one in-NYC clipped stop: no elevation of its own, fallback from 5 of 8 ring points
    clipped = next(r for r in rows if r["asset_id"] == "bus:308410")
    assert clipped["elev_2017_m"] is None and clipped["ring15_n"] == 5


def test_assets_outside_the_study_area_are_never_called_analyzed(root, feats):
    """The out-of-city imputation, on real data: 72 MTA Bus Company stops in Nassau sit
    outside DEP's study area and outside its PLUTO exclusion mask, so the default would have
    published them as "DEP modelled here, no flooding"."""
    study = features.nyc_study_area(root)
    tree = shapely.STRtree(study)
    cats = {r["asset_id"]: r["stormwater_cat"] for r in feats.to_pylist()}
    outside = []
    for a in features.point_assets(root):
        pt = shapely.Point(*features.TO_SW.transform(a["lon"], a["lat"]))
        if not any(study[k].covers(pt) for k in tree.query(pt)):
            outside.append(a["asset_id"])
    assert len(outside) == 72
    assert {cats[i] for i in outside} == {"not-analyzed"}


def test_stormwater_join_agrees_with_a_second_engine(root, feats):
    """The whole 4326 -> EPSG:2263 reprojection and containment path, checked against
    DuckDB's own ST_Transform + ST_Contains reading the same geodatabase. DuckDB resolves a
    deep/nuisance tie the other way, so agreement also proves the two classes never overlap
    on the sample. A stratified 400 rather than all 15,490: unindexed point-in-polygon
    against two 500k-vertex MultiPolygons costs ~114 s at full universe (measured), and the
    full-universe run — 800 flooded, zero disagreements — is recorded on the ticket."""
    published = {r["asset_id"]: r["stormwater_cat"] for r in feats.to_pylist()}
    sample = []
    for cat in sorted(CATEGORIES):  # deterministic: first 100 of each level by asset_id
        sample += sorted(a for a, c in published.items() if c == cat)[:100]
    con = connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    gdb = f"/vsizip/{root / 'snapshots' / 'stormwater' / features.SW_ZIP}/{features.SW_SCENARIO}"
    con.execute("CREATE TABLE sw AS SELECT Flooding_Category AS cat, ST_Force2D(Shape) AS g "
                "FROM ST_Read(?)", [gdb])
    con.execute("CREATE TABLE a AS SELECT asset_id, ST_Transform(ST_Point(lon, lat), "
                "'EPSG:4326', 'EPSG:2263', true) AS g FROM read_parquet(?) "
                "WHERE asset_id IN (SELECT unnest(?))",
                [str(root / "ref" / "assets" / "*.parquet"), sample])
    duck = {aid: features.SW_CATEGORY[cat] for aid, cat in con.execute(
        "SELECT a.asset_id, min(sw.cat) FROM a JOIN sw ON ST_Contains(sw.g, a.g) "
        "GROUP BY 1").fetchall()}
    for asset_id in sample:
        # the two flood levels must match exactly; the other two are "no flood polygon here"
        expected = published[asset_id] if published[asset_id] in features.SW_CATEGORY.values() else None
        assert duck.get(asset_id) == expected, asset_id
    assert sum(1 for a in sample if a in duck) == 200  # 100 deep + 100 nuisance


def test_cell_shares_call_unmodelled_ground_unmodelled(root):
    """Same rule as the point grain, at Cell grain: a Cell over Nassau or open water was
    never modelled, and publishing it with three zero shares would imply DEP looked."""
    rows = pq.read_table(root / "silver" / "cell_stormwater").to_pylist()
    study = shapely.union_all(features.nyc_study_area(root))
    cells = ref.read_ref(root, "cells", ["cell", "geometry"])
    by_cell = {r["cell"]: r for r in rows}
    checked = 0
    for cell, wkb in zip(cells["cell"], cells["geometry"]):
        geom = features.reproject(shapely.from_wkb(wkb))
        if geom.intersection(study).area == 0.0:  # touches no NYC land at all
            assert by_cell[cell]["share_not_analyzed"] == 1.0, cell
            checked += 1
    assert checked > 2000  # ~2,759 of the 4,113 bbox Cells hold no NYC land


def test_features_version_never_fetches_the_geodatabase(tmp_path):
    """A version stamp 08 will call to chain score_version must not download 33.8 MB from
    DEP as a side effect — it names a snapshot, it does not go and make one."""
    (tmp_path / "silver" / "asset_features").mkdir(parents=True)
    pq.write_table(pa.table({"asset_id": ["a"], "elev_2017_m": [1.0], "elev_2014_m": [1.0],
                             "ring15_min_m": [1.0], "ring15_med_m": [1.0],
                             "stormwater_cat": ["deep"]}),
                   tmp_path / "silver" / "asset_features" / "part-00000.parquet")
    with pytest.raises(RuntimeError, match="is missing under"):
        features.features_version(tmp_path)
