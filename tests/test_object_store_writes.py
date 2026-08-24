"""cloud 13: a stage may WRITE an object-store root, and the ordering that makes that safe.

Cloud 12 made reads honest and left every writer refusing. What is converted here is the
WHOLE-OBJECT half - `write_bytes`/`write_text`/`touch` (one PUT, atomic by the store),
`mkdir` (a no-op, because there are no directories) and the two module functions
`paths.move` / `paths.rmtree` that a call site needs instead of `shutil`. Everything else
still raises, and the first test below is what keeps that true as sites get converted
later: it enumerates the refusing operations by name, so converting one without deciding
to is a red test rather than a silent half-write.

An object store has no rename, so atomicity is ORDERING, not locking - cloud 09's frozen
pattern: the DATA lands first, the MARKER last, and a missing marker reads UNBUILT. Both
markers this repo has are pinned here, and both pins are MUTATION-CHECKED: the test that
claims to pin the order builds the FLIPPED writer and shows it fails the same assertion,
because a green suite can be green with the logic mutated (KNOWN TRAPS)."""
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from test_gapfill import D0, fake_gcs, remote  # noqa: F401 - ticket 20's gtfsrt.io fake
from test_gapfill import DAY as GDAY

from raincheck import checks, daily, gapfill, paths, stream
from raincheck.paths import RemotePath

BUCKET = "s3a://raincheck-bronze"
DAY = "2026-08-20"
VP = {"vehicle_id": "MTA NYCT_1", "trip_id": "t1", "route_id": "B1", "latitude": 40.7,
      "longitude": -73.9, "timestamp": D0, "start_date": "20260819"}


class FakeStore:
    """An in-memory object store behind BOTH seams RemotePath uses - `_duck_glob` for
    listings and `_fs` for writes - so a whole write-then-read cycle runs with no network.

    `glob` reproduces DuckDB's semantics (`**` crosses `/`, `*` does not), which is the
    same translation `paths._pattern_re` ships; the CACHE test below pins the two against
    each other, and the fidelity of both against the real bucket is the RUN LOG's job."""

    def __init__(self, keys=()):
        self.keys = {str(k): b"" for k in keys}
        self.list_calls = 0
        self.writes = []          # every mutation, IN ORDER - the marker-last pin reads this

    # --- the listing seam ---------------------------------------------------------------
    def glob(self, pattern: str):
        self.list_calls += 1
        rx = paths._pattern_re(pattern)
        return sorted(k for k in self.keys if rx.fullmatch(k))

    # --- the write seam (the subset of s3fs paths.py calls) -----------------------------
    def pipe_file(self, key, data):
        self.keys[key] = bytes(data)
        self.writes.append(("put", key))

    def exists(self, key):
        return key in self.keys or any(k.startswith(key.rstrip("/") + "/") for k in self.keys)

    def copy(self, src, dst):
        self.keys[dst] = self.keys[src]
        self.writes.append(("copy", dst))

    def rm_file(self, key):
        self.keys.pop(key, None)
        self.writes.append(("rm", key))

    def rm(self, key, recursive=False):
        for k in [k for k in self.keys if k == key or k.startswith(key.rstrip("/") + "/")]:
            del self.keys[k]
        self.writes.append(("rmtree", key))


@pytest.fixture
def store(monkeypatch):
    s = FakeStore()
    monkeypatch.setattr(paths, "_duck_glob", s.glob)
    monkeypatch.setattr(paths, "_fs", lambda: s)
    return s


def hour_keys(kind, day, hours, name="part-vp.parquet"):
    return [f"s3://raincheck-bronze/archive/{kind}/date={day}/hour={h}/{name}" for h in hours]


# --- the refusal default, which is the thing that must not erode ------------------------

@pytest.mark.parametrize("op", [
    "replace", "rename",          # an object store HAS no rename - the atomicity problem itself
    "unlink", "rmdir", "iterdir", "read_text", "read_bytes", "stat", "open",
    "is_dir", "is_file", "resolve", "relative_to", "with_name", "samefile"])
def test_the_unconverted_operations_still_refuse_loudly(op):
    """Cloud 12's default, kept. A writer that reaches for one of these has a POSIX
    atomicity story (stage-then-rename) that the store cannot honour, so it must fail
    where it stands rather than be quietly emulated into a half-write."""
    with pytest.raises(NotImplementedError, match="object storage"):
        getattr(RemotePath(BUCKET) / "live", op)()


def test_the_converted_operations_are_exactly_the_whole_object_ones(store):
    """The other half of the pin above: what cloud 13 DID convert, named, so that widening
    it is a deliberate edit here and not a drive-by."""
    p = RemotePath(BUCKET) / "checks" / "check=gapcheck" / "run=1.jsonl"
    assert p.mkdir(parents=True, exist_ok=True) is None      # no directories to create
    assert p.write_text("a\n") == 2
    assert store.keys["s3://raincheck-bronze/checks/check=gapcheck/run=1.jsonl"] == b"a\n"
    assert p.write_bytes(b"xyz") == 3                        # one PUT, overwritten whole
    (p.parent / "_marker").touch()
    assert store.exists("s3://raincheck-bronze/checks/check=gapcheck/_marker")


def test_move_is_a_server_side_copy_and_never_crosses_the_boundary(store, tmp_path):
    src = RemotePath(BUCKET) / ".staging" / "events_2026-08-20" / "part-abc.parquet"
    dst = RemotePath(BUCKET) / "silver" / "events" / f"service_date={DAY}" / daily.PART
    src.write_bytes(b"rows")
    paths.move(src, dst)
    assert store.keys[str(paths.remote(dst))] == b"rows"     # the bytes never left the store
    assert str(paths.remote(src)) not in store.keys
    assert ("copy", str(paths.remote(dst))) in store.writes
    # a half-converted root would otherwise silently download-and-upload, or worse
    with pytest.raises(ValueError, match="not a move"):
        paths.move(tmp_path / "x", dst)


def test_rmtree_sweeps_a_prefix_and_rmdir_if_empty_is_a_no_op_out_there(store, tmp_path):
    staging = RemotePath(BUCKET) / ".staging" / "events_2026-08-20"
    (staging / "part-abc.parquet").write_bytes(b"x")
    (staging / "_SUCCESS").write_bytes(b"")
    paths.rmtree(staging)
    assert not any(k.startswith(str(paths.remote(staging))) for k in store.keys)
    paths.rmtree(staging)                                    # already gone is the outcome asked for
    # nothing to remove: an empty prefix cannot exist, so the day died with its last hour
    assert paths.rmdir_if_empty(RemotePath(BUCKET) / "live" / "vp" / "date=2026-08-01") is None
    d = tmp_path / "empty"
    d.mkdir()
    paths.rmdir_if_empty(d)
    assert not d.exists()
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "keep").write_text("x")
    paths.rmdir_if_empty(tmp_path / "full")                  # a non-empty day stays
    assert (tmp_path / "full" / "keep").exists()


# --- DATA FIRST, MARKER LAST (cloud 09's frozen pattern) --------------------------------

def test_the_real_fill_day_writes_every_marker_after_every_part(store, fake_gcs):
    """The REAL `gapfill.fill_day`, driven onto an object-store root through the same
    gtfsrt.io fake ticket 20's own tests use - not a re-implementation of its two writes,
    because a pin that re-states the code cannot notice the code changing.

    What is asserted is the store's own write log: every part-gapfill object is PUT before
    any `_gapfill` marker is. Flipping the two statements in fill_day turns this red -
    mutation round in the RUN LOG entry, run on a copied source tree."""
    remote(fake_gcs, "vehicle_positions", gapfill.FEEDS["vp"], GDAY, [
        (D0 + 10, D0 + 9, [VP]),              # hour 00
        (D0 + 7300, D0 + 7299, [VP]),         # hour 02
    ])
    gapfill.fill_day(RemotePath(BUCKET), "vp", GDAY)

    kinds = [("marker" if k.endswith("_gapfill") else "part") for _, k in store.writes]
    assert kinds.count("part") == 2 and kinds.count("marker") == 2, store.writes
    assert kinds == ["part", "part", "marker", "marker"], (
        "a marker written before the last part would retire an hour a crash never filled")
    # and the parts really are complete objects, not placeholders
    hour0 = f"s3://raincheck-bronze/archive/vp/date={GDAY}/hour=00/part-gapfill-vp.parquet"
    assert pq.read_table(pa.BufferReader(store.keys[hour0])).num_rows == 1


def test_an_interrupted_fill_reads_as_unbuilt_and_a_marker_first_fill_does_not(store):
    """The case the ordering exists for. Data present + marker absent = still missing, so
    the next run refills; if the marker had gone first, the crash would have RETIRED an
    hour that was never filled - silently, and forever."""
    date_dir = RemotePath(BUCKET) / "archive" / "vp" / f"date={DAY}"
    store.keys.update({k: b"" for k in hour_keys("vp", DAY, [f"{h:02d}" for h in range(24)])})
    for k in list(store.keys):
        if "hour=05" in k:
            del store.keys[k]
    assert gapfill.missing_hours(date_dir) == ["05"]

    (date_dir / "hour=05" / "part-gapfill-vp.parquet").write_bytes(b"rows")   # ... crash here
    assert gapfill.missing_hours(date_dir) == ["05"], "gapfill debris must not retire the hour"

    (date_dir / "hour=05" / "_gapfill").touch()
    assert gapfill.missing_hours(date_dir) == []


def test_a_silver_partition_is_published_by_one_copy_after_its_staging_is_complete(store):
    """`events.one_file`'s ordering, which is the same pattern with the DATA as its own
    marker: daily.gaps() tests for silver/<t>/service_date=D/part-00000.parquet and never
    looks under .staging/, so the partition is invisible until the ONE copy that publishes
    it. Interrupted before that copy, the day reads UNBUILT and rebuilds."""
    root = RemotePath(BUCKET)
    store.keys.update({k: b"" for k in hour_keys("vp", DAY, [f"{h:02d}" for h in range(24)])
                       + hour_keys("vp", "2026-08-21", [f"{h:02d}" for h in range(24)])})
    built = [f"{root}/silver/{t}/service_date={DAY}/{daily.PART}" for t in daily.SILVER]

    from datetime import date
    closed = date.fromisoformat(DAY)
    assert daily.gaps(root, closed) == [DAY]                    # nothing built yet

    # Spark's staging write: every byte of the partition is on the store already ...
    staging = root / ".staging" / f"events_{DAY}"
    (staging / "part-00000-abc.parquet").write_bytes(b"rows")
    assert daily.gaps(root, closed) == [DAY], "staging must not read as built"

    for out in built:                                           # ... and now the two copies
        paths.move(staging / "part-00000-abc.parquet", paths.as_root(out))
        (staging / "part-00000-abc.parquet").write_bytes(b"rows")
    paths.rmtree(staging)
    assert daily.gaps(root, closed) == []                       # the day is done

    # cleanup is LAST and cannot un-publish: staging debris left behind changes nothing
    (staging / "part-00000-abc.parquet").write_bytes(b"rows")
    assert daily.gaps(root, closed) == []


def test_prune_drops_old_live_hours_on_a_remote_root(store):
    """The written decision on `prune`: CONVERTED, because stream.py already writes live/
    over s3a and retention that only ran on the Mac would let an R2 live/ grow forever.
    The horizon compare was always on NAMES; only the two POSIX calls moved."""
    from datetime import datetime, timezone
    root = RemotePath(BUCKET)
    for kind in ("vp", "tu"):
        for day, hour in (("2026-08-18", "00"), ("2026-08-20", "12")):
            store.keys[f"{root.__str__().replace('s3a', 's3')}/live/{kind}/date={day}"
                       f"/hour={hour}/part-0.parquet"] = b"x"
    stream.prune(root, now=datetime(2026, 8, 20, 18, tzinfo=timezone.utc))
    left = sorted(k for k in store.keys if "/live/" in k)
    assert all("date=2026-08-20" in k for k in left) and len(left) == 2, left


def test_checks_batches_land_on_a_remote_root_unchanged(store):
    """checks.write needed NO edit - it was already Path-method-only (mkdir + write_text),
    so converting those two on RemotePath converted the whole check surface with it."""
    from datetime import datetime, timezone
    rows = [checks.Row("gapcheck", f"vp {DAY}", checks.OK, "", {
        "kind": "vp", "day": DAY, "hours_held": 24, "fillable": 0, "dead": 0,
        "stale_dead": ""})]
    out = checks.write(RemotePath(BUCKET), "gapcheck", rows,
                       gapfill.CHECK_COLUMNS["gapcheck"],
                       at=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc))
    assert str(out).endswith("checks/check=gapcheck/run=20260824T120000Z.jsonl")
    assert b'"outcome": "ok"' in store.keys[str(paths.remote(out))]


# --- the listing bill -------------------------------------------------------------------

def test_the_cached_listing_answers_what_a_fresh_listing_would_in_one_call(store):
    """MEASURED against the real bucket, daily.gaps() over its 14-day window is 1,960 store
    list calls / 231.1 s; inside `cached_listing` it is ONE call / 22.4 s for the identical
    answer (RUN LOG, cloud 13). Here the same equality is asserted in-suite: same days out,
    and the call count collapses to one."""
    from datetime import date
    root = RemotePath(BUCKET)
    days = [DAY, "2026-08-21"]
    store.keys.update({k: b"" for d in days
                       for k in hour_keys("vp", d, [f"{h:02d}" for h in range(24)])})
    closed = date.fromisoformat(DAY)

    cached = daily.gaps(root, closed)            # gaps() opens the scope itself
    n_cached = store.list_calls
    assert n_cached == 1, "gaps() must pay ONE recursive listing, not one per predicate"

    store.list_calls = 0                         # the same scan with the scope removed
    from contextlib import nullcontext
    monkey = paths.cached_listing
    paths.cached_listing = lambda root: nullcontext()
    try:
        uncached = daily.gaps(root, closed)
    finally:
        paths.cached_listing = monkey
    assert cached == uncached == [DAY]            # IDENTICAL answer, which is the whole point
    assert store.list_calls > 100, store.list_calls  # ... and the loop shape is what costs


def test_a_write_inside_an_open_scope_drops_the_cache(store):
    """Deliberately not write-through: a write invalidates and the next predicate re-lists.
    Three lines instead of a coherency protocol - and it keeps gapfill's scan-to-write race
    check able to see an EXTERNAL writer, which is the one thing a cache here must not
    break."""
    root = RemotePath(BUCKET)
    store.keys.update({k: b"" for k in hour_keys("vp", DAY, ["00"])})
    hour = root / "archive" / "vp" / f"date={DAY}" / "hour=01"
    with paths.cached_listing(root):
        assert not hour.exists()
        assert store.list_calls == 1
        (hour / "part-gapfill-vp.parquet").write_bytes(b"x")
        assert hour.exists(), "a stale cache would still say no"
        assert store.list_calls == 2


def test_the_pattern_translation_matches_duckdb_glob_semantics():
    """`**` crosses `/`, `*` and `?` do not - the rule the cache is only correct under.
    Verified against the REAL bucket too (RUN LOG: 31 patterns daily.gaps() issues,
    cached vs fresh, 0 mismatches, 14 of them non-empty)."""
    keys = ["s3://b/a/x.parquet", "s3://b/a/c/x.parquet", "s3://b/a/c/d/x.parquet"]

    def m(pattern):
        rx = paths._pattern_re(pattern)
        return [k for k in keys if rx.fullmatch(k)]

    assert m("s3://b/a/*.parquet") == ["s3://b/a/x.parquet"]
    assert m("s3://b/a/**/x.parquet") == keys                  # ** includes zero segments
    assert m("s3://b/a/*/x.parquet") == ["s3://b/a/c/x.parquet"]
    assert m("s3://b/a/**") == keys                            # the prefix form exists() uses
    assert m("s3://b/a/?/x.parquet") == ["s3://b/a/c/x.parquet"]
    assert m("s3://b/nope/**") == []                           # and it can say no
