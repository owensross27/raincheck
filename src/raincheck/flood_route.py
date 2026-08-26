"""`make flood-route` (flood-build 21a): `gold/route_flood` — one row per bus route and
direction, saying how much flood-prone ground that route covers.

THE CLAIM IS DESCRIPTIVE AND THAT IS A DECISION, NOT A SHORTFALL (DESTINATION-PLAN §1 D6).
Ross's sentence — "this bus route is super slowed down because it typically gets flooded" —
reads like a statistical claim, and the statistical claim is not available: its universe is
the flood events that fall inside the hours `gold/cell_hour_route` actually holds, and today
that is TWO. An interval over two events would be a number about the sample. So v1 ships a
lookup — Cells crossed, Cells flood-prone, share of route length inside DEP's
current-sea-level extent, flood events recorded on the route's Cells, last event day — plus
ONE measured exhibit, which lives in `research/flood-21-route-exhibit.{md,json}` and NOT in
this table. The statistical table is the NAMED UPGRADE, gated on the full backfill
(pipeline-build 17) landing `cell_hour_route` for the event months; when it lands it must
inherit `headline.json`'s interval gate and flood 18's own-base-rate rule.

IMPACT, NEVER A DETECTOR INPUT. This table is DOWNSTREAM of `gold/flood_labels` and
`silver/flood_events`. Nothing here writes anything `features.features_version()`,
`flood_matrix.matrix_version()`, `flood_exposure.score_version()` or
`flood_detect.detector_version()` reads, and `main()` brackets the build with all four
stamps and raises on a move rather than trusting that (flood-build 19's rule, reused).

WHAT "INSIDE THE EXTENT" MEANS, and the two columns that cannot be filled today.
`silver/stormwater_extent` (flood-build 19) carries DEP's design-storm polygons per
scenario x horizon x category. Only `horizon = current` describes today's sea level, and at
that horizon DEP gives exactly ONE readable scenario:

  scenario   rain        current sea level      share_len_<scenario>
  limited    1.77 in/hr  declared, UNREADABLE   NULL - compressed FGDB, no open driver
  moderate   2.13 in/hr  readable               measured
  extreme    3.66 in/hr  NOT PUBLISHED at all   NULL - DEP publishes 3.66 at 2080 SLR only

A NULL there is "no source", never 0.0: a zero share is a claim that the route is dry, and
that is the same class of lie as imputing DEP's exclusion mask to "no flooding". The columns
are always present and always in this order, so a consumer's schema does not move; the day a
readable Limited source is pinned into `stormwater_extent.SCENARIOS`, the column fills
itself with no code change here. Both reasons are DERIVED from flood-build 19's own
`SCENARIOS` / `UNREADABLE`, never retyped, and both ride in the check batch as INCONCLUSIVE
rows — a scenario that cannot be read is a could-not-check, not a gap.

`not_analyzed` IS A CATEGORY, NOT AN ABSENCE, so it gets its own column.
`features.sample()` refuses to impute DEP's exclusion mask to "no flooding" and this table
must not undo that from the other side: a route whose footprint is largely inside the mask
has an UNKNOWABLE share, not a low one. Measured on the real root, one route runs 80.5% of
its length through excluded ground. `share_len_not_analyzed` is published beside
`share_len_moderate` for exactly that reason and is never summed into a flooded share.

GEODESIC METRES, AND THE DENOMINATOR IS THE SAME MEASURE AS THE NUMERATOR. Both come from
`schedule.GEOD` — the same `Geod(ellps="WGS84")` object that computed
`silver/shapes.length_m` — so a share is a ratio of like for like rather than a UTM numerator
over a geodesic denominator. Measured against that stored column as an independent oracle:
max relative difference 5.8e-08 over all 1,189 shapes, which is float32 rounding in the
column and not a method difference. DuckDB does the topology (which parts of the line are
inside the polygon) and pyproj does the metric.

Run: make flood-route            (python -m raincheck.flood_route)
     make flood-route-exhibit    (python -m raincheck.flood_route --exhibit)
     rc 1 the table is broken / 2 a declared scenario could not be measured / 0
"""
import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import shapely

from raincheck import checks, duck, features
from raincheck import stormwater_extent as se
from raincheck.paths import REPO, as_root, data_root
from raincheck.ref import WINDOWS          # the baseline windows; ref opens no JVM
from raincheck.schedule import GEOD        # the Geod that measured silver/shapes.length_m

CHECK = "route_flood"
TABLE = "route_flood"
BATCH = "table"                            # the subject of the batch-level check row

# The scenarios this table reserves a column for, read out of flood-build 19's declaration
# rather than retyped (its box's MUST: never retype 1.77 / 2.13 / 3.66). `moderate` is
# declared twice there (current + 2050); the NAME appears once, and the rain rate is one
# number per name.
SCENARIOS = tuple(dict.fromkeys(s.scenario for s in se.SCENARIOS))
RAIN_IN_HR = {s.scenario: s.rain_in_hr for s in se.SCENARIOS}
HORIZON = se.CURRENT

# What "inside the extent" means. `se.MASK` is DEP's exclusion mask and is NEVER summed into
# a flooded share — it is published on its own column so nobody can read excluded ground as
# dry ground.
FLOODED = ("deep", "nuisance")
MASK_COLUMN = f"share_len_{se.MASK}"
PRONE = "share_deep + share_nuisance > 0"   # this ticket's own flood-prone rule, one home

SHARE_COLUMNS = tuple(f"share_len_{s}" for s in SCENARIOS)
SCHEMA = pa.schema(
    [("route_id", pa.string()), ("direction_id", pa.string()),
     ("n_shapes", pa.int32()), ("length_m", pa.float64()),
     ("n_cells", pa.int32()), ("n_cells_flood_prone", pa.int32())]
    + [(c, pa.float64()) for c in SHARE_COLUMNS]
    + [(MASK_COLUMN, pa.float64()),
       ("n_flood_events", pa.int32()), ("last_event_day", pa.date32()),
       ("label_version", pa.string()), ("features_version", pa.string()),
       ("zip_sha256", pa.string()), ("route_flood_version", pa.string())])

CHECK_COLUMNS = checks.CORE + (
    "scenario", "horizon", "rain_in_hr", "share_len_min", "share_len_median",
    "share_len_max", "routes", "routes_zero_geometry", "routes_no_cells",
    "cells_crossed", "cells_flood_prone", "flood_events",
    "label_version", "features_version", "zip_sha256", "route_flood_version")

# hour_of_week, DuckDB side. `gold.baseline()` builds it in Spark as
# `((dayofweek(local) + 5) % 7) * 24 + hour(local)` — Monday 00 local = 0 — and Spark's
# dayofweek is 1=Sunday while DuckDB's is 0=Sunday, so COPYING that expression here shifts
# every hour by a day (measured: Monday 00:00 local reads 144). `isodow` is 1=Monday, which
# makes the Monday-first convention structural rather than an offset to get right. Pinned by
# a literal test in both directions, and confirmed against real data: Ida is a Thursday and
# its 24 hours land on 72..95, exactly Thursday's block.
NY = "America/New_York"
HOUR_OF_WEEK = (f"(isodow({{t}} AT TIME ZONE '{NY}') - 1) * 24 + hour({{t}} AT TIME ZONE '{NY}')")
NY_DATE = f"({{t}} AT TIME ZONE '{NY}')::DATE"

EXHIBIT = REPO / "research" / "flood-21-route-exhibit"


def unsourced(scenario: str) -> str | None:
    """Why `scenario` has no current-sea-level extent, or None if it has one.

    Both reasons are DERIVED from flood-build 19's declaration: a scenario it never declares
    at `current` is one DEP does not publish at today's sea level, and one it declares but
    names in `UNREADABLE` is a container no driver here can open. Neither sentence is a
    literal anybody has to keep in step with that module.
    """
    at_current = [s for s in se.SCENARIOS if s.scenario == scenario and s.horizon == HORIZON]
    if not at_current:
        horizons = "/".join(sorted({s.horizon for s in se.SCENARIOS if s.scenario == scenario}))
        return (f"DEP publishes {scenario} at horizon {horizons} only — there is no "
                f"{HORIZON}-sea-level extent for a route to be measured against")
    return se.UNREADABLE.get(at_current[0].key)


def sourced() -> tuple[str, ...]:
    """The scenarios that have a current-sea-level extent to measure against — today one."""
    return tuple(s for s in SCENARIOS if not unsourced(s))


def baseline_windows() -> dict[str, tuple[date, date]]:
    """`gold.py`'s own `WINDOW` mapping, without importing `gold` (which would pull pyspark
    into a read). The SPANS come from `ref.WINDOWS`, a real import — that module opens no
    JVM — and the NAMES are regexed out of gold.py's own line, the independent-side trick
    flood 17 used on the same table. Neither half is retyped here, and a gold.py that stops
    declaring it this way raises rather than silently answering with a stale map.
    """
    src = (Path(__file__).with_name("gold.py")).read_text()
    m = re.search(r"^WINDOW = dict\(zip\((\([^)]*\)), WINDOWS\)\)\s*$", src, re.M)
    if not m:
        raise RuntimeError("gold.py no longer declares WINDOW = dict(zip((...), WINDOWS)) — "
                           "the baseline window names have moved")
    return dict(zip(eval(m.group(1)), WINDOWS))     # noqa: S307 — a literal tuple of names


# --- the build ----------------------------------------------------------------------------


def _digest(con, sql: str) -> str:
    """md5 over the rows a scan ACTUALLY RETURNS. `sql` selects one VARCHAR column; the rows
    are sorted by their own text before hashing, so the digest is independent of the physical
    order two runs happen to pick (`test_export`'s standing warning, which flood-build 19
    measured again on a new writer).

    chr(31) because DuckDB SQL cannot carry a control character in a quoted literal.
    """
    return con.execute(
        f"SELECT md5(string_agg(k, chr(31) ORDER BY k)) FROM ({sql}) s(k)").fetchone()[0]


def _one(con, table_root, column: str) -> str:
    """The one distinct value of `column`, with the projection INSIDE the read's own
    statement. `query.one_value` asks the same question through `duck.table()`, which binds
    the path as a parameter so nothing can be pushed into the scan — measured by flood 15 at
    437 MiB against 175 MiB for the identical SQL on `gold/flood_matrix`."""
    got = con.execute(f"SELECT DISTINCT {column} FROM read_parquet(?)",
                      [f"{table_root}/**/*.parquet"]).fetchall()
    if len(got) != 1:
        raise RuntimeError(f"{table_root}: {column} has {len(got)} distinct values, expected 1")
    return got[0][0]


def read(root: Path, con) -> dict:
    """Every input this table is a function of, into temp tables, plus a digest of each.

    The digests hash what the build READ, not what it declared. flood 18 measured the other
    way round: a staging that ENUMERATED its inputs missed one, and `spine_version`,
    `label_version` AND `matrix_version` were all identical to the corrected run's, because
    nothing in that chain looks at whether an input was there. A digest over the scan moves
    when a tree goes missing, which is the property that makes it worth stamping.
    """
    r = as_root(root)
    p = lambda *parts: f"{r.joinpath(*parts)}/**/*.parquet"     # noqa: E731
    con.execute("INSTALL spatial; LOAD spatial;")

    con.execute(f"""CREATE TABLE route_shape AS
        SELECT DISTINCT route_id, CAST(direction_id AS VARCHAR) AS direction_id,
                        shape_id, pick_id
        FROM read_parquet('{p("silver", "trips")}')
        WHERE route_id IS NOT NULL AND direction_id IS NOT NULL AND shape_id IS NOT NULL""")
    con.execute(f"""CREATE TABLE shape AS
        SELECT shape_id, pick_id, geometry FROM read_parquet('{p("silver", "shapes")}')""")
    con.execute(f"""CREATE TABLE cells AS
        SELECT cell, geometry FROM read_parquet('{p("ref", "cells")}')""")
    con.execute(f"""CREATE TABLE extent AS
        SELECT scenario, category, poly, geometry
        FROM read_parquet('{p("silver", "stormwater_extent")}') WHERE horizon = '{HORIZON}'""")
    con.execute(f"""CREATE TABLE prone AS
        SELECT cell FROM read_parquet('{p("silver", "cell_stormwater")}') WHERE {PRONE}""")
    con.execute(f"""CREATE TABLE cell_event AS
        SELECT DISTINCT cell, event_id FROM read_parquet('{p("gold", "flood_labels")}')
        WHERE kind = 'cell'""")
    con.execute(f"""CREATE TABLE event_day AS
        SELECT event_id, day_end FROM read_parquet('{p("silver", "flood_events")}')""")

    return {
        "trips": _digest(con, "SELECT route_id || ':' || direction_id || ':' || shape_id "
                              "|| ':' || pick_id FROM route_shape"),
        "shapes": _digest(con, "SELECT shape_id || ':' || pick_id || ':' "
                               "|| md5(ST_AsWKB(geometry)) FROM shape"),
        "cells": _digest(con, "SELECT cell || ':' || md5(ST_AsWKB(geometry)) FROM cells"),
        "extent": _digest(con, "SELECT scenario || ':' || category || ':' || poly || ':' "
                               "|| md5(ST_AsWKB(geometry)) FROM extent"),
        "cell_stormwater": _digest(
            con, "SELECT cell || ':' || share_deep || ':' || share_nuisance FROM "
                 f"read_parquet('{p('silver', 'cell_stormwater')}')"),
        "cell_event": _digest(con, "SELECT cell || ':' || event_id FROM cell_event"),
        "event_day": _digest(con, "SELECT event_id || ':' || day_end FROM event_day"),
        "label_version": _one(con, r / "gold" / "flood_labels", "label_version"),
        "spine_version": _one(con, r / "silver" / "flood_events", "spine_version"),
        "zip_sha256": _one(con, r / "silver" / "stormwater_extent", "zip_sha256"),
        "features_version": features.features_version(root),
    }


def geodesic_m(wkb) -> float:
    """Geodesic metres of the LINEAR parts of a geometry.

    `ST_Intersection` of a line and a polygon hands back a POINT where the line only grazes a
    corner, and a union over a mixed list then carries it — a point has no length but a
    collection would still be asked for one, so the linear parts are taken explicitly rather
    than hoped for. Sibling of flood-build 19's GEOMETRYCOLLECTION finding, one operation on.
    """
    g = shapely.from_wkb(bytes(wkb))
    linear = ("LineString", "MultiLineString", "LinearRing")
    if g.geom_type in linear:
        return GEOD.geometry_length(g)
    return sum(GEOD.geometry_length(part) for part in shapely.get_parts(g)
               if part.geom_type in linear)


def footprint(con) -> None:
    """The route's ground: the union of every shape any of its trips uses, across all six
    schedule Picks on disk.

    A union rather than a sum, because six Picks of one route trace nearly the same street
    and summing them would count that street six times. `n_shapes` rides on the row so a
    reader can see how many went in. Every `shape_id` in `silver/shapes` is globally unique
    (1,189 of 1,189, measured), so a shape belongs to exactly one (route, direction).

    BOTH AGGREGATES ARE ORDERED, AND THAT IS WHAT MAKES THIS TABLE REPRODUCIBLE. GEOS's
    cascaded union is order-dependent in the last bit, and an aggregate's group is unordered,
    so the first version of this module built a table that DIFFERED between two runs of the
    same code on the same inputs: 74 of 683 `length_m`, 70 `share_len_moderate` and 64
    `share_len_not_analyzed`, every one at ~1.4e-15 relative — one ULP, the same arithmetic
    orch 11 measured on `leg_hours.dist_m_sum`. There the answer was a stated tolerance
    because the two sides were two RUNTIMES; here both sides are this module, so the fix is a
    total order and the digest stays exact. `ORDER BY` inside the aggregate is the whole fix.
    """
    con.execute("""CREATE TABLE route_geom AS
        SELECT r.route_id, r.direction_id, count(DISTINCT r.shape_id)::INT AS n_shapes,
               ST_Union_Agg(s.geometry ORDER BY s.pick_id, s.shape_id) AS g
        FROM route_shape r JOIN shape s USING (shape_id, pick_id)
        GROUP BY 1, 2""")
    # (A u B) n C = (A n C) u (B n C): intersect per shape, where the geometries are small,
    # then union at the route grain. The union is what stops a street two Picks share being
    # counted twice inside the extent while being counted once in the denominator.
    con.execute("""CREATE TABLE route_in AS
        SELECT r.route_id, r.direction_id, e.scenario, e.category,
               ST_Union_Agg(ST_Intersection(s.geometry, e.geometry)
                            ORDER BY s.pick_id, s.shape_id, e.poly) AS g
        FROM route_shape r JOIN shape s USING (shape_id, pick_id)
        JOIN extent e ON s.geometry && e.geometry AND ST_Intersects(s.geometry, e.geometry)
        GROUP BY 1, 2, 3, 4""")
    # CROSSING IS A POSITIVE LENGTH, NOT A TOUCH. `ST_Intersects` is true where a route ends
    # exactly on a Cell boundary or clips a vertex, and that zero-length graze would pull the
    # whole Cell's flood events onto the route — `n_flood_events` is a JOIN on this table, so
    # an over-counted Cell is an over-counted event history and not just a bigger `n_cells`.
    # The comparison to 0 is scale-free, so `ST_Length` in degrees answers it as well as
    # metres would and no projection is owed here.
    con.execute("""CREATE TABLE route_cell AS
        SELECT g.route_id, g.direction_id, c.cell
        FROM route_geom g JOIN cells c
          ON g.g && c.geometry AND ST_Length(ST_Intersection(g.g, c.geometry)) > 0""")


def route_flood_version(inputs: Mapping) -> str:
    """sha1 over exactly the inputs that can move a number in this table.

    WHAT IS IN: the seven input digests (the route->shape mapping, the shape geometry, the
    Cell grid, the current-horizon extent geometry, the per-Cell stormwater shares, the
    Cell x event labels, the events' end days), the four upstream identities that already
    chain their own inputs, and the two rules that decide what a number MEANS — which
    categories count as water, and what makes a Cell flood-prone.

    WHAT IS DELIBERATELY OUT: this module's prose, the check-row detail sentences, the column
    names and the exhibit. flood 10's rule — rewording a sentence must not move a digest, or
    a consumer refuses itself over a cosmetic edit.

    WHAT IS NOT COVERED, and is a real limit rather than a choice: this hashes VALUES, so the
    module's own SQL rides only as the labels below. Editing `footprint()` moves a share
    without moving the digest; the tests hold that, not this stamp.
    """
    return hashlib.sha1(json.dumps({
        "inputs": dict(inputs),
        "horizon": HORIZON,
        "flooded_categories": list(FLOODED),
        "mask_category": se.MASK,
        "prone_rule": PRONE,
        "length": "geodesic metres, pyproj Geod(ellps='WGS84')",
    }, sort_keys=True).encode()).hexdigest()


def rows(root: Path, con) -> tuple[list[dict], dict]:
    """(one dict per (route_id, direction_id), the counts the check batch reports)."""
    inputs = read(root, con)
    footprint(con)
    stamp = route_flood_version(inputs)

    length = {(rid, did): (n, geodesic_m(wkb)) for rid, did, n, wkb in con.execute(
        "SELECT route_id, direction_id, n_shapes, ST_AsWKB(g) FROM route_geom").fetchall()}
    inside = {(rid, did, sc, cat): geodesic_m(wkb) for rid, did, sc, cat, wkb in con.execute(
        "SELECT route_id, direction_id, scenario, category, ST_AsWKB(g) "
        "FROM route_in").fetchall()}
    cells = {(rid, did): (n, prone) for rid, did, n, prone in con.execute(
        "SELECT route_id, direction_id, count(*)::INT, "
        "       count(*) FILTER (WHERE cell IN (SELECT cell FROM prone))::INT "
        "FROM route_cell GROUP BY 1, 2").fetchall()}
    events = {(rid, did): (n, day) for rid, did, n, day in con.execute(
        "SELECT rc.route_id, rc.direction_id, count(DISTINCT ce.event_id)::INT, "
        "       max(ed.day_end) "
        "FROM route_cell rc JOIN cell_event ce USING (cell) "
        "JOIN event_day ed ON ed.event_id = ce.event_id GROUP BY 1, 2").fetchall()}

    out, no_geometry = [], 0
    for rid, did in con.execute("SELECT DISTINCT route_id, direction_id FROM route_shape "
                                "ORDER BY 1, 2").fetchall():
        n_shapes, total = length.get((rid, did), (0, 0.0))
        if total <= 0.0:            # trips name a shape that carries no usable geometry
            no_geometry += 1
        n_cells, n_prone = cells.get((rid, did), (0, 0))
        n_events, last_day = events.get((rid, did), (0, None))
        share: dict = {}
        for scenario in SCENARIOS:
            share[f"share_len_{scenario}"] = None if (unsourced(scenario) or total <= 0.0) else (
                sum(inside.get((rid, did, scenario, c), 0.0) for c in FLOODED) / total)
        # The largest share any SOURCED current-sea-level scenario excludes from its model.
        # Today exactly one scenario is sourced, so this is that one; a max rather than a sum
        # so a second pinned source can never double-count the same excluded ground.
        mask = None if total <= 0.0 else max(
            (inside.get((rid, did, s, se.MASK), 0.0) / total for s in sourced()), default=0.0)
        out.append({"route_id": rid, "direction_id": did, "n_shapes": n_shapes,
                    "length_m": total, "n_cells": n_cells, "n_cells_flood_prone": n_prone,
                    **share, MASK_COLUMN: mask, "n_flood_events": n_events,
                    "last_event_day": last_day,
                    "label_version": inputs["label_version"],
                    "features_version": inputs["features_version"],
                    "zip_sha256": inputs["zip_sha256"], "route_flood_version": stamp})

    counts = {
        "routes_zero_geometry": no_geometry,
        "routes_no_cells": sum(1 for r in out if r["n_cells"] == 0),
        "cells_crossed": con.execute(
            "SELECT count(DISTINCT cell) FROM route_cell").fetchone()[0],
        "cells_flood_prone": con.execute("SELECT count(*) FROM prone").fetchone()[0],
        "flood_events": con.execute("SELECT count(DISTINCT ce.event_id) FROM route_cell rc "
                                    "JOIN cell_event ce USING (cell)").fetchone()[0]}
    return out, counts


def write(root: Path, table: list[dict]) -> Path:
    """One part file, staged then moved (flood-build 19's idiom, and notify 03's rule read
    from the other side: a table is a PART FILE, so a torn write must never be reachable)."""
    out = as_root(root) / "gold" / TABLE / "part-00000.parquet"
    tmp = out.with_suffix(".parquet.tmp")
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(table, schema=SCHEMA), tmp, compression="zstd")
    tmp.replace(out)     # POSIX-only, like every other pq.write_table stage here (cloud 13)
    print(f"gold/{TABLE}: {len(table)} rows -> {out}", flush=True)
    return out


# --- the check batch ----------------------------------------------------------------------


def census(table: list[dict], counts: Mapping) -> list[checks.Row]:
    """One batch-level row plus one row per scenario this table reserves a column for.

    The batch row carries the whole-batch claims (row count, routes with no geometry, routes
    that cross no Cell); the scenario rows carry the per-scenario ones. That is orch 08's
    rule, and this batch has to respect it for the same reason its own suite did: a scenario
    held out as INCONCLUSIVE shortens the judged frame, so an aggregate asserted over that
    frame would render "could not read" as a failure.

    A scenario with no current-sea-level source is INCONCLUSIVE with the reason — never a
    FAIL, and never an `ok` row of zeros. NULL is the could-not-check convention here, so a
    suite writing a between-expectation over `share_len_min|median|max` must pair it with a
    not-null: a between counts nulls as MISSING and succeeds without them.
    """
    stamps_ = {k: (table[0][k] if table else None)
               for k in ("label_version", "features_version", "zip_sha256",
                         "route_flood_version")}
    blank: dict = dict.fromkeys(
        ("scenario", "horizon", "rain_in_hr", "share_len_min", "share_len_median",
         "share_len_max", "routes", "routes_zero_geometry", "routes_no_cells",
         "cells_crossed", "cells_flood_prone", "flood_events"))

    broken = bool(counts["routes_zero_geometry"]) or not table
    out = [checks.Row(
        CHECK, BATCH, checks.FAIL if broken else checks.OK,
        "  the table is empty" if not table
        else f"  {counts['routes_zero_geometry']} route(s) have no geometry" if broken else "",
        blank | {"routes": len(table),
                 "routes_zero_geometry": counts["routes_zero_geometry"],
                 "routes_no_cells": counts["routes_no_cells"],
                 "cells_crossed": counts["cells_crossed"],
                 "cells_flood_prone": counts["cells_flood_prone"],
                 "flood_events": counts["flood_events"]} | stamps_)]

    for scenario in SCENARIOS:
        why = unsourced(scenario)
        got = sorted(r[f"share_len_{scenario}"] for r in table
                     if r[f"share_len_{scenario}"] is not None)
        m = blank | {"scenario": scenario, "horizon": HORIZON,
                     "rain_in_hr": RAIN_IN_HR[scenario]} | stamps_
        if why or not got:
            out.append(checks.Row(CHECK, f"{scenario} {HORIZON}", checks.INCONCLUSIVE,
                                  f"  {why or 'no route length was measured against it'}", m))
            continue
        mid = len(got) // 2
        out.append(checks.Row(
            CHECK, f"{scenario} {HORIZON}", checks.OK, "",
            m | {"share_len_min": got[0], "share_len_max": got[-1],
                 "share_len_median": got[mid] if len(got) % 2 else (got[mid - 1] + got[mid]) / 2}))
    return out


def line(r: checks.Row) -> str:
    m = r.measures
    mark = {checks.OK: "OK ", checks.FAIL: "BAD", checks.INCONCLUSIVE: "???"}[r.outcome]
    if m["scenario"] is None:
        return (f"{mark} {r.subject:20s} {m['routes'] or 0:5d} routes  "
                f"{m['cells_crossed'] or 0:5d} Cells crossed  "
                f"{m['cells_flood_prone'] or 0:5d} flood-prone citywide  "
                f"{m['flood_events'] or 0:4d} events{r.detail}")
    share = "     -   " if m["share_len_median"] is None else f"{m['share_len_median']:9.4f}"
    return (f"{mark} {r.subject:20s} {m['rain_in_hr']:.2f} in/hr  "
            f"median share {share}{r.detail}")


# --- the exhibit ---------------------------------------------------------------------------


def held(con, root: Path) -> dict:
    """{month: [the NY-local days gold/cell_hour_route holds]}. RE-MEASURED at every run
    rather than inherited: it is exactly the number the ticket says to re-measure, and it
    moves the day pipeline-build 17's backfill lands."""
    got = con.execute(
        f"SELECT \"month\" AS mo, {NY_DATE.format(t='hour_end_utc')} AS d "
        f"FROM read_parquet(?) GROUP BY 1, 2 ORDER BY 1, 2",
        [f"{as_root(root) / 'gold' / 'cell_hour_route'}/**/*.parquet"]).fetchall()
    out: dict[str, list] = {}
    for month, day in got:
        out.setdefault(month, []).append(day)
    return out


def universe(con, root: Path) -> list[dict]:
    """The flood events whose days intersect the HOURS `gold/cell_hour_route` actually holds.

    This is N, and the asset says so. It is not "the events inside those months": the 2021-09
    partition holds 29 hours across two days, not a month, so an event inside 2021-09 whose
    days fall outside those hours contributes nothing and is not counted as if it did.
    """
    p = as_root(root)
    keys = ("event_id", "day_start", "day_end", "month", "days", "n_hours")
    return [dict(zip(keys, r)) for r in con.execute(f"""
        WITH hrs AS (SELECT DISTINCT "month" AS mo, hour_end_utc,
                            {NY_DATE.format(t="hour_end_utc")} AS d
                     FROM read_parquet('{p / "gold" / "cell_hour_route"}/**/*.parquet'))
        SELECT e.event_id, e.day_start, e.day_end, any_value(hrs.mo),
               array_sort(list(DISTINCT hrs.d)), count(DISTINCT hrs.hour_end_utc)
        FROM read_parquet('{p / "silver" / "flood_events"}/**/*.parquet') e
        JOIN hrs ON hrs.d BETWEEN e.day_start AND e.day_end
        GROUP BY 1, 2, 3 ORDER BY 2""").fetchall()]


def all_event_days(con, root: Path) -> set:
    """Every day of every flood event in the spine. The dry side of any comparison here is
    cut against this, never against the one event being looked at."""
    return {r[0] for r in con.execute(
        "SELECT unnest(generate_series(day_start, day_end, INTERVAL 1 DAY))::DATE "
        "FROM read_parquet(?)",
        [f"{as_root(root) / 'silver' / 'flood_events'}/**/*.parquet"]).fetchall()}


def baseline_window(con, root: Path, day: date) -> str | None:
    """The `cell_hourofweek_baseline` window covering `day`, or None if none is on disk.

    Both halves matter: `w1` is 2021 and `w2` is 2023, and `gold.baseline()` masks dry hours
    with `silver/precip_cell_hourly WHERE src = 'aorc'` — AORC ends 2025-12-31, so no
    capture-era window can be built at all however many capture days accumulate (flood 17
    measured the same wall from the other side). ABSENT, never zero.
    """
    try:
        on_disk = {r[0] for r in con.execute(
            "SELECT DISTINCT \"window\" FROM read_parquet(?)",
            [f"{as_root(root) / 'gold' / 'cell_hourofweek_baseline'}/**/*.parquet"]).fetchall()}
    except Exception:
        return None
    for name, (lo, hi) in baseline_windows().items():
        if name in on_disk and lo <= day <= hi:
            return name
    return None


def event_rows(con, root: Path, ev: Mapping) -> list[dict]:
    """Per route, for one event: the event-day `late_share` / `ewt_s` and the route's own
    dry-side counterpart, with the n behind each.

    THE COUNTERPART IS NOT THE NAMED TABLE'S NAMED COLUMNS, and the asset says so rather than
    papering over it: `gold/cell_hourofweek_baseline` carries `speed_dry`, `n_dry`,
    `n_legs_dry`, `dist_m_sum_dry` and `dt_s_sum_dry` — it holds NO `late_share` and NO
    `ewt_s` at all. So the route's own baseline for the same hours is a SPEED, and the
    comparable event-side number is the route's own speed out of `gold/cell_hour_speed` at
    the same (cell, hour). Where the window does not exist the baseline side is ABSENT.

    Weighted, never averaged from per-row means: `late_share` is a share OF `n_events`, and
    its denominator counts only the rows that HAVE one (2026-08 has 3,161 NULL `late_share`
    rows of 1.36 M — summing over the whole n_events would silently under-weight). A speed is
    `sum(dist_m_sum) / sum(dt_s_sum)` computed AFTER the sum, and both sums need a `::DOUBLE`
    cast: DuckDB's `sum()` of a BIGINT returns DECIMAL and divides badly against a float
    (it cost flood 17 a round).
    """
    p, lo, hi = as_root(root), ev["days"][0], ev["days"][-1]
    window = baseline_window(con, root, lo)
    day, hw = NY_DATE.format(t="hour_end_utc"), HOUR_OF_WEEK.format(t="hour_end_utc")
    got = con.execute(f"""
        WITH r AS (SELECT route_id, sum(n_events)::BIGINT AS n_events,
                          count(DISTINCT hour_end_utc)::INT AS n_hours,
                          sum(late_share * n_events)
                            / nullif(sum(n_events) FILTER (WHERE late_share IS NOT NULL), 0)
                            AS late_share,
                          sum(ewt_s * n_events)
                            / nullif(sum(n_events) FILTER (WHERE ewt_s IS NOT NULL), 0)
                            AS ewt_s
                   FROM read_parquet('{p / "gold" / "cell_hour_route"}/**/*.parquet')
                   WHERE "month" = ? AND {day} BETWEEN ? AND ? GROUP BY 1),
             ev AS (SELECT route_id, cell, hour_end_utc, dist_m_sum, dt_s_sum
                    FROM read_parquet('{p / "gold" / "cell_hour_speed"}/**/*.parquet')
                    WHERE "month" = ? AND {day} BETWEEN ? AND ?),
             sp AS (SELECT route_id,
                           sum(dist_m_sum)::DOUBLE / nullif(sum(dt_s_sum), 0)::DOUBLE AS speed_mps
                    FROM ev GROUP BY 1),
             ch AS (SELECT DISTINCT route_id, cell, {hw} AS hour_of_week FROM ev),
             b AS (SELECT ch.route_id,
                          sum(bl.dist_m_sum_dry)::DOUBLE
                            / nullif(sum(bl.dt_s_sum_dry), 0)::DOUBLE AS speed_dry,
                          count(*)::INT AS n_baseline_rows
                   FROM ch JOIN read_parquet(
                            '{p / "gold" / "cell_hourofweek_baseline"}/**/*.parquet') bl
                     ON bl.cell = ch.cell AND bl.hour_of_week = ch.hour_of_week
                        AND bl."window" = ? GROUP BY 1)
        SELECT r.route_id, r.n_hours, r.n_events, r.late_share, r.ewt_s,
               sp.speed_mps, b.speed_dry, b.n_baseline_rows
        FROM r LEFT JOIN sp USING (route_id) LEFT JOIN b USING (route_id) ORDER BY 1""",
        [ev["month"], lo, hi, ev["month"], lo, hi, window or ""]).fetchall()
    keys = ("route_id", "n_hours", "n_events", "late_share", "ewt_s", "speed_mps",
            "speed_dry", "n_baseline_rows")
    out = []
    for row in got:
        d: dict = dict(zip(keys, row))
        d["n_events"] = int(d["n_events"] or 0)
        d["baseline_window"] = window
        d["speed_ratio"] = (d["speed_mps"] / d["speed_dry"]
                            if d["speed_mps"] and d["speed_dry"] else None)
        out.append(d)
    return out


def other_days(con, root: Path, ev: Mapping, event_days: set) -> dict:
    """The same route's `late_share` / `ewt_s` on the OTHER WEEKDAYS of the same month
    partition, matched by nothing finer than the month.

    This is a SUBSTITUTE and it is labelled as one everywhere it appears. It is NOT
    `gold/cell_hourofweek_baseline` and it is NOT hour-of-week matched: measured on the real
    root, `month=2026-08` spans 2026-08-15..25 and the event day 2026-08-20 is the ONLY
    Thursday in it, so an hour-of-week-matched comparison has n = 0 other days. Weekend days
    are excluded because a Saturday is a different service pattern, not a dry Thursday. What
    is left is a level beside a level on the same metric, the same route and the same month.
    It carries no interval and it is not a control.

    `event_days` is EVERY day of EVERY event in the universe, not just this event's: the dry
    side of a comparison must not contain somebody else's flood. It costs one predicate and
    it is the difference between "the other weekdays" and "the other weekdays that happen not
    to be the one I am looking at".
    """
    p, lo, hi = as_root(root), ev["days"][0], ev["days"][-1]
    day = NY_DATE.format(t="hour_end_utc")
    got = con.execute(f"""
        SELECT route_id, count(DISTINCT {day})::INT AS n_days,
               count(DISTINCT hour_end_utc)::INT AS n_hours,
               sum(late_share * n_events)
                 / nullif(sum(n_events) FILTER (WHERE late_share IS NOT NULL), 0) AS late_share,
               sum(ewt_s * n_events)
                 / nullif(sum(n_events) FILTER (WHERE ewt_s IS NOT NULL), 0) AS ewt_s
        FROM read_parquet('{p / "gold" / "cell_hour_route"}/**/*.parquet')
        WHERE "month" = ? AND {day} NOT BETWEEN ? AND ?
          AND {day} NOT IN (SELECT unnest(?::DATE[]))
          AND isodow(hour_end_utc AT TIME ZONE '{NY}') <= 5
        GROUP BY 1 ORDER BY 1""",
        [ev["month"], lo, hi, sorted(event_days)]).fetchall()
    return {r[0]: dict(zip(("n_days", "n_hours", "late_share", "ewt_s"), r[1:])) for r in got}


def baseline_overlap(window: str | None, days: list) -> dict | None:
    """How independent the baseline window is of the event it is being compared against.

    STRUCTURAL, so it re-implements nothing: `gold.baseline()`'s dry rule has one home and a
    second copy here would rot (orch 13's rendered-declaration trap). What this reports is
    the calendar — how many days in the window share the event's weekday, and whether the
    event's own days are among them — because `gold.baseline()` masks by WETNESS and not by
    date, so an event day's post-storm hours are dry hours and DO enter their own baseline.

    MEASURED once, 2026-08-26, on the real root for the Ida case: of the 668,847 Thursday
    dry Cell-hours in `w1`, **64,160 (9.59%) fall on 2021-09-02 itself** — the event day is
    one of the window's nine Thursdays and about a ninth of the baseline is its own recovered
    hours. That dilutes the baseline toward the event day, i.e. toward NO difference, so a
    ratio below 1 here is if anything understated. Stated, not corrected: correcting it is a
    different table.
    """
    if window is None or not days:
        return None
    lo, hi = baseline_windows()[window]
    weekdays = {d.isoweekday() for d in days}
    span = (hi - lo).days + 1
    same = [lo + timedelta(n) for n in range(span)
            if (lo + timedelta(n)).isoweekday() in weekdays]
    return {"window": window, "span": [str(lo), str(hi)],
            "days_sharing_the_event_weekday": len(same),
            "event_days_inside_the_window": [str(d) for d in days if lo <= d <= hi],
            "note": ("gold.baseline() masks by wetness, not by date, so an event day's own "
                     "post-storm dry hours enter its baseline. Measured for Ida: 9.59% of "
                     "w1's Thursday dry Cell-hours are 2021-09-02 itself. It dilutes toward "
                     "no difference.")}


def exhibit(root: Path) -> dict:
    """The one measured exhibit: what the event days Gold covers can and cannot say.

    Honestly bounded and NOT a skill claim. Every number is a level beside a level with its
    own n; no interval is offered anywhere, because none of these n carry one; there is no
    CSI, and no comparison across two universes (flood 18's rule — a lift without its own
    base rate is a statement about the base rate).
    """
    con = duck.connect()
    try:
        events = universe(con, root)
        every_event_day = all_event_days(con, root)
        per_event = []
        for ev in events:
            rows_ = event_rows(con, root, ev)
            other = other_days(con, root, ev, every_event_day)
            for r in rows_:
                r["other_weekdays"] = other.get(r["route_id"])
            window = rows_[0]["baseline_window"] if rows_ else None
            per_event.append({
                "event_id": ev["event_id"], "day_start": str(ev["day_start"]),
                "day_end": str(ev["day_end"]), "month": ev["month"],
                "days_covered": [str(d) for d in ev["days"]], "n_hours": ev["n_hours"],
                "n_routes": len(rows_),
                "late_share_available": sum(1 for r in rows_ if r["late_share"] is not None),
                "ewt_s_available": sum(1 for r in rows_ if r["ewt_s"] is not None),
                "baseline_window": window,
                "baseline_overlap": baseline_overlap(window, ev["days"]),
                "speed_ratio_available": sum(1 for r in rows_ if r["speed_ratio"] is not None),
                "routes": rows_})
        months = {m: [str(d) for d in days] for m, days in held(con, root).items()}
    finally:
        con.close()
    return {"universe": {
                "n_events": len(events),
                "months_held": months,
                "note": ("N is the flood events whose days intersect the HOURS "
                         "gold/cell_hour_route holds, not the events inside those months: "
                         "the 2021-09 partition holds 29 hours across two days."),
                "gated_on": (
                    "the statistical table is gated on the full backfill (pipeline-build 17) "
                    "landing gold/cell_hour_route for the event months — and, measured here, "
                    "on two things beyond row count: the backfilled months must carry "
                    "SCHEDULE-MATCHED delay columns (2021-09's late_share and ewt_s are NULL "
                    "on every one of its 86,914 rows) and an AORC-era "
                    "cell_hourofweek_baseline window must cover them (AORC ends 2025-12-31, "
                    "so no capture-era window exists)."),
                "not_a_skill_claim": (
                    "every number below is a level beside a level with its own n. No "
                    "interval, no CSI, and no cross-universe comparison without its base "
                    "rate (flood 18).")},
            "events": per_event}


def markdown(doc: Mapping) -> str:
    u = doc["universe"]
    fmt = lambda v, n=4: "-" if v is None else f"{v:.{n}f}"       # noqa: E731
    out = ["# flood-build 21a — the route flood exhibit", "",
           f"**N = {u['n_events']} flood events.** {u['note']}", "",
           u["not_a_skill_claim"], "",
           f"**Gated:** {u['gated_on']}", "",
           "## What `gold/cell_hour_route` holds today", "",
           "| month | days |", "| --- | --- |"]
    out += [f"| `{m}` | {d[0]} .. {d[-1]} ({len(d)} day(s)) |" for m, d in u["months_held"].items()]
    for ev in doc["events"]:
        out += ["", f"## event `{ev['event_id']}` "
                    f"({ev['day_start']} .. {ev['day_end']}, `month={ev['month']}`)", "",
                f"- days covered: {', '.join(ev['days_covered'])} — **{ev['n_hours']} hours**, "
                f"{ev['n_routes']} routes",
                f"- `late_share` present on **{ev['late_share_available']}** of "
                f"{ev['n_routes']} routes; `ewt_s` on **{ev['ewt_s_available']}**",
                f"- `cell_hourofweek_baseline` window: **{ev['baseline_window'] or 'ABSENT'}** "
                f"— a speed ratio is available on **{ev['speed_ratio_available']}** routes"]
        if ev["baseline_overlap"]:
            o = ev["baseline_overlap"]
            out += [f"- baseline independence: `{o['window']}` spans {o['span'][0]} .. "
                    f"{o['span'][1]} and holds **{o['days_sharing_the_event_weekday']}** days "
                    f"of this event's weekday, of which the event's own "
                    f"{len(o['event_days_inside_the_window'])} "
                    f"({', '.join(o['event_days_inside_the_window'])}) are inside it. "
                    f"{o['note']}"]
        out += [""]
        # Sorted by whichever column exists, at the END that is worth reading: the largest
        # late_share, or the LOWEST speed ratio (slowest against the route's own dry side).
        by_late = [r for r in ev["routes"] if r["late_share"] is not None]
        rows_ = (sorted(by_late, key=lambda r: -r["late_share"])[:10] if by_late else
                 sorted([r for r in ev["routes"] if r["speed_ratio"] is not None],
                        key=lambda r: r["speed_ratio"])[:10])
        top = ("ten largest `late_share`" if by_late else
               "ten LOWEST `speed_mps / speed_dry` — slowest against their own dry baseline")
        if not rows_:
            out += ["Nothing on this event is comparable — the two counts above are why.", ""]
            continue
        out += ["| route | n_hours | n_events | late_share | ewt_s | speed_mps | speed_dry |"
                " ratio | other weekdays late_share (n hours) |", "| --- |" + " ---: |" * 8]
        for r in rows_:
            o = r.get("other_weekdays") or {}
            out.append(f"| `{r['route_id']}` | {r['n_hours']} | {r['n_events']} | "
                       f"{fmt(r['late_share'])} | {fmt(r['ewt_s'], 1)} | "
                       f"{fmt(r['speed_mps'], 3)} | {fmt(r['speed_dry'], 3)} | "
                       f"{fmt(r['speed_ratio'], 3)} | {fmt(o.get('late_share'))} "
                       f"({o.get('n_hours', 0)}) |")
        out += ["", f"The {top}; the JSON carries every route.",
                "`other weekdays` is NOT the named baseline table and is NOT hour-of-week "
                "matched, and every flood event day is cut out of it — see the module "
                "docstring for both.", ""]
    return "\n".join(out) + "\n"


# --- the driver ----------------------------------------------------------------------------


def stamps(root: Path) -> dict:
    """The four upstream version stamps this table must not move.

    IMPACT, NEVER A DETECTOR INPUT: `gold/route_flood` is downstream of the labels and the
    spine and feeds none of `features`, `flood_matrix`, `flood_exposure` or `flood_detect`.
    `main()` reads these on both sides of the build and raises on a move, rather than
    asserting the property in a docstring (flood-build 19's rule, one table over).
    """
    from raincheck import flood_detect as fd

    r, con = as_root(root), duck.connect()
    try:
        return {"features_version": features.features_version(root),
                "matrix_version": _one(con, r / "gold" / "flood_matrix", "matrix_version"),
                "score_version": _one(con, r / "gold" / "flood_exposure", "score_version"),
                "detector_version": fd.detector_version(fd.constants())}
    finally:
        con.close()


def build(root: Path) -> tuple[list[dict], list[checks.Row]]:
    con = duck.connect()
    try:
        table, counts = rows(root, con)
    finally:
        con.close()
    write(root, table)
    return table, census(table, counts)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exhibit", action="store_true",
                    help=f"write the measured exhibit to {EXHIBIT}.{{md,json}} (reads only)")
    args = ap.parse_args(argv)
    root = data_root()

    if args.exhibit:
        doc = exhibit(root)
        EXHIBIT.parent.mkdir(parents=True, exist_ok=True)
        EXHIBIT.with_suffix(".json").write_text(json.dumps(doc, indent=2, default=str) + "\n")
        EXHIBIT.with_suffix(".md").write_text(markdown(doc))
        print(f"research/{EXHIBIT.name}.{{md,json}}: N = {doc['universe']['n_events']} event(s)",
              flush=True)
        return

    before = stamps(root)
    table, rows_out = build(root)
    after = stamps(root)
    moved = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    if moved:
        raise SystemExit(f"a detector stamp MOVED: {moved} — this table is downstream of the "
                         f"labels and feeds no model, so something reached across that line")
    for r in rows_out:
        print(line(r))
    checks.write(root, CHECK, rows_out, CHECK_COLUMNS)
    print(f"route_flood_version = {table[0]['route_flood_version'] if table else None}; "
          + ", ".join(f"{k} = {v} (unmoved)" for k, v in after.items()), flush=True)
    sys.exit(checks.rc(rows_out))


if __name__ == "__main__":
    main()
