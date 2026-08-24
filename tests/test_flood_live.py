"""Flood-build ticket 14: the coastal live tier and the winter-gate fetch.

Seam 2 — pure functions over captured bodies, no network. Every fixture is a verbatim
response from the live API on 2026-08-24T01:41Z:

  flood_coops_obs.json          Battery 6-min water levels, `range=1` (the PAST hour)
  flood_coops_pred6.json        the same hour's 6-min harmonic predictions
  flood_coops_hilo_forward.json `begin_date=<capture>&range=36` — highs and lows AHEAD
  flood_coops_hilo_bare.json    a bare `range=36` — the same query minus begin_date,
                                returning the PAST 36 h. The pair is the ticket's
                                forward-vs-past assertion, on two real bodies.
  flood_coops_error.json        a CO-OPS failure: HTTP 200 with an error body
  flood_nws_knyc.json           the KNYC latest observation feeding the winter gate

NOW is pinned just after the capture instant, so freshness and the 12 h anomaly horizon
are properties of the fixtures rather than of the day the suite runs.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from raincheck import flood_coastal as fc, flood_live as fl

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 8, 24, 1, 41, tzinfo=timezone.utc)
BATTERY = "8518750"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(scope="module")
def obs():
    return fl.observations(_load("flood_coops_obs.json"))


@pytest.fixture(scope="module")
def pred6():
    return fl.predictions(_load("flood_coops_pred6.json"))


@pytest.fixture(scope="module")
def highs(obs, pred6):
    a = fl.anomaly(obs, pred6)
    return fl.next_highs(fl.predictions(_load("flood_coops_hilo_forward.json")), NOW,
                         a["anomaly_ft"])


# ---- the forward-vs-past range semantics (the frozen query strings) ---------------
def test_bare_range_returns_the_past_and_begin_date_returns_the_future():
    """The measured trap the constants exist to prevent: `range=36` alone is BACKWARD.
    Two verbatim bodies of the same query, captured minutes apart, differing only in
    whether begin_date was sent."""
    past = fl.predictions(_load("flood_coops_hilo_bare.json"))
    fwd = fl.predictions(_load("flood_coops_hilo_forward.json"))
    assert past and fwd
    assert all(r["t"] < NOW for r in past), "bare range=36 must return the PAST 36 h"
    assert all(r["t"] > NOW for r in fwd), "begin_date + range must return the FORWARD window"


def test_fetch_sends_begin_date_only_when_now_is_supplied(monkeypatch):
    """The direction of a hilo read is decided by one parameter, so assert which reads
    send it: the forecast does, the past-hour observation and prediction reads do not."""
    sent = []

    class R:
        def raise_for_status(self): pass
        def json(self): return {"predictions": []}

    monkeypatch.setattr(fl.requests, "get", lambda url, params, timeout: sent.append(params) or R())
    fl.fetch(BATTERY, fl.HILO_QUERY, now=NOW)
    fl.fetch(BATTERY, fl.OBS_QUERY)
    assert sent[0]["begin_date"] == "20260824 01:41"
    assert "begin_date" not in sent[1]
    assert sent[0]["datum"] == "NAVD" and sent[1]["datum"] == "NAVD"


def test_frozen_queries_are_not_mutated_by_a_fetch(monkeypatch):
    """`fetch` copies before adding station/begin_date; a leak would make the second
    cycle's observation query carry the first cycle's begin_date."""
    before = dict(fl.OBS_QUERY)

    class R:
        def raise_for_status(self): pass
        def json(self): return {"data": []}

    monkeypatch.setattr(fl.requests, "get", lambda url, params, timeout: R())
    fl.fetch(BATTERY, fl.OBS_QUERY, now=NOW)
    assert fl.OBS_QUERY == before


# ---- one constants family, two consumers -----------------------------------------
def test_thresholds_come_from_the_static_layer_not_a_second_copy():
    """This tier imports GAUGES and STAGE; it does not re-declare them. The chip's minor
    stage IS `flood_coastal.minor_navd88_ft`, so a stage moved there moves here."""
    assert fl.GAUGES is fc.GAUGES and fl.STAGE is fc.STAGE
    chip = fl.chip(BATTERY, [(NOW, 0.5)], [], NOW)
    assert chip["minor_navd88_ft"] == fc.minor_navd88_ft(BATTERY) == 4.43
    assert chip["stage"] == "nws_minor"


def test_kings_point_reads_its_own_converted_minor():
    """The Kings Point NWS/NOS inversion recorded at flood_coastal's definition is honored
    by reading the nws_minor stage for every gauge, converted per station: Kings Point's
    22.89 ft STND is 5.80 NAVD88, higher than the Battery's 4.43, so one water level lands
    in two different chips — 4.5 ft is EXCEEDING at the Battery and still QUIET at Kings
    Point, 1.3 ft under its own stage."""
    assert fc.minor_navd88_ft("8516945") == 5.80
    assert fl.chip("8518750", [(NOW, 4.5)], [], NOW)["state"] == fl.EXCEEDING
    assert fl.chip("8516945", [(NOW, 4.5)], [], NOW)["state"] == fl.QUIET


def test_check_shared_family_fails_when_a_gauge_is_added_on_one_side(monkeypatch):
    fl.check_shared_family()
    monkeypatch.setitem(fc.GAUGES, "9999999", dict(fc.GAUGES[BATTERY]))
    with pytest.raises(AssertionError):
        fl.check_shared_family()


# ---- observations -----------------------------------------------------------------
def test_observations_parse_navd88_feet_ascending(obs):
    assert len(obs) == 10
    assert obs[0][0] == datetime(2026, 8, 24, 0, 42, tzinfo=timezone.utc)
    assert obs[-1] == (datetime(2026, 8, 24, 1, 36, tzinfo=timezone.utc), 0.44)
    assert obs == sorted(obs)


def test_a_blank_value_is_a_gap_not_a_zero():
    """CO-OPS emits the stamp with an empty `v` for a missing sample. Reading that as 0.0
    would put the harbour 4.43 ft below its own minor stage."""
    payload = {"data": [{"t": "2026-08-24 01:30", "v": ""},
                        {"t": "2026-08-24 01:36", "v": "0.44"}]}
    assert fl.observations(payload) == [
        (datetime(2026, 8, 24, 1, 36, tzinfo=timezone.utc), 0.44)]


def test_a_coops_error_body_raises_despite_http_200():
    """The measured failure mode: status 200, `{"error": {...}}`. A parser that trusted
    the status code would render an outage as a healthy empty gauge."""
    with pytest.raises(RuntimeError, match="No data was found"):
        fl.observations(_load("flood_coops_error.json"))


# ---- the anomaly ------------------------------------------------------------------
def test_anomaly_joins_on_aligned_6_min_stamps(obs, pred6):
    a = fl.anomaly(obs, pred6)
    assert a["samples"] == 10 and a["span_min"] == 54 and a["why"] is None
    assert a["anomaly_ft"] == pytest.approx(0.756, abs=0.001)


def test_a_thin_window_yields_no_anomaly_rather_than_a_noisy_one(obs, pred6):
    a = fl.anomaly(obs[-3:], pred6)
    assert a["anomaly_ft"] is None and a["span_min"] == 12
    assert "aligned" in a["why"]


def test_hilo_rows_never_enter_the_anomaly(obs):
    """hilo predictions carry a `type`; 6-min ones do not. Joining a high onto an
    observation stamp would compare water to a different quantity."""
    hilo = fl.predictions(_load("flood_coops_hilo_forward.json"))
    assert fl.anomaly(obs, hilo)["anomaly_ft"] is None


# ---- the forward highs and the 12 h horizon --------------------------------------
def test_the_anomaly_rides_only_on_highs_within_the_horizon(highs):
    assert [h["anomaly_applied"] for h in highs] == [True, False, False]
    near, far = highs[0], highs[1]
    assert near["hours"] < fl.ANOMALY_HORIZON_H < far["hours"]
    assert near["ft"] == pytest.approx(near["harmonic_ft"] + 0.756, abs=0.001)
    assert far["ft"] == far["harmonic_ft"]


def test_lows_and_past_highs_are_not_next_highs(highs):
    """The forward body opens with a LOW at 04:24; the next high is 10:26."""
    assert highs[0]["t"].startswith("2026-08-24T10:26")
    assert all(h["hours"] > 0 for h in highs)


# ---- the chips --------------------------------------------------------------------
def test_quiet_when_observed_and_forecast_are_both_clear(obs, highs):
    c = fl.chip(BATTERY, obs, highs, NOW)
    assert c["state"] == fl.QUIET
    assert c["observed_margin_ft"] == pytest.approx(3.99, abs=0.001)
    assert c["next_high"]["ft"] == pytest.approx(1.991, abs=0.001)
    assert c["quality"].startswith("preliminary")


def test_approaching_when_the_next_high_is_within_a_foot_of_minor(obs):
    """4.43 minus 1.0 = 3.43 ft NAVD88 at the Battery: a forecast high at 3.5 approaches,
    one at 3.4 does not."""
    near = [{"t": "x", "hours": 6.0, "harmonic_ft": 3.5, "ft": 3.5, "anomaly_applied": True}]
    assert fl.chip(BATTERY, obs, near, NOW)["state"] == fl.APPROACHING
    near[0]["ft"] = 3.4
    assert fl.chip(BATTERY, obs, near, NOW)["state"] == fl.QUIET


def test_the_anomaly_is_what_tips_a_gauge_into_approaching(obs, pred6):
    """The surge residual is not decoration: the same harmonic high reads QUIET without it
    and APPROACHING with it."""
    hilo = fl.predictions(_load("flood_coops_hilo_forward.json"))
    plain = fl.next_highs(hilo, NOW, None)
    surged = fl.next_highs(hilo, NOW, 2.2)
    assert fl.chip(BATTERY, obs, plain, NOW)["state"] == fl.QUIET
    assert fl.chip(BATTERY, obs, surged, NOW)["state"] == fl.APPROACHING


def test_exceeding_beats_approaching(obs, highs):
    """Water already over minor is EXCEEDING whatever the forecast says next."""
    over = obs[:-1] + [(obs[-1][0], 4.5)]
    assert fl.chip(BATTERY, over, highs, NOW)["state"] == fl.EXCEEDING


def test_outage_is_a_state_never_silence_and_never_a_stale_value(highs):
    empty = fl.chip(BATTERY, [], highs, NOW)
    assert empty["state"] == fl.OUTAGE and empty["observed_ft"] is None
    assert "no observation" in empty["reason"]
    stale = fl.chip(BATTERY, [(NOW - timedelta(minutes=45), 0.4)], highs, NOW)
    assert stale["state"] == fl.OUTAGE and stale["obs_age_min"] == 45.0
    assert stale["observed_ft"] is None, "a stale reading is never shown as current"
    assert stale["next_high"] is not None, "the forecast still renders under a gauge outage"


def test_a_failed_read_greys_one_gauge_not_the_tier(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(fl, "fetch", boom)
    g = fl.gauge(BATTERY, NOW)
    assert g["state"] == fl.OUTAGE and "TimeoutError" in g["reason"]


HOT = [{"station": "8518750", "state": fl.QUIET},
       {"station": "8516945", "state": fl.APPROACHING},
       {"station": "8531680", "state": fl.EXCEEDING}]
MARGINS = [{"asset_id": "a", "gauge": "8518750", "surge_margin_ft": 1.0},
           {"asset_id": "b", "gauge": "8516945", "surge_margin_ft": -2.0},
           {"asset_id": "c", "gauge": "8531680", "surge_margin_ft": 8.0},
           {"asset_id": "d", "gauge": "8531680", "surge_margin_ft": None}]


def test_recolor_names_the_live_gauges_only():
    """The data side of asset recoloring: which gauges are hot. QUIET gauges' Units are
    not in the set, so a quiet harbour recolors nothing."""
    r = fl.recolor(HOT)
    assert r["gauges"] == ["8516945", "8531680"]
    assert "flood_coastal" in r["margin_source"]
    assert r["units"] is None, "no margin table supplied means none is invented"


def test_recolor_carries_the_static_margin_and_never_zeroes_a_null():
    """Ticket 07's warning: a Unit with no margin priced as 0.0 sits exactly at minor
    flood stage, the most alarming value the column can take. It rides through as None."""
    r = fl.recolor(HOT, MARGINS)
    assert [u["asset_id"] for u in r["units"]] == ["b", "c", "d"], "the QUIET gauge is out"
    assert r["n_units"] == 3 and r["n_no_margin"] == 1 and r["n_below_minor"] == 1
    assert [u["surge_margin_ft"] for u in r["units"]] == [-2.0, 8.0, None]


# ---- the winter-gate fetch --------------------------------------------------------
def test_knyc_observation_parses_celsius():
    o = fl.parse_knyc(_load("flood_nws_knyc.json"))
    assert o["temp_c"] == 23.9 and o["unit"] == "wmoUnit:degC" and o["qc"] == "V"
    assert o["t"] == "2026-08-24T00:51:00+00:00"


def test_a_null_temperature_is_none_never_zero():
    """0.0 C is below the gate's 0.5 C cutoff, so a null coerced to zero would suppress
    every tier on a warm day with a broken thermometer."""
    payload = {"properties": {"timestamp": "2026-08-24T00:51:00+00:00",
                              "temperature": {"value": None, "unitCode": "wmoUnit:degC",
                                              "qualityControl": "Z"}}}
    assert fl.parse_knyc(payload)["temp_c"] is None
    assert fl.parse_knyc({})["temp_c"] is None


def test_winter_obs_reports_age_and_greys_on_error(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return _load("flood_nws_knyc.json")

    monkeypatch.setattr(fl.requests, "get", lambda url, timeout, headers: R())
    w = fl.winter_obs(NOW)
    assert w["status"] == "ok" and w["temp_c"] == 23.9 and w["age_min"] == 50.0
    assert "raincheck" in fl.NWS_UA, "an empty User-Agent is a 403 from api.weather.gov"

    def boom(*a, **k):
        raise ConnectionError("refused")

    monkeypatch.setattr(fl.requests, "get", boom)
    e = fl.winter_obs(NOW)
    assert e["status"] == "error" and e["temp_c"] is None


def test_the_shared_check_chains_the_spine(monkeypatch):
    """One number, three consumers: the stage the spine CUTS event-days on, the stage the
    static layer MEASURES margins against, and the stage this tier DRAWS chips against.
    Bending the spine's copy fails this tier's build check, not just flood_coastal's."""
    from raincheck import flood_spine

    monkeypatch.setitem(flood_spine.NWS_MINOR_STND_FT, BATTERY, 99.9)
    with pytest.raises(RuntimeError, match="threshold split"):
        fl.check_shared_family()


def test_an_unsorted_caller_cannot_invert_the_anomaly_window():
    """Measured while probing: a descending series produced a NEGATIVE span, which slid
    under the minimum-span check and published a mean over an arbitrary 11 samples."""
    obs = [(NOW - timedelta(minutes=m), 1.0) for m in range(60, 0, -6)]
    pred = [{"t": t, "ft": 0.5, "type": None} for t, _ in obs]
    up, down = fl.anomaly(obs, pred), fl.anomaly(obs[::-1], pred)
    assert up["span_min"] > 0 and up == down
    assert up["anomaly_ft"] == pytest.approx(0.5)


def test_a_gauge_stamping_ahead_of_the_clock_is_an_outage(highs):
    """A source's own clock is not evidence of its correctness — FloodNet's year-2080
    sensor is the precedent. A future stamp would otherwise read as the freshest sample
    there is and be rendered as current."""
    ahead = fl.chip(BATTERY, [(NOW + timedelta(minutes=30), 0.4)], highs, NOW)
    assert ahead["state"] == fl.OUTAGE and ahead["observed_ft"] is None
    assert "ahead" in ahead["reason"]
    # a couple of minutes of clock skew is normal and still reads
    assert fl.chip(BATTERY, [(NOW + timedelta(minutes=2), 0.4)], highs, NOW)["state"] == fl.QUIET


def test_the_preliminary_label_matches_what_the_api_actually_flags():
    """The label is a constant only because the frozen `range=1` query makes it one: the
    last hour is always preliminary. This asserts the captured body agrees, so a recapture
    is what catches CO-OPS changing its mind — not a user reading a wrong label."""
    flags = {r["q"] for r in _load("flood_coops_obs.json")["data"]}
    assert flags == {"p"} and "q=p" in fl.PRELIMINARY


# ---- failures isolated to the read that failed -----------------------------------
def test_a_forecast_failure_never_erases_a_live_exceeding_observation(monkeypatch):
    """The defect this pins: three fetches shared one try block, so a forecast timeout
    greyed the gauge and took a real EXCEEDING reading down with it. The observation is
    the load-bearing read — water already over the stage is what the tier exists to say."""
    over = {"data": [{"t": "2026-08-24 01:36", "v": "5.20", "q": "p"}]}

    def one_read(station, query, now=None, timeout=fl.TIMEOUT):
        if query is fl.HILO_QUERY:
            raise TimeoutError("forecast timed out")
        return over if query is fl.OBS_QUERY else {"predictions": []}

    monkeypatch.setattr(fl, "fetch", one_read)
    g = fl.gauge(BATTERY, NOW)
    assert g["state"] == fl.EXCEEDING and g["observed_ft"] == 5.20
    assert g["next_high"] is None and "TimeoutError" in g["forecast_error"]


def test_an_observation_failure_is_an_outage_that_still_shows_the_forecast(monkeypatch):
    def one_read(station, query, now=None, timeout=fl.TIMEOUT):
        if query is fl.OBS_QUERY:
            raise ConnectionError("refused")
        return (_load("flood_coops_hilo_forward.json") if query is fl.HILO_QUERY
                else {"predictions": []})

    monkeypatch.setattr(fl, "fetch", one_read)
    g = fl.gauge(BATTERY, NOW)
    assert g["state"] == fl.OUTAGE and "ConnectionError" in g["reason"]
    assert g["next_high"] is not None


def test_every_chip_has_one_shape(monkeypatch):
    """A consumer iterating chips must not KeyError on the failure path: the error chip is
    built through chip() like every other, not hand-rolled."""
    def boom(*a, **k):
        raise TimeoutError("t")

    monkeypatch.setattr(fl, "fetch", boom)
    broken = fl.gauge(BATTERY, NOW)
    monkeypatch.undo()
    healthy = fl.chip(BATTERY, [(NOW, 0.4)], [], NOW) | {
        "anomaly": {}, "anomaly_note": "", "forecast_error": None, "observation_error": None}
    assert set(healthy) - set(broken) <= {"observed_margin_ft", "obs_t"}
    assert broken["minor_navd88_ft"] == 4.43 and broken["stage"] == "nws_minor"


# ---- the fixed thin-window and direction gaps ------------------------------------
def test_two_samples_an_hour_apart_are_not_a_surge_residual():
    """Span alone let a mean-of-two through: a 6-min cadence with holes can span the full
    window on two readings. Both the span AND the count have to clear."""
    obs = [(NOW - timedelta(minutes=m), 1.0) for m in (55, 6)]
    pred = [{"t": t, "ft": 0.5, "type": None} for t, _ in obs]
    a = fl.anomaly(obs, pred)
    assert a["anomaly_ft"] is None and a["samples"] == 2 and a["span_min"] == 49


def test_the_gauge_actually_queries_the_forward_window(monkeypatch):
    """The suite was green with the forecast mutated to backward: the direction test only
    exercised fetch() directly. This one watches what gauge() itself sends."""
    sent = []

    def spy(station, query, now=None, timeout=fl.TIMEOUT):
        sent.append((query.get("interval"), now))
        return {"data": [], "predictions": []}

    monkeypatch.setattr(fl, "fetch", spy)
    fl.gauge(BATTERY, NOW)
    hilo = [n for interval, n in sent if interval == "hilo"]
    assert hilo == [NOW], "the hilo read must carry `now`, or it returns the PAST 36 h"
    assert all(n is None for interval, n in sent if interval != "hilo")


def test_an_observation_within_a_foot_of_minor_approaches_on_its_own(highs):
    """A gauge 0.02 ft under its own flood stage read QUIET whenever the next harmonic
    high was low. Water already here outranks water coming."""
    assert fl.chip(BATTERY, [(NOW, 4.41)], [], NOW)["state"] == fl.APPROACHING
    assert fl.chip(BATTERY, [(NOW, 3.42)], [], NOW)["state"] == fl.QUIET


# ---- boundary hygiene --------------------------------------------------------------
def test_a_non_utc_now_does_not_shift_the_forward_window(monkeypatch):
    """begin_date was formatted off whatever tz the caller passed, so a local-time `now`
    moved the forecast window by the UTC offset without erroring."""
    sent = []

    class R:
        def raise_for_status(self): pass
        def json(self): return {"predictions": []}

    monkeypatch.setattr(fl.requests, "get", lambda url, params, timeout: sent.append(params) or R())
    naive = datetime(2026, 8, 24, 1, 41)
    eastern = datetime(2026, 8, 23, 21, 41, tzinfo=timezone(timedelta(hours=-4)))
    fl.fetch(BATTERY, fl.HILO_QUERY, now=naive)
    fl.fetch(BATTERY, fl.HILO_QUERY, now=eastern)
    assert {p["begin_date"] for p in sent} == {"20260824 01:41"}


def test_a_json_null_value_is_dropped_not_raised():
    """`str(None).strip()` is the truthy "None" that reached float() and greyed a whole
    gauge over one bad sample."""
    payload = {"data": [{"t": "2026-08-24 01:30", "v": None},
                        {"t": "2026-08-24 01:36", "v": "0.44"}]}
    assert fl.observations(payload) == [
        (datetime(2026, 8, 24, 1, 36, tzinfo=timezone.utc), 0.44)]


def test_a_day_old_central_park_reading_is_not_handed_over_as_ok(monkeypatch):
    """The winter gate suppresses every tier on this number. A stale reading must not
    arrive wearing the same "ok" as a fresh one — ticket 11 decides what to do with it."""
    class R:
        def raise_for_status(self): pass
        def json(self): return _load("flood_nws_knyc.json")

    monkeypatch.setattr(fl.requests, "get", lambda url, timeout, headers: R())
    fresh = fl.winter_obs(NOW)
    old = fl.winter_obs(NOW + timedelta(hours=6))
    assert fresh["status"] == "ok" and fresh["stale"] is False
    assert old["status"] == "stale" and old["stale"] is True and old["temp_c"] == 23.9


def test_a_malformed_timestamp_does_not_take_the_tier_down(monkeypatch):
    """`_iso` runs outside winter_obs's try. A `timestamp` that is not a string raised
    AttributeError past every handler — the tier died on the one line not covered."""
    assert fl._iso({"not": "a string"}) is None and fl._iso(17) is None

    class R:
        def raise_for_status(self): pass
        def json(self):
            return {"properties": {"timestamp": {"bad": 1},
                                   "temperature": {"value": 23.9, "qualityControl": "V"}}}

    monkeypatch.setattr(fl.requests, "get", lambda url, timeout, headers: R())
    w = fl.winter_obs(NOW)
    assert w["age_min"] is None and w["stale"] is True and w["temp_c"] == 23.9
