"""The cluster's manifests as data (spec Testing Decisions seam 5). Renders deploy/k8s the
same way the deploy scripts do and pins the handful of things that are irreversible, or
expensive, or silently dangerous to get wrong. Ticket 02 owns the Kafka rows: six
partitions and 48 h retention, exactly one owner of the topic spec, the broker on the
floor in one AZ, and nothing reachable from outside the VPC. Tickets 03/06/07 extend this
same file.

Skips when kubectl is absent - it is the renderer here, the way the shell tests skip on
their tools. `--load-restrictor LoadRestrictionsNone` is required and load-bearing: the
topics ConfigMap is generated from the real src/raincheck/topics.py, so the Job runs the
module rather than a copy of it that can drift.
"""
import ast
import functools
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from raincheck.topics import CONFIG, TOPICS

ROOT = Path(__file__).parents[1]
TOPICS_PY = ROOT / "src" / "raincheck" / "topics.py"
RENDER = ["kubectl", "kustomize", "--load-restrictor", "LoadRestrictionsNone",
          str(ROOT / "deploy" / "k8s")]


@functools.lru_cache(maxsize=1)
def rendered() -> tuple[dict, ...]:
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not installed (it renders deploy/k8s)")
    r = subprocess.run(RENDER, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return tuple(d for d in yaml.safe_load_all(r.stdout) if d)


def of_kind(kind: str) -> list[dict]:
    return [d for d in rendered() if d["kind"] == kind]


def one(kind: str) -> dict:
    docs = of_kind(kind)
    assert len(docs) == 1, f"expected exactly one {kind}, got {len(docs)}"
    return docs[0]


def test_topics_module_owns_the_irreversible_knobs():
    """Six partitions cannot be changed after creation without dropping every retained
    message, so the literal is pinned here rather than trusted to review."""
    parts = {kw.value.value for node in ast.walk(ast.parse(TOPICS_PY.read_text()))
             if isinstance(node, ast.Call)
             for kw in node.keywords if kw.arg == "num_partitions"}
    assert parts == {6}
    assert CONFIG["retention.ms"] == str(48 * 3600 * 1000)  # 48 h delete retention
    assert CONFIG["cleanup.policy"] == "delete"             # never compaction
    assert CONFIG["compression.type"] == "zstd"


def test_the_job_runs_that_module_and_not_a_copy():
    cm = next(d for d in of_kind("ConfigMap") if d["metadata"]["name"].startswith("raincheck-topics"))
    assert cm["data"]["topics.py"] == TOPICS_PY.read_text()
    job = one("Job")
    container = job["spec"]["template"]["spec"]["containers"][0]
    assert "python -m raincheck.topics" in " ".join(container["args"])
    assert job["spec"]["template"]["spec"]["nodeSelector"] == {"raincheck.io/pool": "floor"}


def test_strimzis_topic_operator_is_disabled():
    """Two declarative owners of a six-partition topic is how the knob gets flipped by
    accident: the Topic Operator stays off and no KafkaTopic resource may appear."""
    assert of_kind("KafkaTopic") == []
    assert "entityOperator" not in one("Kafka")["spec"]


def test_nothing_is_exposed_outside_the_vpc():
    assert [s for s in of_kind("Service") if s["spec"].get("type") in ("LoadBalancer", "NodePort")] == []
    types = {li["type"] for li in one("Kafka")["spec"]["kafka"]["listeners"]}
    assert types == {"internal"}, "an external listener means a public bootstrap"


def test_no_manifest_or_script_opens_the_broker_to_the_world():
    """The one permitted inbound addition is the capture box's security group. A CIDR
    rule in the deploy path would hand the broker to the internet."""
    for path in sorted((ROOT / "scripts").glob("cloud-kafka*.sh")) + sorted((ROOT / "deploy" / "k8s").rglob("*.yaml")):
        text = path.read_text()
        assert "0.0.0.0/0" not in text, f"{path.name} opens an inbound CIDR"


def test_broker_is_one_combined_role_node_on_the_floor_in_one_az():
    pool = one("KafkaNodePool")
    assert pool["spec"]["replicas"] == 1 and set(pool["spec"]["roles"]) == {"controller", "broker"}
    affinity = pool["spec"]["template"]["pod"]["affinity"]["nodeAffinity"]
    term = affinity["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"][0]
    assert term["matchExpressions"][0] == {"key": "raincheck.io/pool", "operator": "In",
                                           "values": ["floor"]}
    # gp3, and pinned to the floor's AZ: EBS cannot follow a broker into another zone
    sc = one("StorageClass")
    assert pool["spec"]["storage"]["volumes"][0]["class"] == sc["metadata"]["name"]
    assert sc["parameters"]["type"] == "gp3"
    assert sc["allowedTopologies"][0]["matchLabelExpressions"][0]["values"] == ["us-east-1f"]


def test_replication_factor_one_is_declared_everywhere():
    """RF=1 / min.insync.replicas=1 is a decision, not a default: Bronze is the record, so
    losing this broker is a latency event. Growing to 3 brokers changes these four."""
    config = one("Kafka")["spec"]["kafka"]["config"]
    assert config["default.replication.factor"] == 1
    assert config["min.insync.replicas"] == 1
    assert config["offsets.topic.replication.factor"] == 1
    assert config["transaction.state.log.replication.factor"] == 1
    assert config["auto.create.topics.enable"] == "false"  # only `make topics` makes topics
    assert TOPICS == ["raincheck.bus.vp", "raincheck.bus.tu"]
