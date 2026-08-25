# 04 — Area queries: assets_in_area and obs_near

**What to build:** Ask what flooded inside an area without knowing an asset id, and ask
what was observed near a point. Cell is the only area key; Zone stays a presentation
overlay. Spec: sections 2 and 4; CONTEXT.md (Cell, Zone); SEAM Q.

**Blocked by:** 03.

**Status:** DONE (2026-08-25, branch `notify04-area-queries`)

- [x] `assets_in_area` takes Cell ids, or a bbox resolved to a Cell set before anything is read — Cell is the only area key
- [x] Zone resolves through the static Cell-to-Zone lookup at serving time and appears in no stored key and no query parameter
- [x] a request resolving past the stated Cell cap returns `area_too_large` naming the cap, so a tool call cannot accidentally ask for the city
- [x] `obs_near` returns observations within a radius of a point and is `local` mode only; calling it in `public` returns `restricted_source`
- [x] no query accepts an arbitrary polygon — a caller with one resolves it to Cells itself
- [x] area answers carry the same version stamps as every other payload


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

**Register `assets_in_area` / `obs_near` in `query.QUERIES`** — an unregistered name
already raises `unknown_query`, and `area_too_large` / `restricted_source` are already in
`REASONS` waiting for you. Cell ids arrive and leave as H3 hex strings (above).

## Inherited from notify 03 (landed 2026-08-25, branch `notify03-exposure-of`)

**`exposure_of` is registered, so `QUERIES` has TWO entries now** and the shape you write
is unchanged:

    query("exposure_of", {"asset_id": "stn:611"}, root, mode="public") -> dict

    {"query": "exposure_of", "mode": "public",
     "asset":    {asset_id, kind, name?, cell?, complex_id?},          # 02's block, verbatim
     "exposure": {estimand, model_id, score_index, score_ref, score_severe,
                  surge_margin_ft?, flags: [...], modelled: bool},
     "versions": {assets_version, spine_version, label_version, score_version?}}

**No new `REASONS` entry was added and none is owed** — the frozen vocabulary is
unchanged, and `area_too_large` / `restricted_source` are still waiting for you.

**`versions()` gained a FOURTH stamp, `score_version`**, on any root that publishes
`gold/flood_exposure`. Your area payloads carry it for free. It is ABSENT (never null) on
a root with no exposure table, which is the same absent-never-null rule as everywhere
else — do not "normalise" it to a null to make the shape uniform.

**`unit(con, root, asset_id) -> tuple` is factored out of `events_for_asset`** and is the
one place `unknown_asset` is raised. It resolves identity ONLY: which registry rows are
Units is each query's own rule, and the two existing queries answer it from different
authorities (history = F05's `LABEL_KINDS`, score = F10's table membership), which is why
an entrance has a history and no score. If your area answer needs to say "this asset is
not scored", read that membership rather than re-typing a kind list.

## Forward-context from DESTINATION-PLAN.md (copied verbatim by the WAVE 5 GATE PART 2, 2026-08-25, from this ticket's summary line in waves/wave-3-plus.md)

**FROM DESTINATION-PLAN (2026-08-25), one line:** after flood-build 19 (wave 6) `silver/stormwater_extent` exists (scenario x horizon x category polygons). A scenario-as-area parameter for `assets_in_area` is a POSSIBLE later addition, not built here and not owed — Cell stays the only area key in v1.


## LANDED 2026-08-25 (branch `notify04-area-queries`) — the two call shapes

    query("assets_in_area", {"cells": ["882a1072c1fffff", ...]}, root, mode=...) -> dict
    query("assets_in_area", {"bbox": [west, south, east, north]}, root, mode=...) -> dict

    {"query": "assets_in_area", "mode": "public",
     "area":   {"cells": ["<h3 hex>", ...], "n_cells": N, "bbox"?: [w, s, e, n]},
     "n_assets": N,
     "assets": [{asset_id, kind, name?, cell, complex_id?, n_events, last_event_id?}, ...],
     "reason"?: "no assets in this area",
     "versions": {assets_version, spine_version, label_version, score_version?}}

    query("obs_near", {"asset_id": "cell:882a103827fffff", "radius_m": 500}, root,
          mode="local") -> dict      # or {"lon": …, "lat": …, "radius_m": …}

    {"query": "obs_near", "mode": "local",
     "point":  {lon, lat, radius_m, asset_id?},
     "n_observations": N,
     "observations": [{source, source_id, ts_utc, obs_ts_kind, cell?, depth_mm?, text?,
                       distance_m}, ...],          # nearest first
     "versions": {...}}

- `cells` takes H3 HEX STRINGS (a lone string is accepted as a one-element list); the int64
  is REFUSED by name (`missing_param`) rather than accepted, because it has already been
  corrupted by any JSON reader using doubles. Both forms may be given: the area is their
  union, which needs no precedence rule.
- **`CELL_CAP = 64`** Cells (~47 km²; the city is 4,113) and **`RADIUS_CAP_M = 2000.0`**
  metres (`RADIUS_M = 500.0` is obs_near's default) — both raise `area_too_large` naming
  the cap. The area cap is enforced on the RESOLVED Cell set, before any table is read.
- A bbox snaps to the Cells whose CENTROID it holds — the rule `ref/cell_zone` already
  uses — read from `ref/assets`' `kind='cell'` rows, whose lon/lat are exactly `ref/cells`'
  centroids (measured: max |delta| 0.0 over all 4,113). No second table, no second failure
  mode. A flipped box is normalised, not refused.
- Stations are NOT listed in an area (Carriers: `events_for_asset` refuses them and names
  the complex). `n_events` is the history `events_for_asset` would return for that asset,
  complex rollup included, and a test pins the two to agree.
- `REASONS` IS STILL UNCHANGED — `area_too_large` and `restricted_source` were already in
  it and are now raised; both are documented in `docs/read-api-contract.md`. An UNBUILT
  table (the empty-directory trap) is `version_unresolved` naming the table, raised in
  `view()` so every query gets it, not a globber traceback.
- **DuckDB `ST_Distance_Sphere` / `ST_Distance_Spheroid` take (LATITUDE, LONGITUDE)** and
  this project's geometry is CRS84 (lon, lat): handed a stored point they return a
  plausible WRONG number (143.5 m for a pair 248.5 m apart). `obs_near` measures through
  `EPSG:32618` (UTM 18N, metres) instead, which also answers for the MULTIPOLYGON rows
  (Sandy) that the point-only spheroid cannot.
