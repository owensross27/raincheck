"""The sensitivity battery around flood-build ticket 09's fits — the one-at-a-time sweeps,
the named contrasts, the coverage census and the MRMS-era replication status.

Split from `flood_fits` so the fits and the gate stay one readable module: nothing here
changes a fitted model, it re-runs one against a knob and publishes the delta.

The knobs that are NOT here are the point: the label radius {50, 100, 200} m and the
p99-union 311 threshold both redefine the event universe (they live in ticket 05's Sedona
join and ticket 04's spine derivation, upstream of `gold/flood_matrix`, which ticket 09
reads and never rebuilds). They are named as deferred in the published table and run as
ticket 18's outer replication.
"""
import json
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from raincheck import duck, flood_matrix as fm
from raincheck.flood_fits import (GATE_SPLIT, LAMBDAS, OP_THRESHOLD, SCALE_BAND, Rows, cv,
                                  evaluate, fanout_weights)

def sweep_configs(rows: Rows) -> list[dict]:
    """~25 one-at-a-time configs around the frozen primary, everything that can move
    WITHOUT redefining the event universe. The ones that redefine it — the label radius
    {50, 100, 200} m and the p99-union 311 threshold — are not runnable in fold: both are
    upstream of gold/flood_matrix (the radius is a Sedona ST_DWithin join inside ticket 05's
    build, the threshold is ticket 04's spine derivation), and this ticket reads the matrix.
    They are named as deferred in the published table and routed to ticket 18, whose whole
    shape is re-running 04 -> 09 under an alternate universe."""
    out = [{"name": f"lambda={lam}", "lam": lam} for lam in LAMBDAS]
    # one rung BEYOND the selection grid, so "the grid's top was chosen" is visible as a
    # measurement rather than a boundary artifact nobody checked
    out.append({"name": "lambda=1000 (beyond the selection grid)", "lam": 1000.0})
    groups = {"precip_max_1h": ["log1p_precip_max_mm_1h"],
              "precip_total": ["log1p_precip_total_mm"],
              "antecedent_24h": ["log1p_antecedent_mm_24h"]}
    if rows.role == "point":
        groups |= {"elevation": ["elev_ft"], "relief": ["relief_ft"],
                   "stormwater": ["sw_deep", "sw_nuisance", "sw_not_analyzed"],
                   "kind_indicator": ["is_bus_stop"]}
    else:
        groups |= {"stormwater_shares": ["share_deep", "share_nuisance",
                                         "share_not_analyzed"],
                   "history_311_density": ["density_311_3y"]}
    out += [{"name": f"drop {g}", "drop": cols} for g, cols in groups.items()]
    out.append({"name": "operating point: in-fold threshold (not in-fold alert rate)",
                "op": OP_THRESHOLD})
    return out


def run_sweeps(rows: Rows, split: str, lam: float, primary: dict,
               primary_run: dict) -> list[dict]:
    got = []
    for c in sweep_configs(rows):
        m = (evaluate(rows, primary_run, op=c["op"]) if c.get("op") else
             evaluate(rows, cv(rows, split, drop=c.get("drop", ()), lam=c.get("lam", lam))))
        got.append({"config": c["name"], "csi": m["csi"], "pod": m["pod"], "far": m["far"],
                    "pr_auc": m["pr_auc"], "delta_csi": m["csi"] - primary["csi"]})
    return got


def coverage(root: Path) -> dict:
    """The coverage-honesty census, RECOMPUTED against the landed spine. The drafted "115
    union event days" is superseded: silver/flood_events carries 206 events over 248
    event-days, 2010-03-13..2026-08-20."""
    con = duck.connect()
    ev = duck.table(con, root / "silver" / "flood_events")
    ev.create_view("e")
    row = con.execute("""
      SELECT count(*), sum(datediff('day', day_start, day_end) + 1),
             min(day_start), max(day_start),
             count(*) FILTER (WHERE event_class = 'pluvial'),
             count(*) FILTER (WHERE event_class = 'pluvial' AND year(day_start) <= ?),
             sum(datediff('day', day_start, day_end) + 1) FILTER (
                 WHERE event_class = 'pluvial' AND year(day_start) <= ?)
        FROM e""", [fm.FIT_ERA_LAST_YEAR, fm.FIT_ERA_LAST_YEAR]).fetchone()
    by_class = con.execute("SELECT event_class, count(*) FROM e GROUP BY 1 ORDER BY 2 DESC"
                           ).fetchall()
    con.close()
    return {"events": row[0], "event_days": row[1], "first": row[2].isoformat(),
            "last": row[3].isoformat(), "pluvial": row[4], "pluvial_fit_era": row[5],
            "pluvial_fit_era_days": row[6], "by_class": dict(by_class),
            "superseded": "the drafted 115 union event days"}


def era_replication(info: Mapping) -> dict:
    """The MRMS-era out-of-sample replication, reported as what it actually is today.

    gold/flood_matrix holds FIT-era rows only — AORC v1.1 publishes one Zarr per year and
    has no 2026 year, so the 2026 events cannot take fit-era precip at all. Of them exactly
    ONE falls on or after MRMS_FROM. A replication table over one event is not a
    replication, and inventing one from a single storm would be worse than saying so."""
    by_era = json.loads(info.get("gates", "{}")).get("events_by_era", {})
    n = by_era.get(fm.REPLICATION, 0)
    return {"status": "NOT COMPUTED", "events_by_era": by_era, "replication_events": n,
            "scale_band": list(SCALE_BAND),
            "reason": ("the matrix carries era='fit' rows only (AORC has no 2026 year), and "
                       f"the replication era holds {n} event as of the matrix build — "
                       "replication needs MRMS-era feature rows and more than one storm"),
            "caveat": (f"when it runs, every MRMS number is read under the measured "
                       f"{SCALE_BAND[0]}-{SCALE_BAND[1]} Pass2/AORC scale band, never "
                       f"like-for-like against an AORC-fit number")}


def _weight_sweep(r: Rows, split: str, lam: float, primary: dict) -> dict:
    w = fanout_weights(r)
    m = evaluate(r, cv(r, split, lam=lam, weights=w))
    return {"config": "weighted 1/fan-out (proxy: positives per event x Cell)",
            "csi": m["csi"], "pod": m["pod"], "far": m["far"], "pr_auc": m["pr_auc"],
            "delta_csi": m["csi"] - primary["csi"]}


def _contrasts(root: Path, r: Rows, runs: dict, models: dict, lam: float) -> dict:
    """The contrasts the ticket names by name: the history covariate with/without (under
    the location-blocked split, as the spec pins it), the bus-stop churn delta, and the
    pre/post-2014 split with its confound."""
    out = {}
    hist = ("density_311_3y",) if r.role == "cell" else ()
    if hist:
        out["history_covariate"] = {
            "with": models["model"][GATE_SPLIT]["csi"],
            "without": evaluate(r, cv(r, GATE_SPLIT, drop=hist, lam=lam))["csi"],
            "split": GATE_SPLIT}
    if r.role == "point":
        ent = r.extra["kind"] == "entrance"
        bus = ~ent
        run_ent = cv(r, GATE_SPLIT, lam=lam, keep=ent)
        out["bus_stop_churn"] = {
            "split": GATE_SPLIT,
            "pooled_all_rows": models["model"][GATE_SPLIT]["csi"],
            "pooled_on_entrance_rows": evaluate(r, runs[(r.role, GATE_SPLIT)], ent)["csi"],
            "pooled_on_bus_rows": evaluate(r, runs[(r.role, GATE_SPLIT)], bus)["csi"],
            "entrance_only_fit_on_entrance_rows": evaluate(r, run_ent, ent)["csi"],
            "bus_rows": int(bus.sum()), "bus_positives": int(r.y[bus].sum()),
            "bus_events": len(set(r.event_id[bus].tolist())),
            "method_note": (
                "the original churn sensitivity — refit on the bus-stop registry as it "
                "stood in each era — is DROPPED: no historical Picks exist locally "
                "(flood 08's build), so the era restriction is all there is. What is "
                "published instead is the delta between the pooled fit and the same fit "
                "without any bus row.")}
    con = duck.connect()
    ev = duck.table(con, root / "silver" / "flood_events")
    ev.create_view("e")
    pre = {e for (e,) in con.execute(
        "SELECT event_id FROM e WHERE year(day_start) < 2014").fetchall()}
    con.close()
    mask = np.array([e in pre for e in r.event_id])
    run_g = runs[(r.role, GATE_SPLIT)]
    out["pre_post_2014"] = {
        "split": GATE_SPLIT,
        "pre_2014": evaluate(r, run_g, mask), "post_2014": evaluate(r, run_g, ~mask),
        "confound": (
            "LABEL AVAILABILITY, not physics: the sources that mint positives do not reach "
            "back equally. Bus stops enter the universe in 2020 (flood 05's era rule), so "
            "every pre-2014 row here is an entrance or a Cell, and the 311/DEP record "
            "itself thins with age. A pre/post gap is at least as much a difference in who "
            "was reporting as a difference in what flooded.")}
    return out


