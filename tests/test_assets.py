"""Flood-build ticket 01: ref/assets — every Unit and Carrier in one table.
Builder logic tested on mini fixtures (the frozen real-data counts are the builder's own
blocking assertions, gated by expect=ASSETS_EXPECT; tests pass expect=None). Same seam as
test_ref: build under a temp root, read back with DuckDB/pyarrow."""
import hashlib
import json
import zipfile
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raincheck import flood_alerts, ref
from raincheck.paths import data_root

FIXTURES = Path(__file__).parent / "fixtures"
CENTRAL_PARK_CELL = int("882a100895fffff", 16)

DRIFT = ("ref/assets has drifted from tests/fixtures/flood_alerts_stations.json. Re-cutting the "
         "fixture is NOT enough on its own: flood-build 02's precision/recall gate, its "
         "hand-adjudicated truth complex_of mapping and its observation table were all measured "
         "against these frozen rows, so those measurements need re-validating too — see "
         ".scratch/flood-build/issues/02-alert-extractor.md.")

STATIONS = [
    # complex 1: single station; complex 617: two stations (structure mixes); complex 611: misfile target
    {"gtfs_stop_id": "R01", "station_id": "1", "complex_id": "1", "line": "Astoria",
     "stop_name": "Astoria-Ditmars Blvd", "borough": "Q", "daytime_routes": "N W",
     "structure": "Elevated", "gtfs_latitude": "40.775036", "gtfs_longitude": "-73.912034"},
    {"gtfs_stop_id": "R31", "station_id": "27", "complex_id": "617", "line": "4th Av",
     "stop_name": "Atlantic Av-Barclays Ctr", "borough": "B", "daytime_routes": "N Q R",
     "structure": "Subway", "gtfs_latitude": "40.683666", "gtfs_longitude": "-73.978814"},
    {"gtfs_stop_id": "D24", "station_id": "26", "complex_id": "617", "line": "Brighton",
     "stop_name": "Atlantic Av-Barclays Ctr", "borough": "B", "daytime_routes": "B Q",
     "structure": "Open Cut", "gtfs_latitude": "40.683973", "gtfs_longitude": "-73.978167"},
    {"gtfs_stop_id": "127", "station_id": "9", "complex_id": "611", "line": "Broadway-7Av",
     "stop_name": "Times Sq-42 St", "borough": "M", "daytime_routes": "1 2 3",
     "structure": "Subway", "gtfs_latitude": "40.755983", "gtfs_longitude": "-73.986229"},
]

ENTRANCES = [
    # plain row
    {"gtfs_stop_id": "R01", "complex_id": "1", "stop_name": "Astoria-Ditmars Blvd",
     "entrance_type": "Stair", "entry_allowed": "YES", "exit_allowed": "YES",
     "entrance_latitude": "40.775370", "entrance_longitude": "-73.912000"},
    # misfiled complex_id: the stations join (via gtfs_stop_id) must win over the row's own field
    {"gtfs_stop_id": "127", "complex_id": "9999", "stop_name": "Times Sq-42 St",
     "entrance_type": "Stair", "entry_allowed": "YES", "exit_allowed": "YES",
     "entrance_latitude": "40.756100", "entrance_longitude": "-73.986500"},
    # semicolon multivalue, both stations in one complex -> ONE row, array of both ids
    {"gtfs_stop_id": "R31;D24", "complex_id": "617", "stop_name": "Atlantic Av-Barclays Ctr",
     "entrance_type": "Elevator", "entry_allowed": "YES", "exit_allowed": "YES",
     "entrance_latitude": "40.683800", "entrance_longitude": "-73.978500"},
    # shared doorway: same coordinates serving two complexes stays two rows (keys differ by complex)
    {"gtfs_stop_id": "R01", "complex_id": "1", "stop_name": "Astoria-Ditmars Blvd",
     "entrance_type": "Easement - Street", "entry_allowed": "YES", "exit_allowed": "YES",
     "entrance_latitude": "40.760000", "entrance_longitude": "-73.980000"},
    {"gtfs_stop_id": "127", "complex_id": "611", "stop_name": "Times Sq-42 St",
     "entrance_type": "Easement - Street", "entry_allowed": "YES", "exit_allowed": "YES",
     "entrance_latitude": "40.760000", "entrance_longitude": "-73.980000"},
    # exit-only row is kept, exact literals
    {"gtfs_stop_id": "R31", "complex_id": "617", "stop_name": "Atlantic Av-Barclays Ctr",
     "entrance_type": "Stair", "entry_allowed": "NO", "exit_allowed": "YES",
     "entrance_latitude": "40.684200", "entrance_longitude": "-73.979100"},
]


def subway_zip(path: Path) -> None:
    """A mini subway static: location_type=1 parents matching STATIONS plus child platforms
    that the 1:1 verification must ignore."""
    parents = "".join(f"{s['gtfs_stop_id']},{s['stop_name']},"
                      f"{s['gtfs_latitude']},{s['gtfs_longitude']},1,\n" for s in STATIONS)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("stops.txt",
                   "stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station\n"
                   + parents
                   + "R01N,Astoria-Ditmars Blvd,40.775036,-73.912034,0,R01\n"
                   + "R01S,Astoria-Ditmars Blvd,40.775036,-73.912034,0,R01\n")
        z.writestr("calendar.txt",
                   "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                   "WKD,1,1,1,1,1,0,0,20260601,20260830\n")


def bus_stops_part(root: Path, pick_id: str, rows: list[tuple]) -> None:
    """A silver/stops partition in schedule.py's shape (only the columns the builder reads)."""
    out = root / "silver" / "stops" / f"pick_id={pick_id}" / "part-00000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    t = pa.table({"stop_id": [r[0] for r in rows], "stop_name": [r[1] for r in rows],
                  "lon": [r[2] for r in rows], "lat": [r[3] for r in rows]})
    pq.write_table(t, out)


@pytest.fixture(scope="module")
def root(spark, tmp_path_factory):
    root = tmp_path_factory.mktemp("root")
    (root / "ref" / "src").mkdir(parents=True)
    (root / "ref" / "src" / "taxi_zones.zip").write_bytes((FIXTURES / "taxi_zones.zip").read_bytes())
    ref.build_cells(root, spark)
    ref.build_zones(root, spark)
    sub = root / "archive" / "subway"
    sub.mkdir(parents=True)
    (sub / ref.STATIONS_SNAPSHOT).write_text(json.dumps(STATIONS))
    (sub / ref.ENTRANCES_SNAPSHOT).write_text(json.dumps(ENTRANCES))
    # picks: a subway static and two bus feeds (only silver/stops matters for the bus side)
    (root / "archive" / "static" / "subway").mkdir(parents=True)
    subway_zip(root / "archive" / "static" / "subway" / "2026-08-07.zip")
    for feed in ("brooklyn", "queens"):
        (root / "archive" / "static" / feed).mkdir(parents=True)
        (root / "archive" / "static" / feed / "2026-06-23.zip").write_bytes(_feed_zip_bytes(feed))
    ref.build_picks(root)
    picks = {r["feed"]: r["pick_id"] for r in pq.read_table(root / "ref" / "picks").to_pylist()}
    # B1 in both feeds (coords ~11 m apart -> arithmetic mean; name from the
    # lexicographically-first FEED, brooklyn); B2/B3 single-feed
    bus_stops_part(root, picks["brooklyn"],
                   [("B1", "FLATBUSH AV/ATLANTIC AV", -73.978000, 40.684000),
                    ("B2", "SOME OTHER STOP", -73.950000, 40.650000)])
    bus_stops_part(root, picks["queens"],
                   [("B1", "ATLANTIC AV/FLATBUSH AV", -73.977900, 40.684100),
                    ("B3", "QUEENS STOP", -73.912000, 40.775500)])
    ref.build_assets(root, spark, bus_picks={"brooklyn": picks["brooklyn"], "queens": picks["queens"]},
                     subway_pick=picks["subway"], expect=None)
    return root


def _feed_zip_bytes(feed: str) -> bytes:
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("calendar.txt",
                   "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                   f"WKD,1,1,1,1,1,0,0,20260601,20260830\n")
        z.writestr("feed_info.txt",
                   f"feed_publisher_name,feed_publisher_url,feed_lang,feed_version\nMTA,https://mta.info,en,{feed}\n")
    return buf.getvalue()


@pytest.fixture(scope="module")
def assets(root):
    return pq.read_table(root / "ref" / "assets")


def by_id(assets: pa.Table, asset_id: str) -> dict:
    rows = [r for r in assets.to_pylist() if r["asset_id"] == asset_id]
    assert len(rows) == 1, asset_id
    return rows[0]


def test_grain_kinds_and_geoparquet(root, assets):
    ids = assets.column("asset_id").to_pylist()
    assert len(ids) == len(set(ids)) and ids == sorted(ids)
    kinds = assets.column("kind").to_pylist()
    counts = {k: kinds.count(k) for k in set(kinds)}
    assert counts == {"complex": 3, "station": 4, "entrance": 6, "bus_stop": 3, "cell": 4113}
    geo = json.loads(pq.read_metadata(root / "ref" / "assets" / "part-00000.parquet").metadata[b"geo"])
    assert geo["version"] == "1.1.0" and set(geo["columns"]) == {"geometry"}


def test_station_and_complex_rows(assets):
    sta = by_id(assets, "sta:R31")
    assert sta["kind"] == "station" and sta["name"] == "Atlantic Av-Barclays Ctr"
    assert sta["complex_id"] == "617" and sta["parent_asset_id"] == "stn:617"
    assert sta["gtfs_stop_id"] == ["R31"] and sta["structure"] == "Subway"
    assert sta["borough"] == "B" and sta["daytime_routes"] == "N Q R"
    assert sta["scored"] is False and sta["src_asof"] == date(2026, 8, 22)
    cx = by_id(assets, "stn:617")
    assert cx["kind"] == "complex" and cx["name"] == "Atlantic Av-Barclays Ctr"
    assert cx["lon"] == pytest.approx((-73.978814 + -73.978167) / 2)
    assert cx["lat"] == pytest.approx((40.683666 + 40.683973) / 2)
    assert cx["structure"] is None  # structure stays at station grain
    assert cx["borough"] == "B" and cx["scored"] is True and cx["parent_asset_id"] is None


def test_entrance_complex_corrected_from_stations_join(assets):
    ent = by_id(assets, "ent:611:40.756100:-73.986500")
    assert ent["kind"] == "entrance"
    assert ent["complex_id"] == "611"  # the row said 9999; the join corrects it
    assert ent["parent_asset_id"] == "stn:611"
    assert ent["name"] == "Times Sq-42 St"


def test_entrance_semicolon_split_one_row(assets):
    ent = by_id(assets, "ent:617:40.683800:-73.978500")
    assert ent["gtfs_stop_id"] == ["R31", "D24"]
    assert ent["entrance_type"] == "Elevator"


def test_shared_doorway_two_rows_one_per_complex(assets):
    a = by_id(assets, "ent:1:40.760000:-73.980000")
    b = by_id(assets, "ent:611:40.760000:-73.980000")
    assert (a["lon"], a["lat"]) == (b["lon"], b["lat"])
    assert a["entrance_type"] == "Easement - Street"  # exact spaced literal


def test_exit_only_kept(assets):
    ent = by_id(assets, "ent:617:40.684200:-73.979100")
    assert ent["entry_allowed"] == "NO" and ent["exit_allowed"] == "YES"
    assert ent["scored"] is False


def test_bus_cross_feed_mean_and_name(assets, root):
    b1 = by_id(assets, "bus:B1")
    assert b1["lon"] == pytest.approx((-73.978000 + -73.977900) / 2)
    assert b1["lat"] == pytest.approx((40.684000 + 40.684100) / 2)
    assert b1["name"] == "FLATBUSH AV/ATLANTIC AV"  # lexicographically-first feed wins
    assert b1["feeds"] == ["brooklyn", "queens"]
    picks = {r["feed"]: r["pick_id"] for r in pq.read_table(root / "ref" / "picks").to_pylist()}
    assert b1["pick_id"] == [picks["brooklyn"], picks["queens"]]  # aligned to feeds
    assert b1["scored"] is True and b1["src_asof"] == date(2026, 6, 23)
    assert by_id(assets, "bus:B3")["feeds"] == ["queens"]


def test_cell_rows_and_scored_universe(assets):
    cells = [r for r in assets.to_pylist() if r["kind"] == "cell"]
    assert len(cells) == 4113
    assert all(r["name"] is None for r in cells)
    cp = by_id(assets, f"cell:{CENTRAL_PARK_CELL:x}")
    assert cp["cell"] == CENTRAL_PARK_CELL
    assert cp["scored"] is True  # intersects the Central Park zone
    scored = sum(r["scored"] for r in cells)
    # zone-intersecting cells (~1,354 minus EWR) plus asset-bearing ones; mini assets add few
    assert 900 < scored < 1700
    # the Cell holding bus stop B1 is scored even if it were zoneless
    b1 = by_id(assets, "bus:B1")
    assert by_id(assets, f"cell:{b1['cell']:x}")["scored"] is True


def test_every_point_cell_in_ref_cells(assets, root):
    ref_cells = set(pq.read_table(root / "ref" / "cells", columns=["cell"]).column("cell").to_pylist())
    for r in assets.to_pylist():
        assert r["cell"] in ref_cells, r["asset_id"]


def test_names_not_null_except_cell(assets):
    for r in assets.to_pylist():
        if r["kind"] != "cell":
            assert r["name"], r["asset_id"]


def test_assets_version_and_key_diff(root, assets):
    v1 = ref.assets_version(root)
    assert len(v1) == 40  # sha1 over sorted (asset_id, kind, lat, lon)
    old = {r["asset_id"]: (r["lat"], r["lon"]) for r in assets.to_pylist()}
    moved = dict(old)
    moved["bus:B1"] = (old["bus:B1"][0] + 1e-3, old["bus:B1"][1])
    added = dict(old)
    added["bus:NEW"] = (40.7, -73.9)
    diff = ref.assets_key_diff(old, moved)
    assert diff == {"added": [], "removed": [], "moved": ["bus:B1"]}
    assert ref.assets_key_diff(old, added)["added"] == ["bus:NEW"]
    assert ref.assets_key_diff(added, old)["removed"] == ["bus:NEW"]


def _station_rows(stations) -> set:
    return {(s["asset_id"], s["name"], s["complex_id"], s["daytime_routes"]) for s in stations}


def test_flood_alerts_stations_fixture_matches_the_live_registry():
    """Key stability against a downstream consumer: flood-build 02 froze this registry's 496
    station rows into a fixture and measured its whole gate on them. Nothing else compares the
    two, so a rename or an added station leaves those tests green while load_aliases() — the
    production path — resolves aliases the measurements never saw. Real registry, so it skips
    where there is none (same seam as the JVM and vendored-file skips)."""
    root = data_root()
    if not (root / "ref" / "assets").exists():
        pytest.skip(f"no built ref/assets under {root}: run make ref, or point "
                    "RAINCHECK_ARCHIVE_ROOT at a data root that has one")
    frozen = _station_rows(json.loads((FIXTURES / "flood_alerts_stations.json").read_text()))
    try:
        live = _station_rows(s for c in flood_alerts.load_aliases(root).values() for s in c)
    except KeyError as exc:  # FORMER_NAMES guard: a rename it points at raises before we diff
        pytest.fail(f"{DRIFT}\n  load_aliases() rejected the live registry: {exc}")
    assert live == frozen, (f"{DRIFT}\n  only in ref/assets: {sorted(live - frozen)[:5]}"
                            f"\n  only in the fixture: {sorted(frozen - live)[:5]}")


def test_removed_key_with_downstream_rows_fails_build(root, spark):
    picks = {r["feed"]: r["pick_id"] for r in pq.read_table(root / "ref" / "picks").to_pylist()}
    feat = root / "silver" / "asset_features" / "part-00000.parquet"
    feat.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"asset_id": ["bus:B3"], "elev_ft": [12.0]}), feat)
    try:
        # dropping the queens feed removes bus:B3, which asset_features references -> FAIL
        with pytest.raises(RuntimeError, match="bus:B3"):
            ref.build_assets(root, spark, bus_picks={"brooklyn": picks["brooklyn"]},
                             subway_pick=picks["subway"], expect=None)
    finally:
        feat.unlink()
        (root / "silver" / "asset_features").rmdir()
        ref.build_assets(root, spark, bus_picks={"brooklyn": picks["brooklyn"], "queens": picks["queens"]},
                         subway_pick=picks["subway"], expect=None)


def test_rebuild_is_byte_identical(root, spark):
    part = root / "ref" / "assets" / "part-00000.parquet"
    before = hashlib.sha256(part.read_bytes()).hexdigest()
    picks = {r["feed"]: r["pick_id"] for r in pq.read_table(root / "ref" / "picks").to_pylist()}
    ref.build_assets(root, spark, bus_picks={"brooklyn": picks["brooklyn"], "queens": picks["queens"]},
                     subway_pick=picks["subway"], expect=None)
    assert hashlib.sha256(part.read_bytes()).hexdigest() == before


def test_crosswalk_and_null_pixel_gates(root, spark):
    import shutil

    picks = {r["feed"]: r["pick_id"] for r in pq.read_table(root / "ref" / "picks").to_pylist()}
    bp = {"brooklyn": picks["brooklyn"], "queens": picks["queens"]}
    assets = pq.read_table(root / "ref" / "assets")
    scored = [r["cell"] for r in assets.to_pylist() if r["kind"] == "cell" and r["scored"]]
    all_cells = pq.read_table(root / "ref" / "cells", columns=["cell"]).column("cell").to_pylist()
    xwalk = root / "ref" / "cell_pixel" / "part-00000.parquet"
    xwalk.parent.mkdir(parents=True, exist_ok=True)
    try:
        # a crosswalk that misses one scored cell on the mrms grid must abort the build
        covered = [c for c in all_cells if c != scored[0]]
        pq.write_table(pa.table({"grid_id": ["mrms"] * len(covered) + ["aorc"] * len(all_cells),
                                 "cell": covered + all_cells}), xwalk)
        with pytest.raises(RuntimeError, match="mrms"):
            ref.build_assets(root, spark, bus_picks=bp, subway_pick=picks["subway"], expect=None)
        pq.write_table(pa.table({"grid_id": ["mrms"] * len(all_cells) + ["aorc"] * len(all_cells),
                                 "cell": all_cells * 2}), xwalk)
        # a permanently-NULL AORC cell inside cells_scored must abort the build; scored[0]
        # is present-but-all-NULL and every other scored cell is absent entirely — the
        # gate treats both as permanently NULL (only scored[1] has a live reading)
        pch = root / "silver" / "precip_cell_hourly" / "src=aorc" / "month=2021-09"
        pch.mkdir(parents=True)
        pq.write_table(pa.table({"cell": [scored[0], scored[1], scored[1]],
                                 "mm_1h": pa.array([None, 1.0, 0.0], type=pa.float32())}),
                       pch / "part-00000.parquet")
        with pytest.raises(RuntimeError, match="permanently-NULL"):
            ref.build_assets(root, spark, bus_picks=bp, subway_pick=picks["subway"], expect=None)
    finally:
        shutil.rmtree(root / "ref" / "cell_pixel")
        shutil.rmtree(root / "silver" / "precip_cell_hourly", ignore_errors=True)
        ref.build_assets(root, spark, bus_picks=bp, subway_pick=picks["subway"], expect=None)


def test_subway_one_to_one_verification_fails_on_orphan(root, spark):
    # a location_type=1 stop the stations snapshot lacks must abort the build
    zpath = root / "archive" / "static" / "subway" / "2026-08-07.zip"
    orig = zpath.read_bytes()
    with zipfile.ZipFile(zpath) as zin:
        stops = zin.read("stops.txt").decode()
        cal = zin.read("calendar.txt").decode()
    with zipfile.ZipFile(zpath, "w") as zout:
        zout.writestr("stops.txt", stops + "X99,Ghost Station,40.7,-73.9,1,\n")
        zout.writestr("calendar.txt", cal)
    ref.build_picks(root)
    picks = {r["feed"]: r["pick_id"] for r in pq.read_table(root / "ref" / "picks").to_pylist()}
    try:
        with pytest.raises(RuntimeError, match="X99"):
            ref.build_assets(root, spark, bus_picks={"brooklyn": picks["brooklyn"], "queens": picks["queens"]},
                             subway_pick=picks["subway"], expect=None)
    finally:
        zpath.write_bytes(orig)
        ref.build_picks(root)
