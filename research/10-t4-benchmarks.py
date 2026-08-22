"""10-T4 (ticket 06 / spec I benchmarks, report-only, no gate): gold/cell_hour_speed vs
MTA's published speeds. Two comparisons:

  A. W2 route x day-of-week x hour vs Socrata 58t6-89vi ("Bus Route Segment Speeds
     2023-2024"), segments recombined trip-weighted server-side:
     sum(road_distance x trips) / sum(travel_time x trips).
  B. both windows route x month x day_type vs cudb-vcni ("Bus Speeds: Beginning 2015"),
     recombined as sum(miles) / sum(hours) over periods and boroughs.

Our hour label is hour-ENDING; MTA's hour_of_day is the hour bucket, so we bucket by the
hour-beginning instant (hour_end_utc - 1h) in America/New_York, and take day-of-week /
month / day_type from that same local instant. Ratio = ours_mph / mta_mph. Spearman rank
agreement is computed across routes on route-level space-mean speeds within each
comparison. Socrata CSVs are cached under <root>/ref/src/socrata/.

Writes research/10-t4-benchmark-report.md. Run after the slice is loaded:
  .venv/bin/python research/10-t4-benchmarks.py
"""
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np

from raincheck import duck
from raincheck.paths import data_root

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "research" / "10-t4-benchmark-report.md"
MPH = 2.23693629  # m/s -> mph
NY = "America/New_York"

SEG_URL = ("https://data.ny.gov/resource/58t6-89vi.csv?"
           "$select=route_id,day_of_week,hour_of_day,"
           "sum(road_distance%20*%20bus_trip_count)%20as%20dist_mi,"
           "sum(average_travel_time%20*%20bus_trip_count)%20as%20time_min,"
           "sum(bus_trip_count)%20as%20trips"
           "&$where=year='2023'%20AND%20(month='9'%20OR%20month='10')"
           "&$group=route_id,day_of_week,hour_of_day&$limit=200000")
CUDB_URL = "https://data.ny.gov/resource/cudb-vcni.csv?$limit=200000"


def fetch(root: Path, name: str, url: str) -> Path:
    dst = root / "ref" / "src" / "socrata" / name
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {name}", flush=True)
        tmp = dst.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(dst)
    return dst


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


def dist_stats(r: np.ndarray) -> str:
    q = np.percentile(r, [10, 25, 50, 75, 90])
    return (f"n={r.size}  mean={r.mean():.3f}  "
            + "  ".join(f"p{p}={v:.3f}" for p, v in zip((10, 25, 50, 75, 90), q)))


def ours(root: Path, where: str, keys: str) -> str:
    """Route(+key) space-mean mph from gold/cell_hour_speed, bucketed by the
    hour-beginning instant in America/New_York."""
    return f"""
      SELECT route_id, {keys},
             sum(dist_m_sum) / sum(dt_s_sum) * {MPH} AS ours_mph,
             sum(n_legs) AS n_legs
      FROM read_parquet('{root}/gold/cell_hour_speed/**/*.parquet',
                        hive_partitioning = true, hive_types_autocast = false),
           -- hour_end_utc is TIMESTAMPTZ (Spark parquet, UTC-adjusted); for that type
           -- timezone(tz, x) is instant -> local wall clock (verified: 12:00+00 Aug ->
           -- 08:00). Do not "fix" to AT TIME ZONE 'UTC' - that flips the direction.
           LATERAL (SELECT timezone('{NY}', hour_end_utc - INTERVAL 1 HOUR) AS local_t)
      WHERE {where}
      GROUP BY ALL"""


def main() -> None:
    root = data_root()
    con = duck.connect()
    seg = fetch(root, "58t6-89vi-w2-agg.csv", SEG_URL)
    cudb = fetch(root, "cudb-vcni.csv", CUDB_URL)
    lines = ["# 10-T4: gold/cell_hour_speed vs MTA published speeds (report-only)",
             "",
             f"Built {date.today().isoformat()} against the loaded slice at `{root}`.",
             "",
             "Known biases, named up front (spec I): our chord distance runs 7-15% short of",
             "the path (a chord ratio overstates a slowdown); terminal handling differs (~+3%);",
             "MTA operating time may include layover; August 2021 covers only the 16th onward",
             "(W1 starts mid-month); SBS route ids differ ('M15+' here vs 'M15' + trip_type",
             "SBS there) so SBS rows join only in the cudb trip_type mapping, not by raw id.",
             ""]

    # A. W2 route x day-of-week x hour vs 58t6-89vi (already trip-weighted server-side)
    a = con.execute(f"""
        WITH mta AS (
          SELECT route_id, day_of_week, hour_of_day::INT AS hour_of_day,
                 dist_mi / (time_min / 60.0) AS mta_mph
          FROM read_csv('{seg}') WHERE time_min > 0
        ), mine AS ({ours(root, "hour_end_utc > timestamp'2023-09-01 00:00:00' AND hour_end_utc <= timestamp'2023-11-01 00:00:00'",
                         "strftime(local_t, '%A') AS day_of_week, hour(local_t) AS hour_of_day")})
        SELECT mine.ours_mph / mta.mta_mph AS ratio, mine.ours_mph, mta.mta_mph,
               mine.route_id, mine.n_legs
        FROM mine JOIN mta USING (route_id, day_of_week, hour_of_day)
        WHERE mine.n_legs >= 30""").fetchall()
    ratio = np.array([r[0] for r in a])
    lines += ["## A. W2 route x day-of-week x hour vs 58t6-89vi", "",
              f"- {dist_stats(ratio)}" if a else "- no matched keys"]
    if a:
        by_route: dict[str, list] = {}
        for r in a:
            by_route.setdefault(r[3], []).append((r[1], r[2]))
        routes = {k: (np.mean([x[0] for x in v]), np.mean([x[1] for x in v]))
                  for k, v in by_route.items() if len(v) >= 20}
        o = np.array([v[0] for v in routes.values()])
        m = np.array([v[1] for v in routes.values()])
        lines.append(f"- Spearman rank agreement across {len(routes)} routes "
                     f"(>= 20 matched hours): {spearman(o, m):.3f}")
    lines.append("")

    # B. both windows route x month x day_type vs cudb-vcni
    b = con.execute(f"""
        WITH mta AS (
          SELECT route_id, strftime(month::TIMESTAMP, '%Y-%m') AS month, day_type::INT AS day_type,
                 sum(total_mileage) / sum(total_operating_time) AS mta_mph
          FROM read_csv('{cudb}')
          WHERE month::TIMESTAMP >= timestamp'2021-08-01' AND total_operating_time > 0
          GROUP BY 1, 2, 3
        ), mine AS ({ours(root, "1 = 1",
                         "strftime(local_t, '%Y-%m') AS month, CASE WHEN dayofweek(local_t) IN (0, 6) THEN 2 ELSE 1 END AS day_type")})
        SELECT mine.ours_mph / mta.mta_mph AS ratio, mine.ours_mph, mta.mta_mph,
               mine.route_id, mine.n_legs
        FROM mine JOIN mta USING (route_id, month, day_type)
        WHERE mine.n_legs >= 100""").fetchall()
    ratio = np.array([r[0] for r in b])
    lines += ["## B. route x month x day_type vs cudb-vcni (both windows)", "",
              f"- {dist_stats(ratio)}" if b else "- no matched keys"]
    if b:
        by_route = {}
        for r in b:
            by_route.setdefault(r[3], []).append((r[1], r[2]))
        routes = {k: (np.mean([x[0] for x in v]), np.mean([x[1] for x in v])) for k, v in by_route.items()}
        o = np.array([v[0] for v in routes.values()])
        m = np.array([v[1] for v in routes.values()])
        lines.append(f"- Spearman rank agreement across {len(routes)} routes: {spearman(o, m):.3f}")
    lines += ["",
              "No gate is set on this run (calibration, spec I): a candidate future gate is a",
              "ratio band [0.75, 1.15] plus rank agreement, decided after this first month.", ""]
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
