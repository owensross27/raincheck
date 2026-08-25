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


@pytest.mark.parametrize("absent", ["coldgaps", "eras"])
def test_what_is_deliberately_not_in_the_nightly_is_not_in_the_nightly(absent):
    """`coldgaps` covers Mac-era subway positions nobody can recover, so it would page every
    morning forever. `eras` is a real check whose PLACE is ticket 09's call, which is why
    ticket 01 left it out of the declaration. (`gold` was on this list until ticket 06: it
    was the reduce INSIDE daily.build, and it became a stage of its own the moment `events`
    became one pod per Service date, which is the one thing that cannot share it.)

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
    # gapfill carries an argv now (ticket 06), so the driver SPAWNS it (ticket 07) - stub
    # that seam too, or this test runs the real fill against whatever root the env names
    monkeypatch.setattr(daily, "spawn", lambda argv: ran.append(argv[0]) or 0)
    monkeypatch.setattr(daily, "data_root", lambda: Path("/nowhere"))
    monkeypatch.setattr(daily, "precip", lambda month: ran.append(f"precip {month}") or 1)

    daily.main(["gapfill"])
    assert ran == ["gapfill"]
    with pytest.raises(SystemExit) as exit:
        daily.main(["precip"])
    assert "daily: FAILED - precip" in str(exit.value)
    assert len(ran) == 1 + len(daily.precip_months(daily.date.today()))
    with pytest.raises(SystemExit, match="not a declared stage"):
        daily.main(["coldgaps"])


# --- the third outcome (orchestration ticket 07) ---------------------------------------
#
# A TASK STATE CARRIES NO rc. The number comes from the stage pod and reaches Airflow
# through the operator's own exit handling, which is success-or-failure - so unless
# something names the code, a gate that COULD NOT CHECK is indistinguishable from one that
# found a real gap. `skip_on_exit_code` names it, and the pinned property is negative:
# nothing renders INCONCLUSIVE as failed and nothing renders it as ok.


def test_only_a_gate_that_runs_its_module_may_land_a_pod_in_skipped():
    """Both halves of the rule, off the declaration. A gate is the declaration's own word
    for a stage whose output is a VERDICT, and a verdict is the thing with three values.
    The other half is the conflation inverted: GNU make exits 2 for ANY recipe failure, so
    wiring the skip onto a make target would file a genuinely broken recipe as "could not
    check" - which is why the mapping refuses a stage with no process form."""
    for stage in declared():
        rc = raincheck_stage.skip_rc(stage)
        if stage["retry"] == "gate":
            assert rc == daily.INCONCLUSIVE_RC, f"{stage['name']} cannot say INCONCLUSIVE"
            assert raincheck_stage.command(stage)[:2] == ["python", "-m"]
        else:
            assert rc is None, f"{stage['name']} is not a gate but may skip on rc {rc}"
        # never 0 and never 1: a success is not a skip, and neither is a real failure
        assert rc not in (0, 1)


def test_the_skip_code_is_the_check_rows_own_verdict_and_not_a_number_in_a_dag():
    """The task state is a RENDERING; the persisted batch under <root>/checks/check=<name>/
    is the record. This is the seam between them, and it is read from the declaration the
    DAG image bakes - the same file `stages()` parses - rather than typed here, because a
    second copy of a contract is how the two runtimes start disagreeing."""
    from raincheck import checks

    could_not = checks.Row("gapverify", "vp", checks.INCONCLUSIVE, "no pair to compare")
    assert raincheck_stage.constant("INCONCLUSIVE_RC") == checks.rc([could_not])
    assert daily.INCONCLUSIVE_RC == checks.rc([could_not])
    assert re.search(r"(?m)^INCONCLUSIVE_RC = ", raincheck_stage.DECLARATION.read_text())


def test_the_report_counts_a_stage_that_could_not_check_apart_from_one_that_failed(capsys):
    """Neither number inflates the other. A real gap outranks a not-run check, so the run
    still ends FAILED - but the skipped stage is named on its own line and is absent from
    the failure list, and a run with only skips does not exit like a run that broke."""
    def run(*crumbs):
        return json.dumps([{"task_id": t, "map_index": -1, "state": st, "duration": 1.0}
                           for t, st in crumbs])

    with pytest.raises(SystemExit) as exit:
        daily.report(run(("gapverify", "skipped"), ("gapcheck", "failed")))
    assert str(exit.value) == "daily: FAILED - gapcheck (every stage ran; see above)"
    assert "INCONCLUSIVE - gapverify" in capsys.readouterr().out

    with pytest.raises(SystemExit) as exit:
        daily.report(run(("gapverify", "skipped"), ("gapcheck", "success")))
    assert exit.value.code == daily.INCONCLUSIVE_RC   # not 1, and not a clean exit either

    # and a soft stage joins neither list, exactly as it joins neither in the driver
    daily.report(run(("coldcheck", "skipped"), ("gapcheck", "success")))


def test_a_quiet_morning_is_not_an_inconclusive_and_only_a_gate_can_be_one(capsys):
    """The conflation pointing the other way, and the one this rendering could newly cause.
    `skipped` is what a ZERO-LENGTH dynamic expansion lands in too (ticket 06: nothing to
    build, nothing to fill), so counting every skip as "could not check" would report a
    quiet morning as an inconclusive nightly - every quiet morning. Only a GATE carries the
    mapping, in the DAG and here, so only a gate's skip is a verdict. It still prints its
    raw state and never `ok`."""
    transport = [s.name for s in daily.STAGES if s.retry != "gate" and not s.soft]
    assert transport, "the declaration has no non-gate stage to skip"
    daily.report(json.dumps([{"task_id": t, "map_index": -1, "state": "skipped",
                              "duration": None} for t in transport]))   # exits 0
    printed = capsys.readouterr().out
    assert " ok " not in printed and printed.count("skipped") == len(transport)
    assert "INCONCLUSIVE" not in printed


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
    ordered = [t.task_id for t in dag.tasks]
    # every declared stage, in declared order, and a report that ends it. The graph holds
    # MORE tasks than the declaration since ticket 06 - one plan per mapped axis - so this
    # is the property and not a list: a copy here would just be a third declaration.
    assert [t for t in ordered if t in names] == names
    assert ordered[-1] == "report" and ordered.count("report") == 1
    # ...linear: every consecutive pair is an edge, and no edge ever runs backwards
    for a, b in zip(ordered, ordered[1:]):
        assert b in dag.get_task(a).downstream_task_ids, f"{a} does not lead to {b}"
    for task in dag.tasks:
        for down in task.downstream_task_ids:
            assert ordered.index(down) > ordered.index(task.task_id), f"{task.task_id} -> {down}"
    assert dag.get_task("report").downstream_task_ids == set()
    for task in dag.tasks:
        # == and not `.value`: a MAPPED task carries the rule as the plain string it was
        # given, an unmapped one as the enum, and both compare equal to it (measured 3.2.2)
        assert task.trigger_rule == "all_done", f"{task.task_id} can be skipped by an upstream red"
    for stage in declared():
        assert dag.get_task(stage["name"]).retries == (0 if stage["retry"] == "gate" else 3), \
            stage["name"]
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


# --- the fan-out (ticket 06) ------------------------------------------------------------

def test_the_declared_axes_this_runtime_maps_are_mapped_and_the_reduce_is_not():
    """The acceptance row, against the DAG Airflow builds. What is mapped is exactly what
    the declaration says is mappable and this runtime buys pods for - no stage is named
    here or there - and the rollup is a single task standing behind them, because one
    session rolling N months beats N sessions rolling one.

    A mapped stage is still `stage_task`'s pod: the expansion moves the ARGUMENTS, never
    the shape, so N days is the measured pod N times and not a new kind of pod."""
    pytest.importorskip("airflow", reason="airflow is a cluster dependency, not a repo one")
    from airflow.sdk.definitions._internal.contextmanager import DagContext
    from airflow.sdk.definitions.mappedoperator import MappedOperator

    DagContext.current_autoregister_module_name = "raincheck_daily"
    import raincheck_daily
    dag = next(d for d, _ in DagContext.autoregistered_dags if d.dag_id == "raincheck_daily")

    want = {s["name"] for s in declared() if s["fanout"] in raincheck_daily.MAPPED}
    assert want, "this runtime maps no axis at all"
    assert {t.task_id for t in dag.tasks if isinstance(t, MappedOperator)} == want
    # ...and ONE index of each is the placement table's pod with the item as its args:
    # Kubernetes joins command + args, so the process form is untouched and the item is
    # the trailing argument every mapped stage's CLI takes.
    for stage in declared():
        if stage["name"] not in want:
            continue
        built = dag.get_task(stage["name"]).unmap({"arguments": ["ITEM"]}).build_pod_request_obj()
        container = built.spec.containers[0]
        assert container.command == raincheck_stage.command(stage)
        assert container.args == ["ITEM"]
        table = raincheck_stage.pod(raincheck_stage.shape_of(stage["name"]), image=IMAGE)
        assert container.resources.requests == \
            table["spec"]["containers"][0]["resources"]["requests"]
        assert built.spec.node_selector == {"raincheck.io/pool": "burst"}
    for stage in declared():
        if stage["reduces"]:
            reduce = dag.get_task(stage["name"])
            assert not isinstance(reduce, MappedOperator), f"{stage['name']} is mapped"
            # it takes the list its pods were expanded from, from the plan they came from
            assert reduce.cmds[-1] == \
                "{{ ti.xcom_pull(task_ids='plan_" + stage["reduces"] + "') | tojson }}"
            assert stage["reduces"] in raincheck_daily.MAPPED, (
                f"{stage['name']} reduces an axis nothing maps, so its list is always empty")


def test_one_plan_pod_stands_in_front_of_each_mapped_axis():
    """How many pods is a question only a pod can answer - the Service dates come from a
    scan of the data root, which no scheduler has, and a task can be expanded only over an
    XCom. So each mapped axis gets ONE plan task, immediately before the first stage that
    maps on it, in that stage's own measured shape: it is the read that stage did inside
    itself before it was mapped."""
    pytest.importorskip("airflow", reason="airflow is a cluster dependency, not a repo one")
    from airflow.sdk.definitions._internal.contextmanager import DagContext

    DagContext.current_autoregister_module_name = "raincheck_daily"
    import raincheck_daily
    dag = next(d for d, _ in DagContext.autoregistered_dags if d.dag_id == "raincheck_daily")

    ordered = [t.task_id for t in dag.tasks]
    axes = [s["fanout"] for s in declared() if s["fanout"] in raincheck_daily.MAPPED]
    assert sum(t.startswith("plan_") for t in ordered) == len(set(axes))
    for axis in set(axes):
        first = next(s for s in declared() if s["fanout"] == axis)
        plan = dag.get_task(f"plan_{axis}")
        assert ordered[ordered.index(plan.task_id) + 1] == first["name"]
        assert plan.cmds == raincheck_stage.module("daily", "plan", axis, raincheck_stage.XCOM)
        # the same shape as the stage it plans for, so no third opinion about pods exists
        assert plan.build_pod_request_obj().spec.containers[0].resources.requests == \
            dag.get_task(first["name"]).partial_kwargs["pod_template_dict"]["spec"][
                "containers"][0]["resources"]["requests"]
def test_the_three_outcomes_reach_three_different_task_states():
    """The ticket, driven through the OPERATOR'S OWN exit handling rather than around it.

    A task state carries no rc, so this is the only place the mapping actually happens:
    KubernetesPodOperator.cleanup() reads the base container's terminated exit code and
    decides what to raise. Three pods in - 0, 1 and INCONCLUSIVE_RC - and the three
    endings have to be three different things, because a skip that raises like a failure
    is a failure and a skip that raises nothing is an ok.

    The two calls that hit the API server (the already-checked patch and the deletion) are
    stubbed; every line that decides the outcome is the provider's."""
    pytest.importorskip("airflow", reason="airflow is a cluster dependency, not a repo one")
    from airflow.sdk.exceptions import AirflowException, AirflowSkipException
    from airflow.sdk.definitions._internal.contextmanager import DagContext
    from kubernetes.client import models as k8s

    DagContext.current_autoregister_module_name = "raincheck_daily"
    import raincheck_daily                                   # noqa: F401  (registers the DAG)
    dag = next(d for d, _ in DagContext.autoregistered_dags if d.dag_id == "raincheck_daily")

    from airflow.sdk.definitions.mappedoperator import MappedOperator

    def concrete(task):
        # a MAPPED gate (ticket 06) is read through one unmapped index: the kwarg is the
        # same on every pod of the expansion, and only a built operator normalises it
        return task.unmap({"arguments": ["ITEM"]}) if isinstance(task, MappedOperator) else task

    gates = [s["name"] for s in declared() if s["retry"] == "gate"]
    assert gates, "the declaration has no gate to render"
    for task in dag.tasks:
        want = daily.INCONCLUSIVE_RC if task.task_id in gates + ["report"] else None
        # the operator normalises to a list, so [] is "any non-zero exit code is a failure"
        assert concrete(task).skip_on_exit_code == ([want] if want is not None else []), \
            task.task_id

    def pod(exit_code: int):
        state = k8s.V1ContainerState(terminated=k8s.V1ContainerStateTerminated(
            exit_code=exit_code, reason="Completed"))
        return k8s.V1Pod(
            metadata=k8s.V1ObjectMeta(name=f"gapverify-{exit_code}", namespace="raincheck"),
            status=k8s.V1PodStatus(
                phase="Succeeded" if exit_code == 0 else "Failed",
                container_statuses=[k8s.V1ContainerStatus(
                    name="base", image="x", image_id="", ready=False, restart_count=0,
                    state=state)]))

    operator = concrete(dag.get_task(gates[0]))
    # The exit code is read off the BASE container by name, and the placement table calls
    # its container `stage`. The operator renames it when it stamps `pod_template_dict`,
    # which is the only reason the lookup resolves - if it stopped renaming, or if a
    # base_container_name were set here, `skip_on_exit_code` would silently never fire and
    # every inconclusive would land as a failure. Measured on the cluster 2026-08-25:
    # the pods really do report `container=base` with the stage's own command in it.
    built = operator.build_pod_request_obj()
    assert operator.base_container_name == "base"
    assert [c.name for c in built.spec.containers] == ["base"]
    assert built.spec.containers[0].command == raincheck_stage.command(
        next(d for d in declared() if d["name"] == gates[0]))

    operator.patch_already_checked = lambda *a, **k: None
    operator.process_pod_deletion = lambda *a, **k: None
    operator.is_istio_enabled = lambda *a, **k: False   # it READS the pod: a live API call

    ends = {}
    for code in (0, 1, daily.INCONCLUSIVE_RC):
        try:
            operator.cleanup(pod=pod(code), remote_pod=pod(code))
            ends[code] = "success"
        except AirflowSkipException:          # a subclass of AirflowException: order matters
            ends[code] = "skipped"
        except AirflowException:
            ends[code] = "failed"
    assert ends == {0: "success", 1: "failed", daily.INCONCLUSIVE_RC: "skipped"}
    assert len(set(ends.values())) == 3       # and no two of them are the same state

    # the pod carrying the number is KEPT, so `kubectl get pod -o jsonpath=...exitCode`
    # still has it: an inconclusive is debuggable, not just distinguishable
    assert operator.on_finish_action.value == "delete_succeeded_pod"
