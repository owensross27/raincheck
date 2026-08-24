"""Flood-build ticket 16: the impact evidence aggregates.

Seam 1 (the aggregates' contracts) on synthetic inputs, because subwaydata.nyc publishes
no data license: nothing derived from it is committed here. The two rules that can
silently ruin the corpus - the previous-day union and the caught rule's controls - are
pinned on hand-built days that need no network and no snapshot.

The reference-day assertion (2023-09-29) reads the LOCAL build output and skips when the
snapshots are absent, which is the only way to keep the number reproducible without
redistributing the source.
"""
import io
import lzma
import tarfile
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raincheck import flood_impact as fi

DAY = date(2023, 9, 29)
# 2023-09-29 00:30 America/New_York = 04:30 UTC. The trip that makes this call started on
# the 28th, so it is filed in the 28th's file - the whole point of the union.
NY0030 = 1695961800
HOUR = 3600
# the 2023-09-29 reference read, measured 2026-08-23 over the landed spine
FLAGGED = {"225", "232", "236", "243", "47", "623", "626", "79"}
CAUGHT_REF = {"236", "243", "47", "79"}


def write_day(root: Path, d: date, calls: list[tuple[str, str, str, int]]) -> None:
    """One subwaydata-shaped tarball: calls are (trip_uid, route_id, stop_id, epoch)."""
    trips = "trip_uid,trip_id,route_id,direction_id,start_time\n" + "".join(
        f"{t},{t},{r},0,{ts}\n" for t, r, _, ts in {c[0]: c for c in calls}.values())
    stops = "trip_uid,stop_id,track,arrival_time,departure_time\n" + "".join(
        f"{t},{s},1,{ts},{ts + 30}\n" for t, _, s, ts in calls)
    path = fi.snapshot_path(d, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with lzma.open(path, "wb") as raw, tarfile.open(fileobj=raw, mode="w") as tar:
        for member, body in (("trips", trips), ("stop_times", stops)):
            data = body.encode()
            info = tarfile.TarInfo(f"subwaydatanyc_{d}_{member}.csv")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def write_assets(root: Path) -> None:
    (root / "ref" / "assets").mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({
        "kind": ["station", "station"],
        "complex_id": ["C1", "C2"],
        "line": ["L1", "L1"],
        "gtfs_stop_id": [["101"], ["102"]],
    }), root / "ref" / "assets" / "part-0.parquet")


def test_prev_day_union_is_load_bearing(tmp_path):
    """A day's hours 00-05 live in the PREVIOUS day's trip-start-keyed file. Reading D
    alone drops them; the measured cost on the real 2023-09-29 is a 92.6% undercount of
    hour 00 (341 calls read vs 4,601 unioned)."""
    write_assets(tmp_path)
    # four calls at C1 in NY hour 00, all belonging to trips that started on the 28th
    write_day(tmp_path, date(2023, 9, 28),
              [(f"t{i}", "L", "101N", NY0030 + i * 300) for i in range(4)])
    write_day(tmp_path, DAY, [("t9", "L", "101N", NY0030 + 12 * HOUR)])  # a noon call

    t = pq.read_table(fi.aggregate(DAY, tmp_path, force=True))
    by_hour = dict(zip(t.column("hour").to_pylist(), t.column("n_calls").to_pylist()))
    assert by_hour[0] == 4, "hour 00 must come from the previous day's file"
    assert by_hour[12] == 1

    # and without it: the same day read with only its own file loses the hour entirely
    fi.snapshot_path(date(2023, 9, 28), tmp_path).unlink()
    t2 = pq.read_table(fi.aggregate(DAY, tmp_path, force=True))
    assert 0 not in t2.column("hour").to_pylist()


def test_max_gap_spans_midnight(tmp_path):
    """The worst headway in hour 00 is measured against the call before it, which is on
    the other side of midnight - so the gap is taken over the unioned two-day sequence."""
    write_assets(tmp_path)
    write_day(tmp_path, date(2023, 9, 28),
              [("a", "L", "101N", NY0030 - 1800), ("b", "L", "101N", NY0030)])
    write_day(tmp_path, DAY, [])
    t = pq.read_table(fi.aggregate(DAY, tmp_path, force=True))
    assert t.column("max_gap_s").to_pylist() == [1800]


def ratio_table(rows: list[dict]):
    keys = ("complex_id", "hour", "service_ratio", "max_gap_ratio", "resid_ratio",
            "nbr_ratio", "base_calls", "n_ctl")
    return pa.table({k: [r.get(k) for r in rows] for k in keys})


def hit(complex_id: str, hour: int, **over):
    row = dict(complex_id=complex_id, hour=hour, service_ratio=0.2, max_gap_ratio=4.0,
               resid_ratio=0.3, nbr_ratio=0.3, base_calls=10, n_ctl=4)
    row.update(over)
    return row


def test_caught_needs_two_consecutive_daytime_hours():
    assert fi.caught(ratio_table([hit("A", 10), hit("A", 11)])) == {"A"}
    assert fi.caught(ratio_table([hit("A", 10), hit("A", 12)])) == set()  # not sustained
    assert fi.caught(ratio_table([hit("A", 3), hit("A", 4)])) == set()    # overnight
    assert fi.caught(ratio_table([hit("A", 10), hit("A", 11)]), {"B"}) == set()


def test_caught_defers_to_the_attribution_controls():
    """A loss the system-wide route mix or the same-line neighbours already explain is not
    the flood's - that is what the two controls are for."""
    mix = [hit("A", 10, resid_ratio=0.95), hit("A", 11, resid_ratio=0.95)]
    nbr = [hit("A", 10, nbr_ratio=0.95), hit("A", 11, nbr_ratio=0.95)]
    thin = [hit("A", 10, base_calls=2), hit("A", 11, base_calls=2)]
    lone = [hit("A", 10, n_ctl=1), hit("A", 11, n_ctl=1)]
    assert fi.caught(ratio_table(mix)) == set()
    assert fi.caught(ratio_table(nbr)) == set()
    assert fi.caught(ratio_table(thin)) == set()  # no baseline service to lose
    assert fi.caught(ratio_table(lone)) == set()  # one control day is not a baseline
    # a NULL control is not an exoneration: an unexplained loss stays caught
    assert fi.caught(ratio_table([hit("A", 10, nbr_ratio=None),
                                  hit("A", 11, nbr_ratio=None)])) == {"A"}


def test_a_quiet_hour_alone_is_not_impact():
    """service_ratio and max_gap_ratio each stand alone as the loss test (OR), but neither
    fires without one of them: an ordinary hour is never caught."""
    assert fi.caught(ratio_table([hit("A", 10, service_ratio=0.9, max_gap_ratio=1.1),
                                  hit("A", 11, service_ratio=0.9, max_gap_ratio=1.1)])) == set()
    assert fi.caught(ratio_table([hit("A", 10, service_ratio=0.9),
                                  hit("A", 11, service_ratio=0.9)])) == {"A"}  # gap alone
    assert fi.caught(ratio_table([hit("A", 10, max_gap_ratio=1.1),
                                  hit("A", 11, max_gap_ratio=1.1)])) == {"A"}  # service alone


def test_reference_day_2023_09_29():
    """The ticket's reference read, against the local build (skipped without snapshots:
    subwaydata.nyc carries no data license, so no fixture of it is committed)."""
    path = fi.root_dir() / "impact" / "subway_complex_hour.parquet"
    if not path.exists():
        pytest.skip("no local impact build: python -m raincheck.flood_impact fetch agg build")
    t = pq.read_table(path, filters=[("day", "=", DAY)])
    assert fi.caught(t, FLAGGED) == CAUGHT_REF, "4 of the 8 extractor-flagged complexes"
    # and the rule is not catching the whole system: the day's total is a small minority
    assert len(fi.caught(t)) < 0.25 * len(set(t.column("complex_id").to_pylist()))
