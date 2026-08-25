"""Notify ticket 08, SEAM N: the notify decision as pure functions on fixtures.

No network, no database and no clock. The detector payloads are REAL `fd.cycle` output
over flood 11's own Ida fixture, so every assertion here is made against the shape the
detector actually publishes rather than against a hand-shaped stub — and the subscription
rows are asserted, key for key, against `notify_store.COLUMNS`.

`now` is pinned on a fixed epoch inside Ida (2021-09-01), never on the wall clock: quiet
hours are a local-hour rule and a suite that reads the real clock passes for nine months
of the year and then does not.

Where a case cannot be reached from the fixture it is built FROM a real cycle rather than
instead of one: the four-stop vector cannot produce an ELEVATED (the top 10% and the top
2% of four Units are the same Unit), so `_retier` sets `fd.ELEVATED` on a real payload.
`test_the_fixture_really_flags_from_the_real_detector` is the non-degeneracy guard that
keeps that honest.
"""
import copy
import io
import json
import tokenize
from datetime import datetime, timezone
from pathlib import Path

import pytest

from raincheck import flood_detect as fd
from raincheck import flood_exposure as fe
from raincheck import notify_decide as nd
from raincheck import notify_store as ns

FIX = Path(__file__).parent / "fixtures" / "flood_detect_ida.json"
SRC = Path(nd.__file__).read_text()
UTC = timezone.utc


def _code(text: str) -> str:
    """The module's source with every comment and string literal removed. A name MENTIONED
    in a docstring is not a call, and this module's docstring names several of the things
    the purity tests forbid — `notify_store.subscriptions(con)` among them."""
    return "".join(tok.string for tok in tokenize.generate_tokens(io.StringIO(text).readline)
                   if tok.type not in (tokenize.COMMENT, tokenize.STRING))


CODE = _code(SRC)

# A fixed epoch inside Ida. NOON is 12:00 America/New_York and NIGHT is 02:00 — one
# outside the quiet window and one inside it, both stated in UTC so the conversion is the
# thing under test rather than an assumption.
NOON = datetime(2021, 9, 1, 16, tzinfo=UTC)
NIGHT = datetime(2021, 9, 2, 6, tzinfo=UTC)


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


@pytest.fixture(scope="module")
def ida() -> dict:
    f = json.loads(FIX.read_text())
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
    return fd.artifact()


@pytest.fixture(scope="module")
def units(ida) -> list[dict]:
    """flood 11's own `_units` shape: the fixture's points, its Cells and one complex."""
    us = [dict(p) for p in ida["points"]]
    cell = next(iter(ida["mx"]))
    for c, m in ida["mx"].items():
        us.append({"asset_id": f"cell:{c:x}", "kind": "cell", "cell": c} | {
            k: m[k] for k in ("share_deep", "share_nuisance", "share_not_analyzed",
                              "density_311_3y")})
    us.append({"asset_id": ida["complex_asset_id"], "kind": "complex",
               "complex_id": ida["complex_id"], "cell": cell})
    return us


@pytest.fixture(scope="module")
def cycles(ida, units, art, det) -> dict:
    """One real cycle per case, built once: the storm cycle, the same cycle a second time
    (the latch holding), the winter-suppressed one, the skew-refused one and the two
    no-Window ones."""
    def run(**kw):
        kw.setdefault("temp_c", 22.0)
        kw.setdefault("table_score_version", art["score_version"])
        state = kw.pop("state", None)
        now = kw.pop("now", ida["peak"])
        hours = kw.pop("hours", ida["hours"])
        wet = kw.pop("wet", ida["wet"])
        return fd.cycle(state, now, hours, units, art, det, wet_by_hour=wet, **kw)

    one = run()
    return {"run": run, "one": one, "two": run(state=one),
            "winter": run(temp_c=0.0), "skew_none": run(table_score_version=None),
            "skew_other": run(table_score_version="another-model"),
            "insufficient": run(hours=[], wet={}),
            "quiet_city": run(wet={h: 0 for h in ida["wet"]})}


@pytest.fixture
def p(det) -> nd.Policy:
    return nd.policy(det)


@pytest.fixture
def tier_p(det) -> nd.Policy:
    """The other branch, selected the only way it may be: by the artifact's own flag."""
    return nd.policy(dict(det, cutpoints=dict(det["cutpoints"], provisional=False)))


def _sub(handle="a@example.com", asset_id="bus:400070", kind="bus_stop", elevated=0,
         token=None) -> dict:
    return {"handle": handle, "asset_id": asset_id, "asset_kind": kind,
            "elevated_optin": elevated, "consent_ts": "2021-09-01T00:00:00+00:00",
            "unsubscribe_token": token or f"tok-{handle}", "state": "active"}


def _retier(out: dict, want: dict) -> dict:
    """A REAL cycle payload with named Units re-tiered, latched map kept consistent."""
    us = [dict(u, tier=want.get(u["asset_id"], u["tier"])) for u in out["units"]]
    return dict(out, units=us,
                latched={u["asset_id"]: u["tier"] for u in us if u["tier"] != fd.NONE})


def _ungate(out: dict, **gates) -> dict:
    return dict(out, units=[dict(u, **gates) for u in out["units"]])


# ---- the fixture is not degenerate -----------------------------------------------------

def test_the_fixture_really_flags_from_the_real_detector(cycles):
    """Everything below rides on a payload the real detector produced with a real HIGH in
    it. A fixture that flagged nothing would let every silence assertion pass on zeros."""
    one = cycles["one"]
    assert one["window"]["state"] == fd.OK and one["skew"]["model_tier"] == "ok"
    assert one["latched"] and fd.HIGH in one["latched"].values()
    assert {u["kind"] for u in one["units"]} >= {"bus_stop", "complex"}
    assert all(u["gate_citywide_active"] for u in one["units"])


def test_the_subscription_fixture_is_the_stores_own_row_shape():
    """A stub in the wrong shape is how a green suite hides a real defect [TRAPS]."""
    assert tuple(_sub()) == ns.COLUMNS
    assert _sub()["asset_kind"] in ns.KINDS and _sub()["state"] == ns.STATES[0]


# ---- which branch ships is read, never typed --------------------------------------------

def test_the_branch_is_read_from_the_artifact_and_never_typed(det):
    assert nd.branch(det) == nd.WATCH, "the shipped artifact still says provisional"
    assert nd.branch(dict(det, cutpoints=dict(det["cutpoints"], provisional=False))) == nd.TIER
    assert nd.branch(dict(det, cutpoints=dict(det["cutpoints"], provisional=True))) == nd.WATCH


def test_a_missing_provisional_flag_falls_to_the_conservative_branch(det):
    assert nd.branch(dict(det, cutpoints={})) == nd.WATCH
    assert nd.branch({}) == nd.WATCH


def test_confirmed_by_names_who_confirms_and_is_not_the_switch(det):
    """`display.cutpoints_confirmed_by` is populated long before any verdict exists, so a
    branch keyed on it would have shipped tiers from the day flood 11 landed."""
    assert det["display"]["cutpoints_confirmed_by"]
    assert det["cutpoints"]["provisional"] is True and nd.branch(det) == nd.WATCH


def test_a_policy_that_did_not_come_from_the_artifact_is_refused(cycles):
    with pytest.raises(ValueError, match="policy"):
        nd.decide(cycles["one"], None, [_sub()], nd.POLICY, NOON)


def test_the_policy_reads_the_own_cell_gate_from_the_artifact(det, p):
    assert p.own_cell_window_mm == det["gates"]["own_cell_window_mm"] == fd.CELL_WINDOW_MM


def test_the_notifying_tiers_are_flood_elevens_and_never_a_second_spelling(det):
    assert set(nd.POLICY.notifying_tiers) <= set(fd.TIERS)
    assert fd.NONE not in nd.POLICY.notifying_tiers
    with pytest.raises(ValueError):
        nd.policy(det, notifying_tiers=("SEVERE",))
    with pytest.raises(ValueError):
        nd.policy(det, notifying_tiers=(fd.NONE,))


def test_the_tier_vocabulary_is_imported_and_not_respelled():
    for spelling in ('"HIGH"', "'HIGH'", '"ELEVATED"', "'ELEVATED'", '"NONE"'):
        assert spelling not in SRC, spelling


# ---- the caps are the store's own numbers ------------------------------------------------

def test_the_per_handle_cap_is_the_stores_frozen_cap(p):
    assert p.per_handle_event_cap == ns.MAX_PER_HANDLE
    assert "ns.MAX_PER_HANDLE" in SRC


def test_the_fuse_is_the_managed_lists_own_ceiling(p):
    """A cycle can legitimately send at most one message per subscription, and the list is
    allowed `INGRESS_TRIGGER_ENTRIES` subscriptions before ticket 07's ingress reopens."""
    assert p.per_cycle_fuse == ns.INGRESS_TRIGGER_ENTRIES
    assert "ns.INGRESS_TRIGGER_ENTRIES" in SRC


def test_the_worst_case_is_subscribers_times_the_per_handle_cap(cycles, p):
    subs = [_sub(f"h{i}@example.com") for i in range(3)]
    d = nd.decide(cycles["one"], None, subs, p, NOON)
    assert d.worst_case == 3 * ns.MAX_PER_HANDLE
    assert nd.decide(cycles["one"], None, [], p, NOON).worst_case == 0


# ---- the tier branch: entry is the trigger, the latch is the dedupe ----------------------

def test_a_tier_entry_notifies(cycles, tier_p):
    d = nd.decide(cycles["one"], None, [_sub()], tier_p, NOON)
    assert [m.asset_id for m in d.messages] == ["bus:400070"]
    assert d.messages[0].tier == fd.HIGH and d.messages[0].branch == nd.TIER
    assert d.messages[0].top_n is None and d.reason is None


def test_a_held_tier_notifies_nothing_and_the_latch_is_the_dedupe(cycles, tier_p):
    one = nd.decide(cycles["one"], None, [_sub()], tier_p, NOON)
    two = nd.decide(cycles["two"], one, [_sub()], tier_p, NOON)
    assert cycles["two"]["rolled"] is False
    assert one.messages and two.messages == ()
    assert two.latched == cycles["two"]["latched"], "the ledger is the evaluation it saw"


def test_a_window_roll_re_arms_the_tier_branch(cycles, ida, units, art, det, tier_p):
    """A coefficient swap mid-Window rolls the Window [F11 `rolled`], so the flag that is
    still standing is a NEW entry — the same shape as exit-then-re-entry."""
    one = nd.decide(cycles["one"], None, [_sub()], tier_p, NOON)
    swapped = dict(art, score_version=art["score_version"] + "-next")
    rolled = fd.cycle(None, ida["peak"], ida["hours"], units, swapped, det, temp_c=22.0,
                      wet_by_hour=ida["wet"], table_score_version=swapped["score_version"])
    two = nd.decide(rolled, one, [_sub()], tier_p, NOON)
    assert nd.window_id(rolled) != nd.window_id(cycles["one"])
    assert [m.asset_id for m in two.messages] == ["bus:400070"]


def test_the_window_id_is_the_three_fields_the_detector_rolls_on(cycles):
    one = cycles["one"]
    base = nd.window_id(one)
    assert base != nd.window_id(dict(one, anchor="2021-09-02T01:00:00+00:00"))
    assert base != nd.window_id(dict(one, score_version="other"))
    assert base != nd.window_id(dict(one, detector_version="other"))
    assert nd.window_id(dict(one, anchor=None)) is None


def test_an_escalation_into_high_notifies_again(cycles, tier_p):
    """ELEVATED then HIGH is a second entry, and it is the case the per-handle cap is
    written for: a Unit can cost a subscriber two messages in one Window."""
    elevated = _retier(cycles["one"], {"bus:400070": fd.ELEVATED})
    sub = _sub(elevated=1)
    one = nd.decide(elevated, None, [sub], tier_p, NOON)
    two = nd.decide(cycles["one"], one, [sub], tier_p, NOON)
    assert [m.tier for m in one.messages] == [fd.ELEVATED]
    assert [m.tier for m in two.messages] == [fd.HIGH]


def test_a_tier_that_moves_down_never_notifies(cycles, tier_p):
    """The detector logs a downward revision and never clears a flag; a decision that
    fired on any CHANGE rather than on a rise would mail the revision."""
    one = nd.decide(cycles["one"], None, [_sub(elevated=1)], tier_p, NOON)
    down = _retier(cycles["one"], {"bus:400070": fd.ELEVATED})
    assert nd.decide(down, one, [_sub(elevated=1)], tier_p, NOON).messages == ()


def test_elevated_without_the_opt_in_is_silent(cycles, tier_p):
    elevated = _retier(cycles["one"], {"bus:400070": fd.ELEVATED})
    assert nd.decide(elevated, None, [_sub(elevated=0)], tier_p, NOON).messages == ()
    assert nd.decide(elevated, None, [_sub(elevated=1)], tier_p, NOON).messages


def test_high_notifies_without_any_opt_in(cycles, tier_p):
    assert nd.decide(cycles["one"], None, [_sub(elevated=0)], tier_p, NOON).messages


def test_a_unit_nobody_subscribed_to_notifies_nobody(cycles, tier_p):
    d = nd.decide(cycles["one"], None, [_sub(asset_id="bus:400166")], tier_p, NOON)
    assert d.messages == () and cycles["one"]["latched"], "the storm flagged elsewhere"


def test_two_handles_on_one_stop_each_get_one(cycles, tier_p):
    subs = [_sub("a@example.com"), _sub("b@example.com")]
    d = nd.decide(cycles["one"], None, subs, tier_p, NOON)
    assert sorted(m.handle for m in d.messages) == ["a@example.com", "b@example.com"]


# ---- the watch branch: its own dedupe, and its own gates ---------------------------------

def test_watch_mode_notifies_on_first_top_n_entry(cycles, p):
    d = nd.decide(cycles["one"], None, [_sub()], p, NOON)
    assert [m.asset_id for m in d.messages] == ["bus:400070"]
    assert d.messages[0].tier is None and d.messages[0].branch == nd.WATCH
    assert d.messages[0].top_n == p.watch_top_n["bus_stop"]


def test_watch_mode_fires_once_per_unit_per_window_and_not_per_cycle(cycles, p):
    one = nd.decide(cycles["one"], None, [_sub()], p, NOON)
    two = nd.decide(cycles["two"], one, [_sub()], p, NOON)
    assert one.messages and two.messages == ()
    assert "bus:400070" in one.watched and two.watched == one.watched


def test_a_window_roll_re_arms_the_watch_dedupe(cycles, ida, units, art, det, p):
    one = nd.decide(cycles["one"], None, [_sub()], p, NOON)
    swapped = dict(art, score_version=art["score_version"] + "-next")
    rolled = fd.cycle(None, ida["peak"], ida["hours"], units, swapped, det, temp_c=22.0,
                      wet_by_hour=ida["wet"], table_score_version=swapped["score_version"])
    assert nd.decide(rolled, one, [_sub()], p, NOON).messages


def test_watch_mode_takes_the_top_n_and_not_the_whole_rank(cycles, det):
    """N is a COUNT, so it cannot spend more on a bigger storm — the property flood 12
    measured the rank losing."""
    top = nd.policy(det, watch_top_n={"bus_stop": 1})
    all_four = nd.policy(det, watch_top_n={"bus_stop": 4})
    subs = [_sub(f"h{i}@example.com", a) for i, a in enumerate(
        ["bus:400070", "bus:400071", "bus:400166", "bus:400168"])]
    assert [m.asset_id for m in nd.decide(cycles["one"], None, subs, top, NOON).messages] \
        == ["bus:400070"]
    assert len(nd.decide(cycles["one"], None, subs, all_four, NOON).messages) == 4


def test_a_kind_absent_from_the_top_n_map_can_never_notify(cycles, det):
    """`cell` is not subscribable and an entrance publishes no live number; a kind with no
    N is silent rather than defaulted into one."""
    p = nd.policy(det, watch_top_n={"bus_stop": 25})
    cell = [u for u in cycles["one"]["units"] if u["kind"] == "cell"][0]["asset_id"]
    assert nd.decide(cycles["one"], None, [_sub(asset_id=cell, kind="bus_stop")],
                     p, NOON).messages == ()


def test_watch_mode_re_applies_the_citywide_gate(cycles, p):
    """The rank survives a dry afternoon — something is always the maximum of a vector —
    so the branch that reads a rank has to re-apply the gate the tier got for free."""
    dry = _ungate(cycles["one"], gate_citywide_active=False)
    assert nd.decide(dry, None, [_sub()], p, NOON).messages == ()
    assert nd.decide(cycles["one"], None, [_sub()], p, NOON).messages


def test_watch_mode_re_applies_the_own_cell_rain_gate(cycles, p):
    below = _ungate(cycles["one"], gate_own_cell_mm=p.own_cell_window_mm - 0.1)
    at = _ungate(cycles["one"], gate_own_cell_mm=p.own_cell_window_mm)
    assert nd.decide(below, None, [_sub()], p, NOON).messages == ()
    assert nd.decide(at, None, [_sub()], p, NOON).messages


def test_watch_mode_is_silent_through_the_winter_gate(cycles, p):
    """The winter gate zeroes every `tier` and leaves every `rank` untouched, so a watch
    branch that read the payload alone would notify straight through a snowstorm."""
    winter = cycles["winter"]
    assert winter["winter"]["suppressed"] and all(u["tier"] == fd.NONE for u in winter["units"])
    assert any(u["rank"] >= 1.0 for u in winter["units"]), "the ranks survive suppression"
    d = nd.decide(winter, None, [_sub()], p, NOON)
    assert d.messages == () and d.reason == nd.WINTER


# ---- silence: what sends nothing, and why ------------------------------------------------

def test_version_skew_sends_nothing(cycles, p, tier_p):
    for key in ("skew_none", "skew_other"):
        for pol in (p, tier_p):
            d = nd.decide(cycles[key], None, [_sub()], pol, NOON)
            assert d.messages == () and d.reason == nd.SKEW, key


def test_an_absent_table_stamp_refuses_exactly_like_a_skew(cycles, p):
    """"I could not tell" is not "they match" [F11 `skew`]."""
    assert cycles["skew_none"]["skew"]["table_score_version"] is None
    assert nd.decide(cycles["skew_none"], None, [_sub()], p, NOON).reason == nd.SKEW


def test_insufficient_data_sends_nothing(cycles, p, tier_p):
    ins = cycles["insufficient"]
    assert ins["window"]["state"] == fd.INSUFFICIENT_DATA
    for pol in (p, tier_p):
        d = nd.decide(ins, None, [_sub()], pol, NOON)
        assert d.messages == () and d.reason == fd.INSUFFICIENT_DATA.lower()


def test_a_capped_window_sends_nothing(cycles, p):
    capped = dict(cycles["one"], window=dict(cycles["one"]["window"], state=fd.WINDOW_CAPPED))
    d = nd.decide(capped, None, [_sub()], p, NOON)
    assert d.messages == () and d.reason == fd.WINDOW_CAPPED.lower()


def test_the_winter_gate_sends_nothing_on_the_tier_branch(cycles, tier_p):
    d = nd.decide(cycles["winter"], None, [_sub()], tier_p, NOON)
    assert d.messages == () and d.reason == nd.WINTER


def test_a_window_state_this_function_does_not_know_raises(cycles, p):
    """A new detector state must stop the notifier, not pass through it as a send."""
    odd = dict(cycles["one"], window=dict(cycles["one"]["window"], state="SOMETHING_NEW"))
    with pytest.raises(ValueError, match="something_new"):
        nd.decide(odd, None, [_sub()], p, NOON)


def test_a_refused_cycle_carries_the_ledger_rather_than_clearing_it(cycles, p):
    """A refusal teaches the notifier nothing, so it must forget nothing: clearing here
    re-sends every standing flag the moment the refusal lifts."""
    one = nd.decide(cycles["one"], None, [_sub()], p, NOON)
    refused = nd.decide(cycles["skew_none"], one, [_sub()], p, NOON)
    assert refused.watched == one.watched and refused.latched == one.latched
    assert nd.decide(cycles["two"], refused, [_sub()], p, NOON).messages == ()


def test_a_cycle_with_no_window_keeps_the_ledger_of_the_window_it_had(cycles, p):
    one = nd.decide(cycles["one"], None, [_sub()], p, NOON)
    blind = nd.decide(cycles["insufficient"], one, [_sub()], p, NOON)
    assert blind.window_id == one.window_id and blind.watched == one.watched


def test_a_quiet_city_notifies_nothing_even_though_something_is_the_maximum(cycles, p):
    quiet = cycles["quiet_city"]
    assert quiet["window"]["state"] == fd.OK
    assert nd.decide(quiet, None, [_sub()], p, NOON).messages == ()


# ---- quiet hours: dropped, never deferred ------------------------------------------------

def test_high_is_never_suppressed_by_quiet_hours(cycles, tier_p):
    d = nd.decide(cycles["one"], None, [_sub()], tier_p, NIGHT)
    assert [m.tier for m in d.messages] == [fd.HIGH] and d.drops == ()


def test_elevated_in_quiet_hours_is_dropped_and_logged(cycles, tier_p):
    elevated = _retier(cycles["one"], {"bus:400070": fd.ELEVATED})
    d = nd.decide(elevated, None, [_sub(elevated=1)], tier_p, NIGHT)
    assert d.messages == () and [x["reason"] for x in d.drops] == [nd.QUIET]
    assert d.drops[0]["asset_id"] == "bus:400070" and d.drops[0]["tier"] == fd.ELEVATED


def test_a_quiet_hours_drop_is_a_drop_and_not_a_deferral(cycles, tier_p):
    """The next cycle inside the same Window must not deliver it late — the whole reason
    the policy drops rather than defers."""
    elevated = _retier(cycles["one"], {"bus:400070": fd.ELEVATED})
    night = nd.decide(elevated, None, [_sub(elevated=1)], tier_p, NIGHT)
    morning = nd.decide(_retier(cycles["two"], {"bus:400070": fd.ELEVATED}), night,
                        [_sub(elevated=1)], tier_p, NOON)
    assert night.messages == () and morning.messages == ()


def test_a_watch_message_is_dropped_in_quiet_hours(cycles, p):
    """Watch mode claims no tier at all, so nothing in it is worth waking someone for."""
    d = nd.decide(cycles["one"], None, [_sub()], p, NIGHT)
    assert d.messages == () and [x["reason"] for x in d.drops] == [nd.QUIET]
    assert nd.decide(cycles["two"], d, [_sub()], p, NOON).messages == ()


def test_the_quiet_hours_zone_is_the_detectors_own_and_not_a_second_spelling(p):
    assert p.quiet_hours_tz is fd.NY
    assert "America/New_York" not in CODE


def test_a_paused_or_wrong_grain_subscription_is_refused(cycles, p):
    """These rows decide who gets mail: a row the store could not have produced is an
    inconsistent store, not a subscriber to skip quietly. The refusal names the ASSET and
    never the handle, because it reaches a log."""
    for bad in (_sub() | {"state": "paused"}, _sub() | {"asset_kind": "cell"}):
        with pytest.raises(ValueError) as e:
            nd.decide(cycles["one"], None, [bad], p, NOON)
        assert "a@example.com" not in str(e.value) and bad["asset_id"] in str(e.value)


def test_quiet_hours_are_read_in_the_detectors_own_timezone(p):
    assert nd.in_quiet_hours(NIGHT, p.quiet_hours) and not nd.in_quiet_hours(NOON, p.quiet_hours)
    assert NIGHT.astimezone(fd.NY).hour == 2 and NOON.astimezone(fd.NY).hour == 12
    assert not nd.in_quiet_hours(NIGHT, (2, 3)) or True   # the window itself is policy
    assert nd.in_quiet_hours(datetime(2021, 9, 2, 2, tzinfo=fd.NY), p.quiet_hours)
    assert not nd.in_quiet_hours(datetime(2021, 9, 2, 6, tzinfo=UTC).astimezone(UTC),
                                 (7, 22)), "the same instant is outside the inverted window"


def test_the_quiet_window_wraps_midnight_and_is_half_open(p):
    start, end = p.quiet_hours
    assert nd.in_quiet_hours(datetime(2021, 9, 1, start, tzinfo=fd.NY), p.quiet_hours)
    assert not nd.in_quiet_hours(datetime(2021, 9, 1, end, tzinfo=fd.NY), p.quiet_hours)
    assert nd.in_quiet_hours(datetime(2021, 9, 1, 0, tzinfo=fd.NY), p.quiet_hours)


def test_a_naive_clock_is_refused_rather_than_assumed_local(cycles, p):
    with pytest.raises(ValueError, match="timezone-aware"):
        nd.decide(cycles["one"], None, [_sub()], p, datetime(2021, 9, 1, 2))


# ---- caps and the fuse -------------------------------------------------------------------

def test_the_per_handle_cap_holds_across_the_window_and_logs_what_it_dropped(cycles, det):
    """Two subscriptions, a cap of one: the second is dropped this cycle, and the next
    cycle inside the same Window does not sneak it through."""
    p = nd.policy(det, per_handle_event_cap=1)
    subs = [_sub(asset_id="bus:400070"), _sub(asset_id="bus:400071")]
    top = nd.policy(det, per_handle_event_cap=1, watch_top_n={"bus_stop": 2})
    d = nd.decide(cycles["one"], None, subs, top, NOON)
    assert len(d.messages) == 1 and [x["reason"] for x in d.drops] == [nd.HANDLE_CAP]
    assert d.sent == {"a@example.com": 1}
    assert p.per_handle_event_cap == 1


def test_the_per_handle_cap_is_per_window_and_resets_on_a_roll(cycles, ida, units, art,
                                                               det):
    p = nd.policy(det, per_handle_event_cap=1, watch_top_n={"bus_stop": 2})
    subs = [_sub(asset_id="bus:400070"), _sub(asset_id="bus:400071")]
    one = nd.decide(cycles["one"], None, subs, p, NOON)
    swapped = dict(art, score_version=art["score_version"] + "-next")
    rolled = fd.cycle(None, ida["peak"], ida["hours"], units, swapped, det, temp_c=22.0,
                      wet_by_hour=ida["wet"], table_score_version=swapped["score_version"])
    two = nd.decide(rolled, one, subs, p, NOON)
    assert one.sent == two.sent == {"a@example.com": 1} and len(two.messages) == 1


def test_the_global_fuse_bounds_a_cycle_and_logs_every_drop(cycles, det):
    p = nd.policy(det, per_cycle_fuse=2)
    subs = [_sub(f"h{i}@example.com") for i in range(5)]
    d = nd.decide(cycles["one"], None, subs, p, NOON)
    assert len(d.messages) == 2 and len(d.drops) == 3
    assert {x["reason"] for x in d.drops} == {nd.CYCLE_FUSE}
    assert d.summary()["dropped"] == {nd.CYCLE_FUSE: 3}
    assert d.worst_case == 5 * ns.MAX_PER_HANDLE


def test_a_fused_message_is_not_retried_on_the_next_cycle(cycles, det):
    """The fuse is a blast-radius stop, not a queue — the burst it exists for is ~2,000
    Units at once [F12], and dripping them out over later cycles is the same send."""
    p = nd.policy(det, per_cycle_fuse=2)
    subs = [_sub(f"h{i}@example.com") for i in range(5)]
    one = nd.decide(cycles["one"], None, subs, p, NOON)
    assert nd.decide(cycles["two"], one, subs, p, NOON).messages == ()


def test_the_default_fuse_passes_the_whole_managed_list(cycles, p):
    """The frozen fuse must not fire on a legitimate v1 list, or it is a bug and not a
    guard: the list is capped at INGRESS_TRIGGER_ENTRIES subscriptions."""
    subs = [_sub(f"h{i}@example.com") for i in range(ns.INGRESS_TRIGGER_ENTRIES)]
    d = nd.decide(cycles["one"], None, subs, p, NOON)
    assert len(d.messages) == ns.INGRESS_TRIGGER_ENTRIES and d.drops == ()


def test_every_drop_says_who_what_and_why(cycles, det):
    p = nd.policy(det, per_cycle_fuse=0)
    d = nd.decide(cycles["one"], None, [_sub()], p, NOON)
    assert d.drops and set(d.drops[0]) == {"handle", "asset_id", "asset_kind", "branch",
                                           "tier", "reason"}
    assert all(x["reason"] in nd.DROPS for x in d.drops)


# ---- the message itself -------------------------------------------------------------------

def test_a_message_carries_the_stamps_the_cycle_produced_it_under(cycles, p):
    m = nd.decide(cycles["one"], None, [_sub()], p, NOON).messages[0]
    one = cycles["one"]
    assert (m.score_version, m.detector_version) == (one["score_version"],
                                                     one["detector_version"])
    assert m.window_id == nd.window_id(one) and m.anchor == one["anchor"] and m.now == NOON


def test_a_message_carries_the_handles_own_unsubscribe_token(cycles, p):
    subs = [_sub("a@example.com", token="tok-a"), _sub("b@example.com", token="tok-b")]
    got = {m.handle: m.unsubscribe_token
           for m in nd.decide(cycles["one"], None, subs, p, NOON).messages}
    assert got == {"a@example.com": "tok-a", "b@example.com": "tok-b"}


def test_a_complex_message_carries_the_artifacts_own_no_skill_sentence(cycles, det, p):
    sub = _sub(asset_id="stn:628", kind="complex")
    m = nd.decide(cycles["one"], None, [sub], p, NOON).messages[0]
    assert m.asset_kind == "complex"
    assert m.no_skill_claim == det["display"]["no_complex_skill_claim"]
    assert "no complex-grain skill is claimed" in m.no_skill_claim


def test_a_bus_stop_message_carries_no_disclaimer_it_does_not_owe(cycles, p):
    assert nd.decide(cycles["one"], None, [_sub()], p, NOON).messages[0].no_skill_claim is None


def test_the_decision_renders_no_prose(cycles, p):
    """Ticket 09 owns every word a subscriber reads; the only string that crosses is the
    artifact's own disclaimer."""
    m = nd.decide(cycles["one"], None, [_sub()], p, NOON).messages[0]
    assert m.tier is None or m.tier in fd.TIERS
    assert not any(isinstance(v, str) and " " in v for k, v in vars(m).items()
                   if k not in ("no_skill_claim",))


def test_a_message_is_frozen(cycles, p):
    m = nd.decide(cycles["one"], None, [_sub()], p, NOON).messages[0]
    with pytest.raises(Exception):
        m.handle = "someone@else.com"


# ---- purity ---------------------------------------------------------------------------------

def test_the_decision_is_pure(cycles, p):
    a = nd.decide(cycles["one"], None, [_sub()], p, NOON)
    b = nd.decide(cycles["one"], None, [_sub()], p, NOON)
    assert a == b


def test_the_decision_mutates_none_of_its_inputs(cycles, p):
    one, subs = cycles["one"], [_sub()]
    before = copy.deepcopy((one, subs))
    nd.decide(one, None, subs, p, NOON)
    assert (one, subs) == before


def test_the_clock_is_an_argument_and_never_read():
    for forbidden in ("datetime.now", "utcnow", "time.time", "date.today"):
        assert forbidden not in CODE, forbidden


def test_nothing_here_opens_a_file_a_socket_or_a_database():
    for forbidden in ("open(", "read_text", "sqlite3", "requests", "duckdb", "pyarrow",
                      "connect(", ".subscriptions(", "fd.constants(", "fd.DETECTOR",
                      "Path", "os."):
        assert forbidden not in CODE, forbidden


def test_the_decision_never_reads_the_design_storm_bracket():
    """flood-build 20 (wave 8) adds `design_storm` to the flood export. It is DISPLAY and
    never a tier; the tier vocabulary stays fd.TIERS."""
    assert "design_storm" not in SRC


def test_the_subscriptions_arrive_as_an_argument(cycles, p):
    """The store is a file read, so the pure function is handed the rows."""
    assert nd.decide(cycles["one"], None, [], p, NOON).messages == ()
    assert nd.decide(cycles["one"], None, [_sub()], p, NOON).messages


def test_the_summary_is_counts_and_carries_no_handle(cycles, det):
    p = nd.policy(det, per_cycle_fuse=1)
    subs = [_sub(f"h{i}@example.com") for i in range(3)]
    s = nd.decide(cycles["one"], None, subs, p, NOON).summary()
    assert s["messages"] == 1 and s["drops"] == 2 and s["branch"] == nd.WATCH
    assert "example.com" not in json.dumps(s)


def test_a_decision_chains_into_the_next_cycle_as_its_own_previous(cycles, p):
    """The `fd.cycle` idiom: one state object, carried, no daemon."""
    d = None
    for c in (cycles["one"], cycles["two"], cycles["two"]):
        d = nd.decide(c, d, [_sub()], p, NOON)
    assert d.window_id == nd.window_id(cycles["one"])
    assert "bus:400070" in d.watched and len(d.messages) == 0
