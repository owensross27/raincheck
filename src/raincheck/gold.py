"""`make gold MONTH=` and `make baseline WINDOW=` (ticket 05 / spec I).

gold/cell_hour_speed/month=          rollup of leg_hours: reads service_date in
                                     [month_start - 1, month_end], keeps the month's
                                     Hours, sums only (n_legs, n_vehicles, dist_m_sum,
                                     dt_s_sum, n_dropped_terminal, n_dropped_dark);
                                     dynamic overwrite touches only that month.
gold/cell_hourofweek_baseline/window= dry side only, grain (cell, hour_of_week INT16 in
                                     America/New_York, DST transition hours dropped);
                                     dry = mm_1h < 0.1 AND mm_1h_prev < 0.1 AND the
                                     recovery guard mm_6h < 0.5 (swept in analysis),
                                     joined from precip_cell_hourly src=aorc; mergeable
                                     sums (dist_m_sum_dry, dt_s_sum_dry) beside
                                     speed_dry, n_dry, n_legs_dry.

Run: make gold MONTH=YYYY-MM         (python -m raincheck.gold speed YYYY-MM)
     make baseline WINDOW=w1|w2      (python -m raincheck.gold baseline w1)
"""
import argparse
import calendar
from datetime import date, datetime, timedelta
from pathlib import Path

from pyspark.sql import functions as F

from raincheck.paths import data_root
from raincheck.ref import WINDOWS

NY = "America/New_York"
WINDOW = dict(zip(("w1", "w2"), WINDOWS))
SUMS = ("n_legs", "n_vehicles", "dist_m_sum", "dt_s_sum", "n_dropped_terminal", "n_dropped_dark")


def speed(root: Path, spark, month: str) -> None:
    y, m = map(int, month.split("-"))
    lo = date(y, m, 1) - timedelta(days=1)
    hi = date(y, m, calendar.monthrange(y, m)[1])
    df = (spark.read.parquet(str(root / "silver" / "leg_hours"))
          .where(F.col("service_date").cast("string").between(str(lo), str(hi)))
          .where(F.date_format("hour_end_utc", "yyyy-MM") == month)
          .groupBy("cell", "hour_end_utc", "route_id", "route_class")
          .agg(*(F.sum(c).alias(c) for c in SUMS))
          .withColumn("month", F.lit(month))
          .coalesce(1).sortWithinPartitions("cell", "hour_end_utc", "route_id", "route_class"))
    df.write.partitionBy("month").mode("overwrite").parquet(str(root / "gold" / "cell_hour_speed"))
    print(f"cell_hour_speed month={month}: wrote {root / 'gold' / 'cell_hour_speed'}", flush=True)


def baseline(root: Path, spark, window: str) -> None:
    start, end = WINDOW[window]
    chs = (spark.read.parquet(str(root / "gold" / "cell_hour_speed"))
           .where(f"hour_end_utc > timestamp'{start} 00:00:00' AND "
                  f"hour_end_utc <= timestamp'{end + timedelta(days=1)} 00:00:00'"))
    pc = (spark.read.parquet(str(root / "silver" / "precip_cell_hourly"))
          .where(F.col("src") == "aorc")
          .select("cell", "hour_end_utc", "mm_1h", "mm_1h_prev", "mm_6h"))
    dry = (F.col("mm_1h") < 0.1) & (F.col("mm_1h_prev") < 0.1) & (F.col("mm_6h") < 0.5)
    # the two DST transition hours per year: the local offset changes across this Hour
    not_dst = F.expr(f"from_utc_timestamp(hour_end_utc, '{NY}') - "
                     f"from_utc_timestamp(hour_end_utc - INTERVAL 1 HOUR, '{NY}') = INTERVAL 1 HOUR")
    local = F.from_utc_timestamp("hour_end_utc", NY)
    df = (chs.join(pc, ["cell", "hour_end_utc"])
          .where(dry & not_dst)
          .withColumn("hour_of_week",  # Monday 00 local = 0 .. Sunday 23 local = 167
                      (((F.dayofweek(local) + 5) % 7) * 24 + F.hour(local)).cast("smallint"))
          .groupBy("cell", "hour_of_week")
          .agg((F.sum("dist_m_sum") / F.sum("dt_s_sum")).alias("speed_dry"),
               F.countDistinct("hour_end_utc").alias("n_dry"),
               F.sum("n_legs").alias("n_legs_dry"),
               F.sum("dist_m_sum").alias("dist_m_sum_dry"),
               F.sum("dt_s_sum").alias("dt_s_sum_dry"))
          .withColumn("window", F.lit(window))
          .coalesce(1).sortWithinPartitions("cell", "hour_of_week"))
    df.write.partitionBy("window").mode("overwrite").parquet(
        str(root / "gold" / "cell_hourofweek_baseline"))
    print(f"cell_hourofweek_baseline window={window}: wrote "
          f"{root / 'gold' / 'cell_hourofweek_baseline'}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("speed").add_argument("month", help="YYYY-MM")
    sub.add_parser("baseline").add_argument("window", choices=sorted(WINDOW))
    args = ap.parse_args()
    from raincheck.spark import session

    if args.cmd == "speed":
        datetime.strptime(args.month, "%Y-%m")
        speed(data_root(), session(), args.month)
    else:
        baseline(data_root(), session(), args.window)


if __name__ == "__main__":
    main()
