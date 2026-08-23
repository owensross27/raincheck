# 01 — Asset registry: every Unit and Carrier in one table

**What to build:** `ref/assets` — one GeoParquet registry holding every flood Unit (complex, bus stop, Cell)
and Carrier (station, entrance) with stable natural keys and a byte-identical rebuild, plus the
frozen `cells_scored` universe — so every later score and label joins the same 20,544 rows every
time. Spec: Asset registry; Testing seam 1.

**Blocked by:** None — can start immediately

**Status:** resolved 2026-08-23

- [x] `ref/assets` GeoParquet 1.1, EPSG:4326: 20,544 rows = 445 complexes + 496 stations + 2,120 entrances + 13,370 bus stops + 4,113 Cells; a kind column separates score Units (complex, bus_stop, cell) from Carriers (station, entrance — located and aggregated, never scored independently)
- [x] no-hash natural keys: entrance = corrected complex id + 6-dp coordinates; bus-stop coordinates are the cross-feed mean; the key-stability contract runs a rebuild key-diff and it is empty
- [x] byte-identical rebuild off pinned Picks and snapshotted source pulls: two consecutive builds produce byte-equal files; `assets_version` stamped
- [x] `cells_scored` = Cells intersecting a non-EWR taxi Zone UNION Cells containing a scored point asset (~1,351; the ~2,759 no-NYC-land Cells are excluded); the count freezes at build; the permanently-NULL AORC Pixels are asserted disjoint from it and the same coverage assertion runs against the MRMS crosswalk
- [x] the 19/445 complexes with no entrance inside their own 100 m circle are asserted covered by the station→complex path (radius attachment targets entrance, bus_stop and cell rows only)
- [x] Unit and Carrier graduate to CONTEXT.md's glossary
- [x] DuckDB contract tests over the written file in the existing ref test style: grain uniqueness, frozen counts, key stability, cells_scored disjointness

## Comments

**2026-08-23 (resolution):** built as one more builder in the ref layer (`build_assets`, run by
`make ref` after the existing tables). Measured at first real build and now frozen:
`cells_scored = 1,351` (exactly the design's ~1,351); permanently-NULL AORC cells = 168
(= 4,113 − 3,945), disjoint from cells_scored, and the gate treats absent-entirely and
present-but-all-NULL alike; `assets_version = d3c7b0f371a4fcef196588886a2058f755ee1da0`
(sha1 over sorted (asset_id, kind, lat, lon) — recomputed on demand, not stored, so the
table bytes stay version-free). The 39hk-dx4f stations snapshot was fetched once (496 rows)
beside the existing i9wp-a4ja (2,120); both now pinned with a 5,000-row SODA truncation
guard. Byte-identity caveat, same as every ref table: rebuilds are byte-identical within a
JVM session (the repo's existing gate); across sessions parquet-mr permutes the footer's
encodings-set ordering (~27 bytes, data pages identical) — content identity is what
`assets_version` + the key-diff certify. 15 new tests in the assets test module; full suite
106 green. Complex naming rule (not in the design, chosen here): sorted distinct member
station names joined with " / "; complex borough NULL when members mix boroughs.
