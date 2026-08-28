# frontend4 01 — basemap streets + labels: the two-splice, density overrides, one glyph range

Status: ready-for-agent
Spec: `.scratch/frontend4/spec.md` (F1). Charter: `.scratch/frontend4/charter.md`.
Blocked by: none.
Files: `web/basemap.js`, `Makefile`, `docs/read-api-contract.md`, `src/raincheck/publish.py`,
`tests/test_page.py`. The vendored `web/vendor/basemap-dark.json` stays BYTE-UNTOUCHED.

## What this builds

Real street density and street/place names as you zoom, and the recorded orientation gap
closed: basemap label symbol layers paint ABOVE the fills/lines and BELOW the point
layers. All edits are load-time transforms in `basemap.js` — the established pattern.

## MUSTs

1. **Two-splice.** `prepare()` partitions style layers into symbol and non-symbol.
   Non-symbol -> `map.addLayer(l, FIRST_DATA_LAYER)` ("zones-fill", unchanged). Symbol ->
   `map.addLayer(l, LABELS_BEFORE)` where `export const LABELS_BEFORE = "locate";`
   (`SPEC_ORDER[7]`). `dropBasemap()` must still remove every added layer (one `added`
   list covers both splices). The idempotency guard, failure path (`on.basemap = false`,
   catch never rethrows), HEAD freshness dating and `cache: "no-cache"` are untouched.
2. **Density = an `OVERRIDES` const in basemap.js**, keyed by style layer id, applied in
   `prepare()`: patch `minzoom` and/or `paint["line-width"]` (and casing
   `line-gap-width`) interpolation stops. Targets and intent (tune the exact stops
   against real screenshots, not by eye-reading JSON): `roads_minor` (+casing) visible
   hairline ~z10.5-11, clear by ~z12 (today 0-width until z11, 0.5 at z12.5);
   `roads_minor_service` (+casing) from ~z12 (today z13); `roads_other` from ~z13
   (today z14); `roads_link` (+casing) follows minor. Do NOT touch highway/major/rail
   curves, colors, or any layer this table does not name.
3. **Street names:** override `roads_labels_minor` minzoom 15 -> 13 (the extract is
   maxzoom 13; 15 was overzoom-only so minor names never showed). `roads_labels_major`
   and all text sizes/colors untouched.
4. **Nested fonts:** `prepare()` currently collapses only the top-level
   `layout["text-font"]` (`basemap.js:74-76`). Extend it to rewrite EVERY array-valued
   `"text-font"` anywhere in the layer's layout — including the override objects inside
   `text-field` `format` expressions, which name `Noto Sans Devanagari Regular v1` /
   `Noto Sans Regular` and would request un-vendored fontstacks. A recursive walk
   replacing any `{"text-font": [...]}` member with `["notosans"]` is the whole fix.
5. **One glyph range, sha-pinned:** vendor
   `https://protomaps.github.io/basemaps-assets/fonts/Noto%20Sans%20Regular/256-511.pbf`
   as `web/vendor/notosans-256-511.pbf` following `make vendor`'s exact
   download-to-`.new` / `shasum -c` / mv shape (`Makefile:316,326-335`): one curl line,
   one `_SHA :=` pin (record the sha from the real download in this ticket), one printf
   row, one name in the mv loop. Add the key to `publish.FAMILIES["site"]`
   (`publish.py:279-280` area) — ADDITIVE, no `contract.CONTRACT` bump — and one row in
   `docs/read-api-contract.md`. The glyph URL template already resolves it.
6. **Tests (own-module = `tests/test_page.py`, run in the worktree):**
   - Re-derive `test_the_basemap_goes_above_bg_and_below_every_one_of_the_twelve`
     (`:203`) to the two-splice: both `map.addLayer(l, FIRST_DATA_LAYER);` and
     `map.addLayer(l, LABELS_BEFORE);` literals present, `LABELS_BEFORE` derived from
     `page.SPEC_ORDER[7]` in the test (mirrored-constant rule), and the partition rule
     asserted (the symbol branch tests `l.type === "symbol"` — anchor on the code, not
     prose).
   - Extend the vendored-set assert (`:264-265`) with `vendor/notosans-256-511.pbf`.
   - New: the OVERRIDES const exists and names only road layers (assert the key set),
     and the nested-font collapse leaves no `"Noto Sans"` literal reachable — assert on
     the transform code, remembering the docstring-poisons-the-grep family: comments in
     basemap.js must not name fontstacks or angle-bracket tags.
   - Update the layer-count prose if you touch it; the "66" is prose, never asserted.
7. **Screenshots, committed:** before/after at z11 and z13 (city interior, fills lit),
   headless Chrome with `--headless=new --disable-gpu --enable-unsafe-swiftshader
   --use-gl=angle --use-angle=swiftshader --remote-allow-origins=*`, CDP
   `Page.captureScreenshot` after a real wait (never `--screenshot`), cold
   `--user-data-dir` per run, `Emulation.setDeviceMetricsOverride`. Serve via `make web`
   (`raincheck.webserve` — the stdlib server has no Range support and the archive is
   range-read). `net::ERR_ABORTED` on the archive is normal (MapLibre cancels a settled
   viewport's request).
8. **Mutation round** (standing rules: commit first, snapshot from git,
   `PYTHONDONTWRITEBYTECODE=1`, pristine control, verified restore): at minimum — drop
   one splice's beforeId; swap the partition predicate; revert the minor-labels minzoom
   override; skip the nested-font walk. Record kills in your entry.

## Refusals

- No edit to `vendor/basemap-dark.json`, `PMTILES_BUILD`, the tiles family, or
  attribution (same tiles, same licences).
- No new fontstack (Medium/Italic collapse to notosans stays), no sprite, no POIs.
- No new glyph ranges beyond 256-511.
- No color changes to labels or roads — recession is calibrated; position, not hue, was
  the problem.

## Protocol

Worktree at `/Users/ross/raincheck-wt/frontend4-01` (NEVER nested under the repo), own
branch `frontend4-01-basemap-streets`, own-module tests only, no pin commits, no full
suite. `make vendor` in the worktree to materialize vendor/ (gitignored). Commit with
explicit paths, push the branch, append your RUN-LOG entry + forward-context per the
generic ticket prompt.
