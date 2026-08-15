# Zarr-to-Sedona Bridge: Research Findings

Stack under test: Spark 3.5.3 + Apache Sedona 1.9.1, PySpark local mode, M4 Mac 16GB, Kafka. Sources are primary docs at the exact `sedona-1.9.1` git tag and Maven Central unless flagged otherwise. Unverified/inferred items are marked explicitly.

## TL;DR

- Sedona 1.9.1 does **not** read Zarr, in either raster path. Confirmed by absence in the 1.9.1 doc tree and source search. The only Zarr roadmap talk found lives in `apache/sedona-db`, a **separate, non-Spark, Rust-native engine** unrelated to the `sedona-spark-shaded` jar you're running.
- Pattern **(a) xarray -> pandas -> `spark.createDataFrame`** is trivially correct for AORC-over-NYC. Back-of-envelope: NYC bbox is ~53 x 67 cells at AORC's 30 arc-sec grid, roughly 3,500 cells, well under one AORC Zarr chunk (128 lat x 256 lon). Do not build a raster pipeline for this.
- kerchunk/VirtualiZarr/icechunk have **no Spark or JVM connector**, documented or otherwise. They are xarray/zarr-python/fsspec-side tools only.
- Havasu and WherobotsAI Raster Inference are **not** in open-source Sedona. Havasu's *spec* is Apache-2.0 and public; the reader/writer *implementation* lives only in WherobotsDB (commercial). Raster Inference is explicitly listed as Wherobots-exclusive on Wherobots' own comparison page.
- Stream-static join is the documented, stateless, first-class Structured Streaming pattern for this. It beats a hand-rolled broadcast+UDF at this data scale.
- Java version: **Java 11** for Spark 3.4/3.5, not 17 (17 is required only for Spark 4.0/4.1). This corrects the ticket's assumption.
- Your maven pairing (`sedona-spark-shaded-3.5_2.12:1.9.1` + `geotools-wrapper:1.9.1-33.5`) is confirmed published on Maven Central and is the docs-recommended (shaded) variant.

---

## 1. Sedona 1.9.1 raster IO

### Two engines, don't conflate them

Apache Sedona now ships two distinct products and the docs/GitHub search results mix them:

- **Classic Apache Sedona** (`org.apache.sedona:sedona-spark-shaded-3.5_2.12`), the JVM library extending Spark/Flink. This is what you're running. Raster functions are `RS_*` prefixed SQL functions.
- **SedonaDB** (`apache/sedona-db` on GitHub), a new native Rust query engine, standalone, not a Spark extension. This is where out-db raster constructs (`RS_FromPath`, found only in `docs/blog/posts/intro-sedonadb-0-4.md`) and Zarr planning live: [apache/sedona-db issue #746 "N-Dimensional Raster Type Extension"](https://github.com/apache/sedona-db/issues/746) and [issue #308 "Raster Read/Write GeoTiff Format"](https://github.com/apache/sedona-db/issues/308) (found via GitHub code/issue search, titles only, not independently fetched in full). Any Zarr-support roadmap chatter you find belongs to this engine, not the Spark one.

Grep of `apache/sedona` source for `RS_FromPath`, `OutDbRaster`, `"out-db"` (via `gh api search/code`) returned **zero matches** in the classic engine. Confirms: no out-db raster support in the Spark-based Sedona you're using.

### Raster constructors (in-db only)

Source: [`docs/api/sql/Raster-Constructors/RS_FromGeoTiff.md`](https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/api/sql/Raster-Constructors/RS_FromGeoTiff.md), [`RS_FromNetCDF.md`](https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/api/sql/Raster-Constructors/RS_FromNetCDF.md) at the `sedona-1.9.1` tag.

| Function | Signature | Notes |
|---|---|---|
| `RS_FromGeoTiff` | `RS_FromGeoTiff(bytes: ARRAY[Byte])` | Since v1.4.0. Loads full GeoTIFF bytes, in-DB. |
| `RS_FromNetCDF` | `RS_FromNetCDF(netCDF: ARRAY[Byte], recordVariableName: String)` and `RS_FromNetCDF(netCDF: ARRAY[Byte], recordVariableName: String, lonDimensionName: String, latDimensionName: String)` | NetCDF classic (1/2/5) and NetCDF4/HDF5. **No Zarr mention anywhere in this file.** |
| `RS_FromArcInfoAsciiGrid`, `RS_MakeEmptyRaster`, `RS_MakeRaster`, `RS_NetCDFInfo` | (full dir listing) | Same directory, all byte-array/in-memory constructors. |

Standard load pattern (from the doc):
```scala
val df = sedona.read.format("binaryFile").load("/some/path/*.tiff")
df.withColumn("raster", expr("RS_FromGeoTiff(content)"))
```

**In-db vs out-db**: every `RS_From*` constructor materializes pixel bytes into the DataFrame record. Confirmed in [`docs/tutorial/raster.md`](https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/tutorial/raster.md): *"The raster data source loads GeoTIFFs and automatically splits each file into tiles. Every tile becomes a row in a DataFrame with a Raster-typed column."* That auto-tiling exists specifically because full materialization risks Spark's 2GB single-record limit (added in 1.9.0 per release notes: *"Add a new raster data source reader that automatically tiles GeoTiffs to bypass Spark's 2GB record size limit"*). There is no lazy/pointer raster mode in this engine.

New in 1.9.1, useful for filtering large catalogs without paying pixel-decode cost: `geotiff.metadata` and `netcdf.metadata` data sources, one row per file, metadata only (CRS, dims, bands), no pixel array load.

### Zarr: confirmed NO

No `RS_FromZarr`, no Zarr mention in any raster constructor doc, no hit in source search. The only "Zarr coming" signal found is in the separate `sedona-db` repo's roadmap issue, not this engine, not this release, not scheduled.

### RS_ZonalStats / RS_ZonalStatsAll

Source: [`docs/api/sql/Raster-Band-Accessors/RS_ZonalStats.md`](https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/api/sql/Raster-Band-Accessors/RS_ZonalStats.md) at the `sedona-1.9.1` tag. Note the doc path itself: it's a **band accessor**, not in `Raster-Operators`.

```
RS_ZonalStats(raster: Raster, zone: Geometry, statType: String)
RS_ZonalStats(raster: Raster, zone: Geometry, band: Integer, statType: String)
RS_ZonalStats(raster: Raster, zone: Geometry, band: Integer, statType: String, allTouched: Boolean)
RS_ZonalStats(raster: Raster, zone: Geometry, band: Integer, statType: String, allTouched: Boolean, excludeNoData: Boolean)
RS_ZonalStats(raster: Raster, zone: Geometry, band: Integer, statType: String, allTouched: Boolean, excludeNoData: Boolean, lenient: Boolean)
```
Returns `Double`. `statType` in `count, sum, mean/average/avg, median, mode, stddev/sd, variance, min, max`. `allTouched` default `false` (centroid-intersection only). `excludeNoData` default `true`. `lenient` default `true` (non-intersecting raster/zone silently returns null/skips instead of throwing). CRS mismatch between `zone` and `raster` is auto-reprojected: *"If the coordinate reference system (CRS) of the input `zone` geometry differs from that of the `raster`, then `zone` will be transformed to match the CRS."* Available since v1.5.1.

**Point vs polygon**: the doc does not type-restrict `zone` beyond `Geometry`, but the function is semantically a zonal (area) aggregator. For point-based extraction there's a dedicated sibling function, [`RS_Value`](https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/api/sql/Raster-Operators/RS_Value.md):

```
RS_Value(raster: Raster, point: Geometry)
RS_Value(raster: Raster, point: Geometry, band: Integer)
RS_Value(raster: Raster, colX: Integer, colY: Integer, band: Integer)
```
The parameter is literally named `point`, returns `Double`, and auto-transforms CRS. **Practical rule for this ticket**: NYC lat/lon points against an hourly grid should use `RS_Value`/`RS_Values`, not `RS_ZonalStats` (that's for polygon catchments, buffer zones, etc.). Since you're not going the raster route anyway (see 2a), this is moot for the recommended pipeline, but matters if you ever add polygon-based catchment aggregation later.

### ST_ functions on grids

None. No `ST_*` function operates on the `Raster` type. Interop is one-directional: raster to geometry via `RS_Envelope(raster)` / `RS_ConvexHull(raster)`, after which you use ordinary `ST_Intersects`/`ST_Contains` on the resulting geometry. Confirmed via [`docs/api/sql/Raster-Functions.md`](https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/api/sql/Raster-Functions.md) overview: *"No ST_ prefixed functions are mentioned working on raster types."* Separately, 1.9.1 release notes add "distance joins for raster predicates" (`RS_DWithin` etc. in `Raster-Predicates/`), a spatial-join-optimizer feature, not an ST_ function.

### RS_MapAlgebra deprecated

Since 1.9.1, in favor of raster Python UDFs (`@udf` returning `RasterType()`, `.as_numpy()`, `.with_bands()`). Source: [`docs/api/sql/Raster-UDF.md`](https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/api/sql/Raster-UDF.md). Irrelevant to your pipeline if you follow the pattern-(a) recommendation below, flagging only because it's a live 1.9.1 change.

---

## 2. Bridge patterns, ranked

### (a) xarray/dask -> `.sel()` -> pandas -> `spark.createDataFrame` -> Sedona vector ops

**Yes, trivially correct for this use case.** Math:

AORC resolution is confirmed 30 arc-seconds (~800m, commonly rounded to "1km") per [registry.opendata.aws/noaa-nws-aorc](https://registry.opendata.aws/noaa-nws-aorc/). That's 1/120 degree per cell.

NYC bbox (commonly cited 5-borough extent, approximate: lat 40.48-40.92, lon -74.26 to -73.70, not independently surveyed here, mark as approximate):
- Δlat ≈ 0.44° -> ≈ 53 cells
- Δlon ≈ 0.56° -> ≈ 67 cells
- **≈ 3,500 grid cells total per hourly slice.** Your "roughly 60x60" is the right order of magnitude on both axes.

Confirmed AORC Zarr chunking (same source): 144 time steps x 128 lat x 256 lon per chunk, ~18MB/chunk. NYC's ~53x67 footprint is smaller than one spatial chunk (128x256); depending on chunk-boundary alignment (not verified here) you're pulling at most a small handful of ~18MB chunks per query window, not scanning CONUS. `.sel(time=..., latitude=slice(...), longitude=slice(...))` against `xr.open_zarr("s3://noaa-nws-aorc-v1-1-1km/...", storage_options={"anon": True})` then `.to_dataframe().reset_index()` -> `spark.createDataFrame(pdf)` is the entire "bridge." No raster engine, no COG, no Sedona raster functions needed. This is correct, not just convenient.

**Exact S3 path caveat (unverified)**: the registry page confirms the bucket ARN `arn:aws:s3:::noaa-nws-aorc-v1-1-1km` (`us-east-1`), but I could not pull the exact internal Zarr store key/prefix pattern (e.g. per-year store naming) from the NOAA-OWP jupyter-notebooks repo or NODD landing page directly; that repo's README describes the pipeline but the actual notebook code wasn't rendered in fetch. **Run `aws s3 ls --no-sign-request s3://noaa-nws-aorc-v1-1-1km/` before writing pipeline code** rather than trusting a guessed path.

When does this stop being trivial? When your bbox stops being NYC-sized: CONUS-wide or multi-state precip, where pulling everything into driver-side pandas breaks memory, is where you'd want distributed xarray (dask-on-Spark or Sedona raster) instead.

### (b) xarray -> rioxarray -> per-hour COG -> `RS_FromGeoTiff` + `RS_ZonalStats`

Confirmed pattern via rioxarray docs (WebSearch synthesis of [corteva.github.io/rioxarray](https://corteva.github.io/rioxarray/stable/examples/COG.html), not independently fetched verbatim, flagged): `da.rio.to_raster(path, driver='COG', compress='DEFLATE')`. Sedona side loads via `binaryFile` + `RS_FromGeoTiff`, or the newer auto-tiling `geotiff` data source (1.9.0+) for bulk directories.

**When it's worth it over (a):**
- You have genuinely large-area or multi-source raster layers (not a 3,500-cell NYC slice) where distributed raster ops on a Spark cluster actually pay off.
- You need raster-native ops beyond point/zone extraction: reprojection (`RS_ReprojectMatch`), map algebra across bands, raster-raster joins, tiling for downstream visualization.
- You already have a Sedona raster pipeline for other layers (satellite imagery, DEM) and want one code path instead of two.
- You need the raster **as an artifact** (versioned COGs for other consumers), not just as a value lookup.

For a single-variable, NYC-bbox, Kafka-enrichment use case, this is over-engineering: you'd be writing a file, then re-reading it, to do what `.sel()` does in one line. Skip it unless one of the above becomes true.

### (c) kerchunk/VirtualiZarr for Spark: fiction, confirmed

No documented Spark or JVM integration found for kerchunk, VirtualiZarr, or icechunk.

- **kerchunk**: builds JSON/Parquet "reference" files describing byte ranges inside archival formats (HDF5/NetCDF/GRIB), exposed through `fsspec.filesystem("reference")`, consumed by `zarr-python`/xarray. [fsspec/kerchunk docs](https://fsspec.github.io/kerchunk/) and [Advanced Topics](https://fsspec.github.io/kerchunk/advanced.html) describe this as Python/fsspec-only; the `ReferenceFileSystem` is explicitly async-oriented (`fsspec/filesystem_spec` discussion #1939, per WebSearch synthesis, not independently fetched). Nothing Spark-side consumes an `fsspec` reference filesystem natively.
- **VirtualiZarr**: [zarr-developers/VirtualiZarr](https://github.com/zarr-developers/VirtualiZarr) is explicitly xarray-syntax-scoped, feature-parity successor to kerchunk's combine logic, same Python/zarr-python target.
- **icechunk**: directly fetched [icechunk.io FAQ](https://icechunk.io/en/stable/understanding/faq/), confirmed official bindings are **Python, Rust, JavaScript/TypeScript only**: *"We welcome contributions from folks interested in developing Icechunk bindings for other languages"* implies no Spark/JVM binding exists yet. Recommended access path is explicitly Xarray: *"Xarray is the recommended way to read and write Icechunk data for Python users."*

**Verdict**: these tools are real and valuable for making cloud archival data (HDF5/NetCDF/GRIB) fast to open virtually as Zarr in xarray. They do not create a Spark ingestion path. If you use kerchunk, it speeds up the xarray step inside pattern (a); it does not become a new pattern for Spark.

### (d) Wherobots Raster Inference / Havasu: OSS/paid boundary

Directly relevant to your Wherobots portfolio angle.

- **Havasu**: spatial table format on Apache Iceberg. The **specification** is public and Apache-2.0 licensed: [github.com/wherobots/havasu](https://github.com/wherobots/havasu), confirmed via direct fetch: *"This repository contains the Havasu specification... A reader and writer implementation of Havasu table format specification is available in WherobotsDB."* **The implementation is WherobotsDB-only.** You cannot read/write Havasu tables from open-source Apache Sedona alone.
- **WherobotsDB vs Apache Sedona**: directly fetched [docs.wherobots.com/latest/apache-sedona](https://docs.wherobots.com/latest/apache-sedona/): *"Wherobots uses Apache Sedona as an open core to build a cloud data platform."* Features listed as **Wherobots-exclusive** (not in OSS Sedona): Spatial Data Lake Storage, Distributed Vector Tiles, Spatial AI, **Distributed Raster Inference**, Distributed Map Matching, managed deployment.
- **Raster Inference / RasterFlow**: WherobotsAI product, described as "serverless" (cloud-hosted). Uses open-source ML models under the hood (MLM spec for bring-your-own-model) but the inference **engine** (RasterFlow) is a Wherobots Cloud product, not an installable OSS component of Apache Sedona.

**Bottom line for the portfolio**: anything you build with open-source `sedona-spark-shaded` cannot demonstrate Havasu or Raster Inference, those require a WherobotsDB/Wherobots Cloud account. What you *can* demonstrate with pure OSS Sedona: raster/vector interop (`RS_*` + `ST_*`), zonal stats, spatial joins, the DataFrame API, all genuinely open-source and 100% API-compatible with what runs on WherobotsDB per their own compatibility claim.

---

## 3. Structured Streaming: enriching Kafka lat/lon with hourly precip

**Stream-static join is the documented, robust pattern.** Verified against the archived [Spark 3.5.1 Structured Streaming Programming Guide](https://downloads.apache.org/spark/docs/3.5.1/structured-streaming-programming-guide.html) (note: `spark.apache.org/docs/3.5.3/...` and `/3.5.1/`, `/3.5.0/` all 404 on the live site as of this research, current patch releases have superseded them there; `downloads.apache.org` still serves the archived 3.5.1 copy, content is stable across the 3.5.x line for this guide). Quoted from the fetched page:

> *"Note that stream-static joins are not stateful, so no state management is necessary. However, a few types of stream-static outer joins are not yet supported."*

Support matrix (paraphrased from the fetched table, consistent with known Spark behavior): stream (left) join static (right): inner and left-outer supported, right-outer and full-outer **not** supported. Static (left) join stream (right): inner and right-outer supported, left-outer **not** supported. No stateful join, no watermark required, this is exactly what you want for a slowly-changing side table against a fast Kafka stream.

**Refresh semantics** (the part the OSS guide doesn't spell out, confirmed against [Databricks: Work with joins](https://docs.databricks.com/aws/en/transform/join), Databricks-authored docs, underlying mechanism is vanilla Spark query replanning, not a Databricks-exclusive feature):

> *"When Databricks processes a micro-batch of data in a stream-static join, the latest valid version of data from the static Delta table joins with the records present in the current micro-batch."*
> *"If you update the static table between runs, re-processing the same streaming data can produce different results... because each micro-batch joins against the latest version of the static table at the time of processing."*

Mechanically: an **uncached** batch DataFrame (`spark.read.format("delta"/"parquet").load(path)`) gets its source re-resolved on every micro-batch trigger by Spark's incremental planner, so a side job that overwrites/appends the Parquet/Delta table each hour is picked up automatically, no stream restart. Calling `.cache()` on the static side defeats this (pins the old data) and is the standard footgun to avoid.

**Recommendation**: `streaming_kafka_df.join(spark.read.format("delta").load(nyc_precip_path), on=join_condition)` inside `foreachBatch`, with a separate hourly job overwriting `nyc_precip_path` (a ~3,500-row Delta/Parquet table). This is the documented, first-class pattern.

**Vs. hand-rolled broadcast/Arrow lookup**: technically viable (re-create a `sc.broadcast()` periodically, e.g. gated on batch id or a TTL check inside `foreachBatch`, use it in a pandas UDF for point-to-grid-cell lookup), but it's manual cache-invalidation code replacing something Spark's join planner already does for free. At ~3,500 rows there is no performance case for it (a Delta/Parquet static side this small is trivially broadcast-joined by Spark's own cost-based optimizer anyway, no `broadcast()` hint needed, Spark's `spark.sql.autoBroadcastJoinThreshold` will pick it up automatically). Use the stream-static join; skip the custom broadcast machinery unless you hit a demonstrated bottleneck.

---

## 4. Concrete versions

**Maven coordinates**, both confirmed to resolve on Maven Central at exactly these versions (fetched `central.sonatype.com` artifact pages directly, coordinates resolved rather than erroring):

```
org.apache.sedona:sedona-spark-shaded-3.5_2.12:1.9.1
org.datasyslab:geotools-wrapper:1.9.1-33.5
```

This is the docs-recommended pairing. From [`docs/setup/maven-coordinates.md`](https://sedona.apache.org/latest/setup/maven-coordinates/) (fetched, quoted): *"For Scala/Java/Python users, this is the most common way to use Sedona in your environment. Do not use separate Sedona jars unless you are sure that you do not need shaded jars."* The unshaded sibling (`sedona-spark-3.5_2.12`, no `-shaded`) also exists at 1.9.1 and is what the pip-install-python page's copy-paste example happens to use, a minor inconsistency between two doc pages, not a correctness issue either way, but shaded is the stated recommendation and matches what you already have working.

**pip / PySpark setup**, from [`docs/setup/install-python.md`](https://sedona.apache.org/1.9.1/setup/install-python/) (fetched at the 1.9.1-pinned path):

```bash
pip install apache-sedona[spark]
```
```python
from sedona.spark import *
config = (
    SedonaContext.builder()
    .config("spark.jars.packages",
        "org.apache.sedona:sedona-spark-shaded-3.5_2.12:1.9.1,"
        "org.datasyslab:geotools-wrapper:1.9.1-33.5")
    .getOrCreate()
)
sedona = SedonaContext.create(config)
```
`pip install apache-sedona[spark]` pulls in a pyspark version as an optional-dependency resolution (doc quote: *"pyspark is an optional dependency of Sedona Python because spark comes pre-installed on many spark platforms"*), it does not document pinning to 3.5.3 specifically. **Practical recommendation, not from docs**: pin explicitly, `pip install pyspark==3.5.3 apache-sedona` (no `[spark]` extra) to avoid the extra silently resolving a different 3.5.x patch or drifting to a newer minor.

**Java version, corrected from your ticket's guess of 17**: confirmed twice, once via the rendered [release notes page](https://sedona.apache.org/latest/setup/release-notes/) and once via the raw [`release-notes.md` at the `sedona-1.9.1` git tag](https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/setup/release-notes.md):

> *"Spark 3.4 & 3.5: Java 11"*
> *"Spark 4.0 & 4.1: Java 17"*

You need **Java 11**, not 17, for this Spark 3.5.3 stack. (Not independently checked here: ARM64/Apple Silicon-specific JDK 11 distribution caveats, e.g. Temurin/Zulu both publish aarch64 macOS builds, this wasn't flagged as an issue in any source found, but wasn't explicitly tested against M4 either, worth a quick local smoke test before assuming.)

**NetCDF-only caveat**: `RS_FromNetCDF` pulls `netcdf-java` (`edu.ucar:cdm-core:5.4.2`) and `org.datasyslab:sernetcdf:0.1.0`, which are **not on Maven Central**. Per WebSearch synthesis of [Unidata netCDF-java Maven docs](https://docs.unidata.ucar.edu/netcdf-java/dev/userguide/using_netcdf_java_artifacts.html) (not independently fetched verbatim, flagged), you need:
```
.config("spark.jars.repositories", "https://artifacts.unidata.ucar.edu/repository/unidata-all")
```
Only required if you touch `RS_FromNetCDF`/`netcdf.metadata`. Irrelevant if your pipeline stays on the xarray-bridge pattern (2a) and never calls Sedona raster functions at all, which is the recommendation above.

---

## Project-status notes (asked, verified via GitHub API directly)

- **GeoTrellis** (`locationtech/geotrellis`): actively maintained. Latest release `v3.8.1` (2026-06-22), last commit 2026-08-07.
- **RasterFrames** (`locationtech/rasterframes`): stale for new adoption. Last *tagged release* `0.11.1` was 2023-04-03 (over 3 years old), last commit 2025-12-30 (~7.5 months old), not formally archived, 143 open issues. Some maintenance activity persists but no release cadence. Not a viable alternative to Sedona for new work.

---

## Sources (fetched directly unless marked "search synthesis")

- https://sedona.apache.org/latest/setup/release-notes/
- https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/setup/release-notes.md
- https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/api/sql/Raster-Band-Accessors/RS_ZonalStats.md
- https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/api/sql/Raster-Constructors/RS_FromGeoTiff.md
- https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/api/sql/Raster-Constructors/RS_FromNetCDF.md
- https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/api/sql/Raster-Operators/RS_Value.md
- https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/api/sql/Raster-UDF.md
- https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/api/sql/Raster-Functions.md
- https://raw.githubusercontent.com/apache/sedona/sedona-1.9.1/docs/tutorial/raster.md
- https://sedona.apache.org/1.9.1/setup/install-python/
- https://sedona.apache.org/latest/setup/maven-coordinates/
- https://central.sonatype.com/artifact/org.apache.sedona/sedona-spark-shaded-3.5_2.12/1.9.1
- https://central.sonatype.com/artifact/org.datasyslab/geotools-wrapper/1.9.1-33.5
- https://downloads.apache.org/spark/docs/3.5.1/structured-streaming-programming-guide.html
- https://docs.databricks.com/aws/en/transform/join
- https://docs.wherobots.com/latest/apache-sedona/
- https://github.com/wherobots/havasu
- https://registry.opendata.aws/noaa-nws-aorc/
- https://github.com/google-research/arco-era5/blob/main/README.md
- https://icechunk.io/en/stable/understanding/faq/
- GitHub API: `apache/sedona` tags/contents at ref `sedona-1.9.1`; `locationtech/geotrellis` and `locationtech/rasterframes` releases/commits
- Search synthesis only (titles/snippets, not independently fetched verbatim): Unidata netCDF-java Maven repo requirement, VirtualiZarr/kerchunk fsspec async details, rioxarray COG driver syntax, `apache/sedona-db` issue #746/#308 content