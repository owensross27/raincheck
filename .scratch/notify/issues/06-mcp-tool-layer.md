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
