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

Run: make gxcheck   (python -m raincheck.gx)
Exit: 1 any suite failed, 2 any suite could not check, else 0 - checks.rc's own rule.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Callable, NamedTuple

from raincheck import checks, gapfill, publish
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
    """
    name: str
    check: str
    columns: tuple[str, ...]
    expectations: Callable[[], list]
    era: str | None = None


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


SUITES: tuple[Suite, ...] = (
    Suite("live-capture-completeness", "gapcheck",
          gapfill.CHECK_COLUMNS["gapcheck"], _completeness, era="day"),
)


def available() -> bool:
    return find_spec("great_expectations") is not None


def docs_dir(root: Path) -> Path:
    return root.joinpath(*DOCS)


def batch(root: Path, check: str) -> Path | None:
    """The authoritative batch for one check: the newest `run=` stamp.

    The stamp is `%Y%m%dT%H%M%SZ`, so newest is lexicographic max. This matters for the
    cold mirror, which writes a batch PER INVOCATION and is invoked twice by
    `daily.coldcheck()` on a mismatch (check, re-push, re-check): both files are true
    records of a run that happened, and the later one is the verdict.
    """
    runs = sorted((root / "checks" / f"check={check}").glob("run=*.jsonl"))
    return runs[-1] if runs else None


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


def run(root: Path, suites: tuple[Suite, ...] = SUITES) -> tuple[list[Result], Path]:
    """Every declared suite, then Data Docs ONCE at the end of the run.

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
    docs = docs_dir(root)
    # ponytail: the REMOTE still keeps whatever a previous run published under a stamp this
    # one does not write - publish overwrites, it never deletes - and nothing links to them.
    # A bucket lifecycle rule is the place to fix that, not this stage.
    ctx = context(docs)
    results = []
    for suite in suites:
        path = batch(root, suite.check)
        if path is None:
            # A producer with nothing on disk is a check that did not run. Never an ok:
            # that is the false-OK the whole check vocabulary exists to kill.
            results.append(Result(suite.name, suite.check,
                                  inconclusive=("<no batch>",),
                                  detail=f"no batch under checks/check={suite.check}/"))
            continue
        results.append(validate(ctx, suite, rows(path, suite.columns, suite.era)))
    ctx.build_data_docs(site_names=[SITE])
    return results, docs


def rc(results: list[Result]) -> int:
    return checks.rc([r.row() for r in results])


def main(argv: list[str] | None = None) -> None:
    root = data_root()
    if not available():
        # The extra is not installed, so nothing was checked. INCONCLUSIVE, and on a
        # declared gate that is a `skipped` task rather than a red one (orch 07).
        print("gxcheck: great_expectations is not installed - nothing was checked. "
              "Install the optional extra: pip install -e '.[gx]'", flush=True)
        sys.exit(checks.rc([checks.Row("gxcheck", "library", checks.INCONCLUSIVE, "")]))
    results, docs = run(root)
    for result in results:
        print(result.line(), flush=True)
    # The report is only useful if it can be published, and the publisher's allowlist is
    # what decides. Checked HERE, on the tree that was just built, so a GX version that
    # starts emitting something that is not a web payload fails in this stage with the
    # offending file named - not later, in another session, at publish time.
    published = publish.plan("docs", docs)
    print(f"gxcheck: Data Docs -> {docs} ({len(published)} publishable object(s); "
          f"`make publish FAMILY=docs` sends them to docs/** on the public host)", flush=True)
    sys.exit(rc(results))


if __name__ == "__main__":
    main(sys.argv[1:])
