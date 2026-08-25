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

import ast
import os
from pathlib import Path

import yaml

# Baked beside the DAGs by docker/Dockerfile's `dags` stage. Overridable so the tests can
# point it at the placement table in the repo - which is the same file.
PLACEMENT = Path(os.environ.get("RAINCHECK_PLACEMENT", "/opt/airflow/placement/build.yaml"))
# The stage contract (orchestration ticket 01), likewise baked and likewise the same file.
DECLARATION = Path(os.environ.get("RAINCHECK_DECLARATION", "/opt/airflow/placement/daily.py"))

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


def stages() -> list[dict]:
    """`raincheck.daily.STAGES` - the nightly stage contract - as plain dicts.

    READ, not imported, for two reasons that point the same way. This image is the Airflow
    base plus this folder: there is no raincheck package in it, because the stages run in
    pods of their own on cloud 03's image. And a DAG file that COULD import raincheck is a
    DAG file that could run a stage in the scheduler's process, which is why
    tests/test_dag_delivery.py forbids the import outright.

    So the declaration arrives the way the pod spec does - as data, baked beside the DAGs -
    and it is PARSED rather than generated, so that the one home ticket 01 built stays the
    one home. A generated copy is a copy, and the whole point of the declaration is that
    "gapfill before gapcheck" cannot be true in one runtime and false in the other.
    """
    tree = ast.parse(DECLARATION.read_text())
    row = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Stage")
    fields = [f.target.id for f in row.body if isinstance(f, ast.AnnAssign)]
    blank = {f.target.id: ast.literal_eval(f.value) for f in row.body
             if isinstance(f, ast.AnnAssign) and f.value is not None}
    declared = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                    and any(getattr(t, "id", None) == "STAGES" for t in n.targets))
    out = []
    for call in declared.elts:
        stage = dict(blank, **dict(zip(fields, [ast.literal_eval(a) for a in call.args])))
        stage.update({k.arg: ast.literal_eval(k.value) for k in call.keywords})
        out.append(stage)
    return out


def command(stage: dict) -> list[str]:
    """What ONE declared stage runs as its own process.

    Two forms and one rule, both from the declaration: a stage that carries an `argv`
    invokes the module directly, and every GATE carries one - GNU make exits 2 for any
    recipe failure, so a check reached through make cannot report INCONCLUSIVE apart from
    broken (orch 03). Everything else runs the make target the single box runs.
    """
    if stage["argv"]:
        return module(*stage["argv"])
    kind, _, target = stage["entrypoint"].partition(":")
    if kind != "make":
        raise ValueError(f"{stage['name']}: a {kind}: entrypoint has no process form; it "
                         "needs an argv in the declaration")
    return make(target)


def constant(name: str):
    """A module-level literal from the declaration, read the way stages() reads STAGES.

    Same seam and same reason: this image has no raincheck package to import the number
    from, and a copy of it here would be a second home for a contract that only works
    while there is exactly one.
    """
    tree = ast.parse(DECLARATION.read_text())
    return next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == name for t in n.targets))


def skip_rc(stage: dict) -> int | None:
    """The rc this stage's pod may land in `skipped` for, or None - orchestration ticket 07.

    A TASK STATE CARRIES NO rc. The number comes from the stage pod and reaches Airflow
    through the operator's own exit handling, which is success-or-failure, so an
    INCONCLUSIVE stage is indistinguishable from a broken one unless something names the
    code. `skip_on_exit_code` is that something, and `skipped` is the only terminal state
    Airflow has that is neither success nor failure. The persisted batch under
    `<root>/checks/check=<name>/` stays the record; this is a rendering of it.

    ONLY A GATE, and only one that runs its module. A gate is the declaration's own word
    for a stage whose output is a verdict, and a verdict is what has three values. Wiring
    it onto a make target would be the same conflation inverted - GNU make exits 2 for ANY
    recipe failure (orch 03), so a genuinely broken recipe would render as "could not
    check". Both halves are asserted in tests/test_dag_nightly.py.
    """
    if stage["retry"] != "gate" or not stage["argv"]:
        return None
    return constant("INCONCLUSIVE_RC")


def shape_of(name: str) -> str:
    """The placement table's OWN answer to "which pod does this stage get".

    cloud 03 measured the two shapes and wrote which stages belong to each into the
    templates' `raincheck.io/stages` annotation. Reading that back is what keeps a DAG from
    holding a second opinion about it - and a stage the table does not place is an error
    here rather than a silent 250m pod running a Spark job.
    """
    for template in yaml.safe_load_all(PLACEMENT.read_text()):
        if not template or template.get("kind") != "PodTemplate":
            continue
        listed = template["metadata"]["annotations"].get("raincheck.io/stages", "")
        # Entries read "events (one pod per Service date)" - the name is the first word.
        if name in [entry.split()[0] for entry in listed.split(",") if entry.strip()]:
            return template["metadata"]["name"]
    raise KeyError(f"{name} is in no shape's raincheck.io/stages in {PLACEMENT}")


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
    # EVERY container, init ones included. cloud 12's `refpull` initContainer runs the same
    # image and carries the same ungoverned `image: raincheck` spelling, and pinning only
    # the app container leaves it resolving to `docker.io/library/raincheck:latest` - which
    # no test could see (the placement-table test walked `containers` alone) and which fails
    # as ImagePullBackOff on the INIT step of every stage pod. Measured on the cluster
    # 2026-08-24, orch 05.
    pinned = [c for c in spec.get("initContainers", []) + spec["containers"]
              if c["image"] == IMAGE_NAME]
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
