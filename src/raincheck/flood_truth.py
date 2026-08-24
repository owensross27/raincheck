"""Truth tiers (flood-build ticket 13 / spec "Real-time detector"): FloodNet water
detections and MTA remove-water chips.

Both tiers are DISPLAY ONLY. Neither ever feeds the model — the flood-01 bar on the
FloodNet sensor bar as an input stands, and alert-derived features stay barred from the
exposure fit. This module fetches, parses and rules; ticket 15 joins geometry and renders.

FloodNet, measured against the live API (2026-08-23, and re-measured at build time):
  * An unbounded `order_by time desc` read is poisoned: deployment `only_wise_mule`
    stamps year 2080 and tops every "latest" query. Every read here is bounded to
    [now - 60 min, now + 2 min], and samples outside that window are dropped again after
    parsing so a future clock cannot re-enter through a widened query.
  * Rows with a null deployment_id exist (1,215 of 10,000 in one window) and are dropped.
  * Absolute depth is not a flooding signal: a DRY night showed standing offsets of
    17-372 mm. Water needs a rise, a run and an onset inside the window (RULE below).
  * 10 of the 422 sensors reporting depth are absent from deployments/flood entirely --
    including the two largest standing offsets (372 mm, 331 mm). No metadata means no
    point, no status and no caveat, so those sensors are dropped, not rendered.
  * The row cap is 10,000 per response, which is ~27 min of a 422-sensor minute cadence,
    so the effective window is usually shorter than 60 min. Truncation is reported, not
    hidden: the tier states the window it actually saw.

Run: python -m raincheck.flood_truth        (fetch and print both tiers now)
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from raincheck import duck, flood_alerts as fa
from raincheck.paths import data_root

# ---- FloodNet: frozen endpoints and query ----------------------------------------
GRAPHQL_URL = "https://api.floodnet.nyc/v1/graphql"
DEPLOYMENTS_URL = "https://api.floodnet.nyc/api/rest/deployments/flood"
# ONE bounded query per cycle. deployment_id is filtered server-side so the row cap is
# spent on renderable rows (12% of an unfiltered window was null-id).
DEPTH_QUERY = (
    "query Window($lo: timestamptz!, $hi: timestamptz!, $cap: Int!) {"
    " depth_data(where: {time: {_gte: $lo, _lte: $hi},"
    " deployment_id: {_is_null: false}},"
    " order_by: {time: desc}, limit: $cap)"
    " { deployment_id time depth_proc_mm } }"
)
WINDOW_MIN, AHEAD_MIN, ROW_CAP = 60, 2, 10_000
TIMEOUT = 3.0  # spec: every truth fetch has a hard 3 s timeout

# ---- FloodNet: the water rule (absolute depth is dead) ----------------------------
MIN_DEPTH_MM = 15    # latest sample must clear this
MIN_RISE_MM = 15     # ... and clear the window's own minimum by this much
MIN_RUN = 3          # ... for at least this many consecutive samples
MAX_AGE_MIN = 10     # ... with the newest sample this fresh (spec staleness budget)
# Statuses that mute a sensor. Measured vocabulary (440 deployments): good, good - fs,
# noisy, signal, low_charge, dead, needs_driverail, non-ota, retired, needs_sensor,
# hardware_issue, needs_ota_update, removal_requested. An UNKNOWN status is not muted --
# a new string must not silently hide detections.
BLOCKED_STATUS = frozenset({
    "dead", "retired", "removal_requested", "hardware_issue", "needs_sensor",
    "needs_driverail", "noisy",
})

# ---- FloodNet: fixed strings (the tier shows the network's own caveats) -----------
CITATION = ("FloodNet (NYU and CUNY) — Mydlarz et al. 2024, WRR; "
            "used under a non-commercial data agreement")
CAVEATS = ("snow can register as depth",
           "objects and animals under the sensor can register as depth",
           "sensors recalibrate nightly against a 3-night rolling median")
DRY_LABEL = "dry above curb height at the signpost"
RULE = (f"water detected = latest ≥ {MIN_DEPTH_MM} mm and a ≥ {MIN_RISE_MM} mm rise "
        f"over the window minimum, {MIN_RUN}+ consecutive samples above, onset inside "
        f"the window — never absolute depth")
NO_RAIN = "no concurrent rain in this sensor's Cell"


def window(now: datetime) -> tuple[str, str]:
    """The only window any read uses. +2 min of slack for sensors stamping slightly ahead."""
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return ((now - timedelta(minutes=WINDOW_MIN)).strftime(fmt),
            (now + timedelta(minutes=AHEAD_MIN)).strftime(fmt))


def fetch_depth(now: datetime, timeout: float = TIMEOUT) -> dict:
    lo, hi = window(now)
    r = requests.post(GRAPHQL_URL, timeout=timeout, json={
        "query": DEPTH_QUERY, "variables": {"lo": lo, "hi": hi, "cap": ROW_CAP}})
    r.raise_for_status()
    return r.json()


def fetch_deployments(root: Path, now: datetime, timeout: float = TIMEOUT) -> dict:
    """Deployment metadata, cached one file per UTC day: it carries the point, the name
    and the sensor status, and it changes on a scale of days, not cycles."""
    cache = Path(root) / "live" / "floodnet" / f"deployments_{now.date()}.json"
    if not cache.exists():
        r = requests.get(DEPLOYMENTS_URL, timeout=timeout)
        r.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(r.json()))
    return by_deployment(json.loads(cache.read_text()))


def by_deployment(payload: dict) -> dict:
    return {d["deployment_id"]: d for d in payload.get("deployments") or []
            if d.get("deployment_id")}


def _ts(s: str | None) -> datetime | None:
    try:
        t = datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def series(payload: dict, now: datetime) -> tuple[dict, dict]:
    """Response -> {deployment_id: [(time, depth_mm), ...] ascending} plus a read report.

    Null deployment ids, unparsable stamps and null depths are dropped, and so is every
    sample outside the bounded window — the 2080-clock sensor never survives parsing.
    """
    rows = ((payload or {}).get("data") or {}).get("depth_data") or []
    lo = now - timedelta(minutes=WINDOW_MIN)
    hi = now + timedelta(minutes=AHEAD_MIN)
    out: dict[str, list] = {}
    dropped = {"null_id": 0, "null_depth": 0, "out_of_window": 0}
    for r in rows:
        dep = r.get("deployment_id")
        if not dep:
            dropped["null_id"] += 1
            continue
        t, mm = _ts(r.get("time")), r.get("depth_proc_mm")
        if mm is None or t is None:
            dropped["null_depth"] += 1
            continue
        if not (lo <= t <= hi):
            dropped["out_of_window"] += 1
            continue
        out.setdefault(dep, []).append((t, float(mm)))
    for v in out.values():
        v.sort()
    seen = [t for v in out.values() for t, _ in v]
    return out, {
        "rows": len(rows), "dropped": dropped, "sensors": len(out),
        # the cap truncates the OLDEST end of the window, so say what was actually read
        "truncated": len(rows) >= ROW_CAP,
        "oldest": min(seen).isoformat() if seen else None,
        "newest": max(seen).isoformat() if seen else None,
    }


def sensor_state(samples: list, now: datetime) -> dict:
    """One sensor's window -> the rule's verdict and the numbers behind it."""
    t, depth = samples[-1]
    age = (now - t).total_seconds() / 60
    run = 0
    for _, mm in reversed(samples):
        if mm < MIN_DEPTH_MM:
            break
        run += 1
    floor = min(mm for _, mm in samples)
    # onset inside the window: a sample BELOW the threshold precedes the run. A standing
    # offset is above for the whole window and has no onset, which is the point.
    onset = samples[-run][0].isoformat() if 0 < run < len(samples) else None
    fresh = age <= MAX_AGE_MIN
    return {
        "depth_mm": depth, "rise_mm": round(depth - floor, 1), "floor_mm": floor,
        "run": run, "samples": len(samples), "age_min": round(age, 1),
        "fresh": fresh, "onset": onset,
        "water": bool(fresh and depth >= MIN_DEPTH_MM and depth - floor >= MIN_RISE_MM
                      and run >= MIN_RUN and onset is not None),
    }


def sensors(payload: dict, deployments: dict, now: datetime,
            wet_cells: set | None = None, cell_of: dict | None = None) -> tuple[list, dict]:
    """The renderable sensor list: one row per sensor with metadata, water or dry.

    A sensor absent from the deployment metadata is dropped (no point, no status, and it
    is where the largest standing offsets live). A blocked status renders nothing either;
    both drops are counted so the tier can say how many sensors it is not showing.
    """
    by_dep, report = series(payload, now)
    out, muted, unknown = [], 0, 0
    for dep, samples in sorted(by_dep.items()):
        meta = deployments.get(dep)
        if meta is None:
            unknown += 1
            continue
        status = meta.get("sensor_status")
        if status in BLOCKED_STATUS or meta.get("date_down"):
            muted += 1
            continue
        s = sensor_state(samples, now)
        cell = (cell_of or {}).get(dep)
        # concurrent own-Cell rain is a DISPLAY gate, never part of the rule: with no
        # wet-cell set supplied the gate is simply not evaluated, and says so.
        gated = bool(s["water"] and wet_cells is not None and cell not in wet_cells)
        point = (meta.get("location") or {}).get("coordinates")
        out.append({
            "deployment_id": dep, "name": meta.get("name"), "status": status,
            "deploy_type": meta.get("deploy_type"), "lon": point[0] if point else None,
            "lat": point[1] if point else None, "cell": cell,
            **s,
            "state": "water" if s["water"] else ("dry" if s["fresh"] else "stale"),
            "label": None if s["water"] else (DRY_LABEL if s["fresh"] else None),
            "display": bool(s["water"] and not gated),
            "gate": None if wet_cells is None else ("rain" if not gated else NO_RAIN),
        })
    report |= {"muted": muted, "unknown": unknown, "rendered": len(out)}
    return out, report


def floodnet(root: Path, now: datetime, wet_cells: set | None = None,
             cell_of: dict | None = None, timeout: float = TIMEOUT) -> dict:
    """The FloodNet tier. Any API error greys the tier rather than failing the cycle."""
    tier = {"source": "floodnet", "citation": CITATION, "caveats": list(CAVEATS),
            "rule": RULE, "window_min": WINDOW_MIN, "asof": now.isoformat()}
    try:
        payload = fetch_depth(now, timeout)
        meta = fetch_deployments(root, now, timeout)
    except Exception as e:  # network, timeout, HTTP, malformed JSON: all the same to the panel
        return tier | {"status": "error", "error": f"{type(e).__name__}: {e}",
                       "sensors": [], "detected": 0}
    rows, report = sensors(payload, meta, now, wet_cells, cell_of)
    return tier | {"status": "ok", "sensors": rows, "read": report,
                   "detected": sum(1 for r in rows if r["display"])}


# ---- MTA alert tier ---------------------------------------------------------------
CHIP_HOURS = 6  # how far back a chip can have been first seen and still be shown


def alert_rows(root: Path, now: datetime, hours: int = CHIP_HOURS) -> list[dict]:
    """The newest captured subway-alert rows: partition-bounded, then water-prefiltered."""
    capture = Path(root) / "archive" / "subway_alerts"
    if not capture.exists():
        return []
    cutoff = now - timedelta(hours=hours)
    con = duck.connect()
    cols = ("alert_id", "header", "description", "route_id", "fetched_at")
    rows = [dict(zip(cols, r)) for r in duck.table(con, capture).filter(
        f"date >= '{cutoff.date()}' AND fetched_at >= {cutoff.timestamp()} "
        "AND regexp_matches(upper(coalesce(\"header\", '') || ' ' "
        "|| coalesce(description, '')), 'WATER FROM THE TRACKS')"
    ).project('alert_id, "header", description, route_id, fetched_at').fetchall()]
    con.close()
    return rows


def chips(rows: list[dict], by_alias: dict, alias_pat, now: datetime) -> list[dict]:
    """Captured rows -> one chip per INCIDENT (ticket 02's event key).

    Per-event and per-complex truth only: two events can disagree about one complex
    (264048 active on Utica Av while 264063 says cleared) and both chips say what their
    own event says. Reconciling them is the spine's job (ticket 04), not this tier's.
    State comes from the NEWEST revision of the incident, because the MTA rewrites
    header/description in place under one alert_id between cycles.
    """
    out: dict[str, dict] = {}
    for o in fa.observations(rows, by_alias, alias_pat):
        chip = out.setdefault(o["event_id"], {
            "event_id": o["event_id"], "stations": [], "alert_ids": set(),
            "first_seen": o["first_seen"], "last_seen": o["last_seen"],
        })
        chip["stations"].append({"complex_id": o["complex_id"], "name": o["name"],
                                 "state": o["state"]})
        chip["alert_ids"].update(o["alert_ids"])
        for k, pick in (("first_seen", min), ("last_seen", max)):
            seen = [t for t in (chip[k], o[k]) if t is not None]
            chip[k] = pick(seen) if seen else None
    for chip in out.values():
        chip["alert_ids"] = sorted(chip["alert_ids"])
        # a chip is active while ANY of its stations is still being pumped out
        chip["state"] = (fa.ACTIVE if any(s["state"] == fa.ACTIVE for s in chip["stations"])
                         else fa.CLEARED_STATE)
        chip["age_min"] = (round((now.timestamp() - chip["first_seen"]) / 60, 1)
                           if chip["first_seen"] else None)
    return sorted(out.values(), key=lambda c: (c["first_seen"] or 0, c["event_id"]))


def mta(root: Path, now: datetime, hours: int = CHIP_HOURS) -> dict:
    root = Path(root)
    tier = {"source": "mta_alerts", "vocabulary": fa.LIVE_ANCHOR, "hours": hours,
            "asof": now.isoformat()}
    try:
        by_alias = fa.load_aliases(root)
        rows = alert_rows(root, now, hours)
        got = chips(rows, by_alias, fa.build_pattern(by_alias), now)
    except Exception as e:
        return tier | {"status": "error", "error": f"{type(e).__name__}: {e}", "chips": []}
    return tier | {"status": "ok", "chips": got, "rows": len(rows),
                   "active": sum(1 for c in got if c["state"] == fa.ACTIVE)}


def truth(root: Path | None = None, now: datetime | None = None,
          wet_cells: set | None = None, cell_of: dict | None = None) -> dict:
    """Both tiers, independent: one source's error never hides the other."""
    root = Path(root or data_root())
    now = now or datetime.now(timezone.utc)
    return {"floodnet": floodnet(root, now, wet_cells, cell_of), "mta": mta(root, now)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=None)
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    t = truth(a.root)
    if a.json:
        print(json.dumps(t, indent=1, default=str))
        return
    fn = t["floodnet"]
    print(f"floodnet {fn['status']}  detected {fn.get('detected', 0)}  "
          f"{fn.get('read') or fn.get('error')}")
    for s in fn.get("sensors", []):
        if s["state"] != "dry":
            print(f"  {s['state']:<6} {s['name'] or s['deployment_id']:<34} "
                  f"{s['depth_mm']:>6.0f} mm  rise {s['rise_mm']:>5.0f}  run {s['run']}")
    print(f"  {CITATION}")
    m = t["mta"]
    print(f"mta {m['status']}  chips {len(m.get('chips', []))}  "
          f"active {m.get('active', 0)}  rows {m.get('rows', m.get('error'))}")
    for c in m.get("chips", []):
        print(f"  {c['event_id']} {c['state']:<8} {c['age_min']:>7} min  "
              f"{', '.join(s['name'] for s in c['stations'])}")


if __name__ == "__main__":
    main()
