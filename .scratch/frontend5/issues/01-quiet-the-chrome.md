# frontend5 01 — quiet the chrome: grouped panel, prominent card, clickable dots, thin strip

Status: done
Chartered by Ross live, 2026-08-27, his words: "everything is still super busy — the
whole thing on the left: so much writing; the tooltip for when you click on things is
not very prevalent, it's hard to know 'oh, that thing popped up'; some of the dots are
so small it's hard to click them; the thing at the bottom: you should be able to make
that way smaller; the base map thing, bus route geometry, and all that stuff: you
should make it expandable." Plus: "turn those things back on" = the subway-impact and
MTA-alert layers boot ON again (desktop; the small-screen point rule stands).
Files: `web/layers.js`, `web/panel.js`, `web/app.js`, `web/app.css`, `web/index.html`,
`web/insight.js` (only if the card change needs it), `tests/test_page.py`.

## MUSTs

1. **Defaults**: `subway` and `mta` LAYERS entries -> `open: true`. `zones` and `cells`
   STAY `open: false` (Ross's earlier call — do not revert). Re-derive the opens-set
   test to `{"basemap", "subway", "mta"}` with the two calls dated in the message. The
   small-screen rule (`!(SMALL && l.point)`) is untouched — phones still open points-off.
2. **Ground group, expandable (the left-panel diet)**: the four ground rows —
   `basemap`, `zones`, `stormwater`, `routes` — collapse behind ONE native `<details>`
   ("Ground layers"), default CLOSED, inside the layers card. Native element, no JS
   framework; the summary row shows how many of the four are lit. Everything
   non-ground stays a visible row. Do NOT touch the analyst `<details>` (`:955`-family
   tests pin exactly ONE disclosure by id/shape — re-derive that test honestly to
   distinguish the two by id, never by weakening the closed-by-default pins). Focus
   discipline: the existing rebuild-restores-focus rule must keep passing with rows
   inside the group.
3. **Card prominence**: when `#card` opens, it must be unmissable — a brief highlight
   animation (CSS `@keyframes` outline/background flash on open, ~600 ms,
   `prefers-reduced-motion` respected) and `scrollIntoView({block: "nearest"})` so it
   is on screen. Keep `h.focus()` (the a11y half). No layout moves, no new panel.
4. **Clickable dots**: the interactive point layers (`hist`, `subway`, `mta`, `fn`)
   get honest hit targets. First rung: raise the small radii (hist's minimum, the
   flood-tier dots) a step — measure what they are before choosing numbers. If radii
   alone still feel sub-8px at default zoom, add an invisible hit affordance — BUT
   measure whether a transparent stroke/low-alpha paint actually extends MapLibre's
   hit test in a REAL tab (CDP click at a known offset) before shipping it; do not
   assume. The `fn` hollow-ring = dry-sensor meaning is frozen (shape semantics stay).
   `live` radius stays 2.6 (fleet density is the point).
5. **The bottom strip**: shrink the credit strip — smaller font, tighter padding, one
   line where possible. The strip stays ALWAYS-MOUNTED with every pinned literal
   still in it (licence/attribution strings are publishing conditions — shrink,
   never remove or collapse). Layout reads its MEASURED height, so no clearance
   arithmetic to fix. Re-derive any pixel-pinned CSS test by shape, not by literal.
6. **Claim discipline unchanged**: no pinned string weakened, nothing moved out of
   the always-visible strip, strings still RENDERED from payloads. The mixed-page
   rule: keep every id the current modules touch (old JS over new HTML degrades).
7. **Tests + mutation round** (standing rules; own-module = tests/test_page.py in the
   worktree): re-derive what your changes touch (opens set, disclosure count, strip
   slices), add pins for the group (four ground rows inside the ONE new details, closed
   by default), the card flash (class/keyframes present + reduced-motion guard), the
   radii. Mutants at minimum: group ships open; a fifth row sneaks into the group;
   flash dropped; reduced-motion guard dropped; a strip literal deleted (must go RED).

## Refusals

- No removal of any layer, string, or licence element. No second disclosure pattern.
- No `promoteId`/feature-state; no Popup; no new dependency; no build step.
- `RATIO_STOPS`/`GREY`/`LIVE_*` byte-untouched; the fill radio untouched.

## Protocol

Worktree `/Users/ross/raincheck-wt/frontend5-01` from master, branch
`frontend5-01-quiet-chrome`, own-module tests via main venv + PYTHONPATH=src, never
the full suite, no pin commits, no vault writes (report your RUN-LOG entry back).
Screenshot before/after at 1280x800 (standing headless recipe) committed as
research/frontend5-01-{before,after}.png. Commit explicit paths, push.

## Close-out — 2026-08-27

Landed on `frontend5-01-quiet-chrome`. All 7 MUSTs implemented; every Refusal held
(`RATIO_STOPS`/`GREY`/`LIVE_*` byte-untouched, no `promoteId`/Popup/dependency/build
step, the fill radio untouched — verified by diff against master, not just by eye).

**MUST 1** — `subway` and `mta` boot `open: true` (`web/layers.js`); `zones`/`cells`
untouched. Opens-set test re-derived to `{"basemap", "subway", "mta"}`, dated message
naming both calls (frontend4 05 2026-08-27 opened ground-alone; frontend5 01 2026-08-27
reopened these two).

**MUST 2** — the four ground rows (`basemap`, `zones`, `stormwater`, `routes`) collapse
behind a SECOND native `<details id="ground-layers">`, built entirely by panel.js's new
`groundHTML()` (never in index.html's static markup — the analyst `<details>` stays the
page's one STATIC disclosure, so `html.count("<details") == 1` is still literally true,
now asserted deliberately rather than by accident). Its own open state rides the same
`openDet` Set the row chevrons use, keyed `"ground"`, synced in app.js from the native
`toggle` event (delegated on `#layers` with `capture: true`, since the element is
destroyed and rebuilt on every `renderLayers()` call). Verified in a real headless-Chrome
tab (not just source-text): the group stays open across a rebuild triggered by ticking a
row inside it, and the rebuild-restores-focus rule lands focus back on that row — but only
under a REAL `Input.dispatchMouseEvent` click; a synthetic `element.click()` via
`Runtime.evaluate` does NOT focus a form control the way a real pointer click does (no
mousedown precedes it), which read as a false "focus lost" until re-tested with a real
click. New CDP-harness fact, worth a TRAPS entry: **a script-triggered `.click()` fires
the click default action but skips the focus step a real user click gets from mousedown —
any focus-restore probe needs a real dispatched click, not `.click()`.**

**MUST 3** — `showCard()` (`web/insight.js`) adds a `flash` class (removed and reflowed
first, so a second click on an already-open card re-triggers it), calls
`scrollIntoView({block: "nearest"})`, then `h.focus()` as before. `app.css`'s
`@keyframes card-flash` is background-only (checked: no width/height/top/left in the
keyframe body) and guarded by `@media (prefers-reduced-motion: reduce)`.

**MUST 4** — rung 1 (measured before choosing numbers): hist's minimum stop was 1.6px
(most of the 8,146 markers sit near it, since n_events=1 is the common case) → 2.6px; fn
6/3.4 → 7/4.4; mta 7 → 8. `live` stays 2.6, byte-untouched. Rung 2, hist only: it is the
one of the four interactive point layers with NO `circle-stroke-width` at all (fn/mta/
subway each already carry a real, visible stroke that already extends their own hit test
the same way, so they needed no separate affordance). Read MapLibre 5.9.0's own vendored
source first — `CircleStyleLayer.queryRadius` and `.queryIntersectsFeature` both sum
`circle-radius` + `circle-stroke-width` for the hit test — then MEASURED it rather than
shipping on the reading alone: a real headless-Chrome CDP session (`--headless=new
--disable-gpu --enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader
--remote-allow-origins=*`) served the worktree, ticked the hist layer, computed a real
marker's projected screen position (Web Mercator math, validated against a dead-center
control click before trusting any offset), and dispatched real
`Input.dispatchMouseEvent` clicks at increasing offsets. **Baseline (stroke 0, radius
2.6px): hit through +3px, missed from +4px.** **Shipped (`HIST_HIT_STROKE=4`, radius+
stroke=6.6px): hit through +7px, missed from +8px.** Same marker, same page, only the
stroke changed, and the hit boundary moved with it — shipped as a zero-alpha
(`rgba(0,0,0,0)`) stroke, pixel-invisible, hit-target only.

**MUST 5/6** — `#provenance`'s own padding/font shrunk (`4px 12px`/`12px` →
`2px 10px`/`11px`); every pinned licence/attribution string unchanged and still rendered
from its payload (verified: the existing basemap-attribution and geo-attribution tests
pass unmodified); the 44px `#info-btn` touch target untouched (an accessibility floor,
not chrome). No id moved, added, or removed on any existing element.

**Tests**: 70 → 74 `def test_` in `tests/test_page.py` (net +4: the ground group, the
card flash + reduced-motion, the four layers' radii, the strip's shrunk chrome — plus
re-derivations of the opens-set test, the layer-panel-ids pin, and the analyst
one-disclosure test's assertions/docstring, none of which added a net-new function).
`PYTHONPATH=src python -m pytest -q tests/test_page.py` → 74 passed.

**Mutation round** (commit `b7d8d9c` first, `PYTHONDONTWRITEBYTECODE=1`, restore verified
clean after each): all 9 mutants killed — the 5 the ticket named at minimum (group ships
open, a fifth row sneaks in, flash dropped, reduced-motion guard dropped, a strip literal
deleted) plus 4 more covering the substantive changes (mta open reverted, hist radius
reverted, `HIST_HIT_STROKE` painted visible, strip padding/font reverted). Pristine
control re-run after restore: 74 passed, `git status --porcelain` empty at `b7d8d9c`.

**Screenshots**: `research/frontend5-01-before.png` (master, served from the main
checkout, still clean on `master`) / `research/frontend5-01-after.png` (this worktree,
real `web/files` copied in for a faithful render), both 1280x800 via
`Page.captureScreenshot` after a real wait (never `--screenshot`), cold `--user-data-dir`
per shot. The after shot shows the collapsed "GROUND LAYERS (1/4 ON)" row replacing four
separate rows, the MTA-alerts row auto-open with its detail expanded, and the subway
overlay's dots rendering across the map (both reopened by MUST 1).
