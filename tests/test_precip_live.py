"""Ticket 11 / 08-T6, 07-4: the MRMS ingest (decode, flip, negatives, hour-ending) and
the live precip table (string valid_ts key, latest-wins, retention). Two seams: the
committed CONUS files for the real storm stamp 2026-08-21T00Z through the real mrms
crosswalk, and a monkeypatched fetch_conus over a synthetic three-cell crosswalk.
No Spark: the live table and the mrms Bronze/hourly path are numpy + pyarrow."""
import gzip
import hashlib
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raincheck import duck, precip, precip_live

FIXTURES = Path(__file__).parent / "fixtures"
STAMP = datetime(2026, 8, 21, 0, tzinfo=timezone.utc)
PASS2_FILE = FIXTURES / "MRMS_MultiSensor_QPE_01H_Pass2_00.00_20260821-000000.grib2.gz"
RADAR_FILE = FIXTURES / "MRMS_RadarOnly_QPE_01H_00.00_20260821-000000.grib2.gz"
CP_I, CP_J = 5603, 2078  # Central Park in ref/grids mrms coordinates (j up from the SW origin)


# --- 08-T6: decode and flip -----------------------------------------------------------

def test_decode_flip_and_central_park():
    import eccodes

    grid = precip_live.decode_conus(gzip.decompress(RADAR_FILE.read_bytes()))
    assert grid.shape == (3500, 7000)
    # ref/grids mrms row: origin centre (-129.995, 20.005), step 0.01, j up from the south
    assert round((-73.965 - -129.995) / 0.01) == CP_I
    assert round((40.782 - 20.005) / 0.01) == CP_J
    # independent north-origin read straight from the message (the evidence-script formula:
    # source rows run north-to-south from lat 54.995) must agree across the flip
    gid = eccodes.codes_new_from_message(gzip.decompress(RADAR_FILE.read_bytes()))
    try:
        raw = eccodes.codes_get_values(gid).reshape(3500, 7000)
    finally:
        eccodes.codes_release(gid)
    assert grid[CP_J, CP_I] == raw[round((54.995 - 40.782) / 0.01), CP_I]
    assert grid[CP_J, CP_I] > 0.5  # 2026-08-21T00Z is a real storm hour at Central Park


# --- 08-T6 / 07-5: the batch mrms path through the real crosswalk ---------------------

@pytest.fixture(scope="module")
def landed(tmp_path_factory):
    """precip.hourly mrms for 2026-08 with fetch_conus faked: the Pass2 fixture at 00Z,
    a tampered copy (one negative footprint pixel) at 01Z, None (unpublished) elsewhere."""
    root = tmp_path_factory.mktemp("mrms")
    (root / "ref" / "cell_pixel").mkdir(parents=True)
    shutil.copy(FIXTURES / "ref-cell_pixel-mrms.parquet",
                root / "ref" / "cell_pixel" / "part-00000.parquet")
    grid = precip_live.decode_conus(gzip.decompress(PASS2_FILE.read_bytes()))
    tampered = grid.copy()
    tampered[CP_J, CP_I] = -3.0
    calls: list[datetime] = []

    def fake(product, stamp):
        assert product == precip_live.PASS2
        calls.append(stamp)
        if stamp == STAMP:
            return grid
        if stamp == STAMP + timedelta(hours=1):
            return tampered
        return None

    mp = pytest.MonkeyPatch()
    mp.setattr(precip_live, "fetch_conus", fake)
    precip.hourly(root, "mrms", "2026-08")
    mp.undo()
    return root, calls, fake


def test_mrms_bronze_footprint_only_raw_values(landed):
    root, _, _ = landed
    t = pq.read_table(root / "archive" / "precip" / "mrms" / "date=2026-08-21" / "hour=00")
    x = pq.read_table(root / "ref" / "cell_pixel")
    fp = {(i, j) for i, j in zip(x.column("i").to_pylist(), x.column("j").to_pylist())}
    assert t.num_rows == len(fp) == 3449  # footprint only, not a bbox
    assert set(zip(t.column("i").to_pylist(), t.column("j").to_pylist())) == fp
    t1 = pq.read_table(root / "archive" / "precip" / "mrms" / "date=2026-08-21" / "hour=01")
    rows = {(i, j): mm for i, j, mm in zip(t1.column("i").to_pylist(), t1.column("j").to_pylist(),
                                           t1.column("mm").to_pylist())}
    assert rows[(CP_I, CP_J)] == -3.0  # Bronze keeps the raw sentinel; silver nulls it


def test_mrms_hourly_hour_ending_negatives_dense(landed):
    root, _, _ = landed
    con = duck.connect()
    p = f"{root}/silver/precip_hourly/**/*.parquet"
    hours = [r[0] for r in con.execute(
        "SELECT DISTINCT hour_end_utc FROM read_parquet(?) ORDER BY 1", [p]).fetchall()]
    # the file stamped H yields hour_end_utc = H: hour-ending by measurement, no shift (ADR-0002)
    assert [h.isoformat() for h in hours] == ["2026-08-21T00:00:00+00:00", "2026-08-21T01:00:00+00:00"]
    n, uniq, nulls, t2m = con.execute(
        "SELECT count(*), count(DISTINCT (i, j, hour_end_utc)), "
        "count(*) FILTER (mm IS NULL), count(t2m_k) FROM read_parquet(?)", [p]).fetchone()
    assert n == uniq == 3449 * 2  # dense over footprint x published hours, unique grain (07-5)
    assert t2m == 0               # t2m_k NULL for mrms
    assert nulls == 1             # exactly the tampered negative pixel-hour
    (cp,) = con.execute(
        "SELECT mm FROM read_parquet(?) WHERE i = ? AND j = ? "
        "AND hour_end_utc = timestamp '2026-08-21 01:00:00+00'", [p, CP_I, CP_J]).fetchone()
    assert cp is None


def test_mrms_hourly_rebuild_idempotent_bronze_not_refetched(landed):
    root, calls, fake = landed
    out = root / "silver" / "precip_hourly" / "src=mrms" / "month=2026-08" / "part-00000.parquet"
    before = hashlib.sha256(out.read_bytes()).hexdigest()
    calls.clear()
    mp = pytest.MonkeyPatch()
    mp.setattr(precip_live, "fetch_conus", fake)
    precip.hourly(root, "mrms", "2026-08")
    mp.undo()
    assert STAMP not in calls and STAMP + timedelta(hours=1) not in calls  # Bronze is the cache
    assert hashlib.sha256(out.read_bytes()).hexdigest() == before


# --- 07-4: the live table over a synthetic crosswalk ----------------------------------

def synth_root(tmp: Path) -> Path:
    """Cell 1 = {(0,0) 0.5, (0,1) 0.5}, cell 2 = {(1,0) 1.0}, cell 3 = {(1,1) 0.6, (2,1) 0.4}."""
    root = tmp / "root"
    rows = [("mrms", 1, 0, 0, 0.5), ("mrms", 1, 0, 1, 0.5), ("mrms", 2, 1, 0, 1.0),
            ("mrms", 3, 1, 1, 0.6), ("mrms", 3, 2, 1, 0.4)]
    schema = pa.schema([("grid_id", pa.string()), ("cell", pa.int64()),
                       ("i", pa.int16()), ("j", pa.int16()), ("weight", pa.float64())])
    (root / "ref" / "cell_pixel").mkdir(parents=True)
    pq.write_table(pa.Table.from_pydict(
        {k: [r[n] for r in rows] for n, k in enumerate(schema.names)}, schema=schema),
        root / "ref" / "cell_pixel" / "part-00000.parquet")
    return root


# value at (i, j) is A[j, i]: pixel (2,1) carries the negative sentinel
A = np.array([[2.0, 6.0, 9.0],
              [4.0, 5.0, -3.0]])
H20 = datetime(2026, 8, 21, 20, tzinfo=timezone.utc)


def live(root: Path):
    con = duck.connect()
    return con, duck.table(con, root / "live" / "precip_cell")


def test_live_tick_string_key_means_and_negative_guard(tmp_path, monkeypatch):
    root = synth_root(tmp_path)
    monkeypatch.setattr(precip_live, "fetch_conus", lambda p, s: A if s == H20 else None)
    precip_live.tick(root, now=datetime(2026, 8, 21, 20, 40, 12, tzinfo=timezone.utc))
    con, t = live(root)
    t.create_view("lv")
    assert (root / "live" / "precip_cell" / "valid_ts=2026-08-21T20"
            / "part-20260821T204012.parquet").exists()
    (kind,) = con.execute("SELECT typeof(valid_ts) FROM lv LIMIT 1").fetchone()
    assert kind == "VARCHAR"  # string key, no autocast
    rows = dict(con.execute("SELECT cell, mm_1h FROM lv").fetchall())
    assert rows[1] == pytest.approx(3.0)   # 0.5*2 + 0.5*4
    assert rows[2] == pytest.approx(6.0)
    assert rows[3] is None                 # negative pixel -> realized weight 0.6 < 1 - 1e-6


def test_live_refetch_latest_wins_and_fallback_hour(tmp_path, monkeypatch):
    root = synth_root(tmp_path)
    monkeypatch.setattr(precip_live, "fetch_conus", lambda p, s: A if s == H20 else None)
    precip_live.tick(root, now=datetime(2026, 8, 21, 20, 40, 12, tzinfo=timezone.utc))
    monkeypatch.setattr(precip_live, "fetch_conus", lambda p, s: A * 2 if s == H20 else None)
    # 21:02, the 21:00 file not yet on NODD: the tick falls back to the 20:00 stamp
    precip_live.tick(root, now=datetime(2026, 8, 21, 21, 2, 0, tzinfo=timezone.utc))
    con, t = live(root)
    t.create_view("lv")
    (n_hours,) = con.execute("SELECT count(DISTINCT valid_ts) FROM lv").fetchone()
    assert n_hours == 1  # the fallback landed in the same Hour, not a new key
    (n_parts,) = con.execute("SELECT count(DISTINCT fetched_at) FROM lv").fetchone()
    assert n_parts == 2  # append-only: the re-fetch is a second part in the same valid_ts dir
    rows = dict(con.execute("""
        SELECT cell, mm_1h FROM (
          SELECT cell, mm_1h, row_number() OVER (PARTITION BY cell, valid_ts
                                                 ORDER BY fetched_at DESC) AS rn
          FROM lv WHERE valid_ts = '2026-08-21T20') WHERE rn = 1""").fetchall())
    assert rows[1] == pytest.approx(6.0)  # latest fetched_at wins per (cell, valid_ts)


def test_live_scalar_latest_complete_hour_and_retention(tmp_path, monkeypatch):
    root = synth_root(tmp_path)
    stale = root / "live" / "precip_cell" / "valid_ts=2026-08-13T20"
    keep = root / "live" / "precip_cell" / "valid_ts=2026-08-15T20"
    for d in (stale, keep):
        d.mkdir(parents=True)
        pq.write_table(pa.table({"cell": pa.array([1], pa.int64()),
                                 "mm_1h": pa.array([0.0], pa.float32()),
                                 "fetched_at": pa.array([H20], pa.timestamp("us", tz="UTC"))}),
                       d / "part-00000000T000000.parquet")
    monkeypatch.setattr(precip_live, "fetch_conus", lambda p, s: A if s == H20 else None)
    precip_live.tick(root, now=datetime(2026, 8, 21, 20, 40, 12, tzinfo=timezone.utc))
    assert not stale.exists() and keep.exists()  # 7-day retention by directory name
    monkeypatch.setattr(precip_live, "fetch_conus",
                        lambda p, s: A if s in (H20, H20 + timedelta(hours=1)) else None)
    precip_live.tick(root, now=datetime(2026, 8, 21, 21, 7, 0, tzinfo=timezone.utc))
    con, t = live(root)
    t.create_view("lv")
    # the stream's scalar read: max(valid_ts) <= batch time as a string, lexicographic
    for t_str, want in [("2026-08-21T21", "2026-08-21T21"), ("2026-08-21T20", "2026-08-21T20")]:
        (got,) = con.execute(
            "SELECT max(valid_ts) FROM lv WHERE valid_ts <= ?", [t_str]).fetchone()
        assert got == want


def test_live_catchup_lands_missing_hours_once(tmp_path, monkeypatch):
    """Flood spec amendment: a tick walks the trailing 25 h and heals holes; landed
    hours are not re-fetched, the latest published stamp always is."""
    root = synth_root(tmp_path)
    published = {H20 - timedelta(hours=2), H20 - timedelta(hours=1), H20}
    fetched: list[datetime] = []

    def fake(product, stamp):
        fetched.append(stamp)
        return A if stamp in published else None

    monkeypatch.setattr(precip_live, "fetch_conus", fake)
    precip_live.tick(root, now=datetime(2026, 8, 21, 20, 40, 12, tzinfo=timezone.utc))
    dirs = sorted(d.name for d in (root / "live" / "precip_cell").glob("valid_ts=*"))
    assert dirs == ["valid_ts=2026-08-21T18", "valid_ts=2026-08-21T19", "valid_ts=2026-08-21T20"]
    fetched.clear()
    precip_live.tick(root, now=datetime(2026, 8, 21, 20, 45, 12, tzinfo=timezone.utc))
    assert [s for s in fetched if s in published] == [H20]  # only the latest re-fetched
    parts = {d.name: len(list(d.glob("*.parquet")))
             for d in (root / "live" / "precip_cell").glob("valid_ts=*")}
    assert parts == {"valid_ts=2026-08-21T18": 1, "valid_ts=2026-08-21T19": 1,
                     "valid_ts=2026-08-21T20": 2}


def test_live_tick_exits_when_nodd_dark(tmp_path, monkeypatch):
    root = synth_root(tmp_path)
    monkeypatch.setattr(precip_live, "fetch_conus", lambda p, s: None)
    with pytest.raises(SystemExit):
        precip_live.tick(root, now=datetime(2026, 8, 21, 20, 40, 12, tzinfo=timezone.utc))
