"""The cluster's manifests as data (spec Testing Decisions seam 5). Renders deploy/k8s the
same way the deploy scripts do and pins the handful of things that are irreversible, or
expensive, or silently dangerous to get wrong.

Ticket 02 owns the Kafka rows: six partitions and 48 h retention, exactly one owner of the
topic spec, the broker on the floor in one AZ, and nothing reachable from outside the VPC.
Ticket 03 owns the image and workload-shape rows: one ECR repository pinned by git sha with
no `:latest`, nothing installed at pod start, the burst nodeSelector on every build pod,
and block-volume claims only where a single writer is guaranteed. Ticket 07 owns the
credential and network rows: every ServiceAccount binds exactly one R2
token Secret and no two share one; no secret material sits in a manifest, an image or a
plain env literal; no Service of type LoadBalancer or NodePort exists; and no inbound rule
is sourced from a CIDR beyond the named exceptions - of which there are exactly two, both
undrawn. Ticket 06 owns the Airflow rows: the metadata database is a StatefulSet on a
volume rather than in a pod, nothing installs software at container start, every Airflow
component reuses ticket 07's one ServiceAccount, task pods go to burst - and the sum of
everything pinned to the floor still fits the floor's MEASURED allocatable capacity.
Ticket 03 extends this same file.

The Airflow half reads deploy/airflow/values.yaml directly rather than through the
kustomize render, because Helm values are not Kubernetes objects. That is the same seam
deploy/cloud/inbound-allowlist.yaml sits on: a declaration this repo owns, consumed by a
tool the test does not run.

Skips when kubectl is absent - it is the renderer here, the way the shell tests skip on
their tools. `--load-restrictor LoadRestrictionsNone` is required and load-bearing: the
topics ConfigMap is generated from the real src/raincheck/topics.py, so the Job runs the
module rather than a copy of it that can drift.

The network invariant's AWS half is why scripts/inbound-audit.py exists: security groups
live in AWS, where no test can see them, and with no NAT Gateway they are what keeps the
internet out. The audit is driven here against a VERBATIM `aws ec2
describe-security-groups` capture (the live cluster's own, 2026-08-24), so the parser is
tested against the shape AWS really emits.
"""
import ast
import functools
import re
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from raincheck.topics import CONFIG, TOPICS

ROOT = Path(__file__).parents[1]
TOPICS_PY = ROOT / "src" / "raincheck" / "topics.py"
RENDER = ["kubectl", "kustomize", "--load-restrictor", "LoadRestrictionsNone",
          str(ROOT / "deploy" / "k8s")]
ALLOWLIST = ROOT / "deploy" / "cloud" / "inbound-allowlist.yaml"
FLOOR_CAPACITY = ROOT / "deploy" / "cloud" / "floor-capacity.yaml"
AIRFLOW_VALUES = ROOT / "deploy" / "airflow" / "values.yaml"
AUDIT = ROOT / "scripts" / "inbound-audit.py"
SG_CAPTURE = Path(__file__).parent / "fixtures" / "ec2_describe_cluster_sgs.json"

# Env names that carry credentials. A manifest may reference them through secretKeyRef or
# envFrom; a literal `value:` on any of them is a secret in the repo.
CREDENTIAL_ENV = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                  "RAINCHECK_COLD_KEY_ID", "RAINCHECK_COLD_SECRET", "TRANSITLAND_API_KEY",
                  "POSTGRES_PASSWORD")


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


def docs() -> list[dict]:
    """Every rendered YAML document (a plain glob misses deploy/k8s/kafka/)."""
    return list(rendered())


def kind(name: str) -> list[dict]:
    return [d for d in docs() if d.get("kind") == name]


def pod_specs(doc: dict) -> list[dict]:
    """Pod specs wherever a workload kind hides them (bare Pod, controller, CronJob, and
    PodTemplate - which keeps its template at the TOP level, not under spec, and would
    otherwise slip past every assertion in this file while looking covered)."""
    spec = doc.get("spec") or {}
    found = [spec] if doc.get("kind") == "Pod" else []
    tmpl = (doc.get("template") if doc.get("kind") == "PodTemplate" else None) or \
        spec.get("template") or (spec.get("jobTemplate") or {}).get("spec", {}).get("template")
    # `spec.template` is not always a POD template: Karpenter's NodePool templates nodes,
    # and Strimzi's KafkaNodePool templates operator-managed pods with no container list of
    # its own (which is also why the broker pins to the floor with nodeAffinity, not
    # nodeSelector - ticket 02's row asserts that one). Containers are the discriminator.
    if tmpl and (tmpl.get("spec") or {}).get("containers"):
        found.append(tmpl["spec"])
    return found


def containers() -> list[dict]:
    out = []
    for doc in docs():
        for spec in pod_specs(doc):
            out += (spec.get("containers") or []) + (spec.get("initContainers") or [])
    return out


def allowlist() -> dict:
    return yaml.safe_load(ALLOWLIST.read_text())


def airflow_values() -> dict:
    return yaml.safe_load(AIRFLOW_VALUES.read_text())


def floor_capacity() -> dict:
    return yaml.safe_load(FLOOR_CAPACITY.read_text())


def millicores(q: str | int) -> int:
    """K8s CPU quantity -> millicores. "500m" -> 500, 1 -> 1000."""
    q = str(q)
    return int(q[:-1]) if q.endswith("m") else int(float(q) * 1000)


def mib(q: str) -> int:
    """K8s memory quantity -> MiB. Only the units this repo uses, on purpose: a silent
    fallthrough on an unexpected suffix is how a Gi gets counted as a Mi."""
    for suffix, factor in (("Gi", 1024), ("Mi", 1), ("Ki", 1 / 1024)):
        if str(q).endswith(suffix):
            return int(float(str(q)[: -len(suffix)]) * factor)
    raise AssertionError(f"unhandled memory quantity {q!r}")


def floor_requests() -> list[tuple[str, int, int]]:
    """(what, millicores, MiB) for everything this repo pins to the floor NodePool.

    Two shapes, because the floor pin has two spellings: a plain `nodeSelector` on a pod
    spec, and - for Strimzi's operator-managed pods, which have no nodeSelector field -
    node affinity on a custom resource that carries its requests at the top level."""
    out = []
    for doc in docs():
        name = doc["metadata"]["name"]
        for spec in pod_specs(doc):
            if (spec.get("nodeSelector") or {}).get("raincheck.io/pool") != "floor":
                continue
            for c in (spec.get("containers") or []):
                req = (c.get("resources") or {}).get("requests") or {}
                assert req.get("cpu") and req.get("memory"), (
                    f"{name}/{c['name']} is on the floor with no resource request - it is "
                    "invisible to this sum and to the scheduler's bin packing")
                out.append((f"{name}/{c['name']}", millicores(req["cpu"]), mib(req["memory"])))
        if doc["kind"] == "KafkaNodePool":
            affinity = doc["spec"]["template"]["pod"]["affinity"]["nodeAffinity"]
            term = affinity["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"][0]
            if {"key": "raincheck.io/pool", "operator": "In", "values": ["floor"]} in term["matchExpressions"]:
                req = doc["spec"]["resources"]["requests"]
                out.append((name, millicores(req["cpu"]), mib(req["memory"])))
    return out


def airflow_floor_requests() -> list[tuple[str, int, int]]:
    """Same, for the Helm components. Discovered by walking the values rather than by a
    hardcoded component list, so adding a component to the floor cannot slip past the
    capacity sum by not being on someone's list."""
    out = []
    for name, block in airflow_values().items():
        if not isinstance(block, dict) or block.get("enabled") is False:
            continue
        if (block.get("nodeSelector") or {}).get("raincheck.io/pool") != "floor":
            continue
        for label, sub in [(name, block), (f"{name}/log-groomer", block.get("logGroomerSidecar") or {})]:
            req = ((sub.get("resources") or {}).get("requests")) or {}
            if req:
                out.append((label, millicores(req["cpu"]), mib(req["memory"])))
        assert (block.get("resources") or {}).get("requests"), (
            f"Airflow {name} is pinned to the floor with no resource request")
    return out


# --- ticket 02: Kafka on the cluster ----------------------------------------------------

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
    # command + args, not args alone: ticket 03 swapped the pip-install shell wrapper for
    # the shared image, so the entry point moved out of the args list
    ran = " ".join((container.get("command") or []) + (container.get("args") or []))
    assert "python -m raincheck.topics" in ran
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
        # comments cannot open a port, and one of them has to name the CIDR to warn about it
        code = "\n".join(l for l in path.read_text().splitlines() if not l.lstrip().startswith("#"))
        assert "0.0.0.0/0" not in code, f"{path.name} opens an inbound CIDR"


def test_the_broker_rule_is_not_sourced_from_the_shared_dev_security_group():
    """The ticket says "from sg-0cb33dca0ac107599 (the box)" and that premise is false:
    lewis-signs-dev-sg is carried by an UNRELATED staging instance too, and itself allows
    0.0.0.0/0 on tcp/443, so sourcing the broker rule from it would grant Kafka to staging
    (measured by cloud 07). The rule sources the box's own group, looked up by name."""
    body = (ROOT / "scripts" / "cloud-kafka-install.sh").read_text()
    code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    assert "Values=raincheck-capture-box" in code
    assert "BOX_SG=sg-" not in code, "the source group is looked up by name, never pinned by id"


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


# --- ticket 07: the R2 credential split ------------------------------------------------

def test_every_service_account_binds_exactly_one_r2_secret():
    """One Secret, one ServiceAccount. Sharing a token across two workloads is how a
    least-privilege split quietly becomes one shared credential again."""
    accounts = kind("ServiceAccount")
    assert accounts, "deploy/k8s declares no ServiceAccount"
    seen: dict[str, str] = {}
    for sa in accounts:
        ann = sa["metadata"].get("annotations") or {}
        secret = ann.get("raincheck.io/r2-secret")
        name = sa["metadata"]["name"]
        assert secret, f"ServiceAccount {name} declares no raincheck.io/r2-secret"
        assert secret not in seen, (
            f"secret {secret} is bound to both {seen[secret]} and {name} - one Secret, one SA")
        seen[secret] = name
        assert ann.get("raincheck.io/r2-bucket"), f"{name} declares no bucket for {secret}"


def test_serve_token_is_scoped_to_a_bucket_of_its_own():
    """The serve token reaches the public bucket and nothing else. R2 tokens have no
    prefix scoping, so "public" and "the archive" must be different BUCKETS."""
    buckets = {sa["metadata"]["name"]: (sa["metadata"]["annotations"])["raincheck.io/r2-bucket"]
               for sa in kind("ServiceAccount")}
    assert buckets["raincheck-serve"] != "raincheck-bronze"
    assert buckets["raincheck-serve"] != buckets["raincheck-build"]


def test_no_secret_material_in_a_manifest():
    """No Secret object with values, and no credential handed to a container as a literal."""
    for secret in kind("Secret"):
        assert not (secret.get("data") or secret.get("stringData")), (
            f"Secret {secret['metadata']['name']} carries values - Secrets are created by "
            "scripts/r2-secrets.sh from the operator's environment, never committed")
    for c in containers():
        for env in c.get("env") or []:
            if env.get("name") in CREDENTIAL_ENV or env.get("name", "").endswith(("_SECRET", "_TOKEN")):
                assert "value" not in env, (
                    f"container {c.get('name')} sets {env['name']} to a literal - use "
                    "valueFrom.secretKeyRef or envFrom.secretRef")


def test_no_secret_material_baked_into_an_image():
    """Nothing in the repo bakes a credential into an image layer. Vacuous while no
    Dockerfile lives here (cloud 03 brings the first one) - and cheap insurance then."""
    # Deliberately narrow: the data root and .venv live under ROOT too, and the Makefile
    # legitimately writes AWS_ACCESS_KEY_ID=$(RAINCHECK_COLD_KEY_ID) - a reference, not a
    # literal. What must never carry one is an image layer or an applied manifest.
    searched = ([ROOT / "docker-compose.yml"] + sorted(ROOT.glob("Dockerfile*"))
                + sorted((ROOT / "docker").rglob("Dockerfile*"))
                + sorted((ROOT / "deploy").rglob("*.yaml")))
    for path in (p for p in searched if p.is_file()):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            bare = line.strip()
            if bare.startswith("#"):
                continue
            for var in CREDENTIAL_ENV:
                assert f"{var}=" not in bare, f"{path.name}:{n} assigns {var} in an image layer"


def test_the_secret_script_never_puts_a_credential_in_argv_or_on_stdout():
    """--from-literal would put the token in argv, which every user on the host can read
    with ps; an echo of the value would put it in the terminal and the shell history."""
    body = (ROOT / "scripts" / "r2-secrets.sh").read_text()
    code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    assert "--from-literal" not in code, "kubectl --from-literal puts the token in argv"
    assert "--from-env-file" in code
    for var in ("KEY_VAR", "SEC_VAR"):
        assert f"echo {{!{var}}}" not in body and f"echo \"${{!{var}}}\"" not in body
    # the two secret names the manifests bind must be the ones the script creates
    assert 'create secret generic "r2-$ROLE"' in body
    bound = {(sa["metadata"]["annotations"])["raincheck.io/r2-secret"] for sa in kind("ServiceAccount")}
    assert bound == {"r2-build", "r2-serve"}


# --- ticket 07: no inbound from the internet -------------------------------------------

def test_no_loadbalancer_or_nodeport_service():
    """The absence of these IS the enforcement, together with the security groups. Nodes
    sit in public subnets with public IPs (no NAT Gateway), so subnet placement provides
    nothing here."""
    for svc in kind("Service"):
        assert (svc.get("spec") or {}).get("type") not in ("LoadBalancer", "NodePort"), (
            f"Service {svc['metadata']['name']} is internet-reachable")
    for c in containers():
        for port in c.get("ports") or []:
            assert "hostPort" not in port, f"container {c.get('name')} publishes a hostPort"


def test_the_reserved_subscribe_ingress_is_not_drawn():
    """notify 07 landed with no HTTP write path at all, so the notify exception is a
    RESERVATION. Nothing implements it, and that is asserted rather than remembered."""
    assert not kind("Ingress"), "an Ingress exists - the reserved exception has been drawn"


def test_the_inbound_allowlist_has_no_cidr_sources():
    allow = allowlist()
    assert allow["cidr_exceptions"] == [], (
        "a CIDR source appeared in the allowlist - it is a reviewed exception with a "
        "ticket number, so review it here rather than in a diff")
    for src in allow["allowed_source_security_groups"]:
        assert src["id"].startswith("sg-"), f"{src['id']} is not a security group"
        assert src["why"], f"{src['id']} is allowlisted with no reason"


def test_the_named_exceptions_are_exactly_two_and_both_undrawn():
    reserved = {r["name"]: r for r in allowlist()["reserved"]}
    assert set(reserved) == {"static-host", "notify-subscribe-ingress"}
    assert reserved["static-host"]["status"] == "not-cluster-ingress"     # outside the cluster
    assert reserved["notify-subscribe-ingress"]["status"] == "reserved-undrawn"
    assert "DEFERRAL_TRIGGER" in reserved["notify-subscribe-ingress"]["reopens_when"]


# --- scripts/inbound-audit.py against the real describe-security-groups shape -----------

def stub_aws(tmp_path: Path, body: str) -> dict:
    path = tmp_path / "aws"
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return {**os.environ, "RAINCHECK_AWS": str(path)}


def audit(env: dict, allowlist_path: Path | None = None) -> subprocess.CompletedProcess:
    args = ["--allowlist", str(allowlist_path)] if allowlist_path else []
    return subprocess.run([sys.executable, str(AUDIT), *args], cwd="/", env=env,
                          capture_output=True, text=True)


def test_audit_passes_on_the_live_cluster_capture(tmp_path):
    """The verbatim capture from the live cluster: three SGs, every source another SG."""
    r = audit(stub_aws(tmp_path, f'cat {SG_CAPTURE}\n'))
    assert r.returncode == 0, r.stderr
    assert "OK" in r.stdout and "sg-04b76aed2bb2fb61f" in r.stdout


def test_audit_is_loud_about_an_open_port(tmp_path):
    """The regression this exists to catch: someone opens a port to the world."""
    data = json.loads(SG_CAPTURE.read_text())
    data["SecurityGroups"][0]["IpPermissions"].append(
        {"IpProtocol": "tcp", "FromPort": 9092, "ToPort": 9092,
         "IpRanges": [{"CidrIp": "0.0.0.0/0"}], "Ipv6Ranges": [], "UserIdGroupPairs": [],
         "PrefixListIds": []})
    open_json = tmp_path / "open.json"
    open_json.write_text(json.dumps(data))
    r = audit(stub_aws(tmp_path, f'cat {open_json}\n'))
    assert r.returncode == 1
    assert "0.0.0.0/0" in r.stdout and "tcp/9092" in r.stdout


def test_audit_catches_a_rule_from_an_unallowlisted_security_group(tmp_path):
    """An SG source is not automatically fine: the shared dev SG on the capture box also
    carries an unrelated staging instance, so cloud 02's rule has to be reviewed here."""
    data = json.loads(SG_CAPTURE.read_text())
    data["SecurityGroups"][0]["IpPermissions"].append(
        {"IpProtocol": "tcp", "FromPort": 9092, "ToPort": 9092, "IpRanges": [],
         "Ipv6Ranges": [], "PrefixListIds": [],
         "UserIdGroupPairs": [{"GroupId": "sg-0cb33dca0ac107599"}]})
    path = tmp_path / "sg.json"
    path.write_text(json.dumps(data))
    r = audit(stub_aws(tmp_path, f'cat {path}\n'))
    assert r.returncode == 1
    assert "sg-0cb33dca0ac107599" in r.stdout


def test_audit_reports_an_aws_failure_as_inconclusive_never_as_clean(tmp_path):
    """A describe that did not run tells you nothing about the security groups. Rendering
    that as OK is how an open port survives an audit."""
    r = audit(stub_aws(tmp_path, 'echo "An error occurred (UnauthorizedOperation)" >&2\nexit 254\n'))
    assert r.returncode == 2
    assert "INCONCLUSIVE" in r.stderr
    assert "OK" not in r.stdout


def test_audit_is_inconclusive_when_no_security_group_matches(tmp_path):
    """Empty result = the discovery tags moved. Zero groups audited is not zero findings."""
    r = audit(stub_aws(tmp_path, 'echo \'{"SecurityGroups": []}\'\n'))
    assert r.returncode == 2
    assert "INCONCLUSIVE" in r.stderr


def test_audit_reads_the_allowlist_it_is_given(tmp_path):
    """Removing a source from the allowlist must turn the same capture red - otherwise the
    allowlist is decoration and the audit is asserting nothing."""
    allow = allowlist()
    allow["allowed_source_security_groups"] = [
        s for s in allow["allowed_source_security_groups"] if s["id"] != "sg-03b1743dee87eb474"]
    thin = tmp_path / "thin.yaml"
    thin.write_text(yaml.safe_dump(allow))
    r = audit(stub_aws(tmp_path, f'cat {SG_CAPTURE}\n'), thin)
    assert r.returncode == 1
    assert "sg-03b1743dee87eb474" in r.stdout


# --- ticket 03: the one image, and the shapes that run it -------------------------------

# A git sha, which is what scripts/cloud-image.sh writes. Any other tag shape - a version,
# a branch name, PLACEHOLDER - means the pin stopped naming a commit.
SHA_TAG = re.compile(r"^[0-9a-f]{7,40}$")  # not `-dirty`: a scratch push names no commit
# What "pinned" means for a third-party image: at least major.minor spelled out
# (`postgres:17.6-alpine` passes; `postgres:17` still tracks minors and does not).
VERSION_TAG = re.compile(r"^v?\d+(\.\d+)+")
# What a container must never do at start: every recurring pod second is billed, and a
# 5-min CronJob fires ~8,640x/mo. Setup belongs in the image layer, once per git sha.
INSTALLERS = ("pip install", "pip3 install", "apt-get", "apt install", "curl ", "wget ",
              "spark.jars.packages")


def workloads() -> list[dict]:
    """Every doc that really carries containers - the unit these rows assert about."""
    return [d for d in docs() if pod_specs(d)]


def test_every_image_is_the_one_ecr_repository_pinned_by_sha():
    """One image for every RAINCHECK pod: five specialised images would be five drifting
    runtimes. `:latest` is barred twice over - it makes "which code produced this
    partition?" unanswerable, and with imagePullPolicy IfNotPresent a node that already
    pulled it serves the stale one forever.

    Narrowed at the wave-2 gate: the rule's intent is that raincheck CODE moves to a new
    sha atomically, which is a claim about images the `images:` transformer governs. A
    third-party image (cloud 06's postgres metadata db) is categorically not that - it is
    allowed through when it is pinned to an immutable version tag, and still never
    tagless or `:latest`."""
    images = {c["image"] for c in containers()}
    assert images, "no containers in the rendered manifests"
    raincheck_repos = set()
    for image in images:
        repo, _, tag = image.rpartition(":")
        assert repo and tag, f"{image} carries no tag at all - that IS :latest"
        assert tag != "latest", f"{image} is a moving tag"
        if repo.endswith("/raincheck") or repo == "raincheck":
            assert SHA_TAG.match(tag), f"{image} is not pinned to a git sha"
            raincheck_repos.add(repo)
        else:
            assert VERSION_TAG.match(tag), (
                f"{image} is third-party but not pinned to an immutable version tag")
    assert len(raincheck_repos) == 1, (
        f"raincheck images from more than one repository: {sorted(raincheck_repos)}")
    assert raincheck_repos.pop().endswith("/raincheck")


def test_the_image_pin_lives_in_exactly_one_place():
    """The kustomize `images:` transformer, so every manifest moves to a new sha together.
    A half-updated rollout - some pods new, some old - must not be expressible.

    Narrowed at the wave-2 gate: a manifest may name a THIRD-PARTY image directly when it
    is pinned to an immutable version tag (the transformer does not govern those, so there
    is no second pin site to guard against). What stays barred is any direct spelling of
    the raincheck image - repo, sha, or ECR path - anywhere but the transformer."""
    kust = yaml.safe_load((ROOT / "deploy" / "k8s" / "kustomization.yaml").read_text())
    assert len(kust["images"]) == 1 and kust["images"][0]["name"] == "raincheck"
    ecr_repo = kust["images"][0]["newName"]
    for path in sorted((ROOT / "deploy" / "k8s").rglob("*.yaml")):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if line.strip().startswith("image:") and path.name != "kustomization.yaml":
                image = line.split(":", 1)[1].strip()
                if image == "raincheck":
                    continue  # the governed spelling; the transformer pins it
                repo, _, tag = image.rpartition(":")
                assert repo != "raincheck" and not repo.endswith("/raincheck") \
                    and ecr_repo not in image, (
                        f"{path.name}:{n} names the raincheck image directly instead of "
                        "through the pin")
                assert repo and tag and tag != "latest" and VERSION_TAG.match(tag), (
                    f"{path.name}:{n} names a third-party image without an immutable "
                    f"version tag: {image}")


def test_nothing_installs_at_pod_start():
    """The cost rule, as a test. A pip install in an entrypoint is paid on EVERY run of
    that pod for something the image already carries; `spark.jars.packages` re-resolves
    against Maven Central per pod and only looks free on a Mac with a warm ~/.ivy2."""
    for c in containers():
        line = " ".join(c.get("command") or []) + " " + " ".join(c.get("args") or [])
        for bad in INSTALLERS:
            assert bad not in line, f"container {c.get('name')} runs `{bad}` at start: {line}"


def test_every_build_pod_asks_for_burst():
    """Omit raincheck.io/pool: burst and a build pod lands on the FLOOR, where it competes
    with the Kafka broker and the streaming driver for 2 vCPU - the nightly build starves
    the thing capturing the feed. Every workload declares a pool, one way or the other."""
    for doc in workloads():
        for spec in pod_specs(doc):
            pool = (spec.get("nodeSelector") or {}).get("raincheck.io/pool")
            assert pool in ("floor", "burst"), (
                f"{doc['kind']}/{doc['metadata']['name']} declares no raincheck.io/pool")
    shapes = {d["metadata"]["name"]: pod_specs(d)[0]["nodeSelector"]["raincheck.io/pool"]
              for d in workloads() if d["kind"] == "PodTemplate"}
    assert shapes == {"raincheck-stage": "burst", "raincheck-spark": "burst"}


def test_the_batch_shapes_are_templates_and_never_run_themselves():
    """PodTemplate is the API's own "a pod spec that is not a running workload". A Job here
    would fire on every `kubectl apply -k`, and a comment saying not to would not stop it."""
    assert {d["metadata"]["name"] for d in kind("PodTemplate")} == {"raincheck-stage",
                                                                    "raincheck-spark"}
    # exactly one Job in the whole render, and it is ticket 02's topics Job
    assert [j["metadata"]["name"] for j in kind("Job")] == ["topics"]


def test_block_volumes_attach_only_to_single_writer_workloads():
    """A PVC is ReadWriteOnce and single-attach. The one piece of raincheck state with a
    guaranteed single writer is the streaming checkpoint; `live/` has several writers
    across pods, which is why it moves to R2 and why `prune` becomes unpinned."""
    claims = {c["metadata"]["name"]: c for c in kind("PersistentVolumeClaim")}
    for name, claim in claims.items():
        assert claim["spec"]["accessModes"] == ["ReadWriteOnce"], f"{name} is not single-attach"
    for doc in workloads():
        for spec in pod_specs(doc):
            using = [v for v in (spec.get("volumes") or []) if "persistentVolumeClaim" in v]
            if not using:
                continue
            assert doc["kind"] == "Deployment", (
                f"{doc['kind']}/{doc['metadata']['name']} claims a block volume - only the "
                "single-writer streaming Deployment may")
            assert doc["spec"]["replicas"] == 1, "two replicas is two writers on one volume"
            assert doc["spec"]["strategy"]["type"] == "Recreate", (
                "RollingUpdate starts the new pod before the old one goes, so for a moment "
                "two drivers hold one RWO checkpoint")


def test_the_streaming_driver_is_on_the_floor_and_never_discards_its_checkpoint():
    """Burst is spot-only and consolidates after 1 m; the one Spark workload that must not
    be interrupted belongs on the floor. FRESH=1 in a Deployment would discard the
    checkpoints on every restart, silently skipping the hours between - past retention."""
    dep = next(d for d in kind("Deployment") if d["metadata"]["name"] == "raincheck-stream")
    spec = dep["spec"]["template"]["spec"]
    assert spec["nodeSelector"] == {"raincheck.io/pool": "floor"}
    c = spec["containers"][0]
    assert " ".join(c["command"]) == "python -m raincheck.stream"
    env = {e["name"]: e.get("value") for e in c["env"]}
    assert "FRESH" not in env
    assert env["RAINCHECK_KAFKA"] == "raincheck-kafka-bootstrap.kafka.svc:9092", (
        "the 9094 `box` listener is the capture box's alone - it advertises a name only "
        "the box's /etc/hosts resolves")
    # the checkpoint volume is mounted UNDER the data root, so stream.py's
    # <root>/checkpoints/live_<kind> needs no cluster fork to land on block storage
    mounts = {m["name"]: m["mountPath"] for m in c["volumeMounts"]}
    assert mounts["checkpoint"] == env["RAINCHECK_ARCHIVE_ROOT"] + "/checkpoints"


def test_every_r2_pod_takes_its_credentials_from_the_bound_secret():
    """Cloud 07's shape, asserted from the consuming side: the ServiceAccount and the
    Secret its annotation binds, and nothing hand-rolled beside them."""
    bound = {sa["metadata"]["name"]: sa["metadata"]["annotations"]["raincheck.io/r2-secret"]
             for sa in kind("ServiceAccount")}
    for doc in workloads():
        for spec in pod_specs(doc):
            sa = spec.get("serviceAccountName")
            refs = [f["secretRef"]["name"] for c in (spec.get("containers") or [])
                    for f in (c.get("envFrom") or []) if "secretRef" in f]
            if not refs:
                continue
            assert sa in bound, f"{doc['metadata']['name']} pulls a Secret with no bound SA"
            assert refs == [bound[sa]], (
                f"{doc['metadata']['name']} runs as {sa} but reads {refs}, not {bound[sa]}")


def test_the_cluster_mode_driver_can_make_executors_and_nothing_else():
    """`--master k8s://` needs the driver to create its own executor pods - that is what
    replaces the spark-operator. It must not be able to read Secrets: the driver gets R2
    through envFrom on its own pod, and a Role that could read them would hand every
    executor the token as well."""
    role = next(r for r in kind("Role") if r["metadata"]["name"] == "raincheck-spark-driver")
    granted = {r for rule in role["rules"] for r in rule["resources"]}
    assert "pods" in granted
    assert not granted & {"secrets", "serviceaccounts", "roles", "rolebindings"}
    binding = next(b for b in kind("RoleBinding")
                   if b["metadata"]["name"] == "raincheck-spark-driver")
    assert [s["name"] for s in binding["subjects"]] == ["raincheck-build"]
# --- ticket 06: the Airflow platform ----------------------------------------------------

def test_run_history_lives_on_a_volume_and_not_in_a_pod():
    """The ticket's acceptance criterion is "run history survives deleting the scheduler
    pod", which is a claim about WHERE the metadata database is. A StatefulSet with a
    volumeClaimTemplate survives it; the chart's bundled postgres (an emptyDir by default,
    and a subchart kustomize never renders) does not, which is why it is disabled."""
    sts = next(d for d in kind("StatefulSet") if d["metadata"]["name"] == "airflow-metadata-db")
    assert sts["spec"]["replicas"] == 1
    claim = sts["spec"]["volumeClaimTemplates"][0]["spec"]
    sc = one("StorageClass")
    assert claim["storageClassName"] == sc["metadata"]["name"], "not the AZ-pinned gp3 class"
    assert sc["parameters"]["type"] == "gp3"
    # EBS cannot follow a pod into another AZ, so the pod must be pinned where the volume is
    assert sts["spec"]["template"]["spec"]["nodeSelector"] == {"raincheck.io/pool": "floor"}
    assert sc["allowedTopologies"][0]["matchLabelExpressions"][0]["values"] == ["us-east-1f"]
    assert airflow_values()["postgresql"]["enabled"] is False
    assert airflow_values()["data"]["metadataSecretName"], "the URI must come from a Secret"


def test_the_platform_is_the_shape_the_ticket_specified():
    """KubernetesExecutor, no triggerer, one web replica. In Airflow 3 the webserver was
    split into an API server, so the ticket's "one webserver replica" is apiServer here -
    and `webserver` is the 2.x component, which must stay off rather than render twice."""
    v = airflow_values()
    assert v["executor"] == "KubernetesExecutor"
    assert v["triggerer"]["enabled"] is False, "spec 1: nothing here uses deferrable operators"
    assert v["apiServer"]["replicas"] == 1
    assert v["webserver"]["enabled"] is False
    # Celery's half of the chart costs floor and does nothing under KubernetesExecutor
    assert v["redis"]["enabled"] is False and v["flower"]["enabled"] is False


def test_nothing_installs_software_at_container_start():
    """A per-start install is a recurring bill: scheduler, api-server and EVERY task pod
    restart routinely, so `_PIP_ADDITIONAL_REQUIREMENTS` (the chart's own dev-only escape
    hatch) would be paid thousands of times a month. Setup belongs in an image layer."""
    body = AIRFLOW_VALUES.read_text()
    code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    assert "_PIP_ADDITIONAL_REQUIREMENTS" not in code
    for token in ("pip install", "apt-get", "pip3 install"):
        assert token not in code, f"{token} in the values means a per-start install"


def test_every_airflow_image_is_pinned_and_not_repulled():
    """`latest` is a standing trap here (images are git-sha tags), and imagePullPolicy
    Always re-pulls on every pod start - which for task pods is every task."""
    for name, img in airflow_values()["images"].items():
        assert img.get("tag"), f"images.{name} has no tag"
        assert img["tag"] != "latest", f"images.{name} is :latest"
        assert img["pullPolicy"] == "IfNotPresent", f"images.{name} re-pulls on every start"
    for c in containers():                      # the metadata DB, from the kustomize render
        assert ":" in c["image"] and not c["image"].endswith(":latest"), c["image"]


def test_airflow_reuses_ticket_07s_service_account_and_never_mints_a_second():
    """One Secret, one ServiceAccount. Every Airflow component runs as the SA that already
    holds r2-build; a chart-created SA would be a second identity for the same token."""
    v = airflow_values()
    bound = {sa["metadata"]["name"]: (sa["metadata"]["annotations"])["raincheck.io/r2-secret"]
             for sa in kind("ServiceAccount")}
    for name, block in v.items():
        if isinstance(block, dict) and isinstance(block.get("serviceAccount"), dict):
            sa = block["serviceAccount"]
            assert sa["create"] is False, f"{name} would create a ServiceAccount of its own"
            assert sa["name"] in bound, f"{name} runs as {sa['name']}, which binds no R2 secret"
    assert "r2-build" in v["extraEnvFrom"], "the R2 credential never reaches the pods"
    # cloud 07 measured that nothing in-cluster calls an AWS API. The first pod that does
    # needs a NEW IAM role, and that is a Ross decision - not a values-file annotation.
    # Comments are stripped first: the annotation is NAMED in the file's own prose, and a
    # grep that cannot tell a warning from a setting can never pass (notify 01's lesson).
    code = "\n".join(l for l in AIRFLOW_VALUES.read_text().splitlines()
                     if not l.lstrip().startswith("#"))
    assert "eks.amazonaws.com/role-arn" not in code


def test_remote_logging_goes_to_r2_with_no_credential_in_the_config():
    """Logs off pod disk, and the credential arriving from the environment rather than
    from an Airflow Connection - a connection URI would put a secret in this file."""
    log = airflow_values()["config"]["logging"]
    assert log["remote_logging"] == "True"
    bucket = {sa["metadata"]["name"]: (sa["metadata"]["annotations"])["raincheck.io/r2-bucket"]
              for sa in kind("ServiceAccount")}["raincheck-build"]
    assert log["remote_base_log_folder"].startswith(f"s3://{bucket}/"), (
        "task logs must land in the bucket the build token is actually scoped to")
    # empty conn id => the amazon provider falls through to boto3's default chain, which is
    # what reads AWS_ENDPOINT_URL and the key pair out of Secret r2-build
    assert log["remote_log_conn_id"] == ""
    assert airflow_values()["logs"]["persistence"]["enabled"] is False


def test_task_pods_land_on_burst_and_never_on_the_floor():
    """T1's handoff: a build pod without the burst selector lands on the floor and competes
    with Kafka and the streaming driver. Task pods ARE build pods, and there can be many."""
    workers = airflow_values()["workers"]
    # `workers.kubernetes` is the per-executor home; the flat `workers.nodeSelector` still
    # works but the chart deprecation-warns on it. Accept whichever is set, require one.
    selector = (workers.get("kubernetes") or {}).get("nodeSelector") or workers.get("nodeSelector")
    assert selector == {"raincheck.io/pool": "burst"}


def test_no_airflow_component_is_reachable_from_outside_the_cluster():
    """The UI is reached with port-forward. A LoadBalancer here would be the first inbound
    path into a cluster whose security groups have zero CIDR sources."""
    v = airflow_values()
    assert v["apiServer"]["service"]["type"] == "ClusterIP"
    assert not (v.get("ingress") or {}).get("apiServer", {}).get("enabled")


def test_the_floor_workloads_fit_the_declared_floor_capacity():
    """The ticket's test, and the reason floor-capacity.yaml exists: adding the DAG
    platform must not evict the pipeline. Allocatable is MEASURED (a t4g.large offers
    1930m/7069Mi of its 2 vCPU / 8 GiB), and so is what is already on the floor without
    being declared here - kube-system, Karpenter and the Strimzi operator.

    When this goes red the answer is the third spot node (`maxSize: 3` is in place), taken
    as a decision against the budget alarm at ~$20.73/mo, never as a silent scale-up."""
    cap = floor_capacity()["floor"]
    cpu_cap = cap["nodes"] * cap["allocatable_per_node"]["cpu_millis"]
    mem_cap = cap["nodes"] * cap["allocatable_per_node"]["memory_mib"]

    items = ([(u["name"], u["cpu_millis"], u["memory_mib"]) for u in floor_capacity()["unmanaged"]]
             + floor_requests() + airflow_floor_requests())
    cpu, mem = sum(i[1] for i in items), sum(i[2] for i in items)
    ledger = "\n".join(f"    {n:38s} {c:>6}m {m:>7}Mi" for n, c, m in items)
    assert cpu <= cpu_cap and mem <= mem_cap, (
        f"the floor does not hold what is pinned to it:\n{ledger}\n"
        f"    {'TOTAL':38s} {cpu:>6}m {mem:>7}Mi  vs {cpu_cap}m / {mem_cap}Mi allocatable")

    # Totals hide the thing that actually fails to schedule: a pod is placed whole, on one
    # node, so no single container may exceed what one node can ever offer.
    per_node_cpu = cap["allocatable_per_node"]["cpu_millis"]
    per_node_mem = cap["allocatable_per_node"]["memory_mib"]
    for name, c, m in items:
        assert c <= per_node_cpu and m <= per_node_mem, (
            f"{name} requests {c}m/{m}Mi, which no single floor node can offer")


# --- ticket 05: the live path as pods ---------------------------------------------------

def cronjob(name: str) -> dict:
    return next(c for c in kind("CronJob") if c["metadata"]["name"] == name)


def test_the_precip_tick_runs_the_module_itself_and_never_two_at_once():
    """THE row this ticket exists for. `precip_live.tick()` fetches every `:00` stamp the
    table is MISSING inside MRMS's ~25 h retention, not just the newest one - measured
    2026-08-24 against the live feed: 0.70 s and one fetch with the table warm, 10.61 s and
    all 25 hours from empty. A shell equivalent (curl the latest, write it) is
    indistinguishable on a healthy day and silently drops catch-up, which re-blocks the
    flood replay gate [T11, F12] the first time a tick is missed. So the command is
    asserted LITERALLY, not by substring: `... && python -m raincheck.precip_live` or a
    wrapper script would pass a looser check while changing what runs.

    Forbid is the other half: two overlapping walks of the same 25 h window would both
    write into `live/precip_cell/valid_ts=.../`, leaving "latest fetched_at wins" to
    arbitrate between two half-finished passes."""
    cj = cronjob("precip-live")["spec"]
    assert cj["schedule"] == "*/5 * * * *"
    assert cj["concurrencyPolicy"] == "Forbid"
    job = cj["jobTemplate"]["spec"]
    assert job["backoffLimit"] == 0, (
        "NODD having published nothing in 25 h is not a transient error - a retry ten "
        "seconds later asks the same empty bucket, and the next tick is five minutes away")
    c = job["template"]["spec"]["containers"][0]
    assert c["command"] == ["python", "-m", "raincheck.precip_live"], (
        "the CronJob must run the module itself - that is the catch-up contract")
    assert not c.get("args"), "an args list after that command is a wrapper by another name"


def test_the_precip_cronjob_cannot_permanently_stop_scheduling_itself():
    """With Forbid and no `startingDeadlineSeconds`, the controller counts every missed
    schedule since the last successful run and STOPS scheduling the CronJob for good past
    100 of them ("Too many missed start times"). At 5-minute ticks that is 8 h 20 m of
    downtime - comfortably inside the 25 h retention the catch-up walk depends on - so the
    unbounded version converts a recoverable outage into a dead tick, and then, one
    retention window later, into permanently lost hours. Bounded, only that window is
    counted: a tick that cannot start is skipped and the next one's catch-up heals it."""
    cj = cronjob("precip-live")["spec"]
    deadline = cj.get("startingDeadlineSeconds")
    assert deadline is not None, "unbounded missed-schedule counting can retire this CronJob"
    assert deadline < 100 * 5 * 60


def test_the_five_minute_tick_runs_on_the_floor_and_never_buys_a_node():
    """The one raincheck workload where `burst` costs MORE than the floor. The tick runs
    for well under a second and exits, 8,640 times a month; on burst that is 8,640 spot
    nodes provisioned for a sub-second job and consolidated a minute later. Its measured
    average draw (~0.2% of a core over its 300 s period) fits in the floor's idle CPU."""
    spec = cronjob("precip-live")["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    assert spec["nodeSelector"] == {"raincheck.io/pool": "floor"}
    assert spec["restartPolicy"] == "Never"


def test_the_live_export_and_the_detector_are_one_process_in_one_pod():
    """Spec story 28: the panel's two halves must never age apart. One container running
    one loop is what makes that a property rather than a hope - and it is also the cost
    rule, because the alternatives pay per tick. At 2,880 ticks a day, a container per
    concern is three interpreters and three requests on the floor, and a shell `while`
    loop around `python -m ...` is an interpreter start, a full import graph and a COLD
    DuckDB connection every 30 s for what the image already holds (which is why cloud 09's
    `publish()` asks this ticket to call it in-process).

    A second container here, or a `sh -c` command, is the regression this row catches."""
    dep = next(d for d in kind("Deployment") if d["metadata"]["name"] == "raincheck-live")
    spec = dep["spec"]["template"]["spec"]
    assert len(spec["containers"]) == 1, "one process ticks export -> detect -> publish"
    c = spec["containers"][0]
    assert c["command"] == ["python", "-m", "raincheck.live_loop"]
    assert not c.get("args")
    assert "sh" not in c["command"] and "bash" not in c["command"]
    # resident beside the streaming driver: burst is spot-only and consolidates after a
    # 1 m idle window, which would kill a 30 s loop on a schedule
    assert spec["nodeSelector"] == {"raincheck.io/pool": "floor"}
    assert dep["spec"]["replicas"] == 1
    assert dep["spec"]["strategy"]["type"] == "Recreate", (
        "cloud 09 froze the order INSIDE the live pair (live.geojson first, meta.json "
        "last, so a dying publisher leaves a fresh fleet under an older meta - stale, "
        "which is safe). Two overlapping publishers can interleave into exactly the "
        "combination that ordering exists to prevent")


def test_the_live_pod_publishes_the_pair_it_writes():
    """live_export writes into REPO/web/files and publish reads the family from there, so
    the two halves of the 30 s cadence must share a filesystem. They do it by being one
    pod; this pins the mount, because a missing one sends the loop's output to the image
    layer and the publisher to an empty directory."""
    dep = next(d for d in kind("Deployment") if d["metadata"]["name"] == "raincheck-live")
    c = dep["spec"]["template"]["spec"]["containers"][0]
    mounts = {m["name"]: m["mountPath"] for m in c["volumeMounts"]}
    assert mounts["web"] == c["workingDir"] + "/web/files"


def test_the_highest_frequency_pods_never_re_pull_a_pinned_image():
    """The cost rule where it bites hardest: these two are the 8,640/month CronJob and the
    2,880/day loop. `imagePullPolicy: Always` on an IMMUTABLE sha tag pays a registry round
    trip per tick for a layer set that cannot have changed."""
    for name in ("precip-live", "raincheck-live"):
        doc = next(d for d in workloads() if d["metadata"]["name"] == name)
        for spec in pod_specs(doc):
            for c in spec["containers"]:
                assert c.get("imagePullPolicy") == "IfNotPresent", f"{name} re-pulls per tick"
