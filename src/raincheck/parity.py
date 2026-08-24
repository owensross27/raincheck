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

Either side may be a LOCAL PATH or an R2 PREFIX (`s3://bucket/silver/events`, or `s3a://`
- Spark's spelling of the same object store). Cloud 03 needs that: the cluster's build
lands in R2 and `make daily`'s lands on the Mac, so the parity gate compares one of each,
and forking this module for the remote side would give the gate two definitions of
"equal". Remote credentials come from the environment (AWS_ENDPOINT_URL,
AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION) - the r2-build Secret's own
keys [cloud 07], never an argument and never a literal. One asymmetry is inherent, not a
bug: an object store has no empty directories, so the "empty partition vs missing
partition" distinction below exists only on the local side.

Run: python -m raincheck.parity A_ROOT B_ROOT   (rc 0 equal, 1 differ, 2 inconclusive)
"""
import hashlib
import itertools
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb

from raincheck import duck

EMPTY = hashlib.sha256().hexdigest()  # a partition that exists and holds no rows
SEP = "chr(31)"   # row-text field separator (SQL, not a literal: control chars do not
NULL = "chr(30)"  # survive a quoted string), and a NULL marker so ('a',NULL) != (NULL,'a')
BATCH = 10_000


def remote(root: Path | str) -> str | None:
    """The s3:// form of an object-store root, or None for a local path. `s3a://` is the
    same store under Spark's scheme name, so the gate accepts whichever spelling the side
    that wrote the table uses."""
    text = str(root)
    for scheme in ("s3://", "s3a://"):
        if text.startswith(scheme):
            return "s3://" + text[len(scheme):].rstrip("/")
    return None


def connect(root: Path | str):
    """A DuckDB connection that can read `root`. Remote roots get httpfs pointed at R2 from
    the environment; missing or wrong credentials surface as duckdb.Error, which main()
    reports as INCONCLUSIVE - "could not check" is never "equal"."""
    con = duck.connect()
    if remote(root):
        con.execute("INSTALL httpfs")  # a no-op once installed (the image bakes it)
        con.execute("LOAD httpfs")
        # PROVIDER credential_chain / CHAIN 'env' - DuckDB reads AWS_ACCESS_KEY_ID and
        # AWS_SECRET_ACCESS_KEY itself, so the token never appears in a SQL string, in
        # argv or in a traceback. URL_STYLE path because R2 does not do virtual-host
        # buckets, and REGION because R2 has none but the v4 signature still needs one.
        host = (os.environ.get("AWS_ENDPOINT_URL") or "").split("://")[-1].rstrip("/")
        region = os.environ.get("AWS_DEFAULT_REGION") or "auto"
        con.execute("CREATE OR REPLACE SECRET raincheck_r2 (TYPE s3, PROVIDER credential_chain,"
                    f" CHAIN 'env', ENDPOINT '{host}', URL_STYLE 'path', REGION '{region}')")
    return con


def partitions(root: Path | str, con=None) -> dict[str, list[str]]:
    """{"service_date=2026-08-01": [parquet files]} - one entry per leaf Hive partition, at
    whatever depth (Bronze is date=/hour=). An unpartitioned root is its own single
    partition under the key "", so two unpartitioned tables can never compare equal by both
    having no partitions."""
    base = remote(root)
    if base:
        rows = (con or connect(root)).execute(
            "SELECT file FROM glob(?)", [f"{base}/**/*.parquet"]).fetchall()
        if not rows:  # nothing there at all reads like FileNotFoundError, as it does locally
            raise FileNotFoundError(base)
        out: dict[str, list[str]] = {}
        for (path,) in rows:
            rel = path[len(base) + 1:].split("/")[:-1]
            # the leading run of k=v segments IS the partition; anything below one (a part
            # subdir) belongs to it, exactly as the local rglob folds it in
            out.setdefault("/".join(itertools.takewhile(lambda s: "=" in s, rel)), []).append(path)
        return {name: sorted(files) for name, files in sorted(out.items())}
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    leaves = {}
    for d in root.rglob("*"):
        if d.is_dir() and "=" in d.name and not any(
                c.is_dir() and "=" in c.name for c in d.iterdir()):
            leaves[str(d.relative_to(root))] = d
    return {name: sorted(str(p) for p in d.rglob("*.parquet"))
            for name, d in (leaves or {"": root}).items()}


def digest_partition(con, files: list[str]) -> tuple[int, str]:
    """(rows, sha) for one partition. No parquet in it = an empty partition, which is a real
    answer (0, EMPTY) - never a skip and never the same thing as a missing one."""
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
    con = connect(root)
    return {name: digest_partition(con, files)
            for name, files in sorted(partitions(root, con).items())}


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
