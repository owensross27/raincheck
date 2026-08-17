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
