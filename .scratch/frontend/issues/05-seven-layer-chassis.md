# 05 — The seven-layer chassis: one page, honest toggles, five freshness states

**What to build:** the existing live map page becomes the seven-layer page the
spec describes, END TO END, with today's payloads: a viewer opens it and sees
ground zones + delay cells + headline rendering from the real files, a toggle
panel with one row per layer, per-SOURCE freshness chips speaking all five
states (FRESH / STALE+reason / OFF / GATED / AGE, ages computed reader-side
from `Date` − `Last-Modified`), the provenance strip always mounted with
layout driven off its measured height, and the four not-yet-landed sources
(fleet, FloodNet tier, MTA tier, impact) present as honestly OFF/GATED chips —
because rendering truthfully with layers dark is a design requirement, not a
degraded mode. This is the tracer bullet: every later slice only lights a
layer this chassis already declares.

**Blocked by:** None — can start immediately. (Spec: `.scratch/frontend/spec.md`;
the decisions it implements are tickets 01/02's Answers — read both.)

**Status:** ready-for-agent

- [ ] All twelve map layers declared at boot, empty + hidden; `promoteId` off
      everywhere; the layer order is the spec's, verbatim
- [ ] The Cell-fill RADIO exists with delay cells as its only lit option
      (impact joins in ticket 08); two fills at once is impossible, tested
- [ ] Freshness rows: one per source; only budget-frozen sources may say
      FRESH/STALE; unbudgeted sources say AGE; OFF collapses the row; GATED
      renders the chip hue, never absence — all five states mutation-checked
- [ ] The new hues + the hollow-ring dry-sensor mark are constants beside the
      frozen ramps; the ramps themselves are byte-untouched
- [ ] Toggling never destroys keyboard focus (reuse the page's existing
      focus-restore mechanism); verified by test, not by hand
- [ ] <= 900px opens fill-on/points-off; nothing positions against a guessed
      provenance height (the hit-test failure from the prototype cannot recur)
- [ ] The lineage-gate KEYS exist (two gate sides) even while both sides are
      dark, so ticket 08 lights them without re-plumbing
- [ ] Existing page tests stay green; new claims pinned in the same
      page-as-data seam; own-module tests only
