"""Flood-build ticket 07: the coastal rule layer — `surge_margin_ft`.

Coastal exposure is arithmetic, not a model. Every scored Unit gets

    surge_margin_ft = elevation(NAVD88 ft) - assigned gauge's minor flood stage(NAVD88 ft)

with the gauge assigned by geodesic nearest of {Battery, Kings Point, Sandy Hook}. A
negative margin means the Unit sits below the water level at which its own gauge is
already in minor flood. ~15 coastal events in the label era cannot fit a model; this is
the layer that states surge risk without pretending otherwise.

Nothing here is stored. The margin is a pure function of `silver/asset_features` and the
frozen constants below, so ticket 10 calls `unit_margins()` when it writes
`gold/flood_exposure` rather than joining a fourth table that could drift out of step
with the elevations it is derived from.

Two disciplines this module owns:

  * DATUM. Elevations are NAVD88 US survey feet; CO-OPS publishes flood stages on STATION
    DATUM, an arbitrary per-station benchmark. Subtracting the published stage from a
    NAVD88 elevation without converting is the mistake that turns 3 below-minor entrances
    into 103 (`datum_sanity`). Every threshold here is converted once, at the definition.
  * ONE FROZEN STAGE. `STAGE` is chosen once for the whole effort and shared verbatim with
    the detector's coastal tier (ticket 14). `check_shared_thresholds` asserts the spine's
    own frozen pair still equals this module's for the two stations they share, so the
    number a coastal event-day is cut on and the number a margin is measured against can
    never diverge silently.

Run: make flood-coastal   (python -m raincheck.flood_coastal [--skip-canary])
"""
import json
import sys
import urllib.request
from pathlib import Path

import pyarrow.parquet as pq
import shapely
from pyproj import Geod

from raincheck import features, flood_spine, ref
from raincheck.paths import data_root

GEOD = Geod(ellps="WGS84")

# ---- the frozen gauge constants ---------------------------------------------------
# Coordinates, flood stages and NAVD88 offsets all from each station's own CO-OPS mdapi
# resources ({station}.json, floodlevels.json, datums.json), verified 2026-08-23 and held
# by `canary()`. Stages are FEET ON STATION DATUM; offsets are the NAVD88 datum value on
# that same station datum, so NAVD88 stage = stage - offset.
#
# Only these three of the six stations with populated flood levels sit in or near NY
# Harbour / western Long Island Sound; Bridgeport, New Haven and New London are
# Connecticut-shoreline stations and would never be the geodesic nearest for an NYC asset.
#
# KINGS POINT NWS/NOS INVERSION, recorded where the constant is defined: Kings Point's
# published nws_moderate (23.39 ft STND) sits BELOW its own nos_moderate (23.55) — real
# NOAA-published data, re-fetched and reproducible, and unique among the six stations
# checked. It does not touch this layer, which reads the minor stage only, but any later
# cross-station rule that assumes NWS and NOS stages are monotonic in the same direction
# will be wrong here. Do not "fix" it.
STAGE = "nws_minor"  # frozen ONCE for the whole effort: this layer, and ticket 14's tier
GAUGES = {
    "8518750": {"name": "The Battery", "lat": 40.700554, "lon": -74.01417,
                "nws_minor_stnd_ft": 10.49, "navd88_offset_ft": 6.06},
    "8516945": {"name": "Kings Point", "lat": 40.8103, "lon": -73.7649,
                "nws_minor_stnd_ft": 22.89, "navd88_offset_ft": 17.09},
    "8531680": {"name": "Sandy Hook", "lat": 40.4669, "lon": -74.0094,
                "nws_minor_stnd_ft": 9.21, "navd88_offset_ft": 5.33},
}
# datums.json publishes the offset to 2 dp; the offset CO-OPS actually applies to a
# `datum=NAVD` request is the unrounded one (the Battery's is 6.063, not 6.06 — measured).
# The gap is at most 0.005 ft = 1.5 mm, four hundred times smaller than the DEM's own
# 0.88 m epoch sigma, and using the published value is what lets `canary()` compare frozen
# to published as an equality rather than a tolerance.
MDAPI = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/{station}/{res}"

# Jamaica Bay and the Rockaways have NO CO-OPS gauge (flood_spine records the same blind
# spot for the event trigger). Assets there are assigned to whichever of the three is
# geodesically nearest and their margins carry that gauge's stage, which is a substitution,
# not a measurement — `gauge_km` rides on every row so the distance is never hidden.

# Frozen real-data counts, asserted blocking on the real root (tests pass expect=None).
# The datum pair is the load-bearing one: 3 is the count of entrances below the Battery's
# minor stage under NAVD88 discipline, 103 is the same count computed by the naive
# STND-vs-NAVD comparison. If those two ever coincide, the conversion has been lost.
EXPECT = {"units": 15166, "complex": 445, "bus_stop": 13370, "cell": 1351,
          "datum_navd88": 3, "datum_naive_stnd": 103}


def minor_navd88_ft(station: str) -> float:
    """The one conversion in this module: published minor stage, station datum -> NAVD88."""
    g = GAUGES[station]
    return round(g["nws_minor_stnd_ft"] - g["navd88_offset_ft"], 2)


def assign(lon: float, lat: float) -> tuple[str, float]:
    """Geodesic nearest gauge -> (station, distance km). Ties break on station id, which
    is deterministic and cannot happen at 1e-9-degree asset coordinates anyway."""
    d = {s: GEOD.inv(lon, lat, g["lon"], g["lat"])[2] for s, g in GAUGES.items()}
    station = min(sorted(d), key=lambda s: d[s])
    return station, d[station] / 1000.0


def check_shared_thresholds() -> None:
    """The stage is frozen once. `flood_spine` cuts coastal event-days on its own frozen
    pair; this layer measures margins against the same published numbers. Two copies of a
    number are two chances to change one — so the build asserts they are equal for every
    station both modules name, and a Sandy Hook added to the spine's triggers (or a stage
    changed here) fails the build instead of quietly measuring against two definitions."""
    assert STAGE == "nws_minor", STAGE  # flood_spine.NWS_MINOR_STND_FT is the nws_minor stage
    for station, stnd in flood_spine.NWS_MINOR_STND_FT.items():
        mine = GAUGES[station]["nws_minor_stnd_ft"]
        if mine != stnd:
            raise RuntimeError(
                f"coastal/spine threshold split at {station}: spine cuts event-days at "
                f"{stnd} ft STND, this layer measures margins against {mine}")


def elevation_ft(row: dict) -> float | None:
    """The Unit-facing elevation, NAVD88 US survey feet. `silver/asset_features` publishes
    the raw 2017 sample as canonical and leaves the fallback read-side (ticket 03 decision
    7), so applying it is this consumer's job: a row that failed QC uses its 15 m ring
    median — never a Cell median, which measured strictly worse — and a row whose ring is
    NoData too has no elevation at all."""
    if row["grade_ok"] and row["elev_ft"] is not None:
        return row["elev_ft"]
    if row["ring15_med_m"] is not None:
        return row["ring15_med_m"] * features.US_SURVEY_FT
    return None


def unit_margins(root: Path) -> list[dict]:
    """One row per scored Unit (445 complexes + 13,370 bus stops + 1,351 Cells).

    A bus stop is its own elevation. A complex and a Cell take the MINIMUM over their
    point children — the worst doorway, not the average one: a complex is flooded when its
    lowest entrance is, and averaging would hide exactly the entrance that matters. (The
    exposure score takes the MAX over children because it aggregates a probability; the
    margin takes the min because it aggregates a height. Opposite ends, same intent.)

    The gauge is assigned at the UNIT's own location, so every child of a complex is
    measured against one stage rather than a mixture.
    """
    assets = ref.read_ref(root, "assets",
                          ["asset_id", "kind", "lon", "lat", "cell", "parent_asset_id", "scored"])
    feats = {r["asset_id"]: r for r in pq.read_table(
        root / "silver" / "asset_features",
        columns=["asset_id", "elev_ft", "ring15_med_m", "grade_ok", "cell"]).to_pylist()}
    rows = [dict(zip(assets, v)) for v in zip(*assets.values())]
    # the registry's Cell rows key on the h3 hex string, the `cell` column on the h3 int:
    # the join has to go through the registry's own pairing, never a re-derived encoding
    cell_asset = {r["cell"]: r["asset_id"] for r in rows if r["kind"] == "cell"}

    children: dict[str, list[float]] = {}
    for r in rows:
        f = feats.get(r["asset_id"])
        if f is None:
            continue  # stations and complexes carry no elevation of their own
        elev = elevation_ft(f)
        if elev is None:
            continue  # 61 NoData stops, 60 of them without a ring either
        if r["kind"] == "entrance":
            children.setdefault(r["parent_asset_id"], []).append(elev)
        if f["cell"] in cell_asset:
            children.setdefault(cell_asset[f["cell"]], []).append(elev)

    out = []
    for r in rows:
        if not r["scored"]:
            continue
        if r["kind"] == "bus_stop":
            f = feats[r["asset_id"]]
            kids = [e for e in [elevation_ft(f)] if e is not None]
        else:
            kids = children.get(r["asset_id"], [])
        station, km = assign(r["lon"], r["lat"])
        thr = minor_navd88_ft(station)
        elev = min(kids) if kids else None
        out.append({
            "asset_id": r["asset_id"], "kind": r["kind"], "gauge": station,
            "gauge_km": round(km, 3), "threshold_navd88_ft": thr,
            "elev_navd88_ft": elev, "n_support": len(kids),
            "surge_margin_ft": None if elev is None else round(elev - thr, 3),
        })
    out.sort(key=lambda r: r["asset_id"])
    return out


def datum_sanity(root: Path) -> dict[str, int]:
    """The datum check pinned here, where elevations and thresholds first meet.

    Entrances below the Battery's minor flood stage, counted twice: once with the stage
    converted to NAVD88 (3 — the two WTC construction-pit rows and Richmond Valley), once
    with the published STND number compared straight against a NAVD88 elevation (103). The
    naive count is 34x too many and every one of those 100 extra entrances would have read
    as coastally exposed. Raw canonical elevations, no QC fallback, so this reproduces
    ticket 03's independently measured 3 exactly rather than a near neighbour of it.
    """
    feats = pq.read_table(root / "silver" / "asset_features",
                          columns=["asset_id", "elev_ft"]).to_pylist()
    ent = [r["elev_ft"] for r in feats
           if r["asset_id"].startswith("ent:") and r["elev_ft"] is not None]
    g = GAUGES["8518750"]
    return {"navd88": sum(e < minor_navd88_ft("8518750") for e in ent),
            "naive_stnd": sum(e < g["nws_minor_stnd_ft"] for e in ent)}


def sandy_validation(root: Path, margins: list[dict]) -> list[dict]:
    """The descriptive validation: Sandy's inundation polygon against the margin, in
    buckets. Descriptive by design — Sandy is ONE coastal event and its labels are barred
    from the fits (they would mint ~250-350 of ~1,350 cell positives), so this is a
    published table showing the layer orders the ground it should, not a pass/fail gate.
    """
    obs = pq.read_table(root / "silver" / "flood_obs", columns=["source", "geometry"])
    # An STRtree over the 492 polygons, not a union of them: unioning throws
    # "unable to assign free hole to a shell" on this geometry, and a point-in-any-part
    # test needs no union anyway.
    sandy = shapely.STRtree([shapely.from_wkb(g) for s, g in
                             zip(obs.column("source").to_pylist(),
                                 obs.column("geometry").to_pylist()) if s == "sandy"])
    a = ref.read_ref(root, "assets", ["asset_id", "lon", "lat"])
    pt = dict(zip(a["asset_id"], zip(a["lon"], a["lat"])))

    keys = [m for m in margins if m["surge_margin_ft"] is not None]
    pts = shapely.points([pt[m["asset_id"]] for m in keys])
    # `within`, not `contains`: STRtree applies the predicate as
    # predicate(input, tree_geometry), so `contains` here would ask whether a POINT
    # contains a polygon and silently return zero hits for every bucket.
    inside = set(sandy.query(pts, predicate="within")[0].tolist())

    edges = [(-1e9, 0.0), (0.0, 5.0), (5.0, 10.0), (10.0, 20.0), (20.0, 1e9)]
    table = []
    for lo, hi in edges:
        sel = [i for i, m in enumerate(keys) if lo <= m["surge_margin_ft"] < hi]
        n = len(sel)
        hit = sum(i in inside for i in sel)
        table.append({"bucket": f"[{lo:g}, {hi:g})" if abs(lo) < 1e8 else f"< {hi:g}",
                      "units": n, "sandy_inundated": hit,
                      "share": None if not n else round(hit / n, 4)})
    return table


def canary() -> dict[str, str]:
    """Every frozen gauge constant must still equal what CO-OPS publishes.

    NOAA republishes flood stages and re-levels station datums. Both sides of the margin
    subtraction come from this endpoint, so the canary asserts EQUALITY against the
    published values rather than merely that the service answers — the failure mode being
    guarded is a silently-moved threshold, which no liveness check would ever see.
    """
    live = {}
    for station, g in GAUGES.items():
        with urllib.request.urlopen(MDAPI.format(station=station,
                                                 res="floodlevels.json"), timeout=120) as r:
            stage = json.loads(r.read()).get(STAGE)
        if stage != g["nws_minor_stnd_ft"]:
            raise RuntimeError(f"CO-OPS {station}: {STAGE} is {stage} ft STND, frozen as "
                               f"{g['nws_minor_stnd_ft']} — every surge margin moves with it")
        with urllib.request.urlopen(MDAPI.format(station=station,
                                                 res="datums.json"), timeout=120) as r:
            datums = {d["name"]: d["value"] for d in json.loads(r.read())["datums"]}
        if datums.get("NAVD88") != g["navd88_offset_ft"]:
            raise RuntimeError(f"CO-OPS {station}: NAVD88 offset is {datums.get('NAVD88')} ft, "
                               f"frozen as {g['navd88_offset_ft']} — the datum conversion moved")
        live[f"coops:{station}"] = (f"{STAGE} {stage} ft STND - NAVD88 {datums['NAVD88']} "
                                    f"= {minor_navd88_ft(station)} ft NAVD88")
    return live


def report(root: Path, expect: dict | None = EXPECT) -> str:
    """The published table, as markdown on stdout. Not pytest: the Sandy half is
    descriptive and a bucket share is a number to read, not an assertion to pass."""
    check_shared_thresholds()
    margins = unit_margins(root)
    datum = datum_sanity(root)
    got = {"units": len(margins), "datum_navd88": datum["navd88"],
           "datum_naive_stnd": datum["naive_stnd"]}
    for k in ("complex", "bus_stop", "cell"):
        got[k] = sum(m["kind"] == k for m in margins)
    if expect:
        bad = {k: (got[k], v) for k, v in expect.items() if got[k] != v}
        if bad:
            raise RuntimeError(f"frozen count mismatch (got, expected): {bad}")

    L = ["# flood-07 coastal rule layer — surge_margin_ft", "",
         f"Stage frozen once: `{STAGE}`. Margin = elevation(NAVD88 ft) - the assigned "
         f"gauge's minor stage(NAVD88 ft).", "",
         "| gauge | station | minor, ft STND | NAVD88 offset, ft | minor, ft NAVD88 |",
         "|---|---|---|---|---|"]
    for s, g in GAUGES.items():
        L.append(f"| {s} | {g['name']} | {g['nws_minor_stnd_ft']} | "
                 f"{g['navd88_offset_ft']} | **{minor_navd88_ft(s)}** |")

    L += ["", "## Datum sanity", "",
          f"Entrances below the Battery's minor stage: **{datum['navd88']}** under NAVD88 "
          f"discipline, **{datum['naive_stnd']}** if the published STND number is compared "
          f"straight against a NAVD88 elevation.", "", "## Units by assigned gauge", "",
          "| gauge | complex | bus_stop | cell | negative margin | no elevation |",
          "|---|---|---|---|---|---|"]
    for s, g in GAUGES.items():
        sel = [m for m in margins if m["gauge"] == s]
        neg = sum(m["surge_margin_ft"] is not None and m["surge_margin_ft"] < 0 for m in sel)
        L.append(f"| {g['name']} | " + " | ".join(
            str(sum(m['kind'] == k for m in sel)) for k in ("complex", "bus_stop", "cell"))
            + f" | {neg} | {sum(m['surge_margin_ft'] is None for m in sel)} |")

    nulls = {k: sum(m["kind"] == k and m["surge_margin_ft"] is None for m in margins)
             for k in ("complex", "bus_stop", "cell")}
    L += ["", "Units with no margin at all: "
          + ", ".join(f"{v} {k}" for k, v in nulls.items()) +
          " — Cells with no point child inside them (scored via a taxi Zone, not an asset) "
          "and the bus stops whose 2017 sample and 15 m ring are both NoData. Ticket 10 "
          "prices these as NULL surge_margin_ft; they are not zeros.", "", "## The ten lowest margins", "",
          "| unit | name | kind | gauge | elev, ft NAVD88 | surge_margin_ft | support |",
          "|---|---|---|---|---|---|---|"]
    a = ref.read_ref(root, "assets", ["asset_id", "name"])
    names = dict(zip(a["asset_id"], a["name"]))
    low = sorted((m for m in margins if m["surge_margin_ft"] is not None),
                 key=lambda m: m["surge_margin_ft"])[:10]
    for m in low:
        L.append(f"| `{m['asset_id']}` | {names[m['asset_id']] or '-'} | {m['kind']} | "
                 f"{GAUGES[m['gauge']]['name']} | {m['elev_navd88_ft']:.2f} | "
                 f"**{m['surge_margin_ft']}** | {m['n_support']} |")

    L += ["", "The deepest row is a KNOWN DEM ARTIFACT, not a doorway: WTC Cortlandt "
          "(`stn:328`) was an open construction pit when the 2017 raster was flown and the "
          "station did not reopen until 2018, so its 15 m ring is inside the pit too and the "
          "QC fallback cannot rescue it. `grade_ok` already marks those entrances false — "
          "this layer publishes the raw consequence rather than repairing it silently, and "
          "any consumer that ranks on the margin should filter on `grade_ok` the same way "
          "the fits do.", "",
          "## Sandy inundation against the margin (descriptive)", "",
          "| surge_margin_ft | units | inside the Sandy polygon | share |", "|---|---|---|---|"]
    for r in sandy_validation(root, margins):
        L.append(f"| {r['bucket']} | {r['units']} | {r['sandy_inundated']} | "
                 f"{'-' if r['share'] is None else r['share']} |")
    return "\n".join(L) + "\n"


def main() -> None:
    root = data_root()
    if "--skip-canary" not in sys.argv:
        # stderr: `make flood-coastal` redirects stdout into the published markdown
        print(json.dumps(canary(), indent=2), file=sys.stderr, flush=True)
    print(report(root))


if __name__ == "__main__":
    main()
