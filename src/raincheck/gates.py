"""`make gates` (ticket 05 / spec Testing, tier 2): the slice-scale acceptance runner.
Wired: 10-T3 (the Ida gate: citywide space-mean chord Speed for the storm hours over
the median of the same hour-of-week citywide value across the other eight dry weeks of
the window, computed from gold/cell_hour_speed, never the baseline table) and 10-T6
(footprint Cells/day, 0 Legs in AORC-NULL Cells, terminal-drop share storm vs control).
Report-only slots for 10-T4 (Socrata benchmarks) and 10-T5 (Product 3) land with
ticket 06. Reads Gold and Silver with DuckDB; no Spark.

Run: make gates   (python -m raincheck.gates)
"""
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from raincheck import duck
from raincheck.paths import data_root
from raincheck.ref import WINDOWS

IDA_GATED = [datetime(2021, 9, 2, h, tzinfo=timezone.utc) for h in (3, 4)]
REPORTED = [datetime(2021, 9, 2, 2, tzinfo=timezone.utc)] + [
    datetime(2023, 9, 29, h, tzinfo=timezone.utc) for h in range(10, 22)]
TABLES = ("gold/cell_hour_speed", "silver/leg_hours", "silver/precip_cell_hourly")


READ = "read_parquet(?, hive_partitioning = true, hive_types_autocast = false)"


def glob(root: Path, name: str) -> str:
    return f"{root / name}/**/*.parquet"


def citywide(con, root: Path, hours: list[datetime]) -> dict:
    """{hour: (space_mean_speed, n_legs)} from gold/cell_hour_speed."""
    ph = ", ".join("?" * len(hours))
    rows = con.execute(
        f"SELECT hour_end_utc, sum(dist_m_sum) / sum(dt_s_sum), coalesce(sum(n_legs), 0) "
        f"FROM {READ} WHERE hour_end_utc IN ({ph}) GROUP BY 1",
        [glob(root, "gold/cell_hour_speed"), *hours]).fetchall()
    return {h: (s, n) for h, s, n in rows}


def drop_share(con, root: Path, hours: list[datetime]) -> float | None:
    """Terminal drops as a share of candidate Legs, pooled over the given Hours."""
    if not hours:
        return None
    ph = ", ".join("?" * len(hours))
    (s,) = con.execute(
        f"SELECT sum(n_dropped_terminal)::DOUBLE "
        f"  / nullif(sum(n_legs) + sum(n_dropped_terminal) + sum(n_dropped_dark), 0) "
        f"FROM {READ} WHERE hour_end_utc IN ({ph})",
        [glob(root, "gold/cell_hour_speed"), *hours]).fetchone()
    return s


def dry_controls(con, root: Path, h: datetime) -> list[datetime]:
    """Same hour-of-week over the window's other weeks, each < 0.1 mm citywide (AORC)."""
    start, end = next(w for w in WINDOWS if w[0].year == h.year)
    lo = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    hi = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1)
    cands = [h + timedelta(weeks=k) for k in range(-10, 11)
             if k and lo < h + timedelta(weeks=k) <= hi]
    ph = ", ".join("?" * len(cands))
    rows = con.execute(
        f"SELECT hour_end_utc, avg(mm_1h) FROM {READ} "
        f"WHERE src = 'aorc' AND hour_end_utc IN ({ph}) GROUP BY 1",
        [glob(root, "silver/precip_cell_hourly"), *cands]).fetchall()
    return sorted(h for h, mm in rows if mm is not None and mm < 0.1)


def t3(con, root: Path) -> tuple[bool, dict[datetime, list[datetime]]]:
    ok = True
    controls: dict[datetime, list[datetime]] = {}
    print("10-T3 (Ida gate) - ratio = storm citywide space-mean / median of dry control weeks")
    for h in IDA_GATED + REPORTED:
        controls[h] = dry_controls(con, root, h)
        cw = citywide(con, root, [h] + controls[h])
        speed, n_legs = cw.get(h, (None, 0))
        vals = [cw[c][0] for c in controls[h] if c in cw and cw[c][0] is not None]
        med = statistics.median(vals) if vals else None
        ratio = speed / med if speed is not None and med else None
        gated = h in IDA_GATED
        if gated:
            passed = ratio is not None and ratio <= 0.85 and n_legs >= 15000
            ok &= passed
            status = "PASS" if passed else "FAIL"
        else:
            status = "report"
        print(f"  {h:%Y-%m-%d %H}Z: speed={speed and f'{speed:.2f}'} m/s n_legs={n_legs} "
              f"controls={len(vals)} median={med and f'{med:.2f}'} "
              f"ratio={ratio and f'{ratio:.3f}'} [{status}]")
    return ok, controls


def t6(con, root: Path, controls: dict[datetime, list[datetime]]) -> bool:
    print("10-T6 (Leg sanity)")
    lh = glob(root, "silver/leg_hours")
    days, cells = con.execute(
        f"SELECT count(*), avg(c) FROM "
        f"(SELECT service_date, count(DISTINCT cell) AS c FROM {READ} GROUP BY 1)", [lh]).fetchone()
    print(f"  footprint: {cells and f'{cells:.0f}'} Cells/day over {days} days (expect ~1,146) [report]")
    (null_legs,) = con.execute(
        f"SELECT coalesce(sum(l.n_legs), 0) FROM {READ} l JOIN "
        f"(SELECT cell FROM {READ} "
        f" WHERE src = 'aorc' GROUP BY cell HAVING count(mm_1h) = 0) d USING (cell)",
        [lh, glob(root, "silver/precip_cell_hourly")]).fetchone()
    print(f"  Legs in AORC-NULL Cells: {null_legs} (gate: 0) [{'PASS' if null_legs == 0 else 'FAIL'}]")
    ctrl_hours = sorted({c for h in IDA_GATED for c in controls.get(h, [])})
    s_storm = drop_share(con, root, IDA_GATED)
    s_ctrl = drop_share(con, root, ctrl_hours)
    if s_storm is None or s_ctrl is None:
        print("  terminal-drop share: not computable (no storm or control hours) [FAIL]")
        return False
    close = abs(s_storm - s_ctrl) <= 0.01
    print(f"  terminal-drop share: storm={s_storm:.4f} control={s_ctrl:.4f} "
          f"(gate: |diff| <= 0.01) [{'PASS' if close else 'FAIL'}]")
    return null_legs == 0 and close


def main() -> None:
    root = data_root()
    missing = [n for n in TABLES if not any((root / n).rglob("*.parquet"))]
    if missing:
        print(f"slice not loaded: {', '.join(missing)} empty under {root} - "
              f"run make nbp/events/gold (and precip) first")
        return
    con = duck.connect()
    ok, controls = t3(con, root)
    ok &= t6(con, root, controls)
    print("10-T4 (Socrata benchmarks): report-only slot, lands with ticket 06")
    print("10-T5 (Product 3 raster comparison): report-only slot, lands with ticket 06")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
