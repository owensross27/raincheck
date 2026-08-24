"""Flood-build ticket 10: gold/flood_exposure and the coefficient artifact.

Seam 1 (DuckDB assertions over the written table) and seam 2 (pure functions on plain
mappings). The fixture root is ticket 08's — a real registry cut with planted features and
precip, so it already contains the two shapes this ticket has to price: a complex whose
entrances ALL fail grade_ok (the ring15_med fallback is the only thing standing between it
and an empty aggregate) and bus stops with no DEM at all (excluded from the matrix, so they
can never be scored off it).

The published parameters are a READ of `research/flood-09-fits.json` in every case — the
fixture tests patch only the matrix_version the fits were fitted against, so the
fitted-on-THIS-matrix drift check stays live in production instead of being disabled here.
"""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from raincheck import duck, flood_coastal as fc, flood_exposure as fe, flood_fits as ff
from raincheck.paths import data_root
from test_flood_matrix import matrix_root  # noqa: F401 — the fixture, reused whole
from test_flood_labels import label_root  # noqa: F401 — matrix_root's own dependency

PUBLISHED = ff.REPO / "research" / "flood-09-fits.json"


@pytest.fixture(scope="module")
def fits():
    return json.loads(PUBLISHED.read_text())


def _as_fitted_here(root: Path, fits: dict) -> dict:
    """The published parameters, re-pointed at the fixture's own matrix. ONLY the
    matrix_version moves: every coefficient, forcing and gate row stays exactly as flood 09
    published it, so these tests score the shipped model on fixture features."""
    local = deepcopy(fits)
    local["matrix_version"] = pq.read_metadata(
        sorted((root / "gold" / "flood_matrix").glob("*.parquet"))[0]
    ).metadata[b"matrix_version"].decode()
    return local


@pytest.fixture(scope="module")
def built(matrix_root, tmp_path_factory, fits):  # noqa: F811
    """The whole artifact pair, built on the fixture root.

    `matrix_root` also names the two shapes this ticket must price: the complex whose
    entrances ALL fail grade_ok, and the bus stops with no DEM at all.
    """
    root, fallback_cx, no_dem = matrix_root
    local = _as_fitted_here(root, fits)
    out = tmp_path_factory.mktemp("coeff") / "flood-10-coefficients.json"
    fe.build(root, expect=None, fits=local, out=out)
    return root, out, local, fallback_cx, set(no_dem)


@pytest.fixture(scope="module")
def con():
    return duck.connect()


@pytest.fixture(scope="module")
def exposure(con, built):
    return duck.table(con, built[0] / "gold" / "flood_exposure")


def one(rel, sql):
    return rel.query("t", sql).fetchall()


# ---- seam 2: the pure rules ----------------------------------------------------------

MODEL = {"model_id": "toy", "intercept_raw": -1.0, "coef_raw": {"a": 2.0, "b": -0.5}}


def test_eta_is_a_plain_dot_product_not_a_probability():
    """The published score is the LINEAR PREDICTOR. A sigmoid here would put a probability
    in a table whose spec says probabilities live in the validation tables only."""
    assert fe.eta(MODEL, {"a": 3.0, "b": 4.0}) == pytest.approx(-1.0 + 6.0 - 2.0)
    assert fe.eta(MODEL, {"a": 0.0, "b": 0.0}) == -1.0          # never squashed into (0, 1)


def test_eta_refuses_a_missing_feature_instead_of_scoring_it_as_zero():
    """A silently absent term is a DIFFERENT model, and it would read as a plausible score
    rather than an error — the failure mode the detector cannot afford."""
    with pytest.raises(KeyError, match="'b'"):
        fe.eta(MODEL, {"a": 1.0})


def test_extra_features_are_ignored_so_a_live_caller_may_pass_a_wider_vector():
    assert fe.eta(MODEL, {"a": 1.0, "b": 0.0, "unused": 99.0}) == 1.0


def test_the_stormwater_base_level_gets_no_term():
    """Dummy coding against a base: `analyzed-none` differs by the intercept alone. A build
    that gave it a column would be fitting a rank-deficient design."""
    assert fe.dummies("bus_stop", ff.STORMWATER_BASE) == {
        "sw_deep": 0.0, "sw_nuisance": 0.0, "sw_not_analyzed": 0.0, "is_bus_stop": 1.0}
    assert fe.dummies("entrance", "deep")["sw_deep"] == 1.0
    assert fe.dummies("entrance", "deep")["is_bus_stop"] == 0.0
    assert fe.dummies("bus_stop", "not-analyzed")["sw_not_analyzed"] == 1.0


def test_an_unknown_stormwater_category_raises_because_it_is_never_imputed():
    with pytest.raises(ValueError, match="never imputed"):
        fe.dummies("bus_stop", "unknown")


def test_forcing_reads_log1p_space_and_expm1_is_the_only_way_to_mm(fits):
    """The matrix stores precip ALREADY log1p'd. The fits publish both scales; quoting mm
    means expm1 of the log1p value, and log1p'ing a second time is the silent bug."""
    for role in ("point", "cell"):
        m = fits["final"][role]
        for level in fe.REF_LEVELS.values():
            got = fe.forcing(m, level)
            assert set(got) == set(ff.PRECIP)
            for term, v in got.items():
                assert v == m["precip_percentiles_log1p"][term][level]
                assert np.expm1(v) == pytest.approx(
                    m["precip_percentiles_mm"][term][level], abs=1e-9)


def test_score_severe_forcings_are_at_or_above_score_ref_forcings(fits):
    for role in ("point", "cell"):
        p50, p90 = (fe.forcing(fits["final"][role], lv) for lv in ("p50", "p90"))
        assert all(p90[t] >= p50[t] for t in ff.PRECIP)


def test_cume_dist_ties_share_one_index_and_the_maximum_is_one():
    assert fe.cume_dist([1.0, 2.0, 2.0, 4.0]) == [0.25, 0.75, 0.75, 1.0]
    assert fe.cume_dist([5.0]) == [1.0]
    assert min(fe.cume_dist([3.0, 1.0, 2.0])) > 0.0


def test_the_cdf_knots_span_the_whole_kind():
    k = fe.cdf_knots([float(i) for i in range(101)])
    assert k["n"] == 101 and len(k["score_ref"]) == len(k["percentile"]) == 101
    assert k["percentile"][0] == 0.0 and k["percentile"][-1] == 100.0
    assert k["score_ref"][0] == 0.0 and k["score_ref"][-1] == 100.0
    assert k["score_ref"] == sorted(k["score_ref"])


# ---- seam 2: the gate is re-evaluated, never re-typed ---------------------------------

def test_the_shipped_ids_are_re_evaluated_from_the_published_summary(fits):
    assert fe.shipped(fits)["shipped"] == fits["gate"]["shipped"] == {
        "point": "point:l2_logistic", "cell": "cell:l2_logistic"}
    assert fe.shipped(fits)["branch"] == "MODEL"


def test_a_stored_verdict_that_disagrees_with_its_own_tables_is_refused(fits):
    """The whole point of `flood_fits.gate()` being pure: a JSON whose stored gate no longer
    follows from its summary is corrupted, and scoring on it would ship the wrong model."""
    bad = deepcopy(fits)
    bad["summary"]["point"]["B2_unit_climatology"]["location_blocked"]["csi"] = 1.0
    with pytest.raises(RuntimeError, match="disagrees with a re-evaluation"):
        fe.shipped(bad)


def test_the_b2_branch_is_refused_loudly_rather_than_guessed(fits):
    """A real branch of the gate that did not fire. `final.<role>` holds the FITTED model
    only, so a B2 ship would need per-Unit climatology this artifact cannot invent."""
    bad = deepcopy(fits)
    bad["summary"]["point"]["B2_unit_climatology"]["location_blocked"]["csi"] = 1.0
    bad["gate"] = ff.gate(bad["summary"])          # a self-consistent asset, as run() writes
    gate = fe.shipped(bad)
    assert gate["branch"] == "SPLIT"
    assert gate["shipped"] == {"point": "point:b2_climatology", "cell": "cell:l2_logistic"}
    with pytest.raises(NotImplementedError, match="climatology"):
        fe.models_of(bad, gate)


# ---- seam 2: the assertion that is scoped, and why ------------------------------------

def test_the_non_negative_assertion_covers_the_in_window_terms_only(fits):
    """THE scope that matters. The detector's monotone latch is a claim about terms that can
    only RISE inside a Window; the antecedent is frozen at Window open and never moves within
    one. Asserting all three precip terms would fail this build on a coefficient the latch
    does not use."""
    assert fe.IN_WINDOW == ("log1p_precip_max_mm_1h", "log1p_precip_total_mm")
    assert "log1p_antecedent_mm_24h" not in fe.IN_WINDOW

    gate = fe.shipped(fits)
    negative_antecedent = deepcopy(fits)
    negative_antecedent["final"]["point"]["coef_raw"]["log1p_antecedent_mm_24h"] = -9.0
    fe.models_of(negative_antecedent, gate)              # builds: not an event-side term

    for term in fe.IN_WINDOW:
        bad = deepcopy(fits)
        bad["final"]["point"]["coef_raw"][term] = -1e-9
        with pytest.raises(RuntimeError, match="monotone latch"):
            fe.models_of(bad, gate)


def test_the_published_point_fit_really_does_carry_a_negative_antecedent(fits):
    """The measurement the scope rests on (flood 09: -0.093 at point grain). If a refit ever
    turns it positive, the scoping COMMENT is stale — which is a doc fix, not a silent one."""
    assert fits["final"]["point"]["coef_raw"]["log1p_antecedent_mm_24h"] < 0
    assert all(fits["final"][r]["coef_raw"][t] > 0 for r in ("point", "cell")
               for t in fe.IN_WINDOW)


def test_a_double_log1p_in_the_published_forcings_is_caught(fits):
    bad = deepcopy(fits)
    bad["final"]["cell"]["precip_percentiles_mm"]["log1p_precip_total_mm"]["p50"] = 999.0
    with pytest.raises(RuntimeError, match="transformed twice"):
        fe.models_of(bad, fe.shipped(bad))


# ---- seam 2: the version stamp is structural, not clerical ----------------------------

def _stamp(fits, **over):
    gate = fe.shipped(fits)
    models = fe.models_of(fits, gate)
    refs = {r: {n: fe.forcing(models[r], lv) for n, lv in fe.REF_LEVELS.items()}
            for r in models}
    ids = {"label_version": "L", "features_version": "F", "precip_identity": "P",
           "matrix_version": "M", "fits_version": "V", **over}
    return fe.score_version(ids, models, refs)


def test_score_version_moves_when_any_upstream_identity_moves(fits):
    base = _stamp(fits)
    for key in ("label_version", "features_version", "precip_identity", "matrix_version",
                "fits_version"):
        assert _stamp(fits, **{key: "moved"}) != base, key


def test_score_version_moves_when_a_coefficient_or_a_forcing_moves(fits):
    base = _stamp(fits)
    bumped = deepcopy(fits)
    bumped["final"]["cell"]["coef_raw"]["share_deep"] += 1e-12
    assert _stamp(bumped) != base
    moved = deepcopy(fits)
    moved["final"]["point"]["precip_percentiles_log1p"]["log1p_precip_max_mm_1h"]["p90"] += 1e-9
    moved["final"]["point"]["precip_percentiles_mm"]["log1p_precip_max_mm_1h"]["p90"] = float(
        np.expm1(moved["final"]["point"]["precip_percentiles_log1p"]
                 ["log1p_precip_max_mm_1h"]["p90"]))
    assert _stamp(moved) != base


def test_score_version_is_stable_across_processes(fits):
    assert _stamp(fits) == _stamp(deepcopy(fits))


def test_score_version_covers_what_moves_a_score_and_nothing_else():
    """A stamp that moved on a reworded flag would refuse the live model tier over a
    cosmetic edit; a stamp that missed a coefficient would let a changed score pass as
    unchanged. Both directions are asserted."""
    ids = {"label_version": "L", "features_version": "F", "precip_identity": "P",
           "matrix_version": "M", "fits_version": "V"}
    models = {"point": {"model_id": "point:l2_logistic", "features": ["a"],
                        "coef_raw": {"a": 1.0}, "intercept_raw": 0.0,
                        "stormwater_base_level": "analyzed-none"}}
    refs = {"point": {"score_ref": {"a": 1.0}, "score_severe": {"a": 2.0}}}
    base = fe.score_version(ids, models, refs)
    moved = deepcopy(models)
    moved["point"]["coef_raw"]["a"] = 1.000001
    assert fe.score_version(ids, moved, refs) != base
    shifted = deepcopy(refs)
    shifted["point"]["score_severe"]["a"] = 2.5
    assert fe.score_version(ids, models, shifted) != base


def test_a_reworded_flag_does_not_move_score_version(monkeypatch):
    """The other direction: the flag vocabulary is documentation, not a score input, and
    the live model tier must not refuse itself over an edited sentence."""
    ids = {"label_version": "L", "features_version": "F", "precip_identity": "P",
           "matrix_version": "M", "fits_version": "V"}
    models = {"point": {"model_id": "point:l2_logistic", "features": ["a"],
                        "coef_raw": {"a": 1.0}, "intercept_raw": 0.0,
                        "stormwater_base_level": "analyzed-none"}}
    refs = {"point": {"score_ref": {"a": 1.0}}}
    base = fe.score_version(ids, models, refs)
    monkeypatch.setitem(fe.FLAGS, "no_surge_margin", "reworded entirely")
    monkeypatch.setitem(fe.FLAGS, "a_brand_new_flag", "added later")
    assert fe.score_version(ids, models, refs) == base


# ---- seam 1: the written table --------------------------------------------------------

def test_one_row_per_unit_and_the_registry_decides_which(built, exposure):
    root = built[0]
    reg = {a["asset_id"] for a in pq.read_table(
        root / "ref" / "assets", columns=["asset_id", "kind", "scored"]).to_pylist()
        if a["scored"] and a["kind"] in fe.KIND_MODEL}
    got = {r[0] for r in one(exposure, "SELECT asset_id FROM t")}
    assert got == reg
    assert one(exposure, "SELECT count(*), count(DISTINCT asset_id) FROM t")[0] == (
        len(reg), len(reg))
    assert one(exposure, "SELECT count(*) FROM t WHERE kind NOT IN "
                         "('bus_stop', 'complex', 'cell')") == [(0,)]


def test_no_null_scores_anywhere(built, exposure):
    """The contract, and it is paid for upstream: elev_source() applied the ring15_med
    fallback per row, so the all-flagged complex still aggregates over a real set."""
    assert one(exposure, "SELECT count(*) FROM t WHERE score_ref IS NULL "
                         "OR score_severe IS NULL OR score_index IS NULL") == [(0,)]
    assert one(exposure, "SELECT count(*) FROM t WHERE NOT isfinite(score_ref) "
                         "OR NOT isfinite(score_severe)") == [(0,)]
    assert one(exposure, "SELECT count(*) FROM t WHERE flags IS NULL") == [(0,)]


def test_score_index_is_the_within_kind_cdf_of_score_ref(built, exposure):
    assert one(exposure, "SELECT count(*) FROM t WHERE score_index <= 0 "
                         "OR score_index > 1") == [(0,)]
    n, agree = one(exposure, """
        SELECT count(*), sum(abs(score_index - cd) < 1e-12)::INT FROM (
          SELECT score_index, cume_dist() OVER (PARTITION BY kind ORDER BY score_ref) cd
            FROM t)""")[0]
    assert agree == n
    assert one(exposure, "SELECT count(*) FROM (SELECT kind, max(score_index) mx "
                         "FROM t GROUP BY kind) WHERE mx <> 1.0") == [(0,)]


def test_severe_is_never_below_ref_because_both_in_window_terms_are_non_negative(
        built, exposure):
    assert one(exposure, "SELECT count(*) FROM t WHERE score_severe < score_ref") == [(0,)]


def test_a_complex_score_is_the_max_over_its_child_entrance_scores(built, con, exposure):
    """Recomputed from the matrix rather than re-read: the rule that DEFINES the complex
    number. It carries no skill claim — see the artifact test below."""
    root, _, fits, _, _ = built
    m = fits["final"]["point"]
    ref = fe.forcing(m, "p50")
    rows = duck.table(con, root / "gold" / "flood_matrix").query("t", """
        SELECT complex_id, asset_id, kind, min(elev_ft) e, min(relief_ft) r,
               min(stormwater_cat) c
          FROM t WHERE role = 'fit_point' AND kind = 'entrance'
         GROUP BY complex_id, asset_id, kind""").fetchall()
    want: dict[str, float] = {}
    for cx, _aid, kind, e, r, c in rows:
        s = fe.eta(m, {"elev_ft": e, "relief_ft": r, **fe.dummies(kind, c), **ref})
        want[cx] = max(want.get(cx, s), s)
    got = dict(one(exposure, "SELECT asset_id, score_ref FROM t WHERE kind = 'complex' "
                             "AND NOT list_contains(flags, 'no_matrix_row')"))
    assert len(want) == len(got) > 0
    for cx, s in want.items():
        assert got[f"stn:{cx}"] == pytest.approx(s, abs=1e-12)
    # a complex with no doorway in the matrix cannot be a max over doorways: it falls back
    # and says so, rather than publishing a number nothing stands behind
    assert {r[0] for r in one(exposure, "SELECT asset_id FROM t WHERE kind = 'complex' "
                              "AND list_contains(flags, 'no_matrix_row')")} == {
        r[0] for r in one(exposure, "SELECT asset_id FROM t WHERE kind = 'complex'")} - set(got)


def test_an_entrance_or_a_station_never_publishes_a_row(built, exposure):
    """Carriers locate and aggregate; they are never scored independently."""
    root = built[0]
    carriers = {a["asset_id"] for a in pq.read_table(
        root / "ref" / "assets", columns=["asset_id", "kind"]).to_pylist()
        if a["kind"] in ("entrance", "station")}
    got = {r[0] for r in one(exposure, "SELECT asset_id FROM t")}
    assert carriers and not (carriers & got)


def test_the_out_of_dem_stops_get_a_flag_and_a_named_fallback_never_an_elevation(
        built, con, exposure):
    """They are NOT IN THE MATRIX (flood 08 excluded them with a count), so they cannot be
    scored off it. They are still Units: a row, a published reason, and the kind's median —
    which is the one thing that is not an imputed elevation."""
    root, _, _, _, no_dem = built
    scored = {r[0] for r in duck.table(con, root / "gold" / "flood_matrix").query(
        "t", "SELECT DISTINCT asset_id FROM t WHERE role = 'fit_point'").fetchall()}
    assert no_dem and not (no_dem & scored)

    assert {r[0] for r in one(exposure, "SELECT asset_id FROM t WHERE "
                              "list_contains(flags, 'no_dem_footprint')")} == no_dem
    assert {r[0] for r in one(
        exposure, "SELECT asset_id FROM t WHERE kind = 'bus_stop' AND "
                  "list_contains(flags, 'score_fallback_kind_median')")} == no_dem
    # every fallback row carries the SAME number — the kind median, not a per-Unit guess,
    # which is what makes it a declared fallback rather than an invented elevation
    assert one(exposure, "SELECT count(DISTINCT score_ref), count(DISTINCT score_severe) "
                         "FROM t WHERE list_contains(flags, 'no_dem_footprint')") == [(1, 1)]
    (want,) = one(exposure, "SELECT median(score_ref) FROM t WHERE kind = 'bus_stop' "
                            "AND NOT list_contains(flags, 'no_dem_footprint')")[0]
    (got,) = one(exposure, "SELECT DISTINCT score_ref FROM t WHERE "
                           "list_contains(flags, 'no_dem_footprint')")[0]
    assert got == pytest.approx(want, abs=1e-12)
    # and they never claim a ring15 median they do not have
    assert one(exposure, "SELECT count(*) FROM t WHERE "
                         "list_contains(flags, 'no_dem_footprint') AND "
                         "list_contains(flags, 'elev_ring15_fallback')") == [(0,)]


def test_the_complex_with_no_graded_entrance_is_flagged_not_dropped(built, exposure):
    """The ring15_med fallback fires PER ROW at the feature layer, so this complex still
    aggregates over a real set instead of over nothing — and the row says why."""
    _, _, _, fallback_cx, _ = built
    got = {r[0] for r in one(exposure, "SELECT asset_id FROM t WHERE kind = 'complex' "
                                       "AND list_contains(flags, 'elev_ring15_fallback')")}
    assert got == {f"stn:{fallback_cx}"}
    assert one(exposure, f"SELECT count(*) FROM t WHERE asset_id = 'stn:{fallback_cx}' "
                         f"AND score_ref IS NOT NULL") == [(1,)]


def test_flags_never_leave_the_published_vocabulary(built, exposure):
    got = {r[0] for r in one(exposure, "SELECT DISTINCT unnest(flags) FROM t")}
    assert got and got <= set(fe.FLAGS)
    assert one(exposure, "SELECT count(*) FROM t WHERE len(flags) = 0")[0][0] > 0


def test_surge_margin_comes_from_flood_coastal_unchanged(built, exposure):
    """Never recomputed here, and a NULL margin is published as NULL with a flag — 404 Units
    on the real root have no point elevation behind them, and they are not zeros."""
    want = {m["asset_id"]: m["surge_margin_ft"] for m in fc.unit_margins(built[0])}
    got = dict(one(exposure, "SELECT asset_id, surge_margin_ft FROM t"))
    assert got == want
    nulls = {a for a, v in want.items() if v is None}
    flagged = {r[0] for r in one(
        exposure, "SELECT asset_id FROM t WHERE list_contains(flags, 'no_surge_margin')")}
    assert flagged == nulls


def test_every_row_carries_the_same_chained_version_stamps(built, exposure):
    assert one(exposure, "SELECT count(DISTINCT score_version), "
                         "count(DISTINCT matrix_version), count(DISTINCT fits_version) "
                         "FROM t") == [(1, 1, 1)]
    root, out, fits, _, _ = built
    meta = pq.read_metadata(
        sorted((root / "gold" / "flood_exposure").glob("*.parquet"))[0]).metadata
    ids = json.loads(meta[b"identities"].decode())
    assert ids["matrix_version"] == fits["matrix_version"]
    assert ids["fits_version"] == fits["fits_version"]
    assert json.loads(out.read_text())["score_version"] == \
        one(exposure, "SELECT DISTINCT score_version FROM t")[0][0]
    assert meta[b"estimand"].decode() == "flooded_reported"


def test_the_table_is_a_single_sorted_part(built, exposure):
    parts = sorted((built[0] / "gold" / "flood_exposure").glob("*.parquet"))
    assert [p.name for p in parts] == ["part-00000.parquet"]
    rows = one(exposure, "SELECT kind, asset_id FROM t")
    assert rows == sorted(rows)


def test_rebuild_is_byte_identical(built):
    """No wall-clock stamp, one fixed part name, a deterministic sort — the same inputs must
    produce the same bytes or nothing downstream can tell a rebuild from a change."""
    root, out, fits, _, _ = built
    part = root / "gold" / "flood_exposure" / "part-00000.parquet"
    before = (hashlib.sha256(part.read_bytes()).hexdigest(),
              hashlib.sha256(out.read_bytes()).hexdigest())
    fe.build(root, expect=None, fits=fits, out=out)
    assert (hashlib.sha256(part.read_bytes()).hexdigest(),
            hashlib.sha256(out.read_bytes()).hexdigest()) == before


# ---- seam 1: the coefficient artifact --------------------------------------------------

def test_the_artifact_is_the_detector_loader_and_carries_the_shipped_parameters(built):
    _, out, fits, _, _ = built
    art = fe.coefficients(out)
    assert art["estimand"] == "flooded_reported"
    assert art["gate"]["shipped"] == fits["gate"]["shipped"]
    assert art["gate"]["panel_strings"] == fits["gate"]["panel_strings"]
    for role in ("point", "cell"):
        assert art["models"][role]["coef_raw"] == fits["final"][role]["coef_raw"]
        assert art["models"][role]["intercept_raw"] == fits["final"][role]["intercept_raw"]
        assert art["models"][role]["stormwater_base_level"] == ff.STORMWATER_BASE
    assert art["kind_model"] == fe.KIND_MODEL
    assert art["scale_band"]["pass2_over_aorc"] == list(ff.SCALE_BAND) == [0.86, 0.92]
    assert set(art["flags"]) == set(fe.FLAGS)


def test_the_artifact_alone_reproduces_a_published_score(built, con, exposure):
    """THE loader contract for ticket 11: the JSON plus the Unit's own features is enough to
    reproduce a published score — no fits file, no matrix metadata, no constant from this
    module. Replayed here on Cells, whose features all live in one matrix row."""
    root, out, _, _, _ = built
    art = fe.coefficients(out)
    model = art["models"]["cell"]
    ref = art["reference_forcings"]["cell"]["score_ref"]["log1p"]
    feats = duck.table(con, root / "gold" / "flood_matrix").query("t", """
        SELECT asset_id, min(share_deep) sd, min(share_nuisance) sn,
               min(share_not_analyzed) sa, arg_max(density_311_3y, event_id)::DOUBLE d
          FROM t WHERE role = 'fit_cell' GROUP BY asset_id ORDER BY asset_id""").fetchall()
    published = dict(one(exposure, "SELECT asset_id, score_ref FROM t WHERE kind = 'cell'"))
    assert len(feats) == len(published) > 0
    for aid, sd, sn, sa, d in feats:
        replayed = model["intercept_raw"] + sum(model["coef_raw"][k] * v for k, v in {
            "share_deep": sd, "share_nuisance": sn, "share_not_analyzed": sa,
            "density_311_3y": d, **ref}.items())
        assert published[aid] == pytest.approx(replayed, abs=1e-12), aid


def test_the_artifact_publishes_per_kind_cdfs_that_match_the_table(built, exposure):
    _, out, _, _, _ = built
    art = fe.coefficients(out)
    for kind, knots in art["cdf"]["by_kind"].items():
        n, lo, hi = one(exposure, f"SELECT count(*), min(score_ref), max(score_ref) "
                                  f"FROM t WHERE kind = '{kind}'")[0]
        assert knots["n"] == n
        assert knots["score_ref"][0] == pytest.approx(lo)
        assert knots["score_ref"][-1] == pytest.approx(hi)
        assert knots["score_ref"] == sorted(knots["score_ref"])


def test_the_artifact_makes_no_skill_claim_of_any_grain(built):
    """The complex score is an AGGREGATE OF DOORWAY SCORES. The independent complex-grain
    set caught 1 of 118 positives, so no artifact may carry a complex-grain performance
    number — and the cleanest guarantee is that this one carries no metric at all."""
    _, out, _, _, _ = built
    art = fe.coefficients(out)
    assert art["complex_rule"]["rule"] == "max over child entrance scores"
    assert "never measured complex-grain skill" in art["complex_rule"]["claim"]
    blob = json.dumps(art).lower()
    for metric in ('"csi"', '"pod"', '"far"', '"pr_auc"', '"tp"', '"fp"'):
        assert metric not in blob, f"the coefficient artifact must publish no {metric}"


def test_the_artifact_says_the_score_is_not_a_probability(built):
    _, out, _, _, _ = built
    art = fe.coefficients(out)
    assert art["score"]["is_probability"] is False
    assert "validation tables only" in art["score"]["note"]


# ---- the published pair, on whatever root this machine has -----------------------------

def test_the_committed_artifact_still_matches_the_landed_matrix():
    """Drift canary, the shape flood 09 uses: the committed coefficients were measured
    against ONE matrix_version and ONE fits_version. If either moves underneath them the
    pair is re-run — a published constant whose inputs have moved is the whole failure
    mode."""
    root = data_root()
    part = root / "gold" / "flood_matrix"
    if not fe.COEFFICIENTS.exists() or not part.exists():
        pytest.skip("no committed coefficient artifact or no matrix on this root")
    art = fe.coefficients()
    stamped = pq.read_metadata(
        sorted(part.glob("*.parquet"))[0]).metadata[b"matrix_version"].decode()
    assert art["identities"]["matrix_version"] == stamped
    assert art["identities"]["fits_version"] == json.loads(PUBLISHED.read_text())["fits_version"]


def test_the_seven_zero_grade_ok_complexes_are_frozen_by_id_not_by_name():
    """KNOWN TRAP: complex NAMES are not unique — "86 St" alone names five complexes, so a
    name-keyed gate reports 18 and asserts nothing. The frozen set is keyed on complex_id;
    the name rides beside it only as the drift canary. Asserted over the SHIPPED table."""
    root = data_root()
    part = root / "gold" / "flood_exposure"
    if not part.exists() or not (root / "ref" / "assets").exists():
        pytest.skip("no built gold/flood_exposure on this root")
    con = duck.connect()
    flagged = {r[0] for r in duck.table(con, part).query(
        "t", "SELECT asset_id FROM t WHERE kind = 'complex' AND "
             "list_contains(flags, 'elev_ring15_fallback')").fetchall()}
    con.close()
    assert flagged == {f"stn:{c}" for c in fe.NO_GRADE_OK}

    by_name = [a["asset_id"] for a in fe._registry(root)
               if a["kind"] == "complex" and a["name"] in set(fe.NO_GRADE_OK.values())]
    assert len(by_name) > len(fe.NO_GRADE_OK), (
        "a name-keyed set must be strictly LARGER here, or this trap has stopped being real")


def test_the_frozen_gates_actually_fire(built, tmp_path):
    """A gate that never fires is decoration. Both halves are exercised on the fixture's own
    census: the Unit counts, and the complex_id set with no graded entrance."""
    root, _, local, fallback_cx, _ = built
    cen = json.loads(pq.read_metadata(
        sorted((root / "gold" / "flood_exposure").glob("*.parquet"))[0]
    ).metadata[b"census"].decode())
    named = {a["complex_id"]: a["name"] for a in fe._registry(root) if a["kind"] == "complex"}
    ok = {"units": cen["units"], **cen["by_kind"],
          "out_of_footprint": cen["by_flag"]["no_dem_footprint"],
          "no_matrix_row": cen["by_flag"]["no_matrix_row"],
          "no_grade_ok": {fallback_cx: named[fallback_cx]}}

    assert fe.build(root, expect=ok, fits=local, out=tmp_path / "ok.json") == cen["units"]
    with pytest.raises(RuntimeError, match="no graded entrance moved"):
        fe.build(root, expect={**ok, "no_grade_ok": {"999": "Nowhere"}}, fits=local,
                 out=tmp_path / "a.json")
    with pytest.raises(RuntimeError, match="no graded entrance moved"):
        fe.build(root, expect={**ok, "no_grade_ok": {fallback_cx: "Renamed"}}, fits=local,
                 out=tmp_path / "b.json")                       # the NAME is the canary
    with pytest.raises(RuntimeError, match="census moved"):
        fe.build(root, expect={**ok, "units": cen["units"] + 1}, fits=local,
                 out=tmp_path / "c.json")
    with pytest.raises(RuntimeError, match="out-of-DEM stops"):
        fe.build(root, expect={**ok, "out_of_footprint": 999}, fits=local,
                 out=tmp_path / "d.json")


def test_fits_measured_on_a_different_matrix_are_refused(  # noqa: F811
        matrix_root, tmp_path, fits):
    """The published fits carry the REAL matrix_version; the fixture matrix is a different
    table. Scoring one model's coefficients against another table's features is exactly the
    drift this refuses."""
    with pytest.raises(RuntimeError, match="was fitted on matrix"):
        fe.build(matrix_root[0], expect=None, fits=fits, out=tmp_path / "c.json")
