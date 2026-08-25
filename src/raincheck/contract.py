"""`files/index.json`: the static read API's discovery document (frontend ticket 06).

The read surface has been a real API since cloud 09 — stable keys, explicit file lists,
fixed content types and cadences — and the only thing it lacked was a way to discover
itself. This module renders that: one JSON file, written by the same `make export` run
that writes the insight payloads, listing every family (key, content type, schema
pointer, cadence, writer, Cache-Control, gate) INCLUDING itself, plus the version stamps
of the universe that answered.

It is a FILE, not a component. Frontend ticket 03 priced a Cloudflare Worker against
`.scratch/frontend/research/04-worker-r2.md` and killed it on the research's own facts:
CORS is a bucket policy, rate limiting is a free-plan WAF rule, the edge cache fronts a
custom-domain bucket automatically and never fronts a Worker. The written half of this
contract is `docs/read-api-contract.md`; read that before changing anything here.

**`CONTRACT` is an integer a consumer can refuse on.** Static keys carry no `/v1/`
segment, so without it a breaking change to a key a consumer binds to is silent. It bumps
ONLY on a breaking change — and "breaking" is pinned as data rather than as a habit:
`PROMISE[CONTRACT]` is the frozen (family, key, content type) surface that version of the
contract promised, and `tests/test_publish.py` asserts it is still a SUBSET of what
`publish.FAMILIES` renders today.

  removing a key · renaming one · moving it between families · changing its content type
      -> the promise stops being a subset -> the test goes RED and demands the bump
  adding a family, adding a key                                     -> additive, no bump

That asymmetry is the whole point: a digest over the surface would bump on every
additive change, and a contract integer that moves for a reason no consumer can see
teaches consumers to ignore it.

**The version stamps come from SEAM Q and are never re-derived here** (`query.versions`,
the same ones the per-asset history payloads carry). They describe the flood universe —
ref identity, the event spine, the labels, and `score_version` on a root that publishes
F10's scores (notify ticket 03; absent, like every unpublishable value, when it does not) —
which is the history family's universe;
the insight payloads have no version seam of their own today and this document does not
invent one for them. An unresolvable stamp is an ABSENT `versions` key beside a
`versions_unresolved` reason, which is query.py's own convention: a consumer that needs a
stamp refuses on the missing key rather than reading a placeholder.

**No wall-clock stamp lives in this file, deliberately.** A writer's own timestamp inside
a payload breaks `test_re_export_is_byte_identical`, and it does not even measure what a
reader wants: a fresh file over a week-old Gold table still reads FRESH. Consumers date
every payload from its own HTTP response — `Date` − `Last-Modified`, both on the origin's
clock — which is the rule the page already follows and the reason the frozen-age trap
cannot come back through this door.
"""
import json
from pathlib import Path

from raincheck import publish, query

NAME = "index.json"                       # written into web/files/ beside the insight trio
DOC = "docs/read-api-contract.md"         # the human half of the same contract
TREE = "*"                                # a directory family serves per-file types

# The breaking-change integer. Bump it ONLY when the frozen promise below stops being a
# subset of what publish.FAMILIES renders, and add the new promise beside the old one
# rather than editing it - an edited promise is a contract nobody can audit.
CONTRACT = 1

# What each CONTRACT promises: the (family, key, content type) triples a consumer binds
# to. Keys are FULL keys (prefix included); a directory family promises its prefix, since
# its file names are the writer's and its types are per-suffix.
PROMISE: dict[int, frozenset[tuple[str, str, str]]] = {
    1: frozenset({
        ("insight", "files/cells.geojson", "application/geo+json"),
        ("insight", "files/headline.json", "application/json"),
        ("insight", "files/zones.geojson", "application/geo+json"),
        ("insight", "files/index.json", "application/json"),
        ("live", "files/live.geojson", "application/geo+json"),
        ("live", "files/meta.json", "application/json"),
        ("site", "index.html", "text/html"),
        ("site", "app.js", "text/javascript"),
        ("site", "app.css", "text/css"),
        ("site", "vendor/maplibre-gl.js", "text/javascript"),
        ("site", "vendor/maplibre-gl.css", "text/css"),
        ("history", "files/history/**", TREE),
        ("docs", "docs/**", TREE),
    }),
}

# Where a consumer reads the shape of one key. Absent for the `site` keys, which ARE their
# own schema. Trees point at their writer, since the file names are that writer's to make.
SCHEMA = {
    "files/cells.geojson": "web/export.sql (-- @@out cells.geojson)",
    "files/headline.json": "web/export.sql (-- @@out headline.json)",
    "files/zones.geojson": "web/export.sql (-- @@out zones.geojson)",
    "files/index.json": "src/raincheck/contract.py",
    "files/live.geojson": "src/raincheck/live_export.py",
    "files/meta.json": "src/raincheck/live_export.py",
    "files/flood.json": "src/raincheck/flood_panel.py",
    "files/flood-meta.json": "src/raincheck/flood_panel.py",
    "files/flood-mta.json": "src/raincheck/flood_panel.py",
    "files/flood-mta-meta.json": "src/raincheck/flood_panel.py",
    "files/history/**": "src/raincheck/query.py (events_for_asset, mode='public')",
    "docs/**": "Great Expectations Data Docs (orchestration ticket 08)",
    "showcase/**": "src/raincheck/showcase.py (orchestration ticket 13)",
}


def surface() -> frozenset[tuple[str, str, str]]:
    """The (family, key, content type) triples the publisher would ship today, derived
    from `publish.FAMILIES` - never a second copy of the family table."""
    out = set()
    for name, fam in publish.FAMILIES.items():
        if fam.files:
            out.update((name, fam.prefix + f, publish.content_type(Path(f)))
                       for f in fam.files)
        else:
            out.add((name, fam.prefix + "**", TREE))
    return frozenset(out)


def families() -> dict:
    """Every family, sorted by name; keys IN PUBLISH ORDER inside each one, because that
    order is a correctness requirement for the live pair (publish.py's docstring) and a
    consumer reading this document should see the order the writer really uses."""
    types = {(f, k): t for f, k, t in surface()}
    out = {}
    for name in sorted(publish.FAMILIES):
        fam = publish.FAMILIES[name]
        keys = [fam.prefix + f for f in fam.files] if fam.files else [fam.prefix + "**"]
        out[name] = {
            "prefix": fam.prefix,
            "tree": not fam.files,
            "keys": [query.pack(key=k, content_type=types[name, k], schema=SCHEMA.get(k))
                     for k in keys],
            "cadence": fam.cadence,
            "writer": fam.writer,
            "cache_control": fam.cache,
            "gated": fam.gated,
        }
    return out


def index(con, root: Path) -> dict:
    """The document. `con` is the caller's DuckDB connection (the exporter's), so the
    stamps are resolved once per run rather than on a connection of our own."""
    doc = {"contract": CONTRACT, "contract_doc": DOC, "families": families()}
    try:
        doc["versions"] = query.versions(con, root)
    except query.QueryError as exc:
        # absent, never null - and the operator gets the detail, which the payload does
        # not carry because it names a local path.
        print(f"index.json: {exc}", flush=True)
        doc["versions_unresolved"] = exc.reason
    return doc


def text(con, root: Path) -> str:
    """The bytes. Two runs against one root are identical: every value here is either a
    frozen constant or a content digest, and no wall clock touches it."""
    return json.dumps(index(con, root), indent=2) + "\n"
