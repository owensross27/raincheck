# raincheck

Does rain slow the buses? NYC MTA bus GTFS-RT -> Kafka -> Spark/Sedona spatial
enrichment, joined against NOAA AORC 1km hourly precipitation (cloud Zarr).

- Plan: `.scratch/pipeline/map.md` (wayfinder map + tickets)
- Feed facts: `~/vault/nyc-mta-bus-feeds-reference.md`

## Smoke slice

```bash
docker compose up -d --wait
uv venv .venv && uv pip install -e .
.venv/bin/python -m raincheck.producer --once      # real poll -> Kafka
.venv/bin/python -m raincheck.archiver --once      # real poll -> Parquet
.venv/bin/python -m raincheck.zarr_probe           # AORC Zarr vs Hurricane Ida
.venv/bin/pytest -q                                # frozen-fixture checks
```
