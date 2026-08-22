"""`make slice` (ticket 06 / spec M step 3): the two-window slice load driver. Converts
the 124 nycbuspositions UTC-day files to Bronze VP with 10-T1 checked per file (rows ==
xz rows, unique (vehicle_id, ts), ts gate, bbox, three route classes - any failure
aborts loudly), runs `events DATE=` for the 122 service days, `gold MONTH=` for the five
slice months, `baseline WINDOW=` for w1/w2, prints stage timings and disk bytes, then
runs the tier-2 gates (the driver's exit code is the gate result). Every stage is
resumable: converted days and existing leg_hours partitions are skipped unless --force.
Ticket 17's full backfill is this same driver over more days.

Low-disk mode (default; ticket 18 scope change 2026-08-22 - no SSD, cloud is Bronze's
durable home, the Mac has single-digit GB free): the driver refuses to start unless the
data root's filesystem has headroom for the remaining peak footprint, processes
day-by-day, and deletes each xz source immediately after its day converts AND its T1
passes (the sources are re-downloadable; deletion strictly follows a green T1, so a
converted day with no xz on resume counts as previously verified). --keep-xz retains
the sources for ticket 18's bucket push.

Run: make slice   (python -m raincheck.slice [--force] [--keep-xz])
"""
import argparse
import lzma
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from raincheck import duck, nbp
from raincheck.paths import data_root
from raincheck.ref import BBOX, WINDOWS


def days(a: date, b: date) -> list[date]:
    return [a + timedelta(n) for n in range((b - a).days + 1)]


FILE_DAYS = [d for a, b in WINDOWS for d in days(a, b + timedelta(days=1))]  # 124 xz files
SERVICE_DAYS = [d for a, b in WINDOWS for d in days(a, b)]                   # 122
MONTHS = sorted({f"{d:%Y-%m}" for d in SERVICE_DAYS})                        # 5


def xz_path(root: Path, day: str) -> Path:
    y, m, _ = day.split("-")
    return root / "archive" / "nycbuspositions" / y / m / f"{day}-bus-positions.csv.xz"


def t1(root: Path, day: str) -> list[str]:
    """10-T1 at slice scale, per source file (its parts carry the source day in the name).
    The rows==xz check runs only while the source exists; low-disk mode deletes the xz
    strictly after a green T1, so an absent source means the check already passed."""
    src = xz_path(root, day)
    parts = f"{root}/archive/vp/*/*/part-nbp-{day}.parquet"
    con = duck.connect()
    errs = []
    n, uniq = con.execute(
        "SELECT count(*), count(DISTINCT (vehicle_id, ts)) FROM read_parquet(?)", [parts]).fetchone()
    if src.exists():
        with lzma.open(src, "rt") as f:
            n_src = sum(1 for _ in f) - 1
        if n != n_src:
            errs.append(f"rows {n} != xz rows {n_src}")
    if uniq != n:
        errs.append(f"{n - uniq} duplicate (vehicle_id, ts)")
    lo = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()) - 86400
    (bad_ts,) = con.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE ts < ? OR ts >= ?",
        [parts, lo, lo + 3 * 86400]).fetchone()
    if bad_ts:
        errs.append(f"{bad_ts} rows outside the ts gate")
    (bad_pos,) = con.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE lon < ? OR lon > ? OR lat < ? OR lat > ?",
        [parts, BBOX[0], BBOX[2], BBOX[1], BBOX[3]]).fetchone()
    if bad_pos:
        errs.append(f"{bad_pos} rows outside the bbox")
    (classes,) = con.execute(
        "SELECT count(DISTINCT CASE "
        "  WHEN regexp_matches(upper(route_id), '^(X|BM|QM|BXM|SIM)') THEN 'express' "
        "  WHEN route_id LIKE '%+' THEN 'sbs' "
        "  WHEN route_id IS NOT NULL THEN 'local' END) FROM read_parquet(?)", [parts]).fetchone()
    if classes != 3:
        errs.append(f"{classes} route classes, expected 3")
    return errs


def gb(path: Path) -> float:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1e9 if path.exists() else 0.0


def headroom_gate(root: Path, keep_xz: bool) -> None:
    """Refuse to start without room for the remaining peak footprint (the 18 scope
    change's replacement for the SSD precondition)."""
    import shutil

    todo_files = sum(1 for d in FILE_DAYS
                     if not any((root / "archive" / "vp").glob(f"date=*/hour=*/part-nbp-{d}.parquet")))
    todo_events = sum(1 for d in SERVICE_DAYS
                      if not all((root / "silver" / t / f"service_date={d}"
                                  / "part-00000.parquet").exists()
                                 for t in ("leg_hours", "events")))  # same check as build_events
    # measured: ~12 MB Bronze + ~10 MB xz per file, ~6 MB leg_hours + ~12 MB events per
    # day (07: the Ida day wrote 12.1 MB); 0.5 GB margin
    need = todo_files * (0.022 if keep_xz else 0.012) + todo_events * 0.018 + 0.5
    free = shutil.disk_usage(root).free / 1e9
    if free < need:
        sys.exit(f"slice: {free:.1f} GB free at {root} < {need:.1f} GB peak footprint - "
                 f"free disk or land ticket 18's cold storage first")
    print(f"slice: headroom ok ({free:.1f} GB free, ~{need:.1f} GB peak)", flush=True)


def convert(root: Path, force: bool, keep_xz: bool) -> None:
    for d in FILE_DAYS:
        day = d.isoformat()
        cached = any((root / "archive" / "vp").glob(f"date=*/hour=*/part-nbp-{day}.parquet"))
        t0 = time.monotonic()
        if force or not cached:
            nbp.convert(root, day)  # sys.exits loudly on the ts gate
            cached = False
        errs = t1(root, day)
        if errs:
            sys.exit(f"slice: T1 FAILED for {day}: {'; '.join(errs)}")
        src = xz_path(root, day)
        if not keep_xz and src.exists():
            src.unlink()  # strictly after a green T1; re-downloadable
        print(f"slice convert {day}: {time.monotonic() - t0:.0f}s"
              f"{' (cached)' if cached else ''} T1 ok", flush=True)


def build_events(root: Path, spark, force: bool) -> None:
    from raincheck import events

    for d in SERVICE_DAYS:
        day = d.isoformat()
        part = "part-00000.parquet"
        lh = root / "silver" / "leg_hours" / f"service_date={day}" / part
        ev = root / "silver" / "events" / f"service_date={day}" / part
        if lh.exists() and ev.exists() and not force:
            print(f"slice events {day}: cached", flush=True)
            continue
        t0 = time.monotonic()
        if force or not lh.exists():
            events.leg_hours(root, spark, day)
        if force or not ev.exists():  # 07: Passages/Delay (pick_gap rows until 16's picks)
            events.events(root, spark, day)
        print(f"slice events {day}: {time.monotonic() - t0:.0f}s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rebuild cached days")
    ap.add_argument("--keep-xz", action="store_true",
                    help="keep xz sources after T1 (for ticket 18's bucket push)")
    args = ap.parse_args()
    root = data_root()
    headroom_gate(root, args.keep_xz)
    marks = [("start", time.monotonic())]
    convert(root, args.force, args.keep_xz)
    marks.append(("convert+T1", time.monotonic()))

    from raincheck import gold
    from raincheck.spark import session

    spark = session()
    build_events(root, spark, args.force)
    marks.append(("events", time.monotonic()))
    for m in MONTHS:
        gold.speed(root, spark, m)
    for w in ("w1", "w2"):
        gold.baseline(root, spark, w)
    marks.append(("gold+baseline", time.monotonic()))

    for stage, prev, now in zip((s for s, _ in marks[1:]), (t for _, t in marks), (t for _, t in marks[1:])):
        print(f"slice: {stage} took {(now - prev) / 60:.1f} min", flush=True)
    for name in ("archive/nycbuspositions", "archive/vp", "silver/leg_hours", "gold"):
        print(f"slice: {name} = {gb(root / name):.2f} GB", flush=True)

    from raincheck import gates

    gates.main()  # exits 1 on a gate failure - the driver's exit code is the gate result


if __name__ == "__main__":
    main()
