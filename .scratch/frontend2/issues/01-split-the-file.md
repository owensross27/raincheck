# frontend2 01 — split the file

**Status: in-progress** (opened 2026-08-25; written from the paste box in
`~/vault/raincheck-runbook/DESTINATION-PLAN.md` §2)

**Gate: SATISFIED.** frontend 05 (`33d6400`) and 06 (`914c068`) landed on master
`b056ecb` at the WAVE 4 GATE, PART 1.

## What this builds

**NOTHING new.** `web/app.js` is 781 lines and `tests/test_live.py` is 775, both against
the 800 cap, and frontend 05 froze **SPLIT THE FILE, never the page**. Both are split
along the section comments already in them, with zero behaviour change.

## MUSTs

1. **ES modules, no build step, one page.** `web/index.html` keeps ONE script tag for the
   page's own code (`type="module"`, `app.js` is the entry); the vendored MapLibre UMD
   stays a classic tag and a global.
2. **Every new `.js` file is a `site` family key.** Added to
   `publish.FAMILIES["site"].files` (`src/raincheck/publish.py`). Adding keys is ADDITIVE
   under `contract.PROMISE[1]`, so NO `contract.CONTRACT` bump, and
   `tests/test_publish.py::test_the_contract_integer_covers_the_surface_a_consumer_binds_to`
   stays green — asserted explicitly. `docs/read-api-contract.md`'s site row updated.
3. **Tests read the page through the family, never a hand list.** `tests/test_live.py`
   splits into `tests/test_live_export.py` (the 14-3/14-4 export, loop and server tests)
   and `tests/test_page.py` (the page-text rules), over a shared `tests/page.py` whose
   `page_js()` concatenates every `site`-family `.js` key from `publish.FAMILIES` in
   publish order. Every existing text assertion passes UNCHANGED apart from the helper
   import.
4. **No behaviour change, proved two ways:** the same test set passes at the same count,
   and `make web` + a check of the seven-layer page.
5. **frontend 01's boot rule survives the split:** the boot path still names no
   `cells.geojson` (the text assertion moved to the helper, not away).

## The module map (the deliverable wave 8 leans on)

Six files, none over 400 lines, in publish order — which is also load order:

| module | owns |
|---|---|
| `web/layers.js` | the ramps and the four hues, `STALE_AFTER_S` / `DELAY_CUT_S`, the `GATE` table, the `LAYERS` table, `L` / `shut` / `$` / `fmt` / `SMALL` / `on`, and the declare-at-boot map + style (the twelve layers in the frozen order). Constructs `map`. |
| `web/freshness.js` | `ages` / `whys`, `grab` / `load` / `forget`, `fmtAge`, `srcState` (the five states, in their frozen precedence) and `worst`. |
| `web/panel.js` | `chipHTML` / `srcRows` / `rowHTML`, `renderLayers` (with the focus restore), `applyVisibility`, `toggle` (the exclusive fill channel). |
| `web/insight.js` | `paint` / `colorExpr` / `activeProp`, `renderHeadline`, `renderCurve`, `setHour` / `drawHourButtons` / `setView` / `buildViews`, `showTip`, `drawCells`. |
| `web/live.js` | `metaAge` / `isStale`, `renderLive`, `liveTick`, `toggleLive`, and the live panel's state (`liveMeta`, `liveFeatures`, `liveTimer`). |
| `web/app.js` | boot ONLY: the map controls, every `addEventListener`, every `map.on` / `map.once`, both `ResizeObserver`s, and the first `renderLayers()`. |

## The load-order rule this split is pinned on

The graph is CYCLIC by construction — `layers.js` needs `drawCells` (insight) inside a
`LAYERS.draw` closure, and `freshness.js` needs `liveMeta` (live) inside `srcState` — so
ES module evaluation runs the bodies in a surprising order (measured under node 25:
`panel · live · freshness · insight · layers · app`; `layers.js` evaluates almost LAST,
not first). A cycle is safe only when no module BODY reads another module's binding.
Hence: **only `app.js` wires the DOM and the map**, and the other five modules are
declarations plus their own construction. `test_only_the_boot_module_wires_the_dom_and_the_map`
is that rule. Anything a later ticket adds follows it or the page throws a TDZ
`ReferenceError` at load with the map never painting.

Cross-module writes go through a named function for the same reason (an imported binding
is read-only): `layers.markStyled()` and `live.toggleLive()`.

## PROTOCOL

Worktree only; own-module tests only (`tests/test_page.py`, `tests/test_live_export.py`,
`tests/test_publish.py`); never the full suite.
