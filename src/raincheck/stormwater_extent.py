"""`make stormwater-extent` (flood-build 19): `silver/stormwater_extent` — DEP's design-storm
flood extents kept as POLYGONS, and `make geo` — the current-sea-level ones as GeoJSON.

`features.py` reads ONE of DEP's four scenarios (`SW_SCENARIO`, Moderate at current sea
level), reduces it to per-Cell area shares in `silver/cell_stormwater`, and throws every
polygon away. The scenario set is a city-authoritative, already-licensed rain-rate ->
flood-extent lookup (DESTINATION §3.B), so this module keeps the geometry: one row per
polygon, per scenario, with the intensity that produced it.

It is a DISPLAY layer and a lookup, never a detector input (DESTINATION-PLAN D2). Adding a
stormwater term to the model means new columns in `silver/cell_stormwater` ->
`features_version` -> `matrix_version` -> a refit, and flood 12's replay verdict is still
Ross's to read on the CURRENT fits. **Nothing here writes anything `features.features_version()`
reads**, and `main()` asserts the stamp on both sides of the build rather than trusting that.

WHAT DEP ACTUALLY PUBLISHES, measured on the pinned snapshot 2026-08-25:

  scenario   rain       horizon   readable            exported (D3)
  limited    1.77 in/hr current    NO - see UNREADABLE  -
  moderate   2.13 in/hr current    yes                  yes
  moderate   2.13 in/hr 2050       yes                  no
  extreme    3.66 in/hr 2080       yes                  no

D3 keeps every scenario in the table and serves only `horizon = current`: a 2080 climate
projection drawn beside a live rain rate invites the "might flood" over-read DESTINATION
§3.C warns about. There is no current-sea-level `extreme` scenario to serve - DEP publishes
Extreme at 2080 only - so `geo` is DERIVED from the table (`WHERE horizon = 'current'`)
rather than from a list of file names. A scenario appears the moment the table has it.

FOUR CATEGORIES, and "not analyzed" is one of them. `features.sample()` refuses to impute
DEP's exclusion mask to "no flooding"; this table carries the mask as `not_analyzed`
polygons so a consumer can DRAW it. The mask is differenced against that scenario's own
modelled classes (`features.build()`'s rule, reused), so the categories are disjoint and a
renderer may draw them in any order. The SLR scenarios add a third coded class, `Future
High Tides <horizon>` - a category, not the separate display layer flood 04 saw on the
tiled MapServer - which never reaches `horizon = current` and so never exports.

Licence: DEP's maps are NYC Open Data; ATTRIBUTION rides on every exported FeatureCollection
and the ticket file carries the string frontend2 03 renders. The DEC CSO layer flood 04 also
verified is NOT here and never enters `files/`: its licence bars secondary distribution.

Run: make stormwater-extent   (python -m raincheck.stormwater_extent)
     make geo                 (python -m raincheck.stormwater_extent --geo)
     rc 1 a scenario is missing from the table / 2 a declared dataset could not be read / 0
"""
import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import shapely
from pyproj import Transformer

from raincheck import checks, duck, features, publish
from raincheck.paths import as_root, data_root

CHECK = "stormwater_extent"
TABLE = "stormwater_extent"
CHECK_COLUMNS = checks.CORE + ("scenario", "horizon", "rain_in_hr", "category", "polygons",
                               "vertices_src", "vertices_kept", "tolerance_m", "zip_sha256")

# Simplification, chosen and MEASURED (see the RUN LOG entry). 5 m in the FGDB's own CRS,
# applied before reprojection so the tolerance is planar metres and not degrees. On the
# moderate/current scenario it takes 1,129,342 vertices to 222,938 (19.7%) for 0.12% of the
# modelled area - DEP's own framing is planning-grade and explicitly not site-specific, and
# 5 m is ~1.5 px at z15. It is a knob: one constant, one rebuild.
TOLERANCE_M = 5.0
TOLERANCE = TOLERANCE_M * features.US_SURVEY_FT   # SW_CRS is NY Long Island ftUS

# EPSG:2263 -> lon/lat. OGC:CRS84 rather than EPSG:4326 so the axis order is (lon, lat) by
# the CRS's own definition and not by an `always_xy` flag a later edit could drop - notify
# 04 measured what the other convention costs when it goes unnoticed. AXIS_GATE is the
# known pair that proves the direction, the rule `ref.build_zones` follows for Times Square.
FROM_SW = Transformer.from_crs(features.SW_CRS, "OGC:CRS84")
AXIS_GATE = ((989_000.0, 214_000.0), (-73.9855, 40.7580))   # ~Times Square, ftUS -> lon/lat

# The four datasets, copied VERBATIM from `unzip -l`. Nothing here is built from a pattern:
# the 2050 one is spelled `..._2_13_per_hr_with_2050_...` with no "inches", which no rule
# derived from its three siblings would ever produce.
_ZIP = "NYCFloodStormwaterFloodMaps/"
_LIMITED = (_ZIP + "NYC Stormwater Flood Map - Limited Flood (1.77 inches per hr) with "
            "Current Sea Levels/NYC_Stormwater_Flood_Map_Limited_Flood_1_77_inches_per_hr_"
            "with_Current_Sea_Levels.gdb")
_MOD_2050 = (_ZIP + "NYC Stormwater Flood Map - Moderate Flood (2.13 inches per hr) with "
             "2050 Sea Level Rise/NYC_Stormwater_Flood_Map_Moderate_Flood_2_13_per_hr_"
             "with_2050_Sea_Level_Rise.gdb")
_EXTREME = (_ZIP + "NYC Stormwater Flood Map - Extreme Flood (3.66 inches per hr) with "
            "2080 Sea Level Rise/NYC_Stormwater_Flood_Map_Extreme_Flood_3_66_inches_per_hr_"
            "with_2080_Sea_Level_Rise.gdb")


@dataclass(frozen=True)
class Scenario:
    scenario: str
    horizon: str
    rain_in_hr: float
    dataset: str

    @property
    def key(self) -> tuple[str, str]:
        return self.scenario, self.horizon


# features.SW_SCENARIO is the moderate/current path - one home for it, not a fifth copy.
SCENARIOS = (
    Scenario("limited", "current", 1.77, _LIMITED),
    Scenario("moderate", "current", 2.13, features.SW_SCENARIO),
    Scenario("moderate", "2050", 2.13, _MOD_2050),
    Scenario("extreme", "2080", 3.66, _EXTREME),
)
CURRENT = "current"          # the one horizon `make geo` serves (D3)

# The FGDB's own coded domain, EXTENDED rather than retyped: features.SW_CATEGORY is the
# whole domain of the current-sea-level scenarios, and the two SLR ones add code 3, whose
# name comes out of the geodatabase's coded-value domain as "Future High Tides <horizon>".
MASK = "not_analyzed"
CATEGORY = dict(features.SW_CATEGORY) | {3: "future_high_tides"}

# MEASURED 2026-08-25, and a permanent property of this snapshot rather than a flake. The
# Limited geodatabase stores its one feature class as a COMPRESSED FGDB table
# (`a00000009.gdbtable.cdf`, magic "2FDC", and no `a00000009.gdbtablx` - the row index its
# three uncompressed siblings all have). GDAL's OpenFileGDB driver cannot decompress CDF.
# Three measurements, because the SAME unreadable file arrives three different ways:
#   GDAL 3.8.5 (duckdb_spatial's, the repo's only GDAL) through /vsizip -> IOException at open
#   GDAL 3.8.5 on an EXTRACTED copy                     -> opens, ZERO features, no error
#   GDAL 3.12.4 (pyogrio, a throwaway venv, diagnostic) -> refuses, naming CDF and the
#                                                          proprietary Esri FileGDB driver
# The middle row is why `scenario_parts` guards the empty read as well as the exception: a
# reader that handled only the exception would publish an empty Limited extent to anyone
# who unzipped first, and it would render as "1.77 in/hr floods nothing" - the same class
# of lie as imputing DEP's exclusion mask to "no flooding". flood 04 measured that no
# queryable service exists anywhere for 9i7c-xyvv, so the pinned zip IS the access path and
# `limited` cannot be built from it at all. Closing this needs a differently-encoded source,
# re-pinned; it is not a retry. Every OTHER unreadable dataset fails the build outright.
UNREADABLE = {
    ("limited", "current"):
        "compressed FGDB (CDF) feature class - OpenFileGDB cannot decompress it (GDAL "
        "3.8.5 raises through /vsizip and reads 0 features from an extracted copy; 3.12.4 "
        "refuses the dataset); needs a re-encoded source, not a retry",
}

ATTRIBUTION = (
    "Stormwater flood extents: NYC Department of Environmental Protection, NYC Stormwater "
    "Flood Maps (NYC Open Data 9i7c-xyvv), snapshot {asof}. Planning-grade design-storm "
    "modelling - not an observation of water and not a site-specific determination.")


class Unreadable(RuntimeError):
    """A declared dataset came back empty. Fatal unless UNREADABLE names it."""


def check_axis() -> None:
    """Prove the transform's direction before any geometry moves through it.

    A distance or a containment test whose oracle is the same function it is testing proves
    nothing (notify 04, on ST_Distance_Sphere's (lat, lon) argument order). This is the same
    guard one level up: a known ftUS pair whose lon/lat answer is checked against a literal,
    so a transform wired backwards raises here instead of publishing a plausible map of the
    Indian Ocean."""
    (x, y), (want_lon, want_lat) = AXIS_GATE
    lon, lat = FROM_SW.transform(x, y)
    if abs(lon - want_lon) > 0.01 or abs(lat - want_lat) > 0.01:
        raise RuntimeError(f"{features.SW_CRS} -> lon/lat is wired wrong: ({x}, {y}) came "
                           f"back ({lon:.4f}, {lat:.4f}), not ~({want_lon}, {want_lat})")


def to_wgs(geom):
    """The SW CRS -> CRS84, `features.reproject` run the other way."""
    return shapely.transform(
        geom, lambda c: np.column_stack(FROM_SW.transform(c[:, 0], c[:, 1])))


def scenario_parts(zip_path: Path, s: Scenario) -> dict[str, list]:
    """One scenario's coded classes as EPSG:2263 polygon parts.

    `features.flood_parts()`'s read, verbatim except for the dataset: DuckDB spatial's
    OpenFileGDB driver, in place through /vsizip/, no unzip and no new dependency. The
    layer is one MultiPolygon per Flooding_Category.

    A dataset that will not open, and a dataset that opens and yields NOTHING, both raise
    `Unreadable`: GDAL 3.8.5 does the first through /vsizip and the SECOND on an extracted
    copy of the same geodatabase, so a reader that only handled the exception would still
    publish an empty extent for anyone who unzipped first."""
    con = duck.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    try:
        rows = con.execute(
            "SELECT Flooding_Category, ST_AsWKB(ST_Force2D(Shape)) FROM ST_Read(?)",
            [f"/vsizip/{zip_path}/{s.dataset}"]).fetchall()
    except duckdb.Error as exc:
        raise Unreadable(f"{s.scenario}/{s.horizon}: the dataset would not open - "
                         f"{str(exc).splitlines()[0]}") from None
    finally:
        con.close()
    if not rows:
        raise Unreadable(f"{s.scenario}/{s.horizon}: the dataset opened and returned NO "
                         f"features - {s.dataset}")
    out: dict[str, list] = {}
    for code, wkb in rows:
        if code not in CATEGORY:
            raise RuntimeError(f"{s.scenario}/{s.horizon}: unknown Flooding_Category {code} "
                               f"(the geodatabase's coded domain here is {CATEGORY})")
        out[CATEGORY[code]] = list(shapely.get_parts(
            features.valid(shapely.from_wkb(bytes(wkb)))))
    return out


def with_mask(parts: dict[str, list], mask_union) -> dict[str, list]:
    """Add the exclusion mask as its own category, claiming only ground no modelled class
    claims - `features.build()`'s rule, so the four categories partition the same way the
    per-Cell shares do and a renderer can draw them in any order."""
    modelled = shapely.union_all([g for v in parts.values() for g in v])
    left = shapely.get_parts(mask_union.difference(modelled))
    # `get_parts` of an empty geometry is [POLYGON EMPTY], not [] - and a zero-geometry row
    # is exactly the state the check batch reports as a failure.
    return parts | {MASK: [g for g in left if not g.is_empty]}


def simplify(parts: dict[str, list]) -> tuple[dict[str, list], dict[str, tuple[int, int]]]:
    """Simplify in the SOURCE CRS, then reproject. Returns the parts and the per-category
    (vertices before, vertices after) the check row publishes."""
    out, counts = {}, {}
    for name, geoms in parts.items():
        kept = [to_wgs(shapely.simplify(g, TOLERANCE, preserve_topology=True)) for g in geoms]
        kept = [g for g in kept if not g.is_empty]
        out[name] = kept
        counts[name] = (int(sum(shapely.get_num_coordinates(g) for g in geoms)),
                        int(sum(shapely.get_num_coordinates(g) for g in kept)))
    return out, counts


def rows(root: Path, scenarios=SCENARIOS) -> tuple[list[tuple], dict]:
    """Every scenario's polygons, in declaration order. The sha256 is checked ONCE per run:
    `stormwater_zip` re-reads and re-hashes 33.8 MB on every call, so the path is taken once
    and carried, never re-derived per dataset."""
    check_axis()
    root = as_root(root)
    zip_path = features.stormwater_zip(root)
    mask_union = shapely.union_all(features.mask_polygons(root))
    out, counts = [], {}
    for s in scenarios:
        try:
            parts = scenario_parts(zip_path, s)
        except Unreadable as exc:
            if s.key not in UNREADABLE:
                raise
            print(f"  {s.scenario}/{s.horizon}: SKIPPED - {UNREADABLE[s.key]}", flush=True)
            continue
        parts, counts[s.key] = simplify(with_mask(parts, mask_union))
        for name in sorted(parts):
            for i, g in enumerate(parts[name]):
                out.append((s.scenario, s.horizon, s.rain_in_hr, name, i,
                            shapely.to_wkb(g), features.SRC_ASOF, features.SW_ZIP_SHA256))
        print(f"  {s.scenario}/{s.horizon} {s.rain_in_hr} in/hr: "
              f"{ {k: len(v) for k, v in sorted(parts.items())} }", flush=True)
    return out, counts


def write(root: Path, table: list[tuple]) -> Path:
    """One GeoParquet part, staged then moved (the ref-table idiom). DuckDB writes the
    GeoParquet `geo` metadata itself when it copies a GEOMETRY column, so the CRS travels
    with the file and no metadata is hand-rolled here."""
    root = as_root(root)
    out = root / "silver" / TABLE / "part-00000.parquet"
    tmp = out.with_suffix(".parquet.tmp")
    out.parent.mkdir(parents=True, exist_ok=True)
    con = duck.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("CREATE TABLE t (scenario VARCHAR, horizon VARCHAR, rain_in_hr DOUBLE, "
                "category VARCHAR, poly BIGINT, wkb BLOB, src_asof DATE, zip_sha256 VARCHAR)")
    if table:   # executemany refuses an empty parameter list; the empty table is still real
        con.executemany("INSERT INTO t VALUES (?,?,?,?,?,?,?,?)", table)
    con.execute(
        "COPY (SELECT scenario, horizon, rain_in_hr, category, poly, "
        "             ST_GeomFromWKB(wkb) AS geometry, src_asof, zip_sha256 "
        "      FROM t ORDER BY scenario, horizon, category, poly) "
        f"TO '{tmp}' (FORMAT PARQUET, COMPRESSION 'zstd')")
    con.close()
    tmp.replace(out)
    print(f"silver/{TABLE}: {len(table)} rows -> {out}", flush=True)
    return out


# --- the check batch ---------------------------------------------------------------------


def census(root: Path, counts: dict | None = None, scenarios=SCENARIOS) -> list[checks.Row]:
    """One row per (scenario, horizon, category) in the built table, plus one row for every
    DECLARED scenario the table does not hold at all - so a suite can expect on the shape
    rather than on whichever scenarios happened to build.

    A declared scenario missing from the table is FAIL, except the one UNREADABLE names,
    which is INCONCLUSIVE: OpenFileGDB cannot read that container, which says nothing about
    the data. Vertex counts ride only on a run that just built (`counts`); read back off a
    finished table they are absent, never zero.
    """
    con = duck.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    got = con.execute(
        "SELECT scenario, horizon, any_value(rain_in_hr), category, count(*), "
        "       sum(ST_NPoints(geometry)) "
        f"FROM read_parquet(?) GROUP BY 1, 2, 4 ORDER BY 1, 2, 4",
        [f"{as_root(root) / 'silver' / TABLE}/**/*.parquet"]).fetchall()
    con.close()
    rows_out, seen = [], set()
    for scenario, horizon, rain, category, n, pts in got:
        seen.add((scenario, horizon))
        pre = (counts or {}).get((scenario, horizon), {}).get(category, (None,))[0]
        m = {"scenario": scenario, "horizon": horizon, "rain_in_hr": rain,
             "category": category, "polygons": int(n), "vertices_src": pre,
             "vertices_kept": int(pts), "tolerance_m": TOLERANCE_M,
             "zip_sha256": features.SW_ZIP_SHA256}
        rows_out.append(checks.Row(
            CHECK, f"{scenario} {horizon} {category}",
            checks.OK if n and pts else checks.FAIL,
            "" if n and pts else "  the category is present with no geometry", m))
    for s in scenarios:
        if s.key in seen:
            continue
        m = {"scenario": s.scenario, "horizon": s.horizon, "rain_in_hr": s.rain_in_hr,
             "category": None, "polygons": 0, "vertices_src": None, "vertices_kept": None,
             "tolerance_m": TOLERANCE_M, "zip_sha256": features.SW_ZIP_SHA256}
        known = UNREADABLE.get(s.key)
        rows_out.append(checks.Row(
            CHECK, f"{s.scenario} {s.horizon}",
            checks.INCONCLUSIVE if known else checks.FAIL,
            f"  {known}" if known else "  declared but absent from the table", m))
    return rows_out


def line(r: checks.Row) -> str:
    m = r.measures
    mark = {checks.OK: "OK ", checks.FAIL: "BAD", checks.INCONCLUSIVE: "???"}[r.outcome]
    return (f"{mark} {m['scenario']:9s} {m['horizon']:7s} {m['rain_in_hr']:.2f} in/hr "
            f"{(m['category'] or '-'):18s} {m['polygons'] or 0:7d} polys "
            f"{m['vertices_kept'] or 0:8d} pts{r.detail}")


# --- the export --------------------------------------------------------------------------


GEO_DIR = publish.WEB / "files" / "geo"


def geojson(con, root: Path, scenario: str, horizon: str) -> str:
    """One FeatureCollection per scenario: one Feature per category, geometry a MultiPolygon
    of that category's parts in `poly` order.

    Per-category rather than per-polygon because the geometry is the same either way and
    26,418 Feature envelopes are ~2.6 MB of pure boilerplate.

    Three details are load-bearing. Precision is reduced per PART - `ST_ReducePrecision`
    over a whole category at once raises a GEOS side-location conflict (measured). Each
    reduced part is then DUMPED back to polygons before collecting, because reducing a
    polygon can split it in two and `ST_Collect` over a mixed Polygon/MultiPolygon list
    returns a **GeometryCollection**, which MapLibre does not draw (measured: the first
    export of this file was three undrawable GeometryCollections). And a part that collapses
    to nothing at 5 dp - a polygon narrower than the ~1 m grid - is dropped rather than
    emitted empty, which is why `n_polygons` counts what is DRAWN and can sit below the
    table's row count for that category.

    Every aggregate is ORDER BY'd and every coordinate explicitly reduced, so a re-export is
    byte-identical - `tests/test_export.py`'s rule."""
    (text,) = con.execute("""
        SELECT '{"type":"FeatureCollection","attribution":' || to_json(?) ||
               ',"features":[' || string_agg(f, ',' ORDER BY category) || ']}'
        FROM (
          SELECT category, json_object(
                   'type', 'Feature',
                   'properties', json_object('scenario', scenario, 'horizon', horizon,
                                             'rain_in_hr', any_value(rain_in_hr),
                                             'category', category,
                                             'n_polygons', sum(len(parts))),
                   'geometry', ST_AsGeoJSON(
                       ST_Collect(flatten(list(parts ORDER BY poly))))::JSON
                 )::VARCHAR AS f
          FROM (SELECT scenario, horizon, rain_in_hr, category, poly,
                       [d.geom FOR d IN
                        ST_Dump(ST_ReducePrecision(geometry, 0.00001))
                        IF NOT ST_IsEmpty(d.geom)] AS parts
                FROM read_parquet(?)
                WHERE scenario = ? AND horizon = ?)
          WHERE len(parts) > 0
          GROUP BY scenario, horizon, category)
        """, [ATTRIBUTION.format(asof=features.SRC_ASOF),
              f"{as_root(root) / 'silver' / TABLE}/**/*.parquet", scenario, horizon]).fetchone()
    if text is None:
        raise RuntimeError(f"{scenario}/{horizon} has no rows in silver/{TABLE}")
    return text + "\n"


def export(root: Path, out_dir: Path = GEO_DIR) -> dict[str, Path]:
    """Every `horizon = current` scenario the table holds -> `web/files/geo/`.

    DERIVED from the table, never from a list of names: D3 serves the current sea level and
    DEP publishes Extreme at 2080 only, so the served set is whatever `current` scenarios
    exist. `stormwater-limited.geojson` appears with no code change the day its geodatabase
    becomes readable (see UNREADABLE)."""
    con = duck.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    served = [r[0] for r in con.execute(
        f"SELECT DISTINCT scenario FROM read_parquet(?) WHERE horizon = ? ORDER BY 1",
        [f"{as_root(root) / 'silver' / TABLE}/**/*.parquet", CURRENT]).fetchall()]
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for scenario in served:
        name = f"stormwater-{scenario}.geojson"
        tmp = out_dir / (name + ".tmp")
        tmp.write_text(geojson(con, root, scenario, CURRENT))
        written[name] = tmp.replace(out_dir / name)
    con.close()
    missing = sorted({s.scenario for s in SCENARIOS if s.horizon == CURRENT} - set(served))
    for scenario in missing:
        print(f"  {scenario}: NOT exported - no {CURRENT} rows in silver/{TABLE}", flush=True)
    for name, path in written.items():
        print(f"  {name}: {path.stat().st_size / 1024:.0f} KB", flush=True)
    return written


# --- entry points ------------------------------------------------------------------------


def build(root: Path) -> list[checks.Row]:
    table, counts = rows(root)
    write(root, table)
    return census(root, counts)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geo", action="store_true",
                    help=f"export the {CURRENT}-sea-level scenarios to {GEO_DIR}")
    args = ap.parse_args(argv)
    root = data_root()
    if args.geo:
        if not export(root):
            raise SystemExit(f"nothing exported: silver/{TABLE} holds no {CURRENT} scenario")
        return
    # The stamp brackets the build UNCONDITIONALLY. `features_version` is a pure function of
    # silver/asset_features, ref/assets and the frozen constants - none of which this module
    # writes - so a move here means something reached across that line, and a moved stamp
    # rolls matrix_version and demands a refit while flood 12's verdict is pending.
    before = features.features_version(root)
    rows_out = build(root)
    after = features.features_version(root)
    if before != after:
        raise SystemExit(f"features_version MOVED: {before} -> {after} - this module writes "
                         f"nothing that stamp reads, so something reached across that line")
    for r in rows_out:
        print(line(r))
    checks.write(root, CHECK, rows_out, CHECK_COLUMNS)
    print(f"features_version = {after} (unmoved)", flush=True)
    sys.exit(checks.rc(rows_out))


if __name__ == "__main__":
    main()
