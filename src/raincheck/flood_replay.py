"""Flood-build ticket 12 (spec "Real-time detector"; testing seam 2): THE REPLAY GATE.

Runs ticket 11's LIVE detector — the same `flood_detect.cycle` a real 30 s tick calls —
hour by hour over every AORC-era union event on flood 06's precip, and reports what the
PROVISIONAL tier cutpoints would have cost. Nothing here re-fits, re-derives or corrects
anything: `walk`, `window_features`, `evaluate`, `tiers`, `latch` and `revisions` are
READS, the units and their static terms are `gold/flood_matrix`'s own rows, and the labels
are that table's `flooded` column. Two artifacts come out — `research/flood-12-replay.json`
and its rendered `.md` — and **the tier verdict is not one of them.** This module never
writes `research/flood-11-detector.json`; confirming the cutpoints or dropping v1 to
rank-only is Ross's call and bumps `detector_version` in his own session.

Five things this harness had to get right, each of them a way to publish a wrong number:

  * **`wet_by_hour` IS PASSED, ALWAYS.** `cycle` defaults the citywide series off the
    `cell_hours` it was handed, which is right in production (the caller has read the whole
    live table) and silently redefines "citywide" as "these Cells" the moment a replay
    hands it a subset. Every citywide count here is over the WHOLE 4,113-Cell grid.
  * **AORC's 168 permanently dark Cells are UNFORCED, not holed.** They carry NULL mm_1h in
    every hour of every month, so the NULL rows are passed through rather than filtered out
    in SQL: `window_features` puts them in `unforced_cells` and leaves them out of the
    coverage denominator. Filtering them away in the query would report coverage identically
    and `unforced_cells: 0`, which is a quieter lie.
  * **THE LIVE WALK IS NOT "FIXED" TO AGREE WITH THE OFFLINE WINDOW.** It agrees on about
    half the events and is usually one day EARLIER, because the evening before the
    storm-eve was also wet. The live anchor is observation-derived and the offline
    window_start is a calendar fact; the signed live-minus-offline feature deltas below are
    the measurement OF that difference, not a defect report.
  * **`cycle` ITERATES `cell_hours` TWICE** — once for the newest stamp, then again inside
    `window_features` — so a generator is consumed by the first pass and the Window comes
    back with no Cells at all, coverage 1.0 and nothing flagged. It looks exactly like a
    quiet night. Every call here passes a materialised list.
  * **A CROSS-UNIVERSE RATE IS DIVIDED BY ITS OWN BASE RATE** (flood 18). The detector
    publishes no entrance row, so its point-grain universe is bus stops (502,756 rows,
    base rate 0.00563) where flood 09's `per_event.point` is fit_point = bus stops AND
    entrances (783,351 rows, 0.00512). Both are published beside every point-grain number
    here; the Cell-grain universe is identical on both sides and needs no such care.

Run: make flood-replay                    (ONLY=<event_id> / LIMIT=<n> for a smoke run)
"""
import argparse
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from raincheck import duck
from raincheck import flood_detect as fd
from raincheck import flood_exposure as fe
from raincheck import flood_fits as ff
from raincheck.paths import REPO, data_root
from raincheck.precip_flood_era import FIT_ERA_LAST_YEAR

OUT = REPO / "research" / "flood-12-replay.json"
DOC = REPO / "research" / "flood-12-replay.md"
FITS = REPO / "research" / "flood-09-fits.json"

AORC = "aorc"     # flood 06's offline forcing, and the only src this replay walks
BATCH = "mrms"    # the Pass2 batch table (`make precip-cell SRC=mrms`)
LIVE = "live/precip_cell"     # the RadarOnly live table precip_live writes

# The published tier is the union over an event's cycles, not the last cycle's standing
# set: a tier LATCHES within a Window and the Window rolls once the city dries, so reading
# the state at window_end measures the calm after the storm. Ida's last cycle stands at
# zero flags with 264 mm in the peak Cell behind it.
UNION, PEAK = "union", "peak"

# The point-grain universes, and why there are two of them. See the module docstring.
POINT_NOTE = ("the detector publishes no entrance row (gates.entrances_publish_a_live_"
              "number = false), so its point-grain universe is bus stops; flood 09's "
              "per_event.point is fit_point = bus stops AND entrances. Different base "
              "rates, so every rate here is published with its own")


# ---- the event universe --------------------------------------------------------------

def events(con, root: Path | str) -> list[dict]:
    """Every AORC-era union event, oldest first, with the flag that says whether the fitted
    model has rows for it. The era rule is `precip_flood_era`'s constant, imported rather
    than re-typed: 2026 has no AORC year at all, so its 11 union events are not replayable
    on this forcing and are not in this universe.

    `in_matrix` is FALSE for the AORC-era events the fit universe excludes by class
    (coastal / mixed / snowmelt — the matrix is pluvial-only). Their Window walk replays
    exactly like everyone else's; their evaluation cannot, because `density_311_3y` is a
    per-(Cell, event) covariate the matrix build derives and re-deriving it would make this
    a rebuild rather than a replay.
    """
    rows = con.execute(
        f"""SELECT e.event_id, e.day_start, e.window_start_utc, e.window_end_utc,
                   e.event_class, e.n_days, (m.event_id IS NOT NULL) AS in_matrix
            FROM read_parquet('{root}/silver/flood_events/**/*.parquet') e
            LEFT JOIN (SELECT DISTINCT event_id
                       FROM read_parquet('{root}/gold/flood_matrix/**/*.parquet')) m
              ON m.event_id = e.event_id
            WHERE year(e.day_start) <= {FIT_ERA_LAST_YEAR}
            ORDER BY e.window_start_utc""").fetchall()
    return [{"event_id": r[0], "day_start": r[1], "window_start_utc": r[2],
             "window_end_utc": r[3], "event_class": r[4], "n_days": r[5],
             "in_matrix": bool(r[6])} for r in rows]


# ---- the forcing reads ----------------------------------------------------------------

def citywide(con, root: Path | str, lo: datetime, hi: datetime) -> dict:
    """The citywide wet-Cell COUNT per hour_end over the WHOLE grid — `cycle(wet_by_hour=)`.

    An hour with rows and no wet Cell is 0 and an hour with no rows at all is ABSENT, which
    is what `walk` reads as INSUFFICIENT_DATA. The two must not be flattened: "that evening
    was dry" and "we cannot see whether that evening was dry" are different answers.
    """
    rows = con.execute(
        f"""SELECT hour_end_utc, count(*) FILTER (WHERE mm_1h >= {fd.WET_MM})
            FROM read_parquet('{root}/silver/precip_cell_hourly/src={AORC}/**/*.parquet')
            WHERE hour_end_utc BETWEEN ? AND ? GROUP BY 1""", [lo, hi]).fetchall()
    return dict(rows)


def temps(con, root: Path | str, lo: datetime, hi: datetime) -> dict:
    """The citywide MEDIAN AORC 2 m temperature per hour, as the winter gate's observation.

    A REPLAY SUBSTITUTION, stated rather than hidden: live, `winter_gate` consumes flood
    14's Central Park (KNYC) reading, and there is no KNYC history on this root. The AORC
    field is the same forcing the Window features come from, on the same hours, so the
    substitution keeps the gate observation-derived instead of falling back to the calendar
    — which would suppress every event in a snowmelt month whether or not it was freezing.
    """
    rows = con.execute(
        f"""SELECT hour_end_utc, median(t2m_c)
            FROM read_parquet('{root}/silver/precip_cell_hourly/src={AORC}/**/*.parquet')
            WHERE hour_end_utc BETWEEN ? AND ? GROUP BY 1""", [lo, hi]).fetchall()
    return dict(rows)


def cell_rows(con, root: Path | str, lo: datetime, hi: datetime) -> dict:
    """{hour_end: [cell-hour dicts]} for the whole grid, NULLs INCLUDED (the 168 dark Cells
    are how `unforced_cells` gets counted). Grouped by hour so one slice per cycle costs a
    list comprehension rather than a query."""
    out: dict[datetime, list[dict]] = {}
    for cell, h, mm in con.execute(
            f"""SELECT cell, hour_end_utc, mm_1h
                FROM read_parquet('{root}/silver/precip_cell_hourly/src={AORC}/**/*.parquet')
                WHERE hour_end_utc BETWEEN ? AND ?""", [lo, hi]).fetchall():
        out.setdefault(h, []).append({"cell": cell, "hour_end_utc": h, "mm_1h": mm})
    return out


def units(con, root: Path | str, event_id: str) -> list[dict]:
    """THE OFFLINE UNIT SET, read from `gold/flood_matrix` rather than rebuilt: the same
    assets, the same static terms and the same `flooded` label the fit saw for this event.
    Only the three precip terms are recomputed live, which is the whole point."""
    cols = ("asset_id", "kind", "cell", "complex_id", "flooded", "elev_ft", "relief_ft",
            "stormwater_cat", "share_deep", "share_nuisance", "share_not_analyzed",
            "density_311_3y")
    rows = con.execute(
        f"""SELECT {', '.join(cols)}
            FROM read_parquet('{root}/gold/flood_matrix/**/*.parquet')
            WHERE event_id = ?""", [event_id]).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def offline_terms(con, root: Path | str, event_id: str) -> dict:
    """{cell: {the three log1p precip terms}} as `gold/flood_matrix` stored them for this
    event — the offline side of the signed live-minus-offline deltas."""
    rows = con.execute(
        f"""SELECT cell, log1p_precip_max_mm_1h, log1p_precip_total_mm,
                   log1p_antecedent_mm_24h
            FROM read_parquet('{root}/gold/flood_matrix/**/*.parquet')
            WHERE event_id = ? AND role = 'fit_cell'""", [event_id]).fetchall()
    return {r[0]: {"log1p_precip_max_mm_1h": r[1], "log1p_precip_total_mm": r[2],
                   "log1p_antecedent_mm_24h": r[3]} for r in rows}


# ---- the replay ------------------------------------------------------------------------

def hours(lo: datetime, hi: datetime) -> list[datetime]:
    """Every hour_end in [lo, hi], oldest first."""
    out, h = [], lo
    while h <= hi:
        out.append(h)
        h += timedelta(hours=1)
    return out


def slice_rows(by_hour: dict, anchor: datetime | None, now: datetime) -> list[dict]:
    """The Cell-hours a cycle needs: the antecedent block plus the Window, and NOTHING
    older — the same span the live table would hold. A LIST, never a generator: `cycle`
    reads `cell_hours` twice and the second pass would see an exhausted iterator."""
    a = anchor if anchor is not None else now - timedelta(hours=fd.ANTECEDENT_H)
    lo = a - timedelta(hours=fd.ANTECEDENT_H - 1)
    return [r for h in hours(lo, now) for r in by_hour.get(h, ())]


def worse(a: str, b: str) -> str:
    return max(a, b, key=fd.TIERS.index)


def replay(ev: dict, wet: dict, temp: dict, by_hour: dict, us: list[dict],
           art: dict, det: dict, score_version: str) -> dict:
    """One event, replayed hour by hour through `fd.cycle` with the state chained exactly
    as a live loop chains it.

    The readout is the UNION of tiers over the event's cycles, because that is what a
    subscriber would have received: a tier latches within its Window and the Window rolls
    once the city has been dry for long enough, so the standing set at window_end is the
    morning after. The peak standing set is published beside it — that is what a panel
    shows at one moment.
    """
    ws, we = ev["window_start_utc"], ev["window_end_utc"]
    nows = hours(ws + timedelta(hours=1), we)
    walks = {n: fd.walk(n, wet) for n in nows}
    state, states, union, peak, revs = None, Counter(), {}, Counter(), 0
    winter_cycles, feats_at, anchor_at = 0, None, None
    for n in nows:
        w = walks[n]
        states[w["state"]] += 1
        state = fd.cycle(state, n, slice_rows(by_hour, w["anchor"], n), us, art, det,
                         temp_c=temp.get(n), wet_by_hour=wet,
                         table_score_version=score_version)
        if state["window"]["state"] != fd.OK:
            continue
        states["feature_" + state["features"]["state"]] += 1
        revs += len(state["revisions"])
        if state["winter"]["suppressed"]:
            winter_cycles += 1
        standing = Counter()
        for u in state["units"]:
            if u["tier"] != fd.NONE:
                union[u["asset_id"]] = worse(union.get(u["asset_id"], fd.NONE), u["tier"])
                standing[u["tier"]] += 1
        for t, v in standing.items():
            peak[t] = max(peak[t], v)
        # The closing cycle is the last one whose live Window still covers the offline
        # window_start; past that the anchor has moved on and the deltas would compare
        # this event's features against the next Window's.
        if w["anchor"] is not None and w["anchor"] <= ws:
            feats_at, anchor_at = state["features"], w["anchor"]
    return {"cycles": len(nows), "states": dict(states), "union": union,
            "peak": dict(peak), "revisions": revs, "winter_cycles": winter_cycles,
            "features": feats_at, "anchor": anchor_at,
            "published": [u["asset_id"] for u in (state or {}).get("units", [])]}


def skill(us: list[dict], union: dict, kind: str) -> dict:
    """Per-kind volumes and skill for one event, at ELEVATED-and-above and at HIGH alone.

    `positives` is the matrix's own `flooded` for this event, so the denominators are the
    ones flood 09 scored against. `alert_rate` rides beside every rate because CSI and POD
    are monotone in it at a 0.5% base rate — a number quoted without it is partly a
    statement about how often the thing alarms.
    """
    rows = [u for u in us if u["kind"] == kind]
    pos = sum(1 for u in rows if u["flooded"])
    out = {"rows": len(rows), "positives": pos,
           "base_rate": pos / len(rows) if rows else None}
    for name, keep in ((fd.ELEVATED, (fd.ELEVATED, fd.HIGH)), (fd.HIGH, (fd.HIGH,))):
        tp = fp = 0
        for u in rows:
            if union.get(u["asset_id"]) in keep:
                tp, fp = (tp + 1, fp) if u["flooded"] else (tp, fp + 1)
        flagged = tp + fp
        out[name] = {
            "flagged": flagged, "tp": tp, "fp": fp,
            "alert_rate": flagged / len(rows) if rows else None,
            "pod": tp / pos if pos else None,
            "far": fp / flagged if flagged else None,
            "csi": tp / (flagged + pos - tp) if (flagged + pos - tp) else None,
        }
    return out


def deltas(feats: dict | None, offline: dict) -> dict:
    """Signed LIVE-MINUS-OFFLINE feature deltas over this event's `fit_cell` Cells.

    A positive total delta is the live Window being LONGER than the calendar one, which is
    a larger total by construction and not a bias. The terms are compared as stored — the
    matrix keeps them already log1p'd — so this is the same scale the coefficients act on.
    """
    if feats is None:
        return {}
    out: dict[str, dict] = {}
    for term in ("log1p_precip_max_mm_1h", "log1p_precip_total_mm",
                 "log1p_antecedent_mm_24h"):
        d = []
        for cell, want in offline.items():
            got = feats["cells"].get(cell)
            if got is not None and want[term] is not None:
                d.append(fd.precip_terms(got)[term] - want[term])
        out[term] = summarise(d)
    return out


def summarise(xs: list[float]) -> dict:
    """n / mean / the three quantiles / the sign split. Plain sorted-index quantiles: the
    tails are what matter here and interpolating them buys nothing."""
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    q = lambda p: s[min(len(s) - 1, int(p * len(s)))]  # noqa: E731
    return {"n": len(s), "mean": sum(s) / len(s), "p05": q(0.05), "median": q(0.5),
            "p95": q(0.95), "share_positive": sum(1 for x in s if x > 0) / len(s),
            "share_zero": sum(1 for x in s if x == 0) / len(s)}


def agreement(ev: dict, wet: dict) -> dict:
    """The live anchor at the event's PEAK citywide hour against the offline window_start,
    in whole NY days. Mid-storm is where flood 11 measured it and where the comparison
    means something: at window_end the Window has usually rolled to the dry morning after.
    """
    ws, we = ev["window_start_utc"], ev["window_end_utc"]
    win = hours(ws + timedelta(hours=1), we)
    seen = [(wet[h], h) for h in win if wet.get(h) is not None]
    if not seen:
        return {"peak_wet": None, "peak_hour": None, "state": fd.INSUFFICIENT_DATA,
                "day_delta": None}
    k, peak_h = max(seen, key=lambda t: (t[0], -t[1].timestamp()))
    w = fd.walk(peak_h, wet)
    delta = None
    if w["anchor"] is not None:
        delta = (w["anchor"].astimezone(fd.NY).date() - ws.astimezone(fd.NY).date()).days
    return {"peak_wet": k, "peak_hour": peak_h, "state": w["state"],
            "anchor": w["anchor"], "day_delta": delta,
            "citywide_rain": k >= fd.WET_CELLS_K}


# ---- the RadarOnly-vs-AORC ratio -------------------------------------------------------

def forcing_ratio(con, root: Path | str) -> dict:
    """What flood 11 left UNMEASURED: how the LIVE forcing scales against the OFFLINE one.

    It cannot be measured directly on this root and the reason is arithmetic, not effort:
    `src=aorc` ends 2025-12-31 and MRMS begins 2026-07-31, so the two share ZERO hours —
    asserted below rather than asserted about. What IS on disk is the pair that has never
    been compared before: `live/precip_cell` (MRMS **RadarOnly**, what the detector reads)
    against `silver/precip_cell_hourly/src=mrms` (MRMS **Pass2**, the gauge-corrected batch
    product), on the same Cells and the same hours, both aggregated by the SAME area-
    weighted `ref/cell_pixel` crosswalk with the same weight-sum guard — so the ratio is
    about the PRODUCT and not about two different ways of averaging it.

    RadarOnly/AORC is then that measured ratio times flood 06's published Pass2/AORC band,
    and it is published as a CHAIN with both links named. The direction is the part that
    decides something: below 1.0, `gates.own_cell_window_mm` (2.0 mm of raw RadarOnly) asks
    for marginally MORE true rain than the offline model was fitted on, so the gate is
    conservative and the display stays rank-only.

    The live table holds several rows per (cell, hour) — `precip_live` re-fetches the newest
    stamp every tick and catches up on missing ones — so the newest `fetched_at` wins, which
    is the same rule the live reader uses. Reading it without that dedupe multiplies every
    count by ~7 and turns the whole comparison into a statement about tick frequency.
    """
    a = f"read_parquet('{root}/silver/precip_cell_hourly/src={AORC}/**/*.parquet')"
    p = f"read_parquet('{root}/silver/precip_cell_hourly/src={BATCH}/**/*.parquet')"
    lv = f"read_parquet('{root}/{LIVE}/**/*.parquet', hive_partitioning = true)"
    overlap = con.execute(
        f"""SELECT count(*) FROM (SELECT DISTINCT hour_end_utc FROM {a}) x
            JOIN (SELECT DISTINCT hour_end_utc FROM {p}) y USING (hour_end_utc)""").fetchone()[0]
    con.execute(
        f"""CREATE OR REPLACE TEMP VIEW radaronly AS
            SELECT cell, hour_end_utc, mm_1h FROM (
              SELECT cell, strptime(valid_ts, '%Y-%m-%dT%H') AT TIME ZONE 'UTC' AS hour_end_utc,
                     mm_1h, row_number() OVER (PARTITION BY cell, valid_ts
                                               ORDER BY fetched_at DESC) rn
              FROM {lv}) WHERE rn = 1""")
    pair = (f"""FROM radaronly r JOIN {p} b USING (cell, hour_end_utc)
                WHERE r.mm_1h IS NOT NULL AND b.mm_1h IS NOT NULL""")
    tot = con.execute(
        f"""SELECT count(*), count(DISTINCT hour_end_utc), min(hour_end_utc), max(hour_end_utc),
                   sum(r.mm_1h), sum(b.mm_1h),
                   count(*) FILTER (WHERE b.mm_1h >= {fd.WET_MM}),
                   sum(r.mm_1h) FILTER (WHERE b.mm_1h >= {fd.WET_MM}),
                   sum(b.mm_1h) FILTER (WHERE b.mm_1h >= {fd.WET_MM}),
                   median(r.mm_1h / b.mm_1h) FILTER (WHERE b.mm_1h >= {fd.WET_MM})
            {pair}""").fetchone()
    by_hour = con.execute(
        f"""SELECT hour_end_utc, sum(r.mm_1h), sum(b.mm_1h),
                   count(*) FILTER (WHERE r.mm_1h >= {fd.WET_MM}),
                   count(*) FILTER (WHERE b.mm_1h >= {fd.WET_MM})
            {pair} AND b.mm_1h >= {fd.WET_MM} GROUP BY 1 HAVING sum(b.mm_1h) > 0
            ORDER BY 1""").fetchall()
    n, nh, lo, hi, rsum, bsum, wet_n, rwet, bwet, med = tot
    band = tuple(ff.SCALE_BAND)
    ratio_all = (rsum / bsum) if bsum else None
    ratio_wet = (rwet / bwet) if bwet else None
    return {
        "measurable_directly": False,
        "aorc_mrms_overlapping_hours": overlap,
        "why": ("src=aorc ends 2025-12-31 and src=mrms begins 2026-07-31: the two forcings "
                "share no hour on this root, so RadarOnly-vs-AORC is a CHAIN through Pass2 "
                "and is published as one"),
        "radaronly_over_pass2": {
            "paired_cell_hours": n, "paired_hours": nh,
            "from": lo, "to": hi,
            "wet_pairs": wet_n,
            "ratio_all_pairs": ratio_all,
            "ratio_wet_pairs": ratio_wet,
            "median_pair_ratio_wet": med,
            "per_wet_hour": [{"hour_end_utc": h, "radaronly_mm": r, "pass2_mm": b,
                              "ratio": (r / b) if b else None,
                              "radaronly_wet_cells": rw, "pass2_wet_cells": bw}
                             for h, r, b, rw, bw in by_hour],
        },
        "pass2_over_aorc": {"band": list(band), "source": "flood 06, via flood_fits.SCALE_BAND",
                            "measured_here": False},
        "radaronly_over_aorc": {
            "band": [ratio_wet * band[0], ratio_wet * band[1]] if ratio_wet else None,
            "basis": "ratio_wet_pairs x pass2_over_aorc",
            "direction": ("below 1.0 -> the raw 2.0 mm own-Cell gate asks for MORE true "
                          "rain than the offline fit saw, i.e. it is conservative"),
        },
        "limit": ("one storm carries the wet pairs (the live table holds ~90 hours and only "
                  "one of its hours-blocks rained), so this is a first measurement of the "
                  "product ratio and not a climatology of it"),
    }


# ---- the build --------------------------------------------------------------------------

def pooled(per_event: list[dict], kind: str) -> dict:
    """Pool an event-grain skill table the only way that is honest: sum the counts and
    recompute the rates. Averaging per-event PODs weights a 3-positive event the same as
    Ida, which is a statement about the event-size distribution."""
    out: dict = {"rows": 0, "positives": 0, "events": 0}
    for name in (fd.ELEVATED, fd.HIGH):
        out[name] = {"flagged": 0, "tp": 0, "fp": 0}
    for e in per_event:
        s = e["skill"].get(kind)
        if not s:
            continue
        out["events"] += 1
        out["rows"] += s["rows"]
        out["positives"] += s["positives"]
        for name in (fd.ELEVATED, fd.HIGH):
            for k in ("flagged", "tp", "fp"):
                out[name][k] += s[name][k]
    out["base_rate"] = out["positives"] / out["rows"] if out["rows"] else None
    for name in (fd.ELEVATED, fd.HIGH):
        d = out[name]
        d["alert_rate"] = d["flagged"] / out["rows"] if out["rows"] else None
        d["pod"] = d["tp"] / out["positives"] if out["positives"] else None
        d["far"] = d["fp"] / d["flagged"] if d["flagged"] else None
        den = d["flagged"] + out["positives"] - d["tp"]
        d["csi"] = d["tp"] / den if den else None
        d["lift_over_base_rate"] = (d["csi"] / out["base_rate"]
                                    if d["csi"] and out["base_rate"] else None)
    return out


def fits_reference() -> dict:
    """flood 09's pooled out-of-fold decisions and its per-event table, read from the
    published asset and NEVER recomputed here. These numbers are not superseded by this
    replay; they answer a different question (one global cut, out of fold) and they are
    the comparison set the recommendation is written against."""
    d = json.loads(FITS.read_text())
    ref = {"fits_version": d["fits_version"], "gate_branch": d["gate"]["branch"],
           "split": d["gate"]["split"], "per_event": d["per_event"], "pooled": {}}
    for role in ("cell", "point"):
        s = d["summary"][role]["model"][d["gate"]["split"]]
        base = s["positives"] / s["rows"]
        ref["pooled"][role] = {
            "rows": s["rows"], "positives": s["positives"], "base_rate": base,
            "alert_rate": s["alert_rate"], "tp": s["tp"], "fp": s["fp"],
            "pod": s["pod"], "far": s["far"], "csi": s["csi"],
            "lift_over_base_rate": s["csi"] / base}
    return ref


def build(root: Path | str | None = None, only: str | None = None,
          limit: int | None = None, out: Path = OUT, doc: Path = DOC) -> dict:
    rt: Path | str = root if root is not None else str(data_root())
    con = duck.connect()
    art, det = fe.coefficients(), fd.constants()
    score_version = table_score_version(con, rt)
    evs = events(con, rt)
    if only:
        evs = [e for e in evs if e["event_id"] == only]
    if limit:
        evs = evs[:limit]
    per_event, walk_only = [], []
    for i, ev in enumerate(evs, 1):
        ws, we = ev["window_start_utc"], ev["window_end_utc"]
        wet = citywide(con, rt, ws - timedelta(days=fd.CAP_DAYS + 2), we)
        agree = agreement(ev, wet)
        row = {"event_id": ev["event_id"], "day_start": ev["day_start"],
               "event_class": ev["event_class"], "n_days": ev["n_days"],
               "window_start_utc": ws, "window_end_utc": we,
               "in_matrix": ev["in_matrix"], "agreement": agree}
        if not ev["in_matrix"]:
            walk_only.append(row)
            print(f"[{i}/{len(evs)}] {ev['event_id']} walk-only ({ev['event_class']}) "
                  f"delta={agree['day_delta']}", flush=True)
            continue
        us = units(con, rt, ev["event_id"])
        anchors = [w for w in (fd.walk(n, wet) for n in
                               hours(ws + timedelta(hours=1), we)) if w["anchor"]]
        lo = (min(w["anchor"] for w in anchors) if anchors else ws) \
            - timedelta(hours=fd.ANTECEDENT_H)
        by_hour = cell_rows(con, rt, lo, we)
        temp = temps(con, rt, lo, we)
        r = replay(ev, wet, temp, by_hour, us, art, det, score_version)
        row |= {"cycles": r["cycles"], "cycle_states": r["states"],
                "revisions": r["revisions"], "winter_cycles": r["winter_cycles"],
                "published_units": len(r["published"]),
                "flags": {UNION: dict(Counter(t for t in r["union"].values())),
                          PEAK: r["peak"]},
                "flags_by_kind": {k: dict(Counter(
                    r["union"][u["asset_id"]] for u in us
                    if u["kind"] == k and u["asset_id"] in r["union"]))
                    for k in ("cell", "bus_stop", "complex")},
                "skill": {k: skill(us, r["union"], k)
                          for k in ("cell", "bus_stop", "complex")},
                "deltas": deltas(r["features"], offline_terms(con, rt, ev["event_id"])),
                "closing_anchor": r["anchor"],
                "unforced_cells": (r["features"] or {}).get("unforced_cells"),
                "coverage": (r["features"] or {}).get("coverage")}
        per_event.append(row)
        e = row["skill"]["cell"][fd.ELEVATED]
        print(f"[{i}/{len(evs)}] {ev['event_id']} cycles={r['cycles']} "
              f"delta={agree['day_delta']} cellE={e['flagged']} tp={e['tp']} fp={e['fp']}",
              flush=True)
    doc_out = {
        "estimand": det["estimand"], "table": det["table"],
        "detector_version": det["detector_version"],
        "score_version": art["score_version"], "table_score_version": score_version,
        "skew": fd.skew(art, score_version),
        "cutpoints": det["cutpoints"], "cutpoints_note": det["cutpoints_note"],
        "forcing": {"replayed": AORC, "live": det["forcing"]["product"],
                    "scale_band_applied": det["forcing"]["scale_band_applied"]},
        "universe": universe(evs, per_event, walk_only),
        "window_agreement": window_agreement(per_event + walk_only),
        "excluded": excluded(per_event, walk_only),
        "deltas": pooled_deltas(per_event),
        "flag_volume": {k: pooled(per_event, k) for k in ("cell", "bus_stop", "complex")},
        "point_universes_note": POINT_NOTE,
        "no_complex_skill_claim": det["display"]["no_complex_skill_claim"],
        "flood_09": fits_reference(),
        "forcing_ratio": forcing_ratio(con, rt),
        "per_event": per_event,
        "walk_only": walk_only,
        "verdict": {
            "question": "cutpoints confirmed, or v1 ships rank-only",
            "recorded_by": "[YOU] Ross, in his own session",
            "this_build_wrote_the_artifact": False,
            "note": ("this harness measures; it does not edit cutpoints.provisional, "
                     "cutpoints.confirmed_by or detector_version"),
        },
    }
    out.write_text(json.dumps(doc_out, indent=1, sort_keys=True, default=str) + "\n")
    doc.write_text(render(doc_out))
    return doc_out


def table_score_version(con, root: Path | str) -> str | None:
    """The score_version of the TABLE THAT WAS READ, never a constant — `fd.skew`'s rule.
    A `gold/flood_exposure` directory with no readable part file is UNBUILT and returns
    None, which refuses rather than claiming a match."""
    try:
        got = con.execute(
            f"""SELECT DISTINCT score_version
                FROM read_parquet('{root}/gold/flood_exposure/**/*.parquet')""").fetchall()
    except Exception:
        return None
    return got[0][0] if len(got) == 1 else None


def universe(evs: list[dict], per_event: list[dict], walk_only: list[dict]) -> dict:
    return {"aorc_era_events": len(evs), "replayed_with_evaluation": len(per_event),
            "walk_only": len(walk_only),
            "walk_only_reason": ("not in gold/flood_matrix — the fit universe is pluvial "
                                 "only, and density_311_3y is a per-(Cell, event) covariate "
                                 "the matrix build derives, so evaluating these would be a "
                                 "rebuild rather than a replay"),
            "walk_only_classes": dict(Counter(e["event_class"] for e in walk_only)),
            "era_rule": f"day_start.year <= {FIT_ERA_LAST_YEAR} (precip_flood_era)",
            "cycle_cadence_hours": 1,
            "readout": ("the UNION of tiers over an event's cycles — a tier latches within "
                        "its Window and the Window rolls when the city dries, so the set "
                        "standing at window_end is the morning after the storm")}


def window_agreement(rows: list[dict]) -> dict:
    """Does the live walk reproduce the offline window? Flood 11 measured 89 of 166 with
    the usual disagreement one day EARLIER. This is the same measurement over this
    build's own universe, and it is a CORROBORATION, not a defect table."""
    rain = [r for r in rows if r["agreement"].get("citywide_rain")]
    return {"events": len(rows), "with_citywide_rain": len(rain),
            # keys as STRINGS: a `None` delta (the walk found no anchor) cannot sort
            # beside an int, and JSON has no integer key anyway
            "day_delta": {str(k): v for k, v in sorted(Counter(
                r["agreement"]["day_delta"] for r in rain).items(),
                key=lambda kv: (kv[0] is None, kv[0]))},
            "agree_exactly": sum(1 for r in rain if r["agreement"]["day_delta"] == 0),
            "walk_state": dict(Counter(r["agreement"]["state"] for r in rain)),
            "note": ("a negative delta is the live anchor landing EARLIER than the "
                     "calendar window_start, because the evening before the storm-eve was "
                     "also wet; the live anchor is observation-derived and this is the "
                     "rule working")}


def excluded(per_event: list[dict], walk_only: list[dict]) -> dict:
    """Capped and INSUFFICIENT Windows: excluded from the skill numbers and COUNTED, with
    the reason. A cycle whose walk is not OK evaluates nothing — `cycle` returns before
    `window_features` — so the exclusion happens in the detector and this only counts it."""
    c = Counter()
    for e in per_event:
        for k, v in e["cycle_states"].items():
            c[k] += v
    return {"cycles_total": sum(e["cycles"] for e in per_event),
            "cycles_by_walk_state": {k: v for k, v in c.items()
                                     if not k.startswith("feature_")},
            "cycles_by_window_feature_state": {k[len("feature_"):]: v
                                               for k, v in c.items()
                                               if k.startswith("feature_")},
            "events_with_no_ok_cycle": sum(1 for e in per_event
                                           if not e["cycle_states"].get(fd.OK)),
            "walk_only_events": len(walk_only),
            "why": {fd.WINDOW_CAPPED: "six days walked with no citywide-dry 21:00 pad",
                    fd.INSUFFICIENT_DATA: "a pad stamp is missing: the walk stops rather "
                                          "than falling through to a day it can see",
                    fd.HOLES: "an interior Window hour is missing; the anchor still "
                              "stands and the Window is still evaluated"}}


def pooled_deltas(per_event: list[dict]) -> dict:
    """The signed live-minus-offline deltas, pooled over every replayed Cell of every
    replayed event — one row per term."""
    out = {}
    for term in ("log1p_precip_max_mm_1h", "log1p_precip_total_mm",
                 "log1p_antecedent_mm_24h"):
        xs = []
        for e in per_event:
            d = e["deltas"].get(term)
            if d and d.get("n"):
                xs.append((d["n"], d["mean"], d["median"]))
        out[term] = {"events": len(xs),
                     "cells": sum(n for n, _, _ in xs),
                     "mean_of_event_means": (sum(m for _, m, _ in xs) / len(xs)) if xs else None,
                     "median_of_event_medians": summarise([m for _, _, m in xs]).get("median"),
                     "events_with_positive_median": sum(1 for _, _, m in xs if m > 0),
                     "events_with_zero_median": sum(1 for _, _, m in xs if m == 0),
                     "events_with_negative_median": sum(1 for _, _, m in xs if m < 0)}
    # An event whose live anchor never sits at or before the calendar window_start has no
    # cycle whose Window covers this event, so it contributes no delta. Counted, not hidden.
    out["events_with_no_covering_window"] = sum(1 for e in per_event if not e["deltas"])
    out["reading"] = ("positive = the LIVE Window is longer than the calendar one, which is "
                      "a larger total by construction; the antecedent term moves the other "
                      "way because an earlier anchor freezes it earlier")
    return out


# ---- the rendered table -----------------------------------------------------------------

def pct(x: float | None, n: int = 2) -> str:
    return "-" if x is None else f"{100 * x:.{n}f}%"


def num(x: float | None, n: int = 4) -> str:
    return "-" if x is None else f"{x:.{n}f}"


def render(d: dict) -> str:
    """The published table. Every rate carries its own base rate and its own alert rate,
    because a CSI compared across universes without them ranks them backwards."""
    u, L = d["universe"], []
    L += [f"# flood-build 12 — the replay gate\n",
          f"Detector `{d['detector_version'][:12]}` over score `{d['score_version'][:12]}` "
          f"(table read: `{(d['table_score_version'] or 'ABSENT')[:12]}`, model tier "
          f"**{d['skew']['model_tier']}**). Forcing replayed: `{d['forcing']['replayed']}`; "
          f"live forcing `{d['forcing']['live']}`; scale band applied: "
          f"`{d['forcing']['scale_band_applied']}`.\n",
          f"Cutpoints under test: ELEVATED top {pct(d['cutpoints']['ELEVATED'], 0)} / HIGH "
          f"top {pct(d['cutpoints']['HIGH'], 0)} within kind, "
          f"`provisional: {d['cutpoints']['provisional']}`.\n",
          "## Universe\n",
          f"- {u['aorc_era_events']} AORC-era union events ({u['era_rule']})",
          f"- {u['replayed_with_evaluation']} replayed with evaluation; {u['walk_only']} "
          f"walk-only ({u['walk_only_classes']}) — {u['walk_only_reason']}",
          f"- readout: {u['readout']}\n",
          "## Window agreement (live walk vs the offline calendar window)\n",
          f"{d['window_agreement']['agree_exactly']} of "
          f"{d['window_agreement']['with_citywide_rain']} events with citywide rain land on "
          f"the offline `window_start`. Day deltas: `{d['window_agreement']['day_delta']}`. "
          f"{d['window_agreement']['note']}\n",
          "## Excluded and counted\n",
          f"- cycles: {d['excluded']['cycles_total']} total, by walk state "
          f"`{d['excluded']['cycles_by_walk_state']}`",
          f"- Window feature state over the OK cycles: "
          f"`{d['excluded']['cycles_by_window_feature_state']}`",
          f"- events with no OK cycle at all: {d['excluded']['events_with_no_ok_cycle']}\n",
          "## Flag volume at the provisional cutpoints\n",
          "| grain | rows | positives | base rate | tier | flagged | alert rate | TP | FP "
          "| POD | FAR | CSI | CSI/base |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for kind in ("cell", "bus_stop", "complex"):
        p = d["flag_volume"][kind]
        for tier in (fd.ELEVATED, fd.HIGH):
            t = p[tier]
            L.append(f"| {kind} | {p['rows']:,} | {p['positives']:,} | "
                     f"{pct(p['base_rate'], 3)} | {tier} | {t['flagged']:,} | "
                     f"{pct(t['alert_rate'], 2)} | {t['tp']:,} | {t['fp']:,} | "
                     f"{num(t['pod'])} | {num(t['far'])} | {num(t['csi'])} | "
                     f"{num(t['lift_over_base_rate'], 2)} |")
    L += ["", "### flood 09's pooled out-of-fold decisions, NOT superseded", "",
          "| grain | rows | positives | base rate | alert rate | TP | FP | POD | FAR | CSI "
          "| CSI/base |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for role, r in d["flood_09"]["pooled"].items():
        L.append(f"| {role} | {r['rows']:,} | {r['positives']:,} | {pct(r['base_rate'], 3)} "
                 f"| {pct(r['alert_rate'], 2)} | {r['tp']:,} | {r['fp']:,} | "
                 f"{num(r['pod'])} | {num(r['far'])} | {num(r['csi'])} | "
                 f"{num(r['lift_over_base_rate'], 2)} |")
    L += ["", f"{d['point_universes_note']}.", "",
          f"Complex rows are VOLUMES, never skill: {d['no_complex_skill_claim']}", "",
          "## Per-event POD and raw FP, beside flood 09's own per-event table", "",
          "This replay's columns are the ELEVATED-and-above union over the event's cycles;",
          "flood 09's are its out-of-fold decisions at one global cut. `cell` is the SAME",
          "universe on both sides; `bus_stop` and `point` are not (see the note above).", "",
          "| event | class | delta d | cell POD | cell FP | F09 cell POD | F09 cell FP "
          "| stop POD | stop FP | F09 point POD | F09 point FP |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    f9 = {role: {r["event_id"]: r for r in rows}
          for role, rows in d["flood_09"]["per_event"].items()}
    for e in d["per_event"]:
        c, b = e["skill"]["cell"][fd.ELEVATED], e["skill"]["bus_stop"][fd.ELEVATED]
        oc = f9["cell"].get(e["event_id"], {})
        op = f9["point"].get(e["event_id"], {})
        L.append(f"| {e['event_id']} | {e['event_class']} | "
                 f"{e['agreement']['day_delta']} | {num(c['pod'], 3)} | {c['fp']:,} | "
                 f"{num(oc.get('pod'), 3)} | {oc.get('fp', '-'):,} | {num(b['pod'], 3)} | "
                 f"{b['fp']:,} | {num(op.get('pod'), 3)} | {op.get('fp', '-'):,} |")
    L += ["", "## Signed live-minus-offline feature deltas", ""]
    for term, v in d["deltas"].items():
        if not isinstance(v, dict):
            continue
        L.append(f"- `{term}`: {v['cells']:,} Cells over {v['events']} events, "
                 f"median of event medians {num(v['median_of_event_medians'])}, "
                 f"event medians {v['events_with_negative_median']}- / "
                 f"{v['events_with_zero_median']}0 / {v['events_with_positive_median']}+")
    L.append(f"- {d['deltas']['events_with_no_covering_window']} events had NO cycle whose "
             f"live Window covers the calendar `window_start`, so they contribute no delta")
    L += [f"", f"{d['deltas']['reading']}", "", "## The RadarOnly-vs-AORC ratio", ""]
    fr = d["forcing_ratio"]
    rp = fr["radaronly_over_pass2"]
    L += [f"- direct measurement impossible: {fr['aorc_mrms_overlapping_hours']} hours "
          f"shared between `src=aorc` and `src=mrms`. {fr['why']}.",
          f"- **RadarOnly / Pass2 = {num(rp['ratio_wet_pairs'], 3)}** on "
          f"{rp['wet_pairs']:,} wet paired Cell-hours ({rp['paired_hours']} hours, "
          f"{rp['from']} .. {rp['to']}); all-pairs {num(rp['ratio_all_pairs'], 3)}, "
          f"median pair ratio {num(rp['median_pair_ratio_wet'], 3)}.",
          f"- Pass2 / AORC = `{fr['pass2_over_aorc']['band']}` "
          f"({fr['pass2_over_aorc']['source']}, not measured here).",
          f"- **RadarOnly / AORC = "
          f"{[round(x, 3) for x in fr['radaronly_over_aorc']['band']] if fr['radaronly_over_aorc']['band'] else '-'}"
          f"** ({fr['radaronly_over_aorc']['basis']}). "
          f"{fr['radaronly_over_aorc']['direction']}.",
          f"- limit: {fr['limit']}.", "",
          "## The verdict", "",
          f"**{d['verdict']['question']}** — {d['verdict']['recorded_by']}. "
          f"{d['verdict']['note']}.", ""]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="replay one event_id")
    ap.add_argument("--limit", type=int, help="replay the first N events (smoke run)")
    ap.add_argument("--render-only", action="store_true",
                    help="re-render the .md from the committed .json without replaying")
    a = ap.parse_args()
    if a.render_only:
        d = json.loads(OUT.read_text())
        DOC.write_text(render(d))
    else:
        d = build(only=a.only, limit=a.limit)
    p = d["flag_volume"]["cell"][fd.ELEVATED]
    print(f"{OUT.relative_to(REPO)}: {d['universe']['replayed_with_evaluation']} events "
          f"evaluated, cell ELEVATED+ {p['flagged']:,} flags "
          f"({p['tp']:,} TP / {p['fp']:,} FP), "
          f"RadarOnly/Pass2 "
          f"{num(d['forcing_ratio']['radaronly_over_pass2']['ratio_wet_pairs'], 3)}",
          flush=True)


if __name__ == "__main__":
    main()
