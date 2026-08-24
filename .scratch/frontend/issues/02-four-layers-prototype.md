# 02 — Prototype: how do four layers read together on one map?

Type: prototype
Status: claimed
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

## Variations built (2026-08-24) — AWAITING ROSS'S SELECTION, not resolved

Three variations are on disk and runnable:
`.scratch/frontend/prototypes/` (README.md there has the run command and the full
provenance table). Serve from the repo root — `make web` passes `--directory web` and cannot
see the folder:

```
python3 -m http.server 8080
# .../.scratch/frontend/prototypes/proto.html?variant=A   (B, C; ?gate=open lights the three
# .../.scratch/frontend/prototypes/phone.html              MTA-gated layers; phone.html = 375px)
```

All three run on the SAME seven layers and the same surface ticket 01 fixed: one page, plain
per-layer toggles, no modes. They disagree about **which visual channel each quantity gets**,
**what an "affected" station marker is**, and **where a stop's flood record opens**.

| | A — Stack | B — Channels | C — Ledger |
|---|---|---|---|
| Cell fill | ONE at a time (radio): delay cells XOR impact overlay, sharing the frozen ratio ramp | delay cells fill **and** impact overlay as Cell OUTLINE width — both at once | ONE quantity, same as A |
| Point layers | all paint, stacked live &rarr; history &rarr; FloodNet &rarr; MTA | same, plus size/shape coding per layer | **do not paint at all** — they feed the ledger; only a locate ring touches the map |
| Affected station | amber dot on the complex | amber dot, largest in the point stack | a ledger ROW; the map draws a ring on hover |
| Flood record opens | pinned card, bottom-right, clear of the left column | same card | in place, inside the ledger row — no popover ever |
| Freshness | one stacked row per layer, sources indented, collapsing when OFF | one dense 4-column grid, always full | inline under each ledger section |
| Panel | right, 320px | right, 340px | LEFT column, the primary surface |

### What building them measured (all of this is new since ticket 01)

1. **Ticket 01's D2 age mechanism WORKS, and it is the first thing verified.**
   `Date` &minus; `Last-Modified` off the response the page already made renders a real
   per-source age for all nine sources. No payload stamp, no `test_re_export_is_byte_identical`
   breakage.
2. **FRESH/STALE/OFF/GATED is one state short.** The map has NINE sources and only TWO
   frozen staleness constants exist in the whole repo — `app.js`'s `STALE_AFTER_S.live = 120`
   and `flood_truth.py:54`'s `MAX_AGE_MIN = 10`. Between them they cover **3 of the 9**
   (`live.geojson`, `meta.json`, the FloodNet tier); the other **6** — zones, cells,
   headline, `archive/subway_alerts`, `gold/cell_hour_speed` and the notify 05 manifest —
   have an age but no budget, so the honest render is an age with **no verdict**. Counted
   off the running page, not by hand. The prototype adds a fifth chip, **AGE**, rather than
   guess a threshold or paint an unbudgeted layer FRESH.
   Either flood 15/17 and notify 05 freeze budgets, or the vocabulary grows this state.
3. **A `cell`-kind asset has `name = NULL` in `ref/assets`** — only stops and complexes are
   named — and the most-flooded assets are exactly the Cells. The first build labelled the
   ledger off `name` and the top three rows read **"null"**. Any marker label, popover title
   or ledger row needs a fallback (the prototype renders `Cell 882a106…`).
4. **`flood_truth.chips()` carries NO coordinates.** A chip is
   `{event_id, stations[{complex_id, name, state}], alert_ids, first_seen, last_seen, state,
   age_min}` — nothing spatial — so a chip cannot be put on a map without a second lookup
   against `ref/assets`. Same defect as notify 05's manifest, and it lands on flood 15.
   Cost of closing it there: 445 complexes, **30,087 B raw**.
5. **The history manifest's real price, re-measured on all 7,955 assets.** Ticket 01 priced
   coordinates at +65,549 B gz; measured here it is **+59,951 B gz** (39,203 &rarr; 99,154).
   But the prototype also proved the manifest needs the **name** — finding 3 — and that is a
   further **+48,638 B gz / +225,401 B raw** (99,154 &rarr; 147,792 gz; 1,576,447 raw).
   **notify 05 must decide id+kind+count+lon+lat+name, not the three keys the spec names.**
6. **Notify 02's recorded per-asset max is understated by ~3x.** Its close-out records
   "median 746 B, max 7,625 B" from a 60-asset RANDOM sample. Cutting the TOP 40 by event
   count — the tail that sample missed — gives median 10,057 B and **max 23,444 B**
   (`cell:882a1062d5fffff`, 73 events, `mode="public"`). The 746 B median is fine for sizing
   the whole 10.9 MB tree; it is the wrong number for sizing a single click.
7. **7,955 markers at once is unreadable, and that is variant B's verdict, not an opinion.**
   At full density the violet history dots plus 384 FloodNet dots plus 847 vehicles bury the
   Cell fill entirely (see B at 1440px and at 375px). The FloodNet "dry/stale" grey and the
   vehicle grey are also indistinguishable at 2.6 px.
8. **Two bus stops metres apart share a name** (`bus:200163` and `bus:200173`, both
   "FATHER CAPODANNO BLVD/DOTY AV", both 26 events), so a marker click is genuinely
   ambiguous — the card must print the `asset_id`, not only the name. Same shape as the
   trap about complex NAMES not being unique.
9. **At 375px the surface does not break, but it grows.** `web/app.css:69`'s stacking
   survives seven toggles: C is ~6,000 px tall, B ~4,000 px (the grid is the most compact
   panel), A in between. The map is a 60vh strip in all three, and in that strip B's
   seven-layer paint is illegible. The panel set does NOT have to collapse — but the map
   half of a small screen can only carry about two layers.
10. **The impact overlay's real grain is sparse at the head.** The newest closed hour in
    `gold/cell_hour_speed` carries **24 Cells**; the densest carries 1,169. The prototype
    paints the densest so the collision is visible, and the sparse head is itself a design
    input for flood 17.

### Not decided here — the selection is Ross's

Per this ticket's HITL line and the wayfinder's known failure mode, no variant was picked.
