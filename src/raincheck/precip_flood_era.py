"""`make precip-flood-era` (flood-build ticket 06): the AORC precip spine extended to
cover every union-event Window in the fit era, through the existing per-(src, month)
job with src=aorc pinned - never pooled with MRMS (ADR-0002).

The needed month list is DERIVED from `silver/flood_events`, never typed: a Cell month
is needed if any Window hour falls in it; an hourly month is additionally needed if the
Window's 24 h lookback reaches back into it (the Cell build reads its lookback from
`precip_hourly`, so a Window opening early in a month needs the month before it on disk
or its mm_3h/6h/24h frames are silently short).

The fit era stops at 2025 per the spec's era rules. AORC v1.1 publishes one Zarr per
year and 2026 does not exist, so the 11 union events of 2026 CANNOT take AORC rows;
they are the validation-only / MRMS-replication era and belong to tickets 09 and 18.

Run: make precip-flood-era            (add DRY_RUN=1 to print the plan and stop)
"""
import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from raincheck import duck, precip
from raincheck.paths import data_root

FIT_ERA_LAST_YEAR = 2025  # spec era rules: fit on AORC, union events 2010-2025
MB_PIXEL_MONTH = 12  # measured over 128 months: 9.1 MB Bronze Zarr + 2.8 MB Pixel partition
MB_CELL_MONTH = 24  # measured over 124 months: dense 4,113 Cells x every hour of the month
HEADROOM = 2.0  # the run must fit twice over before it starts
RECEIPT = "_flood_era_receipt.json"


def window_months(windows: list[tuple[datetime, datetime]]) -> tuple[list[str], list[str]]:
    """(hourly months, Cell months) for a list of (window_start, window_end) UTC bounds.
    Cell months hold Window hours; hourly months additionally hold the 24 h lookback."""
    cell: set[str] = set()
    hourly: set[str] = set()
    for start, end in windows:
        s = start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        e = end.astimezone(timezone.utc)
        for target, first in ((cell, s), (hourly, s - timedelta(hours=24))):
            h = first
            while h <= e:
                target.add(f"{h:%Y-%m}")
                h += timedelta(hours=1)
    return sorted(hourly | cell), sorted(cell)


def fit_era_windows(root: Path) -> list[tuple[datetime, datetime]]:
    """The union-event Windows the AORC era owns, from the spine."""
    con = duck.connect()
    rows = con.execute(
        "SELECT window_start_utc, window_end_utc FROM read_parquet(?) "
        "WHERE year(window_start_utc) <= ? ORDER BY 1",
        [f"{root / 'silver' / 'flood_events'}/**/*.parquet", FIT_ERA_LAST_YEAR]).fetchall()
    if not rows:
        sys.exit("precip-flood-era: silver/flood_events is empty - run `make flood-spine` first")
    return rows


def built(root: Path, table: str, month: str) -> bool:
    return (root / "silver" / table / "src=aorc" / f"month={month}").exists()


def disk_gate(root: Path, n_pixel: int, n_cell: int) -> tuple[str, float, float]:
    """(path, needed_gb, free_gb). 'full' builds whole month partitions; 'blocked' means
    the window-sliced flood-only fallback is required and the run must not start."""
    free_gb = shutil.disk_usage(root).free / 1e9
    needed_gb = (n_pixel * MB_PIXEL_MONTH + n_cell * MB_CELL_MONTH) / 1e3
    return ("full" if free_gb >= needed_gb * HEADROOM else "blocked"), needed_gb, free_gb


def assert_no_mrms_in_fit_era(root: Path) -> None:
    """ADR-0002 / never-pooled: no MRMS row may carry a fit-era hour."""
    part = root / "silver" / "precip_cell_hourly" / "src=mrms"
    if not part.exists():
        return
    (n,) = duck.connect().execute(
        "SELECT count(*) FROM read_parquet(?) WHERE year(hour_end_utc) <= ?",
        [f"{part}/**/*.parquet", FIT_ERA_LAST_YEAR]).fetchone()
    if n:
        sys.exit(f"precip-flood-era: {n} MRMS Cell-hour rows carry fit-era hours "
                 "(ADR-0002: the sources are never pooled)")


def assert_window_coverage(root: Path, windows: list[tuple[datetime, datetime]],
                           months: list[str]) -> int:
    """Every Window hour has a non-NULL AORC Cell-hour row for every cells_scored Cell.
    Attainable because ref/assets asserts the permanently-NULL Pixels disjoint from
    cells_scored; a NULL here is a real hole, not the ocean mask."""
    con = duck.connect()
    con.execute("CREATE TABLE win_hours (h TIMESTAMPTZ)")
    con.executemany("INSERT INTO win_hours SELECT unnest(generate_series(?, ?, INTERVAL 1 HOUR))",
                    [[s, e] for s, e in windows])
    con.execute("CREATE TABLE hrs AS SELECT DISTINCT h FROM win_hours")
    con.execute("CREATE TABLE sc AS SELECT cell FROM read_parquet(?) WHERE kind = 'cell' AND scored",
                [f"{root / 'ref' / 'assets'}/**/*.parquet"])
    (n_hours,) = con.execute("SELECT count(*) FROM hrs").fetchone()
    (n_cells,) = con.execute("SELECT count(*) FROM sc").fetchone()
    files = [str(root / "silver" / "precip_cell_hourly" / "src=aorc" / f"month={m}" / "*.parquet")
             for m in months]
    (got,) = con.execute(
        "SELECT count(DISTINCT (p.cell, p.hour_end_utc)) FROM read_parquet(?) p "
        "SEMI JOIN sc ON sc.cell = p.cell SEMI JOIN hrs ON hrs.h = p.hour_end_utc "
        "WHERE p.mm_1h IS NOT NULL", [files]).fetchone()
    want = n_hours * n_cells
    if got != want:
        miss = con.execute(
            "SELECT hrs.h, sc.cell FROM hrs CROSS JOIN sc ANTI JOIN "
            "(SELECT cell, hour_end_utc FROM read_parquet(?) WHERE mm_1h IS NOT NULL) p "
            "ON p.cell = sc.cell AND p.hour_end_utc = hrs.h ORDER BY 1, 2 LIMIT 5",
            [files]).fetchall()
        sys.exit(f"precip-flood-era: Window coverage {got}/{want} Cell-hours "
                 f"({n_hours} hours x {n_cells} cells_scored); first holes: {miss}")
    print(f"coverage OK: {want} Cell-hours ({n_hours} Window hours x {n_cells} cells_scored), "
          "none NULL", flush=True)
    return want


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the plan and stop")
    args = ap.parse_args()
    root = data_root()

    windows = fit_era_windows(root)
    hourly_months, cell_months = window_months(windows)
    todo_h = [m for m in hourly_months if not built(root, "precip_hourly", m)]
    todo_c = [m for m in cell_months if not built(root, "precip_cell_hourly", m)]
    print(f"flood era {FIT_ERA_LAST_YEAR}: {len(windows)} union-event Windows -> "
          f"{len(hourly_months)} Pixel months ({len(todo_h)} to build), "
          f"{len(cell_months)} Cell months ({len(todo_c)} to build)", flush=True)

    path, needed_gb, free_gb = disk_gate(root, len(todo_h), len(todo_c))
    print(f"disk gate: {path} (needs ~{needed_gb:.1f} GB x{HEADROOM:g} headroom, "
          f"{free_gb:.1f} GB free)", flush=True)
    if path == "blocked":
        sys.exit("precip-flood-era: cold storage cannot hold the full-month build; the "
                 "fallback is window-sliced flood-only builds, which is NOT implemented "
                 "(the full path has always fit) - free space or build the slicer")
    if args.dry_run:
        print(f"dry run; would build hourly={todo_h}\n           cell={todo_c}")
        return

    for n, m in enumerate(todo_h, 1):
        print(f"[{n}/{len(todo_h)}] precip_hourly aorc {m}", flush=True)
        precip.hourly(root, "aorc", m)
    if todo_c:
        from raincheck.spark import session

        spark = session()
        for n, m in enumerate(todo_c, 1):
            print(f"[{n}/{len(todo_c)}] precip_cell_hourly aorc {m}", flush=True)
            precip.cell_hourly(root, spark, "aorc", m)

    assert_no_mrms_in_fit_era(root)
    cell_hours = assert_window_coverage(root, windows, cell_months)
    receipt = {"path": path, "fit_era_last_year": FIT_ERA_LAST_YEAR,
               "windows": len(windows), "pixel_months": len(hourly_months),
               "cell_months": len(cell_months), "built_now": len(todo_h) + len(todo_c),
               "covered_cell_hours": cell_hours, "free_gb_at_start": round(free_gb, 1),
               "ran_at": datetime.now(timezone.utc).isoformat()}
    out = root / "archive" / "precip" / "aorc" / RECEIPT
    out.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"wrote {out}: {receipt}", flush=True)


if __name__ == "__main__":
    main()
