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
