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
- **MUST, and it bites the first slice to add code: `web/app.js` is 781 lines and
  `tests/test_live.py` is 775, both against an 800 cap.** SPLIT THE FILE, never the page
  (frontend 01 D1): a second `<script src="layers.js">` tag plus ONE line in `publish.py`'s
  `site` family tuple, and the same for a second test module beside the existing seam.
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
