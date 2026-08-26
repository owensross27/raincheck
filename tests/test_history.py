"""Notify ticket 05: the static history surface — the manifest and the per-asset files.

The fixture root is notify 02's, EXTENDED BY NOBODY: `tests/fixtures/notify_query_*.parquet`
already hold every case this renderer has to get right, which is why this file assembles the
same root rather than cutting a second one.

  bus:400081                     a labelled bus stop, in the manifest
  cell:882a103827fffff           a labelled Cell — NO NAME in `ref/assets`, so the manifest
                                 property must be ABSENT rather than the literal "null"
  ent:409:40.722103:-73.996812   an entrance: a HISTORY and NO SCORE, `exposure_of` refuses
    ent:409:40.722226:-73.996790   it by name and hands back the complex to `ask`
  stn:611                        a complex carrying labels of its OWN
  stn:409                        a complex carrying NO label of its own whose ENTRANCES do —
                                 the rollup case, and the reason the manifest is 8,146 assets
                                 on the real root and not the 7,955 the ticket inherited
  bus:400021 · sta:638 · sta:725 · cell:882a100011fffff
                                 absent from the manifest, three different reasons (no
                                 label · Carrier · Carrier · unlabelled Cell), and every one
                                 has to render as "no events on record" with no request
"""
import ast
import json
import shutil
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from raincheck import contract, duck, export, history, publish, query as q
from raincheck.paths import REPO, data_root

FIXTURES = Path(__file__).parent / "fixtures"
LAYOUT = {"assets": ("ref", "assets"), "events": ("silver", "flood_events"),
          "obs": ("silver", "flood_obs"), "labels": ("gold", "flood_labels"),
          "exposure": ("gold", "flood_exposure")}

LISTED = ("bus:400081", "cell:882a103827fffff", "ent:409:40.722103:-73.996812",
          "ent:409:40.722226:-73.996790", "stn:409", "stn:611")
ABSENT = ("bus:400021", "sta:638", "sta:725", "cell:882a100011fffff")
ROLLUP_ONLY = "stn:409"            # no label of its own; two of its entrances have one
ENTRANCE = "ent:409:40.722103:-73.996812"
UNNAMED = "cell:882a103827fffff"   # a Cell: ref/assets names stops, stations and complexes
SOURCE = Path(history.__file__).read_text()


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    r = tmp_path_factory.mktemp("history")
    for name, parts in LAYOUT.items():
        r.joinpath(*parts).mkdir(parents=True)
        shutil.copy(FIXTURES / f"notify_query_{name}.parquet",
                    r.joinpath(*parts) / "part-00000.parquet")
    return r


@pytest.fixture(scope="module")
def built(root, tmp_path_factory):
    out = tmp_path_factory.mktemp("web") / history.DIR
    con = duck.connect()
    rep = history.build(con, root, out)
    con.close()
    return out, rep


@pytest.fixture(scope="module")
def manifest(built):
    out, _ = built
    return json.loads((out / history.MANIFEST).read_text())


def file_for(out: Path, asset_id: str) -> dict:
    return json.loads((out / f"{asset_id}.json").read_text())


def leaves(obj):
    if isinstance(obj, dict):
        return [x for k, v in obj.items() for x in leaves(k) + leaves(v)]
    if isinstance(obj, list):
        return [x for v in obj for x in leaves(v)]
    return [obj]


def sql_literals(src: str) -> list[str]:
    """Every string constant in the module that reads like SQL. An AST walk and not a grep:
    this module's DOCSTRING names the joins it refuses to hold, so a source-text search for
    the word finds its own prose (the trap flood 17 hit one layer up)."""
    return [n.value for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "SELECT" in n.value.upper()]


# ---- the fixture is load-bearing ---------------------------------------------------

def test_the_fixture_holds_a_rollup_only_complex_and_an_unnamed_cell(root):
    """Two of this renderer's rules are invisible on a fixture that lacks these rows: the
    complex whose history comes only from its children, and the asset with no name."""
    assets = pq.read_table(root / "ref" / "assets").to_pylist()
    labelled = {r["asset_id"] for r in pq.read_table(root / "gold" / "flood_labels").to_pylist()}
    by_id = {r["asset_id"]: r for r in assets}
    assert ROLLUP_ONLY not in labelled
    assert {a["asset_id"] for a in assets
            if a.get("parent_asset_id") == ROLLUP_ONLY} & labelled
    assert by_id[UNNAMED]["name"] is None and by_id[UNNAMED]["kind"] == "cell"
    scored = {r["asset_id"] for r in pq.read_table(root / "gold" / "flood_exposure").to_pylist()}
    assert ENTRANCE in labelled and ENTRANCE not in scored


def test_the_batched_sweep_is_complete_because_every_asset_sits_in_a_registered_cell(root):
    """The manifest walks `assets_in_area` over the Cell rows of `ref/assets`, so an asset
    whose `cell` had no `cell:` row of its own would be INVISIBLE — a manifest short by
    assets nobody counted. Measured on the real root (4,113 = 4,113); asserted here so the
    premise cannot rot silently in the fixture."""
    assets = pq.read_table(root / "ref" / "assets").to_pylist()
    cells = {a["cell"] for a in assets if a["kind"] == "cell"}
    assert cells and not [a["asset_id"] for a in assets if a["cell"] not in cells]


# ---- the manifest ------------------------------------------------------------------

def test_the_manifest_lists_every_asset_with_an_attached_event_and_nobody_else(manifest):
    assert manifest["type"] == "FeatureCollection"
    assert [f["properties"]["asset_id"] for f in manifest["features"]] == sorted(LISTED)


def test_a_complex_reaches_the_manifest_on_its_entrances_history_alone(manifest, root):
    """The rollup, and it is the finding that moved the count: `events_for_asset` answers a
    complex for itself AND its children, so a complex carrying no label of its own still has
    a history. Counting label ROWS instead gives 94 complexes on the real root where the
    query answers for 285."""
    feature = next(f for f in manifest["features"]
                   if f["properties"]["asset_id"] == ROLLUP_ONLY)
    assert feature["properties"]["n_events"] == q.query(
        "events_for_asset", {"asset_id": ROLLUP_ONLY}, root)["n_events"] > 0


def test_every_manifest_count_is_the_count_events_for_asset_answers(manifest, root):
    """The manifest is a promise about what the per-asset file holds. If the two disagreed,
    a marker would size itself on one number and open on another."""
    for f in manifest["features"]:
        aid = f["properties"]["asset_id"]
        assert f["properties"]["n_events"] == q.query(
            "events_for_asset", {"asset_id": aid}, root)["n_events"]


def test_an_asset_absent_from_the_manifest_really_has_no_events(root, manifest):
    """The whole point of a manifest: absence is an ANSWER, renderable with no request."""
    listed = {f["properties"]["asset_id"] for f in manifest["features"]}
    for aid in ABSENT:
        assert aid not in listed
        try:
            answer = q.query("events_for_asset", {"asset_id": aid}, root)
        except q.QueryError as exc:                   # a Carrier: refused, never listed
            assert exc.reason == "not_a_scored_unit"
            continue
        assert answer["n_events"] == 0 and answer["reason"] == q.NO_EVENTS


def test_the_manifest_key_set_is_the_six_that_were_decided(manifest):
    """asset_id · kind · n_events · lon · lat · name. The coordinates ARE the geometry —
    without them the page cannot paint a layer and the history layer does not exist."""
    for f in manifest["features"]:
        assert set(f) == {"type", "geometry", "properties"}
        assert f["geometry"]["type"] == "Point" and len(f["geometry"]["coordinates"]) == 2
        assert set(f["properties"]) <= {"asset_id", "kind", "n_events", "name"}
        assert {"asset_id", "kind", "n_events"} <= set(f["properties"])


def test_an_unnamed_cell_omits_the_key_rather_than_publishing_null(manifest):
    """`ref/assets` names only stops, stations and complexes, and the most-flooded assets
    are exactly the Cells — a null here renders the literal word "null" at the TOP of any
    ranked list. Absent, never null."""
    props = {f["properties"]["asset_id"]: f["properties"] for f in manifest["features"]}
    assert "name" not in props[UNNAMED]
    assert props["bus:400081"]["name"] == "CLEVELAND  PL/SPRING ST"


def test_coordinates_are_the_registry_coordinates_rounded_to_five_places(manifest, root):
    """Explicit rounding is half of byte-identity, and the coordinates are the only numbers
    this module MAKES — F10's scores pass through unrounded because they are published
    values and rounding one here would publish something the table does not hold.

    FIVE is a literal here on purpose. Deriving the expected value from `history.COORD_DP`
    would move the fixture with the constant and pin nothing (the trap flood 17 hit three
    times in one round); the independent side is the number `web/export.sql` already
    publishes Cell geometry at."""
    reg = {r["asset_id"]: r for r in pq.read_table(root / "ref" / "assets").to_pylist()}
    for f in manifest["features"]:
        row = reg[f["properties"]["asset_id"]]
        assert f["geometry"]["coordinates"] == [round(row["lon"], 5), round(row["lat"], 5)]
    every = [c for f in manifest["features"] for c in f["geometry"]["coordinates"]]
    assert max(len(str(c).rsplit(".")[-1]) for c in every) == 5   # rounded, and really to 5


def test_the_geometry_is_lon_lat_and_lands_in_new_york(manifest):
    """GeoJSON is (lon, lat) and this repo has already been bitten by a library that reads
    the pair the other way round — a swap returns a PLAUSIBLE point, never an error. Gate
    it on a known place rather than on the expression that built it: every one of these
    assets is in New York City, so longitude is about -74 and latitude about +40.7."""
    for f in manifest["features"]:
        lon, lat = f["geometry"]["coordinates"]
        assert -74.3 < lon < -73.6 and 40.4 < lat < 41.0, f["properties"]["asset_id"]


# ---- the per-asset files -----------------------------------------------------------

def test_one_file_per_manifest_entry_and_no_file_for_anybody_else(built, manifest):
    out, rep = built
    listed = [f["properties"]["asset_id"] for f in manifest["features"]]
    on_disk = sorted(p.name for p in out.iterdir() if p.name != history.MANIFEST)
    assert on_disk == sorted(f"{aid}.json" for aid in listed)
    assert rep["assets"] == len(listed) and rep["files"] == len(listed) + 1


def test_a_file_is_the_merge_of_the_two_public_answers(built, root):
    """`events_for_asset` and `exposure_of` return an IDENTICAL `asset` block and identical
    stamps for one id, so one file holds both without reconciling anything. Asserted here
    rather than trusted: if they ever diverged the merge would silently keep one of them."""
    out, _ = built
    doc = file_for(out, "bus:400081")
    hist = q.query("events_for_asset", {"asset_id": "bus:400081"}, root)
    score = q.query("exposure_of", {"asset_id": "bus:400081"}, root)
    assert hist["asset"] == score["asset"] and hist["versions"] == score["versions"]
    assert doc["asset"] == hist["asset"] and doc["events"] == hist["events"]
    assert doc["exposure"] == score["exposure"] and doc["versions"] == hist["versions"]
    assert doc["mode"] == "public" and doc["queries"] == list(history.QUERIES)


def test_an_entrance_keeps_its_history_and_carries_no_exposure_key_at_all(built):
    """An entrance's score exists only inside its complex's max — 928 of the real root's
    manifest assets. Absent, never null: a fabricated 0.0 would read as "safe"."""
    out, _ = built
    doc = file_for(out, ENTRANCE)
    assert doc["n_events"] > 0 and doc["events"]
    assert "exposure" not in doc
    assert doc["exposure_unavailable"] == {"reason": "not_a_scored_unit",
                                           "ask": ROLLUP_ONLY}


def test_the_ask_hint_points_at_an_asset_that_really_answers(built, root):
    """`ask` is only worth carrying if following it works."""
    out, _ = built
    ask = file_for(out, ENTRANCE)["exposure_unavailable"]["ask"]
    assert q.query("exposure_of", {"asset_id": ask}, root)["exposure"]["score_index"] > 0


def test_no_written_file_holds_a_null_anywhere_parsed_back_from_disk(built):
    out, _ = built
    for path in out.iterdir():
        assert None not in leaves(json.loads(path.read_text())), path.name


def test_every_file_carries_the_stamps_of_the_universe_that_answered(built, root):
    out, _ = built
    con = duck.connect()
    stamps = q.versions(con, root)
    con.close()
    for path in out.iterdir():
        if path.name == history.MANIFEST:
            continue
        assert json.loads(path.read_text())["versions"] == stamps


def test_the_files_are_public_and_carry_no_restricted_value(built):
    """`public` ships COUNTS, never rows. A per-asset file that leaked an observation row
    would put a FloodNet depth and the MTA alert row onto the public host."""
    out, _ = built
    for path in out.iterdir():
        doc = json.loads(path.read_text())
        for event in doc.get("events", []):
            assert "event_observations" not in event and "depth_mm" not in event
            assert "impact" not in event


# ---- re-export is byte-identical, and nothing here reads a clock -------------------

def test_re_export_is_byte_identical(root, tmp_path):
    con = duck.connect()
    first, second = tmp_path / "a" / history.DIR, tmp_path / "b" / history.DIR
    history.build(con, root, first)
    history.build(con, root, second)
    con.close()
    a = {p.name: p.read_bytes() for p in first.iterdir()}
    b = {p.name: p.read_bytes() for p in second.iterdir()}
    assert a == b and len(a) > 1


def test_the_sweep_is_re_sorted_so_batch_order_cannot_leak(manifest):
    """The manifest's order is the Cell batches' order until it is sorted. A rebuild whose
    Cell list moved would otherwise reorder the whole file for no reason."""
    ids = [f["properties"]["asset_id"] for f in manifest["features"]]
    assert ids == sorted(ids)


def test_no_wall_clock_reaches_any_written_file():
    """A writer's own timestamp breaks the byte-identity above and does not even measure
    what a reader wants. The page dates every payload from its own HTTP response."""
    for forbidden in ("datetime.now", "utcnow", "time.time", "date.today", "time.monotonic"):
        assert forbidden not in SOURCE
    tree = ast.parse(SOURCE)
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"time", "datetime"}


# ---- the renderer holds no join of its own -----------------------------------------

def test_the_renderer_reaches_the_flood_tables_only_through_the_query_seam():
    """The ticket's own acceptance row. F05 owns the attachment and `events_for_asset` owns
    the complex rollup; a second copy of either would drift between the map and the model."""
    calls = {n.func.attr for n in ast.walk(ast.parse(SOURCE))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "query"}
    assert calls <= {"view", "pack", "cell_id", "versions"}
    for name in ("flood_labels", "flood_events", "flood_obs", "flood_exposure"):
        assert name not in SOURCE, f"{name} is the seam's to read, not this module's"


def test_no_sql_in_this_module_joins_anything(manifest):
    """Its only SQL is two flat projections of the registry view — the one fact the seam
    does not carry (a coordinate) and the Cell list the sweep walks."""
    statements = sql_literals(SOURCE)
    assert statements and all("JOIN" not in s.upper() for s in statements)
    assert all(s.upper().count("FROM") == 1 and "FROM assets" in s for s in statements)


def test_the_manifest_is_built_by_calling_the_registered_query_functions():
    """Not by importing the implementations: `query.QUERIES[...]` is the registry the whole
    seam is addressed through, and it is what the MCP layer binds to as well."""
    assert 'query.QUERIES["assets_in_area"]' in SOURCE
    assert 'query.QUERIES["events_for_asset"]' in SOURCE
    assert 'query.QUERIES["exposure_of"]' in SOURCE
    assert set(history.QUERIES) <= set(q.QUERIES)


def test_the_sweep_covers_every_cell_however_the_cap_batches_them(root, manifest,
                                                                  monkeypatch):
    """The fixture's six Cells fit in ONE batch at the real cap, so no fixture this size can
    tell a correct sweep from one that walks the first batch and stops — a mutation that
    stepped the range by the whole city while the slice still took CELL_CAP survived exactly
    that gap, and on the real root it would have silently dropped most of NYC. Drive the cap
    down until the batching is real, and require the same answer at every width."""
    con = duck.connect()
    cells, _ = history.registry(con, root)
    assert len(cells) > 2, "a one-batch fixture cannot discriminate any batching bug"
    full = [a["asset_id"] for a in history.flooded(con, root, cells)]
    for cap in (1, 2, 3, len(cells) - 1, len(cells)):
        monkeypatch.setattr(q, "CELL_CAP", cap)
        assert [a["asset_id"] for a in history.flooded(con, root, cells)] == full, cap
    con.close()
    assert full == sorted(f["properties"]["asset_id"] for f in manifest["features"])


def test_the_sweep_respects_the_seams_own_area_cap():
    """`CELL_CAP` exists so a tool call cannot ask for the city by accident. This walks it
    in bounded batches rather than around it — a renderer that raised the cap for itself
    would be deciding a licence-adjacent limit on the seam's behalf."""
    assert "query.CELL_CAP" in SOURCE and str(q.CELL_CAP) not in SOURCE


# ---- the batch cadence, and where the tree lands ------------------------------------

def test_make_exports_own_run_writes_the_tree_on_the_batch_path(root, tmp_path, monkeypatch):
    """`make export` is `python -m raincheck.export`, so main() is where the batch path is
    and where the wiring has to be pinned. The insight half is stubbed: this is the QUERY
    fixture root and it holds no Gold speed tables, and what is under test is that a batch
    export writes the tree at all — the trio is tests/test_export.py's subject."""
    out = tmp_path / "files"
    monkeypatch.setattr(export, "run", lambda *a, **k: {})
    monkeypatch.setattr(export, "report", lambda written: None)
    monkeypatch.setattr(export, "data_root", lambda: root)
    monkeypatch.setattr("sys.argv", ["export", "--out", str(out)])
    export.main()
    tree = json.loads((out / history.DIR / history.MANIFEST).read_text())
    assert [f["properties"]["asset_id"] for f in tree["features"]] == sorted(LISTED)
    assert (out / history.DIR / f"{ENTRANCE}.json").is_file()


def test_the_tree_never_rides_the_thirty_second_live_tick():
    """`make export` is the spine's BATCH path. The 30 s loop publishes the live pair and
    the flood panel; adding thousands of seam calls to it would be a different ticket and a
    dead pod."""
    for module in ("live_loop", "live_export", "flood_panel"):
        text = (REPO / "src" / "raincheck" / f"{module}.py").read_text()
        assert "history" not in text.replace("flood history", ""), module


def test_the_page_reads_the_manifest_at_the_url_frontend_05_froze():
    """A page constant that mirrors a python constant will drift — so DERIVE it here."""
    js = (REPO / "web" / "layers.js").read_text()
    assert f'"files/{history.DIR}/{history.MANIFEST}"' in js


def test_the_tree_publishes_as_the_history_family_and_owes_no_contract_bump(built):
    out, _ = built
    items = publish.plan("history", src=out)
    assert {i.key for i in items} == {f"files/history/{p.name}" for p in out.iterdir()}
    assert all(i.content_type in ("application/json", "application/geo+json") for i in items)
    assert ("history", "files/history/**", contract.TREE) in contract.PROMISE[1]
    assert contract.PROMISE[contract.CONTRACT] <= contract.surface()


# ---- all of the tree or none of it --------------------------------------------------

def test_a_build_that_dies_part_way_leaves_the_previous_tree_whole(root, tmp_path,
                                                                   monkeypatch):
    """Staged into a sibling and swapped in one rename. The failure this prevents is a
    manifest naming files that are not there — which is worse than a stale tree, because a
    consumer cannot tell it from a 404 it caused itself."""
    out = tmp_path / history.DIR
    con = duck.connect()
    history.build(con, root, out)
    before = {p.name: p.read_bytes() for p in out.iterdir()}

    boom = iter(range(2))
    real = history.payload
    monkeypatch.setattr(history, "payload",
                        lambda *a: real(*a) if next(boom, None) is not None
                        else (_ for _ in ()).throw(RuntimeError("died mid-tree")))
    with pytest.raises(RuntimeError):
        history.build(con, root, out)
    con.close()
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before


def test_a_root_with_no_flood_universe_writes_nothing_and_says_so(tmp_path, capsys):
    """`make export` runs against roots that hold no `ref/assets` at all. Refusing the whole
    export over an absent history tree would be a worse answer than an absent tree."""
    out = tmp_path / history.DIR
    con = duck.connect()
    assert history.build(con, tmp_path / "empty", out) == {}
    con.close()
    assert "history: not written" in capsys.readouterr().out
    assert not out.exists()
    history.report({})   # and the report is silent rather than raising on an empty one


# ---- the real root: the number the spec says to decide on ---------------------------

def test_the_seam_route_finds_exactly_what_a_direct_join_would():
    """THE load-bearing claim. The manifest walks the query seam so the attachment rule
    stays in one place — which is only worth doing if the answer is the same one a join
    gives. Real-root canary; the fixture cannot show a disagreement this large."""
    root = data_root()
    if not any((root / "gold" / "flood_labels").rglob("*.parquet")):
        pytest.skip("no built gold/flood_labels on this root")
    con = duck.connect()
    cells, _ = history.registry(con, root)
    seam = {a["asset_id"]: a["n_events"] for a in history.flooded(con, root, cells)}
    q.view(con, root, "gold", "flood_labels", name="labels",
           columns=("asset_id", "event_id"))
    direct = dict(con.execute(
        "SELECT a.asset_id, count(DISTINCT l.event_id) n FROM assets a "
        "JOIN assets c ON c.asset_id = a.asset_id "
        "  OR (a.kind = 'complex' AND c.parent_asset_id = a.asset_id) "
        "JOIN labels l ON l.asset_id = c.asset_id "
        "WHERE a.kind IN ('complex', 'entrance', 'bus_stop', 'cell') "
        "GROUP BY 1 HAVING n > 0").fetchall())
    con.close()
    assert seam == direct and len(seam) > 7000
