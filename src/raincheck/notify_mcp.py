"""The MCP tool layer (notify ticket 06 / spec section 5; SEAM Q's fourth renderer): an
agent gets four named tools over stdio instead of a database credential and a SQL prompt.

DISPATCH ONLY. Every tool here is `validate, select mode, call, return` over
`raincheck.query.query(name, params, data_root, mode)`; not one line of query logic lives
in this module, and a test walks its AST to keep it that way. The four tools ARE
`query.QUERIES` -- same names, same argument names -- so an agent that reads one payload
can feed a value straight back into the next tool without a translation table.

THERE IS NO SQL-PASSTHROUGH TOOL, PERMANENTLY. That is not a deferral: the licence
boundary, the area cap and the version stamps are all properties of `query()`, and a tool
that let an agent write its own SELECT would route around all three at once. The set is
frozen at four and `test_the_tool_set_is_query_QUERIES_and_nothing_else` goes red on a
fifth.

MODE IS FIXED AT STARTUP AND `public` IS THE DEFAULT. `local` needs the explicit
`--local` flag on the command line -- no environment variable reads it, because an
environment variable is exactly the thing a hosting platform sets by accident. A hosted
server that never passes the flag therefore cannot expose `obs_near` AT ALL: it refuses in
`public` with `restricted_source` before it reads any other argument.

TYPED REFUSALS REACH THE AGENT AS DATA, never as a traceback and never as a protocol
error: a `QueryError` comes back as `{"query", "mode", "error": {"reason", "detail"}}`,
where `reason` is one of `query.REASONS`' frozen eight and `detail` is the recovery hint
(which complex to ask, which cap was hit). `QueryError` is the ONLY exception caught --
anything else is a real defect and must not be dressed up as an answer.
"""
import sys
from importlib.util import find_spec
from pathlib import Path

from raincheck import query as q

NAME = "raincheck"
LOCAL = "--local"

# The four stamps every payload carries. `score_version` is legitimately ABSENT on a root
# that publishes no `gold/flood_exposure` -- absent, never null -- which is why the
# descriptions say "four, one of which can be missing" rather than promising four values.
# Pinned against `query.versions()` itself by test_the_named_stamps_are_the_stamps_the_seam
# _returns, so a fifth stamp cannot appear without this line moving.
STAMPS = ("assets_version", "spine_version", "label_version", "score_version")

VERSIONS_LINE = (
    "Every answer carries the version stamps of the universe that answered it, under "
    f"`versions`: {', '.join(STAMPS[:-1])} and {STAMPS[-1]}. The last one is ABSENT -- not "
    "null -- on a root that publishes no scores, so test for the key.")

INSTRUCTIONS = f"""\
Four read-only tools over raincheck's NYC flood dataset: which assets flooded and when,
how exposed an asset is, what is in an area, and what was observed near a point.

THERE IS NO SQL TOOL AND THERE WILL NOT BE ONE. Everything answerable here is answerable
through these four; a question they cannot answer is a question this dataset does not
hold, not a reason to reach for a query language.

MODE. The server runs in one mode, fixed at startup: `public` by default, `local` only
when it was started with the {LOCAL} flag. `public` ships counts and attachment facts;
`local` also ships the rows behind them (FloodNet depths and sensor ids, MTA alert rows,
subwaydata-derived impact numbers). Three of the four tools return the SAME object either
way -- mode changes the answer for `events_for_asset` and refuses `obs_near` outright.

ASSET IDS AND CELL IDS. An asset id is `bus:<id>`, `stn:<complex>`, `sta:<station>`,
`ent:<...>` or `cell:<h3-hex>`. An H3 Cell id crosses this boundary in BOTH directions as
its r8 HEX STRING, never the int64: 613229535722209279 is past 2^53 and a JSON reader
using doubles has already corrupted it. A `cell` value out of one tool goes straight back
into `cells` on another.

THE TWO ASSET TOOLS DISAGREE ABOUT ENTRANCES ON PURPOSE, and the refusal is not a bug. An
entrance has a HISTORY (it is labelled in its own right) and NO SCORE (its score exists
only inside its complex's max), so asking both tools about one entrance yields an answer
and a typed refusal. Stations carry neither and name their complex instead.

REFUSALS ARE DATA. A refused call returns `{{"query", "mode", "error": {{"reason",
"detail"}}}}` instead of a payload. `reason` is one of eight frozen names --
unknown_asset, not_a_scored_unit, area_too_large, restricted_source, version_unresolved,
unknown_query, unknown_mode, missing_param -- and `detail` is the recovery hint: which
complex to ask, which cap was hit, which argument was missing. Read `reason`, act on
`detail`; never retry a refusal unchanged.

ABSENT, NEVER NULL. An unpublishable value is a MISSING KEY, not a null. Test for
presence; a key that is there is a real value.

CITYWIDE AGGREGATES ARE STATIC FILES, NOT A TOOL. "Where flooded recently", "which
complexes carry a flood record" and "how many routes cross flood-prone ground" are
answered by the published `files/summary/` payloads (recent.json, complexes.json,
routes.json -- see docs/read-api-contract.md); fetch those instead of sweeping an asset
tool over the city.

{VERSIONS_LINE}"""

DESCRIPTIONS = {

    "events_for_asset": f"""\
One asset's dated flood history, oldest event first, with what each event was made of.

READS gold/flood_labels (F05's frozen 100 m attachment, POSITIVES ONLY) joined to
silver/flood_events for the windows, with the per-event observation counts from
silver/flood_obs; ref/assets resolves the id.

TAKES {{asset_id}}.

A COMPLEX ANSWERS FOR ITS ENTRANCES: `stn:<complex>` rolls up its own labels and every
child entrance's (max depth, union of support), which is why a complex called dry when the
doorway you actually use flooded is the failure this rollup exists to prevent. A STATION
(`sta:<id>`) carries no history of its own and refuses with `not_a_scored_unit`, naming
the complex to ask in `error.detail.ask`.

COUNTS ARE EVENT-GRAIN, not asset-grain: `event_source_counts` and `event_observations`
are every observation of that source inside the event's WINDOW, city wide -- they are not
a re-attachment of reports to this asset. The asset-grain facts are `sources`,
`label_support` and `depth_mm`.

SIZE. In `local` this payload also carries every observation row inside each event's
window (and, for a complex, subwaydata-derived impact hours): about 2 MB on a 73-event
Cell, against about 1 KB for the same asset in `public`. Ask for a Cell's history in
`local` only when you want the rows.

{VERSIONS_LINE}""",

    "exposure_of": f"""\
One asset's published flood exposure score -- how exposed it is, independent of any
particular storm.

READS gold/flood_exposure (F10's published score, ONE row per scored Unit, read and never
recomputed); ref/assets resolves the id.

TAKES {{asset_id}} -- the same argument name events_for_asset takes.

HOW TO READ THE NUMBERS, because most of them are easy to misreport:
- `score_index` is the RANK WITHIN THIS ASSET'S KIND, bounded (0, 1]. It is the
  human-facing number, and it is only comparable against assets of the same `asset.kind`
  -- the three Units at 1.0 are one bus stop, one complex and one Cell.
- `score_ref` and `score_severe` are the LINEAR PREDICTOR at F10's reference forcings.
  They are NEGATIVE for nearly every Unit and they are NOT probabilities. Do not present
  them to a person as a chance of flooding.
- `modelled: false` marks the 60 bus stops scored on their KIND'S MEDIAN rather than by a
  model evaluation. Never present one of those as a modelled rank.
- `surge_margin_ft` is ABSENT -- never 0.0 -- on the 404 Units with no point elevation
  behind them, because a zero margin would mean the water is AT the doorway. Read whether
  the key is there, not what it holds.
- `flags` is F10's closed vocabulary passed through unworded. Each flag's one-line meaning
  is published under `flags` in research/flood-10-coefficients.json; read it there rather
  than guessing from the name.
- `estimand` says what the score is about: flooding that was REPORTED, not everywhere
  water stood.

NOT SCORED, and each refuses with `not_a_scored_unit`: stations and entrances are Carriers
whose score exists only inside their complex's max, and `error.detail.ask` names that
complex; a ref Cell outside F10's fit set (2,762 of 4,113) has no parent to ask and
therefore has NO `ask` KEY AT ALL -- test for the key before you follow it.

`mode` does not change this answer at all: a score built from elevation, stormwater class
and public precipitation is in no restricted class.

{VERSIONS_LINE}""",

    "assets_in_area": f"""\
Every asset inside an area, each with the size of the flood history it carries. This is
the tool for a question that does not have an asset id in it yet.

READS ref/assets for the area and gold/flood_labels for the counts.

TAKES {{cells}} -- a list of H3 r8 HEX STRINGS, a lone string accepted -- or {{bbox}} =
[west, south, east, north], or BOTH, in which case the area is their UNION. One of the two
is required -- `missing_param` names `cells|bbox`. A bbox snaps to the Cells whose
CENTROIDS it holds before anything is read.

CELL IS THE ONLY AREA KEY. There is no polygon parameter -- a caller holding one resolves
it to Cells itself -- and no zone anywhere: a zone is a presentation overlay, not a stored
key. The area is bounded at {q.CELL_CAP} Cells ON THE RESOLVED SET (about 47 km2 of a
4,113-Cell city), so a bounding box the size of the state is refused by the same number as
a hand-typed list; past it, `area_too_large` carries the count and the cap so you can
retry smaller.

`n_events` IS EXACTLY the history `events_for_asset` would return for that asset, complex
rollup included, so an area can be filtered down to the assets that have actually flooded
without a call per asset. `last_event_id` is the most recent of them, and an event id is
its date. An asset with no history publishes `n_events: 0` and no `last_event_id`.

STATIONS ARE NOT LISTED. They are Carriers that `events_for_asset` refuses, so listing one
with a count would publish a number for an asset that cannot be asked for it; the complex
standing at the same doorway is listed and answers for them.

`mode` does not change this answer -- a count is not a row.

{VERSIONS_LINE}""",

    "obs_near": f"""\
The raw flood OBSERVATIONS near a point, NEAREST FIRST. Every source silver/flood_obs
holds, spelled as the payload spells them: `311` (service requests), `floodnet` (sensor
incidents, the only source carrying `depth_mm`), `mta_alert` (alert rows), `usgs_hwm`
(high-water marks) and `sandy` (inundation extent polygons). `obs_ts_kind` says which
clock a row's `ts_utc` is on: `incident`, `report` or `alert`.

LOCAL ONLY, AND THAT MEANS REFUSED, NOT THINNER. In `public` this refuses with
`restricted_source` BEFORE it reads any other argument, because it returns observation
ROWS by definition and rows are exactly what the licence boundary withholds. `local` is an
explicit {LOCAL} flag at startup, so a hosted server that never sets it can never expose
this tool at all -- there is no smaller public answer to retry for, and no argument you
can change to get one.

READS silver/flood_obs by geometry, distances in metres through EPSG:32618 (UTM 18N);
ref/assets resolves an asset_id to its point.

TAKES {{asset_id}}, or {{lon, lat}}, plus an optional {{radius_m}} -- default
{q.RADIUS_M:.0f} m, capped at {q.RADIUS_CAP_M:.0f} m, past which it refuses with
`area_too_large`.

THIS IS NOT F05's ATTACHMENT and must not be read as one. Which asset a report belongs to
has exactly one owner (gold/flood_labels, 100 m, geodesic) and that is what
`events_for_asset` and `assets_in_area` report. This asks a different question -- what a
person standing at this point would have seen reported nearby -- so it reads every source
straight, including the polygon ones, and a row here is not a claim that the nearest asset
flooded.

{VERSIONS_LINE}""",
}


def refusal(name: str, mode: str, e: q.QueryError) -> dict:
    """A typed refusal as DATA. `reason` is the machine-readable name out of the seam's
    frozen eight; `detail` is the recovery hint, kept whole and under its own key so a
    detail carrying `query`/`mode` (restricted_source does) cannot shadow the envelope."""
    return {"query": name, "mode": mode, "error": {"reason": e.reason, "detail": e.detail}}


def tools(data_root: Path | str | None = None, mode: str = q.MODES[0]) -> dict:
    """The four tools, bound to one root and one mode. THIS IS THE WHOLE SERVER minus the
    protocol: the callables below are plain Python, so the dispatch tests never start a
    session, and the MCP SDK is not imported at all until `server()` runs.

    Every argument is passed through under the name the caller used, and `pack` drops the
    ones left unset so an omitted argument is ABSENT rather than an explicit null -- which
    is what lets `query` apply its own defaults (`radius_m`) and raise its own
    `missing_param` (`cells|bbox`). Nothing is defaulted, validated or renamed here."""

    def call(name: str, **params) -> dict:
        try:
            return q.query(name, q.pack(**params), data_root, mode)
        except q.QueryError as e:      # the ONLY exception caught: anything else is a bug
            return refusal(name, mode, e)

    def events_for_asset(asset_id: str) -> dict:
        return call("events_for_asset", asset_id=asset_id)

    def exposure_of(asset_id: str) -> dict:
        return call("exposure_of", asset_id=asset_id)

    def assets_in_area(cells: list[str] | str | None = None,
                       bbox: list[float] | None = None) -> dict:
        return call("assets_in_area", cells=cells, bbox=bbox)

    def obs_near(asset_id: str | None = None, lon: float | None = None,
                 lat: float | None = None, radius_m: float | None = None) -> dict:
        return call("obs_near", asset_id=asset_id, lon=lon, lat=lat, radius_m=radius_m)

    return {"events_for_asset": events_for_asset, "exposure_of": exposure_of,
            "assets_in_area": assets_in_area, "obs_near": obs_near}


def available() -> bool:
    return find_spec("mcp") is not None


def mode_of(argv) -> str:
    """The ONLY way `local` is ever selected: this flag, on the command line. No
    environment variable is read -- an env var is what a hosting platform sets by
    accident, and `obs_near`'s refusal is only worth anything if it cannot be flipped on
    without someone typing it."""
    argv = list(argv)
    if LOCAL in argv:
        argv.remove(LOCAL)
        mode = q.MODES[1]
    else:
        mode = q.MODES[0]
    if argv:
        raise SystemExit(f"usage: python -m raincheck.notify_mcp [{LOCAL}]"
                         f"  (unknown: {' '.join(argv)})")
    return mode


def server(data_root: Path | str | None, mode: str):
    """The MCP server, tools registered. The SDK is imported HERE and nowhere else, so a
    tree without it still imports this module, still runs every dispatch test, and says
    something useful if you try to serve.

    `mode` IS REQUIRED and deliberately has no default: `tools()` holds the safe one and
    `mode_of()` is the only thing that reads the world, and two copies of "public is the
    default" is one copy too many -- a mutation round flipped this one to `local` and
    nothing went red, because `main()` always passes a mode and nobody else was calling it.

    Argument schemas are the SDK's, derived from the four signatures above -- which is why
    the bound names (`asset_id`, `cells`, `bbox`, `lon`, `lat`, `radius_m`) are the query
    seam's own names and cannot drift into a translation layer."""
    if not available():
        raise SystemExit("the MCP SDK is not installed: pip install -e '.[mcp]'")
    from mcp.server.mcpserver import MCPServer     # mcp 2.x (1.x called this FastMCP)

    srv = MCPServer(NAME, instructions=INSTRUCTIONS)
    for name, fn in tools(data_root, mode).items():
        srv.add_tool(fn, name=name, description=DESCRIPTIONS[name])
    return srv


def main(argv: list[str] | None = None) -> int:
    """stdio, and nothing else. No port is opened here and none is meant to be."""
    server(None, mode_of(sys.argv[1:] if argv is None else argv)).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
