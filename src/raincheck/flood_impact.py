"""Impact evidence (flood-build ticket 16 / spec "Impact signals").

What the floods did to service, as EVIDENCE and never as a feature. Two sides:

  subway   subwaydata.nyc per-day CSVs -> per (complex_id, NY hour) call counts and
           worst headway, ratioed against same-weekday local controls (D+-7, D+-14,
           event days excluded). The files are TRIP-START keyed, so a day's hours 00-05
           live in the PREVIOUS day's file: measured on 2023-09-29, hour 00 reads 341
           calls without the union and 4,601 with it (92.6% undercount), so every day is
           read as file(D) UNION file(D-1) and filtered to D's NY hours afterwards.
  bus      gold/cell_hour_speed sums-merged per (cell, hour) against the dry
           gold/cell_hourofweek_baseline of the window the day falls in.

Attribution controls ride along with the subway ratio, because a complex can lose trains
for reasons that have nothing to do with water:
  route-mix residual   expected calls = sum over routes of (that complex-hour-route's
                       control median) x (that route's SYSTEM-WIDE ratio this hour).
                       resid_ratio = actual / expected: 1.0 means "exactly what the
                       system-wide route cuts already explain".
  neighbor control     nbr_ratio = this complex's service_ratio / the median
                       service_ratio of the same-line complexes that hour (a complex on
                       several lines takes the median of its lines' own medians).

What the evidence can and cannot carry (measured 2026-08-23, day-type-matched placebo days
13 weeks off each covered event day): caught complexes per WEEKDAY run median 5 on event days
against 4 on clean ones - the median event day is not readable. WEEKEND event days (median 34)
are not readable at all: scheduled work shuts whole segments, which trips the same rule a flood
does and takes the same-line neighbours down with it, so the neighbour control cannot see it
(clean weekends run median 36). What does read is the tail - Ida 2021-09-02 (157), 2023-09-29
(98), 2026-02-23 (93) against a clean-weekday maximum of 23. Any panel using this says so.

Licensing: subwaydata.nyc publishes no data license (only an MIT tool licence). The
snapshots therefore live under <root>/snapshots/subwaydata - outside <root>/archive, the
only tree `make coldpush` mirrors - and the derived numbers are local-page-only. No new
Silver table: the aggregates are build assets under the same snapshot root.

Run: python -m raincheck.flood_impact fetch     (snapshot every day the corpus needs)
     python -m raincheck.flood_impact agg       (per-day aggregates, resumable)
     python -m raincheck.flood_impact build     (ratios + coverage.json)
"""
import argparse
import collections
import json
import shutil
import tarfile
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from raincheck import duck
from raincheck.paths import data_root
from raincheck.ref import WINDOWS

# subwaydata.nyc's own stated span (research/subway-rt-archives.md, re-probed 2026-08-23).
ERA_LO, ERA_HI = date(2021, 4, 1), date(2026, 8, 15)
URL = "https://subwaydata.nyc/data/subwaydatanyc_{d}_csv.tar.xz"
CONTROL_OFFSETS = (-14, -7, 7, 14)  # same weekday, local: kills era drift and pick changes

# Frozen "caught" rule for the impact read - evidence display only, never a threshold the
# model sees. A bare "some hour lost half its trains" catches 386 of 445 complexes on
# 2023-09-29 and 101 on the quiet control day 2023-09-11: overnight service is sparse
# enough that any complex trips it. The rule below adds what the ticket's attribution
# controls are for - the loss must survive the system-wide route mix AND the same-line
# neighbours, on a hour with real baseline service, for two consecutive DAYTIME hours.
# Measured 2026-08-23 over all 76 covered event days: 2/445 on the control day,
# 83/445 on 2023-09-29, 113/445 on Ida (2021-09-02), median 8 across event days.
CAUGHT_SERVICE = 0.5    # service_ratio at or under this, OR
CAUGHT_GAP = 2.0        # max_gap_ratio at or over this
CAUGHT_RESID = 0.8      # and not explained by the system-wide route mix
CAUGHT_NBR = 0.8        # and worse than the same-line neighbours
CAUGHT_MIN_BASE = 5     # and a baseline hour with real service
CAUGHT_MIN_CTL = 2      # over at least two control days: one day is not a baseline
CAUGHT_HOURS = (6, 21)  # daytime NY hours, inclusive
CAUGHT_CONSEC = 2       # sustained: two consecutive qualifying hours


def root_dir(root: Path | None = None) -> Path:
    return Path(root or data_root()) / "snapshots" / "subwaydata"


# ---- snapshots ---------------------------------------------------------------------

def snapshot(d: date, root: Path | None = None) -> Path:
    """One day's CSV tarball, fetched only when missing, written through .part."""
    path = root_dir(root) / "raw" / f"{d:%Y-%m}" / f"subwaydatanyc_{d}_csv.tar.xz"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        urllib.request.urlretrieve(URL.format(d=d), tmp)
        tmp.replace(path)
    return path


def event_days(root: Path | None = None) -> list[date]:
    con = duck.connect()
    rows = con.sql(
        "SELECT DISTINCT unnest(generate_series(day_start, day_end, INTERVAL 1 DAY))::DATE d "
        f"FROM read_parquet('{Path(root or data_root()) / 'silver' / 'flood_events'}/**/*.parquet') "
        "ORDER BY 1").fetchall()
    return [r[0] for r in rows]


def corpus(root: Path | None = None) -> tuple[list[date], dict[date, list[date]]]:
    """The event days inside the subwaydata era, and each one's control days."""
    evs = set(event_days(root))
    days = [d for d in sorted(evs) if ERA_LO <= d <= ERA_HI]
    ctl = {d: [d + timedelta(k) for k in CONTROL_OFFSETS
               if ERA_LO <= d + timedelta(k) <= ERA_HI and d + timedelta(k) not in evs]
           for d in days}
    return days, ctl


def fetch(root: Path | None = None, workers: int = 8) -> list[date]:
    """Every day the corpus reads, plus each one's D-1 (the 00-05 union)."""
    days, ctl = corpus(root)
    want = set(days) | {c for cs in ctl.values() for c in cs}
    want |= {d - timedelta(1) for d in want}
    want = sorted(d for d in want if ERA_LO <= d <= ERA_HI)
    missing = [d for d in want if not snapshot_path(d, root).exists()]
    print(f"subwaydata: {len(want)} days needed, {len(missing)} to fetch", flush=True)
    failed = []
    with ThreadPoolExecutor(workers) as pool:
        for d, err in pool.map(lambda x: _try(x, root), missing):
            if err:
                failed.append(d)
                print(f"  {d}: {err}", flush=True)
    print(f"subwaydata: {len(missing) - len(failed)} fetched, {len(failed)} failed", flush=True)
    return failed


def snapshot_path(d: date, root: Path | None = None) -> Path:
    return root_dir(root) / "raw" / f"{d:%Y-%m}" / f"subwaydatanyc_{d}_csv.tar.xz"


def _try(d: date, root: Path | None) -> tuple[date, str | None]:
    try:
        snapshot(d, root)
        return d, None
    except Exception as e:  # a missing day is a coverage fact, not a build failure
        return d, str(e)


def extract(d: date, into: Path, root: Path | None = None) -> tuple[Path, Path] | None:
    """(trips.csv, stop_times.csv) for one day, unpacked from its tarball."""
    tar = snapshot_path(d, root)
    if not tar.exists():
        return None
    out = []
    with tarfile.open(tar) as t:
        for member in ("trips", "stop_times"):
            name = f"subwaydatanyc_{d}_{member}.csv"
            src = t.extractfile(name)
            if src is None:
                return None
            dst = into / name
            with dst.open("wb") as fh:
                shutil.copyfileobj(src, fh)
            out.append(dst)
    return out[0], out[1]


# ---- per-day aggregates -------------------------------------------------------------

STOP_MAP = """
CREATE OR REPLACE TEMP TABLE stop_complex AS
SELECT unnest(gtfs_stop_id) AS base, complex_id, line
FROM read_parquet('{assets}/**/*.parquet') WHERE kind = 'station'
"""

# calls: one row per (trip, stop) call, deduped, with the gap to the previous call at the
# same complex taken over the UNIONED two-day window so hour 00's gap is a real one.
DAY_SQL = """
WITH raw AS (
  SELECT s.trip_uid, s.stop_id, t.route_id,
         coalesce(s.arrival_time, s.departure_time) AS ts
  FROM read_csv([{stop_times}], union_by_name = true) s
  JOIN read_csv([{trips}], union_by_name = true) t USING (trip_uid)
  WHERE coalesce(s.arrival_time, s.departure_time) IS NOT NULL
), calls AS (
  SELECT DISTINCT ON (r.trip_uid, r.stop_id)
         c.complex_id, r.route_id, r.ts,
         (to_timestamp(r.ts) AT TIME ZONE 'America/New_York') AS ny
  FROM raw r JOIN stop_complex c ON c.base = regexp_replace(r.stop_id, '[NS]$', '')
), gapped AS (
  SELECT complex_id, route_id, ny,
         ts - lag(ts) OVER (PARTITION BY complex_id ORDER BY ts) AS gap_s
  FROM calls
), kept AS (
  SELECT complex_id, route_id, ny::DATE AS day, hour(ny)::SMALLINT AS hour, gap_s
  FROM gapped WHERE ny::DATE = DATE '{day}'
)
SELECT complex_id, route_id, day, hour, count(*)::INTEGER AS n_calls,
       max(gap_s)::INTEGER AS max_gap_s
FROM kept GROUP BY ALL
"""


def agg_path(d: date, root: Path | None = None) -> Path:
    return root_dir(root) / "agg" / f"{d:%Y-%m}" / f"{d}.parquet"


def aggregate(d: date, root: Path | None = None, force: bool = False) -> Path | None:
    """(complex_id, route_id, hour) call counts and worst headway for one NY day."""
    out = agg_path(d, root)
    if out.exists() and not force:
        return out
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        files = [f for f in (extract(x, tmp, root) for x in (d - timedelta(1), d)) if f]
        if not files:
            return None
        con = duck.connect()
        con.execute(STOP_MAP.format(assets=Path(root or data_root()) / "ref" / "assets"))
        sql = DAY_SQL.format(
            day=d,
            trips=", ".join(f"'{f[0]}'" for f in files),
            stop_times=", ".join(f"'{f[1]}'" for f in files))
        rel = con.sql(sql)
        out.parent.mkdir(parents=True, exist_ok=True)
        rel.write_parquet(str(out), compression="zstd")
    return out


def aggregate_all(root: Path | None = None, force: bool = False) -> int:
    days, ctl = corpus(root)
    want = sorted(set(days) | {c for cs in ctl.values() for c in cs})
    done = 0
    for i, d in enumerate(want, 1):
        if aggregate(d, root, force):
            done += 1
        if i % 25 == 0:
            print(f"  aggregated {i}/{len(want)}", flush=True)
    print(f"subwaydata: {done}/{len(want)} days aggregated", flush=True)
    return done


# ---- ratios --------------------------------------------------------------------------

RATIO_SQL = """
WITH day AS (SELECT * FROM read_parquet({day_files})),
     ctl AS (SELECT * FROM read_parquet({ctl_files})),
-- complex-hour totals, event day and controls
 d AS (SELECT complex_id, hour, sum(n_calls) AS n_calls, max(max_gap_s) AS max_gap_s
       FROM day GROUP BY ALL),
 c AS (SELECT complex_id, hour, day, sum(n_calls) AS n_calls, max(max_gap_s) AS max_gap_s
       FROM ctl GROUP BY ALL),
 base AS (SELECT complex_id, hour, count(*) AS n_ctl,
                 median(n_calls) AS base_calls, median(max_gap_s) AS base_gap
          FROM c GROUP BY ALL),
-- route mix: each route's system-wide ratio this hour, applied to the control mix
 dr AS (SELECT route_id, hour, sum(n_calls) AS n FROM day GROUP BY ALL),
 cr AS (SELECT route_id, hour, median(n) AS n FROM
          (SELECT route_id, hour, day, sum(n_calls) AS n FROM ctl GROUP BY ALL) GROUP BY ALL),
 sysr AS (SELECT dr.route_id, dr.hour, dr.n / nullif(cr.n, 0) AS r
          FROM dr JOIN cr USING (route_id, hour)),
 cbase AS (SELECT complex_id, route_id, hour, median(n_calls) AS n
           FROM (SELECT complex_id, route_id, hour, day, sum(n_calls) AS n_calls
                 FROM ctl GROUP BY ALL) GROUP BY ALL),
 expect AS (SELECT complex_id, hour, sum(cbase.n * coalesce(sysr.r, 1)) AS n_expect
            FROM cbase LEFT JOIN sysr USING (route_id, hour) GROUP BY 1, 2),
-- FULL JOIN, not LEFT: an hour with NO trains at all has no row on the day side, and a
-- total outage is exactly what this table exists to record - it must read 0, not vanish
 ratio AS (
   SELECT complex_id, hour, coalesce(d.n_calls, 0) AS n_calls, d.max_gap_s,
          base.n_ctl, base.base_calls, base.base_gap, expect.n_expect,
          coalesce(d.n_calls, 0) / nullif(base.base_calls, 0) AS service_ratio,
          d.max_gap_s / nullif(base.base_gap, 0) AS max_gap_ratio,
          coalesce(d.n_calls, 0) / nullif(expect.n_expect, 0) AS resid_ratio
   FROM d FULL JOIN base USING (complex_id, hour)
          LEFT JOIN expect USING (complex_id, hour)),
 lines AS (SELECT DISTINCT complex_id, line FROM read_parquet('{assets}/**/*.parquet')
           WHERE kind = 'station' AND line IS NOT NULL),
-- a complex can sit on several lines: the peer level is the median over its lines'
-- own median service_ratio, so a multi-line complex is not counted once per line
 peer AS (SELECT l.line, r.hour, median(r.service_ratio) AS med
          FROM ratio r JOIN lines l USING (complex_id) GROUP BY 1, 2),
 nbr AS (SELECT l.complex_id, p.hour, median(p.med) AS peer_med
         FROM lines l JOIN peer p USING (line) GROUP BY 1, 2),
 named AS (SELECT complex_id, string_agg(DISTINCT line, ' + ' ORDER BY line) AS line
           FROM lines GROUP BY 1)
SELECT DATE '{day}' AS day, r.complex_id, named.line, r.hour, r.n_calls, r.max_gap_s,
       r.n_ctl, r.base_calls, r.base_gap, r.service_ratio, r.max_gap_ratio, r.resid_ratio,
       r.service_ratio / nullif(nbr.peer_med, 0) AS nbr_ratio
FROM ratio r LEFT JOIN nbr USING (complex_id, hour) LEFT JOIN named USING (complex_id)
ORDER BY r.complex_id, r.hour
"""


def ratios(d: date, controls: list[date], root: Path | None = None):
    """One event day's complex-hour ratios, or None when nothing was snapshotted."""
    day_f = [str(agg_path(d, root))] if agg_path(d, root).exists() else []
    ctl_f = [str(agg_path(c, root)) for c in controls if agg_path(c, root).exists()]
    if not day_f or not ctl_f:
        return None
    con = duck.connect()
    return con.sql(RATIO_SQL.format(
        day=d, day_files=day_f, ctl_files=ctl_f,
        assets=Path(root or data_root()) / "ref" / "assets")).arrow().read_all()


BUS_SQL = """
WITH ev AS (SELECT DISTINCT unnest(generate_series(day_start, day_end, INTERVAL 1 DAY))::DATE d
            FROM read_parquet('{silver}/flood_events/**/*.parquet')),
 h AS (SELECT cell, hour_end_utc,
              (hour_end_utc AT TIME ZONE 'America/New_York') AS ny,
              sum(dist_m_sum) AS dist_m, sum(dt_s_sum) AS dt_s, sum(n_legs) AS n_legs
       FROM read_parquet('{gold}/cell_hour_speed/**/*.parquet') GROUP BY ALL),
 e AS (SELECT h.*, ny::DATE AS day,
              ((dayofweek(ny) + 6) % 7 * 24 + hour(ny))::SMALLINT AS hour_of_week,
              CASE WHEN ny::DATE BETWEEN DATE '{w1lo}' AND DATE '{w1hi}' THEN 'w1'
                   WHEN ny::DATE BETWEEN DATE '{w2lo}' AND DATE '{w2hi}' THEN 'w2' END AS win
       FROM h JOIN ev ON ev.d = ny::DATE),
 b AS (SELECT cell, hour_of_week, "window", speed_dry, dist_m_sum_dry, dt_s_sum_dry
       FROM read_parquet('{gold}/cell_hourofweek_baseline/**/*.parquet',
                         hive_partitioning = true, hive_types_autocast = false))
SELECT e.day, e.cell, e.hour_end_utc, hour(e.ny)::SMALLINT AS hour, e.n_legs,
       e.dist_m / nullif(e.dt_s, 0) AS speed_mps, b.speed_dry, b."window",
       (e.dist_m / nullif(e.dt_s, 0)) / nullif(b.speed_dry, 0) AS speed_ratio
FROM e LEFT JOIN b ON b.cell = e.cell AND b.hour_of_week = e.hour_of_week
                  AND b."window" = e.win
ORDER BY e.day, e.cell, e.hour_end_utc
"""


def bus(root: Path | None = None):
    """Bus Speed ratios on event days: Cell-hour sums merged across routes, over the dry
    hour-of-week baseline of whichever measurement window carries that Cell-hour.
    A day outside both measurement windows has no dry baseline at all (the live era, e.g.
    2026-08-20): the ratio stays NULL rather than borrowing the other window's speeds.
    DuckDB's dayofweek is 0=Sunday; gold's hour_of_week is Monday-based (raincheck.enrich),
    hence the +6 %% 7 shift - copying the Spark expression across engines ships a day off."""
    r = Path(root or data_root())
    con = duck.connect()
    (w1lo, w1hi), (w2lo, w2hi) = WINDOWS
    return con.sql(BUS_SQL.format(gold=r / "gold", silver=r / "silver",
                                  w1lo=w1lo, w1hi=w1hi,
                                  w2lo=w2lo, w2hi=w2hi)).arrow().read_all()


# ---- the placebo read ----------------------------------------------------------------

PLACEBO_SHIFT = 91  # 13 weeks: same weekday, same-ish season, a different storm history


def placebo_days(root: Path | None = None) -> dict[date, date]:
    """A clean twin for each covered event day, 13 weeks away (same weekday, so the base
    rate is day-type matched). Weekends are swamped by scheduled work - a weekend event
    day can only be read against a weekend placebo - so the pairing is not optional.
    Days with no clean twin either side are dropped from the base rate, not substituted."""
    evs = set(event_days(root))
    dirty = {e + timedelta(k) for e in evs for k in range(-14, 15)}
    out: dict[date, date] = {}
    for d in corpus(root)[0]:
        for k in (PLACEBO_SHIFT, -PLACEBO_SHIFT):
            t = d + timedelta(k)
            if ERA_LO <= t <= ERA_HI and t not in dirty and t not in out.values():
                out[d] = t
                break
    return out


def placebo(root: Path | None = None) -> dict[str, int]:
    """The caught count on each placebo day - the base rate the event days are read
    against. Fetches and aggregates those days on first run."""
    twins = placebo_days(root)
    print(f"placebo: {len(twins)} clean twins for {len(corpus(root)[0])} covered event days",
          flush=True)
    out = {}
    for i, d in enumerate(sorted(twins.values()), 1):
        ctl = [d + timedelta(k) for k in CONTROL_OFFSETS]
        for x in [d] + ctl:
            for y in (x, x - timedelta(1)):
                if ERA_LO <= y <= ERA_HI:
                    _try(y, root)
            aggregate(x, root)
        t = ratios(d, ctl, root)
        if t is not None:
            out[str(d)] = len(caught(t))
        if i % 10 == 0:
            print(f"  placebo {i}/{len(twins)}", flush=True)
    return out


# ---- the published object ------------------------------------------------------------

def _median(xs: list[int]) -> float:
    xs = sorted(xs)
    return 0.0 if not xs else (xs[len(xs) // 2] if len(xs) % 2 else
                               (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2)


def _daytype(counts: dict[str, int], kind: str) -> dict:
    xs = [v for k, v in counts.items()
          if (date.fromisoformat(k).weekday() >= 5) == (kind == "weekend")]
    xs = sorted(xs)
    return {"days": len(xs), "median_caught": _median(xs),
            "p90_caught": xs[int(0.9 * len(xs)) - 1] if xs else 0,
            "max_caught": max(xs) if xs else 0}


def build(root: Path | None = None) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq

    r = root_dir(root)
    days, ctl = corpus(root)
    tables = [t for t in (ratios(d, ctl[d], root) for d in days) if t is not None]
    caught_counts = {str(t.column("day")[0].as_py()): len(caught(t)) for t in tables}
    subway = pa.concat_tables(tables) if tables else None
    b = bus(root)
    (r / "impact").mkdir(parents=True, exist_ok=True)
    if subway is not None:
        pq.write_table(subway, r / "impact" / "subway_complex_hour.parquet", compression="zstd")
    pq.write_table(b, r / "impact" / "bus_cell_hour.parquet", compression="zstd")

    pl = placebo(root)
    con = duck.connect()
    all_days = event_days(root)
    sub_days = sorted({d.as_py() for d in subway.column("day")}) if subway is not None else []
    bus_days = sorted({d.as_py() for d in b.column("day")})
    n = len(all_days)
    both = set(sub_days) & set(bus_days)
    neither = n - len(set(sub_days) | set(bus_days))
    ev = con.sql("SELECT count(*) FROM read_parquet('"
                 f"{Path(root or data_root()) / 'silver' / 'flood_events'}/**/*.parquet')"
                 ).fetchone()[0]
    cov = {
        "spine_version": con.sql(
            "SELECT any_value(spine_version) FROM read_parquet('"
            f"{Path(root or data_root()) / 'silver' / 'flood_events'}/**/*.parquet')").fetchone()[0],
        "events": ev, "event_days": n,
        "subway_era": [str(ERA_LO), str(ERA_HI)],
        "subway_days": len(sub_days), "subway_share": round(len(sub_days) / n, 4),
        "bus_days": len(bus_days), "bus_share": round(len(bus_days) / n, 4),
        "both_days": len(both),
        "neither_days": neither, "neither_share": round(neither / n, 4),
        "caught_rule": {"service_ratio_max": CAUGHT_SERVICE, "max_gap_ratio_min": CAUGHT_GAP,
                        "resid_ratio_max": CAUGHT_RESID, "nbr_ratio_max": CAUGHT_NBR,
                        "min_base_calls": CAUGHT_MIN_BASE, "min_control_days": CAUGHT_MIN_CTL,
                        "hours": list(CAUGHT_HOURS),
                        "consecutive_hours": CAUGHT_CONSEC},
        "caught_per_day": caught_counts,
        "caught_placebo": pl,
        "caught_median_event_day": _median(list(caught_counts.values())),
        "caught_median_placebo_day": _median(list(pl.values())),
        # only interpretable within day type: weekends are dominated by scheduled work
        "caught_by_daytype": {kind: {"event": _daytype(caught_counts, kind),
                                     "placebo": _daytype(pl, kind)}
                              for kind in ("weekday", "weekend")},
        "note": ("evidence and display only - never a model feature and never a detector "
                 "input; subwaydata.nyc carries no data license, so these numbers are "
                 "local-page-only and the snapshots never leave <root>/snapshots"),
    }
    (r / "impact" / "coverage.json").write_text(json.dumps(cov, indent=2) + "\n")
    print(json.dumps(cov, indent=2), flush=True)
    return cov


def caught(table, complexes: set[str] | None = None) -> set[str]:
    """The complexes of ONE day's ratio table that trip the frozen caught rule.

    Pure over the table - the test oracle and the panel read the same function."""
    hits: dict[str, set[int]] = collections.defaultdict(set)
    lo, hi = CAUGHT_HOURS
    cols = [table.column(n).to_pylist() for n in
            ("complex_id", "hour", "service_ratio", "max_gap_ratio", "resid_ratio",
             "nbr_ratio", "base_calls", "n_ctl")]
    for cid, hr, sr, gr, res, nbr, base, n_ctl in zip(*cols):
        if complexes is not None and cid not in complexes:
            continue
        if not lo <= hr <= hi or (base or 0) < CAUGHT_MIN_BASE or (n_ctl or 0) < CAUGHT_MIN_CTL:
            continue
        lost = (sr is not None and sr <= CAUGHT_SERVICE) or (
            gr is not None and gr >= CAUGHT_GAP)
        # a NULL control is not an exoneration: an unexplained loss stays caught
        if lost and (res or 0) <= CAUGHT_RESID and (nbr or 0) <= CAUGHT_NBR:
            hits[cid].add(hr)
    return {c for c, hs in hits.items()
            if any(all(h + k in hs for k in range(CAUGHT_CONSEC)) for h in hs)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("cmd", choices=("fetch", "agg", "build"))
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    if a.cmd == "fetch":
        fetch()
    elif a.cmd == "agg":
        aggregate_all(force=a.force)
    else:
        build()


if __name__ == "__main__":
    main()
