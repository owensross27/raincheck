"""`ref/` delivery to a pod (cloud ticket 12, second half).

`<root>/ref` is the root of the whole stage graph - every stage but `make warm` dies
without it (KNOWN TRAPS) - and it is 27 MB of gitignored parquet that CANNOT be rebuilt
while `make picks` is 401-blocked. So it has to reach the cluster somehow, and the two
candidates were: bake it into the image at build time, or pull it from the cold bucket.

IT IS A PULL, for one reason that is not taste: the image is tagged by GIT SHA and its
tags are immutable, so a 27 MB dataset that lives in no commit would make two builds of
the same sha differ in content. The Dockerfile says the same thing about credentials and
the data root - "neither a credential nor a data root is baked in". `ref` is data.

The pod-visible path is the SAME `<root>/ref` the Mac uses; nothing here introduces a
second path abstraction. A pod whose root is ALREADY the object store has ref under it by
definition, so this exits 0 and says so - the same initContainer is correct for both root
kinds.

`ref/src` is skipped by default: it is the raw GTFS zips `ref` is BUILT from, 23 of the
27 MB, and no consumer outside `ref.py` reads it. Everything actually read by a pod
(assets, cell_pixel, cell_zone, cells, zones, calendar, grids, picks) is ~4 MB. The table
list is READ FROM THE BUCKET, never declared here, so a new ref table travels on its own.

Run: python -m raincheck.refpull [TABLE ...]
Env: RAINCHECK_ARCHIVE_ROOT (destination root), RAINCHECK_COLD_BUCKET (source bucket),
     AWS_* from the r2-build Secret.
"""
import os
import sys

from raincheck.paths import as_root, data_root, remote

SKIP = ("src",)


def fs():
    """s3fs, exactly as publish.py reaches R2 - already a dependency, so no aws CLI has to
    exist in the image and no credential is ever an argument."""
    import s3fs

    return s3fs.S3FileSystem(endpoint_url=os.environ.get("AWS_ENDPOINT_URL") or None)


def tables(f, bucket: str) -> list[str]:
    """The ref tables the bucket holds, minus SKIP. Read off the store, never a hardcoded
    list, so a table added by a later `make ref` arrives without an edit here."""
    names = sorted(p.rstrip("/").rsplit("/", 1)[-1] for p in f.ls(f"{bucket}/ref"))
    return [n for n in names if n not in SKIP]


def pull(root, bucket: str, want: list[str] | None = None) -> int:
    """Mirror s3://<bucket>/ref/<table> into <root>/ref/<table>. Idempotent: a table
    already present locally is left alone (a long-lived pod restarting its container must
    not re-download), and what was skipped is printed rather than assumed."""
    root = as_root(root)
    if remote(root):
        print(f"refpull: root is already object storage ({root}) - ref/ is at {root}/ref, "
              f"nothing to deliver", flush=True)
        return 0
    f = fs()
    names = want or tables(f, bucket)
    dest = root / "ref"
    dest.mkdir(parents=True, exist_ok=True)
    got, had = [], []
    for name in names:
        out = dest / name
        if out.is_dir() and any(out.iterdir()):
            had.append(name)
            continue
        f.get(f"{bucket}/ref/{name}", f"{out}/", recursive=True)
        got.append(name)
    print(f"refpull: {len(got)} table(s) pulled into {dest} ({', '.join(got) or '-'}); "
          f"{len(had)} already present ({', '.join(had) or '-'}); "
          f"skipped {', '.join(SKIP)} (build-time GTFS sources, no pod reads them)",
          flush=True)
    return 0


def main(argv: list[str]) -> int:
    bucket = os.environ.get("RAINCHECK_COLD_BUCKET") or ""
    if not bucket:
        print("refpull: set RAINCHECK_COLD_BUCKET (the private archive bucket holding ref/)",
              file=sys.stderr)
        return 2
    return pull(data_root(), bucket, argv or None)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
