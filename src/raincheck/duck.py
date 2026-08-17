"""The DuckDB read-back helper (spec A / 09): the analysis and test oracle for every table.
Every session runs UTC; readers open a dataset root as **/*.parquet (never single parts,
never **/*: Spark's .crc sidecars) with Hive partition keys read back as strings."""
from pathlib import Path

import duckdb


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    return con


def table(con: duckdb.DuckDBPyConnection, root: Path | str) -> duckdb.DuckDBPyRelation:
    return con.sql(  # the Python read_parquet() has no hive_types_autocast knob (1.5.5)
        "SELECT * FROM read_parquet(?, hive_partitioning = true, hive_types_autocast = false)",
        params=[f"{root}/**/*.parquet"],
    )
