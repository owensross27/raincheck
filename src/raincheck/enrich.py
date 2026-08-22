"""Pure DataFrame helpers shared by batch jobs, the streaming job and tests (spec A).
DataFrame API only, no temp views, no I/O. Grows with tickets 05+."""
from pyspark.sql import Column, DataFrame, Window, functions as F


def ceil_hour(ts: Column) -> Column:
    """Hour-ending label of an instant: exactly on the hour stays in that Hour, one
    microsecond after rolls forward (08-T5). Joins precip on (src, cell, hour_end_utc)."""
    trunc = F.date_trunc("hour", ts)
    return F.when(trunc == ts, ts).otherwise(trunc + F.expr("INTERVAL 1 HOUR"))


def route_class(route_id: Column) -> Column:
    """Permanently the pick-free rule (spec G): part of the leg_hours / cell_hour_speed
    key, so it must never change when a Pick lands."""
    return (F.when(F.upper(route_id).rlike("^(X|BM|QM|BXM|SIM)"), "express")
            .when(route_id.endswith("+"), "sbs")
            .otherwise("local"))


def legs(vp: DataFrame) -> DataFrame:
    """Rule set R2 (spec G) over Bronze VP Pings: one row per candidate Leg with
    `dropped` NULL (kept), 'dark' (dt_s > 300) or 'terminal' (stationary run-end,
    counts carried). Trip-change pairs, null-trip Pings and teleports (> 30 m/s at
    dt_s <= 300) yield no row. Cell = H3 res 8 of the midpoint (mean lat/lon);
    Hour = ceil_hour(t0 + dt/2); geodesic distance."""
    v = Window.partitionBy("vehicle_id").orderBy("ts")
    # one Ping per (vehicle_id, ts): on a live-feed repeated ts keep the earliest fetched_at
    pings = (vp.withColumn("rn", F.row_number().over(
                 Window.partitionBy("vehicle_id", "ts").orderBy(F.col("fetched_at").asc_nulls_first())))
               .where(F.col("rn") == 1)
               # gaps-and-islands: a run = a contiguous stretch of one vehicle's Pings with
               # the same (trip_id, start_date); returning to a trip_id later is a new run
               .withColumn("new_run", (~(F.col("trip_id").eqNullSafe(F.lag("trip_id").over(v)) &
                                         F.col("start_date").eqNullSafe(F.lag("start_date").over(v)))).cast("int"))
               .withColumn("run_id", F.sum("new_run").over(v)))
    r = Window.partitionBy("vehicle_id", "run_id").orderBy("ts")
    run = Window.partitionBy("vehicle_id", "run_id")
    flip = (~F.col("stop_id").eqNullSafe(F.col("stop_id1"))).cast("long")
    pair = (pings.where(F.col("trip_id").isNotNull())
            .select("vehicle_id", "trip_id", "route_id", "start_date", "run_id",
                    "ts", "lat", "lon", "stop_id",
                    F.lead("ts").over(r).alias("ts1"), F.lead("lat").over(r).alias("lat1"),
                    F.lead("lon").over(r).alias("lon1"), F.lead("stop_id").over(r).alias("stop_id1"))
            .where(F.col("ts1").isNotNull())
            .withColumn("dt_s", (F.col("ts1") - F.col("ts")).cast("long"))
            .withColumn("dist_m", F.expr("ST_DistanceSpheroid(ST_Point(lon, lat), ST_Point(lon1, lat1))"))
            .withColumn("flip", flip)
            .withColumn("cum_flips", F.sum(flip).over(r))
            .withColumn("total_flips", F.sum(flip).over(run)))
    # drop a Leg only if stationary (< 25 m) AND before the run's first stop_id flip,
    # after its last, or in a run that never flips
    terminal_zone = ((F.col("total_flips") == 0) | (F.col("cum_flips") == 0) |
                     ((F.col("cum_flips") == F.col("total_flips")) & (F.col("flip") == 0)))
    dropped = (F.when(F.col("dt_s") > 300, "dark")
                .when((F.col("dist_m") < 25) & terminal_zone, "terminal"))
    return (pair.where(~((F.col("dt_s") <= 300) & (F.col("dist_m") / F.col("dt_s") > 30)))
            .withColumn("mid_lat", (F.col("lat") + F.col("lat1")) / 2)
            .withColumn("mid_lon", (F.col("lon") + F.col("lon1")) / 2)
            .withColumn("mid_ts", F.timestamp_seconds((F.col("ts") + F.col("ts1")) / 2))
            .select("vehicle_id", "trip_id", "route_id", "start_date",
                    route_class(F.col("route_id")).alias("route_class"),
                    F.expr("ST_H3CellIDs(ST_Point(mid_lon, mid_lat), 8, false)[0]").alias("cell"),
                    ceil_hour(F.col("mid_ts")).alias("hour_end_utc"),
                    "dist_m", "dt_s", dropped.alias("dropped"),
                    "mid_lon", "mid_lat"))  # for 10-T5's RS_Values probe; aggregates ignore them
