# 04 — Area queries: assets_in_area and obs_near

**What to build:** Ask what flooded inside an area without knowing an asset id, and ask
what was observed near a point. Cell is the only area key; Zone stays a presentation
overlay. Spec: sections 2 and 4; CONTEXT.md (Cell, Zone); SEAM Q.

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] `assets_in_area` takes Cell ids, or a bbox resolved to a Cell set before anything is read — Cell is the only area key
- [ ] Zone resolves through the static Cell-to-Zone lookup at serving time and appears in no stored key and no query parameter
- [ ] a request resolving past the stated Cell cap returns `area_too_large` naming the cap, so a tool call cannot accidentally ask for the city
- [ ] `obs_near` returns observations within a radius of a point and is `local` mode only; calling it in `public` returns `restricted_source`
- [ ] no query accepts an arbitrary polygon — a caller with one resolves it to Cells itself
- [ ] area answers carry the same version stamps as every other payload
