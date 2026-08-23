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

    build(data_root(), session())


if __name__ == "__main__":
    main()
