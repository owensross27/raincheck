# 11 — Detector core: the Window walk and live evaluation

**What to build:** The live detector as pure functions — the stateless backward Window walk, the live
evaluation producing within-kind ranks and latched tiers, the winter gate, and the detector
constants artifact — everything the panel will call, testable entirely on fixtures with no
network and no live table. Spec: Real-time detector; Testing seam 2.

**Blocked by:** 10

**Status:** ready-for-agent

- [ ] the detector IS the exposure model evaluated live — it loads ticket 10's coefficient JSON; no second model, no refit
- [ ] forcing is the pipeline's live precip table at MRMS RadarOnly :00 stamps ONLY — the 2-min trailing stamps are rejected inputs (they converge from above and would break the converges-from-below contract), and Pass2 (60–90 min lag) never feeds the live path; a fixture asserts the stamp filter
- [ ] stateless backward walk each cycle: anchor = the most recent 21:00 America/New_York boundary (UTC-pinned hour_ends, DST resolved from the NY-local date) whose three preceding pad hours are citywide dry (wet-cell count below frozen K at ≥ 1.0 mm — never a citywide max), else walk back a day, hard cap 6 days (window_capped); missing pad stamps → INSUFFICIENT_DATA: hold, degrade, never silently reset or latch
- [ ] features over [anchor, now]: running max mm_1h and Window total; antecedent mm_24h frozen at the anchor, persisted with its own coverage fraction; NULL hours count as missing, never zero; Window coverage (present/expected stamps) tracked over the Window and the antecedent block; HOLES is a state distinct from staleness
- [ ] evaluation: live eta per score Unit; display value = within-kind rank across the CURRENT eta vector; the score_ref CDF percentile is the STATIC view only (dormant weather); entrances never publish an independent live number
- [ ] tiers, provisional until ticket 12's replay: ELEVATED = top 10% within kind, HIGH = top 2%; gates latched within a Window: own-Cell Window total ≥ 2.0 mm AND citywide Window active; a downward series revision is logged and never clears a flag; flags dim when citywide wet-cell count has been below K for 3+ hours ("rain ended Xh ago") and clear at Window roll
- [ ] winter gate as a pure function of a supplied temperature: at or below 0.5 °C the tiers suppress and the model tier is labelled "fitted on rain — snow not modeled" (the per-cycle Central Park fetch itself lives in ticket 14)
- [ ] the detector constants JSON (second in-repo artifact): window rule, cutpoints, gates, staleness budgets, vocabularies (including ticket 02's remove-water family), query strings, UGC zone list, winter gate, canary patterns; detector_version = sha1 of the file; loading both JSONs stamps BOTH digests; version skew refuses the model tier; a coefficient swap mid-Window forces a Window roll
- [ ] the MRMS filename-pattern canary runs at build against the live source and fails the build if the pattern stops resolving (this ticket owns the canary patterns constant)
- [ ] fixture tests (seam 2): the Window rule reproduces the offline window on a fixture event day; deleting one interior hour trips HOLES/INSUFFICIENT_DATA; live eta at Window close equals the offline event eta on a replayed fixture event (the converges-from-below contract as an assert)
- [ ] Window and Tier graduate to CONTEXT.md's glossary
