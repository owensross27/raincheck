"""cloud 12: `ref/` reaches a pod by being pulled from the private bucket, not baked into
a git-sha-tagged image. The rows here pin what the initContainer relies on."""
from pathlib import Path

import pytest

from raincheck import refpull

BUCKET = "raincheck-bronze"
IN_BUCKET = ["assets", "calendar", "cell_pixel", "cell_zone", "cells", "grids", "picks",
             "src", "zones"]


class FakeFS:
    def __init__(self, names):
        self.names, self.got = names, []

    def ls(self, path):
        return [f"{path}/{n}" for n in self.names]

    def get(self, src, dst, recursive=False):
        self.got.append(src)
        Path(dst).mkdir(parents=True, exist_ok=True)
        (Path(dst) / "part-00000.parquet").write_bytes(b"")


@pytest.fixture
def fake(monkeypatch):
    fs = FakeFS(IN_BUCKET)
    monkeypatch.setattr(refpull, "fs", lambda: fs)
    return fs


def test_it_pulls_the_tables_the_bucket_holds_and_skips_the_gtfs_sources(fake, tmp_path, capsys):
    assert refpull.pull(tmp_path, BUCKET) == 0
    pulled = [s.rsplit("/", 1)[-1] for s in fake.got]
    assert pulled == [t for t in IN_BUCKET if t != "src"]
    assert "src" not in pulled and not (tmp_path / "ref" / "src").exists()
    assert (tmp_path / "ref" / "cell_pixel" / "part-00000.parquet").is_file()
    out = capsys.readouterr().out
    assert "8 table(s) pulled" in out and "skipped src" in out   # never a silent cap


def test_the_table_list_comes_from_the_bucket_not_from_this_module(monkeypatch, tmp_path):
    """A ref table added by a later `make ref` must travel without an edit here."""
    fs = FakeFS(["assets", "brand_new_table", "src"])
    monkeypatch.setattr(refpull, "fs", lambda: fs)
    refpull.pull(tmp_path, BUCKET)
    assert [s.rsplit("/", 1)[-1] for s in fs.got] == ["assets", "brand_new_table"]


def test_a_table_already_present_is_left_alone(fake, tmp_path):
    """A long-lived pod restarting its container must not re-download 4 MB to find it
    already has it."""
    have = tmp_path / "ref" / "assets"
    have.mkdir(parents=True)
    (have / "part-00000.parquet").write_bytes(b"kept")
    refpull.pull(tmp_path, BUCKET)
    assert "assets" not in [s.rsplit("/", 1)[-1] for s in fake.got]
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
