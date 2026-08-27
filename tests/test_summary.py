"""frontend2 04: the `summary` family — three aggregate payloads under files/summary/.

The flood-universe root is notify 02's fixture set, the same one test_history assembles;
`gold/route_flood` has no fixture, so this file plants one to flood-build 21a's §10
schema exactly — strings for both ids, int32 counts, float64 shares with
`share_len_limited`/`share_len_extreme` entirely NULL, date32 for `last_event_day` — and
DELIBERATELY OUT OF PHYSICAL ORDER, because two runs in one process pick the same
arbitrary order and only a planted-wrong-order table can catch a dropped ORDER BY
[KNOWN TRAPS, flood-build 19].
"""
import ast
import json
import shutil
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raincheck import duck, flood_route, history, publish, query as q, summary
from raincheck import stormwater_extent as se

FIXTURES = Path(__file__).parent / "fixtures"
LAYOUT = {"assets": ("ref", "assets"), "events": ("silver", "flood_events"),
          "obs": ("silver", "flood_obs"), "labels": ("gold", "flood_labels"),
          "exposure": ("gold", "flood_exposure")}
SOURCE = Path(summary.__file__).read_text()

ROUTE_SCHEMA = pa.schema([
    ("route_id", pa.string()), ("direction_id", pa.string()),
    ("n_shapes", pa.int32()), ("length_m", pa.float64()),
    ("n_cells", pa.int32()), ("n_cells_flood_prone", pa.int32()),
    ("share_len_limited", pa.float64()), ("share_len_moderate", pa.float64()),
    ("share_len_extreme", pa.float64()), ("share_len_not_analyzed", pa.float64()),
    ("n_flood_events", pa.int32()), ("last_event_day", pa.date32()),
    ("label_version", pa.string()), ("features_version", pa.string()),
    ("zip_sha256", pa.string()), ("route_flood_version", pa.string()),
])
STAMPS = dict(label_version="lv1", features_version="fv1", zip_sha256="zip1",
              route_flood_version="rfv1")
SECOND_DEPTH = 12.5     # the smaller sibling depth that makes max() discriminable


def route_row(route_id, direction_id, moderate, not_analyzed, **over):
    row = dict(route_id=route_id, direction_id=direction_id, n_shapes=2,
               length_m=10904.662027968465, n_cells=15, n_cells_flood_prone=14,
               share_len_limited=None, share_len_moderate=moderate,
               share_len_extreme=None, share_len_not_analyzed=not_analyzed,
               n_flood_events=89, last_event_day=date(2023, 11, 24), **STAMPS)
    row.update(over)
    return row


# Physically OUT OF ORDER on purpose; ("Q99", "0") is the no-measurable-geometry route,
# whose shares are all NULL — the row that must publish NEITHER share key, never 0.0.
ROUTE_ROWS = [
    route_row("M5", "1", 0.2825, 0.009665206738268668),
    route_row("B1", "1", 0.03637867047326969, 0.805),
    route_row("Q99", "0", None, None, n_cells=0, n_cells_flood_prone=0, length_m=0.0),
    route_row("B1", "0", 0.0282, 0.11),
]


def write_routes(root: Path, rows) -> None:
    dest = root / "gold" / "route_flood"
    dest.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=ROUTE_SCHEMA),
                   dest / "part-00000.parquet")


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    r = tmp_path_factory.mktemp("summary")
    for name, parts in LAYOUT.items():
        r.joinpath(*parts).mkdir(parents=True)
        shutil.copy(FIXTURES / f"notify_query_{name}.parquet",
                    r.joinpath(*parts) / "part-00000.parquet")
    # A SECOND, smaller depth on 2023-08-29's already-labelled Cell, as an extra part
    # file (the shared fixture is notify 02's and extended by nobody). Without it every
    # event holds exactly ONE non-null depth and max() is indistinguishable from min() -
    # the degenerate-fixture trap. Same asset, same source bit: no count, cell list or
    # source decode moves.
    labels = pq.read_table(FIXTURES / "notify_query_labels.parquet")
    extra = next(row for row in labels.to_pylist()
                 if row["event_id"] == "2023-08-29" and row["kind"] == "cell")
    assert extra["depth_mm"] and extra["depth_mm"] != SECOND_DEPTH
    pq.write_table(pa.Table.from_pylist([{**extra, "depth_mm": SECOND_DEPTH}],
                                        schema=labels.schema),
                   r.joinpath(*LAYOUT["labels"]) / "part-00001.parquet")
    write_routes(r, ROUTE_ROWS)
    return r


@pytest.fixture(scope="module")
def built(root, tmp_path_factory):
    out = tmp_path_factory.mktemp("web") / summary.FAMILY
    con = duck.connect()
    sizes = summary.build(con, root, out)
    con.close()
    return out, sizes


def doc(built, name: str) -> dict:
    out, _ = built
    return json.loads((out / name).read_text())


# ---- the family --------------------------------------------------------------------

def test_the_family_is_an_additive_tree_under_files_summary(built):
    """A TREE family: contract.PROMISE[1] freezes the prefix, the file names inside are
    this writer's, and no CONTRACT bump is owed — the same rule `geo` landed under."""
    fam = publish.FAMILIES[summary.FAMILY]
    assert not fam.files and fam.prefix == "files/summary/" and not fam.gated
    out, _ = built
    items = publish.plan(summary.FAMILY, out)
    assert [i.key for i in items] == [f"files/summary/{n}" for n in sorted(summary.FILES)]
    assert all(i.content_type == "application/json" for i in items)


def test_all_three_files_are_written_and_sized(built):
    out, sizes = built
    assert sorted(p.name for p in out.iterdir()) == sorted(summary.FILES)
    assert set(sizes) == set(summary.FILES) and all(v > 0 for v in sizes.values())


def test_every_file_carries_the_stamps_of_the_universe_that_answered(built, root):
    con = duck.connect()
    stamps = q.versions(con, root)
    con.close()
    for name in summary.FILES:
        assert doc(built, name)["versions"] == stamps


def test_every_file_ships_its_caveats_as_sentences(built):
    """The caveats are module constants shipped IN the payload (flood 17's rule: render
    them, never restate them) — and the descriptive-claim sentence is among them."""
    for name, want in (("recent.json", summary.CAVEATS_RECENT),
                       ("complexes.json", summary.CAVEATS_COMPLEXES),
                       ("routes.json", summary.CAVEATS_ROUTES)):
        assert doc(built, name)["strings"]["caveats"] == list(want)
    assert any("statistical claim" in s for s in doc(built, "routes.json")
               ["strings"]["caveats"])


# ---- recent.json -------------------------------------------------------------------

def test_the_window_is_anchored_on_the_spines_newest_day_not_on_today(built):
    """The fixture's newest event is 2023-11-24; a wall-clock anchor would date the
    window in 2026 and empty it."""
    r = doc(built, "recent.json")
    assert r["window"] == {"since": "2022-11-24", "until": "2023-11-24",
                           "days": summary.RECENT_DAYS}
    assert r["n_events"] == 2
    assert [e["event_id"] for e in r["events"]] == ["2023-11-24", "2023-08-29"]


def test_an_event_older_than_the_window_is_dropped(tmp_path):
    """The window predicate is a branch; on the shipped fixture both events pass it, so
    this re-dates one event out of range and asserts it disappears."""
    aged = tmp_path / "aged"
    for name, parts in LAYOUT.items():
        aged.joinpath(*parts).mkdir(parents=True)
        shutil.copy(FIXTURES / f"notify_query_{name}.parquet",
                    aged.joinpath(*parts) / "part-00000.parquet")
    t = pq.read_table(FIXTURES / "notify_query_events.parquet").to_pylist()
    for row in t:
        if row["event_id"] == "2023-08-29":
            row["day_start"] = row["day_end"] = date(2020, 8, 29)
    pq.write_table(
        pa.Table.from_pylist(
            t, schema=pq.read_schema(FIXTURES / "notify_query_events.parquet")),
        aged.joinpath(*LAYOUT["events"]) / "part-00000.parquet")
    con = duck.connect()
    r = summary.recent(con, aged)
    con.close()
    assert [e["event_id"] for e in r["events"]] == ["2023-11-24"]
    assert r["window"]["until"] == "2023-11-24"


def test_event_counts_are_labelled_asset_counts_at_each_kind(built):
    """Counted straight off the published attachment, per kind — 2023-11-24 labels one
    bus stop, one Cell, two entrances and one complex in the fixture."""
    by_id = {e["event_id"]: e for e in doc(built, "recent.json")["events"]}
    assert by_id["2023-11-24"]["n_assets"] == {
        "bus_stop": 1, "cell": 1, "complex": 1, "entrance": 2}
    assert by_id["2023-08-29"]["n_assets"] == {
        "bus_stop": 0, "cell": 1, "complex": 1, "entrance": 0}


def test_event_sources_are_decoded_through_the_frozen_bit_map(built):
    by_id = {e["event_id"]: e for e in doc(built, "recent.json")["events"]}
    assert by_id["2023-08-29"]["sources"] == ["floodnet", "mta_alert"]
    assert by_id["2023-11-24"]["sources"] == ["311", "floodnet", "mta_alert"]


def test_event_cells_are_sorted_hex_strings_never_int64(built):
    """613229535722209279 is past 2^53; the hex spelling is what joins
    files/cells.geojson without a lookup."""
    for e in doc(built, "recent.json")["events"]:
        assert e["cells"] == sorted(e["cells"])
        assert all(isinstance(c, str) and int(c, 16) for c in e["cells"])


def test_depth_passes_through_unrounded_and_absent_beats_null(built):
    """`depth_mm` is the table's own max — rounding it here would publish a different
    value than the table holds — and an event whose labels carry no depth at all would
    omit the key rather than write null. The fixture plants a SECOND, smaller depth on
    the same event, so max() here is not the identity over one value."""
    by_id = {e["event_id"]: e for e in doc(built, "recent.json")["events"]}
    assert by_id["2023-08-29"]["depth_mm"] == 309.87999999999994 != SECOND_DEPTH
    assert None not in leaves(doc(built, "recent.json"))


# ---- complexes.json ----------------------------------------------------------------

def test_a_rollup_only_complex_is_listed_with_its_entrances_history(built):
    """stn:409 carries no label of its own; two of its entrances do. The seam's rollup
    is what lists it — a direct read of gold/flood_labels would have lost it."""
    by_id = {c["asset_id"]: c for c in doc(built, "complexes.json")["complexes"]}
    assert set(by_id) == {"stn:409", "stn:611"}
    assert by_id["stn:409"]["n_events"] == 1
    assert by_id["stn:611"]["n_events"] == 2


def test_complex_counts_match_events_for_asset_exactly(built, root):
    con = duck.connect()
    for c in doc(built, "complexes.json")["complexes"]:
        answer = q.QUERIES["events_for_asset"](
            con, root, {"asset_id": c["asset_id"]}, "public")
        assert c["n_events"] == answer["n_events"]
        assert c["last_event_id"] == answer["events"][-1]["event_id"]
    con.close()


def test_complexes_carry_coordinates_because_a_place_needs_them(built):
    """The repo has shipped a place-shaped payload with no coordinates three times
    [KNOWN TRAPS]; rounded to the same COORD_DP the history manifest uses."""
    for c in doc(built, "complexes.json")["complexes"]:
        assert -75 < c["lon"] < -72 and 40 < c["lat"] < 42
        assert round(c["lon"], history.COORD_DP) == c["lon"]
        assert c["name"] and c["cell"]


def test_complexes_are_ordered_most_flooded_first_then_by_id(built):
    rows = doc(built, "complexes.json")["complexes"]
    assert [(-c["n_events"], c["asset_id"]) for c in rows] == sorted(
        (-c["n_events"], c["asset_id"]) for c in rows)


# ---- routes.json -------------------------------------------------------------------

def test_a_null_share_is_never_zero_and_never_a_key(built):
    """`share_len_limited` and `share_len_extreme` are NULL at the source; 0.0 would be
    a claim the route is dry. No row carries either key, and the raw text carries
    neither name."""
    r = doc(built, "routes.json")
    text = (built[0] / "routes.json").read_text()
    assert '"share_len_limited":0' not in text and '"share_len_extreme":0' not in text
    for row in r["routes"]:
        assert "share_len_limited" not in row and "share_len_extreme" not in row


def test_the_unpublished_reasons_are_derived_from_the_extent_builders_own_declarations(
        built):
    """The independent side: the `limited` reason IS stormwater_extent.UNREADABLE's
    sentence, and the `extreme` reason names the horizon DEP does publish."""
    got = doc(built, "routes.json")["not_published"]
    assert set(got) == {"share_len_limited", "share_len_extreme"}
    assert got["share_len_limited"] == se.UNREADABLE[("limited", "current")]
    assert "2080" in got["share_len_extreme"]
    assert all(reason for reason in got.values())


def test_the_mask_is_published_beside_the_flooded_share_or_neither(built):
    """One real route runs 80.5% of its length through ground DEP excluded; a payload
    carrying only the flooded share calls it safe. The no-geometry route (Q99) publishes
    NEITHER key — absent together, never one without the other and never 0.0."""
    rows = {(r["route_id"], r["direction_id"]): r
            for r in doc(built, "routes.json")["routes"]}
    for row in rows.values():
        assert ("share_len_moderate" in row) == ("share_len_not_analyzed" in row)
    assert "share_len_moderate" not in rows[("Q99", "0")]
    assert rows[("B1", "1")]["share_len_not_analyzed"] == 0.805


def test_routes_are_sorted_although_the_table_is_not(built):
    """The fixture is planted physically out of order; only that can catch a dropped
    ORDER BY, because two runs in one process pick the same arbitrary order."""
    keys = [(r["route_id"], r["direction_id"])
            for r in doc(built, "routes.json")["routes"]]
    assert keys == sorted(keys) and len(keys) == len(ROUTE_ROWS)


def test_route_facts_pass_through_with_their_types(built):
    rows = {(r["route_id"], r["direction_id"]): r
            for r in doc(built, "routes.json")["routes"]}
    b10 = rows[("B1", "0")]
    assert isinstance(b10["direction_id"], str)
    assert b10["length_m"] == 10904.662027968465          # unrounded pass-through
    assert b10["last_event_day"] == "2023-11-24"
    assert doc(built, "routes.json")["source"] == {
        "table": "gold/route_flood", **STAMPS}


def test_a_sourced_share_arriving_all_null_is_refused_not_dropped(tmp_path):
    """`moderate` HAS a current-sea-level source, so a table where it is entirely NULL is
    a broken build — publishing rows without the key would be the compressed-FGDB lie."""
    bad = [route_row("B1", "0", None, None), route_row("B1", "1", None, None)]
    r2 = tmp_path / "allnull"
    write_routes(r2, bad)
    con = duck.connect()
    with pytest.raises(summary.Refused) as exc:
        summary.routes(con, r2)
    con.close()
    assert "share_len_moderate" in str(exc.value)


def test_a_flooded_share_without_the_mask_beside_it_is_refused(tmp_path):
    bad = [route_row("B1", "0", 0.1, None), route_row("B1", "1", 0.2, None)]
    r2 = tmp_path / "nomask"
    write_routes(r2, bad)
    con = duck.connect()
    with pytest.raises(summary.Refused) as exc:
        summary.routes(con, r2)
    con.close()
    assert flood_route.MASK_COLUMN in str(exc.value)


def test_a_mixed_stamp_table_is_two_builds_and_refused(tmp_path):
    bad = [route_row("B1", "0", 0.1, 0.2),
           route_row("B1", "1", 0.1, 0.2, route_flood_version="rfv2")]
    r2 = tmp_path / "mixed"
    write_routes(r2, bad)
    con = duck.connect()
    with pytest.raises(summary.Refused) as exc:
        summary.routes(con, r2)
    con.close()
    assert "route_flood_version" in str(exc.value)


def test_a_missing_route_table_refuses_by_naming_its_builder(tmp_path):
    bare = tmp_path / "bare"
    con = duck.connect()
    with pytest.raises(summary.Refused) as exc:
        summary.routes(con, bare)
    con.close()
    assert "make flood-route" in str(exc.value)


# ---- the export discipline ---------------------------------------------------------

def test_re_export_is_byte_identical(root, tmp_path):
    con = duck.connect()
    first, second = tmp_path / "a" / summary.FAMILY, tmp_path / "b" / summary.FAMILY
    summary.build(con, root, first)
    summary.build(con, root, second)
    con.close()
    a = {p.name: p.read_bytes() for p in first.iterdir()}
    b = {p.name: p.read_bytes() for p in second.iterdir()}
    assert a == b and len(a) == len(summary.FILES)


def test_no_wall_clock_reaches_any_written_file():
    """The recent window is anchored on the spine's own newest day; a writer's timestamp
    would break the byte-identity above and measure nothing a reader wants."""
    for forbidden in ("datetime.now", "utcnow", "time.time", "date.today",
                      "time.monotonic"):
        assert forbidden not in SOURCE
    tree = ast.parse(SOURCE)
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import)
                for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"time", "datetime"}


def test_the_swap_never_leaves_the_family_missing(root, tmp_path):
    """A tree family has no file list for `publish` to refuse a partial build with, so
    the writer stages and swaps whole — a second build over an existing tree leaves no
    staging or previous sibling behind."""
    out = tmp_path / "web" / summary.FAMILY
    con = duck.connect()
    summary.build(con, root, out)
    summary.build(con, root, out)
    con.close()
    assert sorted(p.name for p in out.iterdir()) == sorted(summary.FILES)
    assert not out.with_name(out.name + history.STAGING).exists()
    assert not out.with_name(out.name + history.PREVIOUS).exists()


def leaves(obj):
    if isinstance(obj, dict):
        return [x for k, v in obj.items() for x in leaves(k) + leaves(v)]
    if isinstance(obj, list):
        return [x for v in obj for x in leaves(v)]
    return [obj]


def test_no_written_file_holds_a_null_anywhere(built):
    """Absent, never null — parsed back from disk, every leaf of all three files."""
    for name in summary.FILES:
        assert None not in leaves(doc(built, name)), name
