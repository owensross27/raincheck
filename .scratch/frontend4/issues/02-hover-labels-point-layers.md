# frontend4 02 — hover labels on the point layers, click cards untouched

Status: ready-for-agent
Spec: `.scratch/frontend4/spec.md` (F2). Charter: `.scratch/frontend4/charter.md`.
Blocked by: none.
Files: `web/insight.js`, `web/app.js`, `tests/test_page.py`.

## What this builds

Hovering (or tapping) a flood-history marker, subway-impact dot, MTA-alert dot, or
FloodNet sensor shows a label in the existing `#tip` element — name + the layer's
number/sentence — with the `hist` click record card exactly as it is.

## MUSTs

1. **One mechanism, the existing element.** A `TIPS` table in `insight.js` maps layer id
   -> a render function over `e.features[0].properties`; an exported factory (e.g.
   `pointTip(layerId)`) reuses `#tip`, the `showTip` positioning
   (`e.point.x/y + 14`, right-edge clamp at `window.innerWidth - 280`), and the
   escaping discipline: `innerHTML` assembles literals + `fmt()`-numbers only; every
   untrusted string (names, published sentences) lands via `textContent` (the
   `showTip` pattern at `insight.js:252-256`) or `esc()`.
2. **Wiring in `app.js` ONLY** (the ES-module-cycle rule — a handler registered beside
   its code throws a TDZ ReferenceError at load): per layer in `hist`, `subway`, `mta`,
   `fn`: `map.on("mousemove", id, ...)` + `map.on("click", id, ...)` (click = the touch
   path, the cells tooltip's own pattern) + `map.on("mouseleave", id, hide)`. Keep the
   existing `hist` click -> `showCard` (it already hides `#tip` first at
   `app.js:98-101`); order the registrations so a `hist` tap shows the card, not a
   stale tip. Layer-scoped handlers never fire on a hidden/gated layer — no gate guard.
3. **Content, exact spellings** (verified against the published files):
   - `hist`: title `p.name`, FALLBACK `p.asset_id` (`name` is an ABSENT key on all
     1,276 cell-kind features — the literal words "null"/"undefined" must be
     unrenderable); sub `` `${p.kind} · ${p.asset_id}` `` (names are not unique — the
     id always prints); line `n_events` + " flood event(s)".
   - `subway`: title `p.name`; sub `complex · ${p.complex_id}`; lines from `dropped` /
     `planned` / `drop_share`, plus `rel` ONLY when the key is present.
   - `mta`: title `p.name`; sub `p.complex_id`; line `p.state` + `p.age_min` rounded.
   - `fn`: title `p.name`; line = the published `p.label` sentence verbatim (escaped)
     + `p.age_min`. No page-authored claim strings anywhere — published values and
     neutral nouns only.
4. **Tests** (`tests/test_page.py`, text assertions; remember the traps — bounded
   splits, no prose-poisoning, anchor on code):
   - The wiring: for each of the four layers, the mousemove/click/mouseleave trio is
     registered, and ONLY `app.js` calls `map.on` (extend the existing only-the-boot-
     module-wires rule if it does not already cover the new count).
   - The hist fallback: the title expression is `p.name || p.asset_id` (or equivalent)
     and the sub renders `asset_id` — assert the source shape, not a rendered string.
   - The escaping rule: every `TIPS` render routes name/label through
     `textContent`/`esc(` — assert the mechanism's presence per entry.
   - The conditional `rel` read (`"rel" in` or `p.rel !== undefined`-shaped guard).
5. **Mutation round** (standing rules): at minimum — drop one layer's mouseleave;
   swap `p.name || p.asset_id` to `p.name` alone; unescape one untrusted string; make
   `rel` unconditional. Record kills.

## Refusals

- No cursor changes, no `setFeatureState`, no `promoteId` (hex ids — MapLibre silently
  drops the source), no new highlight layer, no `maplibregl.Popup` (the page owns
  `#tip`).
- No change to `showCard`, `closeCard`, the cells `showTip`, or the `locate` ring.
- The `live` layer's tip is ticket 04's, via this ticket's mechanism — do not add it
  here.

## Protocol

Worktree at `/Users/ross/raincheck-wt/frontend4-02`, branch
`frontend4-02-hover-point-layers`, own-module tests only (`tests/test_page.py` needs
`make vendor` absent? — no: page tests read `web/*.js` source and `publish.FAMILIES`;
run them in the worktree, vendor-file asserts skip or pass off the family table), no
full suite, no pin commits. Commit explicit paths, push, RUN-LOG entry +
forward-context. NOTE for the gate and ticket 04: ticket 04 branches FROM this branch.
