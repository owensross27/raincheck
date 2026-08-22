"""`make nbp DATE=` (ticket 03 / spec E): one nycbuspositions UTC-day xz file -> Bronze VP
partitions in the live archiver's schema, so archive-era and live Pings are one table with
one read rule (`fetched_at IS NULL` is the archive-era discriminator).

Source  s3.amazonaws.com/nycbuspositions/YYYY/MM/YYYY-MM-DD-bus-positions.csv.xz
        (downloaded once, kept under <root>/archive/nycbuspositions - the bucket is a
        volunteer's and can vanish; 20 columns through 2019-09, 22 from 2020-11)
Output  <root>/archive/vp/date=<UTC date of ts>/hour=HH/part-nbp-<source date>.parquet,
        idempotent by part name (a rerun rewrites the same files byte-identically)
Gate    any ts outside [D-1, D+2) UTC fails the whole file loudly before anything is
        written (the pre-2023-04 ms/s timestamp era; both storm days measured clean)

Run: make nbp DATE=YYYY-MM-DD   (python -m raincheck.nbp YYYY-MM-DD)
"""
import argparse
import lzma
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from raincheck.archiver import TYPES
from raincheck.paths import data_root

URL = "https://s3.amazonaws.com/nycbuspositions/{y}/{m}/{day}-bus-positions.csv.xz"
# decode_vp's key order; the census test asserts schema equality with the archiver's parts
COLUMNS = ("vehicle_id", "trip_id", "route_id", "direction_id", "start_date", "lat", "lon",
           "bearing", "stop_id", "ts", "occupancy", "fetched_at")


def source(root: Path, day: str) -> Path:
    y, m, _ = day.split("-")
    src = root / "archive" / "nycbuspositions" / y / m / f"{day}-bus-positions.csv.xz"
    if not src.exists():
        url = URL.format(y=y, m=m, day=day)
        print(f"downloading {url}", flush=True)
        src.parent.mkdir(parents=True, exist_ok=True)
        tmp = src.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(src)
    return src


def convert(root: Path, day: str) -> None:
    src = source(root, day)
    with lzma.open(src, "rb") as f:
        raw = pacsv.read_csv(f, convert_options=pacsv.ConvertOptions(
            column_types={"timestamp": pa.string(), "trip_start_date": pa.string(),
                          "stop_id": pa.string(), "occupancy_status": pa.string(),
                          "latitude": pa.float64(), "longitude": pa.float64(),
                          "bearing": pa.float64()},
            strings_can_be_null=True))  # empty field -> NULL, every era, every column

    stamp = raw.column("timestamp")
    if pc.sum(pc.invert(pc.ends_with(stamp, pattern="+00"))).as_py():
        sys.exit(f"nbp {day}: unexpected timestamp format in {src} (not '...+00')")
    ts = pc.strptime(pc.utf8_slice_codeunits(stamp, 0, 19), format="%Y-%m-%d %H:%M:%S",
                     unit="s").cast(pa.int64())
    d0 = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())
    outside = pc.sum(pc.or_(pc.less(ts, d0 - 86400), pc.greater_equal(ts, d0 + 2 * 86400))).as_py()
    if outside:
        sys.exit(f"nbp {day}: {outside} rows with ts outside [D-1, D+2) in {src} "
                 f"(the ms/s timestamp era) - file failed, nothing written")

    occupancy = raw.column("occupancy_status")
    if pc.count_distinct(occupancy.drop_null()).as_py() <= 1:  # a placeholder day (spec E)
        occupancy = pa.nulls(len(raw), pa.string())
    table = pa.table({
        "vehicle_id": raw.column("vehicle_id"),
        "trip_id": raw.column("trip_id"),
        "route_id": raw.column("route_id"),
        "direction_id": pa.nulls(len(raw), pa.int64()),
        "start_date": pc.replace_substring(raw.column("trip_start_date"), pattern="-", replacement=""),
        "lat": raw.column("latitude"),
        "lon": raw.column("longitude"),
        "bearing": raw.column("bearing"),
        "stop_id": raw.column("stop_id"),
        "ts": ts,
        "occupancy": occupancy,
        "fetched_at": pa.nulls(len(raw), pa.int64()),  # no poll clock in the archive
    }, schema=pa.schema([(c, TYPES.get(c, pa.string())) for c in COLUMNS]))
    table = table.sort_by([("vehicle_id", "ascending"), ("ts", "ascending")])

    hours = pc.strftime(table.column("ts").cast(pa.timestamp("s", tz="UTC")), format="%Y-%m-%d %H")
    n = 0
    for key in sorted(pc.unique(hours).to_pylist()):
        date_str, hh = key.split()
        part = table.filter(pc.equal(hours, key))
        out = root / "archive" / "vp" / f"date={date_str}" / f"hour={hh}" / f"part-nbp-{day}.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(part, out, compression="zstd")
        n += part.num_rows
    print(f"nbp {day}: {n} rows -> {root / 'archive' / 'vp'} ({len(pc.unique(hours))} parts)", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", help="UTC day YYYY-MM-DD of the nycbuspositions file")
    args = ap.parse_args()
    datetime.fromisoformat(args.date)  # validate early
    convert(data_root(), args.date)


if __name__ == "__main__":
    main()
