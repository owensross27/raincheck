"""Ticket 19 box scripts against a stub aws: box-coldpush.sh prune keeps exactly the
unverified/fresh/state files, coldgaps.sh is loud on a missing hour, louder on the budget
marker, and never reports an aws error as a capture gap. The stub mimics real awscli:
dryrun sources print CWD-RELATIVE (the review-confirmed footgun), so every run uses
cwd=/ to prove the scripts are cwd-independent."""
import os
import stat
import subprocess
import time
from pathlib import Path

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
