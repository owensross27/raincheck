# 07 — Coastal rule layer: deterministic surge margins

**What to build:** Coastal exposure as arithmetic, not a model: every Unit's surge_margin_ft against its
assigned gauge's frozen threshold in one datum, shared verbatim with the detector — so storm-surge
risk is stated without pretending ~15 coastal events could fit a model. Spec: Exposure score
(coastal layer); Testing seam 2.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] surge_margin_ft = elevation − assigned gauge threshold, all NAVD88; assignment = geodesic nearest of {Battery, Kings Point, Sandy Hook}; per-station datum offsets applied; the Kings Point NWS/NOS threshold inversion is recorded where the constant is defined
- [ ] the threshold stage is frozen ONCE and shared with the detector's coastal tier — asserted equal at build (ticket 14 consumes the same constants)
- [ ] no fitted coastal terms anywhere; the Sandy inundation polygon validates the layer descriptively (a published table, not pytest)
- [ ] datum sanity pinned here, where elevations and thresholds first meet: the below-minor-flood entrance count reads 3 under NAVD88 discipline, not the naive STND-comparison 103
- [ ] unit tests on fixture elevations and a hand-checked margin
