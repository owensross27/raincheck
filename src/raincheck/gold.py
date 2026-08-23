"""`make gold MONTH=` and `make baseline WINDOW=` (tickets 05, 08 / spec I).

gold/cell_hour_speed/month=          rollup of leg_hours: reads service_date in
                                     [month_start - 1, month_end], keeps the month's
                                     Hours, sums only (n_legs, n_vehicles, dist_m_sum,
                                     dt_s_sum, n_dropped_terminal, n_dropped_dark);
                                     dynamic overwrite touches only that month.
gold/cell_hour_route/month=          rollup of events, grain (cell, hour_end_utc,
                                     route_id, direction_id): n_events, late_share
                                     (delay_s > 300) / early_share (< -60) applied here
                                     only, mean_segment_excess_s, ewt_s by the renewal
                                     formula E[h^2]/2E[h] observed minus scheduled,
                                     bunched_share, wait_ok_share, coverage (n_events /
                                     scheduled arrivals of that Cell-hour-route),
                                     vp_coverage; no precip columns (joined at read).
gold/cell_hourofweek_baseline/window= dry side only, grain (cell, hour_of_week INT16 in
                                     America/New_York, DST transition hours dropped);
                                     dry = mm_1h < 0.1 AND mm_1h_prev < 0.1 AND the
                                     recovery guard mm_6h < 0.5 (swept in analysis),
                                     joined from precip_cell_hourly src=aorc; mergeable
                                     sums (dist_m_sum_dry, dt_s_sum_dry) beside
                                     speed_dry, n_dry, n_legs_dry.

Run: make gold MONTH=YYYY-MM         (python -m raincheck.gold month YYYY-MM: both tables)
     make baseline WINDOW=w1|w2      (python -m raincheck.gold baseline w1)
"""
import argparse
import calendar
from datetime import date, datetime, timedelta
from pathlib import Path

from pyspark.sql import functions as F

from raincheck.enrich import ceil_hour, sched_ts
from raincheck.paths import data_root
from raincheck.ref import WINDOWS

NY = "America/New_York"
WINDOW = dict(zip(("w1", "w2"), WINDOWS))
SUMS = ("n_legs", "n_vehicles", "dist_m_sum", "dt_s_sum", "n_dropped_terminal", "n_dropped_dark")
ROUTE_GRAIN = ("cell", "hour_end_utc", "route_id", "direction_id")


def month_span(month: str) -> tuple[date, date]:
    """[month_start - 1, month_end]: the day-before catch is the service day whose late
    hours spill into the month (spec I's read rule, shared by both rollups)."""
    y, m = map(int, month.split("-"))
    return date(y, m, 1) - timedelta(days=1), date(y, m, calendar.monthrange(y, m)[1])


def speed(root: Path, spark, month: str) -> None:
    lo, hi = month_span(month)
    df = (spark.read.parquet(str(root / "silver" / "leg_hours"))
          .where(F.col("service_date").cast("string").between(str(lo), str(hi)))
          .where(F.date_format("hour_end_utc", "yyyy-MM") == month)
          .groupBy("cell", "hour_end_utc", "route_id", "route_class")
          .agg(*(F.sum(c).alias(c) for c in SUMS))
          .withColumn("month", F.lit(month))
          .coalesce(1).sortWithinPartitions("cell", "hour_end_utc", "route_id", "route_class"))
    df.write.partitionBy("month").mode("overwrite").parquet(str(root / "gold" / "cell_hour_speed"))
    print(f"cell_hour_speed month={month}: wrote {root / 'gold' / 'cell_hour_speed'}", flush=True)


def route(root: Path, spark, month: str) -> None:
    """gold/cell_hour_route (ticket 08 / spec I). The Hour is the event's arrival hour;
    the coverage denominator is the Pick's scheduled arrivals binned by their own
    scheduled hour - a delayed bus counts in the hour it arrived, so a group's coverage
    can exceed 1 and is NULL where the schedule put no arrivals (or on pick_gap /
    unmatched rows, whose delay and headway columns are NULL throughout). The
    denominator is schedule-complete (terminal arrivals included: live-era obs carries
    tu_last terminal rows); events' printed baseline is a different, VP-only bound."""
    from raincheck.events import sched_span

    lo, hi = month_span(month)
    ev = (spark.read.option("mergeSchema", "true").parquet(str(root / "silver" / "events"))
          .where(F.col("service_date").cast("string").between(str(lo), str(hi)))
          .withColumn("hour_end_utc", ceil_hour(F.col("arrival_ts")))
          .where(F.date_format("hour_end_utc", "yyyy-MM") == month))
    # mergeSchema unions only schemas that exist in some footer - a tree of pre-08
    # partitions has no headway columns at all, so guard them in (NULL) rather than abort
    for c, t in (("headway_obs_s", "int"), ("headway_sched_s", "int"),
                 ("wait_ok", "boolean"), ("bunched", "boolean")):
        if c not in ev.columns:
            ev = ev.withColumn(c, F.lit(None).cast(t))
    delayed = F.count(F.when(F.col("delay_s").isNotNull(), 1))
    both = F.col("headway_obs_s").isNotNull() & F.col("headway_sched_s").isNotNull()
    ho = F.when(both, F.col("headway_obs_s").cast("double"))
    hs = F.when(both, F.col("headway_sched_s").cast("double"))
    g = (ev.groupBy(*ROUTE_GRAIN)
         .agg(F.count("*").alias("n_events"),
              # late/early cutoffs applied here only, never baked into Silver (06)
              (F.count(F.when(F.col("delay_s") > 300, 1)) / delayed).alias("late_share"),
              (F.count(F.when(F.col("delay_s") < -60, 1)) / delayed).alias("early_share"),
              F.avg("segment_excess_s").alias("mean_segment_excess_s"),
              # EWT = AWT - SWT, the renewal formula E[h^2]/2E[h] on BOTH sides (06
              # decision 5; never sched/2), over the rows where both headways exist
              (F.sum(ho * ho) / (2 * F.sum(ho))
               - F.sum(hs * hs) / (2 * F.sum(hs))).alias("ewt_s"),
              F.avg(F.col("bunched").cast("int")).alias("bunched_share"),
              F.avg(F.col("wait_ok").cast("int")).alias("wait_ok_share"),
              F.avg((F.col("arrival_src") == "vp_passage").cast("int")).alias("vp_coverage")))
    sched = sched_span(root, spark, lo, hi)
    if sched is not None:
        # only the built service days: a group on an unbuilt day never joins anyway
        # (its hour_end_utc carries the date), and the filter cuts the schedule
        # fan-out ~len(span)/len(built) - measured 50M rows/month unfiltered
        built = [r[0] for r in ev.select("service_date").distinct().collect()]
        sa = (sched.where(F.col("service_date").isin(built))
              .withColumn("hour_end_utc", ceil_hour(sched_ts(
                  F.date_format("service_date", "yyyyMMdd"), F.col("arrival_s"))))
              .where(F.date_format("hour_end_utc", "yyyy-MM") == month)
              .groupBy(*ROUTE_GRAIN).agg(F.count("*").alias("arrivals_sched")))
        g = (g.join(sa, list(ROUTE_GRAIN), "left")
             .withColumn("coverage", F.col("n_events") / F.col("arrivals_sched")))
    else:
        g = g.withColumn("coverage", F.lit(None).cast("double"))
    out = (g.select(*ROUTE_GRAIN, "n_events", "late_share", "early_share",
                    "mean_segment_excess_s", "ewt_s", "bunched_share", "wait_ok_share",
                    "coverage", "vp_coverage")
           .withColumn("month", F.lit(month))
           .coalesce(1).sortWithinPartitions(*ROUTE_GRAIN))
    out.write.partitionBy("month").mode("overwrite").parquet(str(root / "gold" / "cell_hour_route"))
    print(f"cell_hour_route month={month}: wrote {root / 'gold' / 'cell_hour_route'}", flush=True)


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
    sub.add_parser("month").add_argument("month", help="YYYY-MM (cell_hour_speed + cell_hour_route)")
    sub.add_parser("speed").add_argument("month", help="YYYY-MM")
    sub.add_parser("route").add_argument("month", help="YYYY-MM")
    sub.add_parser("baseline").add_argument("window", choices=sorted(WINDOW))
    args = ap.parse_args()
    from raincheck.spark import session

    if args.cmd == "baseline":
        baseline(data_root(), session(), args.window)
        return
    datetime.strptime(args.month, "%Y-%m")
    root, spark = data_root(), session()
    if args.cmd in ("speed", "month"):
        speed(root, spark, args.month)
    if args.cmd in ("route", "month"):
        route(root, spark, args.month)


if __name__ == "__main__":
    main()
