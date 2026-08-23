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

## Domain fact from flood-02 (2026-08-23, recorded by the orchestrator)

alert_id is NOT a stable text key: MTA revises (header, description) in place under one
alert_id (14/24 water ids multi-variant, 50 revisions measured). The MTA tier's "one chip
per incident" dedupe and active-vs-cleared phrasing check must therefore read the NEWEST
revision's text per incident, and expect the text (including the while/after phrasing) to
change under an unchanged alert_id between cycles.

## Inherit from flood-02's landing (2026-08-23, recorded by the orchestrator)

- `state` for a chip = the newest revision of that (event, complex), via flood-02's
  frozen constants (REVISION_KEY / INCIDENT_KEY / OBSERVATION_KEY in flood_alerts.py).
- Events can disagree about a shared complex (264048 active on Utica Av vs 264063
  cleared); render per-event truthfully — reconciling across events is ticket 04's job,
  not this tier's.
- Known extractor debt recorded on ticket 02: BRIDGE_FWD's connector alternation has no
  AT branch (the real cause of the B1 recall miss — the prototype README's explanation is
  wrong), BRIDGE_BACK fullmatches zero live/holdout rows, and the live measurement rests
  on one storm night with 5 distinct station names. Treat live recall claims accordingly.
