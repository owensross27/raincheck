"""The showcase surface (orchestration ticket 13), as data.

Three claims are worth a suite here, and each one fails SILENTLY rather than loudly:

  the picture is the graph    a rendered DAG is the easiest thing in this repo to let rot -
                              nothing goes red when a stage joins the declaration and the
                              drawing does not. So the graph is derived, and the derivation
                              is checked against the DAG object Airflow really builds.
  the verdict is not the run  a DagRun has no third state (orch 07). A summary that counts
                              green tasks would publish "success" over a nightly that could
                              not check anything, forever, and look right doing it.
  the honest label            a probe is not a nightly, and a page that quietly shows one as
                              the other is the whole failure this surface exists to avoid.

Only the cross-check against Airflow's own DAG object needs Airflow, which is a CLUSTER
dependency and deliberately not in pyproject, so exactly one test skips on this Mac - and
it is not left unrun: it is run for real in a throwaway venv pinned to the cluster's
versions (Airflow 3.2.2 + apache-airflow-providers-cncf-kubernetes 10.17.1).
"""
import json
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from raincheck import contract, daily, gx, publish, showcase

ROOT = Path(__file__).parents[1]
DAGS = ROOT / "dags"
PLUGINS = ROOT / "plugins"
SVG = "{http://www.w3.org/2000/svg}"

# Set BEFORE anything imports airflow, exactly as tests/test_dag_nightly.py does: the
# plugin registry is read from this folder and a temporary AIRFLOW_HOME keeps `import
# airflow` from writing a config into the developer's home directory.
os.environ.setdefault("AIRFLOW__CORE__PLUGINS_FOLDER", str(PLUGINS))
os.environ.setdefault("AIRFLOW_HOME", tempfile.mkdtemp(prefix="raincheck-airflow-"))
os.environ.setdefault("RAINCHECK_IMAGE", "the-image:under-test")

# --- the fixture, and why it is shaped like this ----------------------------------------
# VERBATIM lines from the probe run's own logs (`gateprobe-1`, kept under
# s3://raincheck-bronze/airflow-logs/dag_id=raincheck_gateprobe/), one per SHAPE the parser
# reads, with only identity and clock substituted through json below. Copied rather than
# composed on purpose: a stub in the wrong format is how this repo once kept a data-loss bug
# green, and every field these lines carry - `event`, `level`, `reason`, `map_index`,
# `try_number`, and the `[base] ` prefix a stage pod's stdout arrives under - is a field
# this module reads.
# The runner's own first line, and it carries NO task_id, no map_index and no dag_id -
# which is why identity is read from the first line that HAS them and never from rows[0].
# Every fixture log below starts with it, because every real one does.
PRE = ('{"timestamp":"2026-08-25T19:28:56.593986Z","level":"info","event":"::group::Pre '
       'Execute","logger":"task","filename":"task_runner.py","lineno":1926}')
HEAD = ('{"timestamp":"2026-08-25T19:28:57.281044Z","level":"info","event":"setup plugin '
        'alembic.autogenerate.schemas","logger":"alembic.runtime.plugins","map_index":-1,'
        '"task_id":"gate_rc2","ti_id":"01a03a60-d8a2-7fcb-8ddd-a74a1a026297","run_id":'
        '"gateprobe-1","dag_id":"raincheck_gateprobe","try_number":1,"filename":'
        '"plugins.py","lineno":37}')
TERMINATED = ('{"timestamp":"2026-08-25T19:29:04.348368Z","level":"error","event":'
              '"Container \'base\': state=\'TERMINATED\', reason=\'Error\', exit_code=2, '
              'message=\'None\'","map_index":-1,"task_id":"gate_rc2","ti_id":'
              '"01a03a60-d8a2-7fcb-8ddd-a74a1a026297","run_id":"gateprobe-1","dag_id":'
              '"raincheck_gateprobe","try_number":1,"logger":"airflow.task.operators.'
              'airflow.providers.cncf.kubernetes.operators.pod.KubernetesPodOperator",'
              '"filename":"pod.py","lineno":1261}')
SKIPPING = ('{"timestamp":"2026-08-25T19:29:04.378147Z","level":"info","event":"Skipping '
            'task.","reason":"Pod gate-rc2-84wxtptu returned exit code 2. Skipping.",'
            '"map_index":-1,"task_id":"gate_rc2","ti_id":"01a03a60-d8a2-7fcb-8ddd-'
            'a74a1a026297","run_id":"gateprobe-1","dag_id":"raincheck_gateprobe",'
            '"try_number":1,"logger":"task","filename":"task_runner.py","lineno":1327}')
FAILED = ('{"timestamp":"2026-08-25T19:29:19.937189Z","level":"error","event":"Task failed '
          'with exception","run_id":"gateprobe-1","ti_id":"01a03a60-d8a3-7d1a-a021-'
          'f9b7d6be6218","try_number":1,"map_index":-1,"dag_id":"raincheck_gateprobe",'
          '"task_id":"gate_rc1","logger":"task","filename":"task_runner.py","lineno":1356}')
STDOUT = ('{"timestamp":"2026-08-25T19:27:47.498357Z","level":"info","event":"[base] ITEM '
          '[\'b\']\\n","try_number":1,"ti_id":"01a03a62-d810-7b40-8a15-78a5b7126cbd",'
          '"run_id":"gateprobe-1","map_index":1,"dag_id":"raincheck_gateprobe","task_id":'
          '"mapped_a","logger":"airflow.providers.cncf.kubernetes.utils.pod_manager.'
          'PodManager","filename":"pod_manager.py","lineno":493}')


def log(root: Path, task_id: str, *, lines=(HEAD,), start="19:00:00", end="19:00:30",
        map_index=-1, tries=1, dag="raincheck_daily", run="daily-2026-08-25", path=None):
    """One task instance's log file, in the layout Airflow's remote handler writes - the
    identity-less Pre Execute line first, exactly as a real one opens."""
    at = path or (f"dag_id={dag}/run_id={run}/task_id={task_id}"
                  + (f"/map_index={map_index}" if map_index >= 0 else "")
                  + f"/attempt={tries}.log")
    pre = json.loads(PRE)
    pre["timestamp"] = f"2026-08-25T{start}.000000Z"
    out = [json.dumps(pre)]
    for line in lines:
        row = json.loads(line)
        row.update(task_id=task_id, map_index=map_index, try_number=tries,
                   dag_id=dag, run_id=run)
        row["timestamp"] = f"2026-08-25T{end}.000000Z"
        out.append(json.dumps(row))
    p = root / at
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(out) + "\n")
    return p


def verdict_line(text):
    row = json.loads(STDOUT)
    row["event"] = f"[base] {text}\n"
    return json.dumps(row)


@pytest.fixture
def run_dir(tmp_path):
    """A run of the real nightly's shape: a plan, a three-wide map, a gate that could not
    check, and a report whose closing line is the verdict."""
    d = tmp_path / "logs"
    log(d, "plan_kind", start="19:00:00", end="19:00:48")
    for i in range(3):
        log(d, "gapfill", map_index=i, start="19:01:00", end=f"19:0{2 + i}:00")
    log(d, "gxcheck", lines=(HEAD, TERMINATED, SKIPPING), start="19:05:00", end="19:05:08")
    log(d, "report", lines=(HEAD, verdict_line("daily: gxcheck skipped in 8s"),
                            verdict_line("daily: INCONCLUSIVE - gxcheck (could not check)")),
        start="19:06:00", end="19:06:10")
    return d


# --- the picture is the graph -----------------------------------------------------------

def test_the_graph_is_the_declaration_and_never_a_list_in_a_ticket():
    """Every declared stage, in declared order, plus the tasks the DAG adds around them.
    A drawing that named its own boxes would be a picture of whatever the graph was on the
    day somebody drew it."""
    rows = showcase.tasks()
    assert [t.id for t in rows if t.kind == "stage"] == [s.name for s in daily.STAGES]
    assert rows[-1].id == "report" and rows[-1].kind == "report"
    assert [t.id for t in rows if t.kind == "plan"] == \
        [f"plan_{a}" for a in showcase.mapped_axes()]


def test_a_plan_task_stands_in_front_of_each_mapped_axis_and_nowhere_else():
    """One plan per mapped AXIS, not per mapped stage - `gapfill` and `gapverify` share
    one - and it comes immediately before the first stage that maps on it, because that is
    where its list is needed and the read it does is that stage's own."""
    rows = showcase.tasks()
    ids = [t.id for t in rows]
    for axis in showcase.mapped_axes():
        first = next(i for i, t in enumerate(rows) if t.kind == "stage" and t.axis == axis)
        assert ids[first - 1] == f"plan_{axis}"
        assert ids.count(f"plan_{axis}") == 1


def test_a_declared_axis_this_runtime_does_not_map_buys_no_plan_and_no_pods():
    """`precip` declares `month` and stays ONE pod deliberately - one or two MRMS months in
    a single Spark session, where a second pod buys a second node and a second JVM to save
    nothing. So the axis is in the declaration and not in the picture's mapped set."""
    unmapped = [s for s in daily.STAGES if s.fanout and s.fanout not in showcase.mapped_axes()]
    assert unmapped, "this test is vacuous if every declared axis is mapped"
    for s in unmapped:
        task = next(t for t in showcase.tasks() if t.id == s.name)
        assert task.axis is None
        assert f"plan_{s.fanout}" not in [t.id for t in showcase.tasks()]
        assert s.fanout in showcase.badges(task)[0]     # named, not hidden


def test_the_mapped_axes_are_read_from_the_dag_file_rather_than_copied(tmp_path, monkeypatch):
    """Which axes this runtime buys pods for is the DAG file's one opinion. Point the reader
    at a different declaration and the picture must follow it - a tuple copied into this
    module would not."""
    fake = tmp_path / "raincheck_daily.py"
    fake.write_text('MAPPED = ("month",)\n')
    monkeypatch.setattr(showcase, "NIGHTLY", fake)
    assert showcase.mapped_axes() == ("month",)
    ids = [t.id for t in showcase.tasks()]
    assert "plan_month" in ids and "plan_kind" not in ids and "plan_service_date" not in ids


def test_the_rendered_graph_names_every_task_and_invents_none():
    svg = showcase.graph_svg()
    root = ET.fromstring(svg)
    drawn = [e.get("data-task") for e in root.iter() if e.get("data-task")]
    assert drawn == [t.id for t in showcase.tasks()]
    assert "eras" in drawn and drawn.index("eras") == len(drawn) - 3   # ...before gxcheck


def test_a_gate_is_drawn_as_a_gate_and_a_task_that_is_not_a_stage_says_so():
    """The two distinctions a reader of this picture has to be able to make: a gate has
    three outcomes and a `skipped` on one means COULD NOT CHECK; a dashed box is in the
    graph and not in the declaration."""
    root = ET.fromstring(showcase.graph_svg())
    style = {e.get("data-task"): e.get("class") for e in root.iter() if e.get("data-task")}
    for t in showcase.tasks():
        gate = t.stage is not None and t.stage.retry == "gate"
        assert ("rc-gate" in style[t.id]) is gate, t.id
        assert ("rc-plan" in style[t.id]) is (t.stage is None), t.id
    assert {t.id for t in showcase.tasks() if "rc-gate" in style[t.id]} == daily.GATES


def test_a_mapped_stage_is_drawn_as_more_than_one_box():
    """"One pod per item" is the whole claim of the fan-out, so a mapped stage is a STACK
    and an unmapped one is a single box."""
    root = ET.fromstring(showcase.graph_svg())
    ghosts = [e for e in root.iter(f"{SVG}rect") if "rc-ghost" in (e.get("class") or "")]
    mapped = [t for t in showcase.tasks() if t.kind == "stage" and t.axis]
    assert mapped and len(ghosts) == 2 * len(mapped)


def test_the_graph_is_well_formed_standalone_svg_and_says_what_it_is():
    """It ships as its own file as well as inline, so it carries its own namespace, its own
    style and a title a screen reader can read."""
    root = ET.fromstring(showcase.graph_svg())
    assert root.tag == f"{SVG}svg" and root.get("role") == "img"
    assert root.find(f"{SVG}title") is not None and root.find(f"{SVG}desc") is not None
    # inlining an SVG's <style> into a page makes its selectors the page's, so every one
    # of them is prefixed - an unprefixed `text{...}` here would restyle the walkthrough
    style = root.find(f"{SVG}style").text
    selectors = [block.split("}")[-1].strip() for block in style.split("{")[:-1]]
    assert selectors and all(sel.startswith(".rc-") for sel in selectors), selectors


def test_the_rendered_graph_is_the_graph_airflow_builds():
    """The one test that needs Airflow. `tasks()` repeats the DAG file's own loop - it has
    to, because importing the DAG means importing Airflow - so the loop is CHECKED against
    the object the scheduler will hold rather than trusted. A picture of a graph nobody runs
    is the failure this whole module is written against."""
    pytest.importorskip("airflow", reason="airflow is a cluster dependency, not a repo one")
    from airflow.sdk.definitions._internal.contextmanager import DagContext

    sys.path.insert(0, str(DAGS))
    import raincheck_stage
    raincheck_stage.PLACEMENT = ROOT / "deploy" / "k8s" / "raincheck" / "build.yaml"
    raincheck_stage.DECLARATION = ROOT / "src" / "raincheck" / "daily.py"
    DagContext.current_autoregister_module_name = "raincheck_daily"
    import raincheck_daily                                   # noqa: F401 (registers the DAG)
    dag = next(d for d, _ in DagContext.autoregistered_dags if d.dag_id == "raincheck_daily")

    assert [t.task_id for t in dag.tasks] == [t.id for t in showcase.tasks()]


# --- one recorded run --------------------------------------------------------------------

def test_a_gates_rc_2_reads_as_could_not_check_and_its_rc_1_as_failed(tmp_path):
    """The distinction three tickets exist to keep: `skipped` is the only terminal state
    Airflow has that is neither success nor failure, and the operator puts an INCONCLUSIVE
    gate there through `skip_on_exit_code`."""
    d = tmp_path / "logs"
    log(d, "gxcheck", lines=(HEAD, TERMINATED, SKIPPING))
    log(d, "gapverify", lines=(HEAD, TERMINATED.replace("exit_code=2", "exit_code=1"), FAILED))
    log(d, "coldpush")
    by = {r["task_id"]: r for r in showcase.run_record(d, "nightly")["instances"]}
    assert (by["gxcheck"]["state"], by["gxcheck"]["exit_code"]) == ("skipped", 2)
    assert (by["gapverify"]["state"], by["gapverify"]["exit_code"]) == ("failed", 1)
    assert (by["coldpush"]["state"], by["coldpush"]["exit_code"]) == ("success", None)


def test_the_skip_wins_over_the_error_line_underneath_it(tmp_path):
    """An INCONCLUSIVE gate logs BOTH: the pod's container terminated with a non-zero code
    (an `error` line) AND the runner's "Skipping task.". Reading them in the other order
    turns every could-not-check into a failure, which is the exact conflation the rc-2
    rendering exists to prevent - so the precedence here is the operator's own, where
    cleanup() raises AirflowSkipException BEFORE AirflowException."""
    d = tmp_path / "logs"
    log(d, "gxcheck", lines=(HEAD, TERMINATED, SKIPPING))
    assert showcase.run_record(d, "nightly")["instances"][0]["state"] == "skipped"


def test_a_task_that_never_ran_leaves_no_log_and_buys_no_pods(run_dir):
    """A zero-length expansion is `skipped` and never scheduled, so it writes no log at
    all - and the count of what a night COST must follow what ran, not what was declared."""
    rec = showcase.run_record(run_dir, "nightly")
    assert "events" not in {r["task_id"] for r in rec["instances"]}
    assert rec["totals"]["instances"] == 6
    assert rec["totals"]["pods"] == 6 * showcase.PODS_PER_INSTANCE == 12


def test_the_widest_map_is_measured_rather_than_asserted(run_dir, tmp_path):
    rec = showcase.run_record(run_dir, "nightly")
    assert rec["totals"]["widest_map"] == 3
    flat = tmp_path / "flat"
    log(flat, "prune")
    assert showcase.run_record(flat, "nightly")["totals"]["widest_map"] == 1


def test_the_newest_attempt_is_the_instance_that_counts(tmp_path):
    """Transport stages retry with backoff, so a real nightly has two logs for one instance.
    The terminal state is the last attempt's; taking the first would publish a blip as the
    night's outcome."""
    d = tmp_path / "logs"
    log(d, "coldpush", lines=(HEAD, TERMINATED, FAILED), tries=1)
    log(d, "coldpush", tries=2, start="19:10:00", end="19:10:12")
    rec = showcase.run_record(d, "nightly")
    assert len(rec["instances"]) == 1
    assert rec["instances"][0]["tries"] == 2 and rec["instances"][0]["state"] == "success"


def test_identity_comes_out_of_the_log_lines_and_not_off_the_key_path(tmp_path):
    """The path is only how the files are found. A log copied under another prefix - which
    is exactly what fetching a run's logs to a working directory does - must not change what
    it says about itself."""
    d = tmp_path / "logs"
    log(d, "gxcheck", path="somewhere/else/attempt=1.log")
    rec = showcase.run_record(d, "probe")
    assert rec["instances"][0]["task_id"] == "gxcheck"
    assert rec["run"]["dag_id"] == "raincheck_daily" and rec["run"]["run_id"] == "daily-2026-08-25"


def test_the_verdict_is_the_drivers_own_closing_line_and_never_the_run_state(run_dir):
    """A DagRun has no third state: this run's every instance is success or skipped, so the
    RUN reads `success` while the night could not check anything. The record therefore
    carries no run state at all - only the sentence daily.verdict() wrote."""
    rec = showcase.run_record(run_dir, "nightly")
    assert rec["verdict"]["lines"] == ["daily: INCONCLUSIVE - gxcheck (could not check)"]
    assert not any(r["state"] == "failed" for r in rec["instances"])
    assert "success" not in json.dumps(rec["run"])


def test_only_a_closing_line_is_a_verdict_and_a_per_stage_line_is_not(run_dir):
    """`daily: gxcheck skipped in 8s` is a per-stage line the same task prints, and it is
    not the run's verdict. Reading every `daily:` line would put one stage's word where the
    night's own summary belongs."""
    rec = showcase.run_record(run_dir, "nightly")
    assert all(line.startswith(("daily: OK", "daily: INCONCLUSIVE - ", "daily: FAILED - "))
               for line in rec["verdict"]["lines"])


def test_a_run_with_no_report_task_says_so_rather_than_inventing_a_verdict(tmp_path):
    d = tmp_path / "logs"
    log(d, "plan_a")
    rec = showcase.run_record(d, "probe")
    assert rec["verdict"]["lines"] == [] and rec["verdict"]["source"] is None
    assert "no report task" in rec["verdict"]["reason"]


def test_the_published_instance_is_a_frozen_field_list_carrying_no_log_prose(run_dir):
    """What run.json promises, and the no-payload rule read from the other side: names,
    states, the clock and counts. Nothing is lifted out of a log's free text - a pod name
    and a node's private address are both in there, and neither belongs on a public host."""
    rec = showcase.run_record(run_dir, "nightly")
    for row in rec["instances"]:
        assert tuple(row) == showcase.INSTANCE_KEYS
    blob = json.dumps(rec)
    assert "gate-rc2-" not in blob and "ec2.internal" not in blob and "ti_id" not in blob


def test_an_empty_log_directory_is_refused_rather_than_rendered_as_a_quiet_night(tmp_path):
    with pytest.raises(SystemExit, match="no Airflow task logs"):
        showcase.run_record(tmp_path, "nightly")


# --- the walkthrough ---------------------------------------------------------------------

@pytest.fixture
def rendered(run_dir):
    rec = showcase.run_record(run_dir, "nightly")
    return rec, showcase.page(rec, showcase.graph_svg())


def test_the_walkthrough_links_the_front_door_and_the_stable_docs_page(rendered):
    """`files/index.json` is the machine-readable contract and `docs/index.html` is the only
    stable Data Docs link - build_data_docs() rebuilds the whole site every run, so a
    validation page's URL carries that run's timestamp and is gone tomorrow."""
    _, html = rendered
    assert 'href="../files/index.json"' in html and 'href="../docs/index.html"' in html
    assert "validations/" not in html
    assert contract.DOC in html          # the human half, named where it actually lives


def test_it_points_at_the_contract_instead_of_restating_it(rendered):
    """A hand-written second copy of the family table drifts from the generated one on the
    first landing. Naming the families is not restating them; repeating their keys, their
    content types or their cache policy is."""
    _, html = rendered
    for restated in (publish.BUILD_CACHE, publish.NO_CACHE, publish.RARE_CACHE,
                     "application/geo+json", "files/cells.geojson", "files/meta.json"):
        assert restated not in html, restated


def test_every_family_on_the_host_is_named_and_the_gated_one_is_marked(rendered):
    _, html = rendered
    for name, fam in publish.FAMILIES.items():
        assert f"<code>{name}</code>" in html
        if fam.gated:
            assert f"<code>{name}</code> (gated, dark)" in html


def test_the_nightly_suites_are_named_published_and_the_others_named_not(rendered):
    """orch 10's split, and it is not a detail: a named GX run renders into its own
    directory and is published NOWHERE, so a page implying every suite is on the host would
    be false about the one thing this page exists to show."""
    _, html = rendered
    assert gx.SUITES and gx.NON_NIGHTLY
    for suite in gx.SUITES:
        assert suite.name in html
    for suite in gx.NON_NIGHTLY:
        assert suite.name in html
    assert "not published anywhere" in html


def test_the_serial_baseline_travels_beside_the_run(rendered):
    """"Faster" with no denominator is not a claim. The measured serial number and the
    steady-state one go together: 1928s alone reads as a nightly cost and is not one."""
    rec, html = rendered
    assert rec["serial_baseline"] == showcase.SERIAL
    assert f'{showcase.SERIAL["seconds"]}s' in html
    assert str(showcase.SERIAL["steady_seconds_per_day"]) in html
    assert str(showcase.SERIAL["service_days"]) in html


def test_a_probe_is_never_shown_as_a_nightly(run_dir):
    """The label is required at record time and it decides what the page CLAIMS. A probe
    proves a mechanism on the real cluster; it is not a night's work, and its map is not
    five Service dates wide."""
    probe = showcase.page(showcase.run_record(run_dir, "probe"), "")
    nightly = showcase.page(showcase.run_record(run_dir, "nightly"), "")
    assert "probe, not a nightly" in probe and "probe, not a nightly" not in nightly
    # three wide either way, so BOTH say the declared width is not what this run shows
    assert "is not what this run shows" in probe and "is not what this run shows" in nightly


def test_a_five_wide_nightly_is_the_one_run_that_claims_the_fan_out(tmp_path):
    d = tmp_path / "logs"
    for i in range(5):
        log(d, "events", map_index=i)
    log(d, "report", lines=(HEAD, verdict_line("daily: OK")))
    rec = showcase.run_record(d, "nightly")
    assert rec["totals"]["widest_map"] == 5
    assert "is not what this run shows" not in showcase.page(rec, "")


def test_no_clock_is_stamped_into_anything_this_module_writes(run_dir, tmp_path):
    """A writer's own timestamp does not measure what a reader wants - a fresh file over a
    week-old table still reads FRESH - and it breaks byte-identity for no gain. Every
    consumer here dates a payload from its own response headers instead."""
    rec = showcase.run_record(run_dir, "nightly")
    assert showcase.page(rec, showcase.graph_svg()) == showcase.page(rec, showcase.graph_svg())
    src = Path(showcase.__file__).read_text()
    assert "datetime.now" not in src and "utcnow" not in src and "time.time" not in src


# --- the family --------------------------------------------------------------------------

def test_the_publisher_accepts_the_tree_this_module_renders(run_dir, tmp_path):
    """Build the tree and run the OTHER module's plan() on it, rather than believing the two
    fit: that is the check that would have caught the `.otf` allowlist gap a night early."""
    out = tmp_path / "showcase"
    written = showcase.build(showcase.run_record(run_dir, "nightly"), out)
    assert [p.name for p in written] == ["graph.svg", "index.html", "run.json"]
    items = publish.plan(showcase.FAMILY, out)
    assert [i.key for i in items] == ["showcase/graph.svg", "showcase/index.html",
                                      "showcase/run.json"]
    assert {i.content_type for i in items} == {"image/svg+xml", "text/html", "application/json"}
    assert all(p.suffix in publish.PUBLISHABLE for p in written)


def test_the_family_is_a_tree_so_its_file_names_owe_no_contract_bump():
    """A tree family promises its PREFIX, so a fourth artifact here is additive under
    contract.PROMISE's subset rule - and renaming the prefix is what would demand a bump."""
    fam = publish.FAMILIES[showcase.FAMILY]
    assert fam.files == () and fam.prefix == "showcase/" and not fam.gated
    assert (showcase.FAMILY, "showcase/**", contract.TREE) in contract.surface()
    assert contract.PROMISE[contract.CONTRACT] <= contract.surface()
    assert contract.SCHEMA["showcase/**"].endswith("showcase.py (orchestration ticket 13)")


def test_the_renderer_writes_where_the_publisher_reads(run_dir):
    """`make showcase` then `make publish FAMILY=showcase` is two commands over ONE
    directory, so the renderer's default is the publisher's own `src()` - never a second
    path that happens to agree today and stops agreeing when the family moves."""
    written = showcase.build(showcase.run_record(run_dir, "nightly"))
    assert {p.parent for p in written} == {publish.FAMILIES[showcase.FAMILY].src()}


# --- recording a run ---------------------------------------------------------------------

def test_recording_a_run_demands_the_label(tmp_path):
    d = tmp_path / "logs"
    log(d, "prune")
    with pytest.raises(SystemExit, match="must not be shown as one"):
        showcase.main(["--logs", str(d), "--out", str(tmp_path / "out")])


def test_the_run_rendered_is_the_newest_one_recorded_by_its_own_start(tmp_path, monkeypatch):
    """Newest by the run's OWN start, never by file name or mtime: a run id sorts on its own
    vocabulary, and `gateprobe-1` sorts after `daily-2026-09-01` while happening before it."""
    monkeypatch.setattr(showcase, "RECORDS", tmp_path)
    for run_id, started in (("gateprobe-1", "2026-08-25T19:25:02Z"),
                            ("daily-2026-09-01", "2026-09-01T10:00:00Z")):
        (tmp_path / f"orch-13-run-{run_id}.json").write_text(json.dumps(
            {"run": {"run_id": run_id, "started": started}}))
    assert showcase.record()["run"]["run_id"] == "daily-2026-09-01"


def test_no_recorded_run_refuses_and_says_how_to_record_one(tmp_path, monkeypatch):
    monkeypatch.setattr(showcase, "RECORDS", tmp_path)
    with pytest.raises(SystemExit, match="record one with --logs"):
        showcase.record()


def test_the_probe_run_this_ticket_recorded_is_on_disk_and_is_what_it_claims():
    """The recorded artifact itself, from the probe's own kept logs. It is committed rather
    than re-fetched because the logs need the cold R2 credential and the render must not:
    `make showcase` on any checkout draws the same page.

    Its content is also the proof orch 07's rendering reached a real scheduler - one gate
    exited 2 and landed in `skipped`, its sibling exited 1 and landed in `failed`."""
    rec = json.loads((showcase.RECORDS / "orch-13-run-gateprobe-1.json").read_text())
    assert rec["run"]["label"] == "probe" and rec["run"]["run_id"] == "gateprobe-1"
    by = {(r["task_id"], r["map_index"]): r for r in rec["instances"]}
    assert (by["gate_rc2", -1]["state"], by["gate_rc2", -1]["exit_code"]) == ("skipped", 2)
    assert (by["gate_rc1", -1]["state"], by["gate_rc1", -1]["exit_code"]) == ("failed", 1)
    assert [k for k in by if k[0] == "mapped_a"] == [("mapped_a", i) for i in range(3)]
    assert rec["totals"] == {"instances": 9, "pods": 18, "task_seconds": 335.9,
                             "widest_map": 3}
    # the zero expansion: declared in that DAG, never scheduled, so it has no row here
    assert not [k for k in by if k[0] == "mapped_empty"]
