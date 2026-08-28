# frontend4 03 — bronze live-export carries cell, rain, and the agency's delay

Status: ready-for-agent
Spec: `.scratch/frontend4/spec.md` (F3a). Charter: `.scratch/frontend4/charter.md`
(option (a), taken).
Blocked by: none.
Files: `src/raincheck/live_export.py`, `tests/test_live_export.py`.

## What this builds

`make live-export SOURCE=bronze` emits vehicles carrying `cell` (H3 r8 lower-hex, the
spelling `cells.geojson` keys on), `mm_1h` + `precip_valid_ts` (from `live/precip_cell`),
and `trip_delay_s` (the agency's own number, off `archive/tu`) — so the fleet coloring
works before the stream revives. The `live` source path is untouched.

## MUSTs

1. **`enrich_bronze(con, root, now)`**, called from `tick()`/`prepare()` when
   `source == "bronze"`, replacing the three NULL columns in `q`:
   - `cell`: fetch `(vehicle_id, lon, lat)` from `q`, compute the int64 H3 r8 cell via
     the existing shapely-STRtree seam — `flood_panel.cell_index()` / `cell_of()`
     (point-query then `covers`-confirm; the STRtree predicate-direction trap is solved
     there — read those ~20 lines before wiring, do not re-implement). Register a temp
     `vcell(vehicle_id, cell)` and rebuild `q` with the join. `_prop_expr` already
     publishes `lower(to_hex(cell))` — do not add a second spelling.
   - `mm_1h` / `precip_valid_ts`: join `<root>/live/precip_cell` mirroring
     `enrich.with_live_precip` (`src/raincheck/enrich.py:108-141`) semantics EXACTLY:
     newest `valid_ts=` string hive partition <= the wall clock (lexicographic max),
     newest `fetched_at` wins per `(cell, valid_ts)` — the table holds several rows per
     (Cell, hour) by design. Projection + predicates INSIDE the read statement
     (`read_parquet(...)` with the filter in-statement — the memory-bounded-pod rule;
     this module runs in the 768Mi live pod one day).
   - **Failure containment: enrichment is garnish.** Missing/unreadable `ref/cells` or
     `live/precip_cell` -> the three keys stay ABSENT and the tick stays healthy
     (mirror `enrich.py:103-105`). Rule 3 (a failed tick writes meta error and leaves
     live.geojson alone) applies only to the FLEET read, unchanged.
2. **Bronze `trip_delay_s`**: in `_next_stop_sql`'s bronze branch, replace
   `NULL::BIGINT AS trip_delay_s` with `max(trip_delay_s)` over the latest fetch's rows
   (trip-level, identical across a fetch's stop rows; pre-era parts read NULL via
   `union_by_name` -> absent key). Update the module docstring's bronze description.
3. **Era coverage check (verify, don't assume):** confirm whether `eras.READERS` /
   `eras.ERA_COLS` (`src/raincheck/eras.py`) cover the bronze TU read this module does;
   if `trip_delay_s` is an era column not asserted for this reader, register it. Record
   the finding either way in your entry.
4. **Tests** (`tests/test_live_export.py`, own-module):
   - REWRITE `test_bronze_carries_no_cell_precip_or_trip_delay` (`:340`) to the new
     contract. The fixture gains: a `ref/cells` tree with the fixture Cell's real
     polygon (derive from the existing `CELL = 613229522952650751` /
     `CELL_HEX = "882a100895fffff"` oracle — h3 is a test-only DuckDB extension per
     `flood_panel.py:325-327`, or plant a polygon that `covers` the fixture lon/lat),
     and a `live/precip_cell` tree with: the target partition holding TWO rows for the
     Cell (older `fetched_at` decoy with a DIFFERENT mm value — the data must
     discriminate the selection), plus a DECOY newer-than-`now` partition that must NOT
     be picked. Assert: `p["cell"] == CELL_HEX`; `mm_1h` equals the newest-fetch value;
     `precip_valid_ts` names the target partition; `n_in_rain_cells` counts correctly
     at the `RAIN_MM` boundary (fixture mm values must be non-degenerate — not 0, not
     exactly equal on both sides).
   - New: absent `ref/cells` -> `cell`/`mm_1h`/`precip_valid_ts` absent, tick healthy
     (`error is None`); absent `live/precip_cell` -> `cell` present, precip keys
     absent, tick healthy.
   - New: bronze `trip_delay_s` present and equal to the latest fetch's value;
     a pre-era TU part without the column -> key absent (the existing union_by_name
     fixture shape).
   - Keep every existing pin green: the wall-clock recency rule, the snapshot-clock
     prediction, absent-keys-never-null, the 20-min window, the failed-tick meta.
5. **Fixture clock discipline**: the existing fixtures pin `now`; keep every new
   assertion against the pinned epoch, never the wall clock.
6. **Mutation round** (standing rules): at minimum — oldest-fetch-wins flip (must be
   killable BY NAME given the decoy row), future-partition accepted, enrichment raise
   propagating to the tick, `covers`-confirm dropped, `trip_delay_s` from the wrong
   fetch. Record kills; a survivor is a claim about the harness until proven.

## Refusals

- No change to the `live` path, `RAIN_MM`, `PROPS`, the recency/snapshot-clock rules,
  or `swap()`/`once()` error contracts.
- No python `h3` dependency, no DuckDB h3/spatial extension in the module (test-only
  extensions stay test-only), no Sedona/Spark import (this is the 30 s DuckDB loop).
- No meta.json schema change (the existing counts light up on their own).

## Protocol

Worktree at `/Users/ross/raincheck-wt/frontend4-03`, branch
`frontend4-03-bronze-cell-rain`, own-module tests only
(`RAINCHECK_ARCHIVE_ROOT=/Users/ross/raincheck/data` for any real-root check; the
fixtures are tmp-root and need nothing), never the full suite, no pin commits. Commit
explicit paths, push, RUN-LOG entry + forward-context (ticket 04 and the gate read your
entry: say the exact keys bronze now emits and the containment rule).
