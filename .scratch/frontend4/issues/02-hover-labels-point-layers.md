# frontend4 02 — hover labels on the point layers, click cards untouched

Status: done
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

## Close-out, 2026-08-27

Landed on `frontend4-02-hover-point-layers` (sha `ea926d5`), worktree
`/Users/ross/raincheck-wt/frontend4-02`. `tests/test_page.py` def-count 54 -> 58 (+4).
`PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_page.py`: **58 passed in
0.26-0.44s, 0 skipped** (no env-gated skips in this file — page tests read `web/`
source + `publish.FAMILIES`, nothing archive-rooted).

- Built exactly the spec'd mechanism: `TIPS` table + `pointTip(layerId)` factory in
  `insight.js` (new, exported), wired for `mousemove`/`click`/`mouseleave` on `hist`,
  `subway`, `mta`, `fn` in `app.js` ONLY, registered as one `for` loop BEFORE the
  existing `hist` click -> `showCard` handler (so a hist tap's final state is the
  card open and the tip hidden — MapLibre fires same-event handlers on one layer in
  registration order; verified by reading the loop's position in the boot module).
- `hist` fallback (`p.name || p.asset_id`), the id-always-prints sub line, the
  conditional `rel` read (`"rel" in p`, mirroring `live.js`'s own `"rel" in c`) and
  every untrusted string (`name`, `label`) through `esc(` all match the spec's exact
  property spellings, verified against the real published files at the ticket
  (`web/files/history/manifest.geojson`, `impact-subway.json`, `flood-mta.json`,
  `flood.json`).
- Mutation round (standing rules: commit BEFORE mutating, snapshot from git,
  `PYTHONDONTWRITEBYTECODE=1`, pristine control before/after, restore verified with
  `git status --porcelain` empty after every `git checkout -- <path> && git clean
  -fdq <path>`), 4/4 killed:
  1. guard one layer's `mouseleave` (`if (id !== "fn") map.on("mouseleave", ...)`)
     — SURVIVED against my first wiring test (which only checked substring
     presence of each `map.on(...)` line, not that the trio is unconditional and
     contiguous); FIXED the test to pin the whole four-line block as one literal
     unit (commit `ea926d5`), then killed clean.
  2. `p.name || p.asset_id` -> `p.name` alone on `hist` — killed
     (`test_the_hist_tip_falls_back_to_the_asset_id_and_the_id_always_prints`).
  3. unescape `fn`'s `p.label` (`${p.label}` raw) — killed
     (`test_every_tips_entry_escapes_its_untrusted_strings`).
  4. make `subway`'s `rel` line unconditional — killed
     (`test_the_subway_tip_reads_rel_only_when_the_key_is_present`).
- **PROTOCOL DEVIATION, disclosed**: my first edit pass wrote directly into the MAIN
  checkout (`/Users/ross/raincheck/web/{app.js,insight.js}`) before creating the
  worktree — caught before any commit. Diff was saved to a patch file, the main
  checkout was `git checkout --`-reverted to clean, THEN the worktree was created
  and the patch applied there. `git status --porcelain` on the main checkout was
  confirmed clean before proceeding; no commit ever touched master or the main
  checkout.
- No forward-context edits owed beyond this file and this box: the mechanism ticket
  04 must honor is `insight.js`'s exported `TIPS` table (`layerId -> (properties) =>
  htmlString`, entries for `hist`/`subway`/`mta`/`fn`) and `export function
  pointTip(layerId)` (returns a MapLibre event handler that sets `TIPS[layerId](
  e.features[0].properties)` into `$("tip").innerHTML`, positions it at
  `e.point.x/y + 14` clamped to `window.innerWidth - 280`, and sets
  `display: "block"`) — ticket 04 adds a `live:` entry to `TIPS` and wires it the
  same way (`pointTip("live")` on mousemove/click/mouseleave in app.js), per its own
  box.
