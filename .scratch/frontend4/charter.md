# frontend4 — the interactive pass: streets, hover, and a rain-conditioned fleet

Status: chartered 2026-08-27 (Ross, live session on the freshly-lit map). This file is
the INPUT to `/to-spec` — it is the ask plus the load-bearing facts a spec session would
otherwise re-derive. It is not the spec.

## The ask, in Ross's words (paraphrased tight)

1. **More streets.** The basemap is "kind of high-level streets"; he wants real street
   density and street names as you zoom, so the flood/impact layers sit on a city you can
   read.
2. **Hover labels, not just click-cards.** Flood history markers (and the other point
   layers) should label themselves on hover/highlight — name + count — with the record
   card staying on click.
3. **Interact with the live fleet, and color it by "probably slow right now."** Hover a
   bus: what route, how fast is it probably going, is it likely late — from the PAST
   (dry same-hour baselines, wet ratios) crossed with CURRENT rain.
4. (His "ungate" item from the same message was already done this session — see Context.)

## Load-bearing facts (verified 2026-08-27, this session)

- **The MTA gate is OPEN and everything is published.** `LIVE_TERMS_VERIFIED` carries the
  receipt (docs/adr/0003); master `7b3ec8c` pushed; all 12 families on the host
  (history/showcase finished by `open-the-taps.sh`, which ends with an edge purge). If a
  layer still LOOKS gated, it is edge cache — never re-add a gate.
- **The pods still run the closed gate** baked into image pin `3871c6aa699a`. The ops
  tail this effort should carry: image re-pin (`scripts/cloud-image.sh` + rollout), then
  the 08-31 cutover revives capture -> `raincheck-stream` to 1 -> unpause daily; the 30 s
  cadences move to the cluster and the Mac one-shots stop being the data.
- **F1 is a style edit, not a data project.** `tiles/nyc.pmtiles` (52 MB OSM) already
  contains every street; `web/vendor/basemap-dark.json` decides what draws and when.
  Denser roads = minzoom/filter changes on road layers + road-name symbol layers. The
  same pass should fix the recorded orientation gap: the style's neighbourhood/locality
  place labels render BELOW every data layer (basemap.js splices data on top) — raise
  label symbol layers above the fills. Watch the glyph budget: only
  `vendor/notosans-0-255.pbf` is vendored; names outside that range need more ranges
  added to `make vendor` (sha-pinned, licence-checked).
- **F2 has machinery to reuse.** The cells tooltip (mousemove + click for touch) already
  exists in the page; `files/history/manifest.geojson` points carry `name` (ABSENT on
  cells — render the asset_id then) and `n_events`. Subway impact dots carry names + rel;
  MTA alert dots carry complex names. No new data needed.
- **F3 is a join the contract already prepared.** `files/live.geojson` vehicles carry
  `cell` — lower-hex, THE SAME SPELLING `files/cells.geojson` keys on — plus `mm_1h`,
  `next_stop_id`, `pred_next_s`. So expected-condition coloring is a client-side dict
  lookup: vehicle.cell -> the cell's published wet/dry ratio band; current rain from the
  vehicle's own `mm_1h` (or flood.json's raining set). CAVEAT THAT GATES THE DESIGN:
  in `--source bronze` mode the exporter NULLs `cell`/`mm_1h`/`precip_valid_ts`
  (src/raincheck/live_export.py:135); they are real only on the `live` (stream) path.
  Options the spec must decide: (a) compute cell+rain in bronze mode too (exporter has
  lon/lat; smallest diff, works before the stream revives), or (b) ship neutral coloring
  until the stream is back. Prefer (a).
- **Claim discipline is frozen project culture.** The coloring is DESCRIPTIVE: "buses in
  this cell ran at 0.72-0.82x their dry same-hour speed in rain like this" — never "this
  bus is late because of rain." Caveats ride in `strings` and get RENDERED, not
  restated. A cell with no published ratio (interval too wide / no baseline) colors
  neutral-grey, never fabricated. Dry hour -> neutral or delay-only coloring, spec's call.
- **Interval honesty:** the per-cell ratios are the 2021+2023 capture-window estimand
  with a width gate; per-cell colour is a preview until the 7-year backfill (Interline
  grant, hard date 2026-09-30). The hover copy should say the band, not a point number.

## Explicitly out of scope for frontend4

- The "rain now" animated layer (per-cell mm/h sweep off precip-live's 5-min CronJob) —
  chartered separately if Ross still wants it after this pass; the field-guide artifact's
  gaps section holds the sketch.
- Depth-graded flood rendering; layer-panel regrouping (recorded gaps, not this ask).

## Suggested next-session opener

    /to-spec frontend4 — read .scratch/frontend4/charter.md first, then spec the three
    features (basemap streets+labels, hover labels on point layers, live-fleet
    interactivity + rain-conditioned coloring) and the carried ops tail (image re-pin).
    /to-tickets, then /implement per the repo protocol (worktrees, own-module tests,
    one suite at the landing).
