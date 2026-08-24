"""Orchestration ticket 03: the remaining check producers on ticket 02's row vocabulary -
the cold mirror (raincheck.cold), the backfill census (scripts/backfill-verify.py) and the
NEW Bronze bus era-column presence check (raincheck.eras).

Offline throughout: the two remote checks run against a stub `aws` on RAINCHECK_AWS (the
ticket-19 convention), and the era check runs against Bronze trees planted here. All three
outcomes are covered per producer, because the outcome this effort exists for -
INCONCLUSIVE - is the one that never shows up by accident.
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raincheck import checks, cold, duck, eras, events

SCRIPTS = Path(__file__).parents[1] / "scripts"
COLD_ENV = {"RAINCHECK_COLD_BUCKET": "b", "RAINCHECK_COLD_ENDPOINT": "https://r2.example",
            "RAINCHECK_COLD_KEY_ID": "k", "RAINCHECK_COLD_SECRET": "s"}


def stub_aws(tmp_path: Path, body: str) -> Path:
    """A fake awscli on PATH. Ticket 19's convention: RAINCHECK_AWS names the binary, so a
    test never needs the real one and never reaches the network."""
    p = tmp_path / "bin" / "aws"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/bin/bash\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


def batch(root: Path, name: str) -> list[dict]:
    """The one persisted batch this run wrote, read back off disk."""
    (f,) = (root / "checks" / f"check={name}").glob("run=*.jsonl")
    return [json.loads(x) for x in f.read_text().splitlines()]


# --- the cold mirror -----------------------------------------------------------------


@pytest.fixture
def mirror_root(tmp_path, monkeypatch):
    for kind in ("vp", "tu"):
        (tmp_path / "archive" / kind / "date=2026-08-15" / "hour=00").mkdir(parents=True)
    for k, v in COLD_ENV.items():
        monkeypatch.setenv(k, v)
    return tmp_path


def test_a_clean_mirror_is_ok_per_kind(mirror_root, tmp_path, monkeypatch):
    monkeypatch.setenv("RAINCHECK_AWS", str(stub_aws(tmp_path, "exit 0\n")))
    rows = cold.mirror(mirror_root)
    assert [(r.subject, r.outcome) for r in rows] == [("tu", checks.OK), ("vp", checks.OK)]
    assert checks.rc(rows) == 0


def test_a_missing_object_fails_only_its_own_kind(mirror_root, tmp_path, monkeypatch):
    """The dryrun line's LOCAL side is printed relative to awscli's cwd (ticket 19's
    footgun), so the kind is read off /archive/<kind>/ and the verdict is cwd-independent."""
    monkeypatch.setenv("RAINCHECK_AWS", str(stub_aws(tmp_path, (
        'echo "(dryrun) upload: ../data/archive/vp/date=2026-08-15/hour=03/part-0.parquet '
        'to s3://b/archive/vp/date=2026-08-15/hour=03/part-0.parquet"\n'
        'echo "(dryrun) upload: ../data/archive/vp/date=2026-08-15/hour=04/part-0.parquet '
        'to s3://b/archive/vp/date=2026-08-15/hour=04/part-0.parquet"\nexit 0\n'))))
    rows = {r.subject: r for r in cold.mirror(mirror_root)}
    assert rows["vp"].outcome == checks.FAIL and rows["vp"].measures["differing"] == 2
    assert rows["tu"].outcome == checks.OK and rows["tu"].measures["differing"] == 0
    assert checks.rc(list(rows.values())) == 1


def test_a_failed_listing_is_inconclusive_and_never_a_gap(mirror_root, tmp_path, monkeypatch):
    """THE live bug this port fixes. The shell recipe captured stdout and never looked at
    aws's exit status, so a failed listing printed the OK sentence and exited 0."""
    monkeypatch.setenv("RAINCHECK_AWS", str(stub_aws(
        tmp_path, 'echo "Could not connect to the endpoint URL" >&2\nexit 255\n')))
    rows = cold.mirror(mirror_root)
    assert {r.outcome for r in rows} == {checks.INCONCLUSIVE}
    assert all(r.measures["differing"] is None for r in rows)  # nothing counted, not zero
    assert checks.rc(rows) == 2
    assert "NOT a data gap" in rows[0].detail


def test_unconfigured_cold_storage_is_inconclusive_without_running_aws(mirror_root, monkeypatch):
    monkeypatch.delenv("RAINCHECK_COLD_BUCKET")
    monkeypatch.setenv("RAINCHECK_AWS", "/nonexistent/aws")  # would raise if it ran
    rows = cold.mirror(mirror_root)
    assert {r.outcome for r in rows} == {checks.INCONCLUSIVE}
    assert "unconfigured" in rows[0].detail


def test_an_empty_archive_emits_a_row_rather_than_an_empty_batch(tmp_path, monkeypatch):
    """checks.rc([]) is 0: a producer with nothing to say must say INCONCLUSIVE, or a run
    that compared nothing renders as a clean mirror."""
    for k, v in COLD_ENV.items():
        monkeypatch.setenv(k, v)
    rows = cold.mirror(tmp_path)
    assert [(r.subject, r.outcome) for r in rows] == [("archive", checks.INCONCLUSIVE)]
    assert checks.rc(rows) == 2


def test_the_cli_prints_the_lines_writes_the_batch_and_exits_on_the_rule(
        mirror_root, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RAINCHECK_ARCHIVE_ROOT", str(mirror_root))
    monkeypatch.setenv("RAINCHECK_AWS", str(stub_aws(tmp_path, (
        'echo "(dryrun) upload: x/archive/tu/date=2026-08-15/hour=01/p.parquet to '
        's3://b/archive/tu/date=2026-08-15/hour=01/p.parquet"\nexit 0\n'))))
    with pytest.raises(SystemExit) as e:
        cold.main()
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert "GAP tu" in out and "OK  vp" in out
    assert "coldcheck: GAP - objects above are missing or size-mismatched remotely" in out
    got = batch(mirror_root, "coldcheck")
    assert [tuple(r) for r in got] == [cold.CHECK_COLUMNS] * 2  # column set asserted on write
    assert {r["subject"]: r["differing"] for r in got} == {"tu": 1, "vp": 0}


# --- the backfill census (its own era, its own DEAD list, its own 0/1/2) --------------


def r2_listing(day: str, feed: str, hours=range(24), size: int = 4096) -> str:
    """`aws s3 ls --recursive` output: one part + one zero-byte _gapfill marker per hour."""
    out = []
    for h in hours:
        p = f"archive/{feed}/date={day}/hour={h:02d}"
        out.append(f"2026-08-20 01:00:00 {size:>10} {p}/part-gapfill-{feed}.parquet")
        out.append(f"2026-08-20 01:00:00          0 {p}/_gapfill")
    return "\n".join(out)


def run_census(tmp_path, listing: str | None, *args: str) -> subprocess.CompletedProcess:
    body = "exit 254\n" if listing is None else 'cat "$STUB_LISTING"\n'
    stub = stub_aws(tmp_path, body)
    (tmp_path / "listing.txt").write_text(listing or "")
    env = {**os.environ, **COLD_ENV, "RAINCHECK_AWS": str(stub),
           "STUB_LISTING": str(tmp_path / "listing.txt"),
           "RAINCHECK_ARCHIVE_ROOT": str(tmp_path),
           "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    return subprocess.run([sys.executable, str(SCRIPTS / "backfill-verify.py"), *args],
                          capture_output=True, text=True, env=env)


def test_a_complete_range_exits_0_and_writes_one_row_per_feed(tmp_path):
    p = run_census(tmp_path, r2_listing("2026-03-01", "vp"),
                   "2026-03-01", "2026-03-01", "--feeds", "vp")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "OK  vp      24/24 hours" in p.stdout
    (row,) = batch(tmp_path, "backfill")
    assert tuple(row) == checks.CORE + ("feed", "lo", "hi", "hours_seen", "hours_want", "dead",
                                        "missing", "no_part", "no_marker", "zero_byte",
                                        "stale_dead")
    assert (row["outcome"], row["hours_seen"], row["hours_want"]) == ("ok", 24, 24)


def test_a_missing_hour_exits_1(tmp_path):
    p = run_census(tmp_path, r2_listing("2026-03-01", "vp", hours=range(23)),
                   "2026-03-01", "2026-03-01", "--feeds", "vp")
    assert p.returncode == 1
    (row,) = batch(tmp_path, "backfill")
    assert (row["outcome"], row["missing"], row["hours_seen"]) == ("fail", 1, 23)


def test_a_zero_byte_part_is_a_gap_but_an_empty_marker_is_not(tmp_path):
    p = run_census(tmp_path, r2_listing("2026-03-01", "vp", size=0),
                   "2026-03-01", "2026-03-01", "--feeds", "vp")
    assert p.returncode == 1
    (row,) = batch(tmp_path, "backfill")
    assert (row["zero_byte"], row["no_marker"], row["missing"]) == (24, 0, 0)


def test_a_failed_listing_exits_2_and_still_emits_that_feeds_row(tmp_path):
    p = run_census(tmp_path, None, "2026-03-01", "2026-03-01", "--feeds", "vp")
    assert p.returncode == 2
    assert "INCONCLUSIVE vp: remote listing failed" in p.stdout
    (row,) = batch(tmp_path, "backfill")
    assert row["outcome"] == "inconclusive" and row["hours_seen"] is None


def test_a_real_gap_beside_a_failed_listing_exits_1_and_both_feeds_get_a_row(tmp_path):
    """The aggregation rule, applied where the old early `return 2` could not reach it: a
    known hole outranks a not-run check. Aborting at the first failed listing also threw
    away every later feed's verdict, so both rows are here and vp's gap is not hidden."""
    stub = stub_aws(tmp_path, 'case "$*" in *"/archive/tu/"*) exit 254;; esac\n'
                              'cat "$STUB_LISTING"\n')
    (tmp_path / "listing.txt").write_text(r2_listing("2026-03-01", "vp", hours=range(23)))
    env = {**os.environ, **COLD_ENV, "RAINCHECK_AWS": str(stub),
           "STUB_LISTING": str(tmp_path / "listing.txt"),
           "RAINCHECK_ARCHIVE_ROOT": str(tmp_path),
           "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    p = subprocess.run([sys.executable, str(SCRIPTS / "backfill-verify.py"),
                        "2026-03-01", "2026-03-01", "--feeds", "vp,tu"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 1, p.stdout + p.stderr
    assert {r["subject"]: r["outcome"] for r in batch(tmp_path, "backfill")} == {
        "vp": "fail", "tu": "inconclusive"}


def test_the_census_keeps_its_own_dead_list_and_it_is_not_gapfills(tmp_path):
    """Ticket 20's standing rule: the two eras' tools stay apart. The backfill era's dead
    hours live in the script, gapfill.DEAD covers the live era, and neither reads the other."""
    import importlib.util

    from raincheck import gapfill

    spec = importlib.util.spec_from_file_location("bv", SCRIPTS / "backfill-verify.py")
    bv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bv)
    assert ("vp", "2026-04-27") in bv.DEAD and ("vp", "2026-04-27") not in gapfill.DEAD
    assert not set(bv.DEAD) & set(gapfill.DEAD)
    # a dead hour is absent from the listing and must NOT count as a gap
    listing = r2_listing("2026-04-27", "vp", hours=[h for h in range(24) if h != 4])
    p = run_census(tmp_path, listing, "2026-04-27", "2026-04-27", "--feeds", "vp")
    assert p.returncode == 0 and "(+1 dead at source)" in p.stdout


def test_a_stale_dead_entry_is_a_defect(tmp_path):
    """Same verdict gapcheck reached in ticket 02: an allowlisted hour that turns up means
    the allowlist is protecting nothing, and a wrong allowlist hides the next real gap."""
    p = run_census(tmp_path, r2_listing("2026-04-27", "vp"),
                   "2026-04-27", "2026-04-27", "--feeds", "vp")
    assert p.returncode == 1
    assert "STALE DEAD ENTRY" in p.stdout
    (row,) = batch(tmp_path, "backfill")
    assert (row["outcome"], row["stale_dead"]) == ("fail", 1)


# --- the era-column presence check ---------------------------------------------------

NARROW = {"vp": ("vehicle_id", "trip_id"), "tu": ("vehicle_id", "trip_id", "start_date")}


@pytest.fixture
def no_jvm(monkeypatch):
    """The duck rows are the subject of most of these; with no session the spark rows are
    INCONCLUSIVE, which is itself the contract (a reader that was never opened is not ok)."""
    monkeypatch.setattr(eras, "session", lambda: None)


def plant(root: Path, kind: str, day: str, *, mixed: bool = True) -> int:
    """A Bronze date dir whose hour=00 part predates the era columns and whose hour=01 part
    has them - the real 2026-08-15..23 shape, and the only shape on which a union reader is
    distinguishable from one that silently takes a single part's schema. Returns row count."""
    wide = NARROW[kind] + eras.ERA_COLS[kind]
    for hour, cols in (("00", NARROW[kind]), ("01", wide if mixed else NARROW[kind])):
        t = pa.table({c: pa.array(["x"] if c in NARROW[kind] else [1], type=(
            pa.string() if c in NARROW[kind] else pa.int64())) for c in cols})
        out = root / "archive" / kind / f"date={day}" / f"hour={hour}" / "part-0.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(t, out)
    return 2


def duck_rows(root: Path, kind: str, day: str, union: bool) -> int:
    con = duck.connect()
    return len(con.execute(
        "SELECT * FROM read_parquet(?, hive_partitioning = true, hive_types_autocast = false, "
        "union_by_name = ?)", [f"{root}/archive/{kind}/date={day}/**/*.parquet", union]).fetchall())


def narrow_duck(con, root):
    """duck.table with its union dropped - the misconfiguration this check exists to catch."""
    return con.sql("SELECT * FROM read_parquet(?, hive_partitioning = true, "
                   "hive_types_autocast = false, union_by_name = false)",
                   params=[f"{root}/**/*.parquet"])


def test_the_union_reader_holds_the_era_columns(tmp_path, no_jvm):
    for kind in ("vp", "tu"):
        plant(tmp_path, kind, "2026-08-15")
    rows = {r.subject: r for r in eras.check(tmp_path)}
    for kind in ("vp", "tu"):
        assert rows[f"duck {kind}"].outcome == checks.OK
        assert rows[f"duck {kind}"].measures["missing"] == ""
        assert rows[f"duck {kind}"].measures["day"] == "2026-08-15"


def test_a_reader_without_union_fails_while_the_row_count_does_not_move(
        tmp_path, monkeypatch, no_jvm):
    """The proof the ticket asks for. Dropping union_by_name with a NARROW part sorting
    first does not raise: the era columns are simply gone and the row count is unchanged
    (measured, DuckDB 1.5.5), so a row-count expectation passes on both reads and sees
    nothing. Column PRESENCE is the only assertion that catches it."""
    n = plant(tmp_path, "vp", "2026-08-15")
    assert duck_rows(tmp_path, "vp", "2026-08-15", True) == n
    assert duck_rows(tmp_path, "vp", "2026-08-15", False) == n  # <- blind to the drop

    monkeypatch.setattr(duck, "table", narrow_duck)
    row = {r.subject: r for r in eras.check(tmp_path)}["duck vp"]
    assert row.outcome == checks.FAIL
    assert row.measures["missing"] == "schedule_relationship,header_ts"
    assert "DROPPED" in row.detail


def test_a_tree_with_no_mixed_era_day_is_inconclusive_never_ok(tmp_path, no_jvm):
    """A uniform day cannot tell the readers apart: both return every column. Reporting
    that as ok is the false-OK class this whole effort exists to remove."""
    plant(tmp_path, "vp", "2026-08-15", mixed=False)
    rows = {r.subject: r for r in eras.check(tmp_path)}
    assert rows["duck vp"].outcome == checks.INCONCLUSIVE
    assert rows["duck vp"].measures["day"] is None
    assert checks.rc(list(rows.values())) == 2


def test_no_bronze_at_all_is_inconclusive_and_still_emits_every_row(tmp_path, no_jvm):
    rows = eras.check(tmp_path)
    assert {r.outcome for r in rows} == {checks.INCONCLUSIVE}
    assert [r.subject for r in rows] == ["duck vp", "spark vp", "duck tu", "spark tu"]


def test_the_newest_mixed_day_is_the_one_read(tmp_path):
    plant(tmp_path, "vp", "2026-08-15")
    plant(tmp_path, "vp", "2026-08-20")
    plant(tmp_path, "vp", "2026-08-25", mixed=False)  # era 3 throughout: nothing to learn
    assert eras.mixed_day(tmp_path, "vp") == "2026-08-20"


def test_the_cli_writes_the_batch_with_the_declared_columns(
        tmp_path, monkeypatch, capsys, no_jvm):
    plant(tmp_path, "vp", "2026-08-15")
    plant(tmp_path, "tu", "2026-08-15")
    monkeypatch.setenv("RAINCHECK_ARCHIVE_ROOT", str(tmp_path))
    with pytest.raises(SystemExit) as e:
        eras.main()
    assert e.value.code == 2  # inconclusive spark rows, no failure
    assert "OK  duck   vp  date=2026-08-15" in capsys.readouterr().out
    got = batch(tmp_path, "eras")
    assert [tuple(r) for r in got] == [eras.CHECK_COLUMNS] * 4


def test_the_spark_readers_hold_the_era_columns_and_lose_them_silently_without_mergeschema(
        tmp_path, spark):
    """The Spark half of the same blindness, on the readers events.py builds Silver from.
    Without mergeSchema Spark takes one file's schema and never raises - the columns are
    gone and the count is right, exactly as CONTEXT.md measured."""
    for kind in ("vp", "tu"):
        plant(tmp_path, kind, "2026-08-15")
    rows = {r.subject: r for r in eras.check(tmp_path, spark=spark)}
    assert rows["spark vp"].outcome == checks.OK and rows["spark tu"].outcome == checks.OK

    day = tmp_path / "archive" / "vp" / "date=2026-08-15"
    merged = events.bronze_vp(tmp_path, spark, "2026-08-15")
    narrow = spark.read.option("basePath", str(day.parent)).parquet(str(day))
    assert narrow.count() == merged.count()  # <- a row-count expectation sees nothing
    assert set(eras.ERA_COLS["vp"]) - set(narrow.columns)  # and the columns are gone
