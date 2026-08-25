# frontend2 01 — split the file

**Status: DONE 2026-08-25** — branch `frontend2-01-split-the-file`, `36901d4`. (Written from the paste box in
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

## What was measured

- **Zero behaviour change, proved by DIFF not by inspection.** Master's single-file page
  and the six-module page were each loaded under node 25 with a stubbed DOM/MapLibre and
  the real `web/files/` (2.3 MB `cells.geojson`, 1,200 Cells; 263 zones): both print
  BYTE-IDENTICAL boot output — 12 layers declared, 6 layer rows, 6 views, 7 hour buttons,
  headline `0.72–0.82` / `0.86`, the same chip vector, the same GATED live panel, and the
  same behaviour when every layer is toggled and the fill radio is switched.
- **`make web`** (`python -m http.server --directory web`) answers 200 with
  `text/javascript` for all six modules.
- **A real browser**: headless Chrome loads master and the branch IDENTICALLY — one
  `webglcontextcreationerror` from MapLibre and no other console message, so the module
  graph, the `type="module"` tag and the MapLibre global are clean in a real engine. This
  Mac's headless Chrome has no WebGL, so `new maplibregl.Map()` throws on BOTH pages and
  boot stops there. **A VISIBLE-TAB check was NOT done** — see the RUN LOG entry.
- **12 mutations, 12 killed**, both pristine controls 65 passed. Includes: a wiring line
  moved out of `app.js` (red, AND the page throws a real TDZ `ReferenceError`), a seventh
  module with no family key, a family key with no file, `type="module"` dropped, a second
  entry tag, `app.js` renamed (correctly reads as BREAKING and demands a bump), the
  `markStyled` indirection removed, and one inherited rule per moved module.
- **Test delta +4** (806 -> 810 `def test_`): `test_live.py` 37 -> `test_live_export.py`
  15 + `test_page.py` 26. Every pre-existing assertion is unchanged apart from its import.

## PROTOCOL

Worktree `/Users/ross/raincheck-wt/frontend2-01`; own-module tests only
(`tests/test_page.py`, `tests/test_live_export.py`, `tests/test_publish.py`); never the
full suite.
