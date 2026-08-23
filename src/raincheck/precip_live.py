"""`make precip-live` (ticket 11 / spec H, K): one tick of the live precip table.

Fetches the latest MRMS RadarOnly_QPE_01H :00 file from NODD plus every missing :00
stamp of the trailing 25 hours (the flood spec's catch-up amendment: sleep holes heal
on wake), decodes each CONUS grid once, takes the area-weighted Cell mean through
`ref/cell_pixel grid_id=mrms` (numpy, no Spark), and appends
`live/precip_cell/valid_ts=<YYYY-MM-DDTHH>/part-<fetched_at>.parquet` (columns cell,
mm_1h, fetched_at; negatives NULL; latest fetched_at wins per (cell, valid_ts) at
read; valid_ts dirs older than 7 days dropped by name). Runs for seconds and exits, on
its own 300 s StartInterval LaunchAgent (launchd/com.raincheck.precip-live.plist) -
never the archiver loop, never the stream.

`fetch_conus` / `decode_conus` are shared with the batch path (`precip-hourly
SRC=mrms`, raincheck.precip), which reads the gauge-corrected Pass2 product instead.
"""
import gzip
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import requests

from raincheck.paths import data_root
from raincheck.ref import MRMS_TUPLE

NODD = "https://noaa-mrms-pds.s3.amazonaws.com/CONUS"
RADAR = "RadarOnly_QPE_01H_00.00"
PASS2 = "MultiSensor_QPE_01H_Pass2_00.00"
TS = pa.timestamp("us", tz="UTC")
GRID_KEYS = ("Ni", "Nj", "latitudeOfFirstGridPointInDegrees", "latitudeOfLastGridPointInDegrees",
             "longitudeOfFirstGridPointInDegrees", "longitudeOfLastGridPointInDegrees",
             "iDirectionIncrementInDegrees", "jDirectionIncrementInDegrees", "jScansPositively")


def decode_conus(buf: bytes) -> np.ndarray:
    """One GRIB2 message -> (3500, 7000) float array in ref/grids orientation (j up from
    the SW origin). Source rows run north-to-south, so the row axis is flipped; the grid
    tuple is asserted against the frozen ref/grids tuple (research 08 / ref.MRMS_TUPLE)."""
    import eccodes  # heavy; only when a file is actually decoded

    gid = eccodes.codes_new_from_message(buf)
    try:
        got = tuple(round(float(eccodes.codes_get(gid, k)), 3) for k in GRID_KEYS)
        if got != tuple(round(float(v), 3) for v in MRMS_TUPLE):
            raise RuntimeError(f"MRMS grid tuple changed: file {got} != ref/grids {MRMS_TUPLE}")
        vals = eccodes.codes_get_values(gid).reshape(MRMS_TUPLE[1], MRMS_TUPLE[0])
    finally:
        eccodes.codes_release(gid)
    return vals[::-1]


def fetch_conus(product: str, stamp: datetime) -> np.ndarray | None:
    """The decoded grid for one :00 stamp, or None while NODD has not published it."""
    url = f"{NODD}/{product}/{stamp:%Y%m%d}/MRMS_{product}_{stamp:%Y%m%d-%H%M%S}.grib2.gz"
    r = requests.get(url, timeout=120)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return decode_conus(gzip.decompress(r.content))


def cell_means(root: Path, grid: np.ndarray) -> pa.Table:
    """Area-weighted Cell mean of the field through the mrms crosswalk, sorted by cell;
    negatives NULL, and a Cell is NULL unless its realized non-null Pixel weight sums
    to 1 within 1e-6 (spec H, the same guard as the batch table)."""
    x = pq.read_table(root / "ref" / "cell_pixel", columns=["grid_id", "cell", "i", "j", "weight"])
    x = x.filter(pc.equal(x.column("grid_id"), "mrms"))
    w = x.column("weight").to_numpy()
    mm = grid[x.column("j").to_numpy(), x.column("i").to_numpy()].astype(np.float64)
    mm[mm < 0] = np.nan  # negative sentinel -> NULL
    cells, codes = np.unique(x.column("cell").to_numpy(), return_inverse=True)
    ok = ~np.isnan(mm)
    wsum = np.bincount(codes[ok], weights=w[ok], minlength=cells.size)
    val = np.bincount(codes[ok], weights=(w * mm)[ok], minlength=cells.size)
    mm_1h = np.where(wsum >= 1 - 1e-6, val, np.nan)
    return pa.table({"cell": pa.array(cells, pa.int64()),
                     "mm_1h": pa.array(mm_1h, pa.float32(), from_pandas=True)})


def append_hour(root: Path, valid_ts: datetime, grid: np.ndarray, fetched_at: datetime) -> pa.Table:
    t = cell_means(root, grid)
    t = t.append_column("fetched_at", pa.array([fetched_at] * t.num_rows, TS))
    out = (root / "live" / "precip_cell" / f"valid_ts={valid_ts:%Y-%m-%dT%H}"
           / f"part-{fetched_at:%Y%m%dT%H%M%S}.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")  # the stream reads this dir fresh each batch: no torn parts
    pq.write_table(t, tmp, compression="zstd")
    tmp.replace(out)
    return t


def tick(root: Path, now: datetime | None = None) -> None:
    """One tick: walking back 25 hours from `now` (a test seam), fetch the latest
    published :00 stamp unconditionally (a re-fetch: latest fetched_at wins at read) and
    every older stamp the table is missing - the flood spec's catch-up amendment, so
    laptop-sleep holes heal on wake within the source's measured ~25 h retention."""
    fetched_at = now or datetime.now(timezone.utc)
    hour = fetched_at.replace(minute=0, second=0, microsecond=0)
    table = root / "live" / "precip_cell"
    have = {d.name for d in table.glob("valid_ts=*") if any(d.glob("*.parquet"))}
    landed: list[str] = []
    latest_done = False
    for back in range(25):
        valid_ts = hour - timedelta(hours=back)
        if latest_done and f"valid_ts={valid_ts:%Y-%m-%dT%H}" in have:
            continue
        grid = fetch_conus(RADAR, valid_ts)
        if grid is None:  # ahead of publication (top of the walk) or a real source gap
            continue
        t = append_hour(root, valid_ts, grid, fetched_at)
        latest_done = True
        landed.append(f"{valid_ts:%Y-%m-%dT%H} ({t.num_rows - t.column('mm_1h').null_count} non-null)")
    if not landed:
        sys.exit(f"precip-live: no RadarOnly :00 file on NODD in the 25 hours up to {hour:%Y-%m-%dT%H}Z")
    cutoff = f"valid_ts={fetched_at - timedelta(days=7):%Y-%m-%dT%H}"
    for d in table.glob("valid_ts=*"):
        if d.name < cutoff:
            shutil.rmtree(d)
    print(f"precip-live: {', '.join(landed)} at {fetched_at:%Y-%m-%dT%H:%M:%S}Z", flush=True)


def main() -> None:
    tick(data_root())


if __name__ == "__main__":
    main()
