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
        scores = root.joinpath(*EXPOSURE)
        if scores.exists():   # absent, never null: a root with no scores stamps none
            out["score_version"] = one_value(con, scores, "score_version")
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

ASSET_COLUMNS = ("asset_id", "kind", "name", "cell", "complex_id", "parent_asset_id")


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
    aid, kind, name, cell, complex_id, parent = unit(con, root, need(params, "asset_id"))
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
    aid, kind, name, cell, complex_id, parent = unit(con, root, need(params, "asset_id"))
    part = root.joinpath(*EXPOSURE)
    got = []
    if part.exists():   # a root with no F10 table scores NOTHING, and versions() says so
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
            model_id=model_id,
            # THE human-facing number is the within-kind rank, bounded (0, 1]. score_ref and
            # score_severe are the LINEAR PREDICTOR at F10's reference forcings -- negative
            # for nearly every Unit -- and travel as the raw model output they are.
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


# ---- the entry point ---------------------------------------------------------------

QUERIES = {"events_for_asset": events_for_asset, "exposure_of": exposure_of}


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
    projection also keeps GeoParquet's WKB `geometry` out of every payload."""
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
    # 2026-08-24: 0.115 s/call, 0.097 s of it versions() -- the same three stamps every
    # time. Fine for a tool call, ~16 min for ticket 05's 7,955-asset export; the upgrade
    # is a caller-supplied connection + stamps resolved once, NOT a cache keyed on a date.
    stamps = versions(con, root)   # first: an unstamped answer must be impossible
    return {"query": name, "mode": mode,
            **QUERIES[name](con, root, params or {}, mode),
            "versions": stamps}
