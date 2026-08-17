# 01 — Runtime foundation: session factory, pins, data root, test infra

**What to build:** An implementer can run `make warm && pytest` on this Mac and get a green suite that
includes a real Spark 3.5.3 + Sedona 1.9.1 session from the repo venv on the brew JDK 17,
with every later job able to import one `session()` factory and one DuckDB read-back
helper. Prefactoring: the running archiver honours `RAINCHECK_ARCHIVE_ROOT` (default the
repo data dir) so Bronze/Silver/live can move to the external SSD, and `RAINCHECK_BRONZE_GB`
is documented as an absolute byte count over that root (moving the root does not shrink it).
Spec: Implementation Decisions A; Testing Decisions (seams, tiers).

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] pyproject pins pyspark==3.5.3, apache-sedona==1.9.1, setuptools, shapely, pyproj, duckdb, pytz (no Python h3); `make warm` warms the Ivy cache once with the three Maven coordinates (Sedona spark-shaded 3.5/2.12 1.9.1, geotools-wrapper 1.9.1-33.5, spark-sql-kafka 3.5.3)
- [ ] `JAVA_HOME` and `TZ=UTC` come from the Makefile / `.env`, never `brew link`; `raincheck.spark.session()` is the only place the Spark config is written (Kryo + SedonaKryoRegistrator, session timezone UTC, TIMESTAMP_MICROS, partitionOverwriteMode=dynamic, driver -Duser.timezone=UTC, local[6], 3 g driver, 16 shuffle partitions, UI off with a flag)
- [ ] check 07-1 passes: `ST_H3CellIDs` of Central Park = 882a100895fffff, Times Square EPSG:2263 -> 4326 within 1e-4 and not swapped, a pandas DataFrame round-trips through Spark
- [ ] a session-scoped Spark pytest fixture exists and Spark tests skip (not fail) when no JVM is found; a DuckDB helper opens a dataset root and sets TimeZone UTC
- [ ] the archiver reads its root from `RAINCHECK_ARCHIVE_ROOT` (default unchanged) and its budget from `RAINCHECK_BRONZE_GB`; the existing decoder/archiver tests still pass under a temp root
