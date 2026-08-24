# 03 — exposure_of and the Unit/Carrier rule

**What to build:** Ask how exposed a doorway is and get the published exposure object back
— with the Unit/Carrier distinction enforced, so nobody can ask a station for a score it
does not have. Spec: section 1 (complex grain); CONTEXT.md (Unit, Carrier); SEAM Q.

**Blocked by:** 02 — externally on flood-build 10 (`gold/flood_exposure`).

**Status:** ready-for-agent

- [ ] `exposure_of` returns score_ref, score_severe, score_index, surge_margin_ft and flags for a Unit, stamped with model_id / score_version
- [ ] a complex's answer is the max over its child entrances, matching F10's rule exactly
- [ ] a station returns `not_a_scored_unit` naming the complex to ask instead — stations are Carriers and are never scored independently
- [ ] a bus_stop and a Cell each answer directly
- [ ] no NULL score reaches a payload: F10's fallbacks guarantee coverage and reasons ride the flags
- [ ] the per-asset payload composes with 02's history — one asset, one answer, both stamped
