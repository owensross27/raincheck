# frontend5 01 — quiet the chrome: grouped panel, prominent card, clickable dots, thin strip

Status: ready-for-agent
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
