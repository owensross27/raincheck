# 07 — The history layer and the record card

**What to build:** a viewer toggles on flood-history markers (violet, one per
asset with a record), clicks any of them — stop, Cell, or complex — and the
asset's flood record opens in a card that SHARES the right column with the
layer panel (flex shrink, never floating, never covering the freshness rows):
title with the id fallback for unnamed Cells, kind + id, event count, label
version, the last events newest-first with their class/cause/source-counts/
support, and the "counts are city-wide at EVENT grain" caveat. Paint comes
from notify 05's manifest (one bulk file, WITH coordinates); detail is one
per-asset fetch on click, dated reader-side, sized on the recorded tail
(~23 KB max), edge-cached.

**Blocked by:** 05 (the chassis declares the layer) + **notify 05** (the
static per-asset surface, whose manifest carries lon/lat and a freshness
budget — MUSTs already on its summary line). Wave 7 territory; check notify
05's completion entry in the RUN LOG before starting.

**Status:** ready-for-agent (gated)

- [ ] Marker layer paints from the manifest only; no per-asset fetch happens
      before a click (tested — the network discipline IS the payload rule)
- [ ] The card is in-column; a hit-test proves it never covers the freshness
      rows or the provenance strip at 375px and at desktop widths
- [ ] Unnamed assets render the id fallback; the "null"-title failure is a
      red test
- [ ] Click, not hover (touch parity); keyboard reachable; focus returns to
      the marker's toggle row on close
- [ ] Fixtures cut verbatim from notify 05's landed schema; stub fidelity
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
- **07 edits `insight.js` (the record card) and `layers.js` (the `hist` entry's `draw`
  hook and `srcs`) — 08 edits `layers.js` (the `fn` / `mta` / `impact` entries and the
  `GATE` table) and `live.js`.** The overlap is the `LAYERS` table in `layers.js`, and it
  is one table of seven single-line-ish entries: 07 touches only the `hist` entry, 08 only
  `fn` / `mta` / `impact` / `GATE`. Nothing else is shared. That separation is the whole
  reason frontend2 01 ran early.
- Layout: nothing may position against a guessed `#provenance` height — `--prov` is written
  from the strip's measured `offsetHeight` and `#left`/`#right` clear it off that variable.

### Specific to 07

- **The marker layer is `hist`**, source `hist`, already painting violet `#8f7bd6` with
  `circle-radius` interpolated on `n_events` (1 -> 1.6 px, 12 -> 4.6 px). Its `draw` hook is
  already wired to `setData` the manifest as-is, so a manifest that is a FeatureCollection
  needs no code at all to paint.
- **The manifest URL the chassis already fetches is `files/history/manifest.geojson`**
  (a MUST now written onto notify 05). Change it in ONE place — the `hist` entry's `srcs` —
  if notify 05 lands a different name, and correct notify 05's line in the same commit.
- **`locate` is declared and empty** for the hover-locate ring carried over from prototype
  variant C. It is at the right place in the order already.
- The card shares `#right` (`display: flex; flex-direction: column`), the same mechanism
  `#left` uses; `#layers` is `flex: 1 1 auto` with its own scroll, so a card added as a
  sibling shrinks against it rather than floating over it.
- The `hist` source has **no budget frozen**, so its rows read AGE until notify 05 freezes
  one. Do not guess one here.

## Forward-context from DESTINATION-PLAN.md (copied verbatim by the WAVE 5 GATE PART 2, 2026-08-25, from this ticket's summary line in waves/wave-3-plus.md)

**FROM DESTINATION-PLAN (2026-08-25) — YOU LAND INTO A SPLIT FILE.** frontend2 01 (wave 5 box F) HAS SPLIT `web/app.js` into six ES modules; you edit ONLY the module that owns the history layer + card, because frontend 08 edits different ones in the SAME wave. **LANDED 2026-08-25 (frontend2 01, `779e359`) — THE MODULE MAP IS ON YOUR TICKET FILE:** `layers.js` (ramps, hues, `STALE_AFTER_S`, `GATE`, the `LAYERS` table, the declare-at-boot style, `map`) · `freshness.js` (`grab`/`load`/`srcState`/`worst`) · `panel.js` (`rowHTML`/`renderLayers`/`toggle`) · `insight.js` (paint, headline, curve, views, tooltip, `drawCells`) · `live.js` (`isStale`/`renderLive`/`liveTick`) · `app.js` (**boot ONLY: 86 lines**). **07 edits `insight.js` + the `hist` entry; 08 edits `live.js` + the `fn`/`mta`/`impact` entries and `GATE`** — the only shared file is `layers.js` and the entries are disjoint. THREE MUSTs: a new `.js` file MUST be added to `publish.FAMILIES["site"].files` (that is what publishes it AND what puts it under `tests/test_page.py`; ADDITIVE, so **no `contract.CONTRACT` bump**, and update `docs/read-api-contract.md`'s site row) · **every `addEventListener` / `map.on` / `ResizeObserver` goes in `app.js` and nowhere else** — the graph is cyclic and bodies evaluate `panel·live·freshness·insight·layers·app`, so wiring beside its own code throws `ReferenceError: Cannot access '$' before initialization` at load (MEASURED) · a cross-module WRITE goes through a function (`markStyled`, `toggleLive`), because an imported binding is read-only. Layer order: a basemap (frontend2 02) and the geography layers (frontend2 03) sit BELOW every data layer — you add nothing below them. Tests read the page through `tests/page.py`'s helper over the `site` family, never a hand list.

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


## FROM notify 05 — YOUR MANIFEST IS LANDED AND MEASURED (2026-08-26, branch `notify05-static-history`)

`make export` now writes `web/files/history/`. The `hist` row already in `layers.js`
(`url: "files/history/manifest.geojson"`, `draw` = `setData` the body unchanged) works
with no page change — the file it names exists now. **You still own everything visual;
this is the data contract under it.**

**THE MANIFEST IS A GeoJSON FeatureCollection AND THE KEY SET IS SIX, FROZEN:**

    { "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [lon, lat] },   // 5 dp, ~1.1 m
      "properties": { "asset_id", "kind", "n_events", "name"? } }

- **`name` is an ABSENT KEY on every `cell`-kind asset — all 1,276 of them — never null.**
  `ref/assets` names only stops, stations and complexes, and **the most-flooded assets are
  exactly the Cells**, so `props.name` at the top of a ranked list is `undefined`, not a
  string. Fall back to `asset_id`. **And print the `asset_id` even when a name exists:**
  `bus:200163` and `bus:200173` are both "FATHER CAPODANNO BLVD/DOTY AV", both with 26
  events, metres apart on opposite sides of one street — a marker click between them is
  genuinely ambiguous and the name alone cannot resolve it.
- `n_events` is what drives your `circle-radius` ramp. Real distribution over the 8,146
  listed assets, so size the ramp on it rather than on a guess: 73 is the maximum
  (`cell:882a1062d5fffff`).

**THE COUNT IS 8,146, NOT THE 7,955 EVERY EARLIER TICKET SAYS.** 5,657 bus stops + 1,276
Cells + 928 entrances + **285 complexes**. 7,955 counted assets owning a LABEL ROW; only 94
complexes do, but `events_for_asset` answers a complex for ITSELF AND ITS ENTRANCES, so 285
have a history a click returns. **The manifest matches what the click returns**, which is
the only invariant that makes a marker honest, and a test pins the two together.

**THE RECORD CARD'S FETCH: `files/history/<asset_id>.json`, the id VERBATIM.** Flat tree,
no shards, no encoding — derive the URL from the manifest's own `asset_id` and never from a
name. The ids carry `:` (`bus:400081`, `cell:882a1062d5fffff`,
`ent:409:40.722103:-73.996812`); that is legal in a URL path segment and in an object key,
and no id in the registry holds a character outside `[A-Za-z0-9:._-]` (measured over all
20,544).

**SIZES, MEASURED ON THE SHIPPED TREE — and the two numbers are 66x apart, so do not mix
them up.**

| | |
|---|---|
| manifest | **1,458,148 B raw** (138,524 gz), loaded ONCE at boot |
| one click | median **1,138 B**, mean 1,561 B, **max 21,994 B** |
| whole tree | 8,147 files / 14,174,355 B |

Nothing in this repo sets `Content-Encoding`, so the gz figure is CONDITIONAL on an edge
behaviour nobody has verified — **budget in RAW bytes** until the `[YOU]` curl is recorded.
The manifest is ~40% of the live page's current 3.66 MB first paint in raw bytes, so it is
a real boot cost: it is the layer, and it is worth deciding whether it loads at boot or on
first toggle. That is YOUR call, not mine.

**THE PER-ASSET FILE IS A MERGE, and one key can be missing:**

    { "queries": ["events_for_asset", "exposure_of"], "mode": "public",
      "asset": {asset_id, kind, name?, cell?, complex_id?},
      "n_events": N, "events": [...], "reason"?: "no events on record",
      "exposure": {estimand, model_id, score_index, score_ref, score_severe,
                   surge_margin_ft?, flags[], modelled},
      "exposure_unavailable"?: {reason: "not_a_scored_unit", ask: "<complex asset_id>"},
      "versions": {assets_version, spine_version, label_version, score_version?} }

- **928 of the 8,146 files have NO `exposure` KEY AT ALL, and they are all entrances.** An
  entrance's score exists only inside its complex's max. **Test for the key's presence** —
  there is no null and no zero to check, because a fabricated 0.0 would read as "safe".
  `exposure_unavailable.ask` is the complex that DOES answer; following it works (pinned).
- `score_index` is the within-kind RANK bounded (0, 1] — the human-facing number.
  `score_ref` / `score_severe` are the LINEAR PREDICTOR and are **negative for nearly every
  Unit**; neither is a probability. `modelled: false` marks the 60 kind-median bus stops —
  never render one as a modelled rank. An absent `surge_margin_ft` (404 Units) is **not a
  zero**: a zero margin means the water is AT the doorway. Flag meanings are published under
  `flags` in `research/flood-10-coefficients.json` — link it, do not re-word it.
- **NO WALL CLOCK anywhere in this family, by design.** Date every payload the way the page
  already dates the others: response `Date` minus `Last-Modified`, same origin, both on the
  origin's clock. A writer's stamp would break the byte-identical re-export these files are
  evidence for, and it would read FRESH over a week-old table anyway.
- An asset ABSENT from the manifest is **"no events on record"** with NO request. That is
  the whole point of the manifest — do not fetch to discover an absence.

**ONE GAP THE SEAM STILL HAS, and it is not yours to close.** `assets_in_area` — the query
your MCP-facing siblings use — still returns `{asset_id, kind, name?, cell, complex_id?,
n_events, last_event_id?}` and **no coordinate**, so an agent that asks "what is near here"
still cannot place the answer on a map without a second lookup. That is the third time this
repo has shipped that shape. notify 05 worked around it (one flat `ref/assets` projection,
resolved in python) rather than editing `query.QUERIES`, because notify 06 froze the four
tools and their row shapes for wave 7. **The real fix is `lon`/`lat` on `assets_in_area`'s
asset rows — additive, ~4 lines — and it belongs to the next session that owns `query.py`.**
