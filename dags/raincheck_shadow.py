"""The nightly's SHADOW (orchestration ticket 11).

The cutover question is not "does the cluster run?" - orch 04 answered that - but "does
the cluster BUILD THE SAME DATA the Mac builds?". This DAG is how that is asked: the same
graph shape the nightly will run, one pod per Service date and one reduce behind them,
pointed at a SHADOW DATA ROOT. The Mac builds the same days beside it and
`raincheck.parity` compares the two, per partition. Nothing here is a second definition of
anything: the stages, their order, their pods and their commands are all read from the same
declaration and the same placement table the nightly reads.

WHY A SHADOW ROOT AND NOT THE LIVE TREE. Two writers on one Bronze is a data event, not an
experiment. The whole safety story of this DAG is one environment variable - see
raincheck_stage.at_root() - and it is asserted rather than hoped for.

WHAT A SHADOW DAY IS. ONE MAPPED INDEX, not a run: the `events` pod for one Service date
plus the single `gold` reduce standing behind the expansion. The Mac side is the same two
commands (`python -m raincheck.daily events D`, then the reduce over the day list), which
is what makes the two sides comparable at all - since ticket 07 a declared stage with an
argv runs as its own process on `make daily` too, so the Mac runtime and this one issue the
identical command.

WHAT IS DELIBERATELY NOT RUN, AND WHY THE RUN SAYS SO. The first task ECHOES the declared
stages this graph leaves out, derived from the declaration so it can never go stale. Three
of them MUTATE state the Mac shares - the fill writes Bronze, the push writes the cold
mirror, the prune deletes from live/ - and shadowing cannot prove any of them, because a
shadow that ran them would BE the second writer. The rest are checks whose subject is a
tree this root only partly holds, so their verdicts would be about the shadow and not
about the data. How the three get proven after cutover is written down in
.scratch/orchestration/issues/11-shadow-and-parity.md.

THERE IS NO `report` TASK, and that is the one place this graph is deliberately smaller
than the nightly. The nightly's ending is a rendering of ONE runtime's own record; a
shadow's verdict is a statement about TWO runtimes, and no task inside one of them can see
the other. scripts/shadow-day.py is the ending: it runs both sides and records the pair.

RETRIES ARE OFF, everywhere. A shadow run is an experiment whose failures are its findings,
and a transport stage that quietly succeeded on its third attempt is a fact the cutover
wants to see, not one it wants smoothed over. The nightly keeps its own retry classes.

Manual trigger only - a schedule here would be a second nightly.
"""
from __future__ import annotations

import datetime

from airflow.sdk import DAG

from raincheck_stage import (XCOM, command, module, shape_of, skip_rc, stage_task,
                             stages)

# THE SHADOW DATA ROOT, named here and nowhere else. A PREFIX of the archive bucket and
# never the bucket root: `s3a://raincheck-bronze` itself is the cold mirror of Bronze, and
# its silver/ holds the reference tables every build reads. scripts/shadow-day.py stages
# this root's inputs and compares its outputs; the two spellings are pinned together by a
# test.
SHADOW = "s3a://raincheck-bronze/shadow"
# The declared stages a shadow day is made of: the mapped build, and the reduce behind it.
BUILDS = ("events", "gold")
AXIS = "service_date"
# The declared stages that write somewhere the Mac also writes. Not in the declaration -
# it is this ticket's judgement, and it is the reason BUILDS is a short list rather than
# the whole graph. A test asserts these three are never in BUILDS.
MUTATES = ("gapfill", "coldpush", "prune")

_left_out = [s["name"] for s in stages() if s["name"] not in BUILDS]
NOTICE = (
    "shadow: this run builds " + ", ".join(BUILDS) + " onto " + SHADOW + " and nothing else."
    " DELIBERATELY NOT RUN: " + ", ".join(_left_out) + "."
    " Of those, " + ", ".join(n for n in MUTATES if n in _left_out) + " MUTATE state the Mac"
    " also writes - the fill writes Bronze, the push writes the cold mirror, the prune"
    " deletes from live/ - so a shadow that ran them would be the second writer it exists to"
    " avoid, and shadowing therefore proves nothing about them. The rest are checks whose"
    " subject is a tree this root only partly holds, so their verdicts would be about the"
    " shadow and not about the data. How the three get proven after cutover:"
    " .scratch/orchestration/issues/11-shadow-and-parity.md."
)

with DAG(
    dag_id="raincheck_shadow",
    description="the nightly's build, on a shadow data root, for parity (orch 11)",
    schedule=None,
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,          # two runs could build one Service date at once
    tags=["raincheck", "shadow"],
):
    # The run says what it is not doing, in its own log, before it does anything.
    chain = [stage_task("disabled", "raincheck-stage", ["echo", NOTICE],
                        trigger_rule="all_done", retries=0, root=SHADOW)]
    plan = None
    for declared in stages():
        if declared["name"] not in BUILDS:
            continue
        if declared["fanout"] == AXIS and plan is None:
            # The items, from a pod, in the shape of the stage that maps on them: the scan
            # is a read of the data root, which no scheduler has. On THIS root the scan is
            # also the day selector - a shadow day exists because its Bronze was staged
            # here and its Silver was not, so nothing has to tell this graph which days.
            plan = stage_task(f"plan_{AXIS}", shape_of(declared["name"]),
                              module("daily", "plan", AXIS, XCOM),
                              trigger_rule="all_done", do_xcom_push=True, retries=0,
                              root=SHADOW)
            chain.append(plan)
        cmds = command(declared)
        if declared["reduces"]:
            cmds = cmds + ["{{ ti.xcom_pull(task_ids='plan_" + declared["reduces"] + "') | tojson }}"]
        chain.append(stage_task(declared["name"], shape_of(declared["name"]), cmds,
                                items=plan.output if declared["fanout"] == AXIS else None,
                                trigger_rule="all_done", retries=0,
                                skip_on_exit_code=skip_rc(declared), root=SHADOW))

    for upstream, downstream in zip(chain, chain[1:]):
        upstream >> downstream
