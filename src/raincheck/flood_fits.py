"""The fits, the baselines, the validation battery and the headline gate (flood-build
ticket 09 / spec "Exposure score" — models, validation).

`gold/flood_matrix` is a READ here. Nothing in it is re-derived: ticket 08 already resolved
the label, applied the per-row elevation fallback, excluded the out-of-footprint stops with
a count and froze the feature vector, so this module's only job is to fit two L2 logistic
models, run four baselines past them under two split schemes, and decide — in a pure
function over the published tables — which model id ships.

Two models, both L2 logistic, unweighted, lambda by INNER cross-validation:
  point   entrances + bus stops pooled, shared feature vector + a kind indicator
  cell    cells_scored, with the own-source 311 trailing density as the history covariate
A complex is never fitted — its score is the max over its child entrances' OUT-OF-FOLD
scores (a GROUP BY complex_id, event_id over the fit_point rows), which is what keeps the
alert-sourced complex-event pairs an independent complex-grain validation set.

Two splits, both deterministic sha1 group folds: event-grouped (the primary — a whole storm
is held out) and location-blocked (the GATE's split — a whole neighbourhood is held out).
The second is harder on purpose and has a consequence worth knowing before any number is
read: under location blocking a held-out Unit's whole history sits in the held-out fold, so
B2 (unit climatology) has nothing to memorise and measures as the base rate exactly. That is
what the split is for, and it is why the event-grouped column publishes beside it, where B2
is a real competitor — and beats the point model.

Everything published is out of fold, at an operating point chosen in fold: see OP_RATE for
what "chosen in fold" has to mean before a baseline can be compared fairly.

Run: make flood-fits    (python -m raincheck.flood_fits) — writes both build assets:
  research/flood-09-fits.md    the tables the release links
  research/flood-09-fits.json  the machine-readable artifact ticket 10 loads
"""
import argparse
import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from raincheck import duck, flood_matrix as fm
from raincheck.paths import REPO, data_root

K_FOLDS = 5
LAMBDAS = (0.01, 0.1, 1.0, 10.0, 100.0)   # the inner-CV grid, on STANDARDISED features
BOOTSTRAP_B = 1000                        # spec: event-cluster bootstrap, B = 1000
SEED = 20260824                           # the bootstrap's only source of randomness
SMOOTH_M = 1.0                            # B2's pseudo-count toward the training base rate
# THE OPERATING POINT: the CSI-maximising cut on the fold's TRAINING rows, transferred to
# the held-out rows as its ALERT RATE (a quantile of the held-out scores; no held-out label
# is read). Transferring the raw threshold looks purer and is not — a baseline whose
# held-out score is a per-fold constant then reads CSI 0.0 whenever that constant sits under
# the training cut, which is a fact about the score's scale, not about the baseline. The
# rate is also how this is deployed: the detector's tiers are a within-kind RANK (ticket
# 11), not a fixed probability. Both rules publish as sweep rows, so the choice is audited.
OP_RATE, OP_THRESHOLD = "rate", "threshold"
NEWTON_ITERS, NEWTON_TOL = 60, 1e-9
# Published FIM systems run CSI 0.26-0.45. It rides on the CSI table as a REFERENCE BAND
# and the comparison is order-of-magnitude only: those systems predict inundation extent
# from hydraulics over a different estimand (water present) than this one (flooding
# REPORTED at a doorway), on a different support, with a different positive rate.
FIM_BAND = (0.26, 0.45)
# The measured Pass2/AORC scale band (flood 06). Any MRMS-era replication metric is read
# under it, never as a like-for-like number.
SCALE_BAND = (0.86, 0.92)
STORMWATER_BASE = "analyzed-none"          # the dummy-coded reference level (698,326 rows)

# The frozen feature vectors. `sw_*` are the stormwater dummies against STORMWATER_BASE and
# `is_bus_stop` is the pooled point model's kind indicator; everything else is a matrix
# column, read as stored (THE PRECIP TERMS ARE ALREADY log1p'd — raw mm is expm1).
PRECIP = ("log1p_precip_max_mm_1h", "log1p_precip_total_mm", "log1p_antecedent_mm_24h")
POINT_FEATURES = PRECIP + ("elev_ft", "relief_ft", "sw_deep", "sw_nuisance",
                           "sw_not_analyzed", "is_bus_stop")
CELL_FEATURES = PRECIP + ("share_deep", "share_nuisance", "share_not_analyzed",
                          "density_311_3y")
FEATURES = {"point": POINT_FEATURES, "cell": CELL_FEATURES}
# density_311_3y rides on the POINT rows only as B3's baseline column, joined from the
# Cell rows on (cell, event_id). It is NOT a point-model feature: the frozen point vector
# is the spec's, and the history covariate belongs to the Cell model.
B3_COL = {"point": "density_311_3y_of_cell", "cell": "density_311_3y"}
BASELINES = ("B0_base_rate", "B1_precip_only", "B2_unit_climatology", "B3_density_only")
SPLITS = ("event_grouped", "location_blocked")
GATE_SPLIT = "location_blocked"           # the headline gate's split, per spec
PRIMARY_SPLIT = "event_grouped"           # the primary reporting split, per spec


# ---- pure seams: folds ---------------------------------------------------------------

def fold_of(key: str, k: int = K_FOLDS, salt: str = "") -> int:
    """Deterministic sha1 group fold. The same key lands in the same fold on every machine,
    in every process and after any reordering of the table — which is the only property the
    runnable check can assert without re-running a fit."""
    return int(hashlib.sha1(f"{salt}{key}".encode()).hexdigest(), 16) % k


def folds(keys: Iterable[str], k: int = K_FOLDS, salt: str = "") -> np.ndarray:
    return np.fromiter((fold_of(str(x), k, salt) for x in keys), dtype=np.int8)


# ---- pure seams: the fit -------------------------------------------------------------

def standardize(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Column means and standard deviations, computed on TRAINING rows only by every
    caller. A zero-variance column (a dummy with no members in this fold) reads sd 1 so it
    contributes nothing rather than dividing by zero."""
    mu, sd = X.mean(axis=0), X.std(axis=0)
    return mu, np.where(sd > 0, sd, 1.0)


def fit_l2(X: np.ndarray, y: np.ndarray, lam: float,
           w: np.ndarray | None = None) -> np.ndarray:
    """L2-penalised logistic regression by penalised IRLS (Newton). Returns
    [intercept, *coefficients] on whatever scale X arrives in; the intercept is NEVER
    penalised. `w` is an optional per-row weight (the 1/fan-out sensitivity fit; the
    primary fits are unweighted, exactly as the spec froze them).

    Newton rather than a gradient method because p is 7-9: the Hessian is a 10x10 solve and
    the 783k-row point fit converges in ~11 iterations. Ridge keeps X'WX + P positive
    definite, so no line search is needed."""
    n, p = X.shape
    Xa = np.hstack([np.ones((n, 1)), X])
    obs = np.ones(n) if w is None else np.asarray(w, dtype=np.float64)
    pen = np.eye(p + 1) * lam
    pen[0, 0] = 0.0
    b = np.zeros(p + 1)
    for _ in range(NEWTON_ITERS):
        eta = Xa @ b
        mu = 1.0 / (1.0 + np.exp(-eta))
        wt = obs * np.clip(mu * (1.0 - mu), 1e-9, None)
        z = eta + (y - mu) / np.clip(mu * (1.0 - mu), 1e-9, None)
        nb = np.linalg.solve(Xa.T @ (Xa * wt[:, None]) + pen, Xa.T @ (wt * z))
        step = float(np.max(np.abs(nb - b)))
        b = nb
        if step < NEWTON_TOL:
            break
    return b


def predict(X: np.ndarray, b: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-(b[0] + X @ b[1:])))


def unstandardize(b: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    """The same model expressed on the RAW feature scale, so ticket 10 scores a plain dot
    product against the matrix columns instead of re-deriving this module's constants."""
    raw = b[1:] / sd
    return np.r_[b[0] - float(np.sum(b[1:] * mu / sd)), raw]


# ---- pure seams: metrics -------------------------------------------------------------

def _pr_points(scores: np.ndarray, y: np.ndarray):
    """(distinct score, TP at that cut, rows at that cut) descending. Ties are GROUPED: a
    constant-score baseline and a heavily tied density column must not be scored as if the
    tie could be broken in the model's favour."""
    order = np.argsort(-scores, kind="stable")
    s, yy = scores[order], y[order]
    cut = np.r_[np.nonzero(np.diff(s))[0], s.size - 1] if s.size else np.array([], int)
    return s[cut], np.cumsum(yy)[cut], cut + 1


def best_threshold(scores: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """The IN-FOLD operating point: the cut maximising CSI on the rows handed in. Returns
    (threshold, its alert rate, its CSI) — the rate is what transfers to the held-out rows
    (see OP_RATE). Decisions are `score >= threshold`, matching the tie grouping here."""
    pos = float(y.sum())
    if pos == 0 or scores.size == 0:
        return math.inf, 0.0, 0.0
    s, tp, k = _pr_points(scores, y)
    csi = tp / (k + pos - tp)
    i = int(np.argmax(csi))
    return float(s[i]), float(k[i] / scores.size), float(csi[i])


def decide(scores: np.ndarray, fold: np.ndarray, run: Mapping,
           mode: str = OP_RATE) -> np.ndarray:
    """The held-out alarm vector: each fold's in-fold operating point applied to its own
    rows. OP_RATE takes the in-fold alert rate as a quantile of the held-out scores (no
    held-out LABEL is read — only the score distribution, exactly as a rank display would);
    OP_THRESHOLD transfers the raw probability cut."""
    pred = np.zeros(len(scores))
    for f in range(K_FOLDS):
        m = fold == f
        if not m.any():
            continue
        if mode == OP_THRESHOLD:
            cut = run["thr"][f]
        else:
            # the budget is spent over the population the fold was FITTED on. For an
            # unrestricted run that is the whole role, which is the operational read: one
            # deployed cut, and a subpopulation takes whatever share of it its own scores
            # earn. For a keep-restricted run (the bus-stop churn contrast) it is NOT: that
            # fold picked its budget on entrance training rows, so spending it across the
            # 502k bus rows it was told not to fit under-delivers the declared rate by
            # 28-47% per fold and inflates the published churn delta ~2.5x. Measured.
            pop = run.get("population")
            b = m if pop is None else (m & pop)
            rate, ok = run["rate"][f], scores[b][np.isfinite(scores[b])]
            cut = np.quantile(ok, 1.0 - rate) if rate > 0 and ok.size else math.inf
        pred[m] = (scores[m] >= cut).astype(float)
    return pred


def pr_auc(scores: np.ndarray, y: np.ndarray) -> float:
    """Average precision — the PR-AUC the spec keeps as a secondary, threshold-free read."""
    pos = float(y.sum())
    if pos == 0:
        return float("nan")
    _, tp, k = _pr_points(scores, y)
    rec, prec = tp / pos, tp / k
    return float(np.sum(np.diff(np.r_[0.0, rec]) * prec))


def skill(tp: float, fp: float, fn: float) -> dict:
    """CSI / POD / FAR from one confusion. FAR is the false ALARM RATIO (FP / predicted
    positive), the forecast-verification companion of POD and CSI — not FP / actual
    negative, which on a 0.4% base rate would read ~0 for any threshold at all."""
    return {"csi": tp / (tp + fp + fn) if tp + fp + fn else 0.0,
            "pod": tp / (tp + fn) if tp + fn else 0.0,
            "far": fp / (tp + fp) if tp + fp else 0.0,
            "tp": int(tp), "fp": int(fp), "fn": int(fn)}


def event_cluster_ci(pred: np.ndarray, y: np.ndarray, event_idx: np.ndarray,
                     n_events: int, b: int = BOOTSTRAP_B, seed: int = SEED) -> dict:
    """95% percentile intervals from resampling EVENTS with replacement.

    The cluster is the event because the rows are not independent: one storm decides ~7,500
    point rows at once, so a row bootstrap would report an interval an order of magnitude
    too tight. Per-event (tp, fp, fn) are summed once and the resamples index into them,
    which is why B = 1000 costs milliseconds."""
    tp = np.bincount(event_idx, weights=pred * y, minlength=n_events)
    fp = np.bincount(event_idx, weights=pred * (1 - y), minlength=n_events)
    fn = np.bincount(event_idx, weights=(1 - pred) * y, minlength=n_events)
    samp = np.random.default_rng(seed).integers(0, n_events, size=(b, n_events))
    TP, FP, FN = tp[samp].sum(1), fp[samp].sum(1), fn[samp].sum(1)
    den = np.maximum(TP + FP + FN, 1)
    out = {}
    for name, v in (("csi", TP / den), ("pod", TP / np.maximum(TP + FN, 1)),
                    ("far", FP / np.maximum(TP + FP, 1))):
        lo, hi = np.percentile(v, [2.5, 97.5])
        out[name] = [float(lo), float(hi)]
    return out


# The strings the panel and the release select FROM THE BRANCH THAT FIRED — the spec's
# "if B2 wins, v1 ships B2 and the release and panel say so", written down at the point the
# branch is decided rather than left to a later reader's memory. Ticket 15 (flood panel) and
# notify 09 render `headline`; the release checklist asserts `release`.
PANEL_STRINGS = {
    "MODEL": {"headline": "modelled flood exposure",
              "release": "v1 ships the fitted L2 logistic exposure score",
              "caveat": "fitted on reported flooding, 2010-2025 rain events"},
    "B2": {"headline": "how often this spot has been reported flooded",
           "release": "v1 ships B2 unit climatology - the fit did not beat it",
           "caveat": "a history count, not a model: places with no report read low"},
    "SPLIT": {"headline": "modelled where the fit earned it, history elsewhere",
              "release": "v1 ships per role - see gate.shipped for which id each role uses",
              "caveat": "one grain is modelled and one is climatology; the panel labels each"},
}


# ---- pure seam: the headline gate ----------------------------------------------------

def gate(summary: Mapping, split: str = GATE_SPLIT) -> dict:
    """THE headline gate, as a pure function of the published metrics table.

    `summary` is {role: {model_id: {split: {"csi": float, ...}}}} — exactly the object
    written into the JSON build asset, so the release checklist re-evaluates the gate from
    the published tables rather than trusting a sentence in a report. The model ships only
    if it beats BOTH B2 (unit climatology) and B3 (density-only) under the location-blocked
    split; if it does not, the shipped model id is B2 and the alternate panel strings are
    selected."""
    out = {"split": split, "roles": {}, "shipped": {}}
    for role, models in sorted(summary.items()):
        m = models["model"][split]["csi"]
        b2 = models["B2_unit_climatology"][split]["csi"]
        b3 = models["B3_density_only"][split]["csi"]
        won = m > b2 and m > b3
        out["roles"][role] = {"model_csi": m, "b2_csi": b2, "b3_csi": b3,
                              "beats_b2": m > b2, "beats_b3": m > b3, "model_wins": won}
        out["shipped"][role] = f"{role}:l2_logistic" if won else f"{role}:b2_climatology"
    out["branch"] = ("MODEL" if all(r["model_wins"] for r in out["roles"].values())
                     else "B2" if not any(r["model_wins"] for r in out["roles"].values())
                     else "SPLIT")
    out["panel_strings"] = PANEL_STRINGS[out["branch"]]
    return out


# ---- the rows ------------------------------------------------------------------------

@dataclass
class Rows:
    """One role's matrix rows, already numeric. `X` is the FULL design matrix for the role;
    a config selects columns out of it by name, which is what makes the ~25 one-at-a-time
    sweeps five fits each instead of a reload."""
    role: str
    X: np.ndarray
    y: np.ndarray
    names: tuple[str, ...]
    event_id: np.ndarray
    unit: np.ndarray
    cell: np.ndarray
    complex_id: np.ndarray | None = None
    extra: dict = field(default_factory=dict)

    def col(self, name: str) -> np.ndarray:
        return self.X[:, self.names.index(name)]

    def select(self, drop: Sequence[str] = ()) -> tuple[np.ndarray, tuple[str, ...]]:
        keep = [i for i, n in enumerate(self.names) if n not in drop]
        return self.X[:, keep], tuple(self.names[i] for i in keep)


POINT_SQL = f"""
SELECT m.asset_id, m.kind, m.event_id, m.cell, m.complex_id, m.flooded::INT AS y,
       m.log1p_precip_max_mm_1h, m.log1p_precip_total_mm, m.log1p_antecedent_mm_24h,
       m.elev_ft, m.relief_ft,
       (m.stormwater_cat = 'deep')::INT         AS sw_deep,
       (m.stormwater_cat = 'nuisance')::INT     AS sw_nuisance,
       (m.stormwater_cat = 'not-analyzed')::INT AS sw_not_analyzed,
       (m.kind = 'bus_stop')::INT               AS is_bus_stop,
       coalesce(c.density_311_3y, 0)            AS density_311_3y_of_cell,
       (c.density_311_3y IS NULL)::INT          AS density_missing
  FROM m LEFT JOIN (SELECT cell, event_id, density_311_3y FROM m WHERE role = 'fit_cell') c
    ON c.cell = m.cell AND c.event_id = m.event_id
 WHERE m.role = 'fit_point'
 ORDER BY m.event_id, m.asset_id
"""

CELL_SQL = """
SELECT asset_id, kind, event_id, cell, flooded::INT AS y,
       log1p_precip_max_mm_1h, log1p_precip_total_mm, log1p_antecedent_mm_24h,
       share_deep, share_nuisance, share_not_analyzed, density_311_3y::DOUBLE AS density_311_3y
  FROM m WHERE role = 'fit_cell' ORDER BY event_id, asset_id
"""

COMPLEX_SQL = """
SELECT complex_id, event_id, flooded::INT AS y, cell
  FROM m WHERE role = 'validate_complex' ORDER BY event_id, complex_id
"""


def load(root: Path) -> tuple[dict[str, Rows], dict, dict]:
    """The one read of gold/flood_matrix. Returns ({role: Rows}, the complex validation
    pairs, the file's own census/gates metadata) — the metadata rides into the report so
    the base rates published here carry ticket 08's pairable symmetry with them."""
    con = duck.connect()
    part = root / "gold" / "flood_matrix"
    duck.table(con, part).create_view("m")     # a view, never a lazy .arrow() reader

    def arr(t, name, dtype=np.float64):
        return t.column(name).to_numpy(zero_copy_only=False).astype(dtype)

    rows = {}
    t = con.execute(POINT_SQL).to_arrow_table()
    rows["point"] = Rows(
        role="point", names=POINT_FEATURES,
        X=np.column_stack([arr(t, n) for n in POINT_FEATURES]), y=arr(t, "y"),
        event_id=arr(t, "event_id", object), unit=arr(t, "asset_id", object),
        cell=arr(t, "cell", np.int64), complex_id=arr(t, "complex_id", object),
        extra={"kind": arr(t, "kind", object),
               B3_COL["point"]: arr(t, "density_311_3y_of_cell"),
               "density_missing": arr(t, "density_missing")})
    t = con.execute(CELL_SQL).to_arrow_table()
    rows["cell"] = Rows(
        role="cell", names=CELL_FEATURES,
        X=np.column_stack([arr(t, n) for n in CELL_FEATURES]), y=arr(t, "y"),
        event_id=arr(t, "event_id", object), unit=arr(t, "asset_id", object),
        cell=arr(t, "cell", np.int64), extra={"kind": arr(t, "kind", object)})
    t = con.execute(COMPLEX_SQL).to_arrow_table()
    cx = {"complex_id": arr(t, "complex_id", object), "event_id": arr(t, "event_id", object),
          "y": arr(t, "y"), "cell": arr(t, "cell", np.int64)}
    meta = pq.read_metadata(sorted(part.glob("*.parquet"))[0]).metadata or {}
    info = {k.decode(): v.decode() for k, v in meta.items()}
    con.close()
    return rows, cx, info


def group_key(rows: Rows, split: str) -> np.ndarray:
    return rows.event_id if split == "event_grouped" else rows.cell.astype(str)


# ---- cross-validation ----------------------------------------------------------------

def cv(rows: Rows, split: str, drop: Sequence[str] = (), lam: float | None = None,
       weights: np.ndarray | None = None, keep: np.ndarray | None = None) -> dict:
    """One out-of-fold pass: pick lambda by INNER CV inside each training part, standardise
    on the training rows only, fit, score the held-out rows, and take the operating point
    from the training rows. `keep` restricts which rows are FIT on (the bus-stop churn and
    era contrasts) while every kept row is still scored out of fold."""
    X, names = rows.select(drop)
    y = rows.y
    fold = folds(group_key(rows, split), salt=split)
    fit_mask = np.ones(len(y), bool) if keep is None else keep
    oof = np.full(len(y), np.nan)
    thr, rate = np.full(K_FOLDS, math.inf), np.zeros(K_FOLDS)
    chosen, insample = [], []
    for f in range(K_FOLDS):
        te = fold == f
        tr = (~te) & fit_mask
        if not tr.any() or not te.any():
            continue
        lam_f = lam if lam is not None else pick_lambda(X[tr], y[tr],
                                                        group_key(rows, split)[tr], split)
        mu, sd = standardize(X[tr])
        w = None if weights is None else weights[tr]
        b = fit_l2((X[tr] - mu) / sd, y[tr], lam_f, w)
        oof[te] = predict((X[te] - mu) / sd, b)
        thr[f], rate[f], c = best_threshold(predict((X[tr] - mu) / sd, b), y[tr])
        chosen.append(lam_f)
        insample.append(c)
    return {"oof": oof, "fold": fold, "thr": thr, "rate": rate, "lambdas": chosen,
            "names": names, "in_fold_csi": insample,
            "population": None if keep is None else fit_mask}


def pick_lambda(X: np.ndarray, y: np.ndarray, keys: np.ndarray, split: str) -> float:
    """Inner CV over the training part only, scored on PR-AUC (the metric that survives a
    0.4% base rate). The inner folds are the same deterministic sha1 grouping under a
    different salt, so a group never straddles the inner boundary either."""
    inner = folds(keys, salt=f"inner:{split}")
    best, best_score = LAMBDAS[0], -np.inf
    for lam in LAMBDAS:
        got = []
        for f in range(K_FOLDS):
            te = inner == f
            tr = ~te
            if not te.any() or y[tr].sum() == 0 or y[te].sum() == 0:
                continue
            mu, sd = standardize(X[tr])
            b = fit_l2((X[tr] - mu) / sd, y[tr], lam)
            got.append(pr_auc(predict((X[te] - mu) / sd, b), y[te]))
        score = float(np.mean(got)) if got else -np.inf
        if score > best_score:
            best, best_score = lam, score
    return best


def evaluate(rows: Rows, run: dict, mask: np.ndarray | None = None,
             op: str = OP_RATE) -> dict:
    """Pooled out-of-fold skill at the in-fold operating point, with the event-cluster
    bootstrap and the threshold-free PR-AUC beside it."""
    full = decide(np.nan_to_num(run["oof"], nan=-np.inf), run["fold"], run, op)
    keep = np.isfinite(run["oof"]) if mask is None else (np.isfinite(run["oof"]) & mask)
    s, y, pred = run["oof"][keep], rows.y[keep], full[keep]
    ev, idx = np.unique(rows.event_id[keep], return_inverse=True)
    m = skill(float((pred * y).sum()), float((pred * (1 - y)).sum()),
              float(((1 - pred) * y).sum()))
    m["pr_auc"] = pr_auc(s, y)
    m["ci"] = event_cluster_ci(pred, y, idx, len(ev))
    m["rows"], m["positives"], m["events"] = int(keep.sum()), int(y.sum()), len(ev)
    m["alert_rate"] = float(pred.mean())
    m["lambdas"] = run.get("lambdas", [])
    # the optimism the splits exist to expose: what the same cut scored on the rows the fold
    # was FITTED on. A model whose in-fold CSI towers over its out-of-fold CSI is memorising.
    m["in_fold_csi_mean"] = (float(np.mean(run["in_fold_csi"]))
                             if run.get("in_fold_csi") else None)
    return m


def per_event(rows: Rows, run: dict) -> list[dict]:
    """Per-event POD and RAW false-positive count — never per-event CSI: on this matrix most
    events carry a handful of positives (the counts publish in the report), and a CSI over
    one positive is a coin flip dressed as a metric."""
    keep = np.isfinite(run["oof"])
    y = rows.y[keep]
    pred = decide(np.nan_to_num(run["oof"], nan=-np.inf), run["fold"], run)[keep]
    ev, idx = np.unique(rows.event_id[keep], return_inverse=True)
    tp = np.bincount(idx, weights=pred * y, minlength=len(ev))
    fp = np.bincount(idx, weights=pred * (1 - y), minlength=len(ev))
    pos = np.bincount(idx, weights=y, minlength=len(ev))
    return [{"event_id": str(e), "positives": int(pos[i]), "tp": int(tp[i]),
             "fp": int(fp[i]), "pod": float(tp[i] / pos[i]) if pos[i] else None}
            for i, e in enumerate(ev)]


# ---- the baselines -------------------------------------------------------------------

def climatology(rows: Rows, split: str) -> dict:
    """B2 — unit climatology: each Unit's smoothed training-fold positive rate, no features
    at all. Under location blocking every held-out Unit's history is inside the held-out
    fold, so every score falls back to the prior and B2 measures as B0 exactly. Reported,
    not hidden (`held_out_rows_with_own_history` is the receipt)."""
    fold = folds(group_key(rows, split), salt=split)
    uid = np.unique(rows.unit, return_inverse=True)[1]
    n_units = uid.max() + 1
    oof = np.full(len(rows.y), np.nan)
    thr, rate = np.full(K_FOLDS, math.inf), np.zeros(K_FOLDS)
    seen = 0
    for f in range(K_FOLDS):
        te = fold == f
        tr = ~te
        prior = float(rows.y[tr].mean())
        n = np.bincount(uid[tr], minlength=n_units)
        p = np.bincount(uid[tr], weights=rows.y[tr], minlength=n_units)
        unit_rate = (p + SMOOTH_M * prior) / (n + SMOOTH_M)
        oof[te] = unit_rate[uid[te]]
        seen += int((n[uid[te]] > 0).sum())
        # the in-fold operating point, by the same rule the fits use: the threshold that
        # maximises CSI on the TRAINING rows, scored by the same training-fold rates
        thr[f], rate[f], _ = best_threshold(unit_rate[uid[tr]], rows.y[tr])
    return {"oof": oof, "fold": fold, "thr": thr, "rate": rate, "lambdas": [],
            "held_out_rows_with_own_history": seen}


def base_rate(rows: Rows, split: str) -> dict:
    """B0 — the training base rate as a constant score. Its max-CSI threshold can only
    alarm on everything or nothing, which is exactly the floor the other three have to
    clear."""
    fold = folds(group_key(rows, split), salt=split)
    oof = np.zeros(len(rows.y))
    for f in range(K_FOLDS):
        te = fold == f
        oof[te] = float(rows.y[~te].mean())
    # its max-CSI cut can only be "alarm on everything": one constant score, and CSI rises
    # with the alarm count at any base rate this low
    return {"oof": oof, "fold": fold, "thr": np.zeros(K_FOLDS),
            "rate": np.ones(K_FOLDS), "lambdas": []}


def baselines(rows: Rows, split: str) -> dict[str, dict]:
    b3 = B3_COL[rows.role]
    x3 = rows.col(b3) if b3 in rows.names else rows.extra[b3]
    only = Rows(role=rows.role, X=x3.reshape(-1, 1), y=rows.y, names=(b3,),
                event_id=rows.event_id, unit=rows.unit, cell=rows.cell)
    return {"B0_base_rate": base_rate(rows, split),
            "B1_precip_only": cv(rows, split, drop=[n for n in rows.names if n not in PRECIP]),
            "B2_unit_climatology": climatology(rows, split),
            "B3_density_only": cv(only, split)}


# ---- the independent complex-grain validation ----------------------------------------

def complex_validation(points: Rows, run: dict, cx: Mapping) -> dict:
    """The complex set, scored WITHOUT ever being fitted: max over the child entrances'
    OUT-OF-FOLD scores (a GROUP BY complex_id, event_id over the fit_point rows), deciding
    by "any child alarms at its own fold's operating point" — the same max rule, and still
    well defined when a complex's entrances fall in different folds. Pairs with no child
    entrance are COUNTED, never scored (on the landed matrix there are none)."""
    ent = (points.extra["kind"] == "entrance") & np.isfinite(run["oof"])
    key = np.char.add(np.char.add(points.complex_id[ent].astype(str), "|"),
                      points.event_id[ent].astype(str))
    uniq, idx = np.unique(key, return_inverse=True)
    score = np.zeros(len(uniq))
    np.maximum.at(score, idx, run["oof"][ent])
    alarm = np.zeros(len(uniq))
    child = decide(np.nan_to_num(run["oof"], nan=-np.inf), run["fold"], run)[ent]
    np.maximum.at(alarm, idx, child)
    pos = {u: i for i, u in enumerate(uniq)}
    want = np.char.add(np.char.add(cx["complex_id"].astype(str), "|"),
                       cx["event_id"].astype(str))
    have = np.array([pos.get(k, -1) for k in want])
    miss = int((have < 0).sum())
    keep = have >= 0
    s, a, y = score[have[keep]], alarm[have[keep]], cx["y"][keep]
    ev, eidx = np.unique(cx["event_id"][keep], return_inverse=True)
    m = skill(float((a * y).sum()), float((a * (1 - y)).sum()), float(((1 - a) * y).sum()))
    m["pr_auc"] = pr_auc(s, y)
    m["ci"] = event_cluster_ci(a, y, eidx, len(ev))
    m["rows"], m["positives"], m["events"] = int(keep.sum()), int(y.sum()), len(ev)
    m["pairs_without_child_entrances"] = miss
    # the complex grain's own single-positive census — the grain where the drafted "61% of
    # events" was closest to true, so it has to be published, not just asserted in prose
    per_ev = np.bincount(eidx, weights=y, minlength=len(ev))
    m["events_with_a_positive"] = int((per_ev > 0).sum())
    m["single_positive_events"] = int((per_ev == 1).sum())
    m["alert_rate"] = float(a.mean())
    # The same rate-transfer rule the row-grain metrics use, applied to the complex max
    # score: alarm the top `in-fold budget` of complex-event pairs. It separates two
    # different questions the union rule answers together — is the RANKING informative,
    # and does the point-grain operating point transfer to an aggregate of five children?
    budget = float(np.mean([r for r in run["rate"] if np.isfinite(r)]))
    cut = np.quantile(s, 1.0 - budget) if budget > 0 else math.inf
    ranked = (s >= cut).astype(float)
    m["rate_transfer"] = skill(float((ranked * y).sum()), float((ranked * (1 - y)).sum()),
                               float(((1 - ranked) * y).sum())) | {"budget": budget}
    # NOT an upper bound on the union rule (that rule cuts per fold and can beat any single
    # global cut): the best CSI ONE cut on the pooled max score could have reached, chosen
    # on this very set. Printed for scale — choosing a cutpoint on the validation set is
    # exactly what this set exists to prevent.
    m["best_single_cut_csi_selected_here"] = best_threshold(s, y)[2]
    return m


# ---- the sweeps ----------------------------------------------------------------------

def fanout_weights(rows: Rows) -> np.ndarray:
    """1/fan-out, as far as the landed tables allow. TRUE fan-out — how many Units one 311
    report attached to — is not stored (flood_labels keeps a bitmask and a max depth), and
    recovering it means re-attaching flood_obs to ref/assets, which is ticket 05's join and
    nobody else's. PROXY: positives sharing an (event, Cell), so a report that lit thirty
    stops in one Cell counts once. Negatives keep weight 1."""
    key = np.char.add(np.char.add(rows.event_id.astype(str), "|"), rows.cell.astype(str))
    uniq, idx = np.unique(key, return_inverse=True)
    npos = np.bincount(idx, weights=rows.y, minlength=len(uniq))
    w = np.ones(len(rows.y))
    hit = rows.y > 0
    w[hit] = 1.0 / np.maximum(npos[idx[hit]], 1.0)
    return w


# ---- the run -------------------------------------------------------------------------

def fits_version(matrix_version: str) -> str:
    """What names this battery: the matrix it read plus every constant that could move a
    number. Ticket 10 chains score_version on it."""
    return hashlib.sha1(json.dumps({
        "matrix_version": matrix_version, "features": FEATURES, "lambdas": LAMBDAS,
        "k_folds": K_FOLDS, "bootstrap_b": BOOTSTRAP_B, "seed": SEED,
        "smooth_m": SMOOTH_M, "splits": SPLITS, "gate_split": GATE_SPLIT,
        "stormwater_base": STORMWATER_BASE, "operating_point": "max-CSI in fold",
    }, sort_keys=True).encode()).hexdigest()


def run(root: Path) -> dict:
    """Every fit, baseline, split, sweep and gate — one pass over the matrix."""
    from raincheck.flood_fits_sweeps import (_contrasts, _weight_sweep, coverage,
                                             era_replication, run_sweeps)
    rows, cx, info = load(root)
    out = {"matrix_version": info.get("matrix_version"),
           "matrix_census": json.loads(info.get("census", "{}")),
           "matrix_gates": json.loads(info.get("gates", "{}")),
           "estimand": info.get("estimand"), "coverage": coverage(root),
           "era_replication": era_replication(info), "fim_band": list(FIM_BAND),
           "summary": {}, "final": {}, "sweeps": {}, "per_event": {}, "contrasts": {},
           "census": {}}
    out["fits_version"] = fits_version(out["matrix_version"] or "")
    runs: dict[tuple[str, str], dict] = {}

    for role, r in rows.items():
        print(f"[{role}] {len(r.y):,} rows, {int(r.y.sum()):,} positives, "
              f"{len(set(r.event_id)):,} events", flush=True)
        out["census"][role] = {
            "rows": len(r.y), "positives": int(r.y.sum()),
            "base_rate": float(r.y.mean()), "events": len(set(r.event_id)),
            "units": len(set(r.unit)), "cells": len(set(r.cell.tolist())),
            "by_kind": {k: {"rows": int((r.extra["kind"] == k).sum()),
                            "positives": int(r.y[r.extra["kind"] == k].sum())}
                        for k in sorted(set(r.extra["kind"].tolist()))}}
        models: dict[str, dict] = {}
        for split in SPLITS:
            primary = cv(r, split)
            runs[(role, split)] = primary
            models.setdefault("model", {})[split] = evaluate(r, primary)
            for name, b in baselines(r, split).items():
                models.setdefault(name, {})[split] = evaluate(r, b)
            print(f"  {split}: model CSI {models['model'][split]['csi']:.4f} "
                  f"(lambda {models['model'][split]['lambdas']}), "
                  f"B2 {models['B2_unit_climatology'][split]['csi']:.4f}, "
                  f"B3 {models['B3_density_only'][split]['csi']:.4f}", flush=True)
        out["summary"][role] = models
        out["per_event"][role] = per_event(r, runs[(role, GATE_SPLIT)])

        lam = modal_lambda(models["model"][GATE_SPLIT]["lambdas"])
        out["sweeps"][role] = run_sweeps(r, GATE_SPLIT, lam, models["model"][GATE_SPLIT],
                                         runs[(role, GATE_SPLIT)])
        out["sweeps"][role].append(_weight_sweep(r, GATE_SPLIT, lam,
                                                 out["sweeps"][role][0]))
        out["contrasts"][role] = _contrasts(root, r, runs, models, lam)
        out["final"][role] = _final_fit(r, models["model"][GATE_SPLIT]["lambdas"])

    out["complex_validation"] = {
        split: complex_validation(rows["point"], runs[("point", split)], cx)
        for split in SPLITS}
    out["gate"] = gate(out["summary"])
    print(f"GATE ({GATE_SPLIT}): {out['gate']['branch']} — shipped {out['gate']['shipped']}",
          flush=True)
    return out


def modal_lambda(lambdas: Sequence[float]) -> float:
    """The lambda the outer folds agreed on most often — what the shipped refit uses, and
    what the sweeps hold fixed so a one-at-a-time config is one fit per fold, not a nested
    re-selection whose delta would confound the knob with the penalty."""
    got = list(lambdas)
    if not got:
        return 1.0
    top = max(got.count(x) for x in set(got))
    # a 2-2-1 vote must not be settled by float hash order: on a tie take the STRONGER
    # penalty, the conservative direction (less variance carried into the shipped refit)
    return float(max(x for x in set(got) if got.count(x) == top))


def _final_fit(r: Rows, lambdas: Sequence[float]) -> dict:
    """The model that SHIPS: refit on every fit row at the modal CV lambda, published on
    both the standardised and the raw feature scale so ticket 10 scores a dot product."""
    lam = modal_lambda(lambdas)
    mu, sd = standardize(r.X)
    b = fit_l2((r.X - mu) / sd, r.y, lam)
    raw = unstandardize(b, mu, sd)
    return {"lambda": lam, "intercept_standardized": float(b[0]),
            "coef_standardized": {n: float(v) for n, v in zip(r.names, b[1:])},
            "intercept_raw": float(raw[0]),
            "coef_raw": {n: float(v) for n, v in zip(r.names, raw[1:])},
            "standardization": {n: {"mean": float(m), "std": float(s)}
                                for n, m, s in zip(r.names, mu, sd)},
            "features": list(r.names), "stormwater_base_level": STORMWATER_BASE,
            "precip_percentiles_log1p": {
                n: {"p50": float(np.percentile(r.col(n), 50)),
                    "p90": float(np.percentile(r.col(n), 90))} for n in PRECIP},
            "precip_percentiles_mm": {
                n: {"p50": float(np.expm1(np.percentile(r.col(n), 50))),
                    "p90": float(np.expm1(np.percentile(r.col(n), 90)))} for n in PRECIP}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--render-only", action="store_true",
                    help="re-render the markdown from the published JSON, no refit (the "
                         "markdown is a pure rendering, so this can never disagree)")
    args = ap.parse_args()
    from raincheck.flood_fits_report import render      # rendering imports the machinery

    out_md = REPO / "research" / "flood-09-fits.md"
    out_js = REPO / "research" / "flood-09-fits.json"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    if args.render_only:
        out_md.write_text(render(json.loads(out_js.read_text())))
        print(out_md, flush=True)
        return
    res = run(data_root())
    # written here rather than through a shell redirect: this run is minutes long, and `>`
    # would truncate the last good asset the moment anything raised.
    out_js.write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + "\n")
    out_md.write_text(render(res))
    print(f"{out_md}\n{out_js}", flush=True)


if __name__ == "__main__":
    main()
