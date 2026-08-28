# frontend4 05 — the map opens on geography alone: taxi zones + Cell fill boot off

Status: done 2026-08-27
Asked by Ross mid-wave, in his own words: "remove the taxi boundaries and don't
automatically turn the hexagons on the map." Implemented by the wave-12 orchestrator
directly (two flags + one bridge — below the fan-out threshold), branch
`frontend4-05-map-defaults`, cut from `frontend4-04-fleet-rain-coloring`.

## What changed

- `web/layers.js`: `zones` boots `open: false` (the taxi-zone boundaries are gone from
  the default view; the "Ground: taxi zones" panel row stays as an opt-in — deleting
  the layer would break the frozen SPEC_ORDER chassis and `FIRST_DATA_LAYER`, which is
  not the quick fix and was not the ask). `cells` boots `open: false` (the Cell-fill
  radio boots OFF, phones and desktop both).
- `web/live.js`: `toggleLive`'s lit branch gains the guarded data-only bridge —
  `if (!on.cells && cellFeatures().length === 0) load("cells").then(liveTick, () => {});`
  — because ticket 04's band join reads the cells payload and with the fill off by
  default nothing else loads it. Data only: `load()` never touches `on` or visibility,
  the fill stays the radio's; a failed load leaves the fleet neutral (the honest
  degradation). Same `load()` path the fill's own tick uses — no second `fetch(` site
  (the 04 one-fetch test stays green).
- `tests/test_page.py`: the two boot-default pins re-derived (`lit == []` — no fill
  opens lit; `opens == {"basemap"}` — the small-screen test renamed to
  `test_the_map_opens_on_geography_alone_and_points_stay_off_small`), plus one new test
  pinning the bridge literal and its `load` import.

## Verification

67 passed in the worktree (`tests/test_page.py`, main venv + PYTHONPATH=src). Mutation:
(a) revert the zones flag -> the opens-set assert fails; (b) drop the bridge line -> the
new test fails; restore verified `git status --porcelain` empty, pristine control 67
passed, PYTHONDONTWRITEBYTECODE=1. The cells-flag mutant shares mutant (a)'s killing
assert (same set, same test) and was not run separately.

## Known trade-offs (recorded, accepted)

- The `locate` ring over `#recent` rows synthesizes centroids from the map's cells
  source; until the fill is ticked (or the live toggle loads the data) the ring has
  nothing to draw. Follows from the ask; ticking either layer restores it.
- A raining vehicle hovered in the sub-second window before the bridge's load resolves
  reads "no published band for this Cell"; the next tick corrects it.
