# 03 — The geography layers: routes and flood zones

**What to build:** the two geography layers DESTINATION §1 asks for — route lines
(DESTINATION-PLAN D1: a route SEGMENT is a Cell crossing) and DEP's rainfall-scenario
flood extents. Box: `DESTINATION-PLAN.md` §2.

**Gate:** frontend2 01 (LANDED, `779e359`) + flood-build 19 (LANDED, `1fbb0d6`). BOTH
entries verified 2026-08-26 — see "Gate, checked" in the DONE section at the bottom.

**Status:** DONE 2026-08-25 — landed 2026-08-26 on `frontend2-03-geography-layers`.

---

## CORRECTIONS THIS TICKET MEASURED — read these before the box below

**1. `gold/cell_hour_route` CANNOT carry this ticket's estimands, and the box names it.**
Measured 2026-08-26 on the real root. That table is
`(cell, hour_end_utc, route_id, direction_id)` x `n_events, late_share, early_share,
mean_segment_excess_s, ewt_s, bunched_share, wait_ok_share, coverage, vp_coverage` —
SCHEDULE ADHERENCE. It holds no distance, no time and no leg count, so the wet/dry Speed
ratio `cells.geojson` publishes cannot be computed from it at all. It also spans
`month=2021-09` and `month=2026-08` ONLY: **86,914 rows in 2021-09 and 1,358,270 in
2026-08**, which does not cover W1 (2021-08-16..2021-10-16) and covers none of W2.
**`gold/cell_hour_speed` is the table that carries `route_id` AND the Speed sums**
(`n_legs, n_vehicles, dist_m_sum, dt_s_sum`), over 2021-08/09/10 and 2023-09/10 — both
windows whole, 12,945,842 rows, 376 distinct `route_id`, zero nulls. It is also the table
`web/export.sql` reads for `cells.geojson`, which is what makes "the same estimand,
restricted to this route" true by construction rather than by resemblance.
**`DESTINATION.md` §3.A calls `cell_hour_route` "speed evidence already keyed by route".
That sentence is wrong** and is corrected in place there.

**2. THE DENOMINATOR HAD TO BE BUILT, and it is the one design decision in `web/geo.sql`.**
`cells.geojson`'s window estimand divides by `gold/cell_hourofweek_baseline`, which is keyed
`(cell, hour_of_week, window)` and has NO route. Dividing a ROUTE's wet Speed by the Cell's
ALL-ROUTE dry Speed would publish a composition difference as a rain effect — an express
route that is always faster than the Cell's mix would read above 1.0 on a dry day. So
`bl_r` rebuilds the same baseline keyed by route as well, from `gold/cell_hour_speed` under
`gold.baseline()`'s own dry mask (`mm_1h < 0.1 AND mm_1h_prev < 0.1 AND mm_6h < 0.5`, AORC).
Same definition, one more key. Support, measured: **17,156 (window, Cell, route) triples
have a dry baseline · 14,800 clear two wet-event clusters · 8,734 clear the 0.30 gate**.

**3. The estimand is per `(window, Cell, route_id)` and NOT per direction.**
`gold/cell_hour_speed` carries no `direction_id`, so the two directions of a route through
one Cell share one number and both Features carry it. Stated in the payload's contract doc
rather than implied.

**4. The scenario radio needs a MANIFEST, and that is not optional.** `geo` is a TREE family
whose served set is derived from the table — which is the property that lets a second
scenario appear with no code change — and **a browser cannot list a directory**. Without a
manifest the page must name `stormwater-moderate.geojson` in JavaScript, and the day a
second scenario is readable that is a page edit, i.e. exactly the rewrite the box forbids.
`web/geo.sql` therefore emits `files/geo/scenarios.json` beside the route lines.

**5. THE CELL FILL COULD NOT BE TURNED OFF, so half of D1 was unreachable.** A radio cannot
be un-checked by clicking it and the only other fill option (`impact`) is gated and rendered
disabled — so before this ticket a reader could never see the flood zones FILL or the route
line carry the ramp. The Cell-fill group gains a **None** option. It declares no layer and
claims no channel: `fill: true` is still exactly `{cells, impact}` and frontend 02's frozen
exclusivity is untouched.

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

---

## DONE 2026-08-26 — what landed

**Branch** `frontend2-03-geography-layers` · worktree `/Users/ross/raincheck-wt/frontend2-03`.

**Gate, checked.** Both entries exist. The live `RUN-LOG.md` is ONE GATE DEEP by design, so
the two ticket entries live in `RUN-LOG-ARCHIVE.md` (`## frontend2 01 — split the file — ✅
DONE 2026-08-25`, and `- 2026-08-25 · **flood-build 19 — the four scenario extents, kept**`,
which names `silver/stormwater_extent` and the `geo` family); the live log's own WAVE 6 GATE
PART 2 entry records arming this box with "gate frontend2 01 + flood-build 19, both landed".

### The files

| key | features | raw bytes |
| --- | ---: | ---: |
| `files/geo/routes.geojson` | **21,868** | **8,162,311** (7.78 MiB) |
| `files/geo/scenarios.json` | 1 scenario | 113 |
| `files/geo/stormwater-moderate.geojson` (flood-build 19) | 3 | 4,607,370 |

`make geo` runs BOTH writers — `raincheck.stormwater_extent --geo` then
`raincheck.export --geo`. One target, one family, one place to look.

**15,416 of 21,868 features carry a published ratio** in at least one window; 6,452 paint
uncoloured (interval too wide, or the route has no dry baseline in that Cell). The network's
in-grid length is **16,117 km of 16,139 km** — 99.86% of `silver/shapes` is inside the
`ref/cells` grid.

### THE SIZE LEDGER — every lever priced before one was taken

The box says "if the file is too large for a toggle, split by borough or drop `length_m`,
and say which". It is too large, and **NEITHER of those two levers fixes it** — measured
against the built file, not estimated:

| lever | bytes | saved | what it costs |
| --- | ---: | ---: | --- |
| as built, with `length_m` | 8,536,212 | — | — |
| **drop `length_m`** — TAKEN | **8,162,311** | **4.4%** | a value recomputable from the shipped LineString |
| drop `length_m` + `shape_id` | 7,690,179 | 9.9% | the decided unit's own id |
| drop the support counts | 7,293,077 | 14.6% | the honesty payload |
| drop the intervals | 7,799,263 | 8.6% | the gate's own evidence |
| **one Feature per (route, direction, cell)** | **5,753,793** | **32.6%** | D1's DECIDED unit, and `shape_id` |
| split by borough | 8,536,212 | 0.0% | five requests for the same bytes on a citywide toggle |

Geometry is only 2,337,546 B of it (27%); the other 73% is 21,868 copies of an envelope and
up to 18 properties, which is inherent to the decided unit. The simplify sweep, for the
record: raw 9,713,704 B of geometry · 0.0001 (~8 m) 2,556,776 · **0.0002 (~17 m, SHIPPED)
2,337,584 and 0.32% of network length** · 0.0005 4→2,112,468 and 0.89% · 0.001 1,980,759 and
2.1%, which starts cutting real corners. 0.0002 is the knob `zones.geojson` already uses.

**The only lever worth more than 15% overturns D1's decided segment unit, and that is not a
renderer's call.** It is filed here with its measured price: 21,868 → 14,216 features,
−32.6%, and it loses `shape_id` (two shapes of one route+direction through one Cell draw
nearly the same ink and carry identical numbers — the estimand has no shape-level content).
Whoever owns D1 can take it in one afternoon. The other order-of-magnitude answer is vector
tiles, which is `tiles`' family and a real build step.

### The page

- **TWO LAYERS, both `open: false`**: `Bus route lines` (`routes`) and
  `Ground: flood zones (DEP design storm)` (`stormwater` → `stormwater-fill`,
  `stormwater-line`). Nothing is fetched at boot; the panel states 7.8 MB and 4.4 MB before
  a reader ticks either.
- **THE ORDER.** The band sits between `zones-fill` and `cells`: `bg` · 66 basemap layers ·
  **`stormwater-fill` `stormwater-line` `routes`** · `cells` · … · `mta`, **81 layers**
  measured in a real engine. It is ABOVE `zones-fill` on purpose and that is the only
  placement that works — every basemap layer is inserted with `beforeId: "zones-fill"`, so
  anything declared BELOW `zones-fill` lands under all 66 of them and is never seen. The
  twelve keep their frozen relative order, `SPEC_ORDER[1]` is still `zones-fill`, and
  `basemap.js` needed no change. The order test asserts the relative order with the band
  removed, plus the band's own placement derived from `SPEC_ORDER`'s indices — never a
  longer literal.
- **D1'S ONE RAMP IS A PAINT RULE.** `insight.js applyRamp()`: with a Cell fill lit the zone
  fill goes to opacity 0 (outlines only) and the route line is `ROUTE_PLAIN` at the thin
  width; with every Cell fill off the zones fill and the route line carries
  `colorExpr(activeProp(), …)` — the SAME expression on the SAME property the Cell fill
  would use. The layer ORDER says the same thing a second way and neither is redundant.
- **The route's ABSENT colour is `ROUTE_PLAIN`, not `GREY`.** spec L's `#3a4049` is
  calibrated to recede AMONG coloured Cell fills; as a sub-pixel hairline on the dark
  basemap it disappears, so a crossing with no publishable number read as no route at all.
  Found in a real tab, not predicted.
- **The exclusion mask recedes and is never clear**: `fill-opacity` is
  `["match", ["get","category"], "not_analyzed", 0.16, 0.5]`. `not_analyzed` polygons are
  the big ones and at the depths' own opacity they washed the whole city out and hid both
  the modelled classes and the route lines. Its legend row is rendered whether or not the
  payload carries it.
- **The route row SAYS WHY its lines are grey**, and there are two different reasons: a Cell
  fill is on (pick None), or the view is a storm HOUR and a route through one Cell in one
  Hour carries no interval anyone could publish (pick W1/W2). Without that sentence the
  default view shows an uncoloured network and reads as a broken layer.
- **Attribution is read OFF the payload**, not mirrored: `#geo-attribution` inside
  `#provenance` fills from each payload's own `attribution` member while its layer is on and
  empties when it is off, with `textContent`.
- **No new module, no `publish.py` edit, no `contract.SCHEMA` edit, no bump.** `geo` is a
  TREE family so a file joins it for free; `contract.PROMISE[1]` freezes the PREFIX.

### Verified in a real browser

Chrome 152 headless with `--enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader`,
driven over CDP with `Page.captureScreenshot` after a real wait (never `--screenshot`, which
fires before the tiles land), served by `make web` (`raincheck.webserve`, with `Range:`).
**Zero console errors.** Four captures: boot · both geography layers on under the Cell fill
(the band correctly invisible) · the Cell fill off (zones fill, network visible) · the W1
view (the network carrying the frozen diverging ramp). Also driven in a node harness against
a stubbed DOM and the REAL `web/files/`: 81 layers, 21,868 route features and 3 zone features
drawn, the zones layer's `srcs` growing from one to two, one scenario radio, two freshness
rows, and the paint expressions flipping in both directions.

### Mutation round

**23 mutations, 23 killed, zero survivors**, pristine control green at both ends, committed
before mutating, `PYTHONDONTWRITEBYTECODE=1`, snapshot from git with a refuse-on-dirty gate,
restore with `git checkout` AND `git clean` and a clean-tree assert after every row, each
mutant proved landed by `git diff`. The first round was 22/1 and **the survivor was a claim
about the DATA**: over the real shapes x Cells all 24,265 dumped intersection parts are
LINESTRINGs, so nothing in production can discriminate the graze guard from dead code. Fixed
by building a fixture that can — `S4` ends on a hexagon vertex and `ST_Intersection` returns
a POINT, which a `line` layer draws as nothing with no error anywhere.
