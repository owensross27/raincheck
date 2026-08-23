"""The one SparkSession factory (spec A / research 07). Every Spark config line lives here;
batch jobs, the streaming job and pytest all call session().

Runtime: Spark 3.5.3 + Sedona 1.9.1 in-process from the repo venv on the brew JDK 17.
JAVA_HOME and TZ=UTC come from the Makefile / .env, never `brew link`; java_home() only
falls back to the keg path so a bare `pytest` still finds the JVM on this Mac.
"""
import os
import sys
import time
from pathlib import Path

from pyspark.sql import SparkSession
from sedona.spark import SedonaContext

BREW_JDK = "/opt/homebrew/opt/openjdk@17"
PACKAGES = (
    "org.apache.sedona:sedona-spark-shaded-3.5_2.12:1.9.1",
    "org.datasyslab:geotools-wrapper:1.9.1-33.5",
    "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3",
)


def java_home() -> str | None:
    """JAVA_HOME if set, else the brew keg; None when neither holds a bin/java (no JVM found)."""
    home = os.environ.get("JAVA_HOME") or BREW_JDK
    return home if Path(home, "bin", "java").is_file() else None


def session(ui: bool = False) -> SparkSession:
    home = java_home()
    if home is None:
        raise RuntimeError("no JVM found: set JAVA_HOME (see Makefile) or brew install openjdk@17")
    os.environ["JAVA_HOME"] = home
    os.environ["PYSPARK_PYTHON"] = sys.executable  # workers run the venv, not PATH's python3 (3.13 here)
    os.environ.setdefault("TZ", "UTC")  # 07: collect() hands back driver-local naive datetimes
    time.tzset()
    builder = (
        SedonaContext.builder()
        .appName("raincheck")
        .master("local[6]")
        .config("spark.driver.bindAddress", "127.0.0.1")  # local mode; the Mac's hostname may resolve to a stale LAN IP
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.jars.packages", ",".join(PACKAGES))
        .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
        .config("spark.kryo.registrator", "org.apache.sedona.core.serde.SedonaKryoRegistrator")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.parquet.outputTimestampType", "TIMESTAMP_MICROS")
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")  # 07: batch idempotence
        .config("spark.driver.extraJavaOptions", "-Duser.timezone=UTC")
        .config("spark.driver.memory", "3g")
        .config("spark.sql.shuffle.partitions", "16")
        .config("spark.ui.enabled", str(ui).lower())
    )
    return SedonaContext.create(builder.getOrCreate())


def topic_schema(kind: str):
    """Kafka JSON schema for one bus topic (spec J / 07-6): one StructType per topic,
    derived from the decoder row shape (feeds.VP_COLS/TU_COLS) and the archiver's column
    types - never hand-maintained. The census test asserts it equals the decoder keys."""
    import pyarrow as pa
    from pyspark.sql.types import (BooleanType, DoubleType, LongType, StringType, StructField,
                                   StructType)

    from raincheck.archiver import TYPES
    from raincheck.feeds import TU_COLS, VP_COLS

    spark_of = {pa.int64(): LongType(), pa.float64(): DoubleType(), pa.bool_(): BooleanType()}
    cols = {"vp": VP_COLS, "tu": TU_COLS}[kind]
    # strict lookup: a TYPES entry this map does not know must KeyError in the census test,
    # never silently degrade to string; only TYPES-absent columns are strings
    return StructType([StructField(c, spark_of[TYPES[c]] if c in TYPES else StringType(), True)
                       for c in cols])
