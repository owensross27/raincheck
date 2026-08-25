"""`make publish FAMILY=<name>` (cloud ticket 09 / spec sec.9): the five payload families
onto the public static host.

The host is a NEW public bucket - `raincheck-public` - and never `raincheck-bronze`
[T18]: "public" and "the archive" must never be able to be the same mistake, which is
why the serve R2 token is scoped to that one bucket (cloud 07) and why `bucket()` below
refuses the archive name outright even if the environment hands it over. The bucket
lives OUTSIDE the cluster, so it is not cluster ingress and draws no security-group rule
- it is the named `static-host` reservation in deploy/cloud/inbound-allowlist.yaml.

The bucket IS the `web/` tree, so the page's relative paths work unchanged:

    index.html · six .js modules · app.css ·
      vendor/*                                    deploy-time      family `site`
    files/cells.geojson · headline · zones ·
      files/index.json                             per build        family `insight`
    files/live.geojson · files/meta.json            30 s             family `live`   GATED
    files/history/**                                per spine rebuild  family `history`
    docs/**                                         per Airflow run  family `docs`

**Families are explicit file lists, not directory syncs, and that is load-bearing.** The
live pair and the insight trio are written into the same `web/files/` directory by two
different writers on two different cadences: an `aws s3 sync web/files/` would publish
live.geojson on every build - straight past the MTA gate below - and would republish a
stale live pair with a fresh insight build. A family names its files.

**Three rules keep live.geojson a view rather than a feed** (spec sec.9), and each is
structural here rather than remembered:

1. CURRENT SNAPSHOT ONLY, no served history. The live family's two keys are literals, so
   no tick can ever write a second, dated copy; nothing here enables bucket versioning or
   a history lifecycle, and the bucket is created without either (see the ticket).
2. NO BULK OR PROTOBUF ENDPOINT. `PUBLISHABLE` is an allowlist of web payload suffixes,
   so a `.pb`, a `.parquet` or a tarball is refused by construction rather than by
   review - including one that appears inside a directory-tree family later.
3. MTA ATTRIBUTION ON THE PAGE - `web/index.html`, pinned by tests/test_publish.py.

**Publish order inside the live family is load-bearing too.** live.geojson goes first and
meta.json goes LAST, because the page reads freshness out of meta.json: a publisher that
died between the two would leave a fresh fleet under an older meta (the page reads
STALE - safe), where the reverse leaves a fresh meta over an old fleet (the page reads
LIVE while the city is frozen - the exact failure T14 forbids).

STALE semantics unchanged [T14]: the exporter still writes meta.json on a failed tick and
leaves live.geojson alone, and `no-cache` on both keys is what stops a CDN from serving a
frozen snapshot under a fresh-looking page long after the exporter died.

Run: make publish FAMILY=site
     make publish FAMILY=live DRY=1          (print the plan, touch nothing)
     python -m raincheck.publish --family insight --src /tmp/staged

Env: the r2-serve Secret supplies AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY /
     AWS_ENDPOINT_URL / AWS_DEFAULT_REGION=auto (cloud 07: `serviceAccountName:
     raincheck-serve` + `envFrom: [{secretRef: {name: r2-serve}}]`; the bucket is NOT in
     the Secret). RAINCHECK_R2_SERVE_BUCKET overrides the bucket name, exactly as
     scripts/r2-secrets.sh reads it.

Exit codes: 0 published · 3 the MTA gate is closed (a designed state, not a failure -
a supervisor should log it and carry on) · 1 anything else refused or broken. MEASURED:
`make publish` flattens all three to make's own rc 2, so a caller that has to tell
"gated" from "broken" runs the module (or calls `publish()`), never the make target.
"""
import argparse
import mimetypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from raincheck.paths import REPO, data_root

PUBLIC_BUCKET = "raincheck-public"      # cloud 07 annotates raincheck-serve with this
ARCHIVE_BUCKET = "raincheck-bronze"     # the one name the serve token may never hold
WEB = REPO / "web"

# Cache-Control. `no-cache` on the live pair is not politeness: a cached live.geojson is a
# frozen city served under a fresh page, which is the T14 failure with a CDN in front of
# it. Everything else is short enough that a build reaches a returning visitor the same
# day; the vendored MapLibre is version-pinned by `make vendor` and can sit for a day.
NO_CACHE = "no-cache"
BUILD_CACHE = "public, max-age=300"
RARE_CACHE = "public, max-age=86400"

# Rule 2, as an allowlist: what a static page is made of, and nothing else. A denylist
# would have to predict every bulk format anyone might stage into web/ later.
PUBLISHABLE = frozenset({".geojson", ".json", ".html", ".css", ".js", ".map", ".svg",
                         ".png", ".jpg", ".gif", ".ico", ".txt", ".woff", ".woff2"})
# mimetypes knows the rest; these two it either misses or answers inconsistently by OS.
TYPES = {".geojson": "application/geo+json", ".js": "text/javascript"}

# --- the MTA redistribution gate (spec sec.9) -------------------------------------------
# live.geojson is the one family that re-serves an MTA-derived, feed-shaped payload. The
# spec does not assert what MTA's terms say, and neither does this module: publishing it
# is gated on a HUMAN verification. Ross was asked directly on 2026-08-24 and had NOT
# verified the terms, so the gate is closed and `publish("live")` refuses with rc 3.
#
# To open it, replace None with the receipt - the date and what was actually read, e.g.
#     LIVE_TERMS_VERIFIED = "2026-09-01: MTA developer terms, sec.N - derived
#                            current-snapshot views permitted with attribution"
# The three constraints in the module docstring hold either way; the gate only decides
# whether the payload goes public at all.
LIVE_TERMS_VERIFIED: str | None = None


class Refused(Exception):
    """Something is wrong and publishing would be a mistake. rc 1."""


class GateClosed(Refused):
    """A designed, expected refusal: the MTA terms are unverified. rc 3."""


@dataclass(frozen=True)
class Family:
    cadence: str
    writer: str
    src: Callable[[], Path]
    prefix: str
    files: tuple[str, ...] = ()   # explicit, IN PUBLISH ORDER; empty means the whole tree
    cache: str = BUILD_CACHE
    gated: bool = False


FAMILIES: dict[str, Family] = {
    "live": Family(
        cadence="30 s", writer="live-export Deployment [cloud 05]",
        src=lambda: WEB / "files", prefix="files/",
        files=("live.geojson", "meta.json"),   # ORDER IS LOAD-BEARING - see the docstring
        cache=NO_CACHE, gated=True),
    "insight": Family(
        cadence="per build", writer="`make export` behind the daily build",
        src=lambda: WEB / "files", prefix="files/",
        # written all-four-or-none by one export run: cells.geojson carries per-window and
        # per-storm-hour PROPERTIES, so it is per-build output and not, as the spec table
        # had it, a deploy-time rarity. Publishing it with the page would strand the map's
        # colours a build behind its own headline numbers.
        # index.json goes LAST for the same reason meta.json does in the live pair: it is
        # the file a consumer reads to learn what the other three are and which universe
        # stamped them, so a publisher that dies mid-family must leave an OLD contract over
        # new payloads (a consumer re-reads and finds them), never a new contract over old
        # ones. It is `insight` rather than a family of its own because it is written by
        # the same run, on the same cadence, by the same writer - frontend 06.
        files=("cells.geojson", "headline.json", "zones.geojson", "index.json")),
    "docs": Family(
        cadence="per Airflow run", writer="the GX checkpoint's Data Docs task [orch 08]",
        src=lambda: data_root() / "gx" / "data_docs", prefix="docs/"),
    "history": Family(
        cadence="per spine rebuild", writer="`make export`'s static query surface [notify 05]",
        src=lambda: WEB / "files" / "history", prefix="files/history/"),
    "site": Family(
        cadence="deploy-time", writer="the operator, after `make vendor`",
        src=lambda: WEB, prefix="",
        # The page is SIX ES modules with `app.js` as the entry (frontend2 01), and every
        # one of them is a key here: the order below is LOAD order, and it is also the
        # order `tests/page.py` concatenates the `.js` keys in to read the page as one
        # text. Adding a module to the page means adding it HERE, which is what puts it
        # under the page's own rules - a module the family does not name is a module no
        # test can see. Adding a key is additive under contract.PROMISE[1]: no bump.
        files=("index.html",
               "layers.js", "freshness.js", "panel.js", "insight.js", "live.js", "app.js",
               "app.css", "vendor/maplibre-gl.js", "vendor/maplibre-gl.css"),
        cache=RARE_CACHE),
}


@dataclass(frozen=True)
class Item:
    local: Path
    key: str
    cache: str
    content_type: str


def bucket() -> str:
    """The public bucket, and the refusal that keeps it from being the archive.

    scripts/r2-secrets.sh refuses to mint a serve token against raincheck-bronze; this is
    the same refusal at publish time, because the token is not the only way to point a
    writer at a bucket."""
    name = os.environ.get("RAINCHECK_R2_SERVE_BUCKET") or PUBLIC_BUCKET
    if name == ARCHIVE_BUCKET:
        raise Refused(f"refused: the public host must never be {ARCHIVE_BUCKET} - public "
                      "and the archive are different buckets (spec sec.9)")
    return name


def content_type(path: Path) -> str:
    return TYPES.get(path.suffix) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def plan(name: str, src: Path | None = None) -> list[Item]:
    """What publishing this family would upload, in upload order. Pure: no network, no
    credentials, no s3fs import - so `--dry-run` shows exactly what would go public, and
    every rule above is testable without a bucket."""
    try:
        fam = FAMILIES[name]
    except KeyError:
        raise Refused(f"unknown family {name!r} - one of {', '.join(sorted(FAMILIES))}") from None
    if fam.gated and not LIVE_TERMS_VERIFIED:
        raise GateClosed(
            f"refused: {name} is gated on MTA's redistribution terms, which are NOT "
            "verified (spec sec.9, a precondition of shipping rather than a follow-up). "
            "Nothing was published. Open the gate by recording the verification in "
            "raincheck.publish.LIVE_TERMS_VERIFIED.")
    root = Path(src) if src else fam.src()
    if fam.files:
        paths = [root / f for f in fam.files]
        missing = [p for p in paths if not p.is_file()]
        if missing:
            # all of a family or none of it: half a live pair reads as a live city under a
            # stale meta, and half an insight build paints two eras of the same map.
            raise Refused(f"refused: {name} is incomplete - missing "
                          f"{', '.join(str(p) for p in missing)}")
    else:
        if not root.is_dir():
            raise Refused(f"refused: nothing to publish - {root} does not exist "
                          f"(written by {fam.writer}, {fam.cadence})")
        paths = sorted(p for p in root.rglob("*") if p.is_file())
        if not paths:
            raise Refused(f"refused: nothing to publish - {root} is empty "
                          f"(written by {fam.writer}, {fam.cadence})")
    for p in paths:
        if p.suffix not in PUBLISHABLE:
            raise Refused(
                f"refused: {p} is not a publishable web payload ({p.suffix or 'no suffix'}). "
                "The public host serves the map and its derived files - no bulk download "
                "and no protobuf endpoint (spec sec.9).")
    return [Item(p, fam.prefix + str(p.relative_to(root)), fam.cache, content_type(p))
            for p in paths]


def _put(item: Item, dest: str) -> None:
    """One object, overwritten in place. s3fs (already a dependency, so no aws CLI has to
    exist in the image) forwards these kwargs straight to put_object, and a file this size
    is a single put - never a per-tick multipart."""
    import s3fs

    fs = s3fs.S3FileSystem(endpoint_url=os.environ.get("AWS_ENDPOINT_URL") or None)
    fs.put_file(str(item.local), f"{dest}/{item.key}",
                ContentType=item.content_type, CacheControl=item.cache)


def publish(name: str, src: Path | None = None, dest: str | None = None,
            put: Callable[[Item, str], None] = _put) -> list[Item]:
    """Publish one family, in plan order. Returns what it uploaded.

    cloud 05's live Deployment calls `publish("live")` in-process on its 30 s tick rather
    than shelling out to the CLI - an interpreter start every 30 s buys nothing."""
    # ponytail: one object at a time, in order. Order is a correctness requirement for the
    # live pair (two files) and irrelevant for the tree families - but notify 02 measured
    # notify 05's history surface at 7,955 files, which serially is minutes per spine
    # rebuild. If that lands and hurts, parallelise the TREE families only (s3fs's
    # fs.put(..., recursive=True) takes uniform ContentType/CacheControl kwargs) and leave
    # the ordered pair alone.
    dest = dest or bucket()
    items = plan(name, src)
    for item in items:
        put(item, dest)
    return items


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", required=True, choices=sorted(FAMILIES))
    ap.add_argument("--src", type=Path, help="override where the family's writer put them")
    ap.add_argument("--bucket", help=f"override the public bucket (default {PUBLIC_BUCKET})")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, upload nothing")
    args = ap.parse_args()
    try:
        dest = args.bucket or bucket()
        items = plan(args.family, args.src)
        if not args.dry_run:
            for item in items:
                _put(item, dest)
    except GateClosed as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(3)
    except Refused as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
    verb = "would publish" if args.dry_run else "published"
    for item in items:
        print(f"{verb} s3://{dest}/{item.key}  <- {item.local}  [{item.cache}]")
    print(f"publish: {args.family} - {len(items)} object(s) to s3://{dest} "
          f"({FAMILIES[args.family].cadence}, written by {FAMILIES[args.family].writer})")


if __name__ == "__main__":
    main()
