# raincheck

Does rain slow the buses? NYC MTA bus GTFS-RT -> Kafka -> Spark/Sedona spatial
enrichment, joined against NOAA AORC 1km hourly precipitation (cloud Zarr).

- Plan: `.scratch/pipeline/map.md` (wayfinder map + tickets); build spec and tickets: `.scratch/build/`
- Feed facts: `~/vault/nyc-mta-bus-feeds-reference.md`

## Runtime

Spark 3.5.3 + Sedona 1.9.1 run in-process from the repo venv on the brew `openjdk@17`
(`brew install openjdk@17`, never `brew link`). The Makefile exports `JAVA_HOME` and
`TZ=UTC`; `.env` (gitignored) may override `JAVA_HOME` and set `RAINCHECK_ARCHIVE_ROOT`
(the data root, default `data/`; the external SSD in practice) and `RAINCHECK_BRONZE_GB`
(the archiver's absolute byte budget over `<root>/archive`, default 10; moving the root
does not shrink the count, so size it to the drive). `raincheck.spark.session()` is the
only place Spark is configured; `raincheck.duck` is the DuckDB read-back helper.

```bash
uv venv .venv && uv pip install -e .
make warm       # one session through the factory: warms the Ivy cache (~240 MB, once)
make test       # pytest; Spark tests skip when no JVM is found
```

## Smoke slice

```bash
docker compose up -d --wait
.venv/bin/python -m raincheck.producer --once      # real poll -> Kafka
.venv/bin/python -m raincheck.archiver --once      # real poll -> Parquet
.venv/bin/python -m raincheck.zarr_probe           # AORC Zarr vs Hurricane Ida
.venv/bin/pytest -q                                # frozen-fixture checks
```
