# 07 Sedona streaming enrich job v1

Type: task
Status: open
Blocked by: 04

## Question

Spark 3.5.3 + Sedona 1.9.1 Structured Streaming job: Kafka VP topic in, per-message
H3 cell (resolution from ticket 04) + borough/taxi-zone tag via Sedona ST_ join
against broadcast polygons, out to enriched topic + Parquet sink. Reuse the
quakestream stream_job.py pattern and the slim Sedona Dockerfile. Local mode first,
no cluster. Done means: live messages visibly enriched, checkpoint recovery works
(kill and restart resumes without loss), one pytest against a fixture batch.

Preconditions recorded 2026-08-15 from ticket 03: Spark 3.5 needs Java 11 (NOT 17),
and this Mac currently has no JVM (`java -version` fails). Two paths:
`brew install --cask temurin@11` for local mode, or run the job containerized like
quakestream (`~/quakestream/stack/docker/sedona.Dockerfile`, slim 2 GB image).
Weather side per tickets 02/03: stream-static join against an uncached hourly
NYC AORC/MRMS Parquet table; no Sedona raster functions in the hot path.
