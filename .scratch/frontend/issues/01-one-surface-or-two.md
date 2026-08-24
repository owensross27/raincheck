# 01 — One surface or two: does the integrated map extend `web/` or stand beside it?

Type: grilling
Status: open
Blocked by: none

## The question

The live page (`web/index.html` + `app.js`) already renders the 30 s vehicle
fleet and the flood panel, with STALE semantics and the honesty string wired in.
The insight exports (cells/headline/zones) are separate payloads on their own
per-build cadence. Flood tiers/overlays (flood 15/17) and per-stop history
(notify 05) are coming as more layers. Does "one place to see everything" mean
ONE page that grows layer toggles — one clock panel, one honesty string, one
STALE model — or a second, denser page beside the live one?

Tensions to grill through (HITL — Ross speaks for the product):
- One page = one staleness/honesty model, but four cadences under one clock
  (30 s live, per-build insight, per-spine-rebuild history, per-run tiers) —
  the panel must say which layer is how old without lying (the frozen-age trap).
- The live layer is GATED (MTA terms) while every other layer is not; a single
  page must read honestly with its centerpiece dark.
- Payload weight: history popovers are per-asset fetches (median 746 B — cheap);
  cells.geojson and the fleet are the heavy layers.
- Whatever is chosen must not touch spec §9's constraints (current-snapshot-only
  live, no bulk endpoint, attribution on the page).

## Resolution shape

A decision recorded here (## Answer + Status: resolved + one line on the map's
Decisions so far), naming the surface, the layer list, and the staleness model
per layer. No code.
