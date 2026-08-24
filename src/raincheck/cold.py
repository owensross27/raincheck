"""The cold-mirror check (ticket 18's `make coldcheck`), on the ticket-02 row vocabulary:
is every local Bronze object present in R2 at the same size?

One `aws s3 sync --size-only --dryrun` of <root>/archive against the bucket - the same
listing the shell recipe ran - folded into one row per top-level archive kind.

INCONCLUSIVE, not FAIL, when the LISTING ITSELF failed (bad credentials, no network, cold
storage unconfigured, nothing local to mirror). That distinction is the whole point: a
listing that did not run tells you nothing about the remote, and reporting it as a gap
sends someone hunting an object that is sitting there. The shell recipe could not make it:
it captured stdout and never looked at aws's exit status, so a failed listing printed
"OK - local Bronze fully present remotely" and exited 0. That false OK is fixed here.

The check stays SOFT - `daily.coldcheck()` owns the re-push-once-then-warn behaviour and
never fails the job. What survives a re-push is the EC2 box's own capture of the same
window (ticket 19): different bytes for an object that is present, not a missing one.
`make coldgaps` is the check that tells drift from loss.

Run: make coldcheck   (python -m raincheck.cold; rc 1 any gap / 2 inconclusive / 0)
"""
import os
import subprocess
import sys
from pathlib import Path

from raincheck import checks
from raincheck.paths import data_root

CHECK = "coldcheck"
# Counts and kind names only - never an object's contents. See checks.py on why a batch
# that reaches Data Docs may not carry feed payload.
CHECK_COLUMNS = checks.CORE + ("kind", "differing")


def kinds(root: Path) -> list[str]:
    """The top-level archive prefixes the push mirrors (the five live kinds, subway_vp,
    static ...) - read off disk, never a hardcoded list, so a new kind is covered the day
    it lands."""
    archive = root / "archive"
    return sorted(p.name for p in archive.iterdir() if p.is_dir()) if archive.is_dir() else []


def dryrun(root: Path, bucket: str, endpoint: str) -> tuple[int, str]:
    """The listing, exactly as the recipe ran it. Credentials go through the environment,
    never argv (argv is world-readable in ps)."""
    aws = os.environ.get("RAINCHECK_AWS", "aws")
    env = {**os.environ, "AWS_DEFAULT_REGION": "auto",  # R2 rejects real region names (18)
           "AWS_ACCESS_KEY_ID": os.environ.get("RAINCHECK_COLD_KEY_ID", ""),
           "AWS_SECRET_ACCESS_KEY": os.environ.get("RAINCHECK_COLD_SECRET", "")}
    p = subprocess.run([aws, "s3", "--endpoint-url", endpoint, "sync", str(root / "archive"),
                        f"s3://{bucket}/archive", "--size-only", "--dryrun", "--no-progress"],
                       capture_output=True, text=True, env=env)
    if p.returncode:
        print(p.stderr.strip(), file=sys.stderr)
    return p.returncode, p.stdout


def kind_of(line: str) -> str | None:
    """The archive prefix a dryrun line names. Real awscli prints the LOCAL side of a
    dryrun relative to its own cwd (ticket 19 found that footgun) and the remote side
    absolute - both carry /archive/<kind>/, so read the last one and stay cwd-independent."""
    _, sep, tail = line.rpartition("/archive/")
    return tail.split("/", 1)[0] if sep and "/" in tail else None


def mirror(root: Path, bucket: str | None = None, endpoint: str | None = None) -> list[checks.Row]:
    """One row per archive kind. Empty batches are the false OK checks.rc warns about, so a
    run with nothing to say emits one inconclusive row rather than none."""
    bucket = bucket or os.environ.get("RAINCHECK_COLD_BUCKET", "")
    endpoint = endpoint or os.environ.get("RAINCHECK_COLD_ENDPOINT", "")
    present = kinds(root)

    def unchecked(detail: str) -> list[checks.Row]:
        # `differing` is NULL, not 0: nothing was counted. Same shape as gapverify's
        # inconclusive row, so a suite reads "not measured" instead of "measured zero".
        return [checks.Row(CHECK, k, checks.INCONCLUSIVE, detail, {"kind": k, "differing": None})
                for k in present or ["archive"]]

    if not (bucket and endpoint):
        return unchecked("cold storage unconfigured - run scripts/cold-storage-wizard.sh")
    if not present:
        # A sync of an empty tree copies nothing and would have exited 0: "OK" for a mirror
        # nothing was compared against. Same false-OK class as gapverify's missing pair.
        return unchecked(f"no local Bronze under {root / 'archive'} to mirror")
    rc, out = dryrun(root, bucket, endpoint)
    if rc:
        return unchecked(f"remote listing failed (aws exit {rc}) - NOT a data gap, re-run "
                         f"before drawing any conclusion")
    differ: dict[str, int] = dict.fromkeys(present, 0)
    for line in out.splitlines():
        k = kind_of(line)
        if k:
            differ[k] = differ.get(k, 0) + 1
    return [checks.Row(CHECK, k, checks.FAIL if n else checks.OK,
                       f"  {n} object(s) missing or size-mismatched remotely" if n else "",
                       {"kind": k, "differing": n})
            for k, n in sorted(differ.items())]


def line(r: checks.Row) -> str:
    if r.outcome == checks.INCONCLUSIVE:
        return f"??? {r.measures['kind']:13s} {r.detail}"
    return (f"{'GAP' if r.outcome == checks.FAIL else 'OK '} {r.measures['kind']:13s} "
            f"{r.measures['differing']} differing{r.detail}")


def main() -> None:
    root = data_root()
    rows = mirror(root)
    for r in rows:
        print(line(r))
    rc = checks.rc(rows)
    print("coldcheck:", {0: "OK - local Bronze fully present remotely",
                         1: "GAP - objects above are missing or size-mismatched remotely",
                         2: "INCONCLUSIVE - the remote was never listed; NOT a gap"}[rc])
    checks.write(root, CHECK, rows, CHECK_COLUMNS)
    sys.exit(rc)


if __name__ == "__main__":
    main()
