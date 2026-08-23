# 14 — Truth tiers: coastal gauges and the winter-gate fetch

**What to build:** The coastal live tier — three tide gauges observed and forecast against the same frozen
threshold family as the static layer — and the Central Park observation fetch the winter gate
reads. Spec: Real-time detector (coastal live, winter gate); Testing seam 2.

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] the three gauges' 6-min observations read in NAVD88 directly (labelled preliminary); margin computed against ticket 07's frozen threshold family (asserted equal — one constants family, two consumers); the Kings Point NWS/NOS inversion honored
- [ ] forecast: harmonic next high tides over a FORWARD window — begin_date + range in the query (a bare range parameter returns the PAST N hours); the exact query strings are frozen constants — plus a 30–60 min mean anomaly persisted only onto highs within 12 h
- [ ] chips: QUIET / APPROACHING (within 1.0 ft of minor) / EXCEEDING, next high tide with anomaly shown; gauge outage is its own chip state, never silence
- [ ] the data side of asset recoloring: Units assigned to an APPROACHING-or-worse gauge carry their static surge margin for the panel to recolor by (rendering lands in ticket 15)
- [ ] the winter-gate fetch: one Central Park (KNYC) observation per cycle from the frozen NWS endpoint, feeding ticket 11's pure winter-gate function; endpoints are frozen constants, not discovery (measured on wayfinder ticket 10: the /points endpoint 301-redirects on coordinate precision — follow redirects)
- [ ] parsers tested on captured fixture responses — no network in tests; a fixture asserting the forward-vs-past range semantics
