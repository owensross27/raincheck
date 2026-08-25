# 05 — The static query surface: manifest, per-asset files, size report

**What to build:** The map page can answer "has this stop ever flooded?" from static files
alone, and the decision about whether static hosting is enough is settled by a printed
number rather than a guess. Spec: section 3; SEAM Q.

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] `make export` writes a manifest listing every asset with at least one attached event (id, kind, event count), plus one file per listed asset holding its history and its exposure
- [ ] an asset absent from the manifest is renderable as "no events on record" without any request
- [ ] the exporter is a renderer: it calls the query function in `public` mode once per manifest entry and contains no joins of its own
- [ ] the run prints file count, total bytes and largest single file — the comparison point is today's shipped insight surface, 2,606,072 bytes across three files (measured 2026-08-23); no ticket may take the DuckDB-over-R2 escalation path without this number
- [ ] re-export is byte-identical: every aggregate ordered, every number explicitly rounded, writes staged and replaced atomically, all files or none
- [ ] no null values anywhere in the written files, asserted by parsing them back from disk
- [ ] the export ships on the spine's cadence through the batch path and never on the 30 s live tick
- [ ] if the measured file count proves unwieldy for the static host, sharding by asset kind and H3 prefix changes this renderer alone and touches no query


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
sample, 2026-08-24): **7,955 assets have history**; a `public` payload is **mean 1,373 B,
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

- [ ] **The manifest must carry `name` as well as `lon`/`lat`.** `ref/assets` names only
  stops and complexes — **a `cell`-kind asset has `name = NULL`** — and the most-flooded
  assets are exactly the Cells, so a manifest of id+kind+count+lon/lat renders the literal
  word "null" at the TOP of any ranked list. Re-measured over all 7,955 assets in ONE
  envelope throughout (GeoJSON, so absolutes differ from frontend 01's flat-manifest
  figures but the deltas are comparable): **39,203 B gz as specified &rarr; 99,154 with
  lon/lat (+59,951) &rarr; 147,792 with `name` too (+48,638 more; 1,576,447 raw).**
  Freeze the whole key set here: `asset_id, kind, n_events, lon, lat, name` — and note
  `query.py:167`'s `ASSET_COLUMNS` uses `asset_id`, never `id`, so the spec's prose "id"
  should not become a literal key.
- [ ] **Size the CLICK on the tail, not on the random-sample median.** notify 02's recorded
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
