"""Notify ticket 11: the replay harness on fixtures. THE VOLUME NUMBERS ARE NOT ASSERTED
HERE — the deliverable is a build asset a human reads, and this file asserts that the
replay RUNS, that its output has the shape the report is rendered from, and that the six
things which would each publish a SILENTLY WRONG count are still honoured.

No network and no data root above the canaries at the bottom. The detector payloads are
real `fd.cycle` output over flood 11's own Ida fixture — the same slice `test_flood_replay`
and `test_notify_decide` use — so every claim is made against the shape the detector
actually publishes rather than a stub shaped to agree with it.

`now` is pinned on fixed epochs inside Ida, never the wall clock: quiet hours are a
local-hour rule and on the WATCH branch every message is non-urgent, so a suite that read
the real clock would pass for part of the day and not the rest.
"""
import ast
import io
import json
import tokenize
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from raincheck import flood_detect as fd
from raincheck import flood_exposure as fe
from raincheck import flood_replay as fr
from raincheck import notify_decide as nd
from raincheck import notify_replay as nr
from raincheck import notify_store as ns
from raincheck.paths import data_root

FIX = Path(__file__).parent / "fixtures" / "flood_detect_ida.json"
SRC = Path(nr.__file__).read_text()
TREE = ast.parse(SRC)


def _code(text: str) -> str:
    """The module's source with every comment and string literal removed. A name MENTIONED
    in a docstring is not a call, and this module's prose names several of the things the
    rules below forbid [TRAPS: a docstring that names the thing it forbids poisons a
    source-text grep]."""
    return "".join(tok.string for tok in tokenize.generate_tokens(io.StringIO(text).readline)
                   if tok.type not in (tokenize.COMMENT, tokenize.STRING))


CODE = _code(SRC)
UTC = timezone.utc

# Fixed epochs inside Ida. NOON is 12:00 America/New_York (outside quiet hours) and NIGHT
# is 02:00 (inside them); they are stated in UTC so the conversion is the thing under test.
NOON = datetime(2021, 9, 1, 16, tzinfo=UTC)
NIGHT = datetime(2021, 9, 2, 6, tzinfo=UTC)


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


@pytest.fixture(scope="module")
def ida() -> dict:
    f = json.loads(FIX.read_text())
    f["ws"], f["we"] = _dt(f["window_start_utc"]), _dt(f["window_end_utc"])
    f["peak"] = _dt(f["peak_hour_utc"])
    f["wet"] = {_dt(k): v for k, v in f["wet_counts"].items()}
    f["hours"] = [{"cell": c["cell"], "hour_end_utc": _dt(h), "mm_1h": mm}
                  for c in f["cells"] for h, mm in c["hourly"].items()]
    f["mx"] = {c["cell"]: c["matrix"] for c in f["cells"]}
    return f


@pytest.fixture(scope="module")
def art() -> dict:
    return fe.coefficients()


@pytest.fixture(scope="module")
def det() -> dict:
    return fd.constants()


@pytest.fixture
def p(det) -> nd.Policy:
    return nd.policy(det)


def _by_hour(rows) -> dict:
    out: dict = {}
    for r in rows:
        out.setdefault(r["hour_end_utc"], []).append(r)
    return out


def _units(ida) -> list[dict]:
    """The fixture's Units in `gold/flood_matrix`'s own shape, plus the one complex."""
    us = [dict(p) | {"flooded": False} for p in ida["points"]]
    cell = next(iter(ida["mx"]))
    for c, m in ida["mx"].items():
        us.append({"asset_id": f"cell:{c:x}", "kind": "cell", "cell": c, "complex_id": None,
                   "flooded": False}
                  | {k: m[k] for k in ("share_deep", "share_nuisance", "share_not_analyzed",
                                       "density_311_3y")})
    us.append({"asset_id": ida["complex_asset_id"], "kind": "complex",
               "complex_id": ida["complex_id"], "cell": cell, "flooded": False})
    return us


def _ev(ida) -> dict:
    return {"event_id": "2021-09-01", "day_start": ida["ws"].date(), "event_class": "pluvial",
            "n_days": 2, "window_start_utc": ida["ws"], "window_end_utc": ida["we"]}


def _subs(assets, handles=2) -> list[dict]:
    return nr.subscribers([(a, k) for a, k in assets], handles)


@pytest.fixture(scope="module")
def run(ida, art, det) -> dict:
    """One real replay of the fixture event, both branches, on a list that subscribes to
    every subscribable Unit the fixture carries. Built once — it is 46 real cycles."""
    us = _units(ida)
    rows = [(u["asset_id"], u["kind"]) for u in us if u["kind"] in ns.KINDS]
    subs = nr.subscribers(rows, 2)
    watch = nd.policy(det)
    tier = nd.policy(dict(det, cutpoints=dict(det["cutpoints"], provisional=False)))
    chains = {"all/watch": (subs, watch), "all/tier": (subs, tier)}
    got = nr.replay(_ev(ida), ida["wet"], {}, _by_hour(ida["hours"]), us, art, det,
                    art["score_version"], chains)
    return {"got": got, "subs": subs, "units": us, "chains": chains,
            "watch": watch, "tier": tier}


# ---- the fixture is not degenerate -------------------------------------------------------

def test_the_fixture_really_sends_on_the_real_decision_function(run):
    """Everything below rides on a replay that produced real Messages from real cycles. A
    fixture that sent nothing would let every count assertion pass on zeros [TRAPS]."""
    for key in ("all/watch", "all/tier"):
        t = run["got"][key]
        assert t["cycles"] > 10, key
        assert t["messages"] > 0, f"{key} sent nothing — the assertions below prove nothing"
        assert t["by_kind"], key
    assert len(run["got"]["all/watch"]["windows"]) >= 1


def test_the_replayed_units_carry_both_subscribable_kinds(run):
    assert set(run["got"]["all/watch"]["by_kind"]) <= set(ns.KINDS)
    assert {s["asset_kind"] for s in run["subs"]} == set(ns.KINDS)


# ---- the subset is READ off flood 12's asset, never re-derived ----------------------------

def test_the_subset_is_read_from_flood_twelves_asset_and_not_recounted(tmp_path):
    """The universe is COUNTED in `research/flood-12-replay.json`. Move the number there and
    this module follows it; re-deriving it here would be a second copy of a rule."""
    src = json.loads(nr.F12.read_text())
    fake = tmp_path / "f12.json"
    fake.write_text(json.dumps(dict(
        src, per_event=[{"event_id": "2099-01-01"}],
        universe=dict(src["universe"], aorc_era_events=3, replayed_with_evaluation=1,
                      walk_only=2),
        excluded=dict(src["excluded"], cycles_total=7)), default=str))
    got = nr.subset(fake)
    assert got["event_ids"] == ["2099-01-01"]
    assert got["replayed_with_evaluation"] == 1 and got["cycles_total"] == 7
    assert got["aorc_era_events"] == 3 and got["walk_only"] == 2


def test_the_shipped_subset_is_the_aorc_era_one_and_not_the_whole_universe():
    """"248 event-days" is the WHOLE 206-event union universe. The AORC-era subset is what
    flood 12 counted, and it is smaller in both directions."""
    s = nr.subset()
    assert len(s["event_ids"]) == s["replayed_with_evaluation"] == 133
    assert s["aorc_era_events"] == 195 and s["walk_only"] == 62
    assert s["cycles_total"] == 4326 and s["events_with_no_ok_cycle"] == 1
    assert s["cycles_by_walk_state"] == {"OK": 4250, "INSUFFICIENT_DATA": 76}
    assert len(set(s["event_ids"])) == len(s["event_ids"])


# ---- the branch is READ, never typed -------------------------------------------------------

def test_the_branch_this_run_exercises_is_read_from_the_artifact(det):
    """A rank-only run and a tier run are not comparable volumes, so the branch is a
    measurement of the artifact and never a constant in this file."""
    assert nd.branch(det) == nd.WATCH, "the shipped artifact still says provisional"
    assert nd.branch(dict(det, cutpoints=dict(det["cutpoints"], provisional=False))) == nd.TIER


def test_this_module_never_types_a_branch_name():
    """`watch` / `tier` appear in this module's prose and nowhere in its code."""
    lits = {n.value for n in ast.walk(TREE) if isinstance(n, ast.Constant)
            and isinstance(n.value, str)}
    code = {s for s in lits if "\n" not in s and len(s) < 40}
    assert nd.WATCH not in code and nd.TIER not in code, \
        "a branch name is a literal here; it must come from nd.branch(det)"


def test_the_counterfactual_branch_is_selected_by_the_artifacts_own_flag(det):
    """The other branch is reached by flipping `cutpoints.provisional` on a COPY and asking
    `nd.policy` again — never by handing `Policy(branch=...)` a string."""
    flipped = dict(det, cutpoints=dict(det["cutpoints"], provisional=False))
    assert nd.policy(flipped).branch != nd.policy(det).branch
    assert det["cutpoints"]["provisional"] is True, "the copy must not mutate the artifact"


# ---- the four flood-12 rules, each a silently wrong count ----------------------------------

def _calls(fn_name: str) -> list[ast.Call]:
    fn = next(n for n in ast.walk(TREE)
              if isinstance(n, ast.FunctionDef) and n.name == fn_name)
    return [n for n in ast.walk(fn) if isinstance(n, ast.Call)]


def test_every_cycle_call_passes_the_citywide_series(ida, art, det):
    """RULE 1. `fd.cycle` defaults `wet_by_hour` off the Cells it was handed, which is right
    in production and silently redefines "citywide" as "these Cells" for a replay — the
    citywide-ACTIVE gate then never arms and a real storm replays as a quiet night."""
    calls = [c for c in _calls("replay")
             if isinstance(c.func, ast.Attribute) and c.func.attr == "cycle"]
    assert calls, "replay() no longer calls fd.cycle"
    assert all(any(k.arg == "wet_by_hour" for k in c.keywords) for c in calls)


def test_defaulting_the_citywide_series_shuts_the_gate_and_sends_nothing(ida, art, det, run):
    """The same measurement from the other side: run one cycle WITHOUT the series and the
    decision goes quiet, which is what the rule exists to prevent."""
    us, subs, p = run["units"], run["subs"], run["watch"]
    hours = fr.slice_rows(_by_hour(ida["hours"]), fd.walk(ida["peak"], ida["wet"])["anchor"],
                          ida["peak"])
    with_series = fd.cycle(None, ida["peak"], hours, us, art, det, temp_c=22.0,
                           wet_by_hour=ida["wet"], table_score_version=art["score_version"])
    without = fd.cycle(None, ida["peak"], hours, us, art, det, temp_c=22.0,
                       table_score_version=art["score_version"])
    assert any(u["gate_citywide_active"] for u in with_series["units"])
    assert not any(u["gate_citywide_active"] for u in without["units"])
    assert nd.decide(with_series, None, subs, p, NOON).messages
    assert not nd.decide(without, None, subs, p, NOON).messages


def test_the_cell_hour_slice_is_a_materialised_list(ida):
    """RULE 2. `fd.cycle` iterates `cell_hours` TWICE — once for the newest stamp, again
    inside `window_features` — so a generator comes back as a Window with no Cells,
    coverage 1.0 and nothing flagged, which is indistinguishable from a quiet night."""
    rows = fr.slice_rows(_by_hour(ida["hours"]), ida["ws"], ida["peak"])
    assert isinstance(rows, list) and rows
    assert list(rows) == list(rows), "consumed once and empty the second time"


def test_a_generator_slice_would_publish_an_empty_window_that_looks_complete(ida, art, det):
    rows = fr.slice_rows(_by_hour(ida["hours"]), ida["ws"], ida["peak"])
    kw = dict(art=art, det=det, temp_c=22.0, wet_by_hour=ida["wet"],
              table_score_version=art["score_version"])
    good = fd.cycle(None, ida["peak"], rows, _units(ida), **kw)
    bad = fd.cycle(None, ida["peak"], (r for r in rows), _units(ida), **kw)
    assert good["features"]["cells"] and good["features"]["coverage"] <= 1.0
    assert not bad["features"]["cells"] and bad["features"]["coverage"] == 1.0


def test_the_null_rows_are_kept_because_a_dark_cell_is_unforced_not_holed(ida):
    """RULE 3. AORC's 168 permanently dark Cells carry NULL `mm_1h` in every hour; dropping
    them reports identical coverage with `unforced_cells` zeroed, which is the quieter lie.
    This harness reads Cell-hours through `fr.cell_rows`, whose own test pins that SQL, so
    the claim here is that this module issues NO Cell-hour read of its own. Anchored on the
    module's CODE and not its text: this docstring names `mm_1h` and
    `silver/precip_cell_hourly`, and a source-text grep would fail on the sentence
    forbidding them [TRAPS, flood 17].
    """
    assert "IS NOT NULL" not in CODE and "mm_1h" not in CODE
    assert "precip_cell_hourly" not in CODE
    reads = [c for c in _calls("inputs") if isinstance(c.func, ast.Attribute)]
    assert "cell_rows" in {c.func.attr for c in reads}


def test_the_readout_is_the_union_over_cycles_and_not_the_standing_set(run):
    """RULE 4. A tier LATCHES within a Window and the Window ROLLS once the city dries, so
    the set standing at `window_end` is the morning after — Ida's last cycle stands at zero
    flags with 264 mm behind it. Notify 08's (unit, window_id) dedupe IS that union, so the
    message count is already per (unit, Window): it must exceed what the last cycle sent."""
    t = run["got"]["all/watch"]
    assert t["messages"] >= t["peak_cycle_messages"] > 0
    assert t["cycles_with_messages"] < t["cycles"], \
        "every cycle sending means the dedupe is not deduping"


# ---- the subscriptions are the store's own shape --------------------------------------------

def test_the_synthetic_subscriptions_are_store_shaped(run):
    """A stub in the wrong shape is how a green suite hides a real defect [TRAPS]."""
    for s in run["subs"]:
        assert tuple(s) == ns.COLUMNS
        assert s["state"] == ns.STATES[0] and s["asset_kind"] in ns.KINDS
        assert s["elevated_optin"] in (0, 1)


def test_a_row_the_store_could_not_have_produced_is_refused_at_the_call(run, ida, art, det, p):
    """That refusal is the trust boundary working, not a shape to route around."""
    us = run["units"]
    cyc = fd.cycle(None, ida["peak"], ida["hours"], us, art, det, temp_c=22.0,
                   wet_by_hour=ida["wet"], table_score_version=art["score_version"])
    for bad in (dict(run["subs"][0], state=ns.STATES[1]),
                dict(run["subs"][0], asset_kind="cell")):
        with pytest.raises(ValueError, match="active"):
            nd.decide(cyc, None, [bad], p, NOON)


def test_no_list_can_hold_more_than_the_stores_per_handle_cap():
    rows = [(f"bus:{i}", "bus_stop") for i in range(ns.MAX_PER_HANDLE + 1)]
    assert nr.subscribers(rows, ns.MAX_PER_HANDLE + 1)
    with pytest.raises(ValueError, match=str(ns.MAX_PER_HANDLE)):
        nr.subscribers(rows, 1)


def test_the_cohort_sizes_are_derived_from_the_stores_own_constants():
    """Both numbers come from `notify_store`, not from a literal here: the v1 list is
    exactly the entries the deferred ingress is allowed to hold, and the two bigger lists
    are whole handles at the store's per-handle cap."""
    sizes = {name: total for name, total, *_ in nr.COHORTS}
    assert sizes["v1_list"] == ns.INGRESS_TRIGGER_ENTRIES
    assert all(t % ns.MAX_PER_HANDLE == 0 for n, t in sizes.items() if n != "v1_list")
    assert {s for *_, s in nr.COHORTS} == set(nr.SELECTORS) == set(nr.SELECTION_NOTE)


def test_the_kind_mix_follows_the_watch_cuts_own_ratio(p):
    """`watch_top_n` is 25 bus stops to 5 complexes; typing a second ratio here would be a
    copy of a constant with one home."""
    assets = {"bus_stop": [f"bus:{i}" for i in range(100)],
              "complex": [f"stn:{i}" for i in range(100)]}
    got = nr.picks(assets, 30, p)
    assert len(got) == 30
    assert sum(1 for _, k in got if k == "complex") == p.watch_top_n["complex"]
    assert sum(1 for _, k in got if k == "bus_stop") == p.watch_top_n["bus_stop"]


# ---- the same `now` reaches both calls, and both states are chained -------------------------

def test_the_same_now_goes_to_the_cycle_and_to_the_decision():
    """`fd.cycle(state, now, ...)` and `nd.decide(state, decision, subs, p, now)` are handed
    the SAME clock: a decision made against a different instant than the read it is about
    would quiet-hour the wrong messages."""
    fn = next(n for n in ast.walk(TREE)
              if isinstance(n, ast.FunctionDef) and n.name == "replay")
    cyc = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
           and isinstance(c.func, ast.Attribute) and c.func.attr == "cycle"]
    dec = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
           and isinstance(c.func, ast.Attribute) and c.func.attr == "decide"]
    assert len(cyc) == len(dec) == 1
    assert isinstance(cyc[0].args[1], ast.Name) and cyc[0].args[1].id == "now"
    assert isinstance(dec[0].args[4], ast.Name) and dec[0].args[4].id == "now"


def test_both_states_are_chained_so_the_dedupe_can_work(ida, art, det, run):
    """Each call's return is the next call's `previous`. Break the decision chain and the
    same Unit re-notifies every cycle — a rank has no latch of its own."""
    us, subs, p = run["units"], run["subs"], run["watch"]
    by_hour, chained, unchained, state = _by_hour(ida["hours"]), 0, 0, None
    prev = None
    for now in fr.hours(ida["peak"], ida["peak"] + timedelta(hours=5)):
        w = fd.walk(now, ida["wet"])
        state = fd.cycle(state, now, fr.slice_rows(by_hour, w["anchor"], now), us, art, det,
                         temp_c=22.0, wet_by_hour=ida["wet"],
                         table_score_version=art["score_version"])
        prev = nd.decide(state, prev, subs, p, now)
        chained += len(prev.messages)
        unchained += len(nd.decide(state, None, subs, p, now).messages)
    assert 0 < chained < unchained


# ---- where the numbers come from -------------------------------------------------------------

def test_the_per_cycle_counts_come_from_summary_and_carry_no_handle(run, ida, art, det, p):
    cyc = fd.cycle(None, ida["peak"], ida["hours"], run["units"], art, det, temp_c=22.0,
                   wet_by_hour=ida["wet"], table_score_version=art["score_version"])
    d = nd.decide(cyc, None, run["subs"], p, NOON)
    s = d.summary()
    assert set(s) == {"branch", "reason", "window_id", "messages", "drops", "dropped",
                      "worst_case"}
    assert nr.HANDLE.split("}")[-1] not in json.dumps(s)   # "@replay.invalid"


def test_the_fuses_victims_and_the_caps_victims_are_separate_rows(run, ida, art, det, det_p=None):
    """"this would have sent 400" and "this would have DROPPED 400" are different answers,
    and so are the two reasons for the second one."""
    cyc = fd.cycle(None, ida["peak"], ida["hours"], run["units"], art, det, temp_c=22.0,
                   wet_by_hour=ida["wet"], table_score_version=art["score_version"])
    tight = nd.policy(fd.constants(), per_cycle_fuse=1)
    d = nd.decide(cyc, None, run["subs"], tight, NOON)
    assert len(d.messages) == 1 and d.drops
    assert {x["reason"] for x in d.drops} == {nd.CYCLE_FUSE}
    assert d.summary()["dropped"] == {nd.CYCLE_FUSE: len(d.drops)}


def test_the_per_kind_split_is_the_messages_own_asset_kind(run, ida, art, det, p):
    cyc = fd.cycle(None, ida["peak"], ida["hours"], run["units"], art, det, temp_c=22.0,
                   wet_by_hour=ida["wet"], table_score_version=art["score_version"])
    d = nd.decide(cyc, None, run["subs"], p, NOON)
    t = nr.tally()
    nr.add(t, d)
    assert dict(t["by_kind"]) == {k: sum(1 for m in d.messages if m.asset_kind == k)
                                 for k in {m.asset_kind for m in d.messages}}
    assert sum(t["by_kind"].values()) == t["messages"] == len(d.messages)


def test_on_the_watch_branch_no_message_is_urgent_so_quiet_hours_reach_all_of_them(
        run, ida, art, det, p):
    """`Message.tier` is None on the watch branch, so `urgent` is False for every message
    and the quiet-hours rule — which never suppresses HIGH — suppresses everything. A storm
    that peaks at 3am sends nothing at all, and that is a volume fact, not a bug."""
    cyc = fd.cycle(None, ida["peak"], ida["hours"], run["units"], art, det, temp_c=22.0,
                   wet_by_hour=ida["wet"], table_score_version=art["score_version"])
    day = nd.decide(cyc, None, run["subs"], p, NOON)
    night = nd.decide(cyc, None, run["subs"], p, NIGHT)
    assert day.messages and all(m.tier is None for m in day.messages)
    assert not night.messages and len(night.drops) == len(day.messages)
    assert {x["reason"] for x in night.drops} == {nd.QUIET}


# ---- the two per-event expectations ------------------------------------------------------------

def test_a_cycle_that_wants_more_than_the_fuse_allows_gets_an_over_expectation_row(p):
    t = nr.tally()
    t["peak_cycle_wanted"] = p.per_cycle_fuse + 1
    t["dropped"][nd.CYCLE_FUSE] = 1
    rows = nr.over(t, 0, p.per_cycle_fuse)
    assert [r["rule"] for r in rows][:1] == [nr.OVER_FUSE]
    assert rows[0]["wanted"] == p.per_cycle_fuse + 1 and rows[0]["fuse_dropped"] == 1


def test_an_event_owing_more_than_one_message_per_subscription_is_a_rolled_window(p):
    t = nr.tally()
    t["messages"], t["drops"] = 3, 1
    t["windows"] = 2
    rows = nr.over(t, 3, p.per_cycle_fuse)
    assert [r["rule"] for r in rows] == [nr.PER_SUB]
    assert rows[0] == {"rule": nr.PER_SUB, "owed": 4, "subscriptions": 3, "windows": 2}


def test_a_run_inside_both_expectations_files_nothing(p):
    t = nr.tally()
    t["messages"], t["peak_cycle_wanted"] = 2, 2
    assert nr.over(t, 3, p.per_cycle_fuse) == []


def test_the_expectations_are_named_with_what_breaking_one_means(p):
    e = nr.expectations(p.per_cycle_fuse)
    assert set(e) == {nr.OVER_FUSE, nr.PER_SUB}
    assert all(v["rule"] and v["means"] for v in e.values())
    assert str(p.per_cycle_fuse) in e[nr.OVER_FUSE]["rule"]


def test_over_expectation_rows_reach_the_rendered_report(run, p):
    """"never silently absorbed" means the row is in the DOCUMENT, not only in the JSON."""
    d = _doc(run, over=[{"rule": nr.OVER_FUSE, "event_id": "2021-09-01", "chain": "all/tier",
                         "wanted": 41, "allowed": p.per_cycle_fuse, "fuse_dropped": 16}])
    md = nr.render(d)
    assert "2021-09-01" in md and nr.OVER_FUSE in md and "41" in md
    assert "**1 row.**" in md


def test_a_clean_run_says_so_rather_than_printing_an_empty_table(run):
    md = nr.render(_doc(run, over=[]))
    assert "No event broke either expectation" in md


# ---- the rendered report -------------------------------------------------------------------

def _doc(run, over) -> dict:
    """The smallest document `render` accepts, built from the real replay above."""
    p = run["watch"]
    cohort = {"subscriptions": len(run["subs"]), "handles": 2, "per_handle": 1,
              "selection": nr.MOST_FLOODED, "by_kind": {"bus_stop": 1, "complex": 1},
              "assets": {"bus_stop": [], "complex": []}, "worst_case": 20,
              "reachable_max_per_cycle": len(run["subs"]),
              "past_ingress_trigger": False,
              "selection_note": nr.SELECTION_NOTE[nr.MOST_FLOODED]}
    rows = [{"event_id": "2021-09-01", "day_start": "2021-09-01", "event_class": "pluvial",
             "n_days": 2,
             "chains": {k: dict(nr.finish(v),
                                over_expectation=nr.over(nr.finish(v), len(run["subs"]),
                                                         run["chains"][k][1].per_cycle_fuse))
                        for k, v in run["got"].items()}}]
    return {
        "branch": {"live": p.branch, "read_from": "notify_decide.branch(...)",
                   "selected_by": "provisional is True", "counterfactual": "the other one",
                   "why_both": "because", "watch_has_no_urgent_message": True,
                   "watch_note": "tier is None on this branch"},
        "detector_version": "0" * 40, "score_version": "1" * 40,
        "table_score_version": "1" * 40, "skew": {"model_tier": "ok"},
        "policy": nr.policy_block(p), "subset": nr.subset(),
        "span_years": 15.3, "events_replayed": 1, "partial_run": True,
        "cohorts": {"all": cohort},
        "expectations": nr.expectations(p.per_cycle_fuse),
        "volume": {k: nr.pooled(rows, k, cohort, 15.3) for k in run["got"]},
        "over_expectation": over,
        "flood_12_flag_volume": nr.f12_flag_rate(nr.subset(), {"bus_stop": 13310}, 15.3),
        "verdict": {"question": "q", "answered_by": "a",
                    "this_build_wrote_no_artifact_but_its_own": True},
        "per_event": rows,
    }


def test_the_report_names_the_branch_it_exercised(run):
    """A report that does not name its branch is unreadable — a rank-only run and a tier run
    are not comparable volumes."""
    md = nr.render(_doc(run, over=[]))
    assert f"BRANCH EXERCISED: `{run['watch'].branch}`" in md
    assert "read at replay time" in md and "never typed" in md


def test_the_report_carries_the_subsets_own_counts(run):
    md = nr.render(_doc(run, over=[]))
    s = nr.subset()
    assert f"**{s['replayed_with_evaluation']} events**" in md
    assert f"**{s['cycles_total']:,} hourly cycles**" in md
    assert s["source"] in md


def test_the_report_marks_which_chain_is_the_live_one(run):
    md = nr.render(_doc(run, over=[]))
    live = [ln for ln in md.splitlines() if "**(live)**" in ln]
    assert live and all(f"/{run['watch'].branch}`" in ln for ln in live)


def test_a_partial_run_says_the_rates_are_over_the_span_it_replayed(run):
    assert "PARTIAL RUN" in nr.render(_doc(run, over=[]))
    assert "PARTIAL RUN" not in nr.render(dict(_doc(run, over=[]), partial_run=False))


def test_pooling_sums_the_counts_and_recomputes_the_rate(run):
    cohort = {"by_kind": {"bus_stop": 10}}
    rows = [{"chains": {"k": {"cycles": 2, "windows": 1, "messages": 4, "drops": 1,
                              "by_kind": {"bus_stop": 4}, "by_tier": {"None": 4},
                              "dropped": {nd.QUIET: 1}, "silent_cycles": {},
                              "peak_cycle_messages": 3, "peak_cycle_wanted": 4,
                              "worst_case": 20, "over_expectation": []}}},
            {"chains": {"k": {"cycles": 2, "windows": 2, "messages": 6, "drops": 0,
                              "by_kind": {"bus_stop": 6}, "by_tier": {"None": 6},
                              "dropped": {}, "silent_cycles": {nd.SKEW: 1},
                              "peak_cycle_messages": 5, "peak_cycle_wanted": 5,
                              "worst_case": 20,
                              "over_expectation": [{"rule": nr.OVER_FUSE}]}}}]
    got = nr.pooled(rows, "k", cohort, 2.0)
    assert got["messages"] == 10 and got["drops"] == 1 and got["events"] == 2
    assert got["by_kind"] == {"bus_stop": 10} and got["dropped"] == {nd.QUIET: 1}
    assert got["peak_event_messages"] == 6 and got["peak_cycle_wanted"] == 5
    assert got["messages_per_subscription_per_year"] == {"bus_stop": 0.5}
    assert got["events_over_the_fuse"] == 1 and got["multi_window_events"] == 0
    assert got["events_the_fuse_clipped"] == 0
    assert got["silent_cycles"] == {nd.SKEW: 1}


def test_a_flag_is_published_beside_a_message_and_never_as_one():
    """flood 12 measured FLAGS at ELEVATED+; the watch branch sends the top N per Window.
    The two are on the same per-Unit-per-year scale in the report and are never added."""
    got = nr.f12_flag_rate(nr.subset(), {"bus_stop": 13310}, 15.33)
    assert got["bus_stop"]["units"] == 13310
    assert got["bus_stop"]["per_unit_per_year"] == pytest.approx(76165 / 13310 / 15.33)
    assert got["complex"]["units"] is None and got["complex"]["per_unit_per_year"] is None


def test_the_policy_block_is_read_off_the_policy_the_run_used(p):
    b = nr.policy_block(p)
    assert b["per_cycle_fuse"] == p.per_cycle_fuse == ns.INGRESS_TRIGGER_ENTRIES
    assert b["per_handle_event_cap"] == p.per_handle_event_cap == ns.MAX_PER_HANDLE
    assert b["watch_top_n"] == dict(p.watch_top_n) and b["fuse_equals_ingress_trigger"] is True


def test_the_span_is_the_events_own_days():
    rows = [{"day_start": datetime(2010, 8, 22).date()},
            {"day_start": datetime(2025, 12, 19).date()}]
    assert nr.span_years(rows) == pytest.approx(5599 / 365.25, rel=1e-9)


# ---- this module writes only its own asset ------------------------------------------------

def test_this_module_writes_no_artifact_but_its_own():
    """flood 11's detector artifact and flood 12's replay are READ here. Recording the
    tier verdict is Ross's and sizing the live fuse is notify 10's."""
    for n in ast.walk(TREE):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in ("write_text", "write_bytes"):
            assert isinstance(n.func.value, ast.Name) and n.func.value.id in ("out", "doc", "OUT", "DOC")
    # Anchored on the CODE: the detector artifact's path is named in this module's PROSE
    # (the report says which flag selected the branch) and a text grep would fail on it.
    assert "DETECTOR" not in CODE and "flood-11-detector" not in CODE


def test_the_two_output_paths_are_this_tickets_own():
    assert nr.OUT.name == "notify-11-replay.json" and nr.DOC.name == "notify-11-replay.md"
    assert nr.F12 == fr.OUT


# ---- real-root canaries ---------------------------------------------------------------------

def _root_or_skip(*parts):
    root = data_root()
    if not Path(str(root)).joinpath(*parts).exists():
        pytest.skip(f"no {'/'.join(parts)} under {root}")
    return root


def test_the_two_selections_are_different_lists():
    """If they agreed there would be one cohort here, not three: `top_scored` exists because
    the Units a person subscribes to are not the Units a rank puts on top."""
    root = _root_or_skip("gold", "flood_matrix")
    _root_or_skip("gold", "flood_exposure")
    from raincheck import duck
    con = duck.connect()
    a = nr.hot(con, root, "bus_stop", 50)
    b = nr.scored(con, root, "bus_stop", 50)
    assert len(a) == len(b) == 50 and len(set(a)) == 50 and len(set(b)) == 50
    assert set(a) != set(b)


def test_every_selected_asset_is_a_subscribable_unit():
    root = _root_or_skip("gold", "flood_matrix")
    from raincheck import duck
    con = duck.connect()
    for kind in ns.KINDS:
        for sel in nr.SELECTORS.values():
            got = sel(con, root, kind, 5)
            assert got and all(isinstance(a, str) for a in got)


def test_the_published_asset_matches_this_modules_own_shape():
    """The committed asset is what a human reads; a schema drift that nothing re-renders is
    exactly the rot this catches."""
    if not nr.OUT.exists():
        pytest.skip("research/notify-11-replay.json has not been built")
    d = json.loads(nr.OUT.read_text())
    assert set(d) >= {"branch", "policy", "subset", "cohorts", "expectations", "volume",
                      "over_expectation", "per_event", "flood_12_flag_volume", "span_years"}
    assert d["branch"]["live"] in nd.BRANCHES
    assert d["per_event"]
    if not d["partial_run"]:
        assert d["subset"]["replayed_with_evaluation"] == len(d["per_event"])
    assert set(d["expectations"]) == {nr.OVER_FUSE, nr.PER_SUB}
    # the domain half, not "sub" — the prose is full of "subscription" [TRAPS: a
    # substring that is a PREFIX of another value hits the wrong object].
    assert nr.HANDLE.split("}")[-1] not in nr.OUT.read_text(), "a handle reached the asset"
    for row in d["per_event"]:
        for chain in row["chains"].values():
            assert set(chain) >= {"messages", "by_kind", "by_tier", "drops", "dropped",
                                  "peak_cycle_messages", "over_expectation"}


def test_the_committed_report_names_the_branch_it_was_built_on():
    if not nr.DOC.exists():
        pytest.skip("research/notify-11-replay.md has not been built")
    md = nr.DOC.read_text()
    assert "BRANCH EXERCISED:" in md and "never typed" in md


# ---- the two sizing findings this replay exists to produce -------------------------------

def test_the_fuse_and_the_ingress_trigger_are_the_same_number(p):
    """notify 08 sized the per-cycle fuse at the store's own stated list ceiling. A Unit
    fires at most once per cycle, so a cycle owes at most one message per SUBSCRIPTION —
    which means a list inside the ceiling can never ask the fuse for more than it allows.
    The first cycle that can trip it is a cycle on a list that already reopened the
    ingress."""
    assert p.per_cycle_fuse == ns.INGRESS_TRIGGER_ENTRIES
    v1 = next(t for n, t, *_ in nr.COHORTS if n == "v1_list")
    assert v1 <= p.per_cycle_fuse


def test_a_list_inside_the_ceiling_never_wants_more_than_the_fuse_allows(run):
    """The same claim measured on the real replay rather than argued: no cycle wanted more
    than the list holds."""
    for t in run["got"].values():
        assert t["peak_cycle_wanted"] <= len(run["subs"])


def test_the_per_handle_cap_cannot_fire_on_the_watch_branch(run, ida, art, det):
    """`per_handle_event_cap` IS `ns.MAX_PER_HANDLE`, and the store refuses a handle past
    that many ACTIVE rows. On the watch branch a (unit, Window) fires ONCE, so a handle can
    receive at most as many messages per Window as it has subscriptions — and the cap
    triggers on the one after that. It is a belt-and-braces guard there, not a limiter.

    Guarded against passing on an untested mechanism: the same replay with the cap lowered
    below the subscription count DOES drop.
    """
    us, subs = run["units"], run["subs"]
    by_hour = _by_hour(ida["hours"])
    one = [dict(s, handle="one@replay.invalid", unsubscribe_token="t") for s in subs]
    assert len(one) <= ns.MAX_PER_HANDLE, "the store could not hold this list"

    def go(p_):
        got = nr.replay(_ev(ida), ida["wet"], {}, by_hour, us, art, det,
                        art["score_version"], {"one": (one, p_)})
        return got["one"]

    at_cap = go(nd.policy(det))
    lowered = go(nd.policy(det, per_handle_event_cap=1))
    assert at_cap["messages"] > 1 and nd.HANDLE_CAP not in at_cap["dropped"]
    assert lowered["dropped"].get(nd.HANDLE_CAP), "the cap never fires — this test is vacuous"


def test_the_published_worst_case_overstates_what_a_part_full_list_can_send():
    """`Decision.worst_case` is handles x MAX_PER_HANDLE — the ceiling on the STORE, not on
    the list in front of it. Sizing a live fuse off it sizes for a list that does not
    exist, so the cohort block publishes the reachable maximum beside it."""
    rows = [(f"bus:{i}", "bus_stop") for i in range(ns.INGRESS_TRIGGER_ENTRIES)]
    subs = nr.subscribers(rows, 5)
    handles = len({s["handle"] for s in subs})
    assert handles * ns.MAX_PER_HANDLE > len(subs)


def test_the_document_does_not_depend_on_dict_order(run):
    """A build renders from live dicts and `--render-only` renders from a `sort_keys=True`
    JSON. Without a sort at the render, the same numbers produce two different documents —
    the "two runs in one process pick the same arbitrary order" family [TRAPS]."""
    d = _doc(run, over=[])
    shuffled = json.loads(json.dumps(d, default=str, sort_keys=True))
    assert nr.render(d) == nr.render(shuffled)


def test_the_derived_blocks_recompute_from_the_committed_rows(run, p):
    """`over()` lives outside `finish()` so a wording or threshold fix costs a re-render and
    not another 4,326-cycle replay. Move the fuse in the policy block and the rows follow."""
    d = _doc(run, over=[])
    got = nr.derived(d)
    assert set(got["expectations"]) == {nr.OVER_FUSE, nr.PER_SUB}
    tight = nr.derived(dict(d, policy=dict(d["policy"], per_cycle_fuse=0)))
    assert len(tight["over_expectation"]) > len(got["over_expectation"])
    assert all(r["chain"] and r["event_id"] for r in tight["over_expectation"])
    assert str(0) in tight["expectations"][nr.OVER_FUSE]["rule"]


def test_more_than_one_per_subscription_names_both_of_its_causes(p):
    """On the tier branch an ELEVATED -> HIGH escalation is a SECOND message for the same
    (unit, Window), so `windows == 1` there is not a rolled Window. Measured: 2020-11-30
    owed 62 on 60 subscriptions across ONE Window. Calling that a roll would be wrong."""
    e = nr.expectations(p.per_cycle_fuse)[nr.PER_SUB]
    assert "windows" in e["means"] and "ESCALATION" in e["means"] and "ROLLED" in e["means"]
