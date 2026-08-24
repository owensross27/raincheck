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
listed here is a loud NotImplementedError, never a local-disk answer.

WRITES [cloud 13]. Cloud 12 left every writer in that refusing group, so a cluster build
still died with its staging volume. What is converted now is the WHOLE-OBJECT half:
`write_bytes`/`write_text`/`touch` are one PUT, which an object store makes atomic (the
object appears whole or not at all), `mkdir` is an honest no-op (there are no directories
to create), and the two operations that are not Path methods at all - `move` and `rmtree`
- are module functions here that work on both kinds of root, so a call site does not fork.
Everything else STILL REFUSES, deliberately: `replace`/`rename` (an object store has no
rename - that is the whole atomicity problem), `open`/`read_bytes`/`iterdir`/`stat`, and
so on. So `precip_live`, `export`, `features`, `stream`'s batch receipt and the four other
copies of the one_file dance keep failing loudly on a remote root instead of half-writing.

ATOMICITY is ordering, not locking: cloud 09's frozen pattern - write the DATA first, the
MARKER or meta LAST, and a missing marker reads as UNBUILT. gapfill's `_gapfill` is that
marker; for a Silver partition it is `part-00000.parquet` itself, the object daily.gaps()
tests for, published by ONE copy after the staging write is complete.
"""
import contextlib
import os
import re
import shutil
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


def _duck_glob(pattern: str) -> list[str]:
    """One real listing of the store. The single place RemotePath talks to R2."""
    from raincheck import duck  # lazy: DuckDB loads only when a remote root is touched
    return [r[0] for r in duck.connect().execute(
        "SELECT file FROM glob(?)", [pattern]).fetchall()]


def _pattern_re(pattern: str):
    """DuckDB's glob semantics as a regex, so a cached listing answers exactly what a
    fresh one would: `**` crosses `/`, `*` and `?` do not. Pinned against the real bucket
    by test_the_cached_listing_answers_what_a_fresh_listing_would."""
    rx = (re.escape(pattern).replace(r"\*\*/", "(?:.*/)?")
          .replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]"))
    return re.compile(rx)


_LISTINGS: list[dict] = []   # open cached_listing scopes, innermost last


@contextlib.contextmanager
def cached_listing(root: "Path | str | RemotePath"):
    """ONE recursive listing of `root`, answering every exists()/glob() inside the block.

    The upgrade the note below named, taken by cloud 13 because the build gate now runs on
    a remote root. MEASURED against raincheck-bronze: the whole root is 35,658 objects in
    ONE call / 17.1 s, against daily.gaps()'s per-hour POSIX loop - see the RUN LOG entry
    for the before/after. A LOCAL root is a no-op passthrough, so the call site does not
    fork.

    Deliberately NOT write-through: any RemotePath write inside an open scope DROPS the
    cache and the next predicate re-lists. That is three lines instead of a coherency
    protocol, and it protects the one thing a cache here must not break - gapfill's
    scan-to-write race check, which exists to notice an EXTERNAL writer."""
    if remote(root) is None:
        yield
        return
    _LISTINGS.append({"prefix": remote(root), "keys": None})
    try:
        yield
    finally:
        _LISTINGS.pop()


def _drop_cached_listings() -> None:
    for scope in _LISTINGS:
        scope["keys"] = None


def _store_glob(pattern: str) -> list[str]:
    """Object keys matching `pattern` in the store. The seam tests replace.

    A WILDCARD-FREE pattern is refused, and that is not pedantry: measured 2026-08-24,
    DuckDB's `glob('s3://bucket/does-not-exist')` returns the path VERBATIM without
    touching the store, so an existence test written that way answers yes for everything.
    One wildcard anywhere makes it list and verify (`date=2026-08-2*/hour=00/part-NOPE
    .parquet` -> 0 rows), which is why exists() goes through the parent listing."""
    if not any(c in pattern for c in WILD):
        raise ValueError(f"wildcard-free glob would not touch the store: {pattern}")
    for scope in reversed(_LISTINGS):
        if pattern.startswith(scope["prefix"] + "/"):
            if scope["keys"] is None:
                scope["keys"] = _duck_glob(f"{scope['prefix']}/**")
            rx = _pattern_re(pattern)
            return [k for k in scope["keys"] if rx.fullmatch(k)]
    return _duck_glob(pattern)


def _fs():
    """The store handle for WRITES. s3fs is already this repo's object-store writer
    (publish.py), reads AWS_* from the environment itself and forwards to put_object - so
    no second credential path, no token in argv, and no aws CLI in the image."""
    import s3fs
    return s3fs.S3FileSystem(endpoint_url=os.environ.get("AWS_ENDPOINT_URL") or None)


def move(src, dst) -> None:
    """Move ONE file/object. Local: shutil.move, a rename inside one filesystem. Remote: a
    SERVER-SIDE copy then a delete of the source - an object store has no rename, and the
    copy is what makes the destination appear whole or not at all. Bytes never come back
    to the client. Crossing the boundary is refused: that is a transfer, not a move, and
    the only way it happens here is a root that was half-converted."""
    if remote(src) is None and remote(dst) is None:
        shutil.move(src, dst)
        return
    if remote(src) is None or remote(dst) is None:
        raise ValueError(f"move across the local/store boundary is not a move: {src} -> {dst}")
    fs = _fs()
    fs.copy(remote(src), remote(dst))
    fs.rm_file(remote(src))
    _drop_cached_listings()


def rmtree(p) -> None:
    """Delete a directory, or everything under a prefix (one_file's staging, prune's
    expired live hours). Missing is fine either way - an already-gone prefix IS the
    outcome asked for - but a real failure still raises on both kinds of root."""
    if remote(p) is None:
        if Path(p).exists():   # missing is fine; a real failure (permissions) still raises
            shutil.rmtree(p)
        return
    fs = _fs()
    if fs.exists(remote(p)):
        fs.rm(remote(p), recursive=True)
    _drop_cached_listings()


def rmdir_if_empty(p) -> None:
    """Remove `p` if it is an empty directory. On an object store this is a no-op and that
    is the whole truth, not a shortcut: an empty prefix cannot be represented at all, so
    the day directory stopped existing when its last hour object was deleted."""
    if remote(p) is None:
        with contextlib.suppress(OSError):  # a non-empty day raises and stays
            p.rmdir()


def read_table(p, **kw):
    """`pq.read_table` against either kind of root. pyarrow cannot take a RemotePath (it
    probes `.read` and gets the refusal) and does not know the `s3a://` spelling, so the
    remote case hands it the same s3fs filesystem publish.py writes through."""
    import pyarrow.parquet as pq
    s3 = remote(p)
    if s3 is None:
        return pq.read_table(p, **kw)
    return pq.read_table(s3[len("s3://"):], filesystem=_fs(), **kw)


# One store listing per predicate is still the DEFAULT, and still correct-and-slow:
# MEASURED 2026-08-24, daily.gaps() over a one-day window is 164 list calls / 18.9 s
# because gapfill.missing_hours() asks per hour and per marker - the cost is the POSIX
# loop shape, not the listing (rglob over archive/vp is 7,806 objects in ONE call, 4.9 s).
# Cloud 12 left this as a ponytail note for "if a build ever runs off an R2 root"; cloud 13
# is that build, so the note's own answer is now shipped as `cached_listing` above - one
# recursive listing per root, opened at the SCAN (daily.gaps) rather than made clever in
# the predicate. Measured over the real 14-day window: 1,960 calls / 231.1 s -> 1 call /
# 22.4 s, same days out. Nothing else opens a scope, and nothing has to.
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

    # --- writes [cloud 13] --------------------------------------------------------------
    # Whole-object writes only. A PUT is atomic - the object appears whole or not at all -
    # so nothing here needs a lock, and nothing here is read-modify-write. Ordering does
    # the rest (cloud 09's frozen pattern): DATA FIRST, MARKER LAST, a missing marker
    # reads as unbuilt. `replace`/`rename` stay refused on purpose: an object store has no
    # rename, so a writer reaching for one is a writer whose atomicity story is still
    # POSIX and must fail loudly rather than be quietly emulated.

    def mkdir(self, parents: bool = False, exist_ok: bool = False) -> None:
        """A no-op, and an honest one rather than a shortcut: an object store has no
        directories. A prefix exists exactly when an object under it does, so there is
        nothing to create and nothing that could fail - which is the same fact that makes
        an empty directory unrepresentable (see the class docstring)."""

    def write_bytes(self, data: bytes) -> int:
        _fs().pipe_file(remote(self._url), bytes(data))
        _drop_cached_listings()
        return len(data)

    def write_text(self, data: str, encoding: str = "utf-8", errors=None, newline=None) -> int:
        return self.write_bytes(data.encode(encoding, errors or "strict"))

    def touch(self, mode: int = 0o666, exist_ok: bool = True) -> None:
        """An empty object. Unlike `Path.touch` this does NOT preserve existing content and
        carries no mtime semantics - every caller here writes a marker, which is empty by
        definition (gapfill's `_gapfill`), and a marker rewritten empty is still the same
        marker."""
        self.write_bytes(b"")

    def __getattr__(self, name: str):
        if name.startswith("__"):       # let copy/pickle probes fail as absence, not error
            raise AttributeError(name)
        raise NotImplementedError(
            f"{name}() is a local-filesystem operation and this data root is object "
            f"storage ({self._url}). raincheck refuses it rather than answering about the "
            f"local disk: a root that lies here makes daily.gaps() rebuild every service "
            f"day (KNOWN TRAPS). Reads go through the engines' string roots (spark s3a, "
            f"duckdb httpfs). Writes to an R2 root exist [cloud 13] but only as WHOLE "
            f"objects - write_bytes/write_text/touch, plus paths.move() and "
            f"paths.rmtree(). This operation is not one of them, and emulating it would "
            f"be inventing an atomicity story the store does not have.")
