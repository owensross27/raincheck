"""Flood-build ticket 14 (spec "Real-time detector"): the coastal live tier and the
winter-gate fetch.

Two live reads that the panel calls once per cycle, both pure-parse over captured bodies:

  * COASTAL. Three CO-OPS gauges observed in NAVD88 directly, measured against the SAME
    frozen threshold family the static surge layer uses — `flood_coastal.GAUGES` and
    `flood_coastal.STAGE` are imported, never re-declared, and `check_shared_family()`
    asserts the two consumers still read one constant. Chips: QUIET / APPROACHING /
    EXCEEDING / OUTAGE. A gauge that stops reporting gets its own chip; it is never
    silence and never a stale last-good value shown as current.
  * WINTER GATE. One Central Park (KNYC) observation per cycle, feeding ticket 11's pure
    winter-gate function. This module fetches and parses; it does not decide.

Measured against the live APIs 2026-08-24 (fixtures are those exact bodies):

  * `range=N` alone returns the PAST N hours. The forward window needs
    `begin_date=<now UTC>&range=N` — this is the whole reason the query strings are frozen
    constants below rather than assembled at the call site, and `test_flood_live` asserts
    the two directions against captured bodies of each.
  * A CO-OPS failure is HTTP **200** with `{"error": {"message": ...}}`. `raise_for_status`
    never fires, so every read checks the body. A tier that trusted the status code would
    render an outage as a normal quiet gauge.
  * 6-min observation and 6-min prediction stamps align exactly, so the anomaly is a
    stamp-join and not an interpolation. Observations run ~7-10 min behind wall clock.
  * api.weather.gov returns 403 to an empty User-Agent, and `/points` 301-redirects when
    the coordinates carry more than 4 decimals. Neither matters here because nothing is
    discovered: the KNYC observation URL is a constant. The redirect is recorded so the
    next reader does not re-measure it.

Run: python -m raincheck.flood_live      (fetch and print the coastal chips + winter obs)
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from raincheck import flood_coastal
from raincheck.flood_coastal import GAUGES, STAGE, minor_navd88_ft
from raincheck.paths import data_root

# ---- frozen query strings ---------------------------------------------------------
# Every parameter that changes the MEANING of the answer is frozen here. `begin_date` is
# the only value formatted per cycle, and its absence is what flips the hilo query from
# forward to backward.
COOPS = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
COMMON = {"datum": "NAVD", "units": "english", "time_zone": "gmt", "format": "json",
          "application": "raincheck"}
OBS_QUERY = COMMON | {"product": "water_level", "range": 1}       # PAST 1 h — bare range is correct here
PRED6_QUERY = COMMON | {"product": "predictions", "interval": 6, "range": 1}  # the same past hour
HILO_QUERY = COMMON | {"product": "predictions", "interval": "hilo", "range": 36}  # + begin_date => FORWARD
BEGIN_FMT = "%Y%m%d %H:%M"   # CO-OPS' own begin_date format; requests url-encodes the space

NWS_OBS = "https://api.weather.gov/stations/KNYC/observations/latest"
NWS_UA = "raincheck (https://github.com/rossowens/raincheck)"  # an empty UA is a 403
TIMEOUT = 3.0  # spec: every live fetch has a hard 3 s timeout

# ---- the chip rules ---------------------------------------------------------------
APPROACH_FT = 1.0    # forecast next high within this far below minor => APPROACHING
OBS_STALE_MIN = 30   # newest observation older than this => the gauge is out, not quiet
OBS_AHEAD_MIN = 5    # ... and one stamped further AHEAD than this is a broken clock, also out
# CONFLICT, recorded rather than silently resolved: the spec freezes an NWS staleness
# budget of 15 min, but KNYC reports HOURLY at :51 (measured — 24 consecutive obs, all on
# the hour), so a 15-min budget marks essentially every observation stale and the winter
# gate never fires. This uses one missed report instead. Ticket 11 owns the constants
# artifact where staleness budgets live and must reconcile the two; the 15 min almost
# certainly belongs to the per-cycle NWS ALERTS call, not to an hourly observation.
KNYC_STALE_MIN = 120  # = two report intervals: one hourly obs may be missed, not two
ANOMALY_MIN = 30     # the anomaly needs at least this many minutes of aligned samples...
ANOMALY_MIN_N = 5    # ... AND this many of them: span alone let 2 readings 49 min apart through
ANOMALY_MAX_MIN = 60 # ... and reads at most this many
ANOMALY_HORIZON_H = 12  # ... and is persisted onto highs no further out than this
QUIET, APPROACHING, EXCEEDING, OUTAGE = "QUIET", "APPROACHING", "EXCEEDING", "OUTAGE"

# The action stage is NOT used. Ticket 07 left open which rule covers Kings Point, whose
# `action` stage is null where the Battery and Sandy Hook publish one. The answer is that
# the chip family never needs it: APPROACHING is defined relative to minor (minor - 1.0 ft),
# which all three gauges publish, so one rule covers three gauges and no value is invented
# for the gauge that has none.

# The label is a constant because the frozen query makes it one: `range=1` always reads
# the last hour, and CO-OPS serves 6-min water levels for recent time as PRELIMINARY
# (q:"p") — verification lags about a month. A test asserts the captured body carries no
# other quality flag, so a change in that behavior surfaces when the fixture is recaptured
# rather than as a tier quietly mislabelling verified data.
PRELIMINARY = "preliminary (q=p; CO-OPS verification lags ~1 month)"
ANOMALY_NOTE = ("anomaly = mean(observed - harmonic prediction) over the last "
                f"{ANOMALY_MIN}-{ANOMALY_MAX_MIN} min, persisted onto highs within "
                f"{ANOMALY_HORIZON_H} h only")


def _utc(t: datetime) -> datetime:
    """Every window, stamp comparison and begin_date is UTC. A naive or local-tz `now` from
    a caller would otherwise shift the forward forecast window by the UTC offset silently."""
    return (t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t).astimezone(timezone.utc)


def _ts(s: str | None) -> datetime | None:
    """CO-OPS stamps are naive GMT ('2026-08-24 01:30') because time_zone=gmt is frozen."""
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _num(v) -> bool:
    """CO-OPS emits a gap as the stamp with a blank `v`, and JSON null turns up too. Both
    are dropped — `str(None).strip()` is the truthy "None" that used to reach float()."""
    try:
        float(v)
    except (TypeError, ValueError):
        return False
    return True


def _body(payload: dict, key: str) -> list:
    """CO-OPS reports failure as HTTP 200 with an error body. Every read comes through
    here so no caller can mistake an outage for an empty-but-healthy response."""
    err = (payload or {}).get("error")
    if err:
        raise RuntimeError(err.get("message") or "co-ops error")
    return (payload or {}).get(key) or []


def fetch(station: str, query: dict, now: datetime | None = None,
          timeout: float = TIMEOUT) -> dict:
    """One CO-OPS read. `now` supplied => begin_date is sent and the window runs FORWARD."""
    params = dict(query, station=station)
    if now is not None:
        params["begin_date"] = _utc(now).strftime(BEGIN_FMT)
    r = requests.get(COOPS, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def observations(payload: dict) -> list[tuple[datetime, float]]:
    """6-min water levels, NAVD88 feet, ascending. Samples with a blank `v` are dropped —
    CO-OPS emits them for a gap rather than omitting the stamp."""
    out = [(_ts(r.get("t")), r.get("v")) for r in _body(payload, "data")]
    return sorted((t, float(v)) for t, v in out if t is not None and _num(v))


def predictions(payload: dict) -> list[dict]:
    """Harmonic predictions, NAVD88 feet, ascending. `type` is present on hilo only."""
    out = [{"t": _ts(r.get("t")), "ft": float(r["v"]), "type": r.get("type")}
           for r in _body(payload, "predictions") if _num(r.get("v"))]
    return sorted((r for r in out if r["t"] is not None), key=lambda r: r["t"])


def anomaly(obs: list, pred: list) -> dict:
    """mean(observed - predicted) over the aligned 6-min stamps of the last hour.

    The stamps align exactly, so this is a join and never an interpolation. Fewer than
    ANOMALY_MIN minutes of overlap yields None rather than a mean of two samples — the
    number is the storm-surge residual and a thin one is noise.
    """
    by_t = {r["t"]: r["ft"] for r in pred if r["type"] is None}
    # sorted here, not assumed: an unsorted caller produced a NEGATIVE span in testing,
    # which passed the minimum-span check backwards and would have published a mean over
    # whichever 11 samples happened to be last in the list.
    pairs = sorted((t, ft - by_t[t]) for t, ft in obs if t in by_t)
    pairs = pairs[-(ANOMALY_MAX_MIN // 6 + 1):]  # 60 min = 10 intervals = 11 stamps
    span = (pairs[-1][0] - pairs[0][0]).total_seconds() / 60 if len(pairs) > 1 else 0
    if span < ANOMALY_MIN or len(pairs) < ANOMALY_MIN_N:
        # both, not either: a 6-min cadence with holes can span an hour on two samples, and
        # a mean of two is not a surge residual — it is one number wearing a plural.
        return {"anomaly_ft": None, "samples": len(pairs), "span_min": round(span),
                "why": f"under {ANOMALY_MIN} min / {ANOMALY_MIN_N} aligned 6-min stamps"}
    return {"anomaly_ft": round(sum(d for _, d in pairs) / len(pairs), 3),
            "samples": len(pairs), "span_min": round(span), "why": None}


def next_highs(pred: list, now: datetime, anomaly_ft: float | None) -> list[dict]:
    """The forward highs, with the anomaly persisted onto those within the horizon only.

    Persisting a 30-minute surge residual onto a high 20 hours out would be a forecast
    this module has no business making, so the far highs carry the harmonic value alone
    and say why (`anomaly_applied: false`).
    """
    out = []
    for r in pred:
        if r["type"] != "H" or r["t"] <= now:
            continue
        hours = (r["t"] - now).total_seconds() / 3600
        applied = anomaly_ft is not None and hours <= ANOMALY_HORIZON_H
        out.append({"t": r["t"].isoformat(), "hours": round(hours, 2),
                    "harmonic_ft": r["ft"], "anomaly_applied": applied,
                    "ft": round(r["ft"] + anomaly_ft, 3) if applied else r["ft"]})
    return out


def chip(station: str, obs: list, highs: list, now: datetime) -> dict:
    """One gauge's chip. Outage is a STATE, not an absence: an empty or stale read says
    so with its own age, and the observed value is not shown at all rather than shown
    stale. EXCEEDING wins over APPROACHING — the water is already there."""
    minor = minor_navd88_ft(station)
    g = GAUGES[station]
    out = {"station": station, "name": g["name"], "minor_navd88_ft": minor,
           "stage": STAGE, "quality": PRELIMINARY,
           "next_high": highs[0] if highs else None,
           "approach_ft": APPROACH_FT}
    if not obs:
        return out | {"state": OUTAGE, "observed_ft": None, "obs_age_min": None,
                      "reason": "no observation in the last hour"}
    t, ft = max(obs)
    age = (now - t).total_seconds() / 60
    if not (-OBS_AHEAD_MIN <= age <= OBS_STALE_MIN):
        # FloodNet's year-2080 sensor is the precedent: a source's clock is not evidence
        # of its own correctness. A future stamp is an outage, never a fresh reading.
        return out | {"state": OUTAGE, "observed_ft": None, "obs_age_min": round(age, 1),
                      "reason": (f"newest observation {round(age)} min old" if age > 0
                                 else f"newest observation stamped {round(-age)} min ahead")}
    margin = round(minor - ft, 3)
    state = QUIET
    if ft >= minor:
        state = EXCEEDING
    elif ft >= minor - APPROACH_FT or (highs and highs[0]["ft"] >= minor - APPROACH_FT):
        # the OBSERVED leg was missing until review: the design defines APPROACHING off the
        # forecast, which read QUIET for a gauge sitting 0.02 ft under its own flood stage
        # whenever the next harmonic high was low. Water already here outranks water coming.
        state = APPROACHING
    return out | {"state": state, "observed_ft": ft, "obs_age_min": round(age, 1),
                  "observed_margin_ft": margin, "obs_t": t.isoformat(), "reason": None}


def check_shared_family() -> None:
    """One constants family, three consumers. This tier reads `flood_coastal`'s gauges and
    stage directly rather than copying them, so the assertion is that it still CAN: every
    gauge the static layer measures margins against must be one this tier can render a
    chip for. Chaining `flood_coastal`'s own spine check makes the whole line — the stage
    a coastal event-day is CUT on, the stage a Unit's margin is MEASURED against, and the
    stage a live chip is DRAWN against — a single number or a failed build."""
    assert STAGE == "nws_minor", STAGE
    flood_coastal.check_shared_thresholds()
    assert len(GAUGES) == 3, sorted(GAUGES)
    for station in GAUGES:
        assert minor_navd88_ft(station) > 0, station


def _read(station, query, now, timeout, parse):
    """One read, its failure isolated to itself: (value, error-string-or-None)."""
    try:
        return parse(fetch(station, query, now=now, timeout=timeout)), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def gauge(station: str, now: datetime, timeout: float = TIMEOUT) -> dict:
    """One gauge, three reads, each failing ALONE.

    The three were one try block until review: a forecast timeout then greyed the gauge and
    erased a live EXCEEDING observation with it. The observation is the load-bearing read —
    water already over the stage is the thing this tier exists to say — so a failed forecast
    costs the next-high line and nothing else, and a failed observation still renders the
    forecast. Only losing the observation is an OUTAGE.
    """
    now = _utc(now)
    obs, obs_err = _read(station, OBS_QUERY, None, timeout, observations)
    pred6, _ = _read(station, PRED6_QUERY, None, timeout, predictions)
    hilo, hilo_err = _read(station, HILO_QUERY, now, timeout, predictions)
    a = anomaly(obs or [], pred6 or [])
    highs = next_highs(hilo or [], now, a["anomaly_ft"])
    c = chip(station, obs or [], highs, now)
    if obs_err:
        c |= {"reason": obs_err}
    return c | {"anomaly": a, "anomaly_note": ANOMALY_NOTE,
                "forecast_error": hilo_err, "observation_error": obs_err}


def recolor(chips: list[dict], margins: list[dict] | None = None) -> dict:
    """The data side of asset recoloring (ticket 15 renders it): which gauges are hot, and
    the Units assigned to them carrying their STATIC surge margin.

    The margin is never recomputed here — `margins` is `flood_coastal.unit_margins(root)`
    verbatim, so the number the panel recolors by is the same subtraction the exposure
    artifact published. Passing it in rather than reading it keeps this tier a parser: the
    caller already holds the table, and a per-cycle parquet read for a table that changes
    with the DEM epoch would be a re-read of a constant.

    A Unit with `surge_margin_ft: None` (404 of them — Cells with no point child, stops
    that are NoData in both the 2017 sample and the 15 m ring) rides through as None. It
    is NOT dropped and NOT zeroed: ticket 07's own warning is that 0.0 would place a Unit
    exactly at minor flood stage, the most alarming value the column can take.
    """
    hot = sorted(c["station"] for c in chips if c["state"] in (APPROACHING, EXCEEDING))
    out = {"gauges": hot, "margin_source": "flood_coastal.unit_margins (static, NAVD88 ft)"}
    if margins is None:
        return out | {"units": None}
    rows = [r for r in margins if r["gauge"] in hot]
    return out | {"units": rows, "n_units": len(rows),
                  "n_no_margin": sum(1 for r in rows if r["surge_margin_ft"] is None),
                  "n_below_minor": sum(1 for r in rows
                                       if (r["surge_margin_ft"] or 0) < 0)}


def coastal(now: datetime | None = None, timeout: float = TIMEOUT,
            margins: list[dict] | None = None) -> dict:
    now = _utc(now or datetime.now(timezone.utc))
    chips = [gauge(s, now, timeout) for s in sorted(GAUGES)]
    return {"source": "noaa_coops", "asof": now.isoformat(), "stage": STAGE,
            "chips": chips, "recolor": recolor(chips, margins)}


# ---- the winter-gate fetch --------------------------------------------------------
def parse_knyc(payload: dict) -> dict:
    """The KNYC observation ticket 11's winter gate is a pure function of.

    A missing temperature is None, never 0.0: the gate suppresses at or below 0.5 C, so a
    null read coerced to zero would suppress every tier on a warm day with a broken
    sensor. `qc` rides along — NWS marks observations V (validated), Z (preliminary),
    S/C (screened/coarse) — so the gate's caller can see what it is gating on.
    """
    p = (payload or {}).get("properties") or {}
    t = p.get("temperature") or {}
    return {"temp_c": t.get("value"), "qc": t.get("qualityControl"),
            "unit": t.get("unitCode"), "t": p.get("timestamp"),
            "text": p.get("textDescription"), "station": "KNYC"}


def winter_obs(now: datetime | None = None, timeout: float = TIMEOUT) -> dict:
    """One Central Park observation per cycle. The endpoint is a constant, not discovery:
    nothing here calls /points (which 301-redirects past 4 decimal places of coordinate)."""
    now = _utc(now or datetime.now(timezone.utc))
    out = {"source": "nws", "station": "KNYC", "asof": now.isoformat()}
    try:
        r = requests.get(NWS_OBS, timeout=timeout, headers={"User-Agent": NWS_UA})
        r.raise_for_status()
        obs = parse_knyc(r.json())
    except Exception as e:
        return out | {"status": "error", "temp_c": None, "stale": True,
                      "error": f"{type(e).__name__}: {e}"}
    t = _iso(obs["t"])
    age = round((now - _utc(t)).total_seconds() / 60, 1) if t else None
    # the winter gate suppresses tiers on this number; a day-old reading must not arrive
    # wearing the same "ok" as a fresh one. Ticket 11 decides what to do with `stale`.
    stale = age is None or not (-OBS_AHEAD_MIN <= age <= KNYC_STALE_MIN)
    return out | {"status": "stale" if stale else "ok", **obs, "age_min": age,
                  "stale": stale}


def _iso(s: str | None) -> datetime | None:
    """The NWS stamp. TypeError/AttributeError are caught alongside ValueError because this
    runs OUTSIDE winter_obs's try: a body whose `timestamp` is a dict rather than a string
    would otherwise take the whole tier down from the one line the error handling misses."""
    try:
        d = datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def live(now: datetime | None = None, margins: list[dict] | None = None) -> dict:
    """Both reads, independent: a CO-OPS outage never hides the winter observation."""
    now = _utc(now or datetime.now(timezone.utc))
    return {"coastal": coastal(now, margins=margins), "winter": winter_obs(now)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-margins", action="store_true",
                   help="skip the static margin table (the recolor set renders empty)")
    a = p.parse_args()
    check_shared_family()
    # the recolor criterion is data, so the CLI supplies the data rather than demonstrating
    # an empty hook: ticket 15 passes its own table, this prints against the real one.
    margins = None if a.no_margins else flood_coastal.unit_margins(Path(data_root()))
    out = live(margins=margins)
    if a.json:
        print(json.dumps(out, indent=1, default=str))
        return
    c = out["coastal"]
    print(f"coastal  stage={c['stage']}  asof {c['asof']}")
    for ch in c["chips"]:
        nh = ch.get("next_high")
        obs = f"{ch['observed_ft']:>6.2f} ft" if ch.get("observed_ft") is not None else "     --"
        print(f"  {ch['state']:<11} {ch['name']:<12} obs {obs} / minor "
              f"{ch.get('minor_navd88_ft')}  next high "
              + (f"{nh['ft']:.2f} ft in {nh['hours']:.1f} h"
                 f"{'' if nh['anomaly_applied'] else ' (harmonic only)'}" if nh else "--")
              + (f"  [{ch['reason']}]" if ch.get("reason") else ""))
        if ch.get("anomaly"):
            print(f"              anomaly {ch['anomaly']['anomaly_ft']} ft "
                  f"({ch['anomaly']['samples']} samples / {ch['anomaly']['span_min']} min)"
                  + (f" — {ch['anomaly']['why']}" if ch["anomaly"]["why"] else ""))
    rc = out["coastal"]["recolor"]
    print(f"  recolor gauges: {rc['gauges'] or 'none'}  units {rc.get('n_units')}"
          f"  below minor {rc.get('n_below_minor')}  no margin {rc.get('n_no_margin')}")
    w = out["winter"]
    print(f"winter   {w['status']}  KNYC {w.get('temp_c')} C  qc {w.get('qc')}  "
          f"age {w.get('age_min')} min  {w.get('error') or w.get('text') or ''}")


if __name__ == "__main__":
    main()
