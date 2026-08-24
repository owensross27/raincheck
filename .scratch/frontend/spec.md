# Frontend spec — the seven-layer map and the static read contract

Status: ready-for-agent
Produced by /to-spec over the CLEARED wayfinder map (`map.md`), 2026-08-24, at
Ross's direction. Every decision below was resolved on the map's tickets 01-04
(grilling x2, prototype, research) — this document collapses them; it decides
nothing new. Where a table encodes a decision more precisely than prose, it is
inlined from the prototype/resolution verbatim.

## Problem Statement

The system computes real things — live bus positions, delay-by-cell, flood
tiers, station impact, per-stop flood history — but a person can only see them
as separate payloads, and an external consumer can only learn the data's shape
by being told. There is one place to LOOK but not one place to SEE, and there
is an API in substance (stable published files) with no way to discover or
version it.

## Solution

Extend the existing live map page into ONE page with seven independently
toggled layers — ground zones, delay cells, live fleet, FloodNet flood tier,
MTA-alert flood tier, impact overlay, flood-history markers — each honestly
labelled with its own freshness, with per-stop flood records opening in-page
on click. Publish the already-real static contract as the v1 read API: the
five payload families on the public bucket plus one new discovery file
(`files/index.json`) carrying a breaking-change integer. No new runtime
components anywhere: the page is HTML/JS on a bucket, the API is the bucket.

## User Stories

1. As a rider, I want the delay-by-cell picture and the live fleet on one map,
   so that I can see whether rain is slowing buses right now without knowing
   which payload is which.
2. As a rider, I want flood-risk tiers drawn as station/sensor points beside
   the delay picture, so that I can see where flooding is reported or likely
   near my route.
3. As a rider on a phone, I want the map to open legibly at 375px (fill layer
   on, point layers off, added one at a time), so that the small screen shows
   two readable things instead of seven illegible ones.
4. As a viewer, I want every layer to carry FRESH / STALE(+reason) / OFF /
   GATED / AGE per SOURCE, so that a dead feed reads as dead and an unbudgeted
   source shows an age instead of a guessed verdict.
5. As a viewer, I want a layer that is gated (MTA terms) to render as a GATED
   chip rather than vanish, so that absence is explained, not mysterious.
6. As a viewer, I want to click any stop, Cell, or station and get its flood
   record in a card that shares the right column, so that the record never
   covers the freshness rows or the map.
7. As a viewer, I want unnamed assets (Cells) titled by a readable id
   fallback, so that the most-flooded places never display "null".
8. As a keyboard user, I want toggling a layer to keep my focus where it was,
   so that the panel is operable without a mouse.
9. As a screen-reader or low-vision user, I want the "affected station"
   marker, the water-now sensor, and the history marker to differ by hue AND
   mark shape (hollow ring for a dry/stale sensor), so that three meanings
   never collapse into one grey.
10. As the map's author, I want every layer declared at boot with an empty
    source and hidden visibility, so that stacking order never depends on
    click order and a missing layer cannot throw.
11. As the operator, I want the page to read honestly with three layers dark
    (live fleet, MTA tier, impact overlays are MTA-gated today), so that
    publishing before the terms receipt misleads nobody.
12. As an external app developer, I want a documented static contract —
    stable keys, content types, cadences, schema pointers, version stamps —
    so that I can build against the bucket without reading the repo.
13. As an external app developer, I want `files/index.json` to carry a
    `contract` integer that bumps on breaking change, so that my app refuses
    to misread a changed schema rather than misreading it silently.
14. As an agent consumer, I want the discovery file to make the whole dataset
    self-describing, so that no human has to tell me the keys.
15. As a future app, I want stop-history plus current-tier to be two
    edge-cached fetches with reader-side dating, so that no build-time merge
    freezes a 30 s value into a per-rebuild file.
16. As the budget owner, I want zero new runtime components (no Worker, no
    server), so that the read surface adds no bill and no deploy surface.
17. As the licence boundary's owner, I want the MTA gate to cut by LINEAGE
    through the flood panel (two meta files, one per gate side), so that
    opening the vehicles never accidentally opens MTA-derived alert rows, and
    vice versa.
18. As a maintainer, I want the delay fill and the impact overlay to share
    ONE exclusive fill channel (a radio), so that two ramps on one geography
    is structurally impossible.
19. As a maintainer, I want the page's claims pinned by tests reading the
    page as data, so that a wording or rule regression fails a test rather
    than a reader.

## Implementation Decisions

- ONE page: the existing live page grows layer toggles; no second page, no
  modes. The provenance/attribution strip is always mounted (a spec §9
  publishing condition) and layout is driven off its MEASURED height, never a
  guessed clearance.
- Seven layers; history DETAIL is an interaction (click-time per-asset fetch),
  not an eighth layer. Layer order, declared at boot, ambient at the bottom
  and urgent on top (prototype-derived, verbatim): bg · zones-fill · cells
  (delay fill) · impact-fill · cells-line · impact-line · zones-line · locate
  · live · hist · fn · mta.
- The Cell FILL channel is EXCLUSIVE: delay cells XOR impact overlay, one
  frozen diverging ramp, offered as a radio. The flood tiers are point layers
  and never contest it. The impact overlay gets no ramp of its own.
- New hues, none on the ramp's arms (prototype-derived): FloodNet water-now
  aqua `#35d6c2` · MTA station-with-water amber `#ffc447` · flood record
  violet `#8f7bd6` · GATED chip `#d2a24c`. A dry/stale FloodNet sensor is a
  HOLLOW RING (stroke, no fill) — three meanings must not share the existing
  grey.
- An "affected station" marker is a dot on the COMPLEX (amber, radius 7);
  the chip/incident is what the CARD shows. Complex coordinates come from the
  flood-tier payload (a MUST already written onto flood 15).
- Freshness: a row PER SOURCE; vocabulary FRESH / STALE(+reason) / OFF /
  GATED / AGE. Age is computed by the READER from HTTP response headers
  (`Date` − `Last-Modified`, origin's clock) — never a new payload stamp.
  Only sources with a FROZEN budget constant may render FRESH/STALE; the
  rest render AGE until flood 15/17 and notify 05 freeze budgets.
- The MTA gate cuts by LINEAGE and runs through the flood panel: the flood
  tier ships TWO meta files, one per gate side (a MUST already written onto
  flood 15); the page's gated layers key off the gate side, not off one
  global switch.
- Payload rule: paint from ONE bulk file per layer; detail from ONE per-asset
  fetch on click. No compression exists in the pipeline today, so all byte
  budgets are RAW until a Content-Encoding measurement against the real
  bucket exists (a [YOU]-gated curl, filed).
- Boot rule: every layer declared up front with an empty FeatureCollection
  and `visibility: "none"`; `promoteId` OFF everywhere (hex-string ids are
  silently dropped by the map library's integer-like promotion).
- Toggle panel: patch rows in place or restore focus after rebuild — the
  page already solves this for its hour buttons; reuse that mechanism.
- Mobile (<= 900px): open with the fill on and every point layer off.
  The panel set does not collapse; the map strip is the scarce surface.
- The v1 read API is the STATIC CONTRACT, no Worker (research-priced: CORS is
  a bucket policy, rate limiting is a free-plan WAF rule, the edge cache
  fronts a custom-domain bucket automatically and never fronts a Worker,
  and a Worker adds invocations without removing Class B reads). The custom
  domain is LOAD-BEARING, not cosmetic (r2.dev: no cache, no WAF,
  rate-limited, non-production).
- One addition: `files/index.json`, written by the same exporter that writes
  the other payloads — every family with key, content type, cadence, schema
  pointer, version stamps, plus `contract` (integer, bumps on breaking
  change; keys stay unversioned because consumer zero deploys with its
  payloads). Aggregation is two parallel edge-cached fetches; the build-time
  merge is REFUSED (frozen-age trap).
- Consumers: the page itself, Ross's future apps, agents (via the discovery
  file), and the showcase. In-repo alerting is NOT a consumer and must never
  route through HTTP — it runs in-process on the 30 s loop.

## Testing Decisions

- Good tests here assert EXTERNAL behavior: the page's source as data (rules,
  strings, layer declarations, gate keys) and the payload files' shapes —
  never the map library's rendering internals.
- Prior art to extend, not replace: the live-page test file already pins the
  staleness rules and page claims by reading the page as text; the publish
  test file already pins families, ordering, gates, and cache headers. The
  chassis and contract slices extend those two seams — the highest existing
  seams, and no new seam is needed for v1.
- Fixtures for not-yet-landed sources are cut VERBATIM from the frozen
  upstream schemas (stub fidelity is a standing rule); a fixture that guesses
  a field ships a green lie.
- Mutation-check every contract claimed (the standing "green with the logic
  mutated" rule): the exclusive-fill radio, the boot declarations, the
  lineage gate keys, the reader-side age rule, the contract-integer refusal.

## Out of Scope

- Alerting internals (notify 08/10/12 own them).
- The showcase (orch 13).
- Served history for the live tier (spec §9 bars it; bucket versioning stays
  OFF).
- Any server or Worker runtime for the read surface (decided against on
  research facts; revisit only with a consumer the static contract cannot
  serve).
- Embeds/sharing and API auth (map fog, deliberately unresolved).
- The schedule-vs-actual visual layer (fog until a sharp question exists).

## Further Notes

- Three of the seven layers are MTA-GATED and dark until the terms receipt;
  rendering honestly with them dark is a DESIGN REQUIREMENT, not an edge
  case — which is why the chassis slice is buildable and demoable today.
- The losing prototype variants stay on their branch as primary sources; C's
  ranked ledger + hover-locate is the named upgrade path if the map gets
  crowded, B's freshness grid if the stacked rows get too long.
- Upstream MUSTs this spec depends on were already written onto their owners
  at prototype time: flood 15 (two meta files, chip coordinates, budget
  constants), flood 17 (no own ramp, no simultaneous fill), notify 05
  (manifest coordinates, budget constant).
