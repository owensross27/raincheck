"""The training table (flood-build ticket 08 / spec "Exposure score").

`gold/flood_matrix` — one row per (Unit, event) with the frozen feature vector and the
label already resolved, so ticket 09's fit step is a READ, not a judgment call.

PLUVIAL EVENTS ONLY, fit era only. Sandy is coastal and leaves by that filter, not by a
special case: one coastal event would otherwise mint ~250-350 of ~1,350 Cell positives.

Three roles, one table:
  fit_point         entrances + bus stops; the pooled point model's rows
  fit_cell          cells_scored; the Cell model's rows
  validate_complex  complexes — NEVER fit. A complex is alert-only by construction
                    (ticket 05 asserts it), and its score is the max over its child
                    entrances' scores, so the complex-event pairs stay an INDEPENDENT
                    complex-grain validation set. `complex_id` rides on the entrance rows
                    so that aggregate is a GROUP BY, not a second join into ref/assets.

Positives come from `gold/flood_labels` (ticket 05, positives only). Negatives are the
read-side anti-join, generated here by `flood_labels.negatives()` under the spine's own
per-source coverage calendars — never re-derived. The POSITIVES run through
`flood_labels.pairable()` too: the label table deliberately stores positives the negative
rules reject, and keeping a 2015 bus-stop positive while the same rule deletes every 2015
bus-stop negative manufactures a class imbalance out of bookkeeping. What that drops is
published (`census()`), never hidden.

The barred-features wall is asserted on the written table, not just intended: nothing
FloodNet-derived, nothing grade_ok/epoch-delta-derived, nothing alert-derived, no borough,
no asset counts, no impact column (the absence assertion ticket 16 owes this matrix).
grade_ok is a FILTER here, exactly as flood 03 published it — it decides which elevation a
row carries and never travels as a column.

Run: make flood-matrix    (python -m raincheck.flood_matrix [--census])
"""
import argparse
import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from raincheck import duck, features as ft, flood_labels as fl, precip_flood_era as pfe
from raincheck.paths import data_root

EVENT_CLASS = "pluvial"          # the fit universe; coastal/mixed/snowmelt never enter
PRECIP_SRC = "aorc"              # pinned, never pooled with MRMS (ADR-0002)
FIT_ERA_LAST_YEAR = pfe.FIT_ERA_LAST_YEAR   # 2025, imported so the two can never drift
# The spec's era rules. 2026 has no AORC year (v1.1 publishes one Zarr per year), so its
# 11 union events cannot take fit-era precip at all: the pre-MRMS gap is validation-only
# (tickets 09) and the MRMS era is out-of-sample replication (ticket 18). `era()` is the
# seam those tickets call; this build emits FIT rows only and counts the rest.
MRMS_FROM = date(2026, 8, 14)
FIT, VALIDATION_ONLY, REPLICATION = "fit", "validation_only", "replication"

DENSITY_YEARS = 3                # own-source 311 trailing window, strictly before Window open
US_SURVEY_FT = ft.US_SURVEY_FT   # the map's canonical unit, imported from flood 03

# ---- frozen real-data counts, asserted blocking on the real build ------------------
# out_of_footprint: the 60 MTA Bus Company stops in Nassau County with neither a 2017 DEM
# sample nor a ring15 fallback — outside the NYC DEM footprint entirely (flood 03 froze
# the same 60). THE POLICY IS EXCLUDE-WITH-COUNT: they are dropped from the matrix and
# counted here, in the receipt and in the file's own metadata. Never a silent NULL, and
# never an imputed elevation.
# not_analyzed: DEP's fourth stormwater level at point grain, 745 = 673 inside the
# exclusion mask + 72 outside the study area. A level, never an imputation to
# "analyzed, no flooding".
# not_analyzed splits BECAUSE the two exclusions overlap exactly: all 60 out-of-footprint
# stops are Nassau County, which is outside DEP's study area, so all 60 carry
# "not-analyzed". 745 = 685 in the matrix + 60 excluded, and the build asserts that
# arithmetic rather than quietly publishing whichever number it happened to compute.
EXPECT = {"out_of_footprint": 60, "not_analyzed": 745, "not_analyzed_in_matrix": 685,
          "events": 133, "events_2026": 11}
# The SEVEN complexes with entrances but ZERO grade_ok entrances (flood 03's measurement).
# They are why the ring15_med fallback is applied PER ROW, before any read-side aggregate:
# a GROUP BY over grade_ok children returns nothing for these, and gold/flood_exposure
# mandates no NULL scores. Frozen by complex_id WITH the name each must still carry (the
# flood_labels.OPENED precedent): the seven station NAMES are not unique — "86 St" alone
# names five complexes, and a name match returns 18 — so a name-keyed gate would silently
# assert nothing. The build re-derives the set and refuses to run if it moved.
NO_GRADE_OK = {"59": "9 Av", "74": "18 Av", "75": "20 Av", "78": "Avenue U",
               "79": "86 St", "134": "Sutter Av", "299": "Dyckman St"}

# ---- the feature vector, frozen pre-fit -------------------------------------------
SHARED = ("log1p_precip_max_mm_1h", "log1p_precip_total_mm", "log1p_antecedent_mm_24h")
POINT_ONLY = ("elev_ft", "relief_ft", "stormwater_cat")   # + kind, the indicator
CELL_ONLY = ("share_deep", "share_nuisance", "share_not_analyzed", "density_311_3y")
FEATURES = {"fit_point": SHARED + POINT_ONLY, "fit_cell": SHARED + CELL_ONLY,
            "validate_complex": SHARED}
KEYS = ("asset_id", "kind", "event_id", "cell", "complex_id", "role", "era", "flooded")

# ---- the barred-features wall ------------------------------------------------------
# Substrings, matched case-insensitively against every column name in the written table.
# Each entry names a channel that would let the model memorise the label rather than learn
# the terrain: FloodNet is a label source (spec bars its derivatives outright); grade_ok
# and the epoch delta concentrate on alert-heavy complexes inside the Sandy polygon;
# alert-derived anything leaks the complex validation set into the point fit; borough and
# asset counts are administrative proxies; impact is EVIDENCE on the far side of the wall
# (ticket 16's own rule, asserted here because this is the table it could leak into).
BARRED = ("floodnet", "grade_ok", "epoch", "alert", "borough", "n_assets", "asset_count",
          "service_ratio", "gap_ratio", "resid_ratio", "nbr_ratio", "speed_ratio",
          "caught", "impact", "source_mix", "label_support", "depth_mm")


# ---- pure derivation ---------------------------------------------------------------

def era(day_start: date) -> str:
    """Which era an event belongs to — the spec's rule as a function, so tickets 09 and 18
    tag the same way this build filters."""
    if day_start.year <= FIT_ERA_LAST_YEAR:
        return FIT
    return REPLICATION if day_start >= MRMS_FROM else VALIDATION_ONLY


def in_fit_universe(event: Mapping) -> bool:
    return event["event_class"] == EVENT_CLASS and era(event["day_start"]) == FIT


def elev_source(feat: Mapping) -> float | None:
    """THE elevation a row carries, in metres: the canonical 2017 sample where the QC
    boolean passed, the 15 m ring median where it did not (flood 03's rule — never a Cell
    median, measured strictly worse). Applied PER ROW, which is what makes the seven
    zero-grade_ok complexes aggregate to something downstream.

    None means the DEM had nothing here and the ring had nothing either: out of footprint,
    excluded with a count, never imputed."""
    return feat["elev_2017_m"] if feat["grade_ok"] else feat["ring15_med_m"]


def relief_m(feat: Mapping) -> float | None:
    """The ONE relief term: how far this doorway sits above its own 15 m neighbourhood.
    A fallback row reads 0.0 by construction — it has no relief information, and saying so
    is honest; imputing a neighbourhood delta it never measured would not be."""
    e = elev_source(feat)
    return None if e is None or feat["ring15_med_m"] is None else e - feat["ring15_med_m"]


def log1p(mm: float | None) -> float | None:
    return None if mm is None else math.log1p(mm)


# ---- version stamps ----------------------------------------------------------------

def precip_identity(root: Path) -> str:
    """What names the Precip side of this matrix: the pinned source, the fit-era horizon
    and the exact set of built AORC Cell-month partitions. A month appearing (or
    disappearing) under a Window moves a feature, so it has to move the stamp."""
    part = root / "silver" / "precip_cell_hourly" / f"src={PRECIP_SRC}"
    months = sorted(p.name for p in part.glob("month=*")) if part.exists() else []
    if not months:
        raise RuntimeError(f"no {PRECIP_SRC} Cell-months under {part} — run "
                           f"`make precip-flood-era` (flood 06) before this matrix")
    return hashlib.sha1(json.dumps(
        {"src": PRECIP_SRC, "fit_era_last_year": FIT_ERA_LAST_YEAR,
         "months": months}, sort_keys=True).encode()).hexdigest()


def matrix_version(root: Path, label_version: str) -> str:
    """sha1 chaining the three identities this table is a function of — labels (which
    already chain the spine and the registry), features, precip — plus the constants that
    decide which rows and which columns exist. Ticket 18's alternate universes stamp
    differently by construction; so does a rebuild after DEP or the DEM republishes."""
    return hashlib.sha1(json.dumps({
        "label_version": label_version, "features_version": ft.features_version(root),
        "precip_identity": precip_identity(root), "event_class": EVENT_CLASS,
        "fit_era_last_year": FIT_ERA_LAST_YEAR, "mrms_from": MRMS_FROM.isoformat(),
        "density_years": DENSITY_YEARS, "features": {k: list(v) for k, v in FEATURES.items()},
        "keys": KEYS, "barred": BARRED, "us_survey_ft": US_SURVEY_FT,
    }, sort_keys=True).encode()).hexdigest()


# ---- the build ---------------------------------------------------------------------

SCHEMA = pa.schema([
    ("asset_id", pa.string()), ("kind", pa.string()), ("event_id", pa.string()),
    ("cell", pa.int64()), ("complex_id", pa.string()), ("role", pa.string()),
    ("era", pa.string()), ("flooded", pa.bool_()),
    ("log1p_precip_max_mm_1h", pa.float64()), ("log1p_precip_total_mm", pa.float64()),
    ("log1p_antecedent_mm_24h", pa.float64()),
    ("elev_ft", pa.float64()), ("relief_ft", pa.float64()),
    ("stormwater_cat", pa.string()),
    ("share_deep", pa.float64()), ("share_nuisance", pa.float64()),
    ("share_not_analyzed", pa.float64()), ("density_311_3y", pa.int32()),
    ("matrix_version", pa.string())])

ROLE = {"entrance": "fit_point", "bus_stop": "fit_point", "cell": "fit_cell",
        "complex": "validate_complex"}


def pairs(assets: Iterable[Mapping], events: Iterable[Mapping],
          positives: Iterable[tuple[str, str]]) -> tuple[list[dict], dict[str, int]]:
    """(every (Unit, event) row with its label, what the pairable rule dropped).

    Pure, over the same plain mappings `flood_labels.negatives` takes, so ticket 18 drives
    it with fixture calendars. Positives and negatives go through ONE rule: `pairable`.
    """
    units = {a["asset_id"]: a for a in assets if fl.in_universe(a)}
    evs = {e["event_id"]: e for e in events}
    pos = {(a, e) for a, e in positives}
    rows, dropped, off_universe = [], 0, 0
    for asset_id, event_id in sorted(pos):
        a, e = units.get(asset_id), evs.get(event_id)
        if e is None:
            continue          # a positive on an event this universe excludes (era/class)
        if a is None:
            # a positive on a Unit `in_universe` rejects. Ticket 05 mints none (its cell
            # branch filters on `scored`), so this is a registry drift alarm, not a rule —
            # counted rather than skipped, because a silently vanished positive is exactly
            # the class of bug the census exists to make impossible.
            off_universe += 1
            continue
        if not fl.pairable(a, e):
            dropped += 1      # stored by 05 on purpose; not a fit row, and counted
            continue
        rows.append({"asset_id": asset_id, "kind": a["kind"], "cell": a["cell"],
                     "complex_id": a["complex_id"], "event_id": event_id, "flooded": True})
    for n in fl.negatives(units.values(), evs.values(), pos):
        rows.append({**n, "complex_id": units[n["asset_id"]]["complex_id"],
                     "flooded": False})
    return rows, {"positives_dropped_unpairable": dropped,
                  "positives_off_universe": off_universe}


# The Window is (open, close]: an hour STAMPED at Window open covers the hour BEFORE it,
# which is antecedent, not Window. That same row is where mm_24h is frozen — one scan over
# the pruned month partitions serves both terms, and the freeze is structural rather than
# a promise a later edit could quietly break.
HOURS_SQL = """
CREATE TABLE hrs AS
  SELECT event_id, window_start_utc AS h, TRUE AS at_open FROM ev
  UNION ALL
  SELECT event_id, unnest(generate_series(window_start_utc + INTERVAL 1 HOUR,
                                          window_end_utc, INTERVAL 1 HOUR)), FALSE FROM ev
"""

PRECIP_SQL = """
CREATE TABLE pw AS
  SELECT p.cell, h.event_id,
         max(p.mm_1h) FILTER (WHERE NOT h.at_open) AS precip_max_mm_1h,
         sum(p.mm_1h) FILTER (WHERE NOT h.at_open) AS precip_total_mm,
         max(p.mm_24h) FILTER (WHERE h.at_open) AS antecedent_mm_24h
    FROM read_parquet($files) p JOIN hrs h ON h.h = p.hour_end_utc
   GROUP BY 1, 2
"""

DENSITY_SQL = f"""
-- the chronic-reporter control: own-source 311 only, STRICTLY before Window open, so no
-- report from inside the event can reach the feature that helps predict it
CREATE TABLE dens AS
  SELECT e.event_id, o.cell, CAST(count(*) AS INTEGER) AS density_311_3y
    FROM read_parquet($obs) o JOIN ev e
      ON o.ts_utc < e.window_start_utc
     AND o.ts_utc >= e.window_start_utc - INTERVAL {DENSITY_YEARS} YEAR
   WHERE o.source = '311'
   GROUP BY 1, 2
"""

SELECT_SQL = """
SELECT r.asset_id, r.kind, r.event_id, r.cell, r.complex_id, r.role, r.era, r.flooded,
       ln(1 + pw.precip_max_mm_1h)  AS log1p_precip_max_mm_1h,
       ln(1 + pw.precip_total_mm)   AS log1p_precip_total_mm,
       ln(1 + pw.antecedent_mm_24h) AS log1p_antecedent_mm_24h,
       f.elev_ft, f.relief_ft,
       CASE WHEN r.role = 'fit_point' THEN f.stormwater_cat END AS stormwater_cat,
       CASE WHEN r.role = 'fit_cell' THEN sw.share_deep END AS share_deep,
       CASE WHEN r.role = 'fit_cell' THEN sw.share_nuisance END AS share_nuisance,
       CASE WHEN r.role = 'fit_cell' THEN sw.share_not_analyzed END AS share_not_analyzed,
       CASE WHEN r.role = 'fit_cell' THEN coalesce(dens.density_311_3y, 0) END AS density_311_3y,
       $stamp AS matrix_version
  FROM rows r
  LEFT JOIN feat f ON f.asset_id = r.asset_id
  LEFT JOIN pw ON pw.cell = r.cell AND pw.event_id = r.event_id
  LEFT JOIN sw ON sw.cell = r.cell
  LEFT JOIN dens ON dens.cell = r.cell AND dens.event_id = r.event_id
 ORDER BY r.event_id, r.role, r.asset_id
"""


def build(root: Path, expect: dict | None = EXPECT) -> int:
    con = duck.connect()

    def rel(*parts: str):
        return duck.table(con, root.joinpath(*parts))

    events = pq.read_table(root / "silver" / "flood_events").to_pylist()
    fit_events = [e for e in events if in_fit_universe(e)]
    by_era: dict[str, int] = {}
    for e in events:
        by_era[era(e["day_start"])] = by_era.get(era(e["day_start"]), 0) + 1
    if not fit_events:
        raise RuntimeError("no pluvial fit-era events in silver/flood_events — run "
                           "`make flood-spine` (flood 04) first")

    acols = ["asset_id", "kind", "cell", "complex_id", "feeds", "scored"]
    assets = pq.read_table(root / "ref" / "assets", columns=acols).to_pylist()
    labels = pq.read_table(root / "gold" / "flood_labels",
                           columns=["asset_id", "event_id", "kind", "source_mix"])
    keep = {e["event_id"] for e in fit_events}
    pos = [(a, e) for a, e in zip(labels.column("asset_id").to_pylist(),
                                  labels.column("event_id").to_pylist()) if e in keep]
    # Sandy is a COASTAL event, so the pluvial filter is what excludes its polygon labels.
    # Asserted rather than assumed: a sandy bit inside a pluvial Window would mean the
    # spine had reclassified, and one coastal event mints ~250-350 of ~1,350 Cell positives.
    sandy = sum(1 for e, m in zip(labels.column("event_id").to_pylist(),
                                  labels.column("source_mix").to_pylist())
                if e in keep and m & fl.SOURCE_BIT["sandy"])
    if sandy:
        raise RuntimeError(f"{sandy} Sandy-sourced positives landed on a pluvial fit-era "
                           f"event — the Sandy exclusion rests on the event class")

    cen = fl.census(assets, fit_events, pos)
    rows, delta = pairs(assets, fit_events, pos)
    print(f"events: {by_era} by era, {len(fit_events)} pluvial in the fit era", flush=True)
    print(f"census: {cen}", flush=True)
    print(f"pairs: {len(rows)} ({sum(r['flooded'] for r in rows)} positives, "
          f"{delta['positives_dropped_unpairable']} positives dropped as unpairable — the "
          f"same rule that deletes their negatives; "
          f"{delta['positives_off_universe']} outside the negative universe)", flush=True)

    con.register("rows", pa.Table.from_pylist(
        [{**r, "role": ROLE[r["kind"]], "era": FIT} for r in rows],
        schema=pa.schema([("asset_id", pa.string()), ("kind", pa.string()),
                          ("cell", pa.int64()), ("complex_id", pa.string()),
                          ("event_id", pa.string()), ("flooded", pa.bool_()),
                          ("role", pa.string()), ("era", pa.string())])))
    con.register("ev", pa.Table.from_pylist(
        [{k: e[k] for k in ("event_id", "window_start_utc", "window_end_utc")}
         for e in fit_events]))
    # the elevation FALLBACK is applied here, per row, before anything aggregates it
    con.register("feat", pa.Table.from_pylist(
        [{"asset_id": f["asset_id"],
          "elev_ft": None if elev_source(f) is None else elev_source(f) * US_SURVEY_FT,
          "relief_ft": None if relief_m(f) is None else relief_m(f) * US_SURVEY_FT,
          "stormwater_cat": f["stormwater_cat"]}
         for f in pq.read_table(root / "silver" / "asset_features").to_pylist()],
        schema=pa.schema([("asset_id", pa.string()), ("elev_ft", pa.float64()),
                          ("relief_ft", pa.float64()), ("stormwater_cat", pa.string())])))
    rel("silver", "cell_stormwater").select(
        "cell, share_deep, share_nuisance, share_not_analyzed").create_view("sw")

    months = sorted((root / "silver" / "precip_cell_hourly" / f"src={PRECIP_SRC}")
                    .glob("month=*"))
    con.execute(HOURS_SQL)
    con.execute(PRECIP_SQL, {"files": [str(m / "*.parquet") for m in months]})
    con.execute(DENSITY_SQL, {"obs": f"{root / 'silver' / 'flood_obs'}/**/*.parquet"})
    stamp = matrix_version(root, _one_label_version(root))
    # to_arrow_table(), never a relation's .arrow(): that one is a LAZY reader bound to
    # this same connection, and registering it back here deadlocks at 0% CPU (wave-1 gate).
    table = con.execute(SELECT_SQL, {"stamp": stamp}).to_arrow_table().cast(SCHEMA)

    table, gate = _gates(root, table, con, expect)
    dest = root / "gold" / "flood_matrix" / "part-00000.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table.replace_schema_metadata({
        **(table.schema.metadata or {}),
        b"estimand": fl.ESTIMAND.encode(),
        b"estimand_note": b"where flooding was REPORTED, not where water necessarily stood",
        b"matrix_version": stamp.encode(),
        b"event_class": EVENT_CLASS.encode(), b"precip_src": PRECIP_SRC.encode(),
        b"census": json.dumps(cen).encode(),
        b"gates": json.dumps({**gate, **delta, "events_by_era": by_era}).encode(),
        b"out_of_footprint_policy": (
            b"MTA Bus Company stops outside the NYC DEM footprint are EXCLUDED with a "
            b"count (see gates.out_of_footprint); no elevation is ever imputed"),
    }), dest, compression="zstd")
    print(f"gold/flood_matrix: {table.num_rows} rows -> {dest}", flush=True)
    print(f"matrix_version = {stamp}", flush=True)
    return table.num_rows


def _one_label_version(root: Path) -> str:
    (v,) = set(pq.read_table(root / "gold" / "flood_labels",
                             columns=["label_version"]).column(0).to_pylist())
    return v


def _gates(root: Path, table: pa.Table, con,
           expect: dict | None) -> tuple[pa.Table, dict]:
    """Every gate this ticket owes, run on the assembled rows before a byte is written.

    Returns the rows that survive the out-of-footprint exclusion, and what the gates
    counted — the counts ride in the file's own metadata, so the exclusions stay readable
    from the bytes alone."""
    barred = sorted({c for c in table.column_names
                     for b in BARRED if b in c.lower()})
    if barred:
        raise RuntimeError(f"barred feature columns reached the matrix: {barred}")
    missing = set(KEYS) | {f for v in FEATURES.values() for f in v}
    if missing - set(table.column_names):
        raise RuntimeError(f"the frozen feature vector is short: "
                           f"{sorted(missing - set(table.column_names))}")

    con.register("m", table)
    def q(sql):
        return con.execute(sql).fetchall()

    # A point Unit with no asset_features row at all would fall through the exclusion
    # below and be MISCOUNTED as out-of-footprint. Two different facts, so two gates.
    (orphan,) = q(f"""SELECT count(DISTINCT m.asset_id) FROM m ANTI JOIN read_parquet(
        '{root / 'silver' / 'asset_features'}/**/*.parquet') f ON f.asset_id = m.asset_id
         WHERE m.role = 'fit_point'""")[0]
    if orphan:
        raise RuntimeError(f"{orphan} point Units have no silver/asset_features row — "
                           f"rebuild flood 03 before reading that as out-of-footprint")

    # the out-of-footprint policy: EXCLUDE, with a count. Never a silent NULL.
    (n_out,) = q("SELECT count(DISTINCT asset_id) FROM m WHERE role = 'fit_point' "
                 "AND elev_ft IS NULL")[0]
    out_ids = [a for (a,) in q("SELECT DISTINCT asset_id FROM m WHERE role = 'fit_point' "
                               "AND elev_ft IS NULL ORDER BY 1")]
    table = table.filter(pc.invert(pc.and_(pc.equal(table["role"], "fit_point"),
                                           pc.is_null(table["elev_ft"]))))
    con.unregister("m")
    con.register("m", table)
    print(f"out of the DEM footprint: {n_out} point Units excluded with a count "
          f"(first: {out_ids[:3]})", flush=True)

    for role, cols in FEATURES.items():
        for col in cols:
            (n,) = q(f"SELECT count(*) FROM m WHERE role = '{role}' "
                     f"AND {col} IS NULL")[0]
            if n:
                raise RuntimeError(f"{n} {role} rows carry a NULL {col} — every feature a "
                                   f"role's model reads must be present on every one of "
                                   f"its rows")
    if q("SELECT count(*) FROM (SELECT asset_id, event_id FROM m GROUP BY 1, 2 "
         "HAVING count(*) > 1)") != [(0,)]:
        raise RuntimeError("the grain is not one row per (Unit, event)")

    n_seven = _assert_fallback_reaches_the_aggregate(root, q, expect)

    if expect:
        got = {"out_of_footprint": n_out,
               "not_analyzed_in_matrix": q("SELECT count(DISTINCT asset_id) FROM m "
                                           "WHERE stormwater_cat = 'not-analyzed'")[0][0],
               "events": q("SELECT count(DISTINCT event_id) FROM m")[0][0],
               "events_2026": q(f"SELECT count(*) FROM read_parquet("
                                f"'{root / 'silver' / 'flood_events'}/**/*.parquet') "
                                f"WHERE year(day_start) > {FIT_ERA_LAST_YEAR}")[0][0]}
        got["not_analyzed"] = got["not_analyzed_in_matrix"] + n_out
        bad = {k: (got.get(k), v) for k, v in expect.items() if got.get(k) != v}
        if bad:
            raise RuntimeError(f"frozen count mismatch (got, expected): {bad}")
    con.unregister("m")
    return table, {"out_of_footprint": n_out,
                   "no_grade_ok_complexes_with_elevation": n_seven}


def _assert_fallback_reaches_the_aggregate(root: Path, q, expect: dict | None) -> int:
    """The zero-grade_ok complexes are re-DERIVED here, checked against the frozen seven on
    a real build, and then shown to have a child entrance carrying an elevation.

    That is the whole point of applying the ring15_med fallback per row: filter children to
    grade_ok first and these complexes aggregate over NOTHING, which lands as a NULL score
    in gold/flood_exposure, which mandates none. The derivation runs on every registry —
    only the identity of the seven is real-build-specific."""
    a = f"'{root / 'ref' / 'assets'}/**/*.parquet'"
    f = f"'{root / 'silver' / 'asset_features'}/**/*.parquet'"
    got = dict(q(f"""
        SELECT e.complex_id, any_value(cx.name)
          FROM read_parquet({a}) e JOIN read_parquet({f}) ft USING (asset_id)
          JOIN read_parquet({a}) cx ON cx.kind = 'complex' AND cx.complex_id = e.complex_id
         WHERE e.kind = 'entrance'
         GROUP BY 1 HAVING count(*) FILTER (WHERE ft.grade_ok) = 0"""))
    if expect and got != NO_GRADE_OK:
        raise RuntimeError(f"the zero-grade_ok complex set moved: {got} against the frozen "
                           f"{NO_GRADE_OK} — re-measure before trusting the fallback gate")
    if not got:
        return 0
    reached = q(f"""
        SELECT count(DISTINCT e.complex_id) FROM read_parquet({a}) e JOIN m
            ON m.asset_id = e.asset_id
         WHERE e.kind = 'entrance' AND m.elev_ft IS NOT NULL
           AND e.complex_id IN ({','.join(f"'{c}'" for c in got)})""")[0][0]
    if reached != len(got):
        raise RuntimeError(f"only {reached} of the {len(got)} zero-grade_ok complexes have "
                           f"a child entrance with an elevation — the ring15_med fallback "
                           f"did not run before the aggregate")
    print(f"zero-grade_ok complexes: {reached}/{len(got)} reached by the per-row "
          f"ring15_med fallback", flush=True)
    return reached


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--census", action="store_true",
                    help="print the negative universe over the pluvial fit era and stop")
    a = ap.parse_args()
    root = data_root()
    if a.census:
        events = [e for e in pq.read_table(root / "silver" / "flood_events").to_pylist()
                  if in_fit_universe(e)]
        assets = pq.read_table(root / "ref" / "assets").to_pylist()
        lab = pq.read_table(root / "gold" / "flood_labels",
                            columns=["asset_id", "event_id"])
        keep = {e["event_id"] for e in events}
        pos = [(a_, e_) for a_, e_ in zip(lab.column("asset_id").to_pylist(),
                                          lab.column("event_id").to_pylist()) if e_ in keep]
        for k, v in fl.census(assets, events, pos).items():
            print(f"{k}: {v}")
        return
    build(root)


if __name__ == "__main__":
    main()
