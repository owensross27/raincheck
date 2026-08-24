# 07 — Coastal rule layer: deterministic surge margins

**What to build:** Coastal exposure as arithmetic, not a model: every Unit's surge_margin_ft against its
assigned gauge's frozen threshold in one datum, shared verbatim with the detector — so storm-surge
risk is stated without pretending ~15 coastal events could fit a model. Spec: Exposure score
(coastal layer); Testing seam 2.

**Blocked by:** 03

**Status:** resolved 2026-08-23

- [x] surge_margin_ft = elevation − assigned gauge threshold, all NAVD88; assignment = geodesic nearest of {Battery, Kings Point, Sandy Hook}; per-station datum offsets applied; the Kings Point NWS/NOS threshold inversion is recorded where the constant is defined
- [x] the threshold stage is frozen ONCE and shared with the detector's coastal tier — asserted equal at build (ticket 14 consumes the same constants)
- [x] no fitted coastal terms anywhere; the Sandy inundation polygon validates the layer descriptively (a published table, not pytest)
- [x] datum sanity pinned here, where elevations and thresholds first meet: the below-minor-flood entrance count reads 3 under NAVD88 discipline, not the naive STND-comparison 103
- [x] unit tests on fixture elevations and a hand-checked margin

## Comments

**2026-08-23 (resolution).** Built as `src/raincheck/flood_coastal.py` + `make flood-coastal`,
tested in `tests/test_flood_coastal.py` (12 tests). The published table is
`research/flood-07-coastal.md`, re-cut by the make target.

**Nothing is stored.** `surge_margin_ft` is arithmetic over `silver/asset_features` and the
frozen gauge constants, so ticket 10 calls `flood_coastal.unit_margins(root)` when it writes
`gold/flood_exposure` rather than joining a fourth Silver table that could drift out of step
with the elevations it is derived from. A stored margin would need its own version stamp,
its own rebuild gate and its own staleness failure mode to say something a subtraction
already says.

**The three thresholds, converted once at the definition:**

| gauge | minor, ft STND | NAVD88 offset, ft | minor, ft NAVD88 |
|---|---|---|---|
| 8518750 The Battery | 10.49 | 6.06 | **4.43** |
| 8516945 Kings Point | 22.89 | 17.09 | **5.80** |
| 8531680 Sandy Hook | 9.21 | 5.33 | **3.88** |

All six numbers were re-fetched live from each station's own `floodlevels.json` and
`datums.json` on 2026-08-23 and are held by `canary()`, which asserts EQUALITY against the
published values rather than mere liveness — the failure being guarded is a silently-moved
threshold, which a reachability check would never see.

**The datum check reproduces exactly.** Entrances below the Battery's minor stage: **3**
under NAVD88 discipline, **103** if the published STND number is compared straight against
a NAVD88 elevation. Both frozen in `flood_coastal.EXPECT` and asserted; if they ever
coincide the conversion has been lost.

**Units by assigned gauge** (15,166 = 445 complexes + 13,370 bus stops + 1,351 Cells):

| gauge | complex | bus_stop | cell | negative margin | no margin |
|---|---|---|---|---|---|
| The Battery | 312 | 8,062 | 632 | 8 | 138 |
| Kings Point | 112 | 4,440 | 536 | 21 | 189 |
| Sandy Hook | 21 | 868 | 183 | 5 | 77 |

404 Units have no margin at all (0 complexes, 60 bus stops, 344 Cells): Cells scored via a
taxi Zone with no point child inside them, and the 60 bus stops whose 2017 sample and 15 m
ring are both NoData. **Ticket 10 must price these as NULL, not 0.0** — a zero would put
them exactly at minor flood stage, the most alarming value the column can take.

**Sandy validates the layer descriptively** (a published table, not pytest — Sandy is one
coastal event and its labels are barred from the fits):

| surge_margin_ft | units | inside the Sandy polygon | share |
|---|---|---|---|
| < 0 | 34 | 24 | 0.706 |
| [0, 5) | 1,107 | 959 | 0.866 |
| [5, 10) | 1,454 | 405 | 0.279 |
| [10, 20) | 2,191 | 6 | 0.003 |
| [20, +) | 9,976 | 5 | 0.0005 |

The ordering is what the layer claims — 87% of Units within 5 ft of their gauge's minor
stage were inundated, 0.05% of those above 20 ft were — and the two low buckets are NOT
monotone, which is the honest part. All ten negative-margin Units that Sandy missed were
identified: six Kings Point-side Cells (western Long Island Sound, where Sandy's surge was
far smaller than in the Harbour), two road underpasses (Gowanus Expwy/Woodhull St,
Stillwell Av/Neptune Av) that are genuinely below 4 ft NAVD88 but not open to tidewater,
and the WTC Cortlandt pair below. A still-water margin cannot know about connectivity, and
this is precisely where that shows.

**Decisions taken here (not in the ticket):**

1. **The gauge is assigned at the UNIT's location, the elevation is the MINIMUM over its
   point children.** A complex measured against one stage rather than a mixture; the worst
   doorway rather than the average one. Note the deliberate asymmetry with ticket 08: the
   exposure score takes the MAX over children because it aggregates a probability, the
   margin takes the min because it aggregates a height.
2. **The QC fallback is applied here, read-side, exactly as ticket 03 decision 7 specified**
   — a `grade_ok=false` row uses its `ring15_med`, never a Cell median.
3. **The most exposed complex in the city is a DEM artifact and is published as one.** WTC
   Cortlandt (`stn:328`, −38.5 ft) was an open construction pit when the 2017 raster was
   flown; the station reopened in 2018 and its 15 m ring is inside the pit too, so the QC
   fallback cannot rescue it. `grade_ok` already marks those entrances false. The layer
   publishes the raw consequence and names it in the report rather than repairing it
   silently — the alternative is a special case that the next DEM epoch would strand.
4. **`gauge_km` rides on every row.** Jamaica Bay and the Rockaways have no CO-OPS gauge
   (the same blind spot `flood_spine` records for the trigger); those assets get the nearest
   of the three, which is a substitution and not a measurement, so the distance is never
   hidden from a consumer.
5. **The published 2-dp NAVD88 offset is used, not the unrounded one.** CO-OPS applies
   6.063 ft at the Battery where `datums.json` publishes 6.06 — at most 0.005 ft = 1.5 mm,
   four hundred times smaller than the DEM's own 0.88 m epoch sigma, and using the published
   value is what lets the canary compare frozen to published as an equality.
6. **`check_shared_thresholds()` is the shared-constant assertion.** `flood_spine` cuts
   coastal event-days on its own frozen pair (Battery, Kings Point) and this layer measures
   margins against the same published stages; the check asserts they are equal for every
   station both name, and a test bends one copy to prove the failure is loud. Ticket 14
   imports `GAUGES` and `STAGE` from here — they are not re-declared.

**Open for ticket 14.** The stage frozen here is `nws_minor`. The detector's coastal chips
(quiet / approaching / exceeding) need the *action* stage too, which only the Battery and
Sandy Hook publish (Kings Point's is null) — 14 will have to choose a rule for the gauge
that has none rather than inventing a value.
