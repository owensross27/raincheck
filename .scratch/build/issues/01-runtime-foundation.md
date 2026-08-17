# 01 — Runtime foundation: session factory, pins, data root, test infra

**What to build:** An implementer can run `make warm && pytest` on this Mac and get a green suite that
includes a real Spark 3.5.3 + Sedona 1.9.1 session from the repo venv on the brew JDK 17,
with every later job able to import one `session()` factory and one DuckDB read-back
helper. Prefactoring: the running archiver honours `RAINCHECK_ARCHIVE_ROOT` (default the
repo data dir) so Bronze/Silver/live can move to the external SSD, and `RAINCHECK_BRONZE_GB`
is documented as an absolute byte count over that root (moving the root does not shrink it).
Spec: Implementation Decisions A; Testing Decisions (seams, tiers).

**Blocked by:** None — can start immediately

**Status:** resolved

- [x] pyproject pins pyspark==3.5.3, apache-sedona==1.9.1, setuptools, shapely, pyproj, duckdb, pytz (no Python h3); `make warm` warms the Ivy cache once with the three Maven coordinates (Sedona spark-shaded 3.5/2.12 1.9.1, geotools-wrapper 1.9.1-33.5, spark-sql-kafka 3.5.3)
- [x] `JAVA_HOME` and `TZ=UTC` come from the Makefile / `.env`, never `brew link`; `raincheck.spark.session()` is the only place the Spark config is written (Kryo + SedonaKryoRegistrator, session timezone UTC, TIMESTAMP_MICROS, partitionOverwriteMode=dynamic, driver -Duser.timezone=UTC, local[6], 3 g driver, 16 shuffle partitions, UI off with a flag)
- [x] check 07-1 passes: `ST_H3CellIDs` of Central Park = 882a100895fffff, Times Square EPSG:2263 -> 4326 within 1e-4 and not swapped, a pandas DataFrame round-trips through Spark
- [x] a session-scoped Spark pytest fixture exists and Spark tests skip (not fail) when no JVM is found; a DuckDB helper opens a dataset root and sets TimeZone UTC
- [x] the archiver reads its root from `RAINCHECK_ARCHIVE_ROOT` (default unchanged) and its budget from `RAINCHECK_BRONZE_GB`; the existing decoder/archiver tests still pass under a temp root

## Comments

**2026-08-17 (implemented).** Files: `pyproject.toml` (pins), `Makefile` (`warm`, `test`;
exports `JAVA_HOME ?= brew keg`, `TZ := UTC`, passes `RAINCHECK_ARCHIVE_ROOT` /
`RAINCHECK_BRONZE_GB` through from the shell or `.env`, empty meaning default because
GNU make 3.81 exports a declared-but-unset variable as empty), `src/raincheck/spark.py`
(`java_home()`, `PACKAGES`, `session(ui=False)`), `src/raincheck/duck.py` (`connect()`,
`table(con, root)`: `**/*.parquet`, Hive keys as VARCHAR via `hive_types_autocast=false`),
`src/raincheck/paths.py` (`data_root()`), `src/raincheck/archiver.py` (`ROOT = data_root()
/ "archive"`, budget docstring, stop message), `tests/conftest.py` (session-scoped `spark`
fixture, skips when `java_home()` is None), `tests/test_spark.py` (07-1 + pinned
conventions + a Spark-write / DuckDB-read UTC handshake), `tests/test_duck.py`,
`tests/test_feeds.py` (env root/budget in a fresh interpreter), `launchd/...plist`
(comment: the SSD-step env block). 20 tests green via `make test` and bare `pytest`;
`JAVA_HOME=/nonexistent pytest` skips the five Spark cases with a message.

Two runtime traps not in research 07, both fixed inside `session()` (the one config site):
(1) PySpark workers take `python3` from PATH (miniconda 3.13 here) and die with
`PYTHON_VERSION_MISMATCH` against the 3.12 driver — the factory sets `PYSPARK_PYTHON` to
`sys.executable`; (2) this Mac's hostname `Mac.home.local` currently resolves to a stale
LAN IP (.161 vs the interface's .149), so Spark's default driver bind fails with
`BindException` after 16 retries — the factory pins `spark.driver.bindAddress` and
`spark.driver.host` to 127.0.0.1 (local mode never needs a routable driver address).
Also: DuckDB 1.5.5's Python `read_parquet()` has no `hive_types_autocast` argument, so the
helper goes through parameterised SQL. Ivy was already warm from quakestream (13 artifacts
retrieved, 0 downloaded; `make warm` 5 s). The archiver LaunchAgent was not restarted; the
default root is unchanged so the running process is unaffected.
