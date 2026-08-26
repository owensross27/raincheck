"""`make export`'s static history surface (notify ticket 05 / spec section 3; SEAM Q).

The page answers "has this stop ever flooded?" from static files alone: ONE manifest that
paints every asset carrying a flood record, and one file per listed asset holding that
asset's dated history and its published exposure. No server and no query at request time -
an asset ABSENT from the manifest is "no events on record" without any request at all.

**This module is a RENDERER over SEAM Q and holds no join of its own.** F05 owns the
attachment and `events_for_asset` owns the complex rollup; both reach here only through
`raincheck.query`, in `public` mode, exactly as a hosted MCP client would ask:

  the manifest   `assets_in_area` in `CELL_CAP`-sized batches over every Cell in the
                 registry. It is a `public` answer already - it ships F05's attachment
                 COUNTS, and a count is not a row - and its `n_events` is pinned to equal
                 what `events_for_asset` returns for the same id, complex rollup included.
  each file      `events_for_asset` + `exposure_of`, both `public`, MERGED. The two
                 return an IDENTICAL `asset` block and identical stamps for one id, so one
                 file holds both without reconciling anything.

**The batched sweep is COMPLETE by measurement, not by hope.** Every registry row carries
a `cell` and every distinct `cell` value has its own `cell:` registry row (4,113 = 4,113,
measured on the real root 2026-08-26), so the union over those Cells is the whole registry.
Checked the other way too: the manifest this route builds is EQUAL, asset for asset and
count for count, to the same question asked as one direct join - which is the only reason
to trust a seam route over a join nobody can see.

**The one fact the seam does not carry is a COORDINATE**, and a payload with no
coordinates cannot be a map layer (KNOWN TRAPS - this repo has now written that defect
three times). So lon/lat come from a flat projection of `ref/assets`: a registry lookup
resolved in python, never a second attachment rule. Putting them on `assets_in_area`
itself is the real fix and it is FILED FORWARD rather than taken here - `query.QUERIES`
is frozen at four for wave 7 (notify 06 wraps exactly those four, and the shape of an
`assets_in_area` row is a MUST on its box).

**A `cell`-kind asset has NO name** (`ref/assets` names only stops, stations and
complexes) and the most-flooded assets are exactly the Cells, so `name` is an ABSENT key
on 1,276 of them rather than a null that renders as the literal word "null".

**Re-export is byte-identical**, which is what makes these files evidence: every aggregate
is ordered inside the seam, the sweep is re-sorted by `asset_id` so batch order cannot
leak, coordinates are rounded EXPLICITLY to `COORD_DP`, and **no wall clock touches any
file**. A writer's own timestamp would break that identity and would not even measure what
a reader wants - the page dates every payload from its own HTTP response (`Date` minus
`Last-Modified`, same origin, so both are the origin's clock).

Published values pass through UNROUNDED, deliberately: `score_index` / `score_ref` /
`score_severe` / `surge_margin_ft` are F10's numbers and rounding them here would publish
a different value than the table holds. The only numbers this module makes are the
coordinates, and those it rounds.

Written under `web/files/history/`, where `publish --family history` reads it and sends
the tree to `files/history/**`. That prefix is what `contract.PROMISE[1]` freezes, so the
file names inside it are this writer's to make and no `contract.CONTRACT` bump is owed -
resharding later (by kind, by H3 prefix) is additive and touches this renderer alone.

**KNOWN CEILING, priced and NOT taken here:** `publish` PUTs one object at a time, so this
tree is thousands of serial PUTs per spine rebuild. The fix is to parallelise the TREE
families in `raincheck.publish` (its own `ponytail:` note says so) - not to reshape the
query and not to shard this tree, which would move the same object count around. Not done
here because `publish.py` has one editor this wave and it is not this ticket.
"""
import json
import shutil
from pathlib import Path

from raincheck import query

PUBLIC = query.MODES[0]
DIR = "history"                    # under web/files/, matching publish.FAMILIES["history"]
MANIFEST = "manifest.geojson"      # frozen by frontend 05: the page's LAYERS table reads it
STAGING = ".staging"               # sibling of DIR; swapped in whole, or not at all
COORD_DP = 5                       # ~1.1 m, the precision web/export.sql publishes geometry at
# The comparison point the spec names: the insight surface as shipped, three files,
# MEASURED 2026-08-23. No ticket may take the DuckDB-over-R2 escalation path without
# putting this tree's numbers beside it.
INSIGHT_BYTES = 2_606_072
QUERIES = ("events_for_asset", "exposure_of")   # what each per-asset file is a merge of

# Compact, because these are machine-read payloads whose SIZE is this ticket's subject: a
# manifest the page parses on load and a file it fetches on one click. `index.json` is the
# document a human reads and it stays indented.
JSON = dict(separators=(",", ":"), sort_keys=False, allow_nan=False)


def registry(con, root: Path) -> tuple[list[int], dict[str, tuple[float, float]]]:
    """(every Cell in the registry, asset_id -> lon/lat). ONE read, two uses: the Cell set
    the sweep walks and the coordinates the seam does not carry. No join - `assets_in_area`
    answers which assets have a history, this answers only where they are."""
    query.view(con, root, "ref", "assets", name="assets", columns=query.ASSET_COLUMNS)
    cells = [c for (c,) in con.execute(
        "SELECT cell FROM assets WHERE kind = 'cell' ORDER BY cell").fetchall()]
    coords = {a: (lon, lat) for a, lon, lat in con.execute(
        "SELECT asset_id, lon, lat FROM assets").fetchall()}
    return cells, coords


def flooded(con, root: Path, cells: list[int]) -> list[dict]:
    """Every asset with at least one attached event, through the seam, ordered by id.

    `CELL_CAP` is the seam's own cap and this walks it rather than around it - the whole
    city is 65 bounded `public` calls, ~1 s. Re-sorted by `asset_id` at the end because
    batch order is an accident of the Cell list and a manifest that reordered between two
    runs would not be byte-identical."""
    out = []
    for i in range(0, len(cells), query.CELL_CAP):
        batch = [query.cell_id(c) for c in cells[i:i + query.CELL_CAP]]
        answer = query.QUERIES["assets_in_area"](con, root, {"cells": batch}, PUBLIC)
        out += [a for a in answer["assets"] if a["n_events"]]
    return sorted(out, key=lambda a: a["asset_id"])


def feature(asset: dict, coords: dict) -> dict:
    """One manifest Feature. THE KEY SET IS SIX: asset_id, kind, n_events, lon, lat, name -
    the coordinates as the Point geometry (which is what makes it a layer at all) and the
    other four as properties. `name` is ABSENT on a Cell, never null; the page falls back
    to the `asset_id`, which it must print anyway because two bus stops metres apart can
    share a name."""
    lon, lat = coords[asset["asset_id"]]
    return {"type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [round(lon, COORD_DP), round(lat, COORD_DP)]},
            "properties": query.pack(asset_id=asset["asset_id"], kind=asset["kind"],
                                     n_events=asset["n_events"], name=asset.get("name"))}


def manifest(assets: list[dict], coords: dict) -> str:
    return json.dumps({"type": "FeatureCollection",
                       "features": [feature(a, coords) for a in assets]}, **JSON) + "\n"


def payload(con, root: Path, asset_id: str, stamps: dict) -> dict:
    """One asset's file: its history and its exposure, merged.

    The envelope is added HERE rather than by `query()`, which is the whole cost fix - that
    entry point opens a connection and re-resolves the stamps on every call, and this makes
    two calls per asset. The registry functions take the caller's warm connection and the
    stamps are resolved ONCE for the run.

    **An entrance carries a history and NO score** - its score exists only inside its
    complex's max, so `exposure_of` refuses it by name. The file keeps the history, drops
    the `exposure` key entirely (absent, never null - a zero score would be a lie) and
    carries the refusal's own `ask` so a reader can follow it to the complex that does
    answer. `ask` is itself absent where there is nothing to ask (a ref Cell outside F10's
    fit set has no parent)."""
    doc = {"queries": list(QUERIES), "mode": PUBLIC,
           **query.QUERIES["events_for_asset"](con, root, {"asset_id": asset_id}, PUBLIC)}
    try:
        doc["exposure"] = query.QUERIES["exposure_of"](
            con, root, {"asset_id": asset_id}, PUBLIC)["exposure"]
    except query.QueryError as exc:
        doc["exposure_unavailable"] = query.pack(reason=exc.reason,
                                                 ask=exc.detail.get("ask"))
    doc["versions"] = stamps
    return doc


def build(con, root: Path, out_dir: Path) -> dict:
    """Write the whole surface, or none of it. Returns the size report.

    Staged into a sibling directory and swapped in one `replace`, so a run that dies part
    way leaves the PREVIOUS tree whole rather than a manifest naming files that are not
    there. That is the same all-or-none rule the insight trio already has, at tree grain;
    `web/` is always the repo's own POSIX tree, so a directory rename is available here in
    a way it is not on an object-store data root.

    A root with no flood universe writes NOTHING and says so: `make export` runs against
    fixture roots that hold no `ref/assets` at all, and refusing the whole export over an
    absent history tree would be a worse answer than an absent history tree."""
    try:
        stamps = query.versions(con, root)
        cells, coords = registry(con, root)
        assets = flooded(con, root, cells)
    except query.QueryError as exc:
        print(f"history: not written - {exc}", flush=True)
        return {}

    staging = out_dir.with_name(out_dir.name + STAGING)
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    (staging / MANIFEST).write_text(manifest(assets, coords))
    for a in assets:
        (staging / f"{a['asset_id']}.json").write_text(
            json.dumps(payload(con, root, a["asset_id"], stamps), **JSON) + "\n")

    shutil.rmtree(out_dir, ignore_errors=True)
    staging.replace(out_dir)
    sizes = {p.name: p.stat().st_size for p in sorted(out_dir.iterdir())}
    return {"assets": len(assets), "files": len(sizes), "bytes": sum(sizes.values()),
            "manifest_bytes": sizes[MANIFEST],
            "largest": max(sizes.items(), key=lambda kv: (kv[1], kv[0]))}


def report(rep: dict) -> None:
    """The number the spec says to decide the static-vs-DuckDB question on: file COUNT,
    total bytes and the largest single file, against the shipped insight surface. An empty
    report means the tree was not written, and `build` has already said why."""
    if not rep:
        return
    name, size = rep["largest"]
    print(f"  {DIR}/: {rep['files']} files, {rep['bytes']:,} bytes "
          f"({rep['bytes'] / INSIGHT_BYTES:.1f}x the {INSIGHT_BYTES:,}-byte insight "
          f"surface), manifest {rep['manifest_bytes']:,} B, largest {name} {size:,} B")
