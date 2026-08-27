"""Flood-build ticket 15 (spec "Real-time detector": serving, claims, logging; seam 3):
the flood tick, its two gate-side payloads, and the NDJSON cycle log.

THIS IS NOT A DAEMON. It is one call inside cloud 05's existing 30 s loop
(`live_loop.cycle`), which already owns the process, the clock and the warm DuckDB
connection. `tick()` is that call and its return value is the loop's `flood` field.

WHAT IT RENDERS IS READ, NEVER RE-TYPED. Every tier, state, budget and string comes out
of `flood_detect.cycle()` / `flood_detect.constants()` (research/flood-11-detector.json)
and `flood_exposure.coefficients()` (research/flood-10-coefficients.json). This module
computes no threshold, invents no label, and carries no copy of a number that lives in
one of those files - a mirrored constant is a constant that will disagree eventually.

THE GATE CUTS THROUGH THE PANEL, SO THERE ARE TWO FILES AND TWO METAS (frontend 01 D3,
Ross decided; the filenames are frontend 05's, already fetched by web/layers.js):

    files/flood.json + files/flood-meta.json        family `flood`      UNGATED
        the FloodNet tier, the CO-OPS coastal chips, and the 311/USGS/AORC-derived
        exposure - Cells and flagged point Units. Nothing MTA-derived may appear here.
    files/flood-mta.json + files/flood-mta-meta.json family `flood-mta`  GATED
        the MTA alert tier alone, on the same gate side as live.geojson.
    files/impact.json + files/impact-subway.json     family `impact`     GATED
        flood-build 17's two IMPACT overlays - bus Speed at Cell grain, subway service at
        complex grain. Both VP/TU-derived, so both gated; a third family rather than two
        more keys on `flood-mta` because an alert chip and a Cell-grain Speed read have
        nothing in common but their gate. They are written by `flood_overlay`, which this
        module calls once per work cycle - `flood_overlay` NEVER imports back, and it
        never imports `flood_impact` either (subwaydata numbers stay local; the reason is
        in its docstring and `release_check` asserts the rule for this module).

The split is by LINEAGE, not by panel. One meta shared between them is what frontend 01
measured as wrong: the MTA terms gate would withhold the FloodNet tier - which contains
no MTA content at all - because it shared a file with bus data. Splitting the FAMILY does
not split the FILE: publish moves whole objects, so this is the writer's shape.

Each family is payload-FIRST, meta-LAST, for cloud 09's reason: a publisher that dies
between them must leave an OLD meta over a new payload (a consumer re-reads and finds it),
never a fresh meta over a payload that is not there. `impact` has no meta at all and that
is deliberate rather than an omission: each overlay states its own hour, budget and
staleness inline, and the page fetches exactly one file per layer, so a second document
would be a freshness claim nothing reads. Subway impact numbers
(`flood_impact`, subwaydata.nyc, no published licence) are LOCAL ONLY and this module
never imports them - `release_check` asserts it.

WHAT THE PANEL MAY SAY, all of it structural here rather than remembered:

  * the human-facing value is the RANK (0..1 within kind) or the static `score_index`,
    NEVER a raw eta - the score is the linear predictor and is negative for nearly every
    Unit - and never a probability. No `eta` key is emitted anywhere.
  * `skew.model_tier == "refused"` means the artifact and the table that was read are
    different models: the model tier is DROPPED (no ranks, no tiers, no flagged Units)
    and the reason is rendered. A last-good number is never served in its place.
  * `window.state` OK / HOLES / INSUFFICIENT_DATA / WINDOW_CAPPED and `staleness.state`
    FRESH / STALE / DOWN are DIFFERENT facts and both are data, never absence. A holed
    Window is still a Window; INSUFFICIENT_DATA means there is no Window at all.
  * every staleness verdict is dated at the READER (`_source` below and `fd.staleness`),
    against the file's own stamp: a future stamp reads DOWN, never FRESH. Nothing here
    freezes an age the way meta.json's `vp_age_s` once did.
  * the tiers are PROVISIONAL while `cutpoints.provisional` is true in the artifact, and
    that flag is read AT RENDER TIME, every cycle - flood 12 recommended rank-only and
    the verdict is Ross's, so recording it must change the panel without a redeploy.
  * the frozen operating-truth string (notify 01) rides on BOTH files, verbatim.

Run: make flood-panel        (one tick against the real root, then exit)
"""
import argparse
import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from raincheck import design_storm as ds
from raincheck import duck, flood_detect as fd, flood_exposure as fe
from raincheck import flood_live as fl, flood_overlay as fo, flood_truth as ft
from raincheck import live_export, publish
from raincheck.paths import as_root, data_root
from raincheck.query import pack

# The families and their keys, in PUBLISH ORDER. Payload first, meta LAST.
#
# flood-build 17 added a THIRD, `impact`, rather than appending its two overlays to
# `flood-mta`: the alert tier and the impact overlays are gated for the same reason but
# they are not the same payload, they are read by different layers, and one meta over both
# would put the alert tier's freshness on a Cell-grain Speed read. Its keys and its
# all-or-none rule live in `flood_overlay`; this module owns only the writing and the
# publish order, exactly as it does for its own two.
UNGATED, GATED, IMPACT = "flood", "flood-mta", fo.FAMILY
FILES = {UNGATED: ("flood.json", "flood-meta.json"),
         GATED: ("flood-mta.json", "flood-mta-meta.json"),
         IMPACT: fo.FILES}
ORDER = (UNGATED, GATED, IMPACT)

# THE BUDGETS THE PAGE READS. Frontend 02 counted nine sources on the running map and
# exactly three carrying a frozen budget; these are the five this ticket owed, and every
# one is DERIVED from the module that fetches it rather than re-typed here (flood 11 built
# the artifact the same way, and asserts the artifact against these same constants). The
# page's layer table is in seconds, which is why this is.
BUDGETS_S = {
    "precip_fresh": fd.PRECIP_FRESH_MIN * 60,      # 5400
    "precip_stale": fd.PRECIP_STALE_MIN * 60,      # 10800
    "floodnet": ft.MAX_AGE_MIN * 60,               # 600
    "coops": fl.OBS_STALE_MIN * 60,                # 1800
    "nws_alerts": fd.NWS_ALERTS_MIN * 60,          # 900
    "nws_knyc_obs": fl.KNYC_STALE_MIN * 60,        # 7200 - two hourly reports, SETTLED
}

# How far back the forcing is read. The Window can walk back CAP_DAYS and freezes a 24 h
# antecedent block at the anchor, so 8 days covers the deepest legal Window with a day to
# spare - and precip_live prunes at 7, so this reads everything there is.
READ_DAYS = 8

LOG_DIR = "live/flood_log"
LOG_KEEP_DAYS = 30
# GZIPPED, and that is what makes the spec's byte budget true rather than aspirational.
# MEASURED 2026-08-25 on the real universe: one full unit-state vector is 15,106 rows =
# 1,651,324 B raw, so the ~24 recomputes a day the spec describes are 39.6 MB/day and
# 1.2 GB across the 30-day prune - against a budget of "~3 MB/day, <= ~100 MB". The rows
# are a tier vocabulary and a rank column, which is exactly what compresses: 12.4x on a
# single row, and 39.6 MB -> 3.2 MB across a day. `gzip.open(..., "at")` appends a new
# member per write and concatenated members are a valid gzip stream, so the file stays
# appendable and `zcat`-able. The budget the spec named is met, not re-negotiated.
LOG_SUFFIX = ".ndjson.gz"


# ---- the reads ----------------------------------------------------------------------

# EVERY READ HERE PUTS ITS PROJECTION AND ITS PREDICATE INSIDE THE READ'S OWN STATEMENT,
# and that is a memory contract, not style. `duck.table()` binds the path as a PARAMETER,
# so the file list is unknown when the scan is planned and a filter or projection applied
# OUTSIDE that statement - a `.filter()/.project()` chain, or a view queried afterwards -
# cannot be pushed into it. MEASURED on this Mac, 2026-08-25, threads=1, memory_limit
# 384MB, same rows out of `gold/flood_matrix` (1,006,123 rows, 19 columns):
#
#     duck.table(...).create_view("m") then SELECT 7 cols      437 MiB peak
#     the same SELECT with read_parquet(?) in-statement        175 MiB peak
#
# This pod is limited to 768 MiB (`deploy/k8s/raincheck/live.yaml`), so the difference is
# the whole margin. The same shape cost `flood_truth.alert_rows` 5 GiB before this ticket
# rewrote it; TRAPS carries the general rule.
READ = ("read_parquet(?, hive_partitioning = true, hive_types_autocast = false, "
        "union_by_name = true)")


def _rows(con, sql: str, path) -> list[dict]:
    """One statement, one scan, columns and predicates pushed into it."""
    return con.execute(sql.format(read=READ), [path]).to_arrow_table().to_pylist()


def newest_stamp(root: Path) -> str | None:
    """The newest `valid_ts=` partition NAME, by name. This is the skip test, so it must
    be cheaper than the read it guards: one directory listing, no parquet opened."""
    table = as_root(root) / "live" / "precip_cell"
    try:
        names = sorted(p.name for p in table.glob("valid_ts=*"))
    except (OSError, NotImplementedError):
        return None
    return names[-1] if names else None


# THE FORCING IS READ IN TWO PASSES, and that is a memory contract rather than an
# optimisation. This tick runs inside cloud 05's Deployment, which is limited to 768 MiB
# (`deploy/k8s/raincheck/live.yaml`, sized from a measured 368 MiB plateau). Eight days of
# `live/precip_cell` is 4,113 Cells x ~190 hours = ~378,000 rows, which peaks over a GiB
# as python objects - and nearly all of it is thrown away, because the Window is usually
# one or two days long. The walk needs only the CITYWIDE COUNT per hour, which is 190 rows
# aggregated in the engine; the features need per-Cell rows only from the antecedent block
# forward. So: count first, walk, then read the slice the anchor actually names.
#
# `precip_live` re-fetches the latest :00 stamp every tick and appends a part each time, so
# the raw table holds ~7 rows per (Cell, hour) and the NEWEST fetched_at wins. Both passes
# dedupe; an aggregate without it is a statement about how often the pod ran, not about
# rain (TRAPS, measured by flood 12).
def parts(root: Path, since: datetime) -> list[str]:
    """THE DEDUPE, DONE BY FILE NAME. `precip_live.append_hour` writes the WHOLE 4,113-Cell
    grid for one (valid_ts, fetched_at) into `valid_ts=<hour>/part-<fetched_at>.parquet`
    and replaces it atomically, so the NEWEST part in an hour directory already holds the
    newest fetched_at for every Cell in that hour. Selecting one file per hour is therefore
    exactly `row_number() OVER (PARTITION BY cell, valid_ts ORDER BY fetched_at DESC) = 1`,
    and it reads 92 files instead of 657 with no window function at all.

    VERIFIED, not assumed: identical row set to the window-function form on the real table
    (378,396 rows), and all 662 parts on disk carry exactly 4,113 rows. If a partial part
    ever appeared, the Cells it lost would surface as `window.coverage` < 1 and state
    HOLES - the degrade this detector already renders - rather than as a quiet wrong total.
    """
    key = since.strftime("valid_ts=%Y-%m-%dT%H")
    out = []
    for d in sorted((as_root(root) / "live" / "precip_cell").glob("valid_ts=*")):
        if d.name < key:
            continue
        got = sorted(p.name for p in d.glob("part-*.parquet"))
        if got:
            out.append(str(d / got[-1]))
    return out


def wet_series(con, root: Path, now: datetime, days: int = READ_DAYS) -> dict:
    """Citywide wet-Cell COUNT per hour_end - `fd.wet_counts` computed in the engine.

    CITYWIDE MEANS THE WHOLE GRID. This is deliberately not derived from the narrowed
    per-Cell read below: counting over a Cell SUBSET would silently redefine the citywide
    gate as "these Cells", which is the trap flood 12's box calls out. A NULL mm_1h is
    missing, not dry, so it is simply not counted wet - the same rule `wet_counts` applies.
    """
    rows = con.execute(
        "SELECT strptime(valid_ts, '%Y-%m-%dT%H')::TIMESTAMPTZ AS hour_end_utc, "
        f"count(*) FILTER (WHERE mm_1h >= {fd.WET_MM})::BIGINT AS wet "
        f"FROM {READ} GROUP BY 1 ORDER BY 1",
        [parts(root, now - timedelta(days=days))]).fetchall()
    return {h: n for h, n in rows}


def cell_hours(con, root: Path, since: datetime, now: datetime) -> list[dict]:
    """The per-Cell forcing from `since` forward, as a materialised LIST.

    A LIST, not a generator: `fd.cycle` iterates it twice (once for the newest stamp, once
    for the Window) and an exhausted generator publishes an empty Window that reports
    coverage 1.0 / state OK - complete and empty at once, indistinguishable from a quiet
    night (flood 12 measured exactly that, TRAPS).
    """
    rows = con.execute(
        "SELECT cell, strptime(valid_ts, '%Y-%m-%dT%H')::TIMESTAMPTZ AS hour_end_utc, mm_1h "
        f"FROM {READ}", [parts(root, since)]).fetchall()
    return [{"cell": c, "hour_end_utc": h, "mm_1h": mm} for c, h, mm in rows]


def since_of(walk: dict, now: datetime) -> datetime:
    """The oldest hour the per-Cell read must carry: the antecedent block's first hour,
    which is `anchor - 23 h` (the block is the 24 hour_ends ENDING at the anchor). One hour
    of margin is taken because the partition key is hour-grain. With no anchor there is no
    Window at all and only `staleness` reads the rows, so a day is enough."""
    anchor = walk.get("anchor")
    if anchor is None:
        return now - timedelta(days=1)
    return anchor - timedelta(hours=fd.ANTECEDENT_H)


# One row per scored Unit, statics only. The distinct-counts are flood_exposure's own
# drift rule (compare the TUPLE, never the sum: count(DISTINCT ...) skips NULLs) applied
# to the columns THIS read uses, `cell` included - a Unit that moved Cell between events
# cannot be given one live forcing.
POINT_SQL = """
SELECT asset_id, any_value(kind) AS kind, any_value(complex_id) AS complex_id,
       min(cell) AS cell, min(elev_ft) AS elev_ft, min(relief_ft) AS relief_ft,
       min(stormwater_cat) AS stormwater_cat,
       count(DISTINCT cell) AS n_cell, count(DISTINCT elev_ft) AS n_elev,
       count(DISTINCT relief_ft) AS n_relief, count(DISTINCT stormwater_cat) AS n_cat
  FROM {read} WHERE role = 'fit_point' GROUP BY asset_id ORDER BY asset_id
"""
CELL_SQL = """
SELECT asset_id, min(cell) AS cell, min(share_deep) AS share_deep,
       min(share_nuisance) AS share_nuisance,
       min(share_not_analyzed) AS share_not_analyzed,
       arg_max(density_311_3y, event_id)::DOUBLE AS density_311_3y,
       count(DISTINCT cell) AS n_cell, count(DISTINCT share_deep) AS n_deep,
       count(DISTINCT share_nuisance) AS n_nuisance,
       count(DISTINCT share_not_analyzed) AS n_not_analyzed
  FROM {read} WHERE role = 'fit_cell' GROUP BY asset_id ORDER BY asset_id
"""
POINT_STATIC = ("n_cell", "n_elev", "n_relief", "n_cat")
CELL_STATIC = ("n_cell", "n_deep", "n_nuisance", "n_not_analyzed")


def _drift(rows: list[dict], cols: tuple[str, ...], what: str) -> None:
    bad = [r["asset_id"] for r in rows
           if tuple(r[c] for c in cols) != (1,) * len(cols)]
    if bad:
        raise RuntimeError(f"{len(bad)} {what} carry more than one static value across "
                           f"events, e.g. {bad[:3]} - one live forcing cannot represent them")


def universe(con, root: Path) -> dict:
    """The scoring universe and the static exposure view, read ONCE per process.

    Returns {units, static, table_score_version, complexes}. `units` is what
    `fd.evaluate` scores: bus stops and entrances with their point statics, Cells with
    their shares and the frozen 311 density, and the registry's own complex rows (a
    complex is scored as the MAX over its child entrances, so it needs no statics of its
    own). `table_score_version` is the stamp on the TABLE THAT WAS READ - never a
    constant - and is None when the table carries more than one, which `fd.skew` refuses.
    """
    root = as_root(root)
    matrix = f"{root}/gold/flood_matrix/**/*.parquet"
    points = _rows(con, POINT_SQL, matrix)
    cells = _rows(con, CELL_SQL, matrix)
    _drift(points, POINT_STATIC, "point Units")
    _drift(cells, CELL_STATIC, "Cells")
    for c in cells:
        c["kind"] = "cell"
    reg = _rows(con, "SELECT asset_id, kind, complex_id, cell, name, lon, lat "
                     "FROM {read} WHERE scored AND kind IN ('complex', 'bus_stop', 'cell')",
                f"{root}/ref/assets/**/*.parquet")
    where = {r["asset_id"]: r for r in reg}
    # the static exposure view: score_index is the within-kind empirical CDF of score_ref,
    # bounded (0, 1], one row per Unit, no nulls. It is the DORMANT-weather read and the
    # only number the panel shows when there is no Window.
    exp = _rows(con, "SELECT asset_id, kind, score_index, surge_margin_ft, flags, "
                     "score_version FROM {read}",
                f"{root}/gold/flood_exposure/**/*.parquet")
    stamps = {e["score_version"] for e in exp}
    units = [dict(p) for p in points] + [dict(c) for c in cells]
    units += [r for r in reg if r["kind"] == "complex"]
    return {
        "units": units,
        "static": {e["asset_id"]: e for e in exp},
        "where": where,
        "table_score_version": stamps.pop() if len(stamps) == 1 else None,
    }


def wet_cells(rows: list[dict], now: datetime) -> set:
    """Cells taking rain in the newest hour that has landed - the FloodNet tier's
    concurrent-own-Cell-rain DISPLAY gate (never part of its water rule)."""
    hours = [r["hour_end_utc"] for r in rows if r["hour_end_utc"] <= now]
    if not hours:
        return set()
    newest = max(hours)
    return {r["cell"] for r in rows if r["hour_end_utc"] == newest
            and r["mm_1h"] is not None and r["mm_1h"] >= fd.WET_MM}


def cell_index(root: Path):
    """(centroids tree, cell ids) for placing a FloodNet sensor in an H3 Cell.

    `ref/cells` is the only H3 oracle on this box (no python h3; the DuckDB community
    extension is a test-only dependency), and the query direction matters: STRtree applies
    predicate(input, tree), so this queries with the POINT and confirms with the polygon's
    own `covers` - the shape `ref.build_cell_zone` already uses.
    """
    import pyarrow.parquet as pq
    import shapely
    from shapely import STRtree

    t = pq.read_table(as_root(root) / "ref" / "cells", columns=["cell", "geometry"])
    geoms = [shapely.from_wkb(g) for g in t.column("geometry").to_pylist()]
    return STRtree(geoms), t.column("cell").to_pylist(), geoms


def cell_of(index, points: dict[str, tuple]) -> dict[str, int]:
    tree, ids, geoms = index
    import shapely

    out = {}
    for key, (lon, lat) in points.items():
        if lon is None or lat is None:
            continue
        p = shapely.Point(lon, lat)
        hit = [k for k in tree.query(p) if geoms[k].covers(p)]
        if hit:
            out[key] = ids[hit[0]]
    return out


# ---- staleness, dated at the reader --------------------------------------------------

def _source(newest: datetime | None, now: datetime, budget_s: int, ok: bool = True,
            ahead: float = 0.0) -> dict:
    """One source's freshness verdict against ITS OWN budget, on the READER's clock.

    A missing stamp, a failed read and a stamp further AHEAD than the source's published
    tolerance all read DOWN: a clock that runs ahead of the source is not evidence of
    freshness, and "I could not tell" is not "fresh". The vocabulary is flood 11's
    (`display.precip_states`), not a second one.

    `ahead` is that tolerance and it is READ, never chosen here
    (`staleness_budgets.clock_ahead_min`). Zero is the wrong default for a sensor network:
    FloodNet stamps up to two minutes ahead by design and `flood_truth`'s own query window
    allows it, so a stricter rule here would paint 386 live sensors DOWN forever - the
    tier inventing the outage it exists to report.
    """
    if not ok or newest is None:
        return {"state": fd.DOWN, "budget_s": budget_s}
    age = (now - newest).total_seconds() / 60.0
    state = (fd.DOWN if age < -ahead else
             fd.FRESH if age * 60 <= budget_s else fd.STALE)
    return {"state": state, "age_min": round(age, 1), "budget_s": budget_s}


def _iso(t) -> str | None:
    return t.isoformat() if isinstance(t, datetime) else None


# ---- the strings ---------------------------------------------------------------------

# notify 01 froze this on 2026-08-23 and it replaces the retired storm-page claim, which a
# notifier falsifies. It is rendered VERBATIM on both files and notify 09 renders the same
# words, so a panel and a message cannot contradict each other. Do not re-word it.
OPERATING_TRUTH = (
    "raincheck ranks where a flood REPORT is likely from rain that has already fallen, on "
    "hour-grain evidence that trails the storm. A rank is not an observation of water, and "
    "a quiet panel or a quiet inbox means nothing was flagged, not that nothing flooded."
)


def strings(det: dict, art: dict) -> dict:
    """Every human-readable string the panel shows. All of them are READ: `display.*` is
    flood 11's (deliberately outside `detector_version`, so rewording one cannot roll a
    live Window) and `gate.panel_strings` is flood 10's, PRE-SELECTED by the headline gate
    - the B2 alternates are not the live branch, so the branch is read, never chosen."""
    d = det["display"]
    return dict(d) | {
        "operating_truth": OPERATING_TRUTH,
        "estimand": det["estimand"],
        "estimand_note": det["estimand_note"],
        "tiers_provisional": det["cutpoints_note"],
        "gate_branch": art["gate"]["branch"],
        "panel": dict(art["gate"]["panel_strings"]),
        "complex_rule": det["gates"]["complex_rule"],
    }


# ---- the payloads ---------------------------------------------------------------------

def _window(read: dict) -> dict:
    w, f = read["window"], read.get("features") or {}
    return pack(state=w["state"], anchor=read.get("anchor"),
                walked_days=w.get("walked_days"),
                missing_pad=[_iso(h) for h in w.get("missing_pad") or []] or None,
                coverage=f.get("coverage"),
                hours_expected=f.get("window_hours_expected"),
                unforced_cells=f.get("unforced_cells"))


def _r(v, nd: int = 6):
    return None if v is None else round(v, nd)


def _prune(o):
    """ABSENT, NEVER NULL - applied to the whole document rather than key by key.

    MapLibre's ["has", p] is true on a null and `interpolate` then errors on it, which is
    why the whole read surface writes an absent key instead. Doing it at the end makes the
    rule structural: three of the members here are other modules' shapes (`flood_live`'s
    coastal chips, `flood_truth`'s read report and its chips), and every one of them
    carries explicit Nones by ITS own convention - a `reason` that is None because nothing
    is wrong, an `observed_ft` that is None because the gauge is out.

    EMPTY IS NOT ABSENT: [] and 0 and false still publish, because "no sensors detected
    water" and "the tier is off" are answers.
    """
    if isinstance(o, dict):
        return {k: _prune(v) for k, v in o.items() if v is not None}
    if isinstance(o, list):
        return [_prune(v) for v in o]
    return o


def _coastal(coastal: dict | None) -> dict | None:
    """The CO-OPS tier, minus the per-Unit recolor set.

    `recolor.units` is `flood_coastal.unit_margins()` filtered to the hot gauges - 1,072
    rows / 212 KB measured during a real APPROACHING tide, which would be the largest
    member of a `no-cache` payload republished every two minutes. It is also STATIC (the
    margin moves with the DEM epoch, not with the water) and the same number already rides
    per Cell in `cells[].surge_margin_ft` from `gold/flood_exposure`. So the counts ship
    and the rows do not: no page layer reads them today, and the ticket that adds one
    should take them from the exposure table it is already holding rather than from a
    live tick. The gauge chips themselves ARE live and ship whole.
    """
    if not coastal:
        return None
    r = coastal.get("recolor") or {}
    return dict(coastal) | {"recolor": {k: v for k, v in r.items() if k != "units"}}


def _cells(read: dict, uni: dict, modelled: bool, rates: dict | None = None) -> dict:
    """One dict per SCORED Cell, keyed by the H3 HEX string - the same spelling
    cells.geojson keys on, because an H3 id is an int64 past 2^53 and JSON cannot carry
    one. Geometry is deliberately NOT duplicated here: the page already holds it.

    Absent, never null, and one dict per Cell so a later ticket can add a key without a
    rewrite - flood-build 20's `design_storm` is the first: {mm_1h, bracket?}, present
    only while it is raining in that Cell. `rates` covers the whole 4,113-Cell grid but
    the key set here stays the 1,351 SCORED Cells on purpose: a Cell with no exposure
    row has no dict to carry it, and widening that is a deliberate loop change, not a
    lookup (flood 15's rule).
    """
    live = {u["asset_id"]: u for u in read.get("units") or []} if modelled else {}
    totals = read.get("cell_totals") or {}
    out = {}
    for asset_id, e in uni["static"].items():
        if e["kind"] != "cell":
            continue
        hexid = asset_id.split(":", 1)[1]
        u = live.get(asset_id)
        # the KEY is the hex Cell id, so `asset_id` would be "cell:" + the key on every
        # one of 1,351 rows. Ranks and indices are display numbers: 6 dp, not 17 - which
        # is ~70 KB of this file and changes nothing a reader can see.
        out[hexid] = pack(
            score_index=_r(e["score_index"]), flags=list(e["flags"] or []) or None,
            surge_margin_ft=e["surge_margin_ft"],
            window_mm=_r(totals.get(hexid), 3),
            rank=_r((u or {}).get("rank")), tier=(u or {}).get("tier"),
            latched=(u or {}).get("latched") or None,
            design_storm=ds.cell((rates or {}).get(hexid)))
    return out


def _flagged(read: dict, uni: dict, modelled: bool) -> list[dict]:
    """Point Units at ELEVATED+ only. In dormant weather this is empty and the panel
    shows the static Cell view instead; there is no dormant list of 13,370 bus stops."""
    if not modelled:
        return []
    out = []
    for u in read.get("units") or []:
        if u["tier"] == fd.NONE or u["kind"] == "cell":
            continue
        e = uni["static"].get(u["asset_id"]) or {}
        w = uni["where"].get(u["asset_id"]) or {}
        out.append(pack(asset_id=u["asset_id"], kind=u["kind"], cell=u["cell"],
                        tier=u["tier"], rank=_r(u["rank"]), latched=u["latched"] or None,
                        suppressed_by=u.get("suppressed_by"),
                        score_index=_r(e.get("score_index")),
                        flags=list(e.get("flags") or []) or None,
                        surge_margin_ft=e.get("surge_margin_ft"),
                        name=w.get("name"), lon=w.get("lon"), lat=w.get("lat")))
    return sorted(out, key=lambda u: (u["kind"], u["asset_id"]))


def _fn_geojson(tier: dict) -> dict:
    """The FloodNet sensors as Points. `display` is a REQUIRED boolean on every feature:
    the map paints a water-now sensor as a filled disc and a dry or stale one as a hollow
    ring, and the MapLibre expression that does it reads exactly ["get", "display"] - a
    missing key paints every sensor as a ring (frontend 05)."""
    feats = []
    for s in tier.get("sensors") or []:
        if s.get("lon") is None or s.get("lat") is None:
            continue
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
            "properties": pack(
                display=bool(s["display"]), deployment_id=s["deployment_id"],
                name=s["name"], status=s["status"], state=s["state"], label=s["label"],
                depth_mm=s["depth_mm"], rise_mm=s["rise_mm"], run=s["run"],
                age_min=s["age_min"], fresh=s["fresh"], gate=s["gate"],
                cell=fd.hexcell(s["cell"]) if s.get("cell") is not None else None),
        })
    return {"type": "FeatureCollection", "features": feats}


def _mta_geojson(tier: dict) -> dict:
    """One Point per AFFECTED COMPLEX. `flood_truth.chips()` carries the coordinates now
    (this ticket closed that; the price was 30 KB for all 445 complexes), so a page can
    place an affected station without a second lookup against ref/assets."""
    feats = []
    for c in tier.get("chips") or []:
        for s in c.get("stations") or []:
            if s.get("lon") is None or s.get("lat") is None:
                continue
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                "properties": pack(display=s["state"] == "active", event_id=c["event_id"],
                                   complex_id=s["complex_id"], name=s["name"],
                                   state=s["state"], chip_state=c["state"],
                                   age_min=c["age_min"]),
            })
    return {"type": "FeatureCollection", "features": feats}


def payloads(read: dict, uni: dict, truth: dict, coastal: dict | None, winter: dict | None,
             det: dict, art: dict, now: datetime, impact: dict | None = None,
             design_storm: dict | None = None) -> dict:
    """The six documents this cycle publishes, keyed by file name.

    ONE cycle_id across the set, so a reader can tell a torn set from a coherent one.
    `provisional` is read from the artifact HERE, at render time, every cycle: flood 12
    recommended rank-only and the verdict is Ross's, so recording it must reach the panel
    without a redeploy.

    `design_storm` is `raincheck.design_storm.read()`'s snapshot (flood-build 20) and is
    keyword-with-a-default for flood 17's reason: `release_check._sample_payloads()` calls
    this positionally with eight arguments and must keep working. Its block and its
    per-Cell rates land on the UNGATED file only - MRMS-derived, nothing MTA in it.
    """
    cycle_id = now.isoformat()
    cuts = det["cutpoints"]
    modelled = read["skew"]["model_tier"] == "ok" and read["window"]["state"] == fd.OK
    ahead = det["staleness_budgets"]["clock_ahead_min"]
    fn, mta = truth["floodnet"], truth["mta"]
    stale = {
        "precip": pack(**read["staleness"], budget_s=BUDGETS_S["precip_fresh"],
                       down_after_s=BUDGETS_S["precip_stale"]),
        "floodnet": _source(_ts(fn.get("read", {}).get("newest")), now,
                            BUDGETS_S["floodnet"], fn.get("status") == "ok", ahead),
        "coops": _source(_coops_newest(coastal), now, BUDGETS_S["coops"],
                         bool(_coops_newest(coastal)), ahead),
        "nws_knyc_obs": _source(_ts((winter or {}).get("t")), now,
                                BUDGETS_S["nws_knyc_obs"],
                                (winter or {}).get("status") == "ok", ahead),
    }
    head = {"cycle_id": cycle_id, "detector_version": read["detector_version"],
            "score_version": read["score_version"],
            "provisional": bool(cuts["provisional"])}
    meta = head | {
        "staleness": stale, "budgets_s": dict(BUDGETS_S),
        "window": _window(read), "dim": pack(**(read.get("dim") or {})),
        "skew": pack(**read["skew"]), "winter": pack(**(read.get("winter") or {})),
        "revisions": len(read.get("revisions") or []),
        "model_tier": "ok" if modelled else "dropped",
    }
    cells = _cells(read, uni, modelled, (design_storm or {}).get("rates"))
    flagged = _flagged(read, uni, modelled)
    ungated = head | {
        "lineage": "ungated", "strings": strings(det, art), "cutpoints": dict(cuts),
        "window": meta["window"], "staleness": stale, "budgets_s": dict(BUDGETS_S),
        "dim": meta["dim"], "winter": meta["winter"], "skew": meta["skew"],
        "model_tier": meta["model_tier"], "cells": cells, "units": flagged,
    } | pack(coastal=_coastal(coastal),
             design_storm=(design_storm or {}).get("block")) | {
        "floodnet": pack(source=fn["source"], status=fn["status"], citation=fn["citation"],
                         caveats=fn["caveats"], rule=fn["rule"],
                         window_min=fn["window_min"], asof=fn["asof"],
                         detected=fn.get("detected"), read=fn.get("read"),
                         error=fn.get("error"), geojson=_fn_geojson(fn)),
    }
    gated = head | {
        "lineage": "mta-alerts",
        "strings": {"operating_truth": OPERATING_TRUTH,
                    "no_complex_skill_claim": det["display"]["no_complex_skill_claim"]},
        "mta": pack(source=mta["source"], status=mta["status"],
                    vocabulary=mta["vocabulary"], hours=mta["hours"], asof=mta["asof"],
                    active=mta.get("active"), rows=mta.get("rows"),
                    error=mta.get("error"), chips=mta.get("chips") or [],
                    geojson=_mta_geojson(mta)),
    }
    return _prune({
        # flood 17's two, rendered from the same `now` so all six carry one cycle_id.
        # `impact=None` renders the honest DOWN pair rather than dropping the keys: a
        # family is all-or-none at publish time.
        **fo.docs(impact, now),
        "flood.json": ungated,
        "flood-meta.json": meta | {"lineage": "ungated", "counts": {
            "cells": len(cells), "units_flagged": len(flagged),
            "units_high": sum(1 for u in flagged if u["tier"] == fd.HIGH),
            "floodnet_sensors": len(fn.get("sensors") or []),
            "floodnet_detected": fn.get("detected") or 0}},
        "flood-mta.json": gated,
        "flood-mta-meta.json": head | {"lineage": "mta-alerts", "counts": {
            "chips": len(mta.get("chips") or []), "active": mta.get("active") or 0,
            "stations": sum(len(c.get("stations") or [])
                            for c in mta.get("chips") or [])},
            "status": mta["status"], "asof": mta["asof"],
            "budgets_s": dict(BUDGETS_S)},
    })


def _coops_newest(coastal: dict | None) -> datetime | None:
    """The newest CO-OPS OBSERVATION stamp across the three gauges - never `coastal.asof`,
    which is when the loop fetched. A writer's own clock inside a payload is the frozen-age
    trap (TRAPS); the age the panel shows has to be the age of the DATA."""
    seen = [t for t in (_ts(c.get("obs_t")) for c in (coastal or {}).get("chips") or [])
            if t is not None]
    return max(seen) if seen else None


def _ts(s) -> datetime | None:
    if isinstance(s, datetime):
        return s
    try:
        t = datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


# ---- writing, publishing, logging ------------------------------------------------------

def write(out_dir: Path, docs: dict) -> None:
    """Every family, payload first and meta LAST, each swapped atomically into place."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for family in ORDER:
        for name in FILES[family]:
            live_export.swap(out_dir / name, json.dumps(docs[name], default=str))


def ship(out_dir: Path, prev: dict) -> dict:
    """Publish every family. Returns {family: word} for the loop's state and the log line.

    Cloud 05's failure policy, copied unchanged: an outage is a FIELD, never a stopped
    loop. `GateClosed` (cloud 09 rc 3) is a DESIGNED state - the MTA terms are unverified,
    so the gated pair is written locally and not published - and is logged on CHANGE only,
    because 2,880 identical lines a day would bury the tick that actually failed."""
    out = {}
    for family in ORDER:
        try:
            out[family] = f"published {len(publish.publish(family, src=out_dir))}"
        except publish.GateClosed as exc:
            if (prev or {}).get(family) != "gated":
                print(f"flood-panel: {family} publish gated (rc 3, designed) - {exc}",
                      flush=True)
            out[family] = "gated"
        except Exception as exc:  # noqa: BLE001 - a failed upload is a stale page, not a stop
            out[family] = f"failed {type(exc).__name__}: {str(exc)[:120]}"
    return out


def log(root: Path, now: datetime, read: dict, full: bool, truth: dict | None) -> None:
    """One NDJSON file per day under <root>/live/flood_log, pruned on the first write of a
    day. The FULL unit-state vector only when the model tier recomputed (~24/day); the
    flagged subset every other cycle; a truth snapshot when it is handed one."""
    d = as_root(root) / LOG_DIR
    path = d / f"{now:%Y-%m-%d}{LOG_SUFFIX}"
    if not path.exists():
        d.mkdir(parents=True, exist_ok=True)
        cutoff = f"{now.date() - timedelta(days=LOG_KEEP_DAYS)}{LOG_SUFFIX}"
        for old in d.glob(f"*{LOG_SUFFIX}"):
            if old.name < cutoff:
                old.unlink()
    units = [pack(asset_id=u["asset_id"], kind=u["kind"], cell=u["cell"], tier=u["tier"],
                  rank=round(u["rank"], 6), latched=u["latched"] or None)
             for u in read.get("units") or []
             if full or u["tier"] != fd.NONE]
    rows = [{"at": now.isoformat(), "kind": "full" if full else "flagged",
             "detector_version": read["detector_version"],
             "score_version": read["score_version"],
             "window": read["window"]["state"], "skew": read["skew"]["model_tier"],
             "revisions": read.get("revisions") or [], "units": units}]
    if truth is not None:
        rows.append({"at": now.isoformat(), "kind": "truth",
                     "floodnet": truth["floodnet"].get("detected"),
                     "floodnet_status": truth["floodnet"]["status"],
                     "mta_active": truth["mta"].get("active"),
                     "mta_status": truth["mta"]["status"]})
    with gzip.open(path, "at") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str) + "\n")


def _truth_key(truth: dict) -> tuple:
    fn, mta = truth["floodnet"], truth["mta"]
    return (fn["status"], fn.get("detected"), mta["status"], mta.get("active"),
            tuple(sorted((c["event_id"], c["state"]) for c in mta.get("chips") or [])))


# ---- the tick --------------------------------------------------------------------------

def due(prev: dict | None, stamp: str | None, now: datetime, throttle_s: float) -> bool:
    """Skip unless the forcing moved or a truth throttle expired.

    The model tier can only change when the precip stamp advances - hourly - so on a 30 s
    loop nearly every tick has nothing new to score. The truth tiers CAN change in
    between, which is what the FloodNet throttle (the artifact's, not a number retyped
    here) is for. First cycle always runs."""
    if not prev:
        return True
    if stamp != prev.get("stamp"):
        return True
    last = prev.get("at")
    return last is None or (now - last).total_seconds() >= throttle_s


def tick(con, root: Path, out_dir: Path, prev: dict | None, now: datetime,
         detector: dict | None = None, ship_=None) -> dict:
    """ONE flood cycle, or the reason there wasn't one. Never raises.

    `detector` is the loop's own `flood_live.live()` read, already fetched on its 360 s
    cadence - the winter gate's Central Park temperature and the coastal chips come from
    there rather than from a second fetch of the same two endpoints at the render rate.
    """
    prev = prev or {}
    stamp = None
    # `fd.constants()` and the skip test are INSIDE the guard, and that is what makes the
    # first line of this docstring true. They used to sit above it, so a missing
    # research/flood-11-detector.json raised out of a function documented never to raise -
    # which killed live_loop's whole cycle, the FLEET EXPORT HALF INCLUDED, in flat
    # contradiction of that module's own failure policy ("a dead detector must not stop the
    # fleet from publishing"). Measured on the cluster by cloud 14, 2026-08-27: the artifact
    # is not in the image, and raincheck-live CrashLoopBackOff'd on it rather than
    # degrading to an error field. The image half is fixed in docker/Dockerfile; this half
    # is the contract, and it holds for any future artifact that goes missing.
    try:
        det_art = prev.get("det") or fd.constants()
        stamp = newest_stamp(root)
        if not due(prev, stamp, now, det_art["throttles"]["floodnet_s"]):
            return prev | {"skipped": True}
        return _tick(con, root, out_dir, prev, now, detector, det_art, stamp,
                     ship_ or ship)
    except Exception as exc:  # noqa: BLE001 - an outage is a field on state, never a stop
        return prev | {"skipped": False, "at": now, "stamp": stamp,
                       "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _tick(con, root, out_dir, prev, now, detector, det_art, stamp, ship_) -> dict:
    art = prev.get("art") or fe.coefficients()
    uni = prev.get("uni") or universe(con, root)
    # count the whole grid, walk to the anchor, then read only the Cell-hours that anchor
    # names. `wet` is passed to `cycle` explicitly for the same reason ticket 12 was told
    # to pass it: "citywide" is a property of the grid, not of the rows this read carries.
    wet = wet_series(con, root, now)
    rows = cell_hours(con, root, since_of(fd.walk(now, wet), now), now)
    winter = (detector or {}).get("winter") or {}
    coastal = (detector or {}).get("coastal")
    read = fd.cycle(prev.get("read"), now, rows, uni["units"], art, det_art,
                    temp_c=winter.get("temp_c"), temp_stale=bool(winter.get("stale")),
                    table_score_version=uni["table_score_version"], wet_by_hour=wet)
    index = prev.get("index")
    if index is None:
        try:
            index = cell_index(root)
        except Exception as exc:  # noqa: BLE001 - no ref/cells is an ungated display gate
            print(f"flood-panel: no Cell index ({type(exc).__name__}) - the FloodNet "
                  "own-Cell rain gate is not evaluated", flush=True)
            index = False
    placed = prev.get("cell_of")
    if index and placed is None:
        # deployments move on a scale of DAYS and flood_truth caches them one file per UTC
        # day, so the placement is read from that cache once per process rather than out of
        # a second truth() round trip - which would be a second FloodNet depth fetch too.
        try:
            deps = ft.fetch_deployments(root, now)
            placed = cell_of(index, {
                d: tuple(((m.get("location") or {}).get("coordinates") or [None, None])[:2])
                for d, m in deps.items()})
        except Exception as exc:  # noqa: BLE001 - an unplaced sensor renders without a gate
            print(f"flood-panel: sensors not placed ({type(exc).__name__}) - the own-Cell "
                  "rain gate is not evaluated", flush=True)
            placed = {}
    truth = ft.truth(root, now, wet_cells(rows, now) if placed else None, placed or None)
    # flood 17's two overlays ride THIS tick rather than standing a second call up beside
    # it in `live_loop.cycle()` - one process, one clock, one warm connection, and one
    # `now`, so the impact files cannot age apart from the tiers they sit next to. It
    # never raises: each side comes back with its own `state`, DOWN included.
    impact = fo.read(con, root, now)
    # flood-build 20: the design-storm sentence's data, on the same `now`. No new read -
    # the per-Cell rate is the newest landed hour of `rows`, already in memory - and the
    # DEP intensities are read from stormwater_extent.SCENARIOS (lazily, once per process).
    design = ds.read(rows, now)
    docs = payloads(read, uni, truth, coastal, winter, det_art, art, now, impact,
                    design_storm=design)
    write(out_dir, docs)
    full = stamp != prev.get("stamp")
    key = _truth_key(truth)
    log(root, now, read, full, truth if key != prev.get("truth_key") else None)
    return {"skipped": False, "at": now, "stamp": stamp, "read": read, "art": art,
            "det": det_art, "uni": uni, "index": index, "cell_of": placed,
            "truth_key": key, "counts": docs["flood-meta.json"]["counts"],
            "impact": impact, "design_storm": design["summary"],
            "window": read["window"]["state"], "skew": read["skew"]["model_tier"],
            "publish": ship_(out_dir, prev.get("publish")), "error": None}


def line(state: dict) -> str:
    if state.get("skipped"):
        return "flood=skipped"
    if state.get("error"):
        return f"flood=error {state['error']}"
    c = state.get("counts") or {}
    return (f"flood window={state.get('window')} skew={state.get('skew')} "
            f"flagged={c.get('units_flagged')} fn={c.get('floodnet_detected')} "
            f"publish={(state.get('publish') or {}).get(UNGATED)} "
            f"{fo.line(state.get('impact'))} {ds.line(state.get('design_storm'))}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=live_export.OUT)
    ap.add_argument("--no-publish", action="store_true",
                    help="write the four files, upload nothing")
    args = ap.parse_args()
    root = data_root()
    now = datetime.now(timezone.utc)
    con = duck.connect()
    skip = (lambda out_dir, prev: {f: "not published" for f in ORDER})
    state = tick(con, root, args.out, None, now, ship_=skip if args.no_publish else None)
    print(line(state), flush=True)
    if state.get("error"):
        raise SystemExit(1)
    for name in [n for f in ORDER for n in FILES[f]]:
        print(f"  {args.out / name}  {(args.out / name).stat().st_size} B")


if __name__ == "__main__":
    main()
