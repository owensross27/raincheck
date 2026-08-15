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
