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

Ticket 03 extended that same cut rather than starting a second one: `gold/flood_exposure`
rows for every scored asset above, plus TWO assets whose exposure answer is the interesting
one -- `bus:503102` (outside the DEM footprint: the kind-median fallback score, NULL surge
margin, three flags) and `cell:882a100011fffff` (a ref Cell outside F10's fit set, so it
has NO exposure row and no parent to ask). Neither sits in a Cell any fixture observation
touches, so the attachment tests above see exactly what they saw before.
"""
import ast
import inspect
import json
import shutil
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raincheck import duck, flood_exposure as fe, query as q
from raincheck.paths import data_root

FIXTURES = Path(__file__).parent / "fixtures"
LAYOUT = {"assets": ("ref", "assets"), "events": ("silver", "flood_events"),
          "obs": ("silver", "flood_obs"), "labels": ("gold", "flood_labels"),
          "exposure": ("gold", "flood_exposure")}
IMPACT = ("snapshots", "subwaydata", "impact")

COMPLEX, STATION, ROLLUP = "stn:611", "sta:725", "stn:409"
CELL_UNIT, DRY, CROSSED = "cell:882a103827fffff", "bus:400021", "bus:400081"
ENTRANCE = "ent:409:40.722103:-73.996812"     # a Unit for history, a Carrier for a score
FALLBACK = "bus:503102"                       # no DEM footprint -> the kind median
UNSCORED_CELL = "cell:882a100011fffff"        # in ref/assets, outside F10's fit set
SCORED = (COMPLEX, ROLLUP, CELL_UNIT, DRY, CROSSED, FALLBACK)
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


def score(root, asset_id, **kw):
    return q.query("exposure_of", {"asset_id": asset_id}, root, **kw)


def exposure_rows(root) -> dict:
    """F10's rows as they sit on disk -- what the payload is compared against."""
    return {r["asset_id"]: r
            for r in pq.read_table(root / "gold" / "flood_exposure").to_pylist()}


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
    exposure = pq.read_table(root / "gold" / "flood_exposure")
    assert stamps["score_version"] == exposure.column("score_version")[0].as_py()
    assert "model_id" not in stamps   # two of them ship: a fact about the ANSWER, not the
                                      # universe, so it rides on the exposure payload


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


# ---- ticket 03: exposure_of and the Unit/Carrier rule ------------------------------

def test_the_exposure_fixture_is_not_degenerate_for_what_these_tests_pin(root):
    """A fallback row whose flags were empty, or a margin that happened to be non-NULL,
    would let the two payload rules below pass while asserting nothing."""
    rows = exposure_rows(root)
    assert set(rows) == set(SCORED)                     # and NOT the station or entrance
    assert rows[FALLBACK]["surge_margin_ft"] is None
    assert "score_fallback_kind_median" in rows[FALLBACK]["flags"]
    assert rows[CELL_UNIT]["surge_margin_ft"] is None
    assert rows[COMPLEX]["surge_margin_ft"] is not None  # or "absent" proves nothing
    assert {r["model_id"] for r in rows.values()} == {"point:l2_logistic", "cell:l2_logistic"}


def test_the_answer_is_f10s_row_read_and_nothing_is_recomputed(root):
    """The complex row ALREADY holds the max over its child entrances (F10 computed it and
    verified it against an independent recomputation for all 445), and entrances publish no
    row, so it is not even re-derivable here. Equality against the table is the pin; the
    source check is the second half, because a recomputation that agreed on this fixture
    would still be a second implementation of a one-home rule."""
    rows = exposure_rows(root)
    for asset in SCORED:
        got = score(root, asset)["exposure"]
        row = rows[asset]
        assert got["model_id"] == row["model_id"]
        assert (got["score_ref"], got["score_severe"], got["score_index"]) == (
            row["score_ref"], row["score_severe"], row["score_index"])
        assert got["flags"] == row["flags"]
    src = inspect.getsource(q.exposure_of)
    assert "max(" not in src.lower() and "group by" not in src.lower()


def test_the_complex_answer_is_the_one_the_table_publishes_not_a_child_rollup(root):
    """stn:409's four entrances are in this fixture's registry and NONE of them is in
    gold/flood_exposure -- a query that rolled up children here would have nothing to roll
    up and could not return the complex's number at all."""
    rows = exposure_rows(root)
    children = [a["asset_id"] for a in
                pq.read_table(root / "ref" / "assets").to_pylist()
                if a["parent_asset_id"] == ROLLUP]
    assert len(children) == 5 and not set(children) & set(rows)
    assert score(root, ROLLUP)["exposure"]["score_index"] == rows[ROLLUP]["score_index"]


def test_a_carrier_is_never_scored_and_names_the_complex_to_ask(root):
    """The table's MEMBERSHIP is the Unit/Carrier rule made concrete: `not_a_scored_unit`
    fires on absence, not on a kind list. An entrance is the case the two queries disagree
    about on purpose -- it carries a history of its own and no score of its own."""
    for carrier, parent in ((STATION, COMPLEX), (ENTRANCE, ROLLUP)):
        with pytest.raises(q.QueryError) as e:
            score(root, carrier)
        assert e.value.reason == "not_a_scored_unit"
        assert e.value.detail["ask"] == parent
    assert ask(root, ENTRANCE)["asset"]["kind"] == "entrance"   # history: a Unit


def test_a_cell_outside_the_fit_set_is_unscored_with_no_ask_rather_than_a_null_one(root):
    """2,762 of the real root's 4,113 ref Cells are outside F10's fit set. They are not
    Carriers and have no parent, so `ask` is ABSENT -- a null would read as an answer."""
    with pytest.raises(q.QueryError) as e:
        score(root, UNSCORED_CELL)
    assert e.value.reason == "not_a_scored_unit" and e.value.detail["kind"] == "cell"
    assert "ask" not in e.value.detail
    with pytest.raises(q.QueryError) as e:
        score(root, "bus:000000")
    assert e.value.reason == "unknown_asset"      # unknown is not the same as unscored


def test_a_missing_surge_margin_is_absent_never_zero(root):
    """404 Units have no point elevation behind them. Zero would say the water is AT the
    doorway; the reason rides on the flag instead."""
    got = score(root, FALLBACK)["exposure"]
    assert "surge_margin_ft" not in got and "no_surge_margin" in got["flags"]
    assert score(root, COMPLEX)["exposure"]["surge_margin_ft"] > 0


def test_a_fallback_score_is_never_presented_as_a_modelled_rank(root):
    """60 bus stops score on the KIND MEDIAN because their features could not be built at
    all. The rank is still published -- it is what the median means -- but a renderer that
    never looks at flags must not be able to read it as a model evaluation."""
    assert score(root, FALLBACK)["exposure"]["modelled"] is False
    assert all(score(root, a)["exposure"]["modelled"] is True
               for a in SCORED if a != FALLBACK)


def test_the_fallback_flag_names_the_one_f10_publishes_as_not_a_model_evaluation(root):
    """`modelled` hinges on ONE flag name, and the DATA cannot pin which one: on the real
    root `no_dem_footprint` and `score_fallback_kind_median` sit on exactly the same 60
    rows (measured 2026-08-25, zero either way), so swapping the constant between them is
    a mutation no fixture can catch. F10's published MEANINGS can and do -- only one of
    the five says the score is not a model evaluation, which is the property `modelled`
    reports. The rows are equal today by construction, not by definition: FLAGS' own text
    says the fallback rides beside `no_dem_footprint` OR `no_matrix_row`, and the latter is
    frozen at 0."""
    meaning = fe.FLAGS[q.FALLBACK_FLAG]
    assert "median" in meaning and "not a model evaluation" in meaning
    assert [f for f, m in fe.FLAGS.items() if "not a model evaluation" in m] == [q.FALLBACK_FLAG]


def test_the_flags_are_f10s_closed_vocabulary_and_their_meanings_are_published(root):
    """Passed through unworded: the payload names the flag, the coefficient artifact says
    what it means, so nobody words it twice and the two cannot drift."""
    published = json.loads(fe.COEFFICIENTS.read_text())["flags"]
    assert set(published) == set(fe.FLAGS)
    for asset in SCORED:
        assert set(score(root, asset)["exposure"]["flags"]) <= set(published)


def test_the_human_facing_number_is_the_rank_and_the_scores_are_the_raw_predictor(root):
    """A score is the LINEAR PREDICTOR, negative for nearly every Unit -- shipping it as
    "the number" invites a probability reading. `score_index` is the within-kind rank."""
    for asset in SCORED:
        got = score(root, asset)["exposure"]
        assert 0 < got["score_index"] <= 1
        assert got["score_ref"] < 0 and got["score_severe"] < 0
        assert got["score_severe"] > got["score_ref"]     # severe forcing, same Unit


def test_the_licence_boundary_does_not_reach_this_answer(root):
    """One rule, and it is about MTA / FloodNet / subwaydata ROWS. A score built from
    elevation, stormwater class and public precip is in no restricted class."""
    for asset in SCORED:
        pub, loc = score(root, asset), score(root, asset, mode="local")
        assert loc.pop("mode") == "local" and pub.pop("mode") == "public"
        assert pub == loc


def test_one_asset_gets_one_answer_from_both_queries_both_stamped(root):
    """The per-asset payload composes with 02's history: the same identity block, the same
    stamps, two objects a renderer can put side by side."""
    hist, exp = ask(root, COMPLEX), score(root, COMPLEX)
    assert hist["asset"] == exp["asset"]
    assert hist["versions"] == exp["versions"]
    assert exp["query"] == "exposure_of" and exp["mode"] == "public"


def test_the_score_stamp_is_absent_on_a_root_that_publishes_no_scores(root, tmp_path):
    """Absent, never null -- the convention `files/index.json` renders. contract.index()
    calls this same seam, so a Gold-only root there loses the key rather than nulling it."""
    con = duck.connect()
    assert "score_version" in q.versions(con, root)
    bare = tmp_path / "bare"
    shutil.copytree(root, bare)
    shutil.rmtree(bare / "gold" / "flood_exposure")
    assert "score_version" not in q.versions(con, bare)
    con.close()
    with pytest.raises(q.QueryError) as e:
        score(bare, COMPLEX)
    assert e.value.reason == "not_a_scored_unit"   # no table, so nothing is a scored Unit


def test_the_exposure_payload_is_json_able_and_carries_no_null(root):
    for asset in SCORED:
        for mode in q.MODES:
            payload = score(root, asset, mode=mode)
            assert json.loads(json.dumps(payload)) == payload
            assert None not in leaves(payload)


def test_the_registry_and_the_scored_table_agree_about_who_is_a_unit():
    """Real-root canary. F10's membership is the rule this query enforces; `ref/assets`
    declares `scored` independently. They agree EXACTLY on the real root (15,166 both
    ways), so a disagreement means one of the two moved without the other."""
    root = data_root()
    part = root / "gold" / "flood_exposure"
    if not part.exists() or not (root / "ref" / "assets").exists():
        pytest.skip("no built gold/flood_exposure on this root")
    con = duck.connect()
    scored = {r[0] for r in duck.table(con, root / "ref" / "assets").query(
        "t", "SELECT asset_id FROM t WHERE scored").fetchall()}
    published = {r[0] for r in duck.table(con, part).project("asset_id").fetchall()}
    census = dict(duck.table(con, part).query(
        "t", "SELECT f, count(*) FROM (SELECT unnest(flags) AS f FROM t) GROUP BY 1").fetchall())
    con.close()
    assert scored == published and len(published) == 15166
    # and the flag census F10 published, so `modelled` is measured against real counts
    assert census == {"elev_ring15_fallback": 36, "no_dem_footprint": 60,
                      "score_fallback_kind_median": 60, "no_surge_margin": 404}
    assert "no_matrix_row" not in census   # frozen at 0 by F10's own gate
