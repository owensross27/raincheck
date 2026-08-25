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
from pathlib import Path

import pytest

from raincheck import checks, daily, gapfill, gx, publish

ROOT = Path(__file__).parents[1]
needs_gx = pytest.mark.skipif(not gx.available(), reason="great_expectations not installed "
                                                         "(optional extra: pip install -e '.[gx]')")
COLUMNS = gapfill.CHECK_COLUMNS["gapcheck"]
DAY = "2026-08-20"


def gapcheck_row(kind: str, outcome: str, day: str = DAY, held: int = 24, **over) -> checks.Row:
    """One gapcheck-shaped row. An INCONCLUSIVE one carries NULL measures, never zeros -
    the convention the whole third outcome rests on."""
    measures = {"kind": kind, "day": day, "hours_held": held,
                "fillable": "", "dead": "", "stale_dead": ""}
    if outcome == checks.INCONCLUSIVE:
        measures = {"kind": kind} | dict.fromkeys(
            (c for c in COLUMNS[len(checks.CORE):] if c != "kind"))
    return checks.Row("gapcheck", f"{kind} {day}", outcome, "", measures | over)


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
    false-OK the check vocabulary was built to kill."""
    assert gx.batch(tmp_path, "gapcheck") is None
    result = gx.Result("s", "gapcheck", inconclusive=("<no batch>",))
    assert result.outcome == checks.INCONCLUSIVE
    assert gx.rc([result]) == 2


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
    (suite,) = gx.SUITES
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
    (suite,) = gx.SUITES
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
    (suite,) = gx.SUITES
    result = gx.validate(gx.context(tmp_path / "docs"), suite, gx.rows(path, COLUMNS))
    assert result.outcome == checks.FAIL
    assert result.failed == (f"subway_vp {DAY}",)


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
    (suite,) = gx.SUITES
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
    (suite,) = gx.SUITES
    result = gx.validate(gx.context(tmp_path / "docs"), suite, gx.rows(path, COLUMNS))
    assert result.failed == (f"vp {DAY}",)


# --- Data Docs: built once, into the one place the publisher reads -------------------------

@needs_gx
def test_data_docs_build_into_the_publish_target_and_are_publishable(tmp_path):
    """cloud 09 froze the target: `<data_root>/gx/data_docs` is what `publish --family docs`
    reads, and the whole tree goes to `docs/**` on the PUBLIC host. So the tree has to
    satisfy the publisher's suffix ALLOWLIST - measured here rather than assumed, because a
    GX version that starts emitting something that is not a web payload would otherwise
    fail in another session at publish time."""
    full_batch(tmp_path)
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
    """`docs/**` is THIS run's report. A timestamped validation page per run would
    otherwise pile up in a tree that is published wholesale every night - the same "no
    served history" rule cloud 09 wrote for the live family, read across."""
    full_batch(tmp_path)
    gx.run(tmp_path)
    docs = gx.docs_dir(tmp_path)
    (stale,) = [p for p in docs.rglob("*.html") if p.parent.parent.name == "__none__"]
    gx.run(tmp_path)
    assert not stale.exists()
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
    produces = {"gapcheck", "coldcheck"} & set(order)
    assert produces, "the declaration no longer holds a check producer this suite reads"
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
