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

  A GATE HAS THREE OUTCOMES (ticket 07). A task state carries no rc, so a gate that exits
  `daily.INCONCLUSIVE_RC` - it COULD NOT CHECK - would otherwise be indistinguishable from
  one that found a real gap. `skip_rc()` gives exactly the gates that run their module the
  `skip_on_exit_code` that lands that rc in `skipped`, a terminal state that is neither
  success nor failure, and `report` carries the same mapping because its own exit line is
  the run's verdict. Nothing here renders inconclusive as ok and nothing renders it as
  failed; the persisted rows under `<root>/checks/` remain the record either way.

WHAT IS DELIBERATELY NOT HERE. `coldgaps` (the remote census over unrecoverable Mac-era
subway positions: it would page forever about hours nobody can recover) and `make eras`
(a check whose place in the nightly is ticket 09's call, which is why ticket 01 left it out
of the declaration). `gold` is not a task either: it is the reduce INSIDE `daily.build`
over the months the built days touched, and it only needs splitting out when `events`
becomes one pod per Service date - which is ticket 06's fan-out, not this graph.
"""
from __future__ import annotations

import datetime

import pendulum
from airflow.sdk import DAG

from raincheck_stage import command, constant, module, shape_of, skip_rc, stage_task, stages
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

with DAG(
    dag_id="raincheck_daily",
    description="the nightly catch-up, one pod per declared stage (orch 05)",
    schedule=DailyRunIdTimetable(AT, timezone=NY),
    start_date=pendulum.datetime(2026, 1, 1, tz=NY),
    catchup=False,
    max_active_runs=1,          # two runs could build one Service date at once
    tags=["raincheck", "nightly"],
):
    previous = None
    for declared in stages():
        task = stage_task(declared["name"], shape_of(declared["name"]), command(declared),
                          trigger_rule="all_done", skip_on_exit_code=skip_rc(declared),
                          **RETRIES[declared["retry"]])
        if previous is not None:
            previous >> task
        previous = task

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
    previous >> stage_task(
        "report", "raincheck-stage",
        module("daily", "report", "{{ ti.get_task_breadcrumbs(ti.dag_id, ti.run_id) | tojson }}"),
        trigger_rule="all_done", retries=0,
        skip_on_exit_code=constant("INCONCLUSIVE_RC"))
