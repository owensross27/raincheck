"""`make features` (flood-build 03): `silver/asset_features` — NAVD88 elevation, the 15 m
doorway-scale relief ring and the DEP stormwater category for every point asset, plus
`silver/cell_stormwater`, the per-Cell area shares 08's Cell model reads.

Point assets only (15,490 = 2,120 entrances + 13,370 bus stops). Complex and Cell
elevation aggregates are read-side GROUP BYs over grade_ok children in 08, never stored
rows: ref/cells is a bbox tiling and ~2,759 of its 4,113 Cells touch no NYC land.

Canonical elevation is the 2017 1-m DEM ImageServer in NAVD88 metres, published as US
survey feet; the 2014 epoch is a cross-check that feeds `grade_ok` and nothing else.
grade_ok is a FILTER, never a model feature — the flagged rows concentrate on
alert-heavy complexes inside the Sandy polygon, which would be a memorization channel.

Licence discipline (DEC/DEP fetch-and-use, rehosting barred): every snapshot lands under
<root>/snapshots, NOT <root>/archive, so `make coldpush` can never carry it off the
machine.

Run: make features   (python -m raincheck.features)
"""
import hashlib
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from pyproj import Geod, Transformer
from shapely.strtree import STRtree

from raincheck import ref
from raincheck.paths import data_root

# ---- elevation: the NYS ImageServer getSamples path (keyless, no bulk download) ----
ELEV_URL = "https://elevation.its.ny.gov/arcgis/rest/services/{service}/ImageServer/getSamples"
DEM_2017 = "NYC_TopoBathymetric_2017_1_meter"  # canonical: NAVD88 metres, Geoid 12B
DEM_2014 = "USGS_NYC2014_1_meter"              # cross-check only; its service metadata is EMPTY,
# units/datum inferred from agreement with 2017 (median delta +0.075 m, sigma 0.88 m) — a
# provenance caveat that rides with every grade_ok this table publishes.
DEM_2017_FLOWN = (date(2017, 5, 3), date(2017, 7, 26))  # acquisition window, frozen
# Frozen request constants. The server default matches RSP_NearestNeighbor today, but
# bilinear moves values by up to 0.342 m — a third of the water threshold — so a rebuild
# gate cannot rest on a server default.
INTERPOLATION = "RSP_NearestNeighbor"
WKID = 4326
BATCH = 500
US_SURVEY_FT = 3.280833333  # NOT 3.28084 (international foot); the map's canonical unit
RING_M, RING_N = 15.0, 8    # the doorway-scale octagon: 8 points on a 15 m ring
EPOCH_DELTA_M = 2.0         # |2017 - 2014| above this flags the row
ELEV_FLOOR_M = -1.0         # 2017 below this flags the row
GEOD = Geod(ellps="WGS84")

# ---- DEP stormwater (9i7c-xyvv): File-Geodatabase-only, read once through DuckDB spatial ----
SW_ZIP_URL = ("https://data.cityofnewyork.us/api/views/9i7c-xyvv/files/"
              "6ce7b252-a38c-47ae-a823-680f443227e5?download=true")
SW_ZIP = "NYCFloodStormwaterFloodMaps_2026-08-23.zip"
SW_ZIP_SHA256 = "5effe9bcca896660f44a5e50c348ab4ebf7550ff3c764ef77f06d775f0c010f5"
SW_SCENARIO = ("NYCFloodStormwaterFloodMaps/NYC Stormwater Flood Map - Moderate Flood "
               "(2.13 inches per hr) with Current Sea Levels/NYC_Stormwater_Flood_Map_Moderate_"
               "Flood_2_13_inches_per_hr_with_Current_Sea_Levels.gdb")
SW_CATEGORY = {1: "nuisance", 2: "deep"}  # the FGDB's own coded domain (its data dictionary)
# The fourth level. DEP's exclusion mask is NOT in the geodatabase — but unlike the flood
# polygons it IS a queryable FeatureServer, so "not analyzed" never has to be imputed to
# "analyzed, no flooding". 16,856 PLUTO lots: rail lines and their buffers, large lots,
# open space, LTCP boundary gaps.
SW_MASK_URL = ("https://services.arcgis.com/at3rDjch5X7i9Bag/arcgis/rest/services/"
               "Area_not_included_in_analysis/FeatureServer/1/query")
SW_MASK_PAGE = 2000
SW_CRS = "EPSG:2263"  # the FGDB's own CRS (NY Long Island ftUS): every area is computed here
TO_SW = Transformer.from_crs("EPSG:4326", SW_CRS, always_xy=True)

SRC_ASOF = date(2026, 8, 23)  # snapshot date; names the snapshot files
FEATURES_FROZEN = datetime(2026, 8, 23, tzinfo=timezone.utc)
TS = pa.timestamp("us", tz="UTC")

# Frozen real-data counts, asserted blocking on the real build (tests pass expect=None).
# entrance_flagged is the service-drift canary: 41 was measured over all 2,120 entrances on
# 2026-08-22, so any move means the DEM service republished under us and every elevation in
# this table needs re-reading. The bus-stop numbers were measured here at first full build
# (the design's 4/4,557 was a sample, not the 13,370-stop universe).
# bus_stop_flagged/elev_null/no_fallback measured here at first full build 2026-08-23: the
# design's 4/4,557 came from a sample that held no out-of-city stops, and 61 of the 89
# flagged stops are exactly that — MTA Bus Company routes crossing into Nassau, outside the
# NYC DEM footprint entirely (60 of them have no ring15_med fallback either).
EXPECT = {"rows": 15490, "entrance": 2120, "bus_stop": 13370, "entrance_flagged": 41,
          "bus_stop_flagged": 89, "elev_null": 61, "no_fallback": 60}
# Six frozen 2017 samples, measured at first full build. The count canary catches a
# service that moved its QC-relevant values; these catch one that silently changed
# interpolation, datum or raster without moving a single flag.
ELEV_PROBE = {
    "ent:328:40.712685:-74.011952": -10.488167763,  # WTC Cortlandt, the 2017 construction pit
    "ent:519:40.519668:-74.228684": 1.344167948,    # Richmond Valley, the one true low entrance
    "ent:146:40.852930:-73.937430": 76.80960083,    # 181 St, the highest entrance
    "ent:100:40.706527:-73.952617": 7.629144192,    # Hewes St
    "bus:100014": 44.68062973,                      # Bedford Pk Blvd/Grand Concourse
    "bus:200620": 106.975654602,                    # Arlo Rd/Grymes Hill, the highest stop
}


def ring_points(lon: float, lat: float) -> list[tuple[float, float]]:
    """The 8-point 15 m octagon around one asset — the relief neighbourhood a doorway
    actually drains into. Hex-grain anomaly carries no doorway signal (measured: p50
    within-cell relief 2.6 m), which is why the ring exists at all."""
    out = []
    for k in range(RING_N):
        x, y, _ = GEOD.fwd(lon, lat, k * 360.0 / RING_N, RING_M)
        out.append((x, y))
    return out


def parse_samples(payload: dict, n: int) -> list[float | None]:
    """One getSamples response -> n values, NULL where the service returned nothing.

    Responses are keyed by within-batch `locationId` and out-of-footprint points are
    SILENTLY OMITTED (their locationIds skip) — this, not dedupe, is what produced the
    933-of-1000 return that first looked like truncation. Join on locationId, never on
    coordinates: ref/assets keeps 9 shared doorways as separate rows at identical coords,
    so a coordinate join would fan samples and erase the NoData diagnostic. `value` arrives
    as a JSON string."""
    if "error" in payload:
        raise RuntimeError(f"getSamples error: {payload['error']}")
    out: list[float | None] = [None] * n
    for s in payload["samples"]:
        i = s["locationId"]
        if not 0 <= i < n:
            raise RuntimeError(f"locationId {i} outside a batch of {n}")
        out[i] = float(s["value"])
    return out


def post_samples(service: str, points: list[tuple[float, float]]) -> dict:
    geometry = json.dumps({"points": [[lon, lat] for lon, lat in points],
                           "spatialReference": {"wkid": WKID}})
    body = urllib.parse.urlencode({
        "geometry": geometry, "geometryType": "esriGeometryMultipoint",
        "returnFirstValueOnly": "true", "interpolation": INTERPOLATION, "f": "json"}).encode()
    url = ELEV_URL.format(service=service)
    for attempt in range(3):  # ~310 POSTs in one run: a transient failure must not cost the run
        try:
            with urllib.request.urlopen(urllib.request.Request(url, body), timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError:
            raise  # a batch entirely outside the raster hard-400s; retrying only wastes 6 s
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == 2:
                raise
            print(f"  retry {attempt + 1}: {exc!r}", file=sys.stderr, flush=True)
            time.sleep(2 * (attempt + 1))
    raise AssertionError("retry loop fell through")


def sampled_at(points: list[tuple[float, float]]) -> str:
    """The identity of a sampling run: the exact coordinates asked for, plus the request
    constants that decide what comes back. A snapshot is only reusable for the same one."""
    h = hashlib.sha1(repr((INTERPOLATION, WKID, BATCH)).encode())
    for lon, lat in points:
        h.update(f"{lon:.7f},{lat:.7f};".encode())
    return h.hexdigest()


def sample(root: Path, service: str, tag: str,
           points: list[tuple[float, float]]) -> list[float | None]:
    """Sample one service at every point, snapshotting the raw responses. Fetch only when
    the snapshot is missing: a present snapshot means the build never calls the API.

    The snapshot is bound to the coordinates and constants it was taken under, and refuses
    to answer for any others. Without that, a registry rebuild that MOVES an asset without
    changing the asset_id set — a re-pinned bus Pick shifts a cross-feed mean, and ticket
    01's key-diff calls that "moved", not "added" — would republish the old elevations under
    a features_version chained to the new assets_version, which is the exact reciprocal of
    01's orphan-is-failure contract. Same for the frozen interpolation: flipping it to
    bilinear moves values up to 0.342 m, and a stale snapshot would hide that behind a
    changed version stamp."""
    path = root / "snapshots" / "elevation" / f"{service}_{tag}_{SRC_ASOF}.json"
    if path.exists():
        snap = json.loads(path.read_text())
        if snap.get("sampled_at") != sampled_at(points):
            raise RuntimeError(
                f"{path.name} was taken at different coordinates or request constants than this "
                f"build asks for — re-sample (delete it and rerun) rather than publish stale "
                f"elevations under a fresh features_version")
    else:
        batches = []
        for off in range(0, len(points), BATCH):
            batches.append({"offset": off, "response": post_samples(service, points[off:off + BATCH])})
            print(f"  {service}/{tag}: {min(off + BATCH, len(points))}/{len(points)}", flush=True)
        snap = {"service": service, "tag": tag, "asof": str(SRC_ASOF), "n_points": len(points),
                "sampled_at": sampled_at(points),
                "constants": {"interpolation": INTERPOLATION, "wkid": WKID, "batch": BATCH,
                              "returnFirstValueOnly": True},
                "batches": batches}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")  # never leave a half-written snapshot
        tmp.write_text(json.dumps(snap))
        tmp.replace(path)
    out: list[float | None] = []
    for b in snap["batches"]:
        if b["offset"] != len(out):  # the batch_offset half of the join, asserted
            raise RuntimeError(f"{path.name}: batch offset {b['offset']} after {len(out)} samples")
        out += parse_samples(b["response"], min(BATCH, len(points) - b["offset"]))
    if len(out) != len(points):
        raise RuntimeError(f"{path.name}: {len(out)} samples for {len(points)} points")
    return out


def grade_ok(elev_2017: float | None, elev_2014: float | None) -> bool:
    """The one QC boolean, from frozen constants; reasons stay recoverable from the raw
    columns in the same row. NoData on either epoch flags the row (it is never a build
    failure, only a counted NULL). Known blind class: cross-epoch agreement is not
    correctness — at Kings Hwy both epochs hold the same el deck, so one Station House row
    passes QC at a wrong-high grade (a named 08 obligation)."""
    if elev_2017 is None or elev_2014 is None:
        return False
    return abs(elev_2017 - elev_2014) <= EPOCH_DELTA_M and elev_2017 >= ELEV_FLOOR_M


# ---- stormwater ----------------------------------------------------------------


def nyc_study_area(root: Path) -> list:
    """DEP modelled the city; the registry's own definition of the city is the non-EWR taxi
    zones (the same oracle ref/assets uses for cells_scored), in the stormwater CRS."""
    z = ref.read_ref(root, "zones", ["zone_id", "geometry"])
    return [reproject(valid(shapely.from_wkb(g)))
            for zid, g in zip(z["zone_id"], z["geometry"]) if zid != ref.EWR_ZONE_ID]


def stormwater_zip(root: Path) -> Path:
    """The 33.8 MB DEP geodatabase, fetched once and pinned by digest. Stays under
    snapshots/ (never the archive root): DEP is fetch-and-use, rehosting is barred. The
    date is in the name and the sha256 is checked on every use, so a DEP republish under
    the same URL can never quietly become the thing src_asof already claims to name."""
    path = root / "snapshots" / "stormwater" / SW_ZIP
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {SW_ZIP_URL}", flush=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(fetch(SW_ZIP_URL, timeout=600))
        tmp.replace(path)
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    if got != SW_ZIP_SHA256:
        raise RuntimeError(f"{path.name}: sha256 {got} != the pinned {SW_ZIP_SHA256} — DEP "
                           f"republished, so re-measure the counts rather than rebuild on it")
    return path


def flood_parts(root: Path) -> dict[str, list]:
    """The Moderate-current scenario's two flood classes as EPSG:2263 polygon parts, read
    ONCE through DuckDB spatial's OpenFileGDB driver — in place, through /vsizip/, no
    unzip and no new dependency. The layer is two MultiPolygons (Flooding_Category 1 and
    2), 25k parts between them."""
    from raincheck.duck import connect

    con = connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    rows = con.execute("SELECT Flooding_Category, ST_AsWKB(ST_Force2D(Shape)) FROM ST_Read(?)",
                       [f"/vsizip/{stormwater_zip(root)}/{SW_SCENARIO}"]).fetchall()
    con.close()
    out: dict[str, list] = {name: [] for name in SW_CATEGORY.values()}
    for code, wkb in rows:
        if code not in SW_CATEGORY:
            raise RuntimeError(f"unknown Flooding_Category {code} (expected {SW_CATEGORY})")
        out[SW_CATEGORY[code]] += list(shapely.get_parts(valid(shapely.from_wkb(bytes(wkb)))))
    if not all(out.values()):
        raise RuntimeError(f"stormwater scenario missing a category: "
                           f"{ {k: len(v) for k, v in out.items()} }")
    return out


def valid(geom):
    return geom if geom.is_valid else shapely.make_valid(geom)


def mask_polygons(root: Path) -> list:
    """DEP's "Area not included in analysis" as EPSG:2263 polygons — the fourth level.
    Unlike the flood extents (FGDB-only, no queryable service anywhere) the mask IS a
    queryable FeatureServer, so "not analyzed" is measured rather than imputed. Paged; the
    page sum is checked against the service's own count, because a silent truncation here
    would read downstream as "analyzed, no flooding"."""
    d = root / "snapshots" / "stormwater"
    manifest = d / f"mask_{SRC_ASOF}.json"
    if not manifest.exists():
        d.mkdir(parents=True, exist_ok=True)
        count = int(json.loads(fetch(f"{SW_MASK_URL}?where=1%3D1&returnCountOnly=true&f=json"))["count"])
        pages = []
        for off in range(0, count, SW_MASK_PAGE):
            name = f"mask_{SRC_ASOF}_{off:05d}.json"
            print(f"  stormwater mask: {off}/{count}", flush=True)
            body = fetch(f"{SW_MASK_URL}?where=1%3D1&outFields=OBJECTID,notes&returnGeometry=true"
                         f"&geometryPrecision=6&f=geojson&orderByFields=OBJECTID"
                         f"&resultRecordCount={SW_MASK_PAGE}&resultOffset={off}")
            (d / (name + ".tmp")).write_bytes(body)
            (d / (name + ".tmp")).replace(d / name)
            pages.append(name)
        (d / (manifest.name + ".tmp")).write_text(json.dumps({"count": count, "pages": pages}))
        (d / (manifest.name + ".tmp")).replace(manifest)
    man = json.loads(manifest.read_text())
    out = []
    for name in man["pages"]:  # one page at a time: the whole mask is ~78 MB of GeoJSON
        for f in json.loads((d / name).read_text())["features"]:
            out.append(valid(shapely.from_geojson(json.dumps(f["geometry"]))))
    if len(out) != man["count"]:
        raise RuntimeError(f"stormwater mask: {len(out)} features for a declared {man['count']}")
    return [reproject(g) for g in out]


def fetch(url: str, timeout: int = 120) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def reproject(geom):
    """EPSG:4326 -> the stormwater CRS. Every area and containment test runs in 2263, so
    the big flood polygons are never moved and no area is computed in degrees."""
    return shapely.transform(
        geom, lambda c: np.column_stack(TO_SW.transform(c[:, 0], c[:, 1])))


def categorize(points: list, parts: dict[str, list], study_area: list) -> list[str]:
    """Four levels, never imputed: deep / nuisance / not-analyzed / analyzed-none.

    A point inside both a flood polygon and the exclusion mask is reported as flooded — the
    model plainly ran there — and the mask only ever answers for points no flood class
    claims. A point outside DEP's study area altogether is not-analyzed too: the mask is a
    PLUTO layer that stops at the city line, so 72 MTA Bus Company stops in Nassau would
    otherwise fall through the default and be published as "DEP modelled here and found no
    flooding" — the one imputation this encoding exists to forbid."""
    tree = STRtree(study_area)
    out = ["analyzed-none" if any(study_area[k].covers(pt) for k in tree.query(pt))
           else "not-analyzed" for pt in points]
    for name in ("not-analyzed", "nuisance", "deep"):  # later classes overwrite earlier
        tree = STRtree(parts[name])
        for i, pt in enumerate(points):
            if any(parts[name][k].covers(pt) for k in tree.query(pt)):
                out[i] = name
    return out


def area_shares(cells: list, parts: dict[str, list]) -> dict[str, list[float]]:
    """Per-Cell area share per class. Within a class the parts are disjoint (the FGDB's own
    MultiPolygons; the mask is unioned first), so summing per-part intersections is exact —
    and a sum meaningfully above 1 means that stopped being true, which fails the build
    instead of publishing a "share" nobody can read as a fraction. A Cell wholly inside one
    class still lands a couple of ULPs over, so the last hair is clamped."""
    out = {}
    for name, geoms in parts.items():
        tree = STRtree(geoms)
        shares = []
        for cell in cells:
            share = sum(geoms[k].intersection(cell).area for k in tree.query(cell)) / cell.area
            if share > 1 + 1e-6:
                raise RuntimeError(f"{name}: area share {share} over 1 — the parts overlap")
            shares.append(min(1.0, share))
        out[name] = shares
    return out


# ---- the build -----------------------------------------------------------------


def point_assets(root: Path) -> list[dict]:
    t = pq.read_table(root / "ref" / "assets", columns=["asset_id", "kind", "lon", "lat", "cell"])
    rows = [r for r in t.to_pylist() if r["kind"] in ("entrance", "bus_stop")]
    return sorted(rows, key=lambda r: r["asset_id"])


def write(root: Path, name: str, table: pa.Table) -> None:
    out = root / "silver" / name / "part-00000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out, compression="zstd")
    print(f"silver/{name}: {table.num_rows} rows", flush=True)


def features_version(root: Path) -> str:
    """sha1 over the sorted feature rows + assets_version + the frozen constants +
    the stormwater snapshot's bytes. Structural, not clerical: a moved asset, a
    republished DEM, a re-cut stormwater snapshot or a changed threshold all change it.
    Recomputed on demand, so the table's bytes stay version-free (the ref precedent)."""
    t = pq.read_table(root / "silver" / "asset_features",
                      columns=["asset_id", "elev_2017_m", "elev_2014_m", "ring15_min_m",
                               "ring15_med_m", "stormwater_cat"])
    fmt = lambda v: "NULL" if v is None else f"{v:.4f}"  # noqa: E731 — pinned float formatting
    h = hashlib.sha1()
    for r in sorted(t.to_pylist(), key=lambda r: r["asset_id"]):
        h.update(repr((r["asset_id"], fmt(r["elev_2017_m"]), fmt(r["elev_2014_m"]),
                       fmt(r["ring15_min_m"]), fmt(r["ring15_med_m"]),
                       r["stormwater_cat"])).encode())
    # the stormwater snapshot by its pinned digest, never by fetching it: a version stamp a
    # consumer calls must not download 33.8 MB from DEP as a side effect
    if not (root / "snapshots" / "stormwater" / SW_ZIP).exists():
        raise RuntimeError(f"{SW_ZIP} is missing under {root}/snapshots/stormwater — "
                           f"features_version names the snapshot the table was built from")
    h.update(repr((ref.assets_version(root), EPOCH_DELTA_M, ELEV_FLOOR_M, US_SURVEY_FT,
                   INTERPOLATION, RING_M, RING_N, SW_ZIP_SHA256)).encode())
    return h.hexdigest()


def build(root: Path, expect: dict | None = EXPECT) -> None:
    assets = point_assets(root)
    coords = [(r["lon"], r["lat"]) for r in assets]
    ring = [p for lon, lat in coords for p in ring_points(lon, lat)]
    e17 = sample(root, DEM_2017, "points", coords)
    e14 = sample(root, DEM_2014, "points", coords)
    e17_ring = sample(root, DEM_2017, "ring15", ring)

    sw_parts = flood_parts(root)
    # The mask minus the flood extents, so the two classes never claim the same ground: the
    # 0.19%-of-flood-area overlap is resolved toward flooded, exactly as it is point-side.
    flooded = shapely.union_all(sw_parts["deep"] + sw_parts["nuisance"])
    mask = shapely.union_all(mask_polygons(root)).difference(flooded)
    sw_parts["not-analyzed"] = list(shapely.get_parts(mask))
    print(f"stormwater parts: { {k: len(v) for k, v in sw_parts.items()} }", flush=True)
    study_area = nyc_study_area(root)
    cats = categorize([shapely.Point(*TO_SW.transform(lon, lat)) for lon, lat in coords],
                      sw_parts, study_area)

    rows = []
    for i, a in enumerate(assets):
        vals = [v for v in e17_ring[i * RING_N:(i + 1) * RING_N] if v is not None]
        m17 = e17[i]
        rows.append({
            "asset_id": a["asset_id"], "elev_2017_m": m17, "elev_2014_m": e14[i],
            "elev_ft": None if m17 is None else m17 * US_SURVEY_FT,
            "ring15_min_m": min(vals) if vals else None,
            "ring15_med_m": statistics.median(vals) if vals else None,
            # how many of the 8 answered: a half-ring median is not the octagon 08 asked
            # for, and it is the fallback grade for exactly the assets the raster clips
            "ring15_n": len(vals),
            "grade_ok": grade_ok(e17[i], e14[i]), "stormwater_cat": cats[i],
            "cell": a["cell"], "src_asof": SRC_ASOF, "frozen_at": FEATURES_FROZEN})

    kinds = {a["asset_id"]: a["kind"] for a in assets}
    got = {"rows": len(rows),
           "entrance": sum(k == "entrance" for k in kinds.values()),
           "bus_stop": sum(k == "bus_stop" for k in kinds.values()),
           "entrance_flagged": sum(not r["grade_ok"] and kinds[r["asset_id"]] == "entrance"
                                   for r in rows),
           "bus_stop_flagged": sum(not r["grade_ok"] and kinds[r["asset_id"]] == "bus_stop"
                                   for r in rows),
           "elev_null": sum(r["elev_2017_m"] is None for r in rows),
           # a flagged row falls back to ring15_med; a row whose ring is NoData too has no
           # fallback at all and is 08's problem to price, so the count is frozen, not warned
           "no_fallback": sum(not r["grade_ok"] and r["ring15_med_m"] is None for r in rows)}
    by_cat = {c: cats.count(c) for c in sorted(set(cats))}
    print(f"silver/asset_features: {got}, stormwater={by_cat}", flush=True)
    if expect:
        bad = {k: (got[k], v) for k, v in expect.items() if v is not None and got[k] != v}
        if bad:  # entrance_flagged moving is the service-drift canary, not a count nit
            raise RuntimeError(f"frozen count mismatch (got, expected): {bad}")
        by_id = {r["asset_id"]: r for r in rows}
        drift = {a: (by_id[a]["elev_2017_m"], v) for a, v in ELEV_PROBE.items()
                 if by_id[a]["elev_2017_m"] is None
                 or abs(by_id[a]["elev_2017_m"] - v) > 1e-6}
        if drift:
            raise RuntimeError(f"frozen elevation drift (got, expected): {drift}")

    cells = ref.read_ref(root, "cells", ["cell", "geometry"])
    geoms = [reproject(shapely.from_wkb(g)) for g in cells["geometry"]]
    shares = area_shares(geoms, sw_parts)
    # Same rule as the point grain: ground outside the study area was never modelled either,
    # and DEP's own mask stops at the city line. Both terms are disjoint from the flood
    # classes (mask and flood alike live inside the study area), so the shares still partition.
    nyc = shapely.union_all(study_area)
    shares["not-analyzed"] = [min(1.0, m + 1.0 - min(1.0, cell.intersection(nyc).area / cell.area))
                              for m, cell in zip(shares["not-analyzed"], geoms)]

    schema = pa.schema([("asset_id", pa.string()), ("elev_2017_m", pa.float64()),
                        ("elev_2014_m", pa.float64()), ("elev_ft", pa.float64()),
                        ("ring15_min_m", pa.float64()), ("ring15_med_m", pa.float64()),
                        ("ring15_n", pa.int8()), ("grade_ok", pa.bool_()),
                        ("stormwater_cat", pa.string()), ("cell", pa.int64()),
                        ("src_asof", pa.date32()), ("frozen_at", TS)])
    cell_schema = pa.schema([("cell", pa.int64()), ("share_deep", pa.float64()),
                             ("share_nuisance", pa.float64()),
                             ("share_not_analyzed", pa.float64()),
                             ("src_asof", pa.date32()), ("frozen_at", TS)])
    # both tables land after every gate has passed: a half-written pair is a mismatched pair
    write(root, "asset_features", pa.Table.from_pylist(rows, schema=schema))
    write(root, "cell_stormwater", pa.Table.from_pydict(
        {"cell": cells["cell"], "share_deep": shares["deep"],
         "share_nuisance": shares["nuisance"], "share_not_analyzed": shares["not-analyzed"],
         "src_asof": [SRC_ASOF] * len(cells["cell"]),
         "frozen_at": [FEATURES_FROZEN] * len(cells["cell"])}, schema=cell_schema))
    print(f"features_version = {features_version(root)}", flush=True)


def main() -> None:
    build(data_root())


if __name__ == "__main__":
    main()
