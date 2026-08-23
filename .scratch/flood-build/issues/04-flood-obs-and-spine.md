# 04 — Flood observations and the event spine

**What to build:** `silver/flood_obs` (every label-grade flood observation in one table) and
`silver/flood_events` (the deterministic spine of dated flood events with UTC windows), with the
311 thresholds re-measured on the four-literal union and canaries on every frozen source literal —
so "during the event" means the same hours everywhere downstream. Spec: Labels and the event
spine; Testing seams 1 and 2.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] `silver/flood_obs` GeoParquet (~60K rows), label-grade sources only: 311 street/highway flooding points, FloodNet events from the curated Socrata event table (never the row-capped raw API), station-labeled alerts from ticket 02, USGS high-water marks, Sandy inundation polygons; columns source, source_id, ts_utc, obs_ts_kind {incident, report, alert}, geometry, Cell, depth_mm (nullable), text (nullable); covariate sources never enter
- [ ] the 311 descriptor set is FOUR exact literals — 'Street Flooding (SJ)', 'Highway Flooding (SH)' and their 2023-09 renames 'Flooding on Street', 'Flooding on Highway' — and the daily-count p99 triggers are RE-MEASURED on the union per era-dataset (nearest-rank), frozen as named constants with the era they were measured on (the original 97/84 were legacy-literal-only and biased low across the 2023-09..2026 overlap)
- [ ] spine triggers, any of: (a) 311 daily count ≥ frozen p99; (b) ≥ 1 station-naming alert flood event; (c) NOAA Storm Events flood types by county FIPS and the enumerated coastal zone names; (d) CO-OPS water level at the Battery or Kings Point ≥ that station's own NWS minor threshold, station datum both sides, two consecutive readings
- [ ] contiguous event-days merge; window = [NY-midnight of first day − 3 h, NY-midnight after last day + 3 h] as UTC hour_end bounds — never observation-derived; event class from Storm Events FLOOD_CAUSE where present, else trigger-based; Dec–Mar pluvial days at or below freezing reclass to snowmelt and leave the pluvial fit
- [ ] fixture: 2023-09-29 appears as an event-day under the four-literal union
- [ ] canary: each of the four 311 literals matches trailing-30-day rows, and every frozen source literal and endpoint answers — the build fails otherwise
- [ ] spine derivation is a pure function tested on fixtures; DuckDB contract tests on both written tables
