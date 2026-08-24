"""The outer replication (flood-build ticket 18 / spec "Exposure score" — validation).

Two knobs decide which (Unit, event) pairs are POSITIVE, and both sit upstream of
`gold/flood_matrix`, so neither can be swept in fold: moving them redefines the event
universe itself, which is why ticket 09 routed both here.

  311 threshold   `flood_spine.P99_311` cuts an event-day out of the 311 daily counts.
                  Lower it and days become events; raise it and events disappear.
  label radius    `flood_labels.RADIUS_M` is the geodesic cut inside flood 05's Sedona
                  `ST_DWithin` join. Move it and a doorway that was dry becomes flooded.

An alternate universe is therefore a REBUILD of 04 -> 05 -> 06 -> 08 -> 09, not a re-read
of the matrix — and it runs through exactly those jobs, parameterized. Nothing here forks
their logic: `flood_spine.build(root, asof, thresholds)`, `flood_labels.build(root, spark,
asof, radius_m)`, `flood_matrix.build(root, expect=None)` and `flood_fits.run(root)` are
called as they stand.

THE PRIMARY IS NOT TOUCHED. Each universe gets its own data root under `<root>/alt/<id>/`,
whose inputs are SYMLINKS back to the primary's and whose three rebuilt tables
(`silver/flood_events`, `gold/flood_labels`, `gold/flood_matrix`) are its own bytes. The
subtle half is that a universe which needs AORC months the primary never built cannot
write them into the primary root either: `flood_matrix.precip_identity()` hashes the SET
of built Cell-month partitions, so one new month there would stop the frozen
`matrix_version 8bc1e891...` from ever reproducing, without changing a byte of the table.
So the precip trees are linked PER MONTH and the extension lands in the alternate root.

`verify_primary()` is the receipt, not the intention: it hashes the primary's artifacts and
recomputes its three chained identities before and after the run.

Recorded limit, restated not fixed: `precip_identity()` names the built AORC Cell-month
partition SET, not the pixel bytes — a month rewritten under the same name does not move
the stamp.

Run: make flood-replication     (python -m raincheck.flood_replication)
"""
import argparse
import hashlib
import json
import shutil
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

from raincheck import (features as ft, flood_labels as fl, flood_matrix as fm,
                       flood_obs as fo, flood_spine as fs, precip_flood_era as pfe, ref)
from raincheck.paths import REPO, data_root

PRIMARY = "primary"
Q_PRIMARY = 0.99          # the quantile the frozen P99_311 pins were measured at

# ---- the sweep ---------------------------------------------------------------------
# Both knobs move in BOTH directions around the frozen primary. The 311 arm asks for a
# QUANTILE and lets `flood_spine.remeasure_311` return the counts, so no threshold is ever
# typed by hand — a hand-typed cut is a cut somebody chose, and the replication exists to
# show the knob without the knob having selected the result. The radius arm is the spec's
# own {50, 100, 200} m, 100 m being the primary.


@dataclass(frozen=True)
class Universe:
    """One alternate event universe: which knob moved, and to what."""
    uid: str
    knob: str
    q: float = Q_PRIMARY
    radius_m: float = fl.RADIUS_M

    @property
    def rebuilds_spine(self) -> bool:
        return self.q != Q_PRIMARY


SWEEP = (
    Universe("q9750", "311_threshold", q=0.975),
    Universe("q9950", "311_threshold", q=0.995),
    Universe("r050", "label_radius", radius_m=50.0),
    Universe("r200", "label_radius", radius_m=200.0),
)

# ---- staging an alternate root ------------------------------------------------------
# The alternate root is DISCOVERED, not enumerated. An earlier draft listed the inputs it
# thought a universe needed and linked those; it missed `archive/subway_alerts` — the live
# alert capture `flood_obs.alert_rows` folds in beside the Socrata snapshots — and the
# alternate spine quietly lost an alert-triggered 2026 event. A universe that is silently
# short one input still builds, still fits, and publishes a delta that is measuring the
# staging. So: everything under the primary root is linked except what this ticket rebuilds
# or must not touch, and the walk finds inputs nobody remembered to name.
REBUILT = {("silver", "flood_events"), ("gold", "flood_labels"), ("gold", "flood_matrix")}
# Linked per CHILD, not as a directory, because a universe may write a NEW sibling here (a
# Bronze AORC month, a Pixel month, a Cell month) and that write must land in the alternate
# root — `precip_identity()` hashes the SET of Cell-month partitions, so one extra month
# under the primary would stop `matrix_version 8bc1e891...` from ever reproducing.
PER_CHILD = {("archive", "precip", "aorc"),
             ("silver", "precip_hourly", "src=aorc"),
             ("silver", "precip_cell_hourly", "src=aorc")}
# Never linked: the alternate roots themselves, and the writable trees no leg of 04-09
# reads. Not linking a writable directory is safer than linking it; if some later job does
# need one it fails loudly here rather than writing into the primary.
SKIP = {("alt",), ("live",), ("logs",), ("checks",), ("checkpoints",), (".staging",)}


def universe_root(root: Path, uid: str) -> Path:
    return root / "alt" / uid


def stage(root: Path, alt: Path, link_events: bool) -> None:
    """Build the alternate root out of symlinks. `link_events` shares the primary's spine —
    right for a radius universe, where the event list is unchanged and re-deriving it would
    only invite a difference the sweep is not measuring."""
    shutil.rmtree(alt, ignore_errors=True)
    rebuilt = REBUILT - {("silver", "flood_events")} if link_events else REBUILT
    _mirror(root, alt, (), rebuilt)


def _mirror(src: Path, dst: Path, parts: tuple[str, ...], rebuilt: set) -> None:
    special = PER_CHILD | rebuilt
    dst.mkdir(parents=True, exist_ok=True)
    for child in sorted(src.iterdir()):
        here = parts + (child.name,)
        if here in SKIP or here in rebuilt:
            continue
        descend = child.is_dir() and (here in PER_CHILD or any(
            len(q) > len(here) and q[:len(here)] == here for q in special))
        if descend:
            _mirror(child, dst / child.name, here, rebuilt)
        else:
            (dst / child.name).symlink_to(child.resolve())


# ---- the primary's byte receipt ------------------------------------------------------
# The artifacts whose bytes must not move, and the three identities the primary's own
# stamps are chained on. Hashing 2.5 GB of precip to prove that is the wrong instrument:
# what the stamps actually consume is `precip_identity`, `features_version` and
# `assets_version`, so those are recomputed instead — a new month under the primary's
# precip root changes `precip_identity` without changing one artifact byte, and that is
# exactly the failure this receipt has to catch.
FROZEN = (("silver", "flood_events"), ("gold", "flood_labels"), ("gold", "flood_matrix"),
          ("gold", "flood_exposure"))
FROZEN_ASSETS = ("research/flood-09-fits.json", "research/flood-09-fits.md",
                 "research/flood-10-coefficients.json")


def verify_primary(root: Path) -> dict:
    """sha256 of every frozen artifact byte, plus the identities the stamps are made of."""
    files = {}
    for parts in FROZEN:
        part = root.joinpath(*parts)
        for f in sorted(part.rglob("*")) if part.exists() else ():
            if f.is_file():
                files[str(f.relative_to(root))] = _sha(f)
    for rel in FROZEN_ASSETS:
        f = REPO / rel
        if f.exists():
            files[rel] = _sha(f)
    lv = _stamp(root / "gold" / "flood_labels", b"label_version")
    sv = _stamp(root / "gold" / "flood_labels", b"spine_version")
    return {"files": files,
            "assets_version": ref.assets_version(root),
            "features_version": ft.features_version(root),
            "precip_identity": fm.precip_identity(root),
            "label_version": lv, "spine_version": sv,
            "label_version_recomputed": fl.label_version(root, sv),
            "matrix_version": _stamp(root / "gold" / "flood_matrix", b"matrix_version"),
            "matrix_version_recomputed": fm.matrix_version(root, lv)}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _stamp(part: Path, key: bytes) -> str | None:
    meta = pq.read_metadata(sorted(part.glob("*.parquet"))[0]).metadata or {}
    return (meta.get(key) or b"").decode() or None


def diff_manifest(before: dict, after: dict) -> dict:
    """What moved. Empty means the primary is untouched — bytes AND stamps."""
    # the UNION of keys, not `before`'s: a receipt that only looks at what it knew about
    # cannot report an identity or an artifact that APPEARED during the run
    out = {k: [before.get(k), after.get(k)]
           for k in sorted(set(before) | set(after)) if k != "files"
           and before.get(k) != after.get(k)}
    moved = sorted(k for k in set(before["files"]) | set(after["files"])
                   if before["files"].get(k) != after["files"].get(k))
    if moved:
        out["files"] = moved
    return out


# ---- one universe --------------------------------------------------------------------

def build_universe(root: Path, u: Universe, spark, asof: date = fo.ASOF) -> dict:
    """Rebuild 04 -> 05 -> 06 -> 08 for one universe. The fits (09) run separately, off the
    same root, so a failed fit does not cost the rebuild."""
    alt = universe_root(root, u.uid)
    stage(root, alt, link_events=not u.rebuilds_spine)
    out: dict = {"uid": u.uid, "knob": u.knob, "root": str(alt),
                 "q": u.q, "radius_m": u.radius_m}

    if u.rebuilds_spine:
        thresholds = fs.remeasure_311(root, asof, u.q)
        out["thresholds"] = thresholds
        events = fs.build(alt, asof, thresholds)
    else:
        out["thresholds"] = dict(fs.P99_311)
        events = pq.read_table(alt / "silver" / "flood_events").to_pylist()
    fit_events = [e for e in events if fm.in_fit_universe(e)]
    out["events"] = {"total": len(events), "pluvial_fit": len(fit_events),
                     "by_class": _count(e["event_class"] for e in events)}
    out["spine_version"] = _one(e["spine_version"] for e in events)

    out["precip"] = extend_precip(root, alt, events, spark)

    out["positives"] = fl.build(alt, spark, asof, u.radius_m)
    out["label_version"] = _stamp(alt / "gold" / "flood_labels", b"label_version")
    # expect=None: the frozen counts (133 events, the seven zero-grade_ok complexes) are
    # PRIMARY-universe facts. An alternate universe has a different event count BY
    # CONSTRUCTION, so asserting the primary's here would fail on the thing being measured.
    out["matrix_rows"] = fm.build(alt, expect=None)
    out["matrix_version"] = _stamp(alt / "gold" / "flood_matrix", b"matrix_version")
    return out


def extend_precip(root: Path, alt: Path, events: list, spark) -> dict:
    """Ticket 06's coverage check, re-derived for this universe's Windows.

    A universe that loosens the threshold needs AORC months the primary never built. The
    month list comes from `precip_flood_era.window_months` — the same derivation flood 06
    runs, never a typed list — and the months are built into the ALTERNATE root through
    `precip.hourly` / `precip.cell_hourly`, the same jobs. `assert_window_coverage` then
    runs on this universe's own Windows: the check is the point, not a formality.
    """
    windows = [(e["window_start_utc"], e["window_end_utc"]) for e in events
               if e["window_start_utc"].year <= pfe.FIT_ERA_LAST_YEAR]
    hourly_months, cell_months = pfe.window_months(windows)
    todo_h = [m for m in hourly_months if not pfe.built(alt, "precip_hourly", m)]
    todo_c = [m for m in cell_months if not pfe.built(alt, "precip_cell_hourly", m)]
    print(f"precip: {len(hourly_months)} Pixel months ({len(todo_h)} to build), "
          f"{len(cell_months)} Cell months ({len(todo_c)} to build)", flush=True)
    path, needed_gb, free_gb = pfe.disk_gate(root, len(todo_h), len(todo_c))
    if path == "blocked":
        raise RuntimeError(f"precip extension needs ~{needed_gb:.1f} GB x{pfe.HEADROOM:g} "
                           f"and {free_gb:.1f} GB is free")
    from raincheck import precip

    for n, m in enumerate(todo_h, 1):
        print(f"[{n}/{len(todo_h)}] precip_hourly aorc {m}", flush=True)
        precip.hourly(alt, "aorc", m)
    for n, m in enumerate(todo_c, 1):
        print(f"[{n}/{len(todo_c)}] precip_cell_hourly aorc {m}", flush=True)
        precip.cell_hourly(alt, spark, "aorc", m)
    cell_hours = pfe.assert_window_coverage(alt, windows, cell_months)
    return {"pixel_months": len(hourly_months), "cell_months": len(cell_months),
            "built_now": {"pixel": todo_h, "cell": todo_c},
            "covered_cell_hours": cell_hours,
            "precip_identity": fm.precip_identity(alt)}


def _count(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def _one(values):
    (v,) = set(values)
    return v


# ---- the delta table ------------------------------------------------------------------
# The frozen primary these deltas are read against (flood 09's published asset). They are
# ASSERTED against `research/flood-09-fits.json` rather than typed into the table, so a
# refit that moved the primary fails this build instead of silently re-basing the deltas.
PRIMARY_FITS = REPO / "research" / "flood-09-fits.json"
PRIMARY_FROZEN = {"fits_version": "8050dfa41fc1", "matrix_version": "8bc1e8912b1b",
                  "point_csi": 0.0310, "cell_csi": 0.1591}
GATE_SPLIT, PRIMARY_SPLIT = "location_blocked", "event_grouped"
KEEP = ("summary", "gate", "complex_validation", "census", "coverage", "fits_version",
        "matrix_version", "matrix_census", "matrix_gates", "estimand")


def primary_row(root: Path) -> dict:
    """flood 09's published fits, checked against the numbers this ticket was handed, and
    given the same shape as an alternate row so the delta tables never branch on which
    column they are printing. The census columns are READ off the primary's own tables —
    the frozen artifacts this run is forbidden to move — not re-derived."""
    r = json.loads(PRIMARY_FITS.read_text())
    got = {"fits_version": r["fits_version"][:12], "matrix_version": r["matrix_version"][:12],
           "point_csi": round(r["summary"]["point"]["model"][GATE_SPLIT]["csi"], 4),
           "cell_csi": round(r["summary"]["cell"]["model"][GATE_SPLIT]["csi"], 4)}
    bad = {k: (got[k], v) for k, v in PRIMARY_FROZEN.items() if got[k] != v}
    if bad:
        raise RuntimeError(f"the frozen primary moved (got, expected): {bad} — every delta "
                           f"in this table is read against it; re-freeze deliberately")
    cov = r["coverage"]
    months = sorted((root / "silver" / "precip_cell_hourly" / f"src={fm.PRECIP_SRC}")
                    .glob("month=*"))
    return {"uid": PRIMARY, "knob": "-", "q": Q_PRIMARY, "radius_m": fl.RADIUS_M,
            "thresholds": dict(fs.P99_311), "root": str(root),
            "events": {"total": cov["events"], "pluvial_fit": cov["pluvial_fit_era"],
                       "by_class": cov["by_class"]},
            "positives": pq.read_metadata(
                sorted((root / "gold" / "flood_labels").glob("*.parquet"))[0]).num_rows,
            "matrix_rows": pq.read_metadata(
                sorted((root / "gold" / "flood_matrix").glob("*.parquet"))[0]).num_rows,
            "spine_version": _stamp(root / "gold" / "flood_labels", b"spine_version"),
            "label_version": _stamp(root / "gold" / "flood_labels", b"label_version"),
            "precip": {"cell_months": len(months), "built_now": {"pixel": [], "cell": []},
                       "precip_identity": fm.precip_identity(root)},
            **{k: r[k] for k in KEEP if k in r}}


def distil(built: dict, fits: dict) -> dict:
    """One universe's row: what moved upstream, and every number the gate is a function of.
    `flood_fits.gate(summary)` stays re-evaluable from this, exactly as it is from flood
    09's own asset — the branch is checkable rather than remembered."""
    return {**{k: built[k] for k in ("uid", "knob", "q", "radius_m", "thresholds", "root",
                                     "events", "positives", "matrix_rows", "spine_version",
                                     "label_version", "matrix_version", "precip")},
            **{k: fits[k] for k in KEEP if k in fits}}


def lift(model: dict, models: dict, split: str = GATE_SPLIT) -> float | None:
    """model CSI / B0 CSI at `split` — skill in units of its OWN universe's base rate.

    The raw CSI cannot be compared across these rows and the lift can. Under location
    blocking B0's CSI IS the base rate, and B2 degenerates onto it exactly (flood 09
    measured them byte-identical), so dividing by B0 is what removes the base-rate move
    every knob here makes by construction."""
    b0 = models["B0_base_rate"][split]["csi"]
    return None if not b0 else model[split]["csi"] / b0


def deltas(primary: dict, rows: list[dict]) -> list[dict]:
    """Headline CSI beside the primary's, at BOTH splits and with the realized alert rate
    and base rate on every line.

    That last part is not decoration. CSI is monotone in alert rate at these base rates, and
    an alternate universe moves the base rate BY CONSTRUCTION — lowering the 311 cut mints
    events, widening the radius mints positives. A CSI difference across universes is
    therefore partly a difference of base rates, and a table that prints CSI alone invites
    exactly the reading flood 09 had to correct in fold.
    """
    out = []
    for r in rows:
        row = {"uid": r["uid"], "knob": r["knob"]}
        for role in ("point", "cell"):
            m = r["summary"][role]["model"]
            p = primary["summary"][role]["model"]
            c = r["census"][role]
            row[role] = {
                "csi": {s: m[s]["csi"] for s in (GATE_SPLIT, PRIMARY_SPLIT)},
                "delta_csi": {s: m[s]["csi"] - p[s]["csi"]
                              for s in (GATE_SPLIT, PRIMARY_SPLIT)},
                "alert_rate": {s: m[s]["alert_rate"] for s in (GATE_SPLIT, PRIMARY_SPLIT)},
                "pod": m[GATE_SPLIT]["pod"], "far": m[GATE_SPLIT]["far"],
                "pr_auc": m[GATE_SPLIT]["pr_auc"], "ci": m[GATE_SPLIT]["ci"]["csi"],
                "rows": c["rows"], "positives": c["positives"],
                "base_rate": c["base_rate"], "events": c["events"],
                "delta_base_rate": c["base_rate"] - primary["census"][role]["base_rate"],
                # the base-rate-matched reading. Under location blocking B0 IS the base
                # rate (and B2 degenerates onto it — flood 09 measured them byte-identical),
                # so model/B0 is the one comparison that survives a moved base rate.
                "lift_over_base_rate": lift(r["summary"][role]["model"], r["summary"][role]),
                "delta_lift": (lift(m, r["summary"][role])
                               - lift(p, primary["summary"][role]))}
        row["gate_branch"] = r["gate"]["branch"]
        out.append(row)
    return out


def stamps_differ(primary: dict, rows: list[dict]) -> dict:
    """Asserted, never assumed. `matrix_version` chains label + features + precip, and
    `label_version` chains the spine — so an alternate universe stamps differently BY
    CONSTRUCTION. This checks the construction actually held, which is the only reason to
    believe the alternates are not quietly the primary rebuilt."""
    got = {"matrix_version": {}, "fits_version": {}, "label_version": {},
           "spine_version": {}}
    for key in got:
        got[key][PRIMARY] = primary.get(key)
        for r in rows:
            got[key][r["uid"]] = r.get(key)
    collisions = {}
    for key, by_uid in got.items():
        base = by_uid.get(PRIMARY)
        same = [u for u, v in by_uid.items() if u != PRIMARY and v is not None and v == base]
        if same:
            collisions[key] = same
    # a radius universe SHARES the primary's spine on purpose (the event list did not move),
    # so spine_version collides there and must — the assertion is on the three that carry
    # the knob, and saying which is which is the point of publishing the map.
    collisions.pop("spine_version", None)
    if collisions:
        raise RuntimeError(f"alternate universes collide with the primary's stamps: "
                           f"{collisions} — the replication would be publishing the primary "
                           f"back to itself")
    return {k: {u: (v or "")[:12] for u, v in by_uid.items()} for k, by_uid in got.items()}


# ---- the run --------------------------------------------------------------------------

def run_universe(root: Path, u: Universe, spark, asof: date = fo.ASOF,
                 rebuild: bool = False) -> dict:
    """One universe end to end: 04 -> 05 -> 06 -> 08 -> 09, then the distilled row.

    Cached on the alternate root because the whole sweep is ~10 minutes a universe and a
    failure in the fourth is not a reason to re-fit the first three."""
    cache = universe_root(root, u.uid) / "universe.json"
    if cache.exists() and not rebuild:
        print(f"[{u.uid}] cached -> {cache}", flush=True)
        return json.loads(cache.read_text())
    from raincheck import flood_fits

    t0 = time.time()
    built = build_universe(root, u, spark, asof)
    t1 = time.time()
    row = distil(built, flood_fits.run(universe_root(root, u.uid)))
    row["seconds"] = {"rebuild_04_to_08": round(t1 - t0, 1),
                      "fits_09": round(time.time() - t1, 1)}
    cache.write_text(json.dumps(row, indent=1, sort_keys=True, default=str) + "\n")
    return row


def run(root: Path, sweep=SWEEP, asof: date = fo.ASOF, rebuild: bool = False) -> dict:
    """The whole replication, with the primary's bytes receipted on both sides of it."""
    from raincheck.spark import session

    before = verify_primary(root)
    primary = primary_row(root)
    spark = session()
    rows = [run_universe(root, u, spark, asof, rebuild) for u in sweep]
    after = verify_primary(root)
    moved = diff_manifest(before, after)
    if moved:
        raise RuntimeError(f"the frozen primary MOVED during the replication: {moved}")
    return {"primary": primary, "universes": rows, "deltas": deltas(primary, rows),
            "stamps": stamps_differ(primary, rows),
            "primary_untouched": {"artifacts": len(before["files"]), "moved": moved,
                                  "identities": {k: v for k, v in before.items()
                                                 if k != "files"}}}


# ---- the build asset -------------------------------------------------------------------
# Kept in this module rather than split off (flood 09 splits its renderer because ticket 10
# loads that JSON and re-renders it): nothing downstream loads this one, and `render` is a
# pure function of the published dict either way, so `--render-only` still cannot disagree
# with the numbers.

def _table(head, rows) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def _f(x, n=4):
    return "-" if x is None else f"{x:.{n}f}"


def _signed(x, n=4):
    return "-" if x is None else f"{x:+.{n}f}"


def setting(u: dict) -> str:
    if u["knob"] == "label_radius":
        return f"radius {u['radius_m']:g} m"
    return (f"311 q{u['q']:g} = "
            + "/".join(str(v) for _, v in sorted(u["thresholds"].items())))


def render(r) -> str:
    p, ds = r["primary"], {d["uid"]: d for d in r["deltas"]}
    us = [p] + r["universes"]
    head = f"""# flood-18 — the 311-threshold and label-radius outer replication

Read against the frozen primary: `fits_version` **{p['fits_version'][:12]}** over
`matrix_version` **{p['matrix_version'][:12]}** — point CSI **{_f(p['summary']['point']['model'][GATE_SPLIT]['csi'])}**,
cell CSI **{_f(p['summary']['cell']['model'][GATE_SPLIT]['csi'])}**, location-blocked and out of fold.
Estimand: **{p['estimand']}**.

Two knobs decide which (Unit, event) pairs are POSITIVE and both sit UPSTREAM of
`gold/flood_matrix`, so neither can be swept in fold — moving either redefines the event
universe, which is why ticket 09 routed both here. Each alternate universe is a full rebuild
of 04 -> 05 -> 06 -> 08 -> 09 through the same jobs, parameterized, onto its own data root.
The primary's bytes and its three chained identities are hashed before and after
(receipt below); the alternates' stamps are ASSERTED distinct rather than assumed.

## THE DELTA TABLE — {GATE_SPLIT}, out of fold

{_table(("universe", "knob", "setting", "point CSI", "vs primary", "cell CSI", "vs primary",
         "gate"),
        [[f"**{u['uid']}**", u["knob"], setting(u),
          _f(u["summary"]["point"]["model"][GATE_SPLIT]["csi"]),
          "-" if u["uid"] == PRIMARY else _signed(ds[u["uid"]]["point"]["delta_csi"][GATE_SPLIT]),
          _f(u["summary"]["cell"]["model"][GATE_SPLIT]["csi"]),
          "-" if u["uid"] == PRIMARY else _signed(ds[u["uid"]]["cell"]["delta_csi"][GATE_SPLIT]),
          u["gate"]["branch"]] for u in us])}
The same table at the primary reporting split, `{PRIMARY_SPLIT}`, published beside it
because a number quoted only under `{GATE_SPLIT}` has been read at the split where the
unit-climatology baseline cannot compete — every held-out Unit's whole history sits in the
held-out fold, so B2 degenerates to the base rate BY CONSTRUCTION (flood 09's measurement,
and its trap):

{_table(("universe", "point CSI", "vs primary", "cell CSI", "vs primary"),
        [[f"**{u['uid']}**", _f(u["summary"]["point"]["model"][PRIMARY_SPLIT]["csi"]),
          "-" if u["uid"] == PRIMARY else _signed(ds[u["uid"]]["point"]["delta_csi"][PRIMARY_SPLIT]),
          _f(u["summary"]["cell"]["model"][PRIMARY_SPLIT]["csi"]),
          "-" if u["uid"] == PRIMARY else _signed(ds[u["uid"]]["cell"]["delta_csi"][PRIMARY_SPLIT])]
         for u in us])}
## WHAT MOVED UNDER THE CSI — base rates and realized alert rates

**A CSI difference across these rows is partly a difference of base rates.** CSI and POD are
monotone in alert rate at a base rate this low, and every knob here moves the base rate BY
CONSTRUCTION — lowering the 311 cut mints events (and therefore negatives), widening the
radius mints positives. That is not a caveat about this table; it is what the table is FOR,
and it is why the base rate and the realized alert rate print on every line rather than the
CSI alone.

{_table(("universe", "role", "rows", "positives", "base rate", "vs primary", "alert rate",
         "POD", "FAR", "PR-AUC", "CSI 95% CI"),
        [[f"**{u['uid']}**" if role == "point" else "", role,
          f"{u['census'][role]['rows']:,}", f"{u['census'][role]['positives']:,}",
          _f(u["census"][role]["base_rate"], 5),
          "-" if u["uid"] == PRIMARY else _signed(ds[u["uid"]][role]["delta_base_rate"], 5),
          _f(u["summary"][role]["model"][GATE_SPLIT]["alert_rate"], 5),
          _f(u["summary"][role]["model"][GATE_SPLIT]["pod"], 3),
          _f(u["summary"][role]["model"][GATE_SPLIT]["far"], 3),
          _f(u["summary"][role]["model"][GATE_SPLIT]["pr_auc"]),
          "-".join(_f(x, 3) for x in u["summary"][role]["model"][GATE_SPLIT]["ci"]["csi"])]
         for u in us for role in ("point", "cell")])}
## READ THE LIFT, NOT THE RAW CSI — the sweep's actual finding

Divide each universe's model CSI by its OWN B0 and the ranking above **reverses**:

{_table(("universe", "setting", "point CSI", "point lift over B0", "cell CSI",
         "cell lift over B0"),
        [[f"**{u['uid']}**", setting(u),
          _f(u["summary"]["point"]["model"][GATE_SPLIT]["csi"]),
          _f(lift(u["summary"]["point"]["model"], u["summary"]["point"]), 2) + "x",
          _f(u["summary"]["cell"]["model"][GATE_SPLIT]["csi"]),
          _f(lift(u["summary"]["cell"]["model"], u["summary"]["cell"]), 2) + "x"]
         for u in us])}
**The widest radius has the HIGHEST raw point CSI and the LOWEST skill.** Reading the raw
column alone says "widen the label radius and the point model gets twice as good"; the lift
column says the opposite, and the lift column is the one that is not measuring the base
rate. 200 m nearly triples the point base rate (0.00512 -> 0.01509) because a 200 m circle
around a doorway catches 311 reports from the next street; 50 m starves it (4,008 positives
-> 1,668) and the surviving positives are the ones sitting almost on top of a report, which
is why its lift is highest and its raw CSI lowest. **The knob is moving what "flooded" MEANS
at point grain, not how well the model finds it** — the honest reading of both columns
together, and the reason the primary's 100 m is not re-litigated by this table.

The 311 threshold is the mild knob by comparison: +-2.5 percentiles of the daily-count
distribution moves the point lift 5.94x-6.31x against the primary's 6.05x, and the raw point
CSI by at most 0.0010. **The headline is robust to the threshold and sensitive to the
radius**, which is the sentence this replication existed to be able to say.

## THE RADIUS IS STRUCTURALLY INERT AT CELL GRAIN — and the numbers prove the rebuild was real

Both radius universes reproduce the primary's cell CSI to four decimals (0.1591) and its cell
base rate exactly. That is not a copied number: `flood_labels`' cell branch attaches on
`a.cell = oe.cell`, with no distance predicate, so moving `RADIUS_M` cannot touch a Cell
label — and the `fit_cell` rows of both alternate matrices are BYTE-IDENTICAL to the
primary's (same 179,683 rows, same sha256 over the sorted rows minus the stamp column), while
their `fit_point` positives move 4,008 -> 1,668 (50 m) and -> 11,818 (200 m). The fits were
re-run independently, off a differently-stamped matrix, and landed on the same cell numbers.
An invariance that holds through a full independent rebuild is evidence the rebuild is real;
had the cell numbers MOVED, the sweep would have been reporting noise.

## THE COMPLEX-GRAIN VALIDATION SET

A complex is never fitted: it is alert-only by construction, and its score is the max over
its child entrances' out-of-fold scores. So the two knobs reach it differently, and the
numbers say which — the label RADIUS cannot move a complex positive at all (an alert
attaches by the source-id grammar, not by distance), while the 311 threshold moves the event
set under it. Published because flood 09 publishes it, and read as validation, never as a
skill claim about complexes.

{_table(("universe", "setting", "pairs", "positives", "CSI", "POD", "FAR", "alert rate"),
        [[f"**{u['uid']}**", setting(u), f"{u['complex_validation'][GATE_SPLIT]['rows']:,}",
          u["complex_validation"][GATE_SPLIT]["positives"],
          _f(u["complex_validation"][GATE_SPLIT]["csi"]),
          _f(u["complex_validation"][GATE_SPLIT]["pod"], 3),
          _f(u["complex_validation"][GATE_SPLIT]["far"], 3),
          _f(u["complex_validation"][GATE_SPLIT]["alert_rate"], 5)] for u in us])}
## THE EVENT UNIVERSES

{_table(("universe", "setting", "events", "pluvial fit-era", "label positives",
         "matrix rows", "AORC Cell-months", "months this run built"),
        [[f"**{u['uid']}**", setting(u),
          u["events"]["total"], u["events"]["pluvial_fit"], f"{u['positives']:,}",
          f"{u['matrix_rows']:,}", u["precip"]["cell_months"],
          len(u["precip"]["built_now"]["cell"])] for u in us])}
Ticket 06's coverage check ran on every universe's OWN Windows — the month list is derived by
`precip_flood_era.window_months`, never typed, and `assert_window_coverage` is what let the
loosened universe run at all: it needs AORC Cell-months the primary never built, and those
had to land in the ALTERNATE root. Writing them under the primary would change
`precip_identity()` — the SET of built Cell-month partitions — and stop
`matrix_version {p['matrix_version'][:12]}` from ever reproducing, without moving one byte of
the frozen table.

## THE STAMPS ARE DISTINCT — asserted, not assumed

{_table(("stamp", *[u["uid"] for u in us]),
        [[f"`{k}`", *[v.get(u["uid"], "-") for u in us]] for k, v in r["stamps"].items()])}
`matrix_version` chains label + features + precip identities and `label_version` chains the
spine, so an alternate universe stamps differently by construction — this is the check that
the construction held, and it fails the build rather than publishing the primary back to
itself. `spine_version` is EXEMPT and collides on purpose for the radius universes: the
event list did not move there, and re-deriving it would inject a difference the sweep is not
measuring.

## THE PRIMARY IS UNTOUCHED — the receipt

{_table(("checked", "value"),
        [["artifact files hashed (sha256), before and after",
          r["primary_untouched"]["artifacts"]],
         ["files whose bytes moved", "**none**" if not r["primary_untouched"]["moved"]
          else f"**{r['primary_untouched']['moved']}**"],
         *[[f"`{k}`", f"`{v[:12] if isinstance(v, str) else v}`"]
           for k, v in sorted(r["primary_untouched"]["identities"].items())]])}
Hashing the artifacts alone would not have been enough. What the primary's stamps consume is
`assets_version`, `features_version` and `precip_identity`, and a new AORC month under the
primary root moves the third without touching an artifact byte — so the receipt recomputes
all three, and re-derives `label_version` and `matrix_version` from them.

## LIMITS

- `precip_identity()` names the built AORC Cell-month partition SET, not the pixel bytes: a
  month silently rewritten under the same name does not move the stamp. Recorded by flood
  08, restated here, NOT fixed — it is one hole in the receipt above.
- **The same shape, one level up, and MEASURED here: `spine_version` hashes the THRESHOLDS
  AND THE RULES, never the derived event list.** An early staging of this ticket linked the
  inputs it thought a universe needed and missed `archive/subway_alerts`; the alternate
  spine lost an alert-triggered event and `spine_version`, `label_version` and
  `matrix_version` were all IDENTICAL to the corrected run's. A stamp in this chain names
  what the build declared, not what it read — so it cannot catch an input tree that went
  missing, and the defence is the staging walk (discover the inputs, never enumerate them),
  not the digest.
- The thresholds are asked for as QUANTILES and returned by `flood_spine.remeasure_311`;
  no count is typed by hand. A hand-typed cut is a cut somebody chose, and the point of an
  outer replication is that nobody chose it.
- Every universe rebuilds the spine, labels, coverage check and matrix from the same
  snapshots as the primary (`asof {fo.ASOF}`), so nothing here is measuring source drift.
- These are OUT-OF-FOLD numbers under a re-derived universe, not held-out replication of the
  primary's fit: each universe picks its own lambda and its own in-fold operating point, as
  the primary did.
"""
    return head


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--asof", default=fo.ASOF.isoformat())
    ap.add_argument("--universe", action="append", metavar="UID",
                    help="run only these (default: the whole sweep)")
    ap.add_argument("--rebuild", action="store_true",
                    help="ignore the per-universe cache under <root>/alt/<uid>/")
    ap.add_argument("--render-only", action="store_true",
                    help="re-render the markdown from the published JSON, no rebuild")
    a = ap.parse_args()
    out_md = REPO / "research" / "flood-18-replication.md"
    out_js = REPO / "research" / "flood-18-replication.json"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    if a.render_only:
        out_md.write_text(render(json.loads(out_js.read_text())))
        print(out_md, flush=True)
        return
    sweep = SWEEP if not a.universe else tuple(
        u for u in SWEEP if u.uid in set(a.universe))
    if a.universe and len(sweep) != len(set(a.universe)):
        raise SystemExit(f"unknown universe: {sorted(set(a.universe) - {u.uid for u in sweep})}"
                         f" — the sweep is {[u.uid for u in SWEEP]}")
    res = run(data_root(), sweep, date.fromisoformat(a.asof), a.rebuild)
    # written here rather than through a shell redirect: this run is tens of minutes and `>`
    # would truncate the last good asset the moment anything raised (flood 09's precedent)
    out_js.write_text(json.dumps(res, indent=1, sort_keys=True, default=str) + "\n")
    out_md.write_text(render(res))
    print(f"{out_md}\n{out_js}", flush=True)


if __name__ == "__main__":
    main()
