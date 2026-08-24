# 02 — Query core: one entry point, events_for_asset, and the licence boundary

**What to build:** Ask the dataset for one Unit's flood history and get back a stamped,
licence-safe answer. This is the tracer bullet for the whole query path: the single entry
point every later consumer renders over, its boundary mode, its version stamps and its
typed errors, proven end to end on one query. Spec: sections 1 and 2; SEAM Q.

**Blocked by:** None in this effort — externally on flood-build 05 (`gold/flood_labels`).

**Status:** ready-for-agent

- [ ] one query entry point taking (query name, params, data root, boundary mode) and returning a JSON-able dict; `public` is the default mode, so a caller that forgets is safe
- [ ] `events_for_asset` returns the Unit's attached events with their UTC windows, read from `gold/flood_labels` joined to `silver/flood_events` — it NEVER re-attaches `silver/flood_obs` to `ref/assets`, because F05 owns that join
- [ ] an asset with no attached events returns an explicit empty event list with a stated reason (not an absent key, not an error); an unknown id raises `unknown_asset`
- [ ] every payload carries its version stamps (assets, spine, label, plus score where one is present); an unresolvable stamp raises `version_unresolved` rather than returning an unstamped answer
- [ ] no null values in any payload — an unpublishable value is an ABSENT KEY, per the repo's pure-SQL JSON convention
- [ ] `public` returns per-source observation COUNTS; `local` may return the rows behind them
- [ ] the fixture root contains real FloodNet, MTA-alert and subwaydata-derived rows, and the boundary test asserts `local` returns them while `public` does not — a fixture with no restricted rows fails this criterion, because the test would pass for the wrong reason
- [ ] the fixture is built so that the wrong join (flood_obs to ref/assets) returns a detectably different answer than the right one
- [ ] reads go through the existing DuckDB helpers (UTC session, `union_by_name`, hive keys as strings); no Spark on the read path
