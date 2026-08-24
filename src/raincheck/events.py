"""`make events DATE=` (tickets 05, 07 / spec E, F, G): the per-service-day events job.
Derives Legs (enrich.legs, rule set R2) into Silver `leg_hours`, and Passages with Delay
(enrich.passages_*, ADR-0001) into Silver `events`, both from the Bronze VP
`date IN (D, D+1)` read.

silver/leg_hours/service_date=D  one sorted file, grain (cell, hour_end_utc, route_id,
                                 route_class) unique (ticket 05 docstring history).
silver/events/service_date=D     one file sorted (cell, arrival_ts), one row per Passage,
                                 key (start_date, trip_id, stop_sequence, vehicle_id)
                                 unique; Delay by the DST-safe noon rule against the Picks
                                 loaded by `make schedule PICK=`; when no Pick covers the
                                 date the rows carry pick_gap = true and NULL sched_*
                                 (logged, never an abort). Ticket 08: headway columns
                                 (headway_obs_s, headway_sched_s, wait_ok, bunched,
                                 family) and the TU Prediction stream (pred_* churn
                                 features, NULL archive-era; the trip's final stop gets a
                                 tu_last fallback arrival when TU predicted it).
silver/events_view.sql           06's names (pass_lo_ts, pass_hi_ts, sched_ts,
                                 pred_last_ts, censor_halfwidth_s) over the physical
                                 columns.

Run: make events DATE=YYYY-MM-DD   (python -m raincheck.events YYYY-MM-DD)
"""
import argparse
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import pyarrow.parquet as pq
from pyspark.sql import DataFrame, Window, functions as F

from raincheck.enrich import (PASSAGE_KEY, ceil_hour, legs, passages_matched,
                              passages_observed, sched_ts)
from raincheck.paths import data_root

EVENTS_VIEW = """\
-- 06's names over silver/events' physical columns (tickets 07/08). Run from the data
-- root in a UTC DuckDB session.
-- pass_lo/hi are the ping bracket, so only vp_passage rows have them (an interpolated
-- arrival sits off-centre in its crossing gap and a tu_last arrival has no bracket at
-- all - its censor_width_s is NULL).
-- sched_ts is reconstructed from the integer delay_s: +/- 0.5 s on odd censor widths.
CREATE OR REPLACE VIEW events AS
SELECT e.*,
       CASE WHEN arrival_src = 'vp_passage'
            THEN arrival_ts - to_microseconds(censor_width_s::BIGINT * 500000) END AS pass_lo_ts,
       CASE WHEN arrival_src = 'vp_passage'
            THEN arrival_ts + to_microseconds(censor_width_s::BIGINT * 500000) END AS pass_hi_ts,
       arrival_ts - to_microseconds(delay_s::BIGINT * 1000000)                     AS sched_ts,
       arrival_ts + to_microseconds(pred_last_off_s::BIGINT * 1000000)             AS pred_last_ts,
       censor_width_s / 2.0                                                        AS censor_halfwidth_s
FROM read_parquet('silver/events/**/*.parquet', hive_partitioning = true,
                  hive_types_autocast = false, union_by_name = true) e;
"""


def bronze_vp(root: Path, spark, day: str) -> DataFrame:
    """Bronze VP for service day D: partitions date IN (D, D+1), whichever exist."""
    d = date.fromisoformat(day)
    vp = root / "archive" / "vp"
    paths = [vp / f"date={x}" for x in (d, d + timedelta(days=1)) if (vp / f"date={x}").exists()]
    if not paths:
        sys.exit(f"events {day}: no Bronze VP under {vp} for {day}")
    # mergeSchema: parts written before the decoder gained schedule_relationship coexist
    # with parts written after
    return (spark.read.option("basePath", str(vp)).option("mergeSchema", "true")
            .parquet(*(str(p) for p in paths)))


def one_file(root: Path, name: str, day: str, df: DataFrame, sort: list[str]) -> Path:
    """Write one sorted file per service_date partition through .staging (idempotent)."""
    staging = root / ".staging" / f"{name}_{day}"
    df.coalesce(1).sortWithinPartitions(*sort).write.mode("overwrite").parquet(str(staging))
    out = root / "silver" / name / f"service_date={day}" / "part-00000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    (part,) = staging.glob("part-*.parquet")
    shutil.move(part, out)
    shutil.rmtree(staging)
    return out


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
               F.count(F.when(F.col("dropped") == "dark", 1)).alias("n_dropped_dark")))
    out = one_file(root, "leg_hours", day, df, ["cell", "hour_end_utc", "route_id", "route_class"])
    print(f"leg_hours service_date={day}: wrote {out}", flush=True)


# --- Passages and Delay (ticket 07) ----------------------------------------------------

SCHED_TABLES = ("trips", "trip_stops", "stops", "service_days")


def loaded_picks(root: Path) -> list[dict]:
    """ref/picks rows whose schedule tables `make schedule PICK=` has loaded."""
    picks_ref = root / "ref" / "picks"
    if not picks_ref.exists():
        return []
    rows = pq.read_table(picks_ref).to_pylist()
    return [r for r in rows
            if all((root / "silver" / t / f"pick_id={r['pick_id']}").exists()
                   for t in SCHED_TABLES)]


def read_pick_table(root: Path, spark, name: str, pick_ids: list[str]) -> DataFrame:
    base = root / "silver" / name
    paths = [str(base / f"pick_id={p}") for p in pick_ids]
    return spark.read.option("basePath", str(base)).parquet(*paths)


def sched_span(root: Path, spark, lo: date, hi: date) -> DataFrame | None:
    """One row per (service_date, trip_id, stop_sequence) across the loaded Picks for
    service dates in [lo, hi]. Resolver v2's gate applies at the join (spec D): a Pick
    joins a date only when published <= D+1, and a trip_id in several eligible Picks
    keeps the greatest published per date - a mid-pick revision supersedes from its
    fetch date forward, never retroactively. None when no eligible Pick's service_days
    touch the span. Shared by the daily events join (sched_for) and the Gold coverage
    denominator (gold.route)."""
    picks = loaded_picks(root)
    if not picks:
        return None
    ids = [p["pick_id"] for p in picks]
    published = spark.createDataFrame(
        [(p["pick_id"], p["published"]) for p in picks], "pick_id string, published timestamp")
    sd = (read_pick_table(root, spark, "service_days", ids)
          .where(F.col("service_date").between(lo, hi))
          .join(published, "pick_id")
          .where(F.to_date("published") <= F.date_add("service_date", 1)))
    if not sd.head(1):
        return None
    trips = (read_pick_table(root, spark, "trips", ids)
             .join(sd.select("pick_id", "service_id", "service_date", "published"),
                   ["pick_id", "service_id"])
             .withColumn("rk", F.row_number().over(
                 Window.partitionBy("trip_id", "service_date")
                 .orderBy(F.col("published").desc(), "pick_id")))
             .where(F.col("rk") == 1))
    stops = read_pick_table(root, spark, "stops", ids).select(
        "pick_id", "stop_id", F.col("lon").alias("stop_lon"), F.col("lat").alias("stop_lat"), "cell")
    return (read_pick_table(root, spark, "trip_stops", ids)
            .join(trips.select("pick_id", "trip_id", "route_id", "direction_id",
                               "trip_type", "service_date"),
                  ["pick_id", "trip_id"])
            .join(stops, ["pick_id", "stop_id"], "left"))


def sched_for(root: Path, spark, day: str) -> DataFrame | None:
    """sched_span for one service day plus the Pick-side headway columns (spec F / 06
    decision 5): headway_sched_s = gap to the previous scheduled arrival at the same
    route/direction/stop, and family = 'headway' when the route-direction-hour's median
    scheduled headway is <= 600 s (the hour of the scheduled arrival - a pure function
    of the Pick, independent of the observed delay), else 'schedule'. An hour with a
    single scheduled arrival has no headway and is 'schedule'."""
    d = date.fromisoformat(day)
    frame = sched_span(root, spark, d, d)
    if frame is None:
        return None
    w = Window.partitionBy("route_id", "direction_id", "stop_id").orderBy("arrival_s", "trip_id")
    frame = (frame.drop("service_date")
             .withColumn("headway_sched_s",
                         (F.col("arrival_s") - F.lag("arrival_s").over(w)).cast("int"))
             .withColumn("sh", ceil_hour(sched_ts(F.lit(day.replace("-", "")),
                                                  F.col("arrival_s")))))
    fam = (frame.groupBy("route_id", "direction_id", "sh")
           .agg(F.expr("percentile_approx(headway_sched_s, 0.5)").alias("med")))
    return (frame.join(fam, ["route_id", "direction_id", "sh"], "left")
            .withColumn("family", F.when(F.col("med") <= 600, "headway").otherwise("schedule"))
            .drop("sh", "med"))


def warn_unloaded(root: Path, day: str) -> None:
    """A registered Pick whose calendar covers D but whose tables were never loaded is an
    operator gap, not an archive-era pick_gap - say so loudly (spec D: live-era pick_gap
    rows would be a false archive-era signal)."""
    picks_ref = root / "ref" / "picks"
    if not picks_ref.exists():
        return
    d = date.fromisoformat(day)
    loaded = {p["pick_id"] for p in loaded_picks(root)}
    missing = [r for r in pq.read_table(picks_ref).to_pylist()
               if r["pick_id"] not in loaded and r["feed"] != "subway"
               and r["earliest_calendar_date"] and r["latest_calendar_date"]
               and r["earliest_calendar_date"] <= d <= r["latest_calendar_date"]]
    for r in missing:
        print(f"events {day}: WARNING pick {r['pick_id']} ({r['feed']}) covers this date "
              f"but is not loaded - run make schedule PICK={r['pick_id']}", flush=True)


def bronze_tu(root: Path, spark, day: str) -> DataFrame | None:
    """Bronze TU for service day D: partitions date IN (D, D+1), whichever exist. None when
    no TU Bronze exists (the archive era: nycbuspositions has no stop-level TU rows).

    mergeSchema: parts written before the decoder gained direction_id/trip_delay_s/trip_ts/
    header_ts coexist with parts written after. Dropping it does not raise - it SILENTLY
    loses those columns with the row count still correct, which is why raincheck.eras
    checks this reader's columns are PRESENT rather than counting rows."""
    d = date.fromisoformat(day)
    tu = root / "archive" / "tu"
    paths = [tu / f"date={x}" for x in (d, d + timedelta(days=1)) if (tu / f"date={x}").exists()]
    if not paths:
        return None
    return (spark.read.option("basePath", str(tu)).option("mergeSchema", "true")
            .parquet(*(str(p) for p in paths)))


def tu_rows(root: Path, spark, day: str) -> DataFrame | None:
    """Stop-level TU predictions for service day D, one row per (trip_id, vehicle_id,
    stop_id, fetched_at) with `pred` = the predicted arrival epoch. None when no TU
    Bronze exists (the archive era: nycbuspositions has no stop-level TU rows)."""
    tu = bronze_tu(root, spark, day)
    if tu is None:
        return None
    return (tu
            .where((F.col("start_date") == day.replace("-", ""))
                   & F.col("arrival_time").isNotNull() & F.col("vehicle_id").isNotNull()
                   & F.col("stop_id").isNotNull())
            # one row per fetch: an OBA double-publish inside one poll keeps the max
            .groupBy("trip_id", "vehicle_id", "stop_id", "fetched_at")
            .agg(F.max("arrival_time").alias("pred")))


def pred_feats(ev: DataFrame, tu: DataFrame) -> DataFrame:
    """The Prediction churn features per event (06 decision 2 / measured 7), keyed
    (trip_id, vehicle_id, stop_sequence) - unique within one service day. pred_last is
    the latest fetch's prediction; the 10-min error uses the prediction in effect at
    arr - 600 s (fixed-horizon 'delay' is refuted, the churn itself is the feature)."""
    seq = Window.partitionBy("trip_id", "vehicle_id", "stop_id").orderBy("fetched_at")
    t = tu.withColumn("changed", (F.col("pred") != F.lag("pred").over(seq)).cast("int"))
    keys = ev.select("trip_id", "vehicle_id", "stop_id", "stop_sequence", "arr")
    return (keys.join(t, ["trip_id", "vehicle_id", "stop_id"])
            .groupBy("trip_id", "vehicle_id", "stop_id", "stop_sequence", "arr")
            .agg(F.max(F.struct("fetched_at", "pred")).alias("last"),
                 F.min(F.struct("fetched_at", "pred")).alias("first"),
                 (F.max("pred") - F.min("pred")).alias("rng"),
                 F.coalesce(F.sum("changed"), F.lit(0)).alias("nch"),
                 F.max(F.when(F.col("fetched_at") <= F.col("arr") - 600,
                              F.struct("fetched_at", "pred"))).alias("at10"))
            .select("trip_id", "vehicle_id", "stop_sequence",
                    F.round(F.col("last.pred") - F.col("arr")).cast("int")
                     .alias("pred_last_off_s"),
                    (F.col("first.pred") - F.col("first.fetched_at")).cast("int")
                     .alias("pred_first_horizon_s"),
                    F.col("rng").cast("int").alias("pred_range_s"),
                    F.round(F.col("at10.pred") - F.col("arr")).cast("int")
                     .alias("pred_err_10min_s"),
                    F.col("nch").cast("smallint").alias("pred_n_changes")))


def tu_last_rows(m: DataFrame, sched: DataFrame, tu: DataFrame) -> DataFrame:
    """The final stop never yields a VP Passage (06 decision 1); live era it gets a
    fallback arrival from TU's last prediction, tagged tu_last. Gated: the (vehicle,
    trip) must have reached the second-to-last scheduled stop, and the prediction must
    lie after the last observed Passage - a TU series that vanished mid-route with the
    prediction still ahead is a short-turn or reassignment, not an arrival (06 measured
    6), and yields no row. censor_width_s is NULL: there is no ping bracket."""
    mx = sched.groupBy("trip_id").agg(F.max("stop_sequence").alias("last_seq"))
    second = (sched.join(mx, "trip_id").where(F.col("stop_sequence") < F.col("last_seq"))
              .groupBy("trip_id").agg(F.max("stop_sequence").alias("second_seq")))
    vt = (m.groupBy("trip_id", "start_date", "vehicle_id")
          .agg(F.max("stop_sequence").alias("mx_seq"), F.max("arr").alias("last_arr"),
               F.max("route_id").alias("route_id"),
               F.max("schedule_relationship").alias("schedule_relationship")))
    last_stop = (sched.join(mx, "trip_id")
                 .where(F.col("stop_sequence") == F.col("last_seq"))
                 .select("trip_id", "stop_sequence", "stop_id", "arrival_s",
                         "stop_lon", "stop_lat", "cell", "pick_id", "direction_id",
                         "trip_type", "headway_sched_s", "family"))
    pred = (tu.groupBy("trip_id", "vehicle_id", "stop_id")
            .agg(F.max(F.struct("fetched_at", "pred")).alias("lastp")))
    return (vt.join(second, "trip_id").where(F.col("mx_seq") == F.col("second_seq"))
            .join(last_stop, "trip_id")
            .join(pred, ["trip_id", "vehicle_id", "stop_id"])
            .where(F.col("lastp.pred") > F.col("last_arr"))
            .withColumn("arr", F.col("lastp.pred").cast("double"))
            .withColumn("censor_width_s", F.lit(None).cast("long"))
            .withColumn("interpolated", F.lit(False))
            .withColumn("interp_k", F.lit(None).cast("int"))
            .withColumn("arrival_src", F.lit("tu_last"))
            .withColumn("sched_ts", sched_ts(F.col("start_date"), F.col("arrival_s")))
            .withColumn("delay_s", F.round(F.col("arr") - F.unix_timestamp("sched_ts"))
                        .cast("int"))
            .withColumn("is_first", F.lit(False))
            .withColumn("is_last", F.lit(True))
            .withColumn("pick_gap", F.lit(False)))


def events(root: Path, spark, day: str) -> None:
    day8 = day.replace("-", "")
    vp = bronze_vp(root, spark, day).where(F.col("start_date") == day8)
    if "schedule_relationship" not in vp.columns:  # pre-07 Bronze parts
        vp = vp.withColumn("schedule_relationship", F.lit(None).cast("string"))
    # CANCELED filtered (spec F); ADDED/DUPLICATED ride along verbatim as the flag
    vp = vp.where(F.coalesce(F.col("schedule_relationship"), F.lit("")) != "CANCELED")
    warn_unloaded(root, day)
    sched = sched_for(root, spark, day)
    pick_gap = sched is None
    tu = tu_rows(root, spark, day)

    h3 = "ST_H3CellIDs(ST_Point(mid_lon, mid_lat), 8, false)[0]"
    if sched is not None:
        sched = sched.cache()
        trip_index = sched.select("trip_id").distinct()
        matched_vp = vp.join(trip_index, "trip_id", "leftsemi")
        unmatched_vp = vp.join(trip_index, "trip_id", "leftanti")
        firsts = sched.groupBy("trip_id").agg(F.min("stop_sequence").alias("first_seq"),
                                              F.max("stop_sequence").alias("last_seq"))
        m = (passages_matched(matched_vp, sched)
             .join(sched.select("trip_id", "stop_sequence", "stop_id", "arrival_s",
                                "stop_lon", "stop_lat", "cell", "pick_id",
                                "direction_id", "trip_type", "headway_sched_s", "family"),
                   ["trip_id", "stop_sequence"], "left")
             .join(firsts, "trip_id", "left")
             .withColumn("sched_ts", sched_ts(F.col("start_date"), F.col("arrival_s")))
             .withColumn("delay_s", F.round(F.col("arr") - F.unix_timestamp("sched_ts")).cast("int"))
             .withColumn("is_first", F.col("stop_sequence") == F.col("first_seq"))
             .withColumn("is_last", F.col("stop_sequence") == F.col("last_seq"))
             .withColumn("pick_gap", F.lit(False)))
    else:
        m = None
        unmatched_vp = vp

    o = (passages_observed(unmatched_vp)
         .withColumn("cell", F.expr(h3))
         .withColumn("arrival_s", F.lit(None).cast("int"))
         .withColumn("sched_ts", F.lit(None).cast("timestamp"))
         .withColumn("delay_s", F.lit(None).cast("int"))
         .withColumn("stop_lon", F.lit(None).cast("double"))
         .withColumn("stop_lat", F.lit(None).cast("double"))
         .withColumn("pick_id", F.lit(None).cast("string"))
         # direction_id stays: the feed's own value (passages_observed), so a live
         # unmatched trip shares its matched neighbours' headway group; archive rows
         # carry NULL from the converter and group by (route, stop) alone
         .withColumn("trip_type", F.lit(None).cast("string"))
         .withColumn("headway_sched_s", F.lit(None).cast("int"))
         .withColumn("family", F.lit(None).cast("string"))
         # without a Pick the trip's endpoints are unknowable (a relief vehicle's first
         # observed flip is a mid-route arrival, not a pull-out): honest NULLs
         .withColumn("is_first", F.lit(None).cast("boolean"))
         .withColumn("is_last", F.lit(None).cast("boolean"))
         .withColumn("pick_gap", F.lit(pick_gap)))

    cols = [*PASSAGE_KEY, "route_id", "schedule_relationship", "stop_sequence", "stop_id",
            "arr", "censor_width_s", "interpolated", "interp_k", "arrival_src",
            "arrival_s", "sched_ts", "delay_s", "stop_lon", "stop_lat", "cell", "pick_id",
            "direction_id", "trip_type", "headway_sched_s", "family",
            "is_first", "is_last", "pick_gap"]
    parts = [o.select(*cols)]
    if m is not None:
        parts.append(m.select(*cols))
        if tu is not None:
            parts.append(tu_last_rows(m, sched, tu).select(*cols))
    base = parts[0]
    for p in parts[1:]:
        base = base.unionByName(p)
    base = base.persist()  # the headway self-join and the pred join both re-read it
    ev = base

    if tu is not None:
        ev = ev.join(pred_feats(base, tu), ["trip_id", "vehicle_id", "stop_sequence"], "left")
    else:
        for c, t in (("pred_last_off_s", "int"), ("pred_first_horizon_s", "int"),
                     ("pred_range_s", "int"), ("pred_err_10min_s", "int"),
                     ("pred_n_changes", "smallint")):
            ev = ev.withColumn(c, F.lit(None).cast(t))

    # headway_obs_s = gap to the previous different-vehicle arrival at the same route/
    # direction/stop; same-trip followers are excluded too (06 measured 9: an OBA
    # double-publish of one bus under two vehicle_ids would otherwise read as 0 s
    # bunching). Live rows all carry the feed's direction (matched rows the Pick's), so
    # matched and unmatched trips share a group; archive rows are NULL-direction
    # throughout and group by (route, stop) alone.
    # ponytail: O(n^2)-per-stop-group self-join, ~10-100 arrivals per group per day;
    # switch to a run-window (gaps-and-islands over vehicle runs) if a day ever hurts
    prev = base.select(F.col("route_id").alias("p_route"), F.col("direction_id").alias("p_dir"),
                       F.col("stop_id").alias("p_stop"), F.col("arr").alias("p_arr"),
                       F.col("vehicle_id").alias("p_veh"), F.col("trip_id").alias("p_trip"))
    cond = ((F.col("route_id") == F.col("p_route"))
            & F.col("direction_id").eqNullSafe(F.col("p_dir"))
            & (F.col("stop_id") == F.col("p_stop")) & (F.col("p_arr") < F.col("arr"))
            & (F.col("p_veh") != F.col("vehicle_id")) & (F.col("p_trip") != F.col("trip_id")))
    hw = (base.select("trip_id", "vehicle_id", "stop_sequence", "route_id", "direction_id",
                      "stop_id", "arr")
          .join(prev, cond, "left")
          .groupBy("trip_id", "vehicle_id", "stop_sequence", "arr")
          .agg(F.max("p_arr").alias("prev_arr"))
          .select("trip_id", "vehicle_id", "stop_sequence",
                  F.round(F.col("arr") - F.col("prev_arr")).cast("int").alias("headway_obs_s")))
    ev = (ev.join(hw, ["trip_id", "vehicle_id", "stop_sequence"], "left")
          .withColumn("wait_ok", F.col("headway_obs_s") <= F.col("headway_sched_s") + 180)
          .withColumn("bunched", F.col("headway_obs_s") < 0.5 * F.col("headway_sched_s")))

    # stop_sequence tie-break: a clamped-shape interpolation can share its anchor's arr;
    # without it lag() is nondeterministic across reruns
    seg = Window.partitionBy(*PASSAGE_KEY).orderBy("arr", "stop_sequence")
    trip_w = Window.partitionBy("trip_id", "start_date")
    ev = (ev
          .withColumn("segment_s", F.round(F.col("arr") - F.lag("arr").over(seg)).cast("int"))
          .withColumn("sched_segment_s",
                      (F.col("arrival_s") - F.lag("arrival_s").over(seg)).cast("int"))
          .withColumn("segment_excess_s", F.col("segment_s") - F.col("sched_segment_s"))
          .withColumn("n_vehicles_on_trip",
                      F.size(F.collect_set("vehicle_id").over(trip_w)).cast("tinyint"))
          .select(
              "trip_id", "vehicle_id", "route_id", "stop_id",
              F.col("stop_sequence").cast("smallint").alias("stop_sequence"),
              F.col("direction_id").cast("tinyint").alias("direction_id"),
              "trip_type", "stop_lon", "stop_lat", F.col("cell").cast("bigint").alias("cell"),
              F.timestamp_seconds("arr").alias("arrival_ts"),
              # least() skips NULLs, so guard: a tu_last row's NULL bracket must stay NULL
              F.when(F.col("censor_width_s").isNotNull(),
                     F.least("censor_width_s", F.lit(32767)))
               .cast("smallint").alias("censor_width_s"),
              "arrival_src", "interpolated", F.col("interp_k").cast("tinyint").alias("interp_k"),
              "is_first", "is_last", "pick_id", "pick_gap", "delay_s",
              "segment_s", "sched_segment_s", "segment_excess_s",
              "headway_obs_s", "headway_sched_s", "wait_ok", "bunched", "family",
              "schedule_relationship",  # verbatim; NULL on all pre-07 and archive Bronze
              "pred_last_off_s", "pred_first_horizon_s", "pred_range_s",
              "pred_err_10min_s", "pred_n_changes",
              "n_vehicles_on_trip"))

    out = one_file(root, "events", day, ev, ["cell", "arrival_ts"])
    base.unpersist()

    con_rows = spark.read.parquet(str(out)).count()
    gap_rows = spark.read.parquet(str(out)).where("pick_gap").count()
    print(f"events service_date={day}: {con_rows} rows ({gap_rows} pick_gap) -> {out}", flush=True)
    if sched is not None:
        baselines(root, spark, day, out, sched)
        sched.unpersist()
    else:
        print(f"events {day}: coverage / Passage-vs-Prediction baselines n/a "
              f"(no Pick covers the date)", flush=True)

    view = root / "silver" / "events_view.sql"
    view.write_text(EVENTS_VIEW)


def baselines(root: Path, spark, day: str, out: Path, sched) -> None:
    """Regression bounds printed per run (spec Testing / 06): Passage coverage vs the
    scheduled non-terminal arrivals of matched trips, and Passage-vs-Prediction
    agreement when the day has stop-level TU rows (live era only)."""
    ev = spark.read.parquet(str(out))
    # vp_passage/interpolated only: a tu_last terminal row is not a Passage and the
    # denominator below is explicitly non-terminal (ticket 08 review)
    matched = ev.where(F.col("pick_id").isNotNull() & (F.col("arrival_src") != "tu_last"))
    n_matched = matched.count()
    # denominator per (trip, vehicle): a multi-vehicle trip contributes one Passage set
    # per vehicle (16.9% of trip_ids), so per-trip scheduled counts would inflate the ratio
    denom = (matched.select("trip_id", "vehicle_id").distinct()
             .join(sched.groupBy("trip_id").agg((F.count("*") - 1).alias("n")), "trip_id")
             .agg(F.sum("n")).first()[0])
    cov = n_matched / denom if denom else None
    print(f"events {day}: coverage baseline = {n_matched} passages / "
          f"{denom or 0} scheduled non-terminal arrivals of matched (trip, vehicle) pairs"
          f"{f' = {cov:.3f}' if cov else ''} [regression bound]", flush=True)

    bronze = bronze_tu(root, spark, day)
    if bronze is None:
        print(f"events {day}: Passage-vs-Prediction agreement n/a (no TU rows; archive era)",
              flush=True)
        return
    tu = (bronze
          .where(F.col("start_date") == day.replace("-", ""))
          .where(F.col("arrival_time").isNotNull())
          .withColumn("rk", F.row_number().over(
              Window.partitionBy("trip_id", "stop_id", "vehicle_id", "start_date")
              .orderBy(F.col("fetched_at").desc())))
          .where(F.col("rk") == 1)
          .select("trip_id", "stop_id", "vehicle_id",
                  F.col("arrival_time").alias("pred_ts")))
    # vp_passage rows only: a tu_last arrival IS the last prediction (diff 0 by
    # construction) and would inflate the bound; interpolated arrivals are estimates
    j = (ev.where(F.col("arrival_src") == "vp_passage")
         .join(tu, ["trip_id", "stop_id", "vehicle_id"])
         .withColumn("diff", F.abs(F.col("pred_ts") - F.unix_timestamp("arrival_ts"))))
    n = j.count()
    if n:
        within = j.where(F.col("diff") <= 60).count()
        print(f"events {day}: Passage-vs-Prediction agreement |d|<=60s = {within}/{n} "
              f"= {within / n:.3f} [regression bound]", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", help="service day YYYY-MM-DD")
    args = ap.parse_args()
    date.fromisoformat(args.date)  # validate early
    from raincheck.spark import session

    spark = session()
    root = data_root()
    leg_hours(root, spark, args.date)
    events(root, spark, args.date)


if __name__ == "__main__":
    main()
