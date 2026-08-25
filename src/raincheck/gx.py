"""The Great Expectations foundation and the live-capture completeness suite
(orchestration ticket 08).

A suite here expects on CHECK-RESULT ROWS - the batches `raincheck.checks` producers
persist under `<root>/checks/check=<name>/run=<stamp>.jsonl` - and never on Bronze. Two
reasons, and the second one is now literal rather than hypothetical:

  - The suite must not re-derive a check a module already implements, so every threshold
    keeps exactly one home. `gapfill.check()` decides what a gap is; this suite reads the
    verdict it wrote. A suite that recomputed `fillable` would be a second home for the
    rule and would start disagreeing with the first one silently.
  - GX renders UNEXPECTED VALUES into Data Docs, and Data Docs are PUBLISHED: cloud 09's
    `docs` family is `<root>/gx/data_docs` -> `docs/**` on the public host. A suite
    pointed at Bronze would put MTA feed rows on a public bucket. Rows carry counts,
    dates, kinds, hour labels and ratios only (checks.py), which is what makes the report
    publishable at all.

THREE OUTCOMES, AND THE THIRD ONE SURVIVES. A check that could not run tells you nothing
about the data. It is not a pass and it is not a gap, and its measures are NULL rather
than 0 (`differing`, `hours_seen`). So the adapter HOLDS INCONCLUSIVE ROWS OUT of the
batch it hands GX: an expectation can only say expected/unexpected, so any row inside the
frame has already been flattened into two. The rows GX never sees are reported as their
own bucket on `Result`, they set the outcome when nothing failed, and no configuration of
this module can render them as either a pass or a failure. That is the ticket.

The DAG side of the same distinction is orchestration 07: `<stage> retry="gate"` with an
`argv` makes `raincheck_stage.skip_rc()` map this module's rc 2 onto a `skipped` task -
the only terminal state Airflow has that is neither success nor failure. The persisted
row stays the record either way; a task state is a rendering of it.

SCOPE: THE LIVE-CAPTURE ERA ONLY. `gapfill.START` is when capture began, and the
backfilled range (2026-03-01..08-14) is a different era with a different check
(`scripts/backfill-verify.py`, check `backfill`) and a different DEAD list. A suite whose
batch reaches back before START is REFUSED here rather than reported: it is pointed at the
wrong data, which is a defect and not a finding.

GX IS AN OPTIONAL EXTRA (`pip install -e '.[gx]'`, pinned to MAJOR VERSION 1 - the 0.x and
1.x context/checkpoint APIs differ substantially and this module is written against 1.x
only). No pipeline module imports it, this one imports it lazily, and a missing library is
INCONCLUSIVE - the suite could not run, which is exactly the third outcome.

NOT EVERY SUITE IS A NIGHTLY SUITE (orchestration 10). `SUITES` is the nightly declaration
and `gxcheck` runs exactly that; `NON_NIGHTLY` holds the two families whose data CANNOT
CHANGE - the closed backfill era and the reference registry - and those are named on the
command line by their own `make` targets, after the event that could have moved them. A
named run renders into its OWN Data Docs directory, because `build_data_docs()` rebuilds the
whole site and the nightly's tree is what gets published.

Run: make gxcheck     (python -m raincheck.gx)                 the nightly's four
     make gxbackfill  (python -m raincheck.gx backfill-census) after a backfill chunk lands
     make gxref       (python -m raincheck.gx ref-canaries)    after make refcanary
Exit: 1 any suite failed, 2 any suite could not check, else 0 - checks.rc's own rule.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib.util import find_spec
from pathlib import Path
from typing import Callable, NamedTuple

from raincheck import checks, cold, eras, gapfill, publish, ref_canary
from raincheck.paths import data_root

# The live-capture era's first day. Read from gapfill rather than retyped: the backfill
# range ends where this begins, and a copy here would be a second definition of the era.
ERA_START = gapfill.START.isoformat()
DATASOURCE = "checks"     # the GX data source name; the batch is always a check batch
SITE = "raincheck"        # the one Data Docs site
DOCS = ("gx", "data_docs")  # <root>/gx/data_docs - cloud 09's `docs` family src, pinned
                            # against publish.FAMILIES by a test rather than by comment
# COMPLETE + the subject column is what lets a failing expectation NAME the check subjects
# it rejected. `subject` is in checks.CORE, so every batch has one.
RESULT_FORMAT = {"result_format": "COMPLETE", "unexpected_index_column_names": ["subject"]}
STAMP = "%Y%m%dT%H%M%SZ"   # checks.write's own: fixed width UTC, so lexicographic IS chronological
# The window ONE run's batches fall in. A stage that FANS OUT writes its batch once per
# POD - `gapverify` is five pods, one per feed kind, since orch 06 - and a stage invoked
# twice writes two (daily.coldcheck() checks, re-pushes, re-checks). Both are one run, so
# "the batch" is a SET and reading only the newest stamp would judge one kind and silently
# drop four. The set has to be BOUNDED, though: a batch from a run that is over would let a
# pod which did not run tonight answer for tonight, which is the false OK this whole
# vocabulary exists to kill.
#
# TWO BOUNDS, and twelve hours is the middle of them. It must be LONGER than the nightly
# itself, because the first producer's batch (`gapverify`, third task) has to still be in
# the window when `gxcheck` reads it last - a stage's exponential backoff and the node
# purchase in front of every pod (measured 95 s + 74 s, orch 04) both push that out, and
# the fan-out's own baseline is 1928 s of Spark for a seven-day catch-up. And it must be
# SHORTER than the gap between two runs: the schedule is 06:00 daily and max_active_runs
# is 1, so one check's consecutive batches are a day apart. Erring long only ever costs a
# false INCONCLUSIVE (the suite says it could not check a run that did); erring short is
# what would let last night answer for tonight, which is the false OK.
RUN_WINDOW = timedelta(hours=12)


class Suite(NamedTuple):
    """One named suite over one producer's batch.

    `columns` is that producer's OWN declared constant - `gapfill.CHECK_COLUMNS[...]`,
    `cold.CHECK_COLUMNS`, `eras.CHECK_COLUMNS`, backfill-verify's `CHECK_COLUMNS` - never
    a literal list retyped here. The batch is asserted against it on read, so a producer
    that changes shape is a loud refusal rather than a suite quietly expecting on columns
    that moved. `expectations` is a CALLABLE because building one imports the optional
    extra, and importing this module must not.

    `era` names the column carrying an ISO day, if the batch has one; its values are
    refused before ERA_START. Leave it None for a batch with no day (the cold mirror's is
    per archive prefix), and never set it on the backfill census - that check IS the other
    era.

    `whole` is the suite's claim about the batch AS A WHOLE, and it exists because an
    EXPECTATION CANNOT MAKE ONE: inconclusive rows are held out of the frame, so anything
    that counts rows sees a short batch and fails - rendering "could not check" as a
    failure (orch 08 measured exactly that). It is handed every row, before the split, plus
    the data root, and returns `(failed, inconclusive, detail)` for merged() to fold into
    the verdict. "One row per archive prefix", "five kinds this run" and "four readers
    every run" are all this, and none of them is an expectation.
    """
    name: str
    check: str
    columns: tuple[str, ...]
    expectations: Callable[[], list]
    era: str | None = None
    whole: Callable[[list[dict], Path], tuple[tuple[str, ...], tuple[str, ...], str]] | None = None


@dataclass(frozen=True)
class Result:
    """One suite's verdict, with all three outcomes kept apart.

    `inconclusive` is not a subset of either other tuple and never becomes one: those
    subjects were held out of the batch, so no expectation was ever asked about them.
    `ok` means "judged, and named by no failing expectation" - which is not quite "the
    suite vouched for it" when the suite failed at BATCH level (an aggregate expectation
    names no row), so read `outcome` for the verdict and these tuples for the detail.
    """
    suite: str
    check: str
    ok: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    inconclusive: tuple[str, ...] = ()
    detail: str = ""

    @property
    def outcome(self) -> str:
        """checks.py's vocabulary, in checks.rc's own precedence: a real failure outranks
        a not-run check, and a not-run check is never an ok."""
        if self.failed:
            return checks.FAIL
        return checks.INCONCLUSIVE if self.inconclusive else checks.OK

    def row(self) -> checks.Row:
        """This verdict as a check Row - so rc() below is checks.rc and not a second copy
        of its precedence. Not persisted: this module consumes batches, it produces none."""
        return checks.Row("gxcheck", self.suite, self.outcome, self.detail)

    def line(self) -> str:
        return (f"{self.outcome.upper():13s} {self.suite} [{self.check}] "
                f"{len(self.ok)} ok / {len(self.failed)} failed / "
                f"{len(self.inconclusive)} could not check"
                + (f" - {self.detail}" if self.detail else "")
                + ("" if not self.failed else f"\n  failed: {', '.join(self.failed)}")
                + ("" if not self.inconclusive
                   else f"\n  could not check: {', '.join(self.inconclusive)}"))


def _completeness() -> list:
    """The live-capture completeness suite's expectations, over `gapcheck`'s rows.

    Four, and every one of them is PER-ROW rather than aggregate. That is not a style
    choice: the inconclusive rows are held out of this frame, so an AGGREGATE expectation
    here would see a short batch and fail - which would render "could not check" as a
    failure, the exact conflation this ticket exists to prevent. Measured, not reasoned:
    an `ExpectColumnDistinctValuesToEqualSet` over the kinds did precisely that the first
    time a kind came back INCONCLUSIVE, and the test below is what caught it. A suite that
    needs a batch-level claim has to make it over the WHOLE batch, before the split.

    1. THE PRODUCER'S OWN VERDICT. `gapfill.check()` fails a row when it holds a fillable
       hour or a stale DEAD entry, so "24/24 or only allowlisted hours missing, and no
       stale allowlist entry" IS `outcome == ok`. Expecting on `fillable`/`stale_dead`
       here instead would copy that expression into a second home, which is the one thing
       this suite must not do.
    2. ONLY THE DECLARED KINDS, read from `gapfill.KINDS`. This is where the unrecoverable
       subway positions are excluded: gtfsrt.io archives subway TU only, so `subway_vp` is
       not a kind, and a batch that grew one would report a 0/24 gap nobody can ever fill.
       The check's own note says so in words; this says it in an expectation.
    3+4. THE ROW'S OWN ARITHMETIC. `hours_held` is `24 - len(missing)`; a judged row must
       carry it (NULL is the could-not-check convention, and those rows are not in this
       frame) and it cannot leave 0..24.
    """
    from great_expectations import expectations as gxe

    return [
        gxe.ExpectColumnValuesToBeInSet(column="outcome", value_set=[checks.OK]),
        gxe.ExpectColumnValuesToBeInSet(column="kind", value_set=list(gapfill.KINDS)),
        gxe.ExpectColumnValuesToNotBeNull(column="hours_held"),
        gxe.ExpectColumnValuesToBeBetween(column="hours_held", min_value=0, max_value=24),
    ]


def _fidelity() -> list:
    """The fill-fidelity suite's expectations, over `gapverify`'s rows. Per-row, all five.

    THE BAND IS THE MODULE'S, NEVER THE MEASURED ONE. Ticket 20 measured filled hours at
    0.85-1.2x their archiver neighbours; `gapfill.ROW_BAND` / `KEY_BAND` are what verify()
    actually enforces, an order of magnitude wider. Writing the observed figure here would
    make this suite the real gate and silently change what passes - which is the one thing
    ticket 09 exists to avoid. So the numbers are READ from the constants and a tightening
    is a change to the module, with its own evidence, never a second threshold over here.

    1. THE PRODUCER'S VERDICT. `verify()` is `FAIL if empty or schema drifted or either
       ratio out of band else OK`; this expects the verdict it wrote, not a copy of that
       expression.
    2. ONLY THE DECLARED KINDS, from `gapfill.KINDS`.
    3+4. THE RATIOS, in the module's own bands. Redundant with the verdict on purpose:
       `outcome` says a kind is bad and THIS says which measure left which band, in the
       Data Docs page a human reads at 06:00. Each is paired with a not-null, because a
       between-expectation counts nulls as MISSING and succeeds without them (orch 08
       measured that too) - and NULL is the could-not-check convention, so a judged row
       that carries no measure is a producer bug rather than a third outcome.
    5. A NON-EMPTY FILLED HOUR, and the archiver's columns present as a typed superset -
       `schema` is the producer's own rendering of that comparison ("=" / "superset" /
       "DIFFERS"), so reading it is not a second implementation of it.
    """
    from great_expectations import expectations as gxe

    return [
        gxe.ExpectColumnValuesToBeInSet(column="outcome", value_set=[checks.OK]),
        gxe.ExpectColumnValuesToBeInSet(column="kind", value_set=list(gapfill.KINDS)),
        gxe.ExpectColumnValuesToNotBeNull(column="row_ratio"),
        gxe.ExpectColumnValuesToBeBetween(column="row_ratio", min_value=gapfill.ROW_BAND[0],
                                          max_value=gapfill.ROW_BAND[1]),
        gxe.ExpectColumnValuesToNotBeNull(column="key_ratio"),
        gxe.ExpectColumnValuesToBeBetween(column="key_ratio", min_value=gapfill.KEY_BAND[0],
                                          max_value=gapfill.KEY_BAND[1]),
        gxe.ExpectColumnValuesToNotBeNull(column="filled_rows"),
        gxe.ExpectColumnValuesToBeBetween(column="filled_rows", min_value=1),
        gxe.ExpectColumnValuesToBeInSet(column="schema", value_set=["=", "superset"]),
    ]


def _fidelity_batch(batch_rows: list[dict], root: Path):
    """Two claims about the gapverify batch SET. Neither is an expectation, and neither
    could be: both are about rows that are not in the frame.

    ONE ROW PER DECLARED KIND. `gapverify` is MAPPED over `kind` (orch 06): five pods, five
    batches, five disjoint subjects. A kind whose pod never wrote is a check that did not
    run - INCONCLUSIVE, never an ok - and it is invisible to every expectation, because the
    row is not there to be unexpected.

    AND AN INCONCLUSIVE ROW MUST CARRY NO DAY. `verify()` says INCONCLUSIVE for exactly one
    reason - no filled hour with an archiver hour on the SAME DAY - and fills that row's
    measures with NULLs (`dict.fromkeys`). So a row that names a day and still could not
    judge it is a kind that went inconclusive on a day which HAS a comparable pair: the
    pair-finding broke, which is a defect and not a third outcome. Read off the column the
    producer already distinguishes rather than re-walking Bronze - `gxcheck` is the LAST
    stage of the nightly, the disk has moved on since the fill, and a second implementation
    of "is there a pair here" would be a second home for the one rule verify() owns.
    """
    seen = {r["kind"] for r in batch_rows}
    missing = tuple(f"<no batch: {k}>" for k in gapfill.KINDS if k not in seen)
    broke = tuple(sorted(r["subject"] for r in batch_rows
                         if r["outcome"] == checks.INCONCLUSIVE and r["day"]))
    notes = []
    if missing:
        notes.append(f"{len(missing)} declared kind(s) wrote no gapverify batch this run")
    if broke:
        notes.append(f"{len(broke)} kind(s) named a day and still could not check it - "
                     "the pair-finding broke")
    return broke, missing, "; ".join(notes)


def _cold_mirror() -> list:
    """The cold-mirror suite's expectations - and the two that are DELIBERATELY ABSENT.

    THIS SUITE REPORTS AND NEVER GATES, which is ticket 18's placement and ticket 09 does
    not get to change it on the side. `daily.coldcheck()` owns the behaviour: check,
    re-push once, warn, exit 0 - because what survives a re-push is the EC2 box's own
    capture of the same window (ticket 19), different bytes for an object that is PRESENT.
    An expectation on `outcome` here would route that straight into `gx.rc()` and out
    through the gxcheck gate, making GX the hard gate the module refuses to be. So the
    mirror's state is REPORTED - in the Result's detail and the line it prints - and what
    is expected on is the row CONVENTION instead:

      `differing` is NULL, never 0, on every could-not-check path (aws non-zero, cold
      storage unconfigured, nothing local to mirror). Those rows are held out of this
      frame, so a judged row that carries no count is a producer that started writing a
      measurement it never took - the exact conflation the null convention prevents, and
      the not-null is the only thing standing in front of it.
    """
    from great_expectations import expectations as gxe

    return [
        gxe.ExpectColumnValuesToNotBeNull(column="differing"),
        gxe.ExpectColumnValuesToBeBetween(column="differing", min_value=0),
    ]


def _cold_mirror_batch(batch_rows: list[dict], root: Path):
    """ONE ROW PER TOP-LEVEL `archive/` PREFIX, read off disk through `cold.kinds()` - the
    producer's own function and the one home for that list, so the row set grows with a new
    kind the day it lands instead of being pinned to five names here.

    A prefix with no row is a slice of Bronze the mirror was never asked about, which is a
    false OK with a whole feed behind it - and it is a claim about a MISSING row, so no
    expectation can make it. An EXTRA row is deliberately not failed: a tree with no
    `archive/` at all makes the producer emit one synthetic row rather than an empty batch
    (empty batches are the false OK checks.rc warns about), and that row is right.

    The mirror's own state rides out in `detail`. That is the report half of "reports and
    never gates": the counts reach the run's log and the Result, and nothing routes them
    into the exit code.
    """
    missing = tuple(f"<no row: {k}>" for k in sorted(set(cold.kinds(root))
                                                     - {r["kind"] for r in batch_rows}))
    differ = sorted((r["kind"], r["differing"]) for r in batch_rows
                    if r["outcome"] == checks.FAIL and r["differing"])
    notes = []
    if differ:
        notes.append("mirror drift REPORTED, not gated (daily.coldcheck re-pushes then "
                     "warns; `make coldgaps` tells drift from loss): "
                     + ", ".join(f"{k} {n}" for k, n in differ))
    if missing:
        notes.append(f"{len(missing)} archive/ prefix(es) have no row in this batch")
    return missing, (), "; ".join(notes)


def _schema_eras() -> list:
    """The schema-era suite's expectations, over `eras`' rows. COLUMN PRESENCE, never a
    count: a reader that forgets to union drops columns with the ROW COUNT STILL CORRECT
    (measured both ways in eras.py), so counting anything here would see nothing at all.

    `missing` is the producer's own rendering of that presence test and `outcome` is its
    verdict; both are expected on, because the verdict says a reader is broken and
    `missing` is what a human reads in Data Docs to see WHICH era columns went. `reader`
    and `kind` come from the module's own dicts, so a subject the check never declared
    cannot slip into the frame unnoticed.
    """
    from great_expectations import expectations as gxe

    return [
        gxe.ExpectColumnValuesToBeInSet(column="outcome", value_set=[checks.OK]),
        gxe.ExpectColumnValuesToBeInSet(column="missing", value_set=[""]),
        gxe.ExpectColumnValuesToBeInSet(column="reader", value_set=list(eras.READERS)),
        gxe.ExpectColumnValuesToBeInSet(column="kind", value_set=list(eras.ERA_COLS)),
    ]


def _schema_eras_batch(batch_rows: list[dict], root: Path):
    """EVERY DECLARED (reader, kind) HAS A ROW EVERY RUN - four today (`duck vp`,
    `spark vp`, `duck tu`, `spark tu`), and the product is read from `eras.READERS` and
    `eras.ERA_COLS` so a fifth reader is covered the day it is declared.

    `check()` emits a row for every pair on every path, INCONCLUSIVE included (no
    mixed-era day, no JVM), which is precisely why a short batch cannot be explained away
    as "that one could not check": those rows are here. A missing pair is a reader nobody
    looked at, and no expectation can be asked about a row that does not exist.
    """
    want = {f"{reader} {kind}" for reader in eras.READERS for kind in eras.ERA_COLS}
    missing = tuple(f"<no row: {s}>" for s in sorted(want - {r["subject"] for r in batch_rows}))
    return missing, (), (f"{len(missing)} declared (reader, kind) pair(s) have no row in "
                         f"this batch" if missing else "")


# --- orchestration 10: the two families that must NOT grow a nightly check -----------------
#
# Both of these expect on data that CANNOT CHANGE. The backfill range ends the day before
# live capture begins, and `ref/` cannot be rebuilt at all (`make picks` is 401-blocked). So
# neither belongs in SUITES: `gxcheck` would re-answer a settled question every morning, and
# it would answer it off whatever batch last landed - `batches()` takes the newest `run=`
# stamp and asks NO question about its age, which is exactly right for a nightly producer
# and exactly wrong for one that last ran in July. They are named on the command line
# instead, by the two `make` targets that fire after the event which could have moved them.

def _script(stem: str):
    """A `scripts/` producer loaded BY PATH, so its declared constants keep one home.

    `scripts/backfill-verify.py` is a script and not a package module ON PURPOSE: orch 03
    kept the two eras' tools apart, and `tests/test_check_producers.py` asserts its DEAD
    list is disjoint from `gapfill.DEAD`. Re-homing its CHECK_COLUMNS into the package so an
    `import` would work here would undo that separation for a suite's convenience. Loading
    it is side-effect free - the module body is constants and defs, and its `main()` is
    behind `__main__` - and `scripts/` is COPYed into the image beside `src/`.
    """
    from importlib.util import module_from_spec, spec_from_file_location

    from raincheck import paths

    path = paths.REPO / "scripts" / f"{stem}.py"
    spec = spec_from_file_location(f"_producer_{stem.replace('-', '_')}", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BACKFILL = _script("backfill-verify")


def _backfill() -> list:
    """The backfill census's expectations, over `backfill`'s rows. Per-row, all seven.

    1. THE PRODUCER'S OWN VERDICT. The census is `ok = not (missing or no_part or no_marker
       or zero_byte or stale_dead)`, and this expects the verdict it wrote. Restating that
       expression here would be a second home for it, and the two would drift apart the
       first time a chunk taught the census something new.
    2. ONLY THE DECLARED FEEDS, read from the script's own `FEEDS`. The backfill era has
       three (`vp`, `tu`, `alerts`) and they are NOT `gapfill.KINDS` - the two eras' tools
       stay apart, which is this ticket's standing rule and the reason for `_script` above.
    3-7. THE NULL CONVENTION AND THE TWO RULES THE TICKET NAMES, each a not-null PAIRED
       with its claim. `hours_seen`, `zero_byte` and `stale_dead` are NULL on the
       could-not-check path (`backfill-verify.py`'s `base` dict) and those rows are held out
       of this frame, so a JUDGED row carrying no count is a producer that started
       publishing a measurement it never took. The pairing is not decoration: an in-set
       expectation IGNORES nulls and succeeds without them (orch 08 measured the same for
       `between`), so the not-null is the only thing standing in front of a vanished measure.

       `zero_byte == 0` is the ticket's zero-byte-part rule. Its other half - that an empty
       `_gapfill` MARKER is exempt - is a property of the producer (a marker is counted as a
       marker and never as a part) and is pinned in `tests/test_check_producers.py`; a
       second implementation of it here could only disagree with the first.
       `stale_dead == 0` is the ticket's dead-hour-list rule: a listed dead hour that turned
       up means the allowlist is WRONG, and a wrong allowlist hides real gaps. Both are
       redundant with the verdict on purpose - `outcome` says a feed is bad, these say WHICH
       WAY, on the Data Docs page a human reads after a chunk lands.
    """
    from great_expectations import expectations as gxe

    return [
        gxe.ExpectColumnValuesToBeInSet(column="outcome", value_set=[checks.OK]),
        gxe.ExpectColumnValuesToBeInSet(column="feed", value_set=list(BACKFILL.FEEDS)),
        gxe.ExpectColumnValuesToNotBeNull(column="hours_seen"),
        gxe.ExpectColumnValuesToNotBeNull(column="zero_byte"),
        gxe.ExpectColumnValuesToBeInSet(column="zero_byte", value_set=[0]),
        gxe.ExpectColumnValuesToNotBeNull(column="stale_dead"),
        gxe.ExpectColumnValuesToBeInSet(column="stale_dead", value_set=[0]),
    ]


def _backfill_batch(batch_rows: list[dict], root: Path):
    """ONE ROW PER FEED - the census's own contract, and a claim no expectation can make.

    `backfill-verify.py` emits a row for every feed on EVERY path, INCONCLUSIVE included
    (orch 03 deleted the early return that used to abort the remaining feeds precisely so
    that stayed true). So a feed with no row is a feed whose range was never censused: a
    could-not-check and never a pass - and it is invisible inside the frame, because the row
    is not there to be unexpected.

    INCONCLUSIVE rather than FAIL, deliberately, and the `--feeds vp,tu` form is what
    decides it: censusing a subset on purpose is a legitimate run, and the honest report of
    the feeds it never asked about is "could not check", not "broken".

    THE RANGE RIDES OUT IN `detail` AND IS NOT GATED. `fold()` unions every batch within
    RUN_WINDOW and keeps the newest row per SUBJECT, so two census runs inside one window
    over DIFFERENT ranges fold into one batch whose rows are each true about a different
    chunk. Printing the ranges is what makes that readable; failing it would gate a workflow
    nobody runs today - the era is closed, the backfill ends where `gapfill.START` begins.
    """
    seen = {r["feed"] for r in batch_rows}
    missing = tuple(f"<no row: {f}>" for f in BACKFILL.FEEDS if f not in seen)
    ranges = sorted({"{}..{}".format(r["lo"], r["hi"]) for r in batch_rows})
    notes = [f"range(s) censused: {', '.join(ranges)}"] if ranges else []
    if missing:
        notes.append(f"{len(missing)} declared feed(s) have no row in this batch - a "
                     f"--feeds subset, or a feed that never ran")
    return (), missing, "; ".join(notes)


def _ref_canaries() -> list:
    """The reference canaries' expectations. TWO, and the shortness is the point.

    EXPECT THROUGH THE CANARY, NEVER RESTATE ITS NUMBER - not in an expectation and not in
    this docstring either, which is why no count is spelled out below. `ref.ASSETS_EXPECT`
    is the one home for every frozen count (complexes, stations, scored Cells, the total)
    and `ref_canary` compares the built table against it; this suite expects on the
    VERDICT that comparison wrote. Re-typing a count here would make the SUITE the real
    canary, and the two copies would disagree the first time the registry legitimately
    moved - the exact failure `ref.py` keeps its constants in one place to avoid.

    The not-null is on `got` ALONE: `want` is legitimately NULL on the identity row, which
    has nothing frozen to compare against (see `ref_canary`'s ceiling note). A canary that
    could not run at all - no `ref/assets` on this root, which is every worktree and every
    task pod - is INCONCLUSIVE with both measures NULL and is held out of this frame.
    """
    from great_expectations import expectations as gxe

    return [
        gxe.ExpectColumnValuesToBeInSet(column="outcome", value_set=[checks.OK]),
        gxe.ExpectColumnValuesToNotBeNull(column="got"),
    ]


def _ref_canaries_batch(batch_rows: list[dict], root: Path):
    """EVERY DECLARED CANARY HAS A ROW, and the identity's VALUE rides out in `detail`.

    The declaration is `ref_canary.subjects()` - derived from `ref.ASSETS_EXPECT` and the
    two key tables, so a count frozen in `ref.py` tomorrow is covered the day it lands
    rather than the day someone remembers this list. A canary with no row was not run, which
    no expectation can be asked about and which must not read as a pass.

    Reporting `assets_version` here is the whole job of the identity row: nothing in this
    repo persists a counterpart to compare it against, so its value exists to be READ - on
    the page, beside the counts that would have moved with it.
    """
    have = {r["subject"] for r in batch_rows}
    missing = tuple(f"<no canary: {s}>" for s in ref_canary.subjects() if s not in have)
    identity = [r["got"] for r in batch_rows if r["subject"] == ref_canary.IDENTITY]
    notes = [f"{ref_canary.IDENTITY} {identity[0]}"] if identity and identity[0] else []
    if missing:
        notes.append(f"{len(missing)} declared canary(ies) have no row in this batch")
    return (), missing, "; ".join(notes)


SUITES: tuple[Suite, ...] = (
    Suite("live-capture-completeness", "gapcheck",
          gapfill.CHECK_COLUMNS["gapcheck"], _completeness, era="day"),
    # Orchestration ticket 09's three. Names are URL segments (a Data Docs page each), so
    # no spaces and no collision with orch 10's, which land in this same tuple this wave.
    Suite("fill-fidelity", "gapverify", gapfill.CHECK_COLUMNS["gapverify"],
          _fidelity, era="day", whole=_fidelity_batch),
    # No `era`: the cold mirror's subject is an archive prefix and its batch has no day.
    Suite("cold-mirror", "coldcheck", cold.CHECK_COLUMNS, _cold_mirror,
          whole=_cold_mirror_batch),
    # No `era` EITHER, and this one is a decision rather than an absence. `eras.day` is the
    # newest Bronze date dir whose parts disagree about their columns - the producer's
    # choice of where to stand, not a declaration of scope - and `archive/` holds the
    # backfilled range too. Setting era="day" would turn "the only mixed-schema day left is
    # an old one" into a refusal, i.e. a crash in this stage over a check that ran fine.
    Suite("schema-eras", "eras", eras.CHECK_COLUMNS, _schema_eras,
          whole=_schema_eras_batch),
)

NON_NIGHTLY: tuple[Suite, ...] = (
    # `Suite.era` STAYS None here, and that is a hard requirement rather than an omission:
    # `ERA_START` is `gapfill.START` and the backfill range ENDS THE DAY BEFORE, so
    # `era="lo"` (or "hi") would refuse this batch ENTIRELY - every row, every run, with the
    # message telling you to go and look at this very check. This check IS the other era.
    # orch 08's live-capture suite must never be pointed at this range, and this suite must
    # never inherit that suite's boundary; the two eras' tools stay apart.
    Suite("backfill-census", BACKFILL.CHECK, BACKFILL.CHECK_COLUMNS, _backfill,
          whole=_backfill_batch),
    # No `era` either, and nothing here carries a day at all: a canary's subject is a frozen
    # count, an identity or a derived table's key set.
    Suite("ref-canaries", ref_canary.CHECK, ref_canary.CHECK_COLUMNS, _ref_canaries,
          whole=_ref_canaries_batch),
)

DECLARED: tuple[Suite, ...] = SUITES + NON_NIGHTLY


def by_name(name: str) -> Suite:
    """One declared suite, by name - what the two non-nightly `make` targets select with.

    BY NAME and never by position, for the same reason `tests/test_gx.py` looks its suites
    up that way: three tickets have appended to these tuples in two waves, and an index
    silently repoints one ticket's trigger at another ticket's suite.
    """
    for suite in DECLARED:
        if suite.name == name:
            return suite
    raise SystemExit(f"gxcheck: no suite named {name!r}. Declared: "
                     + ", ".join(s.name for s in DECLARED))


def available() -> bool:
    return find_spec("great_expectations") is not None


def docs_dir(root: Path) -> Path:
    return root.joinpath(*DOCS)


def _stamp(path: Path) -> str:
    return path.name[len("run="):-len(".jsonl")]


def batches(root: Path, check: str) -> list[Path]:
    """ONE run's batches for one check, NEWEST FIRST - the set, where batch() is its head.

    A producer writes one file per INVOCATION, and since orch 06 a stage that fans out is
    invoked once per pod: `gapverify` is mapped over `kind`, so five pods write five
    batches carrying five disjoint subjects. Reading the newest stamp alone would judge
    whichever kind finished last and report nothing at all about the other four - not as a
    gap, not as a could-not-check, but as rows that were never in the frame.

    RUN_WINDOW is what keeps this a RUN and not a history. Only the newest stamp is ever
    parsed: the floor is formatted back into checks.write's own fixed-width alphabet and
    compared as text, which is the same comparison the sort above already made.
    """
    runs = sorted((root / "checks" / f"check={check}").glob("run=*.jsonl"), reverse=True)
    if not runs:
        return []
    floor = (datetime.strptime(_stamp(runs[0]), STAMP) - RUN_WINDOW).strftime(STAMP)
    return [p for p in runs if _stamp(p) >= floor]


def batch(root: Path, check: str) -> Path | None:
    """The authoritative batch for one check: the newest `run=` stamp.

    The stamp is `%Y%m%dT%H%M%SZ`, so newest is lexicographic max. This matters for the
    cold mirror, which writes a batch PER INVOCATION and is invoked twice by
    `daily.coldcheck()` on a mismatch (check, re-push, re-check): both files are true
    records of a run that happened, and the later one is the verdict.
    """
    runs = batches(root, check)
    return runs[0] if runs else None


def fold(paths: list[Path], columns: tuple[str, ...], era: str | None = None) -> list[dict]:
    """One run's batches (newest first) as ONE list of rows: the newest verdict per subject.

    The two producers that need this need it for opposite reasons, and one rule covers
    both. `gapverify`'s five pods write disjoint subjects, so the run's rows are their
    UNION. `coldcheck` re-checks the same subjects after a re-push, so there the later
    stamp WINS - which is exactly the rule batch() has documented since orch 08, now
    implemented rather than implied.
    """
    out: dict[str, dict] = {}
    for path in paths:
        for row in rows(path, columns, era):
            out.setdefault(row["subject"], row)
    return list(out.values())


def merged(result: Result, failed: tuple[str, ...] = (),
           inconclusive: tuple[str, ...] = (), detail: str = "") -> Result:
    """A suite's own batch-level claim, folded into the verdict GX returned.

    FAILED WINS OVER COULD-NOT-CHECK, and that direction is the point: a subject the
    producer reported inconclusive and the batch claim proves was judgeable is a defect in
    the producer, not a third outcome, so it LEAVES `inconclusive` when it joins `failed`.
    checks.rc's precedence then applies to the merged Result unchanged.
    """
    if not (failed or inconclusive or detail):
        return result
    red = set(result.failed) | set(failed)
    held = (set(result.inconclusive) | set(inconclusive)) - red
    return Result(result.suite, result.check,
                  ok=tuple(s for s in result.ok if s not in red and s not in held),
                  failed=tuple(sorted(red)), inconclusive=tuple(sorted(held)),
                  detail="; ".join(d for d in (result.detail, detail) if d))


def rows(path: Path, columns: tuple[str, ...], era: str | None = None) -> list[dict]:
    """One batch as flat dicts, asserted against the producer's declared columns.

    `checks.write` asserts the same tuple on the way out, so a mismatch here means the
    batch on disk and the constant have drifted apart - a crash upstream of GX rather
    than a suite expecting on columns that moved.
    """
    out = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for row in out:
        if tuple(row) != tuple(columns):
            raise ValueError(f"{path}: row columns {tuple(row)} != declared {tuple(columns)}")
    if era:
        early = sorted({r[era] for r in out if r.get(era) and r[era] < ERA_START})
        if early:
            raise ValueError(
                f"{path}: {len(early)} row(s) before the live-capture era "
                f"({early[0]} < {ERA_START}). This suite is scoped to live capture and "
                f"must never be pointed at the backfill range - that era has its own "
                f"census, its own DEAD list and its own check (scripts/backfill-verify.py).")
    return out


def context(docs: Path):
    """An EPHEMERAL GX context whose one Data Docs site writes into `docs`.

    Ephemeral on purpose: nothing about a nightly checkpoint wants a `great_expectations.yml`,
    an expectations/ tree or an uncommitted/ tree living on the data root. The suites are
    declared in this file, the batches are on disk, and the only durable output is the
    rendered site - which is the thing that gets published.

    Analytics OFF explicitly. A pod must make no network call nobody asked for, and
    "the current version does not bundle the client" is not a guarantee about the next one.
    """
    import great_expectations as gx

    ctx = gx.get_context(mode="ephemeral")
    ctx.enable_analytics(False)
    ctx.variables.progress_bars = {"globally": False, "metric_calculations": False}
    ctx.variables.data_docs_sites = {SITE: {
        "class_name": "SiteBuilder",
        "show_how_to_buttons": False,
        # GX refuses a relative base_directory without a project root, and this context
        # has none.
        "store_backend": {"class_name": "TupleFilesystemStoreBackend",
                          "base_directory": str(docs.resolve())},
        "site_index_builder": {"class_name": "DefaultSiteIndexBuilder"},
    }}
    return ctx


def validate(ctx, suite: Suite, batch_rows: list[dict]) -> Result:
    """The adapter: check rows in, a validation result with THREE outcomes out.

    The split is the whole mechanism. INCONCLUSIVE rows never enter the frame, because an
    expectation has exactly two answers and anything inside the frame gets one of them.
    They come back on `Result.inconclusive`, they decide the outcome when nothing failed,
    and they are in neither `ok` nor `failed` by construction rather than by convention.

    NULL measures stay NULL. The frame is built straight from the rows with no dtype
    coercion and no fillna anywhere: `differing` and `hours_seen` on a could-not-check row
    are NULL and must never read as a measured 0.
    """
    import great_expectations as gx
    import pandas as pd

    judged = [r for r in batch_rows if r["outcome"] != checks.INCONCLUSIVE]
    held = tuple(r["subject"] for r in batch_rows if r["outcome"] == checks.INCONCLUSIVE)
    if not judged:
        return Result(suite.name, suite.check, inconclusive=held or ("<empty batch>",),
                      detail="no row in this batch could be judged")

    asset = _source(ctx).add_dataframe_asset(suite.name)
    definition = ctx.validation_definitions.add(gx.ValidationDefinition(
        name=suite.name, data=asset.add_batch_definition_whole_dataframe("batch"),
        suite=ctx.suites.add(_suite_of(suite))))
    result = definition.run(batch_parameters={"dataframe": pd.DataFrame(judged)},
                            result_format=RESULT_FORMAT)

    named = {d["subject"] for e in result.results if not e.success
             for d in (e.result.get("unexpected_index_list") or [])}
    # GX's OWN `success` decides; the named subjects only say WHICH. An aggregate
    # expectation fails without naming a row, and so does a per-row one over an all-null
    # column - so a failing suite that named nobody must still be charged to the batch.
    # Without this the outcome would read INCONCLUSIVE (or OK) on a suite that failed,
    # which is the third outcome's conflation pointing the other way.
    failed = tuple(sorted(named)) if named else ((f"<{suite.check} batch>",)
                                                 if not result.success else ())
    return Result(suite.name, suite.check,
                  ok=tuple(sorted(r["subject"] for r in judged if r["subject"] not in named)),
                  failed=failed, inconclusive=held,
                  detail="" if result.success else
                         ", ".join(sorted(e.expectation_config.type for e in result.results
                                          if not e.success)))


def _source(ctx):
    """The one pandas data source, created on first use. `add_pandas` raises on a name
    that already exists, so validate() can be called more than once against one context."""
    from great_expectations.exceptions import DataContextError

    try:
        return ctx.data_sources.get(DATASOURCE)
    except (KeyError, DataContextError):
        return ctx.data_sources.add_pandas(DATASOURCE)


def _suite_of(suite: Suite):
    import great_expectations as gx

    out = gx.ExpectationSuite(name=suite.name)
    for expectation in suite.expectations():
        out.add_expectation(expectation)
    return out


def run(root: Path, suites: tuple[Suite, ...] = SUITES,
        docs: Path | None = None) -> tuple[list[Result], Path]:
    """Every declared suite, then Data Docs ONCE at the end of the run.

    `docs` defaults to `docs_dir(root)`, which is the NIGHTLY's site and the `docs` family's
    source. A run of a NON-NIGHTLY suite passes its own directory, and that is not tidiness:
    `build_data_docs()` rebuilds the WHOLE site (below), so a `make gxref` at noon writing
    into the nightly's tree would DELETE last night's four pages from the exact directory
    `make publish FAMILY=docs` sends to the public host.

    `docs/**` is THIS run's report and nothing accumulates in it, which matters because
    the tree is published wholesale every night - the "no served history" rule cloud 09
    wrote for the live family, read across. MEASURED on GX 1.21.0 rather than assumed, and
    then a line was DELETED for it: `build_data_docs()` rebuilds the whole site, so the
    previous run's validation page is replaced and a RETIRED suite's pages disappear
    entirely. An `rmtree` of the site here was dead code - it survived every mutation
    because nothing could observe it. The property is pinned by a test instead, which is
    also where a future GX that stopped cleaning would be caught. Do not put it back
    without a failing case.
    """
    from raincheck import paths

    if paths.remote(root) is not None:
        # GX's filesystem store backend writes a real directory tree. Same POSIX-only list
        # as precip_live, export and live_export (cloud 12/13): the data root can be an
        # object store, this writer cannot follow it there yet.
        raise ValueError(f"gxcheck: Data Docs are POSIX-only and this root is an object "
                         f"store ({root}). Run the checkpoint on a local root.")
    docs = docs or docs_dir(root)
    # ponytail: the REMOTE still keeps whatever a previous run published under a stamp this
    # one does not write - publish overwrites, it never deletes - and nothing links to them.
    # A bucket lifecycle rule is the place to fix that, not this stage.
    ctx = context(docs)
    results = []
    for suite in suites:
        paths = batches(root, suite.check)
        if not paths:
            # A producer with nothing on disk is a check that did not run. Never an ok:
            # that is the false-OK the whole check vocabulary exists to kill.
            results.append(Result(suite.name, suite.check,
                                  inconclusive=("<no batch>",),
                                  detail=f"no batch under checks/check={suite.check}/"))
            continue
        # The RUN's rows, not one file's: a mapped stage writes a batch per pod (orch 06).
        batch_rows = fold(paths, suite.columns, suite.era)
        result = validate(ctx, suite, batch_rows)
        # ...and the claims no expectation can make, over every row, before the split.
        results.append(merged(result, *suite.whole(batch_rows, root)) if suite.whole
                       else result)
    ctx.build_data_docs(site_names=[SITE])
    return results, docs


def rc(results: list[Result]) -> int:
    return checks.rc([r.row() for r in results])


def main(argv: list[str] | None = None) -> None:
    """No argument runs the NIGHTLY declaration; one argument names ONE declared suite.

    `daily.STAGES`' `gxcheck` carries `argv=("gx",)` and so reaches the no-argument form -
    the nightly's four suites, into the nightly's own Data Docs tree. The named form is what
    orch 10's two non-nightly `make` targets run, and it renders into its own directory
    (see `run`). Selecting a SET rather than a suite was considered and dropped: two targets
    means two names, and a set would be a second declaration to keep in step with this one.
    """
    argv = list(argv or [])
    root = data_root()
    if len(argv) > 1:
        raise SystemExit(f"gxcheck: one suite name at most, got {argv}. Each named run "
                         f"renders its own Data Docs site, so they cannot share one.")
    if not available():
        # The extra is not installed, so nothing was checked. INCONCLUSIVE, and on a
        # declared gate that is a `skipped` task rather than a red one (orch 07).
        print("gxcheck: great_expectations is not installed - nothing was checked. "
              "Install the optional extra: pip install -e '.[gx]'", flush=True)
        sys.exit(checks.rc([checks.Row("gxcheck", "library", checks.INCONCLUSIVE, "")]))
    nightly = not argv
    suites = SUITES if nightly else (by_name(argv[0]),)
    results, docs = run(root, suites, None if nightly else root / "gx" / f"docs-{argv[0]}")
    for result in results:
        print(result.line(), flush=True)
    # The report is only useful if it can be published, and the publisher's allowlist is
    # what decides. Checked HERE, on the tree that was just built, so a GX version that
    # starts emitting something that is not a web payload fails in this stage with the
    # offending file named - not later, in another session, at publish time. A named run
    # checks the same thing and publishes nothing: only the nightly's tree is a family.
    published = publish.plan("docs", docs)
    where = ("`make publish FAMILY=docs` sends them to docs/** on the public host"
             if nightly else
             f"NOT published - the `docs` family's source is {docs_dir(root)}, and this "
             f"run deliberately did not touch it")
    print(f"gxcheck: Data Docs -> {docs} ({len(published)} publishable object(s); "
          f"{where})", flush=True)
    sys.exit(rc(results))


if __name__ == "__main__":
    main(sys.argv[1:])
