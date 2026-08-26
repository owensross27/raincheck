# frontend2 02 — the basemap decision, landed

**Status: DONE 2026-08-25** — branch `frontend2-02-basemap`, final `a403dba`, PUSHED, landed on master at the wave-6 gate; +14 tests, 22 mutants / 21 killed (the one survivor is measured-equivalent and recorded). The R2 half stays UNMEASURED, blocked on the `raincheck-public` bucket ([YOU]). (Written from the paste
box in `~/vault/raincheck-runbook/DESTINATION-PLAN.md` §2, re-armed as wave 6 box I.)

**Gate: SATISFIED.** frontend2 01's completion entry is in `RUN-LOG-ARCHIVE.md` (the
wave-5 gate moved it there — the live log is one gate deep) and its landing is recorded in
`RUN-LOG.md`'s "WAVE 5 GATE, PART 1" entry: `779e359` -> `a1f1c60 9f9cbf5 d7be5c9` on
master. The page IS six ES modules on disk.

## The reversal, named

`.scratch/pipeline/issues/14-serving-surface.md:88-97` (2026-08-17) refused a basemap:
"no basemap now (Protomaps NYC extract measured at 112 MB, **needs a Range server** and
**three-licence attribution** -> optional `make basemap`)". **That refusal is REVERSED
here**, per `DESTINATION.md` §3.D and `DESTINATION-PLAN.md` §1's reversal paragraph, and
the decision was already MADE before this session started — this ticket records WHAT
CHANGED, it does not re-open the question.

| ticket 14's reason (2026-08-17) | status 2026-08-25 |
| --- | --- |
| "needs a Range server" | **EXPIRED.** frontend 03/04 (2026-08-24) moved serving to an R2 bucket + a custom domain, and R2 serves byte ranges. MEASURED at this ticket against the same architecture (Cloudflare R2 behind a custom domain): `curl -sI -r 0-1023 https://build.protomaps.com/20260824.pmtiles` -> **206**, `accept-ranges: bytes`, `content-range: bytes 0-1023/137522619143`. PMTiles is single-file range-request by design. |
| "112 MB" | **EXPIRED and re-measured smaller.** 112 MB is immaterial on R2, and it was the wrong number to inherit anyway: it is the CITY bbox at full zoom. This ticket ships the METRO bbox at maxzoom 13 — **52,405,810 bytes** — which covers the whole frame the page's opening view can show and is a sixth of the metro-at-z15 alternative. |
| "three-licence attribution" | **SURVIVES as work, not as a refusal.** It is TWO licences, not three (the tileset is one ODbL Produced Work; the style is CC0 and the code BSD-3), and `#provenance` has been mounted and mode-invariant since cloud 09 for exactly this. Worded below from the two upstream requirements, read at this ticket. |
| the local preview | **SURVIVES, and is handled here.** `python -m http.server` genuinely has no Range support, which is why `make web` now points at `raincheck.webserve`. |

## What this builds

A vector basemap under the seven layers — land, water/shoreline, roads, place labels —
from ONE PMTiles file, so the map reads as geography instead of a flat rectangle with
taxi zones on it.

## MUSTs

1. **One file, range-served, no compute.** `make basemap` writes gitignored
   `web/tiles/nyc.pmtiles`, sha256-pinned in the Makefile in `make vendor`'s
   download-to-`.new` / verify / move shape. The three new vendored web assets
   (`vendor/pmtiles.js`, `vendor/basemap-dark.json`, `vendor/notosans-0-255.pbf`) come
   through `make vendor`, each with its own sha pin — **no CDN at demo time** (spec L),
   and the basemap STYLE is a vendored JSON, never fetched from a third host.
2. **Every new vendored file is a `site` family key** (additive under
   `contract.PROMISE[1]`, **no `contract.CONTRACT` bump**). The `.pmtiles` object is NOT
   `site` and is never committed: it gets its own family **`tiles`** (prefix `tiles/`,
   `RARE_CACHE`, cadence "deploy-time", writer "the operator, after `make basemap`"),
   documented in `docs/read-api-contract.md`. `web/tiles/` is gitignored.
3. **The basemap is a SOURCE like any other and gets a freshness row.** It is a `LAYERS`
   entry; when the tile fetch fails the layer goes **OFF with the reason printed** and the
   page degrades to the flat `bg` rectangle (`layers.js` style layer `bg`) — a missing
   basemap is an explained chip, never a black screen and never a thrown boot. Its layers
   sit ABOVE `bg` and BELOW every one of the twelve data layers, and the frozen-order test
   is re-derived to assert exactly that rather than a longer literal.
4. **Attribution in `#provenance`, mode-invariant**, worded from the two upstream
   requirements as read on 2026-08-25 (not paraphrased from memory):
   - **OSMF Attribution Guidelines** (`https://osmfoundation.org/wiki/Licence/Attribution_Guidelines`):
     credit "© OpenStreetMap contributors"; for a browsable map the credit appears in a
     corner of the map or adjacent to it; attribution "must also make it clear that the
     data is available under the Open Database License", which may be done by linking
     "OpenStreetMap" to `openstreetmap.org/copyright`.
   - **Protomaps basemaps** (`https://github.com/protomaps/basemaps`): tilesets are ODbL;
     the required corner attribution is
     `<a href="https://github.com/protomaps/basemaps">Protomaps</a> © <a href="https://openstreetmap.org">OpenStreetMap</a>`;
     "Web maps and native apps that use this Produced Work must visibly attribute ©
     OpenStreetMap". Credit to Protomaps is requested, not legally required — it is given.
   The archive carries the same requirement in its own metadata (`pmtiles show`):
   `attribution <a href="https://www.openstreetmap.org/copyright" ...>&copy; OpenStreetMap</a>`.
5. **Local preview needs Range.** `raincheck.webserve` is a ~40-line
   `SimpleHTTPRequestHandler` subclass honouring a SINGLE `Range:` byte range, and
   `make web` points at it. Marked `# ponytail:` (single-range only).

## Refusals

- **No second ramp and no new colour channel.** The basemap is the official Protomaps
  DARK flavour, unmodified apart from three structural edits made at load time (drop its
  own `background`, drop `pois`, collapse three fontstacks to one). It recedes; the Cell
  fill keeps the only ramp on screen (frontend 02 D1, DESTINATION-PLAN D1).
- **No POI icons and no sprite.** Dropping the `pois` layer is what removes the sprite
  dependency, so there is no second third-host asset to vendor.
- **No basemap tier, no basemap input to anything.** It is a serving asset and does not
  enter the data pipeline (DESTINATION §4).

## Measurements

Recorded in the RUN LOG entry for this ticket: the extract's size and determinism, the
alternatives measured before the bbox/zoom choice, the Range curl, and the R2 rows (or
their UNMEASURED status — the `raincheck-public` bucket is a standing [YOU] item).
