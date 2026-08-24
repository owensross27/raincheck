"""Run ids a human can read a month of: `daily-YYYY-MM-DD`.

Orchestration ticket 05, user story 8. Airflow's own scheduled run id is
`scheduled__<run_after ISO timestamp>__<random>`, which is exact, unique and unreadable -
and the nightly is one run per calendar day, so the calendar day IS the identity.

A run id is the timetable's to make (`Timetable.generate_run_id`), so this is the smallest
thing that can produce one: `CronTriggerTimetable` with that one method overridden. Only
SCHEDULED runs are renamed. A manual trigger keeps Airflow's id on purpose - two manual
runs on one day would otherwise collide on a unique constraint, and "daily-2026-08-24" has
to mean the 06:00 run.

WHY THIS IS A PLUGIN AND NOT A CLASS IN dags/. A custom timetable is stored in the
serialized DAG by qualified name, and deserialization looks that name up in the PLUGIN
registry - an unregistered one raises TimetableNotRegistered. That failure is not local to
this DAG: `airflow dags list` deserializes every serialized DAG in the metadata database,
so one row it cannot decode breaks the listing for all of them (this project has already
lost a session to that, with 94 orphaned example_dags rows). So the price of a readable run
id is that this file must keep existing under this name for as long as any serialized run
of the nightly does. If it is ever removed, delete the DAG's rows first:
`airflow dags delete -y raincheck_daily`.
"""
from __future__ import annotations

from airflow.plugins_manager import AirflowPlugin
from airflow.timetables.trigger import CronTriggerTimetable


class DailyRunIdTimetable(CronTriggerTimetable):
    """A cron timetable that names its scheduled runs after the local calendar day."""

    def generate_run_id(self, *, run_type, run_after, data_interval=None, **extra) -> str:
        if str(run_type) != "scheduled":
            return super().generate_run_id(run_type=run_type, run_after=run_after,
                                           data_interval=data_interval, **extra)
        return f"daily-{run_after.astimezone(self._timezone).date().isoformat()}"


class RaincheckTimetablePlugin(AirflowPlugin):
    """Registration is what makes the serialized DAG decodable; see the module docstring."""

    name = "raincheck_timetable"
    timetables = [DailyRunIdTimetable]
