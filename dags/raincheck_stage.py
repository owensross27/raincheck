"""One stage, one pod - the seam every raincheck DAG builds its tasks with.

Orchestration ticket 04. A stage is `make -C /opt/raincheck <target>` or
`python -m raincheck.<module>` running in ITS OWN pod, on cloud 03's image. A stage
implemented as a callable inside a DAG file is a defect, not a shortcut: it would run
inside the scheduler's own process, on the floor, with the floor's memory and none of the
staging volume - so the thing the nightly is supposed to schedule would instead be the
thing that starves Kafka.

WHERE THE POD SPEC COMES FROM, AND WHY NOT FROM HERE. Every number in a task pod -
250m/512Mi for a stage, 1500m/3Gi for a Spark shape, the 4Gi staging emptyDir, the burst
nodeSelector, the r2-build envFrom - is READ from deploy/k8s/raincheck/build.yaml, which
is cloud 03's stage-placement table and was measured on cluster hardware. This module
contains no capacity number at all, and tests/test_dag_delivery.py fails if one appears:
a number retyped here is a number that stops tracking the table it was measured into.

THE IMAGE IS A PIN, NOT A STRING. build.yaml writes `image: raincheck`, the ungoverned
spelling that deploy/k8s/kustomization.yaml's `images:` transformer rewrites for the
manifests. Nothing renders kustomize inside an Airflow pod, so the same substitution
happens here, from RAINCHECK_IMAGE - baked into the DAG image by scripts/cloud-image.sh
from the one sha it just built and pushed. Baked into the IMAGE, deliberately, and not
set on the Airflow Deployments: env on a Deployment does not reach task pods (the executor
renders its pod template from the chart's global env), and it is the WORKER pod that
parses this file and builds the spec below.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

# Baked beside the DAGs by docker/Dockerfile's `dags` stage. Overridable so the tests can
# point it at the placement table in the repo - which is the same file.
PLACEMENT = Path(os.environ.get("RAINCHECK_PLACEMENT", "/opt/airflow/placement/build.yaml"))

# The spelling every raincheck manifest writes, and the transformer rewrites.
IMAGE_NAME = "raincheck"
REPO = "/opt/raincheck"          # where the image installs the repo, editable


def make(target: str, **variables: str) -> list[str]:
    """`make -C /opt/raincheck <target> [VAR=value ...]` - the stage boundary a single box
    runs, unchanged. Kept next to the pod spec so a DAG never spells the repo path."""
    return ["make", "-C", REPO, target, *(f"{k}={v}" for k, v in sorted(variables.items()))]


def module(name: str, *args: str) -> list[str]:
    """`python -m raincheck.<module>` - the form a task MUST use when it needs to tell the
    three check outcomes apart: GNU make exits 2 for any recipe failure, so a module rc of
    1 arrives as 2 and INCONCLUSIVE becomes indistinguishable from broken (orch 03)."""
    return ["python", "-m", f"raincheck.{name}", *args]


def pod(shape: str, image: str | None = None) -> dict:
    """The named PodTemplate from the placement table, as a Pod manifest dict.

    `shape` is `raincheck-stage` (the six no-Spark stages) or `raincheck-spark` (per-day
    events, gold, precip). There is no third shape and this is not the place to invent one.
    """
    templates = {d["metadata"]["name"]: d
                 for d in yaml.safe_load_all(PLACEMENT.read_text())
                 if d and d.get("kind") == "PodTemplate"}
    if shape not in templates:
        raise KeyError(f"{shape} is not a shape in {PLACEMENT}: {sorted(templates)}")
    template = templates[shape]

    if image is None:
        image = os.environ.get("RAINCHECK_IMAGE") or ""
    if not image:
        raise RuntimeError(
            "RAINCHECK_IMAGE is empty: the DAG image was built without the pin that names "
            "the code image its tasks run (scripts/cloud-image.sh --build-arg)")

    spec = template["template"]["spec"]
    pinned = [c for c in spec["containers"] if c["image"] == IMAGE_NAME]
    if not pinned:
        raise RuntimeError(f"{shape} has no `image: {IMAGE_NAME}` container to pin")
    for container in pinned:
        container["image"] = image
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        # The namespace is the PodTemplate object's own, not a literal: the template and
        # the pods stamped from it belong in the same place by construction.
        "metadata": {**template["template"].get("metadata", {}),
                     "namespace": template["metadata"]["namespace"]},
        "spec": spec,
    }


def stage_task(task_id: str, shape: str, command: list[str], **kwargs):
    """A KubernetesPodOperator that fills in the COMMAND on `shape` and nothing else."""
    from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator

    spec = pod(shape)
    return KubernetesPodOperator(
        task_id=task_id,
        namespace=spec["metadata"]["namespace"],
        pod_template_dict=spec,
        cmds=command,
        # Karpenter has to BUY the burst node this lands on. 120 s (the default) is a node
        # launch plus an image pull short, and the failure it produces - AirflowException,
        # pod deleted - reads like the stage failed rather than like nothing ran yet.
        startup_timeout_seconds=900,
        # Task logs are dark until r2-build exists, so the scheduling events ARE the
        # diagnosis when a pod never starts ("no instance type met all requirements" is
        # what Karpenter's t4g exclusion looks like from here).
        log_events_on_failure=True,
        # The same policy the executor applies to its own worker pods: a succeeded pod is
        # deleted, a failed one is kept so `kubectl describe`/`logs` still has it.
        on_finish_action="delete_succeeded_pod",
        **kwargs,
    )
