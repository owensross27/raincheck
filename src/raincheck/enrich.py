"""Pure DataFrame helpers shared by batch jobs, the streaming job and tests (spec A).
DataFrame API only, no temp views, no I/O except the one `spark.read` inside
`with_live_precip` (research 07 section 2). Grows with tickets 05+."""
import sys
from datetime import datetime
from pathlib import Path

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


def sched_ts(start_date: Column, arrival_s: Column) -> Column:
    """DST-safe GTFS noon rule (spec F / 06): local noon of start_date (YYYYMMDD string)
    in America/New_York minus 12 h plus the Pick's arrival seconds. Anchoring at noon,
    never midnight, is what survives the 23/25-hour DST days."""
    noon = F.to_utc_timestamp(
        F.to_timestamp(F.concat(start_date, F.lit(" 12:00:00")), "yyyyMMdd HH:mm:ss"),
        "America/New_York")
    return noon + F.make_dt_interval(secs=(arrival_s - F.lit(43200)).cast("double"))


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


# --- Row-point enrichment for the live tables (ticket 12, spec J) -----------------------
# Stateless, per row, and the streaming job's only enrichment: the live tables are the raw
# rows plus these three. `legs` cells the *midpoint* of a Leg - a different grain, not a
# second implementation of this one.

def with_cell(df: DataFrame) -> DataFrame:
    """Cell (H3 res 8, INT64 per 09) of the row's own (lon, lat)."""
    return df.withColumn("cell", F.expr("ST_H3CellIDs(ST_Point(lon, lat), 8, false)[0]"))


def with_zone(df: DataFrame, cell_zone: DataFrame) -> DataFrame:
    """Taxi Zone of the row's Cell from `ref/cell_zone` (4,113 rows, one per Cell, so the
    broadcast left join is 1:1). A Cell outside every zone carries NULL zone_id/borough -
    ref/cell_zone already stores it that way."""
    return df.join(F.broadcast(cell_zone.select("cell", "zone_id", "borough")), "cell", "left")


def _no_precip(df: DataFrame) -> DataFrame:
    return (df.withColumn("mm_1h", F.lit(None).cast("float"))
              .withColumn("precip_valid_ts", F.lit(None).cast("timestamp")))


def with_live_precip(df: DataFrame, root: Path, batch_ts: datetime) -> DataFrame:
    """The latest complete precip Hour at `batch_ts`, broadcast-joined on cell (spec J).

    `valid_ts` is hour-ending (ADR-0002) and a STRING partition key, so the newest Hour at
    or before the batch clock is a lexicographic max: a Ping at 20:40 carries the Hour
    ending 20:00. Every row in a batch carries the same `precip_valid_ts` - that is what
    "the latest complete Hour" means, and the reader sees the age.

    The read is INSIDE the caller's foreachBatch on purpose: a DataFrame built once from a
    path keeps its file index and never sees a newly written Hour (measured, research 07 section 0).
    Latest `fetched_at` wins per (cell, valid_ts) before the join - both because that is
    the table's read rule and because it keeps the join 1:1. An absent, empty or unreadable
    table NULLs mm_1h / precip_valid_ts and never fails the batch (spec J).
    """
    table = Path(root) / "live" / "precip_cell"
    if not table.exists():
        return _no_precip(df)
    try:
        live = df.sparkSession.read.parquet(str(table))
        (valid_ts,) = live.where(F.col("valid_ts") <= F.lit(batch_ts.strftime("%Y-%m-%dT%H"))) \
                          .agg(F.max("valid_ts")).first()
    except Exception as exc:  # a torn part or a schema surprise is a NULL batch, never a dead query
        print(f"with_live_precip: {table} unreadable ({exc}) - mm_1h NULL this batch",
              file=sys.stderr, flush=True)
        return _no_precip(df)
    if valid_ts is None:  # the table holds only Hours later than this batch
        return _no_precip(df)
    latest = (live.where(F.col("valid_ts") == F.lit(valid_ts))
              .withColumn("rn", F.row_number().over(
                  Window.partitionBy("cell").orderBy(F.col("fetched_at").desc())))
              .where(F.col("rn") == 1)
              .select("cell", "mm_1h"))
    return (df.join(F.broadcast(latest), "cell", "left")
            .withColumn("precip_valid_ts", F.to_timestamp(F.lit(valid_ts), "yyyy-MM-dd'T'HH")))


# --- Passages (ticket 07 / ADR-0001, spec F) -------------------------------------------

PASSAGE_KEY = ["vehicle_id", "trip_id", "start_date"]


def _dedupe(vp: DataFrame) -> DataFrame:
    """Ping identity for Passages is (vehicle_id, ts, stop_id, lat, lon) (06)."""
    # ponytail: the time axis is ts ordered by (ts, fetched_at); a live frozen-ts
    # republish collapses to a zero-width bracket instead of walking the fetched_at
    # axis - upgrade when live-era events land (archive fetched_at is NULL throughout)
    return vp.dropDuplicates(["vehicle_id", "ts", "stop_id", "lat", "lon"])


def passages_matched(vp: DataFrame, sched: DataFrame) -> DataFrame:
    """Passages for Pings whose trip_id matches a Pick trip active on the service day:
    monotone envelope of static stop_sequence (backward flaps absorbed), every forward
    advance is a Passage of the previous envelope stop at the flip midpoint. A multi-stop
    advance crossed all its intermediate stops inside the same ping gap, so they are
    interpolated within that gap - from the anchor midpoint toward the gap's end -
    proportional to cumulative shape distance (linear in stop index when distances are
    missing or flat). `sched` grain (trip_id, stop_sequence) with stop_id/shape_dist_m.
    Output: PASSAGE_KEY, route_id, stop_sequence, arr (epoch s, double), censor_width_s,
    interpolated, interp_k, arrival_src, mid_lat/mid_lon (NULL here)."""
    w = Window.partitionBy(*PASSAGE_KEY).orderBy(
        "ts", F.col("fetched_at").asc_nulls_first(), "stop_id")  # stop_id: deterministic ties
    # a stop repeated within a trip (loop) keeps its smallest stop_sequence
    seq_map = sched.groupBy("trip_id", "stop_id").agg(
        F.min("stop_sequence").cast("int").alias("seq"))
    p = (_dedupe(vp).select(*PASSAGE_KEY, "route_id", "schedule_relationship",
                            "ts", "fetched_at", "stop_id")
         .join(seq_map, ["trip_id", "stop_id"], "left")
         .withColumn("env", F.max("seq").over(w))
         .withColumn("env_prev", F.lag("env").over(w))
         .withColumn("lo", F.lag("ts").over(w)))
    anchors = (p.where(F.col("env_prev").isNotNull() & (F.col("env") > F.col("env_prev")))
               .select(*PASSAGE_KEY, "route_id", "schedule_relationship",
                       F.col("env_prev").alias("seq_lo"), F.col("env").alias("seq_hi"),
                       F.col("ts").cast("double").alias("hi"),
                       ((F.col("lo") + F.col("ts")) / 2).alias("arr"),
                       (F.col("ts") - F.col("lo")).cast("long").alias("censor_width_s")))
    direct = anchors.select(
        *PASSAGE_KEY, "route_id", "schedule_relationship",
        F.col("seq_lo").alias("stop_sequence"), "arr", "censor_width_s",
        F.lit(False).alias("interpolated"), F.lit(None).cast("int").alias("interp_k"),
        F.lit("vp_passage").alias("arrival_src"))
    dist = sched.select(F.col("trip_id").alias("d_trip"), F.col("stop_sequence").alias("d_seq"),
                        F.col("shape_dist_m").alias("d"))
    gaps = anchors.where(F.col("seq_hi") > F.col("seq_lo") + 1)
    interp = (gaps
              .join(dist.select(F.col("d_trip"), F.col("d_seq"), F.col("d").alias("d_lo")),
                    (gaps.trip_id == F.col("d_trip")) & (gaps.seq_lo == F.col("d_seq")),
                    "left").drop("d_trip", "d_seq")
              .join(dist.select(F.col("d_trip"), F.col("d_seq"), F.col("d").alias("d_hi")),
                    (gaps.trip_id == F.col("d_trip")) & (gaps.seq_hi == F.col("d_seq")),
                    "left").drop("d_trip", "d_seq")
              .withColumn("seq_i", F.explode(F.sequence(F.col("seq_lo") + 1,
                                                        F.col("seq_hi") - 1))))
    # inner: a seq inside the advance that the static does not schedule (non-contiguous
    # stop_sequence) yields no row rather than a stop-less event
    # shape distances must be strictly inside (d_lo, d_hi): a NULL (stop missing from the
    # shape) or a value clamped onto an endpoint (loop-stop cummax in schedule.py) falls
    # back to linear-in-stop-index rather than collapsing onto the anchor midpoint
    usable = (F.col("d_i").isNotNull() & (F.col("d_hi") > F.col("d_lo")) &
              (F.col("d_i") > F.col("d_lo")) & (F.col("d_i") < F.col("d_hi")))
    interp = (interp
              .join(dist.select(F.col("d_trip"), F.col("d_seq"), F.col("d").alias("d_i")),
                    (interp.trip_id == F.col("d_trip")) & (interp.seq_i == F.col("d_seq")),
                    "inner").drop("d_trip", "d_seq")
              .withColumn("frac", F.when(
                  usable, (F.col("d_i") - F.col("d_lo")) / (F.col("d_hi") - F.col("d_lo")))
                  .otherwise((F.col("seq_i") - F.col("seq_lo")).cast("double")
                             / (F.col("seq_hi") - F.col("seq_lo"))))
              .select(*PASSAGE_KEY, "route_id", "schedule_relationship",
                      F.col("seq_i").alias("stop_sequence"),
                      # ms rounding: float32 shape distances would smear exact fractions
                      F.round(F.col("arr") + F.col("frac") * (F.col("hi") - F.col("arr")),
                              3).alias("arr"),
                      "censor_width_s", F.lit(True).alias("interpolated"),
                      (F.col("seq_hi") - F.col("seq_lo")).cast("int").alias("interp_k"),
                      F.lit("interpolated").alias("arrival_src")))
    return direct.unionByName(interp)


def passages_observed(vp: DataFrame) -> DataFrame:
    """Passages for Pings with no static match (a pick_gap date, or a trip absent from
    the Pick): every observed stop_id change is a Passage of the previous stop_id at the
    flip midpoint. No static ordering exists, so stop_sequence is the observed flip
    ordinal, repeats of a stop_id are dropped (absorbs A-B-A flap artifacts; loop trips
    lose their second visit), nothing is interpolated and the position midpoint rides
    along for the Cell. The feed's direction_id rides along too (live Bronze carries it
    100%; archive NULL) so an unmatched live trip joins the same headway group as its
    matched neighbours (ticket 08 review). Replaced wholesale when a Pick lands
    (ticket 16)."""
    w = Window.partitionBy(*PASSAGE_KEY).orderBy(
        "ts", F.col("fetched_at").asc_nulls_first(), "stop_id")  # stop_id: deterministic ties
    p = (_dedupe(vp).where(F.col("trip_id").isNotNull() & F.col("stop_id").isNotNull())
         .select(*PASSAGE_KEY, "route_id", "schedule_relationship", "direction_id",
                 "ts", "fetched_at", "stop_id", "lat", "lon")
         .withColumn("prev_stop", F.lag("stop_id").over(w))
         .withColumn("lo", F.lag("ts").over(w))
         .withColumn("lo_lat", F.lag("lat").over(w))
         .withColumn("lo_lon", F.lag("lon").over(w)))
    flips = (p.where(F.col("prev_stop").isNotNull() & (F.col("stop_id") != F.col("prev_stop")))
             .withColumn("rn", F.row_number().over(
                 Window.partitionBy(*PASSAGE_KEY, "prev_stop").orderBy("lo")))
             .where(F.col("rn") == 1))
    return (flips
            .withColumn("stop_sequence", F.row_number().over(
                Window.partitionBy(*PASSAGE_KEY).orderBy("lo")))
            .select(*PASSAGE_KEY, "route_id", "schedule_relationship", "stop_sequence",
                    F.col("direction_id").cast("tinyint").alias("direction_id"),
                    F.col("prev_stop").alias("stop_id"),
                    ((F.col("lo") + F.col("ts")) / 2).alias("arr"),
                    (F.col("ts") - F.col("lo")).cast("long").alias("censor_width_s"),
                    F.lit(False).alias("interpolated"), F.lit(None).cast("int").alias("interp_k"),
                    F.lit("vp_passage").alias("arrival_src"),
                    ((F.col("lo_lat") + F.col("lat")) / 2).alias("mid_lat"),
                    ((F.col("lo_lon") + F.col("lon")) / 2).alias("mid_lon")))
