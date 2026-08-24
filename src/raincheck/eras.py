"""The schema-era column-presence check (orchestration ticket 03), on the ticket-02 row
vocabulary: does each VERIFIED Bronze bus reader still surface the era columns?

Live-era bus Bronze has three column eras on disk (CONTEXT.md, permanent data fact): era 1
vp lacks `schedule_relationship`, era 2 vp lacks `header_ts` and tu lacks `direction_id` /
`trip_delay_s` / `trip_ts` / `header_ts`, era 3 is canonical. The 2026-08-15..21 archiver
parts are never refilled, so the boundary is permanent.

**A reader that forgets to union fails SILENTLY** (measured 2026-08-23, re-measured here
against DuckDB 1.5.5): Spark without `mergeSchema` takes one file's schema and the missing
columns simply are not there, with the row count still correct; DuckDB without
`union_by_name` raises only when a WIDE part sorts first - when a narrow part sorts first
it drops the columns the same way, again with the row count correct. So a row-count
expectation cannot see this, and the check has to assert the columns are PRESENT.

The check reads a date dir whose parts DISAGREE about their columns, because that is the
only place a union reader is distinguishable from a narrow one. A tree with no such day is
INCONCLUSIVE, never ok: on a uniform day both readers return every column and the run
proved nothing (the same false-OK class as gapverify with no filled/captured pair).

Reading columns never materialises a row: `duck.table(...).columns` is metadata off the
relation, so this check does not go near the lazy-RecordBatchReader deadlock that the
Arrow bridge has (KNOWN TRAPS / flood 05).

Run: python -m raincheck.eras   (rc 1 a reader lost a column / 2 inconclusive / 0)
"""
import sys
from pathlib import Path

import pyarrow.parquet as pq

from raincheck import checks, duck, events
from raincheck.paths import data_root

CHECK = "eras"
# The one home for the era columns per kind (CONTEXT.md's Bronze bus-part schema eras).
ERA_COLS = {"vp": ("schedule_relationship", "header_ts"),
            "tu": ("direction_id", "trip_delay_s", "trip_ts", "header_ts")}
CHECK_COLUMNS = checks.CORE + ("reader", "kind", "day", "era_cols", "missing")


def mixed_day(root: Path, kind: str) -> str | None:
    """The newest date dir under archive/<kind> whose parts do not all carry the same
    columns - the only day on which this check can tell the readers apart.

    Newest first and stop at the first hit: parquet footers are cheap but a full Bronze
    tree is thousands of files, and the era boundary is recent, so the scan is short in
    practice and bounded by the tree in the worst case."""
    for date_dir in sorted((root / "archive" / kind).glob("date=*"), reverse=True):
        shapes = {tuple(pq.read_schema(p).names) for p in sorted(date_dir.glob("hour=*/*.parquet"))}
        if len(shapes) > 1:
            return date_dir.name[5:]
    return None


def duck_columns(root: Path, kind: str, day: str, spark=None) -> list[str]:
    """duck.table - the union_by_name read every analysis and test oracle goes through."""
    return list(duck.table(duck.connect(), root / "archive" / kind / f"date={day}").columns)


def spark_columns(root: Path, kind: str, day: str, spark) -> list[str]:
    """The mergeSchema readers events.py builds Silver from. Both take a SERVICE day and so
    read date=D and date=D+1 - a superset of the mixed day, which only strengthens this."""
    read = events.bronze_vp if kind == "vp" else events.bronze_tu
    df = read(root, spark, day)
    return list(df.columns) if df is not None else []


# Looked up per call, never captured: a test that swaps duck.table for a non-union read
# must move this check's verdict, which is the proof that the check has teeth.
READERS = {"duck": duck_columns, "spark": spark_columns}


def session():
    """The Spark session for the mergeSchema readers, or None when this box has no JVM (the
    spark rows are then inconclusive - never ok, and never a data gap)."""
    from raincheck import spark as spark_mod

    return spark_mod.session() if spark_mod.java_home() else None


def check(root: Path, spark=None) -> list[checks.Row]:
    """One row per (reader, kind). Every reader named in CONTEXT.md's verified list gets a
    row every run, so a suite can expect on the shape rather than on what happened to run."""
    rows, built = [], False
    for kind, want in ERA_COLS.items():
        day = mixed_day(root, kind)
        for name, reader in READERS.items():
            if name == "spark" and spark is None and not built:
                spark, built = session(), True
            m = {"reader": name, "kind": kind, "day": day, "era_cols": ",".join(want),
                 "missing": None}
            if day is None:
                rows.append(checks.Row(CHECK, f"{name} {kind}", checks.INCONCLUSIVE,
                                       "no date dir mixes part schemas - a union reader is "
                                       "indistinguishable from a narrow one here", m))
                continue
            if name == "spark" and spark is None:
                rows.append(checks.Row(CHECK, f"{name} {kind}", checks.INCONCLUSIVE,
                                       "no JVM on this box - the mergeSchema readers were "
                                       "never opened", m))
                continue
            have = reader(root, kind, day, spark)
            missing = [c for c in want if c not in have]
            rows.append(checks.Row(
                CHECK, f"{name} {kind}", checks.FAIL if missing else checks.OK,
                f"  DROPPED {','.join(missing)} - reader is not unioning part schemas"
                if missing else "", m | {"missing": ",".join(missing)}))
    return rows


def line(r: checks.Row) -> str:
    m = r.measures
    mark = {checks.OK: "OK ", checks.FAIL: "BAD", checks.INCONCLUSIVE: "???"}[r.outcome]
    return (f"{mark} {m['reader']:6s} {m['kind']:3s} date={m['day']} "
            f"era_cols={m['era_cols']}{r.detail}")


def main() -> None:
    root = data_root()
    rows = check(root)
    for r in rows:
        print(line(r))
    checks.write(root, CHECK, rows, CHECK_COLUMNS)
    sys.exit(checks.rc(rows))


if __name__ == "__main__":
    main()
