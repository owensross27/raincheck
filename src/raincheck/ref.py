"""`make ref` (ticket 02 / spec B, D): every lookup the pipeline joins at read, built whole
under <root>/ref and byte-identical on rebuild (stable part names, sorted rows, pyarrow or
a single sorted Spark partition).

Tables  grids (one row per precip grid), cells (H3 res-8, Sedona, GeoParquet 1.1),
        zones (TLC taxi zones, EPSG:2263 -> 4326 once, Times Square axis gate),
        cell_zone (centroid point-in-polygon), cell_pixel (area-weighted Pixel shares per
        Cell for both grids, shapely + pyproj in EPSG:32618), calendar (one row per slice
        service day), picks (the static zips the archiver captures, registered as Picks).
Inputs  <root>/archive/precip/aorc/coords.npz (fetched once from the cloud Zarr),
        <root>/ref/src/taxi_zones.zip (downloaded once from TLC), <root>/archive/static.

Run: make ref   (python -m raincheck.ref)
"""
import csv
import hashlib
import io
import json
import shutil
import sys
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from pyproj import Transformer
from shapely.strtree import STRtree

from raincheck.paths import data_root

AORC_STORE = "s3://noaa-nws-aorc-v1-1-1km/2021.zarr"
TAXI_URL = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zones.zip"
BBOX = (-74.30, 40.45, -73.65, 40.95)  # lon_min, lat_min, lon_max, lat_max
UTM = Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)
# MRMS grid tuple as read from the GRIB2 headers 2026-08-16 (research 08): Ni, Nj,
# first/last lat, first/last lon (0-360), di, dj, jScansPositively. Ticket 11's ingest
# asserts the live file still matches.
MRMS_TUPLE = (7000, 3500, 54.995, 20.005, 230.005, 299.995, 0.01, 0.01, 0)
MRMS_FROZEN = datetime(2026, 8, 16, tzinfo=timezone.utc)  # measurement date of the tuple
MRMS_URL = "s3://noaa-mrms-pds/CONUS/MultiSensor_QPE_01H_Pass2_00.00"

# ref/calendar facts (verified 2026-08-22 against the NYC DOE calendars and the UN GA
# session pages; research 10 pins the two first days of school).
WINDOWS = ((date(2021, 8, 16), date(2021, 10, 15)), (date(2023, 9, 1), date(2023, 10, 31)))
SCHOOL_FIRST_DAY = {2021: date(2021, 9, 13), 2023: date(2023, 9, 7)}
SCHOOL_CLOSED = {date(2021, 9, 16), date(2021, 10, 11),  # Yom Kippur, Indigenous Peoples' Day
                 date(2023, 9, 25), date(2023, 10, 9)}   # Yom Kippur, Italian Heritage/IPD
HOLIDAYS = {date(2021, 9, 6), date(2021, 10, 11), date(2023, 9, 4), date(2023, 10, 9)}
UNGA = ((date(2021, 9, 21), date(2021, 9, 27)), (date(2023, 9, 19), date(2023, 9, 26)))

TS = pa.timestamp("us", tz="UTC")

# ---- ref/assets (flood-build 01): every flood Unit and Carrier in one registry ----
# Score Units: complex, bus_stop, cell. Carriers (located and aggregated, never scored
# independently): station, entrance. Design: flood wayfinder ticket 06.
SODA_BASE = "https://data.ny.gov/resource"
STATIONS_SNAPSHOT = "39hk-dx4f_2026-08-22.json"   # MTA subway stations
ENTRANCES_SNAPSHOT = "i9wp-a4ja_2026-08-22.json"  # MTA subway entrances and exits
SNAPSHOT_ASOF = date(2026, 8, 22)
ASSETS_FROZEN = datetime(2026, 8, 22, tzinfo=timezone.utc)
EWR_ZONE_ID = 1  # Newark Airport, the one non-NYC taxi zone: excluded from cells_scored
BUS_PICKS = {  # the static zips behind silver/stops, pinned by sha1 (five feeds
    # 2026-06-23, staten_island 2026-07-28); make ref never re-reads the zips for stops
    "bronx": "1e05b66603f781491ba2f9e6c3a012ed68e599f3",
    "brooklyn": "c05b9aefc277ec4e766c07ea5ea9c26faa7bcbfc",
    "busco": "3d84ded191bcc80d82a6653655b1064fc495bb6a",
    "manhattan": "e19457c845680d939472dfb801c1a35bed1479fd",
    "queens": "1382a2eba797e7257b197a360e0396ac5e2ed812",
    "staten_island": "2df7eee4c96825d3418ba604958122875c6182ea",
}
SUBWAY_PICK = "5116d5c7bc4afeddf53f34dcbc2c29363e84b2a2"  # subway static 2026-08-07
# frozen real-data counts, asserted blocking on the real build (tests pass expect=None);
# cells_scored measured 1,351 on the first real build 2026-08-22
ASSETS_EXPECT = {"complex": 445, "station": 496, "entrance": 2120, "bus_stop": 13370,
                 "cell": 4113, "total": 20544, "cells_scored": 1351}


def write(root: Path, name: str, table: pa.Table) -> None:
    out = root / "ref" / name / "part-00000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out, compression="zstd")
    print(f"ref/{name}: {table.num_rows} rows", flush=True)


def spark_write(root: Path, name: str, df) -> None:
    """One sorted GeoParquet part moved from .staging to a stable name (byte-identical rebuilds)."""
    staging = root / ".staging" / name
    df.write.format("geoparquet").mode("overwrite").save(str(staging))
    out = root / "ref" / name / "part-00000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    (part,) = staging.glob("part-*.parquet")
    shutil.move(part, out)
    shutil.rmtree(staging)
    print(f"ref/{name}: wrote {out.name}", flush=True)


def aorc_coords(root: Path) -> tuple[np.ndarray, np.ndarray, datetime]:
    """The stored Zarr coordinate arrays (never arange), fetched once from the cloud store."""
    npz = root / "archive" / "precip" / "aorc" / "coords.npz"
    if not npz.exists():
        import xarray as xr  # heavy; only on first fetch

        print(f"fetching AORC coordinate arrays from {AORC_STORE}", flush=True)
        ds = xr.open_zarr(AORC_STORE, storage_options={"anon": True}, consolidated=True)
        npz.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(npz, longitude=ds["longitude"].values, latitude=ds["latitude"].values)
    z = np.load(npz)
    frozen = datetime.fromtimestamp(npz.stat().st_mtime, tz=timezone.utc)
    return z["longitude"], z["latitude"], frozen


def build_grids(root: Path) -> None:
    lon, lat, frozen = aorc_coords(root)
    ni, nj = MRMS_TUPLE[0], MRMS_TUPLE[1]
    rows = {
        "grid_id": ["aorc", "mrms"],
        "source_url": [AORC_STORE.rsplit("/", 1)[0], MRMS_URL],
        "origin_lon": [float(lon[0]), MRMS_TUPLE[4] - 360.0],
        "origin_lat": [float(lat[0]), MRMS_TUPLE[3]],
        "step_deg": [float(lon[1] - lon[0]), MRMS_TUPLE[6]],
        "nx": [lon.size, ni],
        "ny": [lat.size, nj],
        "registration": ["center", "center"],
        "coord_sha256": [hashlib.sha256(lon.tobytes() + lat.tobytes()).hexdigest(),
                         hashlib.sha256(repr(MRMS_TUPLE).encode()).hexdigest()],
        "frozen_at": [frozen, MRMS_FROZEN],
    }
    schema = pa.schema([("grid_id", pa.string()), ("source_url", pa.string()),
                        ("origin_lon", pa.float64()), ("origin_lat", pa.float64()),
                        ("step_deg", pa.float64()), ("nx", pa.int32()), ("ny", pa.int32()),
                        ("registration", pa.string()), ("coord_sha256", pa.string()),
                        ("frozen_at", TS)])
    write(root, "grids", pa.Table.from_pydict(rows, schema=schema))


def build_cells(root: Path, spark) -> None:
    bbox = f"ST_PolygonFromEnvelope({BBOX[0]}, {BBOX[1]}, {BBOX[2]}, {BBOX[3]})"
    df = spark.sql(f"""
        SELECT cell,
               ST_SetSRID(geom, 4326) AS geometry,
               ST_X(ST_Centroid(geom)) AS centroid_lon,
               ST_Y(ST_Centroid(geom)) AS centroid_lat
        FROM (SELECT cell, ST_H3ToGeom(array(cell))[0] AS geom
              FROM (SELECT DISTINCT explode(ST_H3CellIDs({bbox}, 8, false)) AS cell))
    """).coalesce(1).sortWithinPartitions("cell")
    spark_write(root, "cells", df)


def zones_shapefile(root: Path) -> Path:
    src = root / "ref" / "src"
    shp = next(src.rglob("taxi_zones.shp"), None)
    if shp is None:
        zip_path = src / "taxi_zones.zip"
        if not zip_path.exists():
            src.mkdir(parents=True, exist_ok=True)
            print(f"downloading {TAXI_URL}", flush=True)
            urllib.request.urlretrieve(TAXI_URL, zip_path)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(src / "taxi_zones")
        shp = next(src.rglob("taxi_zones.shp"))
    return shp.parent


def build_zones(root: Path, spark) -> None:
    (ts,) = spark.sql(
        "SELECT ST_AsText(ST_Transform(ST_Point(988267.1, 215436.9), 'EPSG:2263', 'EPSG:4326'))"
    ).first()
    x, y = map(float, ts.removeprefix("POINT (").removesuffix(")").split())
    if abs(x - -73.9855) > 1e-4 or abs(y - 40.7580) > 1e-4:  # axis gate, at ingest (09)
        raise RuntimeError(f"Times Square axis gate failed: {ts}")
    spark.read.format("shapefile").load(str(zones_shapefile(root))).createOrReplaceTempView("tz")
    df = spark.sql("""
        SELECT cast(LocationID AS smallint) AS zone_id, borough, zone AS zone_name,
               ST_SetSRID(ST_Transform(geometry, 'EPSG:2263', 'EPSG:4326'), 4326) AS geometry
        FROM tz
    """).coalesce(1).sortWithinPartitions("zone_id")
    spark_write(root, "zones", df)


def read_ref(root: Path, name: str, columns: list[str]) -> dict[str, list]:
    t = pq.read_table(root / "ref" / name, columns=columns)
    return {c: t.column(c).to_pylist() for c in columns}


def build_cell_zone(root: Path) -> None:
    zones = read_ref(root, "zones", ["zone_id", "borough", "geometry"])
    geoms = [shapely.from_wkb(g) for g in zones["geometry"]]
    tree = STRtree(geoms)
    cells = read_ref(root, "cells", ["cell", "centroid_lon", "centroid_lat"])
    zone_ids, boroughs = [], []
    for lon, lat in zip(cells["centroid_lon"], cells["centroid_lat"]):
        hits = [k for k in tree.query(shapely.Point(lon, lat)) if geoms[k].covers(shapely.Point(lon, lat))]
        zone_ids.append(zones["zone_id"][hits[0]] if hits else None)
        boroughs.append(zones["borough"][hits[0]] if hits else None)
    schema = pa.schema([("cell", pa.int64()), ("zone_id", pa.int16()), ("borough", pa.string())])
    write(root, "cell_zone", pa.Table.from_pydict(
        {"cell": cells["cell"], "zone_id": zone_ids, "borough": boroughs}, schema=schema))


def build_cell_pixel(root: Path) -> None:
    grids = read_ref(root, "grids", ["grid_id", "origin_lon", "origin_lat", "step_deg", "nx", "ny"])
    cells = read_ref(root, "cells", ["cell", "geometry"])
    out: list[tuple] = []
    for g in range(len(grids["grid_id"])):
        grid_id, lon0, lat0, step = (grids[c][g] for c in ("grid_id", "origin_lon", "origin_lat", "step_deg"))
        nx, ny = grids["nx"][g], grids["ny"][g]
        for cell, wkb in zip(cells["cell"], cells["geometry"]):
            poly = shapely.from_wkb(wkb)
            cell_xy = shapely.transform(poly, lambda c: np.column_stack(UTM.transform(c[:, 0], c[:, 1])))
            minx, miny, maxx, maxy = poly.bounds
            i_lo, i_hi = max(0, int((minx - lon0) / step) - 1), min(nx - 1, int((maxx - lon0) / step) + 2)
            j_lo, j_hi = max(0, int((miny - lat0) / step) - 1), min(ny - 1, int((maxy - lat0) / step) + 2)
            for i in range(i_lo, i_hi + 1):
                for j in range(j_lo, j_hi + 1):
                    px, py = lon0 + i * step, lat0 + j * step
                    corners_lon = np.array([px - step / 2, px + step / 2, px + step / 2, px - step / 2])
                    corners_lat = np.array([py - step / 2, py - step / 2, py + step / 2, py + step / 2])
                    pixel = shapely.Polygon(zip(*UTM.transform(corners_lon, corners_lat)))
                    w = cell_xy.intersection(pixel).area / cell_xy.area
                    if w > 0:
                        out.append((grid_id, cell, i, j, w))
    out.sort()
    schema = pa.schema([("grid_id", pa.string()), ("cell", pa.int64()),
                        ("i", pa.int16()), ("j", pa.int16()), ("weight", pa.float64())])
    write(root, "cell_pixel", pa.Table.from_pydict(
        {k: [r[n] for r in out] for n, k in enumerate(schema.names)}, schema=schema))


def build_calendar(root: Path) -> None:
    days = [w[0] + timedelta(n) for w in WINDOWS for n in range((w[1] - w[0]).days + 1)]
    school = [d.weekday() < 5 and d >= SCHOOL_FIRST_DAY[d.year] and d not in SCHOOL_CLOSED
              for d in days]
    unga = [any(a <= d <= b for a, b in UNGA) for d in days]
    schema = pa.schema([("service_date", pa.date32()), ("school_in_session", pa.bool_()),
                        ("holiday", pa.bool_()), ("unga_week", pa.bool_())])
    write(root, "calendar", pa.Table.from_pydict(
        {"service_date": days, "school_in_session": school,
         "holiday": [d in HOLIDAYS for d in days], "unga_week": unga}, schema=schema))


def gtfs_span(zip_path: Path) -> tuple[date | None, date | None, str | None]:
    """(earliest, latest) calendar date across calendar.txt + calendar_dates.txt, feed_version."""
    dates: list[str] = []
    version = None
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        if "calendar.txt" in names:
            for row in csv.DictReader(io.TextIOWrapper(z.open("calendar.txt"), "utf-8-sig")):
                dates += [row["start_date"].strip(), row["end_date"].strip()]
        if "calendar_dates.txt" in names:
            dates += [row["date"].strip()
                      for row in csv.DictReader(io.TextIOWrapper(z.open("calendar_dates.txt"), "utf-8-sig"))]
        if "feed_info.txt" in names:
            for row in csv.DictReader(io.TextIOWrapper(z.open("feed_info.txt"), "utf-8-sig")):
                version = row.get("feed_version", "").strip() or None
                break
    parsed = sorted(datetime.strptime(d, "%Y%m%d").date() for d in dates if d)
    return (parsed[0], parsed[-1], version) if parsed else (None, None, version)


def build_picks(root: Path) -> None:
    rows = []
    for zip_path in sorted((root / "archive" / "static").glob("*/*.zip")):
        try:
            earliest, latest, version = gtfs_span(zip_path)
            # the archiver names the zip by its Last-Modified date; the time of day is not kept
            published = datetime.strptime(zip_path.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (zipfile.BadZipFile, ValueError, KeyError) as exc:
            # the archiver writes zips non-atomically: a kill mid-write leaves a truncated file
            print(f"picks: skipping {zip_path} ({exc!r})", file=sys.stderr, flush=True)
            continue
        rows.append({
            "pick_id": hashlib.sha1(zip_path.read_bytes()).hexdigest(),
            "feed": zip_path.parent.name,
            "published": published,
            "feed_version": version,
            "earliest_calendar_date": earliest,
            "latest_calendar_date": latest,
            # ticket 09: the puller leaves a .tl.json sidecar next to Transitland zips
            "source": "transitland" if zip_path.with_name(zip_path.name + ".tl.json").exists() else "mta",
            "path": zip_path.relative_to(root).as_posix(),
        })
    rows.sort(key=lambda r: (r["feed"], r["published"]))
    schema = pa.schema([("pick_id", pa.string()), ("feed", pa.string()), ("published", TS),
                        ("feed_version", pa.string()), ("earliest_calendar_date", pa.date32()),
                        ("latest_calendar_date", pa.date32()), ("source", pa.string()),
                        ("path", pa.string())])
    write(root, "picks", pa.Table.from_pylist(rows, schema=schema))


def subway_snapshot(root: Path, name: str) -> list[dict]:
    """A pinned Socrata snapshot under archive/subway, fetched only when missing —
    a present snapshot means make ref never calls SODA."""
    path = root / "archive" / "subway" / name
    if not path.exists():
        url = f"{SODA_BASE}/{name.split('_')[0]}.json?$limit=5000"
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {url}", flush=True)
        urllib.request.urlretrieve(url, path)
    rows = json.loads(path.read_text())
    if len(rows) >= 5000:  # SODA truncates silently at $limit
        raise RuntimeError(f"{name}: {len(rows)} rows hit the $limit — snapshot truncated")
    return rows


def assets_version(root: Path) -> str:
    """sha1 over sorted (asset_id, kind, lat, lon) — the label_version chain ingredient."""
    t = pq.read_table(root / "ref" / "assets", columns=["asset_id", "kind", "lat", "lon"])
    h = hashlib.sha1()
    for row in sorted(zip(t.column("asset_id").to_pylist(), t.column("kind").to_pylist(),
                          t.column("lat").to_pylist(), t.column("lon").to_pylist())):
        h.update(repr(row).encode())
    return h.hexdigest()


def assets_key_diff(old: dict[str, tuple], new: dict[str, tuple]) -> dict[str, list[str]]:
    """The key-stability contract: what a rebuild added, removed, or moved."""
    return {"added": sorted(new.keys() - old.keys()),
            "removed": sorted(old.keys() - new.keys()),
            "moved": sorted(k for k in old.keys() & new.keys() if old[k] != new[k])}


def build_assets(root: Path, spark, bus_picks: dict[str, str] | None = None,
                 subway_pick: str | None = None, expect: dict | None = ASSETS_EXPECT) -> None:
    bus_picks = BUS_PICKS if bus_picks is None else bus_picks
    subway_pick = SUBWAY_PICK if subway_pick is None else subway_pick
    stations = subway_snapshot(root, STATIONS_SNAPSHOT)
    entrances = subway_snapshot(root, ENTRANCES_SNAPSHOT)
    sta_by_gtfs = {s["gtfs_stop_id"]: s for s in stations}
    if len(sta_by_gtfs) != len(stations):
        raise RuntimeError("stations snapshot: gtfs_stop_id not unique")

    def row(**kw) -> dict:
        base = dict.fromkeys(("name", "complex_id", "parent_asset_id", "gtfs_stop_id",
                              "daytime_routes", "line", "structure", "borough", "entrance_type",
                              "entry_allowed", "exit_allowed", "feeds", "pick_id", "src_asof"))
        return {**base, "scored": False, "frozen_at": ASSETS_FROZEN, **kw}

    rows = []
    for s in stations:
        rows.append(row(asset_id=f"sta:{s['gtfs_stop_id']}", kind="station", name=s["stop_name"],
                        lon=float(s["gtfs_longitude"]), lat=float(s["gtfs_latitude"]),
                        complex_id=s["complex_id"], parent_asset_id=f"stn:{s['complex_id']}",
                        gtfs_stop_id=[s["gtfs_stop_id"]], daytime_routes=s.get("daytime_routes"),
                        line=s.get("line"), structure=s.get("structure"),
                        borough=s.get("borough"), src_asof=SNAPSHOT_ASOF))
    by_cx: dict[str, list[dict]] = {}
    for s in stations:
        by_cx.setdefault(s["complex_id"], []).append(s)
    for cx, members in sorted(by_cx.items()):
        names = sorted({m["stop_name"] for m in members})
        boroughs = {m.get("borough") for m in members}
        rows.append(row(asset_id=f"stn:{cx}", kind="complex", name=" / ".join(names),
                        lon=sum(float(m["gtfs_longitude"]) for m in members) / len(members),
                        lat=sum(float(m["gtfs_latitude"]) for m in members) / len(members),
                        complex_id=cx, borough=boroughs.pop() if len(boroughs) == 1 else None,
                        scored=True, src_asof=SNAPSHOT_ASOF))
    for e in entrances:
        ids = [g.strip() for g in e.get("gtfs_stop_id", "").split(";") if g.strip()]
        missing = [g for g in ids if g not in sta_by_gtfs]
        if not ids or missing:
            raise RuntimeError(f"entrance gtfs_stop_id orphaned from stations: {missing or e}")
        # complex_id comes from the stations join, never the row's own field (10 misfiled rows)
        cxs = {sta_by_gtfs[g]["complex_id"] for g in ids}
        if len(cxs) != 1:
            raise RuntimeError(f"entrance maps to multiple complexes: {e}")
        cx = cxs.pop()
        lat, lon = float(e["entrance_latitude"]), float(e["entrance_longitude"])
        rows.append(row(asset_id=f"ent:{cx}:{lat:.6f}:{lon:.6f}", kind="entrance",
                        name=e["stop_name"], lon=lon, lat=lat, complex_id=cx,
                        parent_asset_id=f"stn:{cx}", gtfs_stop_id=ids,
                        entrance_type=e.get("entrance_type"), entry_allowed=e.get("entry_allowed"),
                        exit_allowed=e.get("exit_allowed"), src_asof=SNAPSHOT_ASOF))

    published = {r["pick_id"]: r["published"] for r in pq.read_table(root / "ref" / "picks").to_pylist()}
    per_stop: dict[str, list[tuple]] = {}
    for feed, pick in sorted(bus_picks.items()):
        t = pq.read_table(root / "silver" / "stops" / f"pick_id={pick}",
                          columns=["stop_id", "stop_name", "lon", "lat"])
        for sid, nm, lo, la in zip(*(t.column(c).to_pylist() for c in t.column_names)):
            per_stop.setdefault(sid, []).append((feed, pick, nm, lo, la))
    for sid, srcs in sorted(per_stop.items()):
        srcs.sort()  # by feed name; the lexicographically-first feed names the stop
        rows.append(row(asset_id=f"bus:{sid}", kind="bus_stop", name=srcs[0][2],
                        lon=sum(s[3] for s in srcs) / len(srcs),
                        lat=sum(s[4] for s in srcs) / len(srcs),
                        feeds=[s[0] for s in srcs], pick_id=[s[1] for s in srcs], scored=True,
                        src_asof=max(published[s[1]].date() for s in srcs)))

    if subway_pick:  # 1:1 against the pick's parent stations, zero orphans both ways
        with zipfile.ZipFile(root / pick_row_path(root, subway_pick)) as z:
            parents = {r["stop_id"].strip()
                       for r in csv.DictReader(io.TextIOWrapper(z.open("stops.txt"), "utf-8-sig"))
                       if r.get("location_type", "").strip() == "1"}
        if parents != set(sta_by_gtfs):
            raise RuntimeError(f"stations<->subway pick mismatch: pick-only="
                               f"{sorted(parents - set(sta_by_gtfs))} stations-only="
                               f"{sorted(set(sta_by_gtfs) - parents)}")

    # point -> Cell through the pipeline's own idiom; membership in ref/cells is blocking
    pdf = spark.createDataFrame([(r["asset_id"], r["lon"], r["lat"]) for r in rows],
                                "asset_id string, lon double, lat double")
    cell_of = dict(pdf.selectExpr("asset_id",
                                  "ST_H3CellIDs(ST_Point(lon, lat), 8, false)[0] AS cell").collect())
    cells = read_ref(root, "cells", ["cell", "geometry", "centroid_lon", "centroid_lat"])
    known = set(cells["cell"])
    for r in rows:
        r["cell"] = cell_of[r["asset_id"]]
    lost = sorted(r["asset_id"] for r in rows if r["cell"] not in known)
    if lost:
        raise RuntimeError(f"assets outside ref/cells (fail, never null): {lost[:10]}")

    # cells_scored: intersects a non-EWR taxi Zone, UNION holds a scored point asset
    zones = read_ref(root, "zones", ["zone_id", "geometry"])
    zgeoms = [shapely.from_wkb(g) for zid, g in zip(zones["zone_id"], zones["geometry"])
              if zid != EWR_ZONE_ID]
    tree = STRtree(zgeoms)
    scored_cells = {r["cell"] for r in rows if r["scored"]}
    for cell, wkb in zip(cells["cell"], cells["geometry"]):
        poly = shapely.from_wkb(wkb)
        if any(zgeoms[k].intersects(poly) for k in tree.query(poly)):
            scored_cells.add(cell)
    for cell, clon, clat in zip(cells["cell"], cells["centroid_lon"], cells["centroid_lat"]):
        rows.append(row(asset_id=f"cell:{cell:x}", kind="cell", lon=clon, lat=clat,
                        cell=cell, scored=cell in scored_cells))

    # coverage gates: both precip crosswalks reach every scored Cell, and the Cells whose
    # AORC Pixels never report stay out of the score universe (skipped where absent: the
    # fixture roots; the real root has both)
    if (root / "ref" / "cell_pixel").exists():
        cp = pq.read_table(root / "ref" / "cell_pixel", columns=["grid_id", "cell"])
        for grid in ("aorc", "mrms"):
            covered = {c for g, c in zip(cp.column("grid_id").to_pylist(),
                                         cp.column("cell").to_pylist()) if g == grid}
            gap = sorted(scored_cells - covered)
            if gap:
                raise RuntimeError(f"cells_scored not covered by the {grid} crosswalk: {gap[:5]}")
    else:
        print("ref/assets: cell_pixel absent, crosswalk coverage gate SKIPPED", flush=True)
    pch = root / "silver" / "precip_cell_hourly" / "src=aorc"
    if pch.exists():
        import duckdb  # heavy path only where the table exists

        (live,) = duckdb.connect().execute(
            "SELECT coalesce(list(cell), []) FROM (SELECT cell FROM read_parquet(?) "
            "GROUP BY cell HAVING count(mm_1h) > 0)", [f"{pch}/*/*.parquet"]).fetchone()
        # absent-entirely and present-but-all-NULL are both permanently-NULL for scoring
        bad = sorted(scored_cells - set(live))
        if bad:
            raise RuntimeError(f"permanently-NULL AORC cells inside cells_scored: {bad[:5]}")
    else:
        print("ref/assets: precip_cell_hourly absent, permanently-NULL gate SKIPPED", flush=True)

    ids = [r["asset_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("asset_id not unique")
    if any(not r["name"] for r in rows if r["kind"] != "cell"):
        raise RuntimeError("NULL name outside cell rows")
    counts = {k: sum(r["kind"] == k for r in rows) for k in
              ("complex", "station", "entrance", "bus_stop", "cell")}
    print(f"ref/assets: {counts}, cells_scored={len(scored_cells)}", flush=True)
    if expect:
        got = {**counts, "total": len(rows), "cells_scored": len(scored_cells)}
        bad = {k: (got[k], v) for k, v in expect.items() if v is not None and got[k] != v}
        if bad:
            raise RuntimeError(f"frozen count mismatch (got, expected): {bad}")

    out = root / "ref" / "assets" / "part-00000.parquet"
    new_keys = {r["asset_id"]: (r["lat"], r["lon"]) for r in rows}
    if out.exists():  # the key-stability contract
        t = pq.read_table(out, columns=["asset_id", "lat", "lon"])
        old_keys = {a: (la, lo) for a, la, lo in zip(t.column("asset_id").to_pylist(),
                                                     t.column("lat").to_pylist(),
                                                     t.column("lon").to_pylist())}
        diff = assets_key_diff(old_keys, new_keys)
        print(f"ref/assets key-diff: +{len(diff['added'])} -{len(diff['removed'])} "
              f"~{len(diff['moved'])}", flush=True)
        for tbl in ("gold/flood_labels", "silver/asset_features"):
            if diff["removed"] and (root / tbl).exists():
                refd = set(pq.read_table(root / tbl, columns=["asset_id"])
                           .column("asset_id").to_pylist())
                orphans = sorted(refd & set(diff["removed"]))
                if orphans:
                    raise RuntimeError(f"rebuild would orphan {tbl} rows: {orphans[:10]}")

    order = ("asset_id", "kind", "name", "lon", "lat", "cell", "complex_id", "parent_asset_id",
             "gtfs_stop_id", "daytime_routes", "line", "structure", "borough", "entrance_type",
             "entry_allowed", "exit_allowed", "feeds", "pick_id", "scored", "src_asof", "frozen_at")
    schema = ("asset_id string, kind string, name string, lon double, lat double, cell long, "
              "complex_id string, parent_asset_id string, gtfs_stop_id array<string>, "
              "daytime_routes string, line string, structure string, borough string, "
              "entrance_type string, entry_allowed string, exit_allowed string, "
              "feeds array<string>, pick_id array<string>, scored boolean, src_asof date, "
              "frozen_at timestamp")
    df = spark.createDataFrame([tuple(r[c] for c in order) for r in rows], schema)
    df = df.selectExpr("asset_id", "kind", "name",
                       "ST_SetSRID(ST_Point(lon, lat), 4326) AS geometry",
                       *order[3:]).coalesce(1).sortWithinPartitions("asset_id")
    spark_write(root, "assets", df)


def pick_row_path(root: Path, pick_id: str) -> str:
    t = pq.read_table(root / "ref" / "picks").to_pylist()
    rows = [r for r in t if r["pick_id"] == pick_id]
    if not rows:
        raise RuntimeError(f"pick {pick_id} not in ref/picks - run make ref after landing the zip")
    return rows[0]["path"]


def build(root: Path, spark) -> None:
    build_grids(root)
    build_cells(root, spark)
    build_zones(root, spark)
    build_cell_zone(root)
    build_cell_pixel(root)
    build_calendar(root)
    build_picks(root)


def main() -> None:
    from raincheck.spark import session

    root, spark = data_root(), session()
    build(root, spark)
    build_assets(root, spark)


if __name__ == "__main__":
    main()
