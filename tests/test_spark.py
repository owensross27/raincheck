"""07-1: the session factory on this stack (Spark 3.5.3 + Sedona 1.9.1 on the brew JDK 17).
Skips as a whole when no JVM is found (conftest)."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from raincheck import duck, spark as rspark


def test_java_home_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("JAVA_HOME", str(tmp_path))
    assert rspark.java_home() is None  # set but no bin/java: no JVM found -> tests skip
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "java").touch()
    assert rspark.java_home() == str(tmp_path)


def test_session_is_the_pinned_stack(spark):
    assert spark.version == "3.5.3"
    conf = spark.conf
    assert conf.get("spark.sql.session.timeZone") == "UTC"
    assert conf.get("spark.sql.parquet.outputTimestampType") == "TIMESTAMP_MICROS"
    assert conf.get("spark.sql.sources.partitionOverwriteMode") == "dynamic"
    assert conf.get("spark.sql.shuffle.partitions") == "16"
    assert conf.get("spark.ui.enabled") == "false"
    assert conf.get("spark.kryo.registrator") == "org.apache.sedona.core.serde.SedonaKryoRegistrator"
    assert spark.sparkContext.master == "local[6]"
    (tz,) = spark.sql("SELECT java_method('java.util.TimeZone', 'getDefault')").first()
    assert "UTC" in str(tz)  # -Duser.timezone=UTC reached the driver JVM


def test_h3_cell_of_central_park(spark):
    (cell,) = spark.sql("SELECT ST_H3CellIDs(ST_Point(-73.965, 40.782), 8, false)[0]").first()
    assert isinstance(cell, int) and f"{cell:x}" == "882a100895fffff"  # 09: INT64 Cell


def test_times_square_axis_gate(spark):
    """09: EPSG:2263 ftUS -> 4326 lon/lat within 1e-4 and not swapped (axis order, not datum)."""
    (x, y) = spark.sql(
        "SELECT ST_X(g), ST_Y(g) FROM (SELECT ST_Transform(ST_Point(988267.1, 215436.9), "
        "'EPSG:2263', 'EPSG:4326') AS g)"
    ).first()
    assert x == pytest.approx(-73.9855, abs=1e-4)
    assert y == pytest.approx(40.7580, abs=1e-4)


def test_pandas_round_trip(spark):
    pdf = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    assert spark.createDataFrame(pdf).toPandas().equals(pdf)  # the distutils/setuptools trap


def test_partitioned_write_reads_back_utc_in_duckdb(spark, tmp_path):
    """Seam A handshake: Spark writes a Hive-partitioned root, DuckDB reads it with string
    partition keys and the same UTC instant (TIMESTAMP_MICROS, both sessions UTC)."""
    root = tmp_path / "t"
    spark.sql(
        "SELECT '2026-08-11' AS date, '20' AS hour, timestamp'2026-08-11 20:00:00' AS ts, 1 AS n"
    ).write.partitionBy("date", "hour").parquet(str(root))
    con = duck.connect()
    rel = duck.table(con, root)
    assert dict(zip(rel.columns, map(str, rel.types))) == {
        "ts": "TIMESTAMP WITH TIME ZONE", "n": "INTEGER", "date": "VARCHAR", "hour": "VARCHAR",
    }
    assert rel.fetchall() == [
        (datetime(2026, 8, 11, 20, tzinfo=timezone.utc), 1, "2026-08-11", "20"),
    ]
