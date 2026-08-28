"""cloud 12: `ref/` reaches a pod by being pulled from the private bucket, not baked into
a git-sha-tagged image. The rows here pin what the initContainer relies on.

frontend5 02: the pull is per-file now, never a recursive directory get - fsspec versions
disagree on what that copies IN to (measured live: the image's version nested
<table>/<table>/, the Mac's did not), and DuckDB's `**` glob tolerated the doubling while
Spark's flat read died UNABLE_TO_INFER_SCHEMA."""
import ast
import inspect
from pathlib import Path

import pytest

from raincheck import refpull

BUCKET = "raincheck-bronze"
IN_BUCKET = ["assets", "calendar", "cell_pixel", "cell_zone", "cells", "grids", "picks",
             "src", "zones"]


class FakeFS:
    """One file per table by default (`files=` overrides per-table object keys, so a test
    can hand it a nested key without the real store touching this Mac)."""

    def __init__(self, names, files=None):
        self.names = names
        self.files = files or {n: ["part-00000.parquet"] for n in names}
        self.got = []

    def ls(self, path):
        return [f"{path}/{n}" for n in self.names]

    def find(self, path):
        name = path.rsplit("/", 1)[-1]
        return [f"{path}/{key}" for key in self.files.get(name, ["part-00000.parquet"])]

    def get(self, src, dst):
        self.got.append(src)
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"")


@pytest.fixture
def fake(monkeypatch):
    fs = FakeFS(IN_BUCKET)
    monkeypatch.setattr(refpull, "fs", lambda: fs)
    return fs


def _pulled_tables(got):
    """Each `got` entry is a full object key (.../<table>/<file>); the table name is the
    second-to-last path segment now that pull() gets files, not directories."""
    return [key.split("/")[-2] for key in got]


def test_it_pulls_the_tables_the_bucket_holds_and_skips_the_gtfs_sources(fake, tmp_path, capsys):
    assert refpull.pull(tmp_path, BUCKET) == 0
    assert _pulled_tables(fake.got) == [t for t in IN_BUCKET if t != "src"]
    assert "src" not in _pulled_tables(fake.got) and not (tmp_path / "ref" / "src").exists()
    assert (tmp_path / "ref" / "cell_pixel" / "part-00000.parquet").is_file()
    out = capsys.readouterr().out
    assert "8 table(s) pulled" in out and "skipped src" in out   # never a silent cap


def test_the_table_list_comes_from_the_bucket_not_from_this_module(monkeypatch, tmp_path):
    """A ref table added by a later `make ref` must travel without an edit here."""
    fs = FakeFS(["assets", "brand_new_table", "src"])
    monkeypatch.setattr(refpull, "fs", lambda: fs)
    refpull.pull(tmp_path, BUCKET)
    assert _pulled_tables(fs.got) == ["assets", "brand_new_table"]


def test_a_table_already_present_is_left_alone(fake, tmp_path):
    """A long-lived pod restarting its container must not re-download 4 MB to find it
    already has it."""
    have = tmp_path / "ref" / "assets"
    have.mkdir(parents=True)
    (have / "part-00000.parquet").write_bytes(b"kept")
    refpull.pull(tmp_path, BUCKET)
    assert "assets" not in _pulled_tables(fake.got)
    assert (have / "part-00000.parquet").read_bytes() == b"kept"


def test_an_object_store_root_already_has_ref_under_it(monkeypatch, capsys):
    """The SAME initContainer is correct for both root kinds - `<root>/ref` is one path,
    not two. It must not try (and must not silently look like it succeeded)."""
    monkeypatch.setattr(refpull, "fs", lambda: pytest.fail("touched the store"))
    assert refpull.pull("s3a://raincheck-bronze", BUCKET) == 0
    assert "already object storage" in capsys.readouterr().out


def test_main_refuses_without_a_bucket(monkeypatch, capsys):
    monkeypatch.delenv("RAINCHECK_COLD_BUCKET", raising=False)
    assert refpull.main([]) == 2
    assert "RAINCHECK_COLD_BUCKET" in capsys.readouterr().err


def test_pulled_files_sit_directly_under_the_table_dir_no_doubled_level(fake, tmp_path):
    """The regression this ticket exists for: a recursive directory get copies the
    DIRECTORY in under some fsspec versions, doubling <table>/<table>/. Pin the LAYOUT by
    walking the result, not by mocking the old bug back in."""
    refpull.pull(tmp_path, BUCKET)
    for table in (t for t in IN_BUCKET if t != "src"):
        table_dir = tmp_path / "ref" / table
        assert table_dir.is_dir()
        assert not (table_dir / table).exists(), f"{table} doubled itself under its own dir"
        entries = list(table_dir.iterdir())
        assert entries, f"{table} pulled nothing"
        assert all(e.is_file() for e in entries), f"{table} has a subdirectory, not a flat file"


def test_the_module_never_issues_a_recursive_directory_get():
    """Anchor on the CALL SHAPE, not on text a rewrite could quietly drop: walk the AST for
    any call passing recursive=True, the shape a directory-get needs regardless of how the
    surrounding prose reads."""
    tree = ast.parse(inspect.getsource(refpull))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "recursive" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                pytest.fail(f"recursive=True call at refpull.py:{node.lineno} - "
                             "directory gets are refused by this ticket")


def test_a_nested_key_fails_loudly_rather_than_guessing(monkeypatch, tmp_path):
    fs = FakeFS(["assets"], files={"assets": ["sub/part-00000.parquet"]})
    monkeypatch.setattr(refpull, "fs", lambda: fs)
    with pytest.raises(ValueError, match="nested key"):
        refpull.pull(tmp_path, BUCKET)
