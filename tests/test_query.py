"""Notify ticket 02: the query core, its version stamps and THE LICENCE BOUNDARY.

The fixture root is CUT FROM THE REAL TABLES, which is the only way the boundary test
means anything: it holds real FloodNet incidents with real depths (309.88 mm and 46.99 mm),
a real MTA alert row with its prose and its `<alert_ids>:<complex_id>` source id, and 48
hours of real subwaydata-derived impact ratios for complex 611. A fixture with no
restricted rows would let `public` pass for the wrong reason, so `test_the_fixture_really_
holds_restricted_rows` asserts they are there before anything else asserts they stay in.

Provenance (Mac-only, one-off, against /Users/ross/raincheck/data): two small real events
(2023-08-29: 3x311 + 3xfloodnet + 1 alert; 2023-11-24: 2x311 + 2xfloodnet + 1 alert), every
observation inside their windows, eleven assets and every label on them, plus complex 611's
impact hours for those two days. The cast is chosen so the WRONG JOIN is detectable:

  bus:400081   labelled for 2023-11-24 by F05's 100 m radius from a 311 report that sits in
               a DIFFERENT H3 cell -- re-attaching flood_obs to ref/assets by cell LOSES it
  bus:400021   shares its cell with an in-window 311 report but is NOT labelled (>100 m) --
               the same wrong join INVENTS a flood for it
  stn:409      carries no label of its own; two of its four child entrances do (story 4)
  stn:611      alert-sourced labels in both events, and the subwaydata numbers
  cell:882a103827fffff   labelled in both events by FloodNet, so it carries the depths
"""
import ast
import json
import shutil
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raincheck import query as q

FIXTURES = Path(__file__).parent / "fixtures"
LAYOUT = {"assets": ("ref", "assets"), "events": ("silver", "flood_events"),
          "obs": ("silver", "flood_obs"), "labels": ("gold", "flood_labels")}
IMPACT = ("snapshots", "subwaydata", "impact")

COMPLEX, STATION, ROLLUP = "stn:611", "sta:725", "stn:409"
CELL_UNIT, DRY, CROSSED = "cell:882a103827fffff", "bus:400021", "bus:400081"
EVENTS = ("2023-08-29", "2023-11-24")
# the restricted values themselves: every one of these is a real production value, and
# none of them may appear anywhere in a `public` payload
FLOODNET_DEPTHS = (309.87999999999994, 46.99)
FLOODNET_SENSOR = "Q-beach-84-st-0me680"
ALERT_SOURCE_ID = "117601+117595+117596+117605:611"
# flood_obs.text on an alert row is the station name the alert NAMED, not its prose (the
# prose stays in the archive snapshot). That string is also this complex's public name in
# ref/assets, so the MTA-derived value a sweep can discriminate on is the alert id set --
# the row itself is what `public` withholds, structurally, by never emitting an obs row.
ALERT_TEXT = "Times Sq-42 St"


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    r = tmp_path_factory.mktemp("query")
    for name, parts in LAYOUT.items():
        (r.joinpath(*parts)).mkdir(parents=True)
        shutil.copy(FIXTURES / f"notify_query_{name}.parquet",
                    r.joinpath(*parts) / "part-00000.parquet")
    r.joinpath(*IMPACT).mkdir(parents=True)
    shutil.copy(FIXTURES / "notify_query_impact.parquet",
                r.joinpath(*IMPACT) / "subway_complex_hour.parquet")
    return r


def ask(root, asset_id, **kw):
    return q.query("events_for_asset", {"asset_id": asset_id}, root, **kw)


def leaves(obj):
    """Every scalar in a payload, flattened -- what a boundary sweep has to look at."""
    if isinstance(obj, dict):
        return [x for k, v in obj.items() for x in leaves(k) + leaves(v)]
    if isinstance(obj, list):
        return [x for v in obj for x in leaves(v)]
    return [obj]


# ---- the fixture is load-bearing: prove it holds what the boundary test bites on ----

def test_the_fixture_really_holds_restricted_rows(root):
    """A boundary test over a fixture with no restricted rows passes for the wrong reason."""
    obs = pq.read_table(root / "silver" / "flood_obs").to_pylist()
    fn = [o for o in obs if o["source"] == "floodnet"]
    alerts = [o for o in obs if o["source"] == "mta_alert"]
    assert len(fn) == 5 and {o["depth_mm"] for o in fn} >= set(FLOODNET_DEPTHS)
    assert any(FLOODNET_SENSOR in o["source_id"] for o in fn)
    assert [o["source_id"] for o in alerts].count(ALERT_SOURCE_ID) == 1
    assert all(o["text"] == ALERT_TEXT for o in alerts)
    impact = pq.read_table(root.joinpath(*IMPACT) / "subway_complex_hour.parquet")
    assert impact.num_rows == 48 and set(impact.column("complex_id").to_pylist()) == {"611"}
    # and the depths reach the labels, which is where `public` could leak them
    labels = pq.read_table(root / "gold" / "flood_labels").to_pylist()
    assert {r["depth_mm"] for r in labels if r["depth_mm"]} == set(FLOODNET_DEPTHS)


# ---- the licence boundary ----------------------------------------------------------

def test_public_is_the_default_mode(root):
    assert ask(root, COMPLEX)["mode"] == "public" == q.MODES[0]


def test_public_emits_no_restricted_value_for_any_asset(root):
    """The sweep: every asset in the fixture, every leaf of the payload, no FloodNet depth,
    no alert row or prose, no subwaydata number."""
    impact = [v for e in ask(root, COMPLEX, mode="local")["events"]
              for v in e["impact"].values()]
    assert len(impact) == 6
    # leaf EQUALITY for the numbers (a substring sweep would trip over n_hours=24 inside
    # the date "2023-11-24"), substring for the two long ids that could ride in a field
    values, ids = {*FLOODNET_DEPTHS, *impact}, (FLOODNET_SENSOR, ALERT_SOURCE_ID)
    for asset in (COMPLEX, ROLLUP, CELL_UNIT, CROSSED, DRY):
        payload = ask(root, asset)
        text = json.dumps(payload)
        assert values.isdisjoint(leaves(payload)), f"{asset}: a restricted number leaked"
        assert all(i not in text for i in ids), f"{asset}: a restricted id leaked"
        assert not {"depth_mm", "impact", "event_observations"} & set(leaves(payload))


def test_local_returns_the_rows_public_only_counts(root):
    pub, loc = ask(root, CELL_UNIT), ask(root, CELL_UNIT, mode="local")
    for p, l in zip(pub["events"], loc["events"]):
        assert p["event_source_counts"] == l["event_source_counts"]
        assert "event_observations" not in p
        # the counts are exactly the rows behind them, per source
        got = {}
        for o in l["event_observations"]:
            got[o["source"]] = got.get(o["source"], 0) + 1
        assert got == l["event_source_counts"]


def test_local_returns_the_floodnet_depth_public_cannot(root):
    loc = ask(root, CELL_UNIT, mode="local")
    assert [e["depth_mm"] for e in loc["events"]] == list(FLOODNET_DEPTHS)
    assert any(FLOODNET_SENSOR in o["source_id"]
               for e in loc["events"] for o in e["event_observations"])
    assert all("depth_mm" not in e for e in ask(root, CELL_UNIT)["events"])


def test_local_returns_the_alert_row_and_prose_public_cannot(root):
    loc = ask(root, COMPLEX, mode="local")
    rows = [o for e in loc["events"] for o in e["event_observations"]
            if o["source"] == "mta_alert"]
    assert {o["source_id"] for o in rows} >= {ALERT_SOURCE_ID}
    assert {o["text"] for o in rows} == {ALERT_TEXT}
    # public still says an alert saw it -- a count and an attachment are not a row
    pub = ask(root, COMPLEX)
    assert all("mta_alert" in e["sources"] for e in pub["events"])
    assert all(e["event_source_counts"]["mta_alert"] == 1 for e in pub["events"])


def test_local_returns_the_subwaydata_impact_public_cannot(root):
    loc = ask(root, COMPLEX, mode="local")
    assert all(e["impact"]["n_hours"] == 24 for e in loc["events"])
    assert all(0 < e["impact"]["min_service_ratio"] < 2 for e in loc["events"])
    # only a complex has one, and only where the file exists
    assert all("impact" not in e for e in ask(root, CELL_UNIT, mode="local")["events"])


def test_an_unknown_mode_is_a_typed_error(root):
    with pytest.raises(q.QueryError) as e:
        ask(root, COMPLEX, mode="Public")
    assert e.value.reason == "unknown_mode"


# ---- the attachment rule has one owner ---------------------------------------------

WRONG_JOIN = """
SELECT DISTINCT a.asset_id, e.event_id
  FROM read_parquet('{root}/silver/flood_obs/**/*.parquet') o
  JOIN read_parquet('{root}/silver/flood_events/**/*.parquet') e
    ON o.ts_utc >= e.window_start_utc AND o.ts_utc < e.window_end_utc
  JOIN read_parquet('{root}/ref/assets/**/*.parquet') a USING (cell)
"""


def test_the_wrong_join_gives_a_detectably_different_answer(root):
    """Re-attaching flood_obs to ref/assets is F05's job and nobody else's. The fixture is
    cut so the tempting re-attachment (same Cell, inside the window) disagrees with
    gold/flood_labels in BOTH directions -- it loses a real flood and invents one."""
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    wrong = {(a, e) for a, e in con.sql(WRONG_JOIN.format(root=root)).fetchall()}
    right = {(r["asset_id"], r["event_id"])
             for r in pq.read_table(root / "gold" / "flood_labels").to_pylist()}
    assert wrong != right
    assert (CROSSED, "2023-11-24") in right - wrong   # the radius crossed a cell boundary
    assert (DRY, "2023-11-24") in wrong - right       # same cell, but 100 m is 100 m

    # and the query follows the labels, not the join
    assert [e["event_id"] for e in ask(root, CROSSED)["events"]] == ["2023-11-24"]
    assert ask(root, DRY)["events"] == []


def test_a_complex_answers_over_its_child_entrances(root):
    """Story 4: a complex is not dry because the entrance you did not use stayed dry.
    stn:409 has no label row of its own -- two of its entrances do."""
    own = {r["asset_id"] for r in pq.read_table(root / "gold" / "flood_labels").to_pylist()}
    assert ROLLUP not in own
    got = ask(root, ROLLUP)
    assert [e["event_id"] for e in got["events"]] == ["2023-11-24"]
    assert got["events"][0]["label_support"] == ["radius"]


def test_a_station_is_a_carrier_and_names_the_complex_to_ask(root):
    with pytest.raises(q.QueryError) as e:
        ask(root, STATION)
    assert e.value.reason == "not_a_scored_unit"
    assert e.value.detail["ask"] == COMPLEX


# ---- the payload contract ----------------------------------------------------------

def test_the_history_is_the_labels_joined_to_the_event_windows(root):
    got = ask(root, COMPLEX)
    assert [e["event_id"] for e in got["events"]] == list(EVENTS)
    assert got["n_events"] == 2
    first = got["events"][0]
    assert first["window_start_utc"] == "2023-08-29T01:00:00Z"
    assert first["window_end_utc"] == "2023-08-30T07:00:00Z"
    assert first["day_start"] == "2023-08-29" and first["n_days"] == 1
    assert first["event_class"] == "pluvial"
    assert first["sources"] == ["mta_alert"] and first["label_support"] == ["station"]
    assert got["asset"]["kind"] == "complex"


def test_an_asset_with_no_history_says_so_explicitly(root):
    got = ask(root, DRY)
    assert got["events"] == [] and got["n_events"] == 0
    assert got["reason"] == q.NO_EVENTS
    assert got["versions"]["label_version"]     # an empty answer is stamped like any other


def test_an_unknown_id_raises_unknown_asset(root):
    with pytest.raises(q.QueryError) as e:
        ask(root, "bus:000000")
    assert e.value.reason == "unknown_asset"
    with pytest.raises(q.QueryError) as e:
        q.query("events_for_asset", {}, root)
    assert e.value.reason == "missing_param"
    with pytest.raises(q.QueryError) as e:
        q.query("obs_near", {}, root)
    assert e.value.reason == "unknown_query"


def test_no_payload_carries_a_null(root):
    """Absent, never null: the repo's pure-SQL JSON convention, carried through verbatim."""
    for asset in (COMPLEX, ROLLUP, CELL_UNIT, CROSSED, DRY):
        for mode in q.MODES:
            assert None not in leaves(ask(root, asset, mode=mode))


def test_every_payload_is_json_able(root):
    """DECIMAL call counts, int64 Cell ids and timestamps all break a naive encoder."""
    for asset in (COMPLEX, CELL_UNIT):
        for mode in q.MODES:
            payload = ask(root, asset, mode=mode)
            assert json.loads(json.dumps(payload)) == payload


def test_a_cell_crosses_the_boundary_as_an_h3_string(root):
    """An int64 H3 id does not survive a JSON reader that uses doubles."""
    got = ask(root, CELL_UNIT, mode="local")
    assert got["asset"]["cell"] == CELL_UNIT.split(":")[1]
    assert all(isinstance(o["cell"], str)
               for e in got["events"] for o in e["event_observations"])


def test_every_payload_carries_the_version_stamps(root):
    stamps = ask(root, COMPLEX)["versions"]
    labels = pq.read_table(root / "gold" / "flood_labels")
    events = pq.read_table(root / "silver" / "flood_events")
    assert stamps["label_version"] == labels.column("label_version")[0].as_py()
    assert stamps["spine_version"] == events.column("spine_version")[0].as_py()
    assert len(stamps["assets_version"]) == 40
    assert "score_version" not in stamps   # absent, not null: no score is read here


def test_an_unresolvable_stamp_is_an_error_not_an_unstamped_answer(root, tmp_path):
    """Two label versions under one root is the real hazard -- a half-rebuilt table."""
    mixed = tmp_path / "mixed"
    shutil.copytree(root, mixed)
    labels = pq.read_table(mixed / "gold" / "flood_labels")
    other = labels.set_column(labels.schema.get_field_index("label_version"),
                              "label_version",
                              pa.array(["other-version"] * labels.num_rows))
    pq.write_table(other, mixed / "gold" / "flood_labels" / "part-00001.parquet")
    with pytest.raises(q.QueryError) as e:
        ask(mixed, COMPLEX)
    assert e.value.reason == "version_unresolved"

    shutil.rmtree(mixed / "silver" / "flood_events")
    with pytest.raises(q.QueryError) as e:
        ask(mixed, COMPLEX)
    assert e.value.reason == "version_unresolved"


def test_the_read_path_holds_no_lazy_arrow_reader(root):
    """The wave-1 gate's deadlock: `rel.arrow()` is a LAZY RecordBatchReader on the
    relation's own connection, and this module joins several relations on one."""
    tree = ast.parse(Path(q.__file__).read_text())   # AST, so the docstring may say it
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "arrow" not in called and "create_view" in called
