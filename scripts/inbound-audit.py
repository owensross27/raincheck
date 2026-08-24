"""Audit the raincheck cluster's security groups against deploy/cloud/inbound-allowlist.yaml.

Why this exists: there is no NAT Gateway, so the nodes sit in PUBLIC subnets with PUBLIC
IPs. "No inbound from the internet" is provided by these security groups and by the
absence of any LoadBalancer/NodePort Service - not by subnet placement. The manifest test
covers the Kubernetes half without touching AWS; this covers the AWS half, which no test
can see. Run it after any cluster change that could add a rule (cloud 02 adds exactly
one), and before trusting the property in a later ticket.

Usage: scripts/inbound-audit.py [--allowlist PATH]
Env:   RAINCHECK_AWS (aws binary, for tests), AWS credentials as usual.

Exit 0 every inbound rule allowlisted, 1 real violations, 2 INCONCLUSIVE (the AWS call
itself failed). 2 is deliberately distinct from 0: a describe that did not run tells you
nothing about the security groups, and rendering that as "clean" is how an open port
survives an audit.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ALLOWLIST = Path(__file__).parents[1] / "deploy" / "cloud" / "inbound-allowlist.yaml"


def describe(allow: dict) -> list[dict]:
    """Every SG in the VPC carrying one of the discovery tag keys. Values within one
    --filters entry are OR'd, so this is one call, not one per key."""
    aws = os.environ.get("RAINCHECK_AWS", "aws")
    out = subprocess.run(
        [aws, "ec2", "describe-security-groups", "--region", allow["region"], "--filters",
         f"Name=vpc-id,Values={allow['vpc']}",
         "Name=tag-key,Values=" + ",".join(allow["discovery_tag_keys"]), "--output", "json"],
        capture_output=True, text=True, check=True)
    return json.loads(out.stdout)["SecurityGroups"]


def sources(rule: dict) -> list[tuple[str, str]]:
    """-> [(kind, source)] for one ingress permission. Every source shape AWS can put in
    a rule is enumerated here; an unhandled shape would silently read as no source."""
    return ([("sg", p["GroupId"]) for p in rule.get("UserIdGroupPairs", [])]
            + [("cidr", r["CidrIp"]) for r in rule.get("IpRanges", [])]
            + [("cidr", r["CidrIpv6"]) for r in rule.get("Ipv6Ranges", [])]
            + [("prefix-list", p["PrefixListId"]) for p in rule.get("PrefixListIds", [])])


def violations(groups: list[dict], allow: dict) -> list[str]:
    """Anything sourced from outside the allowlist. SG-to-SG is the only permitted shape;
    a CIDR source must be named in cidr_exceptions with its ticket."""
    ok_sgs = {g["id"] for g in allow.get("allowed_source_security_groups") or []}
    ok_cidrs = {e["cidr"] for e in allow.get("cidr_exceptions") or []}
    bad = []
    for g in groups:
        for rule in g.get("IpPermissions", []):
            port = f"{rule.get('IpProtocol')}/{rule.get('FromPort', 'all')}-{rule.get('ToPort', 'all')}"
            for kind, src in sources(rule) or [("none", "(rule with no source)")]:
                if kind == "sg" and src in ok_sgs:
                    continue
                if kind == "cidr" and src in ok_cidrs:
                    continue
                bad.append(f"{g['GroupId']} ({g['GroupName']}) {port} <- {kind} {src}")
    return bad


def main(argv: list[str]) -> int:
    path = Path(argv[argv.index("--allowlist") + 1]) if "--allowlist" in argv else ALLOWLIST
    allow = yaml.safe_load(path.read_text())
    try:
        groups = describe(allow)
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, OSError) as e:
        detail = getattr(e, "stderr", "") or repr(e)
        print(f"inbound-audit: INCONCLUSIVE - could not read security groups: {detail.strip()}",
              file=sys.stderr)
        return 2
    if not groups:
        print("inbound-audit: INCONCLUSIVE - no security group carried a discovery tag; "
              "either the tags moved or the filter is wrong", file=sys.stderr)
        return 2
    bad = violations(groups, allow)
    for line in bad:
        print(f"INBOUND: unallowlisted rule  {line}")
    names = ", ".join(sorted(g["GroupId"] for g in groups))
    if bad:
        print(f"inbound-audit: {len(bad)} unallowlisted inbound rule(s) across {names} - "
              f"every one is a regression unless {ALLOWLIST.name} is updated with its ticket")
        return 1
    print(f"inbound-audit: OK - {len(groups)} cluster security group(s) ({names}); "
          "every inbound rule is allowlisted, zero CIDR sources unless listed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
