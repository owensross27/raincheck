#!/usr/bin/env python3
"""One shadow day: build it on BOTH runtimes, then prove they agree (orchestration 11).

The cutover gate is "the cluster builds the same data the Mac builds, N clean days
running". This script is one such day (or several at once - the cluster maps over them),
and it is the ENDING the shadow DAG deliberately does not have: a shadow's verdict is a
statement about TWO runtimes, and no task inside one of them can see the other.

  1  STAGE the day's inputs into the shadow root - a server-side copy inside the archive
     bucket, so no bytes cross the wire and the live tree is never written.
  2  PROVE THE INPUTS ARE THE SAME on both sides, with `raincheck.parity` and per Bronze
     partition. Without this the output comparison is a statement about the cold mirror,
     not about the two runtimes: a day whose mirror is a part behind would DIFFER for a
     reason that has nothing to do with Airflow.
  3  CLEAR both sides' outputs for those days. This is cloud 13's trap, encoded: its first
     comparison ran a fresh remote build against a Mac partition built two days earlier
     and reported 1,469,145 vs 1,354,911 rows - 16 gapfill parts had landed in between,
     and it reads exactly like a broken writer. BUILD BOTH SIDES, THEN COMPARE. Neither
     side may be an artifact that was already lying there.
  4  RUN THE CLUSTER SIDE: trigger raincheck_shadow, wait, read the task states. The DAG's
     own plan pod decides which days to build by scanning the shadow root, so step 3 is
     also what makes the days it finds be exactly the days asked for.
  5  RUN THE MAC SIDE: `python -m raincheck.daily events D` per day and the reduce behind
     them - the identical commands the pods run - into a LOCAL shadow root whose inputs
     are symlinks to the Mac's own tree. Symmetric with the cluster on purpose: `gold`
     rolls a month out of whatever Silver its root holds, so a reduce over the Mac's full
     August could never equal a reduce over the two days the shadow staged.
  6  RECORD THE TWO PROOFS per day - content equality per partition, and outcome equality
     between the two runtimes - as one entry in research/orch-11-shadow.json.

Parity is CONTENT equality (rows + a sha over the rows), never bytes: parquet-mr permutes
footer encoding across JVM sessions, and the two sides are two sessions by construction.
Comparison logic lives in `raincheck.parity` and is not re-implemented here.

  scripts/shadow-day.py DAY [DAY ...]
Exit: 0 every day clean - 1 a day differs - 2 INCONCLUSIVE (a step could not be run)
Env: RAINCHECK_SHADOW_ROOT (the Mac side's scratch root, default ~/raincheck-shadow),
     RAINCHECK_ARCHIVE_ROOT (the Mac's real tree, default <repo>/data), and the
     RAINCHECK_COLD_* credentials from .env.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

DAG_ID = "raincheck_shadow"
SHADOW_DAG = REPO / "dags" / "raincheck_shadow.py"
LEDGER = REPO / "research" / "orch-11-shadow.json"
# The Bronze kinds `events` reads (date IN (D, D+1)), and the reference tables its
# schedule join needs. Both are READ off the shadow root by the pods, so both have to be
# there before a plan pod can call the day buildable.
KINDS = ("vp", "tu")
REFS = ("trips", "trip_stops", "stops", "service_days")
# What a shadow day is compared on. The mapped index's own two tables, and the reduce's -
# always at the PARTITION level: `parity.compare` on a table root lists every partition
# the other side does not hold as missing, so a table-level compare of a two-day shadow
# against a full Mac tree can never be `ok` and says nothing when it is not.
SILVER = ("events", "leg_hours")
GOLD = ("cell_hour_speed", "cell_hour_route")
POLL_S = 20
DEADLINE_S = 3600
# The relative distance two runtimes' floating-point aggregates may sit apart and still be
# the same number. MEASURED 2026-08-25 on the first clean shadow: `leg_hours.dist_m_sum` is
# a distributed `sum()` of DOUBLEs, floating-point addition is NOT associative, and the two
# runtimes split their input differently (`local[6]` over local files against `local[2]`
# over s3a), so the last bit moves - **max relative difference 1.24e-15 over 16,773 of
# 72,087 rows, i.e. one ULP**, and the whole-table total differs by 3e-8 in 2.2e8. A sha
# over such a column therefore CANNOT match across two runtimes, ever, on correct data.
# 1e-9 is six orders of magnitude above what was measured and far below any difference that
# could mean something about a bus: anything wider is a real disagreement.
FLOAT_TOL = 1e-9
NUMERIC = ("DOUBLE", "FLOAT", "REAL", "DECIMAL")


def fail(rc: int, message: str):
    print(f"shadow-day: {message}", file=sys.stderr)
    raise SystemExit(rc)


def dotenv() -> dict:
    """The Makefile's `-include .env`, for a script make cannot run: `make` may not shell
    out to a cluster-only tool (tests/test_cloud_cost.py), and this one drives kubectl."""
    out = {}
    for line in (REPO / ".env").read_text().splitlines() if (REPO / ".env").exists() else []:
        if (m := re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", line)):
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


ENV = dotenv()
BUCKET = os.environ.get("RAINCHECK_COLD_BUCKET") or ENV.get("RAINCHECK_COLD_BUCKET", "")
ENDPOINT = os.environ.get("RAINCHECK_COLD_ENDPOINT") or ENV.get("RAINCHECK_COLD_ENDPOINT", "")
MAC = Path(os.environ.get("RAINCHECK_ARCHIVE_ROOT") or ENV.get("RAINCHECK_ARCHIVE_ROOT")
           or REPO / "data")
LOCAL = Path(os.environ.get("RAINCHECK_SHADOW_ROOT") or Path.home() / "raincheck-shadow")


def prefix() -> str:
    """The shadow root, read out of the DAG that writes it - one spelling, and the two
    sides of the comparison cannot drift apart into two different trees."""
    m = re.search(r'(?m)^SHADOW = "(s3a?://[^"]+)"', SHADOW_DAG.read_text())
    if not m:
        fail(2, f"no SHADOW root declared in {SHADOW_DAG}")
    root = m.group(1)
    if root.split("//", 1)[1].strip("/").count("/") == 0:
        fail(2, f"{root} is a bucket root, not a shadow prefix - it is the cold mirror")
    return root


SHADOW = prefix()                                     # s3a://bucket/prefix, the DAG's own
S3 = "s3://" + SHADOW.split("//", 1)[1]               # the same tree, the aws CLI spelling


def credentials() -> None:
    """The cold token, under the names DuckDB's own credential chain reads, so that
    `parity.compare` can open the shadow side at all. The Makefile does this for `make
    coldpush`; a script make may not run has to do it itself. Set on the ENVIRONMENT and
    never on a command line - argv is world-readable in `ps`, which is the rule cold.py
    follows and the reason the aws calls below inherit rather than carry."""
    os.environ.setdefault("AWS_DEFAULT_REGION", "auto")   # R2 rejects real region names
    for cold, aws_name in (("RAINCHECK_COLD_KEY_ID", "AWS_ACCESS_KEY_ID"),
                           ("RAINCHECK_COLD_SECRET", "AWS_SECRET_ACCESS_KEY"),
                           ("RAINCHECK_COLD_ENDPOINT", "AWS_ENDPOINT_URL")):
        value = os.environ.get(cold) or ENV.get(cold, "")
        if value and not os.environ.get(aws_name):
            os.environ[aws_name] = value


def aws(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["aws", "s3", "--endpoint-url", ENDPOINT, *args],
                          capture_output=True, text=True)


def plain() -> dict:
    """The environment WITHOUT the R2 token, for everything that talks to real AWS or runs
    a stage locally.

    Measured the hard way: credentials() puts the Cloudflare keys under the AWS_* names,
    because that is the only chain DuckDB's httpfs reads - and kubeconfig's `aws eks
    get-token` reads exactly the same names, so every kubectl call in this process tree
    came back `You must be logged in to the server (Unauthorized)` with a perfectly valid
    cluster in front of it. The same names also flip `spark.py` onto its s3a branch, which
    is not the shape a LOCAL Mac build runs in. One scrub, both problems."""
    return {k: v for k, v in os.environ.items()
            if k not in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                         "AWS_ENDPOINT_URL", "AWS_DEFAULT_REGION")}


def airflow(*args: str) -> str:
    p = subprocess.run(["kubectl", "exec", "-n", "raincheck", "deploy/airflow-scheduler",
                        "-c", "scheduler", "--", "airflow", *args],
                       capture_output=True, text=True, env=plain())
    if p.returncode:
        fail(2, f"airflow {' '.join(args)}: {p.stderr.strip()[-400:]}")
    return p.stdout


def rows(out: str) -> list[dict]:
    """The CLI writes structured logging onto stdout beside its own output, so the JSON is
    carved out rather than parsed off line 1 - and the carve cannot be "from the first
    bracket", because those log lines are `... [info ] setup plugin ...` and the first
    bracket is theirs. Try each opening bracket in turn against the last closing one; the
    first that parses IS the payload, and an Airflow that printed no JSON at all raises
    here rather than reading as an empty result set."""
    end = out.rindex("]") + 1 if "]" in out else 0
    for start in (i for i, c in enumerate(out) if c == "["):
        try:
            return json.loads(out[start:end])
        except json.JSONDecodeError:
            continue
    fail(2, f"no JSON in the airflow CLI output: {out.strip()[-400:]}")


def spans(days: list[str]) -> list[tuple[str, str]]:
    """(kind, date) for every Bronze partition a day is built from: `events` reads
    date IN (D, D+1), because a Leg that started on D can still be running at 03:00."""
    dates = sorted({d for day in days for d in
                    (day, (date.fromisoformat(day) + timedelta(days=1)).isoformat())})
    return [(kind, d) for kind in KINDS for d in dates]


def stage(days: list[str]) -> None:
    """Server-side, inside one bucket: no bytes cross the wire and the source is the cold
    mirror the Mac's own coldpush wrote. `sync` and not `cp`, so re-running a shadow day
    is free."""
    todo = [(f"archive/{kind}/date={d}",) for kind, d in spans(days)]
    todo += [("ref",)] + [(f"silver/{t}",) for t in REFS]
    for (rel,) in todo:
        p = aws("sync", f"s3://{BUCKET}/{rel}", f"{S3}/{rel}", "--no-progress")
        if p.returncode:
            fail(2, f"staging {rel}: {p.stderr.strip()[-300:]}")
        print(f"shadow-day: staged {rel} ({len(p.stdout.splitlines())} object(s) copied)",
              flush=True)


def reconcile(rows: list[dict]) -> list[str]:
    """Replace, from the MAC'S OWN Bronze, every input partition where the mirror is not
    what the Mac reads.

    MEASURED 2026-08-25 and it is not a mirror defect: `s3://<bucket>/archive` is a UNION
    of this Mac's capture and the EC2 capture box's overlapping capture of the same feed
    (ticket 19), and `coldcheck` syncs `--size-only`, so whichever pushed an hour first
    keeps it. The two versions hold the SAME feed messages - identical in every column and
    even identical in file size - and differ only in `fetched_at`, each poller's own fetch
    instant. That is not cosmetic: `enrich` orders on it and `events` derives the TU churn
    features (pred_first_horizon_s, pred_err_10min_s, pred_range_s, pred_n_changes) from
    it, so a day built off the box's copy legitimately differs from the Mac's.

    A shadow asks whether two RUNTIMES agree, so the inputs are pinned to one capture and
    the difference is recorded rather than tolerated. `rm` before `sync`: an upload skips a
    destination object of the same size whose timestamp is newer, which every server-side
    copy here is."""
    fixed = []
    for row in rows:
        base = row["a"].split(f"{S3}/", 1)[1]
        for part in row["differing"]:
            rel = f"{base}/{part}" if part else base
            aws("rm", "--recursive", "--quiet", f"{S3}/{rel}")
            p = aws("sync", str(MAC / rel) + "/", f"{S3}/{rel}/", "--no-progress")
            if p.returncode:
                fail(2, f"reconciling {rel}: {p.stderr.strip()[-300:]}")
            fixed.append(rel)
    print(f"shadow-day: reconciled {len(fixed)} input partition(s) the capture box also "
          f"holds - the shadow reads THIS Mac's Bronze, not the union", flush=True)
    return fixed


def clear(days: list[str]) -> None:
    """Neither side may be an artifact that was already lying there (cloud 13's trap), and
    on the cluster side this is also what makes the plan pod find exactly these days."""
    import shutil

    for day in days:
        for table in SILVER:
            aws("rm", "--recursive", "--quiet", f"{S3}/silver/{table}/service_date={day}")
            shutil.rmtree(LOCAL / "silver" / table / f"service_date={day}", ignore_errors=True)
    for month in sorted({d[:7] for d in days}):
        for table in GOLD:
            aws("rm", "--recursive", "--quiet", f"{S3}/gold/{table}/month={month}")
            shutil.rmtree(LOCAL / "gold" / table / f"month={month}", ignore_errors=True)
    print(f"shadow-day: cleared {len(days)} day(s) on both sides - both are built from "
          "scratch below", flush=True)


def link_local() -> None:
    """The Mac side's root: its OUTPUTS are its own, its INPUTS are the Mac's real tree by
    symlink. Nothing is copied and nothing under the live tree is written - `events` and
    `gold` only ever write silver/{events,leg_hours} and gold/, which are real directories
    here."""
    (LOCAL / "silver").mkdir(parents=True, exist_ok=True)
    for name, target in [("archive", MAC / "archive"), ("ref", MAC / "ref")] + \
            [(f"silver/{t}", MAC / "silver" / t) for t in REFS]:
        link = LOCAL / name
        if not link.is_symlink():
            link.symlink_to(target)
        elif link.readlink() != target:
            fail(2, f"{link} points at {link.readlink()}, not {target}")


def cluster(days: list[str]) -> dict:
    """Trigger the shadow DAG and wait. The run id names the days it was asked for, so the
    record and the Airflow row can always be lined up afterwards."""
    run_id = f"shadow-{days[0]}-{len(days)}d-{datetime.now(timezone.utc):%H%M%S}"
    airflow("dags", "trigger", DAG_ID, "-r", run_id)
    print(f"shadow-day: triggered {DAG_ID} {run_id}", flush=True)
    deadline = time.monotonic() + DEADLINE_S
    while True:
        # The RUN's state first, and the tasks' second. A mapped task's instances appear as
        # the expansion happens, so a poll that lands between two of them sees a set of task
        # rows that are all terminal while the run is nowhere near over.
        run = next((r for r in rows(airflow("dags", "list-runs", DAG_ID, "-o", "json"))
                    if r["run_id"] == run_id), None)
        states = rows(airflow("tasks", "states-for-dag-run", DAG_ID, run_id, "-o", "json"))
        live = [r for r in states if r["state"] in (None, "", "queued", "running",
                                                    "scheduled", "up_for_retry", "deferred")]
        if run and run["state"] in ("success", "failed") and not live:
            break
        if time.monotonic() > deadline:
            fail(2, f"{run_id} still running after {DEADLINE_S}s: "
                    f"{[(r['task_id'], r['state']) for r in live]}")
        time.sleep(POLL_S)
    tally: dict[str, list[str]] = {}
    for r in states:
        tally.setdefault(r["task_id"], []).append(r["state"])
    print(f"shadow-day: {run_id} {run['state']} - "
          + ", ".join(f"{t}={'/'.join(s)}" for t, s in sorted(tally.items())), flush=True)
    return {"run_id": run_id, "state": run["state"], "tasks": tally}


def mac(days: list[str]) -> dict[str, int]:
    """The identical commands the pods run, in the identical process form: since ticket 07
    a declared stage with an argv runs as its own process on `make daily` too."""
    link_local()
    env = {**plain(), "RAINCHECK_ARCHIVE_ROOT": str(LOCAL)}
    out = {}
    for day in days:
        out[day] = subprocess.call([sys.executable, "-m", "raincheck.daily", "events", day],
                                   cwd=REPO, env=env)
    out["gold"] = subprocess.call(
        [sys.executable, "-m", "raincheck.daily", "gold", json.dumps(days)], cwd=REPO, env=env)
    return out


def explain(con, a_files: list[str], b_files: list[str]) -> dict:
    """WHICH columns two builds of one partition disagree on, and by how much.

    Asked only when the shas differ, because a sha says THAT and never WHAT - and on a
    float aggregate the answer is usually "the last bit", which is not a disagreement about
    the data (see FLOAT_TOL). Key-free on purpose: a partition's natural key is not the same
    from one table to the next, so each column is compared as a MULTISET (`except all` gives
    the count) and its magnitude is bounded by pairing the two sides' SORTED values - a
    one-ULP perturbation can only swap neighbours, so the pairwise distance stays an upper
    bound on the per-row one."""
    read = "read_parquet(?, union_by_name = true)"
    schema = {r[0]: r[1] for r in
              con.execute(f"DESCRIBE SELECT * FROM {read}", [a_files]).fetchall()}
    out = {}
    for name, kind in schema.items():
        col = '"' + name.replace('"', '""') + '"'
        n = con.execute(f"SELECT count(*) FROM (SELECT {col} FROM {read} EXCEPT ALL "
                        f"SELECT {col} FROM {read})", [a_files, b_files]).fetchone()[0]
        if not n:
            continue
        row = {"rows": n, "type": kind, "float": kind.startswith(NUMERIC)}
        if row["float"]:
            paired = (f"SELECT max(abs(a.v - b.v) / nullif(abs(b.v), 0)) FROM "
                      f"(SELECT {col} v, row_number() OVER (ORDER BY {col}) rn FROM {read}) a "
                      f"JOIN (SELECT {col} v, row_number() OVER (ORDER BY {col}) rn FROM "
                      f"{read}) b USING (rn)")
            row["max_rel"] = con.execute(paired, [a_files, b_files]).fetchone()[0]
        out[name] = row
    return out


def compare(remote: str, local: Path) -> dict:
    """The content proof for ONE partition, exact first.

    `parity.compare` is left exactly as the T17 gate uses it - one definition of equal, and
    an exact one. What this adds is the SECOND question a shadow has to ask when the exact
    answer is no: is the difference a disagreement about the data, or is it floating-point
    addition being non-associative across two differently-partitioned runtimes? A partition
    is `ok_within_tolerance` only if the row counts match, every differing column is a
    floating-point one, and every one of them is inside FLOAT_TOL. A changed row count, a
    string or integer column, or a float beyond the bound is a real difference and stays
    one."""
    from raincheck import parity

    try:
        report = parity.compare(remote, str(local))
        row = {"a": remote, "b": str(local), "ok": report.ok, "differing": report.differing,
               "rows": {p: report.a[p][0] for p in sorted(report.a)},
               "sha": {p: report.a[p][1][:12] for p in sorted(report.a)},
               "detail": report.lines()[-1] if report.ok else str(report)}
        if report.differing and not (report.only_in_a or report.only_in_b):
            con = parity.connect(remote)
            a, b = parity.partitions(remote, con), parity.partitions(str(local))
            row["columns"] = {p: explain(con, a[p], b[p]) for p in report.differing}
            row["ok_within_tolerance"] = all(
                report.a[p][0] == report.b[p][0] and cols and all(
                    c["float"] and c["max_rel"] is not None and c["max_rel"] <= FLOAT_TOL
                    for c in cols.values())
                for p, cols in row["columns"].items())
    except Exception as e:                      # unreadable side: could not check, never ok
        return {"a": remote, "b": str(local), "ok": None, "differing": None,
                "detail": f"INCONCLUSIVE: {e}"}
    return row


def settled(row: dict) -> bool:
    """Equal, or equal to within the floating-point bound this shadow states."""
    return bool(row["ok"] or row.get("ok_within_tolerance"))


def main(argv: list[str]) -> int:
    if not argv:
        fail(2, "usage: scripts/shadow-day.py DAY [DAY ...]")
    if not (BUCKET and ENDPOINT):
        fail(2, "RAINCHECK_COLD_BUCKET / _ENDPOINT are unset - see .env")
    credentials()
    days = sorted(argv)

    stage(days)
    inputs = [compare(f"{S3}/archive/{kind}/date={d}", MAC / "archive" / kind / f"date={d}")
              for kind, d in spans(days)]
    for row in inputs:
        print(f"shadow-day: INPUT {row['a']}: {row['detail'].splitlines()[-1]}", flush=True)
    # Bronze is what the archiver wrote, not an aggregate of it, so the inputs are held to
    # EXACT equality - the tolerance below is about a distributed sum and nothing else.
    fixed = reconcile([r for r in inputs if not r["ok"]])
    for rel in fixed:                       # re-proved one partition at a time, not the lot
        again = compare(f"{S3}/{rel}", MAC / rel)
        if not again["ok"]:
            fail(2, f"{rel} still differs after reconciling: {again['detail']}")
    if any(row["differing"] is None or (not row["ok"] and not row["differing"])
           for row in inputs):
        fail(2, "an input partition is missing on one side, which reconciling cannot fix - "
                "the two sides would not read the same Bronze, so nothing downstream would "
                "be a statement about the runtimes. Run `make coldpush` and try again.")

    clear(days)
    run = cluster(days)
    rcs = mac(days)

    entries, worst = [], 0
    for day in days:
        content = [compare(f"{S3}/silver/{t}/service_date={day}",
                           LOCAL / "silver" / t / f"service_date={day}") for t in SILVER]
        content += [compare(f"{S3}/gold/{t}/month={day[:7]}",
                            LOCAL / "gold" / t / f"month={day[:7]}") for t in GOLD]
        # PROOF 2, and it is independent of every sha above: the two runtimes' own record
        # of what happened. A build that wrote the right bytes and reported a failure, or
        # reported success on a day it never expanded to, is a cutover defect the digests
        # cannot see. The cluster's record is Airflow's task states; the Mac's is the rc
        # daily.py exits with, in checks.rc()'s own vocabulary.
        cluster_ok = (run["state"] == "success"
                      and len(run["tasks"].get("events", [])) == len(days)
                      and set(run["tasks"].get("events", [])) == {"success"}
                      and run["tasks"].get("gold") == ["success"])
        outcome = {"cluster": run["tasks"], "cluster_ok": cluster_ok,
                   "mac_rc": rcs[day], "mac_gold_rc": rcs["gold"],
                   "ok": bool(cluster_ok and rcs[day] == 0 and rcs["gold"] == 0)}
        ok = all(settled(c) for c in content) and outcome["ok"]
        entries.append({"day": day, "recorded_utc": datetime.now(timezone.utc).isoformat(),
                        "run_id": run["run_id"], "shadow_root": SHADOW, "mac_root": str(LOCAL),
                        "content": content, "outcome": outcome,
                        "inputs_equal": True, "inputs_reconciled": fixed,
                        "clean": ok})
        worst = max(worst, 0 if ok else 1)
        print(f"\nshadow-day: {day} {'CLEAN' if ok else 'NOT CLEAN'}", flush=True)
        for c in content:
            if c["ok"]:
                verdict = "EQUAL"
            elif c.get("ok_within_tolerance"):
                worst = max((col["max_rel"] or 0) for cols in c["columns"].values()
                            for col in cols.values())
                names = sorted({n for cols in c["columns"].values() for n in cols})
                verdict = (f"EQUAL to {worst:.1e} relative on {', '.join(names)} "
                           f"(floating-point sum order, bound {FLOAT_TOL:.0e})")
            else:
                verdict = c["detail"]
            print(f"  content {c['a'].rsplit('/', 2)[-2]}/{c['a'].rsplit('/', 1)[-1]}: "
                  f"{verdict}", flush=True)
        print(f"  outcome cluster={'ok' if cluster_ok else run['tasks']} "
              f"mac rc={rcs[day]} gold rc={rcs['gold']}", flush=True)

    ledger = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(ledger + entries, indent=1) + "\n")
    clean = sum(e["clean"] for e in ledger + entries)
    print(f"\nshadow-day: recorded {len(entries)} day(s) in {LEDGER} "
          f"({clean} clean day(s) on the ledger)", flush=True)
    return worst


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
