"""Flood labels (flood-build ticket 05 / spec "Labels and the event spine").

`gold/flood_labels` — POSITIVES ONLY. One row per (asset_id, event_id) where at least one
label-grade observation from `silver/flood_obs` attached to a Unit or Carrier during an
event's window. There are no negative rows in the file and there never will be: negatives
are generated at READ by `negatives()`, an anti-join under the per-source coverage
calendars and the anachronism rules, so a Unit is only ever "dry" for an event where some
source could actually have seen it flood.

The estimand is `flooded_reported` — where flooding was REPORTED, not where water
necessarily stood. It is stamped in the file's parquet metadata as well as said here,
because the whole downstream fit inherits it.

Attachment (one rule per source shape, identical everywhere):
  radius   point observations within RADIUS_M = 100 m GEODESIC of an entrance or bus stop
  cell     point observations whose H3 Cell equals a scored Cell asset's
  polygon  the Sandy footprint containing a point asset / intersecting a Cell's HEXAGON
           (ref/assets stores a Cell as its centroid point; the footprint is 30 km wide
           and centroid-in-polygon undercounts the coastal Cells by roughly five to one)
  station  an MTA alert that NAMED a complex, landing as ONE row on the complex
           (entrances inherit for display only, never as stored rows)
Alerts attach to the complex and to nothing else: ticket 08 uses the alert-sourced
complex-event pairs as an INDEPENDENT complex-grain validation set, which a leak onto
the child entrances the point model fits on would destroy.

Run: make flood-labels     (python -m raincheck.flood_labels)
"""
import argparse
import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

from raincheck import flood_obs as fo, flood_spine as fs, ref
from raincheck.paths import data_root

ESTIMAND = "flooded_reported"
RADIUS_M = 100.0  # THE attachment radius, geodesic, one constant for every point source

# ---- the frozen attachment matrix -------------------------------------------------
LABEL_KINDS = ("complex", "entrance", "bus_stop", "cell")  # stations are Carriers only
RADIUS_KINDS = ("entrance", "bus_stop")
POINT_SOURCES = ("311", "floodnet", "usgs_hwm")
POLYGON_SOURCES = ("sandy",)
STATION_SOURCES = ("mta_alert",)
SUPPORT = ("cell", "polygon", "radius", "station")  # sorted: the stored arrays are sorted
# bit per label-grade source, in flood_obs's own frozen SOURCES order. Reordering SOURCES
# restamps label_version by construction, so an old file can never be read with a new map.
SOURCE_BIT = {s: 1 << i for i, s in enumerate(fo.SOURCES)}

# ---- the negative universe: which sources can set `flooded` on which kind ---------
# A negative pair is valid iff at least ONE source that can label this kind was live for
# every day of the event. The spine already computed the per-event coverage flags off the
# per-source calendars (311 continuous; alerts 2016+ minus the 2020-04 hole and the
# 2026-06-30..08-15 dark gap; FloodNet 2020-11-16+) — this is only the kind -> source map.
# Complexes are alert-only BECAUSE alert-only is how their positives are minted: a complex
# in a 2012 event has no source that could have reported it, so it is not a negative.
DETECTORS = {"complex": ("alert",), "entrance": ("311", "floodnet"),
             "bus_stop": ("311", "floodnet"), "cell": ("311", "floodnet")}

# ---- anachronism rules ------------------------------------------------------------
# Post-2010 subway openings, frozen with the name each complex_id must still carry (the
# build asserts it: a re-keyed registry must fail loudly, never silently stop excluding).
# A Unit that did not exist cannot have been dry.
OPENED = {"471": (date(2015, 9, 13), "34 St-Hudson Yards"),
          "477": (date(2017, 1, 1), "72 St"),        # Second Av, the three SAS complexes
          "476": (date(2017, 1, 1), "86 St"),
          "475": (date(2017, 1, 1), "96 St"),
          "328": (date(2018, 9, 8), "WTC Cortlandt")}
# The bus registry is built from 2026 Picks and no historical Pick exists locally (flood
# wayfinder 13 measured that nothing public holds the bytes), so a pre-2020 stop-event
# pair asserts an existence we cannot check. The two redesigns moved whole boroughs, so
# their feeds carry a later floor. Month granularity is the design's own precision.
BUS_STOPS_FROM = date(2020, 1, 1)
BUS_REDESIGN = {"bronx": date(2022, 6, 1), "queens": date(2025, 1, 1)}


# ---- the pure read-side negatives generator ---------------------------------------

def detectable(kind: str, event: Mapping) -> bool:
    """Could any source that labels this kind have seen this event? A dark source is
    coverage=missing, never an implicit dry Unit."""
    return any(event[f"cov_{s}"] for s in DETECTORS[kind])


def anachronistic(asset: Mapping, event: Mapping) -> bool:
    """Did this Unit not exist yet — or not exist in a form we can vouch for?

    Judged on the event's FIRST day: a station that opened mid-event was not there for
    the whole window, and the conservative call mints no negative rather than a false one.
    """
    day = event["day_start"]
    if asset["kind"] in ("complex", "entrance"):
        opened = OPENED.get(asset["complex_id"])
        return opened is not None and day < opened[0]
    if asset["kind"] == "bus_stop":
        floors = [BUS_STOPS_FROM] + [BUS_REDESIGN[f] for f in (asset["feeds"] or ())
                                     if f in BUS_REDESIGN]
        return day < max(floors)
    return False  # an H3 Cell has always been there


def in_universe(asset: Mapping) -> bool:
    """Cells enter the negative universe only inside the frozen cells_scored set; every
    other label kind enters whole."""
    return asset["kind"] in LABEL_KINDS and (asset["kind"] != "cell" or asset["scored"])


def pairable(asset: Mapping, event: Mapping) -> bool:
    """THE rule: is (this Unit, this event) a pair we can say anything about at all?

    Ticket 08 must run positives through this too. The table below stores every positive,
    including the ones this rejects — the label record is the label record — but a fit
    that keeps a 2015 bus-stop positive while the same rule deletes every 2015 bus-stop
    negative has manufactured a class imbalance out of a bookkeeping rule. `census()`
    counts exactly those rows so the choice is made in daylight.
    """
    return (in_universe(asset) and detectable(asset["kind"], event)
            and not anachronistic(asset, event))


def negatives(assets: Iterable[Mapping], events: Iterable[Mapping],
              positives: Iterable[tuple[str, str]]) -> Iterator[dict]:
    """Every valid negative (asset_id, event_id), generated — never stored.

    Pure: assets, events and positives are plain mappings, so ticket 18's alternate
    universes and every test drive it with fixture calendars instead of a table.
    """
    pos = {(a, e) for a, e in positives}
    units = [a for a in assets if in_universe(a)]
    for event in events:
        for asset in units:
            if not pairable(asset, event):
                continue
            if (asset["asset_id"], event["event_id"]) in pos:
                continue
            yield {"asset_id": asset["asset_id"], "kind": asset["kind"],
                   "cell": asset["cell"], "event_id": event["event_id"]}


def read_negatives(root: Path) -> Iterator[dict]:
    """`negatives()` bound to the built tables — the read-side entry point ticket 08 and
    the validation harness call."""
    cols = ("asset_id", "kind", "cell", "complex_id", "feeds", "scored")
    assets = pq.read_table(root / "ref" / "assets", columns=list(cols)).to_pylist()
    events = pq.read_table(root / "silver" / "flood_events").to_pylist()
    labels = pq.read_table(root / "gold" / "flood_labels",
                           columns=["asset_id", "event_id"])
    return negatives(assets, events, zip(labels.column("asset_id").to_pylist(),
                                         labels.column("event_id").to_pylist()))


def census(assets: Iterable[Mapping], events: Iterable[Mapping],
           positives: Iterable[tuple[str, str]] = ()) -> dict[str, int]:
    """What each rule drops from the raw kind x event grid — the published deltas. No
    silent caps: an exclusion nobody can count is an exclusion nobody will check."""
    units, evs = [a for a in assets if in_universe(a)], list(events)
    pos, out = {(a, e) for a, e in positives}, {
        "units": len(units), "events": len(evs), "grid": len(units) * len(evs),
        "dropped_uncovered": 0, "dropped_anachronistic": 0, "positives_outside": 0}
    for e in evs:
        for a in units:
            if not detectable(a["kind"], e):
                out["dropped_uncovered"] += 1
            elif anachronistic(a, e):
                out["dropped_anachronistic"] += 1
            else:
                continue
            out["positives_outside"] += (a["asset_id"], e["event_id"]) in pos
    out["candidates"] = (out["grid"] - out["dropped_uncovered"]
                         - out["dropped_anachronistic"])
    out["negatives"] = out["candidates"] - (len(pos) - out["positives_outside"])
    return out


# ---- label_version ----------------------------------------------------------------

def label_version(root: Path, spine_version: str, asof: date = fo.ASOF) -> str:
    """sha1 over everything that can move a label: the source as-of stamp, the frozen 311
    thresholds, RADIUS_M, assets_version — and spine_version, which already chains the
    window rule and the trigger vocabularies. Chaining it is what stops labels from ever
    silently mixing spines, and makes ticket 18's alternate universes stamp differently by
    construction. The negative rules are in here too: they are part of the label set even
    though no negative row is stored."""
    payload = json.dumps({
        "asof": asof.isoformat(), "assets_version": ref.assets_version(root),
        "spine_version": spine_version, "p99": fs.P99_311, "radius_m": RADIUS_M,
        "source_bit": SOURCE_BIT, "label_kinds": LABEL_KINDS,
        "radius_kinds": RADIUS_KINDS, "detectors": DETECTORS, "estimand": ESTIMAND,
        "opened": {k: v[0].isoformat() for k, v in OPENED.items()},
        "bus_stops_from": BUS_STOPS_FROM.isoformat(),
        "bus_redesign": {k: v.isoformat() for k, v in BUS_REDESIGN.items()},
    }, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()


# ---- the build --------------------------------------------------------------------

def _quoted(values: Iterable[str]) -> str:
    return ",".join(f"'{v}'" for v in values)


# One SELECT per attachment rule, unioned. Every branch answers the same eight columns.
# The radius branch leans on Sedona's distance join: ST_DWithin(..., useSpheroid = true)
# was cross-checked against an independent H3 kRing(1) prefilter plus an explicit
# ST_DistanceSpheroid filter on the real tables — 51,690 pairs both ways.
ATTACH = f"""
SELECT a.asset_id, a.kind, a.cell, oe.event_id, oe.source, oe.depth_mm, 'radius' AS support
  FROM oe JOIN a ON ST_DWithin(oe.geometry, a.geometry, {RADIUS_M}, true)
 WHERE oe.source IN ({_quoted(POINT_SOURCES)}) AND a.kind IN ({_quoted(RADIUS_KINDS)})
UNION ALL
SELECT a.asset_id, a.kind, a.cell, oe.event_id, oe.source, oe.depth_mm, 'cell'
  FROM oe JOIN a ON a.cell = oe.cell
 WHERE oe.source IN ({_quoted(POINT_SOURCES)}) AND a.kind = 'cell' AND a.scored
UNION ALL
SELECT a.asset_id, a.kind, a.cell, oe.event_id, oe.source, oe.depth_mm, 'polygon'
  FROM oe JOIN a ON ST_Contains(oe.geometry, a.geometry)
 WHERE oe.source IN ({_quoted(POLYGON_SOURCES)}) AND a.kind IN ({_quoted(RADIUS_KINDS)})
UNION ALL
SELECT h.asset_id, h.kind, h.cell, oe.event_id, oe.source, oe.depth_mm, 'polygon'
  FROM oe JOIN h ON ST_Intersects(oe.geometry, h.geometry)
 WHERE oe.source IN ({_quoted(POLYGON_SOURCES)})
UNION ALL
-- the alert's complex is the tail of flood_obs's frozen source_id grammar
-- '<event_id>[+<event_id>...]:<complex_id>'; complex ids carry no colon
SELECT a.asset_id, a.kind, a.cell, oe.event_id, oe.source, oe.depth_mm, 'station'
  FROM oe JOIN a ON a.complex_id = element_at(split(oe.source_id, ':'), -1)
 WHERE oe.source IN ({_quoted(STATION_SOURCES)}) AND a.kind = 'complex'
"""

def build(root: Path, spark, asof: date = fo.ASOF) -> int:
    import shutil

    def geo(*parts: str):
        return spark.read.format("geoparquet").load(str(root.joinpath(*parts)))

    events = spark.read.parquet(str(root / "silver" / "flood_events"))
    (version,) = {r[0] for r in events.select("spine_version").distinct().collect()}
    geo("ref", "assets").where(f"kind IN ({_quoted(LABEL_KINDS)})").createOrReplaceTempView("a")
    geo("silver", "flood_obs").createOrReplaceTempView("o")
    geo("ref", "cells").createOrReplaceTempView("c")
    events.createOrReplaceTempView("e")
    # a Cell asset is a centroid point; its FOOTPRINT lives in ref/cells, and the polygon
    # rule needs the hexagon. A scored Cell with no hexagon is a broken registry, not a
    # quiet zero, so the join is asserted total.
    spark.sql("""SELECT a.asset_id, a.kind, a.cell, c.geometry FROM a JOIN c USING (cell)
                  WHERE a.kind = 'cell' AND a.scored""").createOrReplaceTempView("h")
    scored, hexes = (spark.sql("SELECT count(*) FROM a WHERE kind = 'cell' AND scored")
                     .collect()[0][0], spark.table("h").count())
    if scored != hexes:
        raise RuntimeError(f"{scored - hexes} scored Cells have no hexagon in ref/cells")

    # an observation belongs to the ONE event whose window contains it; the windows of two
    # events never overlap (contiguous days merge, so a gap is at least two days, and the
    # 3 h pads cannot meet across one), which the grain test pins
    spark.sql("""SELECT o.*, e.event_id FROM o JOIN e
                   ON o.ts_utc >= e.window_start_utc AND o.ts_utc < e.window_end_utc"""
              ).cache().createOrReplaceTempView("oe")
    n_obs, n_in = spark.table("o").count(), spark.table("oe").count()
    print(f"flood_obs: {n_obs} observations, {n_in} inside an event window "
          f"({n_obs - n_in} on no event-day)", flush=True)

    spark.sql(ATTACH).createOrReplaceTempView("attached")
    alerts = spark.sql("SELECT count(*) FROM attached WHERE support = 'station'").collect()
    want = spark.sql("SELECT count(*) FROM oe WHERE source = 'mta_alert'").collect()
    if alerts[0][0] != want[0][0]:
        raise RuntimeError(f"alert observations lost their complex: {alerts[0][0]} labels "
                           f"from {want[0][0]} observations — ref/assets re-keyed?")
    _assert_openings(spark)

    stamp = label_version(root, version, asof)
    out = spark.sql(f"""
        SELECT asset_id, kind, event_id, cell,
               CAST(bit_or(bit) AS SMALLINT) AS source_mix,
               max(depth_mm) AS depth_mm,
               sort_array(collect_set(support)) AS label_support,
               '{stamp}' AS label_version
          FROM (SELECT asset_id, kind, event_id, cell, depth_mm, support,
                       CASE source {' '.join(f"WHEN '{s}' THEN {b}"
                                             for s, b in SOURCE_BIT.items())} END AS bit
                  FROM attached)
         GROUP BY asset_id, kind, event_id, cell
    """).coalesce(1).sortWithinPartitions("event_id", "asset_id")

    staging = root / ".staging" / "flood_labels"
    out.write.mode("overwrite").parquet(str(staging))
    (part,) = staging.glob("part-*.parquet")
    table = pq.read_table(part)
    shutil.rmtree(staging)
    dest = root / "gold" / "flood_labels" / "part-00000.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    # the estimand rides in the file, not only in the docs: every reader of these bytes
    # inherits "where flooding was REPORTED", and a stripped-down copy still says so
    pq.write_table(table.replace_schema_metadata({
        **(table.schema.metadata or {}), b"estimand": ESTIMAND.encode(),
        b"estimand_note": b"where flooding was REPORTED, not where water necessarily stood",
        b"label_version": stamp.encode(),
        b"spine_version": version.encode(), b"negatives": b"generated at read; none stored",
    }), dest, compression="zstd")
    print(f"gold/flood_labels: {table.num_rows} positives -> {dest}", flush=True)
    return table.num_rows


def _assert_openings(spark) -> None:
    """The frozen opening list must still name the complexes it was measured on."""
    got = dict(spark.sql(f"SELECT complex_id, name FROM a WHERE kind = 'complex' "
                         f"AND complex_id IN ({_quoted(OPENED)})").collect())
    bad = {c: (got.get(c), n) for c, (_, n) in OPENED.items() if got.get(c) != n}
    if bad:
        raise RuntimeError(f"station-opening list drifted from ref/assets (got, frozen): "
                           f"{bad} — the anachronism rule would stop excluding silently")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--asof", default=fo.ASOF.isoformat())
    ap.add_argument("--census", action="store_true",
                    help="print the negative universe and what each rule drops")
    a = ap.parse_args()
    root = data_root()
    if a.census:
        assets = pq.read_table(root / "ref" / "assets").to_pylist()
        events = pq.read_table(root / "silver" / "flood_events").to_pylist()
        lab = pq.read_table(root / "gold" / "flood_labels",
                            columns=["asset_id", "event_id"])
        for k, v in census(assets, events,
                           zip(lab.column("asset_id").to_pylist(),
                               lab.column("event_id").to_pylist())).items():
            print(f"{k}: {v}")
        return
    from raincheck.spark import session

    build(root, session(), date.fromisoformat(a.asof))


if __name__ == "__main__":
    main()
