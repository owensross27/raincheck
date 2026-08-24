"""The data root (spec A): RAINCHECK_ARCHIVE_ROOT, default the repo's data/ (the external SSD
in practice). Every dataset root hangs off it: archive/ (Bronze), ref/, silver/, gold/,
live/, checkpoints/, checks/, .staging/. Unset or empty means the default.

The root may also be an OBJECT STORE - `s3a://raincheck-bronze` (Spark's scheme name) or
`s3://...` (DuckDB's) - so a cluster pod can read the real tables instead of an ephemeral
staging volume [cloud 12]. `Path` cannot hold one: `Path("s3a://b/x")` collapses to
`s3a:/b/x`. The BARRED fix (KNOWN TRAPS) is a Path subclass that re-expands on `__str__`,
because it inherits `.exists()`/`.glob()`/`.rglob()` from Path and those keep answering
about the LOCAL disk - after which `daily.gaps()` reads every service day off the wrong
filesystem and rebuilds the lot, silently.

So a remote root is `RemotePath`, which inherits NOTHING. It joins and stringifies like a
Path (that is how the engines get their string roots: spark.py's s3a when AWS_ENDPOINT_URL
is set, duck.py's httpfs), it answers `exists()`/`glob()`/`rglob()` against the STORE, and
every other Path operation raises. Refusing is the point: the default for anything not
listed here is a loud NotImplementedError, never a local-disk answer. Writes are all in
that second group - `mkdir`, `replace`, `touch`, `write_text` - so the build path fails at
its first POSIX call rather than half-writing somewhere nobody looks.
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCHEMES = ("s3://", "s3a://")
WILD = ("*", "?", "[")


def remote(root: "Path | str | RemotePath") -> str | None:
    """The `s3://` form of an object-store root, or None for a local path. `s3a://` is the
    same store under Spark's scheme name, so either spelling is accepted and the canonical
    (DuckDB) one is returned. The scheme must START the string: `/data/s3a://x` is a
    local path with a silly name."""
    text = str(root)
    for scheme in SCHEMES:
        if text.startswith(scheme):
            return "s3://" + text[len(scheme):].rstrip("/")
    return None


def as_root(root: "Path | str | RemotePath") -> "Path | RemotePath":
    """Normalise a caller-supplied data root. Use this INSTEAD OF `Path(root)` wherever a
    root arrives as a string, or the scheme collapses and the remote root silently becomes
    a relative local one."""
    return RemotePath(root) if remote(root) else Path(root)


def data_root() -> "Path | RemotePath":
    return as_root(os.environ.get("RAINCHECK_ARCHIVE_ROOT") or REPO / "data")


def _store_glob(pattern: str) -> list[str]:
    """Object keys matching `pattern` in the store. The one place RemotePath talks to R2,
    so it is also the seam tests replace.

    A WILDCARD-FREE pattern is refused, and that is not pedantry: measured 2026-08-24,
    DuckDB's `glob('s3://bucket/does-not-exist')` returns the path VERBATIM without
    touching the store, so an existence test written that way answers yes for everything.
    One wildcard anywhere makes it list and verify (`date=2026-08-2*/hour=00/part-NOPE
    .parquet` -> 0 rows), which is why exists() goes through the parent listing."""
    if not any(c in pattern for c in WILD):
        raise ValueError(f"wildcard-free glob would not touch the store: {pattern}")
    from raincheck import duck  # lazy: DuckDB loads only when a remote root is touched
    return [r[0] for r in duck.connect().execute(
        "SELECT file FROM glob(?)", [pattern]).fetchall()]


# ponytail: one store listing per predicate, no caching. MEASURED 2026-08-24 against the
# real bucket: daily.gaps() over a ONE-day window is 164 list calls / 18.9 s, because
# gapfill.missing_hours() asks per hour and per marker - the cost is the POSIX loop shape,
# not the listing (rglob over archive/vp is 7,806 objects in one call, 4.9 s). Correct and
# slow is the right trade while this ships READ honesty; if a build ever runs off an R2
# root, cache one recursive listing per root rather than making the predicates cleverer.
class RemotePath:
    """One object-store location. Joins and stringifies like a Path; answers existence and
    globs against the store; refuses every other Path operation.

    One asymmetry is inherent, not a bug (parity.py says the same): an object store has no
    directories, so "this prefix exists" means "some object lives under it" and an empty
    directory cannot be represented at all."""
    __slots__ = ("_url",)

    def __init__(self, url: "Path | str | RemotePath") -> None:
        self._url = str(url).rstrip("/")

    def __str__(self) -> str:
        return self._url

    def __repr__(self) -> str:
        return f"RemotePath({self._url!r})"

    def __eq__(self, other) -> bool:
        return isinstance(other, RemotePath) and self._url == other._url

    def __hash__(self) -> int:
        return hash(self._url)

    def __truediv__(self, other) -> "RemotePath":
        return RemotePath(f"{self._url}/{str(other).strip('/')}")

    def joinpath(self, *parts) -> "RemotePath":
        out = self
        for p in parts:
            out = out / p
        return out

    @property
    def name(self) -> str:
        return self._url.rsplit("/", 1)[-1]

    @property
    def parent(self) -> "RemotePath":
        return RemotePath(self._url.rsplit("/", 1)[0])

    def exists(self) -> bool:
        """True when this is a prefix with objects under it, or an object itself. The
        object case is a listing of the PARENT and a membership test, never a bare
        glob of the key - see _store_glob."""
        s3 = remote(self._url)
        if _store_glob(f"{s3}/**"):
            return True
        return s3 in _store_glob(f"{s3.rsplit('/', 1)[0]}/*")

    def glob(self, pattern: str):
        """Path.glob semantics over the store: a pattern segment matches objects AND the
        implied prefixes objects sit under, so `glob("date=*")` yields the date partitions
        exactly as it does on disk (DuckDB alone returns nothing for that - there is no
        `date=...` object to match)."""
        if not any(c in pattern for c in WILD):
            child = self / pattern
            return iter([child] if child.exists() else [])
        s3 = remote(self._url)
        keys = {f[len(s3) + 1:] for f in _store_glob(f"{s3}/{pattern}")}
        if "**" not in pattern:  # with ** the match depth is not the pattern's depth
            depth = len(pattern.split("/"))
            keys |= {"/".join(f[len(s3) + 1:].split("/")[:depth])
                     for f in _store_glob(f"{s3}/{pattern}/**")}
        return iter([self / k for k in sorted(keys)])

    def rglob(self, pattern: str):
        return self.glob(f"**/{pattern}")

    def __getattr__(self, name: str):
        if name.startswith("__"):       # let copy/pickle probes fail as absence, not error
            raise AttributeError(name)
        raise NotImplementedError(
            f"{name}() is a local-filesystem operation and this data root is object "
            f"storage ({self._url}). raincheck refuses it rather than answering about the "
            f"local disk: a root that lies here makes daily.gaps() rebuild every service "
            f"day (KNOWN TRAPS). Reads go through the engines' string roots (spark s3a, "
            f"duckdb httpfs); writes to an R2 root are not supported yet [cloud 12].")
