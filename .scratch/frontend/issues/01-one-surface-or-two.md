# 01 — One surface or two: does the integrated map extend `web/` or stand beside it?

Type: grilling
Status: resolved
Blocked by: none

## The question

The live page (`web/index.html` + `app.js`) already renders the 30 s vehicle
fleet and the flood panel, with STALE semantics and the honesty string wired in.
The insight exports (cells/headline/zones) are separate payloads on their own
per-build cadence. Flood tiers/overlays (flood 15/17) and per-stop history
(notify 05) are coming as more layers. Does "one place to see everything" mean
ONE page that grows layer toggles — one clock panel, one honesty string, one
STALE model — or a second, denser page beside the live one?

Tensions to grill through (HITL — Ross speaks for the product):
- One page = one staleness/honesty model, but several cadences under one clock —
  the panel must say which layer is how old without lying (the frozen-age trap).
  **SUPERSEDED BY MEASUREMENT (see ## Answer): "four cadences ... per-run tiers"
  was wrong twice over. There are THREE write cadences (30 s live loop, per
  build, per spine rebuild) and FIVE data cadences, because write cadence is not
  data cadence. The "per-run" row in spec §9's table is GX Data Docs, which is
  orch 13's showcase tree, not a map layer.**
- The live layer is GATED (MTA terms) while every other layer is not; a single
  page must read honestly with its centerpiece dark.
  **SUPERSEDED BY MEASUREMENT: "every other layer is not [gated]" is FALSE. The
  flood panel is MTA-derived too — `flood_truth.py:285` emits an `mta_alerts`
  tier beside the publishable `floodnet` tier at :218. The gate line runs THROUGH
  the flood panel, not around it. See ## Answer, D3.**
- Payload weight: history popovers are per-asset fetches (median 746 B — cheap);
  cells.geojson and the fleet are the heavy layers.
- Whatever is chosen must not touch spec §9's constraints (current-snapshot-only
  live, no bulk endpoint, attribution on the page).

## Resolution shape

A decision recorded here (## Answer + Status: resolved + one line on the map's
Decisions so far), naming the surface, the layer list, and the staleness model
per layer. No code.

## Answer

Resolved 2026-08-24 by grilling. Measured first (the real `web/files/` payloads
raw and gzipped, `ref/assets` and `gold/flood_labels` on the real root, a built
proxy for the history marker layer), then two opus adversarial reviewers — an
honesty/domain lens and a mechanics/cost lens — attacked a written draft before
the human round. **They reversed four parts of it, including its central fix**
(see "What the reviews reversed" below). One round of four numbered decisions
went to Ross; he took all four recommendations ("all rec").

### D1 — ONE page. `web/index.html` grows. No second page, and no modes.

The integrated map EXTENDS the existing live page with plain per-layer toggles.
The mechanism already exists and is the right one: `#livetoggle`
(`web/index.html:64`, `web/app.js:427-439`) fetches nothing until ticked, owns
its own freshness line, flips layer visibility, and says so on the page. Every
new layer is that pattern again. **No mode switch** — modes are a second
mechanism for the job toggles already do, and they add a state variable gating
both DOM mounting and layer eligibility with no good answer for "what happens to
a layer I enabled in mode A when I switch to B".

The cost argument for one page does NOT hold and is not the reason. Measured, a
second page is **1 line** in `publish.py`'s `site` family tuple, 2-3 lines in
`tests/test_publish.py` (the attribution assertion must loop over both pages),
**zero** in the Makefile (`Makefile:194-195` serves the whole `web/` tree) and
zero in the export path. The real case FOR two pages is isolation: this stack has
no bundler (MapLibre is a UMD `<script>` tag, frozen by pipeline 14), `web/app.js`
is already **440 lines** against the 400-line house target and clears 800 with
five layers, and it is one global scope where a flood-panel throw kills the
insight view — `app.js:417-423` documents exactly that silent-kill class.

**What settles it is that the gate line does not run between pages.** The flood
panel is itself part MTA-derived (D3), so no page boundary can be drawn on the
MTA gate. Per-layer gate handling is required on whatever surface is chosen, and
once it exists a second page buys nothing but a second copy of the §9 attribution
assertion. Against that, "read together" — one stop that is both slow AND
flooding — is the destination, and two documents structurally prevent it.

Answer the 800-line problem by splitting the **file**, never the page: a second
`<script>` tag costs the same one line in the `site` family that a second page
would. Precedent, correctly cited: `.scratch/pipeline/map.md:62` — "one static
page ... with the insight and engineering views as two panels". (Do NOT cite
pipeline 14's "route pages" under Not built as a rejection of multi-page: in a
bus repo that reads as per-bus-route detail pages, and a scope list is not a
reasoned rejection. That decision also covered two panels on one cadence and
does not automatically scale to this.)

**MUST, mode-invariance:** whatever the panel set does, the `#provenance` strip —
the MTA attribution block and the "Current snapshot only ... no bulk or protobuf
download" sentence — is ALWAYS mounted. §9 makes attribution a condition of
publishing, and `tests/test_publish.py:232-240` asserts it by splitting the
STATIC `index.html` and grepping strings, so a runtime unmount ships a §9 breach
with the suite green. If the panel set ever becomes conditional, that assertion
moves to a rendered check.

### D2 — Age is computed from HTTP response headers, on the ORIGIN's clock.

**Rejected: adding `as_of_utc` to every payload.** It breaks
`tests/test_export.py:284` `test_re_export_is_byte_identical`, which asserts raw
`read_bytes()` equality — a stated invariant, and the export files are diffable
evidence artifacts. notify 05 carries the same byte-identity requirement
(`05-static-query-surface.md:15`), so the same stamp would break it too.

**The model:** `age = <origin Date header> − <Last-Modified header>`, both taken
from the response the page already made. The bucket IS the `web/` tree
(`publish.py:11`), so the page and its payloads are same-origin and both headers
are readable without a CORS exposure list. Both come from the origin, so a
browser clock cannot fake freshness — which today it can: `metaAge`
(`app.js:347-350`) uses `Math.max(0, Date.now() - t)`, and a browser running an
hour BEHIND clamps to 0. A CDN serving a cached copy returns the ORIGINAL
`Last-Modified`, which errs stale — the safe direction. Zero writer changes, zero
byte-identity break.

Three rules on top:

1. **Keep the live pair's composite** `vp_age_s + metaAge` (`app.js:355-359`). It
   telescopes to `now − vp_max`, i.e. it measures DATA age, which file age cannot.
   Where a layer has an inner data age, it is added the same way; where it has
   none, file age is the whole age.
2. **A layer with several sources shows a row PER SOURCE, not per layer.** flood
   15 already froze the budgets and they are not derivable from a write cadence:
   precip fresh <= 90 min / stale to 180 / down past 180 with holes counted
   separately, FloodNet 10 min, CO-OPS 30 min, NWS 15 min. The layer takes the
   worst of its sources; the panel shows the sources. A writer's stamp is the age
   of its newest INPUT, never the time it ran — otherwise a nightly rebuild over
   week-old Gold paints FRESH.
3. **Thresholds stay a per-layer TABLE**, the shape `STALE_AFTER_S`
   (`app.js:328`) already is. A formula ("2x cadence") was rejected: it would
   silently retune the deliberately chosen bronze value from 900 s to 1200.

**Freshness vocabulary: FRESH / STALE (+reason) / OFF / GATED.** The two reviewers
split here — the honesty lens wanted `INSUFFICIENT_DATA`, `HOLES` and
`INCONCLUSIVE` added; the mechanics lens wanted three states total. Resolved by
separating two vocabularies: **freshness is not verdict.** The freshness panel
answers "how old, and is it being fetched"; flood 15's tier states
(INSUFFICIENT_DATA, HOLES, the winter gate, version-skew refusal) are the flood
layer's own rendered vocabulary and stay flood 15's, unchanged. `ERROR` is not a
state — `app.js:355-359` already folds it into STALE — it is a reason string.
"Not built yet" is not a state either: ship the toggle with the layer.

**Hard rule, unchanged from the draft: absent must never render as zero.** A 404
and an empty FeatureCollection must not both paint an empty map under a fresh
clock.

### D3 — The MTA gate cuts by LINEAGE, and it runs through the flood panel.

This is the reversal. The draft called the flood panel "the one layer with zero
MTA dependency" and proposed a single ungated `flood` family. That would have
published MTA alert rows straight past the gate built to withhold them.

Measured: `src/raincheck/flood_truth.py:218` emits a `floodnet` tier (with its own
citation and caveats — publishable); `:285` emits an `mta_alerts` tier built by
`alert_rows()` (`:234-247`) reading `<root>/archive/subway_alerts`, whose chips
carry `alert_ids`, `complex_id`, station name and first/last seen. KNOWN TRAPS is
explicit that the MTA-derived thing to withhold is the alert ROW — its
`<alert_ids>:<complex_id>` source id, its timestamp, its existence — which is why
notify 02's `public` mode emits no observation row at all.

**The split, by lineage:**

| what | lineage | where |
|---|---|---|
| FloodNet tier | FloodNet sensors, own citation | **ungated** family |
| Cells/Units exposure files | 311 / FloodNet / USGS / AORC | **ungated** family |
| MTA alert tier | `archive/subway_alerts` | **gated**, with `live.geojson` |
| flood 17 bus overlay | `gold/cell_hour_speed` <- VP | **gated** |
| flood 17 subway overlay | TU capture | **gated** |
| subwaydata.nyc numbers | no published licence at all | **off the host entirely** (`flood_impact.py:36-38`, local-page-only) |

**MUST for flood 15 — splitting the FAMILY does not split the FILE.** `publish`
moves whole objects. flood 15 is currently frozen at "one process, ONE meta file
whose flood keys the single writer merges" (`.scratch/flood/spec.md:395-397`,
`.scratch/flood-build/spec.md:405-407`, `15-flood-panel-and-exports.md`), and that
one meta file is `web/files/meta.json` (`live_export.py:246`), which is inside the
GATED `live` family (`publish.py:124-128`). As frozen, **the MTA terms gate would
withhold the FloodNet tier — a layer with no MTA content — because it shares a
meta file with bus data.** flood 15 must write **TWO meta files**, one per gate
side. Recorded now because flood 15 is `ready-for-agent`: if it lands the merged
meta, the split becomes a rewrite. (Separately and additionally: flood 15's three
export files and flood 17's two are in NO family at all — `plan()` refuses any
name outside the five-entry `FAMILIES` table. That is an unwired writer, a second
defect, not this one.)

**No `status.json`.** The draft proposed one and it was rejected as re-committing
the frozen-age trap at manifest grain, plus a new family, a new cadence and a
Class B op per page load. The gate is a deploy-time CONSTANT
(`publish.py`'s `LIVE_TERMS_VERIFIED`) that changes at most once: one sentence in
`index.html`, carried by the `site` family that already publishes at deploy time
and is already text-asserted, says it at exactly the cadence the fact changes.
And today's false string — `liveTick`'s catch (`app.js:411-413`) collapses every
failure to `meta = null`, rendering *"STALE: the pipeline is not writing. No
files/meta.json - run make live-export"*, which on the public host is false in
both halves — is a two-line fix: branch on `res.status === 404` and say "not
published" instead.

### D4 — The payload rule, and why there is no byte budget.

**Nothing in this repo compresses.** `publish._put()` forwards exactly
`ContentType` and `CacheControl` to `put_object`; there is no `ContentEncoding`
anywhere. As published today, first paint is **3,661,475 raw bytes** — MapLibre
alone is 954,516. Every gzip figure below is therefore CONDITIONAL on a
custom-domain edge behaviour nobody has verified, and the serving host is still
frontend 03's open question. A gz byte budget was drafted, then dropped: MapLibre
js+css alone is 260,636 B gz, 74.5% of the 350 KB proposed, and there is no JS
test runner that could enforce it (`tests/test_publish.py:9-11`).

**MUST for whoever creates `raincheck-public`:** run one
`curl -sI -H 'Accept-Encoding: gzip' <url>` against a published object and record
whether `Content-Encoding: gzip` comes back. Until that is recorded, size
reasoning uses RAW bytes.

**The rule that replaces the number: paint from ONE bulk layer file; detail from
ONE per-asset fetch on click.** Enforced in the style
`tests/test_publish.py:232-240` already uses — a text assertion that
`cells.geojson` is not in the boot path — not a byte count. This is also what
keeps §9 honest: live stays current-snapshot-only, one file, no history, no bulk.

Measured (gzip / raw, level 6):

| payload | gz | raw |
|---|---:|---:|
| maplibre-gl.js | 250,585 | 954,516 |
| maplibre-gl.css | 10,051 | 69,430 |
| app.js | 9,027 | 23,314 |
| headline.json | 4,299 | 48,321 |
| zones.geojson | 65,549 | 257,488 |
| **cells.geojson** | **395,437** | **2,300,263** |
| live fleet (pipeline-14 prototype fixture) | 33,219 | 260,078 |
| notify 05 manifest AS SPECIFIED (id, kind, count) | 36,051 | 350,501 |
| same manifest **+ lon/lat**, i.e. paintable | 101,600 | 1,179,405 |

**Three MUSTs ride along:**

1. **`cells.geojson` is fetched TWICE at boot** — as a MapLibre style source
   (`app.js:41`) and again in the boot `Promise.all` (`app.js:297`). The HTTP
   cache collapses them to one GET, so the cost is a second 2.3 MB JSON parse, not
   a second download. Making it lazy is a TWO-SITE change, and the `app.js:297`
   fetch exists only to derive `cellKeys` (`:300`, used once at `:242`) and a
   feature count (`:306`). `headline.json`'s `cell_property_keys` cannot
   substitute — `export.sql:374-377` writes it as human-readable prose. Freeing
   that fetch needs a small `export.sql` addition; cost it.
2. **notify 05's manifest carries no coordinates, so as specified it CANNOT paint
   a layer.** Measured price to make it paintable: **+65,549 B gz** (36,051 ->
   101,600) over all 7,955 assets with a flood record. Decide it in notify 05, not
   downstream. And the deciding number there is the PUBLISH side, not the wire:
   7,955 objects PUT serially is minutes per spine rebuild (the `ponytail:` note
   in `publish.py` names parallelising tree families as the fix, not reshaping the
   query).
3. **Every layer declares at boot** with an empty `FeatureCollection` and
   `visibility: "none"` — already the `live` pattern (`app.js:45`, `:56`) — never
   a lazy `addSource`/`addLayer`. A lazily added layer lands on top of the order,
   so with everything lazy the stacking depends on CLICK ORDER, and a `beforeId`
   naming a not-yet-added layer THROWS (the vendored 5.9.0 bundle carries the
   literal `Cannot add layer "${a}" before non-existing layer "${i}".`).
   Declare-at-boot also keeps `paint()`/`setView()`'s unconditional
   `setPaintProperty("cells", ...)` from throwing when cells goes lazy.
   **`promoteId` stays OFF the history layer**: asset ids are hex strings
   (`cell:882a100001fffff`, VARCHAR — verified on the real root), and MapLibre
   5.9.0 SILENTLY drops a GeoJSON source whose promoted id is not integer-like —
   zero features, no error event (`app.js:38-44` records the measurement).

### The surface, the layers, and the staleness model per layer

ONE page, `web/index.html` + `web/app.js`, published by the `site` family at the
bucket root; the bucket is the `web/` tree, so relative paths are unchanged.

| # | layer | payload | write cadence | data cadence | age from | gate |
|---|---|---|---|---|---|---|
| 1 | Ground (taxi zones) | `files/zones.geojson` | per build | per build | headers | — |
| 2 | Delay cells (choropleth) | `files/cells.geojson` | per build | newest Gold input | headers | — |
| 3 | Live fleet | `files/live.geojson` + `meta.json` | 30 s | 30 s | `vp_age_s` + headers | **MTA** |
| 4 | Flood tier — FloodNet | flood 15 ungated exports | 30 s loop | per source (10/30/15 min, precip hourly) | headers, per source | — |
| 5 | Flood tier — MTA alerts | flood 15 gated exports | 30 s loop | alert feed | headers | **MTA** |
| 6 | Impact overlays | flood 17, both files | 30 s loop | last CLOSED hour | headers | **MTA** |
| 7 | Flood history markers | notify 05 manifest (+lon/lat) | per spine rebuild | per spine rebuild | headers | — |
| — | History detail | one per-asset file on click | per spine rebuild | per spine rebuild | n/a (interaction) | — |

Layers 2-7 are toggles. Layer 1 and the shell are the only first paint. Row 8 is
not a layer: it is a click-time fetch, median 746 B, and it is what keeps the
10.9 MB of per-asset history off every page load.

**Write cadence is not data cadence** — the distinction the original ticket
missed. Three write cadences (30 s loop, per build, per spine rebuild); five data
cadences, because the 30 s loop carries sources publishing at 10 / 15 / 30 / 360 s
and hourly, and the model tier recomputes ~24/day. The panel is keyed on DATA
cadence.

### What the reviews reversed

Recorded because the draft would have shipped all four:

1. **"The flood panel has zero MTA dependency"** — false; the proposed ungated
   `flood` family was a licence breach with a family name on it (D3).
2. **"Skew errs stale"** — false in the common direction: `Math.max(0, ...)`
   clamps a behind-running browser clock to 0, and the draft's "file age alone for
   new layers" would have removed the `vp_age_s` backstop that currently covers it
   (D2).
3. **"Add `as_of_utc` to every payload"** — breaks a green byte-identity test and
   notify 05's own re-export requirement; also creates fresh-file-over-stale-
   upstream, the very trap it cited (D2).
4. **A gz byte budget** — denominated in a unit this deployment does not produce
   (D4). Plus: the draft's D1 (open in "Explain" mode) and D4 (cells leaves first
   paint) contradicted each other, since cells IS Explain mode's content — modes
   were cut (D1).

### Fog graduated

"Mobile/small-screen treatment of a four-layer map" is now specifiable and was
folded into **ticket 02** rather than minted as a new number: 02 already builds
2-3 throwaway variations of these layers reading together, and small-screen is the
same prototype at a different width, not a second session. `web/app.css:69` already
carries a 900px breakpoint that stacks the panels under a 60vh map — the now-
concrete question is whether stacking survives seven toggles and their freshness
rows, or whether the panel set has to collapse. Recorded on the map.

No other fog graduated: embeds/sharing still waits on a visibility decision,
auth/abuse belongs to ticket 03, and schedule-vs-actual still has no phrasable
question.
