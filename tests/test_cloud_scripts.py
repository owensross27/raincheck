"""Ticket 19 box scripts against a stub aws, plus cloud 03's parity gate: box-coldpush.sh prune keeps exactly the
unverified/fresh/state files, coldgaps.sh is loud on a missing hour, louder on the budget
marker, and never reports an aws error as a capture gap. The stub mimics real awscli:
dryrun sources print CWD-RELATIVE (the review-confirmed footgun), so every run uses
cwd=/ to prove the scripts are cwd-independent."""
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

SCRIPTS = Path(__file__).parents[1] / "scripts"
OLD = time.time() - 7 * 3600  # past the 360-min prune horizon

# real awscli prints dryrun sources through relative_path() — relative to ITS cwd. The
# scripts cd to ROOT first, so the stub emits ROOT-relative lines from $STUB_PENDING.
COLDPUSH_STUB = """\
for a in "$@"; do [ "$a" = --dryrun ] && { cat "$STUB_PENDING" 2>/dev/null; exit 0; }; done
exit 0
"""


def write_stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def run(script: str, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPTS / script), *args], cwd="/",
                          env={**os.environ, **env}, capture_output=True, text=True)


def coldpush_env(tmp_path: Path) -> dict:
    return {"RAINCHECK_AWS": str(tmp_path / "aws"), "RAINCHECK_ARCHIVE_ROOT": str(tmp_path),
            "RAINCHECK_COLD_BUCKET": "b", "RAINCHECK_COLD_ENDPOINT": "http://x",
            "RAINCHECK_COLD_KEY_ID": "k", "RAINCHECK_COLD_SECRET": "s",
            "STUB_PENDING": str(tmp_path / "pending")}


def make_tree(root: Path) -> dict[str, Path]:
    files = {
        "old_verified": root / "vp/date=2026-08-20/hour=03/part-00.parquet",
        "old_pending": root / "vp/date=2026-08-20/hour=03/part-10.parquet",
        "fresh": root / "tu/date=2026-08-21/hour=11/part-50.parquet",
        "etags": root / "static/etags.json",
    }
    for f in files.values():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    for name in ("old_verified", "old_pending", "etags"):
        os.utime(files[name], (OLD, OLD))
    return files


def test_coldpush_prunes_only_verified_old_files(tmp_path):
    root = tmp_path / "archive"
    files = make_tree(root)
    write_stub(tmp_path / "aws", COLDPUSH_STUB)
    (tmp_path / "pending").write_text("")  # dryrun lists nothing: all old files verified
    r = run("box-coldpush.sh", coldpush_env(tmp_path))
    assert r.returncode == 0, r.stderr
    assert not files["old_verified"].exists() and not files["old_pending"].exists()
    assert files["fresh"].exists() and files["etags"].exists()  # fresh + state survive
    assert not files["old_verified"].parent.exists()  # emptied hour dir removed
    assert root.exists()


def test_coldpush_keeps_unverified_and_goes_loud(tmp_path):
    root = tmp_path / "archive"
    files = make_tree(root)
    write_stub(tmp_path / "aws", COLDPUSH_STUB)
    (tmp_path / "pending").write_text(  # ROOT-relative, exactly as real aws prints it
        "(dryrun) upload: vp/date=2026-08-20/hour=03/part-10.parquet"
        " to s3://b/archive/vp/date=2026-08-20/hour=03/part-10.parquet\n")
    r = run("box-coldpush.sh", coldpush_env(tmp_path))
    assert r.returncode == 1  # an old unverified file is a STUCK failure
    assert files["old_pending"].exists() and not files["old_verified"].exists()
    assert "STUCK" in r.stderr


def test_coldpush_failed_sync_prunes_nothing(tmp_path):
    root = tmp_path / "archive"
    files = make_tree(root)
    write_stub(tmp_path / "aws", "exit 1\n")
    r = run("box-coldpush.sh", coldpush_env(tmp_path))
    assert r.returncode != 0
    assert all(f.exists() for f in files.values())


GAPS_STUB = """\
p=""; for a in "$@"; do case "$a" in s3://*) p="$a";; esac; done
hours="$STUB_HOURS"
case "$p" in *"/$STUB_GAPKIND/"*) hours="$STUB_GAPHOURS";; esac
[ -n "$hours" ] || exit 1
for h in $hours; do echo "                           PRE hour=$h/"; done
"""


def coldgaps_env(tmp_path: Path, **extra: str) -> dict:
    write_stub(tmp_path / "aws", GAPS_STUB)
    hours = " ".join(f"{h:02d}" for h in range(24))
    return {"RAINCHECK_AWS": str(tmp_path / "aws"), "RAINCHECK_COLD_BUCKET": "b",
            "RAINCHECK_COLD_ENDPOINT": "http://x", "RAINCHECK_COLD_KEY_ID": "k",
            "RAINCHECK_COLD_SECRET": "s", "RAINCHECK_ARCHIVE_ROOT": str(tmp_path),
            "STUB_HOURS": hours, "STUB_GAPKIND": "__none__", "STUB_GAPHOURS": "", **extra}


def test_coldgaps_ok_on_complete_day(tmp_path):
    r = run("coldgaps.sh", coldgaps_env(tmp_path), "2026-08-20")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "coldgaps: OK" in r.stdout and r.stdout.count("24/24") == 6


def test_coldgaps_loud_on_missing_hour(tmp_path):
    gap_hours = " ".join(f"{h:02d}" for h in range(24) if h != 7)
    env = coldgaps_env(tmp_path, STUB_GAPKIND="subway_vp", STUB_GAPHOURS=gap_hours)
    r = run("coldgaps.sh", env, "2026-08-20")
    assert r.returncode == 1
    assert "COLDGAPS 2026-08-20 subway_vp: missing hour(s): 07" in r.stdout


def test_coldgaps_loud_on_absent_day(tmp_path):
    # empty prefix: aws s3 ls exits 1 with NO stderr — a real gap, not an infra error
    r = run("coldgaps.sh", coldgaps_env(tmp_path, STUB_HOURS=""), "2026-08-19")
    assert r.returncode == 1
    assert r.stdout.count("missing hour(s): 00 01") == 6


def test_coldgaps_aws_error_is_not_a_gap(tmp_path):
    env = coldgaps_env(tmp_path)
    write_stub(tmp_path / "aws", 'echo "InvalidAccessKeyId" >&2; exit 255\n')
    r = run("coldgaps.sh", env, "2026-08-20")
    assert r.returncode == 2
    assert "InvalidAccessKeyId" in r.stderr and "missing hour" not in r.stdout


def test_coldgaps_loud_on_budget_stop_marker(tmp_path):
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive/STOPPED_BUDGET").write_text("999 bytes at 2026-08-20T00:00:00Z\n")
    r = run("coldgaps.sh", coldgaps_env(tmp_path), "2026-08-20")
    assert r.returncode == 1  # 24/24 hours present, but capture is stopped
    assert "STOPPED over budget" in r.stdout


# --- cutover.sh: the gate must never retire the Mac agent on thin evidence -------------
# Stubs mimic the real tools: ssh carries the remote command as its LAST arg, and the
# box's journal lines are verbatim journald format ("coldgaps: OK — <day> complete for
# all 6 kinds", em dash, as coldgaps.sh actually prints it).
CUTOVER_SSH_STUB = """\
cmd="${@: -1}"
case "$cmd" in
  *journalctl*raincheck-coldgaps*)
      [ "${STUB_UNREACHABLE:-0}" = 1 ] && { echo "ssh: connect: timed out" >&2; exit 255; }
      cat "$STUB_JOURNAL" 2>/dev/null; exit 0 ;;
  *journalctl*raincheck-archiver*)
      cat "$STUB_BOXHOURS" 2>/dev/null; exit 0 ;;
  *is-active*)   exit "${STUB_INACTIVE:-0}" ;;
  *list-units*)  printf '%s' "${STUB_FAILED:-}"; exit 0 ;;
esac
exit 0
"""

# `launchctl print` succeeds while loaded; bootout records the call and unloads it.
CUTOVER_LAUNCHCTL_STUB = """\
case "$1" in
  print)   [ -f "$STUB_BOOTED_OUT" ] && exit 1; exit 0 ;;
  bootout) echo "$2" >> "$STUB_BOOTOUT_LOG"; touch "$STUB_BOOTED_OUT"; exit 0 ;;
esac
exit 0
"""

DAYS7 = [f"2026-08-{d}" for d in range(24, 31)]


def cutover_env(tmp_path: Path, **extra: str) -> dict:
    write_stub(tmp_path / "ssh", CUTOVER_SSH_STUB)
    write_stub(tmp_path / "launchctl", CUTOVER_LAUNCHCTL_STUB)
    return {"PATH": f"{tmp_path}:{os.environ['PATH']}",
            "STUB_JOURNAL": str(tmp_path / "journal"),
            "STUB_BOXHOURS": str(tmp_path / "boxhours"),
            "STUB_BOOTOUT_LOG": str(tmp_path / "bootout.log"),
            "STUB_BOOTED_OUT": str(tmp_path / "booted_out"),
            "RAINCHECK_CUTOVER_FIRST_DAY": "2026-08-24", **extra}


KINDS = ("vp", "tu", "alerts", "subway_tu", "subway_vp", "subway_alerts")


def write_journal(tmp_path: Path, clean_days: list[str], *, box_days=None,
                  drop_hours: int = 0) -> None:
    """Both evidence sources. `clean_days` are green in the bucket; `box_days` (default
    the same) are what the BOX's own archiver journal proves, minus `drop_hours` hours."""
    (tmp_path / "journal").write_text("".join(
        f"Aug 25 02:15:03 ip-172-31-66-109 coldgaps.sh[9]: "
        f"coldgaps: OK — {d} complete for all 6 kinds\n" for d in clean_days))
    # ssh returns what the box's `grep -oE ... | sort -u` already reduced it to
    (tmp_path / "boxhours").write_text("".join(
        f"archive/{k}/date={d}/hour={h:02d}\n"
        for d in (DAYS7 if box_days is None else box_days)
        for k in KINDS for h in range(24 - drop_hours)))


def booted_out(tmp_path: Path) -> bool:
    return (tmp_path / "bootout.log").exists()


def test_cutover_retires_agent_when_all_seven_days_clean(tmp_path):
    env = cutover_env(tmp_path)
    write_journal(tmp_path, DAYS7)
    r = run("cutover.sh", env)
    assert r.returncode == 0, r.stderr
    assert booted_out(tmp_path)
    assert "com.raincheck.archiver" in (tmp_path / "bootout.log").read_text()
    assert "DONE" in r.stdout


def test_cutover_refuses_when_one_day_unproven(tmp_path):
    env = cutover_env(tmp_path)
    write_journal(tmp_path, [d for d in DAYS7 if d != "2026-08-27"])  # 6/7 clean
    r = run("cutover.sh", env)
    assert r.returncode == 1
    assert not booted_out(tmp_path), "retired the Mac agent on 6/7 days"
    assert "2026-08-27" in r.stderr


def test_cutover_refuses_when_box_archiver_is_down(tmp_path):
    env = cutover_env(tmp_path, STUB_INACTIVE="1")
    write_journal(tmp_path, DAYS7)  # history is spotless, but the box is dead NOW
    r = run("cutover.sh", env)
    assert r.returncode == 1
    assert not booted_out(tmp_path), "retired the Mac agent while the box was down"
    assert "archiver not active" in r.stderr


def test_cutover_refuses_when_a_raincheck_unit_failed(tmp_path):
    env = cutover_env(tmp_path, STUB_FAILED="  raincheck-coldpush.service loaded failed failed\n")
    write_journal(tmp_path, DAYS7)
    r = run("cutover.sh", env)
    assert r.returncode == 1
    assert not booted_out(tmp_path)
    assert "raincheck-coldpush.service" in r.stderr


def test_cutover_refuses_when_box_unreachable(tmp_path):
    env = cutover_env(tmp_path, STUB_UNREACHABLE="1")
    write_journal(tmp_path, DAYS7)
    r = run("cutover.sh", env)
    assert r.returncode == 2
    assert not booted_out(tmp_path), "retired the Mac agent without reading the box"


def test_cutover_refuses_when_bucket_is_green_but_the_box_gapped(tmp_path):
    # the hole this closes: the Mac still captures locally, so one manual `make coldpush`
    # can fill a box gap in the bucket and turn coldgaps green. The box's own journal is
    # the evidence that cannot be forged by the Mac.
    env = cutover_env(tmp_path)
    write_journal(tmp_path, DAYS7, drop_hours=3)  # bucket says all 7 clean; box missed 3h/day
    r = run("cutover.sh", env)
    assert r.returncode == 1
    assert not booted_out(tmp_path), "retired the Mac agent on bucket evidence the Mac could have written"
    assert "126/144" in r.stdout  # 6 kinds x 21 hours


def test_cutover_refuses_when_box_journal_has_no_record_of_a_day(tmp_path):
    env = cutover_env(tmp_path)
    write_journal(tmp_path, DAYS7, box_days=[d for d in DAYS7 if d != "2026-08-29"])
    r = run("cutover.sh", env)
    assert r.returncode == 1
    assert not booted_out(tmp_path)
    assert "2026-08-29" in r.stderr


def test_cutover_status_never_touches_the_agent(tmp_path):
    env = cutover_env(tmp_path)
    write_journal(tmp_path, DAYS7)  # gate MET, but --status must still change nothing
    r = run("cutover.sh", env, "--status")
    assert r.returncode == 0
    assert not booted_out(tmp_path), "--status retired the Mac agent"
    assert "gate MET" in r.stdout


# --- cloud 03: the events parity gate, and the T17 backfill's trigger -------------------

def gate(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    """cwd=/ like every other script here. RAINCHECK_PYTHON keeps the gate off the repo
    venv path, which does not exist in a worktree."""
    env = {**os.environ, "RAINCHECK_PARITY_TICKET": str(tmp_path / "ticket.md"),
           "RAINCHECK_PYTHON": sys.executable,
           "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    return subprocess.run(["bash", str(SCRIPTS / "cloud-parity-gate.sh"), *args],
                          cwd="/", env=env, capture_output=True, text=True)


def table(root: Path, values: list[int]) -> Path:
    part = root / "service_date=2026-08-01"
    part.mkdir(parents=True)
    pq.write_table(pa.table({"delay_s": values}), part / "p.parquet")
    return root


def test_the_backfill_is_shut_until_a_parity_pass_is_recorded(tmp_path):
    """The T17 trigger as a mechanism rather than a sentence. "The backfill is the first
    thing the cluster is trusted with, and not before" does not stop a 2,278-file submit;
    a recorded PASS that --backfill-allowed re-reads does."""
    assert gate(tmp_path, "--backfill-allowed").returncode == 1
    a, b = table(tmp_path / "a", [1, 2, 3]), table(tmp_path / "b", [1, 2, 3])
    assert gate(tmp_path, str(a), str(b), "--record").returncode == 0
    allowed = gate(tmp_path, "--backfill-allowed")
    assert allowed.returncode == 0 and "PASS" in allowed.stdout


def test_a_difference_is_recorded_and_still_does_not_open_the_backfill(tmp_path):
    a, b = table(tmp_path / "a", [1, 2, 3]), table(tmp_path / "b", [1, 2, 4])
    r = gate(tmp_path, str(a), str(b), "--record")
    assert r.returncode == 1 and "DIFFERS" in r.stdout
    assert gate(tmp_path, "--backfill-allowed").returncode == 1


def test_an_inconclusive_comparison_records_nothing(tmp_path):
    """rc 2 is "could not check", and recording it would let an unreadable side - an
    expired token, a wrong bucket - open the backfill on a comparison that never ran."""
    a = table(tmp_path / "a", [1, 2, 3])
    r = gate(tmp_path, str(a), str(tmp_path / "nope"), "--record")
    assert r.returncode == 2
    assert "INCONCLUSIVE" in r.stderr
    assert not (tmp_path / "ticket.md").exists(), "an inconclusive run wrote a record"
    assert gate(tmp_path, "--backfill-allowed").returncode == 1
