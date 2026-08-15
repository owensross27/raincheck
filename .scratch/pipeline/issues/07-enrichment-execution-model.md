# 07 Enrichment execution model

Type: grilling
Status: open
Blocked by: 04, 09

## Question

Where and how does Sedona enrichment run: one code path that serves both the batch
backfill and the Kafka stream (Structured Streaming with `foreachBatch` reusing the
batch functions), or two jobs? Local JVM (Java 11 via Temurin) vs the containerized
Sedona image from quakestream? What are the checkpoint, recovery, and exactly-once
requirements worth paying for on a laptop? Which spatial ops run in Sedona (H3
assignment, ST_ joins to boroughs/taxi zones, precip lookup on (h3, hour)) versus
plain PySpark? The Answer is the execution model; the job is downstream build work.
