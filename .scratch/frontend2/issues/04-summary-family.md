# 04 — the `summary` family: recent-flooding aggregates

**Status: done** (2026-08-26, branch `frontend2-04-summary-family`)

**The contract for this ticket was never a file of its own**: flood-build 21a's ticket
file §10 (`.scratch/flood-build/issues/21-route-flood-attribution.md`) plus the wave-8
box E prompt WERE the contract, and this file was created by the ticket that closed it —
both halves are restated below so the record stands alone.

## What was owed

`files/summary/{recent,complexes,routes}.json` — the three aggregate payloads answering
Ross's API questions ("where flooded recently / which complexes / how many routes") —
as a new TREE family `summary` in `publish.FAMILIES`, built by `make summary`, listed in
`index.json` automatically, documented in `docs/read-api-contract.md`. Three MUSTs:
(a) a NULL share is not a zero (absent or null WITH a derived reason, never 0.0);
(b) `share_len_not_analyzed` beside `share_len_moderate` or neither;
(c) every claim descriptive — "crosses N flood-prone Cells" yes, "slower because it
floods" no (wave 10+, gated on the backfill). Plus: route ids are facts, route bullets
are MTA IP; family rules from notify 05 (additive tree, no wall clock, byte-identity,
one-connection shape); the four MCP tools stay four.

## What shipped

`src/raincheck/summary.py` (one module, ~230 lines) + `tests/test_summary.py` (27
tests), with additive edits to `publish.FAMILIES` (+`summary` — FAMILIES is TWELVE),
`contract.SCHEMA` (`files/summary/**` pointer), `docs/read-api-contract.md` (row +
section + "Twelve" recount), `Makefile` (`summary` target), and ONE string in
`notify_mcp.INSTRUCTIONS` pointing agents at the static files (the tools stay exactly
four; `test_the_tool_set_is_query_QUERIES_and_nothing_else` untouched and green).

### The payload shapes (measured on the real root, 2026-08-26)

Every file carries `strings{label, caveats[]}` (module-constant sentences — render,
never restate) and `versions` = `query.versions(con, root)` resolved ONCE (the
one-connection shape; the seam sweep in complexes.json runs through
`query.QUERIES[...]` on the same connection).

**`recent.json`** (32,924 B) — window + events, newest first:

    {"window": {"since": "2025-08-20", "until": "2026-08-20", "days": 365},
     "n_events": 14,
     "events": [{"event_id": "2026-08-20", "day_start": …, "day_end": …, "n_days": 1,
                 "event_class": "pluvial", "flood_cause": …?, "sources": ["311", …],
                 "depth_mm": …?,          <- max labelled depth, pass-through, ABSENT if none
                 "n_assets": {"bus_stop": 86, "cell": 82, "complex": 4, "entrance": 27},
                 "cells": ["882a…", …]}]} <- sorted H3 hex, joins files/cells.geojson

The window is ANCHORED ON THE SPINE'S NEWEST `day_end`, never on today — no wall clock
reaches any payload. `n_assets` are EVENT-grain counts of the published attachment
(`gold/flood_labels`), said so in the caveats — never a re-attachment.

**`complexes.json`** (41,372 B) — 285 complexes, most-flooded first:

    {"n_complexes": 285,
     "complexes": [{"asset_id": "stn:99", "name": "Lorimer St", "lon": -73.94741,
                    "lat": 40.70387, "cell": "882a100debfffff", "n_events": 21,
                    "last_event_id": "2026-07-18"}]}   <- an event id IS its day_start

Counts come through `history.flooded`'s seam sweep (`assets_in_area` in CELL_CAP
batches), so a complex answers for itself AND its child entrances — asserted equal to
`events_for_asset` per id. 285, not 94: the rollup is why (notify 05's own measured
distinction). lon/lat at `history.COORD_DP` because a payload naming a place carries
its coordinates [KNOWN TRAPS, three prior offences].

**`routes.json`** (173,733 B) — 683 rows, ordered (route_id, direction_id):

    {"n_routes": 683,
     "source": {"table": "gold/route_flood", "label_version": …, "features_version": …,
                "zip_sha256": …, "route_flood_version": …},   <- distinct-checked, Refused if mixed
     "not_published": {"share_len_limited":  <UNREADABLE's own sentence>,
                       "share_len_extreme":  "DEP publishes extreme at horizon 2080 only …"},
     "routes": [{"route_id": "B1", "direction_id": "0",   <- both STRINGS
                 "n_shapes": 3, "length_m": 10904.66…,    <- pass-through, unrounded
                 "n_cells": 15, "n_cells_flood_prone": 14,
                 "share_len_moderate": 0.0363…, "share_len_not_analyzed": 0.0096…,
                 "n_flood_events": 89, "last_event_day": "2026-08-03"}]}

MUST (a): a share column entirely NULL at the source is not written per row at all;
`not_published` carries the reason DERIVED through `flood_route.unsourced` (which reads
`stormwater_extent.SCENARIOS`/`UNREADABLE`) — no sentence retyped. A SOURCED column
arriving all-NULL is `Refused`, not dropped (the compressed-FGDB lie guard). MUST (b):
the mask is published beside the flooded share per row, or (a no-geometry route)
neither key — enforced by a build-time `Refused` if the table ever carries a flooded
share without the mask. MUST (c): the caveat sentences ship in every file; no exhibit
number was lifted anywhere (the exhibit was not read).

### Discipline

- Byte-identical re-export: proven on the real root (two builds, byte-equal) and pinned
  by test against a route table PLANTED physically out of order — the only fixture that
  can catch a dropped ORDER BY [flood-build 19's trap].
- Staged-and-swapped whole (history.build's two-rename dance): a TREE family has no
  file list for `publish.plan` to refuse a partial build with, so the writer refuses to
  leave one.
- **Mutation round: 10/10 killed**, pristine green before and after, harness under
  every TRAPS rule (committed first, snapshot from git, refuse-dirty,
  PYTHONDONTWRITEBYTECODE, checkout+clean restore with a porcelain assert, every mutant
  proven landed): drop-routes-order · drop-cells-sort · drop-window-where ·
  max-to-min-depth (needed a planted SECOND depth — the fixture held one non-null depth
  per event, the degenerate-fixture trap by the letter) · or-to-and-sources ·
  complex-filter-flip · sort-ascending · never-unpublished · drop-mask-guard ·
  drop-coord-round.
- Own-module runs only: `test_summary` 27/0; `test_publish` + `test_export` +
  `test_history` + `test_notify_mcp` all green (177 passed, 1 skipped = the worktree's
  vendor-absent skip). No full suite — that is the gate's.

### What ran into what

- **`test_no_module_but_this_one_imports_the_sdk_and_this_one_does_it_lazily`
  (test_notify_mcp.py) greps every module for the SUBSTRING "mcp"** — a docstring that
  merely NAMES `notify_mcp` turns it red. Reworded the docstring; TRAPS carries the
  bullet now.
- `depth_mm`'s max() was indiscriminable on the shared notify 02 fixture (every event
  held exactly one non-null depth). Fixed by an EXTRA part file in this suite's own
  assembled root — the shared parquet stays notify 02's, extended by nobody.

## Deliberately not done

- No release_check row: nothing here re-serves an MTA row (event-grain existence and
  attachment counts are the seam's own public answers), and the box named four edit
  sites, not five.
- No parallel PUT work: `publish`'s serial-PUT ceiling is `publish.py`'s own
  `ponytail:` note; three more objects move nothing.
- No `daily.STAGES` registration: `make summary` is operator-run after
  `make flood-route`, the same posture as `flood-route` itself until 21b's gate step
  registers that stage — a `summary` stage registration would be a wave-9+ decision.

## Close-out — DONE 2026-08-26

Branch `frontend2-04-summary-family`, worktree `/Users/ross/raincheck-wt/frontend2-04`
(removed after landing entry). Test delta +27 (`tests/test_summary.py`; recounted by
`def test_` against merge base `ed23cfa`). FAMILIES eleven -> TWELVE; `contract.CONTRACT`
stays 1 (additive tree family — the subset rule held, `test_the_contract_integer_covers_
the_surface_a_consumer_binds_to` green untouched). Forward context written onto
frontend2 05's held entry and STATUS's wave-9 P3 row.
