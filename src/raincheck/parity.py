"""Content equality between two builds of one partitioned table (cloud spec section 4 /
ticket 11): the seam the cluster parity gate (03), the capture-placement gate (04) and the
Mac decommission gate (10) all ask "are these two builds the same?".

CONTENT, never bytes. Byte-identity holds only inside one JVM session - parquet-mr permutes
footer encoding order across sessions (~27 bytes, data pages identical) [F01, T02] - and a
cluster run is by construction a different session than `make daily`, so a byte comparison
fails on genuinely correct builds.

A digest is, per partition, (row count, sha256 over the md5 of each row, rows taken in
hash order). Row order, column order, part-file count, row-group size and compression are
therefore invisible; a single changed value is not. Read with DuckDB (duck.py's oracle),
so it digests whatever wrote the files and needs no JVM.

Run: python -m raincheck.parity A_ROOT B_ROOT   (rc 0 equal, 1 differ, 2 inconclusive)
"""
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb

from raincheck import duck

EMPTY = hashlib.sha256().hexdigest()  # a partition that exists and holds no rows
SEP = "chr(31)"   # row-text field separator (SQL, not a literal: control chars do not
NULL = "chr(30)"  # survive a quoted string), and a NULL marker so ('a',NULL) != (NULL,'a')
BATCH = 10_000


def partitions(root: Path | str) -> dict[str, Path]:
    """{"service_date=2026-08-01": dir} - the leaf Hive dirs under root, at whatever depth
    (Bronze is date=/hour=). An unpartitioned root is its own single partition, so two
    unpartitioned tables can never compare equal by both having no partitions."""
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    leaves = {}
    for d in root.rglob("*"):
        if d.is_dir() and "=" in d.name and not any(
                c.is_dir() and "=" in c.name for c in d.iterdir()):
            leaves[str(d.relative_to(root))] = d
    return leaves or {"": root}


def digest_partition(con, path: Path) -> tuple[int, str]:
    """(rows, sha) for one partition dir. No parquet under it = an empty partition, which is
    a real answer (0, EMPTY) - never a skip and never the same thing as a missing one."""
    files = sorted(str(p) for p in path.rglob("*.parquet"))
    if not files:
        return 0, EMPTY
    # union_by_name: parts within one partition may differ in schema (duck.py) - a column
    # absent from a part reads NULL, exactly as the reader sees it
    read = "read_parquet(?, union_by_name = true)"
    cols = sorted(r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {read}", [files]).fetchall())
    row = f" || {SEP} || ".join(
        f"coalesce(\"{c.replace(chr(34), chr(34) * 2)}\"::VARCHAR, {NULL})" for c in cols)
    cur = con.execute(f"SELECT md5({row}) AS h FROM {read} ORDER BY h", [files])
    sha, rows = hashlib.sha256(), 0
    while batch := cur.fetchmany(BATCH):  # hash streaming: a Silver partition is millions of rows
        rows += len(batch)
        for (h,) in batch:
            sha.update(h.encode())
    return rows, sha.hexdigest()


def digest(root: Path | str) -> dict[str, tuple[int, str]]:
    con = duck.connect()
    return {name: digest_partition(con, path) for name, path in sorted(partitions(root).items())}


@dataclass(frozen=True)
class Report:
    """What differs between two digests, and how. Nothing is dropped: every partition of
    either side lands in exactly one of matching / differing / only_in_a / only_in_b."""
    a: dict[str, tuple[int, str]]
    b: dict[str, tuple[int, str]]

    @property
    def only_in_a(self) -> list[str]:
        return sorted(self.a.keys() - self.b.keys())

    @property
    def only_in_b(self) -> list[str]:
        return sorted(self.b.keys() - self.a.keys())

    @property
    def differing(self) -> list[str]:
        return sorted(p for p in self.a.keys() & self.b.keys() if self.a[p] != self.b[p])

    @property
    def matching(self) -> list[str]:
        return sorted(p for p in self.a.keys() & self.b.keys() if self.a[p] == self.b[p])

    @property
    def ok(self) -> bool:
        return not (self.only_in_a or self.only_in_b or self.differing)

    def lines(self) -> list[str]:
        out = [f"MISSING ON B  {p}  rows={self.a[p][0]}" for p in self.only_in_a]
        out += [f"MISSING ON A  {p}  rows={self.b[p][0]}" for p in self.only_in_b]
        for p in self.differing:
            (ra, sa), (rb, sb) = self.a[p], self.b[p]
            how = f"rows {ra} vs {rb}" if ra != rb else f"same {ra} rows, sha {sa[:12]} vs {sb[:12]}"
            out.append(f"DIFFERS       {p}  {how}")
        return out + [f"{'EQUAL' if self.ok else 'NOT EQUAL'}: {len(self.matching)} partitions "
                      f"match, {len(self.differing)} differ, {len(self.only_in_a)} only in A, "
                      f"{len(self.only_in_b)} only in B"]

    def __str__(self) -> str:
        return "\n".join(self.lines())


def compare(a: Path | str, b: Path | str) -> Report:
    return Report(digest(a), digest(b))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: python -m raincheck.parity A_ROOT B_ROOT", file=sys.stderr)
        return 2
    try:
        report = compare(*argv)
    except (OSError, duckdb.Error) as e:  # unreadable side: could not check, never "ok"
        print(f"INCONCLUSIVE: {e}", file=sys.stderr)
        return 2
    print(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
