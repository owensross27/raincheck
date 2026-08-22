"""MTA bus and subway GTFS-RT: fetch and decode. Facts: vault/nyc-mta-bus-feeds-reference.md."""
import time

import requests
from google.transit import gtfs_realtime_pb2

from raincheck import nyct_subway_pb2 as nyct

SUBWAY = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/"
SUBWAY_FEEDS = ["", "-ace", "-bdfm", "-g", "-jz", "-l", "-nqrw", "-si"]  # nyct%2Fgtfs<suffix>, keyless
FEEDS = {
    "vp": "https://gtfsrt.prod.obanyc.com/vehiclePositions",
    "tu": "https://gtfsrt.prod.obanyc.com/tripUpdates",
    "alerts": "https://gtfsrt.prod.obanyc.com/alerts",
    "subway_alerts": SUBWAY + "camsys%2Fsubway-alerts",
    **{f"subway{sfx}": SUBWAY + f"nyct%2Fgtfs{sfx}" for sfx in SUBWAY_FEEDS},
}

OCCUPANCY = gtfs_realtime_pb2.VehiclePosition.OccupancyStatus
STATUS = gtfs_realtime_pb2.VehiclePosition.VehicleStopStatus
TRIP_REL = gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship
CAUSE, EFFECT = gtfs_realtime_pb2.Alert.Cause, gtfs_realtime_pb2.Alert.Effect
DIRECTION = nyct.NyctTripDescriptor.Direction


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
            # 07: verbatim per spec F - events filters CANCELED, flags ADDED/DUPLICATED
            "schedule_relationship": TRIP_REL.Name(v.trip.schedule_relationship)
            if v.trip.HasField("schedule_relationship") else None,
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


def _text(ts) -> str | None:
    return ts.translation[0].text if ts.translation else None


def decode_alerts(feed, agency: str) -> list[dict]:
    """One flat row per alert x informed_entity (05: agency/route/trip level, no stops on
    the bus feed). Texts are single-language; first active_period only."""
    rows = []
    fetched_at = int(time.time())
    for e in feed.entity:
        if not e.HasField("alert"):
            continue
        a = e.alert
        period = a.active_period[0] if a.active_period else None
        base = {
            "agency": agency,
            "alert_id": e.id,
            "cause": CAUSE.Name(a.cause) if a.HasField("cause") else None,
            "effect": EFFECT.Name(a.effect) if a.HasField("effect") else None,
            "active_start": int(period.start) if period and period.HasField("start") else None,
            "active_end": int(period.end) if period and period.HasField("end") else None,
            "header": _text(a.header_text),
            "description": _text(a.description_text),
            "fetched_at": fetched_at,
        }
        for ie in a.informed_entity or [None]:
            rows.append({
                **base,
                "agency_id": ie.agency_id or None if ie else None,
                "route_id": ie.route_id or None if ie else None,
                "stop_id": ie.stop_id or None if ie else None,
                "trip_id": ie.trip.trip_id or None if ie and ie.HasField("trip") else None,
                "direction_id": ie.direction_id if ie and ie.HasField("direction_id") else None,
            })
    return rows


def _nyct_trip(trip) -> dict:
    x = trip.Extensions[nyct.nyct_trip_descriptor]
    return {
        "trip_id": trip.trip_id or None,
        "route_id": trip.route_id or None,
        "start_date": trip.start_date or None,
        "train_id": x.train_id or None,
        "direction": DIRECTION.Name(x.direction) if x.HasField("direction") else None,
        "is_assigned": x.is_assigned if x.HasField("is_assigned") else None,
    }


def decode_subway_tu(feed, feed_key: str) -> list[dict]:
    """One flat row per StopTimeUpdate of the subway feed. No stop_sequence, no delay,
    no vehicle on subway TUs (measured 2026-08-16); tracks come from the NYCT extension
    (scheduled_track on every row, actual_track only near-term)."""
    rows = []
    fetched_at = int(time.time())
    header_ts = int(feed.header.timestamp)
    for e in feed.entity:
        if not e.HasField("trip_update"):
            continue
        base = {"feed": feed_key, **_nyct_trip(e.trip_update.trip)}
        for s in e.trip_update.stop_time_update:
            y = s.Extensions[nyct.nyct_stop_time_update]
            rows.append({
                **base,
                "stop_id": s.stop_id or None,
                "arrival_time": int(s.arrival.time) if s.HasField("arrival") and s.arrival.HasField("time") else None,
                "departure_time": int(s.departure.time) if s.HasField("departure") and s.departure.HasField("time") else None,
                "scheduled_track": y.scheduled_track or None,
                "actual_track": y.actual_track or None,
                "header_ts": header_ts,
                "fetched_at": fetched_at,
            })
    return rows


def decode_subway_vp(feed, feed_key: str) -> list[dict]:
    """One row per train. Subway VPs carry stop_id + current_stop_sequence, never a
    position (measured): the train's location is the stop it is at or approaching."""
    rows = []
    fetched_at = int(time.time())
    for e in feed.entity:
        if not e.HasField("vehicle"):
            continue
        v = e.vehicle
        rows.append({
            "feed": feed_key,
            **_nyct_trip(v.trip),
            "stop_id": v.stop_id or None,
            "current_status": STATUS.Name(v.current_status) if v.HasField("current_status") else None,
            "current_stop_sequence": v.current_stop_sequence if v.HasField("current_stop_sequence") else None,
            "ts": int(v.timestamp) if v.HasField("timestamp") else None,
            "fetched_at": fetched_at,
        })
    return rows
