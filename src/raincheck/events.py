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
                                 (logged, never an abort).
silver/events_view.sql           06's names (pass_lo_ts, pass_hi_ts, sched_ts,
                                 censor_halfwidth_s) over the physical columns.

Run: make events DATE=YYYY-MM-DD   (python -m raincheck.events YYYY-MM-DD)
"""
import argparse
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import pyarrow.parquet as pq
from pyspark.sql import DataFrame, Window, functions as F

from raincheck.enrich import PASSAGE_KEY, legs, passages_matched, passages_observed, sched_ts
from raincheck.paths import data_root

EVENTS_VIEW = """\
-- 06's names over silver/events' physical columns (ticket 07; 08 adds pred_last_ts =
-- arrival_ts + pred_last_off_s). Run from the data root in a UTC DuckDB session.
-- pass_lo/hi are the ping bracket, so only direct Passages have them (an interpolated
-- arrival sits off-centre in its crossing gap; its censor_width_s is still that gap).
-- sched_ts is reconstructed from the integer delay_s: +/- 0.5 s on odd censor widths.
CREATE OR REPLACE VIEW events AS
SELECT e.*,
       CASE WHEN NOT interpolated
            THEN arrival_ts - to_microseconds(censor_width_s::BIGINT * 500000) END AS pass_lo_ts,
       CASE WHEN NOT interpolated
            THEN arrival_ts + to_microseconds(censor_width_s::BIGINT * 500000) END AS pass_hi_ts,
       arrival_ts - to_microseconds(delay_s::BIGINT * 1000000)                     AS sched_ts,
       censor_width_s / 2.0                                                        AS censor_halfwidth_s
FROM read_parquet('silver/events/**/*.parquet',
                  hive_partitioning = true, hive_types_autocast = false) e;
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


def sched_for(root: Path, spark, day: str) -> DataFrame | None:
    """One row per (trip_id, stop_sequence) active on service day D across the loaded
    Picks; a trip_id in several Picks keeps the greatest published (mid-pick revisions
    supersede, spec D). None when no loaded Pick's service_days cover the date."""
    picks = loaded_picks(root)
    if not picks:
        return None
    ids = [p["pick_id"] for p in picks]
    sd = (read_pick_table(root, spark, "service_days", ids)
          .where(F.col("service_date") == date.fromisoformat(day)))
    if not sd.head(1):
        return None
    published = spark.createDataFrame(
        [(p["pick_id"], p["published"]) for p in picks], "pick_id string, published timestamp")
    trips = (read_pick_table(root, spark, "trips", ids)
             .join(sd, ["pick_id", "service_id"], "leftsemi")
             .join(published, "pick_id")
             .withColumn("rk", F.row_number().over(
                 Window.partitionBy("trip_id").orderBy(F.col("published").desc(), "pick_id")))
             .where(F.col("rk") == 1))
    stops = read_pick_table(root, spark, "stops", ids).select(
        "pick_id", "stop_id", F.col("lon").alias("stop_lon"), F.col("lat").alias("stop_lat"), "cell")
    return (read_pick_table(root, spark, "trip_stops", ids)
            .join(trips.select("pick_id", "trip_id", "direction_id", "trip_type"),
                  ["pick_id", "trip_id"])
            .join(stops, ["pick_id", "stop_id"], "left"))


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
                                "direction_id", "trip_type"),
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
         .withColumn("direction_id", F.lit(None).cast("tinyint"))
         .withColumn("trip_type", F.lit(None).cast("string"))
         # without a Pick the trip's endpoints are unknowable (a relief vehicle's first
         # observed flip is a mid-route arrival, not a pull-out): honest NULLs
         .withColumn("is_first", F.lit(None).cast("boolean"))
         .withColumn("is_last", F.lit(None).cast("boolean"))
         .withColumn("pick_gap", F.lit(pick_gap)))

    cols = [*PASSAGE_KEY, "route_id", "schedule_relationship", "stop_sequence", "stop_id",
            "arr", "censor_width_s", "interpolated", "interp_k", "arrival_src",
            "arrival_s", "sched_ts", "delay_s", "stop_lon", "stop_lat", "cell", "pick_id",
            "direction_id", "trip_type", "is_first", "is_last", "pick_gap"]
    ev = o.select(*cols) if m is None else m.select(*cols).unionByName(o.select(*cols))

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
              F.least("censor_width_s", F.lit(32767)).cast("smallint").alias("censor_width_s"),
              "arrival_src", "interpolated", F.col("interp_k").cast("tinyint").alias("interp_k"),
              "is_first", "is_last", "pick_id", "pick_gap", "delay_s",
              "segment_s", "sched_segment_s", "segment_excess_s",
              "schedule_relationship",  # verbatim; NULL on all pre-07 and archive Bronze
              "n_vehicles_on_trip"))

    out = one_file(root, "events", day, ev, ["cell", "arrival_ts"])

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
    matched = ev.where(F.col("pick_id").isNotNull())
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

    d = date.fromisoformat(day)
    tu_paths = [p for x in (d, d + timedelta(days=1))
                for p in [root / "archive" / "tu" / f"date={x}"] if p.exists()]
    if not tu_paths:
        print(f"events {day}: Passage-vs-Prediction agreement n/a (no TU rows; archive era)",
              flush=True)
        return
    tu = (spark.read.option("basePath", str(root / "archive" / "tu"))
          .parquet(*(str(p) for p in tu_paths))
          .where(F.col("start_date") == day.replace("-", ""))
          .where(F.col("arrival_time").isNotNull())
          .withColumn("rk", F.row_number().over(
              Window.partitionBy("trip_id", "stop_id", "vehicle_id", "start_date")
              .orderBy(F.col("fetched_at").desc())))
          .where(F.col("rk") == 1)
          .select("trip_id", "stop_id", "vehicle_id",
                  F.col("arrival_time").alias("pred_ts")))
    j = (ev.where(~F.col("interpolated"))
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
