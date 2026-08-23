"""The DuckDB read-back helper (spec A / 09): session TimeZone UTC, dataset roots opened as
**/*.parquet with Hive partition keys read as strings. JVM-free."""
from raincheck import archiver, duck


def test_connect_is_utc():
    con = duck.connect()
    assert con.execute("SELECT current_setting('TimeZone')").fetchone() == ("UTC",)


def test_table_opens_a_dataset_root_with_string_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(archiver, "ROOT", tmp_path)
    row = {"vehicle_id": "a", "ts": 1786478400, "fetched_at": 1786478400}
    archiver.flush([row] * 10, "vp", 1786478400)  # 2026-08-11T20:00Z
    archiver.flush([row] * 5, "vp", 1786482000)  # 21:00Z
    rel = duck.table(duck.connect(), tmp_path / "vp")
    types = dict(zip(rel.columns, map(str, rel.types)))
    assert types["date"] == "VARCHAR" and types["hour"] == "VARCHAR" and types["ts"] == "BIGINT"
    assert rel.aggregate("hour, count(*)").order("hour").fetchall() == [("20", 10), ("21", 5)]


def test_table_unions_mixed_schema_hour_pair(tmp_path, monkeypatch):
    """Bronze vp mixes part schemas within one date: parts written by the pre-07
    archiver lack schedule_relationship, gapfill/post-restart parts have it.
    duck.table must union by name and read the missing column as NULL."""
    monkeypatch.setattr(archiver, "ROOT", tmp_path)
    old = {"vehicle_id": "a", "ts": 1786478400, "fetched_at": 1786478400}
    new = {**old, "vehicle_id": "b", "schedule_relationship": "ADDED",
           "ts": 1786482000, "fetched_at": 1786482000}
    archiver.flush([old], "vp", 1786478400)  # hour=20, no schedule_relationship column
    archiver.flush([new], "vp", 1786482000)  # hour=21, has it
    rel = duck.table(duck.connect(), tmp_path / "vp")
    rows = rel.order("hour").fetchall()
    cols = rel.columns
    assert "schedule_relationship" in cols
    got = [dict(zip(cols, r)) for r in rows]
    assert [g["schedule_relationship"] for g in got] == [None, "ADDED"]
    assert [g["vehicle_id"] for g in got] == ["a", "b"]


TU_ERA_COLS = ("direction_id", "trip_delay_s", "trip_ts", "header_ts")


def test_table_unions_mixed_tu_schema_hour_pair(tmp_path, monkeypatch):
    """Bronze tu drifts the same way vp does but wider: pre-10 archiver parts and the
    ticket-20 gapfill parts lack all four of direction_id, trip_delay_s, trip_ts and
    header_ts. duck.table must union by name and read every one of them as NULL.

    The pre-fix failure mode is order-dependent and the narrow-first case is SILENT
    (measured): with the narrow part first read_parquet binds its schema and the four
    columns simply vanish - right row count, no error; only wide-first raises. The
    narrow part is written first here on purpose, so the column-presence assertion is
    what carries this test."""
    monkeypatch.setattr(archiver, "ROOT", tmp_path)
    old = {"trip_id": "t1", "vehicle_id": "a", "stop_id": "S1",
           "arrival_time": 1786478700, "fetched_at": 1786478400}
    new = {**old, "trip_id": "t2", "vehicle_id": "b", "direction_id": 1,
           "trip_delay_s": 42, "trip_ts": 1786482000, "header_ts": 1786482001,
           "arrival_time": 1786482300, "fetched_at": 1786482000}
    archiver.flush([old], "tu", 1786478400)  # hour=20, pre-10 shape (9 columns)
    archiver.flush([new], "tu", 1786482000)  # hour=21, canonical (13 columns)
    rel = duck.table(duck.connect(), tmp_path / "tu")
    cols = rel.columns
    assert all(c in cols for c in TU_ERA_COLS)
    got = [dict(zip(cols, r)) for r in rel.order("hour").fetchall()]
    assert [g["trip_id"] for g in got] == ["t1", "t2"]  # neither era's rows dropped
    assert [got[0][c] for c in TU_ERA_COLS] == [None] * 4
    assert [got[1][c] for c in TU_ERA_COLS] == [1, 42, 1786482000, 1786482001]
