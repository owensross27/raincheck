# 06 — MCP tool layer: the agentic consumer gets tools, not a login

**What to build:** An agent can answer questions about this dataset by calling four named
tools over stdio — in CONTEXT.md's own vocabulary, with the version stamps of the universe
that answered — without holding a database credential or inventing SQL. Spec: section 5;
SEAM Q.

**Blocked by:** 04.

**Status:** ready-for-agent

- [ ] a read-only stdio MCP server exposes exactly four tools — `events_for_asset`, `exposure_of`, `assets_in_area`, `obs_near` — with the query function's own argument names
- [ ] the server is dispatch-only: validate, select mode, call, return; no query logic lives in it
- [ ] each tool description names the tables it reads and the version stamps it returns, so an agent choosing between tools has the vocabulary in front of it
- [ ] the server defaults to `public`; `local` requires an explicit flag at startup, and a hosted server may never set it
- [ ] no SQL-passthrough tool exists — permanently, not deferred
- [ ] typed errors (`unknown_asset`, `not_a_scored_unit`, `area_too_large`, `restricted_source`, `version_unresolved`) reach the caller by name, never as a bare traceback
- [ ] the MCP SDK is pinned in `pyproject.toml`; tests assert that each tool dispatches to its query name with the arguments it received, and nothing tests the protocol itself
- [ ] the server runs locally against local parquet; nothing in this ticket opens a port


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

**The server dispatches to `query()` and catches `QueryError` only** — `e.reason` is the
machine-readable name for the agent, `e.detail` the recovery hint (which complex to ask,
which cap was hit). `query.REASONS` is the whole vocabulary; do not invent a sixth-plus
name in the wrapper. **Size warning:** a `local` `events_for_asset` payload reaches ~2 MB
on a 73-event Cell (it carries every observation inside each event's window); the same
answer in `public` is ~1 KB. One more reason the default stays `public`.

## Inherited from notify 03 (landed 2026-08-25, branch `notify03-exposure-of`) — two of your four tools now exist

    query("exposure_of", {"asset_id": "stn:611"}, root, mode="public") -> dict

    {"query": "exposure_of", "mode": "public",
     "asset":    {asset_id, kind, name?, cell?, complex_id?},
     "exposure": {estimand, model_id, score_index, score_ref, score_severe,
                  surge_margin_ft?, flags: [...], modelled: bool},
     "versions": {assets_version, spine_version, label_version, score_version?}}

The tool takes ONE argument, `asset_id`, the same name `events_for_asset` takes — so your
"the query function's own argument names" checklist row is satisfied by passing it through.

- **`REASONS` IS UNCHANGED — no sixth name was added, and your typed-error row is already
  complete.** `exposure_of` reuses `not_a_scored_unit` and raises it on ABSENCE from
  `gold/flood_exposure`, so a **station OR an entrance** (both Carriers) gets
  `{"asset_id": …, "kind": …, "ask": "<complex asset_id>"}` — `ask` is the recovery hint
  an agent should follow, and it is the one thing worth naming in the tool description.
  A ref Cell outside F10's fit set (2,762 of 4,113) is also `not_a_scored_unit` and has
  **no `ask` key at all** (no parent to ask) — absent, never null, so an agent must test
  for the key rather than reading it.
- **The two tools disagree about entrances ON PURPOSE.** An entrance has a HISTORY (F05
  labels it) and NO SCORE (its score exists only inside its complex's max). An agent that
  asks both tools for one entrance gets an answer and a typed refusal, and that is
  correct. Say so in the descriptions or the agent will read the refusal as a bug.
- **`mode` does not change this answer at all** (asserted): the licence boundary is one
  rule about MTA / FloodNet / subwaydata ROWS, and a score built from elevation,
  stormwater class and public precip is in no restricted class. `local` and `public`
  return the same object, so the size warning below applies to `events_for_asset` alone —
  an `exposure_of` payload is a flat ~624 B in both modes.
- **`versions()` gained a fourth stamp, `score_version`**, on any root that publishes
  `gold/flood_exposure` (ABSENT, never null, when it does not). Your "each tool description
  names the version stamps it returns" row should name four, and should say that the
  fourth can be legitimately missing.
- **Describe the score honestly or the tool teaches an agent something false.**
  `score_index` is the within-kind RANK, bounded (0, 1] — that is the human-facing number.
  `score_ref` / `score_severe` are the LINEAR PREDICTOR at F10's reference forcings and are
  NEGATIVE for nearly every Unit; they are not probabilities. `modelled: false` marks the
  60 bus stops scored on their kind's median rather than by a model evaluation. Flags are
  F10's closed vocabulary and every flag's one-line meaning is published under `flags` in
  `research/flood-10-coefficients.json` — point the description at that file instead of
  re-wording five sentences. **No complex-grain skill claim in any tool description**: the
  complex number is an aggregate of doorway scores and the independent complex set caught
  1 of 118.

## Forward-context from DESTINATION-PLAN.md (copied verbatim by the WAVE 5 GATE PART 2, 2026-08-25, from this ticket's summary line in waves/wave-3-plus.md)

**FROM DESTINATION-PLAN (2026-08-25), one line:** the static `files/summary/**` (frontend2 04, wave 8) is where an agent asks "where flooded recently / which complexes / how many routes"; a tool description MAY point at it later. Not built here; the four tools stay exactly four.

## Inherited from notify 04 (landed 2026-08-25, branch `notify04-area-queries`) — your other two tools exist, so all FOUR are built

    query("assets_in_area", {"cells": ["882a1072c1fffff", ...]}, root, mode=...) -> dict
    query("assets_in_area", {"bbox": [west, south, east, north]}, root, mode=...) -> dict

    {"query": "assets_in_area", "mode": "public",
     "area":   {"cells": ["<h3 hex>", ...], "n_cells": N, "bbox"?: [w, s, e, n]},
     "n_assets": N,
     "assets": [{asset_id, kind, name?, cell, complex_id?, n_events, last_event_id?}, ...],
     "reason"?: "no assets in this area",          # only when the list is empty
     "versions": {assets_version, spine_version, label_version, score_version?}}

    query("obs_near", {"asset_id": "stn:611", "radius_m": 500}, root, mode="local") -> dict
    query("obs_near", {"lon": -73.98, "lat": 40.75, "radius_m": 500}, root, mode="local")

    {"query": "obs_near", "mode": "local",
     "point":  {lon, lat, radius_m, asset_id?},    # asset_id only when you gave one
     "n_observations": N,
     "observations": [{source, source_id, ts_utc, obs_ts_kind, cell?, depth_mm?, text?,
                       distance_m}, ...],          # NEAREST FIRST
     "versions": {...}}

**The tool argument names, which is the row your checklist actually binds:** `cells`,
`bbox`, `asset_id`, `lon`, `lat`, `radius_m`. `cells` is a list of H3 HEX STRINGS (a lone
string is accepted as a one-element list); giving both `cells` and `bbox` unions them.
`radius_m` defaults to 500 and `assets_in_area` has no default at all — one of `cells` or
`bbox` is required (`missing_param` names `cells|bbox`).

- **`REASONS` IS STILL UNCHANGED** — eight names, the same eight notify 02 froze. Ticket 04
  RAISED the two that were waiting: `area_too_large` (an area past `query.CELL_CAP` = 64
  Cells, or a radius past `query.RADIUS_CAP_M` = 2,000 m; the detail carries the count and
  the cap so an agent can retry smaller) and `restricted_source` (`obs_near` in `public`).
  Both are now documented in `docs/read-api-contract.md`. A ninth name is still owed to
  nobody: an UNBUILT table refuses as `version_unresolved` naming the table.
- **`obs_near` is the ONE tool your `local` flag changes**, and it changes it to a refusal,
  not to a smaller payload: in `public` it raises `restricted_source` BEFORE it looks at any
  other argument, so a hosted server learns nothing from the shape of a later error. The
  other three answer identically in both modes. Say that in its description — an agent that
  reads "local only" as "richer when local" will keep retrying.
- **Cell ids cross as H3 HEX STRINGS in BOTH directions.** The int64 is refused by name
  rather than accepted, because a JSON reader using doubles has already corrupted
  613229535722209279 by the time it reaches the tool. An agent that got a Cell from
  `events_for_asset`'s `asset.cell` can pass it straight back into `cells`.
- **Cell is the only area key, permanently in v1**: no polygon parameter (a caller holding
  one resolves it to Cells itself), and no Zone anywhere — a Zone is a presentation overlay
  resolved through the static Cell-to-Zone lookup at serving time. `assets_in_zone` and
  `obs_in_polygon` raise `unknown_query` and a test pins that they stay unregistered. **The
  tools stay exactly four.**
- **Size, measured on the real root 2026-08-25:** a 2.2 km bbox (7 Cells) is 242 assets /
  35 KB / 0.31 s; the WORST case the cap allows (the 64 densest Cells) is 3,573 assets /
  519 KB / 0.15 s. `obs_near` at Times Square is 187 rows / 35 KB at 500 m and 1,177 rows /
  217 KB at the 2,000 m cap. Nothing here approaches the ~2 MB `events_for_asset` warning
  above, but an area answer is still the biggest thing three of your four tools return.
- **Stations never appear in an area answer.** They are Carriers; `events_for_asset` refuses
  them and names the complex, so listing one with a count would publish a number for an
  asset that cannot be asked for it. The complex at the same doorway is listed and answers.
  `n_events` is exactly the history `events_for_asset` would return for that asset (complex
  rollup included), and a test pins the two to agree — so an agent can filter an area to the
  flooded assets without a second call per asset.
