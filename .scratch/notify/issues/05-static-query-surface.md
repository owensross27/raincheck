# 05 — The static query surface: manifest, per-asset files, size report

**What to build:** The map page can answer "has this stop ever flooded?" from static files
alone, and the decision about whether static hosting is enough is settled by a printed
number rather than a guess. Spec: section 3; SEAM Q.

**Blocked by:** 03.

**Status:** DONE 2026-08-26 (branch `notify05-static-history`) — see the close-out at the bottom

- [x] `make export` writes a manifest listing every asset with at least one attached event (id, kind, event count), plus one file per listed asset holding its history and its exposure
- [x] an asset absent from the manifest is renderable as "no events on record" without any request
- [x] the exporter is a renderer: it calls the query function in `public` mode once per manifest entry and contains no joins of its own
- [x] the run prints file count, total bytes and largest single file — the comparison point is today's shipped insight surface, 2,606,072 bytes across three files (measured 2026-08-23); no ticket may take the DuckDB-over-R2 escalation path without this number
- [x] re-export is byte-identical: every aggregate ordered, every number explicitly rounded, writes staged and replaced atomically, all files or none
- [x] no null values anywhere in the written files, asserted by parsing them back from disk
- [x] the export ships on the spine's cadence through the batch path and never on the 30 s live tick
- [x] if the measured file count proves unwieldy for the static host, sharding by asset kind and H3 prefix changes this renderer alone and touches no query


## Inherited from notify 02 (landed 2026-08-24, branch `notify02-query-core`, 13a93ab)

**SEAM Q exists — consume it, never re-derive it.** `src/raincheck/query.py`:

    query(name, params, data_root=None, mode="public") -> dict     # THE entry point
    QUERIES = {"events_for_asset": events_for_asset}                # the registry
    fn(con, root, params, mode) -> dict                             # every implementation
    QueryError(reason, **detail)                                    # e.reason, e.detail

`query()` adds the `query` / `mode` / `versions` envelope, validates the mode (`public`
is `MODES[0]` and the default) and resolves the version stamps BEFORE any answer is
built, so an unstamped payload cannot exist. `REASONS` is the frozen error vocabulary:
the spec's five plus `unknown_query`, `unknown_mode`, `missing_param`; `QueryError`
refuses anything outside it. Helpers to reuse rather than rewrite: `pack(**kv)` (absent,
never null), `jsonable(v)`, `cell_id(int)`, `sources(source_mix)`, `holes(n)`,
`view(con, root, *parts, name=, columns=)`.

**Frozen by that landing:**
- **A Cell id crosses the boundary as its H3 HEX STRING** (`format(cell, "x")`), never
  the int64 — 613229535722209279 is past 2^53 and a JSON reader using doubles corrupts it.
- **The licence boundary is one rule**: `public` ships COUNTS and F05's attachment facts;
  `local` ships the ROWS behind them. Public emits NO observation row at all — that, not
  field filtering, is what keeps the FloodNet depths, the alert row and the subwaydata
  numbers in. Anything you add answers to the same rule.
- **Counts are EVENT-grain** (`event_source_counts`, `event_observations`): F05 stores no
  per-source counts, so an asset-grain count would mean re-attaching flood_obs to
  ref/assets, which is F05's join alone. The `event_` prefix is the guard.
- **Reads are narrowed `create_view` relations, never `rel.arrow()`** (the wave-1
  lazy-reader deadlock), and every value is a bound parameter — `holes(n)` builds
  placeholder lists, values are never formatted into SQL text.
- Fixtures: `tests/fixtures/notify_query_*.parquet` (17 KB, cut from the real tables,
  two real events, real restricted rows) assemble a whole root in `tests/test_query.py`'s
  `root` fixture — extend that fixture rather than cutting a second one.

**notify 02 measured your surface so you do not have to guess** (real root, 60-asset
sample, 2026-08-24): **7,955 assets have history** — **CORRECTED BY MEASUREMENT
2026-08-26: it is 8,146. 7,955 counts assets that own a LABEL ROW; the manifest lists
what `events_for_asset` ANSWERS for, and a complex answers for its entrances too, so
complexes are 285 and not 94. Both numbers are right about different questions and the
query's one is the one a click sees. See the close-out.**; a `public` payload is **mean 1,373 B,
median 746 B, max 7,625 B → ~10.9 MB across 7,955 files**. Bytes are the same order of
magnitude as today's 2,606,072-byte insight surface, so static-host territory holds on
size; the FILE COUNT is the part that may break the host's sync, which is exactly the
shard-by-kind + H3-prefix escape the spec names — decide it on this number.

**COST MUST:** `query()` opens a DuckDB connection and re-resolves the three version
stamps on EVERY call — 0.115 s per call, 0.097 s of it `versions()`, i.e. ~16 min for a
7,955-asset export. Resolve the stamps once and reuse one connection (the `ponytail:`
note at the call site names this upgrade). Do NOT add a date-keyed cache: key any cache
on the inputs, or it serves stale answers when the spine moves.

## Inherited from frontend 02 (prototype, `4ac3ebe`, 2026-08-24) — the manifest, re-measured

Frontend 02 built the flood-history marker layer against the real `ref/assets JOIN
gold/flood_labels` and the real `query('events_for_asset', mode='public')`, over all 7,955
assets. It confirms frontend 01's coordinate MUST and adds two things:

- [x] **The manifest must carry `name` as well as `lon`/`lat`.** `ref/assets` names only
  stops and complexes — **a `cell`-kind asset has `name = NULL`** — and the most-flooded
  assets are exactly the Cells, so a manifest of id+kind+count+lon/lat renders the literal
  word "null" at the TOP of any ranked list. Re-measured over all 7,955 assets in ONE
  envelope throughout (GeoJSON, so absolutes differ from frontend 01's flat-manifest
  figures but the deltas are comparable): **39,203 B gz as specified &rarr; 99,154 with
  lon/lat (+59,951) &rarr; 147,792 with `name` too (+48,638 more; 1,576,447 raw).**
  Freeze the whole key set here: `asset_id, kind, n_events, lon, lat, name` — and note
  `query.py:167`'s `ASSET_COLUMNS` uses `asset_id`, never `id`, so the spec's prose "id"
  should not become a literal key.
- [x] **Size the CLICK on the tail, not on the random-sample median.** notify 02's recorded
  "median 746 B / max 7,625 B" came from a 60-asset RANDOM sample. Cutting the TOP 40 by
  event count — same code path, same `mode="public"` — gives median 10,057 B and **max
  23,444 B** (`cell:882a1062d5fffff`, 73 events): about 3x the recorded max. The 746 B
  median is still right for sizing the ~10.9 MB tree; it is the wrong number for sizing one
  per-asset fetch, and a per-asset fetch on click is exactly what frontend 01's payload rule
  ("paint from one bulk file, detail from one per-asset fetch") makes the page do.

## MUST from frontend 05 (the chassis landed 2026-08-25, `frontend05-seven-layer-chassis`)

- **The page reads your manifest at `web/files/history/manifest.geojson`, as a GeoJSON
  FeatureCollection.** That URL is already in the live page's `LAYERS` table and its `draw`
  hook `setData`s the body unchanged, so a FeatureCollection paints the history layer with
  no page code at all. Land that name and shape, or land another and correct this line, the
  table and your summary line in the same commit.
- Each feature's `properties` must carry **`asset_id`, `kind`, `name`, `n_events`** — the
  coordinate MUST already on this ticket plus the two the marker layer reads:
  `n_events` drives `circle-radius` (1 -> 1.6 px, 12 -> 4.6 px) and `name`/`kind` drive the
  id fallback that keeps the most-flooded assets from rendering the literal "null".
- **A budget constant here graduates the layer's freshness row from a bare AGE to a
  verdict.** Without one the page reports an age and judges nothing, deliberately; a
  downstream guess is refused by a test that counts the budgeted sources.

## Forward context from frontend 06 — the published contract you write into (2026-08-25)

Landed on branch `frontend06-discovery-contract` (`8bd82db`). Read
`docs/read-api-contract.md` before shaping the manifest: it is the written contract your
files are published under.

**YOU DO NOT OWE `files/index.json`.** Frontend ticket 03's Answer put that MUST on this
line; frontend 06 BUILT it. `raincheck.contract` renders it inside the same `make export`
run that writes the insight trio, and `publish.FAMILIES["insight"]` publishes it LAST.
**Do not write a second copy** — two writers on one key is the drift the single-renderer
rule exists to prevent.

**Your tree needs no contract bump.** `contract.PROMISE[1]` freezes the `history` family
as its PREFIX, `files/history/**`, not as individual file names. Adding, renaming or
resharding files INSIDE that tree is additive and demands nothing. **Renaming the prefix
itself, or moving history out of its family, IS breaking:**
`tests/test_publish.py::test_the_contract_integer_covers_the_surface_a_consumer_binds_to`
goes red and demands `contract.CONTRACT` bumped with a NEW frozen `PROMISE` entry beside
the old one (never edit an old entry) plus the Status line of `docs/read-api-contract.md`,
all in one commit.

**Same stamps, one seam.** `index.json` carries `query.versions(con, root)`'s
assets/spine/label — the same three you resolve. Your cost MUST (resolve once, reuse one
connection) is unchanged; nothing here re-derives them.

**Still no wall clock**, in the manifest or the per-asset files. `index.json` carries none
either, which is what keeps `test_re_export_is_byte_identical` covering the whole export
run. Consumers date every payload from its own HTTP response (`Date` − `Last-Modified`).

## Inherited from notify 03 (landed 2026-08-25, branch `notify03-exposure-of`) — the exposure half of your per-asset file

    query("exposure_of", {"asset_id": "stn:611"}, root, mode="public") -> dict

    {"query": "exposure_of", "mode": "public",
     "asset":    {asset_id, kind, name?, cell?, complex_id?},          # 02's block, verbatim
     "exposure": {estimand, model_id, score_index, score_ref, score_severe,
                  surge_margin_ft?, flags: [...], modelled: bool},
     "versions": {assets_version, spine_version, label_version, score_version?}}

`asset` and `versions` are IDENTICAL to the ones `events_for_asset` returns for the same
id (asserted by a test), so one file holding both is a merge, not a reconciliation.

- **928 OF YOUR MANIFEST ASSETS HAVE NO EXPOSURE ROW, and they are all entrances.**
  Measured on the real root: the assets with history are 5,657 bus stops + 1,276 Cells +
  94 complexes + **928 entrances** — **the 928 is EXACT and confirmed on the shipped tree;
  the complex figure is not: 94 own a label row, 285 have a history through the rollup,
  and all 8,146 - 928 = 7,218 non-entrance assets are scored (2026-08-26)** — and every
  entrance publishes a history and NO score
  (its score exists only inside its complex's max — that is the Unit/Carrier rule). So
  "its history and its exposure" is not a blind pairing: `exposure_of` raises
  `QueryError("not_a_scored_unit", asset_id=…, kind="entrance", ask="<complex asset_id>")`
  for those 928. Write the file with the history and NO exposure key (absent, never null),
  and let the `ask` id point at the complex — do not invent a score, and do not drop the
  asset from the manifest.
- **Your surface is measured, both halves.** An `exposure_of` payload is a flat 590-633 B
  (median **624 B**, 40-asset random sample, no tail at all — unlike the history payload,
  which frontend 02 re-measured at max 23,444 B on the top-40 by event count). Publishing
  one per Unit over all 15,166 rows is ~**9.4 MB**; publishing only the 7,027 manifest
  assets that HAVE a score is ~4.4 MB on top of the ~10.9 MB history tree.
- **The cost MUST above just doubled — AND THE UPGRADE IS MEASURED AND WORKS.**
  `exposure_of` through `query()` costs **0.1024 s per asset**, ~0.09 s of it `versions()`
  re-resolving stamps on a fresh connection; two calls per asset is ~27 min for your 7,955.
  Calling the registry function directly on ONE connection with the stamps resolved once is
  **0.0083 s per asset — 12x, 2.1 min over all 15,166 Units** (measured 2026-08-25, real
  root, 100-asset sample). **One connection serves both queries and repeated calls with no
  view-name collision** (`view()`'s `create_view` replaces), so the whole upgrade is: open
  `duck.connect()` once, call `query.versions(con, root)` once, then
  `query.QUERIES[name](con, root, params, "public")` per asset and add the
  `query`/`mode`/`versions` envelope yourself. Do NOT invent a date-keyed cache.
- **`versions()` gained `score_version`** (a fourth stamp) on any root that publishes
  `gold/flood_exposure`, so every file you write carries it and `files/index.json` does
  too — `contract.index()` calls the same seam. Additive: no `contract.CONTRACT` bump was
  owed and none is owed by you. It is ABSENT, never null, on a root with no scores.
- **Never present a fallback score as a modelled rank.** 60 bus stops (flag
  `score_fallback_kind_median`) score on their kind's MEDIAN because their features could
  not be built at all; `exposure.modelled` is `false` for exactly those, and the flags
  ride beside it. Every flag's one-line meaning is published under `flags` in
  `research/flood-10-coefficients.json` — link that rather than wording a second copy.
  `score_index` (the within-kind rank, bounded (0, 1]) is the human-facing number;
  `score_ref` / `score_severe` are the LINEAR PREDICTOR and are negative for nearly every
  Unit. No complex-grain skill claim anywhere.
- **An absent `surge_margin_ft` is not a zero.** 404 Units have no point elevation behind
  them and carry the `no_surge_margin` flag; the key is simply not there. A zero margin
  means the water is AT the doorway, so writing 0.0 there inverts the meaning.

## Forward-context from DESTINATION-PLAN.md (copied verbatim by the WAVE 5 GATE PART 2, 2026-08-25, from this ticket's summary line in waves/wave-3-plus.md)

**FROM DESTINATION-PLAN (2026-08-25):** frontend2 04 (wave 8) adds a SIBLING family `summary` (`files/summary/{recent,complexes,routes}.json` — aggregates over `flood_events`/`flood_labels`/`gold/route_flood`). It shares your public-lineage rule and your byte-identical rule and touches nothing under `files/history/**`. Nothing new is owed by you.

## Inherited from notify 04 (landed 2026-08-25, branch `notify04-area-queries`) — an area file, if you want one

`QUERIES` now has FOUR entries; the two new ones are `assets_in_area` and `obs_near`.
Neither is on your critical path — the manifest plus per-asset files is still the ticket —
but one of them is a precompute you could ship and the other you must never call:

    query("assets_in_area", {"cells": ["<h3 hex>", ...]}, root)          # or {"bbox": [...]}
    -> {"area": {"cells": [...], "n_cells": N, "bbox"?: [w, s, e, n]},
        "n_assets": N,
        "assets": [{asset_id, kind, name?, cell, complex_id?, n_events, last_event_id?}, ...],
        "reason"?: "no assets in this area", "versions": {...}}

- **It is a `public`-mode answer already** — built from `ref/assets` and F05's attachment
  COUNTS, and a count is not a row — so it carries nothing the licence withholds and needs
  no filtering to be publishable. `mode` does not change it at all.
- **A per-Cell area file is a renderer decision, not a query change.** One call per Cell
  over the real root's 4,113 Cells at ~0.15 s a call is ~10 minutes, the same shape as the
  ~27 min your two-calls-per-asset manifest already costs, and with the same upgrade in
  front of it: a caller-supplied connection and stamps resolved ONCE (`query()` re-resolves
  four stamps per call, ~0.1 s of every call, measured by notify 02 and unchanged here).
  Do that upgrade at the SEAM if you do it at all — never a cache keyed on a date.
- **Sizes, measured on the real root 2026-08-25:** a 2.2 km bbox (7 Cells) is 242 assets /
  35,296 bytes; the worst case the cap allows (the 64 densest Cells) is 3,573 assets /
  519,140 bytes. A per-Cell file would be small (5 assets is the median Cell) but there
  would be 4,113 of them — the same file-count question your own checklist asks about the
  per-asset files, so answer both with one number.
- **`obs_near` is `local` ONLY and raises `restricted_source` in `public`.** The static
  surface runs `public`, so it can never call it — that is by construction, not by
  discipline, and `docs/read-api-contract.md` now says so on the host's own contract page.
- **Cell ids cross as H3 HEX STRINGS** (`asset.cell` is already that string), the int64 is
  refused by name, and `area_too_large` names the cap (`query.CELL_CAP` = 64 Cells).


## DONE 2026-08-26 — branch `notify05-static-history`

`src/raincheck/history.py` renders `web/files/history/` on `make export`'s batch run;
`src/raincheck/export.py`'s `main()` calls it (13 added lines, `run()` untouched so
frontend2 03's staging refactor does not collide); `tests/test_history.py` is +32.

**THE KEY SET, AS SHIPPED — SIX:** `asset_id, kind, n_events` as Feature properties,
`lon, lat` as the Point geometry, `name` as a property that is **ABSENT on all 1,276
Cells**. Never `id`.

**THE COUNT IS 8,146, NOT 7,955, AND THE DIFFERENCE IS THE COMPLEX ROLLUP.** 5,657 bus
stops + 1,276 Cells + 928 entrances are all EXACT; complexes are **285**, because
`events_for_asset` answers a complex for itself AND its child entrances while 7,955
counted assets holding a label ROW (94 complexes do). The manifest has to be what a click
returns, so 285 is the right number here. Verified two ways: `stn:409` in the test fixture
carries no label of its own and returns a real history, and on the real root the seam's
answer is EQUAL — asset for asset, count for count — to the same question asked as one
direct join.

**MEASURED ON THE REAL ROOT (2026-08-26), one clean uncontended run:**

| | |
|---|---|
| files | **8,147** (1 manifest + 8,146 per-asset) |
| total | **14,174,355 B** = 5.4x the 2,606,072-byte insight surface |
| manifest | **1,458,148 B raw**, 138,524 gz — loaded ONCE |
| per-asset | median **1,138 B**, mean 1,561 B, **max 21,994 B** (`cell:882a1062d5fffff`, 73 events) |
| no exposure key | **928**, every one an entrance |
| no `name` | **1,276**, every one a Cell |
| build | **436.2 s (7.27 min)**, clean; a second full build is **BYTE-IDENTICAL across all 8,147 files** |

**THE FILE-COUNT DECISION: FLAT, NO SHARDS, and the escape stays open.** 8,147 objects is
nothing for R2's keyspace and nothing for `publish.plan()`'s `rglob`. What the count
actually costs is the SERIAL PUT loop, and sharding by kind or H3 prefix moves the same
object count into more directories without touching that. So the tree is flat
(`files/history/<asset_id>.json`, the id verbatim) and resharding remains what the spec
says it is: a change to this renderer alone, one f-string, no query touched.

**THE COST FIX, RE-MEASURED HERE:** through `query()` a call is **176.5 ms**; on one
connection with the stamps resolved once, both queries together are **48.6 ms per asset**
— **7.3x**, and the whole tree builds in **436.2 s (7.27 min)**, measured clean and uncontended on the real root. The box's 12x is `exposure_of` alone
(the cheap half); `events_for_asset` is 45.6 of those 48.6 ms and is dominated by the
seam's per-call `create_view` + `rglob`, not by the stamps. No cache of any kind was
added.

**WHAT WAS DELIBERATELY NOT DONE.** `publish` still PUTs one object at a time, so this
tree is 8,147 serial PUTs per spine rebuild. **NOT fixed here: `publish.py` has one editor
this wave and it is flood 17.** The named `ponytail:` upgrade in that module (parallelise
the TREE families, leave the ordered live pair alone) is still the right fix and is now
priced against a real object count. `query.QUERIES` was NOT touched either — notify 06
wraps exactly four tools this wave.
