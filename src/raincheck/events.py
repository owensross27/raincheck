"""`make events DATE=` (ticket 05 / spec E, G): the per-service-day events job. This
ticket derives Legs (enrich.legs, rule set R2) from the Bronze VP `date IN (D, D+1)`
read, keeps Legs whose start Ping has `start_date = D`, and writes Silver `leg_hours`;
ticket 07 extends the same job with Passages and Delay.

silver/leg_hours/service_date=D  one sorted file, grain (cell, hour_end_utc, route_id,
                                 route_class) unique; n_legs, n_vehicles (approx
                                 distinct), dist_m_sum, dt_s_sum, leg_speed_p50 (day
                                 grain only, not mergeable), n_dropped_terminal,
                                 n_dropped_dark. Per-Leg rows are not stored (fog).

Run: make events DATE=YYYY-MM-DD   (python -m raincheck.events YYYY-MM-DD)
"""
import argparse
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

from pyspark.sql import DataFrame, functions as F

from raincheck.enrich import legs
from raincheck.paths import data_root


def bronze_vp(root: Path, spark, day: str) -> DataFrame:
    """Bronze VP for service day D: partitions date IN (D, D+1), whichever exist."""
    d = date.fromisoformat(day)
    vp = root / "archive" / "vp"
    paths = [vp / f"date={x}" for x in (d, d + timedelta(days=1)) if (vp / f"date={x}").exists()]
    if not paths:
        sys.exit(f"events {day}: no Bronze VP under {vp} for {day}")
    return spark.read.option("basePath", str(vp)).parquet(*(str(p) for p in paths))


def leg_hours(root: Path, spark, day: str) -> None:
    lg = legs(bronze_vp(root, spark, day)).where(F.col("start_date") == day.replace("-", ""))
    kept = F.col("dropped").isNull()
    df = (lg.groupBy("cell", "hour_end_utc", "route_id", "route_class")
          .agg(F.count(F.when(kept, 1)).alias("n_legs"),
               F.expr("approx_count_distinct(CASE WHEN dropped IS NULL THEN vehicle_id END)")
                .alias("n_vehicles"),
               F.sum(F.when(kept, F.col("dist_m"))).alias("dist_m_sum"),
               F.sum(F.when(kept, F.col("dt_s"))).alias("dt_s_sum"),
               F.expr("percentile_approx(CASE WHEN dropped IS NULL THEN dist_m / dt_s END, 0.5)")
                .alias("leg_speed_p50"),
               F.count(F.when(F.col("dropped") == "terminal", 1)).alias("n_dropped_terminal"),
               F.count(F.when(F.col("dropped") == "dark", 1)).alias("n_dropped_dark"))
          .coalesce(1).sortWithinPartitions("cell", "hour_end_utc", "route_id", "route_class"))
    staging = root / ".staging" / f"leg_hours_{day}"
    df.write.mode("overwrite").parquet(str(staging))
    out = root / "silver" / "leg_hours" / f"service_date={day}" / "part-00000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    (part,) = staging.glob("part-*.parquet")
    shutil.move(part, out)
    shutil.rmtree(staging)
    print(f"leg_hours service_date={day}: wrote {out}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", help="service day YYYY-MM-DD")
    args = ap.parse_args()
    date.fromisoformat(args.date)  # validate early
    from raincheck.spark import session

    leg_hours(data_root(), session(), args.date)


if __name__ == "__main__":
    main()
