"""The DuckDB read-back helper (spec A / 09): the analysis and test oracle for every table.
Every session runs UTC; readers open a dataset root as **/*.parquet (never single parts,
never **/*: Spark's .crc sidecars) with Hive partition keys read back as strings.
union_by_name: Bronze mixes part schemas within one date (pre-07 archiver parts lack
schedule_relationship; gapfill/post-restart parts have it) - missing columns read NULL.

`table()` has always taken `Path | str`, so it reads an R2 prefix as happily as a local
directory - what was missing was the connection. connect() now configures httpfs from the
environment whenever AWS_ENDPOINT_URL is set, the same one switch spark.py's s3a branch
reads [cloud 03], so every DuckDB stage follows a `s3a://` data root without a fork
[cloud 12]. Unset (the Mac's default) and nothing changes."""
import os
from pathlib import Path

import duckdb


def r2(con: duckdb.DuckDBPyConnection) -> None:
    """Point a connection's httpfs at R2 from the environment. PROVIDER credential_chain /
    CHAIN 'env' - DuckDB reads AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY itself, so the
    token never appears in a SQL string, in argv or in a traceback. URL_STYLE path because
    R2 does not do virtual-host buckets, and REGION because R2 has none but the v4
    signature still needs one. Idempotent: INSTALL is a no-op once installed (the image
    bakes it) and the secret is CREATE OR REPLACE."""
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    host = (os.environ.get("AWS_ENDPOINT_URL") or "").split("://")[-1].rstrip("/")
    region = os.environ.get("AWS_DEFAULT_REGION") or "auto"
    con.execute("CREATE OR REPLACE SECRET raincheck_r2 (TYPE s3, PROVIDER credential_chain,"
                f" CHAIN 'env', ENDPOINT '{host}', URL_STYLE 'path', REGION '{region}')")


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    if os.environ.get("AWS_ENDPOINT_URL"):
        r2(con)
    return con


def table(con: duckdb.DuckDBPyConnection, root: Path | str) -> duckdb.DuckDBPyRelation:
    return con.sql(  # the Python read_parquet() has no hive_types_autocast knob (1.5.5)
        "SELECT * FROM read_parquet(?, hive_partitioning = true, hive_types_autocast = false, "
        "union_by_name = true)",
        params=[f"{root}/**/*.parquet"],
    )
