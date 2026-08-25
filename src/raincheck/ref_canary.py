"""The reference canaries as CHECK ROWS (orchestration ticket 10), on ticket 02's
vocabulary — so the canaries `ref.py` already enforces at BUILD time have a batch a GX
suite can expect on, and a Data Docs page a human can read.

WHY THIS EXISTS AT ALL, and why it is a CENSUS rather than a rebuild. `ref/` is the root of
the whole stage graph and it CANNOT be rebuilt here: `ref/assets` needs `silver/stops`,
which needs `make picks`, which is 401-blocked (KNOWN TRAPS). So the three canaries below
fire today only inside `ref.build_assets()`, i.e. only on a rebuild nobody can run — they
raise, they print, and they leave nothing behind. This module runs the SAME three
comparisons read-side against the built table, which is the only form of them that is
available at all, and persists them as rows.

NOT A SECOND HOME FOR A SINGLE NUMBER. Every threshold and every frozen count stays in
`ref.py`:

  - the frozen counts are `ref.ASSETS_EXPECT` — one row per key, `got` beside the
    constant's `want`. No count is retyped in this file or in the suite that reads it.
  - the content identity is `ref.assets_version(root)`, recorded as the row's measure.
  - the key-stability contract is `ref.assets_key_diff(old, new)`, run against the two
    derived tables `build_assets()` itself guards: an `asset_id` they reference that the
    registry no longer holds is an ORPHAN, which is the rebuild check with no rebuild.

NAMED CEILING on the identity row. Nothing in this repo PERSISTS an `assets_version` to
compare against — it is an INGREDIENT of `label_version` and `features_version` and a live
field of `query.versions()`, never a stored column. So that row proves the identity
RESOLVES and publishes its value; a registry that MOVED is caught by the count rows and the
orphan rows. A frozen sha here would be the second home this ticket exists to avoid.

THE THIRD OUTCOME IS THE COMMON CASE HERE, not an edge. A worktree, a fresh checkout and
every task pod have no `ref/assets` at all (`refpull` writes one only on the four POSIX
pods), and a root with no registry tells you NOTHING about the registry — INCONCLUSIVE,
with every measure NULL, never a pass and never a gap. Same rule per derived table: no
`gold/flood_labels` on this root means the orphan question was not asked.

A TABLE IS A PART FILE, NOT A FOLDER (KNOWN TRAPS): every writer here mkdirs before it
writes, so a directory-existence test reads a half-built table as built. Presence is
`any(rglob("*.parquet"))` throughout.

Run: make refcanary   (python -m raincheck.ref_canary)
Exit: 1 a canary moved, 2 nothing could be checked, else 0 — checks.rc's own rule.
The suite over its batch is `make gxref` (`python -m raincheck.gx ref-canaries`).
"""
import sys
from pathlib import Path

from raincheck import checks
from raincheck.paths import data_root

CHECK = "ref"
# `got` and `want` are STRINGS because one batch carries both counts and a sha1. `want` is
# NULL on a row with nothing frozen to compare against (the identity), which is why the
# suite's not-null expectation is on `got` alone.
CHECK_COLUMNS = checks.CORE + ("got", "want")
ASSETS = ("ref", "assets")
# The two derived tables `ref.build_assets()` refuses to orphan on a rebuild. Read from
# there rather than invented here: this module asks the same question read-side.
KEY_TABLES = ("gold/flood_labels", "silver/asset_features")
IDENTITY = "assets_version"


def built(root: Path, *parts: str) -> bool:
    """A readable PART FILE, never a directory. Every Gold/Silver writer mkdirs before it
    writes, so a run that dies in between leaves an empty directory that a `.exists()`
    reads as a built table (KNOWN TRAPS, notify 03's whole-root outage)."""
    return any(root.joinpath(*parts).rglob("*.parquet"))


def subjects() -> tuple[str, ...]:
    """Every canary this producer emits a row for, on EVERY path — the declaration the
    suite's batch-level claim reads, so a canary that did not run is a missing row rather
    than a silent absence. Derived from `ref.ASSETS_EXPECT` and KEY_TABLES, so a count
    frozen in `ref.py` tomorrow is covered the day it lands."""
    from raincheck import ref

    return (*(f"count {k}" for k in sorted(ref.ASSETS_EXPECT)), IDENTITY,
            *(f"keys {t}" for t in KEY_TABLES))


def row(subject: str, outcome: str, detail: str = "",
        got=None, want=None) -> checks.Row:
    """One canary's row. NULL measures on the could-not-check path, never zeros: a 0 is a
    measurement that was taken, and the whole third outcome rests on the difference."""
    return checks.Row(CHECK, subject, outcome, detail,
                      {"got": got, "want": want})


def counts(t) -> dict[str, int]:
    """`build_assets()`'s own arithmetic, read off the table instead of off the rows it was
    about to write. The COUNTING has to be re-expressed (the build counts before the table
    exists); the NUMBERS are not — every expected value is `ref.ASSETS_EXPECT`'s.

    `cells_scored` is the count of `cell` rows carrying `scored`, which is exactly
    `len(scored_cells)` on the build side: every Cell row is written with
    `scored=cell in scored_cells`.
    """
    from raincheck import ref

    kinds = t.column("kind").to_pylist()
    scored = t.column("scored").to_pylist()
    got = {k: kinds.count(k) for k in ref.ASSETS_EXPECT}
    got["total"] = t.num_rows
    got["cells_scored"] = sum(1 for k, s in zip(kinds, scored) if k == "cell" and s)
    return got


def census(root: Path) -> list[checks.Row]:
    """Every canary, one row each, on every path.

    `ref` is imported HERE and not at module level: `raincheck.gx` reads this module's
    CHECK_COLUMNS to declare its suite, and `ref.py` pulls numpy, pyarrow, shapely and
    pyproj on import — none of which belong in the 250m/512Mi pod that renders Data Docs.
    Same rule orch 09 applied to `eras.py`'s duck/events imports, for the same reason.
    """
    from raincheck import paths, ref

    if not built(root, *ASSETS):
        return [row(s, checks.INCONCLUSIVE,
                    f"no {'/'.join(ASSETS)} part file under {root} - nothing was checked")
                for s in subjects()]

    t = paths.read_table(root.joinpath(*ASSETS),
                         columns=["asset_id", "kind", "scored"])
    got = counts(t)
    rows = []
    for key, want in sorted(ref.ASSETS_EXPECT.items()):
        n = got[key]
        rows.append(row(f"count {key}", checks.OK if n == want else checks.FAIL,
                        "" if n == want else f"  FROZEN COUNT MOVED {want} -> {n}",
                        got=str(n), want=str(want)))
    # The identity resolves off the same table; see this module's ceiling note above for
    # why it has no `want`. This one read is POSIX-only - `ref.assets_version` calls
    # `pq.read_table` itself - which costs nothing today: `ref/` reaches a pod through
    # refpull, as a real directory tree, and never as an object-store prefix (cloud 12).
    rows.append(row(IDENTITY, checks.OK, got=ref.assets_version(root)))

    current = dict.fromkeys(t.column("asset_id").to_pylist(), ())
    for table in KEY_TABLES:
        parts = tuple(table.split("/"))
        if not built(root, *parts):
            rows.append(row(f"keys {table}", checks.INCONCLUSIVE,
                            f"  {table} is not built on this root - the orphan question "
                            f"was never asked"))
            continue
        referenced = dict.fromkeys(
            paths.read_table(root.joinpath(*parts), columns=["asset_id"])
            .column("asset_id").to_pylist(), ())
        # `ref.assets_key_diff` IS the key-stability contract - the one home for it. Only
        # `removed` is read: old minus new, i.e. every asset_id this derived table still
        # references that the registry no longer holds. The coordinates it also diffs are
        # EMPTY on both sides here, because a derived table carries no lon/lat to move.
        orphans = ref.assets_key_diff(referenced, current)["removed"]
        rows.append(row(f"keys {table}", checks.FAIL if orphans else checks.OK,
                        f"  ORPHANED {len(orphans)}: {', '.join(orphans[:5])}"
                        f"{' ...' if len(orphans) > 5 else ''}" if orphans else "",
                        got=str(len(orphans)), want="0"))
    return rows


def line(r: checks.Row) -> str:
    mark = {checks.OK: "OK ", checks.FAIL: "BAD", checks.INCONCLUSIVE: "???"}[r.outcome]
    got, want = r.measures["got"], r.measures["want"]
    tail = "" if want is None else f" want={want}"
    return f"{mark} {r.subject:28s} got={got}{tail}{r.detail}"


def main() -> None:
    root = data_root()
    rows = census(root)
    for r in rows:
        print(line(r), flush=True)
    checks.write(root, CHECK, rows, CHECK_COLUMNS)
    sys.exit(checks.rc(rows))


if __name__ == "__main__":
    main()
