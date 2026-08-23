"""`make schedule PICK=` (ticket 07 / spec D): load one registered Pick's GTFS zip into
the per-Pick schedule tables, partitioned by pick_id, loaded only for Picks a slice needs.

silver/stops/pick_id=          stop_id, stop_name, lon, lat, cell, geometry POINT (GeoParquet)
silver/trips/pick_id=          trip_id, route_id, direction_id, service_id, shape_id, trip_type
silver/trip_stops/pick_id=     trip_id, stop_sequence, stop_id, arrival_s, departure_s,
                               shape_dist_m (cumulative geodesic along the shape, computed
                               at ingest); sorted (trip_id, stop_sequence)
silver/service_days/pick_id=   service_id, service_date (calendar x calendar_dates flattened)
silver/shapes/pick_id=         shape_id, geometry LINESTRING (GeoParquet), length_m

Gate: the trip_id scheme check - >= 98% of trip_ids parse as the depot form
`<depot>_<pick>-<service>[-modifiers]-<start:6>_<route>_<run>` or the MTA Bus Company
`-..P<code>-` form (resolver v2 grammar, research 11/13) - fails the load loudly.

Run: make schedule PICK=<pick_id>   (python -m raincheck.schedule <pick_id>)
"""
import argparse
import csv
import io
import re
import shutil
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
from pyproj import Geod

from raincheck.paths import data_root
from raincheck.picks import BUSCO_RE, DEPOT_RE
from raincheck.ref import UTM

GEOD = Geod(ellps="WGS84")


def read_txt(z: zipfile.ZipFile, name: str, **kwargs) -> pa.Table:
    return pacsv.read_csv(io.BytesIO(z.read(name)), **kwargs)


def hms_to_s(values: pa.ChunkedArray) -> pa.Array:
    """GTFS H:MM:SS (hours may exceed 24) -> seconds; blank -> NULL. Cached per distinct."""
    cache: dict[str | None, int | None] = {None: None, "": None}
    out = []
    for v in values.to_pylist():
        if v not in cache:
            h, m, s = v.split(":")
            cache[v] = int(h) * 3600 + int(m) * 60 + int(s)
        out.append(cache[v])
    return pa.array(out, pa.int32())


def trip_type(route_id: str) -> str:
    """The Pick's own trip classification (06). Same shape as the pick-free route_class
    rule; kept separate on purpose - this one may follow the static feed."""
    if re.match(r"^(X|BM|QM|BXM|SIM)", route_id.upper()):
        return "express"
    return "sbs" if route_id.endswith("+") else "local"


def scheme_check(trip_ids: list[str], feed: str) -> None:
    n = len(trip_ids)
    ok = sum(1 for t in trip_ids if DEPOT_RE.match(t) or BUSCO_RE.search(t))
    rate = ok / n if n else 0.0
    print(f"schedule {feed}: trip_id scheme check {ok}/{n} = {rate:.3f}", flush=True)
    if rate < 0.98:
        sys.exit(f"schedule {feed}: trip_id scheme check failed ({rate:.3f} < 0.98) - "
                 f"the resolver grammar would not recognize this zip")


def cum_geodesic(lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    """Cumulative geodesic metres along a polyline, 0 at the first vertex."""
    if len(lons) < 2:
        return np.zeros(len(lons))
    _, _, seg = GEOD.inv(lons[:-1], lats[:-1], lons[1:], lats[1:])
    return np.concatenate([[0.0], np.cumsum(seg)])


def shape_distances(z: zipfile.ZipFile, stops: pa.Table, by_shape: dict[str, set[str]]
                    ) -> tuple[dict[tuple[str, str], float], list[tuple[str, str, float]]]:
    """Project every (shape_id, stop_id) pair a trip uses onto its shape: distance along
    found in EPSG:32618, mapped back to the cumulative geodesic distance at that point.
    Returns the lookup and one (shape_id, wkt, length_m) row per shape."""
    import shapely

    pts = read_txt(z, "shapes.txt", convert_options=pacsv.ConvertOptions(
        column_types={"shape_id": pa.string(), "shape_pt_lat": pa.float64(),
                      "shape_pt_lon": pa.float64(), "shape_pt_sequence": pa.int32()}))
    pts = pts.sort_by([("shape_id", "ascending"), ("shape_pt_sequence", "ascending")])
    sid = np.asarray(pts.column("shape_id"))
    lon = np.asarray(pts.column("shape_pt_lon"), dtype=float)
    lat = np.asarray(pts.column("shape_pt_lat"), dtype=float)
    starts = np.concatenate([[0], np.nonzero(sid[1:] != sid[:-1])[0] + 1, [len(sid)]])

    stop_xy = dict(zip(stops.column("stop_id").to_pylist(),
                       zip(*UTM.transform(np.asarray(stops.column("lon"), dtype=float),
                                          np.asarray(stops.column("lat"), dtype=float)))))
    lookup: dict[tuple[str, str], float] = {}
    shape_rows: list[tuple[str, str, float]] = []
    for a, b in zip(starts[:-1], starts[1:]):
        shape = str(sid[a])
        slon, slat = lon[a:b], lat[a:b]
        cum_geo = cum_geodesic(slon, slat)
        x, y = UTM.transform(slon, slat)
        cum_utm = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
        line = shapely.LineString(np.column_stack([x, y]))
        wkt = "LINESTRING (" + ", ".join(f"{o:.6f} {a_:.6f}" for o, a_ in zip(slon, slat)) + ")"
        shape_rows.append((shape, wkt, float(cum_geo[-1])))
        for stop in by_shape.get(shape, ()):
            if stop not in stop_xy:
                continue
            s = line.project(shapely.Point(stop_xy[stop]))
            i = min(int(np.searchsorted(cum_utm, s, side="right")) - 1, len(cum_utm) - 2)
            seg_utm = cum_utm[i + 1] - cum_utm[i]
            frac = (s - cum_utm[i]) / seg_utm if seg_utm > 0 else 0.0
            lookup[(shape, stop)] = float(cum_geo[i] + frac * (cum_geo[i + 1] - cum_geo[i]))
    return lookup, shape_rows


def service_days_rows(z: zipfile.ZipFile) -> list[tuple[str, object]]:
    names = set(z.namelist())
    active: set[tuple[str, object]] = set()
    if "calendar.txt" in names:
        for row in csv.DictReader(io.TextIOWrapper(z.open("calendar.txt"), "utf-8-sig")):
            start = datetime.strptime(row["start_date"].strip(), "%Y%m%d").date()
            end = datetime.strptime(row["end_date"].strip(), "%Y%m%d").date()
            days = [row[k].strip() == "1" for k in ("monday", "tuesday", "wednesday",
                                                    "thursday", "friday", "saturday", "sunday")]
            d = start
            while d <= end:
                if days[d.weekday()]:
                    active.add((row["service_id"].strip(), d))
                d += timedelta(days=1)
    if "calendar_dates.txt" in names:
        for row in csv.DictReader(io.TextIOWrapper(z.open("calendar_dates.txt"), "utf-8-sig")):
            key = (row["service_id"].strip(),
                   datetime.strptime(row["date"].strip(), "%Y%m%d").date())
            if row["exception_type"].strip() == "1":
                active.add(key)
            else:
                active.discard(key)
    return sorted(active)


def write_part(root: Path, name: str, pick_id: str, table: pa.Table) -> None:
    out = root / "silver" / name / f"pick_id={pick_id}" / "part-00000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out, compression="zstd")
    print(f"silver/{name}/pick_id={pick_id}: {table.num_rows} rows", flush=True)


def spark_geo_part(root: Path, name: str, pick_id: str, df) -> None:
    staging = root / ".staging" / f"{name}_{pick_id}"
    df.write.format("geoparquet").mode("overwrite").save(str(staging))
    out = root / "silver" / name / f"pick_id={pick_id}" / "part-00000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    (part,) = staging.glob("part-*.parquet")
    shutil.move(part, out)
    shutil.rmtree(staging)
    print(f"silver/{name}/pick_id={pick_id}: wrote {out.name}", flush=True)


def pick_row(root: Path, pick_id: str) -> dict:
    t = pq.read_table(root / "ref" / "picks")
    rows = [r for r in t.to_pylist() if r["pick_id"] == pick_id]
    if not rows:
        sys.exit(f"schedule: pick {pick_id} not in ref/picks - run make ref after landing the zip")
    return rows[0]


def load(root: Path, spark, pick_id: str) -> None:
    pick = pick_row(root, pick_id)
    with zipfile.ZipFile(root / pick["path"]) as z:
        stops_t = read_txt(z, "stops.txt", convert_options=pacsv.ConvertOptions(
            column_types={"stop_id": pa.string(), "stop_name": pa.string(),
                          "stop_lat": pa.float64(), "stop_lon": pa.float64()}))
        stops_t = pa.table({"stop_id": stops_t.column("stop_id"),
                            "stop_name": stops_t.column("stop_name"),
                            "lon": stops_t.column("stop_lon"),
                            "lat": stops_t.column("stop_lat")}).sort_by("stop_id")
        trips_t = read_txt(z, "trips.txt", convert_options=pacsv.ConvertOptions(
            column_types={"trip_id": pa.string(), "route_id": pa.string(),
                          "service_id": pa.string(), "shape_id": pa.string(),
                          "direction_id": pa.int8()}))
        trip_ids = trips_t.column("trip_id").to_pylist()
        scheme_check(trip_ids, pick["feed"])
        routes = trips_t.column("route_id").to_pylist()
        trips_out = pa.table({
            "trip_id": trip_ids, "route_id": routes,
            "direction_id": trips_t.column("direction_id").cast(pa.int8()),
            "service_id": trips_t.column("service_id"),
            "shape_id": trips_t.column("shape_id"),
            "trip_type": pa.array([trip_type(r) for r in routes], pa.string()),
        }).sort_by("trip_id")

        st = read_txt(z, "stop_times.txt", convert_options=pacsv.ConvertOptions(
            column_types={"trip_id": pa.string(), "stop_id": pa.string(),
                          "arrival_time": pa.string(), "departure_time": pa.string(),
                          "stop_sequence": pa.int32()},
            include_columns=["trip_id", "arrival_time", "departure_time",
                             "stop_id", "stop_sequence"]))
        st = st.sort_by([("trip_id", "ascending"), ("stop_sequence", "ascending")])

        shape_of = dict(zip(trip_ids, trips_t.column("shape_id").to_pylist()))
        st_trip = st.column("trip_id").to_pylist()
        st_stop = st.column("stop_id").to_pylist()
        by_shape: dict[str, set[str]] = {}
        for t, s in zip(st_trip, st_stop):
            sh = shape_of.get(t)
            if sh:
                by_shape.setdefault(sh, set()).add(s)

        lookup, shape_rows = shape_distances(z, stops_t, by_shape)
        dist = np.array([lookup.get((shape_of.get(t) or "", s), np.nan)
                         for t, s in zip(st_trip, st_stop)], dtype=np.float64)
        # monotone along each trip (a loop stop projects onto its first pass): cummax
        # with a reset at each trip boundary keeps interpolation weights non-negative;
        # a stop the projection could not place stays NaN (enrich falls back to
        # linear-in-stop-index there), it is never backfilled from its neighbour
        tarr = np.asarray(st.column("trip_id"))
        new_trip = np.concatenate([[True], tarr[1:] != tarr[:-1]])
        d = np.where(np.isnan(dist), -np.inf, dist)
        cur = -np.inf  # ponytail: plain loop; segmented cummax has no clean numpy one-liner
        acc = np.empty_like(d)
        for i in range(len(d)):
            cur = max(d[i], -np.inf if new_trip[i] else cur)
            acc[i] = cur
        dist_mono = np.where(np.isnan(dist) | np.isinf(acc), np.nan, acc).astype(np.float32)

        trip_stops_out = pa.table({
            "trip_id": st.column("trip_id"),
            "stop_sequence": st.column("stop_sequence").cast(pa.int16()),
            "stop_id": st.column("stop_id"),
            "arrival_s": hms_to_s(st.column("arrival_time")),
            "departure_s": hms_to_s(st.column("departure_time")),
            "shape_dist_m": pa.array(dist_mono, pa.float32(), from_pandas=True),
        })

        sd = service_days_rows(z)
        service_days_out = pa.table({
            "service_id": pa.array([s for s, _ in sd], pa.string()),
            "service_date": pa.array([d_ for _, d_ in sd], pa.date32()),
        })

    write_part(root, "trips", pick_id, trips_out)
    write_part(root, "trip_stops", pick_id, trip_stops_out)
    write_part(root, "service_days", pick_id, service_days_out)

    stops_df = spark.createDataFrame(
        list(zip(*(stops_t.column(c).to_pylist() for c in ("stop_id", "stop_name", "lon", "lat")))),
        "stop_id string, stop_name string, lon double, lat double")
    stops_df = (stops_df.selectExpr(
        "stop_id", "stop_name", "lon", "lat",
        "ST_H3CellIDs(ST_Point(lon, lat), 8, false)[0] AS cell",
        "ST_SetSRID(ST_Point(lon, lat), 4326) AS geometry")
        .coalesce(1).sortWithinPartitions("stop_id"))
    spark_geo_part(root, "stops", pick_id, stops_df)

    shapes_df = spark.createDataFrame(shape_rows, "shape_id string, wkt string, length_m float")
    shapes_df = (shapes_df.selectExpr(
        "shape_id", "ST_SetSRID(ST_GeomFromWKT(wkt), 4326) AS geometry", "length_m")
        .coalesce(1).sortWithinPartitions("shape_id"))
    spark_geo_part(root, "shapes", pick_id, shapes_df)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pick_id", help="sha1 pick_id from ref/picks")
    args = ap.parse_args()
    from raincheck.spark import session

    load(data_root(), session(), args.pick_id)


if __name__ == "__main__":
    main()
