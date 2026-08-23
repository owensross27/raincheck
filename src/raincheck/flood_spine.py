"""The flood event spine (flood-build ticket 04 / spec "Labels and the event spine").

`silver/flood_events` — the deterministic list of dated flood events with UTC windows, so
"during the event" means the same hours in every table, fit and test.

A day (America/New_York) is an event-day on ANY of four triggers:
  (a) 311 street/highway flooding reports at or above the frozen nearest-rank p99 for that
      era-dataset (P99_311, re-measured on the four-literal union);
  (b) at least one station-naming alert flood observation;
  (c) a NOAA Storm Events flood row for a five-borough county FIPS or one of the
      enumerated coastal zone names;
  (d) CO-OPS water level at the Battery or Kings Point at or above that station's own NWS
      minor threshold, station datum on both sides, two consecutive readings.
Contiguous event-days merge into one event.

The window is a CALENDAR fact, never an observation-derived one — [NY-midnight of the
first day - 3 h, NY-midnight after the last day + 3 h] — so the spine cannot circularly
confirm its own labels: widening the observations can add a day, but it can never stretch
an hour of an existing one.

Run: make flood-spine     (python -m raincheck.flood_spine)
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import re
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

from raincheck import flood_obs as fo
from raincheck.paths import data_root

NY = ZoneInfo("America/New_York")
PAD_H = 3  # the calendar pad on both ends of the window
TS = pa.timestamp("us", tz="UTC")

# ---- frozen 311 triggers ----------------------------------------------------------
# Nearest-rank p99 of the daily counts over days with >= 1 report, measured 2026-08-23 on
# the FOUR-literal union per era-dataset. The legacy-two measurement biased erm2 low
# (84 vs 85) because the 2023-09 renames carry a third of the modern record; 76ig is
# unchanged at 97 because the renamed literals never appear before 2020.
P99_311 = {"76ig-c548": 97, "erm2-nwe9": 85}
P99_MEASURED_ON = date(2026, 8, 23)

# ---- frozen Storm Events triggers -------------------------------------------------
NCEI_CSV = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
STORM_TYPES = ("Flash Flood", "Flood", "Coastal Flood")
STORM_STATE = "NEW YORK"
STORM_COUNTY_FIPS = ("5", "47", "61", "81", "85")  # Bronx, Kings, New York, Queens, Richmond
# Zone-coded rows carry an NWS zone number in CZ_FIPS, not a county FIPS, and EVERY NYC
# coastal-flood row is zone-coded — a county-FIPS filter alone drops all of them
# (measured: 82/82, including every Sandy row). The zone names are enumerated, never
# pattern-matched.
STORM_ZONES = ("BRONX", "KINGS", "NEW YORK", "QUEENS", "RICHMOND", "KINGS (BROOKLYN)",
               "NEW YORK (MANHATTAN)", "RICHMOND (STATEN IS.)", "NORTHERN QUEENS",
               "SOUTHERN QUEENS")
STORM_FROM = 2010  # the label era; flood types exist from 1996

# ---- frozen tide triggers ---------------------------------------------------------
# NWS minor flood stage, FEET ON STATION DATUM, from each station's own floodlevels.json.
# Both sides of the comparison are STND so no arithmetic touches the reading. Kings
# Point's published nws_moderate (23.39) sits BELOW its nos_moderate (23.55) — a real
# NOAA inversion, recorded so nobody "fixes" it into a cross-station rule.
COOPS = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
NWS_MINOR_STND_FT = {"8518750": 10.49, "8516945": 22.89}  # Battery, Kings Point
COOPS_CONSECUTIVE = 2  # readings at or above the threshold before a day triggers
COOPS_FROM = 2010
# Jamaica Bay / the Rockaways have no gauge: a documented blind spot, not a quiet zero.
COOPS_BLIND = "Jamaica Bay / Rockaway (no CO-OPS gauge; FloodNet partially covers 2020-11+)"

# ---- frozen class rules -----------------------------------------------------------
# Central Park daily maxima (GHCN-Daily, tenths of a degree C). The reclass needs a
# temperature series that spans the whole label era: AORC's t2m_c is the pipeline's own
# term but covers 5 of the ~52 months the flood era needs until ticket 06 lands its
# extension, and a spine whose classes change when a LATER ticket runs is not a spine.
GHCN = ("https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/"
        "access/{station}.csv")
GHCN_STATION = "USW00094728"  # NY CITY CENTRAL PARK
FREEZING_C = 0.0
SNOWMELT_MONTHS = (12, 1, 2, 3)
PLUVIAL, COASTAL, MIXED, SNOWMELT, UNCLASSIFIED = (
    "pluvial", "coastal", "mixed", "snowmelt", "unclassified")

# ---- per-source coverage calendars (code, not per-row flags) ----------------------
COVERAGE = {
    "311": (fo.COVERAGE_311, None, ()),
    "alert": (fo.COVERAGE_ALERT[0], None,
              ((fo.COVERAGE_ALERT[1] + timedelta(days=1), fo.COVERAGE_ALERT[2]
                - timedelta(days=1)), fo.ALERT_DARK)),
    "floodnet": (fo.COVERAGE_FLOODNET, None, ()),
}


# ---- pure derivation --------------------------------------------------------------

def p99(series: dict[date, int], q: float = 0.99) -> int:
    """Nearest-rank quantile of the daily counts over days with at least one report: the
    ceil(q * N)-th smallest of the N such days. Nearest rank, never interpolated — the
    threshold has to be a count a day can actually hit."""
    counts = sorted(n for n in series.values() if n > 0)
    if not counts:
        raise ValueError("no days with a report: the descriptor literals stopped matching")
    return counts[math.ceil(q * len(counts)) - 1]


def runs(days: set[date]) -> list[tuple[date, date]]:
    """Contiguous event-days merge into one event."""
    out: list[tuple[date, date]] = []
    for d in sorted(days):
        if out and d - out[-1][1] == timedelta(days=1):
            out[-1] = (out[-1][0], d)
        else:
            out.append((d, d))
    return out


def window(first: date, last: date) -> tuple[datetime, datetime]:
    """[NY-midnight of the first day - 3 h, NY-midnight after the last day + 3 h] as UTC
    hour_end bounds. NY midnight always falls on a whole UTC hour (the DST switch is at
    02:00 local), so both bounds land on hour_end values without rounding."""
    start = datetime.combine(first, time(0), NY) - timedelta(hours=PAD_H)
    end = datetime.combine(last + timedelta(days=1), time(0), NY) + timedelta(hours=PAD_H)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def covered(source: str, first: date, last: date) -> bool:
    """Was this source live for every day of the event? A dark source is coverage=missing,
    never an implicit non-event."""
    since, until, holes = COVERAGE[source]
    days = [first + timedelta(n) for n in range((last - first).days + 1)]
    return all(d >= since and (until is None or d <= until)
               and not any(a <= d <= b for a, b in holes) for d in days)


def classify(trig: dict[str, bool], cause: str | None, first: date, last: date,
             tmax_c: float | None) -> str:
    """Storm Events FLOOD_CAUSE where it speaks, else the triggers; then the winter
    reclass. A Dec-Mar event that never rose above freezing is snowmelt-driven, not
    pluvial — it keeps its labels and leaves the pluvial fit (ticket 08)."""
    if cause and "snow melt" in cause.lower():
        return SNOWMELT
    # Surge is not only the gauges: a Coastal Flood row in Storm Events is a coastal event
    # whether or not the two gauges we watch crossed minor stage (the Rockaways have no
    # gauge at all), so a storm-coastal-only day is COASTAL, never unclassified.
    surge = trig["by_tide"] or trig["by_storm_coastal"]
    rain = trig["by_311"] or trig["by_alert"] or trig["by_storm_pluvial"]
    if cause and "heavy rain" in cause.lower():
        klass = MIXED if surge else PLUVIAL
    else:
        klass = (MIXED if rain and surge
                 else COASTAL if surge else PLUVIAL if rain else UNCLASSIFIED)
    if klass != PLUVIAL or not all(
            (first + timedelta(n)).month in SNOWMELT_MONTHS
            for n in range((last - first).days + 1)):
        return klass
    if tmax_c is None:  # cannot apply the rule -> do not pretend the class is known
        return UNCLASSIFIED
    return SNOWMELT if tmax_c <= FREEZING_C else PLUVIAL


def derive(trigger_days: dict[str, set[date]], causes: dict[date, str],
           tmax_c: dict[date, float]) -> list[dict]:
    """Trigger day-sets -> the event list. Pure: every input is data, so ticket 18's
    threshold replication re-derives the whole spine by passing different day sets."""
    all_days = set().union(*trigger_days.values()) if trigger_days else set()
    events = []
    for first, last in runs(all_days):
        days = [first + timedelta(n) for n in range((last - first).days + 1)]
        trig = {f"by_{k}": any(d in trigger_days.get(k, ()) for d in days)
                for k in ("311", "alert", "storm", "tide", "storm_pluvial",
                          "storm_coastal")}
        cause = next((causes[d] for d in days if d in causes), None)
        highs = [tmax_c[d] for d in days if d in tmax_c]
        start, end = window(first, last)
        events.append({
            "event_id": first.isoformat(), "day_start": first, "day_end": last,
            "n_days": len(days), "window_start_utc": start, "window_end_utc": end,
            **{k: trig[k] for k in ("by_311", "by_alert", "by_storm", "by_tide")},
            "event_class": classify(trig, cause, first, last,
                                    max(highs) if highs else None),
            "flood_cause": cause,
            **{f"cov_{s}": covered(s, first, last) for s in COVERAGE},
        })
    return events


# ---- (a) 311 ----------------------------------------------------------------------

def days_311(root: Path, asof: date = fo.ASOF,
             thresholds: dict[str, int] | None = None) -> set[date]:
    """Days at or above the frozen p99 for their own era-dataset."""
    thresholds = thresholds or P99_311
    out: set[date] = set()
    for ds, rows in fo.rows_311(root, asof).items():
        cut = thresholds[ds]
        out |= {d for d, n in fo.daily_311(rows).items() if n >= cut}
    return out


def remeasure_311(root: Path, asof: date = fo.ASOF) -> dict[str, int]:
    """What the frozen pins would be if measured today — the build asserts they match."""
    return {ds: p99(fo.daily_311(rows))
            for ds, rows in fo.rows_311(root, asof).items()}


# ---- (b) alerts -------------------------------------------------------------------

def days_alert(root: Path, asof: date = fo.ASOF) -> set[date]:
    """Days holding at least one station-naming alert flood observation. A system-wide-only
    alert day does not trigger: ticket 02's extractor mints nothing for it."""
    return {o["ts_utc"].astimezone(NY).date() for o in fo.obs_alert(root, asof)}


# ---- (c) NOAA Storm Events --------------------------------------------------------

def storm_rows(root: Path, asof: date = fo.ASOF) -> list[dict]:
    """Five-borough flood rows from the bulk details CSVs, one snapshot per year.

    The published file names carry a version and a creation date that both change under
    NCEI's feet, so the year's file is resolved from the live listing and its real name is
    kept in the snapshot. Only the NY rows are stored: the national CSV is ~50 MB a year
    and the archive root is on a byte budget."""
    out = []
    for year in range(STORM_FROM, asof.year + 1):
        path = root / "archive" / "flood" / f"stormevents_{year}_{asof}.csv"
        if not path.exists():
            src = _ncei_file(year)
            if src is None:
                print(f"stormevents: no details file published for {year}", flush=True)
                continue
            print(f"downloading {NCEI_CSV}{src}", flush=True)
            with urllib.request.urlopen(NCEI_CSV + src, timeout=600) as r:
                text = gzip.decompress(r.read()).decode("utf-8", "replace")
            rows = [r for r in csv.DictReader(io.StringIO(text))
                    if r.get("STATE") == STORM_STATE]
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".part")
            with tmp.open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["STATE"])
                w.writeheader()
                w.writerows(rows)
            tmp.replace(path)
            print(f"stormevents {year}: {len(rows)} {STORM_STATE} rows from {src}",
                  flush=True)
        with path.open(newline="") as fh:
            out += [r for r in csv.DictReader(fh) if r.get("EVENT_TYPE") in STORM_TYPES
                    and _is_nyc(r)]
    return out


def _ncei_file(year: int) -> str | None:
    with urllib.request.urlopen(NCEI_CSV, timeout=120) as r:
        listing = r.read().decode("utf-8", "replace")
    names = re.findall(rf"StormEvents_details-ftp_v\d+\.\d+_d{year}_c\d+\.csv\.gz", listing)
    return sorted(set(names))[-1] if names else None  # newest creation stamp wins


def _is_nyc(r: dict) -> bool:
    if r.get("CZ_TYPE") == "C":
        return str(int(r.get("CZ_FIPS") or 0)) in STORM_COUNTY_FIPS
    return (r.get("CZ_NAME") or "").upper() in STORM_ZONES


def storm_days(rows: list[dict]) -> tuple[set[date], set[date], set[date], dict[date, str]]:
    """(every flood day, the pluvial subset, the coastal subset, day -> FLOOD_CAUSE)."""
    days, pluvial, coastal, causes = set(), set(), set(), {}
    for r in rows:
        for d in _storm_span(r):
            days.add(d)
            (pluvial if r["EVENT_TYPE"] in ("Flash Flood", "Flood") else coastal).add(d)
            if r.get("FLOOD_CAUSE"):
                causes.setdefault(d, r["FLOOD_CAUSE"])
    return days, pluvial, coastal, causes


def _storm_span(r: dict) -> list[date]:
    """Every NY day the row covers. Storm Events stamps are already local to the event.
    A stamp this cannot parse is fatal, never an empty span: a silent format change would
    zero the whole trigger and look like a quiet decade."""
    fmt = "%d-%b-%y %H:%M:%S"
    a = datetime.strptime(r["BEGIN_DATE_TIME"], fmt).date()
    b = datetime.strptime(r["END_DATE_TIME"], fmt).date()
    return [a + timedelta(n) for n in range(max((b - a).days, 0) + 1)]


# ---- (d) CO-OPS tide gauges -------------------------------------------------------

def days_tide(root: Path, asof: date = fo.ASOF) -> tuple[set[date], set[date]]:
    """(trigger days, days some gauge reported). Two CONSECUTIVE hourly readings at or
    above the station's own NWS minor threshold, station datum on both sides.

    Consecutive means ADJACENT IN TIME, not merely the next two rows present: the series
    has gaps, and two exceedances an outage apart are two spikes, which is exactly what
    the two-reading rule exists to reject. The scan runs as one stream per station so a
    run is neither broken by a calendar year boundary nor carried across a dark year.
    """
    hit, seen = set(), set()
    for station, threshold in NWS_MINOR_STND_FT.items():
        run, prev = 0, None
        for year in range(COOPS_FROM, asof.year + 1):
            for stamp, feet in _coops_year(root, station, year, asof):
                seen.add(stamp.date())
                adjacent = prev is not None and stamp - prev <= timedelta(hours=1)
                run = (run + 1 if adjacent else 1) if feet >= threshold else 0
                prev = stamp
                if run >= COOPS_CONSECUTIVE:
                    hit.add(stamp.date())
    return hit, seen


def _coops_year(root: Path, station: str, year: int,
                asof: date) -> list[tuple[datetime, float]]:
    """One station-year of hourly heights. The product caps a request at 365 days, so the
    calendar year is the chunk; times come back GMT and the trigger day is the NY day."""
    path = root / "archive" / "flood" / f"coops_{station}_{year}_{asof}.json"
    if not path.exists():
        end = min(date(year, 12, 31), asof)
        url = (f"{COOPS}?product=hourly_height&application=raincheck&station={station}"
               f"&begin_date={year}0101&end_date={end:%Y%m%d}&datum=STND&units=english"
               f"&time_zone=gmt&format=json")
        print(f"downloading {url}", flush=True)
        with urllib.request.urlopen(url, timeout=300) as r:
            body = json.loads(r.read())
        # datagetter answers HTTP 200 for its own errors, so the body is the status. A
        # genuinely empty station-year ("No data was found") is cacheable; anything else
        # is a broken request that must not be frozen into a snapshot as a quiet gauge.
        message = (body.get("error") or {}).get("message", "")
        if message and "No data was found" not in message:
            raise RuntimeError(f"CO-OPS {station} {year}: {message.strip()}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body))
    body = json.loads(path.read_text())
    out = []
    for d in body.get("data", []):
        try:
            v = float(d["v"])
        except (KeyError, TypeError, ValueError):
            continue  # a gap is a gap: never a zero reading
        out.append((datetime.strptime(d["t"], "%Y-%m-%d %H:%M").replace(
            tzinfo=timezone.utc).astimezone(NY), v))
    return out


# ---- the class temperature --------------------------------------------------------

def daily_tmax(root: Path, asof: date = fo.ASOF) -> dict[date, float]:
    """Central Park daily maximum temperature in degrees C (GHCN-Daily tenths)."""
    path = fo.snapshot(root, f"ghcn_{GHCN_STATION}_{asof}.csv",
                       GHCN.format(station=GHCN_STATION))
    out = {}
    with path.open(newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("TMAX") not in (None, ""):
                out[date.fromisoformat(r["DATE"])] = float(r["TMAX"]) / 10.0
    return out


# ---- the table --------------------------------------------------------------------

SCHEMA = pa.schema([
    ("event_id", pa.string()), ("day_start", pa.date32()), ("day_end", pa.date32()),
    ("n_days", pa.int16()), ("window_start_utc", TS), ("window_end_utc", TS),
    ("by_311", pa.bool_()), ("by_alert", pa.bool_()), ("by_storm", pa.bool_()),
    ("by_tide", pa.bool_()), ("event_class", pa.string()), ("flood_cause", pa.string()),
    ("cov_311", pa.bool_()), ("cov_alert", pa.bool_()), ("cov_floodnet", pa.bool_()),
    ("cov_tide", pa.bool_()), ("spine_version", pa.string())])


def spine_version(asof: date, thresholds: dict[str, int]) -> str:
    """sha1 over everything that can move an event boundary: the frozen thresholds, the
    trigger vocabularies, the window rule and the source as-of stamp. Ticket 18's alternate
    universes differ in `thresholds` alone and therefore stamp differently."""
    payload = json.dumps({
        "asof": asof.isoformat(), "p99": thresholds, "descriptors": fo.DESCRIPTORS,
        "storm_types": STORM_TYPES, "storm_fips": STORM_COUNTY_FIPS,
        "storm_zones": STORM_ZONES, "nws_minor_stnd_ft": NWS_MINOR_STND_FT,
        "coops_consecutive": COOPS_CONSECUTIVE, "pad_h": PAD_H,
        "snowmelt_months": SNOWMELT_MONTHS, "freezing_c": FREEZING_C,
        "ghcn_station": GHCN_STATION,
    }, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()


def build(root: Path, asof: date = fo.ASOF,
          thresholds: dict[str, int] | None = None) -> list[dict]:
    thresholds = thresholds or P99_311
    measured = remeasure_311(root, asof)
    if thresholds is P99_311 and measured != P99_311:
        raise RuntimeError(
            f"the frozen 311 p99 pins no longer reproduce: {P99_311} frozen "
            f"{P99_MEASURED_ON}, {measured} on the {asof} snapshot — re-freeze them "
            f"deliberately (every event boundary and every label moves with them)")
    storm_all, storm_pluvial, storm_coastal, causes = storm_days(storm_rows(root, asof))
    tide, tide_seen = days_tide(root, asof)
    trigger_days = {"311": days_311(root, asof, thresholds), "alert": days_alert(root, asof),
                    "storm": storm_all, "storm_pluvial": storm_pluvial,
                    "storm_coastal": storm_coastal, "tide": tide}
    for k, v in trigger_days.items():
        print(f"trigger {k}: {len(v)} event-days", flush=True)
    events = derive(trigger_days, causes, daily_tmax(root, asof))
    version = spine_version(asof, thresholds)
    for e in events:
        e["cov_tide"] = all(
            (e["day_start"] + timedelta(n)) in tide_seen for n in range(e["n_days"]))
        e["spine_version"] = version
    out = root / "silver" / "flood_events" / "part-00000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(events, schema=SCHEMA), out, compression="zstd")
    klasses: dict[str, int] = {}
    for e in events:
        klasses[e["event_class"]] = klasses.get(e["event_class"], 0) + 1
    print(f"silver/flood_events: {len(events)} events {klasses} version {version}",
          flush=True)
    return events


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--asof", default=fo.ASOF.isoformat())
    a = ap.parse_args()
    build(data_root(), date.fromisoformat(a.asof))


if __name__ == "__main__":
    main()
