"""MTA bus GTFS-RT: fetch and decode. Facts: vault/nyc-mta-bus-feeds-reference.md."""
import time

import requests
from google.transit import gtfs_realtime_pb2

FEEDS = {
    "vp": "https://gtfsrt.prod.obanyc.com/vehiclePositions",
    "tu": "https://gtfsrt.prod.obanyc.com/tripUpdates",
    "alerts": "https://gtfsrt.prod.obanyc.com/alerts",
}

OCCUPANCY = gtfs_realtime_pb2.VehiclePosition.OccupancyStatus


def fetch(name: str, timeout: int = 20) -> gtfs_realtime_pb2.FeedMessage:
    resp = requests.get(
        FEEDS[name], timeout=timeout, headers={"Accept": "application/x-protobuf"}
    )
    resp.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed


def decode_vp(feed) -> list[dict]:
    """One flat dict per vehicle with a position. occupancy is None when absent
    (41% coverage, skewed to empty buses; never divide by total vehicles)."""
    rows = []
    fetched_at = int(time.time())
    for e in feed.entity:
        v = e.vehicle
        if not (e.HasField("vehicle") and v.HasField("position")):
            continue
        rows.append({
            "vehicle_id": v.vehicle.id or e.id,
            "trip_id": v.trip.trip_id or None,
            "route_id": v.trip.route_id or None,
            "direction_id": v.trip.direction_id if v.trip.HasField("direction_id") else None,
            "start_date": v.trip.start_date or None,
            "lat": v.position.latitude,
            "lon": v.position.longitude,
            "bearing": v.position.bearing if v.position.HasField("bearing") else None,
            "stop_id": v.stop_id or None,
            "ts": int(v.timestamp),
            "occupancy": OCCUPANCY.Name(v.occupancy_status)
            if v.HasField("occupancy_status") else None,
            "fetched_at": fetched_at,
        })
    return rows


def decode_tu(feed) -> list[dict]:
    """One flat dict per StopTimeUpdate. arrival.delay is never populated by MTA
    (0/37,697 measured); arrival_time is the absolute predicted epoch."""
    rows = []
    fetched_at = int(time.time())
    for e in feed.entity:
        if not e.HasField("trip_update"):
            continue
        tu = e.trip_update
        vehicle_id = tu.vehicle.id if tu.HasField("vehicle") else None
        for s in tu.stop_time_update:
            rows.append({
                "trip_id": tu.trip.trip_id or None,
                "route_id": tu.trip.route_id or None,
                "start_date": tu.trip.start_date or None,
                "vehicle_id": vehicle_id,
                "stop_id": s.stop_id or None,
                "stop_sequence": s.stop_sequence if s.HasField("stop_sequence") else None,
                "arrival_time": int(s.arrival.time) if s.HasField("arrival") and s.arrival.HasField("time") else None,
                "departure_time": int(s.departure.time) if s.HasField("departure") and s.departure.HasField("time") else None,
                "fetched_at": fetched_at,
            })
    return rows
