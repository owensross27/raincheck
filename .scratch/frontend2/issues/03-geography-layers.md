# 03 — The geography layers: routes and flood zones

**What to build:** the two geography layers DESTINATION §1 asks for — route lines
(DESTINATION-PLAN D1: a route SEGMENT is a Cell crossing) and DEP's rainfall-scenario
flood extents. Box: `DESTINATION-PLAN.md` §2.

**Gate:** frontend2 01 (LANDED, `779e359`) + flood-build 19.

**Status:** not-started — this file exists so far only to carry what 19 measured.

---

## FROM flood-build 19 (2026-08-25, branch `floodbuild19-stormwater-extents`) — the flood-zone half, measured

### The files, and there is exactly ONE of them today

Publish family **`geo`** — a TREE family, prefix `files/geo/`, `public, max-age=300`,
written by `make geo`. It is a tree and not a file list on purpose: the served set is
DERIVED from `silver/stormwater_extent` (`WHERE horizon = 'current'`), so it grows without
a code change. Fetch what the family holds; do not hard-code a list of three names.

| key | bytes (raw) | features |
| --- | --- | --- |
| `files/geo/stormwater-moderate.geojson` | **4,607,370** (4.4 MiB) | 3 |

**`files/geo/stormwater-limited.geojson` DOES NOT EXIST**, and it is not an oversight
you can wait out. Its geodatabase stores its feature class in Esri's compressed CDF
container, which the open `OpenFileGDB` driver cannot decompress — GDAL 3.8.5 reads it as
ZERO features with no error at all, and GDAL 3.12.4 refuses the dataset outright. There is
no queryable service for this data. Closing it needs a differently-encoded source, re-pinned.

**And there is no `-extreme` either.** DEP publishes the 3.66 in/hr Extreme scenario only
at 2080 sea level, and DESTINATION-PLAN D3 keeps sea-level-rise horizons off the public
host — a climate projection drawn beside a live rain rate reads as a forecast of tonight.
The 2050 and 2080 rows are in the table and off this host. **If a design decision ever
reopens that, it is Ross's, not a renderer's.**

So: today the flood-zone toggle is ONE scenario. Write the UI so a second one appearing is
a data change, not a rewrite.

### The payload shape

```json
{"type": "FeatureCollection",
 "attribution": "...",
 "features": [ {"type": "Feature",
                "properties": {"scenario": "moderate", "horizon": "current",
                               "rain_in_hr": 2.13, "category": "deep",
                               "n_polygons": 6921},
                "geometry": {"type": "MultiPolygon", "coordinates": [...]}} , ... ]}
```

One Feature per category, geometry a MultiPolygon — per-polygon Features would have added
~2.6 MB of envelope for identical geometry. Coordinates are lon/lat (CRS84) at 5 dp.
Features are ordered by `category`.

**THE THREE CATEGORIES, and the third one is the one that matters:**

| `category` | DEP's own name | n_polygons |
| --- | --- | --- |
| `deep` | Deep and Contiguous Flooding (ponding ≥ 1 ft) | 6,921 |
| `nuisance` | Nuisance Flooding (≥ 4 in, < 1 ft) | 16,866 |
| `not_analyzed` | Area not included in analysis | 1,387 |

**`not_analyzed` MUST be drawable, and it must not be drawn as dry.** It is DEP's
exclusion mask — rail corridors, large lots, open space, LTCP gaps — and the whole flood
chain refuses to impute it to "no flooding" (`features.sample()`'s docstring, and this
table carries it as polygons for exactly this reason). A legend that shows two flood
depths and silently omits the mask tells the reader that everything unpainted was modelled
and found dry, which is false. Give it its own swatch (hatch or grey, not a third depth
ramp) and its own legend line. The categories are DISJOINT, so you may draw them in any
order.

### Size, said out loud with the number

**4.4 MiB raw for one toggle**, against `cells.geojson`'s 2.3 MB on first paint. Nothing in
this repo compresses today and the `Content-Encoding: gzip` curl is still a [YOU] item, so
that is the number to plan against; at a typical 4-5x it would be ~1 MB behind an edge that
gzips. Two things were considered and NOT taken, so you do not have to re-derive them:

- **Splitting by borough does not help you.** The toggle draws the whole city, so five
  files are five requests for the same bytes. It only pays if a consumer ever draws one
  borough — say so if you build that, and it is a table query, not a re-cut.
- **Simplifying harder is the lever that works.** `stormwater_extent.TOLERANCE_M` is 5.0 m
  (0.12% of modelled area lost, 19.7% of vertices kept). 10 m measures at **4.20 MB**. One
  constant and a rebuild.

Do NOT tile these. `tiles` is frontend2 02's family and holds the one basemap object.

### The attribution string, verbatim

> Stormwater flood extents: NYC Department of Environmental Protection, NYC Stormwater
> Flood Maps (NYC Open Data `9i7c-xyvv`), snapshot 2026-08-23. Planning-grade design-storm
> modelling — not an observation of water and not a site-specific determination.

It is also a top-level `attribution` member on the payload, so you may read it from the
file rather than mirroring it into the page — which is the repo's rule for any constant the
page shares with `src/` (a text assertion that mirrors a Python constant pins the mirror to
itself). Render it in `#provenance` beside the MTA credit.

**The DEC CSO outfall layer is NOT available to you and never will be through `files/`:**
its licence permits fetch-and-use and prohibits secondary distribution.

### The honesty line this layer needs

These are DESIGN STORMS, not observations and not forecasts — DEP's own framing is
planning-grade. flood 15's frozen operating-truth string already says a rank is not an
observation of water; this layer needs its own sentence saying the same thing about a
modelled extent. flood-build 20 owns the sentence that places a live MRMS rate against
these intensities; do not invent a different one here.
