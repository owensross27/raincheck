# 08 — Flood tiers and the impact overlay go live

**What to build:** the map's flood half lights up: FloodNet water-now sensors
(aqua; dry/stale sensors as hollow rings), MTA affected-station dots on the
COMPLEX (amber, radius 7, coordinates from the tier payload), and flood 17's
impact overlay joining the exclusive Cell-fill radio (no ramp of its own, no
simultaneous fill — structurally impossible, as decided). The lineage gate
runs through the flood panel: the page reads TWO meta files, one per gate
side, so the MTA-derived tier stays dark on its own key while the FloodNet
side serves — and freshness rows for these sources graduate from AGE to
FRESH/STALE using the budget constants flood 15/17 froze.

**Blocked by:** 05 (chassis) + **flood 15** (panel exports: two meta files,
chip complex-coordinates, budget constants — MUSTs already on its line) +
**flood 17** (impact overlay data; consumes the no-own-ramp rule already on
its line). Wave 7+ territory; check both completion entries in the RUN LOG
before starting. The MTA-side layers additionally stay GATED until the [YOU]
terms receipt — build them gate-aware, do not wait for the receipt.

**Status:** done 2026-08-26 (branch `frontend08-impact-live`; close-out at the bottom)

- [x] The radio's second option (impact) works both directions; delay XOR
      impact pinned by a mutation-checked test (the existing two-fills tests
      plus a fill:true mutant on the new subway entry; 12/12 mutants killed)
- [x] Two-meta lineage: killing one gate side darkens exactly its layers and
      flips exactly its freshness rows; the other side is untouched (the
      GATE-derivation test asserts both sides against publish.LIVE_TERMS_VERIFIED
      and the layer->side map test pins which layers each side carries; verified
      both directions in a real tab — ungated fn lit beside gated impact rows,
      then a LOCAL, uncommitted gate flip lit both overlays with fn untouched)
- [x] Hollow-ring vs filled sensor vs dimmed vehicle are distinct at render
      scale; the subway overlay's absent-rel mark is a ring in its OWN hue
      (SUBWAY #e07ba0), so the ring shape has two hue-distinct meanings, never
      a grey
- [x] Budgeted sources now render FRESH/STALE from the frozen constants —
      impact 122400 s / subway 4200 s, derived in the test from
      flood_overlay.BUS_BUDGET_S / SUBWAY_BUDGET_S. **`mta` deliberately stays
      AGE: no staleness constant for the alert-side FILE is frozen anywhere in
      the repo** (flood 15's budgets_s carries the six FEED budgets, none for
      flood-mta.json) and a guessed threshold is the exact failure the counting
      test exists to catch.
- [x] Payload shapes verified against the REAL landed files, not fixtures:
      there is no JS runner (spec L), so the draws were exercised in a real tab
      against a real `flood_panel` tick's own output (383 sensors, 444
      complexes, a 1-Cell bus hour) — stronger than a fixture and immune to
      stub drift
- [x] Own-module tests only (tests/test_page.py, 40 -> 45); page-as-data seam
      extended (tests/page.py gains SUB_ORDER, the GEO_ORDER shape), not forked

## MUST from flood-build 17 (LANDED 2026-08-26, `flood17-live-impact-overlays`, `bb8d76f`)

**THE OVERLAY DATA IS ON DISK AND ITS KEYS ARE FROZEN.** Family `impact` in
`publish.FAMILIES`, **GATED** (`mta-vehicles` side, same as the live fleet), **no meta** -
each file states its own hour, budget and staleness inline, which is why your freshness
row can graduate without a second fetch.

    files/impact.json          bus,    grain `cell`     <- gold/cell_hour_speed
    files/impact-subway.json   subway, grain `complex`  <- archive/subway_tu

**Your layer ids, and the one-ramp rule as it actually landed.** `web/layers.js` already
declares `impact` / `impact-fill` / `impact-line` on the Cell FILL channel (frontend 05,
frozen) and `files/impact.json` is already its one `src`. **Do not add a ramp.** The
delay layer and this one are the same quantity - a Speed ratio - and share `RATIO_STOPS`;
they are a RADIO and `toggle()` must keep clearing the other.

**THE SUBWAY OVERLAY HAS NO LAYER YET AND THAT IS YOURS.** `files/impact-subway.json` is
complex-grain POINTS, not a fill, so it is a different channel from the radio entirely -
declare it beside `mta` (the alert dots), NEVER as a second Cell fill. **Never two kinds
in one legend**: the bus overlay is Cells and the subway overlay is complexes, and they
get separate legends or they are lying about their grain.

**BOTH FILES PAINT GREY TODAY AND THE PAYLOAD SAYS WHY - render the reason, not a zero.**

- **bus**: `cells` is keyed by the **H3 HEX STRING**, the same spelling
  `files/cells.geojson` and `flood.json`'s `cells` use, so all three join with no lookup.
  Each Cell carries `speed_mps`, `n_legs`, `n_vehicles` and - **only when a capture-era
  baseline exists** - `ratio` and `baseline_days`. There is no capture-era baseline on
  disk today, so **`ratio` is an ABSENT KEY on every Cell** and `["!", ["has", "ratio"]]`
  paints grey, which is the chassis's own rule working as designed. `state` is
  `no_baseline` and `baseline.reason` is a sentence you can render verbatim.
- **subway**: `complexes` is keyed by `complex_id`, each carrying `name`, `lon`, `lat`,
  `cell` (hex), `planned`, `dropped`, `runs`, `drop_share` and - **only above
  `min_planned`** - `rel`. **`rel` is the ONLY number to colour**: it is the complex
  against the CITYWIDE MEDIAN of the same hour of the same feed, because the absolute
  drop rate has never been level-compared against an independent source
  (`level_check.state` is `no_overlap` today). **Clamp your ramp** - measured 2026-08-26
  02:00 UTC, `rel` runs to 18.7 with a median `drop_share` of 0.0247, so an unclamped
  linear ramp is one station and 437 flat ones.

**THE HEAD OF THE CELL GRAIN IS SPARSE AND THE PANEL MUST SAY SO, NOT JUST PAINT IT.**
Measured on the real root 2026-08-26: the newest closed hour carries **19 Cells**, the
densest **1,169**. Both numbers are in the payload every cycle as `n_cells` and
`densest_cells` (plus `densest_hour_end_utc`) - render them, because 19 Cells painted
without a count reads as a claim about the city.

**THE LABEL IS NOT A FOOTNOTE.** `label` is on both documents at the top level AND at
`strings.label`, verbatim: **"impact - never a detector input"**. `strings.caveats` is the
panel's TEXT, not a tooltip - the bus list carries the sparse-head and one-channel
caveats, the subway list carries the three readability claims (median event day
indistinguishable, weekends unreadable, only the tail reads). Render them.

**THE BUDGETS YOU OWED ARE SHIPPED, so both rows graduate from AGE to a VERDICT.**
`budgets_s` is `{"impact_bus": 122400}` (34 h = one nightly cycle + `daily.TAIL_H`) and
`{"impact_subway": 4200}` (the hour + `archiver.WINDOW`). `staleness` beside it is already
a verdict dated at the READER - `FRESH` / `STALE` / `DOWN`, flood 11's vocabulary - so you
can render it directly or recompute from `budgets_s`; a future stamp reads DOWN.

**IT IS A CYCLE OF SIX NOW.** All six documents the flood tick writes carry ONE
`cycle_id`, so a torn set is detectable across the whole panel. The impact documents
deliberately carry **no `detector_version`** - they are impact, never a detector output.

## Inherited from frontend 05 (the chassis, `frontend05-seven-layer-chassis`, 2026-08-25)

**The chassis is landed and its close-out is the contract — read
`.scratch/frontend/issues/05-seven-layer-chassis.md` "The chassis's contract" before
writing a line.** You are LIGHTING declarations that already exist; if you find yourself
adding a layer, a source or a gate switch, stop and re-read, because that is the
re-plumbing this ticket was built to be spared.

- **The twelve layers are already declared at boot** in `web/app.js`'s style, in the frozen
  order `bg · zones-fill · cells · impact-fill · cells-line · impact-line · zones-line ·
  locate · live · hist · fn · mta`, each with an empty `FeatureCollection` and
  `visibility: "none"`. **MUST: you declare at boot — never `addLayer`/`addSource` in YOUR
  module.** A lazily added layer lands on top of the order and a `beforeId` naming a missing
  layer throws. **CORRECTED 2026-08-25 by frontend2 02** (the old wording said the test
  refuses both outright, which is no longer what it asserts): `web/basemap.js` is the ONE
  sanctioned caller, it passes `beforeId = "zones-fill"` on every insert, and
  `test_the_basemap_goes_above_bg_and_below_every_one_of_the_twelve` asserts every OTHER
  module still contains neither call. So the rule for you is unchanged in effect — declare
  your layer in the frozen style block — but do not read a bare `addLayer` on the page as a
  defect. `promoteId` stays off everywhere (hex ids are silently dropped).
- **The two gate keys exist**: `const GATE = { "mta-vehicles": false, "mta-alerts": false }`,
  and every layer carries its own `gate:` side; `shut(lyr)` is the only test of it. **MUST:
  light a side by flipping ONE boolean — never add a second switch.** A test derives the
  expected values from `publish.LIVE_TERMS_VERIFIED`, so opening a side on the page without
  the receipt goes red.
- **The freshness seam is `LAYERS` + `srcState(lyr, s)`.** Add a source as
  `{ k, url, budget, inner? }` on the layer's `srcs`. **A source graduates from AGE to
  FRESH/STALE by getting a non-null `budget` and by nothing else** — never by a new branch.
  Ages come from `grab()` (`Date` − `Last-Modified`); `whys[...]` carries the reason when
  there is none. A test counts the budgeted sources and derives FloodNet's from
  `flood_truth.MAX_AGE_MIN`, so a guessed threshold is caught.
- **`draw:` is the payload -> features hook.** `fn`, `mta` and `impact` ship `draw: null`
  on purpose: the chassis would not guess a schema it had not seen. Land the mapping there.
- **Rows are rebuilt and focus is restored** (`renderLayers`, the same mechanism as
  `setHour`); the change handler is DELEGATED to `#layers`. **MUST: keep any new control
  inside that delegation** — a listener bound to a rendered row dies on the next toggle.
- **RETIRED — the split is DONE. `web/app.js` is 86 lines now, not 781** (frontend2 01,
  2026-08-25). Do not split anything; the old MUST here told you to add a second
  `<script>` tag, and that is now WRONG — there is exactly ONE script tag for the page's
  own code. **Read "The module map" below and edit the module that owns your surface.**
  `tests/test_live.py` is likewise gone: page rules are `tests/test_page.py`, the export
  seam is `tests/test_live_export.py`.

### The module map — which module owns what (frontend2 01, `36901d4`)

The page is six ES modules, `type="module"`, no build step, no bundler. Load order is
publish order, and both come from `publish.FAMILIES["site"].files`:

| module | owns | lines |
| --- | --- | --- |
| `web/layers.js` | the ramps and the four hues, `STALE_AFTER_S` / `DELAY_CUT_S`, the `GATE` table, the **`LAYERS` table**, `L` / `shut` / `$` / `fmt` / `SMALL` / `on`, and the declare-at-boot map + style (the twelve layers in the frozen order). Constructs `map`. | 202 |
| `web/freshness.js` | `ages` / `whys`, `grab` / `load` / `forget`, `fmtAge`, `srcState` (the five states) and `worst`. | 86 |
| `web/panel.js` | `chipHTML` / `srcRows` / **`rowHTML`**, `renderLayers` (the focus restore), `applyVisibility`, `toggle` (the exclusive fill channel). | 79 |
| `web/insight.js` | `paint` / `colorExpr`, `renderHeadline`, `renderCurve`, `setHour` / `setView` / `buildViews`, `showTip`, `drawCells`. | 256 |
| `web/live.js` | `metaAge` / `isStale`, `renderLive`, `liveTick`, `toggleLive`. | 134 |
| `web/app.js` | boot ONLY: the map controls, every `addEventListener`, every `map.on` / `map.once`, both `ResizeObserver`s, the first `renderLayers()`. | 86 |

**MUST — three rules the split makes structural, each pinned by a test in
`tests/test_page.py`:**

1. **Every new `.js` file is a `site` family key** in `publish.FAMILIES` — that is the ONLY
   thing that publishes it AND the only thing that puts it under the page's tests
   (`tests/page.py` derives the file list from the family, so a hand list cannot go stale).
   Adding a key is ADDITIVE under `contract.PROMISE[1]`: **no `contract.CONTRACT` bump.**
   Update `docs/read-api-contract.md`'s `site` row in the same commit.
2. **All DOM and map wiring lives in `app.js` and nowhere else.** The module graph is
   CYCLIC by construction, so bodies do not evaluate in import order — MEASURED under node
   25: `panel · live · freshness · insight · layers · app`, i.e. `layers.js` evaluates
   almost LAST. Put an `addEventListener` / `map.on` / `ResizeObserver` back beside its own
   code and the page throws `ReferenceError: Cannot access '$' before initialization` at
   load and never paints (measured, not predicted).
3. **Cross-module WRITES go through a named function** — an imported binding is read-only.
   `layers.markStyled()` and `live.toggleLive()` are the two that exist; follow that shape.
- **08 edits `layers.js` (the `fn` / `mta` / `impact` entries and the `GATE` table) and
  `live.js` — 07 edits `insight.js` and the `hist` entry.** The overlap is the `LAYERS`
  table in `layers.js`: 08 touches only `fn` / `mta` / `impact` / `GATE`, 07 only `hist`.
  Nothing else is shared. That separation is the whole reason frontend2 01 ran early.
- Layout: nothing may position against a guessed `#provenance` height — `--prov` is written
  from the strip's measured `offsetHeight` and `#left`/`#right` clear it off that variable.

### Specific to 08

- **The radio's second option already exists.** `impact` is `fill: true` in `LAYERS`, its
  row already renders as a radio in the `cellfill` group, and `toggle()` already clears
  every other fill layer in the STATE as well as in the markup. Lighting it is: open the
  `mta-vehicles` gate side, and write `impact-fill`/`impact-line`'s paint + a `draw` hook.
  **It gets no ramp of its own and no simultaneous fill** — both are already structural;
  do not re-litigate them, and do not add a second exclusivity mechanism.
- **The hollow ring is already painted.** `fn`'s `circle-color` is
  `["case", ["get", "display"], WATER, "rgba(0,0,0,0)"]` with the stroke inverted, so a dry
  sensor is a RING and a wet one a filled aqua disc. **MUST: the payload must carry a
  boolean `display` per sensor** (that is the property the case expression reads), or change
  the expression and its test together.
- **The MTA station dot is `mta`**: amber `#ffc447`, radius 7, dark stroke, a dot on the
  COMPLEX. It needs complex coordinates from the tier payload — the MUST already on flood 15.
- **The two meta files are `files/flood.json` (ungated) and `files/flood-mta.json`
  (alerts side)** — the URLs the chassis already fetches, and now MUSTs on flood 15. If
  flood 15 lands different names, change the two `srcs` entries and correct flood 15's line
  in the same commit.
- **Budgets:** `fn` already carries `600` derived from `flood_truth.MAX_AGE_MIN`; `mta` and
  `impact` carry `null` and therefore render AGE. Graduating them is exactly: put flood
  15/17's frozen constant in the `budget:` field. The test that counts budgeted sources
  will need its count updated in the same commit — that is the point of it.

## Forward-context from DESTINATION-PLAN.md (copied verbatim by the WAVE 5 GATE PART 2, 2026-08-25, from this ticket's summary line in waves/wave-3-plus.md)

**FROM DESTINATION-PLAN (2026-08-25) — YOU LAND INTO A SPLIT FILE, AND TWO THINGS SIT UNDER YOU.** Edit only the modules frontend2 01's map assigns to tiers/impact (frontend 07 owns others, same wave). **LANDED 2026-08-25 (frontend2 01, `779e359`) — THE MODULE MAP IS ON YOUR TICKET FILE:** `layers.js` (ramps, hues, `STALE_AFTER_S`, `GATE`, the `LAYERS` table, the declare-at-boot style, `map`) · `freshness.js` (`grab`/`load`/`srcState`/`worst`) · `panel.js` (`rowHTML`/`renderLayers`/`toggle`) · `insight.js` (paint, headline, curve, views, tooltip, `drawCells`) · `live.js` (`isStale`/`renderLive`/`liveTick`) · `app.js` (**boot ONLY: 86 lines**). **07 edits `insight.js` + the `hist` entry; 08 edits `live.js` + the `fn`/`mta`/`impact` entries and `GATE`** — the only shared file is `layers.js` and the entries are disjoint. THREE MUSTs: a new `.js` file MUST be added to `publish.FAMILIES["site"].files` (that is what publishes it AND what puts it under `tests/test_page.py`; ADDITIVE, so **no `contract.CONTRACT` bump**, and update `docs/read-api-contract.md`'s site row) · **every `addEventListener` / `map.on` / `ResizeObserver` goes in `app.js` and nowhere else** — the graph is cyclic and bodies evaluate `panel·live·freshness·insight·layers·app`, so wiring beside its own code throws `ReferenceError: Cannot access '$' before initialization` at load (MEASURED) · a cross-module WRITE goes through a function (`markStyled`, `toggleLive`), because an imported binding is read-only. Your tier points paint ABOVE frontend2 03's flood-zone fills; the ONE-RAMP rule (D1) binds: while any Cell fill is on, zones are outlines and route lines are uncoloured — your impact fill joins the radio as before. If `files/flood.json` carries `design_storm` (flood-build 20, same wave, additive), render it as the design-storm sentence from its own `display` strings; if absent, render nothing — never a placeholder.

## FROM FLOOD 15 (2026-08-25, branch `flood15-panel-exports`, `5925813`) — YOUR PAYLOADS EXIST

The two files `web/layers.js` already fetches by name are written now, and so are their
two metas. **These are the exact keys your `draw` functions bind to; nothing here is
prose.** Read them, never re-derive them — every string and every budget below is read
from `research/flood-11-detector.json` at RENDER time, which is what lets Ross record
flood 12's verdict without a redeploy.

**`files/flood.json` (layer `fn`, gate `null` — OPEN).** Top level:
`cycle_id · detector_version · score_version · provisional · lineage ("ungated") ·
strings · cutpoints · window · staleness · budgets_s · dim · winter · skew ·
model_tier · cells · units · floodnet · coastal`.

* **`floodnet.geojson`** is a FeatureCollection of Points, one per renderable sensor, and
  **every feature carries a boolean `display`** — the MapLibre expression you already
  wrote (`["get", "display"]`) works unchanged: `true` = water now (filled aqua disc),
  `false` = dry or stale (HOLLOW RING). Other properties: `deployment_id · name · status ·
  state ("water"|"dry"|"stale") · label? · depth_mm · rise_mm · run · age_min · fresh ·
  gate? · cell?` (hex). **`gate` is only meaningful when `state == "water"`** — a dry
  sensor also reports `"rain"`, which is `flood_truth`'s own wording, not a claim.
  A sensor with no point is not a feature (counted in `floodnet.read`, not drawn).
* **`cells`** is `{"<h3 hex>": {...}}` keyed by the SAME hex string `cells.geojson` keys
  on, so the Cell fill joins by id with no lookup. Members, all absent-never-null:
  `score_index` (the STATIC dormant view, within-kind CDF, bounded (0,1]) · `rank` ·
  `tier` ("NONE"|"ELEVATED"|"HIGH") · `window_mm` · `flags[]` · `surge_margin_ft` ·
  `latched`. **`rank`/`tier` are ABSENT whenever the model tier is dropped** — see below.
  Geometry is deliberately not duplicated; you already load it.
* **`units`** is point Units at **ELEVATED+ only** (never a dormant list of 13,370 bus
  stops): `asset_id · kind · cell · tier · rank · name? · lon? · lat? · score_index? ·
  flags? · surge_margin_ft? · latched? · suppressed_by?`. **Print `asset_id` beside
  `name`** — names are not unique at bus-stop grain either (TRAPS).
* **`coastal`** is `flood_live`'s CO-OPS tier whole (`chips[]` with `state`,
  `observed_ft?`, `obs_age_min`, `next_high?`, `anomaly`) minus `recolor.units`, which is
  a static 1,072-row table already carried per Cell as `surge_margin_ft`. `recolor` keeps
  `gauges · n_units · n_no_margin · n_below_minor`.

**`files/flood-mta.json` (layer `mta`, gate `mta-alerts` — GATED, dark today).**
`mta.geojson` is one Point per AFFECTED COMPLEX with `display` (`true` while the station
is active), `event_id · complex_id · name · state · chip_state · age_min`; `mta.chips[]`
carries the same rows with `stations[]` now holding `lon`/`lat`/`cell` — **the second
lookup against `ref/assets` is gone**, which was your ticket's blocker.

**THE FRESHNESS TABLE YOU OWED A NUMBER FOR: `budgets_s` on BOTH metas** (seconds, to
match `LAYERS`), and `staleness` beside it with the verdict already computed:

    budgets_s = {precip_fresh: 5400, precip_stale: 10800, floodnet: 600,
                 coops: 1800, nws_alerts: 900, nws_knyc_obs: 7200}
    staleness = {precip|floodnet|coops|nws_knyc_obs: {state, age_min?, budget_s}}

`state` is FRESH / STALE / DOWN — flood 11's vocabulary (`display.precip_states`), and
the SAME three words on every source. **Every one is dated at the READER**, so the
frozen-age trap cannot come back through this door; a stamp further ahead than
`staleness_budgets.clock_ahead_min` reads DOWN, never FRESH. **`floodnet: 600` is exactly
the `budget: 600` you already have on the `fn` layer** — derive the JS number from
`flood_panel.BUDGETS_S` in a test rather than mirroring it (TRAPS: a page constant that
mirrors a python constant will drift).

**WHAT YOU MUST RENDER AS DATA, not as absence** — all four already in the payload:

* `window.state` ∈ OK / HOLES / INSUFFICIENT_DATA / WINDOW_CAPPED. A holed Window is
  still a Window and `window.anchor` stands; INSUFFICIENT_DATA means there is NO Window
  (the key is then absent) and `units` is `[]` while `cells` still carries `score_index`.
* `skew.model_tier` is `"ok"` or `"refused"` with a `reason`. **On a refusal
  `model_tier` is `"dropped"`, `units` is `[]` and no Cell carries `rank` or `tier` —
  render the refusal and its reason, never a last-good number.** The static
  `score_index` view survives, because it is not the model tier.
* `dim.dimmed` + `dim.dry_hours` — the "rain ended Xh ago" number.
* `winter.suppressed` + `winter.label` (absent when it is not suppressing) + `basis`
  ("observed" | "calendar").

**THE STRINGS ARE ALL UNDER `strings` AND NONE MAY BE RE-WORDED IN JS.** `tier_labels ·
tiers · cutpoint_basis · cutpoints_confirmed_by · window_interval · window_states ·
precip_states · forcing_stamp · winter_label · winter_unknown_label ·
no_complex_skill_claim · within_cell` come from `display.*`; plus `operating_truth` (the
FROZEN honesty string — verbatim, and notify 09 renders the same words), `estimand` +
`estimand_note`, `tiers_provisional`, `complex_rule`, `gate_branch`, and `panel` (the
gate's pre-selected `headline` / `release` / `caveat`). **`provisional` is a top-level
boolean: while it is true the panel says the tiers are provisional. flood 12 recommended
RANK-ONLY, so build the no-badge branch as the real one** — if Ross records it,
`cutpoints` stops being a display object, `detector_version` bumps and every open Window
rolls, and this payload changes with no page edit.

**Never render `eta` or a probability** — neither crosses the boundary and
`make release-check` fails if one ever does. The human-facing value is `rank` or
`score_index`. **Never present the point tier as resting on a validated distance**
(`estimand_note` says why). **`no_complex_skill_claim` rides with any complex row and
`within_cell` with any two Units in one Cell.**

Cadence: both files are `no-cache` and rewritten only when the forcing advances or the
FloodNet throttle (120 s) expires — measured 6 rewrites in 21 loop cycles. `flood.json`
is **317,837 B raw** on the real root (cells 169 KB + floodnet 159 KB); size decisions
here stay in RAW bytes until the gzip curl is recorded ([YOU], TRAPS).

## Forward-context from frontend2 02 (the basemap, landed 2026-08-25, branch `frontend2-02-basemap`)

**LAYER ORDER, and it now has a layer BELOW the twelve.** The stack is
`bg · <66 basemap layers> · zones-fill · cells · impact-fill · cells-line · impact-line ·
zones-line · locate · live · hist · fn · mta`. **MUST: you add nothing below `zones-fill`.**
The basemap's layers come from a VENDORED style (`web/vendor/basemap-dark.json`), so their
ids are not this repo's to write down; `web/basemap.js` inserts every one with
`beforeId = "zones-fill"` (derived in the test from `SPEC_ORDER[1]`, never a second copy of
the name). The frozen-order test is now an INVARIANT — "the twelve keep their relative order
and every basemap layer precedes all of them" — measured in a real engine at 78 layers.

**A NEW PUBLISH FAMILY: `tiles`.** `publish.FAMILIES["tiles"]` = prefix `tiles/`,
`RARE_CACHE`, cadence "deploy-time", writer "the operator, after `make basemap`", files
`("nyc.pmtiles",)`. It is deliberately NOT a `site` key: `web/tiles/` is gitignored and the
archive is never committed. `publish.PUBLISHABLE` gained `.pmtiles` and `.pbf`; rule 2 is
unchanged, because a family is an explicit file list. **If you add a payload file, it is
still a `site` or a new family — never `tiles`.**

**`web/basemap.js` is the seventh module** (a `site` key, additive, no `contract.CONTRACT`
bump — the count is 7 now, not 6). It owns the basemap and nothing else, so it does not
collide with `insight.js` (07) or `live.js` (08). It DOES touch `layers.js` (one `LAYERS`
entry, first) and `freshness.js` (two lines) — both landed already.

**`make web` is `raincheck.webserve`, not `python -m http.server`.** The stdlib server
answers a `Range:` request with 200 and the whole body, which makes a PMTiles archive
unusable locally. Same invocation (`make web [PORT=8000]`), single-range support added.

**A `srcs` entry may now carry `head: true`** — `grab()` then sends a HEAD and returns
`true` instead of a parsed body, so a large binary payload's age costs no bytes. And an OFF
row now prints a RECORDED reason when there is one (`why: whys[key] || "nothing is being
fetched"`), which is what lets a layer that turned ITSELF off explain why. If your layer can
fail its own fetch, set `on[<id>] = false` and leave the `why` in place rather than
inventing a state.

**A vendored library that is a bare-import ESM must be a classic tag.** `index.html` now
carries TWO classic library tags (`maplibre-gl.js`, `pmtiles.js`) and still exactly ONE
`type="module"` entry. `test_the_page_is_one_module_entry_with_no_build_step` asserts the
one-entry rule and that every classic tag is a published `site` key — it no longer counts
`<script` tags, so a third vendored library is not automatically a failure.

---

## FROM frontend2 03 (2026-08-26, branch `frontend2-03-geography-layers`) — YOU PAINT ABOVE THE GEOGRAPHY BAND

**THE STACK IS 81 LAYERS AND YOURS ARE STILL THE TOP ELEVEN.** Measured in a real engine:
`bg` · **66 basemap layers** · **`stormwater-fill` `stormwater-line` `routes`** ·
`zones-fill` … wait, read the order carefully, because the band is NOT at the bottom:

    bg · <66 basemap> · zones-fill · stormwater-fill · stormwater-line · routes ·
    cells · impact-fill · cells-line · impact-line · zones-line · locate · live · hist · fn · mta

frontend2 03's three layers sit in the ONE gap between `zones-fill` and `cells`. **You add
NOTHING below `cells`** — your tier points (`fn`, `mta`) and your impact fill are already
declared above the whole band and need no change. The reason the band is above `zones-fill`
rather than below it: every basemap layer is inserted with `beforeId: "zones-fill"`, so a
layer declared below `zones-fill` lands under all 66 basemap layers and is never seen.
`SPEC_ORDER[1]` is still `zones-fill`, so `basemap.js` is untouched.

`tests/page.py` now exports **`GEO_ORDER = ["stormwater-fill", "stormwater-line", "routes"]`**
and the frozen-order test asserts the twelve's RELATIVE order with `GEO_ORDER` removed. If
you add a layer, extend that the same way rather than writing a longer literal.

**THE ONE-RAMP RULE IS A FUNCTION NOW, AND IT BINDS ON YOU: `insight.js applyRamp()`.**
Your impact fill is `fill: true`, so it joins the frozen Cell-fill radio exactly as before —
and the moment it is LIT, `applyRamp()` puts the flood zones to `fill-opacity: 0` (outlines
only) and the route line to `ROUTE_PLAIN` at the thin width. You have to do nothing for that
to work; you only have to not break it. Call `applyRamp()` after anything you add that can
change which fill is lit. **The Cell-fill group has a `None` option now** (`data-nofill`),
without which the rule's other branch was unreachable — a radio cannot be un-checked and
`impact` is gated and disabled, so the fill could never be off. Do not remove it when you
light the vehicle gate side.

**THE LAYER IDS AND SOURCES you may need to name:** sources `routes` and `stormwater`; layers
`routes`, `stormwater-fill`, `stormwater-line`. `LAYERS` ids are `routes` and `stormwater`.

**A LAYER MAY NOW OFFER AN EXCLUSIVE CHOICE INSIDE ITS OWN ROW** — `lyr.opts` /`lyr.opt`,
rendered by `panel.js optsHTML()` as a second radio GROUP (`data-sc`), and `lyr.legend` is
raw HTML rendered under the row while the layer is on. Both are set by the layer's own draw
from the payload it fetched, so they are DATA and not code. Reuse them if a tier layer ever
needs a sub-choice; do not add a third control mechanism.

**`freshness.load()` AWAITS the draw now.** A draw may be async and may add a source to
`lyr.srcs` (frontend2 03's zones layer learns its scenario file from its first source and
fetches the second through `grab()`), so `renderLayers()` cannot run before it finishes.
This also fixed `basemap.js`, whose draw has been async since frontend2 02 and whose
`on.basemap = false` was being set after the panel had already rendered.

**ATTRIBUTION HAS A SLOT: `#geo-attribution` inside `#provenance`.** It is filled from each
payload's own top-level `attribution` member while that layer is on, with `textContent`, and
emptied when it is off. If `files/impact.json` ever needs a credit, put the string in the
PAYLOAD and add two lines to `renderGeoAttribution()` — never a copy in the page.

**MTA TRADEMARK MUST, and it is now live rather than forward:** a polyline, a stop name and
a coordinate are FACTS; a coloured route bullet, a roundel, an MTA line colour and MTA map
styling are IP usable only with prior written permission. frontend2 03 draws route geometry
with its own hue (`ROUTE_PLAIN`) and `tests/test_page.py::
test_no_mta_route_bullet_roundel_or_line_colour_reaches_the_page` fails on the strings
`route_color`, `daytime_routes`, `roundel` and `bullet` anywhere in the page's JS, HTML or
CSS. Your tier points are complex-grain and carry no route identity today — keep it that way.

**THE HUES ARE SPENT NOW, so do not reach for green:** `ZONE_DEEP #2e7d5b`,
`ZONE_NUISANCE #8fcfae`, `ZONE_MASK #7a8794`, `ROUTE_PLAIN #5b6572`, beside `WATER #35d6c2`,
`ALERT #ffc447`, `HIST #8f7bd6`, `GATED_HUE #d2a24c`, `GREY #3a4049` and the two frozen ramps.
A test asserts every one of those is distinct and none is on either arm of the diverging ramp.

**`colorExpr(prop, stops, absent = GREY)` TAKES THE ABSENT COLOUR NOW.** spec L's `#3a4049`
is calibrated to recede among coloured Cell fills and DISAPPEARS as a hairline on the dark
basemap, so the route line passes `ROUTE_PLAIN` instead. If you ever paint a line or a small
mark from a payload property, pass an absent colour that is visible on that mark.

## DONE 2026-08-26 — close-out (frontend 08, branch `frontend08-impact-live`)

**What landed, in two files plus the test seam.** `web/live.js` gained the four draws
(`drawFn`, `drawMta`, `drawImpact`, `drawImpactSub`) — the module map assigns 08 `live.js`,
and no new page module was added, so `publish.FAMILIES` is untouched and there is no
contract edit anywhere. `web/layers.js` changed only the `fn`/`mta`/`impact` entries, a NEW
`subway` entry + boot declaration, and two constants (`SUBWAY = "#e07ba0"`,
`REL_CLAMP = 4`); `GATE` values are UNchanged (LIVE_TERMS_VERIFIED is still None, both
sides false, the derivation test green).

**The subway overlay is layer id `subway`** (source `subway`, complex-grain points),
declared at boot BETWEEN `fn` and `mta` — the bounds derived from `SPEC_ORDER[-2:]` in the
test, `tests/page.py` exports `SUB_ORDER = ["subway"]` the way GEO_ORDER works. `rel`
drives circle SIZE (stops `1 -> 3.5px`, `REL_CLAMP -> 9px`; an interpolate holds its last
output past its last stop, so the clamp IS the expression); absent `rel` (below the
payload's `min_planned`) is a RING in the same hue — present, no publishable value, never
zero. Never a second Cell fill; separate legend per grain, as required.

**The bus overlay's paint is declared AT BOOT**: `["case", ["!", ["has", "ratio"]], GREY,
[interpolate ...RATIO_STOPS.flat()]]` — the frozen ramp spread in, no second stops table,
no draw-time paint call. The draw joins `impact.json`'s hex-keyed `cells` onto the
geometry the page already parsed, read off the map's own `cells` source via
`getSource("cells").serialize().data` (cells.geojson stays ONE fetch, one parse — the
frontend 05 rule).

**The freshness composite (the one design decision worth reading).** The impact payloads
have NO meta and carry `staleness.age_min` inline = the DATA's age at write; the header
age is the file's age since. `addDataAge()` in live.js adds them (the live pair's
`vp_age_s + metaAge` idiom), so the row's verdict is reader-dated, keeps counting after
the writer dies, and a fresh file over a stale Gold hour cannot read FRESH. Verified live:
bus reads **41 h STALE against 122400 s** (hour_end 2026-08-25 10:00 UTC) while subway
reads **42 min FRESH against 4200 s** — same tick, opposite verdicts, both honest.

**Verified in a real tab** (swiftshader flags, CDP screenshots, against `raincheck.webserve`
serving the worktree's web/, real payloads from a real `flood_panel --no-publish` tick):
zero console errors; 383 dry sensors render as hollow aqua rings; the gated rows print
their reason; a local uncommitted GATE flip lit both overlays — grey footprint + 444
rel-sized rose discs with rings where rel is withheld — and the tier side was untouched.

**Mutation round: 12/12 killed** (harness under every TRAPS rule: committed first,
refuse-dirty, landed-mutant proof per case, checkout+clean restore with porcelain assert,
pristine control green at both ends). The round's own catch: the hyphenated words
"design-storm" in a comment tripped frontend2 03's mirrored-string test — the
docstring-poisons-the-grep trap, met and dodged by rewording, not by weakening the test.

**For flood-build 20 (D, same wave, may land after this):** `drawFn` renders
`files/flood.json`'s `design_storm` member as `Object.values(design_storm.display)` — every
STRING value of `display`, in order, escaped, as sentences; absent key renders NOTHING. So
put only display-ready sentences in `display` (labels included will be printed). If your
shape differs, correct `drawFn` and this paragraph in the same commit.

**Known ceilings, named:** the fn `srcs` budget (600 s) reads the FILE's header age, and a
paused live loop (as on this Mac between manual ticks) legitimately shows STALE — correct,
not a defect. `mta` has no frozen file budget and renders AGE (see the checkbox above).
The flood.json `cells` member (score_index per hex) is read by nothing on the page — the
static dormant view is future work, not this ticket's, and no layer claims it.
