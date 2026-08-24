"""Flood-build ticket 18: the 311-threshold and label-radius outer replication.

Three seams, none of them needing the real tables:

  staging   `stage()` builds an alternate root out of symlinks. It is tested on a SYNTHETIC
            root shaped like the real one plus a directory this file never names, because
            the bug that actually happened was an enumerate-what-you-need staging that
            missed `archive/subway_alerts` — the alternate spine then quietly lost an
            alert-triggered event and would have published a delta measuring the staging.
  receipts  `diff_manifest` and `stamps_differ` are what stand between this ticket and
            "the primary is fine, I checked". Both are pinned on the cases that matter: an
            identity that moves while every file hash holds, and an alternate that stamps
            like the primary.
  rendering pure functions over a fixture result dict; no fit, no data root.

The parameterization the sweep rides on (`flood_labels.attach_sql`,
`flood_labels.label_version`, `flood_spine.remeasure_311`) is pinned here too — above all
that the DEFAULTS still reproduce flood 05's frozen text, because a sweep that moved the
primary's own stamp would have failed the ticket's first MUST silently.
"""
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from raincheck import flood_labels as fl, flood_replication as fr, flood_spine as fs

# ---- a synthetic primary root -------------------------------------------------------
# `extra` is the point: a real input directory this test file does not name anywhere else.
TREE = ("ref/assets/part-00000.parquet", "snapshots/stormwater/x.zip",
        "archive/flood/311.json", "archive/subway_alerts/date=2026-08-20/p.parquet",
        "archive/extra_capture_nobody_named/p.parquet", "archive/precip/mrms/x.parquet",
        "archive/precip/aorc/2020-09.zarr/.zmetadata",
        "silver/asset_features/p.parquet", "silver/cell_stormwater/p.parquet",
        "silver/flood_obs/p.parquet", "silver/flood_events/part-00000.parquet",
        "silver/precip_hourly/src=aorc/month=2020-09/p.parquet",
        "silver/precip_cell_hourly/src=aorc/month=2020-09/p.parquet",
        "gold/flood_labels/part-00000.parquet", "gold/flood_matrix/part-00000.parquet",
        "gold/flood_exposure/part-00000.parquet",
        "live/x.json", "logs/x.log", "checks/check=gaps/p.parquet")


@pytest.fixture
def primary(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    for rel in TREE:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rel)
    return root


def _resolves(p: Path) -> bool:
    return p.is_symlink() and p.resolve().exists()


# ---- staging --------------------------------------------------------------------------

def test_staging_links_every_input_including_one_nothing_enumerates(primary: Path):
    """The regression. `archive/subway_alerts` is folded into `flood_obs.alert_rows`
    beside the Socrata snapshots, and an earlier staging that listed its inputs missed it:
    the alternate spine lost the 2026-08-20 alert trigger and still built, still fit, and
    would have published a delta that was measuring the staging. The walk is what fixes
    that, so the pin is a directory this file names nowhere else."""
    alt = primary.parent / "alt"
    fr.stage(primary, alt, link_events=False)
    for name in ("subway_alerts", "extra_capture_nobody_named", "flood"):
        assert _resolves(alt / "archive" / name), name
    assert _resolves(alt / "ref") and _resolves(alt / "snapshots")
    for t in ("asset_features", "cell_stormwater", "flood_obs"):
        assert _resolves(alt / "silver" / t)


def test_staging_links_precip_per_month_so_a_new_month_lands_in_the_alternate(primary: Path):
    """`precip_identity()` hashes the SET of built Cell-month partitions, so a month written
    under the primary would stop its `matrix_version` from ever reproducing while moving no
    artifact byte. Per-CHILD links are what keep the extension in the alternate root."""
    alt = primary.parent / "alt"
    fr.stage(primary, alt, link_events=False)
    for table in ("precip_hourly", "precip_cell_hourly"):
        part = alt / "silver" / table / "src=aorc"
        assert not part.is_symlink(), f"{table}/src=aorc must be a real dir, not a link"
        assert _resolves(part / "month=2020-09")
        (part / "month=2099-01").mkdir()          # what an extension does
        assert not (primary / "silver" / table / "src=aorc" / "month=2099-01").exists()
    aorc = alt / "archive" / "precip" / "aorc"
    assert not aorc.is_symlink() and _resolves(aorc / "2020-09.zarr")
    assert _resolves(alt / "archive" / "precip" / "mrms")   # sibling still linked whole


def test_staging_rebuilds_the_three_tables_and_never_the_primarys(primary: Path):
    alt = primary.parent / "alt"
    fr.stage(primary, alt, link_events=False)
    for parts in fr.REBUILT:
        assert not alt.joinpath(*parts).exists(), parts
    assert _resolves(alt / "gold" / "flood_exposure")   # a gold sibling is still linked


def test_a_radius_universe_shares_the_primary_spine(primary: Path):
    """The event list did not move, so re-deriving it would inject a difference the sweep
    is not measuring. The threshold universes must NOT get the link."""
    alt = primary.parent / "alt"
    fr.stage(primary, alt, link_events=True)
    assert _resolves(alt / "silver" / "flood_events")
    fr.stage(primary, alt, link_events=False)
    assert not (alt / "silver" / "flood_events").exists()


def test_staging_never_mirrors_the_alternate_roots_or_the_writable_trees(primary: Path):
    """`alt/` inside `alt/` is an obvious recursion; `live/`, `logs/`, `checks/` are
    writable trees no leg of 04-09 reads, and not linking a writable directory is safer
    than linking it — a later job that needs one fails loudly instead of writing here."""
    (primary / "alt" / "older" / "gold").mkdir(parents=True)
    alt = fr.universe_root(primary, "u1")
    fr.stage(primary, alt, link_events=False)
    assert not (alt / "alt").exists()
    for name in ("live", "logs", "checks"):
        assert not (alt / name).exists(), name


def test_staging_is_idempotent(primary: Path):
    alt = primary.parent / "alt"
    fr.stage(primary, alt, link_events=False)
    (alt / "silver" / "flood_events" / "x").mkdir(parents=True)   # a stale earlier run
    fr.stage(primary, alt, link_events=False)
    assert not (alt / "silver" / "flood_events").exists()


# ---- the parameterization the sweep rides on -------------------------------------------

def test_the_attachment_radius_reaches_the_join_and_the_default_is_flood_05s_text():
    """A sweep knob that does not reach the SQL is not a sweep. And the default has to be
    byte-identical to what flood 05 shipped, or the primary's own label_version moves."""
    assert "ST_DWithin(oe.geometry, a.geometry, 100.0, true)" in fl.attach_sql()
    for r in (50.0, 200.0):
        sql = fl.attach_sql(r)
        assert f"ST_DWithin(oe.geometry, a.geometry, {r}, true)" in sql
        assert "100.0, true" not in sql


def test_label_version_moves_with_the_radius_and_with_the_spine(tmp_path: Path,
                                                                monkeypatch):
    monkeypatch.setattr(fl.ref, "assets_version", lambda root: "frozen")
    base = fl.label_version(tmp_path, "spine-a")
    assert fl.label_version(tmp_path, "spine-a", radius_m=50.0) != base
    assert fl.label_version(tmp_path, "spine-a", radius_m=200.0) != base
    assert fl.label_version(tmp_path, "spine-b") != base
    assert fl.label_version(tmp_path, "spine-a") == base   # the default is stable


def test_the_thresholds_are_asked_for_as_quantiles_never_typed(monkeypatch):
    """`remeasure_311(q)` is the only way a universe gets a cut, so no count is chosen by
    hand — and a higher quantile can never return a lower count."""
    series = {date(2020, 1, 1) + timedelta(d): d + 1 for d in range(100)}
    monkeypatch.setattr(fs.fo, "rows_311", lambda root, asof: {"ds": []})
    monkeypatch.setattr(fs.fo, "daily_311", lambda rows: series)
    got = [fs.remeasure_311(Path("/x"), date(2026, 8, 23), q)["ds"]
           for q in (0.90, 0.95, 0.99, 0.995)]
    assert got == sorted(got) and len(set(got)) > 1
    assert fs.remeasure_311(Path("/x"), date(2026, 8, 23))["ds"] == got[2]  # default 0.99


def test_the_sweep_moves_both_knobs_in_both_directions():
    """A one-sided sweep is not a sensitivity story. Every universe must also differ from
    the primary in exactly one knob — two moving at once is not a sweep either."""
    for knob, field in (("311_threshold", "q"), ("label_radius", "radius_m")):
        vals = [getattr(u, field) for u in fr.SWEEP if u.knob == knob]
        base = fr.Q_PRIMARY if field == "q" else fl.RADIUS_M
        assert min(vals) < base < max(vals), (knob, vals)
    for u in fr.SWEEP:
        moved = [f for f, base in (("q", fr.Q_PRIMARY), ("radius_m", fl.RADIUS_M))
                 if getattr(u, f) != base]
        assert moved == [{"311_threshold": "q", "label_radius": "radius_m"}[u.knob]], u


# ---- the receipts ------------------------------------------------------------------------

def test_the_receipt_catches_an_identity_that_moves_while_every_file_hash_holds():
    """The failure this ticket is actually exposed to. Building an AORC month under the
    primary changes `precip_identity` — and therefore stops `matrix_version 8bc1e891...`
    from reproducing — without touching one byte of the frozen table. A receipt that only
    hashed artifacts would call that untouched."""
    before = {"files": {"gold/flood_matrix/p.parquet": "aaa"},
              "precip_identity": "p1", "matrix_version_recomputed": "m1"}
    after = {**before, "precip_identity": "p2", "matrix_version_recomputed": "m2"}
    assert fr.diff_manifest(before, before) == {}
    moved = fr.diff_manifest(before, after)
    assert moved["precip_identity"] == ["p1", "p2"]
    assert moved["matrix_version_recomputed"] == ["m1", "m2"]
    assert "files" not in moved


def test_the_receipt_catches_a_moved_or_vanished_artifact_byte():
    before = {"files": {"a": "1", "b": "2"}}
    assert fr.diff_manifest(before, {"files": {"a": "9", "b": "2"}})["files"] == ["a"]
    assert fr.diff_manifest(before, {"files": {"a": "1"}})["files"] == ["b"]
    assert fr.diff_manifest(before, {"files": {"a": "1", "b": "2", "c": "3"}})["files"] == ["c"]
    # and an identity that APPEARED: a receipt that only walks the keys it started with
    # cannot report one, which is the same blindness in the other direction
    assert fr.diff_manifest(before, {**before, "new_identity": "x"})["new_identity"] == [None, "x"]


def test_an_alternate_that_stamps_like_the_primary_fails_the_build():
    primary = {"matrix_version": "M", "fits_version": "F", "label_version": "L",
               "spine_version": "S"}
    ok = [{"uid": "u1", "matrix_version": "M2", "fits_version": "F2",
           "label_version": "L2", "spine_version": "S"}]   # radius: spine shared on purpose
    got = fr.stamps_differ(primary, ok)
    assert got["spine_version"] == {"primary": "S", "u1": "S"}
    assert got["matrix_version"]["u1"] == "M2"
    for key in ("matrix_version", "fits_version", "label_version"):
        with pytest.raises(RuntimeError, match="collide"):
            fr.stamps_differ(primary, [{**ok[0], key: primary[key]}])


def test_the_frozen_primary_is_asserted_not_typed(tmp_path: Path, monkeypatch):
    """Every delta is read against flood 09's published numbers. A refit that moved them
    must fail this build rather than silently re-basing the whole table."""
    published = json.loads(fr.PRIMARY_FITS.read_text())
    published["summary"]["point"]["model"][fr.GATE_SPLIT]["csi"] = 0.9
    tampered = tmp_path / "fits.json"
    tampered.write_text(json.dumps(published))
    monkeypatch.setattr(fr, "PRIMARY_FITS", tampered)
    with pytest.raises(RuntimeError, match="frozen primary moved"):
        fr.primary_row(tmp_path)


# ---- the delta table and the rendering ---------------------------------------------------

def _metrics(csi, alert_rate=0.004):
    return {"csi": csi, "alert_rate": alert_rate, "pod": 0.3, "far": 0.9, "pr_auc": 0.02,
            "ci": {"csi": [csi - 0.001, csi + 0.001]}}


def _universe(uid, knob, csi_p, csi_c, base=0.005, radius_m=100.0, q=0.99):
    return {"uid": uid, "knob": knob, "q": q, "radius_m": radius_m,
            "thresholds": {"76ig-c548": 97, "erm2-nwe9": 85}, "root": f"/x/{uid}",
            "events": {"total": 200, "pluvial_fit": 130, "by_class": {"pluvial": 140}},
            "positives": 24542, "matrix_rows": 1000000, "estimand": "flooded_reported",
            "spine_version": "s" * 40, "label_version": "l" * 40,
            "matrix_version": "m" * 40, "fits_version": "f" * 40,
            "precip": {"cell_months": 124, "built_now": {"pixel": [], "cell": []},
                       "precip_identity": "p" * 40},
            "summary": {"point": {"model": {s: _metrics(csi_p) for s in
                                            (fr.GATE_SPLIT, fr.PRIMARY_SPLIT)},
                                  "B0_base_rate": {s: _metrics(base) for s in
                                                   (fr.GATE_SPLIT, fr.PRIMARY_SPLIT)}},
                        "cell": {"model": {s: _metrics(csi_c) for s in
                                           (fr.GATE_SPLIT, fr.PRIMARY_SPLIT)},
                                 "B0_base_rate": {s: _metrics(base) for s in
                                                  (fr.GATE_SPLIT, fr.PRIMARY_SPLIT)}}},
            "census": {"point": {"rows": 783351, "positives": 4008, "base_rate": base,
                                 "events": 133, "units": 15430, "cells": 1007},
                       "cell": {"rows": 179683, "positives": 6554, "base_rate": base,
                                "events": 133, "units": 1351, "cells": 1351}},
            "gate": {"branch": "MODEL"},
            "complex_validation": {s: {**_metrics(0.006), "rows": 43089, "positives": 118}
                                   for s in (fr.GATE_SPLIT, fr.PRIMARY_SPLIT)},
            "coverage": {"events": 206, "pluvial_fit_era": 133}}


@pytest.fixture
def result():
    p = {**_universe(fr.PRIMARY, "-", 0.0310, 0.1591), "knob": "-"}
    rows = [_universe("q9950", "311_threshold", 0.0400, 0.1400, base=0.006, q=0.995),
            _universe("r200", "label_radius", 0.0250, 0.1700, base=0.009, radius_m=200.0)]
    for i, r in enumerate(rows):
        for key in ("matrix_version", "fits_version", "label_version"):
            r[key] = f"{i}" * 40
    rows[1]["spine_version"] = p["spine_version"]     # a radius universe shares the spine
    return {"primary": p, "universes": rows, "deltas": fr.deltas(p, rows),
            "stamps": fr.stamps_differ(p, rows),
            "primary_untouched": {"artifacts": 7, "moved": {},
                                  "identities": {"precip_identity": "p" * 40}}}


def test_the_lift_is_the_base_rate_matched_reading_and_can_reverse_the_raw_ranking():
    """The sweep's whole finding lives in this ratio. A universe with a HIGHER raw CSI can
    have LOWER skill once its own base rate is divided out — which is what the real 200 m
    run does — so a table that ranks on raw CSI ranks backwards."""
    wide = {"model": {fr.GATE_SPLIT: _metrics(0.0667)},
            "B0_base_rate": {fr.GATE_SPLIT: _metrics(0.0151)}}
    base = {"model": {fr.GATE_SPLIT: _metrics(0.0310)},
            "B0_base_rate": {fr.GATE_SPLIT: _metrics(0.0051)}}
    assert wide["model"][fr.GATE_SPLIT]["csi"] > base["model"][fr.GATE_SPLIT]["csi"]
    assert fr.lift(wide["model"], wide) < fr.lift(base["model"], base)
    assert fr.lift(base["model"], base) == pytest.approx(6.078, abs=1e-3)
    # a degenerate baseline must not become a divide-by-zero in the published table
    assert fr.lift(base["model"], {"B0_base_rate": {fr.GATE_SPLIT: _metrics(0.0)}}) is None


def test_the_deltas_are_signed_and_carry_the_base_rate_that_moved_under_them(result):
    """CSI is monotone in alert rate at these base rates and every knob moves the base rate
    by construction, so a delta table printing CSI alone invites exactly the reading flood
    09 had to correct in fold."""
    d = {x["uid"]: x for x in result["deltas"]}
    assert d["q9950"]["point"]["delta_csi"][fr.GATE_SPLIT] == pytest.approx(0.0090)
    assert d["r200"]["cell"]["delta_csi"][fr.GATE_SPLIT] == pytest.approx(0.0109)
    assert d["r200"]["point"]["delta_csi"][fr.GATE_SPLIT] == pytest.approx(-0.0060)
    assert d["r200"]["point"]["delta_base_rate"] == pytest.approx(0.004)
    for row in result["deltas"]:
        for role in ("point", "cell"):
            assert set(row[role]) >= {"csi", "delta_csi", "alert_rate", "base_rate",
                                      "delta_base_rate", "positives", "rows",
                                      "lift_over_base_rate", "delta_lift"}
            assert set(row[role]["csi"]) == {fr.GATE_SPLIT, fr.PRIMARY_SPLIT}


def test_the_asset_prints_both_splits_the_settings_and_the_receipt(result):
    md = fr.render(result)
    for split in (fr.GATE_SPLIT, fr.PRIMARY_SPLIT):
        assert split in md
    assert "radius 200 m" in md and "311 q0.995" in md
    assert "+0.0090" in md and "-0.0060" in md          # signed deltas, both directions
    assert "0.00600" in md                              # the base rate beside the CSI
    assert "monotone in alert rate" in md
    assert "**none**" in md                             # the untouched receipt
    assert "partition SET, not the pixel bytes" in md   # the recorded limit, restated
    assert "43,089" in md and "alert-only by construction" in md   # the complex grain
    assert "lift over B0" in md and "reverses" in md                # the sweep's finding
    assert "BYTE-IDENTICAL" in md                                   # the cell invariance
    for uid in ("q9950", "r200", fr.PRIMARY):
        assert uid in md


def test_the_rendering_is_pure(result):
    assert fr.render(result) == fr.render(json.loads(json.dumps(result)))


def test_the_setting_column_names_the_knob_not_the_universe_id():
    assert fr.setting({"knob": "label_radius", "radius_m": 50.0}) == "radius 50 m"
    assert fr.setting({"knob": "311_threshold", "q": 0.975,
                       "thresholds": {"76ig-c548": 59, "erm2-nwe9": 45}}) == "311 q0.975 = 59/45"


# ---- real-root drift canaries -------------------------------------------------------
# These need the built alternates and skip with a decodable reason off the main root (flood
# 10's precedent). They exist because the published asset makes two claims about the REAL
# tables — the cell-grain invariance and the distinct stamps — and a claim in a document
# with no runnable check behind it is exactly what this repo calls a stale artifact.

def _alt(uid: str):
    from raincheck.paths import data_root
    root = data_root()
    part = root / "alt" / uid / "gold" / "flood_matrix"
    if not part.exists() or not (root / "gold" / "flood_matrix").exists():
        pytest.skip(f"no built alt/{uid} or no primary matrix on this root")
    return root, part


def _fit_cell_digest(part: Path) -> tuple[int, str]:
    import hashlib

    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    t = pq.read_table(part)
    t = t.filter(pc.equal(t["role"], "fit_cell")).drop_columns(["matrix_version"])
    t = t.sort_by([("event_id", "ascending"), ("asset_id", "ascending")])
    h = hashlib.sha256()
    for b in t.to_batches():
        h.update(b.serialize().to_pybytes())
    return t.num_rows, h.hexdigest()


@pytest.mark.parametrize("uid", ["r050", "r200"])
def test_a_radius_universe_leaves_the_cell_rows_byte_identical(uid: str):
    """The asset publishes this invariance as evidence the rebuild was real. `flood_labels`'
    cell branch attaches on `a.cell = oe.cell` with no distance predicate, so the radius
    cannot reach a Cell label — and if it ever did, the sweep's cell column would silently
    become a different measurement than the one the asset describes."""
    root, part = _alt(uid)
    assert _fit_cell_digest(part) == _fit_cell_digest(root / "gold" / "flood_matrix")


@pytest.mark.parametrize("uid", ["r050", "r200"])
def test_a_radius_universe_still_moves_the_point_rows(uid: str):
    """The other half: an invariance is only evidence if the knob demonstrably did
    something. A radius universe whose POINT positives also matched would mean the rebuild
    never happened."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    root, part = _alt(uid)

    def positives(p):
        t = pq.read_table(p, columns=["role", "flooded"])
        return pc.sum(t.filter(pc.equal(t["role"], "fit_point"))["flooded"]).as_py()

    assert positives(part) != positives(root / "gold" / "flood_matrix")


def test_every_built_alternate_stamps_differently_from_the_primary():
    """The ticket's MUST, checked against the ARTIFACTS rather than against the entry that
    claims it."""
    from raincheck.paths import data_root
    root = data_root()
    alts = sorted(p for p in (root / "alt").glob("*/gold/flood_matrix")) \
        if (root / "alt").exists() else []
    if not alts or not (root / "gold" / "flood_matrix").exists():
        pytest.skip("no built alternates or no primary matrix on this root")
    primary = fr._stamp(root / "gold" / "flood_matrix", b"matrix_version")
    got = {p.parent.parent.name: fr._stamp(p, b"matrix_version") for p in alts}
    assert primary not in got.values(), f"an alternate stamps as the primary: {got}"
    assert len(set(got.values())) == len(got), f"two alternates share a stamp: {got}"
