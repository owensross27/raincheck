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

**Status:** ready-for-agent (gated)

- [ ] The radio's second option (impact) works both directions; delay XOR
      impact pinned by a mutation-checked test
- [ ] Two-meta lineage: killing one gate side darkens exactly its layers and
      flips exactly its freshness rows; the other side is untouched (tested
      both directions)
- [ ] Hollow-ring vs filled sensor vs dimmed vehicle are distinct at render
      scale; the three-meanings-one-grey failure is a red test
- [ ] Budgeted sources now render FRESH/STALE from the frozen constants —
      never from guessed thresholds; unbudgeted remainder still says AGE
- [ ] Fixtures verbatim from flood 15/17's landed schemas; stub fidelity
      mutation-checked
- [ ] Own-module tests only; page-as-data seam extended, not forked

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
