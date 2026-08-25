"""Cloud ticket 11: content equality between two builds of one partitioned table. What the
digest must ignore (writer, part layout, row order, column order) and what it must never
ignore (one changed value, a partition only one side has, an empty partition).
JVM-free except the two-Spark-sessions test, which is the one claim only a second JVM can
make - it skips with the shared spark fixture when no JVM is found."""
import os
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raincheck import parity

# a null, a float, a duplicate row and two partitions: coalesce, VARCHAR casting and the
# duplicate-safety of hashing every row (an xor fold would cancel the pair)
ROWS = [
    {"service_date": "2026-08-01", "vehicle_id": "a", "delay_s": 12.5, "route": "B41"},
    {"service_date": "2026-08-01", "vehicle_id": "b", "delay_s": None, "route": "B41"},
    {"service_date": "2026-08-01", "vehicle_id": "b", "delay_s": None, "route": "B41"},
    {"service_date": "2026-08-02", "vehicle_id": "c", "delay_s": -3.0, "route": "Q59"},
]
COLS = ["service_date", "vehicle_id", "delay_s", "route"]


def write(root: Path, rows: list[dict], cols: list[str] | None = None, **kw) -> Path:
    """rows as a Hive service_date= table, one part file per partition unless kw says else."""
    cols = cols or COLS
    for d in sorted({r["service_date"] for r in rows}):
        part = [r for r in rows if r["service_date"] == d]
        table = pa.table({c: [r[c] for r in part] for c in cols if c != "service_date"})
        out = root / f"service_date={d}"
        out.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, out / "part-00.parquet", **kw)
    return root


def test_row_and_column_order_do_not_change_the_digest(tmp_path):
    a = write(tmp_path / "a", ROWS)
    b = write(tmp_path / "b", list(reversed(ROWS)), cols=list(reversed(COLS)))
    assert parity.digest(a) == parity.digest(b)
    assert parity.compare(a, b).ok


def test_part_layout_and_compression_do_not_change_the_digest(tmp_path):
    """The JVM-free half of the footer-permutation case: same rows, different bytes."""
    a = write(tmp_path / "a", ROWS, compression="snappy")
    b = write(tmp_path / "b", ROWS, compression="gzip", row_group_size=1)
    for i, row in enumerate(ROWS[:2]):  # and split one partition across three more parts
        table = pa.table({c: [row[c]] for c in COLS if c != "service_date"})
        pq.write_table(table, b / "service_date=2026-08-01" / f"extra-{i}.parquet")
    for i, row in enumerate(ROWS[:2]):
        table = pa.table({c: [row[c]] for c in COLS if c != "service_date"})
        pq.write_table(table, a / "service_date=2026-08-01" / f"extra-{i}.parquet")
    assert {p.read_bytes() for p in a.rglob("*.parquet")} != {p.read_bytes()
                                                              for p in b.rglob("*.parquet")}
    assert parity.digest(a) == parity.digest(b)


def test_a_single_changed_value_changes_the_digest(tmp_path):
    changed = [{**ROWS[0], "delay_s": 12.6}] + ROWS[1:]
    a, b = write(tmp_path / "a", ROWS), write(tmp_path / "b", changed)
    report = parity.compare(a, b)
    assert not report.ok
    assert report.differing == ["service_date=2026-08-01"]
    assert report.matching == ["service_date=2026-08-02"]
    assert "same 3 rows, sha" in "\n".join(report.lines())


def test_a_null_is_not_a_missing_field(tmp_path):
    """coalesce, not concat_ws: ("b", NULL) and (NULL, "b") must not collide."""
    a, b = tmp_path / "a", tmp_path / "b"
    for root, row in ((a, {"vehicle_id": "b", "route": None}),
                      (b, {"vehicle_id": None, "route": "b"})):
        part = root / "service_date=2026-08-01"
        part.mkdir(parents=True)
        pq.write_table(pa.table({c: pa.array([row[c]], type=pa.string()) for c in row}),
                       part / "part-00.parquet")
    assert parity.digest(a) != parity.digest(b)


def test_a_partition_on_one_side_only_is_reported_loudly(tmp_path):
    a = write(tmp_path / "a", ROWS)
    b = write(tmp_path / "b", [r for r in ROWS if r["service_date"] == "2026-08-01"])
    report = parity.compare(a, b)
    assert not report.ok
    assert report.only_in_a == ["service_date=2026-08-02"] and report.only_in_b == []
    assert "MISSING ON B  service_date=2026-08-02  rows=1" in report.lines()
    assert "NOT EQUAL" in str(report)
    # and the same absence seen from the other side, never silently dropped
    back = parity.compare(b, a)
    assert back.only_in_b == ["service_date=2026-08-02"] and not back.ok
    assert "MISSING ON A  service_date=2026-08-02  rows=1" in back.lines()


def test_an_empty_partition_is_not_a_missing_one(tmp_path):
    a = write(tmp_path / "a", ROWS)
    (a / "service_date=2026-08-03").mkdir()                       # empty: dir, no parts
    b = write(tmp_path / "b", ROWS)
    (b / "service_date=2026-08-04").mkdir()
    pq.write_table(pa.table({c: pa.array([], type=pa.string()) for c in COLS[1:]}),
                   b / "service_date=2026-08-04" / "part-00.parquet")  # empty: a 0-row part
    da, db = parity.digest(a), parity.digest(b)
    assert da["service_date=2026-08-03"] == (0, parity.EMPTY)
    assert db["service_date=2026-08-04"] == (0, parity.EMPTY)
    report = parity.compare(a, b)
    assert not report.ok  # an empty partition present on one side is still a difference
    assert report.only_in_a == ["service_date=2026-08-03"]
    assert report.only_in_b == ["service_date=2026-08-04"]
    assert "MISSING ON B  service_date=2026-08-03  rows=0" in report.lines()


def test_an_unpartitioned_root_is_its_own_partition(tmp_path):
    """Two tables with no Hive dirs must not compare equal by both having no partitions."""
    a, b = tmp_path / "a", tmp_path / "b"
    for root, rows in ((a, ROWS), (b, ROWS[:1])):
        root.mkdir()
        pq.write_table(pa.table({c: [r[c] for r in rows] for c in COLS}), root / "p.parquet")
    assert list(parity.digest(a)) == [""]
    assert not parity.compare(a, b).ok


# --- cloud 03: the same gate against an R2 prefix ---------------------------------------

def test_a_remote_root_is_recognised_by_either_scheme():
    """The cluster writes s3a:// (Spark's spelling) and DuckDB reads s3://. Both name the
    same object store, so the gate takes whichever spelling the writing side used - and a
    local path stays local, which is what keeps the Mac side going through rglob."""
    assert parity.remote("s3://b/silver/events") == "s3://b/silver/events"
    assert parity.remote("s3a://b/silver/events/") == "s3://b/silver/events"
    assert parity.remote(Path("/data/silver/events")) is None
    assert parity.remote("/data/s3a://not-a-scheme") is None


def test_an_unreachable_remote_side_is_inconclusive_never_equal(tmp_path, monkeypatch):
    """The failure mode this gate exists to survive. A credential that is absent, expired
    or scoped to the wrong bucket must read as "could not check" - rc 2 - because rendering
    it as a pass would let the T17 backfill start on a comparison that never happened."""
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://127.0.0.1:1")  # nothing listens there
    local = write(tmp_path / "a", ROWS)
    assert parity.main(["s3://raincheck-bronze/silver/events", str(local)]) == 2
    assert parity.main([str(local), "s3://raincheck-bronze/silver/events"]) == 2


def test_main_returns_zero_one_two(tmp_path, capsys):
    a, b = write(tmp_path / "a", ROWS), write(tmp_path / "b", ROWS)
    assert parity.main([str(a), str(b)]) == 0
    assert "EQUAL: 2 partitions match" in capsys.readouterr().out
    (b / "service_date=2026-08-02" / "part-00.parquet").unlink()
    assert parity.main([str(a), str(b)]) == 1
    assert parity.main([str(a), str(tmp_path / "nope")]) == 2  # unreadable side: never "ok"
    assert parity.main([str(a)]) == 2
    (b / "service_date=2026-08-01" / "part-00.parquet").write_bytes(b"not parquet")
    assert parity.main([str(a), str(b)]) == 2  # unreadable data is inconclusive, not "differ"


SPARK_WRITE = """
import sys
from raincheck.spark import session
s = session()
s.createDataFrame({rows!r}).write.partitionBy("service_date").parquet(sys.argv[1])
s.stop()
"""


def test_two_spark_sessions_digest_equal(tmp_path, spark):
    """The headline case byte comparison fails: parquet-mr permutes footer encoding order
    across JVM sessions, so `make daily` and a cluster run differ in bytes on identical
    data. Second session is a real second JVM - newSession() would share this one."""
    a, b = tmp_path / "a", tmp_path / "b"
    spark.createDataFrame(ROWS).write.partitionBy("service_date").parquet(str(a))
    env = {**os.environ, "PYTHONPATH": str(Path(parity.__file__).parents[1])}
    subprocess.run([sys.executable, "-c", SPARK_WRITE.format(rows=ROWS), str(b)],
                   env=env, check=True, cwd=tmp_path)
    same_bytes = ({p.read_bytes() for p in a.rglob("*.parquet")}
                  == {p.read_bytes() for p in b.rglob("*.parquet")})
    assert parity.digest(a) == parity.digest(b), f"(parquet bytes identical: {same_bytes})"
    assert parity.compare(a, b).ok


def test_a_shadow_is_compared_at_the_partition_level_and_never_at_the_table_root(tmp_path):
    """cloud 13's measurement, as a test, because orchestration 11's shadow is the caller
    that would get it wrong: a shadow root holds the day it staged and nothing else, so a
    compare rooted on the TABLE lists every partition the Mac also holds as missing and can
    never be `ok` - a red verdict that says nothing about the day under test. Rooted on the
    PARTITION, the same two trees are equal.

    Note WHICH property fails: not "the shas differ" but "only_in_b is non-empty", which is
    also why `Report.ok` is three conditions and not one."""
    mac = write(tmp_path / "mac", ROWS)                       # two service dates
    shadow = write(tmp_path / "shadow", [r for r in ROWS if r["service_date"] == "2026-08-01"])
    table = parity.compare(shadow, mac)
    assert not table.ok
    assert table.only_in_b == ["service_date=2026-08-02"] and table.differing == []
    day = "service_date=2026-08-01"
    assert parity.compare(shadow / day, mac / day).ok
