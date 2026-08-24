"""Orchestration ticket 02: the check-result row vocabulary - the aggregation rule, the
payload ban and the per-run batch on disk."""
import json

import pytest

from raincheck import checks


def row(outcome, check="t", subject="s", **measures):
    return checks.Row(check, subject, outcome, "", measures)


@pytest.mark.parametrize("outcomes,expected", [
    ([], 0),
    (["ok"], 0),
    (["ok", "ok"], 0),
    (["inconclusive"], 2),
    (["ok", "inconclusive"], 2),
    (["fail"], 1),
    (["ok", "fail"], 1),
    # the whole point of the rule: a known gap outranks a not-run check, so an
    # inconclusive beside a failure is still 1 and never masks it.
    (["inconclusive", "fail"], 1),
    (["fail", "inconclusive", "ok"], 1),
])
def test_aggregation_rule(outcomes, expected):
    assert checks.rc([row(o) for o in outcomes]) == expected


def test_an_unknown_outcome_is_not_representable():
    """Two-valued thinking is how INCONCLUSIVE got flattened five times; a typo'd third
    value would flatten it again, silently aggregating to 0."""
    with pytest.raises(AssertionError):
        checks.Row("t", "s", "OK")


def test_write_persists_one_jsonl_per_run_and_pins_the_column_set(tmp_path):
    cols = checks.CORE + ("kind", "n")
    rows = [row("ok", kind="vp", n=3), row("fail", kind="tu", n=0)]
    out = checks.write(tmp_path, "t", rows, cols)
    assert out.parent == tmp_path / "checks" / "check=t" and out.name.startswith("run=")
    back = [json.loads(x) for x in out.read_text().splitlines()]
    assert [tuple(b) for b in back] == [cols, cols]
    assert [b["outcome"] for b in back] == ["ok", "fail"]


def test_write_refuses_a_row_that_drifted_from_the_declared_columns(tmp_path):
    with pytest.raises(AssertionError, match="declared"):
        checks.write(tmp_path, "t", [row("ok", kind="vp")], checks.CORE + ("kind", "n"))


def test_write_refuses_a_non_scalar_measure(tmp_path):
    """A list or a table is how feed payload would arrive in a batch GX publishes."""
    with pytest.raises(AssertionError, match="non-scalar"):
        checks.write(tmp_path, "t", [row("ok", hours=["01", "02"])], checks.CORE + ("hours",))
