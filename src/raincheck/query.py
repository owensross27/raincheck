"""The query core (notify ticket 02 / spec sections 1-2; SEAM Q): one read entry point.

`query(name, params, data_root, mode)` is the ONLY way anything serves the flood tables.
The static export (ticket 05) and the MCP server (ticket 06) are renderers over it, so an
answer is fixed in one place and the licence is decided in one place.

THE LICENCE BOUNDARY is a parameter, never a property of the caller: `public` is the
DEFAULT, so a consumer that forgets is safe. What separates the two modes is one rule --
`public` ships COUNTS and F05's attachment facts, `local` ships the ROWS behind them:

  public   flood_events rows, flood_labels attachments (label_support, the decoded
           source_mix), per-source observation COUNTS, asset identity
  local    all of that plus the restricted classes: FloodNet depths, the observation rows
           themselves (FloodNet sensor ids, the MTA alert row and the station it named),
           and subwaydata-derived impact numbers [flood map l.66, F13, F16]

`events_for_asset` reads `gold/flood_labels` (F05's frozen 100 m attachment, POSITIVES
ONLY) joined to `silver/flood_events` for the windows. It NEVER re-attaches
`silver/flood_obs` to `ref/assets`: that join has exactly one owner and it is F05, and a
second copy of the rule would drift between the map and the model. The observation counts
are therefore EVENT-grain (every source's observations inside the event's window, city
wide) and are named `event_*` to say so; the asset-grain facts are `sources`,
`label_support` and `depth_mm`, all of them read straight out of F05's row.

`exposure_of` reads `gold/flood_exposure` (F10's published score, ONE row per Unit) and
does not recompute any part of it -- above all not the complex rule, which F10 already
applied and verified against an independent recomputation for all 445 complexes.

`assets_in_area` and `obs_near` are the AREA pair (ticket 04). CELL IS THE ONLY AREA KEY
in v1: a bbox snaps to a Cell set before anything is read, an arbitrary polygon is not a
parameter (a caller holding one resolves it to Cells itself), and a Zone appears nowhere --
it is a presentation overlay the page resolves through the static Cell-to-Zone lookup at
serving time, so it is neither a stored key nor a query parameter. Both are BOUNDED, and
`area_too_large` names the cap it hit. `obs_near` is `local` only: it returns observation
ROWS by definition, so `public` refuses it with `restricted_source` rather than filtering
it into a different answer wearing the same name.

Complex grain: a complex's history is the union over its child entrances (max depth,
union of support), because a complex called dry when the entrance you did not use flooded
is the failure story 4 names. A station is a Carrier -- it carries no history of its own
and raises `not_a_scored_unit` naming the complex to ask instead. The two queries draw the
Unit/Carrier line from DIFFERENT authorities and disagree about entrances ON PURPOSE: a
history is F05's LABEL_KINDS (an entrance carries labels of its own), a score is F10's
table MEMBERSHIP (an entrance publishes no row -- its score exists only inside its
complex's max).

Conventions: absent, never null (an unpublishable value is an ABSENT KEY); every payload
carries the version stamps of the universe that answered it, and an unresolvable stamp is
`version_unresolved` rather than an unstamped answer; Cell ids cross the boundary as H3
hex strings (an int64 H3 id does not survive JSON's 2^53); DuckDB only, no Spark.
"""
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from raincheck import duck, flood_labels as fl, ref
from raincheck.paths import as_root, data_root as default_root

MODES = ("public", "local")     # public FIRST: the default is the restrictive one
STAMP = "%Y-%m-%dT%H:%M:%SZ"    # the repo's JSON timestamp, as in live_export/export.sql
NO_EVENTS = "no events on record"

# The named reasons. The first five are the spec's frozen vocabulary (section 5); the last
# three are caller-shape errors this seam needs so no consumer ever sees a bare traceback.
REASONS = ("unknown_asset", "not_a_scored_unit", "area_too_large", "restricted_source",
           "version_unresolved", "unknown_query", "unknown_mode", "missing_param")


class QueryError(Exception):
    """A typed, named failure: `reason` is machine-readable, `detail` carries the recovery
    hint (which complex to ask, which cap was hit, which stamp would not resolve)."""

    def __init__(self, reason: str, **detail):
        if reason not in REASONS:
            raise ValueError(f"{reason} is not one of {REASONS}")
        self.reason, self.detail = reason, detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


# ---- payload discipline ------------------------------------------------------------

def pack(**kv) -> dict:
    """The absent-key convention: an unpublishable value is an ABSENT KEY, never a null.
    Empty is not absent -- [] and 0 publish, which is what "no events on record" needs."""
    return {k: v for k, v in kv.items() if v is not None}


def jsonable(v):
    """Every leaf a JSON encoder accepts. Timestamps take the repo's stamp; a Cell is its
    H3 hex string; a DuckDB DECIMAL (subwaydata call counts) is a float."""
    if isinstance(v, datetime):
        return v.strftime(STAMP)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def cell_id(cell: int | None) -> str | None:
    """H3 r8 ids cross the boundary as hex -- the same string `cell:<h3>` asset ids carry.
    613229535722209279 is not representable in a JSON number reader that uses doubles."""
    return None if cell is None else format(cell, "x")


def sources(source_mix: int | None) -> list[str]:
    """F05's bitmask, decoded through F05's own map (never a second copy of the order)."""
    return [s for s, b in fl.SOURCE_BIT.items() if source_mix and source_mix & b]


# ---- version stamps ----------------------------------------------------------------

EXPOSURE = ("gold", "flood_exposure")   # F10's table: the stamp and exposure_of both read it


def readable(root: Path, *parts: str) -> bool:
    """Is there a TABLE there, not merely a directory? A build that died between
    `mkdir` and `pq.write_table` leaves an empty one, and on such a root DuckDB's globber
    raises IOException -- which `versions()` would turn into `version_unresolved` for the
    WHOLE root, killing `events_for_asset`, which reads no score at all. The repo's own
    marker convention says the same thing: data first, marker last, a missing part file
    reads UNBUILT."""
    return any(root.joinpath(*parts).rglob("*.parquet"))


def one_value(con, table_root: Path, column: str) -> str:
    got = duck.table(con, table_root).project(column).distinct().fetchall()
    if len(got) != 1:
        raise QueryError("version_unresolved", table=str(table_root), column=column,
                         distinct=len(got))
    return got[0][0]


def versions(con, root: Path) -> dict:
    """The universe that answered. Resolved BEFORE any answer is built, so an unstamped
    payload cannot exist -- not even the empty-history one.

    `score_version` (ticket 03) joins on any root that publishes `gold/flood_exposure`, and
    is ABSENT -- never null -- on a root that has no scores to stamp. It reaches
    `files/index.json` too, because `contract.index()` calls this same function; that is
    additive to a promise made of (family, key, content type) triples, so it owes no
    `contract.CONTRACT` bump.

    `model_id` does NOT join here and cannot: F10 ships TWO of them (`point:l2_logistic`
    scores stops and complexes, `cell:l2_logistic` scores Cells), so it is a fact about the
    ANSWER, not about the universe -- `one_value` would read the real table as
    `version_unresolved` and break every query on it. It rides on exposure_of's payload."""
    try:
        out = {"assets_version": ref.assets_version(root),
               "spine_version": one_value(con, root / "silver" / "flood_events",
                                          "spine_version"),
               "label_version": one_value(con, root / "gold" / "flood_labels",
                                          "label_version")}
        if readable(root, *EXPOSURE):   # absent, never null: no scores, no score stamp
            out["score_version"] = one_value(con, root.joinpath(*EXPOSURE),
                                             "score_version")
        return out
    except QueryError:
        raise
    except Exception as e:
        raise QueryError("version_unresolved", root=str(root), error=str(e)) from e


# ---- events_for_asset --------------------------------------------------------------

# The complex rollup rides the registry's own parent link: a complex answers for itself
# AND its children (entrances carry radius/polygon labels, stations carry none by
# construction -- F05's LABEL_KINDS). max(depth) / union(support) is F10's aggregate rule.
EVENTS_SQL = """
SELECT e.event_id, e.day_start, e.day_end, e.n_days,
       e.window_start_utc, e.window_end_utc, e.event_class, e.flood_cause,
       bit_or(l.source_mix) AS source_mix, max(l.depth_mm) AS depth_mm,
       list_sort(list_distinct(flatten(list(l.label_support)))) AS label_support
  FROM labels l JOIN events e USING (event_id)
 WHERE l.asset_id IN {units}
 GROUP BY ALL
 ORDER BY e.day_start, e.event_id
"""

# EVENT-grain, and city wide: these are the observations inside the event's window, not a
# re-attachment to this asset. Naming them event_* is the whole guard against that misread.
COUNTS_SQL = """
SELECT e.event_id, o.source, count(*) AS n
  FROM obs o JOIN events e
    ON o.ts_utc >= e.window_start_utc AND o.ts_utc < e.window_end_utc
 WHERE e.event_id IN {events}
 GROUP BY 1, 2 ORDER BY 1, 2
"""

OBS_SQL = """
SELECT e.event_id, o.source, o.source_id, o.ts_utc, o.obs_ts_kind, o.cell, o.depth_mm, o.text
  FROM obs o JOIN events e
    ON o.ts_utc >= e.window_start_utc AND o.ts_utc < e.window_end_utc
 WHERE e.event_id IN {events}
 ORDER BY e.event_id, o.source, o.ts_utc, o.source_id
"""

IMPACT_SQL = """
SELECT e.event_id, count(*) AS n_hours,
       round(min(i.service_ratio), 4) AS min_service_ratio,
       round(max(i.max_gap_ratio), 4) AS max_gap_ratio
  FROM read_parquet(?) i JOIN events e ON i.day BETWEEN e.day_start AND e.day_end
 WHERE i.complex_id = ? AND e.event_id IN {events}
 GROUP BY 1 ORDER BY 1
"""

IMPACT_FILE = ("snapshots", "subwaydata", "impact", "subway_complex_hour.parquet")

ASSET_COLUMNS = ("asset_id", "kind", "name", "cell", "complex_id", "parent_asset_id",
                 "lon", "lat")   # lon/lat: obs_near takes its point from an asset id


def unit(con, root: Path, asset_id: str) -> tuple:
    """The registry row behind an asset_id, or `unknown_asset`. Which of those rows is a
    Unit is the QUERY's rule, not this one's -- the two queries answer it from different
    authorities (see the module docstring) -- so this resolves identity and nothing else."""
    view(con, root, "ref", "assets", name="assets", columns=ASSET_COLUMNS)
    got = con.execute(f"SELECT {', '.join(ASSET_COLUMNS)} FROM assets WHERE asset_id = ?",
                      [asset_id]).fetchall()
    if not got:
        raise QueryError("unknown_asset", asset_id=asset_id)
    return got[0]


def events_for_asset(con, root: Path, params: Mapping, mode: str) -> dict:
    """One Unit's dated flood history: `gold/flood_labels` joined to `silver/flood_events`."""
    aid, kind, name, cell, complex_id, parent, *_ = unit(con, root,
                                                         need(params, "asset_id"))
    if kind not in fl.LABEL_KINDS:  # a Carrier is located and aggregated, never scored
        raise QueryError("not_a_scored_unit", asset_id=aid, kind=kind, ask=parent)

    # the Unit's own row, plus its children when it is a complex -- resolved once, so the
    # three reads below all mean the same "this Unit" without repeating the rule
    units = [u for (u,) in con.execute(
        "SELECT asset_id FROM assets WHERE asset_id = ? OR (? = 'complex' "
        "AND parent_asset_id = ?) ORDER BY asset_id", [aid, kind, aid]).fetchall()]
    view(con, root, "gold", "flood_labels", name="labels",
         columns=("asset_id", "event_id", "source_mix", "depth_mm", "label_support"))
    view(con, root, "silver", "flood_events", name="events",
         columns=("event_id", "day_start", "day_end", "n_days", "window_start_utc",
                  "window_end_utc", "event_class", "flood_cause"))
    rows = con.execute(EVENTS_SQL.format(units=holes(len(units))), units).fetchall()

    counts, obs, impact = {}, {}, {}
    if rows:
        ids = [r[0] for r in rows]
        view(con, root, "silver", "flood_obs", name="obs",
             columns=("source", "source_id", "ts_utc", "obs_ts_kind", "cell", "depth_mm",
                      "text"))
        for event_id, source, n in con.execute(
                COUNTS_SQL.format(events=holes(len(ids))), ids).fetchall():
            counts.setdefault(event_id, {})[source] = n
        if mode == "local":
            for r in con.execute(OBS_SQL.format(events=holes(len(ids))), ids).fetchall():
                obs.setdefault(r[0], []).append(pack(
                    source=r[1], source_id=r[2], ts_utc=jsonable(r[3]), obs_ts_kind=r[4],
                    cell=cell_id(r[5]), depth_mm=r[6], text=r[7] or None))
            impact = subway_impact(con, root, kind, complex_id, ids)

    events = [pack(
        event_id=r[0], day_start=jsonable(r[1]), day_end=jsonable(r[2]), n_days=r[3],
        window_start_utc=jsonable(r[4]), window_end_utc=jsonable(r[5]),
        event_class=r[6], flood_cause=r[7],
        sources=sources(r[8]), label_support=list(r[10]),
        depth_mm=r[9] if mode == "local" else None,          # FloodNet-derived: local only
        event_source_counts=counts.get(r[0]),
        event_observations=obs.get(r[0]) or None,            # the rows behind the counts
        impact=impact.get(r[0]),                             # subwaydata-derived: local only
    ) for r in rows]

    return pack(
        asset=pack(asset_id=aid, kind=kind, name=name, cell=cell_id(cell),
                   complex_id=complex_id),
        n_events=len(events), events=events,
        reason=None if events else NO_EVENTS)


def subway_impact(con, root: Path, kind: str, complex_id: str | None,
                  event_ids: list[str]) -> dict:
    """subwaydata.nyc carries no data licence: these numbers are local-page-only and the
    snapshots never leave <root>/snapshots [flood_impact]. Absent when unmeasured."""
    path = root.joinpath(*IMPACT_FILE)
    if kind != "complex" or complex_id is None or not path.exists():
        return {}
    return {r[0]: pack(n_hours=r[1], min_service_ratio=r[2], max_gap_ratio=r[3])
            for r in con.execute(IMPACT_SQL.format(events=holes(len(event_ids))),
                                 [str(path), complex_id, *event_ids]).fetchall()}


# ---- exposure_of -------------------------------------------------------------------

EXPOSURE_COLUMNS = ("asset_id", "model_id", "score_ref", "score_severe", "score_index",
                    "surge_margin_ft", "flags")
FALLBACK_FLAG = "score_fallback_kind_median"   # F10: the kind median, not an evaluation


def exposure_of(con, root: Path, params: Mapping, mode: str) -> dict:
    """One Unit's published exposure: F10's row, READ.

    Nothing here is recomputed, and the complex rule least of all: the `kind='complex'` row
    already holds the max over its child entrance scores, verified at F10's landing against
    an independent SQL recomputation for all 445. It is not even re-derivable downstream --
    entrances publish no row -- so a second max would be a second implementation of a rule
    with one home.

    `not_a_scored_unit` fires on ABSENCE from that table, which is the Unit/Carrier rule
    made concrete rather than re-stated: stations and entrances are Carriers and their
    `parent_asset_id` names the complex to ask instead; a ref Cell outside F10's fit set
    (2,762 of 4,113 on the real root) is simply not scored and has no parent, so `ask` is
    absent rather than null.

    `mode` does not change this answer. The licence boundary is one rule about MTA /
    FloodNet / subwaydata ROWS; a score built from elevation, stormwater class and public
    precip is in no restricted class, so both modes get the same object.
    """
    aid, kind, name, cell, complex_id, parent, *_ = unit(con, root,
                                                         need(params, "asset_id"))
    got = []
    if readable(root, *EXPOSURE):   # no F10 table means NOTHING is scored, and versions()
                                    # says so by dropping the stamp rather than failing
        view(con, root, *EXPOSURE, name="exposure", columns=EXPOSURE_COLUMNS)
        got = con.execute("SELECT model_id, score_ref, score_severe, score_index, "
                          "surge_margin_ft, flags FROM exposure WHERE asset_id = ?",
                          [aid]).fetchall()
    if not got:
        raise QueryError("not_a_scored_unit", asset_id=aid, kind=kind, **pack(ask=parent))
    model_id, score_ref, score_severe, score_index, margin, flags = got[0]
    return pack(
        asset=pack(asset_id=aid, kind=kind, name=name, cell=cell_id(cell),
                   complex_id=complex_id),
        exposure=pack(
            # WHAT THE NUMBER IS ABOUT, carried so no consumer has to invent it: F05's
            # estimand, the same constant F10 hashes into score_version. Flooding that was
            # REPORTED, not everywhere water stood.
            estimand=fl.ESTIMAND,
            model_id=model_id,
            # THE human-facing number is the rank WITHIN THIS UNIT'S KIND, bounded (0, 1] --
            # F10 computes it per kind, so the three Units at 1.0 are one bus stop, one
            # complex and one Cell, and a cross-kind ranking needs `asset.kind` beside it.
            # score_ref and score_severe are the LINEAR PREDICTOR at F10's reference
            # forcings -- negative for nearly every Unit -- and travel as the raw model
            # output they are. Neither is a probability.
            score_index=score_index, score_ref=score_ref, score_severe=score_severe,
            # 404 Units have no point elevation behind them: ABSENT, never 0.0 -- a zero
            # margin means the water is at the doorway. `no_surge_margin` carries the reason.
            surge_margin_ft=margin,
            # F10's closed vocabulary, passed through unworded; each flag's one-line meaning
            # is published under `flags` in research/flood-10-coefficients.json.
            flags=list(flags),
            # 60 bus stops outside the DEM footprint score on the kind MEDIAN, not on a model
            # evaluation. Derivable from the flags, said explicitly so a renderer cannot
            # present one as a modelled rank by simply not looking.
            modelled=FALLBACK_FLAG not in flags))


# ---- the area pair: assets_in_area and obs_near (ticket 04) -------------------------

CELL_CAP = 64            # Cells per request: ~47 km2, a large neighbourhood. The city is
                         # 4,113 Cells, so an area request cannot accidentally ask for it.
RADIUS_M = 500.0         # obs_near's default reach
RADIUS_CAP_M = 2000.0    # and its ceiling (1,177 rows at Times Square, the dense case)
METRIC_CRS = "EPSG:32618"          # UTM 18N, metres: NYC sits wholly inside it
NO_ASSETS = "no assets in this area"

# The Cell set a bbox snaps to. A Cell is IN the box when its CENTROID is -- the same rule
# `ref/cell_zone` uses to put a Cell in a Zone (centroid point-in-polygon), so the project
# never holds two answers to "where is this Cell". `ref/assets`' kind='cell' rows carry
# exactly `ref/cells`' centroids (measured on the real root: max |delta| = 0.0 over all
# 4,113), so the box resolves out of the registry this query already reads rather than out
# of a second table whose absence would be a second failure mode.
BBOX_SQL = """
SELECT cell FROM assets
 WHERE kind = 'cell' AND lon BETWEEN ? AND ? AND lat BETWEEN ? AND ?
"""

# One row per asset in the area with the count of its flood history. The self-join IS the
# complex rollup `events_for_asset` applies (a complex answers for itself and its child
# entrances), and `count(DISTINCT event_id)` makes one event that reached two entrances one
# event -- exactly what that query's GROUP BY gives. The two are pinned to agree by
# test_the_area_count_is_the_history_events_for_asset_would_return.
AREA_SQL = """
SELECT a.asset_id, a.kind, a.name, a.cell, a.complex_id,
       count(DISTINCT l.event_id) AS n_events, max(l.event_id) AS last_event_id
  FROM assets a
  LEFT JOIN assets c ON c.asset_id = a.asset_id
                     OR (a.kind = 'complex' AND c.parent_asset_id = a.asset_id)
  LEFT JOIN labels l ON l.asset_id = c.asset_id
 WHERE a.cell IN {cells} AND a.kind IN {kinds}
 GROUP BY ALL
 ORDER BY a.kind, a.asset_id
"""

# Distance in METRES through a projection, never through ST_Distance_Sphere /
# ST_Distance_Spheroid: those take POINT_2D as (LATITUDE, LONGITUDE), and this project's
# geometry is CRS84 (lon, lat), so feeding them a stored point reads the axes swapped and
# returns a plausible WRONG number -- 143.5 m for a pair that is 248.5 m apart, measured on
# the fixture. UTM 18N agrees with the correctly-ordered spheroid to 0.93 m over a 3 km
# radius on the real table, and unlike the point-only spheroid it also answers for the
# MULTIPOLYGON rows (Sandy's inundation extent), which are observations too.
NEAR_SQL = """
WITH p AS (SELECT ST_Transform(ST_Point(?, ?), 'OGC:CRS84', '{crs}') AS g)
SELECT o.source, o.source_id, o.ts_utc, o.obs_ts_kind, o.cell, o.depth_mm, o.text,
       round(ST_Distance(ST_Transform(o.geometry, 'OGC:CRS84', '{crs}'), p.g), 1) AS distance_m
  FROM obs o, p
 WHERE ST_DWithin(ST_Transform(o.geometry, 'OGC:CRS84', '{crs}'), p.g, ?)
 ORDER BY distance_m, o.ts_utc, o.source, o.source_id
"""

OBS_COLUMNS = ("source", "source_id", "ts_utc", "obs_ts_kind", "cell", "depth_mm", "text",
               "geometry")


def number(value, param: str) -> float:
    """A caller-supplied number, or a NAMED refusal -- never a ValueError traceback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        raise QueryError("missing_param", param=param, value=str(value),
                         expect="a number") from None


def h3(value, param: str = "cells") -> int:
    """A Cell id as it crosses this boundary: the H3 HEX STRING, the same string a
    `cell:<h3>` asset id carries. The int64 is refused rather than accepted quietly,
    because 613229535722209279 is past 2^53 and a JSON reader using doubles has already
    corrupted it by the time it arrives -- an accepted int is an accepted wrong Cell."""
    try:
        return int(value, 16)
    except (TypeError, ValueError):
        raise QueryError("missing_param", param=param, value=str(value),
                         expect="an H3 hex string, e.g. 882a1072c1fffff") from None


def area(con, root: Path, params: Mapping) -> tuple[list[int], list[float] | None]:
    """The Cell set an area request resolves to, RESOLVED BEFORE ANYTHING IS READ.

    Cell is the only area key in v1. `cells` is a list of H3 hex strings; `bbox` is
    `[west, south, east, north]` and snaps to the Cells whose centroids it holds; given
    both, the area is their union, which is the only reading of "the area" that needs no
    precedence rule. An arbitrary polygon is not a parameter -- a caller holding one
    resolves it to Cells itself -- and neither is a Zone: a Zone is a presentation overlay
    the page resolves through the static Cell-to-Zone lookup at serving time, so it is
    neither a stored key nor a parameter here [CONTEXT.md, spec section 4].

    The cap is what keeps a tool call from asking for the city by accident, and it is
    enforced on the RESOLVED set, so a bbox the size of the state is refused by the same
    number as 4,113 hand-typed Cell ids."""
    if params.get("cells") is None and params.get("bbox") is None:
        raise QueryError("missing_param", param="cells|bbox")
    given = params.get("cells") or []
    cells = {h3(c) for c in ([given] if isinstance(given, str) else given)}

    box = params.get("bbox")
    if box is not None:
        if isinstance(box, str) or not hasattr(box, "__len__") or len(box) != 4:
            raise QueryError("missing_param", param="bbox", value=str(box),
                             expect="[west, south, east, north]")
        w, s, e, n = (number(v, "bbox") for v in box)
        (w, e), (s, n) = sorted((w, e)), sorted((s, n))   # a flipped box is still a box
        box = [w, s, e, n]
        view(con, root, "ref", "assets", name="assets", columns=ASSET_COLUMNS)
        cells |= {c for (c,) in con.execute(BBOX_SQL, [w, e, s, n]).fetchall()}

    if len(cells) > CELL_CAP:
        raise QueryError("area_too_large", n_cells=len(cells), cap=CELL_CAP,
                         **pack(bbox=box))
    return sorted(cells), box


def assets_in_area(con, root: Path, params: Mapping, mode: str) -> dict:
    """Every asset inside a Cell set, with the flood history each one carries.

    This is the question that does not know an asset id yet, so the answer is the ids plus
    enough to act on them: `n_events` is the history `events_for_asset` would return for
    that asset (the complex rollup included), and `last_event_id` is the most recent of
    them -- an event id is its date. An asset with no history publishes `n_events: 0` and
    no `last_event_id`, which is the same absent-never-null rule as everywhere else.

    STATIONS ARE NOT LISTED. They are Carriers: `events_for_asset` refuses them and names
    the complex to ask, so listing one here with a count would be a number for an asset
    that cannot be asked for it. The complex standing at the same doorway is listed and
    answers for them, which is F05's `LABEL_KINDS` and not a second rule.

    `mode` does not change this answer. It is built from `ref/assets` and F05's attachment
    counts, and a count is not a row -- the licence boundary is about MTA / FloodNet /
    subwaydata ROWS, so both modes get the same object."""
    cells, box = area(con, root, params)
    rows = []
    if cells:
        view(con, root, "ref", "assets", name="assets", columns=ASSET_COLUMNS)
        view(con, root, "gold", "flood_labels", name="labels",
             columns=("asset_id", "event_id"))
        rows = con.execute(
            AREA_SQL.format(cells=holes(len(cells)), kinds=holes(len(fl.LABEL_KINDS))),
            [*cells, *fl.LABEL_KINDS]).fetchall()
    assets = [pack(asset_id=r[0], kind=r[1], name=r[2], cell=cell_id(r[3]), complex_id=r[4],
                   n_events=r[5], last_event_id=r[6]) for r in rows]
    return pack(
        area=pack(cells=[cell_id(c) for c in cells], n_cells=len(cells), bbox=box),
        n_assets=len(assets), assets=assets,
        reason=None if assets else NO_ASSETS)


def obs_near(con, root: Path, params: Mapping, mode: str) -> dict:
    """What was OBSERVED near a point -- the rows, ordered by distance.

    `local` only, and refused by name in `public`. This returns observation rows by
    definition, and rows are exactly what the licence boundary withholds: FloodNet depths
    and sensor ids, the MTA alert row. A `public` version would have to filter to the
    permitted sources, which is a different answer wearing the same name, so the answer is
    a typed refusal instead [spec section 2; DEFAULT, overturned only by a licence change].

    This is NOT F05's attachment and must never be read as one: F05 owns which asset a
    report belongs to (`gold/flood_labels`, 100 m, geodesic, one owner). This asks a
    different question -- what a person standing here would have seen reported -- so it
    reads `silver/flood_obs` straight, by geometry, and answers for every source including
    the polygon ones.

    The point is `lon`/`lat`, or an `asset_id` resolved through the same identity seam
    every other query uses, so "near this stop" needs no coordinates in the caller."""
    if mode != "local":
        raise QueryError("restricted_source", query="obs_near", mode=mode, need=MODES[1])
    asset_id = params.get("asset_id")
    if asset_id is None:
        lon, lat = number(need(params, "lon"), "lon"), number(need(params, "lat"), "lat")
    else:
        asset_id, _kind, _name, _cell, _complex, _parent, lon, lat = unit(con, root, asset_id)
    radius = number(params.get("radius_m", RADIUS_M), "radius_m")
    if radius > RADIUS_CAP_M:
        raise QueryError("area_too_large", radius_m=radius, cap_m=RADIUS_CAP_M)
    if radius <= 0:
        raise QueryError("missing_param", param="radius_m", value=radius,
                         expect=f"a distance in metres, up to {RADIUS_CAP_M}")

    con.execute("LOAD spatial")     # ST_Transform / ST_DWithin, as export.py loads it
    view(con, root, "silver", "flood_obs", name="obs", columns=OBS_COLUMNS)
    rows = con.execute(NEAR_SQL.format(crs=METRIC_CRS), [lon, lat, radius]).fetchall()
    return pack(
        point=pack(lon=lon, lat=lat, radius_m=radius, asset_id=asset_id),
        n_observations=len(rows),
        observations=[pack(source=r[0], source_id=r[1], ts_utc=jsonable(r[2]),
                           obs_ts_kind=r[3], cell=cell_id(r[4]), depth_mm=r[5],
                           text=r[6] or None, distance_m=r[7]) for r in rows])


# ---- the entry point ---------------------------------------------------------------

QUERIES = {"events_for_asset": events_for_asset, "exposure_of": exposure_of,
           "assets_in_area": assets_in_area, "obs_near": obs_near}


def need(params: Mapping, key: str):
    if params.get(key) is None:
        raise QueryError("missing_param", param=key)
    return params[key]


def holes(n: int) -> str:
    """An IN list of placeholders -- values are never interpolated into SQL text."""
    return "({})".format(", ".join(["?"] * n))


def view(con, root: Path, *parts: str, name: str, columns) -> None:
    """A narrowed VIEW over a parquet root -- never `rel.arrow()`, which returns a LAZY
    RecordBatchReader on this same connection: registering two unconsumed readers back
    into it and joining them deadlocks at 0% CPU (wave-1 gate, KNOWN TRAPS). The
    projection also keeps GeoParquet's WKB `geometry` out of every payload.

    An UNBUILT table refuses by name here. A table is a PART FILE, not a folder: a build
    that died between its `mkdir` and its `pq.write_table` leaves an empty directory, and
    DuckDB's globber raises IOException on it -- a bare traceback out of a seam that
    promises typed errors. `version_unresolved` is what `versions()` already answers for
    exactly this root, so the reason is the module's existing one and not a ninth name."""
    if not readable(root, *parts):
        raise QueryError("version_unresolved", table="/".join(parts), root=str(root))
    duck.table(con, root.joinpath(*parts)).select(*columns).create_view(name)


def query(name: str, params: Mapping | None = None, data_root: Path | str | None = None,
          mode: str = MODES[0]) -> dict:
    """THE read entry point. Returns a JSON-able dict; raises QueryError, never a traceback."""
    if mode not in MODES:
        raise QueryError("unknown_mode", mode=mode, modes=list(MODES))
    if name not in QUERIES:
        raise QueryError("unknown_query", query=name, queries=sorted(QUERIES))
    root = as_root(data_root) if data_root is not None else default_root()
    con = duck.connect()
    # ponytail: one connection and one stamp resolution PER CALL. Measured on the real root
    # 2026-08-24 at 0.115 s/call, 0.097 s of it versions(); re-measured 2026-08-25 with the
    # fourth stamp (score_version) at 0.102 s for exposure_of and 0.167 s for a complex's
    # history -- the same stamps every time either way. Fine for a tool call; ticket 05 now
    # makes TWO calls per asset, ~27 min for its 7,955 assets. The upgrade is a
    # caller-supplied connection + stamps resolved once, NOT a cache keyed on a date.
    stamps = versions(con, root)   # first: an unstamped answer must be impossible
    return {"query": name, "mode": mode,
            **QUERIES[name](con, root, params or {}, mode),
            "versions": stamps}
