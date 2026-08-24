# 02 — Prototype: how do four layers read together on one map?

Type: prototype
Status: resolved
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

## Answer

Resolved 2026-08-24. Three variations were built against real payloads and presented; **Ross
picked A — "Stack (one fill)"**. Asset: `.scratch/frontend/prototypes/variant-A-chosen.png`
(the chosen variation, lit, with a real record open), and the full runnable set — A, B and C,
the losers included, as the primary source — on branch `frontend02-four-layers` at
`.scratch/frontend/prototypes/` (README.md has the run command and the provenance of every
byte on screen). **The prototype is not the implementation.**

### D1 — The Cell FILL channel is EXCLUSIVE. That is the whole answer to the colour collision.

The ticket asked how to resolve "delay ramp vs flood tier ramp on the same geography". The
answer is that the collision was never a colour problem: the delay layer and flood 17's bus
impact overlay are **the same quantity — a Speed ratio — over the same ~1,200 H3 Cells at
different time-scales.** So they share ONE frozen ramp and ONE channel, and the page offers
them as a **radio group, "Cell fill — pick one"**, never both at once. Two ramps on one
geography is then structurally impossible rather than merely discouraged.

**Consequence for flood 17, already written onto its ticket (`e61a98d`): it does NOT get its
own ramp and does NOT get a simultaneous fill.** The flood TIERS never contest this channel
at all — they are point layers (D3), so the ramp question never arises for them.

### D2 — Colours: the frozen ramps are untouched; four new hues, none on the ramp's arms.

`RATIO_STOPS` (diverging, dark red -> white -> blue), `SPEED_STOPS` and `GREY` (`#3a4049`,
"no publishable value") stay exactly as `web/app.js` has them. The new hues, chosen to avoid
both arms of the diverging ramp:

| meaning | hue | why |
|---|---|---|
| FloodNet sensor reporting water NOW | `#35d6c2` aqua | far from both ramp arms; reads as "live water" |
| station with water on the tracks (MTA) | `#ffc447` amber | the page's existing `.warn` family (`#ffcf87`) |
| stop or Cell with a flood record | `#8f7bd6` violet | recedes; it is history, not an alarm |
| a GATED layer's chip | `#d2a24c` | dark, not absent |

**MUST for the build — the grey collision the prototype exposed.** A dry/stale FloodNet
sensor and a dimmed live vehicle currently both render at `#3a4049`, which is ALSO the
"absent property" Cell fill, and at 2.6 px they are indistinguishable (visible in variant B's
full-density shot). Three meanings on one grey is one too many: give the dry/stale sensor a
hollow ring (stroke only, no fill) so "sensor present, no water" reads as a different MARK
rather than a different grey.

### D3 — Layer order, declared at boot, ambient at the bottom and urgent on top.

`bg` · `zones-fill` · **`cells`** (delay fill) · **`impact-fill`** · `cells-line` ·
`impact-line` · `zones-line` · `locate` · **`live`** · **`hist`** · **`fn`** · **`mta`**.
Vehicles are ambient and sit under the flood facts; the MTA alert marker is the single most
urgent thing on the map and sits on top. Every one of them is declared at boot with an empty
`FeatureCollection` + `visibility:"none"`, and `promoteId` is off everywhere (ticket 01).

### D4 — An "affected" station marker is a dot on the COMPLEX, not on the chip or the alert.

A `flood_truth` chip is per-INCIDENT and spans one or more complexes, so the chip is what the
CARD shows and the **complex** is what the map marks: amber, radius 7, dark stroke.
This requires coordinates the chip does not carry — written onto flood 15 as a MUST
(`e61a98d`).

### D5 — The record opens in a card that SHARES the right column, and never floats over it.

Click (not hover — touch parity). The card carries: title with an `asset_id` fallback for
unnamed assets, then `kind` + `asset_id`, `n_events`, `label_version`, the last 8 events
newest-first with `event_class` / `flood_cause` / `event_source_counts` / `label_support`,
and the "counts are city-wide at EVENT grain" caveat. **It does not float.** The prototype
first pinned it over the layer panel and it covered the freshness rows it had been opened
from; the fix is the mechanism `web/app.css` already uses for `#left` — a flex COLUMN where
the layer panel and the card shrink against each other. A floating card is the wrong shape
on a page whose panels are the other half of the answer.

### D6 — Freshness renders a row PER SOURCE, and the vocabulary needs a FIFTH state.

Ticket 01's `FRESH / STALE(+reason) / OFF / GATED` plus **`AGE`** — age known, no budget
frozen. Counted off the running page: the map has **9 sources**, the repo's two frozen
constants (`STALE_AFTER_S.live = 120`, `flood_truth.py:54`'s `MAX_AGE_MIN = 10`) cover **3**
of them, and the other **6** can only honestly show an age. Guessing a threshold, or painting
an unbudgeted layer FRESH, are both worse. Rows collapse when a layer is OFF; the reason
string sits under the chip. flood 15 owes the budgets as constants (`e61a98d`).

### D7 — Mobile: the panel set does NOT have to collapse. The MAP is what does not scale.

`web/app.css:69`'s 900px rule survives seven toggles and their freshness rows — measured at
375px, A is roughly 4,500 px of scroll, B ~4,000 (the grid is the most compact panel), C
~6,000. Nothing overlaps and nothing is unreachable. **What does not survive is the 60vh map
strip:** at 375px it carries about two layers legibly, so at <= 900px the build opens with
the Cell fill on and every POINT layer off, and the user adds them one at a time.

### D8 — Two build MUSTs the prototype only found by being clicked.

1. **Rebuilding the panel's `innerHTML` on every toggle destroys every checkbox**, so a
   keyboard user loses focus on each one. `web/app.js:194-201` already solves exactly this
   for the hour buttons by restoring focus after the rebuild — do the same, or patch rows in
   place instead of re-rendering the list.
2. **Nothing may be positioned against a guessed `#provenance` height.** The strip is
   mode-invariant (a section 9 condition), its height changes with the attribution text and
   with every width, and a hard-coded clearance put the seventh toggle UNDERNEATH it where a
   real click never reached it (caught by a hit-test, not by eye — it looked fine).
   `web/app.css:24`'s `bottom: 84px` on `#left` is that same guess. Measure the strip and
   drive the columns off the measurement.

### What was NOT chosen, and what is worth stealing from it

B and C stay on the branch as the primary source. From **C**, worth carrying into A later if
the map gets crowded: the ranked ledger and hover-to-locate are a better answer than a marker
for "7,955 assets have a record", and C is the only variant where a record never covers the
map. From **B**: its 4-column freshness grid is the most compact panel of the three and is
the right shape if A's stacked rows get too long at seven layers.
