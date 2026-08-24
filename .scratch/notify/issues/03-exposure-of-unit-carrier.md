# 03 — exposure_of and the Unit/Carrier rule

**What to build:** Ask how exposed a doorway is and get the published exposure object back
— with the Unit/Carrier distinction enforced, so nobody can ask a station for a score it
does not have. Spec: section 1 (complex grain); CONTEXT.md (Unit, Carrier); SEAM Q.

**Blocked by:** 02 — externally on flood-build 10 (`gold/flood_exposure`).

**Status:** ready-for-agent

- [ ] `exposure_of` returns score_ref, score_severe, score_index, surge_margin_ft and flags for a Unit, stamped with model_id / score_version
- [ ] a complex's answer is the max over its child entrances, matching F10's rule exactly
- [ ] a station returns `not_a_scored_unit` naming the complex to ask instead — stations are Carriers and are never scored independently
- [ ] a bus_stop and a Cell each answer directly
- [ ] no NULL score reaches a payload: F10's fallbacks guarantee coverage and reasons ride the flags
- [ ] the per-asset payload composes with 02's history — one asset, one answer, both stamped


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

**Your Unit/Carrier rule is already half-shipped.** `events_for_asset` raises
`QueryError("not_a_scored_unit", asset_id=..., kind=..., ask=<parent_asset_id>)` for any
kind outside `flood_labels.LABEL_KINDS` — reuse that reason and that `ask` detail key, and
reuse the complex rollup it already does (`parent_asset_id`, max depth, union of support)
instead of writing a second one. `score_version` / `model_id` join `versions()` when you
read F10's scores: today they are ABSENT (not null) because no score is read.
