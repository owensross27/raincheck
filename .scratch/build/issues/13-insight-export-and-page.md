# 13 — Insight export and the page: cells, headline, zones from Gold

**What to build:** `make export` writes the insight files from Gold, the baseline, AORC precip and the ref layer
with the pure-SQL JSON writer, `make vendor` fetches the pinned MapLibre, and `make web` serves
one static page whose insight panel shows the footprint hexes coloured by wet/dry Speed ratio
per window and by storm hour with intervals, gates, hidden counts, estimands and the required
disclaimers - the real map on localhost. Spec: L (insight), I (analysis outputs, wet event);
Testing 14-1 (tier 1 twin on fixture Gold, tier 2 on the slice), 14-4.

**Blocked by:** 06

**Status:** claimed for next session (2026-08-23) - read spec L + this ticket +
research/14-serving-surface.md + research/14-serving-prototype/ before building.
Orientation findings from the claiming session: (1) DuckDB 1.5.5 spatial has
ST_AsGeoJSON / ST_SimplifyPreserveTopology / ST_ReducePrecision / ST_IsValid
(ST_AsGeoJSON takes no precision arg - reduce first); (2) the prototype's export is
pandas+h3 throwaway and its control is a single control day - the real export is
pure-SQL over ref/cells with the dry hour-of-week baseline; (3) chord-band r values
are at research/10-backfill-slice-and-speed.md:78-80 (class medians 1.164 under
3 m/s, 1.025 at 3-6, 1.016 above 10); (4) windows + school dates are constants in
raincheck/ref.py (WINDOWS, SCHOOL_FIRST_DAY, SCHOOL_CLOSED); (5) gates.py is the
tier-2 home for 14-1; suite baseline 136, web/ does not exist yet, .gitignore needs
web/files/ + web/vendor/ lines; (6) the one open design call: H_lo/H_hi for a single
storm hour has no within-hour scatter in Gold - derive the interval from the dry
same-hour-of-week bin's scatter recomputed from cell_hour_speed x the dry mask
(cell_hourofweek_baseline stores only pooled sums).

- [ ] one SQL text computes: per-Cell wet anomalies per window scored against the hour-of-week bin with 95% intervals clustered by wet event (spec's definition) and by service day as the sensitivity check; the two storm composites per fixed citywide hour against the window's dry baseline with the same interval gate; H_mm and H_lag from precip_cell_hourly src=aorc; W_ratio_ex_preschool from ref/calendar; the numeric chord band pair
- [ ] `cells.geojson`: one Feature per footprint Cell, geometry from ref/cells at 5 dp, id = hex Cell, wide properties per spec L, absent (never null) when unpublishable, no route breakdown; `headline.json` rows carry value, the literal estimand sentence, the median-Cell companion and its estimand, n_legs, n_cells, n_cells_hidden, band as [ratio, ratio_chord_upper]; `zones.geojson` 263 simplified zones; every query ORDER BY so re-export is byte-identical; explicit round(x, 3)
- [ ] the page: MapLibre 5.9.0 UMD vendored (v6 is ESM-only), no build step; layers W1/W2 wet-dry, Ida 02Z-08Z, 2023-09-29 10Z-21Z, dry baseline; fixed ramp 0.5..1.2; grey = property absent; the legend names the estimand and "rain: AORC hourly, hour-ending"; the preview sentence, the 2023 band-reaches-1.0 statement and n_cells_hidden beside every median figure; headline = citywide + median Cell + rain-lag curve; provenance strip; taxi zones as the ground; zone name in the tooltip from the export
- [ ] 14-1 tier 1 on a three-Cell fixture Gold: no null property, finite values, estimand + numeric band + hidden count on every row, byte-identical re-export; 14-1 tier 2 on the slice: feature count == publishable footprint Cells, fixture Cell 882a100895fffff has w1_dry > 0 and an Ida hour, 263 valid zones
- [ ] 14-4: the stdlib server answers 200 for the page, the two vendored files and cells/headline/zones; web/files and web/vendor are gitignored
