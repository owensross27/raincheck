"""The one SparkSession factory (spec A / research 07). Every Spark config line lives here;
batch jobs, the streaming job and pytest all call session().

Runtime: Spark 3.5.3 + Sedona 1.9.1 in-process from the repo venv on the brew JDK 17.
JAVA_HOME and TZ=UTC come from the Makefile / .env, never `brew link`; java_home() only
falls back to the keg path so a bare `pytest` still finds the JVM on this Mac.

On the cluster (cloud 03) the same function runs unchanged, steered by environment only -
no forked session builder, because a second SparkSession factory is a second set of Spark
semantics: RAINCHECK_SPARK_MASTER (a 2-vCPU t4g.large is not `local[6]`),
RAINCHECK_SPARK_DRIVER_MEM, and AWS_ENDPOINT_URL (present => configure s3a for R2, spec
sec.3 "every table read and written over s3a://"). The jars are BAKED into the image's
SPARK_HOME/jars, so `spark.jars.packages` is dropped entirely there: resolving from Maven
Central per pod is a recurring bill and a standing outage dependency, and it only looks
free on this Mac because ~/.ivy2 is warm.
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


def jars_baked() -> bool:
    """True when EVERY package below already sits on Spark's default classpath (the image
    copies them into SPARK_HOME/jars). Detected rather than declared: a knob can be
    forgotten, and the failure mode of a wrong knob is a silent per-pod Maven resolve. All
    of them, not just Sedona - baking one and dropping `spark.jars.packages` would lose the
    others. Ivy prefixes the groupId onto the filename, hence the leading `*`."""
    import pyspark
    jars = Path(pyspark.__file__).parent / "jars"
    return all(any(jars.glob(f"*{p.split(':')[1]}-*.jar")) for p in PACKAGES)


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
    master = os.environ.get("RAINCHECK_SPARK_MASTER") or "local[6]"
    builder = (
        SedonaContext.builder()
        .appName("raincheck")
        .master(master)
        .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
        .config("spark.kryo.registrator", "org.apache.sedona.core.serde.SedonaKryoRegistrator")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.parquet.outputTimestampType", "TIMESTAMP_MICROS")
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")  # 07: batch idempotence
        .config("spark.driver.extraJavaOptions", "-Duser.timezone=UTC")
        .config("spark.driver.memory", os.environ.get("RAINCHECK_SPARK_DRIVER_MEM") or "3g")
        .config("spark.sql.shuffle.partitions", "16")
        # 07/12: the streaming job runs two queries in one app - FIFO lets a 62k-row TU
        # batch starve VP. Read at SparkContext start, so it belongs here, not on the query;
        # with one job in flight (every batch target) it is FIFO anyway.
        .config("spark.scheduler.mode", "FAIR")
        .config("spark.ui.enabled", str(ui).lower())
    )
    if master.startswith("local"):
        # local mode only: the Mac's hostname may resolve to a stale LAN IP. In cluster or
        # client mode against k8s:// this pin is a bug - executors would dial 127.0.0.1 and
        # never reach the driver - and spark-submit already sets the right address.
        builder = (builder.config("spark.driver.bindAddress", "127.0.0.1")
                          .config("spark.driver.host", "127.0.0.1"))
    if not jars_baked():
        builder = builder.config("spark.jars.packages", ",".join(PACKAGES))
    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if endpoint:  # R2 over s3a (cloud 03/07). Credentials come from the r2-build Secret
        builder = (  # via envFrom, so the env provider - never a key in a config line.
            builder.config("spark.hadoop.fs.s3a.endpoint", endpoint)
            .config("spark.hadoop.fs.s3a.path.style.access", "true")
            .config("spark.hadoop.fs.s3a.aws.credentials.provider",
                    "org.apache.hadoop.fs.s3a.auth.EnvironmentVariableCredentialsProvider")
            # R2 has no regions and rejects AWS's default v4 signing region probe
            .config("spark.hadoop.fs.s3a.endpoint.region", os.environ.get("AWS_DEFAULT_REGION") or "auto"))
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
