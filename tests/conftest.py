"""Shared fixtures. Seam B (spec Testing Decisions): one session-scoped Spark session per
pytest process (~9 s), skipping (never failing) when no JVM is found. The mini GTFS zip
(ticket 07) feeds both the schedule loader tests and the events Passage/Delay tests."""
import io
import zipfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def spark():
    from raincheck.spark import java_home, session  # pyspark import cost only when a test asks

    if java_home() is None:
        pytest.skip("no JVM found: set JAVA_HOME (see Makefile) or brew install openjdk@17")
    s = session()
    yield s
    s.stop()


# trips: T1 walks S1..S5 (envelope/interpolation tests); FRAG matches a real trip in the
# 2021-11-07 archive fragment (DST fall-back day); SBS/EXPR/BUSCO pin the trip_type rule
# and the two scheme-check grammars. Calendars: WKD leaves 2021-09-02 uncovered (the
# pick_gap day); SUN covers 2021-11-07, 2024-03-10 and 2024-11-03 (the DST trio).
T1 = "MV_C1-Weekday-033000_B41_101"
FRAG = "GA_D1-Sunday-039500_Q59_902"
GTFS = {
    "stops.txt": (
        "stop_id,stop_name,stop_lat,stop_lon\n"
        "S1,First,40.600,-73.950\nS2,Second,40.605,-73.950\nS3,Third,40.610,-73.950\n"
        "S4,Fourth,40.615,-73.950\nS5,Fifth,40.620,-73.950\n"
        "304943,Frag A,40.7095,-73.9595\n503476,Frag B,40.7126,-73.8985\n"),
    "trips.txt": (
        "route_id,service_id,trip_id,direction_id,shape_id\n"
        f"B41,WKD,{T1},0,SH1\n"
        f"Q59,SUN,{FRAG},1,SHF\n"
        "M15+,WKD,MV_C1-Weekday-SDon-040000_M15+_102,0,SH1\n"
        "BXM1,WKD,MV_C1-Weekday-050000_BXM1_103,1,SH1\n"
        "Q50,WKD,1234-LGPA5-Weekday-10-123456_Q50_1,0,SH1\n"),
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        + "".join(f"{T1},07:{m:02d}:00,07:{m:02d}:00,S{k},{k}\n"
                  for k, m in zip(range(1, 6), range(0, 25, 5)))
        + f"{FRAG},06:50:00,06:50:00,304943,1\n{FRAG},07:05:00,07:05:00,503476,2\n"
        + "MV_C1-Weekday-SDon-040000_M15+_102,24:59:00,25:04:00,S1,1\n"
        + "MV_C1-Weekday-SDon-040000_M15+_102,25:09:00,25:09:00,S2,2\n"),
    "calendar.txt": (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "WKD,1,1,1,1,1,0,0,20240101,20251231\n"
        "SUN,0,0,0,0,0,0,1,20211101,20241231\n"),
    "calendar_dates.txt": (
        "service_id,date,exception_type\n"
        "SUN,20240602,2\n"          # removed Sunday
        "WKD,20240601,1\n"),        # added Saturday
    "shapes.txt": (
        "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
        + "".join(f"SH1,{40.600 + 0.005 * k},-73.950,{k + 1}\n" for k in range(5))
        + "SHF,40.7095,-73.9595,1\nSHF,40.7126,-73.8985,2\n"),
}


def gtfs_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in GTFS.items():
            z.writestr(name, text)
    return buf.getvalue()


def land_pick(root: Path) -> str:
    """Land the mini zip as a captured Bronze static zip, register it in ref/picks and
    return its pick_id (sha1)."""
    import hashlib

    from raincheck import ref

    data = gtfs_zip_bytes()
    out = root / "archive" / "static" / "brooklyn" / "2021-10-01.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    ref.build_picks(root)
    return hashlib.sha1(data).hexdigest()
