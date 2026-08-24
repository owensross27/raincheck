"""The nightly DAG (orchestration ticket 05), as data.

The claims here are the ones that fail SILENTLY at 06:00 rather than loudly in a review:

  the graph IS the declaration     - task ids, their order and every edge come from
                                     daily.STAGES, so "gapfill before gapcheck" cannot be
                                     true in one runtime and false in the other
  every edge is all_done           - a red gate must not cost the day's build
  catch-up off, one run, 06:00 NY  - each stage is already a bounded catch-up; replaying
                                     intervals multiplies scans and recovers nothing
  run ids read daily-YYYY-MM-DD    - and the DAG still SERIALIZES, which is a separate
                                     thing from importing: a custom timetable that is not
                                     a registered plugin dies in the dag-processor
  a gate calls the module          - GNU make exits 2 for ANY recipe failure, so a check
                                     reached through make cannot say INCONCLUSIVE
  no task is built any other way   - a stage that is not a stage_task() is a stage without
                                     the measured pod, or worse, one running in-process
  the ending is one sentence       - report() prints daily.py's own exit line from
                                     Airflow's record, and a SOFT stage never joins it

Only the first group needs Airflow, which is a CLUSTER dependency and deliberately not in
pyproject, so exactly one test skips on this Mac. It is not left unrun: it is run for real
against the cluster's own versions (Airflow 3.2.2 + cncf-kubernetes 10.17.1) in a throwaway
venv, and inside docker/Dockerfile's dags stage on every image build.
"""
import ast
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

from raincheck import daily

ROOT = Path(__file__).parents[1]
DAGS = ROOT / "dags"
PLUGINS = ROOT / "plugins"
NIGHTLY = DAGS / "raincheck_daily.py"
IMAGE = "the-image:under-test"

# Set BEFORE anything imports airflow (collection happens before any test runs): the plugin
# registry is read from this folder, and a temporary AIRFLOW_HOME keeps `import airflow`
# from writing a config into the developer's home directory.
os.environ.setdefault("AIRFLOW__CORE__PLUGINS_FOLDER", str(PLUGINS))
os.environ.setdefault("AIRFLOW_HOME", tempfile.mkdtemp(prefix="raincheck-airflow-"))
os.environ.setdefault("RAINCHECK_IMAGE", IMAGE)

sys.path.insert(0, str(DAGS))
import raincheck_stage                        # noqa: E402  (the DAG folder is on sys.path in a pod)

raincheck_stage.PLACEMENT = ROOT / "deploy" / "k8s" / "raincheck" / "build.yaml"
raincheck_stage.DECLARATION = ROOT / "src" / "raincheck" / "daily.py"


def declared() -> list[dict]:
    return raincheck_stage.stages()


# --- the declaration is the graph -------------------------------------------------------

def test_the_dag_reads_the_declaration_rather_than_holding_a_copy_of_it():
    """The parse is the seam: this image has no raincheck package (the stages run in pods on
    cloud 03's image) and a DAG file may not import one, so the contract arrives as data.
    What comes back has to be the same tuple `make daily` runs, field for field."""
    assert [s["name"] for s in declared()] == [s.name for s in daily.STAGES]
    for got, want in zip(declared(), daily.STAGES):
        assert (got["entrypoint"], got["retry"], got["soft"], got["fanout"], got["argv"]) == \
            (want.entrypoint, want.retry, want.soft, want.fanout, want.argv)


def test_the_nightly_names_no_stage_and_builds_no_task_by_hand():
    """Every task in the graph is a `stage_task(...)`, and the ONE that is spelled out is the
    report - which is not a stage. A task built any other way is a task with no measured pod
    behind it; a callable here would be a stage running inside the scheduler, on the floor."""
    tree = ast.parse(NIGHTLY.read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id.endswith(("Operator", "stage_task"))]
    assert calls, "the nightly builds no tasks at all"
    assert {c.func.id for c in calls} == {"stage_task"}
    spelled = [c.args[0].value for c in calls if isinstance(c.args[0], ast.Constant)]
    assert spelled == ["report"], f"the nightly names its own stages: {spelled}"


@pytest.mark.parametrize("absent", ["coldgaps", "eras", "gold"])
def test_what_is_deliberately_not_in_the_nightly_is_not_in_the_nightly(absent):
    """`coldgaps` covers Mac-era subway positions nobody can recover, so it would page every
    morning forever. `eras` is a real check whose PLACE is ticket 09's call, which is why
    ticket 01 left it out of the declaration. `gold` is the reduce inside daily.build over
    the months the built days touched; it only needs its own task once `events` is one pod
    per Service date, which is ticket 06's fan-out.

    Asserted against the DECLARATION and not by grepping the DAG file: this file's own prose
    has to be able to NAME what it is keeping out, and a grep that cannot tell a warning from
    a task can never pass (notify 01 measured that shape). What stops a hand-added task is
    the test above - the only task id spelled anywhere in the nightly is `report`."""
    assert absent not in [s["name"] for s in declared()]


# --- a gate must be able to say INCONCLUSIVE --------------------------------------------

def test_every_gate_invokes_the_module_and_never_the_make_target():
    """orch 03 measured it both ways: GNU make exits 2 for ANY recipe failure, so a module rc
    of 1 arrives as 2 and "checked, data missing" becomes indistinguishable from "could not
    check". A gate reached through `make` is a gate that cannot report its own verdict."""
    for stage in declared():
        command = raincheck_stage.command(stage)
        if stage["retry"] == "gate":
            assert command[:2] == ["python", "-m"], f"{stage['name']} is a gate run through make"
        assert stage["argv"] or stage["entrypoint"].startswith("make:")


def test_every_stages_command_exists_and_every_stage_has_a_measured_pod():
    """A dangling target or a stage the placement table does not place is a 06:00 failure
    with a five-line traceback; both are one grep away here."""
    makefile = (ROOT / "Makefile").read_text()
    for stage in declared():
        command = raincheck_stage.command(stage)
        if command[0] == "make":
            assert re.search(rf"(?m)^{command[3]}:", makefile), f"no `{command[3]}` target"
        else:
            module = command[2].split(".", 1)[1]
            assert (ROOT / "src" / "raincheck" / f"{module}.py").exists(), f"no {module} module"
        assert raincheck_stage.shape_of(stage["name"]) in ("raincheck-stage", "raincheck-spark")


def test_the_one_stage_form_runs_that_stage_and_exits_on_its_own_outcome(monkeypatch, capsys):
    """`python -m raincheck.daily <stage>` is what every task pod runs. It has to expand the
    stage over its own axes exactly as `make daily` does - precip is 1-2 MRMS months in one
    pod here - and exit on THAT stage's verdict, because Airflow owns the ordering now."""
    ran = []
    monkeypatch.setattr(daily, "run", lambda target, **v: ran.append(target) or 0)
    monkeypatch.setattr(daily, "data_root", lambda: Path("/nowhere"))
    monkeypatch.setattr(daily, "precip", lambda month: ran.append(f"precip {month}") or 1)

    daily.main(["gapfill"])
    assert ran == ["gapfill"]
    with pytest.raises(SystemExit) as exit:
        daily.main(["precip"])
    assert "daily: FAILED - precip" in str(exit.value)
    assert len(ran) == 1 + len(daily.precip_months(daily.date.today()))
    with pytest.raises(SystemExit, match="not a declared stage"):
        daily.main(["gold"])


# --- the ending -------------------------------------------------------------------------

def test_the_report_prints_the_drivers_own_sentence_from_airflows_record():
    """One sentence, one home: `make daily` exits with it after running the stages itself and
    the report task prints it from the states of pods it never saw. A SOFT stage is absent
    from the failure list for the same reason it is absent from the driver's."""
    crumbs = json.dumps([
        {"task_id": "prune", "map_index": -1, "state": "success", "duration": 4.0},
        {"task_id": "gapfill", "map_index": -1, "state": "success", "duration": 12.4},
        {"task_id": "coldcheck", "map_index": -1, "state": "failed", "duration": 1.0},
        {"task_id": "gapcheck", "map_index": -1, "state": "failed", "duration": 3.0},
    ])
    with pytest.raises(SystemExit) as exit:
        daily.report(crumbs)
    assert str(exit.value) == "daily: FAILED - gapcheck (every stage ran; see above)"


def test_the_report_prints_declared_order_and_never_paints_a_skip_as_ok(capsys):
    """Ticket 07 renders INCONCLUSIVE as a skipped task. A skip printed as `ok` is exactly
    the rendering five incidents bought the rule against, and the order is the driver's."""
    daily.report(json.dumps([
        {"task_id": "events", "map_index": -1, "state": "skipped", "duration": None},
        {"task_id": "gapfill", "map_index": -1, "state": "success", "duration": 2.0},
    ]))
    printed = [line.split()[1:3] for line in capsys.readouterr().out.splitlines()[:2]]
    assert printed == [["gapfill", "ok"], ["events", "skipped"]]


def test_a_run_with_nothing_to_build_is_green():
    """User story 13: a quiet morning is not an alert. Every stage succeeded, so there is no
    sentence to exit with."""
    daily.report(json.dumps([{"task_id": s.name, "map_index": -1, "state": "success",
                              "duration": 1.0} for s in daily.STAGES]))


# --- delivery ---------------------------------------------------------------------------

def test_the_declaration_and_the_timetable_plugin_are_baked_beside_the_dags():
    """There is no git-sync: a DAG reaches the cluster as an image. The two files it READS at
    parse time have to travel with it, and the timetable has to land in the PLUGINS folder
    or the serialized DAG cannot be decoded by the component that reads it back."""
    stage = (ROOT / "docker" / "Dockerfile").read_text().split("AS dags")[1]
    assert re.search(r"(?m)^COPY .*\bplugins /opt/airflow/plugins$", stage)
    assert re.search(r"(?m)^COPY .*src/raincheck/daily\.py /opt/airflow/placement/daily\.py$", stage)
    assert raincheck_stage.DECLARATION.name == "daily.py"
    assert (PLUGINS / "raincheck_timetable.py").exists()


# --- the DAG Airflow actually builds ----------------------------------------------------

def test_the_dag_airflow_builds_and_stores_is_the_declaration():
    """The one test that needs Airflow, and it is deliberately one: everything above reads
    files, and this reads the object the scheduler will hold. It also SERIALIZES it, which is
    a separate claim from "it imports" - a `zoneinfo.ZoneInfo` timezone and an unregistered
    custom timetable both import fine and both fail in the dag-processor at 03:00 (measured;
    the first one was real, on this DAG, before this test existed)."""
    pytest.importorskip("airflow", reason="airflow is a cluster dependency, not a repo one")
    import pendulum
    from airflow.sdk.definitions._internal.contextmanager import DagContext
    from airflow.serialization.serialized_objects import DagSerialization
    from airflow.utils.types import DagRunType

    DagContext.current_autoregister_module_name = "raincheck_daily"
    import raincheck_daily                                   # noqa: F401  (registers the DAG)
    dag = next(d for d, _ in DagContext.autoregistered_dags if d.dag_id == "raincheck_daily")

    names = [s["name"] for s in declared()]
    assert [t.task_id for t in dag.tasks] == names + ["report"]
    # the declared linear order, and a report that ends it
    edges = {t.task_id: sorted(t.downstream_task_ids) for t in dag.tasks}
    assert edges == {a: [b] for a, b in zip(names + ["report"], names[1:] + ["report", None])
                     if b is not None} | {"report": []}
    for task in dag.tasks:
        assert task.trigger_rule.value == "all_done", f"{task.task_id} can be skipped by an upstream red"
    for task, stage in zip(dag.tasks, declared()):
        assert task.retries == (0 if stage["retry"] == "gate" else 3), task.task_id
    assert dag.get_task("report").retries == 0

    assert dag.catchup is False
    assert dag.max_active_runs == 1
    assert str(dag.timezone) == "America/New_York"
    assert dag.timetable.summary == "0 6 * * *"

    at = pendulum.datetime(2026, 8, 24, 6, 0, tz="America/New_York")
    stored = DagSerialization.from_dict(DagSerialization.to_dict(dag))   # plugin registry + tz
    assert stored.timetable.generate_run_id(run_type=DagRunType.SCHEDULED, run_after=at,
                                            data_interval=None) == "daily-2026-08-24"
    # a manual trigger keeps Airflow's id: two of them in one day must not collide
    assert stored.timetable.generate_run_id(run_type=DagRunType.MANUAL, run_after=at,
                                            data_interval=None).startswith("manual__")

    # and the pod the report task builds is the placement table's, command filled in
    built = dag.get_task("report").build_pod_request_obj()
    assert built.spec.containers[0].command[:3] == ["python", "-m", "raincheck.daily"]
    assert built.spec.node_selector == {"raincheck.io/pool": "burst"}
