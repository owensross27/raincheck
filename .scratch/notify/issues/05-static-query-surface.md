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
