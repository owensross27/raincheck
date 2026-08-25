# 05 — The seven-layer chassis: one page, honest toggles, five freshness states ✅ DONE

**What to build:** the existing live map page becomes the seven-layer page the
spec describes, END TO END, with today's payloads: a viewer opens it and sees
ground zones + delay cells + headline rendering from the real files, a toggle
panel with one row per layer, per-SOURCE freshness chips speaking all five
states (FRESH / STALE+reason / OFF / GATED / AGE, ages computed reader-side
from `Date` − `Last-Modified`), the provenance strip always mounted with
layout driven off its measured height, and the four not-yet-landed sources
(fleet, FloodNet tier, MTA tier, impact) present as honestly OFF/GATED chips —
because rendering truthfully with layers dark is a design requirement, not a
degraded mode. This is the tracer bullet: every later slice only lights a
layer this chassis already declares.

**Blocked by:** None — can start immediately. (Spec: `.scratch/frontend/spec.md`;
the decisions it implements are tickets 01/02's Answers — read both.)

**Status:** DONE 2026-08-25 (`frontend05-seven-layer-chassis`)

- [x] All twelve map layers declared at boot, empty + hidden; `promoteId` off
      everywhere; the layer order is the spec's, verbatim
- [x] The Cell-fill RADIO exists with delay cells as its only lit option
      (impact joins in ticket 08); two fills at once is impossible, tested
- [x] Freshness rows: one per source; only budget-frozen sources may say
      FRESH/STALE; unbudgeted sources say AGE; OFF collapses the row; GATED
      renders the chip hue, never absence — all five states mutation-checked
- [x] The new hues + the hollow-ring dry-sensor mark are constants beside the
      frozen ramps; the ramps themselves are byte-untouched
- [x] Toggling never destroys keyboard focus (reuse the page's existing
      focus-restore mechanism); verified by test, not by hand
- [x] <= 900px opens fill-on/points-off; nothing positions against a guessed
      provenance height (the hit-test failure from the prototype cannot recur)
- [x] The lineage-gate KEYS exist (two gate sides) even while both sides are
      dark, so ticket 08 lights them without re-plumbing
- [x] Existing page tests stay green; new claims pinned in the same
      page-as-data seam; own-module tests only


## Close-out — 2026-08-25, branch `frontend05-seven-layer-chassis`

Landed in `web/index.html` + `web/app.js` + `web/app.css`, pinned by 18 new tests
appended to the existing page-as-data seam in `tests/test_live.py` (57 -> 75 in the
three page modules; no new test file, no new seam).

### The chassis's contract — what tickets 07 and 08 mount into

**The twelve map layers, declared at boot in the frozen order**, every source an empty
`FeatureCollection`, every one but `bg` `visibility: "none"`, `promoteId` off everywhere:

    bg · zones-fill · cells · impact-fill · cells-line · impact-line · zones-line ·
    locate · live · hist · fn · mta

`locate` is declared and empty for 07's hover-locate ring. Nothing is added lazily —
`addLayer(`/`addSource(` appear nowhere in app.js and a test refuses them.

**The two lineage-gate keys** (`const GATE` in app.js), both shut, each layer keying off
its own side via `shut(lyr)`:

    "mta-vehicles"   the live fleet, flood 17's bus impact overlay
    "mta-alerts"     the MTA flood tier's alert rows

A test DERIVES the expected value from `publish.LIVE_TERMS_VERIFIED`, so a side opened on
the page without the receipt goes red. Ticket 08 lights a side by flipping ONE boolean.

**The freshness seam.** `LAYERS` is the table: per layer `id / name / point / gate / fill /
open / map[] / owed / srcs[] / draw`. Per source `{ k, url, budget, inner? }`. Age is
`ages["<layer>/<source key>"]`, filled by `grab(lyrId, s)` from `Date` − `Last-Modified`;
`whys[...]` carries the reason when there is no age. `srcState(lyr, s)` returns
`{s, why?, age?}` in a FIXED precedence — GATED, OFF, STALE-with-no-age, AGE, then
FRESH/STALE against the budget — and `worst(lyr)` folds a layer's sources worst-first.
A layer graduates from AGE to a verdict by getting a non-null `budget`, and by nothing else.

**Payload filenames this chassis reads** (chosen here because no writer had frozen one;
each is now a MUST on its owner's ticket): `files/flood.json` (flood 15, ungated),
`files/flood-mta.json` (flood 15, alerts side), `files/impact.json` (flood 17),
`files/history/manifest.geojson` (notify 05).

### What was measured, not assumed

- **11 mutations applied to `web/app.js` and observed RED**, then reverted: radio ->
  checkbox · exclusivity line deleted · a layer reordered in the boot block · a layer
  shipped visible · OFF tested before the gate · a guessed budget on an unbudgeted source ·
  age off `Date.now()` · a gate side opened without the receipt · focus restore dropped ·
  a point layer defaulted on · a 404 treated as a normal response.
- **The page was RUN, not only read**: `web/app.js` executed under node with a stub DOM
  and a stub MapLibre, against the REAL `web/files/` payloads — 17/17 checks pass. It boots
  without throwing, declares the twelve in order, fetches only the two ticked layers,
  paints 1,200 real Cells, renders the two radios in one group with `impact` disabled and
  GATED, reads AGE off real headers, and — with the vehicle gate forced open — ticking the
  impact overlay really does turn the delay fill off in the state AND on the map.
- **`Date` and `Last-Modified` both arrive** from the stdlib server `make web` runs
  (measured: `Date: Tue, 25 Aug 2026 13:28:54 GMT`, `Last-Modified: Sun, 23 Aug 2026
  19:13:53 GMT` on `files/cells.geojson`), so the header age model works locally and not
  only against R2.

### Deliberate deviations, each with its reason

- **The live fleet's row is the Live panel, not a row in `#layers`.** frontend 01 D1 made
  `#livetoggle` the pattern every layer copies, and it already owns the 30 s interval and
  the `vp_age_s` composite. Two controls for one layer would be the confusing thing.
  `#layers` renders the other six; `#src-live` and `#live-chip` render the fleet's
  freshness inside its own panel, from the same `srcState`.
- **`#livetoggle` stays operable while the vehicle gate is shut.** The gate governs
  PUBLISHING; locally `make live-export` really does write the two files. The row says
  GATED and explains exactly that, and on the host the 404 now reads "not published on this
  host" instead of the old, false "run make live-export".
- **`cells` and `zones` are no longer style-URL sources.** They are fetched by the page so
  their responses' headers can be read, which also retires frontend 01's MUST-3: the 2.3 MB
  `cells.geojson` is now fetched and parsed ONCE, not twice.

### Owed forward

- **`web/app.js` is 781 lines and `tests/test_live.py` is 775** — both inside the 800 cap
  and both out of room. The next slice SPLITS THE FILE, never the page (frontend 01 D1): a
  second `<script>` tag is one line in `publish.py`'s `site` family tuple. Written onto 07
  and 08.
- **Not verified in a visible browser tab.** The repo's own rule is that MapLibre throttles
  rAF when hidden, so rendering is checked by hand; this session had no browser. What is
  unverified is purely visual: hue legibility, the hollow ring at render scale, and whether
  the two columns clear the measured provenance strip at 375 px. Run `make web` and look.
