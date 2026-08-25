# The ONE raincheck image (cloud spec sec.3 / ticket 03). Every raincheck pod runs this:
# the per-day build pods, the precip pod, the streaming Deployment, the cluster-mode
# gold/backfill driver and executors, and the topics Job. Five specialised images would
# be five drifting runtimes.
#
# Built from ~/quakestream/stack/docker/sedona.Dockerfile (slim Sedona: JRE + pyspark +
# sedona, a tenth of apache/sedona:1.9.1's 11.3 GB), extended with eccodes (precip),
# DuckDB (exports, parity) and the repo package itself. arm64 only - the whole cluster is
# Graviton. Tagged by git sha, never :latest (scripts/cloud-image.sh).
#
# NOTHING INSTALLS AT POD START. Every recurring pod second is billed and a 5-min CronJob
# fires ~8,640x/mo, so setup happens here once per git sha: the jars are copied into
# SPARK_HOME/jars (see below), the repo is pip-installed, and no entrypoint downloads
# anything. spark.py detects the baked jars and drops `spark.jars.packages` entirely.
#
# The base is noble, not the upstream jammy: jammy's python3 is 3.10 and pyproject
# requires >=3.11. Noble is PEP 668 externally-managed, hence the venv.
FROM eclipse-temurin:17-jre-noble AS runtime

ENV PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYSPARK_PYTHON=/opt/venv/bin/python \
    PYSPARK_DRIVER_PYTHON=/opt/venv/bin/python \
    TZ=UTC

# `make` because the stage boundary IS the make target: every pod runs the same
# `make <target>` / `python -m raincheck.<module>` a single box runs, which is what keeps
# every existing module test covering behaviour after the move to the cluster.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv build-essential make \
 && python3 -m venv /opt/venv \
 && rm -rf /var/lib/apt/lists/*

ENV SPARK_HOME=/opt/venv/lib/python3.12/site-packages/pyspark

# The repo package pulls pyspark 3.5.3 + sedona 1.9.1 + eccodes + duckdb + confluent-kafka
# from pyproject, so the image's python runtime and the Mac's are one dependency set.
#
# The whole repo lands at /opt/raincheck, installed EDITABLE, for two reasons that are not
# style: `raincheck.paths.REPO` is `parents[2]` of the package, which a site-packages
# install resolves to /opt/venv/lib - breaking daily.py's `make -C REPO`, export.py's
# web/export.sql and live_export.py's web/files; and the Makefile is the stage boundary
# itself. The .venv symlink is why the Makefile needs no cluster fork: its `PY :=
# .venv/bin/python` resolves to this image's interpreter unchanged.
COPY pyproject.toml README.md Makefile /opt/raincheck/
COPY src /opt/raincheck/src
COPY web /opt/raincheck/web
COPY scripts /opt/raincheck/scripts
#
# `[gx]` is the Great Expectations extra (orchestration 08): the nightly's gxcheck stage
# runs in a pod on THIS image, so the extra installs here or the stage has nothing to run.
# It is an extra and not a dependency because no pipeline module imports it - raincheck.gx
# imports it lazily and reports INCONCLUSIVE when it is absent. Imported in the check below
# for the same reason everything else is: a dependency whose failure mode is import time is
# untested until something imports it, and 03:00 in a pod is the wrong place to find out.
RUN pip install --no-cache-dir -e "/opt/raincheck[gx]" \
 && ln -s /opt/venv /opt/raincheck/.venv \
 && python -c "import raincheck.spark, eccodes, duckdb, confluent_kafka, great_expectations" \
 && python -c "from raincheck.paths import REPO; assert str(REPO) == '/opt/raincheck', REPO" \
 && make -C /opt/raincheck --dry-run events DATE=1970-01-01 >/dev/null

# Bake the jars. Version pairing is NOT guessable: geotools-wrapper's suffix is the
# GeoTools version, so Sedona 1.9.1 pairs with 1.9.1-33.5 (not -33.1, which is 1.8.x).
# hadoop-aws must match the Hadoop that pyspark 3.5.3 ships (3.3.4), and aws-java-sdk-bundle
# must match that hadoop-aws - a mismatched pair fails at s3a:// open time, in a pod, at
# 03:00, not here. s3a is how every table is read and written against R2 (spec sec.3).
#
# Resolved with spark-submit (resolution happens in prepareSubmitEnvironment, so any real
# script triggers it) and then COPIED INTO $SPARK_HOME/jars: a jar on the default classpath
# needs no `spark.jars.packages` and no `spark.jars`, so a pod never resolves against Maven
# Central. That is the cost rule, and it is also the availability one - one Maven outage
# would otherwise stop the nightly.
#
# No `|| true`: if the jars cannot be resolved the BUILD must fail rather than shipping an
# image that discovers it at pod-start time. And no pipe into `wc` on the check, because a
# pipeline's exit status is the last command's.
ENV RAINCHECK_JARS="org.apache.sedona:sedona-spark-shaded-3.5_2.12:1.9.1,org.datasyslab:geotools-wrapper:1.9.1-33.5,org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3,org.apache.hadoop:hadoop-aws:3.3.4,com.amazonaws:aws-java-sdk-bundle:1.12.262"
RUN echo 'print("warmup")' > /opt/warmup.py \
 && $SPARK_HOME/bin/spark-submit --packages "$RAINCHECK_JARS" \
      --conf spark.jars.ivy=/opt/ivy --master "local[1]" /opt/warmup.py \
 && test -d /opt/ivy/jars \
 && cp /opt/ivy/jars/*.jar "$SPARK_HOME/jars/" \
 && rm -rf /opt/ivy /opt/warmup.py \
 && ls "$SPARK_HOME/jars" | grep -q sedona-spark-shaded \
 && ls "$SPARK_HOME/jars" | grep -q hadoop-aws

# DuckDB's httpfs extension is a per-connection DOWNLOAD on first use (parity reads R2
# through it, and the live-export path reads DuckDB every 30 s). HOME is pinned so the
# baked extension is the one a pod finds, whatever uid it runs as.
ENV HOME=/opt/raincheck
RUN mkdir -p /opt/raincheck \
 && python -c "import duckdb; c = duckdb.connect(); c.execute('INSTALL httpfs'); c.execute('LOAD httpfs')" \
 && test -d /opt/raincheck/.duckdb/extensions \
 && chmod -R a+rX /opt/raincheck/.duckdb

# Neither a credential nor a data root is baked in: R2 comes from the r2-build Secret via
# envFrom (cloud 07) and the root from RAINCHECK_ARCHIVE_ROOT on the pod.
ENV PATH="${SPARK_HOME}/bin:${PATH}"
WORKDIR /opt/raincheck
CMD ["python", "-c", "import raincheck; print('raincheck image ok')"]

# ----------------------------------------------------------------------------------------
# THE DAG IMAGE (orchestration ticket 04). A second stage, not a second Dockerfile and not
# a second repository: one `scripts/cloud-image.sh` run builds both from one tree and tags
# both with one git sha, which is what makes "the DAG and the code it schedules are the
# same version" true by construction rather than by discipline.
#
# It is a thin layer on the OFFICIAL Airflow image because the Airflow components have to
# run Airflow; the runtime stage above has no Airflow in it, and installing one into the
# other would be two runtimes drifting inside one image. Nothing raincheck-shaped runs
# here: no repo, no venv, no make. This image PARSES DAGs and stamps pods; the stages run
# in the runtime image above, in pods of their own. Keep the tag in step with
# deploy/airflow/values.yaml's airflowVersion - tests/test_dag_delivery.py fails if it
# drifts, because a DAG image a chart upgrade left behind parses with the old Airflow.
#
# /opt/airflow/dags is the chart's own dags.mountPath and Airflow's default dags_folder,
# so baking here IS the delivery: `dags.persistence` and `dags.gitSync` both stay false and
# no volume, sidecar or bundle configuration is involved. That last part is load-bearing -
# a bundle configured on the scheduler alone is not configured on the TASK pod, and the
# worker dies with "Requested bundle is not configured" after it has already started.
FROM apache/airflow:3.2.2 AS dags

# The one sha the runtime stage above was just tagged with, passed by scripts/cloud-image.sh.
# It reaches every pod stamped from this image - workers included - BECAUSE it is in the
# image: env set on the Airflow Deployments does not reach task pods.
ARG RAINCHECK_IMAGE
ENV RAINCHECK_IMAGE=${RAINCHECK_IMAGE}

COPY --chown=airflow:root dags /opt/airflow/dags
# The nightly's run-id timetable (orchestration ticket 05). It has to be a PLUGIN: a custom
# timetable is stored in the serialized DAG by qualified name and looked up in the plugin
# registry to decode, so an unregistered one cannot even be written. Airflow's own
# settings.initialize() appends this folder to sys.path in every component, which is how the
# DAG file's `import raincheck_timetable` resolves - there is no PYTHONPATH to set.
COPY --chown=airflow:root plugins /opt/airflow/plugins
# cloud 03's stage-placement table, verbatim - the pod spec every task is built from, so
# that no capacity number is retyped into a DAG. raincheck_stage.PLACEMENT defaults to this path.
COPY --chown=airflow:root deploy/k8s/raincheck/build.yaml /opt/airflow/placement/build.yaml
# The stage contract (ticket 01), likewise verbatim: the nightly DAG READS daily.STAGES for
# its order, its soft stage and its retry classes rather than holding a second copy of them.
# It is data here, not code - this image has no raincheck package and a DAG may not import
# one. raincheck_stage.DECLARATION defaults to this path.
COPY --chown=airflow:root src/raincheck/daily.py /opt/airflow/placement/daily.py

# An unset --build-arg would bake an empty pin and every task would try to pull the bare
# name `raincheck` from Docker Hub, at 03:00, having looked fine here.
RUN test -n "$RAINCHECK_IMAGE" \
 && python -c "import sys; sys.path.insert(0, '/opt/airflow/dags'); import raincheck_smoke" \
 && python -c "import sys; sys.path.insert(0, '/opt/airflow/dags'); import airflow; import raincheck_daily" \
 && test "$(python -c "import sys; sys.path.insert(0, '/opt/airflow/dags'); import raincheck_stage as s; print(s.pod('raincheck-spark')['spec']['containers'][0]['image'])")" = "$RAINCHECK_IMAGE"
