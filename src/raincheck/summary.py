"""`make summary`: the three aggregate payloads under `files/summary/` (frontend2 04).

They answer the questions an API consumer (or an agent pointed here by the query
server's instructions) actually asks, without a query seam call per asset:

  recent.json      where flooded recently — the trailing RECENT_DAYS of the event spine,
                   newest first, each event with its labelled-asset counts and the Cells
                   it touched
  complexes.json   which complexes carry a flood record — through SEAM Q's own sweep
                   (`history.flooded`), so a complex's count includes its entrances'
                   history exactly as `events_for_asset` would answer it
  routes.json      how many routes, and each route's crossing facts — a projection of
                   `gold/route_flood` (flood-build 21a), one row per
                   (route_id, direction_id)

**A NULL share is not a zero.** `share_len_limited` and `share_len_extreme` are NULL on
every row today — no current-sea-level source exists for either scenario — and `0.0`
would be a claim that the route is dry. A share column that is entirely NULL is not
written per row at all; `not_published` carries the reason, DERIVED from flood-build
19's own `stormwater_extent.SCENARIOS`/`UNREADABLE` through `flood_route.unsourced`,
never retyped here. A sourced column arriving all-NULL is refused outright rather than
silently dropped — that would be the compressed-FGDB lie in a new coat.

**`share_len_not_analyzed` is published beside `share_len_moderate`, or neither.** One
real route runs 80.5% of its length through ground DEP excluded from analysis; its
flooded share is honestly 0.0, and a payload carrying only the flooded share would call
that route safe. Where both are NULL on a row (a route with no measurable geometry)
both keys are absent — never one without the other.

**Every claim is DESCRIPTIVE.** "Crosses n_cells_flood_prone Cells" is supported;
"is slower because it floods" is the excluded statistical claim (gated on the backfill,
wave 10+), and nothing here states or implies it. Route ids are facts and render as
text; no roundel, bullet or line colour ships anywhere near this surface (MTA IP).

**Re-export is byte-identical**: every aggregate is ordered inside its own statement,
every assembled list is re-sorted on a total order, no wall clock touches any file (the
`recent` window is anchored on the spine's own newest day, not on today), and the only
numbers computed here are counts. Table values pass through unrounded — rounding
`share_len_moderate` here would publish a different value than the table holds. The
tree is staged and swapped whole, so `make publish FAMILY=summary` can never ship half
a build.

Written under `web/files/summary/`, a TREE family: `contract.PROMISE[1]` freezes the
prefix, the file names inside it are this writer's, and no `contract.CONTRACT` bump is
owed for adding one.

Run: make summary        (needs the flood universe and `gold/route_flood` — `make flood-route`)
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

from raincheck import duck, flood_route, history, publish, query
from raincheck.flood_labels import LABEL_KINDS
from raincheck.paths import data_root

FAMILY = "summary"                 # publish.FAMILIES[FAMILY].src() is the one home for the path
FILES = ("recent.json", "complexes.json", "routes.json")
RECENT_DAYS = 365                  # trailing window, anchored on the spine's newest day_end
ROUTE_STAMPS = ("label_version", "features_version", "zip_sha256", "route_flood_version")
JSON = history.JSON                # compact, machine-read payloads, same as the history tree

LABEL = "descriptive flood history - never a forecast and never a detector input"
CAVEATS_RECENT = (
    "counts are labelled-asset counts at each kind for the event, from the published "
    "attachment (gold/flood_labels) - they are not a re-attachment and not report counts",
    "cells are H3 r8 hex strings, the same spelling files/cells.geojson keys on, so the "
    "two join without a lookup",
    "the window is anchored on the newest event day the spine holds, not on today - a "
    "stale file describes a stale spine, and the reader dates the file from its own "
    "HTTP response",
)
CAVEATS_COMPLEXES = (
    "a complex answers for itself and its child entrances - the same rollup "
    "events_for_asset applies, so these counts match that query exactly",
    "names are not unique; print the asset_id beside the name",
)
CAVEATS_ROUTES = (
    "descriptive only: a route crosses these Cells and this ground - whether it is "
    "slower because it floods is a statistical claim this surface does not make",
    "share_len_not_analyzed is DEP's exclusion mask, ground DEP did not model; read it "
    "beside share_len_moderate or excluded ground reads as dry",
    "a share column listed under not_published is NULL at the source, never zero - the "
    "reason names the missing dataset",
)

EVENTS_SQL = f"""
SELECT event_id, day_start, day_end, n_days, event_class, flood_cause
  FROM events
 WHERE day_end >= (SELECT max(day_end) FROM events) - INTERVAL {int(RECENT_DAYS)} DAY
 ORDER BY day_start DESC, event_id DESC
"""
WINDOW_SQL = f"""
SELECT max(day_end) - INTERVAL {int(RECENT_DAYS)} DAY, max(day_end) FROM events
"""
KINDS_SQL = """
SELECT event_id, kind, count(DISTINCT asset_id) FROM labels GROUP BY event_id, kind
"""
LABELS_SQL = """
SELECT event_id, bit_or(source_mix), max(depth_mm),
       list_sort(list_distinct(list(cell)))
  FROM labels GROUP BY event_id
"""
ROUTES_SQL = """
SELECT {columns} FROM route_flood ORDER BY route_id, direction_id
"""


class Refused(Exception):
    """The build would publish a lie or half a family. rc 1."""


def recent(con, root: Path) -> dict:
    """The trailing window of the event spine, newest first, with event-grain counts."""
    query.view(con, root, "silver", "flood_events", name="events",
               columns=("event_id", "day_start", "day_end", "n_days",
                        "event_class", "flood_cause"))
    query.view(con, root, "gold", "flood_labels", name="labels",
               columns=("asset_id", "kind", "event_id", "cell", "source_mix", "depth_mm"))
    kinds: dict[str, dict[str, int]] = {}
    for event_id, kind, n in con.execute(KINDS_SQL).fetchall():
        kinds.setdefault(event_id, {})[kind] = n
    labels = {r[0]: r[1:] for r in con.execute(LABELS_SQL).fetchall()}
    since, until = con.execute(WINDOW_SQL).fetchone()
    events = []
    for event_id, day_start, day_end, n_days, event_class, cause in (
            con.execute(EVENTS_SQL).fetchall()):
        mix, depth, cells = labels.get(event_id) or (None, None, [])
        by_kind = kinds.get(event_id) or {}
        events.append(query.pack(
            event_id=event_id, day_start=query.jsonable(day_start),
            day_end=query.jsonable(day_end), n_days=n_days, event_class=event_class,
            flood_cause=cause, sources=query.sources(mix), depth_mm=depth,
            n_assets={k: by_kind.get(k, 0) for k in sorted(LABEL_KINDS)},
            cells=[query.cell_id(c) for c in cells]))
    return {"window": {"since": query.jsonable(since.date()),
                       "until": query.jsonable(until),
                       "days": RECENT_DAYS},
            "n_events": len(events), "events": events}


def complexes(con, root: Path) -> dict:
    """Every complex with a flood record, through the seam's own sweep — so the count is
    exactly what `events_for_asset` answers, entrance rollup included, and a complex
    whose only history is its entrances' is listed rather than lost."""
    cells, coords = history.registry(con, root)
    rows = [a for a in history.flooded(con, root, cells) if a["kind"] == "complex"]
    out = []
    for a in sorted(rows, key=lambda a: (-a["n_events"], a["asset_id"])):
        lon, lat = coords[a["asset_id"]]
        out.append(query.pack(
            asset_id=a["asset_id"], name=a.get("name"),
            lon=round(lon, history.COORD_DP), lat=round(lat, history.COORD_DP),
            cell=a["cell"], n_events=a["n_events"], last_event_id=a.get("last_event_id")))
    return {"n_complexes": len(out), "complexes": out}


def routes(con, root: Path) -> dict:
    """`gold/route_flood` as a payload: the pass-through facts, the published share
    columns, and a reason for every share column the table cannot honestly carry."""
    if not query.readable(root, "gold", "route_flood"):
        raise Refused(f"routes.json: no gold/route_flood under {root} - "
                      "build it first (make flood-route)")
    duck.table(con, root / "gold" / "route_flood").create_view("route_flood")

    shares = (*flood_route.SHARE_COLUMNS, flood_route.MASK_COLUMN)
    filled = dict(zip(shares, con.execute(
        "SELECT {} FROM route_flood".format(
            ", ".join(f"count({c})" for c in shares))).fetchone()))
    not_published = {}
    for column in flood_route.SHARE_COLUMNS:
        if filled[column]:
            continue
        reason = flood_route.unsourced(column.removeprefix("share_len_"))
        if reason is None:
            raise Refused(f"routes.json: {column} is entirely NULL but its scenario has "
                          "a current-sea-level source - refusing to publish a silent "
                          "empty share (the compressed-FGDB lie)")
        not_published[column] = reason
    published = [c for c in shares if filled[c]]
    if any(c != flood_route.MASK_COLUMN for c in published) and not filled[
            flood_route.MASK_COLUMN]:
        raise Refused("routes.json: a flooded share is published without "
                      f"{flood_route.MASK_COLUMN} beside it - excluded ground would "
                      "read as dry")

    facts = ("route_id", "direction_id", "n_shapes", "length_m", "n_cells",
             "n_cells_flood_prone", *published, "n_flood_events", "last_event_day")
    got = con.execute(ROUTES_SQL.format(
        columns=", ".join(facts + ROUTE_STAMPS))).fetchall()
    stamps = {}
    for i, name in enumerate(ROUTE_STAMPS, start=len(facts)):
        values = {r[i] for r in got}
        if len(values) != 1:
            raise Refused(f"routes.json: {len(values)} distinct {name} in one table - "
                          "a mixed-stamp table is two builds, not one")
        stamps[name] = values.pop()
    rows = [query.pack(**{k: query.jsonable(v) for k, v in zip(facts, r)}) for r in got]
    return {"n_routes": len(rows), "source": {"table": "gold/route_flood", **stamps},
            "not_published": not_published, "routes": rows}


def build(con, root: Path, out_dir: Path) -> dict:
    """Write all three files, or none: staged into a sibling and swapped whole, the same
    two-rename dance `history.build` does and for the same reason — `summary` is a TREE
    family, so `publish` has no file list to refuse a partial build with."""
    stamps = query.versions(con, root)
    docs = {"recent.json": recent(con, root),
            "complexes.json": complexes(con, root),
            "routes.json": routes(con, root)}
    caveats = {"recent.json": CAVEATS_RECENT, "complexes.json": CAVEATS_COMPLEXES,
               "routes.json": CAVEATS_ROUTES}

    staging = out_dir.with_name(out_dir.name + history.STAGING)
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    for name in FILES:
        doc = {**docs[name],
               "strings": {"label": LABEL, "caveats": list(caveats[name])},
               "versions": stamps}
        (staging / name).write_text(json.dumps(doc, **JSON) + "\n")
    old = out_dir.with_name(out_dir.name + history.PREVIOUS)
    shutil.rmtree(old, ignore_errors=True)
    if out_dir.exists():
        out_dir.replace(old)
    staging.replace(out_dir)
    shutil.rmtree(old, ignore_errors=True)
    return {name: (out_dir / name).stat().st_size for name in FILES}


def main() -> None:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    con = duck.connect()
    try:
        sizes = build(con, data_root(), publish.FAMILIES[FAMILY].src())
    except (Refused, query.QueryError) as exc:
        print(f"summary: not written - {exc}", file=sys.stderr)
        raise SystemExit(1)
    finally:
        con.close()
    for name, size in sizes.items():
        print(f"  {FAMILY}/{name}: {size:,} B")


if __name__ == "__main__":
    main()
