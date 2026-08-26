"""Notify ticket 06: the four MCP tools. THESE TESTS ASSERT DISPATCH, NEVER PROTOCOL.

Nothing here starts a session, speaks JSON-RPC, or imports the MCP SDK. What is being
pinned is the thin layer that ticket owns -- which query name each tool calls, under which
argument names, in which mode, against which root, and what a `QueryError` looks like when
it comes back out. The protocol is the SDK's and is not this repo's to test; the schemas
it derives are derived from the same four signatures asserted here, so a rename cannot
pass this file and still ship a working tool.

The root is rebuilt from `tests/fixtures/notify_query_*.parquet` -- notify 02's cut,
extended by 03 and 04, and NOT a second cut. It is the only fixture in the repo that holds
real restricted rows, which is what makes the `public`/`local` assertions below mean
something.
"""
import ast
import inspect
import shutil
from pathlib import Path

import pytest

from raincheck import notify_mcp as nm, query as q

FIXTURES = Path(__file__).parent / "fixtures"
LAYOUT = {"assets": ("ref", "assets"), "events": ("silver", "flood_events"),
          "obs": ("silver", "flood_obs"), "labels": ("gold", "flood_labels"),
          "exposure": ("gold", "flood_exposure")}

COMPLEX = "stn:611"                           # a Unit for both tools
STATION = "sta:725"                           # a Carrier: history refused, score refused
ENTRANCE = "ent:409:40.722103:-73.996812"     # history YES, score NO -- on purpose
UNSCORED_CELL = "cell:882a100011fffff"        # outside F10's fit set: no `ask` key at all
CELL_HEX = "882a1072c1fffff"

SOURCE = Path(nm.__file__).read_text()
TREE = ast.parse(SOURCE)


def calls(tree=TREE) -> set:
    """Every call this module makes, as source text. ANCHOR ON THE CALL, NEVER ON THE
    TEXT: this module's docstrings name `sql`, `environ` and `port` in order to forbid
    them, and a grep reads its own prose as the violation (flood 17, notify 01)."""
    return {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}


def names(tree=TREE) -> set:
    """Every identifier and attribute path the module actually references."""
    return ({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            | {ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Attribute)})


def numbers(tree=TREE) -> set:
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
            and not isinstance(n.value, bool)}



@pytest.fixture(scope="module")
def root(tmp_path_factory):
    r = tmp_path_factory.mktemp("mcp")
    for name, parts in LAYOUT.items():
        r.joinpath(*parts).mkdir(parents=True)
        shutil.copy(FIXTURES / f"notify_query_{name}.parquet",
                    r.joinpath(*parts) / "part-00000.parquet")
    return r


@pytest.fixture
def spy(monkeypatch):
    """`query.query` replaced by a recorder: what reaches the seam IS the dispatch."""
    seen = []

    def fake(name, params=None, data_root=None, mode=q.MODES[0]):
        seen.append({"name": name, "params": dict(params or {}), "root": data_root,
                     "mode": mode})
        return {"ok": True}

    monkeypatch.setattr(nm.q, "query", fake)
    return seen


# ---- the set is four, and it is query.QUERIES ---------------------------------------

def test_the_tool_set_is_query_QUERIES_and_nothing_else():
    """Derived from the registry, so a fifth query cannot be wrapped by accident and the
    four cannot be renamed apart. THE TOOLS STAY EXACTLY FOUR."""
    assert set(nm.tools()) == set(q.QUERIES) == {
        "events_for_asset", "exposure_of", "assets_in_area", "obs_near"}
    assert set(nm.DESCRIPTIONS) == set(q.QUERIES)


def test_there_is_no_sql_passthrough_tool_and_no_room_for_one():
    """`assets_in_zone` / `obs_in_polygon` / a `sql` tool are unregistered in the seam, so
    they cannot be tools here either -- the wrapper has no name of its own to offer."""
    for absent in ("sql", "query", "assets_in_zone", "obs_in_polygon", "raw"):
        assert absent not in nm.tools()
    with pytest.raises(q.QueryError) as exc:
        q.query("sql", {}, "/nowhere", "public")
    assert exc.value.reason == "unknown_query"


def test_the_module_holds_no_query_logic_at_all():
    """Dispatch-only, pinned on the CALLS rather than on the source text -- the docstring
    NAMES SQL in order to forbid it, which is exactly what poisons a text grep (flood 17,
    notify 01). Every call this module makes must be to `q.<helper>`, the SDK, or a local.
    """
    called = calls()
    for banned in ("execute", "sql", "table", "connect", "read_parquet", "create_view",
                   "fetchall", "filter", "project"):
        assert not any(c.split(".")[-1] == banned for c in called), (banned, called)
    imported = ({n.module for n in ast.walk(TREE) if isinstance(n, ast.ImportFrom)}
                | {a.name for n in ast.walk(TREE) if isinstance(n, ast.Import)
                   for a in n.names})
    assert imported == {"sys", "importlib.util", "pathlib", "raincheck",
                        "mcp.server.mcpserver"}
    assert not {n for n in names() if n.split(".")[0] in ("duck", "duckdb", "pq", "pa")}


# ---- each tool dispatches to ITS OWN name, with the arguments it received -------------

def test_each_tool_dispatches_to_its_own_query_name(spy):
    for fn in nm.tools().values():
        fn(**{p: None for p in inspect.signature(fn).parameters})
    assert [c["name"] for c in spy] == list(nm.tools())


def test_the_bound_argument_names_are_the_query_seams_own():
    """The six names the ticket binds. They are the SDK's schema property names too --
    it derives the schema from these same signatures -- so this is the one place a
    translation layer could creep in, and it is pinned by name."""
    got = {name: tuple(inspect.signature(fn).parameters)
           for name, fn in nm.tools().items()}
    assert got == {"events_for_asset": ("asset_id",),
                   "exposure_of": ("asset_id",),
                   "assets_in_area": ("cells", "bbox"),
                   "obs_near": ("asset_id", "lon", "lat", "radius_m")}
    assert set().union(*got.values()) == {"asset_id", "cells", "bbox", "lon", "lat",
                                          "radius_m"}


def test_the_arguments_reach_the_seam_under_the_names_they_arrived_with(spy):
    t = nm.tools("/some/root")
    t["events_for_asset"](asset_id=COMPLEX)
    t["assets_in_area"](cells=[CELL_HEX], bbox=[-74.0, 40.7, -73.9, 40.8])
    t["obs_near"](lon=-73.98, lat=40.75, radius_m=250)
    assert [c["params"] for c in spy] == [
        {"asset_id": COMPLEX},
        {"cells": [CELL_HEX], "bbox": [-74.0, 40.7, -73.9, 40.8]},
        {"lon": -73.98, "lat": 40.75, "radius_m": 250}]
    assert {c["root"] for c in spy} == {"/some/root"}


def test_an_omitted_argument_is_absent_and_not_an_explicit_null(spy):
    """`pack` drops what was not given, which is what lets the SEAM apply its own
    `radius_m` default and raise its own `cells|bbox` refusal. A wrapper that forwarded
    `None` would be making those two decisions itself."""
    t = nm.tools()
    t["assets_in_area"](cells=CELL_HEX)
    t["obs_near"](asset_id=COMPLEX)
    assert spy[0]["params"] == {"cells": CELL_HEX}          # no `bbox` key at all
    assert spy[1]["params"] == {"asset_id": COMPLEX}        # no `radius_m` key at all


def test_the_radius_default_is_the_seams_and_this_layer_holds_no_copy(root):
    """RADIUS_M lives in `query` alone: omitting the argument here must produce the seam's
    own number in the payload. A mirrored 500.0 in this module would survive a mutation of
    `query.RADIUS_M`; this does not."""
    got = nm.tools(root, "local")["obs_near"](asset_id=COMPLEX)
    assert got["point"]["radius_m"] == q.RADIUS_M
    # and this layer holds no numeric copy of ANY of the seam's three bounds
    assert not numbers() & {q.RADIUS_M, q.RADIUS_CAP_M, q.CELL_CAP}


# ---- mode: public by default, local only by explicit flag ---------------------------

def test_public_is_the_default_mode(spy):
    nm.tools()["exposure_of"](asset_id=COMPLEX)
    assert spy[0]["mode"] == "public" == q.MODES[0]


def test_local_is_selected_by_the_startup_flag_and_by_nothing_else(monkeypatch):
    assert nm.mode_of([]) == q.MODES[0] == "public"
    assert nm.mode_of([nm.LOCAL]) == q.MODES[1] == "local"
    for var in ("RAINCHECK_MCP_MODE", "MCP_MODE", "MODE", "RAINCHECK_MODE"):
        monkeypatch.setenv(var, "local")
    assert nm.mode_of([]) == "public"
    assert not {n for n in names() if "environ" in n or "getenv" in n}
    assert not {c for c in calls() if c.split(".")[-1] in ("getenv", "environ", "get")}
    with pytest.raises(SystemExit):
        nm.mode_of(["--local-ish"])
    with pytest.raises(SystemExit):
        nm.mode_of([nm.LOCAL, "8080"])


def test_the_chosen_mode_is_the_mode_every_tool_dispatches_in(spy):
    for mode in q.MODES:
        nm.tools(None, mode)["events_for_asset"](asset_id=COMPLEX)
    assert [c["mode"] for c in spy] == list(q.MODES)


# ---- obs_near is local-only, and refuses FIRST --------------------------------------

def test_obs_near_refuses_in_public_before_it_reads_any_other_argument(root):
    """Called with NO arguments at all it must still be `restricted_source`, not
    `missing_param` -- which is the ordering, measured rather than read. A hosted server
    that never sets the flag therefore learns nothing from the shape of a later error."""
    got = nm.tools(root)["obs_near"]()
    assert got["error"]["reason"] == "restricted_source"
    assert got["error"]["detail"]["need"] == "local" == q.MODES[1]
    assert "observations" not in got


def test_obs_near_answers_in_local_nearest_first(root):
    got = nm.tools(root, "local")["obs_near"](lon=-73.9866, lat=40.7561, radius_m=2000)
    assert got["query"] == "obs_near" and got["mode"] == "local"
    assert got["n_observations"] == len(got["observations"]) > 0
    d = [o["distance_m"] for o in got["observations"]]
    assert d == sorted(d)


def test_the_other_three_tools_answer_identically_in_both_modes(root):
    for name, kw in (("exposure_of", {"asset_id": COMPLEX}),
                     ("assets_in_area", {"cells": CELL_HEX})):
        assert nm.tools(root)[name](**kw) | {"mode": None} == \
               nm.tools(root, "local")[name](**kw) | {"mode": None}


# ---- typed refusals reach the caller by name, never as a traceback -------------------

def test_a_refusal_carries_the_reason_and_the_detail_and_no_traceback(root):
    got = nm.tools(root)["events_for_asset"](asset_id="bus:nope")
    assert got == {"query": "events_for_asset", "mode": "public",
                   "error": {"reason": "unknown_asset",
                             "detail": {"asset_id": "bus:nope"}}}
    assert got["error"]["reason"] in q.REASONS


def test_every_reason_this_layer_can_return_is_one_of_the_frozen_eight(root):
    """No ninth name is owed and none is invented: the wrapper raises nothing of its own,
    so its whole error vocabulary is `query.REASONS`."""
    assert len(q.REASONS) == 8
    t, seen = nm.tools(root), set()
    for got in (t["events_for_asset"](asset_id="bus:nope"),
                t["exposure_of"](asset_id=STATION),
                t["assets_in_area"](),
                t["assets_in_area"](cells=["not-a-hex-!"]),
                t["assets_in_area"](cells=[f"882a1072{i:07x}" for i in range(
                    q.CELL_CAP + 1)]),
                t["obs_near"]()):
        seen.add(got["error"]["reason"])
    assert seen == {"unknown_asset", "not_a_scored_unit", "missing_param",
                    "area_too_large", "restricted_source"}
    assert seen <= set(q.REASONS)


def test_only_QueryError_is_caught_and_anything_else_is_a_real_failure(monkeypatch):
    """`except Exception` here would turn a genuine defect -- a dead table, a bad root --
    into something that reads like a typed refusal."""
    def boom(*_a, **_kw):
        raise ValueError("a real defect")
    monkeypatch.setattr(nm.q, "query", boom)
    with pytest.raises(ValueError, match="a real defect"):
        nm.tools()["exposure_of"](asset_id=COMPLEX)


def test_a_detail_carrying_query_or_mode_cannot_shadow_the_envelope(root):
    """`restricted_source`'s detail holds `query` AND `mode` of its own. Splatting it at
    the top level would overwrite the envelope's; nesting it under `detail` cannot."""
    got = nm.tools(root)["obs_near"](asset_id=COMPLEX)
    assert got["query"] == "obs_near" and got["mode"] == "public"
    assert got["error"]["detail"]["query"] == "obs_near"
    assert got["error"]["detail"]["mode"] == "public"


def test_the_two_asset_tools_disagree_about_entrances_and_both_are_right(root):
    """History YES, score NO -- and the score refusal names the complex to ask. This is
    the pair a description has to explain or an agent reads the refusal as a bug."""
    t = nm.tools(root)
    history = t["events_for_asset"](asset_id=ENTRANCE)
    assert "error" not in history and history["n_events"] > 0
    score = t["exposure_of"](asset_id=ENTRANCE)
    assert score["error"]["reason"] == "not_a_scored_unit"
    assert score["error"]["detail"]["ask"].startswith("stn:")
    # a ref Cell outside F10's fit set has NO parent, so `ask` is ABSENT, never null
    unscored = t["exposure_of"](asset_id=UNSCORED_CELL)
    assert unscored["error"]["reason"] == "not_a_scored_unit"
    assert "ask" not in unscored["error"]["detail"]


# ---- the descriptions are the agent's whole vocabulary, so they are pinned -----------

def test_the_named_stamps_are_the_stamps_the_seam_returns(root, tmp_path):
    """Derived, not mirrored: STAMPS is compared against `versions()` on a root that HAS
    scores, and `score_version` is proved to drop on one that does not -- which is the
    'legitimately absent' claim the descriptions make, measured."""
    from raincheck import duck
    con = duck.connect()
    assert tuple(q.versions(con, root)) == nm.STAMPS
    bare = tmp_path / "noscores"
    for name, parts in LAYOUT.items():
        if parts == ("gold", "flood_exposure"):
            continue
        bare.joinpath(*parts).mkdir(parents=True)
        shutil.copy(FIXTURES / f"notify_query_{name}.parquet",
                    bare.joinpath(*parts) / "part-00000.parquet")
    assert tuple(q.versions(duck.connect(), bare)) == nm.STAMPS[:-1]
    assert "score_version" not in q.versions(duck.connect(), bare)


def test_every_description_names_the_version_stamps_it_returns():
    for name, text in nm.DESCRIPTIONS.items():
        for stamp in nm.STAMPS:
            assert stamp in text, (name, stamp)
        assert "ABSENT" in text.split("under `versions`")[-1]


def test_every_description_names_tables_and_only_real_ones():
    """The table vocabulary is DERIVED from `query.py`'s own `view()` calls, so a table
    added to the seam and left out of the descriptions goes red. NAMED LIMIT: this checks
    the UNION over the four descriptions, not the per-tool attribution -- a table named on
    the wrong tool would pass here and is caught by review, not by this test."""
    seam = ast.parse(Path(q.__file__).read_text())
    # module-level string tuples, so a `view(con, root, *EXPOSURE, ...)` resolves too --
    # `gold/flood_exposure` is spelled that way and a literals-only walk misses it
    const = {t.id: [e.value for e in n.value.elts]
             for n in seam.body if isinstance(n, ast.Assign)
             for t in n.targets if isinstance(t, ast.Name)
             if isinstance(n.value, ast.Tuple)
             and all(isinstance(e, ast.Constant) and isinstance(e.value, str)
                     for e in n.value.elts)}

    def parts(arg):
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return [arg.value]
        if isinstance(arg, ast.Starred) and isinstance(arg.value, ast.Name):
            return const.get(arg.value.id, [])
        return []

    tables = {"/".join(p for a in n.args[2:] for p in parts(a))
              for n in ast.walk(seam)
              if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "view"}
    tables = {t for t in tables if "/" in t}
    assert tables == {"ref/assets", "gold/flood_labels", "silver/flood_events",
                      "silver/flood_obs", "gold/flood_exposure"}
    named = {t for t in tables for text in nm.DESCRIPTIONS.values() if t in text}
    assert named == tables, tables - named
    for name, text in nm.DESCRIPTIONS.items():
        mine = {t for t in tables if t in text}
        assert mine, name
        assert not {t for t in mine if t not in tables}


def test_the_exposure_description_describes_the_numbers_honestly():
    """The four traps a wrong sentence sets, each pinned as a positive claim rather than
    as a grep for the wrong word."""
    text = nm.DESCRIPTIONS["exposure_of"]
    assert "RANK WITHIN THIS ASSET'S KIND" in text and "(0, 1]" in text
    assert "LINEAR PREDICTOR" in text and "NOT probabilities" in text
    assert "NEGATIVE for nearly every Unit" in text
    assert "`modelled: false`" in text and "KIND'S MEDIAN" in text
    assert "ABSENT -- never 0.0" in text and "AT the doorway" in text
    assert "NO `ask` KEY AT ALL" in text
    assert "`mode` does not change this answer" in text


def test_the_flag_vocabulary_is_pointed_at_and_not_re_worded():
    """The description names the artifact instead of paraphrasing F10's flag sentences,
    and the artifact really carries them -- a dangling pointer is the defect this catches.
    """
    import json
    pointer = "research/flood-10-coefficients.json"
    assert pointer in nm.DESCRIPTIONS["exposure_of"]
    published = json.loads((Path(q.__file__).parents[2] / pointer).read_text())["flags"]
    assert q.FALLBACK_FLAG in published
    for meaning in published.values():
        assert meaning not in nm.DESCRIPTIONS["exposure_of"]


def test_no_description_makes_a_complex_grain_skill_claim():
    """The complex number is an aggregate of doorway scores and the independent
    complex-grain set caught 1 of 118, so the descriptions state the CONSTRUCTION (a max
    over children) and claim nothing about how well it performs."""
    for text in nm.DESCRIPTIONS.values():
        low = text.lower()
        for claim in ("accurate", "reliable", "skill", "validated", "precision",
                      "recall", "well-calibrated", "trustworthy"):
            assert claim not in low, (claim, text[:60])


def test_the_caps_and_the_default_come_from_the_seams_constants():
    """Derived into the source, not typed beside it: mutate `query.CELL_CAP` and the
    description moves with it, which is the only way a number in prose stays true."""
    src = Path(nm.__file__).read_text()
    assert "{q.CELL_CAP}" in src and "{q.RADIUS_M:.0f}" in src
    assert "{q.RADIUS_CAP_M:.0f}" in src
    area, near = nm.DESCRIPTIONS["assets_in_area"], nm.DESCRIPTIONS["obs_near"]
    assert f"bounded at {q.CELL_CAP} Cells" in area
    assert f"default\n{q.RADIUS_M:.0f} m, capped at {q.RADIUS_CAP_M:.0f} m" in near


def test_obs_near_says_local_only_means_refused_and_not_thinner():
    text = nm.DESCRIPTIONS["obs_near"]
    assert "LOCAL ONLY, AND THAT MEANS REFUSED, NOT THINNER." in text
    assert "`restricted_source` BEFORE it reads any other argument" in text
    assert nm.LOCAL in text and "hosted server that never sets it" in text
    assert "NOT F05's ATTACHMENT" in text


def test_the_instructions_say_there_is_no_sql_tool_and_name_the_eight_reasons():
    assert "THERE IS NO SQL TOOL AND THERE WILL NOT BE ONE." in nm.INSTRUCTIONS
    for reason in q.REASONS:
        assert reason in nm.INSTRUCTIONS
    assert "HEX STRING" in nm.INSTRUCTIONS and "2^53" in nm.INSTRUCTIONS
    assert "DISAGREE ABOUT ENTRANCES ON PURPOSE" in nm.INSTRUCTIONS


def test_the_size_warning_is_on_the_tool_that_earns_it():
    assert "2 MB" in nm.DESCRIPTIONS["events_for_asset"]
    assert "1 KB" in nm.DESCRIPTIONS["events_for_asset"]
    assert "2 MB" not in nm.DESCRIPTIONS["exposure_of"]


# ---- the SDK seam, without importing the SDK ----------------------------------------

def test_the_sdk_is_imported_inside_server_and_nowhere_else():
    """A tree with no MCP SDK still imports this module and still runs every test above --
    which is why the suite gains no skip family from this ticket."""
    tree = ast.parse(Path(nm.__file__).read_text())
    top = {n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert not any("mcp" in ast.unparse(n) for n in top)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "server")
    assert [ast.unparse(n) for n in ast.walk(fn) if isinstance(n, ast.ImportFrom)] == \
        ["from mcp.server.mcpserver import MCPServer"]


def test_serving_without_the_sdk_says_so_instead_of_raising_ImportError(monkeypatch):
    monkeypatch.setattr(nm, "available", lambda: False)
    with pytest.raises(SystemExit, match="MCP SDK is not installed"):
        nm.server()


def test_nothing_in_this_ticket_opens_a_port():
    """stdio, and it is the DEFAULT rather than a spelled-out argument -- `run()` with no
    transport is stdio, and any of `sse` / `streamable-http` would be a listening socket.
    Anchored on the call and on the imports, because the docstring says the word."""
    imported = ({n.module for n in ast.walk(TREE) if isinstance(n, ast.ImportFrom)}
                | {a.name for n in ast.walk(TREE) if isinstance(n, ast.Import)
                   for a in n.names})
    assert not {m for m in imported if m.split(".")[0] in
                ("socket", "socketserver", "http", "asyncio", "uvicorn", "starlette")}
    run = [n for n in ast.walk(TREE) if isinstance(n, ast.Call)
           and ast.unparse(n.func).endswith(".run")]
    assert len(run) == 1 and not run[0].args and not run[0].keywords
    assert not {c for c in calls()
                if c.split(".")[-1] in ("run_sse_async", "run_streamable_http_async",
                                        "sse_app", "streamable_http_app")}
