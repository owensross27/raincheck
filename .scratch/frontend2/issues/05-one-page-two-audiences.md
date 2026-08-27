# frontend2 05 — one page, two audiences

**Status: done** (2026-08-27, branch `frontend2-05-audience-pass`)
Type: design pass, no new data
Gate: frontend 07 + frontend 08, both landed at the WAVE 8 GATE (`f6e783d`, 1712/45/0) — verified in RUN-LOG.md before starting.
Decision base: DESTINATION.md §3 ("less technical density" — design pass, not a rebuild), STATUS.md Q7, DESTINATION-PLAN §1 D7 (two audiences, one page, rider by default).

## What was decided and built

The page keeps ONE surface. The rider view is the default; everything analyst-grade
sits behind ONE disclosure, default closed.

- **Rider view (always visible):** the map with the basemap, the routes/zones/tier-point
  layer rows, ONE plain sentence per layer (`sub:` on each LAYERS entry, rendered under
  the layer name in `panel.js`), every freshness chip and source row in BOTH views, a
  one-line answer (`#answer`: the published band value with a plain gloss, no interval,
  no estimand), and a "Flooding on record" list from `files/summary/recent.json`.
- **Analyst view (ONE `<details id="analyst">` in `#insight`, default CLOSED):**
  `#preview-note`, the whole `#headline` block (per-row 95% intervals, estimand
  sentences, the sensitivity rows, the chord warning), the `#curve` figure, the
  how-to-read notes (`#note-chord`, `#note-hidden`, `#note-gate`), and
  `#legend-estimand` (moved out of `#legend`; the swatches and ticks stay rider-side).
  Everything moved VERBATIM — same ids, same render calls, no prose reworded.
- **Disclosure state** is remembered in `localStorage` (`raincheck.analyst`), both the
  read and the write in try/catch; absent or unreadable state means CLOSED. Verified in
  a real headless tab: closed by default, click stores "open", reload restores open.
- **The rider list** renders recent.json's `strings.label` and every `strings.caveats[]`
  sentence VERBATIM (escaped, never restated); the window prints the payload's own
  `since`/`until` dates — the word "today" appears nowhere in the render (the window is
  anchored on the spine's newest day_end). Rows are a date span + labelled-asset counts.
  Fetched through `grab()` (dated off its own response headers), `budget: null`.
- **Hover-locate (prototype variant C, taken):** hovering or focusing a list row rings
  that event's Cells on the boot-declared `locate` layer; centroids come from the map's
  own `cells` source, so cells.geojson stays ONE fetch. Rows carry `tabindex="0"`, so
  keyboard focus and a tap get the same ring. All wiring in `app.js` (cyclic-module rule).

## Prototype verdicts (both run in a real tab before designing, branch `frontend02-four-layers`)

- **Variant C (ledger + hover-locate): TAKEN** — the ranked "what is happening" list
  with plain-language rows and inline state chips became the recent-flooding list and
  the per-layer rider sentences; hover-locate landed on the existing `locate` layer.
- **Variant B (freshness grid): NOT taken, measured** — at 375 px the 4-column grid
  wraps its reason sentences ("MTA terms not verified") into 3-line narrow cells
  (screenshotted on the prototype), while the page's stacked source rows give a reason
  a full-width line. The stacked rows are already one line per source, so the grid is
  not more compact where it matters.

## What did NOT change (the MUSTs, honoured)

- The honesty string and every flood 15 string: `web/live.js` untouched entirely;
  `research/flood-11-detector.json` untouched. `strings.operating_truth` still renders
  in the fn layer's own row — visible in BOTH views (never inside the disclosure).
  notify 09 renders the same string; nothing moved.
- The record card: untouched (markup, CSS, tests) — restyle was not needed; it stays
  IN-COLUMN, wording still pinned by `tests/test_hist_card.py` (10/10 green).
- The manifest stays a first-tick load; no `open:` default changed; nothing new is
  fetched at boot except `files/summary/recent.json` (32,924 B raw, ~0.9% of first paint).
- Module discipline: no new `.js` file (no site-key change, no CONTRACT bump, no doc
  edit owed); every listener in `app.js`; only `basemap.js` calls addLayer/addSource;
  all files far under the 800-line cap (largest: insight.js 602).
- Freshness rows render in both views for every layer; gated rows stay dark WITH reasons;
  the reader-dated `addDataAge` composite untouched; `mta` still budget-less, renders AGE.

## PRICED DECISION FILED, NOT TAKEN (Ross's or the planner's)

`routes.geojson` is 8,162,311 B behind a toggle; the only lever worth more than 15% is
one Feature per `(route_id, direction_id, cell)` — **−32.6%, losing `shape_id`** — which
overturns DESTINATION-PLAN D1's decided segment unit. Filed here and on the wave-8-CLOSED
held entry; a renderer must not take it.

## Verified

- `tests/test_page.py` + `tests/test_hist_card.py`: **59 passed** (55 existing + 4 new:
  the one-closed-disclosure rule, the guarded localStorage rule, the recent.json
  verbatim-strings/never-today rule, the one-rider-sentence-per-layer rule).
- Real tab (Chrome 152 headless, swiftshader flags, CDP `Page.captureScreenshot` after
  real waits, against `raincheck.webserve`): rider default at 1280x800 and 375 px
  (full stack), disclosure open at both widths (analyst prose legible at 375), the
  hover-locate ring via a REAL `Input.dispatchMouseEvent` hover (91 Cells ringed for the
  2026-08-20 event) and via a bubbling focusin, localStorage persistence across a reload.
  Note: `el.focus()` alone does not fire focus events in an unfocused headless window —
  the wiring was proven with a real mouse move and a bubbling FocusEvent instead.

## FORWARD-CONTEXT for the WAVE 9 GATE's P4 row

**What the rider view SHOWS:** the map (basemap + taxi zones + the Cell fill lit), a
one-line answer (band value + plain gloss), the storm/window picker, the "Flooding on
record" list (recent.json: 8 newest events, dates and labelled-asset counts, caveats
verbatim, hover/focus rings the Cells), one plain sentence + freshness chips per layer,
the gated rows dark with their reasons, and the provenance strip.
**Where the analyst prose lives:** every estimand, interval, gate/preview/hidden/chord
note, the curve and the legend estimand are inside `<details id="analyst">` in
`#insight` — default closed, state in localStorage, ids unchanged so every existing
render call and test still binds.

## JUDGED AT THE WAVE 9 GATE, PART 2 (2026-08-27)

The gate fan-out's finding (b) — `#grey-note` lost its "(the property is absent, not
null)" clause in the rider shortening, and nothing pins that string — was left to PART 2
to judge. **Judged: the clause does NOT return.** It is analyst-grade precision, the
rider pass's whole charter was removing exactly that register from the default view, and
the absent-vs-null distinction still lives where an analyst looks (the estimand prose
behind the `#analyst` disclosure and the payload contract docs). Findings (c) aria-live
double-announce, (d) `mouseout`->`mouseleave`, and (e) the verbatim-source-line
localStorage test stay filed on STATUS's end-state FILED-FORWARD list, none blocking.
