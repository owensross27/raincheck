"""cloud 12: the data root may be an object store, and it may never LIE about the local disk.

`Path("s3a://bucket/x")` collapses to the relative path `s3a:/bucket/x`, so the tempting
fix - a Path subclass that re-expands the scheme on `__str__` - inherits `.exists()`,
`.glob()` and `.rglob()` from Path and keeps answering about whatever sits under the
current directory. `daily.gaps()` is where that bites: it decides which service days are
already built by asking the filesystem, so a lying root rebuilds the lot in silence.

The pin below is mutation-checked in the last test: the barred subclass is constructed
here and shown to give the WRONG answer against the same fixtures, so these assertions
cannot pass by being vacuous."""
import re
from datetime import date
from pathlib import Path

import pytest

from raincheck import daily, duck, parity, paths
from raincheck.paths import RemotePath, as_root, data_root, remote

BUCKET = "s3a://raincheck-bronze"
DAY = "2026-08-20"
NEXT = "2026-08-21"


def fake_store(keys):
    """`_store_glob` over an in-memory key list - the seam RemotePath reaches R2 through."""
    def _glob(pattern):
        rx = (re.escape(pattern).replace(r"\*\*/", "(?:.*/)?")
              .replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]"))
        return sorted(k for k in keys if re.fullmatch(rx, k))
    return _glob


def bronze_keys(*days):
    return [f"s3://raincheck-bronze/archive/vp/date={d}/hour={h:02d}/part-vp.parquet"
            for d in days for h in range(24)]


def silver_keys(day):
    return [f"s3://raincheck-bronze/silver/{t}/service_date={day}/{daily.PART}"
            for t in daily.SILVER]


def decoy(tmp_path, silver: bool):
    """The LOCAL tree a lying root would read: `Path("s3a://raincheck-bronze")` is the
    RELATIVE path `s3a:/raincheck-bronze`, so it resolves under the current directory."""
    base = tmp_path / "s3a:" / "raincheck-bronze"
    for day in (DAY, NEXT):
        for h in range(24):
            d = base / "archive" / "vp" / f"date={day}" / f"hour={h:02d}"
            d.mkdir(parents=True, exist_ok=True)
            (d / "part-vp.parquet").write_bytes(b"")
    for t in daily.SILVER:
        p = base / "silver" / t / f"service_date={DAY}" / daily.PART
        p.parent.mkdir(parents=True, exist_ok=True)
        if silver:
            p.write_bytes(b"")
    return base


# --- the local case is untouched --------------------------------------------------------

def test_a_local_root_is_still_a_plain_path(tmp_path, monkeypatch):
    monkeypatch.delenv("RAINCHECK_ARCHIVE_ROOT", raising=False)
    assert isinstance(data_root(), Path) and data_root() == paths.REPO / "data"
    monkeypatch.setenv("RAINCHECK_ARCHIVE_ROOT", str(tmp_path))
    assert isinstance(data_root(), Path) and data_root() == tmp_path
    assert (data_root() / "nope").exists() is False  # real disk, real answer


def test_remote_recognises_both_spellings_and_nothing_else():
    assert remote("s3://b/silver/events") == "s3://b/silver/events"
    assert remote("s3a://b/silver/events/") == "s3://b/silver/events"
    assert remote(Path("/data/silver/events")) is None
    assert remote("/data/s3a://not-a-scheme") is None
    assert parity.remote is remote          # one definition, shared with the parity gate


# --- the remote case: joins and strings work, POSIX refuses ------------------------------

def test_the_scheme_survives_joining_and_stringifying(monkeypatch):
    monkeypatch.setenv("RAINCHECK_ARCHIVE_ROOT", BUCKET)
    root = data_root()
    assert isinstance(root, RemotePath)
    assert str(root / "silver" / "events") == "s3a://raincheck-bronze/silver/events"
    assert f"{root.joinpath('gold', 'flood_matrix')}/**/*.parquet" == (
        "s3a://raincheck-bronze/gold/flood_matrix/**/*.parquet")
    assert (root / "silver" / "events").name == "events"
    assert (root / "silver" / "events").parent == root / "silver"
    # ... and this is what a plain Path would have made of the same root
    assert str(Path(BUCKET)) == "s3a:/raincheck-bronze"


def test_as_root_is_a_drop_in_for_Path_at_a_join_site(tmp_path):
    assert as_root(str(tmp_path)) == tmp_path and isinstance(as_root(tmp_path), Path)
    assert as_root(BUCKET) == RemotePath(BUCKET)
    assert as_root(RemotePath(BUCKET)) == RemotePath(BUCKET)


@pytest.mark.parametrize("op", [
    "mkdir", "touch", "unlink", "rmdir", "replace", "rename", "is_dir", "is_file",
    "iterdir", "read_text", "write_text", "read_bytes", "write_bytes", "stat", "open",
    "resolve", "relative_to", "with_name", "samefile"])
def test_every_other_path_operation_refuses_loudly(op):
    """The default is refusal, not a local answer: anything not implemented on RemotePath
    raises, so a POSIX-only stage (precip_live's mkdir/replace/rmtree, events' one_file)
    fails at its first write instead of half-writing somewhere nobody looks."""
    with pytest.raises(NotImplementedError, match="object storage"):
        getattr(RemotePath(BUCKET) / "live", op)()


def test_a_wildcard_free_glob_is_refused_because_duckdb_would_not_check_it():
    """Measured 2026-08-24: DuckDB's glob('s3://bucket/does-not-exist') returns the path
    VERBATIM without touching the store, so an existence test written that way says yes to
    everything. exists() therefore lists the PARENT and tests membership."""
    with pytest.raises(ValueError, match="wildcard-free"):
        paths._store_glob("s3://raincheck-bronze/archive")


# --- the store answers, the disk does not ------------------------------------------------

def test_exists_and_glob_read_the_store(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    decoy(tmp_path, silver=True)            # a full local tree that must never be consulted
    monkeypatch.setattr(paths, "_store_glob", fake_store(bronze_keys(DAY)))
    root = RemotePath(BUCKET)
    assert (root / "archive" / "vp" / f"date={DAY}").exists()
    assert not (root / "silver" / "events").exists()       # on disk it is right there
    hours = list((root / "archive" / "vp" / f"date={DAY}").glob("hour=*"))
    assert [h.name for h in hours] == [f"hour={h:02d}" for h in range(24)]
    assert hours[0] == root / "archive" / "vp" / f"date={DAY}" / "hour=00"
    parts = list((root / "archive" / "vp" / f"date={DAY}").glob("hour=*/*.parquet"))
    assert len(parts) == 24 and parts[0].name == "part-vp.parquet"
    assert len(list((root / "archive").rglob("*.parquet"))) == 24
    assert list((root / "archive").rglob("*.orc")) == []


def test_exists_is_false_for_an_object_the_store_does_not_hold(monkeypatch):
    monkeypatch.setattr(paths, "_store_glob", fake_store(bronze_keys(DAY)))
    part = RemotePath(BUCKET) / "archive" / "vp" / f"date={DAY}" / "hour=00" / "part-vp.parquet"
    assert part.exists()
    assert not (part.parent / "part-gapfill-vp.parquet").exists()
    assert not (RemotePath(BUCKET) / "ref" / "assets").exists()


# --- the trap itself, and the mutation check ---------------------------------------------

def test_daily_gaps_answers_from_the_store_never_from_the_local_disk(monkeypatch, tmp_path):
    """Both directions, against a local decoy that says the opposite each time. Either
    assertion alone could pass by accident; together they can only pass if gaps() read
    the store."""
    monkeypatch.chdir(tmp_path)
    root = RemotePath(BUCKET)

    decoy(tmp_path, silver=False)           # disk: DAY is UNBUILT -> a liar returns [DAY]
    monkeypatch.setattr(paths, "_store_glob",
                        fake_store(bronze_keys(DAY, NEXT) + silver_keys(DAY)))
    assert daily.gaps(root, date.fromisoformat(DAY)) == []

    decoy(tmp_path, silver=True)            # disk: DAY is BUILT -> a liar returns []
    monkeypatch.setattr(paths, "_store_glob", fake_store(bronze_keys(DAY, NEXT)))
    assert daily.gaps(root, date.fromisoformat(DAY)) == [DAY]


def test_the_barred_path_subclass_fails_the_pin_above(monkeypatch, tmp_path):
    """THE MUTATION CHECK. The fix KNOWN TRAPS bars, built here and run against the same
    fixtures: `.exists()` and `.glob()` come from Path, so both answers come off the local
    disk and both are the opposite of the store's. If this ever stops failing, the test
    above has stopped discriminating."""
    class Barred(Path):
        def __str__(self):
            return super().__str__().replace("s3a:/", "s3a://", 1)

    monkeypatch.chdir(tmp_path)
    liar = Barred(BUCKET)
    assert str(liar / "silver") == "s3a://raincheck-bronze/silver"   # it does re-expand
    assert isinstance(liar / "silver", Barred)                       # and it propagates

    decoy(tmp_path, silver=False)
    monkeypatch.setattr(paths, "_store_glob",
                        fake_store(bronze_keys(DAY, NEXT) + silver_keys(DAY)))
    assert daily.gaps(liar, date.fromisoformat(DAY)) == [DAY]        # store said []

    decoy(tmp_path, silver=True)
    monkeypatch.setattr(paths, "_store_glob", fake_store(bronze_keys(DAY, NEXT)))
    assert daily.gaps(liar, date.fromisoformat(DAY)) == []           # store said [DAY]


# --- the connection the stages read through ----------------------------------------------

def test_duck_connect_configures_r2_only_when_the_endpoint_is_set(monkeypatch):
    """One switch, the same one spark.py's s3a branch reads, so a DuckDB stage follows an
    s3a:// root without a fork and the Mac's default behaviour is untouched."""
    called = []
    monkeypatch.setattr(duck, "r2", lambda con: called.append(con))
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    duck.connect()
    assert called == []
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://acct.r2.cloudflarestorage.com")
    duck.connect()
    assert len(called) == 1
    parity.connect("/data/silver/events")      # a local root never needs httpfs...
    assert len(called) == 2                    # (the endpoint is set, so connect() did it)
    parity.connect(BUCKET)                     # ...a remote one asks for it explicitly
    assert len(called) == 4
