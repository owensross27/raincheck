"""The platform seam, on a graph small enough to be all seam.

Orchestration ticket 04. Everything the nightly (orch 05) will depend on is proved here
first, on one task, so that a red run means the PLATFORM is broken rather than the
pipeline: the DAG reaches the scheduler from inside the image, the executor stamps a
worker, the worker builds a pod from cloud 03's placement table, Karpenter buys a burst
node, the image pulls, and a real `make` target runs to completion in it.

`make warm` is that target because it is the only stage that completes on an EMPTY data
root - every other stage in every subsystem dies on `ref/assets`, which is not yet on the
cluster (cloud 12 owns delivering it). It is also not a no-op: it starts a real Spark
session through raincheck.spark's factory, so a green run says the baked Sedona and
hadoop-aws jars resolved and the JVM came up inside the pod's memory request.

Manual trigger only. A schedule here would be a second nightly.
"""
from __future__ import annotations

import datetime

from airflow.sdk import DAG

from raincheck_stage import make, stage_task

with DAG(
    dag_id="raincheck_smoke",
    description="platform seam: one make target, one pod, one burst node (orch 04)",
    schedule=None,
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["raincheck", "platform"],
):
    stage_task("warm", "raincheck-spark", make("warm"))
