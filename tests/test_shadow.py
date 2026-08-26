"""The shadow and its recorder (orchestration ticket 11).

What has to be true before a shadow run is worth anything, and what only a real run can
say:

  the shadow root is a SHADOW    - a prefix of its own, never the bucket root (which is
                                   the cold mirror) and never the tree the Mac serves.
                                   Two writers on one Bronze is a data event.
  every pod goes there           - a rebind that missed one container would leave that
                                   stage building into the default tree, silently
  the graph is the declaration   - the shadow runs a SUBSET of the nightly's declared
                                   stages, named by the declaration and not by a count
  the run says what it skips     - derived from the declaration, so a stage added later
                                   joins the notice without an edit here
  no mutating stage is in it     - the fill, the push and the prune write where the Mac
                                   writes; shadowing cannot prove them and must not run
                                   them (the ticket file says how they get proven)
  the two sides read one Bronze  - the recorder proves the INPUTS equal before it believes
                                   anything about the outputs

The DAG object itself needs Airflow, which is a cluster dependency and deliberately not in
pyproject, so those tests skip here and are run for real in a throwaway venv pinned to the
cluster's versions (Airflow 3.2.2 + cncf-kubernetes 10.17.1) and inside docker/Dockerfile's
dags stage on every image build. Everything else reads files.
"""
import ast
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DAGS = ROOT / "dags"
SHADOW_DAG = DAGS / "raincheck_shadow.py"
IMAGE = "the-image:under-test"

os.environ.setdefault("AIRFLOW__CORE__PLUGINS_FOLDER", str(ROOT / "plugins"))
os.environ.setdefault("AIRFLOW_HOME", tempfile.mkdtemp(prefix="raincheck-airflow-"))
os.environ.setdefault("RAINCHECK_IMAGE", IMAGE)

sys.path.insert(0, str(DAGS))
import raincheck_stage                        # noqa: E402  (the DAG folder is on sys.path in a pod)

raincheck_stage.PLACEMENT = ROOT / "deploy" / "k8s" / "raincheck" / "build.yaml"
raincheck_stage.DECLARATION = ROOT / "src" / "raincheck" / "daily.py"

TREE = ast.parse(SHADOW_DAG.read_text())


def constant(name: str):
    """A module-level literal out of the shadow DAG, read the way raincheck_stage reads the
    declaration - so these tests do not need Airflow to know what the file declares."""
    return next(ast.literal_eval(n.value) for n in TREE.body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == name for t in n.targets))


def declared() -> list[str]:
    return [s["name"] for s in raincheck_stage.stages()]


def driver():
    """scripts/shadow-day.py as a module. It reads the DAG file at import, which is the
    point: one spelling of the shadow root, on both sides of the comparison."""
    spec = importlib.util.spec_from_file_location("shadow_day", ROOT / "scripts" / "shadow-day.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the shadow root --------------------------------------------------------------------

def test_the_shadow_root_is_a_prefix_of_its_own_and_never_a_tree_anything_else_writes():
    """The whole safety story of this DAG is one string. `s3a://raincheck-bronze` is the
    cold mirror of Bronze and holds the reference tables every build reads, so the bucket
    ROOT is exactly the tree a shadow must not write into - and a shadow pointed at the
    Mac's own root would be the two-writers event the ticket exists to avoid."""
    shadow = constant("SHADOW")
    assert shadow.startswith(("s3a://", "s3://")), shadow
    bucket, _, key = shadow.split("//", 1)[1].partition("/")
    assert bucket and key.strip("/"), f"{shadow} is a bucket root, not a shadow prefix"
    assert not Path(shadow).exists()
    table = raincheck_stage.pod("raincheck-spark", image=IMAGE)
    default = [v["value"] for c in table["spec"]["containers"] for v in c["env"]
               if v["name"] == raincheck_stage.ROOT_ENV]
    assert default and shadow not in default, "the shadow root IS the default root"


def test_the_recorder_reads_the_shadow_root_out_of_the_dag_that_writes_it():
    """Two spellings of one tree is how a comparison ends up proving that an empty prefix
    equals an empty prefix. The recorder parses it out of the DAG rather than holding a
    copy, and it refuses a bucket root for the same reason the test above does."""
    shadow_day = driver()
    assert shadow_day.SHADOW == constant("SHADOW")
    assert shadow_day.S3 == "s3://" + constant("SHADOW").split("//", 1)[1]


# --- every pod, and only where it is told -----------------------------------------------

def test_every_container_of_a_shadow_pod_is_rebound_and_none_keeps_the_default():
    """A rebind that missed one container - the init step is a container too - would leave
    that step reading a different tree from the stage it prepares, which is the one failure
    that looks like a clean run."""
    for shape in ("raincheck-stage", "raincheck-spark"):
        spec = raincheck_stage.at_root(raincheck_stage.pod(shape, image=IMAGE), "s3a://b/shadow")
        bound = [v for c in spec["spec"].get("initContainers", []) + spec["spec"]["containers"]
                 for v in c["env"] if v["name"] == raincheck_stage.ROOT_ENV]
        assert bound, shape
        assert {v["value"] for v in bound} == {"s3a://b/shadow"}


def test_a_shape_that_binds_no_root_is_an_error_and_never_a_silent_default():
    """If the placement table ever stopped binding the root, a shadow run would build into
    whatever the image defaults to - on the live tree, at cluster speed. It has to fail
    where it stands."""
    spec = raincheck_stage.pod("raincheck-stage", image=IMAGE)
    for container in spec["spec"].get("initContainers", []) + spec["spec"]["containers"]:
        container["env"] = [v for v in container["env"]
                            if v["name"] != raincheck_stage.ROOT_ENV]
    with pytest.raises(RuntimeError, match=raincheck_stage.ROOT_ENV):
        raincheck_stage.at_root(spec, "s3a://b/shadow")


# --- what a shadow day is made of -------------------------------------------------------

def test_a_shadow_day_is_declared_stages_and_never_a_mutating_one():
    """A shadow day is ONE MAPPED INDEX and the reduce behind it. The three stages that
    write where the Mac also writes are named apart and asserted OUT: shadowing cannot
    prove them, because a shadow that ran them would be the second writer."""
    builds, mutates = constant("BUILDS"), constant("MUTATES")
    assert set(builds) <= set(declared()), f"{builds} is not the declaration's vocabulary"
    assert set(mutates) <= set(declared()), f"{mutates} is not the declaration's vocabulary"
    assert not set(builds) & set(mutates)
    assert constant("AXIS") in {s["fanout"] for s in raincheck_stage.stages()}
    # ...and the mapped one really is mappable, with the reduce standing behind it
    stages = {s["name"]: s for s in raincheck_stage.stages()}
    assert [s for s in builds if stages[s]["fanout"] == constant("AXIS")]
    assert [s for s in builds if stages[s]["reduces"] == constant("AXIS")]


def test_the_stages_a_shadow_leaves_out_are_derived_and_never_a_list_in_this_file():
    """The notice exists so the run SAYS what it is not doing rather than silently skipping
    it - which is only true while the list comes from the declaration. A literal here would
    keep printing the same eight names on the day someone declares a ninth stage, and the
    run would then silently skip that one. Pinned as the nightly pins the same property:
    on the shape of the expression, not on its current value."""
    left_out = next(n for n in TREE.body if isinstance(n, ast.Assign)
                    and any(getattr(t, "id", None) == "_left_out" for t in n.targets))
    assert isinstance(left_out.value, ast.ListComp), "the notice holds a copy of the graph"
    calls = {n.func.id for n in ast.walk(left_out.value)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "stages" in calls, "the notice does not read the declaration"


# --- the recorder's own arithmetic ------------------------------------------------------

def test_a_shadow_day_stages_the_bronze_the_build_actually_reads():
    """`events` reads date IN (D, D+1) - a Leg that started on D can still be running at
    03:00 - so staging D alone would build a short day on the cluster and a whole one on
    the Mac, and the compare would blame the runtime for a missing tail."""
    shadow_day = driver()
    assert shadow_day.spans(["2026-08-22"]) == [
        ("vp", "2026-08-22"), ("vp", "2026-08-23"), ("tu", "2026-08-22"), ("tu", "2026-08-23")]
    # two adjacent days share a date, and it is staged once
    both = shadow_day.spans(["2026-08-22", "2026-08-23"])
    assert len(both) == len(set(both)) == 6


def test_the_recorder_compares_at_the_partition_level_and_holds_both_silver_tables():
    """A compare rooted on a TABLE lists every partition the shadow root does not hold as
    missing and can never be `ok` (cloud 13, measured on the real thing). Both Silver
    tables belong in it: `events` writes leg_hours as well, and a build that got one right
    and the other wrong is exactly what a one-table gate would certify."""
    shadow_day = driver()
    assert set(shadow_day.SILVER) == {"events", "leg_hours"}
    assert shadow_day.GOLD, "the reduce behind the expansion is not compared at all"


# --- the DAG Airflow builds -------------------------------------------------------------

def shadow_dag():
    from airflow.sdk.definitions._internal.contextmanager import DagContext

    DagContext.current_autoregister_module_name = "raincheck_shadow"
    import raincheck_shadow                                  # noqa: F401  (registers the DAG)
    return next(d for d, _ in DagContext.autoregistered_dags if d.dag_id == "raincheck_shadow")


def test_the_shadow_airflow_builds_is_the_nightlys_shape_on_the_shadow_root():
    """The claims a file read cannot make: what Airflow expanded, what it did not, where
    every pod's root points, and that the thing SERIALIZES - a DAG that imports is not a
    DAG that ships (orch 05 lost a nightly to a timezone the encoder refused)."""
    pytest.importorskip("airflow", reason="airflow is a cluster dependency, not a repo one")
    from airflow.sdk.definitions.mappedoperator import MappedOperator
    from airflow.serialization.serialized_objects import DagSerialization

    dag = shadow_dag()
    builds, mutates, axis = constant("BUILDS"), constant("MUTATES"), constant("AXIS")
    ordered = [t.task_id for t in dag.tasks]
    assert [t for t in ordered if t in declared()] == list(builds)
    assert ordered[0] == "disabled" and f"plan_{axis}" in ordered
    assert not set(ordered) & set(mutates), f"a shadow runs a mutating stage: {ordered}"
    assert dag.schedule is None, "a scheduled shadow is a second nightly"
    # the mapped index and the single reduce behind it, exactly as in the nightly
    mapped = {t.task_id for t in dag.tasks if isinstance(t, MappedOperator)}
    assert mapped == {s["name"] for s in raincheck_stage.stages()
                      if s["name"] in builds and s["fanout"] == axis}
    for stage in raincheck_stage.stages():
        if stage["name"] in builds and stage["reduces"]:
            reduce = dag.get_task(stage["name"])
            assert not isinstance(reduce, MappedOperator)
            assert reduce.cmds[-1] == \
                "{{ ti.xcom_pull(task_ids='plan_" + stage["reduces"] + "') | tojson }}"
    # EVERY task, mapped or not, on the shadow root and nothing on the default
    shadow = constant("SHADOW")
    for task in dag.tasks:
        spec = (task.partial_kwargs if isinstance(task, MappedOperator)
                else task.__dict__)["pod_template_dict"]
        bound = [v["value"] for c in spec["spec"].get("initContainers", []) +
                 spec["spec"]["containers"] for v in c["env"]
                 if v["name"] == raincheck_stage.ROOT_ENV]
        assert bound and set(bound) == {shadow}, f"{task.task_id} builds into {bound}"
    # the run says what it is not doing, and it names every one of them
    notice = " ".join(dag.get_task("disabled").cmds)
    for name in declared():
        if name not in builds:
            assert name in notice, f"the run does not say it is skipping {name}"
    assert DagSerialization.from_dict(DagSerialization.to_dict(dag))


# --- the second question, when the shas differ ------------------------------------------

def two_builds(tmp_path, tweak):
    """The same partition twice, the second one perturbed by `tweak(value) -> value`."""
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    pytest.importorskip("duckdb", reason="the compare reads parquet through duck.py")

    rows = [{"cell": f"c{i}", "dist_m_sum": 1000.0 + i, "route_id": "B41"} for i in range(50)]
    out = []
    for name, f in (("a", lambda v: v), ("b", tweak)):
        part = tmp_path / name / "service_date=2026-08-22"
        part.mkdir(parents=True)
        pq.write_table(pa.table({"cell": [r["cell"] for r in rows],
                                 "dist_m_sum": [f(r["dist_m_sum"]) for r in rows],
                                 "route_id": [r["route_id"] for r in rows]}),
                       part / "part-00000.parquet")
        out.append(part)
    return out


def test_a_one_ulp_float_sum_is_the_same_number_and_a_real_difference_is_not(tmp_path):
    """MEASURED on the first shadow: `leg_hours.dist_m_sum` is a distributed sum() of
    DOUBLEs, floating-point addition is not associative, and the two runtimes split their
    input differently - so 16,773 of 72,087 rows differed by at most **1.24e-15 relative**,
    one ULP, on data that is otherwise identical. An exact sha over such a column can never
    match across two runtimes, so a gate built only on it could never go green on a correct
    build. The tolerance is therefore stated, bounded, and asked ONLY after the exact
    question has been answered - `parity.compare` itself is untouched, because the T17
    backfill gate reads it and wants exactness."""
    shadow_day = driver()
    a, b = two_builds(tmp_path, lambda v: v * (1 + 4e-16))
    row = shadow_day.compare(str(a), b)
    assert not row["ok"], "the fixture is degenerate - the two sides are byte-equal"
    assert row["ok_within_tolerance"] and shadow_day.settled(row)
    # keyed "" and not "service_date=...": the compare is rooted ON the partition, which is
    # the MUST this whole ticket carries - a table-rooted one lists every other partition as
    # missing and can never be `ok`.
    assert list(row["columns"][""]) == ["dist_m_sum"]

    # ...and the same machinery must REFUSE a difference that means something
    a, b = two_builds(tmp_path / "far", lambda v: v * 1.01)
    row = shadow_day.compare(str(a), b)
    assert not shadow_day.settled(row), "a 1% difference passed a 1e-9 bound"


def test_a_non_float_column_is_never_within_tolerance(tmp_path):
    """The bound is about floating-point addition order and nothing else. A string, an
    integer or a changed row count is a disagreement about the data, and no amount of
    smallness makes it one of these."""
    shadow_day = driver()
    a, b = two_builds(tmp_path, lambda v: v)
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    table = pq.read_table(b / "part-00000.parquet").to_pydict()
    table["route_id"] = ["Q59"] + table["route_id"][1:]          # one changed label
    pq.write_table(pa.table(table), b / "part-00000.parquet")
    row = shadow_day.compare(str(a), b)
    assert not shadow_day.settled(row)
    assert row["columns"][""]["route_id"]["float"] is False
