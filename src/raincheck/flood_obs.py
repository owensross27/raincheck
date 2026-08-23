"""Flood observations (flood-build ticket 04 / spec "Labels and the event spine").

`silver/flood_obs` — every LABEL-GRADE flood observation in one GeoParquet file, so every
downstream artifact draws from one auditable well. Label-grade means a source that may set
`flooded` on an asset: 311 street/highway flooding points, FloodNet events from the curated
Socrata event table, station-named MTA alerts (ticket 02's extractor), USGS high-water
marks, the Sandy inundation polygons. Covariate sources (NFIP, sewer backup SA, catch
basin SC, MyCoast) never enter this table, and neither do the spine-only sources (Storm
Events, CO-OPS) — those live in flood_spine.

The estimand is `flooded_reported`: where flooding was REPORTED, not where water stood.

Every source is pinned as a snapshot under <root>/archive/flood: a present snapshot means
a rebuild never calls the network, which is what makes the table reproducible years later.

Run: make flood-obs              (python -m raincheck.flood_obs)
     python -m raincheck.flood_obs --measure    the 311 daily series behind the p99 pins
"""
import argparse
import json
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

from raincheck import duck, flood_alerts as fa
from raincheck.paths import data_root

NY = ZoneInfo("America/New_York")
SODA_NYC = "https://data.cityofnewyork.us/resource"
SODA_NY = "https://data.ny.gov/resource"
PAGE = 50_000  # SODA truncates silently at $limit: the page loop stops only on a short page
ASOF = date(2026, 8, 23)  # the as-of stamp every snapshot name carries

# ---- frozen 311 pins -------------------------------------------------------------
# FOUR exact literals, never LIKE '%FLOOD%' (which catches ~8,700 "Flood Light Lamp"
# street-light rows). The city renamed the dropdown in 2023-09 and kept BOTH spellings
# alive: the legacy pair ends 2026-07, the renames start 2023-09-28 — so the eras overlap
# and only the union sees the whole record, including the 2023-09-29 reference storm.
DESCRIPTORS_LEGACY = ("Street Flooding (SJ)", "Highway Flooding (SH)")
DESCRIPTORS_RENAMED = ("Flooding on Street", "Flooding on Highway")
DESCRIPTORS = DESCRIPTORS_LEGACY + DESCRIPTORS_RENAMED
# Two era-datasets, no overlap in time (measured: 76ig ends 2019-12-31, erm2 opens
# 2020-01-01, and erm2 holds zero legacy-literal rows before 2020). erm2-nwe9 is the BASE
# dataset, never the 9qq5-d465 view.
DATASET_311 = {"76ig-c548": (date(2010, 1, 1), date(2019, 12, 31)),
               "erm2-nwe9": (date(2020, 1, 1), None)}
COVERAGE_311 = date(2010, 1, 1)  # 311 is continuous from here (per-source coverage calendar)

# ---- frozen FloodNet pins --------------------------------------------------------
# The CURATED event table, never the raw API (measured: a 7-month single-sensor request
# returns exactly 10,000 rows and silently truncates to the first ~7 days).
FLOODNET_EVENTS = "aq7i-eu5q"
FLOODNET_SENSORS = "kb2e-tjy3"
COVERAGE_FLOODNET = date(2020, 11, 16)  # first detected event
MM_PER_INCH = 25.4

# ---- frozen alert pins -----------------------------------------------------------
# Three eras of one signal. The two Socrata archives carry their own incident keys
# (status_id pre-2020, event_id/update_number post-2020); the archiver's own capture
# carries ticket 02's lmm alert_id. All three are rendered into 02's frozen alert_id
# grammar so ONE extractor, with ONE measured precision, serves every era.
ALERTS_OLD = "3h5b-5ktz"   # MTA Service Alerts 2012-10-02 .. 2020-03-31
ALERTS_NEW = "7kct-peq7"   # MTA Service Alerts, beginning 2020-04-28
# The two archives do not share an agency vocabulary — 'Subway' in the old one, 'NYCT
# Subway' in the new — and one filter for both silently returns an EMPTY old era rather
# than an error (measured: it did, and cost the whole 2012-2020 label era until soda()
# started refusing empty answers).
ALERT_AGENCY = {ALERTS_OLD: "Subway", ALERTS_NEW: "NYCT Subway"}
# the keyword prefilter, verbatim from research/subway-flood-labels.md, widened by the
# live family ticket 02 measured (zero live rows carry the legacy literals)
ALERT_WHERE = (
    "agency='{agency}' AND ("
    "upper(header) like '%FLOOD%' OR upper(description) like '%FLOOD%'"
    " OR upper(header) like '%WATER COND%' OR upper(description) like '%WATER COND%'"
    " OR upper(header) like '%WATER FROM THE TRACKS%'"
    " OR upper(description) like '%WATER FROM THE TRACKS%')")
COVERAGE_ALERT = (date(2012, 10, 2), date(2020, 3, 31), date(2020, 4, 28))
ALERT_DARK = (date(2026, 6, 30), date(2026, 8, 15))  # Socrata tail -> archiver capture

# ---- frozen USGS / Sandy pins ----------------------------------------------------
# STN's single-event parameter is Event=, never EventId= (which answers HTTP 500), and a
# bare County= without the literal " County" suffix answers [] with HTTP 200 — so the
# borough filter runs client-side against countyName.
STN_HWM = "https://stn.wim.usgs.gov/STNServices/HWMs/FilteredHWMs.json?Event={event}"
# event_id -> the NY day the marks belong to. A high-water mark is a peak, not a timed
# sighting: the day is what carries into the spine, and both days sit inside their event.
STN_EVENTS = {24: date(2012, 10, 29),   # Sandy
              312: date(2021, 9, 1)}    # Ida
# The county filter needs the state: STN answers nationwide, and Kings (CA, WA) and
# Richmond (GA, NC, VA) are county names in other states Sandy and Ida also hit.
HWM_STATE = "NY"
NYC_COUNTIES = ("Bronx", "Kings", "New York", "Queens", "Richmond")
HWM_EXPECT = {24: 111}  # measured NYC marks for Sandy; the vault's independent count
SANDY_ZONE = "5xsi-dfpx"      # NYC Sandy Inundation Zone, 492 field-verified polygons
SANDY_DAY = date(2012, 10, 29)  # the landfall day; the footprint is the whole event's

SOURCES = ("311", "floodnet", "mta_alert", "usgs_hwm", "sandy")
OBS_TS_KIND = ("incident", "report", "alert")


# ---- snapshots -------------------------------------------------------------------

def snapshot(root: Path, name: str, url: str) -> Path:
    """A pinned source snapshot under <root>/archive/flood, fetched only when missing.
    Written through .part so a killed fetch never leaves a truncated snapshot behind."""
    path = root / "archive" / "flood" / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {url}", flush=True)
        tmp = path.with_name(path.name + ".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(path)
    return path


def soda(root: Path, name: str, base: str, dataset: str, allow_empty: bool = False,
         **params) -> list[dict]:
    """Every row of a SODA query, paged and snapshotted whole. :id ordering is the only
    stable paging order Socrata offers.

    An empty answer is a FAILURE, not an empty source: every filter here is pinned to
    literals the endpoint is supposed to still carry, so zero rows means a pin went stale
    and the build must stop rather than cache the hole (measured: an agency literal that
    was right for one era and wrong for the other cached an empty 2012-2020 alert archive
    and silently deleted eight years of labels)."""
    path = root / "archive" / "flood" / name
    if path.exists():
        return json.loads(path.read_text())
    rows: list[dict] = []
    while True:
        q = {f"${k}": v for k, v in params.items()}
        q.update({"$limit": PAGE, "$offset": len(rows), "$order": ":id"})
        url = f"{base}/{dataset}.json?{urllib.parse.urlencode(q)}"
        print(f"downloading {url}", flush=True)
        with urllib.request.urlopen(url, timeout=300) as r:
            page = json.loads(r.read())
        rows += page
        if len(page) < PAGE:
            break
    if not rows and not allow_empty:
        raise RuntimeError(f"{dataset} answered zero rows for {params} — a frozen literal "
                           f"or the endpoint moved; nothing was snapshotted")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return rows


def ny_utc(stamp: str) -> datetime:
    """A floating timestamp on the CITY's datasets is America/New_York wall time (verified
    on 311: the hour-of-day distribution peaks 09:00-16:00 and troughs 02:00-04:00)."""
    return datetime.fromisoformat(stamp).replace(tzinfo=NY).astimezone(timezone.utc)


def utc(stamp: str) -> datetime:
    """FloodNet is the exception: its floating stamps are already UTC. Measured against
    the pipeline's own AORC rain over the 141 events inside the built precip months —
    mean mm_1h in the sensor's Cell at the flood-start hour peaks at 8.49 reading them as
    UTC and falls monotonically to either side (3.25 at the -4 h EDT reading). Reading
    them as local would shift a fifth of the evening events onto the wrong NY day."""
    return datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)


def row(source: str, source_id: str, ts_utc: datetime, kind: str, lon: float, lat: float,
        wkt: str | None = None, depth_mm: float | None = None,
        text: str | None = None) -> dict:
    """One observation. lon/lat locate the row's Cell (the polygon centroid for polygons);
    wkt carries the geometry itself, defaulting to the point."""
    if source not in SOURCES or kind not in OBS_TS_KIND:
        raise ValueError(f"{source}/{kind} is not a label-grade source and kind")
    return {"source": source, "source_id": source_id, "ts_utc": ts_utc, "obs_ts_kind": kind,
            "wkt": wkt or f"POINT ({lon} {lat})", "lon": lon, "lat": lat,
            "depth_mm": depth_mm, "text": text}


# ---- 311 -------------------------------------------------------------------------

def rows_311(root: Path, asof: date = ASOF) -> dict[str, list[dict]]:
    """The four-literal union per era-dataset, raw. Coordinates are NOT filtered here:
    the daily counts behind the p99 trigger must count every report, including the ~2%
    that carry no usable point."""
    where = "descriptor in({})".format(",".join(f"'{d}'" for d in DESCRIPTORS))
    return {ds: soda(root, f"311_{ds}_{asof}.json", SODA_NYC, ds, where=where,
                     select="unique_key,created_date,descriptor,latitude,longitude")
            for ds in DATASET_311}


def daily_311(rows: list[dict]) -> dict[date, int]:
    """Reports per America/New_York calendar day — the series the p99 trigger is cut on."""
    out: dict[date, int] = {}
    for r in rows:
        d = datetime.fromisoformat(r["created_date"]).date()
        out[d] = out.get(d, 0) + 1
    return out


def obs_311(rows: list[dict]) -> tuple[list[dict], int]:
    """Points only. A report with no coordinate still counts as a report (it is in the
    daily series) but cannot attach to an asset, so it mints no observation."""
    out, dropped = [], 0
    for r in rows:
        lon, lat = r.get("longitude"), r.get("latitude")
        if lon in (None, "") or lat in (None, "") or (float(lon), float(lat)) == (0.0, 0.0):
            dropped += 1
            continue
        out.append(row("311", r["unique_key"], ny_utc(r["created_date"]), "report",
                       float(lon), float(lat), text=r["descriptor"]))
    return out, dropped


# ---- FloodNet --------------------------------------------------------------------

def obs_floodnet(root: Path, asof: date = ASOF) -> list[dict]:
    """Curated flood events, geometry joined on sensor_id to the DEP deployment table.
    Depth is inches at the source and millimetres here."""
    events = soda(root, f"floodnet_events_{asof}.json", SODA_NYC, FLOODNET_EVENTS)
    sensors = soda(root, f"floodnet_sensors_{asof}.json", SODA_NYC, FLOODNET_SENSORS)
    at = {}
    for s in sensors:
        lon, lat = _sensor_point(s)
        if lon is not None:
            at[(s.get("sensor_id") or "").strip()] = (lon, lat)
    out, unplaced = [], set()
    for e in events:
        sensor = (e.get("sensor_id") or "").strip()
        start = e.get("flood_start_time")
        p = at.get(sensor)
        if not start:
            continue
        if p is None:  # the deployment table is not a superset: one event-table sensor has
            unplaced.add(sensor)  # no location row, and an event with no point is no label
            continue
        depth = e.get("max_depth_inches")
        out.append(row("floodnet", f"{sensor}:{start}", utc(start), "incident",
                       p[0], p[1],
                       depth_mm=float(depth) * MM_PER_INCH if depth else None))
    if unplaced:
        print(f"floodnet: {len(unplaced)} sensor(s) absent from {FLOODNET_SENSORS}: "
              f"{sorted(unplaced)}", flush=True)
    return out


def _sensor_point(s: dict) -> tuple[float | None, float | None]:
    for lon_k, lat_k in (("longitude", "latitude"), ("lon", "lat")):
        if s.get(lon_k) and s.get(lat_k):
            return float(s[lon_k]), float(s[lat_k])
    geo = s.get("the_geom") or s.get("location") or s.get("point")
    if isinstance(geo, dict) and geo.get("coordinates"):
        c = geo["coordinates"]
        return float(c[0]), float(c[1])
    return None, None


# ---- MTA alerts ------------------------------------------------------------------

def adapt_socrata_alerts(rows: list[dict], era: str) -> list[dict]:
    """Socrata alert rows -> the shape ticket 02's extractor folds (alert_id, header,
    description, route_id, fetched_at).

    Both archives carry their own incident key — event_id/update_number in the 2020+ set,
    a reused status_id in the 2012-2020 set — and ticket 02 froze the live grammar
    lmm:alert:<event>:<update> around exactly that pair. Rendering both eras into the one
    grammar keeps INCIDENT_KEY/OBSERVATION_KEY meaning the same thing everywhere; the
    pre-2020 update component is the row's rank within its status_id by date, so it is a
    function of the snapshot, not of iteration order.
    """
    out: list[dict] = []
    seq: dict[str, int] = {}
    if era == "old":
        rows = sorted(rows, key=lambda r: (r.get("status_id") or "", r.get("date") or ""))
    for r in rows:
        if era == "old":
            incident = str(r.get("status_id") or "").strip()
            update = seq[incident] = seq.get(incident, -1) + 1
        else:
            incident = str(r.get("event_id") or "").strip()
            update = int(float(r.get("update_number") or 0))
        stamp = r.get("date") or r.get("update_date")
        if not incident or not stamp:
            continue
        base = {"alert_id": f"lmm:alert:{incident}:{update}",
                "header": r.get("header"), "description": r.get("description"),
                "fetched_at": ny_utc(stamp).timestamp()}
        routes = [p.strip() for p in (r.get("affected") or "").split("|") if p.strip()]
        out += [{**base, "route_id": rt} for rt in routes] or [{**base, "route_id": None}]
    return out


def alert_rows(root: Path, asof: date = ASOF) -> list[dict]:
    """Every era of captured alert prose, in one list the extractor can fold."""
    rows: list[dict] = []
    for dataset, era in ((ALERTS_OLD, "old"), (ALERTS_NEW, "new")):
        rows += adapt_socrata_alerts(
            soda(root, f"alerts_{dataset}_{asof}.json", SODA_NY, dataset,
                 where=ALERT_WHERE.format(agency=ALERT_AGENCY[dataset])), era)
    capture = root / "archive" / "subway_alerts"
    if capture.exists():
        con = duck.connect()
        cols = ("alert_id", "header", "description", "route_id", "fetched_at")
        rows += [dict(zip(cols, r)) for r in duck.table(con, capture).filter(
            "regexp_matches(upper(coalesce(\"header\", '') || ' ' "
            "|| coalesce(description, '')), 'FLOOD|WATER COND|WATER FROM THE TRACKS')"
        ).project('alert_id, "header", description, route_id, fetched_at').fetchall()]
        con.close()
    return rows


def reconcile(obs: list[dict]) -> list[dict]:
    """Cross-event state reconciliation — this ticket's job (ticket 13 renders per event
    and does not reconcile).

    One physical flood mints several alert events: the 2026-08-20 night put World Trade
    Center under four event ids and Utica Av under two, and because each event carries
    only its OWN newest revision they disagree — 264048 ends active on Utica Av while
    264063 reports it cleared. Concurrency is what makes them one flood, so events naming
    the same complex whose [first_seen, last_seen] spans OVERLAP merge into one
    observation, and the newest revision across the merged events owns the state. No gap
    tolerance is needed or invented: every measured disagreement overlaps in time.
    """
    by_complex: dict[str, list[dict]] = {}
    for o in sorted(obs, key=lambda o: (o["complex_id"], o["first_seen"] or 0,
                                        o["event_id"])):
        by_complex.setdefault(o["complex_id"], []).append(o)
    out = []
    for complex_id, group in sorted(by_complex.items()):
        merged: list[list[dict]] = []
        for o in group:
            if merged and o["first_seen"] <= max(m["last_seen"] for m in merged[-1]):
                merged[-1].append(o)
            else:
                merged.append([o])
        for cluster in merged:
            newest = max(cluster, key=lambda o: (o["last_seen"], o["event_id"]))
            out.append({"complex_id": complex_id,
                        "event_ids": [o["event_id"] for o in cluster],
                        "first_seen": min(o["first_seen"] for o in cluster),
                        "last_seen": newest["last_seen"], "state": newest["state"],
                        "name": newest["name"]})
    return sorted(out, key=lambda o: (o["first_seen"], o["complex_id"]))


def obs_alert(root: Path, asof: date = ASOF) -> list[dict]:
    """Station-named alert floods, one row per reconciled physical flood at a complex.

    Ticket 02 mints one observation per (event_id, complex_id); this table lands ONE row
    on the complex per flood, because a per-event row would count the World Trade Center
    night four times in any downstream density.
    """
    by_alias = fa.load_aliases(root)
    pat = fa.build_pattern(by_alias)
    pairs = fa.observations(alert_rows(root, asof), by_alias, pat, live_only=False)
    at = complex_points(root)
    out = []
    for o in reconcile(pairs):
        p = at.get(o["complex_id"])
        if p is None:  # a complex the registry no longer carries: fail loudly, never drop
            raise RuntimeError(f"alert complex {o['complex_id']} missing from ref/assets")
        out.append(row("mta_alert", f"{'+'.join(o['event_ids'])}:{o['complex_id']}",
                       datetime.fromtimestamp(o["first_seen"], timezone.utc), "alert",
                       p[0], p[1], text=o["name"]))
    return out


def complex_points(root: Path) -> dict[str, tuple[float, float]]:
    t = pq.read_table(root / "ref" / "assets", columns=["kind", "complex_id", "lon", "lat"])
    return {c: (lo, la) for k, c, lo, la in zip(*(t.column(n).to_pylist()
                                                  for n in t.column_names)) if k == "complex"}


# ---- USGS high-water marks and the Sandy footprint --------------------------------

def obs_hwm(root: Path, asof: date = ASOF,
            expect: dict[int, int] | None = HWM_EXPECT) -> list[dict]:
    """Surveyed marks inside the five boroughs. elev_ft is a peak water-SURFACE elevation
    in NAVD88, not a depth above ground, so depth_mm stays NULL — ticket 07 owns the
    ground elevation that would turn one into the other."""
    out = []
    for event, day in STN_EVENTS.items():
        name = f"usgs_hwm_event{event}_{asof}.json"
        marks = json.loads(snapshot(root, name, STN_HWM.format(event=event)).read_text())
        got = 0
        for m in marks:
            if m.get("stateName") != HWM_STATE or (
                    m.get("countyName") or "").replace(" County", "") not in NYC_COUNTIES:
                continue
            lon = m.get("longitude_dd") or m.get("longitude")
            lat = m.get("latitude_dd") or m.get("latitude")
            if lon in (None, "") or lat in (None, ""):
                continue
            got += 1
            out.append(row("usgs_hwm", f"{event}:{m['hwm_id']}",
                           datetime.combine(day, time(0), NY).astimezone(timezone.utc),
                           "incident", float(lon), float(lat),
                           text=m.get("hwmTypeName") or m.get("hwm_environment")))
        want = (expect or {}).get(event)
        if want not in (None, got):
            raise RuntimeError(f"USGS event {event}: {got} NYC marks, expected {want} — "
                               f"the survey or the county filter moved")
    return out


def obs_sandy(root: Path, asof: date = ASOF) -> list[dict]:
    """The field-verified inundation footprint. A polygon is a whole-event footprint, not
    a timed sighting: the day is what carries, so ts is NY-midnight of the landfall day."""
    import shapely

    rows = soda(root, f"sandy_{SANDY_ZONE}_{asof}.json", SODA_NYC, SANDY_ZONE)
    ts = datetime.combine(SANDY_DAY, time(0), NY).astimezone(timezone.utc)
    out = []
    for i, r in enumerate(rows):
        geo = r.get("the_geom") or r.get("multipolygon")
        if not geo:
            continue
        poly = shapely.from_geojson(json.dumps(geo))
        c = poly.centroid
        out.append(row("sandy", str(r.get("objectid") or i), ts, "incident",
                       c.x, c.y, wkt=poly.wkt))
    return out


# ---- the table -------------------------------------------------------------------

SCHEMA = ("source string, source_id string, ts_utc timestamp, obs_ts_kind string, "
          "wkt string, lon double, lat double, depth_mm double, text string")
ORDER = ("source", "source_id", "ts_utc", "obs_ts_kind", "wkt", "lon", "lat",
         "depth_mm", "text")


def write(root: Path, spark, rows: list[dict]) -> None:
    """One sorted GeoParquet part, staged then moved (the ref-table idiom, byte-identical
    rebuilds within a session)."""
    import shutil

    df = spark.createDataFrame([tuple(r[c] for c in ORDER) for r in rows], SCHEMA)
    df = df.selectExpr(
        "source", "source_id", "ts_utc", "obs_ts_kind",
        "ST_SetSRID(ST_GeomFromText(wkt), 4326) AS geometry",
        "ST_H3CellIDs(ST_Point(lon, lat), 8, false)[0] AS cell",
        "depth_mm", "text").coalesce(1).sortWithinPartitions("source", "ts_utc", "source_id")
    staging = root / ".staging" / "flood_obs"
    df.write.format("geoparquet").mode("overwrite").save(str(staging))
    out = root / "silver" / "flood_obs" / "part-00000.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    (part,) = staging.glob("part-*.parquet")
    shutil.move(part, out)
    shutil.rmtree(staging)
    print(f"silver/flood_obs: {len(rows)} rows -> {out}", flush=True)


def build(root: Path, spark, asof: date = ASOF,
          expect: dict[int, int] | None = HWM_EXPECT) -> list[dict]:
    per_dataset = rows_311(root, asof)
    rows, dropped, n311 = [], 0, 0
    for ds, raw in sorted(per_dataset.items()):
        got, lost = obs_311(raw)
        rows += got
        dropped += lost
        n311 += len(raw)
        print(f"311 {ds}: {len(raw)} reports, {len(got)} placed", flush=True)
    print(f"311: {n311} reports, {dropped} without a usable point "
          f"({dropped / max(n311, 1):.1%})", flush=True)
    for name, fetch in (("floodnet", obs_floodnet), ("mta_alert", obs_alert),
                        ("usgs_hwm", lambda r, a: obs_hwm(r, a, expect)),
                        ("sandy", obs_sandy)):
        got = fetch(root, asof)
        print(f"{name}: {len(got)} observations", flush=True)
        rows += got
    write(root, spark, rows)
    return rows


# ---- the canary ------------------------------------------------------------------

def count(base: str, dataset: str, where: str | None = None) -> int:
    """A live row count. Never snapshotted: a cached canary cannot catch a rename."""
    q = {"$select": "count(1) as n"}
    if where:
        q["$where"] = where
    url = f"{base}/{dataset}.json?{urllib.parse.urlencode(q)}"
    with urllib.request.urlopen(url, timeout=120) as r:
        return int(json.loads(r.read())[0]["n"])


def canary(asof: date = ASOF, days: int = 30) -> dict[str, int]:
    """Every frozen source literal and endpoint must still answer, or the build fails.

    The four 311 literals are the sharp end: the city renamed the dropdown once already
    and the two-literal set silently lost every label after 2026-07. The RENAMES must
    match rows in the trailing 30 days; the legacy pair is asserted non-empty over the
    whole record instead, because the city has already retired it (measured: SJ ends
    2026-07-29, SH 2026-07-21) — a trailing window on those two would fail every build
    from now on and teach everyone to ignore the canary.
    """
    since = (asof - timedelta(days=days)).isoformat()
    live = {}
    for d in DESCRIPTORS:
        where = f"descriptor='{d}'" + ("" if d in DESCRIPTORS_LEGACY
                                       else f" AND created_date > '{since}'")
        live[f"311:{d}"] = count(SODA_NYC, "erm2-nwe9", where)
    for dataset, agency in ALERT_AGENCY.items():
        live[f"alerts:{agency}"] = count(SODA_NY, dataset, f"agency='{agency}'")
    for dataset in (FLOODNET_EVENTS, FLOODNET_SENSORS, SANDY_ZONE):
        live[dataset] = count(SODA_NYC, dataset)
    dead = [k for k, n in live.items() if n == 0]
    if dead:
        raise RuntimeError(f"source canary: no rows for {dead} — a frozen literal or "
                           f"endpoint moved. Re-measure before rebuilding: every event "
                           f"boundary and every label downstream rides on these pins.")
    return live


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--measure", action="store_true",
                    help="print the 311 daily series and its nearest-rank quantiles")
    ap.add_argument("--skip-canary", action="store_true",
                    help="rebuild from the snapshots alone; the literals may be long dead")
    a = ap.parse_args()
    root = data_root()
    if a.measure:
        from raincheck.flood_spine import p99

        for ds, raw in sorted(rows_311(root).items()):
            series = daily_311(raw)
            counts = sorted(series.values())
            print(f"{ds}: {sum(counts)} reports over {len(counts)} days with >=1  "
                  f"p95={p99(series, 0.95)} p99={p99(series)} max={counts[-1]}")
        return
    from raincheck.spark import session

    if a.skip_canary:
        print("flood_obs: source canary SKIPPED", flush=True)
    else:
        for k, n in sorted(canary().items()):
            print(f"canary {k}: {n} rows", flush=True)
    build(root, session())


if __name__ == "__main__":
    main()
