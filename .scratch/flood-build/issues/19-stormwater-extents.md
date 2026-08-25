# 19 — The four scenario extents, kept

**What to build:** DEP's rainfall-scenario flood maps stop being thrown away. `features.py`
reads ONE scenario (`SW_SCENARIO`, Moderate/current), reduces it to per-Cell area shares in
`silver/cell_stormwater`, and discards every polygon. This ticket keeps the polygons:
`src/raincheck/stormwater_extent.py` + `make stormwater-extent` build
`silver/stormwater_extent/` (GeoParquet, EPSG:4326), and `make geo` exports the
current-sea-level scenarios to `web/files/geo/` behind a new `geo` publish family.

**Gate:** NONE. The input is `data/snapshots/stormwater/NYCFloodStormwaterFloodMaps_2026-08-23.zip`,
on disk and sha256-pinned at `features.SW_ZIP_SHA256`.

**Source:** `DESTINATION.md` §3.B · `DESTINATION-PLAN.md` §1 D2/D3 ·
`.scratch/flood/issues/04-stormwater-geodata.md` + `research/flood-04-stormwater-geodata.md`
(research resolved 2026-08-22 — the service, the licence and the categories are settled and
were NOT re-researched).

**Status:** in-progress

- [ ] `silver/stormwater_extent/` — one row per polygon: `scenario` · `horizon` ·
      `rain_in_hr` · `category` · `poly` · `geometry` · `src_asof` · `zip_sha256`
- [ ] the `.gdb`s open through the same code path `features.flood_parts()` uses, and the
      33.8 MB sha256 is checked ONCE per run (`features.stormwater_zip`)
- [ ] `features_version` does not move — asserted before and after every real-root build
- [ ] `not_analyzed` is its own category, never absence
- [ ] `make geo` exports the CURRENT-sea-level scenarios only (D3)
- [ ] publish family `geo`, `contract.PROMISE` unbumped, documented in `docs/read-api-contract.md`
- [ ] a `checks.Row` batch `stormwater_extent` under `<root>/checks/check=stormwater_extent/`
- [ ] the attribution string, for frontend2 03 to render

---

## MEASURED 2026-08-25 — three things the box could not have known

Everything in this section was measured on the pinned snapshot in this session. Two of the
three change what can ship, so they are at the top rather than in a footnote.

### 1. THE `limited` SCENARIO CANNOT BE READ FROM THE PINNED SNAPSHOT

`NYC_Stormwater_Flood_Map_Limited_Flood_1_77_inches_per_hr_with_Current_Sea_Levels.gdb`
stores its one feature class as a **compressed FGDB table**: `a00000009.gdbtable.cdf`
(2,463,595 B, magic `32 46 44 43` = `2FDC`), with **no `a00000009.gdbtablx`** — the row
index the other three geodatabases have. The other three are ordinary uncompressed FGDBs.

GDAL's `OpenFileGDB` driver cannot decompress CDF, and the two GDAL versions available
here disagree about how to say so:

| GDAL | how it arrives |
| --- | --- |
| **3.8.5** (the one `duckdb_spatial` bundles — the repo's ONLY GDAL) | opens the dataset, returns **ZERO features, no error, no warning** |
| **3.12.4** (`pyogrio` 0.13.0, a throwaway venv, used to diagnose only) | **refuses the dataset**: `not recognized as being in a supported file format`, with the warning `... a00000009.gdbtable.cdf file using Compressed Data Format (CDF) that is unhandled by the OpenFileGDB driver, but could be handled by the FileGDB driver` |

The `FileGDB` driver is Esri's proprietary SDK. It is not a dependency here and would not
be one. And flood 04 already measured that **no queryable service exists anywhere** for
`9i7c-xyvv` — the pinned zip IS the access path.

So `scenario = limited` is not in the table and `files/geo/stormwater-limited.geojson`
does not exist. The 3.8.5 behaviour is the dangerous half: a reader that trusted it would
have published an EMPTY Limited extent that renders as "1.77 in/hr floods nothing". The
build refuses a zero-row read outright, and only the dataset named in
`stormwater_extent.UNREADABLE` is allowed to be absent — as an INCONCLUSIVE check row that
names CDF, never as an OK and never as silence.

**To close it, someone has to supply a differently-encoded source** — a DEP re-publish, or
a one-off conversion through a driver that reads CDF — and re-pin it. That is not a retry.

### 2. THERE IS NO CURRENT-SEA-LEVEL `extreme` SCENARIO, SO D3 EXPORTS FEWER FILES THAN THE BOX NAMES

DEP publishes exactly four scenarios and only TWO of them are at current sea level
(`DESTINATION.md` §3.B's own table says so):

| scenario | rain | horizon | readable | exported |
| --- | --- | --- | --- | --- |
| `limited` | 1.77 in/hr | `current` | **no — CDF** | — |
| `moderate` | 2.13 in/hr | `current` | yes | **yes** |
| `moderate` | 2.13 in/hr | `2050` | yes | no (D3) |
| `extreme` | 3.66 in/hr | `2080` | yes | no (D3) |

The box asks for `stormwater-limited.geojson`, `-moderate` and `-extreme`, "current horizon
only". Those two halves contradict each other: `extreme` exists ONLY at 2080 sea level, and
the same box says "2050/2080 stay in the table and off the host". D3's prose is the
decision and gives the reason — *"Climate projections beside a live rain rate invite exactly
the 'might flood' over-read"* — so the RULE was kept and the FILE LIST was not: **`make geo`
exports every `horizon = 'current'` row and nothing else.** Today that is one file.

The export is derived from the table (`WHERE horizon = 'current'`), not from a list of three
names, so `stormwater-limited.geojson` appears with no code change the moment §1 is closed.

**This is a decision worth Ross's eye** (it is the served surface, not an implementation
detail): shipping `extreme` would put a 2080 climate projection on the public host, which
D3 forbids in as many words. Not taken here.

### 3. THE SLR SCENARIOS CARRY A THIRD CODED CATEGORY

`features.SW_CATEGORY = {1: "nuisance", 2: "deep"}` is the whole coded domain for the
current-sea-level scenarios. The two SLR scenarios add **code 3**, and the FGDB's own
coded-value domain (read out of `GDB_Items`) names it:

```
<CodedValue><Name>Nuisance Flooding (greater or equal to 4 in. and less than 1 ft.)</Name><Code>1</Code></CodedValue>
<CodedValue><Name>Deep and Contiguous Flooding (1 ft. and greater)</Name><Code>2</Code></CodedValue>
<CodedValue><Name>Future High Tides 2050</Name><Code>3</Code></CodedValue>          <- 2050 gdb
<CodedValue><Name>Future High Tides 2080</Name><Code>3</Code></CodedValue>          <- 2080 gdb
```

flood 04 saw "Future High Tides 2050" as a separate *display sublayer* on the tiled
MapServer and its Unverified section says plainly that the in-`.gdb` schema was never
opened. It is a CATEGORY, not a layer. `features.py` would raise
`unknown Flooding_Category 3` on either SLR scenario — it never reads them, so nothing is
broken today, and `features.py` was not touched.

`stormwater_extent.CATEGORY` is `features.SW_CATEGORY` plus `{3: "future_high_tides"}`,
derived from the constant rather than retyped. It only ever appears on `horizon` 2050/2080
rows, which never export, so the served `category` domain is exactly
`deep | nuisance | not_analyzed` as the box requires.

---

## The attribution string — for frontend2 03 to render

DEP's stormwater flood maps are NYC Open Data (Socrata asset `9i7c-xyvv`, terms in flood
04's asset). One line, to be rendered wherever these layers are drawn:

> Stormwater flood extents: NYC Department of Environmental Protection, NYC Stormwater
> Flood Maps (NYC Open Data `9i7c-xyvv`), snapshot 2026-08-23. Planning-grade design-storm
> modelling — not an observation of water and not a site-specific determination.

It is also a top-level `"attribution"` member on every exported FeatureCollection, so the
credit travels with the payload and not only with the page.

**NOT in scope and it never enters `files/`:** the DEC CSO outfall layer flood 04 also
verified. Its licence permits fetch-and-use and **prohibits secondary distribution**, so it
may inform a derived covariate and may never be republished.

## The second half of the "not analyzed" refusal

`features.sample()`'s docstring refuses to impute DEP's exclusion mask to "no flooding".
This table carries the mask as `category = not_analyzed` POLYGONS, per scenario, so a
consumer can draw it. Same recipe as `features.build()`, reused rather than re-derived:
`shapely.union_all(mask_polygons(root)).difference(<that scenario's modelled classes>)` —
the mask only ever claims ground no flood class claims, which keeps the categories disjoint
so a renderer can draw them in any order.

The mask comes from the FeatureServer snapshot under `<root>/snapshots/stormwater/`
(16,856 PLUTO lots, already fetched, `features.mask_polygons`), not from the geodatabases.

## Forward context

- **frontend2 03** renders these files — exact keys, categories, sizes and the attribution
  string are written onto its ticket file.
- **flood-build 20** brackets a live MRMS rate against `rain_in_hr` — the three literal
  intensities and the table path are written onto its file.
- **orch 13** carries the GX suite for this batch (orch 10 landed first and deliberately
  wrote none) — the exact `CHECK_COLUMNS` are written onto its file.
- **notify 04** — a future `assets_in_area` could take a scenario as an area. Not built here.
