# 03 Zarr to Spark/Sedona bridge

Type: research
Status: resolved

## Question

Sedona 1.9.1 does not (believed, confirm) read Zarr natively. What is the practical
bridge on Spark 3.5.3 local mode: xarray-select-to-DataFrame vector join, hourly COG
GeoTIFF + RS_ZonalStats, kerchunk/VirtualiZarr, or something else? Also: which raster
capabilities are OSS Sedona vs WherobotsDB-only (portfolio-relevant), and the robust
Structured Streaming pattern for enriching a Kafka point stream with a slowly-changing
hourly precip grid (broadcast lookup vs stream-static join).

## Answer

Resolved 2026-08-15 by research subagent (full report:
[research/03-zarr-spark-sedona-bridge-full.md](../../../research/03-zarr-spark-sedona-bridge-full.md)).

**Verdict: no raster engine needed. xarray does the Zarr work, Sedona does the vector work.**

- Sedona 1.9.1 does NOT read Zarr in any path (confirmed at the sedona-1.9.1 tag;
  the only Zarr roadmap lives in apache/sedona-db, the separate Rust engine, not the
  Spark library). Raster constructors are in-db byte-array only (RS_FromGeoTiff,
  RS_FromNetCDF); no out-db rasters in OSS Sedona.
- The bridge is pattern (a): xarray .sel() the NYC bbox (~53 x 67 = ~3,500 cells,
  smaller than ONE AORC chunk) -> to_dataframe() -> spark.createDataFrame -> plain
  Sedona vector joins. Building a COG/RS_ZonalStats path for a 3,500-cell slice is
  over-engineering; use RS_Value/RS_ZonalStats only if polygon catchment aggregation
  arrives later.
- kerchunk / VirtualiZarr / icechunk: NO Spark/JVM connector exists (icechunk FAQ
  confirms Python/Rust/JS bindings only). They optimize the xarray step, nothing else.
- Streaming enrichment: documented stream-static join, stateless, no watermark. Keep
  the static side UNCACHED so each micro-batch re-resolves the hourly-overwritten
  precip Parquet/Delta table (.cache() pins stale data, the standard footgun). At
  ~3,500 rows Spark auto-broadcasts; no hand-rolled broadcast machinery.
- Portfolio boundary (Wherobots): Havasu spec is Apache-2.0 but reader/writer is
  WherobotsDB-only; Raster Inference is Wherobots-exclusive. OSS Sedona demonstrates
  RS_*/ST_ interop, zonal stats, spatial joins, 100% API-compatible per their docs.
- CORRECTIONS to prior assumptions: **Java 11** for Spark 3.5 (17 is Spark 4.x), and
  this Mac has NO JVM installed at all (quakestream ran Spark in Docker). Maven pair
  sedona-spark-shaded-3.5_2.12:1.9.1 + geotools-wrapper:1.9.1-33.5 confirmed on
  Central. Pin pyspark==3.5.3 explicitly, skip the [spark] extra.
- RasterFrames is stale (last release 2023); GeoTrellis alive but irrelevant here.

## Comments

2026-08-16, from [07 Enrichment execution model](07-enrichment-execution-model.md): two
corrections to the Answer. (1) "Java 11 not 17" is wrong for Spark 3.5: the 3.5.3 docs
say "Spark runs on Java 8/11/17" and PySpark's launcher adds the JDK 17 module opens
itself; measured on this Mac, Spark 3.5.3 + Sedona 1.9.1 run natively on the brew
`openjdk@17` already installed (Sedona's platform matrix pairs Spark 3.5 with Java 11;
every ST_/RS_/GeoParquet/Kafka path ran clean on 17). No JVM install was needed after
all. (2) "Raster constructors are in-db byte-array only (RS_FromGeoTiff, RS_FromNetCDF)"
is incomplete: 1.9.1 exposes 102 RS_ functions including `RS_MakeEmptyRaster`,
`RS_AddBandFromArray`, `RS_MakeRaster`, so an in-db raster can be built from the AORC
slice without a GeoTIFF round trip (10's Product 3). Also: "keep the static side
uncached" is necessary but not sufficient - a DataFrame built once from a path keeps
its file index; the `spark.read` must sit inside the `foreachBatch` callback (measured).
