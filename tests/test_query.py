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

Ticket 04 extended that same cut once more, with the four `cell:` REGISTRY rows for the
Cells the assets above sit in (`882a100d61fffff`, `882a103a45fffff`, `882a10725bfffff`,
`882a1072c1fffff`). The real registry holds a Cell row for every populated Cell; without
them a bbox resolves to a Cell set containing no bus stop, and the resolution tests would
pass while asserting nothing. They add no label and no exposure row, so every count above
is unchanged -- only `assets_version`, which no test pins by value, moves.
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

from raincheck import duck, flood_exposure as fe, flood_labels as fl, query as q
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
        q.query("obs_anywhere", {}, root)      # ticket 04 registered obs_near itself
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
    published = json.loads(fe.COEFFICIENTS.read_text())
    assert published["score"]["is_probability"] is False
    for asset in SCORED:
        got = score(root, asset)["exposure"]
        assert 0 < got["score_index"] <= 1
        assert got["score_ref"] < 0 and got["score_severe"] < 0
        assert got["score_severe"] > got["score_ref"]     # severe forcing, same Unit
        # and the payload says what the number is ABOUT, from F10's own constant
        assert got["estimand"] == published["estimand"] == fl.ESTIMAND


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
    calls this same seam, so a Gold-only root there loses the key rather than nulling it.

    BOTH shapes of "no scores" are here, because they are not the same root: the table
    missing, and the table's DIRECTORY present but EMPTY -- what a scoring run that died
    between its `mkdir` and its `pq.write_table` leaves behind. A directory-existence test
    reads the second as "this root publishes scores", and then DuckDB's globber raises,
    `versions()` reports `version_unresolved` for the whole root, and `events_for_asset`
    -- which reads no score at all -- dies with it. A table is a part file, not a folder."""
    con = duck.connect()
    assert "score_version" in q.versions(con, root)
    for how in ("removed", "emptied"):
        bare = tmp_path / how
        shutil.copytree(root, bare)
        table = bare / "gold" / "flood_exposure"
        shutil.rmtree(table) if how == "removed" else [f.unlink() for f in table.iterdir()]
        assert table.exists() is (how == "emptied")
        assert "score_version" not in q.versions(con, bare)
        assert ask(bare, COMPLEX)["n_events"] == 2      # the history is untouched by this
        with pytest.raises(q.QueryError) as e:          # a typed refusal, never a traceback
            score(bare, COMPLEX)
        assert e.value.reason == "not_a_scored_unit"
        with pytest.raises(q.QueryError):               # and on the REGISTRY call too --
            q.exposure_of(duck.connect(), bare, {"asset_id": COMPLEX}, "public")
    con.close()


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


# ---- ticket 04: the area pair, the cap, and the licence refusal --------------------

AREA = "882a1072c1fffff"          # the Cell stn:409, its four entrances, bus:400081 and
                                  # the Carrier sta:638 all sit in
AREA_ASSETS = ("bus:400081", "cell:882a1072c1fffff", "stn:409",
               "ent:409:40.722103:-73.996812", "ent:409:40.722226:-73.996790",
               "ent:409:40.722408:-73.997477", "ent:409:40.722477:-73.997419")
AREA_BBOX = [-74.005, 40.720, -73.999, 40.726]     # a box around that Cell's centroid
OCEAN = [-73.60, 40.20, -73.55, 40.25]             # the Atlantic: a box with no Cell in it
SENSOR_M = 248.4                  # CELL_UNIT's centroid to the beach FloodNet sensor


def where(root, mode="public", **params):
    return q.query("assets_in_area", params, root, mode=mode)


def near(root, mode="local", **params):
    return q.query("obs_near", params, root, mode=mode)


def ids(payload) -> list:
    return [a["asset_id"] for a in payload["assets"]]


def test_the_area_fixture_is_not_degenerate_for_what_these_tests_pin(root):
    """Three properties this section leans on. The registry cut is COMPLETE the way the
    real one is -- every asset's Cell has a `cell:` row of its own -- or a bbox would
    resolve to a Cell set that holds no bus stop and the resolution test would pass while
    asserting nothing. The area holds a station, so excluding Carriers is a real exclusion.
    And its complex carries NO label row of its own, so `n_events` for it can only come
    from the rollup over its entrances."""
    assets = pq.read_table(root / "ref" / "assets").to_pylist()
    assert {a["cell"] for a in assets} == {a["cell"] for a in assets if a["kind"] == "cell"}
    here = {a["kind"] for a in assets if a["cell"] == int(AREA, 16)}
    assert here == {"bus_stop", "cell", "complex", "entrance", "station"}
    own = {r["asset_id"] for r in pq.read_table(root / "gold" / "flood_labels").to_pylist()}
    assert ROLLUP not in own and any(a.startswith("ent:409") for a in own)


def test_a_cell_id_crosses_the_area_boundary_as_an_h3_hex_string(root):
    """In and out: the same string a `cell:<h3>` asset id carries. The int64 is REFUSED by
    name rather than accepted, because 613229535722209279 is past 2^53 and a JSON reader
    using doubles has already corrupted it by the time it arrives here."""
    got = where(root, cells=[AREA])
    assert got["area"] == {"cells": [AREA], "n_cells": 1}
    assert {a["cell"] for a in got["assets"]} == {AREA}
    assert where(root, cells=AREA) == got          # one Cell needs no list
    with pytest.raises(q.QueryError) as e:
        where(root, cells=[int(AREA, 16)])
    assert e.value.reason == "missing_param" and e.value.detail["param"] == "cells"
    with pytest.raises(q.QueryError):
        where(root, cells=["not-hex"])


def test_the_area_lists_every_unit_in_the_cell_and_no_carrier(root):
    """`assets_in_area` answers with ids a caller did not have to know. Stations are
    Carriers -- `events_for_asset` refuses them and names the complex -- so listing one
    with a count would publish a number for an asset that cannot be asked for it."""
    got = where(root, cells=[AREA])
    assert sorted(ids(got)) == sorted(AREA_ASSETS) and got["n_assets"] == 7
    assert STATION not in ids(got) and ROLLUP in ids(got)
    with pytest.raises(q.QueryError) as e:      # the reason it is not listed
        ask(root, STATION)
    assert e.value.reason == "not_a_scored_unit"


def test_the_area_count_is_the_history_events_for_asset_would_return(root):
    """One rollup rule, two queries: a complex answers for its child entrances in both, so
    `n_events` here and the event list there cannot drift. stn:409 is the case that proves
    it -- zero label rows of its own, one event through an entrance."""
    for area in ([AREA], [CELL_UNIT.split(":")[1]]):     # the second Cell has TWO events,
        for asset in where(root, cells=area)["assets"]:  # so `last_` is not `first_`
            events = ask(root, asset["asset_id"])["events"]
            assert asset["n_events"] == len(events)
            assert asset.get("last_event_id") == (events[-1]["event_id"] if events else None)
    assert [a["n_events"] for a in where(root, cells=[AREA])["assets"]
            if a["asset_id"] == ROLLUP] == [1]
    assert [a["last_event_id"] for a in where(root, cells=[CELL_UNIT.split(":")[1]])["assets"]
            if a["asset_id"] == CELL_UNIT] == [EVENTS[-1]]


def test_a_bbox_snaps_to_a_cell_set_and_answers_the_same_as_the_cells_do(root):
    """A bbox is not a second area key: it RESOLVES to Cells (by centroid, the rule
    `ref/cell_zone` already uses) and the answer names them. A flipped box is still a box."""
    got = where(root, bbox=AREA_BBOX)
    assert got["area"]["cells"] == [AREA] and got["area"]["bbox"] == AREA_BBOX
    assert ids(got) == ids(where(root, cells=[AREA]))
    flipped = [AREA_BBOX[2], AREA_BBOX[3], AREA_BBOX[0], AREA_BBOX[1]]
    assert where(root, bbox=flipped) == got
    with pytest.raises(q.QueryError) as e:
        where(root, bbox=[-74.0, 40.7])
    assert e.value.reason == "missing_param" and e.value.detail["param"] == "bbox"
    with pytest.raises(q.QueryError) as e:
        where(root, cells=None, bbox=None)
    assert e.value.detail["param"] == "cells|bbox"


def test_an_area_past_the_cap_is_refused_by_name_before_anything_is_read(root, tmp_path):
    """The cap is what stops a tool call asking for the city (4,113 Cells) by accident, and
    the refusal NAMES it so an agent can retry smaller. `before anything is read` is the
    other half and it is measurable: on a root whose labels table is gone, an over-large
    area still returns `area_too_large` while an in-cap one dies resolving the tables."""
    over = [format(int(AREA, 16) + i, "x") for i in range(q.CELL_CAP + 1)]
    with pytest.raises(q.QueryError) as e:
        where(root, cells=over)
    assert e.value.reason == "area_too_large"
    assert e.value.detail == {"n_cells": q.CELL_CAP + 1, "cap": q.CELL_CAP}

    bare = tmp_path / "unlabelled"
    shutil.copytree(root, bare)
    shutil.rmtree(bare / "gold" / "flood_labels")
    con = duck.connect()
    with pytest.raises(q.QueryError) as e:
        q.assets_in_area(con, bare, {"cells": over}, "public")
    assert e.value.reason == "area_too_large"
    with pytest.raises(q.QueryError) as e:
        q.assets_in_area(con, bare, {"cells": [AREA]}, "public")
    assert e.value.reason == "version_unresolved"
    con.close()


def test_an_area_with_nothing_in_it_says_so_and_is_still_stamped(root):
    """Absence is legible as absence: a box over open water resolves to no Cell at all and
    that is an answer, not an error -- an empty list, a stated reason, the same stamps."""
    got = where(root, bbox=OCEAN)
    assert got["area"] == {"cells": [], "n_cells": 0, "bbox": OCEAN}
    assert got["n_assets"] == 0
    assert got["assets"] == [] and got["reason"] == q.NO_ASSETS
    assert got["versions"]["label_version"]


def test_zone_is_not_an_area_key_and_no_polygon_query_exists(root):
    """v1's frozen shape: FOUR query names, Cell the only area key. A Zone is a
    presentation overlay resolved through the static Cell-to-Zone lookup at serving time --
    it is no stored key, no parameter and no query -- and a caller holding a polygon
    resolves it to Cells itself."""
    assert set(q.QUERIES) == {"events_for_asset", "exposure_of", "assets_in_area",
                              "obs_near"}
    for name in ("assets_in_zone", "obs_in_polygon"):
        with pytest.raises(q.QueryError) as e:
            q.query(name, {}, root)
        assert e.value.reason == "unknown_query"
    with pytest.raises(q.QueryError) as e:          # a Zone is not a parameter either
        where(root, zone_id=161)
    assert e.value.reason == "missing_param" and e.value.detail["param"] == "cells|bbox"
    assert "zone" not in json.dumps(where(root, cells=[AREA])).lower()


def test_the_area_answer_is_the_same_in_both_modes(root):
    """Mode-invariance: this answer is built from the registry and F05's attachment COUNTS,
    and a count is not a row. The boundary differs by refusal, never by shape."""
    pub, loc = where(root, cells=[AREA]), where(root, mode="local", cells=[AREA])
    assert loc.pop("mode") == "local" and pub.pop("mode") == "public"
    assert pub == loc


# ---- obs_near: the local-only one --------------------------------------------------

def test_obs_near_is_local_only_and_public_refuses_it_by_name(root):
    """It returns observation ROWS by definition, and rows are what the licence withholds.
    The refusal comes FIRST -- before a missing parameter, before an unknown asset -- so
    `public` can never learn anything from the shape of a later error."""
    for params in ({}, {"lon": -73.98758, "lat": 40.75575}, {"asset_id": "bus:000000"}):
        with pytest.raises(q.QueryError) as e:
            near(root, mode="public", **params)
        assert e.value.reason == "restricted_source"
        assert e.value.detail == {"query": "obs_near", "mode": "public", "need": "local"}


def test_obs_near_returns_the_rows_inside_the_radius_ordered_by_distance(root):
    """The answer is the rows themselves, nearest first, each carrying how far it was."""
    got = near(root, asset_id=CELL_UNIT, radius_m=500)
    assert got["n_observations"] == 2 and len(got["observations"]) == 2
    assert [o["source"] for o in got["observations"]] == ["floodnet"] * 2
    assert [o["depth_mm"] for o in got["observations"]] == list(FLOODNET_DEPTHS)
    assert [round(o["distance_m"]) for o in got["observations"]] == [round(SENSOR_M)] * 2
    assert all(o["distance_m"] <= 500 for o in got["observations"])
    assert near(root, asset_id=CELL_UNIT, radius_m=100)["n_observations"] == 0
    wider = near(root, asset_id=COMPLEX, radius_m=1500)["observations"]
    assert [o["source"] for o in wider] == ["mta_alert", "mta_alert", "311"]
    assert [o["distance_m"] for o in wider] == sorted(o["distance_m"] for o in wider)


def test_obs_near_returns_the_restricted_rows_the_public_side_can_never_see(root):
    """The point of the local mode, asserted against the real values in the fixture."""
    text = json.dumps(near(root, asset_id=CELL_UNIT, radius_m=500))
    assert FLOODNET_SENSOR in text and str(FLOODNET_DEPTHS[0]) in text
    alerts = near(root, asset_id=COMPLEX, radius_m=100)["observations"]
    assert {o["source_id"] for o in alerts} >= {ALERT_SOURCE_ID}
    assert {o["text"] for o in alerts} == {ALERT_TEXT}


def test_the_distance_is_metres_on_lon_lat_data_not_a_swapped_axis(root):
    """THE trap in this query. DuckDB's `ST_Distance_Sphere` / `ST_Distance_Spheroid` read
    a point as (LATITUDE, LONGITUDE); every geometry in this project is CRS84 (lon, lat).
    Handed a stored point they return a plausible WRONG number -- 143.5 m for this pair,
    which is 248.5 m apart -- so the projection is the implementation and this test is its
    gate. The oracle is the spheroid called with the axes the RIGHT way round."""
    con = duckdb.connect()
    con.execute("LOAD spatial")
    lon, lat = (near(root, asset_id=CELL_UNIT, radius_m=500)["point"][k]
                for k in ("lon", "lat"))
    got = near(root, asset_id=CELL_UNIT, radius_m=500)["observations"][0]["distance_m"]
    oracle, swapped = con.execute(
        "SELECT min(ST_Distance_Spheroid(ST_Point(ST_Y(geometry), ST_X(geometry))::POINT_2D,"
        f"                               ST_Point({lat}, {lon})::POINT_2D)),"
        "       min(ST_Distance_Spheroid(ST_Point(ST_X(geometry), ST_Y(geometry))::POINT_2D,"
        f"                               ST_Point({lon}, {lat})::POINT_2D))"
        f" FROM read_parquet('{root}/silver/flood_obs/**/*.parquet')").fetchone()
    assert abs(got - oracle) < 1.0                 # metres, and the right axes
    assert abs(got - swapped) > 100                # and the wrong ones are this far off
    con.close()


def test_the_point_can_be_an_asset_id_through_the_same_identity_seam(root):
    """"Near this stop" needs no coordinates in the caller, and identity is resolved by the
    one function that owns it, so an unknown id is `unknown_asset` here as everywhere."""
    by_asset = near(root, asset_id=CELL_UNIT, radius_m=500)
    assert by_asset["point"]["asset_id"] == CELL_UNIT
    by_point = near(root, radius_m=500,
                    lon=by_asset["point"]["lon"], lat=by_asset["point"]["lat"])
    assert "asset_id" not in by_point["point"]
    assert by_point["observations"] == by_asset["observations"]
    with pytest.raises(q.QueryError) as e:
        near(root, asset_id="bus:000000")
    assert e.value.reason == "unknown_asset"
    with pytest.raises(q.QueryError) as e:
        near(root, lat=40.75)
    assert e.value.reason == "missing_param" and e.value.detail["param"] == "lon"


def test_a_radius_past_the_cap_is_refused_by_name_and_a_useless_one_too(root):
    """Same fuse as the area cap, same reason: a radius is an area. A radius of zero or
    less would return an empty answer that reads like `nothing happened here`."""
    with pytest.raises(q.QueryError) as e:
        near(root, asset_id=CELL_UNIT, radius_m=q.RADIUS_CAP_M + 1)
    assert e.value.reason == "area_too_large" and e.value.detail["cap_m"] == q.RADIUS_CAP_M
    for bad in (0, -100):
        with pytest.raises(q.QueryError) as e:
            near(root, asset_id=CELL_UNIT, radius_m=bad)
        assert e.value.reason == "missing_param"
    with pytest.raises(q.QueryError) as e:
        near(root, asset_id=CELL_UNIT, radius_m="near-ish")
    assert e.value.reason == "missing_param" and e.value.detail["param"] == "radius_m"
    assert near(root, asset_id=CELL_UNIT)["point"]["radius_m"] == q.RADIUS_M


def test_an_empty_table_directory_is_a_typed_refusal_and_never_takes_the_root_down(root,
                                                                                   tmp_path):
    """A table is a PART FILE, not a folder. An empty `gold/flood_exposure/` -- what a run
    that died between its `mkdir` and its `pq.write_table` leaves -- must cost this root its
    score stamp and NOTHING else: neither area query reads a score. An empty
    `silver/flood_obs/` is the same shape one table over, and there the globber's
    IOException would reach a caller as a bare traceback if the read path did not test for
    the part file."""
    bare = tmp_path / "emptied"
    shutil.copytree(root, bare)
    for f in (bare / "gold" / "flood_exposure").iterdir():
        f.unlink()
    got = where(bare, cells=[AREA])
    assert ids(got) == ids(where(root, cells=[AREA]))
    assert "score_version" not in got["versions"]
    assert near(bare, asset_id=CELL_UNIT, radius_m=500)["n_observations"] == 2

    for f in (bare / "silver" / "flood_obs").iterdir():
        f.unlink()
    with pytest.raises(q.QueryError) as e:
        near(bare, asset_id=CELL_UNIT, radius_m=500)
    assert e.value.reason == "version_unresolved"
    assert e.value.detail["table"] == "silver/flood_obs"
    assert where(bare, cells=[AREA])["n_assets"] == 7      # untouched by that table


def test_every_area_payload_is_json_able_carries_no_null_and_is_stamped(root):
    """The module's three payload conventions, over both new queries."""
    payloads = [where(root, cells=[AREA]), where(root, bbox=AREA_BBOX),
                where(root, bbox=OCEAN), near(root, asset_id=COMPLEX, radius_m=1500),
                near(root, asset_id=CELL_UNIT, radius_m=500)]
    for payload in payloads:
        assert json.loads(json.dumps(payload)) == payload
        assert None not in leaves(payload)
        assert set(payload["versions"]) == {"assets_version", "spine_version",
                                            "label_version", "score_version"}
