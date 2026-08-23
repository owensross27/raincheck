# 06 Asset registry design

Type: grilling
Status: resolved

## Answer

Resolved 2026-08-22 (measured live + local archive; 3-lens adversarial review
in `../assets/06-adversarial-verdicts.json`; Ross: yes to all). Draft history:
map session scratchpad; all counts below measured, not estimated.

**One table.** `ref/assets` at `data/ref/assets/` — one GeoParquet 1.1 file
(SRID 4326, crs omitted, POINT geometry named `geometry`), single sorted part
file per the ref-layer byte-identical rebuild gate, **20,544 rows** =
445 complexes + 496 stations + 2,120 entrances + 13,370 bus stops + 4,113
Cells. Columns: asset_id STRING pk, kind {complex, station, entrance,
bus_stop, cell}, name (NOT NULL except cell), geometry POINT, lon/lat DOUBLE,
cell INT64 (h3 res 8 of the point; identity for cell rows, whose geometry is
the ref/cells centroid), complex_id, parent_asset_id (station->complex,
entrance->complex), gtfs_stop_id ARRAY (station rows; entrance rows'
semicolon-multivalues split at ingest), daytime_routes + line + structure +
borough (station rows — structure stays at station grain, 9 complexes mix
values), entrance_type + entry_allowed + exit_allowed (entrances; exact
literals, "Easement - Street" spaced; 48 exit-only rows kept), feeds ARRAY +
pick_id ARRAY (bus stops), src_asof, frozen_at.

**Keys.** `stn:<complex_id>` (445); `sta:<gtfs_stop_id>` (496, verified 1:1
against the subway pick's location_type=1 stops, zero orphans);
`ent:<complex_id>:<lat>:<lon>` at 6 dp, no hash (measured unique 2,120/2,120;
the rounded-hash draft collided 59 St-Columbus Circle and Freeman St);
entrance complex_id derived from the stations join via gtfs_stop_id (corrects
10 misfiled rows), never the row's own field; `bus:<stop_id>` (13,370;
cross-feed shares are the same physical stop — median 9.8 m, max 147.7 m —
coords = arithmetic mean, order-free; name from lexicographically-first
feed); `cell:<h3>` (4,113). Key stability is a contract: rebuilds emit an
added/removed/moved key-diff; orphaning a gold/flood_labels or
silver/asset_features row is a build FAILURE. The 9 shared doorways serving
two complexes stay as two rows (one per complex).

**Score units vs carriers.** Published units: complex, bus_stop, Cell.
Stations and entrances are join/feature carriers (station: subwaydata.nyc
delay join + route filter + structure; entrance: 07's elevation, display).
**Radius-attachment targets: entrance, bus_stop, cell rows ONLY** — complex/
station points never take the 100 m circle (24.4% of entrances sit >100 m
from the complex centroid; 19/445 complexes have zero entrances inside their
own circle). Complex positive = OR over child entrances, plus alert-station
labels landing as ONE row at `stn:<complex_id>` with label_support='station'
(not fanned to entrances — mean 4.8x inflation for zero information).

**Amendments to 01** (recorded as a comment there): (a) negative generator
works verbatim over the mixed-kind table with a per-kind grain filter (score
units only: complex, bus_stop, cell — ~1.02M pairs at ~57 events, never
materialized); (b) label_support renamed **{radius, station, cell}** (old
enum had no value for bus stops); (c) label_version gains **assets_version**
= sha1 over sorted (asset_id, kind, lat, lon); (d) alert labels land at the
complex row, entrances inherit for display.

**Street segments: Cell for v1, measured.** LION/CSCL = 122,256 segments
(`inkn-q76z`, live) = 7.7x the point registry, for zero label sources not
already served at Cell grain. The map's parked "bus alerts as segment labels"
item is retired for v1 (no segment grain to starve). Revisit trigger stays:
street-level display consumer, or 08 finds Cell-grain CSI vs FloodNet point
truth too coarse.

**Build.** One more builder in `src/raincheck/ref.py` under `make ref`
(Sedona write, DuckDB h3 oracle with ST_ReducePrecision 1e-9, tested in
tests/test_ref.py). Bus stops read from the pipeline's existing per-pick
stops tables pinned by pick_id sha1 (five feeds 2026-06-23, staten_island
2026-07-28; subway static 2026-08-07). Socrata sources snapshotted to
`data/archive/subway/i9wp-a4ja_2026-08-22.json` (assert 2,120) and
`39hk-dx4f_2026-08-22.json` (assert 496), fetched only when missing —
`make ref` never calls SODA. Blocking assertions: asset_id unique 20,544;
entrance keys 2,120; 445<->445 complex join zero orphans; **every asset cell
in ref/cells** (measured 15,935/15,935 point assets today; fail, never
null); byte-identical rebuild.

**Known biases handed to 08** (obligations added there): bus-stop churn —
the 2022 Bronx and 2025 Queens redesigns sit inside the label era and bus
stops are 81% of point assets (sensitivity report required); label fan-out —
one 311 point mints ~2.8 bus-stop and ~4.7 entrance correlated positives
within 100 m; effective-sample caveat — 13,370 bus stops occupy 1,035 Cells
(mean 12.9/Cell, max 67). Flagged to 07: sampling universe = all radius
targets (~15,500 points, ~16 getSamples POSTs/epoch), samples land in sibling
`silver/asset_features` keyed asset_id (ref/assets is immutable). SIR in
scope: 21 complexes / 66 entrances, alert path proven by 02.

## Comments

2026-08-22 — implication discovered by 07's review (no change to the table):
the 4,113 Cell rows are the bbox tiling copied from ref/cells, and a
measured ~2,759 of them touch no NYC land (ref/cell_zone: 3,043 centroids
in no taxi zone; 1,354 cells intersect any zone). ref/assets stays as
built — the precip spine wants the full tiling and 01's anti-join
generator still works verbatim — but the SCORED cell universe must be
restricted to land/asset-bearing cells or the negative class is silently
diluted. Restriction is delegated to 08 (obligation posted there).
Related: 07 put no cell rows in silver/asset_features (cell elevation =
read-side aggregate over member point assets).

## Question

The three scored asset universes and their canonical tables: subway stations/
complexes + the 2,120 entrances (`i9wp-a4ja`, `39hk-dx4f` with its `structure`
field), bus stops (from the static GTFS picks the archiver already captures —
which pick, how versioned), and street segments (LION? which release, which
segment key, vs the taxi-zone/Cell shortcut of scoring Cells instead of
segments). Keys, geometry storage per pipeline-09 conventions, and the mapping
of every asset to its H3 res-8 Cell so the precip spine joins for free. Decide
whether "street segment" survives as a first-class asset or collapses to
Cell-grain for v1 (ponytail question — segments triple the asset count and 311
is the only segment-grain label source).
