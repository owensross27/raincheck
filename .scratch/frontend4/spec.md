# frontend4 spec — the interactive pass: streets, hover, and a rain-conditioned fleet

Status: ready-for-agent
Produced by /to-spec over `.scratch/frontend4/charter.md` (Ross, 2026-08-27), 2026-08-27.
The charter is the ask; this document is the decision record. Every load-bearing fact
below was re-verified against the tree at master `a4c246f` in the spec session (four
scouted reports: style/glyphs, hover machinery, live-fleet contract, ops tail) — where
this spec cites a line number, it was read, not inherited.

## Problem Statement

The map is lit but not conversational. (1) The basemap draws highways and major roads
only until deep zoom (minor-road widths interpolate from 0 at z11, name labels for minor
roads sit at minzoom 15 against a maxzoom-13 extract), and every basemap label —
neighbourhood and locality names included — is spliced BELOW the data layers
(`basemap.js:103` inserts all 66 style layers with `beforeId: "zones-fill"`), so the
flood/impact story floats over a city you cannot read. (2) Point layers answer only to
click (`hist` opens the record card) or not at all (`subway`, `mta`, `fn` have no
handlers); only the Cell fill has a tooltip. (3) The live fleet is a flat grey dot field:
`route_id`, `next_stop_id`, `pred_next_s` are published and unused, and the
expected-condition join the contract prepared (vehicle `cell` -> the Cell's published
wet/dry ratio band x current rain) is dark because bronze mode NULLs `cell`/`mm_1h`
(`live_export.py:135-136`) and the stream that would carry them is paused until the
08-31 cutover. (4) The pods still run the closed MTA gate baked into image pin
`3871c6aa699a` — opened in code at `fd3c438`, never re-baked.

## Solution

Four tickets, one wave (wave 12). 01: denser roads and street/place names via load-time
style edits in `basemap.js` — a two-splice (label symbol layers above the fills, below
the point layers) plus per-layer width/minzoom overrides and one more sha-pinned glyph
range. 02: one generalized hover-tip mechanism over the existing `#tip` element, wired
for the four point layers, name + count on hover with the click card untouched. 03:
bronze-mode `live_export` computes `cell` (shapely STRtree over `ref/cells`, the
`flood_panel.cell_index` seam) and joins `mm_1h`/`precip_valid_ts` from
`live/precip_cell` (mirroring `enrich.with_live_precip` semantics), and carries the
agency's `trip_delay_s` through the bronze TU reduce. 04: the fleet joins client-side —
vehicles in rain whose Cell has a published band take the frozen `RATIO_STOPS` ramp
(byte-untouched, absent -> neutral), and a fleet hover shows route, the agency's
next-stop prediction, and the band, never a point number. The image re-pin + rollout is
the wave-12 gate's STEP 3b (single-writer rule), not a ticket.

## User Stories

1. As a rider zooming to my block, I want side streets to appear by ~z11 and their names
   by z13, so that flood markers sit on streets I recognize.
2. As a viewer, I want neighbourhood/locality/street labels to paint above the Cell fill
   and zone lines (but below every point marker), so that the city stays legible with the
   fills lit.
3. As a viewer, I want hovering any flood-history marker to show its name and event
   count without opening the card, so that I can scan the map; clicking still opens the
   record card.
4. As a viewer, I want hover labels on the subway-impact, MTA-alert, and FloodNet dots
   (name + the published state/sentence), so that no dot is mute.
5. As a viewer on a phone, I want a tap to show the same label (the cells tooltip's
   click-for-touch pattern), so that hover-only content is not desktop-only.
6. As a rider, I want to hover a bus and see its route and the agency's own next-stop
   prediction, labeled as the agency's number, so that I know what the dot is.
7. As a rider in the rain, I want buses colored by their Cell's published wet/dry speed
   band on the same frozen ramp the delay fill uses, so that "probably slow right now"
   is one vocabulary, not a second one.
8. As the claim discipline's owner, I want the hover to say the BAND ("0.72-0.82x dry
   same-hour speed"), the caveats to be RENDERED from published strings, and a Cell with
   no published ratio (or a dry hour, or a missing join) to stay neutral, so that the
   coloring never claims more than the estimand.
9. As the operator, I want bronze-mode exports to carry `cell`/`mm_1h` so the coloring
   works before the stream revives — and to keep working (keys absent, export alive)
   when `ref/cells` or the precip table is missing.
10. As the gate, I want the next image bake to carry the open MTA gate and these page
    changes, converged on every container, so the pods stop logging `publish=gated`.

## Implementation Decisions

### F1 — basemap streets + labels (ticket 01; `web/basemap.js`, `Makefile`, tests)

- **The vendored style JSON stays byte-untouched.** All edits are load-time transforms in
  `prepare()`/`drawBasemap()` — the established pattern (drop background/pois, re-source,
  collapse fonts). No test parses the JSON; `make vendor`'s sha pin keeps it foreign.
- **Two-splice.** `prepare()` partitions layers into symbol and non-symbol. Non-symbol
  layers insert before `FIRST_DATA_LAYER = "zones-fill"` (`SPEC_ORDER[1]`, unchanged).
  Symbol layers insert before a new `LABELS_BEFORE = "locate"` (`SPEC_ORDER[7]`): above
  every fill and line (cells, impact, geography band, zone lines), below every point
  layer (locate, live, hist, fn, mta) — the charter's "raise labels above the fills"
  with the dots keeping top billing. Both constants derived-asserted in the test from
  `page.SPEC_ORDER`, per the mirrored-constant rule. The trap "the gap above
  `zones-fill` belongs to basemap.js's owner" is honored: basemap.js IS the owner and
  takes a second, bounded gap.
- **Density is an `OVERRIDES` map in basemap.js keyed by layer id**, patching `minzoom`
  and `paint["line-width"]` interpolation stops (the width curves ARE the zoom gate —
  most road layers have no minzoom). Intent, tuned by screenshot at the ticket: minor
  roads visible (hairline) from ~z10.5-11 and clearly by ~z12 (today: 0 at z11, 0.5 at
  z12.5); service roads from ~z12 (today z13); paths/other from ~z13 (today z14); link
  roads follow minor. Casings follow their fills. Highways/major/rail untouched.
- **Street names:** `roads_labels_minor` minzoom 15 -> 13 (the extract is maxzoom 13;
  z13 tiles carry minor-road `name`, and 15 was overzoom-only). `roads_labels_major`
  (minzoom 11) and text sizes/colors untouched — the calibrated greys recede correctly
  now that they sit above the fills.
- **Fonts:** `prepare()` must also rewrite the NESTED `text-font` overrides inside
  `text-field` `format` expressions (they name `Noto Sans Devanagari Regular v1` etc.
  and survive the current top-level-only collapse at `basemap.js:74-76`) — walk the
  layout object and replace every array-valued `text-font`. CORRECTED at ticket 01
  (measured via real console errors): inside a `format` expression tree the
  replacement must be `["literal", ["notosans"]]` — a bare `["notosans"]` there is
  parsed as an expression call and throws; the top level keeps the plain array.
- **One more glyph range:** vendor `Noto Sans Regular/256-511.pbf` (Latin Extended-A —
  Kościuszko is U+015B) as `web/vendor/notosans-256-511.pbf` through `make vendor`'s
  download-to-`.new`/sha-verify/mv shape, with its own `_SHA` pin recorded from the real
  download at the ticket. It is a new `site` family key (additive under
  `contract.PROMISE[1]`, NO `contract.CONTRACT` bump — the subset rule), one row in
  `docs/read-api-contract.md`, one member in `tests/test_page.py`'s vendored-set assert.
  The glyph URL template `vendor/{fontstack}-{range}.pbf` already resolves it; no JS
  edit. Further ranges stay a two-line Makefile addition; do not add ranges nothing
  requests.
- **Untouched:** the failure path (`dropBasemap`, catch never rethrows, `on.basemap =
  false`), the HEAD-dated freshness row, `cache: "no-cache"`, attribution (same tiles,
  same two licences), the `tiles` family and `PMTILES_BUILD` pin.

### F2 — hover labels on point layers (ticket 02; `web/insight.js`, `web/app.js`, tests)

- **One mechanism, the existing element.** A `TIPS` table in `insight.js` maps layer id
  -> a render function returning the tip content for a feature's properties; one
  exported `showPointTip(layerId)` handler factory reuses `#tip`, the `showTip`
  positioning (`e.point + 14`, right-edge clamp), and its escaping discipline
  (`innerHTML` only for literals + numbers; every untrusted string — names, labels —
  through `textContent`/`esc()`).
- **Wiring lives in `app.js` and nowhere else** (the ES-module-cycle rule): for each of
  `hist`, `subway`, `mta`, `fn` — `mousemove` + `click` show (click is the touch path,
  the cells tooltip's own pattern), `mouseleave` hides. The existing `hist` click ->
  `showCard` stays; it already hides `#tip` first (`app.js:98-101`), so on `hist` the
  click both opens the card and never leaves a stale tip. Handlers on hidden/gated
  layers never fire (layer-scoped `map.on`), so no gate guard is needed.
- **Content per layer** (exact property spellings verified against the published
  files): `hist`: title `name`, falling back to `asset_id` (`name` is an ABSENT key on
  all 1,276 cell-kind features — never render "null"/"undefined"), sub `kind ·
  asset_id` (names are not unique — the id always prints), line "`n_events` flood
  event(s)". `subway`: title `name`, sub `complex · complex_id`, lines from
  `dropped`/`planned`/`drop_share` (+ `rel` only when present — `"rel" in c` is
  conditional at `live.js:276`). `mta`: title `name`, sub `complex_id`, line `state` +
  `age_min`. `fn`: title `name`, line = the published `label` sentence verbatim
  (escaped) + `age_min`. Numbers format via the page's existing `fmt` helpers; no new
  claim strings are authored — a tip renders published values and neutral nouns only.
- **No cursor/feature-state work.** `promoteId` stays off everywhere (hex ids;
  MapLibre drops integer-unlike promoted ids silently); highlight styling is not the
  ask. The `locate` ring mechanism is untouched.

### F3a — bronze exporter enrichment (ticket 03; `src/raincheck/live_export.py`, tests)

- **Charter option (a), taken.** After `prepare()` builds `q` in bronze mode, an
  `enrich_bronze(con, root, now)` step replaces the three NULL columns:
  - `cell`: fetch `q`'s `(vehicle_id, lon, lat)`, compute the H3 r8 int cell via the
    existing shapely-STRtree seam (`flood_panel.cell_index()` / `cell_of()` —
    point-queried then `covers`-confirmed; the STRtree predicate-direction trap is
    already solved there), register a temp `vcell(vehicle_id, cell)` table, and rebuild
    `q` with the join. The published spelling stays `lower(to_hex(cell))` — the same
    15-char lower-hex `cells.geojson` keys on (`882a100895fffff` pinned by the
    existing fixture).
  - `mm_1h`/`precip_valid_ts`: join `<root>/live/precip_cell` mirroring
    `enrich.with_live_precip` semantics exactly — newest `valid_ts=` hive partition
    <= the wall clock (lexicographic max on the string key), newest `fetched_at` wins
    per `(cell, valid_ts)` (the several-rows-per-hour table), projection and
    predicates INSIDE the read statement (the memory-bounded-pod rule).
  - **Enrichment failure is garnish failure, not export failure**: a missing/unreadable
    `ref/cells` or `live/precip_cell` leaves the keys ABSENT (the columns NULL) and the
    tick healthy — mirroring `enrich.py:103-105`. The `once()` never-raises contract and
    rule 3 (a failed tick leaves live.geojson alone) are untouched.
- **Bronze carries `trip_delay_s` now**: the two-step TU reduce takes `max(trip_delay_s)`
  off the latest fetch's rows (trip-level, identical across a fetch's stop rows;
  pre-era parts read NULL via `union_by_name` -> absent key). It is the agency's own
  number and the page already words it that way (`live.js:92-96`). Check
  `eras.READERS`/`ERA_COLS` coverage for the bronze TU read and register if absent —
  a MUST-verify at the ticket, not assumed either way.
- The `live` source path is untouched. `RAIN_MM = 1.0` is unchanged and stays the one
  rain flag.

### F3b — fleet interactivity + rain-conditioned coloring (ticket 04; `web/live.js`, `web/layers.js`, `web/insight.js`, `web/app.js`, tests)

- **The join is a client-side dict lookup at tick time.** `insight.js` exposes a named
  getter over the cells FeatureCollection it already fetched (one fetch, one parse —
  never a second fetch; cross-module access is a named function in the owning module).
  `liveTick` builds `cell -> band` once per cells arrival and, per vehicle feature,
  attaches computed properties BEFORE `setData` when ALL of: the feature carries `cell`;
  `mm_1h >= RAIN_MM` (the mirrored constant — the page literal is derived in the test
  from `live_export.RAIN_MM`, never written twice); the Cell publishes a band. Attached:
  `ratio`, `lo`, `hi`, `win` — from `w2_*` (the 2023 window) when published, else
  `w1_*` (2021). Anything else -> no keys, neutral.
- **Paint: the frozen ramp, declared at boot, absent -> neutral.** The `live` style
  layer's `circle-color` becomes the `impact-fill` pattern (`layers.js:325-326`):
  `["case", ["!", ["has", "ratio"]], LIVE_FRESH, ["interpolate", ..., RATIO_STOPS...]]`.
  `RATIO_STOPS` stays BYTE-UNTOUCHED (Ross's recorded wave-11 gate decision) — reuse is
  the point: one ramp vocabulary, one meaning (wet/dry speed ratio), now on a second
  mark. The point-mark neutral is `LIVE_FRESH` (the existing "geometry, no number"
  fleet grey), NOT fill-`GREY` — an absent-value color is a property of the mark
  (frontend2 03's lesson). Staleness still wins: `renderLive`'s stale branch paints
  flat `LIVE_STALE` + 0.35 opacity over everything; the fresh branch restores the case
  expression instead of flat `LIVE_FRESH`. Radius/opacity untouched. The exclusive
  Cell-FILL radio is uncontested (points never claim the fill channel); if the
  one-ramp-on-screen test (`test_page.py:660`) pins fill-exclusivity it stands, and if
  it pins ramp-literal-count it is re-derived onto the rule (the ramp appears only via
  `RATIO_STOPS`, whose stops are frozen).
- **Fleet hover, via 02's mechanism** (`live` gets a `TIPS` entry; ticket 04 branches
  from 02): title `Route {route_id}` (fallback `vehicle_id`), sub `vehicle_id`, lines:
  next stop + `pred_next_s` labeled as the agency's own prediction; `trip_delay_s` when
  present, in the page's existing agency-number wording; and a conditions line ONLY
  when `ratio` was attached: the BAND — "wet-hour speed {lo}-{hi}x dry same-hour
  ({win} window)" — never the point ratio alone. Raining but no published band: "no
  published band for this Cell". Not raining (or no `cell`/`mm_1h`): no conditions
  line. Nothing on the tip says "late because of rain" — descriptive vocabulary only.
- **Caveats are RENDERED, not restated.** While any vehicle is ramp-colored, the live
  layer's legend renders `headline.json`'s published `estimand` and `preview_note`
  strings verbatim through the existing `note()`/`esc()` path (`cells.geojson` itself
  carries no strings; headline is where the estimand prose lives). The preview status
  (2021+2023 capture-window estimand, 7-year backfill pending, Interline hard
  2026-09-30) therefore rides published strings and needs no page-authored copy.

### Ops tail — the wave-12 gate carries it (no ticket)

- **An image pin is a single-writer resource**: tickets never run `cloud-image.sh` or
  commit pin sites. At the gate, after landing and THE ONE SUITE: `scripts/cloud-image.sh`
  over the landed tree (both targets), pins committed alone, pushed image verified by
  RUNNING it (the gate receipt: `publish.LIVE_TERMS_VERIFIED` non-None inside the
  image; the three research artifacts still present), then the wave-11 rollout recipe
  verbatim — filtered kustomize render (`--load-restrictor LoadRestrictionsNone`,
  topics Job filtered OUT) applied to `raincheck-live` + `precip-live`;
  `raincheck-stream` pin moved by `kubectl set image` on both containers with replicas
  HELD AT 0; `scripts/airflow-install.sh` for the three Airflow Deployments.
  Post-roll evidence: `raincheck-live`'s log stops saying `publish=gated`.
- **Publish**: `site` family (basemap.js + the new glyph key + any changed modules) and
  a fresh bronze `make live-export ONCE=1 SOURCE=bronze` + `live` family, then the edge
  purge if a purge-capable token exists (else name the <=86400 s heal window — mixed
  old-JS/new-HTML must degrade, so ticket JS changes keep every id the old modules
  touch). Credentialed steps may be classifier-blocked for an agent session; if so, the
  gate splits per the standing rule — land/suite/runbook always; the blocked half
  becomes one [YOU] paste.
- **Not this effort**: cloud 04 / the capture box (date-gated 08-31, paste J), the
  08-31 cutover sequence itself, `raincheck_daily` unpausing.

## Testing Decisions

- Page rules stay text assertions over `web/` via `tests/page.py` (no JS runner — spec
  L). Derive, never mirror: `LABELS_BEFORE`/`FIRST_DATA_LAYER` from `page.SPEC_ORDER`;
  the page's rain threshold from `live_export.RAIN_MM`; the vendored-set and site-key
  asserts from `publish.FAMILIES`. Prose-poisoning: no comment in web/ names a banned
  token or an angle-bracket tag; containment asserts are bounded (no split-to-EOF).
- `tests/test_live_export.py`: `test_bronze_carries_no_cell_precip_or_trip_delay` is
  REWRITTEN to the new contract (bronze carries `cell`/`mm_1h`/`precip_valid_ts`/
  `trip_delay_s`; the fixture gains `ref/cells` geometry + a `live/precip_cell`
  partition with a decoy older `fetched_at` row and a decoy newer-than-now partition);
  new pins: the hex spelling against the independent `CELL_HEX` oracle, newest-partition
  /newest-fetch selection BY NAME (the data cannot always discriminate oldest vs
  newest — the flood 15 lesson), absent `ref/cells` -> absent keys + healthy tick,
  absent precip table -> absent keys + healthy tick. Fixture values must be
  non-degenerate for every term under test (a fixture whose `mm_1h` is 0 pins nothing).
- Mutation-check every contract claimed, per the standing harness rules (commit first,
  snapshot from git, `PYTHONDONTWRITEBYTECODE=1`, pristine control printed, restore
  verified, one harness per worktree): the two-splice bound, the nested-font collapse,
  the bronze enrichment failure containment, the ratio-attach conditions (each leg:
  no-cell, dry, no-band), stale-overrides-color, the band-not-point tip rule.
- Screenshots are cheap evidence for F1/F4 (headless WebGL: swiftshader flags, CDP
  capture never `--screenshot`, cold profile per run, `setDeviceMetricsOverride`);
  commit before/after at z11 and z13 for the basemap ticket.
- Ticket sessions run own-module tests in worktrees only (`RAINCHECK_ARCHIVE_ROOT`
  exported for real-root tests; 16-19 env skips normal); THE ONE FULL SUITE runs once,
  at the gate, on the landed tree. Baseline to reconcile against: `1746 / 45 / 0`
  (master `7b3ec8c`) plus the four tickets' recorded deltas.

## Out of Scope

- The "rain now" animated layer (per-cell mm/h sweep) — separately chartered if wanted.
- Depth-graded flood rendering; layer-panel regrouping.
- Cursor changes, feature-state highlight, `promoteId` (stays off).
- The `live`-path exporter, `RAIN_MM`'s value, the ramp's stops, `DELAY_CUT_S`.
- cloud 04 / capture / cutover / `raincheck_daily` (08-31, paste J owns it).
- New glyph ranges beyond 256-511; sprite/POI icons (pois stays dropped).
- Per-stop or per-route lateness surfaces (nothing stop-grain is published; the fleet
  tip uses only what `live.geojson` carries).

## Further Notes

- The current pin `3871c6aa699a` predates `fd3c438`: the pods' `publish=gated` is
  expected until the gate's re-pin, and if a layer LOOKS gated on the host it is edge
  cache — never re-add a gate (charter, verified).
- `impact.json`'s live ratio path (`flood_overlay`, `window=live`) publishes no `ratio`
  today (`no_baseline` — the `window=live` baseline partition does not exist). The
  fleet coloring deliberately keys on the PUBLISHED capture-window bands in
  `cells.geojson`, not on the live overlay, exactly as the charter directs.
- Conflict surface, planned: 01 (basemap.js/Makefile), 02 (insight.js/app.js), 03
  (src/tests only) are pairwise disjoint; 04 touches 02's files and BRANCHES FROM 02's
  branch (gate lands 02 then 04 in order). All web tickets append to
  `tests/test_page.py`; the gate takes the union and recounts deltas on the branch.
