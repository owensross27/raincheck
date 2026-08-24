# 02 — Prototype: how do four layers read together on one map?

Type: prototype
Status: open
Blocked by: 01

## The question

Talking cannot settle how vehicles + delay-cells + flood tiers/stations +
history popovers LOOK together — layer order, color collisions (delay ramp vs
flood tier ramp on the same geography), what a station "affected" marker is,
how a popover shows a stop's flood record without burying the live view. Build
2-3 throwaway variations against REAL payloads that already exist in
`web/files/` (fleet GeoJSON, cells/headline/zones) plus FIXTURE tiers/history
shaped like flood 15's and notify 02's real payload schemas (both are frozen —
copy shapes verbatim, never invent fields; stub-fidelity is a standing rule).

HITL: **the selection between variations is Ross's, not the agent's** — the
wayfinder doc records agents closing prototype tickets by picking their own
variant as a known failure. Present, then stop.

## Inherited from ticket 01 (resolved 2026-08-24) — load-bearing, do not re-decide

The SURFACE is settled: **ONE page, extending `web/index.html`, with plain
per-layer toggles** (the `#livetoggle` pattern — fetches nothing until ticked,
owns its own freshness line). **No modes** — they were considered and cut.
Prototype on that surface; do not prototype a second page.

- **Seven layers, not four** (01's table): ground zones · delay cells · live
  fleet · flood tier FloodNet · flood tier MTA alerts · flood 17 impact overlays
  · flood history markers. Plus history DETAIL as a click-time per-asset fetch,
  which is an interaction, not a layer.
- **Three of the seven are MTA-GATED** (live fleet, MTA alert tier, both impact
  overlays) and dark today. A variation has to read honestly with them dark —
  that is a design requirement, not an edge case.
- **MOBILE IS NOW YOURS.** Ticket 01 graduated "small-screen treatment" into this
  ticket instead of a new number. `web/app.css:69` already stacks the panels
  under a 60vh map at 900px. Show each variation at 375px and answer: does
  stacking survive seven toggles and their freshness rows, or must the panel set
  collapse?
- **Freshness vocabulary to render: FRESH / STALE (+reason) / OFF / GATED.**
  Age comes from HTTP response headers (`Date` − `Last-Modified`), NOT a payload
  stamp. A multi-source layer shows a row PER SOURCE. flood 15's tier states
  (INSUFFICIENT_DATA, HOLES, winter gate, version-skew) are a SEPARATE
  vocabulary — freshness is not verdict; render both, do not merge them.
- **`#provenance` is always mounted** — the MTA attribution and the "current
  snapshot only / no bulk or protobuf" sentence are a §9 condition of publishing.
  No variation may hide them.
- **MapLibre MUSTs from 01's review**: declare every layer at boot with an empty
  `FeatureCollection` + `visibility: "none"` (the `live` pattern at `app.js:45`,
  `:56`) — never a lazy `addSource`/`addLayer`, or stacking depends on click
  order and a `beforeId` for a not-yet-added layer throws. **`promoteId` stays
  OFF the history layer**: asset ids are hex strings (`cell:882a100001fffff`) and
  MapLibre 5.9.0 silently drops a source whose promoted id is not integer-like.
- **Measured payloads** (gz / raw): cells.geojson 395,437 / 2,300,263 ·
  zones 65,549 / 257,488 · headline 4,299 / 48,321 · fleet fixture 33,219 /
  260,078 · history markers over all 7,955 flooded assets 101,600 / 1,179,405.
  **Nothing in the repo compresses today** (`publish._put` sends no
  `ContentEncoding`), so reason in RAW bytes. cells is NOT in first paint.
- notify 05's manifest as specified carries **no coordinates**, so the history
  marker layer needs lon/lat added there (+65,549 B gz). Fixture it with
  coordinates and note the dependency.

## Resolution shape

The chosen variation linked from this ticket as an asset (throwaway code stays
throwaway), the layer/color/interaction decisions recorded under ## Answer, one
line on the map. The prototype is NOT the implementation.
