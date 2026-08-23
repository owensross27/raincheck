"""archiver.flush durability: the daily job (ticket 15) reads today's Bronze while the
archiver daemon is still writing it, so a part must never be visible half-written."""
from raincheck import archiver

W = 1786478400  # 2026-08-11T20:00Z
ROW = {"vehicle_id": "a", "ts": W, "fetched_at": W}


def test_flush_never_writes_into_the_final_path(tmp_path, monkeypatch):
    """A reader that opens the part mid-write must see the old part or nothing, never a
    torn footer: write to <part>.tmp and rename over. Fails if flush writes out directly."""
    monkeypatch.setattr(archiver, "ROOT", tmp_path)
    dests = []
    real = archiver.pq.write_table
    monkeypatch.setattr(archiver.pq, "write_table",
                        lambda t, d, **k: (dests.append(d), real(t, d, **k))[1])

    out = archiver.flush([ROW] * 3, "vp", W)
    archiver.flush([ROW] * 2, "vp", W)  # restart inside the window: append path, same rule

    assert dests == [out.with_suffix(".parquet.tmp")] * 2
    assert list(out.parent.glob("*.tmp")) == []  # renamed away, no debris
    monkeypatch.undo()
    assert archiver.pq.read_table(out).num_rows == 5
