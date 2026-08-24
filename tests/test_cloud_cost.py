"""Cloud ticket 08 against a stub aws: the monthly bill review renders actual, run rate
and the delta against the frozen $130 envelope; a crossing is a HARD LOOK that stamps an
unrecorded decision and `--check` keeps failing until someone writes one (never an
auto-stop, never a silent continuation); missing tag data and any aws error are
INCONCLUSIVE (2), never `under budget`. Plus the standing constraint the downscale path
rests on, asserted project-wide: no stage depends on a cluster-only feature."""
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
TICKET = ROOT / ".scratch/cloud/issues/08-cost-guardrails.md"

# Dispatch order matters: the tagged query carries --filter, the account query carries
# neither. --output text is what the script asks for, so the stub emits text, not JSON.
AWS_STUB = """\
echo "$*" >> "$STUB_LOG"
case "$*" in
  *get-tags*)  cat "$STUB_TAGS" ;;
  *--filter*)  cat "$STUB_GROUPS" ;;
  *)           cat "$STUB_ACCOUNT" ;;
esac
"""
BROKEN_STUB = 'echo "$*" >> "$STUB_LOG"; echo "could not connect" >&2; exit 255\n'


def write_stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def run(script: str, env: dict, *args: str) -> subprocess.CompletedProcess:
    """cwd=/ on every run: these scripts resolve their own root and must not need one."""
    return subprocess.run(["bash", str(SCRIPTS / script), *args], cwd="/",
                          env={**os.environ, **env}, capture_output=True, text=True)


def bill_env(tmp_path: Path, groups: str, account: str = "180.00",
             tags: str = "raincheck-cloud", ticket: Path | None = None) -> dict:
    write_stub(tmp_path / "aws", AWS_STUB)
    (tmp_path / "groups").write_text(groups)
    (tmp_path / "account").write_text(account + "\n")
    (tmp_path / "tags").write_text(tags + "\n")
    (tmp_path / "log").write_text("")
    return {"RAINCHECK_AWS": str(tmp_path / "aws"), "STUB_GROUPS": str(tmp_path / "groups"),
            "STUB_ACCOUNT": str(tmp_path / "account"), "STUB_TAGS": str(tmp_path / "tags"),
            "STUB_LOG": str(tmp_path / "log"),
            "RAINCHECK_BILL_TICKET": str(ticket or tmp_path / "ticket.md")}


UNDER = "Amazon Elastic Kubernetes Service\t73.00\nEC2 - Other\t45.00\n"
OVER = "Amazon Elastic Kubernetes Service\t73.00\nEC2 - Other\t61.20\n"


def test_review_of_a_closed_month_reports_lines_total_and_delta(tmp_path):
    r = run("cloud-bill-review.sh", bill_env(tmp_path, UNDER), "2026-07")
    assert r.returncode == 0, r.stderr
    assert "| Amazon Elastic Kubernetes Service | 73.00 |" in r.stdout
    assert "**tagged total (31 of 31 days)** | **118.00**" in r.stdout
    # a closed month covers every day, so the run rate is the actual and the delta is exact
    assert "Run rate 118.00/mo against the $130 envelope: -12.00" in r.stdout
    assert "Account total 180.00 (backstop $210)" in r.stdout
    assert "Verdict: OK" in r.stdout


def test_crossing_the_envelope_is_a_hard_look_with_an_unrecorded_decision(tmp_path):
    r = run("cloud-bill-review.sh", bill_env(tmp_path, OVER), "2026-07")
    assert r.returncode == 1, r.stdout
    assert "Verdict: HARD LOOK - actual $134.20 crossed the $130 line" in r.stdout
    assert "Decision: REQUIRED - not yet recorded" in r.stdout


def test_run_rate_catches_the_drift_a_month_before_the_actual_does(tmp_path):
    """$129 of closed-day spend is under the line as an actual and over it as a rate, on
    every day of a month but the 1st. Catching that IS the point of a monthly review --
    the AWS alarm only fires once the month has already crossed."""
    if _today_day() == 1:
        pytest.skip("no closed days yet this month; the run-rate path needs one")
    r = run("cloud-bill-review.sh", bill_env(tmp_path, "EC2 - Other\t129.00\n"), _current_month())
    assert r.returncode == 1, r.stdout
    assert "Verdict: HARD LOOK - run rate" in r.stdout and "crosses the $130 line" in r.stdout
    assert "Decision: REQUIRED - not yet recorded" in r.stdout


def _today_day() -> int:
    return int(subprocess.run(["date", "-u", "+%d"], capture_output=True, text=True).stdout)


def _current_month() -> str:
    return subprocess.run(["date", "-u", "+%Y-%m"], capture_output=True, text=True).stdout.strip()


def test_absent_tag_data_is_inconclusive_never_under_budget(tmp_path):
    """Measured 2026-08-24: the tag was Active and the tagged total was $0 while the
    account total was $103.18. Reading that $0 as `under envelope` is the exact failure
    this ticket exists to prevent."""
    env = bill_env(tmp_path, "", account="103.18", tags="")
    r = run("cloud-bill-review.sh", env, "2026-07")
    assert r.returncode == 2, r.stdout
    assert "Verdict: INCONCLUSIVE" in r.stdout
    assert "Verdict: OK" not in r.stdout and "HARD LOOK" not in r.stdout


def test_an_aws_error_is_inconclusive_not_a_spend_verdict(tmp_path):
    env = bill_env(tmp_path, UNDER)
    write_stub(tmp_path / "aws", BROKEN_STUB)
    r = run("cloud-bill-review.sh", env, "2026-07")
    assert r.returncode == 2
    assert "NOT a spend verdict" in r.stderr
    assert "Verdict:" not in r.stdout


def test_append_records_one_entry_and_refuses_to_double_record(tmp_path):
    ticket = tmp_path / "ticket.md"
    ticket.write_text("# T8\n")
    env = bill_env(tmp_path, UNDER, ticket=ticket)
    assert run("cloud-bill-review.sh", env, "2026-07", "--append").returncode == 0
    assert ticket.read_text().count("### bill 2026-07") == 1
    again = run("cloud-bill-review.sh", env, "2026-07", "--append")
    assert again.returncode == 2 and "already recorded" in again.stderr
    assert ticket.read_text().count("### bill 2026-07") == 1


def test_check_fails_while_a_crossing_has_no_decision_and_passes_once_it_does(tmp_path):
    ticket = tmp_path / "ticket.md"
    env = bill_env(tmp_path, OVER, ticket=ticket)
    ticket.write_text("# T8\n")
    assert run("cloud-bill-review.sh", env, "2026-07", "--append").returncode == 1
    bad = run("cloud-bill-review.sh", env, "--check")
    assert bad.returncode == 1 and "2026-07" in bad.stdout
    assert "not an auto-stop" in bad.stderr
    ticket.write_text(ticket.read_text().replace(
        "Decision: REQUIRED - not yet recorded", "Decision: dropped the third node 2026-08-02"))
    good = run("cloud-bill-review.sh", env, "--check")
    assert good.returncode == 0, good.stdout + good.stderr


def test_every_crossing_recorded_in_the_real_ticket_carries_a_decision():
    """The standing gate: a $130 crossing may not sit in the log undecided."""
    r = run("cloud-bill-review.sh", {"RAINCHECK_BILL_TICKET": str(TICKET)}, "--check")
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_service_sum_is_not_shadowed_by_a_bash_special_variable(tmp_path):
    """A `GROUPS=` capture is silently ignored by bash 3.2 and the sum reads the caller's
    primary GID instead -- $0.00 spend and a clean bill. The named-variable trap, pinned."""
    r = run("cloud-bill-review.sh", bill_env(tmp_path, UNDER), "2026-07")
    assert "**118.00**" in r.stdout and "**0.00**" not in r.stdout


def test_the_envelope_is_frozen_in_the_script_not_read_from_the_environment(tmp_path):
    env = bill_env(tmp_path, OVER)
    r = run("cloud-bill-review.sh", {**env, "ENVELOPE": "500", "RAINCHECK_ENVELOPE": "500"}, "2026-07")
    assert r.returncode == 1 and "$130 line" in r.stdout


# --- the standing constraint: no stage may depend on a cluster-only feature ----------

CLUSTER_ONLY = re.compile(r"\b(kubectl|eksctl|helm|kubeconfig|aws eks|k8s://|karpenter)\b", re.I)


def make_targets() -> dict[str, str]:
    """target -> its recipe, from the real Makefile. Recipe lines are tab-indented."""
    targets: dict[str, list[str]] = {}
    current = None
    for line in (ROOT / "Makefile").read_text().splitlines():
        if line.startswith("\t"):
            if current:
                targets[current].append(line)
        elif (m := re.match(r"^([A-Za-z][\w-]*):(?!=)", line)):
            current = m.group(1)
            targets.setdefault(current, [])
        elif line and not line.startswith((" ", "#")):
            current = None
    return {t: "\n".join(r) for t, r in targets.items() if r}


def test_no_make_target_shells_out_to_a_cluster_only_tool():
    """Spec section 8's standing constraint, as a test rather than a paragraph: the
    downscale path is only real while every stage runs on one box. The moment a recipe
    needs kubectl, the two-EC2 escape hatch becomes a paragraph."""
    offenders = {t: r for t, r in make_targets().items() if CLUSTER_ONLY.search(r)}
    assert offenders == {}, f"cluster-only tooling in a make recipe: {sorted(offenders)}"


def test_no_stage_module_reaches_for_a_kubernetes_client():
    hits = []
    for src in (ROOT / "src/raincheck").glob("*.py"):
        text = src.read_text()
        if re.search(r"^\s*(import|from)\s+kubernetes\b", text, re.M) or \
           "KUBERNETES_SERVICE_HOST" in text or CLUSTER_ONLY.search(text):
            hits.append(src.name)
    assert hits == [], f"cluster-only dependency in stage code: {hits}"


def test_every_exercised_downscale_stage_is_a_real_make_target():
    """No dangling stage: the exercise list is only proof if each line really runs."""
    script = (SCRIPTS / "downscale.sh").read_text()
    listed = set()
    for block in re.findall(r"_STAGES='([^']*)'", script):
        listed.update(line.split()[0] for line in block.splitlines() if line.strip())
    assert listed, "downscale.sh declares no stages"
    assert listed <= set(make_targets()), f"not make targets: {sorted(listed - set(make_targets()))}"


# --- the downscale script itself ----------------------------------------------------

def test_plan_costs_nothing_and_touches_no_aws(tmp_path):
    """`plan` is the half of the path that needs no approval, so it must not need aws."""
    r = run("downscale.sh", {"RAINCHECK_AWS": str(tmp_path / "nope")}, "plan")
    assert r.returncode == 0, r.stderr
    assert "**total** | **58.97** | **27.00**" in r.stdout
    assert "floor stage: make warm" in r.stdout


def test_up_refuses_without_the_recorded_ok_and_launches_nothing(tmp_path):
    write_stub(tmp_path / "aws", AWS_STUB)
    (tmp_path / "log").write_text("")
    env = {"RAINCHECK_AWS": str(tmp_path / "aws"), "STUB_LOG": str(tmp_path / "log"),
           "STUB_TAGS": "/dev/null", "STUB_GROUPS": "/dev/null", "STUB_ACCOUNT": "/dev/null"}
    r = run("downscale.sh", env, "up")
    assert r.returncode == 1
    assert "Nothing was launched" in r.stderr
    assert (tmp_path / "log").read_text() == "", "up called aws before the gate"
