"""DAG delivery and per-task runtime (orchestration ticket 04), as data.

Six claims live here, one per acceptance row, and each of them is a thing that fails
SILENTLY in production if it drifts:

  the DAG ships inside the image      - no git-sync, no DAG volume, so a DAG and the code
                                        it schedules cannot be different versions
  one sha, one repository             - the DAG image and the runtime image are pinned
                                        apart (Helm values vs the kustomize transformer),
                                        so nothing but a test keeps them one release
  the pod comes from the table        - every capacity number is cloud 03's MEASURED one,
                                        read from deploy/k8s/raincheck/build.yaml
  the image is a pin                  - `image: raincheck` resolves from the build-time
                                        pin, never from a string typed into a DAG
  credentials come from the Secret    - envFrom r2-build, bound to the SA, nothing baked
  no stage is a callable              - a stage that runs inside the DAG file runs on the
                                        scheduler, on the floor, next to Kafka

Only the last test needs Airflow installed (it is not a repo dependency - Airflow runs in
the cluster, not on this Mac), so it skips here and runs in the image's own build check.
Everything else is plain parsing and runs everywhere.
"""
import ast
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
DAGS = ROOT / "dags"
PLACEMENT = ROOT / "deploy" / "k8s" / "raincheck" / "build.yaml"
KUSTOMIZATION = ROOT / "deploy" / "k8s" / "kustomization.yaml"
AIRFLOW_VALUES = ROOT / "deploy" / "airflow" / "values.yaml"
DOCKERFILE = ROOT / "docker" / "Dockerfile"
MAKEFILE = ROOT / "Makefile"
DAG_IMAGE_PATH = "/opt/airflow/dags"          # the chart's dags.mountPath and Airflow's default
IMAGE = "the-image:under-test"

sys.path.insert(0, str(DAGS))
import raincheck_stage                        # noqa: E402  (the DAG folder is on sys.path in a pod)

raincheck_stage.PLACEMENT = PLACEMENT          # in a pod it is the copy baked beside the DAGs


def values() -> dict:
    return yaml.safe_load(AIRFLOW_VALUES.read_text())


def templates() -> dict:
    return {d["metadata"]["name"]: d for d in yaml.safe_load_all(PLACEMENT.read_text())
            if d and d.get("kind") == "PodTemplate"}


def dag_files() -> list[Path]:
    return sorted(DAGS.glob("*.py"))


def code_strings(path: Path) -> list[str]:
    """Every string literal in the file that is NOT a docstring.

    Docstrings are stripped for the reason notify 01 measured: a file whose job is to
    explain why a number must not be written here has to be able to NAME the number, and a
    grep that cannot tell prose from code can never pass."""
    tree = ast.parse(path.read_text())
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                  and ast.get_docstring(n) is not None}
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def dockerfile_stage(name: str) -> str:
    """The Dockerfile text from `FROM ... AS <name>` to the next FROM (or the end)."""
    body = DOCKERFILE.read_text()
    start = re.search(rf"(?m)^FROM .+ AS {name}$", body)
    assert start, f"docker/Dockerfile has no `AS {name}` stage"
    rest = body[start.start():]
    nxt = re.search(r"(?m)^FROM ", rest[1:])
    return rest[: nxt.start() + 1] if nxt else rest


# --- the DAG ships inside the image -----------------------------------------------------

def test_the_dag_ships_in_the_image_and_not_on_a_volume_or_a_sidecar():
    """git-sync would make the DAG's version independent of the code's - a scheduler
    holding today's DAG against last week's image, with nothing saying so. A DAG PVC is the
    same failure with a manual step in front of it. Both stay off, and the delivery is a
    COPY into the folder Airflow already reads."""
    v = values()
    assert v["dags"]["persistence"]["enabled"] is False
    assert v["dags"]["gitSync"]["enabled"] is False
    # ...and nothing may quietly re-introduce a mount path or a bundle to fill instead
    assert "mountPath" not in v["dags"], "a mountPath here means the DAGs are not in the image"
    # Comments stripped first: this file's own prose NAMES the setting in order to explain
    # why it is absent, and a grep that cannot tell a warning from a setting never passes.
    settings = "\n".join(l for l in AIRFLOW_VALUES.read_text().splitlines()
                         if not l.lstrip().startswith("#"))
    assert "dag_bundle_config_list" not in settings, (
        "a bundle is configured per component; one configured on the scheduler alone is not "
        "configured on the task pod, which then dies after it has already started")
    stage = dockerfile_stage("dags")
    assert re.search(rf"(?m)^COPY .*\bdags {DAG_IMAGE_PATH}$", stage), (
        f"the dags stage does not COPY dags/ to {DAG_IMAGE_PATH}")
    assert re.search(r"(?m)^COPY .*deploy/k8s/raincheck/build\.yaml ", stage), (
        "the placement table is not baked beside the DAGs, so no task pod can be built")


def test_the_dag_image_and_the_code_image_are_one_sha_in_one_repository():
    """The two pins live in different files because Helm values are not Kubernetes objects,
    so nothing but this test keeps them one release. `<sha>` runs the stages; `<sha>-airflow`
    is the same tree's DAGs on the Airflow base, built beside it by one script run."""
    pin = yaml.safe_load(KUSTOMIZATION.read_text())["images"][0]
    for name, img in values()["images"].items():
        assert img["repository"] == pin["newName"], (
            f"images.{name} is not the repository the manifests are pinned to")
        assert img["tag"] == f"{pin['newTag']}-airflow", (
            f"images.{name} is {img['tag']}, not the code image's sha ({pin['newTag']}) - "
            "the DAGs and the code they schedule are different versions")
        assert img["pullPolicy"] == "IfNotPresent"


def test_the_dag_image_is_built_on_the_airflow_the_chart_installs():
    """A DAG image left behind by a chart upgrade parses this repo's DAGs with the wrong
    Airflow. The base tag and airflowVersion are one number in two files."""
    version = values()["airflowVersion"]
    assert re.search(rf"(?m)^FROM apache/airflow:{re.escape(version)} AS dags$",
                     DOCKERFILE.read_text()), (
        f"the dags stage is not FROM apache/airflow:{version}")


# --- the pod comes from the placement table ---------------------------------------------

def test_the_task_pod_is_the_placement_tables_pod_with_only_the_image_filled_in():
    """The ticket's row: no capacity number is invented here. Both shapes come through
    whole - requests, limits, the staging volume, the burst selector, the ServiceAccount -
    and the ONLY difference from the table is the resolved image.

    EVERY container, `initContainers` included. That list is walked here because it once was
    not: cloud 12's refpull init carries the same ungoverned `image: raincheck` spelling, and
    while only `containers` was pinned this test stayed green with every stage pod resolving
    its init step to `docker.io/library/raincheck:latest` - ImagePullBackOff on the cluster,
    invisible in the repo (measured 2026-08-24, orch 05)."""
    for shape, template in templates().items():
        built = raincheck_stage.pod(shape, image=IMAGE)
        expected = templates()[shape]["template"]["spec"]     # re-read from disk, unmutated
        for key in ("initContainers", "containers"):
            assert len(built["spec"].get(key, [])) == len(expected.get(key, [])), \
                f"{shape} lost a {key} entry"
            for want, got in zip(expected.get(key, []), built["spec"].get(key, [])):
                assert got["resources"] == want["resources"], f"{shape} lost its measured requests"
                assert got["volumeMounts"] == want["volumeMounts"]
                assert got["envFrom"] == want["envFrom"]
                assert got["image"] == IMAGE
        assert raincheck_stage.IMAGE_NAME not in [c["image"] for c in
                                  built["spec"].get("initContainers", []) + built["spec"]["containers"]], \
            f"{shape} leaves a container on the unpinned name, which resolves to Docker Hub"
        assert built["spec"]["volumes"] == expected["volumes"], f"{shape} lost its staging volume"
        assert built["spec"]["nodeSelector"] == {"raincheck.io/pool": "burst"}
        assert built["spec"]["serviceAccountName"] == "raincheck-build"
        assert built["metadata"]["namespace"] == template["metadata"]["namespace"]
        assert built["kind"] == "Pod" and built["apiVersion"] == "v1"


def test_the_task_reads_r2_from_the_secret_bound_to_its_service_account():
    """Nothing is baked into the image and nothing is a literal: the credential arrives as
    the whole Secret, and `optional: true` is what lets the pod START before Ross has
    minted the token (without it the pod sits in CreateContainerConfigError forever)."""
    for shape in templates():
        for c in raincheck_stage.pod(shape, image=IMAGE)["spec"]["containers"]:
            refs = [e["secretRef"] for e in c["envFrom"]]
            assert [r["name"] for r in refs] == ["r2-build"]
            assert all(r.get("optional") is True for r in refs)
            for env in c.get("env", []):
                assert "value" not in env or "KEY" not in env["name"].upper(), env


def test_an_unknown_shape_is_an_error_and_not_an_invented_pod():
    with pytest.raises(KeyError, match="raincheck-stage"):     # the message lists what exists
        raincheck_stage.pod("raincheck-enormous", image=IMAGE)


def test_the_image_is_a_pin_and_an_unpinned_dag_image_refuses_to_build_a_pod(monkeypatch):
    """`image: raincheck` is the ungoverned spelling the kustomize transformer rewrites for
    the manifests; nothing renders kustomize in an Airflow pod, so the same substitution
    happens from the build-time pin. An EMPTY pin must fail here - the alternative is every
    task pod trying to pull the bare name `raincheck` from Docker Hub at 03:00."""
    monkeypatch.setenv("RAINCHECK_IMAGE", IMAGE)
    assert raincheck_stage.pod("raincheck-stage")["spec"]["containers"][0]["image"] == IMAGE
    monkeypatch.setenv("RAINCHECK_IMAGE", "")
    with pytest.raises(RuntimeError, match="RAINCHECK_IMAGE"):
        raincheck_stage.pod("raincheck-stage")


# --- what a DAG file may contain --------------------------------------------------------

def test_no_dag_names_a_capacity_number_or_an_image():
    """Both are measured elsewhere and both drift silently: a request retyped here stops
    tracking the table it was measured into, and an image spelled here is a second pin site
    that a `scripts/cloud-image.sh` run does not move."""
    banned_word = re.compile(r"(?i)\b(cpu|memory|resources|limits|nodeselector|emptydir|"
                             r"ecr|amazonaws|dkr)\b")
    banned_quantity = re.compile(r"^\d+(m|Mi|Gi|Ki)$")
    banned_kwarg = {"container_resources", "node_selector", "resources", "image"}
    for path in dag_files():
        for s in code_strings(path):
            assert not banned_word.search(s), f"{path.name} spells a pod-spec field: {s!r}"
            assert not banned_quantity.match(s.strip()), f"{path.name} names a quantity: {s!r}"
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    assert kw.arg not in banned_kwarg, (
                        f"{path.name} passes {kw.arg}= instead of taking it from the table")


def test_no_stage_runs_inside_a_dag_file():
    """"A stage implemented as a callable inside the DAG file is a defect, not a shortcut."
    It would run in the scheduler's own process on the floor, with the floor's memory and
    no staging volume - the nightly starving the capture it exists to schedule."""
    for path in dag_files():
        tree = ast.parse(path.read_text())
        imported = {n.module.split(".")[0] for n in ast.walk(tree)
                    if isinstance(n, ast.ImportFrom) and n.module}
        imported |= {a.name.split(".")[0] for n in ast.walk(tree)
                     if isinstance(n, ast.Import) for a in n.names}
        for module in ("raincheck", "subprocess", "os.system"):
            assert module not in imported, f"{path.name} imports {module}: that is a stage in-process"
        called = {n.func.id for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        decorators = {d.id for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                      for d in n.decorator_list if isinstance(d, ast.Name)}
        for operator in ("PythonOperator", "BashOperator", "PythonVirtualenvOperator"):
            assert operator not in called, f"{path.name} runs work on the scheduler: {operator}"
        assert "task" not in decorators, f"{path.name} has an @task callable"


def test_the_smoke_dag_runs_a_make_target_that_exists():
    """The acceptance row is "one task pod runs an EXISTING make target to completion", so
    the target is checked against the Makefile rather than trusted."""
    command = raincheck_stage.make("warm")
    assert command[:3] == ["make", "-C", "/opt/raincheck"]
    target = command[3]
    assert re.search(rf"(?m)^{target}:", MAKEFILE.read_text()), f"no `{target}` target"
    assert f'make("{target}")' in (DAGS / "raincheck_smoke.py").read_text()


def test_a_check_stage_can_still_tell_the_three_outcomes_apart():
    """orch 03's MUST, as a callable form: GNU make exits 2 for ANY recipe failure, so a
    module rc of 1 arrives as 2 and INCONCLUSIVE stops being distinguishable from broken.
    A task that needs the distinction invokes the module directly."""
    assert raincheck_stage.module("gapfill", "verify") == \
        ["python", "-m", "raincheck.gapfill", "verify"]


# --- the operator, against the real provider --------------------------------------------

def test_the_operator_builds_the_placement_tables_pod(monkeypatch):
    """The one test that needs Airflow: everything above checks the dict we hand the
    operator, and this checks what the operator makes of it. Skips on this Mac (Airflow is
    a cluster dependency, not a repo one) and runs inside docker/Dockerfile's dags stage."""
    pytest.importorskip("airflow", reason="airflow is a cluster dependency, not a repo one")
    monkeypatch.setenv("RAINCHECK_IMAGE", IMAGE)
    operator = raincheck_stage.stage_task("warm", "raincheck-spark",
                                          raincheck_stage.make("warm"))
    built = operator.build_pod_request_obj()
    container = built.spec.containers[0]
    table = templates()["raincheck-spark"]["template"]["spec"]["containers"][0]
    assert container.image == IMAGE
    assert container.command == ["make", "-C", "/opt/raincheck", "warm"]
    assert container.resources.requests == table["resources"]["requests"]
    assert built.spec.node_selector == {"raincheck.io/pool": "burst"}
    assert built.spec.service_account_name == "raincheck-build"
    assert built.metadata.namespace == "raincheck"
    assert [v.name for v in container.volume_mounts] == ["staging"]
    assert [e.secret_ref.name for e in container.env_from] == ["r2-build"]
