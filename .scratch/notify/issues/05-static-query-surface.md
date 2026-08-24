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
