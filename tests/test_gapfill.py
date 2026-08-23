"""Ticket 20: gap backfill from gtfsrt.io. Offline: the remote GCS layout is faked with a
file:// tree of parquet files written one row group per poll snapshot (the real files'
verified shape), and mapper schemas are censused against archiver.flush on the same pb
fixtures the feeds tests use."""
import hashlib
import sys
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from google.transit import gtfs_realtime_pb2

from raincheck import archiver, gapfill
from raincheck.feeds import decode_alerts, decode_subway_tu, decode_tu, decode_vp

FIXTURES = Path(__file__).parent / "fixtures"
US = 1_000_000
DAY = "2026-08-19"
D0 = 1787097600  # 2026-08-19T00:00:00Z


def load(name: str) -> gtfs_realtime_pb2.FeedMessage:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString((FIXTURES / name).read_bytes())
    return feed


def bronze_day(root: Path, day: str, missing: dict[str, list[str]]) -> None:
    """A Bronze tree with every kind x hour of `day` present except the named misses."""
    for kind in gapfill.KINDS:
        for h in range(24):
            if f"{h:02d}" in missing.get(kind, []):
                continue
            d = root / "archive" / kind / f"date={day}" / f"hour={h:02d}"
            d.mkdir(parents=True)
            (d / "part-00.parquet").touch()


@pytest.fixture()
def one_day(monkeypatch):
    monkeypatch.setattr(gapfill, "days", lambda *a, **k: ["2026-08-15"])
    return "2026-08-15"


def test_check_allowlists_dead_hours(tmp_path, one_day, monkeypatch, capsys):
    """Hours gtfsrt.io never stored are reported but must not fail a scheduled check."""
    monkeypatch.setattr(gapfill, "DEAD", {("subway_alerts", one_day): ("07", "12")})
    bronze_day(tmp_path, one_day, {"subway_alerts": ["07", "12"]})
    assert gapfill.check(tmp_path) == 0
    out = capsys.readouterr().out
    assert "dead at source: 07,12" in out and "22/24" in out  # reported, never hidden
    assert "GAP" not in out


def test_check_still_fails_on_a_fillable_gap_beside_a_dead_one(tmp_path, one_day, monkeypatch, capsys):
    monkeypatch.setattr(gapfill, "DEAD", {("subway_alerts", one_day): ("07",)})
    bronze_day(tmp_path, one_day, {"subway_alerts": ["07", "18"]})
    assert gapfill.check(tmp_path) == 1
    out = capsys.readouterr().out
    assert "missing 18" in out and "[dead at source: 07]" in out  # 18 fillable, 07 not


def test_check_flags_a_stale_dead_entry(tmp_path, one_day, monkeypatch, capsys):
    monkeypatch.setattr(gapfill, "DEAD", {("vp", one_day): ("05",)})
    bronze_day(tmp_path, one_day, {})  # every hour present: the entry has rotted
    assert gapfill.check(tmp_path) == 0
    assert "stale DEAD entry" in capsys.readouterr().out


def test_dead_entries_are_well_formed():
    """A typo in a key silently never matches, leaving the allowlist inert."""
    for (kind, day), hours in gapfill.DEAD.items():
        assert kind in gapfill.KINDS, kind
        assert date.fromisoformat(day) >= gapfill.START, day
        assert set(hours) <= {f"{h:02d}" for h in range(24)}, (kind, day, hours)


def test_start_stays_in_the_live_capture_era():
    """Moving START back is not a config change - it would halt live capture.

    `days()` defaults its span to START and `missing_hours` reads the LOCAL tree. Bronze
    for 2026-03-01..08-14 was filled, pushed to R2 and pruned locally on purpose (ticket
    18: R2 is its durable home), so local reads as entirely missing. Move START back and a
    routine `make gapfill` tries to re-pull the whole range - ~207 GB of downloads, ~37 GB
    of local writes - trips RAINCHECK_BRONZE_GB and STOPS THE ARCHIVER, opening the very
    gaps this tool exists to close. It fires on a normal command, not an exotic one.

    Verify that range with scripts/backfill-verify.py, which reads R2 where the data
    actually lives. To genuinely move START you must first teach check() and
    missing_hours() that a pruned-to-cloud hour is complete, stop the prune deleting
    _gapfill markers, and recreate ~12,000 markers from the R2 listing - see ticket 20's
    "Decision needed from Ross" section. This test is here so that work is chosen, not
    stumbled into.
    """
    assert gapfill.START >= date(2026, 8, 15), (
        f"START={gapfill.START} predates live capture; read this test's docstring before "
        f"changing it - a routine `make gapfill` would re-pull ~207 GB and halt capture")


def test_pick_snapshots_cadence_and_header_dedupe():
    snaps = [(0, 10), (20, 10), (40, 11), (60, 11), (80, 11), (120, 11), (180, 13)]
    assert gapfill.pick(snaps, 60) == [0, 3, 6]
    assert gapfill.pick([], 60) == []
    assert gapfill.pick([(0, 5), (30, 5)], 30) == [0]  # dup header at exactly one cadence


def test_missing_hours(tmp_path):
    d = tmp_path / "date=2026-08-19"
    (d / "hour=01").mkdir(parents=True)
    (d / "hour=01" / "part-00.parquet").touch()          # archiver's -> not missing
    (d / "hour=02").mkdir()
    (d / "hour=02" / "part-gapfill-vp.parquet").touch()  # filled + marker -> not missing
    (d / "hour=02" / "_gapfill").touch()
    (d / "hour=03").mkdir()
    (d / "hour=03" / "part-gapfill-vp.parquet").touch()  # crash debris, no marker -> redo
    (d / "hour=04").mkdir()
    (d / "hour=04" / "part-nbp-2026-08-19.parquet").touch()  # converter's -> not missing
    missing = gapfill.missing_hours(d)
    assert "01" not in missing and "02" not in missing and "04" not in missing
    assert "00" in missing and "03" in missing and "23" in missing
    assert len(missing) == 21


def raw(feed_type: str, snaps: list[tuple[int | None, int, list[dict]]]) -> tuple[pa.schema, list[pa.Table]]:
    """Synthetic gtfsrt.io tables, one per snapshot: (fetch_s, header_ts, entity rows)."""
    cols = dict.fromkeys(gapfill.RAW_COLS[feed_type], pa.string())
    cols.update(feed_timestamp=pa.uint64(), fetch_timestamp=pa.timestamp("us", tz="UTC"),
                direction_id=pa.uint32())
    if feed_type == "vehicle_positions":
        cols.update(latitude=pa.float32(), longitude=pa.float32(), bearing=pa.float32(),
                    timestamp=pa.uint64(), schedule_relationship=pa.int32(),
                    occupancy_status=pa.int32())
    if feed_type == "trip_updates":
        cols.update(stop_sequence=pa.uint32(), arrival_time=pa.int64(),
                    departure_time=pa.int64(), trip_delay=pa.int32(),
                    trip_timestamp=pa.uint64())
    if feed_type == "service_alerts":
        cols.update(cause=pa.int32(), effect=pa.int32(), active_period_start=pa.uint64(),
                    active_period_end=pa.uint64())
    schema = pa.schema([*cols.items(), ("extra_ignored", pa.string())])
    tables = []
    for fetch_s, header, rows in snaps:
        full = [{**dict.fromkeys(schema.names), **r, "entity_id": r.get("entity_id", "e1"),
                 "feed_timestamp": header,
                 "fetch_timestamp": fetch_s * US if fetch_s is not None else None} for r in rows]
        tables.append(pa.Table.from_pylist(full, schema=schema))
    return schema, tables


def remote(base: Path, feed_type: str, url: str, day: str,
           snaps: list[tuple[int | None, int, list[dict]]]) -> Path:
    schema, tables = raw(feed_type, snaps)
    out = base / feed_type / f"date={day}" / f"base64url={gapfill.b64(url)}" / "data.parquet"
    out.parent.mkdir(parents=True)
    with pq.ParquetWriter(out, schema) as w:
        for t in tables:
            w.write_table(t)
    return out


@pytest.fixture()
def fake_gcs(tmp_path, monkeypatch):
    base = tmp_path / "gcs"
    monkeypatch.setattr(gapfill, "GCS", base.as_uri())
    return base


def test_fill_day_vp_end_to_end(tmp_path, fake_gcs):
    root = tmp_path / "root"
    captured = root / "archive" / "vp" / f"date={DAY}" / "hour=01"
    captured.mkdir(parents=True)
    (captured / "part-00.parquet").write_bytes(b"archiver sentinel")
    v = {"vehicle_id": "MTA NYCT_1", "trip_id": "t1", "route_id": "B1", "latitude": 40.7,
         "longitude": -73.9, "timestamp": D0, "occupancy_status": 1, "start_date": "20260819"}
    remote(fake_gcs, "vehicle_positions", gapfill.FEEDS["vp"], DAY, [
        (D0 + 10, D0 + 9, [v, {"entity_id": "no-pos"}]),      # hour 00: 2 entities, 1 keepable
        (D0 + 40, D0 + 9, [dict(v, latitude=40.8)]),          # dup header -> dropped
        (D0 + 70, D0 + 69, [dict(v, vehicle_id="", trip_id="")]),  # empties -> NULL, id falls back
        (D0 + 3660, D0 + 3659, [v]),                          # hour 01: archiver has it -> skipped
        (D0 + 7300, D0 + 7299, [v]),                          # hour 02
    ])
    gapfill.fill_day(root, "vp", DAY)

    day_dir = root / "archive" / "vp" / f"date={DAY}"
    assert (captured / "part-00.parquet").read_bytes() == b"archiver sentinel"
    assert not (captured / "_gapfill").exists()
    assert sorted(p.name for p in (day_dir / "hour=00").iterdir()) == ["_gapfill", "part-gapfill-vp.parquet"]
    assert (day_dir / "hour=02" / "_gapfill").exists()
    assert not (day_dir / "hour=03").exists()  # no remote rows -> no dir, stays visibly missing

    t = pq.read_table(day_dir / "hour=00" / "part-gapfill-vp.parquet")
    assert t.num_rows == 2  # entity without a position dropped, dup-header snapshot dropped
    rows = t.to_pylist()
    assert rows[0]["vehicle_id"] == "MTA NYCT_1" and rows[0]["fetched_at"] == D0 + 10
    assert rows[0]["occupancy"] == "MANY_SEATS_AVAILABLE" and rows[0]["lat"] == pytest.approx(40.7)
    assert rows[1]["vehicle_id"] == "e1" and rows[1]["trip_id"] is None  # "" -> NULL + id fallback

    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in day_dir.rglob("*.parquet")}
    gapfill.fill_day(root, "vp", DAY)  # rerun: markers make it a no-op
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in day_dir.rglob("*.parquet")}
    assert after == before


def test_no_poll_clock_snapshot_is_skipped_not_fatal(tmp_path, fake_gcs, capsys):
    """Seen in the wild (subway-jz 2026-08-15 rg 310): a snapshot whose fetch_timestamp
    is entirely NULL, which also leaves the column chunk without stats."""
    root = tmp_path / "root"
    v = {"vehicle_id": "MTA NYCT_1", "latitude": 40.7, "longitude": -73.9, "timestamp": D0}
    remote(fake_gcs, "vehicle_positions", gapfill.FEEDS["vp"], DAY, [
        (D0 + 10, D0 + 9, [v]),
        (None, D0 + 39, [dict(v, vehicle_id="ghost")]),  # no poll clock -> skipped
        (D0 + 70, D0 + 69, [v]),
    ])
    gapfill.fill_day(root, "vp", DAY)
    assert "no poll clock" in capsys.readouterr().out
    t = pq.read_table(root / "archive" / "vp" / f"date={DAY}" / "hour=00")
    assert t.num_rows == 2 and "ghost" not in set(t.column("vehicle_id").to_pylist())


def test_fill_day_missing_remote_file_is_loud_but_clean(tmp_path, fake_gcs, capsys):
    root = tmp_path / "root"
    ok = gapfill.fill_day(root, "tu", DAY)  # nothing published for DAY
    assert "not published" in capsys.readouterr().out
    assert not (root / "archive" / "tu").exists()
    assert ok is False, "an unpublished day must report failure, not success"


def test_fill_reports_failure_when_it_filled_nothing(tmp_path, fake_gcs, monkeypatch, capsys):
    """A run that accomplished nothing must not exit 0.

    August 1-14 once reported all 42 day-feed combinations 'not published yet' in the same
    second - no network after a crash - and still exited 0, so its driver logged success.
    """
    monkeypatch.setattr(gapfill, "data_root", lambda: tmp_path / "root")
    monkeypatch.setattr(sys, "argv", ["gapfill", "fill", "--feed", "tu", "--date", DAY])
    with pytest.raises(SystemExit) as e:
        gapfill.main()
    assert e.value.code, "exit code must be truthy when nothing was filled"
    assert "nothing filled" in str(e.value.code)


def test_fill_tolerates_one_unpublished_day_among_good_ones(tmp_path, fake_gcs, monkeypatch):
    """gtfsrt.io lags 1-2 days, so the newest day of a default span is routinely
    unpublished. Failing on that would page every morning about a hole that fills itself
    tomorrow - one good day proves the source was reachable."""
    root = tmp_path / "root"
    v = {"vehicle_id": "MTA NYCT_1", "trip_id": "t1", "route_id": "B1", "latitude": 40.7,
         "longitude": -73.9, "timestamp": D0, "occupancy_status": 1, "start_date": "20260819"}
    remote(fake_gcs, "vehicle_positions", gapfill.FEEDS["vp"], DAY, [(D0 + 10, D0 + 9, [v])])
    nxt = "2026-08-20"                      # deliberately NOT published
    monkeypatch.setattr(gapfill, "data_root", lambda: root)
    monkeypatch.setattr(sys, "argv",
                        ["gapfill", "fill", "--feed", "vp", "--date", f"{DAY}:{nxt}"])
    gapfill.main()                          # must NOT raise: one day filled, one lagging


def test_subway_tu_fill_writes_one_part_per_feed(tmp_path, fake_gcs):
    root = tmp_path / "root"
    s = {"trip_id": "072150_G..N", "route_id": "G", "stop_id": "G22N", "start_date": "20260819",
         "arrival_time": D0 + 100, "departure_time": D0 + 130}
    for sfx in gapfill.SUBWAY_FEEDS:
        remote(fake_gcs, "trip_updates", gapfill.FEEDS[f"subway{sfx}"], DAY,
               [(D0 + 5, D0 + 4, [s])])
    gapfill.fill_day(root, "subway_tu", DAY)
    hour = root / "archive" / "subway_tu" / f"date={DAY}" / "hour=00"
    parts = sorted(p.name for p in hour.glob("part-gapfill-*.parquet"))
    assert parts == sorted(f"part-gapfill-subway{sfx}.parquet" for sfx in gapfill.SUBWAY_FEEDS)
    assert (hour / "_gapfill").exists()
    t = pq.read_table(hour / "part-gapfill-subway-g.parquet")
    row = t.to_pylist()[0]
    assert row["feed"] == "subway-g" and row["header_ts"] == D0 + 4
    assert row["train_id"] is None and row["direction"] is None  # NYCT ext not archived
    assert row["scheduled_track"] is None and row["is_assigned"] is None


def test_tu_drops_stu_less_entity_rows(tmp_path, fake_gcs):
    root = tmp_path / "root"
    stu = {"trip_id": "t1", "route_id": "B1", "stop_id": "S1", "stop_sequence": 3,
           "arrival_time": D0 + 50, "vehicle_id": "MTA NYCT_9"}
    remote(fake_gcs, "trip_updates", gapfill.FEEDS["tu"], DAY,
           [(D0 + 5, D0 + 4, [stu, {"trip_id": "t2"}])])  # t2: entity with no StopTimeUpdate
    gapfill.fill_day(root, "tu", DAY)
    t = pq.read_table(root / "archive" / "tu" / f"date={DAY}" / "hour=00")
    assert t.to_pylist() == [{"trip_id": "t1", "route_id": "B1", "start_date": None,
                              "direction_id": None, "vehicle_id": "MTA NYCT_9",
                              "trip_delay_s": None, "trip_ts": None, "stop_id": "S1",
                              "stop_sequence": 3, "arrival_time": D0 + 50,
                              "departure_time": None, "header_ts": D0 + 4,
                              "fetched_at": D0 + 5}]


def test_alerts_mapping(tmp_path, fake_gcs):
    root = tmp_path / "root"
    a = {"entity_id": "alert:1", "cause": 6, "effect": 4, "active_period_start": D0,
         "active_period_end": D0 + 3600, "header_text": "detour", "description_text": "",
         "route_id": "B41", "agency_id": "MTA NYCT", "direction_id": 1}
    remote(fake_gcs, "service_alerts", gapfill.FEEDS["subway_alerts"], DAY,
           [(D0 + 5, D0 + 4, [a])])
    gapfill.fill_day(root, "subway_alerts", DAY)
    row = pq.read_table(root / "archive" / "subway_alerts" / f"date={DAY}" / "hour=00").to_pylist()[0]
    assert row["agency"] == "subway" and row["alert_id"] == "alert:1"
    assert row["cause"] == "ACCIDENT" and row["effect"] == "DETOUR"
    assert row["active_start"] == D0 and row["active_end"] == D0 + 3600
    assert row["description"] is None and row["direction_id"] == 1  # "" -> NULL


def test_alerts_maps_pre_expansion_source_without_direction_id(tmp_path, fake_gcs):
    """gtfsrt.io grew service_alerts from 20 to 50 columns mid-2026, so their historical
    files have no direction_id COLUMN at all (not merely a null value). The mapper must
    NULL it rather than KeyError - the crash this replays is what blocked the
    2026-03-01.. bus-history backfill. Measured: direction_id is all-NULL for this feed
    in both source eras, so NULL-filling loses nothing real."""
    root = tmp_path / "root"
    a = {"entity_id": "alert:1", "cause": 6, "effect": 4, "active_period_start": D0,
         "active_period_end": D0 + 3600, "header_text": "detour", "description_text": "",
         "route_id": "B41", "agency_id": "MTA NYCT"}
    src = remote(fake_gcs, "service_alerts", gapfill.FEEDS["alerts"], DAY,
                 [(D0 + 5, D0 + 4, [a])])
    t = pq.read_table(src)  # replay the pre-expansion source shape in place
    pq.write_table(t.drop_columns(["direction_id"]), src)

    gapfill.fill_day(root, "alerts", DAY)
    row = pq.read_table(root / "archive" / "alerts" / f"date={DAY}" / "hour=00").to_pylist()[0]
    assert row["direction_id"] is None          # absent column -> NULL, no crash
    assert row["agency"] == "bus" and row["alert_id"] == "alert:1"
    assert row["cause"] == "ACCIDENT" and row["effect"] == "DETOUR"  # rest still maps


# --- schema census: every mapper's output schema == what archiver.flush writes ---------
CENSUS = [
    ("vp", "vehicle_positions", lambda: decode_vp(load("vehicle_positions_2026-08-11.pb"))),
    ("tu", "trip_updates", lambda: decode_tu(load("trip_updates_2026-08-11.pb"))),
    ("alerts", "service_alerts", lambda: decode_alerts(load("alerts_2026-08-11.pb"), "bus")),
    ("subway_alerts", "service_alerts", lambda: decode_alerts(load("alerts_2026-08-11.pb"), "subway")),
    ("subway_tu", "trip_updates",
     lambda: decode_subway_tu(load("subway_1234567S_2026-08-16.pb"), "subway")),
]


@pytest.mark.parametrize("kind,feed_type,live_rows", CENSUS, ids=[c[0] for c in CENSUS])
def test_mapper_schema_matches_archiver(kind, feed_type, live_rows, tmp_path, monkeypatch):
    monkeypatch.setattr(archiver, "ROOT", tmp_path)
    live_schema = pq.read_schema(archiver.flush(live_rows()[:5], kind, 1786478400))
    _, tables = raw(feed_type, [(D0 + 5, D0 + 4, [{}])])
    mapper = dict(gapfill.SOURCES[kind][1])[
        "subway" if kind == "subway_tu" else kind]
    assert mapper(tables[0]).schema.equals(live_schema)
