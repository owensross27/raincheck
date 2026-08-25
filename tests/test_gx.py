"""The Great Expectations foundation and the live-capture completeness suite
(orchestration ticket 08).

The claim this file exists for is a NEGATIVE one, the same shape as ticket 07's: no path
through the adapter renders an INCONCLUSIVE check row as either a pass or a failure. A
check that could not run tells you nothing about the data, and an expectation has exactly
two answers - so the third outcome survives only because those rows are held OUT of the
frame GX sees, and that is what is pinned here.

Most of this needs no Great Expectations: the batch selection, the column assertion, the
era refusal, the three-way split and the declaration are all plain Python, so they run on
any checkout. Only the tests that actually validate a batch and render Data Docs need the
optional extra, and those SKIP cleanly when it is absent (`pip install -e '.[gx]'`). They
are not left unrun: they are run for real against a pinned GX 1.x in a throwaway venv, the
orch 04/05/07 precedent for Airflow.

Nothing here reaches the network. GX analytics are disabled by the module itself.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from raincheck import checks, cold, daily, eras, gapfill, gx, publish, ref_canary

ROOT = Path(__file__).parents[1]
needs_gx = pytest.mark.skipif(not gx.available(), reason="great_expectations not installed "
                                                         "(optional extra: pip install -e '.[gx]')")
COLUMNS = gapfill.CHECK_COLUMNS["gapcheck"]
DAY = "2026-08-20"
LIVE = "live-capture-completeness"


def declared_suite(name: str) -> gx.Suite:
    """One declared suite BY NAME, never by position: three tickets append to these tuples
    across two waves, and an index here would quietly start testing someone else's.

    Over `gx.DECLARED` rather than `gx.SUITES` since orch 10: `SUITES` is the NIGHTLY
    declaration alone now, and the two non-nightly suites live in `gx.NON_NIGHTLY`."""
    return next(s for s in gx.DECLARED if s.name == name)


def gapcheck_row(kind: str, outcome: str, day: str = DAY, held: int = 24, **over) -> checks.Row:
    """One gapcheck-shaped row. An INCONCLUSIVE one carries NULL measures, never zeros -
    the convention the whole third outcome rests on."""
    measures = {"kind": kind, "day": day, "hours_held": held,
                "fillable": "", "dead": "", "stale_dead": ""}
    if outcome == checks.INCONCLUSIVE:
        measures = {"kind": kind} | dict.fromkeys(
            (c for c in COLUMNS[len(checks.CORE):] if c != "kind"))
    return checks.Row("gapcheck", f"{kind} {day}", outcome, "", measures | over)


VERIFY = gapfill.CHECK_COLUMNS["gapverify"]
ERAS = eras.CHECK_COLUMNS
AT = datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc)   # one nightly's own clock


def verify_row(kind: str, outcome: str, **over) -> checks.Row:
    """One gapverify-shaped row. Its INCONCLUSIVE form is the producer's own -
    `dict.fromkeys(...)` over every measure, so `day` is NULL with the rest - and `over` is
    what a test uses to break exactly one of those conventions on purpose."""
    if outcome == checks.INCONCLUSIVE:
        measures = dict.fromkeys(VERIFY[len(checks.CORE):]) | {"kind": kind}
    else:
        measures = {"kind": kind, "day": DAY, "filled_hour": "03", "captured_hour": "09",
                    "filled_rows": 900, "captured_rows": 1000, "filled_keys": 90,
                    "captured_keys": 100, "row_ratio": 0.9, "key_ratio": 0.9,
                    "schema": "superset"}
    return checks.Row("gapverify", kind, outcome, "", measures | over)


def verify_batch(root: Path, rows: list[checks.Row], at: datetime = AT) -> list[Path]:
    """The MAPPED producer's real shape: one batch PER POD, minutes apart (orch 06)."""
    return [checks.write(root, "gapverify", [r], VERIFY, at=at + timedelta(minutes=i))
            for i, r in enumerate(rows)]


def cold_row(kind: str, outcome: str, differing: int | None = 0) -> checks.Row:
    return checks.Row("coldcheck", kind, outcome, "",
                      {"kind": kind, "differing": differing})


def eras_row(reader: str, kind: str, outcome: str, missing: str | None = "",
             day: str | None = DAY) -> checks.Row:
    return checks.Row("eras", f"{reader} {kind}", outcome, "",
                      {"reader": reader, "kind": kind, "day": day,
                       "era_cols": ",".join(eras.ERA_COLS[kind]), "missing": missing})


def eras_batch(root: Path, rows: list[checks.Row] | None = None) -> Path:
    rows = rows if rows is not None else [eras_row(r, k, checks.OK)
                                          for r in eras.READERS for k in eras.ERA_COLS]
    return checks.write(root, "eras", rows, ERAS, at=AT)


def every_producer(root: Path) -> None:
    """A batch for every declared suite's producer - what a whole green nightly leaves on
    disk, so a full gx.run() here is the whole report and not one page of it."""
    full_batch(root)
    verify_batch(root, [verify_row(k, checks.OK) for k in gapfill.KINDS])
    checks.write(root, "coldcheck", [cold_row("vp", checks.OK)], cold.CHECK_COLUMNS, at=AT)
    (root / "archive" / "vp").mkdir(parents=True, exist_ok=True)
    eras_batch(root)


def full_batch(root: Path, outcomes: dict[str, str] | None = None) -> Path:
    """One batch holding every declared kind, so the suite's coverage expectation is
    satisfied unless a test deliberately breaks it."""
    outcomes = outcomes or {}
    rows = [gapcheck_row(k, outcomes.get(k, checks.OK),
                         held=23 if outcomes.get(k) == checks.FAIL else 24,
                         **({"fillable": "03"} if outcomes.get(k) == checks.FAIL else {}))
            for k in gapfill.KINDS]
    return checks.write(root, "gapcheck", rows, COLUMNS)


# --- the batch on disk ---------------------------------------------------------------------

def test_the_authoritative_batch_is_the_newest_run_stamp(tmp_path):
    """The cold mirror writes a batch PER INVOCATION, and daily.coldcheck() invokes it
    twice on a mismatch (check, re-push, re-check). Both files are true records of a run
    that happened; the later stamp is the verdict. Written here through checks.write's own
    `at`, so the rule is tested against the real stamp format and not a hand-made name."""
    from datetime import datetime, timezone

    early = datetime(2026, 8, 20, 6, 0, tzinfo=timezone.utc)
    late = datetime(2026, 8, 20, 6, 30, tzinfo=timezone.utc)
    checks.write(tmp_path, "coldcheck", [checks.Row("coldcheck", "vp", checks.FAIL)],
                 checks.CORE, at=early)
    newest = checks.write(tmp_path, "coldcheck", [checks.Row("coldcheck", "vp", checks.OK)],
                          checks.CORE, at=late)
    assert gx.batch(tmp_path, "coldcheck") == newest
    assert gx.rows(newest, checks.CORE)[0]["outcome"] == checks.OK


def test_no_batch_at_all_is_inconclusive_and_never_ok(tmp_path):
    """A producer with nothing on disk did not run. Reporting that as a pass is the exact
    false-OK the check vocabulary was built to kill. Rows only: the same claim is made
    through run() below, because a Result built by hand tests the constructor and not the
    path that actually builds one."""
    assert gx.batch(tmp_path, "gapcheck") is None
    result = gx.Result("s", "gapcheck", inconclusive=("<no batch>",))
    assert result.outcome == checks.INCONCLUSIVE
    assert gx.rc([result]) == 2


@needs_gx
def test_a_run_with_no_batch_on_disk_reports_could_not_check(tmp_path):
    """The whole stage on an empty root: the suite could not run, so the run is
    INCONCLUSIVE and its rc is 2 - which on this declared gate is a `skipped` task rather
    than a red one (orch 07). Data Docs still build: an empty report is the honest one."""
    results, docs = gx.run(tmp_path)
    assert [r.outcome for r in results] == [checks.INCONCLUSIVE] * len(gx.SUITES)
    assert all(r.inconclusive == ("<no batch>",) and not r.ok for r in results)
    assert gx.rc(results) == 2
    assert (docs / "index.html").is_file()


def test_a_batch_that_drifted_from_the_producers_constant_is_refused(tmp_path):
    """The suite asserts the batch against the producer's OWN declared CHECK_COLUMNS, never
    a literal list retyped here. checks.write asserts the same tuple on the way out, so a
    mismatch means the two have drifted apart - a crash upstream of GX, not a leak."""
    path = full_batch(tmp_path)
    path.write_text(json.dumps({"check": "gapcheck", "subject": "vp", "outcome": "ok"}) + "\n")
    with pytest.raises(ValueError, match="!= declared"):
        gx.rows(path, COLUMNS)


def test_the_suite_is_refused_on_a_batch_that_reaches_into_the_backfill_era(tmp_path):
    """SCOPE: live capture only. The backfilled range (2026-03-01..08-14) predates capture,
    has its own DEAD list and its own census (scripts/backfill-verify.py) - a completeness
    suite pointed at it is pointed at the wrong data, which is a defect and not a finding.
    The boundary is read from gapfill.START, so moving capture's start moves this too."""
    from datetime import timedelta

    before = (gapfill.START - timedelta(days=1)).isoformat()
    path = checks.write(tmp_path, "gapcheck", [gapcheck_row("vp", checks.OK, day=before)],
                        COLUMNS)
    with pytest.raises(ValueError, match="before the live-capture era"):
        gx.rows(path, COLUMNS, era="day")
    assert gx.ERA_START == gapfill.START.isoformat()


def test_could_not_check_stays_null_and_is_never_read_as_a_measured_zero(tmp_path):
    """`differing` and `hours_seen` are NULL on a could-not-check row, and a 0 there is a
    measurement that was never taken. Nothing in the adapter coerces dtypes or fills, so
    the null survives the read - asserted here against `is None` rather than falsiness,
    because 0 is falsy and that is the whole conflation."""
    path = checks.write(tmp_path, "gapcheck",
                        [gapcheck_row("vp", checks.INCONCLUSIVE)], COLUMNS)
    (row,) = gx.rows(path, COLUMNS, era="day")
    assert row["hours_held"] is None and row["day"] is None
    assert row["hours_held"] != 0


# --- the adapter: three outcomes in, three outcomes out ------------------------------------

@needs_gx
def test_the_third_outcome_survives_the_adapter(tmp_path):
    """THE ticket. One passing subject, one failing subject, one that could not be checked:
    the inconclusive one is in NEITHER the passed nor the failed list, and it is not
    invented - it is the row's own outcome carried through untouched.

    It survives because it is held OUT of the frame GX sees. An expectation answers
    expected/unexpected and nothing else, so any row inside the batch has already been
    flattened into two outcomes by the time the suite runs."""
    rows = [gapcheck_row("vp", checks.OK),
            gapcheck_row("tu", checks.FAIL, held=23, fillable="03"),
            gapcheck_row("alerts", checks.INCONCLUSIVE),
            gapcheck_row("subway_tu", checks.OK), gapcheck_row("subway_alerts", checks.OK)]
    path = checks.write(tmp_path, "gapcheck", rows, COLUMNS)
    ctx = gx.context(tmp_path / "docs")
    suite = declared_suite(LIVE)
    result = gx.validate(ctx, suite, gx.rows(path, COLUMNS, suite.era))

    assert result.inconclusive == (f"alerts {DAY}",)
    assert f"alerts {DAY}" not in result.ok
    assert f"alerts {DAY}" not in result.failed
    assert result.failed == (f"tu {DAY}",)         # named, from GX's own unexpected index
    assert f"vp {DAY}" in result.ok
    assert result.outcome == checks.FAIL           # a real gap outranks a not-run check


@needs_gx
def test_a_batch_whose_only_red_is_a_not_run_check_is_inconclusive_not_failed(tmp_path):
    """The other direction, and the one a two-outcome rendering gets wrong: nothing failed,
    so the suite must not be red - but something could not be checked, so it must not be
    green either. checks.rc's precedence, reached through checks.rc itself."""
    rows = [gapcheck_row(k, checks.INCONCLUSIVE if k == "alerts" else checks.OK)
            for k in gapfill.KINDS]
    path = checks.write(tmp_path, "gapcheck", rows, COLUMNS)
    suite = declared_suite(LIVE)
    result = gx.validate(gx.context(tmp_path / "docs"), suite,
                         gx.rows(path, COLUMNS, suite.era))
    assert not result.failed and result.inconclusive == (f"alerts {DAY}",)
    assert result.outcome == checks.INCONCLUSIVE
    assert gx.rc([result]) == 2


@needs_gx
def test_the_unrecoverable_subway_positions_are_excluded_by_the_checks_own_kinds(tmp_path):
    """gtfsrt.io archives subway TU only, so `subway_vp` is not one of gapfill.KINDS and
    the check never asks about it - its note says so in words. A batch that grew such a row
    would report a 0/24 gap nobody can ever fill, so the suite fails it, and the value_set
    is read from the constant rather than typed here."""
    assert "subway_vp" not in gapfill.KINDS
    rows = [gapcheck_row(k, checks.OK) for k in gapfill.KINDS]
    rows.append(gapcheck_row("subway_vp", checks.OK, held=0))
    path = checks.write(tmp_path, "gapcheck", rows, COLUMNS)
    suite = declared_suite(LIVE)
    result = gx.validate(gx.context(tmp_path / "docs"), suite, gx.rows(path, COLUMNS))
    assert result.outcome == checks.FAIL
    assert result.failed == (f"subway_vp {DAY}",)


@needs_gx
def test_a_judged_row_that_carries_no_measure_fails_rather_than_passing_quietly(tmp_path):
    """NULL is the could-not-check convention, and those rows are not in this frame - so a
    row that claims to have been judged and then carries no `hours_held` is a producer bug,
    not a third outcome. It has to FAIL: a between-expectation counts nulls as MISSING and
    succeeds without them, so the not-null expectation is the only thing standing between a
    measure that vanished and a green suite."""
    rows = [gapcheck_row(k, checks.OK) for k in gapfill.KINDS]
    rows[0] = gapcheck_row("vp", checks.OK, held=None)
    path = checks.write(tmp_path, "gapcheck", rows, COLUMNS)
    suite = declared_suite(LIVE)
    result = gx.validate(gx.context(tmp_path / "docs"), suite, gx.rows(path, COLUMNS))
    assert result.outcome == checks.FAIL
    assert result.failed == (f"vp {DAY}",)
    assert not result.inconclusive     # a missing measure is not a check that did not run


@needs_gx
def test_a_suite_that_failed_without_naming_a_row_is_still_a_failure(tmp_path):
    """An AGGREGATE expectation - one orch 09/10 may well want - fails without an
    unexpected index, so nobody is named. GX's own `success` is what decides the outcome;
    if the named subjects decided it, a failing suite would read as an ok (or, with a row
    held out, as inconclusive) and the failure would vanish."""
    from great_expectations import expectations as gxe

    aggregate = gx.Suite("row-count", "gapcheck", COLUMNS,
                         lambda: [gxe.ExpectTableRowCountToEqual(value=99)])
    path = checks.write(tmp_path, "gapcheck",
                        [gapcheck_row(k, checks.OK) for k in gapfill.KINDS], COLUMNS)
    result = gx.validate(gx.context(tmp_path / "docs"), aggregate, gx.rows(path, COLUMNS))
    assert result.outcome == checks.FAIL
    assert result.failed == ("<gapcheck batch>",)


@needs_gx
def test_an_inconclusive_row_never_makes_an_expectation_fail(tmp_path):
    """The mirror of the test above, and the bug this file actually caught: the held-out
    rows shorten the frame, so an AGGREGATE expectation in the live suite would see four
    kinds instead of five and go red - rendering "could not check" as a failure. Every
    expectation in _completeness() is therefore PER-ROW. Asserted by making one kind
    inconclusive and requiring every expectation to still pass."""
    rows = [gapcheck_row(k, checks.INCONCLUSIVE if k == "alerts" else checks.OK)
            for k in gapfill.KINDS]
    path = checks.write(tmp_path, "gapcheck", rows, COLUMNS)
    suite = declared_suite(LIVE)
    result = gx.validate(gx.context(tmp_path / "docs"), suite,
                         gx.rows(path, COLUMNS, suite.era))
    assert result.failed == () and result.detail == ""


@needs_gx
def test_the_suite_reads_the_producers_verdict_rather_than_recomputing_it(tmp_path):
    """Every threshold keeps exactly ONE home. `gapfill.check()` decides what a gap is
    (`FAIL if fillable or stale else OK`); the suite expects on the verdict it wrote. So a
    row whose measures look clean but whose outcome says FAIL still fails - which is only
    true because the expectation is on `outcome` and not on a copy of that expression."""
    rows = [gapcheck_row(k, checks.FAIL if k == "vp" else checks.OK) for k in gapfill.KINDS]
    path = checks.write(tmp_path, "gapcheck", rows, COLUMNS)   # vp: fillable="", held=24
    assert json.loads(path.read_text().splitlines()[0])["fillable"] == ""
    suite = declared_suite(LIVE)
    result = gx.validate(gx.context(tmp_path / "docs"), suite, gx.rows(path, COLUMNS))
    assert result.failed == (f"vp {DAY}",)


# --- Data Docs: built once, into the one place the publisher reads -------------------------

@needs_gx
def test_data_docs_build_into_the_publish_target_and_are_publishable(tmp_path):
    """cloud 09 froze the target: `<data_root>/gx/data_docs` is what `publish --family docs`
    reads, and the whole tree goes to `docs/**` on the PUBLIC host. So the tree has to
    satisfy the publisher's suffix ALLOWLIST - measured here rather than assumed, because a
    GX version that starts emitting something that is not a web payload would otherwise
    fail in another session at publish time.

    Every DECLARED suite's producer is seeded, so this is the whole green nightly's report
    and not one page of it (orch 09 added three)."""
    every_producer(tmp_path)
    results, docs = gx.run(tmp_path)
    assert docs == tmp_path / "gx" / "data_docs"
    assert (docs / "index.html").is_file()
    items = publish.plan("docs", docs)
    assert items and all(i.key.startswith("docs/") for i in items)
    assert {r.outcome for r in results} == {checks.OK}


def test_the_publisher_accepts_the_font_faces_data_docs_actually_ship(tmp_path):
    """MEASURED on GX 1.21.0, and the reason `.otf` joined the allowlist: a Data Docs site
    ships TEN HK Grotesk `.otf` faces beside its CSS, and cloud 09's list had `.woff` and
    `.woff2` but no OTF - so `make publish FAMILY=docs` refused the whole family on a font.
    Pinned as behaviour over a Docs-shaped tree rather than as the constant's contents, and
    rule 2 is asserted alongside it: a bulk payload in the same tree is still refused."""
    docs = tmp_path / "data_docs"
    (docs / "static" / "fonts").mkdir(parents=True)
    (docs / "index.html").write_text("<html>")
    (docs / "static" / "styles" / "x.css").parent.mkdir(parents=True)
    (docs / "static" / "styles" / "x.css").write_text("@font-face{}")
    (docs / "static" / "fonts" / "HKGrotesk-Regular.otf").write_bytes(b"OTTO")
    keys = [i.key for i in publish.plan("docs", docs)]
    assert "docs/static/fonts/HKGrotesk-Regular.otf" in keys
    assert publish.content_type(Path("x.otf")) == "font/otf"
    (docs / "rows.parquet").write_bytes(b"PAR1")
    with pytest.raises(publish.Refused, match="not a publishable web payload"):
        publish.plan("docs", docs)


def test_the_docs_target_is_the_publishers_own(monkeypatch, tmp_path):
    """Derived, not retyped: the family's src and this module's output directory are the
    same path, so re-homing one without the other cannot happen quietly."""
    monkeypatch.setenv("RAINCHECK_ARCHIVE_ROOT", str(tmp_path))
    assert gx.docs_dir(tmp_path) == publish.FAMILIES["docs"].src()


@needs_gx
def test_the_site_is_rebuilt_each_run_and_never_becomes_a_served_history(tmp_path):
    """`docs/**` is THIS run's report, published wholesale every night - so nothing may
    accumulate in it. This pins a DEPENDENCY's behaviour rather than raincheck code, on
    purpose: `build_data_docs()` rebuilds the whole site, so a suite that STOPS running - a
    rename, a retirement, a producer removed - leaves no page behind. An `rmtree` here was
    written first and then deleted, because it survived every mutation: nothing could
    observe it. If a future GX starts leaving stale pages in a published tree, this is
    where it shows up."""
    full_batch(tmp_path)
    live = declared_suite(LIVE)
    retired = gx.Suite("retired-suite", "gapcheck", COLUMNS, live.expectations, era=live.era)
    gx.run(tmp_path, (live, retired))
    docs = gx.docs_dir(tmp_path)
    assert (docs / "expectations" / "retired-suite.html").is_file()

    gx.run(tmp_path, (live,))
    assert not (docs / "expectations" / "retired-suite.html").exists()
    assert (docs / "expectations" / f"{live.name}.html").is_file()
    assert len([p for p in docs.rglob("*.html") if p.parent.parent.name == "__none__"]) == 1


# --- the stage: a three-part change, and the third outcome's declaration --------------------

def test_the_checkpoint_is_declared_as_a_gate_that_carries_its_own_argv():
    """A GATE, so it never retries - re-reading a batch cannot change a verdict - and so
    orch 07's `skip_rc()` maps its rc 2 onto a `skipped` task, the only terminal state
    Airflow has that is neither success nor failure. The argv is not a preference: GNU make
    exits 2 for ANY recipe failure, so a checkpoint reached through `make` could not tell
    "could not check" from "the recipe broke"."""
    (stage,) = [s for s in daily.STAGES if s.name == "gxcheck"]
    assert stage.retry == "gate" and stage.argv == ("gx",)
    assert not stage.soft            # a red suite is named in the run's own ending
    assert stage.fanout is None


def test_the_checkpoint_runs_after_every_producer_it_expects_on():
    """It reads the batches this run wrote, so it has nothing to say until they exist -
    and the Data Docs are built once, at the end. Asserted against the producers it
    actually reads rather than against a position, so adding a stage after it is fine and
    adding a PRODUCER after it is not."""
    order = [s.name for s in daily.STAGES]
    produces = {s.check for s in gx.SUITES} & set(order)
    assert produces, "the declaration no longer holds a check producer these suites read"
    assert all(order.index(p) < order.index("gxcheck") for p in produces)


def test_the_stage_is_placed_by_the_tables_own_annotation():
    """The pod shape is READ from `raincheck.io/stages` in cloud 03's placement table.
    A stage the table does not name raises in the DAG at parse time, so the annotation and
    the declaration land in one commit or the nightly stops building."""
    import yaml

    listed = set()
    for doc in yaml.safe_load_all(
            (ROOT / "deploy" / "k8s" / "raincheck" / "build.yaml").read_text()):
        if doc and doc.get("kind") == "PodTemplate":
            listed |= {e.split()[0] for e
                       in doc["metadata"]["annotations"]["raincheck.io/stages"].split(",")
                       if e.strip()}
    assert {s.name for s in daily.STAGES} <= listed


def test_no_pipeline_module_imports_great_expectations():
    """It is an OPTIONAL extra. A pipeline module that imported it would make every stage
    on the image depend on it, and `raincheck.gx` itself only imports it INSIDE functions -
    so this module imports, and reports INCONCLUSIVE, on a checkout without it."""
    offenders = []
    for path in sorted((ROOT / "src" / "raincheck").glob("*.py")):
        text = path.read_text()
        if path.name == "gx.py":
            top = [ln for ln in text.splitlines()
                   if ln.startswith(("import great_expectations", "from great_expectations"))]
            assert not top, f"gx.py imports GX at module level: {top}"
            continue
        if "great_expectations" in text:
            offenders.append(path.name)
    assert not offenders, f"pipeline modules importing great_expectations: {offenders}"


def test_the_extra_is_pinned_to_one_major_version():
    """The 0.x and 1.x context/checkpoint APIs differ substantially and this module is
    written against 1.x only, so an unpinned extra would resolve a 2.x someday and the
    nightly would find out in a pod."""
    text = (ROOT / "pyproject.toml").read_text()
    assert 'gx = ["great-expectations>=1,<2"]' in text
    assert '"/opt/raincheck[gx]"' in (ROOT / "docker" / "Dockerfile").read_text()


# --- orchestration 09: the run's batches are a SET -----------------------------------------

def test_a_mapped_stage_writes_one_batch_per_pod_and_the_run_is_their_union(tmp_path):
    """`gapverify` is MAPPED over `kind` since orch 06: five pods, five batches, five
    disjoint subjects, minutes apart. `batch()` answers "the newest stamp", which here is
    whichever kind's pod finished last - so reading it alone would judge one kind and
    report NOTHING about the other four: not a gap, not a could-not-check, just rows that
    were never in the frame. The run's rows are the union, and this is the rule this ticket
    pinned."""
    verify_batch(tmp_path, [verify_row(k, checks.OK) for k in gapfill.KINDS])
    paths = gx.batches(tmp_path, "gapverify")
    assert len(paths) == len(gapfill.KINDS)
    assert gx.batch(tmp_path, "gapverify") == paths[0]      # the head of the same set
    folded = gx.fold(paths, VERIFY, era="day")
    assert {r["kind"] for r in folded} == set(gapfill.KINDS)


def test_last_nights_batch_never_answers_for_this_run(tmp_path):
    """RUN_WINDOW is what makes the set a RUN rather than a history. A pod that did not run
    tonight, leaving last night's `ok` in tonight's frame, is a false OK with a whole feed
    behind it - and it would be invisible, because the row looks exactly like a fresh one.

    The interval here is the NIGHTLY'S OWN - 24 h, `raincheck_daily`'s schedule - and not
    `RUN_WINDOW` shifted by a second: a fixture derived from the constant moves with it, so
    widening the window to a year would leave this green. Asked the other way, the bound is
    the claim: strictly inside a day, and long enough to hold a stage's retries."""
    assert timedelta(hours=1) <= gx.RUN_WINDOW < timedelta(days=1)
    checks.write(tmp_path, "gapverify", [verify_row("vp", checks.OK)], VERIFY,
                 at=AT - timedelta(days=1))
    checks.write(tmp_path, "gapverify", [verify_row("tu", checks.OK)], VERIFY, at=AT)
    assert len(gx.batches(tmp_path, "gapverify")) == 1
    assert {r["kind"] for r in gx.fold(gx.batches(tmp_path, "gapverify"), VERIFY)} == {"tu"}


def test_the_later_stamp_wins_where_one_producer_rechecks_the_same_subject(tmp_path):
    """The other half of the same rule, and the cold mirror's real shape: daily.coldcheck()
    checks, re-pushes and re-checks, so two batches carry the SAME subject. Both are true
    records; the later one is what happened last. Same fold, no special case."""
    checks.write(tmp_path, "coldcheck", [cold_row("vp", checks.FAIL, 4)],
                 cold.CHECK_COLUMNS, at=AT)
    checks.write(tmp_path, "coldcheck", [cold_row("vp", checks.OK, 0)],
                 cold.CHECK_COLUMNS, at=AT + timedelta(minutes=3))
    (row,) = gx.fold(gx.batches(tmp_path, "coldcheck"), cold.CHECK_COLUMNS)
    assert row["outcome"] == checks.OK and row["differing"] == 0


# --- orchestration 09: fill fidelity -------------------------------------------------------

@needs_gx
def test_the_fidelity_band_is_the_modules_and_never_ticket_20s_measured_one(tmp_path):
    """THE TRAP THIS TICKET EXISTS FOR. 0.85-1.2x is a measured RESULT from the backfill
    work; `gapfill.ROW_BAND` / `KEY_BAND` are what `verify()` actually enforces, about an
    order of magnitude looser. A ratio outside the MEASUREMENT and inside the BAND has to
    pass here - a suite that failed it would be the real gate, and what passes would have
    changed with no change to the module and no evidence for it."""
    assert not 0.85 <= 3.0 <= 1.2                                  # outside the measurement
    assert gapfill.ROW_BAND[0] <= 3.0 <= gapfill.ROW_BAND[1]       # inside the enforced band
    assert gapfill.KEY_BAND[0] <= 3.0 <= gapfill.KEY_BAND[1]
    verify_batch(tmp_path, [verify_row(k, checks.OK, row_ratio=3.0, key_ratio=3.0)
                            for k in gapfill.KINDS])
    results, _ = gx.run(tmp_path, (declared_suite("fill-fidelity"),))
    assert results[0].outcome == checks.OK
    assert set(results[0].ok) == set(gapfill.KINDS)


@needs_gx
def test_a_ratio_outside_the_modules_own_band_fails_and_names_the_kind(tmp_path):
    """The other side of the same constant: 20x IS out of ROW_BAND, so the suite fails and
    GX's own unexpected index names which kind - which is what the band expectation buys
    over the verdict alone, on the page a human reads at 06:00."""
    rows = [verify_row(k, checks.OK) for k in gapfill.KINDS]
    rows[1] = verify_row("tu", checks.OK, row_ratio=20.0)
    verify_batch(tmp_path, rows)
    results, _ = gx.run(tmp_path, (declared_suite("fill-fidelity"),))
    assert results[0].outcome == checks.FAIL and results[0].failed == ("tu",)


@needs_gx
def test_a_kind_with_no_pair_anywhere_is_held_out_and_the_short_batch_stays_green(tmp_path):
    """The producer's REAL inconclusive: no filled hour with an archiver hour on the same
    day, so every measure is NULL and `day` is NULL with them. Held out of the frame, kept
    on its own bucket - and the four expectations left looking at four rows instead of five
    all still pass, which is only true because every one of them is PER-ROW."""
    rows = [verify_row(k, checks.OK) for k in gapfill.KINDS]
    rows[2] = verify_row("alerts", checks.INCONCLUSIVE)
    verify_batch(tmp_path, rows)
    results, _ = gx.run(tmp_path, (declared_suite("fill-fidelity"),))
    assert results[0].failed == () and results[0].inconclusive == ("alerts",)
    assert results[0].outcome == checks.INCONCLUSIVE and gx.rc(results) == 2


@needs_gx
def test_a_kind_inconclusive_on_a_day_it_named_is_a_failure_not_a_third_outcome(tmp_path):
    """THE ACCEPTANCE ROW. `verify()` goes INCONCLUSIVE for exactly one reason and NULLs
    every measure when it does, so a row that names a day and still could not judge it is a
    kind that went inconclusive on a day which HAS a comparable pair: the pair-finding
    broke. That is a defect, so it FAILS - and it leaves the could-not-check bucket when it
    does, because a subject cannot be both.

    No expectation can make this claim: the row is held out of the frame before any
    expectation sees it. It is made in the suite's own code, over the whole batch."""
    rows = [verify_row(k, checks.OK) for k in gapfill.KINDS]
    rows[0] = verify_row("vp", checks.INCONCLUSIVE, day=DAY)
    verify_batch(tmp_path, rows)
    results, _ = gx.run(tmp_path, (declared_suite("fill-fidelity"),))
    assert results[0].failed == ("vp",)
    assert "vp" not in results[0].inconclusive and "vp" not in results[0].ok
    assert results[0].outcome == checks.FAIL
    assert "pair-finding broke" in results[0].detail


@needs_gx
def test_a_kind_whose_pod_wrote_no_batch_at_all_is_inconclusive_and_never_ok(tmp_path):
    """Five pods, four batches: the fifth kind was never checked. Nothing in the frame can
    say so - there is no row to be unexpected - so the batch claim says it, as a
    could-not-check and not as a pass."""
    verify_batch(tmp_path, [verify_row(k, checks.OK) for k in gapfill.KINDS[:-1]])
    results, _ = gx.run(tmp_path, (declared_suite("fill-fidelity"),))
    assert results[0].inconclusive == (f"<no batch: {gapfill.KINDS[-1]}>",)
    assert results[0].outcome == checks.INCONCLUSIVE and not results[0].failed


# --- orchestration 09: the cold mirror reports and never gates -----------------------------

@needs_gx
def test_a_mirror_gap_is_reported_and_never_gates_the_nightly(tmp_path):
    """Ticket 18's placement, which this suite does not get to change on the side.
    `daily.coldcheck()` re-pushes once and warns (rc 0) because what survives a re-push is
    the EC2 box's own overlapping capture - different bytes for an object that is PRESENT.
    An expectation on `outcome` here would route that into gx.rc() and out through the
    gxcheck GATE, making GX the hard gate the module deliberately is not. So: the counts
    are reported, and the suite is green."""
    checks.write(tmp_path, "coldcheck",
                 [cold_row("vp", checks.FAIL, 5), cold_row("tu", checks.OK, 0)],
                 cold.CHECK_COLUMNS, at=AT)
    for kind in ("vp", "tu"):
        (tmp_path / "archive" / kind).mkdir(parents=True)
    results, _ = gx.run(tmp_path, (declared_suite("cold-mirror"),))
    assert results[0].outcome == checks.OK and gx.rc(results) == 0
    assert "mirror drift REPORTED, not gated" in results[0].detail and "vp 5" in results[0].detail


@needs_gx
def test_a_judged_cold_row_that_counted_nothing_is_a_failure(tmp_path):
    """`differing` is NULL, never 0, on every could-not-check path - and those rows are not
    in this frame. So a row claiming to have been judged while carrying no count is a
    producer that started publishing a measurement it never took. The not-null is the only
    thing in front of it: a between-expectation counts nulls as MISSING and succeeds."""
    (tmp_path / "archive" / "vp").mkdir(parents=True)
    checks.write(tmp_path, "coldcheck", [cold_row("vp", checks.OK, None)],
                 cold.CHECK_COLUMNS, at=AT)
    results, _ = gx.run(tmp_path, (declared_suite("cold-mirror"),))
    assert results[0].outcome == checks.FAIL and results[0].failed == ("vp",)


@needs_gx
def test_every_archive_prefix_has_a_row_or_the_mirror_was_never_asked(tmp_path):
    """ONE ROW PER TOP-LEVEL `archive/` PREFIX, read off disk through `cold.kinds()` - the
    producer's own function, so the row set grows with a new kind instead of being pinned
    to five names in a suite. A prefix with no row is a slice of Bronze nobody compared,
    which is a false OK with a whole feed behind it, and it is a claim about a MISSING row -
    no expectation can be asked about one."""
    for kind in ("vp", "subway_tu"):
        (tmp_path / "archive" / kind).mkdir(parents=True)
    checks.write(tmp_path, "coldcheck", [cold_row("vp", checks.OK, 0)],
                 cold.CHECK_COLUMNS, at=AT)
    results, _ = gx.run(tmp_path, (declared_suite("cold-mirror"),))
    assert results[0].failed == ("<no row: subway_tu>",)
    assert results[0].outcome == checks.FAIL


@needs_gx
def test_a_remote_that_was_never_listed_is_could_not_check_and_never_clean(tmp_path):
    """The unconfigured / aws-non-zero paths: every row INCONCLUSIVE with a NULL count.
    They are all held out, so nothing is judged - and a suite with nothing judged is not a
    pass. rc 2, which on the gxcheck gate is a `skipped` task rather than a red one."""
    (tmp_path / "archive" / "vp").mkdir(parents=True)
    checks.write(tmp_path, "coldcheck", [cold_row("vp", checks.INCONCLUSIVE, None)],
                 cold.CHECK_COLUMNS, at=AT)
    results, _ = gx.run(tmp_path, (declared_suite("cold-mirror"),))
    assert results[0].outcome == checks.INCONCLUSIVE and not results[0].ok
    assert results[0].inconclusive == ("vp",) and gx.rc(results) == 2


# --- orchestration 09: schema eras ---------------------------------------------------------

@needs_gx
def test_a_reader_that_dropped_an_era_column_is_named_by_column_presence(tmp_path):
    """A reader that forgets to union fails SILENTLY, with the ROW COUNT still correct - so
    the check asserts the columns are PRESENT and this suite expects on that, never on a
    count. `missing` is the producer's own rendering of it and `outcome` is its verdict."""
    rows = [eras_row(r, k, checks.OK) for r in eras.READERS for k in eras.ERA_COLS]
    rows[0] = eras_row("duck", "vp", checks.FAIL, missing="header_ts")
    eras_batch(tmp_path, rows)
    results, _ = gx.run(tmp_path, (declared_suite("schema-eras"),))
    assert results[0].outcome == checks.FAIL and results[0].failed == ("duck vp",)


@needs_gx
def test_four_rows_every_run_is_a_batch_claim_and_never_an_expectation(tmp_path):
    """Every declared (reader, kind) pair gets a row on EVERY path, inconclusive included -
    so a short batch is a reader nobody looked at, not one that could not check. The four
    are the product of `eras.READERS` and `eras.ERA_COLS`, read from the module, so a fifth
    reader is covered the day it is declared."""
    want = {f"{r} {k}" for r in eras.READERS for k in eras.ERA_COLS}
    assert len(want) == 4
    eras_batch(tmp_path, [eras_row(r, k, checks.OK) for r in eras.READERS
                          for k in eras.ERA_COLS][:-1])
    results, _ = gx.run(tmp_path, (declared_suite("schema-eras"),))
    assert results[0].outcome == checks.FAIL
    assert results[0].failed == ("<no row: spark tu>",)


@needs_gx
def test_a_day_of_null_is_could_not_check_and_must_not_read_as_a_pass(tmp_path):
    """No date dir mixed part schemas, so a union reader is indistinguishable from a narrow
    one and the run proved nothing. Same false-OK class as gapverify with no pair: held
    out, reported as its own bucket, never green."""
    eras_batch(tmp_path, [eras_row(r, k, checks.INCONCLUSIVE, missing=None, day=None)
                          for r in eras.READERS for k in eras.ERA_COLS])
    results, _ = gx.run(tmp_path, (declared_suite("schema-eras"),))
    assert results[0].outcome == checks.INCONCLUSIVE and not results[0].ok
    assert len(results[0].inconclusive) == 4 and gx.rc(results) == 2


# --- orchestration 09: the declaration -----------------------------------------------------

def test_the_three_suites_are_appended_and_expect_on_their_producers_own_columns():
    """Adding a suite is appending one `Suite` and nothing else. Each names a producer that
    exists and carries THAT producer's own CHECK_COLUMNS constant, never a literal list -
    the batch is asserted against it on read, so a producer that changes shape is a loud
    refusal here rather than a suite quietly expecting on columns that moved."""
    mine = {"fill-fidelity": ("gapverify", gapfill.CHECK_COLUMNS["gapverify"]),
            "cold-mirror": ("coldcheck", cold.CHECK_COLUMNS),
            "schema-eras": ("eras", eras.CHECK_COLUMNS)}
    for name, (check, columns) in mine.items():
        suite = declared_suite(name)
        assert (suite.check, suite.columns) == (check, columns)
        assert " " not in suite.name          # a Data Docs page and a URL segment
    names = [s.name for s in gx.SUITES]
    assert len(names) == len(set(names)), f"two suites share a name: {names}"


def test_the_era_check_is_declared_where_its_batch_can_be_read_this_run():
    """This ticket's placement call. `eras` PRODUCES a check batch, so it stands in front of
    the one stage that reads batches; it READS Bronze, so it stands behind the one stage
    that writes any. And it is a GATE with an argv: both of its non-verdicts are
    INCONCLUSIVE - no mixed-schema day, or no JVM on this box - and `make` exits 2 for any
    recipe failure, which would flatten that into "the recipe broke"."""
    order = [s.name for s in daily.STAGES]
    (stage,) = [s for s in daily.STAGES if s.name == "eras"]
    assert stage.retry == "gate" and stage.argv == ("eras",) and not stage.soft
    assert stage.fanout is None and stage.reduces is None
    assert order.index("gapfill") < order.index("eras") < order.index("gxcheck")


# --- orchestration 10: the two NON-nightly suites -------------------------------------------
#
# Both expect on data that CANNOT CHANGE - the closed backfill era, and a reference registry
# that cannot even be rebuilt here - so neither is in the nightly declaration and neither is
# a DAG stage. Their rc therefore never reaches a task state at all (orch 07), which makes
# the persisted ROW the only record and these suites the only thing that reads it.

BACKFILL_COLUMNS = gx.BACKFILL.CHECK_COLUMNS
LO, HI = "2026-03-01", "2026-08-14"        # the backfill era: it ENDS the day before START
REF_COLUMNS = ref_canary.CHECK_COLUMNS
CENSUS, CANARIES = "backfill-census", "ref-canaries"


def backfill_row(feed: str, outcome: str, **over) -> checks.Row:
    """One census-shaped row, mirroring `backfill-verify.py`'s own two shapes: its `base`
    dict NULLs every measure and the judged path fills them. `hours_want` is filled on both
    paths there, so it is filled on both here."""
    base = {"feed": feed, "lo": LO, "hi": HI, "hours_seen": None, "hours_want": 4008,
            "dead": None, "missing": None, "no_part": None, "no_marker": None,
            "zero_byte": None, "stale_dead": None}
    if outcome != checks.INCONCLUSIVE:
        base |= {"hours_seen": 4008, "dead": 0, "missing": 0, "no_part": 0,
                 "no_marker": 0, "zero_byte": 0, "stale_dead": 0}
    return checks.Row(gx.BACKFILL.CHECK, feed, outcome, "", base | over)


def backfill_batch(root: Path, rows: list[checks.Row] | None = None) -> Path:
    rows = rows if rows is not None else [backfill_row(f, checks.OK)
                                          for f in gx.BACKFILL.FEEDS]
    return checks.write(root, gx.BACKFILL.CHECK, rows, BACKFILL_COLUMNS, at=AT)


def canary_row(subject: str, outcome: str, got: str | None = "1",
               want: str | None = "1") -> checks.Row:
    if outcome == checks.INCONCLUSIVE:
        got = want = None
    return checks.Row(ref_canary.CHECK, subject, outcome, "", {"got": got, "want": want})


def canary_batch(root: Path, rows: list[checks.Row] | None = None) -> Path:
    rows = rows if rows is not None else [canary_row(s, checks.OK)
                                          for s in ref_canary.subjects()]
    return checks.write(root, ref_canary.CHECK, rows, REF_COLUMNS, at=AT)


# --- the census: era=None, and it is a requirement rather than an omission ------------------

def test_the_backfill_census_carries_no_era_because_it_is_the_other_era(tmp_path):
    """THE MUST ON THIS TICKET, and it is asserted the only way that can fail loudly: not by
    reading `era is None` alone - which a mutation could satisfy by moving ERA_START - but by
    PROVING that an era column would refuse this batch outright.

    `ERA_START` is `gapfill.START` and the backfill range ends the DAY BEFORE, so `era="lo"`
    would refuse every row of every run, with a message telling the reader to go and look at
    the census that produced them. This check IS the other era. orch 08's live-capture suite
    must never be pointed at this range, and this suite must never inherit that boundary."""
    assert declared_suite(CENSUS).era is None
    path = backfill_batch(tmp_path)
    assert gx.rows(path, BACKFILL_COLUMNS)                      # no era: read fine
    for column in ("lo", "hi"):
        assert HI < gx.ERA_START and LO < gx.ERA_START
        with pytest.raises(ValueError, match="before the live-capture era"):
            gx.rows(path, BACKFILL_COLUMNS, era=column)


def test_the_census_reads_the_scripts_own_columns_and_feeds(tmp_path):
    """`scripts/backfill-verify.py` is a SCRIPT, not a package module - orch 03 kept the two
    eras' tools apart and a test asserts its DEAD list is disjoint from `gapfill.DEAD`. So
    the suite loads it by path rather than re-homing its constants, and what it declares is
    the script's own: the feeds are NOT `gapfill.KINDS`, which is the separation itself."""
    suite = declared_suite(CENSUS)
    assert (suite.check, suite.columns) == ("backfill", gx.BACKFILL.CHECK_COLUMNS)
    assert set(gx.BACKFILL.FEEDS) != set(gapfill.KINDS)
    assert gx.BACKFILL.DEAD and not set(gx.BACKFILL.DEAD) & set(gapfill.DEAD)


@needs_gx
def test_a_complete_census_is_ok_and_the_range_rides_out_in_the_detail(tmp_path):
    """A clean chunk: every declared feed judged, nothing missing, rc 0. The RANGE is
    reported rather than gated - `fold()` unions every batch inside RUN_WINDOW, so a reader
    has to be told which chunk these rows are about."""
    backfill_batch(tmp_path)
    results, _ = gx.run(tmp_path, (declared_suite(CENSUS),))
    assert results[0].outcome == checks.OK and gx.rc(results) == 0
    assert set(results[0].ok) == set(gx.BACKFILL.FEEDS)
    assert f"{LO}..{HI}" in results[0].detail


@needs_gx
def test_the_census_verdict_is_expected_on_rather_than_recomputed(tmp_path):
    """Every threshold keeps ONE home. The census decides what a complete range is; this
    expects the verdict it wrote. So a row whose measures are all perfectly clean and whose
    OUTCOME says fail still fails - which is only true because the expectation is on
    `outcome` and not on a copy of `not (missing or no_part or ... )`."""
    rows = [backfill_row(f, checks.OK) for f in gx.BACKFILL.FEEDS]
    rows[0] = backfill_row(gx.BACKFILL.FEEDS[0], checks.FAIL)      # every count still 0
    backfill_batch(tmp_path, rows)
    results, _ = gx.run(tmp_path, (declared_suite(CENSUS),))
    assert results[0].outcome == checks.FAIL
    assert results[0].failed == (gx.BACKFILL.FEEDS[0],)


@needs_gx
def test_a_zero_byte_part_fails_even_where_the_census_called_the_feed_ok(tmp_path):
    """THE TICKET'S ZERO-BYTE RULE. An object can exist and still be useless, and a
    zero-byte part counted as present would verify the range OK - the same false-OK that
    makes `gapverify` useless over this era.

    The row here says `ok` WHILE carrying a zero-byte part, which is the census contradicting
    itself, and isolating it that way is the whole point: with `outcome` set to fail as well,
    this test passed with the zero-byte expectation DELETED - the verdict expectation was
    failing the row and this one proved nothing. Measured by the mutation probe, and it is
    the degenerate-fixture rule applied to a suite: check the fixture is not already failing
    for the reason you are not testing."""
    rows = [backfill_row(f, checks.OK) for f in gx.BACKFILL.FEEDS]
    rows[1] = backfill_row(gx.BACKFILL.FEEDS[1], checks.OK, zero_byte=2)
    backfill_batch(tmp_path, rows)
    results, _ = gx.run(tmp_path, (declared_suite(CENSUS),))
    assert results[0].outcome == checks.FAIL
    assert results[0].failed == (gx.BACKFILL.FEEDS[1],)


@needs_gx
def test_an_empty_gapfill_marker_is_not_a_zero_byte_part(tmp_path):
    """The other half of the same rule, and the half a suite must not re-implement: an empty
    `_gapfill` MARKER is legitimately zero bytes and is counted as a marker, never as a
    part. That exemption is a property of the producer (pinned in
    `tests/test_check_producers.py`); here it shows up as a feed whose markers are present
    and whose `zero_byte` is 0, and the suite is green."""
    backfill_batch(tmp_path, [backfill_row(f, checks.OK, no_marker=0, zero_byte=0)
                              for f in gx.BACKFILL.FEEDS])
    results, _ = gx.run(tmp_path, (declared_suite(CENSUS),))
    assert results[0].outcome == checks.OK


@needs_gx
def test_a_stale_dead_entry_fails_the_feed_that_owns_the_allowlist(tmp_path):
    """THE TICKET'S DEAD-HOUR-LIST RULE. A listed dead hour that turned up after all means
    the allowlist is WRONG, and a wrong allowlist HIDES REAL GAPS - which is why this is
    failed rather than reported. The list itself stays inside the census script, one home,
    disjoint from `gapfill.DEAD` by a test of its own.

    The row says `ok` AND carries the stale entry, for the same isolation reason as the
    zero-byte test above: with `outcome` failing too, this passed with the expectation
    deleted."""
    rows = [backfill_row(f, checks.OK) for f in gx.BACKFILL.FEEDS]
    rows[0] = backfill_row(gx.BACKFILL.FEEDS[0], checks.OK, stale_dead=1)   # ok, and stale
    backfill_batch(tmp_path, rows)
    results, _ = gx.run(tmp_path, (declared_suite(CENSUS),))
    assert results[0].outcome == checks.FAIL
    assert results[0].failed == (gx.BACKFILL.FEEDS[0],)


@needs_gx
def test_a_feed_whose_listing_failed_is_held_out_and_the_short_batch_stays_green(tmp_path):
    """The census's real INCONCLUSIVE: the remote listing itself failed, so that run proves
    NOTHING about that feed's range and every measure is NULL. Held out of the frame, kept
    in its own bucket - and the seven expectations, now looking at two rows instead of
    three, all still pass. That is only true because every one of them is PER-ROW: an
    aggregate here would see the short batch and go red, rendering could-not-check as a
    failure (orch 08 measured exactly that)."""
    rows = [backfill_row(f, checks.OK) for f in gx.BACKFILL.FEEDS]
    rows[2] = backfill_row(gx.BACKFILL.FEEDS[2], checks.INCONCLUSIVE)
    backfill_batch(tmp_path, rows)
    results, _ = gx.run(tmp_path, (declared_suite(CENSUS),))
    assert results[0].failed == () and results[0].detail.count("expect") == 0
    assert results[0].inconclusive == (gx.BACKFILL.FEEDS[2],)
    assert results[0].outcome == checks.INCONCLUSIVE and gx.rc(results) == 2


@needs_gx
def test_a_judged_feed_that_counted_no_hours_fails_rather_than_passing_quietly(tmp_path):
    """NULL is the could-not-check convention and those rows are not in this frame, so a row
    claiming to have been judged while carrying no `hours_seen` is a producer that started
    publishing a measurement it never took. The not-null is the only thing in front of it:
    an in-set expectation IGNORES nulls and succeeds without them, which is why every count
    claim in this suite is PAIRED with one."""
    rows = [backfill_row(f, checks.OK) for f in gx.BACKFILL.FEEDS]
    rows[0] = backfill_row(gx.BACKFILL.FEEDS[0], checks.OK, hours_seen=None)  # only this one
    backfill_batch(tmp_path, rows)
    results, _ = gx.run(tmp_path, (declared_suite(CENSUS),))
    assert results[0].outcome == checks.FAIL
    assert results[0].failed == (gx.BACKFILL.FEEDS[0],)
    assert not results[0].inconclusive     # a vanished measure is not a check that did not run


@needs_gx
def test_a_feed_with_no_row_at_all_is_could_not_check_and_never_ok(tmp_path):
    """ONE ROW PER FEED - the census's own contract, and a claim no expectation can make,
    because the row is not there to be unexpected. INCONCLUSIVE rather than FAIL, and the
    `--feeds vp,tu` form is what decides that: censusing a subset on purpose is a legitimate
    run, and the honest report of the feed it never asked about is "could not check"."""
    backfill_batch(tmp_path, [backfill_row(f, checks.OK) for f in gx.BACKFILL.FEEDS[:-1]])
    results, _ = gx.run(tmp_path, (declared_suite(CENSUS),))
    assert results[0].inconclusive == (f"<no row: {gx.BACKFILL.FEEDS[-1]}>",)
    assert results[0].outcome == checks.INCONCLUSIVE and not results[0].failed


@needs_gx
def test_an_undeclared_feed_in_the_census_batch_is_failed(tmp_path):
    """The value_set is the script's own `FEEDS`. A batch that grew a subject the census
    never declared is a range nobody agreed to check, and it must not ride in green."""
    rows = [backfill_row(f, checks.OK) for f in gx.BACKFILL.FEEDS]
    rows.append(backfill_row("subway_vp", checks.OK))
    backfill_batch(tmp_path, rows)
    results, _ = gx.run(tmp_path, (declared_suite(CENSUS),))
    assert results[0].outcome == checks.FAIL and results[0].failed == ("subway_vp",)


# --- the reference canaries: expect THROUGH the code canary --------------------------------

@needs_gx
def test_a_clean_canary_batch_is_ok_and_publishes_the_identity(tmp_path):
    """Every declared canary green. The identity's VALUE rides out in the detail, which is
    the whole job of that row: nothing in this repo persists a counterpart to compare it
    against, so it exists to be READ - beside the counts that would have moved with it."""
    canary_batch(tmp_path, [canary_row(s, checks.OK) for s in ref_canary.subjects()
                            if s != ref_canary.IDENTITY]
                 + [canary_row(ref_canary.IDENTITY, checks.OK, got="d3c7b0f3", want=None)])
    results, _ = gx.run(tmp_path, (declared_suite(CANARIES),))
    assert results[0].outcome == checks.OK and gx.rc(results) == 0
    assert f"{ref_canary.IDENTITY} d3c7b0f3" in results[0].detail


@needs_gx
def test_a_moved_frozen_count_fails_through_the_canarys_own_verdict(tmp_path):
    """THE TICKET'S RULE. The count lives in `ref.ASSETS_EXPECT`, `ref_canary` compares the
    built table against it, and this suite expects on the VERDICT that comparison wrote -
    which is why a row whose `got` and `want` are both perfectly well-formed still fails
    when its outcome says so. Re-typing the number here would have made the SUITE the
    canary, and the two copies would disagree the first time the registry legitimately
    moved."""
    subject = next(s for s in ref_canary.subjects() if s.startswith("count "))
    rows = [canary_row(s, checks.FAIL if s == subject else checks.OK)
            for s in ref_canary.subjects()]
    assert [r.subject for r in rows].count(subject) == 1     # the row really is in the batch
    canary_batch(tmp_path, rows)
    results, _ = gx.run(tmp_path, (declared_suite(CANARIES),))
    assert results[0].outcome == checks.FAIL and results[0].failed == (subject,)


@needs_gx
def test_a_root_with_no_registry_is_could_not_check_and_never_clean(tmp_path):
    """The COMMON case, not an edge: a worktree, a fresh checkout and every task pod have no
    `ref/assets`, so every canary is INCONCLUSIVE with NULL measures. They are all held out,
    nothing is judged, and a suite with nothing judged is not a pass."""
    canary_batch(tmp_path, [canary_row(s, checks.INCONCLUSIVE)
                            for s in ref_canary.subjects()])
    results, _ = gx.run(tmp_path, (declared_suite(CANARIES),))
    assert results[0].outcome == checks.INCONCLUSIVE and not results[0].ok
    assert len(results[0].inconclusive) == len(ref_canary.subjects())
    assert gx.rc(results) == 2


@needs_gx
def test_a_judged_canary_that_measured_nothing_fails(tmp_path):
    """A canary that ran and recorded no measurement is a producer bug, not a third outcome.
    The not-null is on `got` ALONE, because `want` is legitimately NULL on the identity row -
    which is asserted in the same batch here, so a not-null wrongly added to `want` would
    turn this test red rather than passing unnoticed."""
    rows = [canary_row(s, checks.OK) for s in ref_canary.subjects()
            if s != ref_canary.IDENTITY]
    rows.append(canary_row(ref_canary.IDENTITY, checks.OK, got="d3c7b0f3", want=None))
    rows[0] = canary_row(rows[0].subject, checks.OK, got=None)
    canary_batch(tmp_path, rows)
    results, _ = gx.run(tmp_path, (declared_suite(CANARIES),))
    assert results[0].outcome == checks.FAIL and results[0].failed == (rows[0].subject,)


@needs_gx
def test_a_canary_that_never_ran_is_a_missing_row_and_not_a_pass(tmp_path):
    """The batch-level claim: `ref_canary.subjects()` is the declaration, derived from
    `ref.ASSETS_EXPECT` and the two key tables, so a canary frozen tomorrow is covered the
    day it lands. A canary with no row was not run, and no expectation can be asked about a
    row that does not exist."""
    missing = ref_canary.subjects()[0]
    canary_batch(tmp_path, [canary_row(s, checks.OK) for s in ref_canary.subjects()[1:]])
    results, _ = gx.run(tmp_path, (declared_suite(CANARIES),))
    assert results[0].inconclusive == (f"<no canary: {missing}>",)
    assert results[0].outcome == checks.INCONCLUSIVE and not results[0].failed


# --- the declaration and the two triggers --------------------------------------------------

def test_neither_suite_is_in_the_nightly_declaration_or_the_stage_graph():
    """THE TICKET. `gxcheck` runs `SUITES` and nothing else, so appending these there would
    have made both of them nightly - and a nightly check over data that cannot change
    re-answers a settled question every morning, off whatever batch last landed (`batches()`
    takes the newest `run=` stamp and asks no question about its age). Neither producer is a
    stage either, which is orch 07's point: their rc never reaches a task state at all, so
    the persisted ROW is the only record there is."""
    nightly = {s.name for s in gx.SUITES}
    assert {CENSUS, CANARIES} & nightly == set()
    assert {s.name for s in gx.NON_NIGHTLY} == {CENSUS, CANARIES}
    assert gx.DECLARED == gx.SUITES + gx.NON_NIGHTLY
    stages = {s.name for s in daily.STAGES}
    assert {s.check for s in gx.NON_NIGHTLY} & stages == set()


def test_no_two_declared_suites_share_a_name():
    """Every name is a Data Docs page and a URL segment. Three tickets have appended to these
    tuples across two waves, so the check is over DECLARED rather than over either half."""
    names = [s.name for s in gx.DECLARED]
    assert len(names) == len(set(names)), f"two suites share a name: {names}"
    assert all(" " not in n for n in names)


def test_each_non_nightly_suite_has_a_make_target_that_names_it():
    """THE TRIGGER HALF OF THIS TICKET, and it is derived rather than mirrored: the expected
    command line is computed from the declaration, so renaming a suite without moving its
    target goes red here instead of leaving a `make` recipe pointed at a name that no longer
    resolves. `make` targets and not stages, and Mac-runnable: these fire on the event that
    could have moved the data, never on a schedule."""
    makefile = (ROOT / "Makefile").read_text()
    for suite in gx.NON_NIGHTLY:
        assert f"-m raincheck.gx {suite.name}" in makefile, suite.name
    assert "-m raincheck.ref_canary" in makefile        # the ref canary's own producer
    for target in ("gxbackfill:", "gxref:", "refcanary:"):
        assert f"\n{target}" in makefile


def test_an_unknown_suite_name_is_refused_and_the_declared_ones_are_listed():
    """A typo in a `make` recipe must not silently run nothing, and it must not run the
    NIGHTLY set either - which is what a fall-through default would do."""
    assert gx.by_name(CENSUS) is declared_suite(CENSUS)
    with pytest.raises(SystemExit, match="no suite named"):
        gx.by_name("backfill")                          # the CHECK name, not the suite's


@needs_gx
def test_a_named_run_renders_its_own_site_and_leaves_the_published_tree_alone(
        tmp_path, monkeypatch):
    """THE CLOBBER GUARD. `build_data_docs()` rebuilds the WHOLE site (orch 08 measured it,
    and deleted an `rmtree` for it), so a named run writing into `<root>/gx/data_docs` would
    DELETE last night's pages from the exact tree `make publish FAMILY=docs` sends to the
    public host - replacing the nightly's report with one page, on the strength of someone
    running `make gxbackfill` at noon. Each named run therefore renders into its own
    directory, and the nightly's is left untouched here to prove it."""
    monkeypatch.setenv("RAINCHECK_ARCHIVE_ROOT", str(tmp_path))
    full_batch(tmp_path)
    gx.run(tmp_path, (declared_suite(LIVE),))           # last night, in the published tree
    assert (gx.docs_dir(tmp_path) / "expectations" / f"{LIVE}.html").is_file()

    backfill_batch(tmp_path)
    with pytest.raises(SystemExit) as exc:
        gx.main([CENSUS])
    assert exc.value.code == 0
    assert (tmp_path / "gx" / f"docs-{CENSUS}" / "index.html").is_file()
    assert (gx.docs_dir(tmp_path) / "expectations" / f"{LIVE}.html").is_file()
    assert not (gx.docs_dir(tmp_path) / "expectations" / f"{CENSUS}.html").exists()


@needs_gx
def test_the_no_argument_form_is_the_nightly_and_publishes_into_the_docs_family(
        tmp_path, monkeypatch, capsys):
    """The other direction: `daily.STAGES`' gxcheck carries `argv=("gx",)` and so reaches
    this form. It runs the nightly declaration into the `docs` family's own source, and the
    printed line says so - a named run prints that it published nothing, because only this
    tree is a family."""
    monkeypatch.setenv("RAINCHECK_ARCHIVE_ROOT", str(tmp_path))
    every_producer(tmp_path)
    with pytest.raises(SystemExit) as exc:
        gx.main([])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert str(gx.docs_dir(tmp_path)) in out and "FAMILY=docs" in out
    assert len([ln for ln in out.splitlines() if ln.startswith("OK")]) == len(gx.SUITES)


def test_more_than_one_suite_name_is_refused_rather_than_sharing_a_site():
    """Two named suites in one run would have to share one Data Docs directory, and the
    second would rebuild the site over the first. Refused at the argument instead."""
    with pytest.raises(SystemExit, match="one suite name at most"):
        gx.main([CENSUS, CANARIES])
