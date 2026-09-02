"""Live impact overlays (flood-build ticket 17 / spec "Impact signals (live)"; seam 3):
what the water did to SERVICE, beside the tiers that say where water is likely.

TWO OVERLAYS, TWO GRAINS, TWO FILES, and never two kinds in one legend:

    files/impact.json          bus, CELL grain     <- gold/cell_hour_speed
    files/impact-subway.json   subway, COMPLEX grain <- archive/subway_tu

BOTH ARE IMPACT AND NEITHER IS EVER A DETECTOR INPUT. `LABEL` rides on both payloads,
at the top level and again inside `strings`, because a consequence layer drawn beside a
cause layer is exactly the thing a reader merges by accident. Nothing here is imported by
`flood_detect`, and nothing here reaches `files/flood.json` - both files are VP/TU-derived
and therefore live on the GATED side of the lineage gate, in family `impact`.

WHY THEY ARE GREY TODAY, AND WHY THAT IS THE DESIGNED RENDER RATHER THAN A GAP.
An overlay that paints a number it cannot defend is worse than one that paints nothing,
so each side has ONE condition it must clear before a colour is emitted at all, and both
are MEASURED here every cycle rather than assumed:

  bus     a ratio needs a CAPTURE-ERA hour-of-week baseline (`window=LIVE_WINDOW`), and
          the two on disk (`w1`, `w2`) are the 2021/2023 BACKFILL windows - a live Speed
          over a 2021 baseline is a claim about five years of route change, not about
          rain. Absent that partition the Cells ship their counts and NO `ratio` key, and
          MapLibre's ["!", ["has", p]] paints them grey (frontend 05's own rule).
  subway  the stop-row-disappearance inference has never been LEVEL-COMPARED against
          subwaydata.nyc, because the two corpora do not overlap by a single day
          (`level_check`, computed from the two day sets, never hard-coded). So the
          absolute rate is not offered as a rate: what ships is each complex against the
          CITYWIDE MEDIAN OF THE SAME HOUR OF THE SAME SOURCE, which is a within-source
          comparison and needs no cross-source calibration to be readable.

THE READS PUT THEIR PROJECTION AND PREDICATE INSIDE THE READ'S OWN STATEMENT, and that
is a memory contract rather than style - this tick runs in cloud 05's Deployment, limited
to 768 MiB, already peaking near 500 MiB. `duck.table()` binds the path as a PARAMETER,
so a `.filter()/.project()` chain or a view queried afterwards cannot push into the scan:
flood 15 measured `flood_truth.alert_rows` at 5,000 MiB / 9.4 s for SIX rows that way
against 173 MiB / 0.25 s in one statement. Both reads here are also PARTITION-BOUNDED by
directory name before a parquet is opened, the same shape `flood_panel.newest_stamp` uses.

SUBWAYDATA NUMBERS NEVER APPEAR HERE. `flood_impact` (subwaydata.nyc, no published data
licence) is not imported, and the honesty caveats below are the SENTENCES that
measurement produced, never the counts behind them - those stay in
`<root>/snapshots/subwaydata/impact/coverage.json`, off every host. `release_check`
asserts the non-import for `flood_panel`; the same rule is why this module states it.

Run: python -m raincheck.flood_overlay          (one read against the real root, no write)
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from raincheck import daily, duck, flood_detect as fd, live_export
from raincheck.paths import as_root, data_root
from raincheck.query import pack

# The label, verbatim on both payloads. Ticket 17's whole point in one string.
LABEL = "impact - never a detector input"
NEVER_INPUT = ("These layers show what happened to SERVICE. They are evidence beside the "
               "detector, never evidence inside it: no number on this page feeds the "
               "flood model, the exposure fit or any tier.")

FAMILY = "impact"
BUS_FILE, SUBWAY_FILE = "impact.json", "impact-subway.json"
FILES = (BUS_FILE, SUBWAY_FILE)

NY = ZoneInfo("America/New_York")

# ---- the bus side ---------------------------------------------------------------------

BUS_TABLE = "gold/cell_hour_speed"
BASE_TABLE = "gold/cell_hourofweek_baseline"

# THE CAPTURE-ERA BASELINE PARTITION, and it is named rather than inferred on purpose.
# `gold/cell_hourofweek_baseline` is partitioned by `window`, and the two that exist are
# the 2021 and 2023 BACKFILL measurement windows (`ref.WINDOWS`, named w1/w2 by
# `gold.WINDOW`). Selecting "the newest window" or "not w1/w2" would read whichever
# partition happened to appear; naming the one partition this overlay may use means the
# backfill baselines cannot be read here by any accident, including a new window landing.
LIVE_WINDOW = "live"
# ... and a baseline hour needs at least this many SAME-WEEKDAY days behind it. The
# baseline's own `n_dry` is count(DISTINCT hour_end_utc) per (cell, hour_of_week), and for
# a fixed hour-of-week each distinct hour is a different week - so n_dry IS the number of
# same-weekday baselines, and one day is not a baseline.
MIN_BASE_DAYS = 2

# The freshness budget the page graduates from an AGE to a VERDICT (frontend 05 asked for
# one; `budget: null` on the layer row renders an age and no verdict). A Cell-hour reaches
# Gold through the NIGHTLY, and a service day's Legs run `daily.TAIL_H` UTC hours into the
# next day - so the newest closed hour is at worst one nightly cycle plus that tail behind
# the clock. TAIL_H is imported, never re-typed; `daily` costs this pod nothing beyond
# `paths` and the stdlib.
NIGHTLY_H = 24
BUS_BUDGET_S = (NIGHTLY_H + daily.TAIL_H) * 3600

# The Cell-grain caveats, MEASURED by frontend 02 (`4ac3ebe`) and re-measured every cycle
# by the numbers beside them in the payload. flood-build 21a inherits these VERBATIM by
# importing this tuple rather than re-typing it - a copied caveat is a caveat that drifts.
CAVEATS_BUS = (
    "The head of this grain is SPARSE. The newest closed hour usually carries a few dozen "
    "Cells against more than a thousand in a dense midday hour; the counts beside this "
    "text are that hour's own, so read them before reading the map.",
    "A near-empty map is a thin hour, not a quiet city.",
    "The Cell fill is ONE channel shared with the delay layer - the two are the same "
    "quantity, a Speed ratio, at two time-scales, so they share one frozen ramp and are "
    "offered as a radio. Only one can be lit.",
    "Without a capture-era dry baseline there is no ratio and every Cell paints grey. "
    "A live Speed over a backfill-era baseline would be a claim about route change, "
    "not about rain.",
)

# ---- the subway side ------------------------------------------------------------------

SUBWAY_TABLE = "archive/subway_tu"
# The control the inference owes a level comparison to, and where its own numbers live.
# NOT imported: `flood_impact` reads subwaydata.nyc, which publishes no data licence, and
# its derived numbers are local-page-only. Only the day NAMES are compared, and only when
# the tree is present at all - on the cluster it never is.
CONTROL = "subwaydata.nyc"
CONTROL_AGG = "snapshots/subwaydata/agg"

# The Bronze part window (`archiver.WINDOW`, 600 s) on top of the hour itself. Pinned to
# that module by a test rather than imported: `archiver` pulls the protobuf decoders and
# this tick has no other reason to hold them.
SUBWAY_BUDGET_S = 3600 + 600

# A complex the feed barely mentioned this hour gets no colour. MEASURED on the real
# capture (2026-08-26 02:00 UTC, 438 complexes): planned rows run min 5 / p10 15 / median
# 27 / max 268, and this floor drops 22 complexes while moving the head of the `rel`
# distribution not at all (max 18.7 either way, p90 ~10). So it is not a noise filter
# dressed up as one - it is the same "a baseline hour with real service" guard
# flood_impact's caught rule carries, and the skew above it is the real distribution.
MIN_PLANNED = 10

INFERENCE = ("a planned stop row that vanished from a run's trip update while the run was "
             "still being reported AND its arrival was still ahead - never a row the train "
             "simply passed")

CAVEATS_SUBWAY = (
    "This is a WITHIN-SOURCE comparison: each complex against the citywide median of the "
    "same hour of the same feed. The absolute drop rate is not offered, because it has "
    "never been level-compared against an independent source.",
    "On the evidence corpus this method reads, the MEDIAN event day is indistinguishable "
    "from a clean day of the same type.",
    "WEEKEND event days are unreadable: scheduled work shuts whole segments, trips the "
    "same rule a flood does, and takes the same-line neighbours down with it.",
    "Only the TAIL reads. The largest event days - Hurricane Ida, 2021-09-02 - stand well "
    "clear of any clean day; nothing in the middle of the distribution does.",
    "The counts behind those three statements are LOCAL ONLY: subwaydata.nyc publishes no "
    "data licence, so they never leave the host.",
    "RAIN HERE IS CONTEXT, NOT ATTRIBUTION: `mm_1h` is MRMS RadarOnly, uncalibrated, "
    "hour-ending precipitation for the complex's own Cell, offered beside the drop - "
    "coincidence is not attribution, and a complex with no rain in its Cell can still "
    "carry a real drop.",
)

# The rain-context read (site feedback: a dropped-service colour renders identically for a
# rain-coincident drop and a mechanical or police one, so the closed hour's own Cell rain
# rides beside it - context, never a filter and never a second detector). `live/precip_cell`
# is the LIVE table `precip_live.tick` appends every 300 s and keeps ~7 days of (spec H/K);
# `valid_ts=<hour>` is the hour START and files are hour-ending, the same grain as this
# overlay's own closed hour, so the two `day`/`hour` strings name the SAME partition here.
PRECIP_TABLE = "live/precip_cell"

# ---- the reads ------------------------------------------------------------------------

# One statement, one scan, columns and predicates pushed into it. `flood_panel` and
# `flood_truth` each carry this same pair for the same reason; a shared helper would make
# one of the three import another purely to borrow a string, and this module is imported
# BY flood_panel.
READ = ("read_parquet(?, hive_partitioning = true, hive_types_autocast = false, "
        "union_by_name = true)")


def _rows(con, sql: str, *params) -> list[dict]:
    return con.execute(sql.format(read=READ), list(params)).to_arrow_table().to_pylist()


def _partitions(root, table: str, prefix: str) -> list[str]:
    """The partition directory NAMES under a table, sorted. One listing, no parquet
    opened - the skip test has to be cheaper than the read it bounds."""
    try:
        return sorted(p.name for p in (as_root(root) / table).glob(f"{prefix}=*"))
    except (OSError, NotImplementedError):
        return []


def hour_of_week(t: datetime) -> int:
    """Monday 00:00 America/New_York = 0 .. Sunday 23:00 = 167 - `gold.baseline`'s own
    grain, computed here in python rather than in SQL.

    Spark's `dayofweek` is 1=Sunday and DuckDB's is 0=Sunday, so the SAME text means
    different days in the two engines (TRAPS) and gold's expression cannot simply be
    copied. `datetime.weekday()` is Monday=0 with no dialect at all, which is the one
    spelling that cannot drift.
    """
    local = t.astimezone(NY)
    return local.weekday() * 24 + local.hour


BUS_HOURS_SQL = """
SELECT hour_end_utc, count(DISTINCT cell)::BIGINT AS n
  FROM {read} WHERE hour_end_utc <= ? GROUP BY 1 ORDER BY 1
"""
BUS_CELLS_SQL = """
SELECT cell, sum(dist_m_sum)::DOUBLE AS dist_m, sum(dt_s_sum)::DOUBLE AS dt_s,
       sum(n_legs)::BIGINT AS n_legs, sum(n_vehicles)::BIGINT AS n_vehicles
  FROM {read} WHERE hour_end_utc = ? GROUP BY 1 ORDER BY 1
"""
# `window` and `hour_of_week` are both predicates INSIDE the statement, and `window` is
# the hive key - so the backfill partitions are never opened, not merely never used.
BUS_BASE_SQL = """
SELECT cell, speed_dry, n_dry::BIGINT AS n_dry
  FROM {read} WHERE "window" = ? AND hour_of_week = ? AND n_dry >= ? AND speed_dry > 0
"""


def bus(con, root, now: datetime) -> dict:
    """The bus overlay: the last CLOSED hour of `gold/cell_hour_speed` at Cell grain.

    Two statements over ONE month partition, in the shape `flood_panel` uses for the
    forcing: aggregate the whole month to find the hour AND how thin it is (both numbers
    the panel owes the reader), then read only that hour's Cells. Counting per hour is
    what makes "the newest closed hour carries N Cells, the densest M" a measurement
    rather than a frozen sentence.
    """
    months = _partitions(root, BUS_TABLE, "month")
    if not months:
        return {"state": "down", "reason": f"no {BUS_TABLE} partitions under {root}"}
    month = months[-1]
    path = f"{as_root(root)}/{BUS_TABLE}/{month}/**/*.parquet"
    hours = _rows(con, BUS_HOURS_SQL, path, now)
    if not hours:
        return {"state": "no_rows", "month": month,
                "reason": f"{BUS_TABLE}/{month} holds no hour ending at or before {now}"}
    newest = max(hours, key=lambda r: r["hour_end_utc"])
    densest = max(hours, key=lambda r: r["n"])
    hour = newest["hour_end_utc"]
    rows = _rows(con, BUS_CELLS_SQL, path, hour)
    # the baseline partition is checked by NAME before a parquet is opened, and the read is
    # bounded to that one directory: the backfill windows are not filtered out downstream,
    # they are never in the scan. An absent table is a grey overlay, not an IOException.
    windows = _partitions(root, BASE_TABLE, "window")
    base = {}
    if f"window={LIVE_WINDOW}" in windows:
        base = {r["cell"]: r for r in _rows(
            con, BUS_BASE_SQL,
            f"{as_root(root)}/{BASE_TABLE}/window={LIVE_WINDOW}/**/*.parquet",
            LIVE_WINDOW, hour_of_week(hour), MIN_BASE_DAYS)}
    cells = {}
    for r in rows:
        speed = r["dist_m"] / r["dt_s"] if r["dt_s"] else None
        b = base.get(r["cell"])
        # ABSENT, never null: no baseline -> no `ratio` key -> the Cell paints grey.
        cells[fd.hexcell(r["cell"])] = pack(
            speed_mps=round(speed, 3) if speed is not None else None,
            n_legs=r["n_legs"], n_vehicles=r["n_vehicles"],
            ratio=round(speed / b["speed_dry"], 4) if b and speed is not None else None,
            baseline_days=b["n_dry"] if b else None)
    return {
        "state": "ok" if base else "no_baseline",
        "month": month, "hour_end_utc": hour, "hours_read": len(hours),
        "n_cells": len(cells), "densest_cells": densest["n"],
        "densest_hour_end_utc": densest["hour_end_utc"],
        "hour_of_week": hour_of_week(hour),
        "baseline": pack(
            window=LIVE_WINDOW, present=bool(base), min_days=MIN_BASE_DAYS,
            n_cells=len(base) or None,
            reason=None if base else
            (f"no `window={LIVE_WINDOW}` partition with {MIN_BASE_DAYS}+ same-weekday "
             f"days for hour-of-week {hour_of_week(hour)}; the partitions on disk are "
             f"{windows} and those are BACKFILL-era windows this overlay may not read")),
        "cells": cells,
    }


# One scan, three aggregates, ~445 rows out. Per (feed, run, start_date) the trip's own
# last sighting; per stop row its last sighting and the arrival it still claimed then. A
# row that vanished BEFORE its run did, while its arrival was still ahead, is a stop the
# run stopped planning to make. A row that vanished WITH the run is a run that ended, and
# a row whose arrival had passed is a stop the train made - neither counts.
SUBWAY_SQL = """
WITH r AS (
  -- the trailing N/S is the DIRECTION, and this is a COMPLEX-grain overlay: a complex
  -- serves both, and a single run is one direction, so stripping it before the grouping
  -- merges nothing real. `rtrim(id, 'NS')` and "drop a trailing N or S" agree on all 503
  -- stop ids in the capture (measured).
  SELECT feed, coalesce(train_id, trip_id) AS run_id, start_date,
         rtrim(stop_id, 'NS') AS stop, arrival_time, fetched_at
    FROM {read}
   WHERE date = ? AND hour = ? AND stop_id IS NOT NULL AND fetched_at IS NOT NULL),
 t AS (SELECT feed, run_id, start_date, max(fetched_at) AS run_last
         FROM r GROUP BY 1, 2, 3),
 s AS (SELECT feed, run_id, start_date, stop, max(fetched_at) AS stop_last,
              arg_max(arrival_time, fetched_at) AS last_arrival
         FROM r GROUP BY 1, 2, 3, 4)
SELECT s.stop, count(*)::BIGINT AS planned,
       count(*) FILTER (WHERE s.stop_last < t.run_last
                          AND s.last_arrival > s.stop_last)::BIGINT AS dropped,
       count(DISTINCT s.run_id)::BIGINT AS runs
  FROM s JOIN t USING (feed, run_id, start_date)
 GROUP BY 1 ORDER BY 1
"""
# One scan of ref/assets for both halves of the placement: the stop ids a complex answers
# to, and the complex's own point. A payload that names an asset a consumer cannot locate
# is a defect this repo has shipped twice (TRAPS), so the point rides along.
COMPLEX_SQL = """
WITH s AS (SELECT complex_id, unnest(gtfs_stop_id) AS stop
             FROM {read} WHERE kind = 'station' AND complex_id IS NOT NULL),
     c AS (SELECT complex_id, any_value(name) AS name, any_value(lon) AS lon,
                  any_value(lat) AS lat, any_value(cell) AS cell
             FROM {read} WHERE kind = 'complex' AND complex_id IS NOT NULL GROUP BY 1)
SELECT s.stop, s.complex_id, c.name, c.lon, c.lat, c.cell
  FROM s JOIN c USING (complex_id)
"""
# One `valid_ts=` partition, already bounded by path. `cell IS NOT NULL` is the predicate
# this statement owes the house rule; the dedup is the QUALIFY, ranking every row (a NULL
# `mm_1h` included) so the LATEST `fetched_at` wins per cell even when that latest row is
# the one with no usable weight sum - the null is dropped after, not before, the ranking.
PRECIP_SQL = """
SELECT cell, mm_1h FROM {read} WHERE cell IS NOT NULL
QUALIFY row_number() OVER (PARTITION BY cell ORDER BY fetched_at DESC) = 1
"""


def _median(xs: list[float]) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2


def level_check(root) -> dict:
    """Days the TU capture and the `CONTROL` corpus BOTH cover.

    The ticket's precondition on displaying an absolute rate, and it is computed from the
    two day sets rather than remembered: only the directory NAMES are read, never a
    subwaydata number, and the control tree is absent on the cluster by design (it sits
    outside `<root>/archive`, the only tree `make coldpush` mirrors), which reads as zero
    overlapping days - the honest answer there too.
    """
    tu = {n[len("date="):] for n in _partitions(root, SUBWAY_TABLE, "date")}
    try:
        ctl = {p.name[:-len(".parquet")]
               for p in (as_root(root) / CONTROL_AGG).glob("*/*.parquet")}
    except (OSError, NotImplementedError):
        ctl = set()
    both = sorted(tu & ctl)
    return {
        "control": CONTROL, "overlapping_days": len(both),
        "capture_days": len(tu), "control_days": len(ctl),
        "state": "compared" if both else "no_overlap",
        "note": ("the absolute drop rate is NOT displayed: it has never been "
                 "level-compared against an independent source, so what ships is each "
                 "complex against the citywide median of the same hour of this feed"),
    }


def subway(con, root, now: datetime) -> dict:
    """The subway overlay: the last CLOSED hour of `archive/subway_tu` at complex grain."""
    days = _partitions(root, SUBWAY_TABLE, "date")
    if not days:
        return {"state": "down", "reason": f"no {SUBWAY_TABLE} partitions under {root}"}
    closed = now.replace(minute=0, second=0, microsecond=0)
    day, hour = None, None
    for name in reversed(days):
        d = name[len("date="):]
        got = [h[len("hour="):] for h in
               _partitions(root, f"{SUBWAY_TABLE}/{name}", "hour")]
        for h in sorted(got, reverse=True):
            # the hour is CLOSED when the hour AFTER it has begun on the reader's clock
            if datetime.fromisoformat(f"{d}T{h}:00:00+00:00") + timedelta(hours=1) <= closed:
                day, hour = d, h
                break
        if day:
            break
    if day is None:
        return {"state": "no_rows",
                "reason": f"no closed hour in {SUBWAY_TABLE} at or before {closed}"}
    root_ = as_root(root)
    stops = _rows(con, SUBWAY_SQL, f"{root_}/{SUBWAY_TABLE}/**/*.parquet", day, hour)
    assets = f"{root_}/ref/assets/**/*.parquet"
    where = {r["stop"]: r for r in _rows(con, COMPLEX_SQL, assets, assets)}
    # the SAME hour, named by the SAME day/hour strings: `valid_ts=<hour START>` and this
    # overlay's own closed hour are both hour-ending, so no shift is owed between them. The
    # table holds ~7 days and only while `precip-live` runs - an absent partition says so
    # rather than shipping a payload silently missing rain, per the partition-by-name rule
    # every read in this module already follows.
    vts = f"{day}T{hour}"
    rain_by_cell: dict[int, float] = {}
    have_precip = f"valid_ts={vts}" in _partitions(root, PRECIP_TABLE, "valid_ts")
    if have_precip:
        prows = _rows(con, PRECIP_SQL, f"{root_}/{PRECIP_TABLE}/valid_ts={vts}/**/*.parquet")
        rain_by_cell = {r["cell"]: round(r["mm_1h"], 2) for r in prows if r["mm_1h"] is not None}
    by_complex: dict[str, dict] = {}
    unresolved = 0
    for r in stops:
        w = where.get(r["stop"])
        if w is None:
            unresolved += 1
            continue
        c = by_complex.setdefault(w["complex_id"], {"w": w, "planned": 0, "dropped": 0,
                                                    "runs": 0})
        c["planned"] += r["planned"]
        c["dropped"] += r["dropped"]
        c["runs"] += r["runs"]
    for c in by_complex.values():
        c["share"] = c["dropped"] / c["planned"] if c["planned"] else None
    med = _median([c["share"] for c in by_complex.values()])
    out = {}
    for cid, c in sorted(by_complex.items()):
        w = c["w"]
        out[cid] = pack(
            name=w["name"], lon=w["lon"], lat=w["lat"],
            cell=fd.hexcell(w["cell"]) if w["cell"] is not None else None,
            planned=c["planned"], dropped=c["dropped"], runs=c["runs"],
            drop_share=round(c["share"], 4) if c["share"] is not None else None,
            # the within-source number, and the ONLY one offered as a colour. Absent
            # when the citywide median is zero ("x times nothing" is not a ratio) or when
            # the complex is under MIN_PLANNED - absent, so the complex renders grey
            # rather than carrying a rate built on a handful of rows.
            rel=round(c["share"] / med, 3)
            if med and c["share"] is not None and c["planned"] >= MIN_PLANNED else None,
            # ABSENT, never null: no cell, or no row for that cell this hour, and the key
            # is simply not there - context, never a second detector.
            mm_1h=rain_by_cell.get(w["cell"]) if w["cell"] is not None else None)
    total = sum(c["planned"] for c in by_complex.values())
    rain = ({"valid_ts": vts,
             "n_wet": sum(1 for c in out.values()
                          if c.get("mm_1h", -1) >= live_export.RAIN_MM),
             "n_with_mm": sum(1 for c in out.values() if "mm_1h" in c)}
            if have_precip else
            {"state": "no_partition", "valid_ts": vts,
             "reason": f"no {PRECIP_TABLE}/valid_ts={vts} partition under {root}"})
    return {
        "state": "ok", "hour_end_utc": datetime.fromisoformat(
            f"{day}T{hour}:00:00+00:00") + timedelta(hours=1),
        "n_complexes": len(out), "planned": total, "min_planned": MIN_PLANNED,
        "n_rel": sum(1 for c in out.values() if "rel" in c),
        "dropped": sum(c["dropped"] for c in by_complex.values()),
        "median_drop_share": round(med, 4) if med is not None else None,
        "unresolved_stops": unresolved, "stops_read": len(stops),
        "level": level_check(root), "rain": rain, "complexes": out,
    }


# ---- the payloads ----------------------------------------------------------------------

def _stale(newest: datetime | None, now: datetime, budget_s: int) -> dict:
    """One overlay's freshness, dated at the READER against its own budget - never a
    number the writer froze into the file (TRAPS: a frozen age stops advancing when its
    writer dies). A stamp from the future reads DOWN, exactly as `flood_panel._source`
    does; the vocabulary is flood 11's, not a second one."""
    if newest is None:
        return {"state": fd.DOWN, "budget_s": budget_s}
    age = (now - newest).total_seconds()
    return {"state": fd.DOWN if age < 0 else
            fd.FRESH if age <= budget_s else fd.STALE,
            "age_min": round(age / 60, 1), "budget_s": budget_s}


def _doc(read: dict, now: datetime, kind: str, grain: str, table: str, budget_s: int,
         caveats: tuple, body_key: str) -> dict:
    """One overlay document. The label is on the document AND in `strings`, because the
    two are read by different things - a card renders `strings`, a legend renders the
    top-level key - and the one claim this ticket exists to make must survive either."""
    body = read.pop(body_key, {})
    return {
        # the SAME cycle_id flood 15's four documents carry - one `now`, one tick, so a
        # reader can tell a torn set of six from a coherent one
        "cycle_id": now.isoformat(),
        "kind": kind, "grain": grain, "lineage": "mta-vehicles", "label": LABEL,
        "source": table, "budgets_s": {f"impact_{kind}": budget_s},
        "staleness": _stale(read.get("hour_end_utc"), now, budget_s),
        "strings": {"label": LABEL, "never_a_detector_input": NEVER_INPUT,
                    "caveats": list(caveats)},
        **read, body_key: body,
    }


def read(con, root, now: datetime) -> dict:
    """Both overlays, independently. One side's outage never hides the other, and neither
    ever raises: the flood tick this rides inside is a panel, not a job."""
    out = {}
    for name, fn in (("bus", bus), ("subway", subway)):
        try:
            out[name] = fn(con, root, now)
        except Exception as exc:  # noqa: BLE001 - an outage is a field, never a stopped tick
            out[name] = {"state": "down",
                         "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return out


def docs(read_: dict | None, now: datetime) -> dict:
    """The two documents this cycle publishes, keyed by file name. `None` renders the
    honest DOWN pair rather than nothing: a family is all-or-none at publish time, and a
    reader must be able to tell "not read this cycle" from "read and empty"."""
    read_ = read_ or {}
    bus_read = dict(read_.get("bus") or {"state": "down", "reason": "not read this cycle"})
    sub_read = dict(read_.get("subway") or {"state": "down", "reason": "not read this cycle"})
    return {
        BUS_FILE: _doc(bus_read, now, "bus", "cell", BUS_TABLE, BUS_BUDGET_S,
                       CAVEATS_BUS, "cells"),
        SUBWAY_FILE: _doc(sub_read, now, "subway", "complex", SUBWAY_TABLE,
                          SUBWAY_BUDGET_S, CAVEATS_SUBWAY, "complexes"),
    }


def line(read_: dict | None) -> str:
    b, s = (read_ or {}).get("bus") or {}, (read_ or {}).get("subway") or {}
    return (f"impact bus={b.get('state')}/{b.get('n_cells')} "
            f"subway={s.get('state')}/{s.get('n_complexes')}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", action="store_true", help="print both documents whole")
    args = ap.parse_args()
    root = as_root(args.root) if args.root else data_root()
    now = datetime.now(timezone.utc)
    got = read(duck.connect(), root, now)
    if args.json:
        print(json.dumps(docs(got, now), indent=1, default=str))
        return
    print(line(got))
    b, s = got["bus"], got["subway"]
    print(f"  bus     {b.get('hour_end_utc')}  {b.get('n_cells')} Cells "
          f"(densest hour {b.get('densest_cells')})  baseline "
          f"{(b.get('baseline') or {}).get('present')}  "
          f"{b.get('reason') or b.get('error') or ''}")
    print(f"  subway  {s.get('hour_end_utc')}  {s.get('n_complexes')} complexes  "
          f"{s.get('dropped')}/{s.get('planned')} rows  "
          f"level {(s.get('level') or {}).get('state')}  "
          f"{s.get('reason') or s.get('error') or ''}")


if __name__ == "__main__":
    main()
