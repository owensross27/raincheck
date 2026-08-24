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

## Fix pass, 2026-08-24 — the radius "bug" was the fixture, not the cut

Branch `flood05-radius-fix`, worktree `/Users/ross/raincheck/.claude/worktrees/flood05fix`.

**BUG 1 — `test_radius_attachment_is_geodesic_and_cuts_at_one_hundred_metres`. The code is
correct; the fixture was mis-placed.** Measured, not argued (pyproj `Geod(ellps="WGS84")`,
independent of Spark/Sedona):

| fixture row | to 311 report 24283048 | to its NEAREST observation |
|---|---|---|
| `ent:fixture-inside-95m` (as planted) | 94.77 m | **84.06 m** — 311 report 24284319 |
| `ent:fixture-outside-140m` (as planted) | 139.66 m | **59.31 m** — 311 report 24284319 |

Both rows were planted due north of report 24283048, and a second 311 report of the same
Sandy day (24284319, 2012-10-29T16:15) sits 56.7 m east and 156.9 m north of that report —
i.e. 59.31 m from the "outside" row. It attached because it IS inside 100 m of a real
observation. An outside fixture pins nothing unless it is outside the radius of EVERY
observation, not merely of the one it was measured against.

**Proof the 100 m geodesic cut itself is sound.** Rebuilt the fixture label root and
recomputed the entire radius branch independently: WGS84 geodesic distance for every
in-window point observation (141) against every radius-kind asset (2,060) — 289,260
candidate pairs — keeping `d <= RADIUS_M`. Result: **92 pairs by pyproj, 92 pairs in the
built table, zero disagreement in either direction.** `ST_DWithin(oe.geometry, a.geometry,
100.0, true)` is doing true geodesic metres; there is no planar fallback, no unit factor,
no H3 prefilter standing in for the cut. On the real fixture pairs the boundary sits
between 99.80 m (farthest attaching) and 100.07 m (nearest non-attaching).

**The fix: re-plant, do not re-assert.** Both rows moved due SOUTH of report 24283048 —
bearing 180 is the only clean quadrant here — at exactly 95.000 m and 140.000 m. Nearest
observation of any kind is then 95.00 m (24283048) for the inside row and 139.45 m
(24281879) for the outside row, so the pin is real from both sides: 95.00 attaches,
139.45 does not. `tests/fixtures/flood_labels_assets.parquet` was patched IN PLACE through
its own original writer (pyarrow + zstd, one row group) rather than regenerated through
Spark — a Sedona geoparquet rewrite changed the codec to snappy and added `bbox`/`crs` to
the `geo` metadata, which is drift the diff does not need. Schema and metadata compare
identical to the committed file and exactly two of 3,112 rows differ: `lat`, `geometry`
(shapely WKB, byte-identical to Sedona's for unchanged rows), `geometry_bbox`, and `cell`
(recomputed with Sedona `ST_H3CellIDs(ST_Point(lon, lat), 8, false)[0]` — both rows crossed
into new res-8 cells). The assertion `got == {"ent:fixture-inside-95m"}` is untouched, and
`RADIUS_M = 100.0` is untouched.

**BUG 2 — the >400 s hang. SUPERSEDED DIAGNOSIS (wave-1 gate, 2026-08-24 landing): it was
a DEADLOCK, not the polygon.** The first pass blamed `duck.table(...).arrow()` dragging
Sandy's 2.3M-vertex footprint through Arrow and narrowed the columns — and the narrowed
version still hung, at 0% CPU, because column width was never the mechanism. On this
DuckDB, `rel.arrow()` returns a LAZY `RecordBatchReader` on the relation's own connection;
the test registered two unconsumed readers back into that same connection and joined them,
so the join's Arrow scan blocks pulling a batch whose production needs the connection
context the join itself holds. Proven both ways at the gate: the register-readers shape
deadlocks against the identical built root until killed; projected `create_view`s over the
same relations return in 0.2 s. The test now builds `o`/`e` as views
(`rel.select(...).create_view(...)` — `rel.query("t", ...)` is also unusable here, its
lazy shared virtual name `"t"` rebinds to the last relation). Geometry still never enters
the join; assertion unchanged. The repo's only other `.arrow()` call sites
(`flood_impact.py:300,339`) consume their reader immediately via `.read_all()` and do not
carry the bug.

**Docstring/assertion mismatch, recorded not corrected.** The test's name and first line
say "every label sits inside its own event's window"; the assertion says "no observation
lands in two event windows". The second is the PRECONDITION for the first — it is what
makes `oe` assign each observation to exactly one event — but it is narrower than the
name, and it never reads `gold/flood_labels` at all. Left as-is per instruction and
annotated in the test docstring. If a later ticket wants the literal claim, it needs a
label-grain check that carries the observation's ts through to the label row.

**VERIFIED at the wave-1 gate, 2026-08-24.** The un-run caveat that stood here is closed:
after the deadlock fix above, the full 23-test file ran green in 8.69 s at the landing
(its first complete execution ever — the pre-fix file had never finished a run). The
re-planted fixture passed the radius test exactly as the pyproj arithmetic predicted.
