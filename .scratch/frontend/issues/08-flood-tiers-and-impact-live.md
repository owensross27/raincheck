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
