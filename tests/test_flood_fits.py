"""Flood-build ticket 09: the fits, the baselines, the validation battery, the gate.

The ticket's own testing decision is BUILD-ASSET EVIDENCE, not pytest — the numbers that
matter are measured on the real matrix and published in `research/flood-09-fits.{md,json}`.
What is runnable here is what the ticket names as runnable: the fold assignment is
deterministic, and the gate evaluation is a pure function of the published tables. Around
those two, the arithmetic seams every published number is built from (the IRLS fit, the
skill scores, the tie-grouped threshold sweep, the event-cluster bootstrap, the complex
max-over-children aggregate) and one end-to-end run over a PLANTED matrix, small enough to
run in seconds and shaped exactly like the real one.

Seam 3 (pure functions on arrays) plus one full `run()` over a fixture data root.
"""
import json
import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raincheck import flood_fits as ff, flood_matrix as fm
from raincheck.flood_fits_report import render

UTC = timezone.utc


# ---- the fixture matrix ---------------------------------------------------------------

def _events(n: int = 32) -> list[dict]:
    """Union events on real-shaped ids (the spine keys on the start date), a third of them
    pre-2014 so the pre/post contrast has both sides."""
    out = []
    for i in range(n):
        d = date(2010 + i // 4, 1 + (i * 3) % 12, 1 + (i * 7) % 27)
        start = datetime(d.year, d.month, d.day, 12, tzinfo=UTC)
        out.append({"event_id": d.isoformat(), "day_start": d, "day_end": d, "n_days": 1,
                    "window_start_utc": start, "window_end_utc": start + timedelta(hours=6),
                    "event_class": "pluvial"})
    return out


def _matrix(root, seed: int = 7) -> pa.Table:
    """A matrix with REAL SIGNAL in it: the label is drawn from a logistic in precip and
    elevation, so a fit that works beats a baseline and a fit that is wired backwards does
    not. Roles, kinds and the complex_id carriage match gold/flood_matrix exactly."""
    rng = np.random.default_rng(seed)
    events = _events()
    cells = [613229524682801151 + i for i in range(24)]
    rows = []
    units = ([(f"stn-ent:{i}", "entrance", str(i % 10)) for i in range(60)]
             + [(f"bus:{i}", "bus_stop", None) for i in range(40)])
    elev = {u: float(rng.uniform(-5, 90)) for u, _, _ in units}
    for e in events:
        pmax, ptot = float(rng.uniform(1, 40)), float(rng.uniform(2, 90))
        for j, (uid, kind, cx) in enumerate(units):
            eta = -4.0 + 0.06 * pmax + 0.02 * ptot - 0.03 * elev[uid]
            rows.append({
                "asset_id": uid, "kind": kind, "event_id": e["event_id"],
                "cell": cells[j % len(cells)], "complex_id": cx, "role": "fit_point",
                "era": fm.FIT, "flooded": bool(rng.random() < 1 / (1 + math.exp(-eta))),
                "log1p_precip_max_mm_1h": math.log1p(pmax),
                "log1p_precip_total_mm": math.log1p(ptot),
                "log1p_antecedent_mm_24h": math.log1p(float(rng.uniform(0, 20))),
                "elev_ft": elev[uid], "relief_ft": float(rng.normal(0, 2)),
                "stormwater_cat": ("deep", "nuisance", "analyzed-none",
                                   "not-analyzed")[j % 4]})
        for j, c in enumerate(cells):
            eta = -3.0 + 0.05 * pmax - 1.5 * (j % 3 == 0)
            rows.append({
                "asset_id": f"cell:{c}", "kind": "cell", "event_id": e["event_id"],
                "cell": c, "complex_id": None, "role": "fit_cell", "era": fm.FIT,
                "flooded": bool(rng.random() < 1 / (1 + math.exp(-eta))),
                "log1p_precip_max_mm_1h": math.log1p(pmax),
                "log1p_precip_total_mm": math.log1p(ptot),
                "log1p_antecedent_mm_24h": math.log1p(float(rng.uniform(0, 20))),
                "share_deep": 0.2, "share_nuisance": 0.3, "share_not_analyzed": 0.1,
                "density_311_3y": int(rng.integers(0, 40))})
        for cx in sorted({c for _, _, c in units if c}):
            rows.append({
                "asset_id": f"stn:{cx}", "kind": "complex", "event_id": e["event_id"],
                "cell": cells[int(cx) % len(cells)], "complex_id": cx,
                "role": "validate_complex", "era": fm.FIT,
                "flooded": bool(rng.random() < 0.05),
                "log1p_precip_max_mm_1h": math.log1p(pmax),
                "log1p_precip_total_mm": math.log1p(ptot),
                "log1p_antecedent_mm_24h": math.log1p(float(rng.uniform(0, 20)))})
    table = pa.Table.from_pylist(
        [{c: r.get(c) for c in fm.SCHEMA.names if c != "matrix_version"} for r in rows],
        schema=pa.schema([f for f in fm.SCHEMA if f.name != "matrix_version"]))
    table = table.append_column("matrix_version",
                                pa.array(["fixture" + "0" * 34] * table.num_rows))
    return table, events


@pytest.fixture(scope="module")
def fit_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("flood09")
    table, events = _matrix(root)
    dest = root / "gold" / "flood_matrix" / "part-00000.parquet"
    dest.parent.mkdir(parents=True)
    pq.write_table(table.replace_schema_metadata({
        b"matrix_version": b"fixture" + b"0" * 34, b"estimand": b"flooded_reported",
        b"census": json.dumps({"units": 124, "events": len(events)}).encode(),
        b"gates": json.dumps({"out_of_footprint": 0, "positives_dropped_unpairable": 11,
                              "events_by_era": {"fit": len(events), "replication": 1}
                              }).encode()}), dest)
    ev = root / "silver" / "flood_events" / "part-00000.parquet"
    ev.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(events), ev)
    return root


# ---- the runnable check the ticket names: folds are deterministic ---------------------

def test_the_fold_assignment_is_deterministic_and_group_complete():
    keys = [f"2019-0{i%9+1}-1{i%9}" for i in range(200)]
    a, b = ff.folds(keys), ff.folds(keys)
    assert np.array_equal(a, b)                      # same call, same answer
    assert np.array_equal(a, ff.folds(list(reversed(keys)))[::-1])   # order-independent
    assert set(a.tolist()) == set(range(ff.K_FOLDS))  # every fold populated
    assert not np.array_equal(a, ff.folds(keys, salt="location_blocked"))
    # a GROUP never straddles a boundary: one key, one fold, whatever it is mixed with
    by_key = {}
    for k, f in zip(keys, a):
        by_key.setdefault(k, set()).add(int(f))
    assert all(len(v) == 1 for v in by_key.values())
    assert ff.fold_of("2019-09-01") == ff.fold_of("2019-09-01")


def test_the_gate_is_a_pure_function_of_the_published_tables():
    def summary(model_csi, b2, b3):
        return {"point": {"model": {ff.GATE_SPLIT: {"csi": model_csi}},
                          "B2_unit_climatology": {ff.GATE_SPLIT: {"csi": b2}},
                          "B3_density_only": {ff.GATE_SPLIT: {"csi": b3}}}}

    won = ff.gate(summary(0.20, 0.10, 0.05))
    assert won == ff.gate(summary(0.20, 0.10, 0.05))          # pure: same in, same out
    assert won["branch"] == "MODEL"
    assert won["shipped"]["point"] == "point:l2_logistic"
    # B2 ahead by any margin flips the shipped id — the branch the release checklist asserts
    lost = ff.gate(summary(0.20, 0.21, 0.05))
    assert lost["branch"] == "B2" and lost["shipped"]["point"] == "point:b2_climatology"
    assert ff.gate(summary(0.20, 0.10, 0.99))["shipped"]["point"] == "point:b2_climatology"
    # a tie is NOT a win: the model has to BEAT both, not match them — and the tie has to
    # reach the SHIPPED id, not just the beats_ flag beside it
    tie = ff.gate(summary(0.20, 0.20, 0.05))
    assert tie["roles"]["point"]["beats_b2"] is False
    assert tie["roles"]["point"]["model_wins"] is False
    assert tie["branch"] == "B2" and tie["shipped"]["point"] == "point:b2_climatology"


# ---- the arithmetic seams -------------------------------------------------------------

def test_the_fit_recovers_a_known_boundary_and_the_penalty_shrinks_it():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(4000, 3))
    truth = np.array([-1.0, 1.5, -0.8, 0.0])
    y = (rng.random(4000) < 1 / (1 + np.exp(-(truth[0] + X @ truth[1:])))).astype(float)
    b = ff.fit_l2(X, y, 1e-6)
    assert np.allclose(b, truth, atol=0.15)
    heavy = ff.fit_l2(X, y, 1e5)
    assert abs(heavy[1]) < abs(b[1]) and abs(heavy[2]) < abs(b[2])   # shrinkage, monotone
    assert ff.predict(X, b).min() >= 0.0 and ff.predict(X, b).max() <= 1.0


def test_unstandardize_is_the_same_model_on_the_raw_scale():
    rng = np.random.default_rng(11)
    X = rng.normal(size=(500, 4)) * [3.0, 0.1, 10.0, 1.0] + [7.0, -2.0, 100.0, 0.0]
    y = (rng.random(500) < 0.3).astype(float)
    mu, sd = ff.standardize(X)
    b = ff.fit_l2((X - mu) / sd, y, 1.0)
    assert np.allclose(ff.predict((X - mu) / sd, b),
                       ff.predict(X, ff.unstandardize(b, mu, sd)))


def test_skill_thresholds_and_pr_auc_are_arithmetic():
    assert ff.skill(3, 1, 6) == {"csi": 0.3, "pod": 0.3333333333333333, "far": 0.25,
                                 "tp": 3, "fp": 1, "fn": 6}
    assert ff.skill(0, 0, 0)["csi"] == 0.0
    y = np.array([1.0, 1, 0, 0, 0, 0])
    thr, rate, csi = ff.best_threshold(np.array([0.9, 0.8, 0.7, 0.2, 0.1, 0.05]), y)
    assert thr == 0.8 and csi == 1.0                       # the perfect cut, TP 2 FP 0 FN 0
    assert rate == pytest.approx(2 / 6)                    # ... at a 2-in-6 alert budget
    assert ff.pr_auc(np.array([0.9, 0.8, 0.7, 0.2, 0.1, 0.05]), y) == 1.0
    # TIES ARE GROUPED: a constant score cannot be cut in the model's favour
    flat = np.full(6, 0.5)
    thr, rate, csi = ff.best_threshold(flat, y)
    assert thr == 0.5 and rate == 1.0 and csi == pytest.approx(2 / 6)   # all, or nothing
    assert ff.pr_auc(flat, y) == pytest.approx(1 / 3)
    assert ff.best_threshold(flat, np.zeros(6)) == (math.inf, 0.0, 0.0)   # no positives


def test_a_keep_restricted_run_spends_its_budget_on_the_rows_it_was_fitted_on():
    """The bus-stop churn contrast fits on entrance rows only. Its in-fold budget is picked
    on entrance rows, so spending it across the bus rows the run was told not to fit
    under-delivers the declared rate and inflates the published delta."""
    scores = np.r_[np.linspace(0.9, 1.0, 10), np.zeros(90)]   # 10 "entrance", 90 "bus"
    pop = np.r_[np.ones(10, bool), np.zeros(90, bool)]
    fold = np.zeros(100, int)
    run = {"thr": np.full(ff.K_FOLDS, 0.5), "rate": np.full(ff.K_FOLDS, 0.2),
           "population": pop}
    got = ff.decide(scores, fold, run)
    assert got[pop].sum() == 2                    # 20% OF THE FITTED POPULATION, as declared
    assert ff.decide(scores, fold, {**run, "population": None})[pop].sum() == 10
    # ... which is the bug: the whole-vector cut spends the entrance budget on bus rows


def test_the_operating_point_transfers_as_a_rate_not_as_a_raw_threshold():
    """The rule that keeps the gate honest. A baseline whose held-out score is a per-fold
    CONSTANT sitting under the training cut alarms on nothing under threshold transfer and
    reads CSI 0.0 — a number about the score's scale, not about the baseline. Rate transfer
    spends the same alert budget on whatever the held-out distribution is."""
    scores = np.full(10, 0.004)          # a constant held-out score, under the cut
    fold = np.zeros(10, int)
    run = {"thr": np.full(ff.K_FOLDS, 0.02), "rate": np.full(ff.K_FOLDS, 0.3)}
    assert ff.decide(scores, fold, run, ff.OP_THRESHOLD).sum() == 0      # alarms nothing
    assert ff.decide(scores, fold, run, ff.OP_RATE).sum() == 10          # spends the budget
    varied = np.linspace(0.0, 1.0, 10)
    assert ff.decide(varied, fold, run, ff.OP_RATE).sum() == 3           # the top 30%
    assert ff.decide(varied, fold, {"thr": np.full(ff.K_FOLDS, 0.5),
                                    "rate": np.zeros(ff.K_FOLDS)}, ff.OP_RATE).sum() == 0


def test_the_bootstrap_is_seeded_clustered_and_brackets_the_point_estimate():
    rng = np.random.default_rng(5)
    y = (rng.random(600) < 0.2).astype(float)
    pred = np.where(rng.random(600) < 0.25, 1.0, 0.0)
    idx = np.repeat(np.arange(30), 20)
    a = ff.event_cluster_ci(pred, y, idx, 30)
    assert a == ff.event_cluster_ci(pred, y, idx, 30)       # seeded: reproducible
    point = ff.skill(float((pred * y).sum()), float((pred * (1 - y)).sum()),
                     float(((1 - pred) * y).sum()))
    lo, hi = a["csi"]
    assert lo <= point["csi"] <= hi and lo < hi
    # a row bootstrap would be tighter — the cluster is the event, and it costs width
    assert hi - lo > 0.01


def test_the_fanout_weight_downweights_one_report_that_lit_a_whole_cell():
    rows = ff.Rows(role="point", X=np.zeros((4, 1)), y=np.array([1.0, 1, 1, 0]),
                   names=("x",), event_id=np.array(["e", "e", "e", "e"], object),
                   unit=np.array(["a", "b", "c", "d"], object),
                   cell=np.array([1, 1, 1, 2]))
    w = ff.fanout_weights(rows)
    assert w.tolist() == [1 / 3, 1 / 3, 1 / 3, 1.0]       # three positives, one Cell, one vote


def test_the_complex_score_is_the_max_over_its_children():
    rows = ff.Rows(role="point", X=np.zeros((3, 1)), y=np.zeros(3), names=("x",),
                   event_id=np.array(["e1", "e1", "e1"], object),
                   unit=np.array(["a", "b", "c"], object), cell=np.array([1, 1, 1]),
                   complex_id=np.array(["7", "7", "9"], object),
                   extra={"kind": np.array(["entrance"] * 3, object)})
    run = {"oof": np.array([0.1, 0.9, 0.4]), "fold": np.zeros(3, int),
           "thr": np.full(ff.K_FOLDS, 0.5), "rate": np.full(ff.K_FOLDS, 1 / 3)}
    cx = {"complex_id": np.array(["7", "9"], object),
          "event_id": np.array(["e1", "e1"], object), "y": np.array([1.0, 0.0]),
          "cell": np.array([1, 1])}
    m = ff.complex_validation(rows, run, cx)
    assert m["tp"] == 1 and m["fp"] == 0 and m["fn"] == 0   # 0.9 alarms, 0.4 does not
    assert m["pairs_without_child_entrances"] == 0
    # a complex whose children are all missing is COUNTED, never silently scored
    cx2 = {k: np.append(v, ["404"] if k == "complex_id" else
                        (["e1"] if k == "event_id" else [0.0])) for k, v in cx.items()}
    assert ff.complex_validation(rows, run, cx2)["pairs_without_child_entrances"] == 1


# ---- end to end over the planted matrix ----------------------------------------------

def test_the_whole_battery_runs_and_republishes_identically(fit_root):
    a = ff.run(fit_root)
    b = ff.run(fit_root)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True,
                                                                    default=str)
    assert a["gate"] == ff.gate(a["summary"])              # the gate re-evaluates from JSON
    assert a["fits_version"] == ff.fits_version(a["matrix_version"])
    for role in ("point", "cell"):
        for model in ("model", *ff.BASELINES):
            for split in ff.SPLITS:
                m = a["summary"][role][model][split]
                assert 0.0 <= m["csi"] <= 1.0 and 0.0 <= m["pod"] <= 1.0
                assert m["ci"]["csi"][0] <= m["ci"]["csi"][1]
                assert m["rows"] == a["census"][role]["rows"]   # every row scored, once
    # the signal planted in the fixture is real, so the fit has to find it
    assert a["summary"]["point"]["model"][ff.PRIMARY_SPLIT]["csi"] > \
        a["summary"]["point"]["B0_base_rate"][ff.PRIMARY_SPLIT]["csi"]
    assert a["final"]["point"]["coef_raw"]["log1p_precip_max_mm_1h"] > 0
    assert a["final"]["point"]["coef_raw"]["elev_ft"] < 0     # higher ground floods less
    # 15 point / 13 cell configs + the frozen-lambda REFERENCE row each
    assert len(a["sweeps"]["point"]) == 16 and len(a["sweeps"]["cell"]) == 14
    for role in ("point", "cell"):                # the delta reference is row 0, delta 0
        assert a["sweeps"][role][0]["config"].startswith("REFERENCE:")
        assert a["sweeps"][role][0]["delta_csi"] == 0.0
    # the fan-out proxy is DEGENERATE at Cell grain and says so instead of republishing
    assert a["sweeps"]["cell"][-1]["csi"] is None
    assert "DEGENERATE" in a["sweeps"]["cell"][-1]["config"]
    assert a["gate"]["panel_strings"] == ff.PANEL_STRINGS[a["gate"]["branch"]]
    for split in ff.SPLITS:                       # the complex set is scored, never fitted
        assert a["complex_validation"][split]["rate_transfer"]["budget"] > 0
    assert a["era_replication"]["status"] == "NOT COMPUTED"
    assert a["coverage"]["events"] == 32


def test_b2_degenerates_to_the_base_rate_under_location_blocking(fit_root):
    """The property the honest-strings paragraph rests on: with folds blocked by Cell, a
    held-out Unit's whole history is inside the held-out fold, so B2 has nothing to
    memorise. Asserted, not asserted-in-prose."""
    rows, _, _ = ff.load(fit_root)
    blocked = ff.climatology(rows["point"], "location_blocked")
    grouped = ff.climatology(rows["point"], "event_grouped")
    assert blocked["held_out_rows_with_own_history"] == 0
    assert grouped["held_out_rows_with_own_history"] > 0
    assert len(set(np.round(blocked["oof"], 12).tolist())) <= ff.K_FOLDS


def test_the_report_is_a_rendering_of_the_json(fit_root):
    r = ff.run(fit_root)
    md = render(r)
    assert f"**{r['gate']['branch']}**" in md
    assert r["fits_version"][:12] in md and "0.26-0.45" in md      # the FIM band, stamped
    # the pairable symmetry: the two counts the asset READS, and the two it inherits from
    # flood 08's build and labels as inherited
    assert f"{r['matrix_gates']['positives_dropped_unpairable']:,}" in md
    assert "inherited, not as measured by this run" in md   # the ONE inherited count
    assert f"{r['matrix_gates']['positives_dropped_unpairable']:,} of" in md
    assert "NOT COMPUTED" in md and "0.86-0.92" in md              # the MRMS-era honesty
    assert "{50, 100, 200} m" in md                                # the deferral, named
    assert str(r["coverage"]["event_days"]) in md and "never 115" in md


def test_the_published_asset_still_matches_the_landed_matrix():
    """Drift canary: the committed build asset was measured against ONE matrix_version. If
    the matrix is rebuilt and moves, this fails and the assets are re-run — a published
    metric whose inputs have moved underneath it is the whole failure mode."""
    published = ff.REPO / "research" / "flood-09-fits.json"
    root = fm.data_root()
    part = root / "gold" / "flood_matrix"
    if not published.exists() or not part.exists():
        pytest.skip("no published asset or no matrix on this root")
    got = pq.read_metadata(sorted(part.glob("*.parquet"))[0]).metadata[b"matrix_version"]
    assert json.loads(published.read_text())["matrix_version"] == got.decode()
