# 02 — Prototype: how do four layers read together on one map?

Type: prototype
Status: open
Blocked by: 01

## The question

Talking cannot settle how vehicles + delay-cells + flood tiers/stations +
history popovers LOOK together — layer order, color collisions (delay ramp vs
flood tier ramp on the same geography), what a station "affected" marker is,
how a popover shows a stop's flood record without burying the live view. Build
2-3 throwaway variations against REAL payloads that already exist in
`web/files/` (fleet GeoJSON, cells/headline/zones) plus FIXTURE tiers/history
shaped like flood 15's and notify 02's real payload schemas (both are frozen —
copy shapes verbatim, never invent fields; stub-fidelity is a standing rule).

HITL: **the selection between variations is Ross's, not the agent's** — the
wayfinder doc records agents closing prototype tickets by picking their own
variant as a known failure. Present, then stop.

## Resolution shape

The chosen variation linked from this ticket as an asset (throwaway code stays
throwaway), the layer/color/interaction decisions recorded under ## Answer, one
line on the map. The prototype is NOT the implementation.
