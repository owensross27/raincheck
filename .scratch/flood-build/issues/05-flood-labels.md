# 05 — Flood labels: positives only, negatives at read

**What to build:** `gold/flood_labels` — positives-only labels attaching observations to assets under one
attachment rule, plus the negatives generator that anti-joins at read under per-source coverage
calendars and anachronism rules, so a Unit is only ever "dry" where some source could actually
have seen it flood. Spec: Labels and the event spine; Testing seam 1.

**Blocked by:** 01, 04

**Status:** ready-for-agent

- [ ] `gold/flood_labels` POSITIVES ONLY: asset_id, event_id, Cell, source-mix bitmask, depth where measured, label_support {radius, station, cell}
- [ ] attachment: one constant RADIUS_M = 100 m geodesic for every point source, identical everywhere; Cell-grain by H3 equality; polygons by contains/intersects; alert stations land as ONE row on the complex (entrances inherit for display only)
- [ ] negatives generator (a read-side function, no stored negative rows): anti-join under per-source coverage calendars — 311 continuous; alerts effectively 2016+ minus the 2020-04 hole and the 2026-06-30..08-15 Socrata-to-archiver dark gap; FloodNet 2020-11-16+ — plus anachronism rules (frozen station-opening list; bus-stop pairs restricted to events from 2020 on)
- [ ] label_version = sha1 over source as-of dates, frozen thresholds, RADIUS_M, and assets_version
- [ ] the artifact names its estimand: `flooded_reported` — where flooding was REPORTED, not where water necessarily stood — carried as table metadata and in the schema docs
- [ ] fixture: the 149 St rename resolves to the right complex
- [ ] DuckDB contract tests: grain uniqueness, no stored negatives, bitmask sanity, version chaining; negatives generator tested as a pure function on fixture calendars

## Inherit from flood-04's build (2026-08-23, recorded by the orchestrator)

Chain label_version on flood-04's spine_version (plus assets_version). spine_version
already covers the re-measured 311 thresholds, vocabularies, the window rule and the
source as-of stamp — so ticket 18's alternate threshold universes stamp differently by
construction, and labels never silently mix spines.
