# frontend3 01 — teardown of the live page and the redesign spec

Wave 11 box A (Ross-chartered 2026-08-27, from a screenshot review). This document is
the spec box B implements; its decisions are restated as MUSTs in
`waves/wave-11.md` box B. Charter: presentation moves, claims do not — every number,
gate and honesty string keeps its meaning.

Deliverables in this commit:

- this file
- `web/prototype-frontend3.html` — static layout proof over the page's real `files/`
  JSON (no new data; `web/{files,vendor,tiles}` are gitignored and were symlinked from
  the main checkout into the worktree)
- `research/frontend3-01-proto-1280.png` · `research/frontend3-01-proto-375.png` —
  headless screenshots of the prototype (swiftshader/CDP recipe, cold profile per run)
- `research/frontend3-01-live-1280.png` · `research/frontend3-01-live-375.png` — the
  LIVE page photographed the same way, the same day, as the before

Every observation below says which host it is from. The live page is
`https://rainchecknyc.com/` (the apex, fixed 2026-08-27 — never `r2.dev`, disabled,
401s). A headless screenshot proves LAYOUT and never BEHAVIOUR: the live panel's 30 s
rAF tick does not fire in a hidden tab (`web/app.js:118`).

---

## 1. Teardown of the LIVE page

### 1.1 The numbers behind Ross's complaint (measured on rainchecknyc.com, 2026-08-27, CDP)

At **1280x800**: `#left` 380x574, `#right` 340x574, `#provenance` 1256x**194** —
the three chrome boxes cover **64.2% of the viewport**. The unoccluded map is a
~536x576 centre window, ~24% of the screen, on a page whose product is the map. The
provenance slab alone is 24% of the viewport height, permanently.

Default-visible words, by panel (`innerText`, live DOM): Layers **458** · insight 245
(66 of them visible pre-scroll) · provenance **198** · Live 126 · legend 24 — about
**1,050 words on screen by default**, before the analyst disclosure is opened. For
scale, Google Maps' default chrome carries ~30.

At **375x812**: the map is a 487px strip (60vh), and the stack below it runs
**~3,850px — 4.7 screens of panels** (Layers alone 1,704px, provenance 500px). Also
measured: MapLibre's compact `AttributionControl` renders EXPANDED over the map strip
at this width — a white box occluding ~15% of the only map a phone gets, duplicating
credits the strip below already carries.

Bytes (cold profile, this run): 32 requests / 1,635,289 B at 1280; 30 / 1,333,053 B
at 375; **zero console errors**. The byte totals and the zero-error count match
frontend2 06's record exactly at 1280 (its 30/28 request counts differ from this
harness's 32/30 because this one counts the always-aborted PMTiles request — block
4's `net::ERR_ABORTED`, not a defect — and the `/favicon.ico` 404 as requests).
The page is fast and correct; the problem is composition, not engineering.

### 1.2 What every piece of chrome is, and where it renders today

Classification: **R** = rider content (glance value), **A** = analyst content
(methodology, estimands, file-level detail), **L** = licence/serving obligations.
"Payload" strings render verbatim by frozen contract and cannot be reworded — only
relocated (their surfaces are the page's to arrange).

| Element (live page) | Class | Today |
|---|---|---|
| `h1` question + `#answer` band + gloss | R | top of `#insight`, correct |
| `#views` / `#hours` buttons | R | `#insight`; 6 view pills + up to 7 hour pills, three wrapped rows |
| `#recent` "Flooding on record" rows + payload caveats | R (payload strings verbatim) | `#insight`, 501px tall, pushes the analyst summary off-screen |
| `#analyst` `<details>` (estimands, CI rows, curve, chord/hidden/gate notes) | A | correctly behind the ONE disclosure, closed — D7 holding |
| `#legend` ramp + ticks + grey note | R | own panel, 97px — fine |
| `#legend` "rain: AORC hourly, hour-ending" | A/L | legend; a data-provenance qualifier, not a reading aid |
| `#layers` intro paragraph (chip vocabulary decoder) | A | inline, 40 words before any control |
| Layer rows: name + checkbox + chip + `sub` line | R | correct — this IS the control |
| Per-source rows (`files/*.json` paths + age + chip + "no budget frozen…") | A | inline under every row, always; file paths are analyst vocabulary |
| Gate reason paragraph ("Dark: publishing anything on this gate side…", 30 words) | R/L | inline, repeated per gated row |
| Byte-warning paragraphs (7.8 MB / 4.4 MB / 1.5 MB, three paragraphs) | A | inline in `#layers`, 90 words — two of the three describe layers that 404 on this host |
| `#live` h2 + toggle | R | own panel |
| `#live` prose (30 s mechanics, snapshot-only, delay line, MRMS line) | A/L | inline, 4 paragraphs always visible |
| `#provenance` pipeline sentence + `#prov-files` | A | the slab |
| `#mta-gate` paragraph (74 words) | L | the slab |
| `#geo-attribution` (dynamic, empty today) | L | the slab |
| `#basemap-attribution` (3 sentences) | L | the slab — the always-visible credit, test-pinned |
| `#attribution` MTA non-affiliation (43 words) | L | the slab |
| MapLibre compact AttributionControl (runtime `<details>`) | L (duplicate) | bottom-right over the map; expanded at 375 |

The diagnosis in one line: **rider content and controls are already mostly right;
the page drowns them by rendering every analyst qualifier and licence paragraph at
full text, always, on every surface.** (a), (b), (c), (d) of the charter are all this
one defect in four places.

### 1.3 Which layers are dark, and why — three distinct reasons (block 5), verified on the live host today

Probed 2026-08-27 against `rainchecknyc.com` (status codes below are this session's
own curl, not inherited):

- **(a) MTA-GATED — a licence refusal (rc 3 at publish; `publish.LIVE_TERMS_VERIFIED
  is None`).** `files/live.geojson` 404 · `files/meta.json` 404 ·
  `files/flood-mta.json` 404 · `files/impact.json` 404 · `files/impact-subway.json`
  404. Layers: Live fleet, MTA alerts, both impact overlays. The page renders these
  GATED — correct, pinned, and the redesign keeps them visible and explained.
- **(b) THE WRITER GAP — nothing publishes them yet** (`raincheck-live`'s emptyDir;
  cloud 10's cutover). `files/flood.json` 404 · `files/flood-meta.json` 404. Layer:
  FloodNet tier. Its row reads OFF by default; when ticked it reports "not published
  on this host". **Consequence for verification: the honesty string
  (`strings.operating_truth`) renders only off this payload and CANNOT be shown in a
  public screenshot — it is dispositioned by grep of `web/live.js`, never by
  screenshot.**
- **(c) SOURCE FILES ABSENT FROM THIS MAC — a data-build gap, not a publish bug.**
  `files/geo/routes.geojson` 404 · `files/geo/scenarios.json` 404 ·
  `files/history/manifest.geojson` 404. Layers: Bus route lines, DEP flood zones,
  flood-history markers. One measured sharpening of block 5(c): **the 4.4 MB
  `files/geo/stormwater-moderate.geojson` IS served (200) but unreachable by the
  page**, because the zones layer's first source is the `scenarios.json` manifest,
  which 404s — the layer is dark while its data sits on the host. (The wave-10 gate
  built `web/files/history/` locally; it is still unpublished, so (c) stands for all
  three.)

So of the page's 15 data URLs, **9 return 404 today** and 6 serve. The redesign
designs against what is there: one lit fill (Delay cells), two ground layers
(basemap, taxi zones), the recent list — and honest chips for everything else.

### 1.4 Variants B and C (branch `frontend02-four-layers`, `1275e52`) — what is KEPT, what is RETIRED

Read before designing, per DESTINATION Q7: `.scratch/frontend/prototypes/` (A/B/C)
and its ticket file; `research/14-serving-prototype/` is the older third tree
(pre-chassis, superseded by the chassis itself — nothing to take).

**KEPT:**

- **C's hover-locate ring** — already shipped (`web/app.js:135-142`, the `locate`
  layer): the recent rows ring their Cells. The redesign keeps it untouched; it is
  exactly the map-as-index interaction Q7 wanted for crowding.
- **C's ledger row grammar** (date left, counts right, whole-row hover/focus target)
  — already the `#recent` markup. Kept.
- **B's dense freshness GRID, relocated** — B proved the per-source table reads best
  as one compact aligned grid instead of stacked rows-with-reasons. The redesign
  keeps that finding but moves the grid to detail-on-demand (§2.4): per-source rows
  leave the default view entirely, and where they render (row detail, info surface)
  they render as B's grid, not as today's stacked lines.

**RETIRED:**

- **B's everything-at-once channels** (fill + outline-width encodings, all point
  layers lit) — the ticket's own finding 7 measured it unreadable at 7,955 markers,
  and D1 froze the exclusive fill channel. Nothing of it returns.
- **C's points-never-paint / panel-as-primary-surface** — Ross picked A (the map is
  the surface); the redesign is A with the prose demoted, not C revived. The ledger
  stays a complement to the map, never its replacement.

---

## 2. The design spec

Design priorities, in Ross's standing order: Anti-slop > Accessibility > Touch >
Performance > Style > Layout — plus the web-mapping canon: map-first chrome,
progressive disclosure (glance → tap → detail), one ramp at a time (already
structural, D1), legend visible only when a ramp is lit, detail on demand.

Anti-slop note, resolved structurally: the distinctive character of this page is its
**honesty grammar** — chips, hollow rings, explained absence — not a novelty
typeface. A webfont would be a new vendored asset (the static contract bars new
origins; `make vendor` is sha-pinned scope) for no legibility gain; the system stack
stays and the anti-slop budget is spent on hierarchy, spacing and microcopy.

### 2.1 Layout — 1280 (map-first, floating cards)

Map full-bleed, unchanged. Three floating surfaces plus one credit line:

```
+--------------------------------------------------------------------+
| [ANSWER CARD 340w]                              [LAYERS CARD 300w] |
|  h1 question                                     h2 Layers         |
|  0.72–0.82  (big band)                           fill radio rows   |
|  one-line gloss                                  ground/point rows |
|  view pills · hour pills                          (name+chip+sub)  |
|  Flooding on record (5 rows)                     Live row + toggle |
|  ▸ Analyst details (ONE <details>)                                 |
|                                                                    |
| [LEGEND 220w]                            MAP                       |
|  ramp bar + lo/mid/hi · grey chip                                  |
+--------------------------------------------------------------------+
| Basemap © OSM contributors · Protomaps — ODbL · Not an MTA service ⓘ|
+--------------------------------------------------------------------+
```

- `#left` narrows 380 → **340px**; `#right` 340 → **300px**. Both stay
  `position: absolute` flex columns with `bottom: var(--prov)` — the measured-
  clearance mechanism (ResizeObserver on `#provenance`) is kept verbatim;
  `tests/test_page.py:564`'s shape survives unchanged.
- `#insight` order: h1 → `#answer` → `#views` → `#hours` → `#recent` (5 rows, was 8;
  the cap note names the rest) → `#analyst`. The analyst summary must sit above the
  fold of its own card: `#recent` gets `max-height: 40vh; overflow-y: auto` so the
  disclosure is never scrolled out of existence (measured today: the summary sits at
  y=788 of an 800px viewport — effectively invisible).
- `#legend` renders **while a RAMP is on screen** — not "while a fill is lit": with
  the Cell fill OFF, the route line and the zone fill carry the same ramp (D1's
  other half), and hiding the key for a painting ramp would contradict the rule the
  OFF row exists to reach. The owner is `applyRamp()` (insight.js), which already
  computes exactly this value (`fillOn || ramped`); it toggles `hidden` on
  `#legend` and NEVER removes the elements — `paint()` writes unconditionally into
  `#legend-title`/`#swatches`/`#tick-*`, so destroy-and-recreate throws on the next
  view switch. All five legend ids survive. The "rain: AORC hourly, hour-ending"
  line moves to the info surface (§2.3) — source provenance, not a reading aid.
- **`#card` (the flood record card) is unchanged in mechanism and stays a flex
  sibling of `#layers` inside `#right`** — now the 300px column — still `hidden`
  until a hist marker (or box B's inherited keyboard route from `#recent`) opens
  it, `max-height: 46%` kept, `#card`/`#card-close`/`#card-h`/`#card-id`/
  `#card-body` and the closeCard focus return all survive. The spec narrows its
  column; nothing else about it moves.
- `#provenance` collapses to a **credit strip** (~28px one line at 1280 against
  today's 194px; it WRAPS below 900px — an ellipsis that clips the ODbL sentence
  would be the `:532` killed mutation achieved in CSS). Everything else it held
  moves to the info surface. Contents, in order: `#basemap-attribution` (short
  form, §2.3), `#geo-attribution` (unchanged, empty → `display:none` today), a
  five-word MTA non-affiliation shorthand, and the ⓘ button. It becomes a
  `<footer>` landmark. **The `<dialog id="info">` markup sits BEFORE `#provenance`
  in index.html source order** — `tests/test_page.py:545` slices from
  `id="provenance"` to end of file, so a dialog placed after the strip would let
  the credit pass the check from inside a collapsed surface, silently weakening
  what the row measures. Box B may additionally bound that slice (split at
  `<dialog` or `</footer>`) as a hardening, proving it still fails when the credit
  moves into the dialog.
- **The NavigationControl gets a stated home**: full-bleed map + a full-height
  right card + a bottom strip cover MapLibre's default bottom-right corner at
  1280. Offset it clear: `.maplibregl-ctrl-bottom-right { right: 316px;
  bottom: calc(var(--prov) + 8px) }` (or equivalent), and verify by hit test at
  both widths.
- Landmarks (from box B's inherited a11y block, adopted here as layout): `<main>`
  wraps **`#map` + `#left` + `#right`** — the map is the main content of a
  map-first page and must be inside a landmark; a skip link ("Skip to controls")
  is first in the DOM; `#provenance` is the `<footer>`.

Measured on the prototype (same CDP probe as §1.1, not estimated): chrome share
**52.1% at 1280 (was 64.2%)** — the strip 194px → **45px**, default-visible words
1,051 → **318 as prototyped, ≈410 like-for-like** (the prototype omits
`recent.json`'s label + three caveat sentences, ~90 words of payload prose that
render verbatim by contract and must be counted; the analyst summary stays on-card
either way — `#recent`'s 40vh cap absorbs them, measured 240px against a 325px
cap). The whole centre-plus-bottom map band is clear. The residual is the two
columns' width, and that is the answer surface (D5/D7), not slop; if Ross wants
more map still, the next lever — panels collapsing to pill buttons — is named as
an option, not specified.

### 2.2 Layout — 375

Map 60vh (kept — the SMALL rule and its two-layer legibility finding stand), then:
**legend** (the fill is ON by default at 375, so its key renders directly under the
map strip) → answer card → recent (5) → analyst disclosure → layers card (+ `#card`
stacked immediately after it when open) → live row. Stack under the map, measured
on the final prototype: **≈1,830px as prototyped, ≈1,930px like-for-like (was ~3,850px)**
— halved by §2.4's demotions alone, no content deleted. `#recent`'s 40vh cap is
RESET below 900px (`max-height: none`) — the cap exists to keep the analyst
summary on-card at 1280, and at 375 it would only manufacture a nested scroller
inside an already-scrolling page.

**The credit strip is position-fixed at the viewport bottom at EVERY width** —
that is what carries the OSMF "in a corner of the map or adjacent to it"
requirement on a phone, where the stack would otherwise put the only credit ~1.5
screens below the map. At ≤900px it wraps to two or three lines (~40-50px of an
812px viewport, against the 500px slab it replaces); never `nowrap`/ellipsis.

**The MapLibre compact `AttributionControl` is REMOVED** (the `addControl` at
`web/app.js:49-51`). Measured at 375 it renders expanded over the map strip; the
page's own comment already calls it "a convenience, never the attribution itself",
and with the credit strip fixed at the viewport bottom the adjacency requirement
is met at BOTH widths by the strip. No test pins the call (grepped);
`layers.js:283` already passes `attributionControl: false`, so nothing re-adds a
default one. This also removes the SECOND runtime `<details>` MapLibre injects
(measured: the live DOM holds 2 while the source holds 1) — one less disclosure
widget for a screen reader. **One credit in its customAttribution string exists
NOWHERE else on the page: "nycbuspositions archive"** (the 2017-2024 archive
behind every historical bus number, the Ida view included). Collapse, never
delete: it joins the pipeline sentence in info §1 in the SAME commit that removes
the control, and it is a §4 grep target. The other four credits already live in
the strip or the dialog. The `NavigationControl` stays (relocated, §2.1).

### 2.3 The info control — the element, named

**`<dialog id="info">`, opened with `showModal()` by the ⓘ button in the credit
strip.** Not a second `<details>` (`tests/test_page.py:955` holds at 1) and not a
styled div: a native dialog brings focus trap, `Esc`-to-close and `::backdrop` from
the platform — the same "platform semantics over hand-rolled" argument D7 used for
`<details>`. Wiring lives in `app.js` (the cyclic-module rule). Button: 44x44px
target, `aria-haspopup="dialog"`, visible focus ring; dialog carries
`aria-labelledby`, a close button, and closes on backdrop click. On 375 it styles
as a full-width bottom sheet (`margin: auto 0 0; width: 100%; max-height: 85vh`).

Content, in sections (everything moved here is MOVED, not deleted):

1. **About this map** — the pipeline provenance sentence (Kafka → Spark/Sedona →
   GeoParquet → DuckDB → MapLibre) + `#prov-files` (footprint-cell count, gate
   width) + the source credits the deleted AttributionControl carried, **the
   "nycbuspositions archive" credit included** (its only other home was the
   control) + one "where the data lives" line naming `files/` and
   `docs/read-api-contract.md` (the home §2.7 row 7's shortened cap note points
   at).
2. **Rain sources** — the AORC line (from the legend) and the MRMS qualifier
   context.
3. **The MTA gate** — `#mta-gate` verbatim. `tests/test_page.py:471` pins the
   LITERAL `not\n  verified` (newline + exactly two spaces) — an indentation
   artifact of the paragraph's current nesting, so this is a CONSTRAINT, not a
   free ride: inside the dialog the paragraph must keep a continuation line
   breaking between "not" and "verified" with a two-space indent regardless of
   nesting depth — or box B changes the check to a whitespace-normalised assert in
   the same commit and proves it still fails when the sentence is missing.
4. **Licences** — the full basemap Produced-Work text + Noto Sans/SIL sentence and
   the full `#attribution` MTA non-affiliation paragraph. **NOT the DEP/GTFS
   credits**: those are payload-driven by rule (`#geo-attribution`, a pinned
   mirror-ban — writing DEP's sentence into static page copy is the killed
   mutation), so the dialog may only point at the strip's geography line in words
   that name no source.
5. **Serving contract** — the "current snapshot only, no bulk or protobuf" sentence.
6. **Reading the chips** — the five-state vocabulary decoder (FRESH / STALE / OFF /
   GATED / AGE), one line per state.

What does NOT move into it: `#basemap-attribution` (test-pinned to the strip, §2.6),
`#geo-attribution` (its own test's docstring pins it to the always-mounted strip; it
costs zero pixels while empty and one line while a geo layer is lit — kept in the
strip), and every per-row GATED reason (chip + row detail, §2.4 — absence stays
explained at the point of absence).

The credit strip's short form keeps every pinned string:

> `Basemap © `[`OpenStreetMap contributors`](https://www.openstreetmap.org/copyright)`, built with `[`Protomaps`](https://github.com/protomaps/basemaps)` — map data under the Open Database License (ODbL). Not an MTA service.` ⓘ

(`tests/test_page.py:545` needs: the `<p id="basemap-attribution">` element in the
strip and the five literals "OpenStreetMap contributors", the copyright URL, "Open
Database License (ODbL)", "Protomaps", the protomaps/basemaps URL — all present
above. The mutation the test kills — credit only in a collapsed control — stays
killed: this line never collapses.)

### 2.4 The Layers panel — a control is a control

Default row = `[input] Name ····· CHIP` (min 44px hit area; the whole label is the
target) + the one-line `sub` beneath it in 12px dim. That is ALL a row shows by
default. Everything else becomes detail-on-demand:

- **Per-row detail** — a chevron button per row (`aria-expanded`, rotating glyph,
  35x44 target), collapsed by default, holding: the per-source grid (B's grid: one
  row per source — key · age · chip · reason), the gate reason for GATED rows, the
  byte warning for heavy layers, and the `owed` note where one exists. Not a
  `<details>` — a button + hidden div, so `:955` holds. **The state model is
  named, because `renderLayers()` rewrites the rows' innerHTML on six events
  (every toggle, view switch, hour switch, scenario change, boot, and every 30 s
  while the live toggle is on):** a module-level `openDet` Set in `panel.js`
  keyed by layer id (the `on[]` idiom), read by `rowHTML()` to emit
  `hidden`/`aria-expanded`, written by a delegated click handler in `app.js`
  (every listener lives there — the cyclic-module rule, test-enforced); and the
  `panel.js:79-86` focus restore grows a third case for the chevron's own data
  attribute (`data-det`) so focus returns to it after a rebuild. Without both, a
  reader's open detail slams shut and focus falls to `<body>` on every hour
  click.
- **GATED rows**: chip always visible (pinned), reason one tap away in the row
  detail — exactly the "chip/badge + detail-on-demand" compression the pinned list
  licenses. The reason keeps the phrase "does not exist", and the pin is on
  **`rowHTML`'s own function body** (the test slices `js` from
  `function rowHTML` to the first `\n}` and greps inside), so the detail markup
  is built INLINE in `rowHTML` — no extracted `detailHTML()` helper, or the slice
  loses the literal and the check goes red for a page that still prints it. The
  same slice pins `const kind = lyr.fill ? "radio" : "checkbox";` and
  `name="cellfill"`.
- **The OFF fill row ("None — show the geography instead") gets NO chip and NO
  source detail** — it declares no layer and has no source, and a five-state chip
  on a radio state would be a sixth meaning for a frozen vocabulary. It keeps only
  its one sentence (§2.7 row 15).
- **Layer legends** (`lyr.legend`: fn panel text, zone legend + scenario radio,
  route grey-reason, hist count) stay AUTO-SHOWN while their layer is LIT — a legend
  for visible data is not methodology, it is the map key. They collapse with the
  layer.
- The panel intro paragraph (chip decoder) leaves the panel for info §6; the chip
  element itself gets `title` text as a pointer hover affordance (never the only
  path — the decoder is one tap away for touch).
- The two byte-warning paragraphs about `routes`/`stormwater`/`hist` move into those
  rows' details — and stop rendering as page-level warnings for data that 404s on
  this host today.
- **The Live panel merges into the layers card as its last row group — as STATIC
  MARKUP in `index.html`, never as a `rowHTML()`-generated row.** This is
  load-bearing, not taste, and the two readings differ by four pinned asserts:
  `tests/test_page.py:147` pins the byte-adjacency `id="livetoggle" disabled` in
  the HTML; `:162` pins the MRMS literal in `page_html()` (the HTML, not the JS);
  `:620` pins `id="src-live"`/`id="live-chip"` in the HTML; and `:626` pins the
  exact `LAYERS.filter(l => !l.fill && !l.toggle).map(rowHTML)` source — the live
  layer is deliberately OUTSIDE the generated list (`toggle: "livetoggle"`,
  unchanged). And `app.js:117-120` attaches a DIRECT listener + the
  enable-on-load to `$("livetoggle")`: inside an innerHTML rebuild both would die
  silently — the exact failure `test_the_toggle_waits_for_maplibre…` exists to
  prevent. So: the `#live` subtree moves inside `<section id="layers">` after
  `#layers-pts`, restyled as a row group; the h2 demotes to a row line **keeping
  `id="live-h"`** (app.css's `.stale` STALE affordance binds `#live.stale
  #live-h::after` — keep the id or re-point the rule in the same edit);
  `#livemeta` renders under it while the toggle is on; the snapshot-only sentence
  goes to info §5; the delay + MRMS lines go into a STATIC hidden detail div in
  the HTML (ids `#delaystate`/`#rainstate` and the pinned MRMS literal intact,
  byte-position free). Only `#src-live` and `#live-chip` keep being filled by
  `renderLayers()`. All wired ids survive; only their geometry changes.
- **The mount points stay `#layers-fill` and `#layers-pts`** (both pinned in HTML
  and JS, `:620`/`:681`), and the legend's five ids
  (`legend-title`/`swatches`/`tick-lo`/`tick-mid`/`tick-hi`) are untouched — the
  prototype's `rows-fill`/`rows-pts` ids are throwaway, not structure.

### 2.5 Type scale, spacing, color

**Type scale** (system stack, unchanged family):

| Role | Now | Spec |
|---|---|---|
| h1 (the question) | 16px/-.01em | **17px/650/-.01em** — it is the page title |
| `.big` (answer band) | 26px (22 in `#answer`) | 24px both — one size for the one number |
| body / row names | 14px | 13px in panels (map-first: chrome dims a step) |
| `.note` | 12px | 12px, but ≤ 2 lines anywhere visible by default |
| `.lbl` caps labels | 11px/.06em | unchanged |
| chips `.st` | 10px/700 | **11px/700** (10px is below the floor for meaning-bearing text) |
| credit strip | 12px | 12px, one line |

**Spacing**: 4px base grid. Panel padding 12x14 (kept). Row rhythm: 8px vertical
padding, **44px minimum height for layer rows, chevrons and the ⓘ button** (today
~30px / 36px in the first prototype cut), 8px between control groups, 12px card
gap. **Stated deliberately, not an oversight: the view/hour pills stay at 36px
min-height with ≥8px gaps** — 44px on thirteen pills costs a third row of vertical
in the answer card; 36px + real spacing clears WCAG 2.5.8's 24px floor with
margin, and the pills are the one control dense enough to price it. Radius 10px,
`--line` borders, panel translucency + blur kept.

**Color**: page palette untouched; chip hues untouched (test-pinned set); GREY
untouched — at 1.86:1 it deliberately recedes, which is its job ("no publishable
value" must not pop). **The ramp: argument stated, decision surfaced, DEFAULT
UNCHANGED.** The charter says do not restyle the diverging ramp without the
perceptual argument; here is the argument, with the arithmetic done at the pixel
the map paints, not the swatch:

- `RATIO_STOPS[0]` `#7f0000` is **1.76:1 as a swatch** against `#0b0d10` — and the
  Cell fill paints at `fill-opacity: 0.86`, so the rendered pixel composites to
  ≈`#6f0202` = **1.56:1** on the flat ground (lower still over lit basemap land).
  WCAG 1.4.11's 3:1 for meaning-bearing graphics fails, in the worst direction: on
  a dark ground, luminance contrast carries a fill, so the ramp as built makes the
  **worst slowdown the least visible thing on the map** while "no change" white
  pops hardest. Dark-equals-severe is a light-basemap convention riding on a dark
  basemap.
- **The cheap fix does not exist.** A first draft of this spec lifted the one stop
  to `#b91c1c` (3.01:1 as a swatch) — but composited at 0.86 that renders
  ≈**2.48:1, still failing**, and the lift cuts the two most severe buckets'
  adjacent-step separation from 2.28x to 1.33x — trading a ground-contrast failure
  for an adjacent-fill one. Composited 3:1 forces the darkest stop up to roughly
  `#d7301f` — i.e. a real re-spacing of the whole slower arm (four new OrRd-family
  anchors, monotone, composited 3:1 → ~12:1), not a one-stop edit.
- **DEFAULT (this spec, the prototype, and box B unless Ross opts in): the ramp is
  BYTE-UNTOUCHED** — `tests/test_page.py:578`'s pin stays honored — and the
  residual is stated: the 0.5-bucket reads at composited 1.56:1 and relies on
  adjacency to its brighter neighbours to be seen. **OPTION, Ross's call at the
  gate: re-space the slower arm** to composited-3:1 anchors; that is a data-ramp
  restyle + the `:578` check change in one commit (§2.6 row 5), with the new stops
  chosen by the constraint above, not by eye.
- Noted, FILED, not changed: `SPEED_STOPS`' dark terminus `#0d1b2a` is **1.12:1
  (swatch)** on the same ground — the same defect class on the dry-baseline
  (analyst-selected) view. Same constraint applies if it is ever taken.

### 2.6 The test-enforced conflicts — honored, or asking to change the check

The four from the PINNED list, plus one this spec adds:

| # | Check | Disposition |
|---|---|---|
| 1 | `tests/test_page.py:955` — `html.count("<details") == 1` | **HONORED.** The info control is `<dialog id="info">`, not a details; `#analyst` stays the ONE disclosure. (The count also stays honest in the DOM: removing the MapLibre compact control removes the runtime second `<details>`.) |
| 2 | `:532/:545` — basemap credit in the mode-invariant strip (killed mutation: credit in a collapsed control alone) | **HONORED.** `#basemap-attribution` stays in the always-visible strip in the §2.3 short form carrying all five pinned literals + both links + the ODbL sentence; only the Produced-Work/fonts prose moves to the dialog. `#geo-attribution` also stays in the strip. |
| 3 | Honesty string visible in both views (`:835`; renders only off `files/flood.json`, 404 in public) | **HONORED BY CODE PATH.** `web/live.js`'s `drawFn` rendering of `strings.operating_truth` is untouched by this spec; the fn legend still renders under the fn row when lit, in both views. Dispositioned by grep of `web/live.js`, never by screenshot. |
| 4 | `:977` verbatim localStorage source line · `:564` bans `bottom: 84px` | **HONORED.** The disclosure-persistence lines in `app.js` do not change; the measured `--prov` clearance mechanism and both `position: absolute` column rules survive verbatim. Box B still owes the fix-by-shape of both brittle tests (its inherited item 4) — independent of this layout. |
| 5 | `:578` — `RATIO_STOPS` pinned byte-exactly, `#7f0000` included (**found by this ticket**) | **HONORED BY DEFAULT; check change offered as an OPTION.** §2.5 states the full argument including the 0.86-composite arithmetic; the default keeps the ramp byte-untouched (the one-stop lift was drafted and WITHDRAWN — composited it still fails 3:1 and halves the top buckets' separation). If Ross opts into the slower-arm re-spacing at the gate, box B changes `:578`'s literal in the same commit as the stops, with the constraint (composited ≥3:1 at the terminus, monotone, OrRd family) in the docstring, and proves the check still fails when a stop is nudged. |

Checks box B will touch for its OWN inherited items (named so nothing surprises
the gate):

- the `cache: "no-store"` literal is asserted **TWICE** — `test_page.py:138` and
  `:386` — and both go red when the no-store → no-cache fix lands (change checks +
  code in one commit); the third no-store site, `basemap.js:95`, has **no test at
  all**, so the fix there needs its own assert or the gate's ledger must not read
  a one-file change as complete;
- `:471`'s `not\n  verified` literal must survive `#mta-gate`'s move into the
  dialog (§2.3's constraint — the wrap is an indentation artifact, keep it
  deliberately or normalise the check);
- `:1013` asserts the literal `$("recent").addEventListener("mouseout"` — box B's
  inherited mouseout → mouseleave fix turns it red; change check + code together
  and assert the PAIR (ring set on enter, cleared on leave), not the event name.

### 2.7 Microcopy — every page-authored panel string, with a shorter candidate

Payload strings (`strings.*`, caveats, estimands, tier labels, `operating_truth`)
render verbatim by frozen contract and are NOT in scope. Pinned literals are marked.
Meaning is preserved in every candidate; where a string moves, §2.3/§2.4 said where.

| # | Now (live page) | Candidate | Home |
|---|---|---|---|
| 1 | "Does rain slow the NYC buses, and where?" | keep — it is the product in nine words | answer card |
| 2 | "how fast the buses moved in this rain, as a share of their dry-weather Speed — 1.00 means no change (Ida 2021-09-02)" | "bus speed in this rain vs dry weather — 1.00 = no change (Ida 2021-09-02)" | answer card |
| 3 | "loading…" (x2) | keep | — |
| 4 | "Analyst details — estimands, intervals, gates and the curve" | "Analyst details — estimands, intervals, gates" (the curve is inside; three nouns carry it) | disclosure summary |
| 5 | "Flooding on record, {since} to {until}" | keep (dates are payload facts) | recent header |
| 6 | "Point at an event to ring its areas on the map." | "Point at a row to see it on the map." | recent |
| 7 | "…and N earlier events in files/summary/recent.json." | "…and N earlier events." — the file path moves to info §1's "where the data lives" line, which is the home this shortening depends on | recent |
| 8 | "Speed ratio, wet over dry" / "Dry baseline Speed, m/s" (the JS-written legend titles; the HTML default is the bare "Speed ratio") | keep, in full — the qualifier is the axis meaning | legend |
| 9 | "grey = no publishable value for this layer" | "grey — no publishable value" | legend |
| 10 | "rain: AORC hourly, hour-ending" | unchanged text, moved | info §2 |
| 11 | "Each row is one data source and its chip says how current it is; a bare AGE means no staleness budget is frozen for that file. Nothing is fetched until you tick it." | "Nothing loads until you tick it." (row line) + the full decoder verbatim in info §6 | layers header / info |
| 12 | "Cell fill — pick one" | keep — it is the radio's name and D1's rule in four words | layers |
| 13 | "One fill at a time: both options colour the same areas with one shared ramp, so they can never disagree on screen." | "One ramp at a time." (full sentence to info §6) | layers → info |
| 14 | "None — show the geography instead" | keep | fill radio |
| 15 | "One ramp on screen at a time: with the Cell fill off, the flood zones fill and the route line carries the ramp instead of the Cells." | "With the fill off, zones and routes carry the ramp." | OFF row detail |
| 16 | "Ground and points" | keep | layers |
| 17 | "The bus route lines are 21,868 Cell crossings and 7.8 MB; the flood zones are 4.4 MB. Neither is fetched until you tick it." | "Loads 7.8 MB when ticked." / "Loads 4.4 MB when ticked." — one line inside each row's detail | row detail |
| 18 | "The flood-history markers are 8,146 assets and 1.5 MB, fetched once when first ticked — never at boot. Clicking a marker fetches that one asset's record alone (median ~1 KB, at most 22 KB)." | "Loads 1.5 MB once when ticked; each marker click fetches ~1 KB." | hist row detail |
| 19 | "Dark: publishing anything on this gate side needs the MTA redistribution terms verified. The row stays, so the page never pretends the layer does not exist." | "Dark: needs the MTA terms verified. The row stays so the page never pretends the layer **does not exist**." (pinned phrase kept) | gated row detail |
| 20 | "Declared and dark: {ticket} lands this payload." | keep (owed notes are already one line) | row detail |
| 21 | "Live: the fleet right now" | "Live fleet" (row form; "right now" is the chip's job) | live row |
| 22 | "off - tick the box below to fetch files/meta.json every 30 s. Nothing is fetched until you do, so nothing here can look live when it is not." | "off — tick to fetch every 30 s; nothing can look live when it is not." | live row |
| 23 | "Current snapshot only: no vehicle history is served here, and there is no bulk or protobuf download." | unchanged text, moved | info §5 |
| 24 | "MTA-reported trip delay: …" / "rain: MRMS RadarOnly QPE 01H, uncalibrated, hour-ending, …" | unchanged — "MRMS RadarOnly QPE 01H, uncalibrated, hour-ending," is **pinned verbatim** (`test_page.py:163`) | live row detail |
| 25 | "show vehicles (30 s refresh)" | keep | live row |
| 26 | Provenance pipeline sentence ("Kafka 3.9 → … read by range request.") | unchanged text, moved | info §1 |
| 27 | `#mta-gate` paragraph | unchanged text (the `not\n  verified` wrap is **pinned**, `:471`), moved | info §3 |
| 28 | `#basemap-attribution` (3 sentences) | §2.3 one-line short form in the strip (five pinned literals kept); Produced-Work + fonts sentences to info §4 | strip + info |
| 29 | `#attribution` MTA non-affiliation (43 words) | "Not an MTA service." in the strip; full paragraph verbatim in info §4 | strip + info |
| 30 | "N assets with a flood record. Click a marker for its record card - one small fetch per click." | "N assets with a flood record — click one for its card." | hist legend (lit) |
| 31 | "Dark: the vehicle side of the MTA gate is shut, so the fleet is not published on this host. The toggle stays: locally, `make live-export` writes the two files and the panel reads them." (panel.js → `#src-live`) | "Dark: the vehicle gate side is shut, so the fleet is not published on this host. The toggle stays. (Locally, `make live-export` feeds it.)" | live row detail, beside `#delaystate`/`#rainstate` |
| 32 | applyRamp()'s three route grey-reason sentences ("A Cell fill is on, so these are geometry only…" / "…a single storm HOUR…carries no interval…" / "Coloured by {view} — the same estimand…") | keep — each states WHY lines are grey in the current state, which is exactly detail-at-the-moment-of-need; they render only while the routes layer is lit | routes row (lit) |
| 33 | zoneLegend()'s "DEP design storm: N in/hr, current sea level. A PLANNING map of what would flood at that rain rate - not an observation of water, not a forecast, and not a site-specific determination." | keep verbatim — it is the layer's honesty sentence, shown only while lit | zones row (lit) |
| 34 | drawCells()'s two failure strings ("the insight files are not published on this host." / "export files missing - run `make export` and reload.") | keep — error states, already terse, and pinned to land on the rider surface | `#answer` on failure |
| 35 | showCard()'s "Source counts are city-wide at EVENT grain — what the whole event generated across the city, not what was observed at this asset." | keep — a claim-scope sentence; shortening it changes what it claims | record card |

Scope note: rows 1-30 are the strings visible at DEFAULT state (index.html +
`rowHTML`); rows 31-35 are the page-authored strings that render only inside a lit
layer's row, an error state or the card — enumerated so their absence from the
table cannot be read as a deletion licence. Payload strings stay out of scope
(verbatim by contract).

Net effect at default state, measured like-for-like on the prototype: ~1,050
visible words → **≈410** (318 as prototyped + ~90 words of verbatim recent.json
label/caveats the prototype omits), nothing deleted, every demoted sentence one
interaction away.

### 2.8 What this spec deliberately does not do

- No basemap restyle, no replacement frame (block 10 — the recommendation to keep it
  stands; not this ticket's call).
- No new fetches, no new origins, no new data files — the prototype and the spec
  consume exactly today's static contract.
- No change to any payload contract, `publish.FAMILIES`, or `src/` (the favicon
  `site` key etc. are box B's own inherited items).
- No forecast language; the five-state vocabulary intact; "is", never "might".

---

## 3. The prototype

`web/prototype-frontend3.html` — one self-contained static file (inline CSS/JS —
legal here: `tests/page.py` reads only `index.html` + the published `site` modules,
so a `prototype-*.html` is invisible to every page test and never publishes; the
inline-script ban binds the page, not this artifact). It shares the page's REAL
assets over `make web`'s Range-capable server: vendored MapLibre + pmtiles, the
vendored basemap style and tiles archive, `files/cells.geojson`,
`files/headline.json`, `files/summary/recent.json`. No new data; the layer rows
render today's real chip states (cells AGE · impact/live/subway/mta GATED · the
rest OFF).

It proves LAYOUT at 1280x800 and 375x812 — the two committed screenshots — and the
info dialog, the row-detail pattern and the credit strip are real and clickable in
it. **It paints the REAL, unchanged `RATIO_STOPS`** (the ramp option in §2.5 is
Ross's to take, so the prototype does not presuppose it). It does NOT prove
behaviour (no live tick, no toggling of real layers), and its JS is throwaway by
design — its `rows-fill`/`rows-pts` ids and generated live row are visual
stand-ins, NOT the structure §2.4 specifies (static live markup, `#layers-fill`/
`#layers-pts` mounts): box B implements the spec in the real modules, not by
promoting this file.

Screenshots (cold `--user-data-dir` per run, swiftshader flags,
`Page.captureScreenshot` over CDP, never `--screenshot`):

- `research/frontend3-01-proto-1280.png` — prototype, 1280x800
- `research/frontend3-01-proto-375.png` — prototype, 375x812
- `research/frontend3-01-live-1280.png` / `-live-375.png` — the live page, same day,
  for the before/after read

---

## 4. Verification ledger for box B and the gate

Pinned strings and where they land (grep targets, all expected present after box B):

| Pinned thing | Where it lives after the redesign |
|---|---|
| "OpenStreetMap contributors" + copyright URL + "Open Database License (ODbL)" + "Protomaps" + basemaps URL | `#basemap-attribution`, in the always-visible strip |
| `#geo-attribution` empty-mounted element | the strip |
| `#mta-gate` + "not\n  verified" | info dialog §3, byte-identical text |
| MTA non-affiliation paragraph (`#attribution`) | info dialog §4 (strip carries "Not an MTA service.") |
| "MRMS RadarOnly QPE 01H, uncalibrated, hour-ending," | live row detail, verbatim |
| "STALE: the pipeline is not writing" / "over 5 min (agency-computed, unvalidated)" | `web/live.js`, untouched |
| `strings.operating_truth` render path | `web/live.js` `drawFn`, untouched — grep, never screenshot |
| "does not exist" (gated rowHTML phrase) | gated row detail sentence |
| five-state chips + `.st-*` hues | row chips, unchanged values |
| ONE `<details id="analyst">`, closed, seven analyst ids inside | answer card, unchanged |
| `bottom: var(--prov)` + measured `--prov` observer | unchanged mechanism |
| Snapshot-only sentence | info dialog §5, unchanged text |
| The five-state decoder sentence(s) | info dialog §6 |
| **"nycbuspositions archive"** (today only in app.js's customAttribution — deleted with the control) | info dialog §1, same commit; grep target for the gate |
| `#card` + `#card-close`/`#card-h`/`#card-id`/`#card-body`, closeCard focus return | unchanged, flex sibling of `#layers` in the 300px column |
| `id="livetoggle" disabled` byte-adjacency, MRMS literal, `#src-live`/`#live-chip` in HTML, `!l.toggle` filter | the STATIC live row group inside the layers card (§2.4) |
| `#layers-fill`/`#layers-pts` mounts, the legend's five ids | unchanged |
| The chevron detail state (`openDet` Set) + `data-det` focus restore | `panel.js` state + `app.js` delegation (§2.4) — box B adds a check that an open detail survives an hour switch |

Checks box B changes, each in the same commit as its code, each proven to still
fail when its subject is missing: `:578` (ramp literal, if Ross takes §2.5),
`:133` (`no-store` literal, when the inherited no-cache fix lands), and any
layout-shape assert its `web/` diff moves — `tests/test_page.py` is read WHOLE
first (its own box says so).
