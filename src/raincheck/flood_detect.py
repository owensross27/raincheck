"""Flood-build ticket 11 (spec "Real-time detector"; testing seam 2): the live detector as
pure functions — the stateless backward Window walk, the live evaluation into within-kind
ranks and latched tiers, the winter gate, and the detector constants artifact.

THE MODEL IS A READ. There is no second model here and nothing is refitted: every score is
`flood_exposure.eta(art["models"][role], feats)` — THE function that built
`gold/flood_exposure` — called with live precip terms instead of event ones, so the offline
and the live number cannot drift apart. A score is the LINEAR PREDICTOR, never a
probability; the display value is a within-kind RANK across the CURRENT eta vector.

Nothing in this module opens a socket or reads the live table. `walk`, `window_features`,
`evaluate`, `tiers`, `winter_gate` and `cycle` take data and return data, which is what
lets ticket 12 replay them over history and ticket 15 render them per cycle.

Two decisions this ticket owned and settled, both recorded in the artifact:

  * **THE NWS STALENESS BUDGET.** The spec froze 15 min; KNYC reports HOURLY (flood 14
    measured 24 consecutive observations, all on the hour at :51), so a 15-min budget marks
    every observation stale and the winter gate never fires. Settled: the 15 min belongs to
    the per-cycle NWS ALERTS call, not to an hourly observation. The KNYC observation
    budget is **120 min** — two report intervals, so one missed hourly report degrades
    nothing and two do. `flood_live.KNYC_STALE_MIN` is asserted equal to the published
    budget, so the two cannot drift.
  * **THE SCALE BAND IS NOT APPLIED, and the reason is not deference.** `scale_band.
    pass2_over_aorc` = [0.86, 0.92] was measured for MRMS **Pass2** against AORC. The live
    forcing is MRMS **RadarOnly**, a different product whose bias against AORC nobody here
    has measured, so dividing by a Pass2 band would be applying a correction fitted to the
    wrong product. The display is rank-only, and the one absolute gate that survives
    (own-Cell Window total >= 2.0 mm) is applied to the raw RadarOnly total: if RadarOnly
    shares Pass2's low bias the gate is strictly CONSERVATIVE — a Cell needs marginally
    more true rain to raise a flag — which is the safe direction. The RadarOnly-vs-AORC
    ratio is owed, and ticket 12's replay is the place that can measure it.

Run: make flood-detector          (rebuild research/flood-11-detector.json; --skip-canary
                                   to skip the live MRMS filename probe)
"""
import argparse
import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from raincheck import flood_alerts as fa
from raincheck import flood_exposure as fe
from raincheck import flood_live as fl
from raincheck import flood_truth as ft
from raincheck import precip_live as pl
from raincheck.flood_spine import SNOWMELT_MONTHS
from raincheck.paths import REPO

DETECTOR = REPO / "research" / "flood-11-detector.json"
NY = ZoneInfo("America/New_York")

# ---- the Window rule ---------------------------------------------------------------
# The anchor is a 21:00 America/New_York boundary, which is exactly flood_spine's offline
# window_start (NY midnight - PAD_H): the live walk and the calendar window speak about the
# same instant. The Window is (anchor, now] and the anchor hour itself is ANTECEDENT, the
# same (open, close] convention flood_matrix's HOURS_SQL uses.
ANCHOR_LOCAL_H = 21
PAD_H = 3            # hour_ends anchor-2h, anchor-1h, anchor must all be citywide dry
CAP_DAYS = 6         # ... else walk back a day, this many times, then window_capped
ANTECEDENT_H = 24    # mm_24h frozen at the anchor: hour_ends [anchor-23h, anchor]

WET_MM = 1.0         # a Cell-hour is wet at or above this (CONTEXT.md's Wet hour cutoff)
# K, frozen here and measured rather than guessed (see the artifact's window._note):
# 5 Cells of the 4,113-Cell grid. Small on purpose. K has THREE jobs and they pull in
# opposite directions — it picks the anchor, it arms the "citywide active" gate, and it
# dims a flag — and the measurement says only one of them is sensitive to it. Over the
# whole 90,888-hour AORC record only 1,540 hours (1.7%) hold between 1 and 41 wet Cells at
# all, so the anchor walk barely notices K: of 166 AORC-era events with citywide rain, the
# walk lands on the offline window_start for 88 at K=5 and 89 at K=41. The gate DOES
# notice: 41 Cells is ~12 km2, enough to miss a convective core dumping 50 mm on one
# neighbourhood, which is the flash-flood case the detector exists for. So K is chosen
# small for the gate and costs nothing at the anchor. It is a COUNT, never a citywide max.
WET_CELLS_K = 5

CELL_WINDOW_MM = 2.0   # own-Cell Window total gate
DIM_AFTER_H = 3        # citywide below K for this many consecutive hours -> flags dim

# Window states. HOLES is about the INTERIOR of a built Window; INSUFFICIENT_DATA is about
# the pad, which is what decides whether there is a Window at all. Staleness is a third
# thing entirely (how old the newest stamp is) and lives in `staleness`.
OK, HOLES, INSUFFICIENT_DATA, WINDOW_CAPPED = "OK", "HOLES", "INSUFFICIENT_DATA", "WINDOW_CAPPED"

# ---- tiers (PROVISIONAL until ticket 12's replay gate) ------------------------------
NONE, ELEVATED, HIGH = "NONE", "ELEVATED", "HIGH"
TIERS = (NONE, ELEVATED, HIGH)
CUT = {ELEVATED: 0.10, HIGH: 0.02}   # top X% of the CURRENT within-kind eta vector
TIERS_PROVISIONAL = ("top 10% / top 2% within kind, provisional until ticket 12's replay "
                     "measures per-event false-positive volume; the alternative v1 is "
                     "rank-only")

# ---- the winter gate ---------------------------------------------------------------
FREEZE_C = 0.5
WINTER_LABEL = "fitted on rain — snow not modeled"
UNKNOWN_LABEL = "no Central Park temperature — snow not excluded"

# ---- staleness budgets, in minutes --------------------------------------------------
# precip from the spec's measured cadences; floodnet/coops from the modules that fetch
# them (asserted equal at build, so a budget cannot drift from its fetcher); nws_knyc_obs
# is this ticket's settlement, nws_alerts is where the spec's 15 min actually belongs.
PRECIP_FRESH_MIN, PRECIP_STALE_MIN = 90, 180
NWS_ALERTS_MIN = 15
FRESH, STALE, DOWN = "FRESH", "STALE", "DOWN"

# ---- the forcing: MRMS RadarOnly :00 stamps ONLY ------------------------------------
# The 2-min trailing stamps converge from ABOVE and would break the converges-from-below
# contract; Pass2 lags 60-90 min and is the BATCH product. Neither ever feeds the live
# path, and neither is distinguishable once a row is in live/precip_cell — the live table
# has no product column — so the filter has to run on the SOURCE name, which is what this
# pattern is and what the build canary probes.
MRMS_URL = pl.NODD + "/{product}/{d:%Y%m%d}/MRMS_{product}_{d:%Y%m%d}-{d:%H%M%S}.grib2.gz"
MRMS_NAME = "MRMS_{product}_{stamp}.grib2.gz"
LIVE_PRODUCT = pl.RADAR            # RadarOnly_QPE_01H_00.00
REJECTED_PRODUCTS = (pl.PASS2,)    # MultiSensor_QPE_01H_Pass2_00.00


def accepts(name: str) -> bool:
    """Is this MRMS object name an accepted live forcing input?

    Accepted: the RadarOnly hourly product stamped on the hour. Rejected, by contract and
    not by preference: any other product (Pass2 above all) and any 2-min trailing stamp.
    Written against the NAME because that is the only place the distinction survives —
    `live/precip_cell` carries cell / mm_1h / fetched_at and nothing that says which
    product wrote the row.
    """
    tail = name.rpartition("/")[2]
    if not (tail.startswith("MRMS_") and tail.endswith(".grib2.gz")):
        return False
    body = tail[len("MRMS_"):-len(".grib2.gz")]
    product, _, stamp = body.rpartition("_")
    # stamp is YYYYMMDD-HHMMSS: it is "on the hour" when MMSS is 0000, NOT when the whole
    # HHMMSS is — an == "000000" test accepts midnight and rejects every other hour.
    return (product == LIVE_PRODUCT and len(stamp) == 15 and stamp[8] == "-"
            and stamp[:8].isdigit() and stamp[9:].isdigit() and stamp[11:] == "0000")


# ---- hours -------------------------------------------------------------------------

def hour_ends(start: datetime, end: datetime) -> list[datetime]:
    """The hour_end labels in the HALF-OPEN interval (start, end] — flood_matrix's Window
    convention, so an hour stamped at Window open is antecedent and never in the Window."""
    h, out = start + timedelta(hours=1), []
    while h <= end:
        out.append(h)
        h += timedelta(hours=1)
    return out


def anchors(now: datetime, cap_days: int = CAP_DAYS) -> list[datetime]:
    """Candidate anchors newest first: the most recent 21:00 America/New_York boundary at
    or before `now`, then one per day back to the cap. DST is resolved from the NY-LOCAL
    date rather than by subtracting 24 h, so a spring-forward day still yields 21:00
    local — the two differ by an hour exactly once a year, which is when it matters."""
    loc = now.astimezone(NY)
    a = loc.replace(hour=ANCHOR_LOCAL_H, minute=0, second=0, microsecond=0)
    if a > loc:
        a -= timedelta(days=1)
    out = []
    for d in range(cap_days + 1):
        local = (a - timedelta(days=d)).date()
        out.append(datetime.combine(local, a.timetz().replace(tzinfo=None), NY)
                   .replace(tzinfo=NY).astimezone(timezone.utc))
    return out


def pad_hours(anchor: datetime) -> list[datetime]:
    """The PAD_H hour_ends immediately preceding the anchor instant, oldest first. hour_end
    == anchor covers (anchor-1h, anchor], which is entirely before the anchor, so all three
    are outside the Window the anchor opens."""
    return [anchor - timedelta(hours=h) for h in reversed(range(PAD_H))]


def wet_counts(cell_hours: Iterable[Mapping], wet_mm: float = WET_MM) -> dict[datetime, int]:
    """Citywide wet-Cell COUNT per hour_end — never a citywide max, which one hot Pixel
    could carry on its own. A NULL mm_1h is missing, not dry: it is simply not counted
    wet, and the coverage fraction is where its absence is reported."""
    out: dict[datetime, int] = {}
    for r in cell_hours:
        h = r["hour_end_utc"]
        mm = r.get("mm_1h")
        out[h] = out.get(h, 0) + (1 if mm is not None and mm >= wet_mm else 0)
    return out


def walk(now: datetime, wet_by_hour: Mapping[datetime, int | None],
         k: int = WET_CELLS_K, cap_days: int = CAP_DAYS) -> dict:
    """The stateless backward Window walk. No memory of the previous cycle is read: the
    anchor is a function of `now` and the citywide series alone, which is what makes a
    restarted detector agree with one that has been up for a week.

    A missing pad stamp is INSUFFICIENT_DATA and stops the walk where it stands — it does
    NOT fall through to an older anchor, because "we cannot see whether that evening was
    dry" is a different answer from "that evening was wet". Hold, degrade, never silently
    reset and never latch on a guess.
    """
    cands = anchors(now, cap_days)
    for i, anchor in enumerate(cands):
        pad = pad_hours(anchor)
        seen = {h: wet_by_hour.get(h) for h in pad}
        if any(v is None for v in seen.values()):
            return {"anchor": None, "state": INSUFFICIENT_DATA, "walked_days": i,
                    "missing_pad": [h for h, v in seen.items() if v is None],
                    "pad": {h: v for h, v in seen.items()}}
        if all(v is not None and v < k for v in seen.values()):
            return {"anchor": anchor, "state": OK, "walked_days": i,
                    "missing_pad": [], "pad": dict(seen)}
    return {"anchor": None, "state": WINDOW_CAPPED, "walked_days": len(cands) - 1,
            "missing_pad": [], "pad": {}}


def dry_run_hours(wet_by_hour: Mapping[datetime, int | None], now: datetime,
                  k: int = WET_CELLS_K) -> int | None:
    """How many consecutive hours, counting back from the newest hour_end at or before
    `now`, have been citywide below K. None when the newest hour is missing — an unknown
    hour cannot be counted dry, which is the whole point of HOLES being its own state."""
    h = now.replace(minute=0, second=0, microsecond=0)
    if h > now:
        h -= timedelta(hours=1)
    n = 0
    while True:
        v = wet_by_hour.get(h)
        if v is None:
            return n or None
        if v >= k:
            return n
        n += 1
        h -= timedelta(hours=1)


# ---- Window features ---------------------------------------------------------------

def window_features(cell_hours: Iterable[Mapping], anchor: datetime, now: datetime) -> dict:
    """Per-Cell running max mm_1h and Window total over (anchor, now], plus mm_24h frozen
    at the anchor — the same three terms `gold/flood_matrix` builds for an event, so the
    live and the offline feature vectors are the same object measured at different times.

    NULL counts as MISSING and never as zero: a Cell that reported nothing for an hour has
    an unknown hour, not a dry one, and summing it as zero is how a Window quietly
    under-reports a storm. Coverage is published per Cell and citywide, over both the
    Window and the antecedent block, so a consumer can tell a small total from a thin one.

    A Cell with NO value anywhere in the Window is UNFORCED, not holed, and is left out of
    the coverage denominator entirely — the two are different facts and conflating them
    reads as a broken feed. AORC has 168 permanently dark Cells of 4,113 (measured: every
    hour of 2021-09 has exactly 3,945 non-null Cells), so counting them as holes would
    make every offline replay report HOLES forever. Live MRMS has all 4,113.
    """
    win = set(hour_ends(anchor, now))
    ante = {anchor - timedelta(hours=h) for h in range(ANTECEDENT_H)}
    cells: dict[int, dict] = {}
    unforced: set = set()
    for r in cell_hours:
        h, mm = r["hour_end_utc"], r.get("mm_1h")
        if h not in win and h not in ante:
            continue
        cell = r["cell"]
        if mm is None:
            unforced.add(cell)            # provisional: cleared the moment a value lands
            continue
        unforced.discard(cell)
        c = cells.setdefault(cell, {"max_mm_1h": None, "total_mm": 0.0,
                                    "antecedent_mm_24h": 0.0, "window_hours": 0,
                                    "antecedent_hours": 0})
        if h in win:
            c["window_hours"] += 1
            c["total_mm"] += float(mm)
            c["max_mm_1h"] = (float(mm) if c["max_mm_1h"] is None
                              else max(c["max_mm_1h"], float(mm)))
        else:
            c["antecedent_hours"] += 1
            c["antecedent_mm_24h"] += float(mm)
    n_win, n_ante = len(win), len(ante)
    for c in cells.values():
        c["max_mm_1h"] = c["max_mm_1h"] if c["max_mm_1h"] is not None else 0.0
        c["window_coverage"] = c["window_hours"] / n_win if n_win else 1.0
        c["antecedent_coverage"] = c["antecedent_hours"] / n_ante
    present = sum(c["window_hours"] for c in cells.values())
    # A Window with no elapsed hours yet is COMPLETE, not holed: nothing is missing when
    # nothing is expected. Falling to 0.0 here painted the degrade state over every cycle in
    # the first hour of a Window — and a Window opens at 21:00 NY, so that fired nightly.
    cov = 1.0 if not n_win else (present / (n_win * len(cells)) if cells else 1.0)
    return {"cells": cells, "window_hours_expected": n_win,
            "antecedent_hours_expected": n_ante, "coverage": cov,
            "unforced_cells": len(unforced - set(cells)),
            "state": OK if cov >= 1.0 else HOLES,
            "anchor": anchor, "now": now}


def precip_terms(cell: Mapping) -> dict[str, float]:
    """The three live precip features, log1p'd once. The matrix stores these terms ALREADY
    log1p'd, so this is the only place the transform happens; expm1 before quoting mm."""
    return {"log1p_precip_max_mm_1h": math.log1p(cell["max_mm_1h"]),
            "log1p_precip_total_mm": math.log1p(cell["total_mm"]),
            "log1p_antecedent_mm_24h": math.log1p(cell["antecedent_mm_24h"])}


# ---- live evaluation ---------------------------------------------------------------

def unit_feats(unit: Mapping, precip: Mapping[str, float]) -> dict[str, float]:
    """One Unit's full feature vector: its static terms plus the Window's precip terms.
    `fe.dummies` does the stormwater coding (never re-spelled here, never imputed), and
    the entrances behind a complex score as entrances, so `is_bus_stop` is 0 for them."""
    kind = unit["kind"]
    if role_of(kind) == "cell":
        static = {f: float(unit[f]) for f in
                  ("share_deep", "share_nuisance", "share_not_analyzed", "density_311_3y")}
    else:
        static = {"elev_ft": float(unit["elev_ft"]), "relief_ft": float(unit["relief_ft"])}
        static |= fe.dummies(kind, unit["stormwater_cat"])
    return static | dict(precip)


def hexcell(cell: int) -> str:
    """An H3 Cell id is an int64 and JSON cannot carry one: 613229551394226175 is past 2^53,
    so a consumer reading numbers as doubles corrupts it silently. Every id that crosses a
    serving boundary goes as the same hex string `ref.py` already writes into `cell:<h3>`."""
    return format(cell, "x")


def role_of(kind: str) -> str:
    """An entrance is scored by the POINT model — it is a doorway, and the complex score is
    an aggregate of doorway scores. There is no entrance role and no entrance model."""
    return fe.KIND_MODEL["bus_stop"] if kind == "entrance" else fe.KIND_MODEL[kind]


def evaluate(art: Mapping, units: Sequence[Mapping], feats: Mapping) -> list[dict]:
    """Live eta for every score Unit, then the within-kind rank across the CURRENT vector.

    ENTRANCES NEVER PUBLISH A ROW. They are scored, because `complex_rule` is max over
    child entrance scores, and then they are rolled up and dropped — the artifact's own
    disclaimer (the independent complex set caught 1 of 118) is why a complex number is an
    aggregate of doorway scores and never a measured complex-grain claim.

    The display value is `rank`, the empirical CDF of the live eta inside the Unit's own
    kind (`fe.cume_dist`, the same function behind `score_index`). `art["cdf"].by_kind` is
    the STATIC view for dormant weather and is deliberately not consulted here: fed a live
    eta it reads ~0 in light rain and ties at the ceiling in a storm.
    """
    cells = feats["cells"]
    scored, by_complex = [], {}
    for u in units:
        if u["kind"] == "complex":
            continue                          # scored from its own doorways, below
        cell = cells.get(u["cell"])
        if cell is None:
            continue                          # no forcing for this Cell -> no live number
        e = fe.eta(art["models"][role_of(u["kind"])], unit_feats(u, precip_terms(cell)))
        if u["kind"] == "entrance":
            cur = by_complex.get(u["complex_id"])
            if cur is None or e > cur[0]:
                by_complex[u["complex_id"]] = (e, u["cell"])
            continue
        scored.append({"asset_id": u["asset_id"], "kind": u["kind"], "cell": u["cell"],
                       "eta": e})
    for u in units:
        # the registry's own complex row takes the max, exactly as flood_exposure's build
        # does. Its Cell for gating purposes is the SCORING DOORWAY's, so the score and the
        # own-Cell rain gate describe the same doorway rather than two different ones.
        got = by_complex.get(u.get("complex_id")) if u["kind"] == "complex" else None
        if got is not None:
            scored.append({"asset_id": u["asset_id"], "kind": "complex", "cell": got[1],
                           "eta": got[0]})
    for kind in sorted({s["kind"] for s in scored}):
        grp = [s for s in scored if s["kind"] == kind]
        for s, r in zip(grp, fe.cume_dist([s["eta"] for s in grp])):
            s["rank"] = r
    return sorted(scored, key=lambda s: (s["kind"], s["asset_id"]))


def tiers(scored: Sequence[Mapping], feats: Mapping, citywide_active: bool,
          cut: Mapping[str, float] | None = None) -> list[dict]:
    """The provisional tier for each Unit, before latching and before the winter gate.

    Two gates, and both are ANDed with the rank rather than replacing it: the Unit's own
    Cell must have taken at least CELL_WINDOW_MM in this Window, and the city must be
    actively raining. A rank alone would tier the top 2% of Units on a dry afternoon —
    something is always the maximum of a vector.
    """
    cut = dict(cut or CUT)
    cells = feats["cells"]
    out = []
    for s in scored:
        c = cells.get(s["cell"]) or {}
        gate = citywide_active and float(c.get("total_mm") or 0.0) >= CELL_WINDOW_MM
        tier = NONE
        if gate:
            if s["rank"] >= 1.0 - cut[HIGH]:
                tier = HIGH
            elif s["rank"] >= 1.0 - cut[ELEVATED]:
                tier = ELEVATED
        out.append(dict(s) | {"tier": tier, "gate_own_cell_mm": float(c.get("total_mm") or 0.0),
                              "gate_citywide_active": citywide_active})
    return out


def latch(previous: Mapping[str, str] | None, current: Sequence[Mapping]) -> list[dict]:
    """Tiers are LATCHED within a Window: a Unit that reached a tier keeps at least that
    tier until the Window rolls. The Window total is non-decreasing and both in-Window
    coefficients are positive, so the model itself only ever pushes a Unit up — the latch
    exists for the case the model cannot cover, a downward SERIES revision, which is logged
    and never clears a flag. `previous` is last cycle's {asset_id: tier}; None is a fresh
    Window, which is the only thing that clears one."""
    prev = dict(previous or {})
    out = []
    for s in current:
        was = prev.get(s["asset_id"], NONE)
        tier = max(s["tier"], was, key=TIERS.index)
        out.append(dict(s) | {"tier": tier, "latched": tier != s["tier"],
                              "tier_now": s["tier"]})
    return out


def revisions(previous: Mapping[int, float] | None, feats: Mapping) -> list[dict]:
    """Cells whose Window total went DOWN since the last cycle. Rain does not un-fall: a
    drop is the source revising its series, and it is logged rather than acted on. It never
    clears a flag — see `latch`, which is what actually enforces that."""
    prev = dict(previous or {})
    out = []
    for cell, c in sorted(feats["cells"].items()):
        was = prev.get(cell)
        if was is not None and c["total_mm"] < was - 1e-9:
            out.append({"cell": cell, "was_mm": was, "now_mm": c["total_mm"],
                        "delta_mm": c["total_mm"] - was})
    return out


# ---- the winter gate ---------------------------------------------------------------

def winter_gate(temp_c: float | None, now: datetime, stale: bool = False) -> dict:
    """A pure function of a SUPPLIED Central Park temperature (ticket 14 fetches it).

    At or below 0.5 C the tiers suppress and the model tier is labelled — the fit is on
    rain events and snow is not modeled. A missing or stale reading falls back to the
    CALENDAR rather than to either extreme: suppressing on absence would turn one dead
    third-party endpoint into a citywide detector outage in July, and rendering on absence
    would publish rain-model tiers through a February snowmelt. Outside flood_spine's
    snowmelt months a sub-freezing hour is not a live possibility, so the fallback costs
    nothing where it is not needed and holds where it is.
    """
    if temp_c is not None and not stale:
        cold = float(temp_c) <= FREEZE_C
        return {"suppressed": cold, "basis": "observed", "temp_c": float(temp_c),
                "label": WINTER_LABEL if cold else None}
    winter = now.astimezone(NY).month in SNOWMELT_MONTHS
    return {"suppressed": winter, "basis": "calendar", "temp_c": None,
            "reason": "stale" if stale else "absent",
            "label": (WINTER_LABEL if winter else None) if temp_c is None and not stale
            else (WINTER_LABEL if winter else UNKNOWN_LABEL)}


# ---- staleness and version skew ------------------------------------------------------

def staleness(newest: datetime | None, now: datetime) -> dict:
    """The forcing's age, dated at the READER against the stamp it carries. A missing
    stamp is DOWN, not fresh, and a stamp in the FUTURE is DOWN too — a clock that runs
    ahead of the source is not evidence of freshness."""
    if newest is None:
        return {"state": DOWN, "age_min": None}
    age = (now - newest).total_seconds() / 60.0
    state = DOWN if age < 0 or age > PRECIP_STALE_MIN else (
        FRESH if age <= PRECIP_FRESH_MIN else STALE)
    return {"state": state, "age_min": round(age, 1)}


def skew(art: Mapping, table_score_version: str | None) -> dict:
    """Does the live model tier agree with the table it is scoring against?

    Compared against the TABLE THAT WAS READ — the `score_version` column on every row of
    `gold/flood_exposure` and its parquet footer key — never against a constant compiled in
    here, because a constant only proves this module and the artifact agree with each
    other. An absent stamp REFUSES: "I could not tell" is not "they match".
    """
    ours = art["score_version"]
    ok = table_score_version is not None and table_score_version == ours
    return {"model_tier": "ok" if ok else "refused",
            "score_version": ours, "table_score_version": table_score_version,
            "reason": None if ok else ("no score_version on the table read"
                                       if table_score_version is None
                                       else "score_version skew: the artifact and the "
                                            "table are different models")}


def rolled(previous: Mapping | None, anchor: datetime | None,
           score_version: str, detector_version_: str) -> bool:
    """Does the Window roll this cycle? A new anchor rolls it, and so does either digest
    moving: a coefficient swap or a changed detector rule mid-Window would leave latched
    tiers standing that the running model never produced."""
    if not previous:
        return True
    return (previous.get("anchor") != (anchor.isoformat() if anchor else None)
            or previous.get("score_version") != score_version
            or previous.get("detector_version") != detector_version_)


# ---- one cycle -----------------------------------------------------------------------

def cycle(state: Mapping | None, now: datetime, cell_hours: Sequence[Mapping],
          units: Sequence[Mapping], art: Mapping | None = None,
          det: Mapping | None = None, temp_c: float | None = None,
          temp_stale: bool = False, table_score_version: str | None = None,
          wet_by_hour: Mapping[datetime, int | None] | None = None) -> dict:
    """One detector read, composed from the pure pieces above and itself pure: same inputs,
    same output, no clock and no filesystem. `state` is the previous cycle's return value
    (or None), which is the only thing carried across a cycle and is exactly what makes the
    latch and the revision log possible without a daemon.

    Both digests are stamped on every cycle, whatever the outcome, so a payload always says
    which model and which rules produced it — including when it produced nothing.
    """
    art = art if art is not None else fe.coefficients()
    det = det if det is not None else constants()
    dv = det["detector_version"]
    # CITYWIDE means the whole grid. Defaulting it off `cell_hours` is right in production,
    # where the caller has read the whole live table anyway — and wrong the moment someone
    # passes a SUBSET of Cells, which would silently redefine "citywide" as "these Cells".
    # A replay over a handful of Cells passes the real series here.
    wet = dict(wet_by_hour) if wet_by_hour is not None else wet_counts(cell_hours)
    w = walk(now, wet)
    newest = max((r["hour_end_utc"] for r in cell_hours), default=None)
    out = {"now": now, "score_version": art["score_version"], "detector_version": dv,
           "skew": skew(art, table_score_version),
           "staleness": staleness(newest, now), "window": w,
           "tiers_provisional": TIERS_PROVISIONAL}
    if w["state"] != OK:
        return out | {"units": [], "features": None, "winter": None, "revisions": [],
                      "dim": None, "latched": {}, "cell_totals": {}, "rolled": True}
    feats = window_features(cell_hours, w["anchor"], now)
    roll = rolled(state, w["anchor"], art["score_version"], dv)
    prev_tiers = None if roll else (state or {}).get("latched")
    prev_totals = None if roll else {int(c, 16): v for c, v
                                     in ((state or {}).get("cell_totals") or {}).items()}
    dry = dry_run_hours(wet, now)
    active = dry is not None and dry == 0
    scored = latch(prev_tiers, tiers(evaluate(art, units, feats), feats, active))
    winter = winter_gate(temp_c, now, temp_stale)
    if winter["suppressed"]:
        scored = [dict(s) | {"tier": NONE, "suppressed_by": "winter"} for s in scored]
    # THE BOUNDARY IS HERE. An H3 Cell id is an int64 and 613229551394226175 is past 2^53,
    # so any consumer reading it as a JSON number silently corrupts it — the repo already
    # fixed this once in ref.py and TRAPS carries it as a standing rule. The lower seams
    # (`window_features`, `evaluate`, `tiers`) keep the int because they join on it; `cycle`
    # is what tickets 12 and 15 serialize, so this is where it becomes hex, once.
    return out | {
        "units": [dict(s, cell=hexcell(s["cell"])) for s in scored],
        "features": feats, "winter": winter, "rolled": roll,
        "revisions": [dict(r, cell=hexcell(r["cell"])) for r in revisions(prev_totals, feats)],
        "dim": {"dimmed": dry is not None and dry >= DIM_AFTER_H, "dry_hours": dry},
        "latched": {s["asset_id"]: s["tier"] for s in scored if s["tier"] != NONE},
        "cell_totals": {hexcell(c): v["total_mm"] for c, v in feats["cells"].items()},
        "anchor": w["anchor"].isoformat(),
    }


# ---- the detector constants artifact -------------------------------------------------

# Everything that decides WHICH Units are flagged and WHEN. Deliberately NOT the whole
# file: `display` is labels and `*_note` is prose, and a reworded sentence must not roll a
# live Window. Published as `detector_version_scope` so a reader can audit the claim
# instead of taking it.
#
# THE RULE IS ABOUT LEAVES, NOT TOP-LEVEL KEYS, and the first draft got that wrong: it
# excluded `display` and `*_note` BY NAME while `cutpoints.basis`, `cutpoints.confirmed_by`,
# `forcing.stamp` and `canary.checks` sat as pure prose INSIDE digested dicts — so fixing a
# typo in one of them moved the digest, rolled every open Window through `rolled()` and
# cleared every latched flag mid-storm, which is exactly the failure the scoping exists to
# prevent. Those four moved into `display`. `test_the_digested_leaves_are_frozen` pins the
# whole leaf inventory, so adding a field inside a digested dict is a deliberate act. The limit, stated rather than papered over: like flood 10's
# score_version this hashes VALUES, so this module's own code rides only as labels —
# editing `walk` moves a decision without moving the digest. Tests hold that, not this.
DIGESTED = ("window", "cutpoints", "gates", "winter", "staleness_budgets", "throttles",
            "forcing", "vocabularies", "query_strings", "nws_ugc_zones", "canary")


def detector_version(c: Mapping) -> str:
    return hashlib.sha1(json.dumps({k: c[k] for k in DIGESTED},
                                   sort_keys=True, default=str).encode()).hexdigest()


def constants(path: Path = DETECTOR) -> dict:
    """THE detector's rule book (tickets 12, 15 and notify 08). One file, one call."""
    return json.loads(path.read_text())


def artifact() -> dict:
    """Build the constants dict. Every value that also lives in a python module is READ
    from that module here rather than re-typed, so the artifact cannot drift from the code
    that fetches — a mirrored constant is a constant that will disagree eventually."""
    c = {
        "estimand": "flooded_reported",
        "estimand_note": ("within 100 m of a report — the radius is a labelling choice "
                          "flood 18 measured as NOT optimal (lift per own base rate 11.13x "
                          "at 50 m / 6.05x at 100 m / 4.42x at 200 m), so no tier here "
                          "rests on a validated distance"),
        "table": "gold/flood_exposure",
        "live_table": "live/precip_cell",
        "window": {
            "anchor_local_hour": ANCHOR_LOCAL_H, "tz": "America/New_York",
            "pad_hours": PAD_H, "cap_days": CAP_DAYS, "antecedent_hours": ANTECEDENT_H,
            "wet_mm": WET_MM, "wet_cells_k": WET_CELLS_K,
        },
        "window_note": ("the anchor is flood_spine's offline window_start (NY midnight - "
                        "3 h) reached by observation instead of by calendar. K = 5 Cells of "
                        "4,113, measured: only 1,540 of 90,888 AORC hours hold 1-41 wet "
                        "Cells, so the anchor walk is nearly K-inert (88 of 166 events land "
                        "on the offline window_start at K=5, 89 at K=41) while the citywide "
                        "gate is not — 41 Cells is ~12 km2 and would miss a convective core. "
                        "The live walk agrees with the offline window_start on 89 of 166 "
                        "AORC-era events; the usual disagreement is one day EARLIER because "
                        "the evening before the storm-eve was also wet. That is the rule "
                        "working, not a defect — see ticket 12."),
        "cutpoints": {"ELEVATED": CUT[ELEVATED], "HIGH": CUT[HIGH], "provisional": True},
        "cutpoints_note": TIERS_PROVISIONAL,
        "gates": {"own_cell_window_mm": CELL_WINDOW_MM, "citywide_active": True,
                  "latched_within_window": True, "dim_after_dry_hours": DIM_AFTER_H,
                  "downward_revision_clears_a_flag": False,
                  "entrances_publish_a_live_number": False,
                  "complex_rule": "max over child entrance scores"},
        "winter": {"freeze_c": FREEZE_C,
                   "unknown_fallback_months": list(SNOWMELT_MONTHS)},
        "staleness_budgets": {
            "precip_fresh_min": PRECIP_FRESH_MIN, "precip_stale_min": PRECIP_STALE_MIN,
            "floodnet_min": ft.MAX_AGE_MIN, "coops_min": fl.OBS_STALE_MIN,
            "nws_knyc_obs_min": fl.KNYC_STALE_MIN, "nws_alerts_min": NWS_ALERTS_MIN,
            "clock_ahead_min": fl.OBS_AHEAD_MIN,
        },
        "staleness_budgets_note": ("SETTLED HERE (ticket 11 owned this): the spec's 15-min "
                                   "NWS budget belongs to the per-cycle ALERTS call, not to "
                                   "the KNYC observation, which publishes HOURLY at :51 "
                                   "(flood 14 measured 24 consecutive obs). The observation "
                                   "budget is two report intervals — one missed hourly "
                                   "report degrades nothing, two do. At 15 min the winter "
                                   "gate could never fire."),
        "throttles": {"floodnet_s": 120, "coops_s": 360, "nws_s": 300,
                      "fetch_timeout_s": fl.TIMEOUT},
        "forcing": {
            "product": LIVE_PRODUCT, "rejected_products": list(REJECTED_PRODUCTS),
            "url": MRMS_URL, "name": MRMS_NAME, "retention_days": 7,
            "scale_band_applied": False,
        },
        "forcing_note": ("2-min trailing stamps converge from ABOVE and would break the "
                         "converges-from-below contract; Pass2 lags 60-90 min and is the "
                         "batch product. scale_band.pass2_over_aorc was measured on PASS2, "
                         "and the live forcing is RadarOnly, so no band is applied to "
                         "anything: the display is rank-only and the one absolute gate "
                         "(2.0 mm) reads the raw total, where a low bias makes it "
                         "conservative. The RadarOnly-vs-AORC ratio is UNMEASURED and owed "
                         "to ticket 12's replay."),
        "vocabularies": {
            "remove_water_live": fa.LIVE_ANCHOR, "remove_water_legacy": fa.LEGACY_ANCHOR,
            "cleared": fa.CLEARED.pattern, "incident_key": list(fa.INCIDENT_KEY),
            "floodnet_blocked_status": sorted(ft.BLOCKED_STATUS),
        },
        "query_strings": {
            "coops_obs": fl.OBS_QUERY, "coops_pred6": fl.PRED6_QUERY,
            "coops_hilo": fl.HILO_QUERY, "coops_url": fl.COOPS,
            "coops_begin_fmt": fl.BEGIN_FMT, "nws_knyc_obs": fl.NWS_OBS,
            "floodnet_graphql": ft.GRAPHQL_URL, "floodnet_deployments": ft.DEPLOYMENTS_URL,
        },
        "nws_ugc_zones": None,
        "nws_ugc_zones_note": ("OWED, deliberately null rather than guessed. No NWS-alert "
                               "fetch exists in this repo yet (13 is FloodNet+MTA, 14 is "
                               "coastal+winter), so the list has no consumer, and the five "
                               "NYC zone codes are not written down anywhere here. The "
                               "ticket that first fetches api.weather.gov alerts verifies "
                               "them against the live API and fills this in; inventing five "
                               "NYZ codes would be a canary that can never fail."),
        # The canary's OUTCOME is deliberately not in here. It is a build gate, and a probe
        # result carries a wall-clock stamp, which would move detector_version on every
        # build and make the artifact irreproducible — the pattern is the frozen thing.
        "canary": {"pattern": MRMS_URL, "product": LIVE_PRODUCT},
        "canary_note": ("the MRMS RadarOnly :00 filename pattern still resolves against the "
                        "live source; run at build, never in a cycle"),
        # DISPLAY IS EVERY STRING A HUMAN READS AND NO CODE BRANCHES ON, and it is out of
        # the digest for the same reason flood 10 left the flag vocabulary out of
        # score_version: renaming a tier must never roll a live Window. The names still
        # cannot drift — they are `fd.TIERS` and the module's state constants, pinned by
        # tests; what is not pinned is the digest.
        "display": {"tier_labels": {ELEVATED: "elevated", HIGH: "high", NONE: "not flagged"},
                    "tiers": list(TIERS),
                    "cutpoint_basis": "within-kind rank of the CURRENT live eta vector",
                    "cutpoints_confirmed_by": "flood-build ticket 12",
                    "window_interval": "(anchor, now]",
                    "window_states": [OK, HOLES, INSUFFICIENT_DATA, WINDOW_CAPPED],
                    "precip_states": [FRESH, STALE, DOWN],
                    "forcing_stamp": "on the hour only (HHMMSS = HH0000)",
                    "winter_label": WINTER_LABEL, "winter_unknown_label": UNKNOWN_LABEL,
                    "no_complex_skill_claim": (
                        "a complex score is an aggregate of doorway scores; the independent "
                        "complex-grain set caught 1 of 118 positives, so no complex-grain "
                        "skill is claimed anywhere"),
                    "within_cell": ("live ordering inside a Cell is purely static — every "
                                    "Unit in a Cell shares one forcing")},
        "detector_version_scope": list(DIGESTED),
        "detector_version_note": ("sha1 over the keys above — what decides WHICH Units are "
                                  "flagged and WHEN — and deliberately not over `display` "
                                  "or the `_note` prose, so a reworded sentence never rolls "
                                  "a live Window. Like flood 10's score_version it hashes "
                                  "VALUES: this module's code rides only as labels, so "
                                  "editing `walk` moves a decision without moving the "
                                  "digest. The tests hold that, not the stamp."),
    }
    return c | {"detector_version": detector_version(c)}


def canary(timeout: float = 10.0) -> str:
    """Build-time only: does the MRMS RadarOnly :00 filename pattern still resolve against
    the live source? A HEAD, not a download. This is the one thing in this module that
    opens a socket and it never runs at import or in a cycle."""
    import requests

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    for back in range(1, 6):
        url = MRMS_URL.format(product=LIVE_PRODUCT, d=now - timedelta(hours=back))
        if not accepts(url):
            raise RuntimeError(f"the frozen MRMS pattern builds a name our own filter "
                               f"rejects: {url}")
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return url
    raise RuntimeError(f"MRMS canary: no RadarOnly :00 object resolved in the 5 hours "
                       f"before {now:%Y-%m-%dT%H}Z under {MRMS_URL}")


def build(out: Path = DETECTOR, skip_canary: bool = False) -> dict:
    probed = None if skip_canary else canary()   # raises, and that IS the build failing
    c = artifact()
    out.write_text(json.dumps(c, indent=1, sort_keys=True, default=str) + "\n")
    if probed:
        print(f"canary ok: {probed}", flush=True)
    return c


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-canary", action="store_true",
                    help="skip the live MRMS filename probe (offline builds)")
    a = ap.parse_args()
    c = build(skip_canary=a.skip_canary)
    print(f"{DETECTOR.relative_to(REPO)}: detector_version {c['detector_version'][:12]}, "
          f"K={c['window']['wet_cells_k']} cells, tiers PROVISIONAL until ticket 12",
          flush=True)


if __name__ == "__main__":
    main()
