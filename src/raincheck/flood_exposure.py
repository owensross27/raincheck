"""Flood-build ticket 10: `gold/flood_exposure` and the coefficient artifact.

ONE row per Unit (445 complexes + 13,370 bus stops + 1,351 Cells = 15,166) and ONE in-repo
JSON, so the score has exactly one artifact chain: ticket 09 fitted it, this writes it down,
ticket 11 loads the JSON and evaluates the SAME `eta()` live.

Nothing is refitted here. `research/flood-09-fits.json` is a READ: its gate is re-evaluated
with `flood_fits.gate()` (a pure function of the published summary — the verdict is never
re-typed) and the shipped role parameters come from `final.<role>.coef_raw` /
`intercept_raw`, which score as a plain dot product on the raw matrix scale.

What a score IS: the LINEAR PREDICTOR, not a probability. Probabilities live in the
validation tables only (spec, Exposure score), and the detector's display value is a rank,
so a sigmoid here would add a monotone transform nobody reads and invite calibration
claims the evidence does not support. `score_ref` and `score_severe` are that predictor at
the frozen reference forcings — p50 and p90 of the fit rows' precip terms — with every
other feature the Unit's own.

Three coverage rules, all of them already paid for upstream, none re-solved here:
  * NO NULL scores. `flood_matrix.elev_source()` applied the ring15_med fallback PER ROW at
    the feature layer, so the seven complexes with no graded entrance still aggregate over
    a real set. They are frozen by `complex_id` (never by station name — "86 St" alone
    names SIX complexes, so a name gate matches 18 and asserts nothing) and RE-DERIVED at
    build against `NO_GRADE_OK`.
  * The 60 MTA Bus Company stops outside the NYC DEM footprint are NOT IN THE MATRIX
    (flood 08 excluded them with a count) and cannot be scored off it. They are Units, so
    they get a row, a published `flags` class and the kind-median fallback score — never an
    imputed elevation, which is the one thing the exclusion exists to prevent.
  * `surge_margin_ft` comes from `flood_coastal.unit_margins()` and is never recomputed. It
    is NULL for the 404 Units with no point elevation behind them (344 Cells scored through
    a taxi Zone, the same 60 stops); those are flagged, not zeroed.

A complex's score is the MAX over its child entrances — an aggregate of doorway scores.
That rule defines the number; it carries NO skill claim. The independent complex-grain set
caught 1 of 118 positives (flood 09), so nothing downstream may word this as measured
complex-grain performance.

Both artifacts name the estimand: `flooded_reported`.
"""
import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from raincheck import (duck, features as ft, flood_coastal as fc, flood_fits as ff,
                       flood_labels as fl, flood_matrix as fm, ref)
from raincheck.paths import REPO, data_root

FITS = REPO / "research" / "flood-09-fits.json"
COEFFICIENTS = REPO / "research" / "flood-10-coefficients.json"

# Which fitted model scores which Unit kind. A complex has no features of its own.
KIND_MODEL = {"bus_stop": "point", "complex": "point", "cell": "cell"}
KINDS = tuple(sorted(KIND_MODEL))                      # the published Unit kinds
REF_LEVELS = {"score_ref": "p50", "score_severe": "p90"}

# The four stormwater levels (spec: deep / nuisance / analyzed-none / not-analyzed, never
# imputed) and the dummy column each one maps to. The base level is coded by ABSENCE, which
# is why it has no column; `models_of()` checks these names against the fitted point vector
# so a renamed dummy cannot pass silently.
SW_DUMMY = {"deep": "sw_deep", "nuisance": "sw_nuisance", "not-analyzed": "sw_not_analyzed"}
STORMWATER_CATS = tuple(sorted({ff.STORMWATER_BASE, *SW_DUMMY}))

# THE monotone-latch assertion, scoped to the terms that can only RISE inside a Window.
# `log1p_antecedent_mm_24h` is frozen at Window open and measured NEGATIVE at point grain
# (-0.093, flood 09); the latch never rested on it, and asserting all three precip terms
# fails this build on a coefficient the detector does not depend on.
IN_WINDOW = ("log1p_precip_max_mm_1h", "log1p_precip_total_mm")

# The seven complexes with no grade_ok entrance at all: every doorway elevation behind their
# score is a 15 m ring median. Frozen by complex_id with the NAME beside it as the drift
# canary, and re-derived at build — a gate keyed on the name reports 18 and asserts nothing.
NO_GRADE_OK = {"59": "9 Av", "74": "18 Av", "75": "20 Av", "78": "Avenue U",
               "79": "86 St", "134": "Sutter Av", "299": "Dyckman St"}

# The closed flag vocabulary. Flags carry the REASON a row is unusual; they are never NULL
# and an ordinary Unit carries an empty list.
FLAGS = {
    "elev_ring15_fallback":
        "every elevation behind this score is a 15 m ring median, not a graded 2017 sample "
        "(a bus stop whose own grade_ok is false; a complex with no graded entrance)",
    "no_dem_footprint":
        "outside the NYC DEM footprint, so this Unit has NO elevation at all and is not in "
        "gold/flood_matrix (flood 08 excluded it with a count); no elevation is imputed",
    "no_matrix_row":
        "this Unit has no feature row in gold/flood_matrix for a reason other than the DEM "
        "(a complex with no scorable doorway), so the model cannot be evaluated for it",
    "score_fallback_kind_median":
        "the score is the kind's median, not a model evaluation — the Unit's features "
        "could not be built at all. It rides beside the reason above",
    "no_surge_margin":
        "no point elevation stands behind this Unit, so flood_coastal has no margin to "
        "report; NULL, never zero",
}

# Frozen shape of the real root. `expect=None` on a fixture root. `no_matrix_row` is 0 and
# must stay 0: every complex on this registry has a scorable doorway and every scored Cell
# is in the matrix, so a non-zero count is a real regression, not a fallback doing its job.
EXPECT = {"units": 15166, "complex": 445, "bus_stop": 13370, "cell": 1351,
          "out_of_footprint": 60, "no_matrix_row": 0, "no_grade_ok": NO_GRADE_OK}

SCHEMA = pa.schema([("asset_id", pa.string()), ("kind", pa.string()),
                    ("model_id", pa.string()), ("score_ref", pa.float64()),
                    ("score_severe", pa.float64()), ("score_index", pa.float64()),
                    ("surge_margin_ft", pa.float64()),
                    ("flags", pa.list_(pa.string())), ("score_version", pa.string()),
                    ("matrix_version", pa.string()), ("fits_version", pa.string())])


# ---- pure seams ----------------------------------------------------------------------

def eta(model: Mapping, feats: Mapping[str, float]) -> float:
    """THE score: a plain dot product of `coef_raw` against the raw matrix columns.

    Not a probability — the linear predictor. Ticket 11 calls this with live precip terms
    in `feats`, which is why the same function builds the table: the offline and the live
    number cannot drift apart. Every coefficient needs its feature; a missing one raises
    rather than contributing zero, because a silently absent term is a different model.
    """
    coef = model["coef_raw"]
    missing = sorted(set(coef) - set(feats))
    if missing:
        raise KeyError(f"{model.get('model_id', '?')}: no value for {missing}")
    return float(model["intercept_raw"] + sum(coef[k] * feats[k] for k in sorted(coef)))


def dummies(kind: str, stormwater_cat: str) -> dict[str, float]:
    """The point model's dummy-coded columns. `stormwater_cat` is never imputed — an
    unknown level raises — and the base level gets NO term at all, which is what dummy
    coding against a base means: an `analyzed-none` row differs by the intercept alone."""
    if stormwater_cat not in STORMWATER_CATS:
        raise ValueError(f"stormwater_cat {stormwater_cat!r} is not one of "
                         f"{list(STORMWATER_CATS)} — this feature is never imputed")
    return {col: float(stormwater_cat == level) for level, col in sorted(SW_DUMMY.items())} | {
        "is_bus_stop": float(kind == "bus_stop")}


def forcing(model: Mapping, level: str) -> dict[str, float]:
    """The frozen reference forcing: each precip term at its p50 or p90 over the fit rows,
    read from the fits JSON in LOG1P space, which is the space the matrix stores and the
    model was fit in. Quoting mm means `expm1` of these — never `log1p` a second time."""
    pct = model["precip_percentiles_log1p"]
    return {term: float(pct[term][level]) for term in ff.PRECIP}


def cume_dist(values: Sequence[float]) -> list[float]:
    """The within-kind percentile of every value: the empirical CDF, (# <= x) / n, so ties
    share one index and the maximum reads 1.0. This is `score_index`, and the CDF knots
    published in the coefficient JSON are the same distribution for a live consumer."""
    a = np.asarray(values, dtype=np.float64)
    order = np.argsort(a, kind="stable")
    ranks = np.empty(a.size, dtype=np.float64)
    s = a[order]
    # last index of each tie run, +1, as a fraction of n
    ranks[order] = (np.searchsorted(s, s, side="right")).astype(np.float64) / a.size
    return [float(v) for v in ranks]


def cdf_knots(values: Sequence[float], n: int = 101) -> dict:
    """The published static view: `n` evenly spaced quantile knots of one kind's score_ref,
    enough for a consumer to place any score on the same curve `score_index` uses. Ticket
    11 reads this for DORMANT weather only — fed a live eta it reads ~0 in light rain and
    ties at the ceiling in a storm, which is why the live display is a rank instead."""
    a = np.asarray(values, dtype=np.float64)
    pct = np.linspace(0.0, 100.0, n)
    return {"n": int(a.size),
            "percentile": [float(round(p, 6)) for p in pct],
            "score_ref": [float(v) for v in np.percentile(a, pct, method="linear")]}


def score_version(identities: Mapping, models: Mapping, refs: Mapping) -> str:
    """sha1 over the label / features / precip identities plus the model constants.

    Structural, not clerical: a relabelled universe, a rebuilt DEM, one more AORC month, a
    different coefficient or a moved reference forcing each change the digest, so a
    downstream artifact stamped with an old one is detectably stale. Ticket 11 stamps this
    beside its own detector_version and refuses the model tier on skew.

    WHAT IS IN: everything about the upstream data and the fitted parameters — the four
    identities, the per-role model constants, the reference forcings, which model scores
    which kind, and the encoding that turns a Unit's stormwater level into a coefficient
    (permuting `SW_DUMMY` moves every point score, and the set-containment guard in
    `models_of` cannot see a permutation).

    WHAT IS DELIBERATELY OUT: the flag vocabulary, the assertion scope and the informational
    scale band — bumping the stamp for a reworded flag would refuse the live model tier over
    a cosmetic edit.

    WHAT IS NOT COVERED, and is a real limit rather than a choice: this is a hash of VALUES,
    so the module's own code — `POINT_SQL`'s aggregation, `eta`'s summation, the argmax
    behind the complex rule — rides only as the labels below. Editing that code changes
    scores without moving the digest; the tests, not this stamp, are what hold it.
    """
    return hashlib.sha1(json.dumps({
        "estimand": fl.ESTIMAND, "identities": dict(identities),
        "models": {r: {"model_id": m["model_id"], "features": list(m["features"]),
                       "coef_raw": m["coef_raw"], "intercept_raw": m["intercept_raw"],
                       "stormwater_base_level": m["stormwater_base_level"]}
                   for r, m in models.items()},
        "reference_forcings": dict(refs), "kind_model": KIND_MODEL,
        "stormwater_dummy": SW_DUMMY, "kind_indicator": "is_bus_stop",
        "complex_rule": "max over child entrance scores",
        "fallback": "kind median score_ref/score_severe",
    }, sort_keys=True).encode()).hexdigest()


def coefficients(path: Path = COEFFICIENTS) -> dict:
    """THE detector's loader (ticket 11). One file, one call, no second model."""
    return json.loads(path.read_text())


# ---- the build -----------------------------------------------------------------------

# Every aggregate here is a "this is constant per Unit" claim, so each one carries its own
# distinct-count and the gate compares the TUPLE. Summing the counts would not work:
# count(DISTINCT ...) skips NULLs, so 2 + 1 + 0 also reaches 3 and a drifting column passes.
POINT_SQL = """
SELECT asset_id, any_value(kind) AS kind, any_value(complex_id) AS complex_id,
       min(elev_ft) AS elev_ft, min(relief_ft) AS relief_ft,
       min(stormwater_cat) AS stormwater_cat,
       count(DISTINCT elev_ft) AS n_elev, count(DISTINCT relief_ft) AS n_relief,
       count(DISTINCT stormwater_cat) AS n_cat, count(DISTINCT kind) AS n_kind,
       count(DISTINCT complex_id) AS n_cx
  FROM m WHERE role = 'fit_point' GROUP BY asset_id ORDER BY asset_id
"""
POINT_STATIC = ("n_elev", "n_relief", "n_cat", "n_kind")

# The chronic-reporter control is the one static feature that MOVES: it is a 3-year
# trailing count, so a Cell carries one value per event. The frozen choice is the newest
# fit-era event's — the most current 3-year window — taken with arg_max over event_id,
# which is the event DAY as an ISO string and therefore sorts chronologically.
CELL_SQL = """
SELECT asset_id, min(share_deep) AS share_deep, min(share_nuisance) AS share_nuisance,
       min(share_not_analyzed) AS share_not_analyzed,
       arg_max(density_311_3y, event_id)::DOUBLE AS density_311_3y,
       max(event_id) AS as_of,
       count(DISTINCT share_deep) AS n_deep,
       count(DISTINCT share_nuisance) AS n_nuisance,
       count(DISTINCT share_not_analyzed) AS n_not_analyzed,
       sum(density_311_3y IS NULL)::INT AS n_null_density
  FROM m WHERE role = 'fit_cell' GROUP BY asset_id ORDER BY asset_id
"""
CELL_STATIC = ("n_deep", "n_nuisance", "n_not_analyzed")


def shipped(fits: Mapping) -> dict:
    """Re-evaluate the headline gate from the published summary and take the model ids it
    selects. `flood_fits.gate()` is a pure function of the JSON, so the verdict is READ,
    never re-typed — and a JSON whose stored gate disagrees with its own tables is a
    corrupted artifact, not something to build on."""
    g = ff.gate(fits["summary"])
    if g["shipped"] != fits["gate"]["shipped"] or g["branch"] != fits["gate"]["branch"]:
        raise RuntimeError(f"{FITS.name}: stored gate {fits['gate']['branch']}/"
                           f"{fits['gate']['shipped']} disagrees with a re-evaluation of "
                           f"its own summary ({g['branch']}/{g['shipped']})")
    return g


def models_of(fits: Mapping, gate: Mapping) -> dict:
    """The shipped parameters per role, straight out of `final.<role>` — never refitted.

    The B2 branch is a real branch of the gate and this build refuses it loudly rather than
    guessing: `final` holds the FITTED model only, so climatology would need per-Unit
    values that flood 09 publishes nowhere. It did not fire (both roles won on
    2026-08-24); if it ever does, that is a ticket, not a fallback.
    """
    out = {}
    for role, model_id in sorted(gate["shipped"].items()):
        if not model_id.endswith(":l2_logistic"):
            raise NotImplementedError(
                f"gate shipped {model_id} for role {role}: this artifact carries the "
                f"FITTED parameters from final.{role}, and {FITS.name} publishes no "
                f"per-Unit climatology to carry instead — see summary.{role} and "
                f"flood_fits.climatology()")
        f = fits["final"][role]
        if role == "point" and not set(SW_DUMMY.values()) <= set(f["coef_raw"]):
            raise RuntimeError(f"the fitted point vector {sorted(f['coef_raw'])} does not "
                               f"carry the stormwater dummies {sorted(SW_DUMMY.values())}")
        neg = {t: f["coef_raw"][t] for t in IN_WINDOW if f["coef_raw"][t] < 0}
        if neg:
            raise RuntimeError(
                f"{role}: in-Window event-side coefficients must be non-negative for the "
                f"detector's monotone latch, got {neg}")
        mm = f["precip_percentiles_mm"]
        for term, by_level in f["precip_percentiles_log1p"].items():
            for level, v in by_level.items():
                if not np.isclose(np.expm1(v), mm[term][level], rtol=1e-9, atol=1e-9):
                    raise RuntimeError(f"{role}.{term}.{level}: mm {mm[term][level]} is not "
                                       f"expm1({v}) — a precip term was transformed twice")
        out[role] = {"model_id": model_id, **f}
    return out


def _registry(root: Path) -> list[dict]:
    reg = ref.read_ref(root, "assets",
                       ["asset_id", "kind", "name", "complex_id", "scored"])
    return [dict(zip(reg, v)) for v in zip(*reg.values())]


def _units(rows: Sequence[Mapping]) -> list[dict]:
    """The Unit universe from the registry — the ONE place that decides which rows exist,
    so a Unit the matrix could not feature still gets a row and a reason."""
    return sorted((dict(r) for r in rows if r["scored"] and r["kind"] in KIND_MODEL),
                  key=lambda r: (r["kind"], r["asset_id"]))


def _elevation_classes(root: Path, rows: Sequence[Mapping]
                       ) -> tuple[set[str], dict[str, str | None], set[str]]:
    """How each Unit's elevation was come by, re-derived from the feature table every build.

    Returns (bus stops standing on the ring15_med fallback, complex_id -> NAME for the
    complexes with NO graded entrance at all, point assets with no elevation of any kind).
    Freezing the seven without re-deriving them is how a moved set goes unnoticed, and the
    name travels only as the drift canary beside the id it can never replace.
    """
    feats = {r["asset_id"]: r for r in pq.read_table(
        root / "silver" / "asset_features",
        columns=["asset_id", "elev_2017_m", "grade_ok", "ring15_med_m"]).to_pylist()}
    named = {r["complex_id"]: r["name"] for r in rows if r["kind"] == "complex"}

    stops, graded, parents, no_elev = set(), set(), set(), set()
    for r in rows:
        f = feats.get(r["asset_id"])
        if f is None:
            continue                      # stations and complexes carry no elevation
        # a point with neither a graded sample nor a ring has NO elevation at all: that is
        # `no_dem_footprint`, a more specific reason than the ring fallback, and it must
        # never claim a ring median it does not have. BOTH conditions, not just
        # elev_source(): that returns None for a grade_ok row whose canonical sample is
        # NULL, and such a row does have a ring — it is not outside the DEM footprint.
        if fm.elev_source(f) is None and f["ring15_med_m"] is None:
            no_elev.add(r["asset_id"])
        elif r["kind"] == "bus_stop" and not f["grade_ok"]:
            stops.add(r["asset_id"])
        if r["kind"] == "entrance":
            parents.add(r["complex_id"])
            if f["grade_ok"]:
                graded.add(r["complex_id"])
    return stops, {c: named.get(c) for c in sorted(parents - graded)}, no_elev


def build(root: Path, expect: dict | None = EXPECT, fits: Mapping | None = None,
          out: Path = COEFFICIENTS) -> int:
    """Score every Unit at the frozen reference forcings and write both artifacts.

    `fits` and `out` exist so a fixture root can be scored without loading the published
    asset or overwriting the in-repo one; production passes neither, which keeps the
    fitted-on-THIS-matrix check live rather than switched off in tests.
    """
    fits = json.loads(FITS.read_text()) if fits is None else fits
    gate = shipped(fits)
    models = models_of(fits, gate)

    con = duck.connect()
    part = root / "gold" / "flood_matrix"
    duck.table(con, part).create_view("m")      # a view, never a lazy .arrow() reader
    points = con.execute(POINT_SQL).to_arrow_table().to_pylist()
    cells = con.execute(CELL_SQL).to_arrow_table().to_pylist()
    con.close()

    drift = [p["asset_id"] for p in points
             if tuple(p[k] for k in POINT_STATIC) != (1,) * len(POINT_STATIC)
             or p["n_cx"] > 1]
    if drift:
        raise RuntimeError(f"{len(drift)} point Units carry more than one static feature "
                           f"value across events, e.g. {drift[:3]} — the matrix is not "
                           f"Unit-static and a single exposure row cannot represent them")
    drift = [c["asset_id"] for c in cells
             if tuple(c[k] for k in CELL_STATIC) != (1,) * len(CELL_STATIC)]
    if drift:
        raise RuntimeError(f"{len(drift)} Cells carry more than one stormwater share, "
                           f"e.g. {drift[:3]}")
    # arg_max SKIPS rows whose value is NULL while max(event_id) does not, so a NULL density
    # on the newest event would score the Cell off an older one while `as_of` still published
    # the newest. Refuse the input instead of publishing a date the density does not match.
    blank = [c["asset_id"] for c in cells if c["n_null_density"]]
    if blank:
        raise RuntimeError(f"{len(blank)} Cells carry a NULL 311 density, e.g. {blank[:3]} — "
                           f"the frozen as-of date would no longer name the event the "
                           f"density was taken from")
    as_of = sorted({c["as_of"] for c in cells})
    if len(as_of) != 1:
        raise RuntimeError(f"the 311 density freeze needs ONE as-of event across Cells, "
                           f"got {len(as_of)}: {as_of[:3]}...{as_of[-1:]}")

    stamp = _identities(root, fits, part)
    refs = {role: {name: forcing(models[role], level)
                   for name, level in sorted(REF_LEVELS.items())} for role in sorted(models)}
    version = score_version(stamp, models, refs)

    # score every matrix Unit; complexes then take the MAX over their child entrances
    scores: dict[str, dict[str, float]] = {}
    by_complex: dict[str, dict[str, float]] = {}
    for p in points:
        feats = {"elev_ft": p["elev_ft"], "relief_ft": p["relief_ft"],
                 **dummies(p["kind"], p["stormwater_cat"])}
        s = {name: eta(models["point"], {**feats, **refs["point"][name]}) for name in REF_LEVELS}
        if p["kind"] == "bus_stop":
            scores[p["asset_id"]] = s
        else:                                    # an entrance publishes no row of its own
            cur = by_complex.setdefault(p["complex_id"], s)
            by_complex[p["complex_id"]] = {n: max(cur[n], s[n]) for n in REF_LEVELS}
    for c in cells:
        feats = {k: c[k] for k in ("share_deep", "share_nuisance", "share_not_analyzed",
                                   "density_311_3y")}
        scores[c["asset_id"]] = {n: eta(models["cell"], {**feats, **refs["cell"][n]})
                                 for n in REF_LEVELS}

    registry = _registry(root)
    units = _units(registry)
    for u in (u for u in units if u["kind"] == "complex"):
        got = by_complex.get(u["complex_id"])
        if got is not None:                 # else: no scorable doorway, flagged below
            scores[u["asset_id"]] = got

    ring_stops, ring_complexes, no_elev = _elevation_classes(root, registry)
    margins = {m["asset_id"]: m["surge_margin_ft"] for m in fc.unit_margins(root)}
    if set(margins) != {u["asset_id"] for u in units}:
        raise RuntimeError("flood_coastal.unit_margins() and the registry disagree about "
                           "the Unit universe — the two are derived independently and must "
                           "not drift")

    # The kind-median fallback, taken over the MODEL-SCORED rows only: a Unit whose features
    # could not be built at all is priced as the typical Unit of its kind and SAYS SO in
    # flags. It imputes a SCORE, never a feature — an imputed elevation is the one thing
    # flood 08's exclusion exists to prevent.
    fallback = {}
    for k in KINDS:
        have = [scores[u["asset_id"]] for u in units
                if u["kind"] == k and u["asset_id"] in scores]
        if not have:
            raise RuntimeError(f"no {k} Unit could be scored at all, so there is no median "
                               f"to fall back to — this is a broken matrix, not a fallback")
        fallback[k] = {n: float(np.median([s[n] for s in have])) for n in REF_LEVELS}

    rows = []
    for u in units:
        aid, kind = u["asset_id"], u["kind"]
        flags = []
        if aid in ring_stops or (kind == "complex" and u["complex_id"] in ring_complexes):
            flags.append("elev_ring15_fallback")
        s = scores.get(aid)
        if s is None:
            s = fallback[kind]
            flags += ["no_dem_footprint" if aid in no_elev else "no_matrix_row",
                      "score_fallback_kind_median"]
        if margins[aid] is None:
            flags.append("no_surge_margin")
        rows.append({"asset_id": aid, "kind": kind,
                     "model_id": models[KIND_MODEL[kind]]["model_id"],
                     "score_ref": s["score_ref"], "score_severe": s["score_severe"],
                     "score_index": None, "surge_margin_ft": margins[aid],
                     "flags": sorted(flags), "score_version": version,
                     "matrix_version": stamp["matrix_version"],
                     "fits_version": stamp["fits_version"]})

    cdf = {}
    for kind in KINDS:
        idx = [i for i, r in enumerate(rows) if r["kind"] == kind]
        vals = [rows[i]["score_ref"] for i in idx]
        for i, v in zip(idx, cume_dist(vals)):
            rows[i]["score_index"] = v
        cdf[kind] = cdf_knots(vals)

    _gates(rows, ring_complexes, expect)
    table = pa.Table.from_pylist(rows, schema=SCHEMA)
    dest = root / "gold" / "flood_exposure" / "part-00000.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table.replace_schema_metadata({
        **(table.schema.metadata or {}),
        b"estimand": fl.ESTIMAND.encode(),
        b"estimand_note": b"where flooding was REPORTED, not where water necessarily stood",
        b"score_version": version.encode(),
        b"score_note": (b"score_ref/score_severe are the model's LINEAR PREDICTOR at the "
                        b"frozen reference forcings, not probabilities; probabilities live "
                        b"in the validation tables only"),
        b"complex_rule": (b"a complex score is the MAX over its child entrance scores - an "
                          b"aggregate of doorway scores, never a measured complex-grain "
                          b"skill claim (the independent complex set caught 1 of 118)"),
        b"identities": json.dumps(stamp, sort_keys=True).encode(),
        b"census": json.dumps(_census(rows), sort_keys=True).encode(),
        b"coefficients": out.name.encode(),
    }), dest, compression="zstd")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_artifact(version, stamp, gate, models, refs, cdf, as_of[0]),
                              sort_keys=True, indent=2) + "\n")
    print(f"gold/flood_exposure: {len(rows)} rows, score_version {version[:12]}", flush=True)
    print(f"{out.name}: {len(models)} models, "
          f"{sum(c['n'] for c in cdf.values())} Units in the CDFs", flush=True)
    return len(rows)


def _identities(root: Path, fits: Mapping, part: Path) -> dict:
    """The upstream identities this score is a function of. `matrix_version` is read from
    the table's own footer AND recomputed from its inputs, because a matrix that no longer
    matches the labels/features/precip under it would silently poison every score; and the
    fits must have been fitted on THIS matrix, not a previous one."""
    (label_version,) = set(pq.read_table(root / "gold" / "flood_labels",
                                         columns=["label_version"]).column(0).to_pylist())
    meta = pq.read_metadata(sorted(part.glob("*.parquet"))[0]).metadata or {}
    stamped = (meta.get(b"matrix_version") or b"").decode()
    rebuilt = fm.matrix_version(root, label_version)
    if stamped != rebuilt:
        raise RuntimeError(f"gold/flood_matrix is stamped {stamped[:12]} but its inputs "
                           f"now hash to {rebuilt[:12]} — rebuild it (`make flood-matrix`) "
                           f"before scoring")
    if fits["matrix_version"] != stamped:
        raise RuntimeError(f"{FITS.name} was fitted on matrix {fits['matrix_version'][:12]}, "
                           f"not the {stamped[:12]} on disk — rerun `make flood-fits`")
    return {"label_version": label_version, "features_version": ft.features_version(root),
            "precip_identity": fm.precip_identity(root), "matrix_version": stamped,
            "fits_version": fits["fits_version"]}


def _census(rows: Sequence[Mapping]) -> dict:
    out = {"units": len(rows), "by_kind": {}, "by_flag": {f: 0 for f in sorted(FLAGS)},
           "null_surge_margin_ft": sum(r["surge_margin_ft"] is None for r in rows)}
    for r in rows:
        out["by_kind"][r["kind"]] = out["by_kind"].get(r["kind"], 0) + 1
        for f in r["flags"]:
            out["by_flag"][f] += 1
    return out


def _gates(rows: Sequence[Mapping], ring_complexes: Mapping, expect: dict | None) -> None:
    """What must be true of the written table, checked before it is written."""
    bad = [r["asset_id"] for r in rows
           if r["score_ref"] is None or r["score_severe"] is None
           or not np.isfinite(r["score_ref"]) or not np.isfinite(r["score_severe"])]
    if bad:
        raise RuntimeError(f"{len(bad)} Units have no usable score, e.g. {bad[:3]} — "
                           f"NO NULL scores is the contract")
    if len({r["asset_id"] for r in rows}) != len(rows):
        raise RuntimeError("gold/flood_exposure is one row per Unit; asset_id repeats")
    # NOT implied by the in-Window assertion, which is why it is checked separately. The
    # p50 -> p90 shift is a per-Unit CONSTANT summing the in-Window gain and the antecedent
    # term: at point grain that is +1.1940 and -0.2657, net +0.9283. A refit that leaves both
    # in-Window coefficients positive but strengthens the antecedent past about -0.42 would
    # ship a "severe" storm scoring BELOW a median one, and nothing above would notice.
    inverted = [r["asset_id"] for r in rows if r["score_severe"] < r["score_ref"]]
    if inverted:
        raise RuntimeError(f"{len(inverted)} Units score LOWER at the severe reference "
                           f"forcing than at the median one, e.g. {inverted[:3]} — the "
                           f"published pair would be backwards")
    unknown = sorted({f for r in rows for f in r["flags"]} - set(FLAGS))
    if unknown:
        raise RuntimeError(f"flags outside the published vocabulary: {unknown}")
    if expect is None:
        return
    cen = _census(rows)
    want = {"units": expect["units"],
            **{k: expect[k] for k in KINDS}}
    got = {"units": cen["units"], **cen["by_kind"]}
    if got != want:
        raise RuntimeError(f"Unit census moved: {got} != {want}")
    if cen["by_flag"]["no_dem_footprint"] != expect["out_of_footprint"]:
        raise RuntimeError(f"out-of-DEM stops: {cen['by_flag']['no_dem_footprint']} != "
                           f"{expect['out_of_footprint']}")
    if cen["by_flag"]["no_matrix_row"] != expect["no_matrix_row"]:
        raise RuntimeError(f"{cen['by_flag']['no_matrix_row']} Units fell back for a reason "
                           f"other than the DEM (expected {expect['no_matrix_row']}) — on "
                           f"this registry every complex has a scorable doorway and every "
                           f"scored Cell is in the matrix, so this is a regression")
    # keyed on complex_id; the NAME rides beside it as the drift canary and is checked too.
    # A name-keyed gate would match 18 complexes and assert nothing ("86 St" names SIX).
    if dict(ring_complexes) != dict(expect["no_grade_ok"]):
        raise RuntimeError(
            f"the complexes with no graded entrance moved: "
            f"{dict(sorted(ring_complexes.items()))} != "
            f"{dict(sorted(expect['no_grade_ok'].items()))}")


def _artifact(version: str, stamp: Mapping, gate: Mapping, models: Mapping,
              refs: Mapping, cdf: Mapping, density_as_of: str) -> dict:
    """THE coefficient JSON — everything ticket 11 needs to evaluate this model live, and
    nothing it would have to go and re-derive."""
    return {
        "estimand": fl.ESTIMAND,
        "estimand_note": "where flooding was REPORTED, not where water necessarily stood",
        "score_version": version,
        # identities holds ONLY identities, so a consumer may iterate it
        "identities": dict(stamp),
        "identities_note": "matrix_version already chains label_version, features_version "
                           "and precip_identity; it is verified equal to both the matrix's "
                           "own footer stamp and a recomputation from those three at build",
        "gate": {"branch": gate["branch"], "shipped": gate["shipped"],
                 "split": gate["split"], "panel_strings": gate["panel_strings"],
                 "note": "re-evaluate with flood_fits.gate(summary) against "
                         f"{FITS.name}; never re-type the verdict"},
        "score": {"kind": "linear predictor (eta) on the raw feature scale",
                  "is_probability": False,
                  "note": "probabilities live in the validation tables only; the live "
                          "display value is a within-kind rank, and the score_ref CDF "
                          "below is the STATIC view for dormant weather only"},
        "kind_model": KIND_MODEL,
        "complex_rule": {
            "rule": "max over child entrance scores",
            "claim": "an aggregate of doorway scores, never measured complex-grain skill",
            "evidence": "the independent complex-grain set caught 1 of 118 positives "
                        "(flood 09: CSI 0.0025, PR-AUC 0.0057, base rate 0.0027)"},
        "models": {role: {"model_id": m["model_id"], "features": list(m["features"]),
                          "coef_raw": m["coef_raw"], "intercept_raw": m["intercept_raw"],
                          "coef_standardized": m["coef_standardized"],
                          "intercept_standardized": m["intercept_standardized"],
                          "standardization": m["standardization"],
                          "stormwater_base_level": m["stormwater_base_level"],
                          "lambda": m["lambda"]}
                   for role, m in sorted(models.items())},
        "preprocessing": {
            "precip_transform": "log1p",
            "precip_note": "the matrix stores the precip terms ALREADY log1p'd; expm1 "
                           "before quoting mm and never log1p twice",
            "precip_terms": list(ff.PRECIP),
            "in_window_terms": list(IN_WINDOW),
            "in_window_note": "the monotone-latch claim rests on these two only; "
                              "log1p_antecedent_mm_24h is frozen at Window open and is "
                              "negative at point grain (-0.093), so it is not an "
                              "event-side term",
            "stormwater_levels": list(STORMWATER_CATS),
            "stormwater_base_level": ff.STORMWATER_BASE,
            "stormwater_dummy": dict(sorted(SW_DUMMY.items())),
            "stormwater_note": "dummy-coded against the base level, which gets NO term; "
                               "stormwater_dummy is the level -> coefficient-name map, "
                               "published so no consumer has to re-derive it from spelling",
            "kind_indicator": {"feature": "is_bus_stop", "one_when_kind_is": "bus_stop",
                               "note": "a complex's child entrances score as entrances, so "
                                       "is_bus_stop is 0 for every doorway behind a "
                                       "complex score"},
            "density_311_3y_as_of": density_as_of,
            "density_note": "the chronic-reporter control is a 3-year trailing count, "
                            "frozen at the newest fit-era event",
        },
        "reference_forcings": {
            role: {name: {"log1p": refs[role][name],
                          "mm": {t: float(np.expm1(v)) for t, v in refs[role][name].items()}}
                   for name in sorted(REF_LEVELS)}
            for role in sorted(refs)},
        "reference_forcings_note":
            "score_ref evaluates at p50 and score_severe at p90 of the fit rows' precip "
            "terms; every other feature is the Unit's own",
        "cdf": {"score": "score_ref", "by_kind": dict(sorted(cdf.items())),
                "method": "numpy percentile, linear interpolation",
                "note": "the static view: percentile knots of the PUBLISHED score_ref "
                        "(fallback rows included, exactly as they ship). It is the same "
                        "DATA as gold/flood_exposure.score_index but not the same "
                        "estimator — score_index is the empirical CDF (# <= x)/n, these "
                        "knots invert a linearly interpolated quantile, so reading a "
                        "percentile off them agrees with score_index to within ~0.6 "
                        "percentage points, not exactly"},
        "scale_band": {
            "pass2_over_aorc": list(ff.SCALE_BAND),
            "note": "MRMS Pass2 measured at 0.86-0.92 of AORC (flood 06). The fit is "
                    "AORC-only, so any MRMS-era number is read under this band and never "
                    "like-for-like. Informational: no code applies it."},
        "flags": dict(sorted(FLAGS.items())),
        "table": "gold/flood_exposure",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--census", action="store_true",
                    help="print the written table's census and exit, building nothing")
    a = ap.parse_args()
    root = data_root()
    if a.census:
        meta = pq.read_metadata(sorted(
            (root / "gold" / "flood_exposure").glob("*.parquet"))[0]).metadata or {}
        for k in (b"score_version", b"census", b"identities"):
            print(f"{k.decode()}: {(meta.get(k) or b'-').decode()}")
        return
    build(root)


if __name__ == "__main__":
    main()
