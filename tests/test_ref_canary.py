"""The reference canaries as check rows (orchestration ticket 10).

The claim this file exists for: the canaries `ref.py` already enforces at BUILD time keep
exactly ONE home, and this producer only RUNS them read-side. So the frozen counts are
never retyped (there is a test for that, over the source text), the key-stability diff is
`ref.assets_key_diff` and not a second set expression, and a root with no registry reports
the third outcome rather than a pass.

Offline throughout, on a planted three-row registry: `ref/assets` cannot be rebuilt here
(`make picks` is 401-blocked), which is exactly why this producer censuses rather than
builds - and why every test below plants its own table instead of touching the real root.
"""
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raincheck import checks, ref, ref_canary

SRC = Path(__file__).parents[1] / "src" / "raincheck"

# A registry small enough to read, with the frozen constant that matches it. Two `cell`
# rows, ONE of them scored, so `cells_scored` is not the same number as `cell` - the two
# would be indistinguishable on a fixture where every Cell is scored, which is the
# degenerate-fixture trap this project keeps re-learning.
ASSETS = [("stn:1", "complex", True), ("cell:a", "cell", True), ("cell:b", "cell", False)]
EXPECT = {"complex": 1, "cell": 2, "total": 3, "cells_scored": 1}


def write_assets(root: Path, rows=ASSETS) -> Path:
    """A `ref/assets` part file. `lat`/`lon` are here because `ref.assets_version` reads
    them: the identity is over (asset_id, kind, lat, lon), the same tuple the key-stability
    contract is keyed on."""
    out = root / "ref" / "assets" / "part-00000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({
        "asset_id": [r[0] for r in rows], "kind": [r[1] for r in rows],
        "scored": [r[2] for r in rows],
        "lat": [40.7 + i / 1000 for i, _ in enumerate(rows)],
        "lon": [-73.9 - i / 1000 for i, _ in enumerate(rows)]}), out)
    return out


def write_derived(root: Path, table: str, asset_ids: list[str]) -> Path:
    out = root.joinpath(*table.split("/")) / "part-00000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"asset_id": asset_ids}), out)
    return out


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """The planted registry plus the frozen constant it should satisfy. Patching
    `ASSETS_EXPECT` rather than writing 20,544 rows is the same escape `ref.build_assets`
    already offers its own tests (`expect=None`); what is under test here is the
    COMPARISON, and the real numbers are asserted to be absent from this ticket's code."""
    monkeypatch.setattr(ref, "ASSETS_EXPECT", EXPECT)
    write_assets(tmp_path)
    return tmp_path


def by_subject(rows) -> dict[str, checks.Row]:
    return {r.subject: r for r in rows}


# --- the census -----------------------------------------------------------------------

def test_a_registry_that_matches_the_frozen_counts_is_ok_on_every_canary(registry):
    """Every declared canary emits a row, all of them green, rc 0. `cells_scored` counts
    the SCORED cell rows and not the cell rows, which is `build_assets`' own arithmetic:
    every Cell row is written `scored=cell in scored_cells`.

    BOTH derived tables are planted, because a green census needs them: without them the
    orphan question was never asked and those two rows are honestly INCONCLUSIVE (the test
    below). A fixture that skipped them would make "all green" mean "all green except the
    two rows I did not look at"."""
    for table in ref_canary.KEY_TABLES:
        write_derived(registry, table, ["stn:1"])
    rows = ref_canary.census(registry)
    assert {r.outcome for r in rows} == {checks.OK}
    assert checks.rc(rows) == 0
    got = by_subject(rows)
    assert got["count cells_scored"].measures["got"] == "1"
    assert got["count cell"].measures["got"] == "2"
    assert set(got) == set(ref_canary.subjects())


def test_a_frozen_count_that_moved_fails_and_names_which_one(registry):
    """The canary is a COMPARISON against `ref.ASSETS_EXPECT`, so moving the registry under
    a frozen number has to fail - and name the count, because "ref/assets moved" is useless
    on its own. Only that one canary goes red: the others are still true."""
    write_assets(registry, ASSETS + [("stn:2", "complex", True)])
    rows = by_subject(ref_canary.census(registry))
    assert rows["count complex"].outcome == checks.FAIL
    assert rows["count complex"].measures == {"got": "2", "want": "1"}
    assert rows["count total"].outcome == checks.FAIL      # 4 rows against a frozen 3
    assert rows["count cell"].outcome == checks.OK
    assert checks.rc(list(rows.values())) == 1


def test_no_registry_at_all_is_inconclusive_on_every_canary_and_never_ok(tmp_path):
    """The common case, not an edge: a worktree, a fresh checkout and every task pod have no
    `ref/assets`. A root with no registry tells you NOTHING about the registry, so every
    canary is could-not-check with NULL measures - never a pass, and never a gap either."""
    rows = ref_canary.census(tmp_path)
    assert [r.subject for r in rows] == list(ref_canary.subjects())
    assert {r.outcome for r in rows} == {checks.INCONCLUSIVE}
    assert all(r.measures == {"got": None, "want": None} for r in rows)
    assert checks.rc(rows) == 2


def test_an_empty_directory_is_not_a_built_registry(tmp_path):
    """KNOWN TRAPS: a table is a PART FILE, not a folder. Every writer here mkdirs before it
    writes, so a run that died in between leaves an empty directory - and a `.exists()` test
    would read that as a built table and then fail deep inside pyarrow. It reads UNBUILT,
    which is the repo's own data-first/marker-last rule seen from the other side."""
    (tmp_path / "ref" / "assets").mkdir(parents=True)
    assert not ref_canary.built(tmp_path, *ref_canary.ASSETS)
    assert {r.outcome for r in ref_canary.census(tmp_path)} == {checks.INCONCLUSIVE}


def test_the_measures_are_null_and_never_a_measured_zero_when_nothing_ran(tmp_path):
    """0 is a count that was taken; NULL is the could-not-check convention the whole third
    outcome rests on. Asserted against `is None` rather than falsiness, because 0 is falsy
    and that conflation is the entire point."""
    (row,) = [r for r in ref_canary.census(tmp_path) if r.subject == ref_canary.IDENTITY]
    assert row.measures["got"] is None and row.measures["got"] != 0


# --- the key-stability contract -------------------------------------------------------

def test_a_derived_table_referencing_a_vanished_asset_is_an_orphan(registry):
    """`ref.build_assets` refuses a rebuild that would orphan these two tables. This asks
    the same question read-side, which is the only form available while `ref` cannot be
    rebuilt at all - and it is the reason the orphan check exists rather than a taste."""
    write_derived(registry, "gold/flood_labels", ["stn:1", "bus:GONE"])
    rows = by_subject(ref_canary.census(registry))
    assert rows["keys gold/flood_labels"].outcome == checks.FAIL
    assert rows["keys gold/flood_labels"].measures == {"got": "1", "want": "0"}
    assert "bus:GONE" in rows["keys gold/flood_labels"].detail


def test_a_derived_table_inside_the_registry_is_clean(registry):
    """The other direction, and the one that must NOT be failed: a derived table naming a
    SUBSET of the registry is normal - `gold/flood_labels` holds only labelled assets. Only
    `removed` is read out of the diff; `added` is 20,000-odd unlabelled assets on the real
    root and means nothing here."""
    write_derived(registry, "silver/asset_features", ["stn:1"])
    rows = by_subject(ref_canary.census(registry))
    assert rows["keys silver/asset_features"].outcome == checks.OK
    assert rows["keys silver/asset_features"].measures["got"] == "0"


def test_a_derived_table_that_is_not_built_was_never_asked(registry):
    """No `gold/flood_labels` on this root means the orphan question was not put, which is a
    could-not-check and not a clean bill. The rest of the census still runs: one absent
    input must not take the whole batch with it (notify 03's whole-root outage)."""
    rows = by_subject(ref_canary.census(registry))
    assert rows["keys gold/flood_labels"].outcome == checks.INCONCLUSIVE
    assert rows["count total"].outcome == checks.OK
    assert checks.rc(list(rows.values())) == 2


def test_the_orphan_check_is_the_registrys_own_diff_and_not_a_second_one(registry,
                                                                        monkeypatch):
    """The key-stability contract keeps ONE home: `ref.assets_key_diff`. Pinned by making
    that function the only thing that can answer - a stub that reports an orphan turns the
    row red, so a re-implementation here would have to disagree with `ref.py` to pass."""
    write_derived(registry, "gold/flood_labels", ["stn:1"])
    monkeypatch.setattr(ref, "assets_key_diff",
                        lambda old, new: {"added": [], "removed": ["stn:PLANTED"],
                                          "moved": []})
    rows = by_subject(ref_canary.census(registry))
    assert rows["keys gold/flood_labels"].outcome == checks.FAIL
    assert "stn:PLANTED" in rows["keys gold/flood_labels"].detail


# --- the identity ---------------------------------------------------------------------

def test_the_identity_row_carries_the_registrys_own_version(registry):
    """`ref.assets_version` is the content identity and this records it. Its named ceiling:
    nothing in this repo PERSISTS a counterpart to compare against, so the row proves the
    identity resolves and publishes its value - a registry that MOVED is caught by the count
    rows and the orphan rows. Freezing a sha here would be the second home this ticket is
    about avoiding, so `want` is NULL on purpose."""
    (row,) = [r for r in ref_canary.census(registry) if r.subject == ref_canary.IDENTITY]
    assert row.measures["got"] == ref.assets_version(registry)
    assert len(row.measures["got"]) == 40
    assert row.measures["want"] is None


def test_the_identity_moves_when_the_registry_moves(registry):
    """The canary half of the identity: it is a function of the rows, so a registry that
    gained an asset stamps differently. Without this the row could be any constant."""
    before = by_subject(ref_canary.census(registry))[ref_canary.IDENTITY].measures["got"]
    write_assets(registry, ASSETS + [("bus:9", "bus_stop", True)])
    after = by_subject(ref_canary.census(registry))[ref_canary.IDENTITY].measures["got"]
    assert before != after


# --- one home for every number --------------------------------------------------------

def test_this_tickets_code_retypes_no_frozen_count():
    """THE TICKET'S OWN RULE, as a test rather than a promise: expect THROUGH the canaries,
    never restate a count. Every frozen number lives in `ref.ASSETS_EXPECT`; if one appeared
    in this producer or in the suite that reads it, the two copies would disagree the first
    time the registry legitimately moved and the older copy would be the one nobody
    remembered to update. Scanned over the source TEXT, docstrings included - a count in
    prose is still a second copy, and TRAPS has a whole bullet on retired strings coming
    back through the documents that quote them."""
    for name in ("ref_canary.py", "gx.py"):
        text = (SRC / name).read_text()
        planted = [k for k, v in ref.ASSETS_EXPECT.items() if str(v) in text]
        assert not planted, f"{name} retypes frozen count(s) {planted}"


def test_the_declared_subjects_are_exactly_what_the_census_emits(registry):
    """`subjects()` is what the GX suite's batch-level claim reads to say "this canary never
    ran". If the two lists could drift, a canary could vanish from the census and the claim
    would report nothing missing - the false OK, one level up."""
    assert [r.subject for r in ref_canary.census(registry)] == list(ref_canary.subjects())
    assert [r.subject for r in ref_canary.census(registry.parent / "nowhere")] \
        == list(ref_canary.subjects())


def test_the_declaration_grows_with_the_constant(monkeypatch):
    """Derived from `ref.ASSETS_EXPECT`, never listed here: a count frozen in `ref.py`
    tomorrow is covered the day it lands rather than the day someone remembers this file."""
    monkeypatch.setattr(ref, "ASSETS_EXPECT", EXPECT | {"ferry_pier": 7})
    assert "count ferry_pier" in ref_canary.subjects()


# --- the CLI --------------------------------------------------------------------------

def test_the_cli_writes_the_batch_with_the_declared_columns_and_exits_on_the_rule(
        registry, monkeypatch, capsys):
    """The batch is the record: `backfill` and `ref` are not in the nightly declaration, so
    no task state ever renders their outcome (orch 07) and the persisted rows are all there
    is. Columns are asserted by `checks.write` itself, so a producer that drifts from
    CHECK_COLUMNS crashes here rather than reaching a suite."""
    monkeypatch.setenv("RAINCHECK_ARCHIVE_ROOT", str(registry))
    write_derived(registry, "gold/flood_labels", ["stn:1", "bus:GONE"])
    with pytest.raises(SystemExit) as exc:
        ref_canary.main()
    assert exc.value.code == 1                      # an orphan is a real failure
    (path,) = (registry / "checks" / f"check={ref_canary.CHECK}").glob("run=*.jsonl")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert all(tuple(r) == ref_canary.CHECK_COLUMNS for r in rows)
    assert {r["subject"] for r in rows} == set(ref_canary.subjects())
    assert "ORPHANED 1" in capsys.readouterr().out
