"""The nightly, as one DAG (orchestration ticket 05).

`make daily` has run this pipeline every morning at 06:00 from a LaunchAgent: eight stages
in a pinned order, every stage running even when an earlier one failed, and an exit line
naming the ones that did. This is the same contract with a scheduler that survives a
laptop lid - and it is deliberately not a second copy of it. The order, which stage is
soft, which retries and which fans out are READ from `raincheck.daily.STAGES` (ticket 01);
the pod each stage runs in is READ from cloud 03's placement table; nothing here names a
stage, an edge, a capacity number or an image.

WHAT THIS DAG DECIDES AND WHAT IT REFUSES TO.

  It is STATE-DRIVEN, never date-driven. `gaps()` reads the data root and decides which
  Service dates to build, inside the `events` task, at task time. `logical_date` chooses
  nothing: the driver's rule about a Service date still out on the road (`closed_through`)
  is the only definition, and a run id is a label, not an input.

  CATCH-UP IS OFF, and that is not a convenience. Every stage is already a catch-up over a
  bounded window - the gap scan sweeps 14 days, gapfill sweeps to yesterday, precip
  rebuilds the current MRMS month. One run per missed interval would re-run the same
  bounded windows N times over and recover nothing the next single run would not.

  EVERY EDGE IS `all_done`. A red gapcheck must not cost the day's build; that has been
  true of the driver since ticket 15 and it survives the move as a trigger rule rather
  than as a note in a docstring.

  A GATE DOES NOT RETRY. Re-reading the same data cannot change a verdict, so a retrying
  gate turns a stable red into a flapping one. Transport stages - the ones that can fail on
  a blip and are idempotent - retry with exponential backoff.

WHAT THE FAN-OUT ADDED (ticket 06). The stages whose declared axis this runtime maps
become ONE POD PER ITEM: the fill and its verifier per feed kind, the build per Service
date. Nothing here names them - `stage["fanout"]` is in the declaration and MAPPED below
says which axes this runtime buys pods for.

  HOW MANY PODS IS A QUESTION ONLY A POD CAN ANSWER. The Service dates come from a scan of
  the data root, which no scheduler has, and Airflow can expand a task only over an XCom -
  so each mapped axis gets ONE plan task in front of it, running the same read the mapped
  stage used to do inside itself, in that stage's own measured shape.

  AN EXPANSION TO ZERO IS A SKIP, and a green one. A morning with no gaps is not an alert
  (user story 13); `all_done` carries the rest of the graph past it either way. The plan
  writing `[]` and the plan writing NOTHING are deliberately different outcomes - an empty
  list is a skip, an absent one is upstream_failed - so a scan that broke can never read as
  a quiet morning (airflow 3.2.2 models/taskmap.py; cncf-kubernetes 10.17.1 turns an empty
  result file into no XCom at all).

  THE REDUCE STAYS ONE POD. `gold` rolls the months the built days touched, and one Spark
  session rolling N months beats N sessions rolling one. It reads the SAME plan its days
  were expanded from and lets the disk say which of them landed - a finished task's record
  carries a map index and no Service date, so a state alone cannot name a month.
  A GATE HAS THREE OUTCOMES (ticket 07). A task state carries no rc, so a gate that exits
  `daily.INCONCLUSIVE_RC` - it COULD NOT CHECK - would otherwise be indistinguishable from
  one that found a real gap. `skip_rc()` gives exactly the gates that run their module the
  `skip_on_exit_code` that lands that rc in `skipped`, a terminal state that is neither
  success nor failure, and `report` carries the same mapping because its own exit line is
  the run's verdict. Nothing here renders inconclusive as ok and nothing renders it as
  failed; the persisted rows under `<root>/checks/` remain the record either way.

  ONE CEILING, stated rather than discovered: a DagRun has no third state. A run whose
  only red is an inconclusive gate leaves every task terminal and nothing failed, so the
  RUN reads `success` while the report task reads `skipped` and its log names the stage.
  The distinction lives on the TASK and in the rows, which is as far as Airflow goes.

WHAT IS DELIBERATELY NOT HERE. `coldgaps` (the remote census over unrecoverable Mac-era
subway positions: it would page forever about hours nobody can recover) and `make eras`
(a check whose place in the nightly is ticket 09's call, which is why ticket 01 left it out
of the declaration).
"""
from __future__ import annotations

import datetime

import pendulum
from airflow.sdk import DAG

from raincheck_stage import (XCOM, command, constant, module, shape_of, skip_rc,
                             stage_task, stages)
from raincheck_timetable import DailyRunIdTimetable

# A pendulum timezone, not a `zoneinfo.ZoneInfo`: the DAG imports and even runs with one,
# and then SERIALIZATION refuses it - so the failure lands in the dag-processor at 03:00
# rather than here. `tests/test_dag_nightly.py` round-trips the DAG for exactly that reason.
NY = "America/New_York"
AT = "0 6 * * *"          # 06:00 local, the LaunchAgent's slot, tracking DST the way it did
# One retry class per declared stage. Transport work is idempotent and fails on blips, so
# it backs off; a gate is a verdict, and a verdict re-read is the same verdict.
RETRIES = {"transport": {"retries": 3,
                         "retry_delay": datetime.timedelta(minutes=2),
                         "retry_exponential_backoff": True,
                         "max_retry_delay": datetime.timedelta(minutes=20)},
           "gate": {"retries": 0}}
# The axes this runtime buys pods for. `month` is deliberately not one: precip rebuilds one
# or two MRMS months in a single Spark session, and a second pod would buy a second node and
# a second JVM to save nothing - a task is TWO burst pods and the node purchase (measured:
# 95 s for the worker's, 74 s more for the stage's) is what a short stage's clock is made of.
MAPPED = ("kind", "service_date")

with DAG(
    dag_id="raincheck_daily",
    description="the nightly catch-up, one pod per declared stage (orch 05)",
    schedule=DailyRunIdTimetable(AT, timezone=NY),
    start_date=pendulum.datetime(2026, 1, 1, tz=NY),
    catchup=False,
    max_active_runs=1,          # two runs could build one Service date at once
    tags=["raincheck", "nightly"],
):
    chain, plans = [], {}
    for declared in stages():
        axis = declared["fanout"] if declared["fanout"] in MAPPED else None
        if axis and axis not in plans:
            # The items, once per axis, from the first stage that maps on it and in that
            # stage's own shape - it is the read that stage did inside itself before it was
            # mapped. A transport retry class: a listing blip must not cost the night.
            plans[axis] = stage_task(f"plan_{axis}", shape_of(declared["name"]),
                                     module("daily", "plan", axis, XCOM),
                                     trigger_rule="all_done", do_xcom_push=True,
                                     **RETRIES["transport"])
            chain.append(plans[axis])
        cmds = command(declared)
        if declared["reduces"]:
            # the reduce takes the whole list its pods were expanded from, from the same
            # plan; which of those days landed is the disk's answer, not this graph's
            cmds = cmds + ["{{ ti.xcom_pull(task_ids='plan_" + declared["reduces"] + "') | tojson }}"]
        # skip_rc (ticket 07): a GATE's INCONCLUSIVE_RC lands the task in `skipped`, mapped
        # or not - a mapped gate's N pods each carry the same rendering.
        chain.append(stage_task(declared["name"], shape_of(declared["name"]), cmds,
                                items=plans[axis].output if axis else None,
                                trigger_rule="all_done", skip_on_exit_code=skip_rc(declared),
                                **RETRIES[declared["retry"]]))

    # The driver's own ending, from Airflow's record of the run. It has to be a POD like
    # every other task - a callable here would run on the scheduler, on the floor - and a
    # pod cannot see the run it belongs to, so the finished tasks' states and durations are
    # rendered INTO its argument. `all_done` and no retries: it reports, it does not work.
    #
    # It carries the skip mapping for the same reason a gate does (ticket 07): report()
    # exits with daily.verdict(), which is INCONCLUSIVE_RC on a run that could only not
    # check. Without it the run's own summary - the one task whose state IS the nightly's
    # outcome - would render that as FAILED, which is the exact conflation this graph
    # spent three tasks avoiding one level down.
    chain.append(stage_task(
        "report", "raincheck-stage",
        module("daily", "report", "{{ ti.get_task_breadcrumbs(ti.dag_id, ti.run_id) | tojson }}"),
        trigger_rule="all_done", retries=0,
        skip_on_exit_code=constant("INCONCLUSIVE_RC")))

    for upstream, downstream in zip(chain, chain[1:]):
        upstream >> downstream
