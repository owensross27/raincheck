"""Ticket 06: the slice driver's T1 checker on the committed 2021-11-07 fragment, and
the window derivations pinned to the ticket's counts. JVM-free."""
from datetime import date
from pathlib import Path

import pytest

from raincheck import nbp, slice as slice_mod

FIXTURES = Path(__file__).parent / "fixtures"


def test_window_derivations():
    assert len(slice_mod.FILE_DAYS) == 124
    assert len(slice_mod.SERVICE_DAYS) == 122
    assert slice_mod.MONTHS == ["2021-08", "2021-09", "2021-10", "2023-09", "2023-10"]
    assert slice_mod.FILE_DAYS[0].isoformat() == "2021-08-16"
    assert slice_mod.FILE_DAYS[-1].isoformat() == "2023-11-01"


@pytest.fixture()
def converted(tmp_path):
    day = "2021-11-07"
    src = tmp_path / "archive" / "nycbuspositions" / "2021" / "11" / f"{day}-bus-positions.csv.xz"
    src.parent.mkdir(parents=True)
    src.write_bytes((FIXTURES / "nbp-2021-11-07-fragment.csv.xz").read_bytes())
    nbp.convert(tmp_path, day)
    return tmp_path, day


def test_t1_clean_day_passes(converted):
    root, day = converted
    assert slice_mod.t1(root, day) == []


def test_t1_catches_missing_rows(converted):
    root, day = converted
    part = next((root / "archive" / "vp").glob(f"date=*/hour=12/part-nbp-{day}.parquet"))
    part.unlink()
    errs = slice_mod.t1(root, day)
    assert any("xz rows" in e for e in errs)


def test_t1_skips_row_check_after_lowdisk_delete(converted):
    root, day = converted
    slice_mod.xz_path(root, day).unlink()  # low-disk mode deleted it after a green T1
    assert slice_mod.t1(root, day) == []   # remaining checks still run and pass


def test_convert_deletes_xz_only_after_green_t1(converted, monkeypatch):
    root, day = converted
    monkeypatch.setattr(slice_mod, "FILE_DAYS", [date.fromisoformat(day)])
    src = slice_mod.xz_path(root, day)
    slice_mod.convert(root, force=False, keep_xz=True)   # cached day, keep-xz: source stays
    assert src.exists()
    slice_mod.convert(root, force=False, keep_xz=False)  # low-disk: deleted after green T1
    assert not src.exists()


def test_convert_aborts_and_keeps_xz_on_red_t1(converted, monkeypatch):
    root, day = converted
    monkeypatch.setattr(slice_mod, "FILE_DAYS", [date.fromisoformat(day)])
    part = next((root / "archive" / "vp").glob(f"date=*/hour=12/part-nbp-{day}.parquet"))
    part.unlink()
    monkeypatch.setattr(slice_mod.nbp, "convert", lambda root, day: None)  # keep the damage
    with pytest.raises(SystemExit, match="T1 FAILED"):
        slice_mod.convert(root, force=True, keep_xz=False)
    assert slice_mod.xz_path(root, day).exists()  # never deleted on a red T1


def test_headroom_gate(tmp_path, monkeypatch, capsys):
    import shutil as _shutil
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(_shutil, "disk_usage", lambda p: usage(1, 1, 100_000_000_000))
    slice_mod.headroom_gate(tmp_path, keep_xz=False)  # 100 GB free: passes
    assert "headroom ok" in capsys.readouterr().out
    monkeypatch.setattr(_shutil, "disk_usage", lambda p: usage(1, 1, 1_000_000_000))
    with pytest.raises(SystemExit, match="peak footprint"):
        slice_mod.headroom_gate(tmp_path, keep_xz=False)  # 1 GB free < ~2.7 GB needed
