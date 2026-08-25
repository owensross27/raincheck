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
  `visibility: "none"`. **MUST: never `addLayer`/`addSource`** — a test refuses both, because
  a lazily added layer lands on top of the order and a `beforeId` naming a missing layer
  throws. `promoteId` stays off everywhere (hex ids are silently dropped).
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
