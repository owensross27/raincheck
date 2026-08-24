"""The cluster manifests' standing invariants, asserted without a cluster or an AWS call.

Ticket 07 owns four of them: every ServiceAccount binds exactly one R2 token Secret and
no two share one; no secret material sits in a manifest, an image or a plain env literal;
no Service of type LoadBalancer or NodePort exists; and no inbound rule is sourced from a
CIDR beyond the named exceptions - of which there are exactly two, both undrawn.

The last one is why scripts/inbound-audit.py exists: security groups live in AWS, where no
test can see them, and with no NAT Gateway they are what keeps the internet out. The audit
is driven here against a VERBATIM `aws ec2 describe-security-groups` capture (the live
cluster's own, 2026-08-24), so the parser is tested against the shape AWS really emits.
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
K8S = ROOT / "deploy" / "k8s"
ALLOWLIST = ROOT / "deploy" / "cloud" / "inbound-allowlist.yaml"
AUDIT = ROOT / "scripts" / "inbound-audit.py"
SG_CAPTURE = Path(__file__).parent / "fixtures" / "ec2_describe_cluster_sgs.json"

# Env names that carry credentials. A manifest may reference them through secretKeyRef or
# envFrom; a literal `value:` on any of them is a secret in the repo.
CREDENTIAL_ENV = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                  "RAINCHECK_COLD_KEY_ID", "RAINCHECK_COLD_SECRET", "TRANSITLAND_API_KEY")


def docs() -> list[dict]:
    """Every YAML document under deploy/k8s."""
    out = []
    for path in sorted(K8S.glob("*.yaml")):
        out += [d for d in yaml.safe_load_all(path.read_text()) if d]
    return out


def kind(name: str) -> list[dict]:
    return [d for d in docs() if d.get("kind") == name]


def pod_specs(doc: dict) -> list[dict]:
    """Pod specs wherever a workload kind hides them (bare Pod, controller, CronJob)."""
    spec = doc.get("spec") or {}
    found = [spec] if doc.get("kind") == "Pod" else []
    tmpl = spec.get("template") or (spec.get("jobTemplate") or {}).get("spec", {}).get("template")
    if tmpl:
        found.append(tmpl.get("spec") or {})
    return found


def containers() -> list[dict]:
    out = []
    for doc in docs():
        for spec in pod_specs(doc):
            out += (spec.get("containers") or []) + (spec.get("initContainers") or [])
    return out


def allowlist() -> dict:
    return yaml.safe_load(ALLOWLIST.read_text())


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
