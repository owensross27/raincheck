"""`make showcase` (orchestration ticket 13): the portfolio surface, as static files.

The cluster has no inbound path from the internet - that is a security-group property and
the deliberate absence of a LoadBalancer, not an oversight (cloud 07) - so the Airflow UI
is reachable by `kubectl port-forward` and by nothing else. It therefore cannot be the
thing anyone is SHOWN. What can be shown is what the run leaves behind, published to the
same public bucket the map page already lives on:

    showcase/index.html   the walkthrough - what the nightly is, and where its output is
    showcase/graph.svg    the task graph, rendered from the declaration
    showcase/run.json     one recorded run: per-instance states and durations

Nothing here re-describes the read API. `files/index.json` (frontend 06) is the
machine-readable contract - every family, its keys, content types, cadences, gate state
and the `contract` integer - generated from `publish.FAMILIES`, so it cannot drift; the
walkthrough links it. `docs/read-api-contract.md` is its human half and ships in the
source tree rather than on the host, because `.md` is not a publishable web payload
(publish.PUBLISHABLE, rule 2) and widening that allowlist for a link is a decision
nobody has made.

THREE THINGS THIS MODULE REFUSES TO RETYPE, because each has exactly one home:

  the graph      `daily.STAGES` (ticket 01) and `MAPPED` in dags/raincheck_daily.py,
                 read below. A picture drawn from a list in a ticket is a picture of a
                 graph that stopped existing the first time somebody added a stage.
  the verdict    `daily`'s own closing lines out of the run's logs. A DagRun has no third
                 state: a run whose only red is an inconclusive gate reads `success`
                 (ticket 07), so the RUN state is exactly the wrong thing to render.
  what is checked  `gx.SUITES` and `gx.NON_NIGHTLY` (orch 08/09/10). Only the nightly
                 tuple renders into the published Data Docs tree.

Run: make showcase                                     re-render from the newest record
     python -m raincheck.showcase --logs <dir> --label probe|shadow|nightly
                                                       record a run, then re-render
     make publish FAMILY=showcase
"""
import argparse
import ast
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from raincheck import daily, gx, publish
from raincheck.paths import REPO

FAMILY = "showcase"
NIGHTLY = REPO / "dags" / "raincheck_daily.py"
RECORDS = REPO / "research"
RECORD_GLOB = "orch-13-run-*.json"

# The serial baseline the fan-out exists to beat, measured BEFORE it existed so the
# improvement has a denominator: one Spark session, seven service days end to end
# (.scratch/orchestration/spec.md, quoted onto orch 06's ticket). Steady state is one day,
# not seven, which is why both numbers travel together - the 1928 s figure alone reads as
# a nightly cost and is not one.
SERIAL = {"seconds": 1928, "service_days": 7, "steady_seconds_per_day": 275}
# An Airflow task is TWO burst pods, not one: the KubernetesExecutor stamps a worker that
# runs `airflow tasks run`, and the KubernetesPodOperator inside it creates the stage pod
# beside it (orch 04, measured). A task instance that never ran buys neither.
PODS_PER_INSTANCE = 2

# The three closing lines daily.verdict() writes, and the only lines read as a verdict.
VERDICT = re.compile(r"daily: (?:OK$|INCONCLUSIVE - |FAILED - )", re.M)
EXIT_CODE = re.compile(r"exit_code=(-?\d+)")
# What one instance publishes. Frozen as a set because it is the whole payload contract of
# run.json AND the no-feed-payload claim: states, names, clock and counts, nothing lifted
# out of a log's free text.
INSTANCE_KEYS = ("task_id", "map_index", "tries", "started", "ended", "seconds",
                 "state", "exit_code")


# --- the graph is the declaration -------------------------------------------------------

class Task(NamedTuple):
    """One task in the graph, not one stage: the graph holds MORE tasks than the
    declaration since ticket 06 - one `plan_<axis>` in front of each mapped axis, and the
    report at the end. `stage` is None for exactly those two kinds."""
    id: str
    kind: str                        # plan | stage | report
    stage: daily.Stage | None = None
    axis: str | None = None          # the axis this task plans, or is mapped over


def mapped_axes() -> tuple[str, ...]:
    """`MAPPED` out of the nightly DAG file: which declared axes THIS runtime buys pods for.

    READ and not imported, the same seam and the same reason as `raincheck_stage.constant()`
    pointing the other way: that file imports Airflow, which is a cluster dependency and
    deliberately not in pyproject, and a copy of the tuple here would be a second home for
    the one opinion the DAG file actually holds."""
    tree = ast.parse(NIGHTLY.read_text())
    return next(tuple(ast.literal_eval(n.value)) for n in tree.body
                if isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == "MAPPED" for t in n.targets))


def tasks() -> list[Task]:
    """The task graph the scheduler really builds, in order.

    This is the DAG file's own loop over the same two inputs, and the airflow-gated test in
    tests/test_showcase.py asserts the two agree task-for-task against the DAG object
    Airflow builds - so the rule is checked rather than trusted. It is repeated here and
    not imported because importing the DAG means importing Airflow."""
    mapped, planned, out = mapped_axes(), set(), []
    for s in daily.STAGES:
        axis = s.fanout if s.fanout in mapped else None
        if axis and axis not in planned:
            planned.add(axis)
            out.append(Task(f"plan_{axis}", "plan", axis=axis))
        out.append(Task(s.name, "stage", s, axis))
    return out + [Task("report", "report")]


def badges(t: Task) -> tuple[str, str]:
    """(role, retry class) for one task, derived from the declaration. Two short lines
    rather than one long one, because the longest of them is 40-odd characters."""
    if t.stage is None:                  # exactly the plan tasks and the report
        if t.kind == "plan":
            return f"plans the {t.axis} axis", "not a stage - a pod that answers 'how many pods'"
        return "the run's own closing lines", "not a stage - it reports, it does not work"
    s, role = t.stage, ""
    if t.axis:
        role = f"mapped - one pod per {t.axis}"
    elif s.reduces:
        role = f"reduce over {s.reduces} - one pod behind the map"
    elif s.fanout:
        role = f"declared axis {s.fanout}, deliberately one pod"
    gate = "GATE - ok / failed / could not check" if s.retry == "gate" else "transport - retries with backoff"
    return role, gate + (" - soft, reports only" if s.soft else "")


# --- the rendered graph -----------------------------------------------------------------

W, X0, NW, NH, PITCH, TOP = 740, 24, 340, 44, 70, 74
CSS = """
.rc-bg{fill:#0b0d10}
.rc-t{font:600 15px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;fill:#e8ebef}
.rc-s{font:12px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;fill:#9aa4b2}
.rc-id{font:600 14px ui-monospace,SFMono-Regular,Menlo,monospace;fill:#e8ebef}
.rc-b{font:11.5px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;fill:#9aa4b2}
.rc-node{fill:#101318;stroke:#2a2f38;stroke-width:1.5}
.rc-gate{stroke:#ffcf87}
.rc-plan{stroke:#2f6ea6;stroke-dasharray:5 4}
.rc-ghost{fill:#101318;stroke:#2a2f38;stroke-width:1.5;opacity:.45}
.rc-edge{stroke:#2a2f38;stroke-width:1.5}
"""


def graph_svg(rows: list[Task] | None = None) -> str:
    """The task graph as one self-contained SVG - standalone in graph.svg and inline in the
    walkthrough, from this one string. Every class is `rc-` prefixed because inlining an
    SVG's <style> into a page makes its selectors the page's."""
    rows = rows or tasks()
    axes = ", ".join(mapped_axes())
    gates = sum(1 for t in rows if t.stage and t.stage.retry == "gate")
    height = TOP + len(rows) * PITCH + 96
    mid = X0 + NW // 2
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" '
         f'height="{height}" role="img" aria-labelledby="rc-title rc-desc">',
         '<title id="rc-title">The raincheck nightly task graph</title>',
         f'<desc id="rc-desc">{len(rows)} tasks in declared order: '
         f'{", ".join(t.id for t in rows)}. Rendered from raincheck.daily.STAGES.</desc>',
         f'<style>{CSS}</style>',
         f'<rect class="rc-bg" width="{W}" height="{height}"/>',
         f'<text class="rc-t" x="{X0}" y="30">raincheck_daily &#183; the nightly, as declared</text>',
         f'<text class="rc-s" x="{X0}" y="52">{len(rows)} tasks &#183; '
         f'{len(daily.STAGES)} declared stages &#183; {gates} gates &#183; '
         f'mapped over {html.escape(axes)} &#183; every edge all_done</text>']
    # every edge first, so a mapped task's stack sits ON its incoming arrow rather than
    # under a smear of one
    for i in range(len(rows) - 1):
        y = TOP + i * PITCH
        o.append(f'<path class="rc-edge" d="M{mid} {y + NH} L{mid} {y + PITCH - 6}"/>')
        o.append(f'<path class="rc-edge" d="M{mid - 5} {y + PITCH - 11} L{mid} {y + PITCH - 4} '
                 f'L{mid + 5} {y + PITCH - 11}" fill="none"/>')
    for i, t in enumerate(rows):
        y = TOP + i * PITCH
        cls = "rc-node" + (" rc-plan" if t.stage is None else
                           " rc-gate" if t.stage.retry == "gate" else "")
        if t.axis and t.kind == "stage":     # a mapped task is N pods: draw the stack
            for d in (12, 6):
                o.append(f'<rect class="rc-ghost" x="{X0 + d}" y="{y + d}" width="{NW}" '
                         f'height="{NH}" rx="9"/>')
        o.append(f'<rect class="{cls}" x="{X0}" y="{y}" width="{NW}" height="{NH}" rx="9" '
                 f'data-task="{html.escape(t.id)}"/>')
        o.append(f'<text class="rc-id" x="{X0 + 16}" y="{y + 27}">{html.escape(t.id)}</text>')
        role, retry = badges(t)
        for n, line in enumerate(b for b in (role, retry) if b):
            o.append(f'<text class="rc-b" x="{X0 + NW + 24}" y="{y + 20 + n * 16}">'
                     f'{html.escape(line)}</text>')
    y = TOP + len(rows) * PITCH + 22
    for n, line in enumerate((
            "A dashed box is not a stage: it is in the graph, not in daily.STAGES.",
            "A stacked box is mapped - one pod per item, and how many is a question only a pod can answer.",
            "An amber box is a GATE: it has three outcomes, and `skipped` on one means COULD NOT CHECK.",
            "A task is two burst pods (the executor's worker, and the stage pod it creates).")):
        o.append(f'<text class="rc-b" x="{X0}" y="{y + n * 18}">{html.escape(line)}</text>')
    return "\n".join(o) + "\n</svg>\n"


# --- one recorded run, out of its own Airflow logs ---------------------------------------

def _state(rows: list[dict]) -> tuple[str, int | None]:
    """This instance's terminal state and the exit code its pod reported, if any.

    A task log is the only durable record here - `airflow dags delete` takes the metadata
    rows with it, and the logs are on R2 under the retention the bucket gives them - so the
    state is DERIVED, from the two endings the runner writes and in the runner's own
    precedence: `cleanup()` raises AirflowSkipException BEFORE AirflowException (orch 07),
    which is why an INCONCLUSIVE gate logs a terminated-with-error container AND a
    "Skipping task." and must be read as the skip. Anything that reached a terminal log
    with neither succeeded."""
    events = [str(r.get("event", "")) for r in rows]
    code = next((int(m.group(1)) for m in map(EXIT_CODE.search, events) if m), None)
    if any(e == "Skipping task." for e in events):
        return "skipped", code
    if any(r.get("level") == "error" for r in rows):
        return "failed", code
    return "success", code


def _instances(log_dir: Path) -> list[dict]:
    """One row per task instance, newest attempt wins.

    Identity comes out of the log LINES (`dag_id`, `run_id`, `task_id`, `map_index`,
    `try_number`), never off the key path: the path is only how the files are found, and a
    log copied to a different prefix would otherwise change what it says about itself."""
    seen: dict[tuple[str, int], dict] = {}
    for p in sorted(log_dir.rglob("attempt=*.log")):
        rows = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
        head = next(r for r in rows if "task_id" in r)
        stamps = sorted(r["timestamp"] for r in rows)
        state, code = _state(rows)
        key = (head["task_id"], head.get("map_index", -1))
        row = {"task_id": key[0], "map_index": key[1], "tries": head.get("try_number", 1),
               "started": stamps[0], "ended": stamps[-1],
               "seconds": round(_secs(stamps[-1]) - _secs(stamps[0]), 1),
               "state": state, "exit_code": code,
               "dag_id": head["dag_id"], "run_id": head["run_id"]}
        if row["tries"] >= seen.get(key, {"tries": 0})["tries"]:
            seen[key] = row
    if not seen:
        raise SystemExit(f"showcase: no Airflow task logs under {log_dir}")
    return [seen[k] for k in sorted(seen)]


def _secs(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def _verdict(log_dir: Path) -> dict:
    """The run's verdict, from `daily`'s own closing lines and from nothing else.

    NOT the DagRun state, which reads `success` on a run whose only red is an inconclusive
    gate (orch 07), and not a tally of task states either: `skipped` on a gate means COULD
    NOT CHECK while `skipped` on any other task means there was nothing to do. daily.report()
    already applies that distinction and prints the sentence; the stage pod's stdout reaches
    the log with a `[base]` prefix in front of it."""
    lines = []
    for p in sorted(log_dir.rglob("attempt=*.log")):
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            event = str(json.loads(line).get("event", ""))
            if VERDICT.search(event):
                lines.append(event.split("[base] ")[-1].strip())
    if lines:
        return {"lines": lines, "source": "daily.verdict(), from the report task's log"}
    return {"lines": [], "source": None,
            "reason": "this run declares no report task, so it writes no daily verdict "
                      "line at all; the per-instance states are its whole record"}


def run_record(log_dir: Path, label: str) -> dict:
    """One run, as data: what ran, for how long, how it ended, and what it cost in pods."""
    rows = _instances(log_dir)
    run = {"dag_id": rows[0]["dag_id"], "run_id": rows[0]["run_id"], "label": label,
           "started": min(r["started"] for r in rows),
           "ended": max(r["ended"] for r in rows)}
    run["wall_seconds"] = round(_secs(run["ended"]) - _secs(run["started"]), 1)
    widest = max(sum(1 for r in rows if r["task_id"] == t)
                 for t in {r["task_id"] for r in rows})
    return {
        "run": run,
        "source": {"kind": "the run's own Airflow task logs",
                   "states": "derived from each log's ending; see raincheck.showcase._state"},
        "instances": [{k: r[k] for k in INSTANCE_KEYS} for r in rows],
        "totals": {"instances": len(rows), "pods": len(rows) * PODS_PER_INSTANCE,
                   "task_seconds": round(sum(r["seconds"] for r in rows), 1),
                   # the fan-out's own claim, measured rather than asserted: the most
                   # instances any ONE task expanded to. 1 means nothing mapped.
                   "widest_map": widest},
        "verdict": _verdict(log_dir),
        "serial_baseline": SERIAL,
    }


def record(path: Path | None = None) -> dict:
    """The recorded run to render: the newest one by its own start, never by file mtime or
    by name (a run id sorts on its own vocabulary, and a probe's does not sort with a
    nightly's)."""
    if path:
        return json.loads(path.read_text())
    found = sorted(RECORDS.glob(RECORD_GLOB))
    if not found:
        raise SystemExit(f"showcase: no recorded run under {RECORDS}/{RECORD_GLOB} - "
                         "record one with --logs <dir> --label <probe|shadow|nightly>")
    return max((json.loads(p.read_text()) for p in found), key=lambda r: r["run"]["started"])


# --- the walkthrough ---------------------------------------------------------------------

PAGE_CSS = """
:root{color-scheme:dark;--bg:#0b0d10;--panel:#101318;--line:#2a2f38;--ink:#e8ebef;
--dim:#9aa4b2;--accent:#7cb7e8;--warn:#ffcf87}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:900px;margin:0 auto;padding:48px 20px 80px}
h1{font-size:30px;line-height:1.2;letter-spacing:-.02em;margin:0 0 8px}
h2{font-size:19px;letter-spacing:-.01em;margin:44px 0 10px;padding-top:20px;
border-top:1px solid var(--line)}
p{margin:0 0 12px}
.lede{color:var(--dim);font-size:17px;margin:0 0 4px}
.note{color:var(--dim);font-size:13.5px}
a{color:var(--accent)}
code{font:13px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--warn)}
ul{margin:0 0 12px;padding-left:20px}
li{margin:0 0 6px}
figure{margin:20px 0;overflow-x:auto}
svg{display:block;max-width:100%;height:auto}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase;
letter-spacing:.06em}
td.n{text-align:right;font-variant-numeric:tabular-nums}
.tag{font-size:12px;padding:1px 7px;border:1px solid var(--line);border-radius:999px;
color:var(--dim)}
.skipped{color:var(--warn)}
.failed{color:#ff9d9d}
.kv{display:flex;flex-wrap:wrap;gap:8px 28px;margin:0 0 12px;padding:0;list-style:none}
.kv b{display:block;font-size:12px;color:var(--dim);font-weight:600;
text-transform:uppercase;letter-spacing:.06em}
.kv span{font-size:19px;font-variant-numeric:tabular-nums}
footer{margin-top:48px;padding-top:20px;border-top:1px solid var(--line);
color:var(--dim);font-size:13px}
"""


def _rows_html(rec: dict) -> str:
    out = []
    for r in rec["instances"]:
        name = r["task_id"] if r["map_index"] < 0 else f'{r["task_id"]} [{r["map_index"]}]'
        code = "" if r["exit_code"] is None else f' <span class="tag">rc {r["exit_code"]}</span>'
        out.append(f'<tr><td><code>{html.escape(name)}</code></td>'
                   f'<td class="{r["state"]}">{r["state"]}{code}</td>'
                   f'<td class="n">{r["seconds"]:.0f}</td></tr>')
    return "\n".join(out)


# What a run of this LABEL does and does not demonstrate. A probe is not a nightly and must
# never be shown as one - it is a throwaway DAG of the same shape, run to prove a mechanism
# on the real cluster while `raincheck_daily` stayed paused - and a shadow is a real nightly
# whose output is compared rather than trusted (orch 11). Keyed on the label the recorder
# was made to supply, so the caveat cannot be lost by forgetting to write it.
SCOPE = {
    "probe": "This run is a <strong>probe, not a nightly</strong>: a throwaway DAG of the "
             "same shape, run against the real cluster to prove two mechanisms - a plan "
             "pod handing its list back through the operator's xcom sidecar, and a gate "
             "exiting 2 landing in <code>skipped</code> while a gate exiting 1 lands in "
             "<code>failed</code> - while <code>raincheck_daily</code> itself stayed "
             "paused. Both are visible in the table above, and the graph above that is the "
             "real nightly's.",
    "shadow": "This run is a <strong>shadow</strong>: the real nightly, run beside the Mac "
              "rather than instead of it, so its output is compared before anything is "
              "retired.",
    "nightly": "This is the nightly.",
}


def page(rec: dict, svg: str) -> str:
    """The walkthrough. No wall-clock stamp anywhere in it, deliberately: a writer's own
    timestamp inside a payload does not measure what a reader wants (a fresh file over a
    week-old table still reads FRESH), and every consumer here dates a payload from its own
    response - `Date` - `Last-Modified`, both on the origin's clock. It also means two
    renders of one record are byte-identical, which a test asserts."""
    run, tot = rec["run"], rec["totals"]
    gates = sorted(daily.GATES)
    nightly = ", ".join(f"<code>{html.escape(s.name)}</code>" for s in gx.SUITES)
    named = ", ".join(f"<code>{html.escape(s.name)}</code>" for s in gx.NON_NIGHTLY)
    families = ", ".join(f"<code>{html.escape(n)}</code>"
                         + (" (gated, dark)" if f.gated else "")
                         for n, f in sorted(publish.FAMILIES.items()))
    # the fan-out's headline claim is "events, five Service dates wide", and the caveat is
    # about the WIDTH alone - the shadow's plan_service_date pod runs the identical
    # `daily plan service_date` scan and produced six (orch 12's recorded run), so the label
    # must not decide this; SCOPE[label] already says separately what a shadow is.
    width = ("." if tot["widest_map"] >= 5 else
             ", so the fan-out at its declared width - one <code>events</code> pod per gap "
             "Service date, five or more of them - is not what this run shows.")
    verdict = rec["verdict"]
    if verdict["lines"]:
        said = ("<pre><code>" + html.escape("\n".join(verdict["lines"])) + "</code></pre>"
                + f'<p class="note">Source: {html.escape(verdict["source"])}.</p>')
    else:
        said = f'<p class="note">{html.escape(verdict["reason"])}.</p>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>raincheck - the nightly, and where its output goes</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<main>

<h1>raincheck - the nightly, and where its output goes</h1>
<p class="lede">NYC bus GTFS-RT crossed with rain: Kafka into Spark/Sedona into GeoParquet,
caught up every morning by an Airflow DAG on EKS, checked by Great Expectations, and
served as static files with no server in front of them.</p>
<p class="note">This page, the graph beside it and the run below are static artifacts on
that same public bucket. They are not a screenshot of a dashboard: the cluster has no
inbound path from the internet - no LoadBalancer, no NodePort, and security groups that
say so - so the Airflow UI is reachable by <code>kubectl port-forward</code> and by
nothing else, and could never be the thing anyone is shown.</p>

<h2>The nightly, as it is declared</h2>
<p>One stage per box. The picture is rendered from
<code>raincheck.daily.STAGES</code> and the DAG file's own <code>MAPPED</code> tuple, so it
is the graph the scheduler builds rather than a drawing of one - add a stage and this
redraws itself.</p>
<figure>{svg}</figure>
<p>Two things in it are worth the space. <strong>The mapped stages are one pod per
item</strong> - the fill and its verifier per feed kind, the build per Service date - and
how many items there are is a question only a pod can answer, because the answer is a scan
of the data root that no scheduler has: that is what each <code>plan_&lt;axis&gt;</code>
task in front of them is for. <strong>The reduce stays one pod</strong>: one Spark session
rolling N months beats N sessions rolling one, and which days actually landed is the
disk's answer, not the graph's.</p>
<p class="note">An expansion to zero is a <code>skipped</code> task and a green run - a
morning with no gaps is not an alert - while a plan that pushed no list at all is
<code>upstream_failed</code>. Those two cannot be confused, which is the property that
makes a fan-out safe to leave running.</p>

<h2>One recorded run</h2>
<ul class="kv">
<li><b>run</b><span>{html.escape(run["run_id"])}</span></li>
<li><b>kind</b><span>{html.escape(run["label"])}</span></li>
<li><b>task instances</b><span>{tot["instances"]}</span></li>
<li><b>burst pods</b><span>{tot["pods"]}</span></li>
<li><b>wall clock</b><span>{run["wall_seconds"]:.0f}s</span></li>
<li><b>task time</b><span>{tot["task_seconds"]:.0f}s</span></li>
</ul>
<table>
<thead><tr><th>task instance</th><th>state</th><th>seconds</th></tr></thead>
<tbody>
{_rows_html(rec)}
</tbody>
</table>
<p>{SCOPE[run["label"]]} Its widest map is <strong>{tot["widest_map"]}
instance{"" if tot["widest_map"] == 1 else "s"} of one task</strong>{width}</p>
<p class="note">Durations are the worker's own wall time, so a short stage's number is
mostly node purchase - measured at 95s for the worker's node and 74s more for the stage
pod's. The pod count is {PODS_PER_INSTANCE} per instance that RAN: an Airflow task is a
worker pod plus the stage pod it creates, and an instance that never started buys neither,
which is why a zero-expansion task appears in the graph above and in no row here.</p>
<p><strong>The verdict is not the DagRun state.</strong> A DagRun has no third state, so a
run whose only red is a gate reporting COULD NOT CHECK still reads <code>success</code> at
the run level. The run's own closing lines are the record:</p>
{said}
<p class="note">Reading a state: <code>skipped</code> on a gate
({", ".join(f"<code>{html.escape(g)}</code>" for g in gates)}) means the check could not
run and nothing is known about that data either way; <code>skipped</code> on anything else
means there was nothing to do. The rows under <code>&lt;root&gt;/checks/</code> are the
record, and every rendering of them - this page included - is a rendering.</p>
<p><strong>The denominator.</strong> Before the fan-out the same work was one Spark session
walking days in series: <strong>{SERIAL["seconds"]}s for a
{SERIAL["service_days"]}-day catch-up</strong>, about
{SERIAL["steady_seconds_per_day"]}s/day at steady state. That is the number the graph above
exists to beat, and it is stated here so an improvement has something to be measured
against.</p>

<h2>What the run checked</h2>
<p>Every stage writes check-RESULT rows, and the last gate validates them with Great
Expectations and rebuilds the report the public host serves:</p>
<ul>
<li><a href="../docs/index.html">Data Docs</a> - the nightly's suites: {nightly}.
Rebuilt whole every run, so <code>docs/index.html</code> is the stable link and a
validation page's URL is one night old at most.</li>
<li>{named} are run by hand, off the nightly - a census of a range that cannot change, and
a read-only census of the built registry. They render into their own directory and are
<strong>not published anywhere</strong>; putting them on this host would be a new family
and a decision, not a link.</li>
</ul>
<p class="note">No feed payload reaches any of this, and that is structural rather than
filtered: a check row carries counts, dates, kinds, hour labels and ratios, the writer
asserts every value is a scalar, and the suites never open Bronze at all. A row that could
not be judged is held out of the frame the validator sees and reported as COULD NOT
CHECK - never flattened into a pass or a failure.</p>

<h2>Where the data is</h2>
<p>One fetch answers the whole surface: <a href="../files/index.json">
<code>files/index.json</code></a> lists every family with its keys, content types, schema
pointers, cadence, writer, <code>Cache-Control</code> and gate state, plus the version
stamps and a <code>contract</code> integer a consumer can refuse on. It is generated from
the publisher's own family table, so it cannot drift from what is actually up here - which
is exactly why this page does not reproduce it. Its human half is
<code>docs/read-api-contract.md</code>, which ships in the source tree rather than on this
host: Markdown is not a publishable web payload, and widening that allowlist for one link
is a decision nobody has made.</p>
<p>On the host today: {families}. A family that lands later appears in
<code>index.json</code> the moment it does.</p>
<p class="note">The gated family is the one derived from an MTA feed. It is built and
refused at the publisher until somebody records having read the redistribution terms -
a precondition of shipping, not a follow-up.</p>

<h2>The map</h2>
<p>The same bucket serves the map page itself: <a href="../index.html">the insight
view</a> - H3 Cells coloured by the wet/dry Speed ratio, with the flood layers beside it.</p>

<footer>Rendered by <code>src/raincheck/showcase.py</code> from the stage declaration, the
DAG's mapped axes and one recorded run - <code>showcase/run.json</code> beside this page is
that record, and <code>showcase/graph.svg</code> is the picture on its own. No clock is
stamped into any of them: date a payload from its own response headers.</footer>

</main>
</body>
</html>
"""


def build(rec: dict, out: Path | None = None) -> list[Path]:
    """Write the family. `out` defaults to the publisher's own source directory, so the
    renderer and `make publish FAMILY=showcase` cannot disagree about where the tree is."""
    out = Path(out) if out else publish.FAMILIES[FAMILY].src()
    out.mkdir(parents=True, exist_ok=True)
    svg = graph_svg()
    written = {"graph.svg": svg,
               "run.json": json.dumps(rec, indent=2) + "\n",
               "index.html": page(rec, svg)}
    for name, text in written.items():
        (out / name).write_text(text)
    return sorted(out / name for name in written)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", type=Path, help="a run's Airflow task logs: record it first")
    ap.add_argument("--label", choices=("probe", "shadow", "nightly"),
                    help="what that run WAS - required with --logs, and not guessable")
    ap.add_argument("--run", type=Path, help=f"one recorded run (default: the newest "
                                             f"{RECORDS.name}/{RECORD_GLOB} by its own start)")
    ap.add_argument("--out", type=Path, help="where to write the family")
    args = ap.parse_args(argv)
    if args.logs:
        if not args.label:
            raise SystemExit("showcase: --logs needs --label probe|shadow|nightly - a run "
                             "that is not a nightly must not be shown as one")
        rec = run_record(args.logs, args.label)
        args.run = RECORDS / f"orch-13-run-{re.sub(r'[^A-Za-z0-9._-]', '_', rec['run']['run_id'])}.json"
        args.run.write_text(json.dumps(rec, indent=2) + "\n")
        print(f"showcase: recorded {rec['run']['run_id']} -> {args.run}", flush=True)
    rec = record(args.run)
    for path in build(rec, args.out):
        print(f"showcase: {path}", flush=True)
    print(f"showcase: {rec['run']['label']} run {rec['run']['run_id']} - "
          f"{rec['totals']['instances']} task instance(s), {rec['totals']['pods']} pods. "
          f"Publish with `make publish FAMILY={FAMILY}`.", flush=True)


if __name__ == "__main__":
    sys.exit(main())
