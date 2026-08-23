# 13 — Truth tiers: FloodNet sensors and MTA alerts

**What to build:** The two reported/measured truth tiers that never feed the model: FloodNet water
detections under the rise-and-persistence rules (absolute depth is dead — standing offsets were
measured), and MTA "remove water" alert chips from the archiver's own capture. Spec: Real-time
detector (FloodNet tier, MTA alert tier); Testing seam 2.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] FloodNet fetch: ONE bounded query per cycle over [now − 60 min, now + 2 min] — unbounded reads are poisoned by a clock-broken sensor stamping year 2080; rows with null deployment_id are dropped
- [ ] water detected = latest depth ≥ 15 mm AND a ≥ 15 mm in-window rise AND ≥ 3 consecutive samples above AND recent onset — never absolute depth alone (18–528 mm standing offsets measured on a dry night); the sensor-status blacklist comes from daily-cached deployment metadata; concurrent own-Cell rain is a display gate
- [ ] dry-and-reporting sensors render dim as "dry above curb height at the signpost"; the tier shows the network's own caveats beside detections (snow and obstruction can register as depth); API errors grey the tier; the tier is display only — the FloodNet bar as model input stands
- [ ] the FloodNet citation renders with the tier ("FloodNet (NYU and CUNY)", Mydlarz et al. 2024, WRR — non-commercial agreement)
- [ ] MTA tier: the newest captured subway-alert rows each cycle, filtered by ticket 02's frozen LIVE vocabulary; one chip per incident via ticket 02's incident dedupe keys; first-seen time; active vs cleared from the "while"/"after" phrasing
- [ ] parsers tested on captured fixture responses — the 2080-clock response, the null-deployment response, a dry-night offsets response — no network in tests
