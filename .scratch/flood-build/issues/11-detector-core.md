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


## Inherited from flood 18's build (2026-08-24, `research/flood-18-replication.json`)

**The 2026 sensitivity story is settled and it has one shape: the headline is ROBUST to the
311 threshold and SENSITIVE to the label radius — and the raw CSI ranks the radius
BACKWARDS.** Four alternate universes were rebuilt end to end (04 -> 05 -> 06 -> 08 -> 09)
at 311 quantiles {0.975, 0.995} and label radii {50, 200} m around the frozen primary. Every
one re-fired the gate as **MODEL**, so nothing below changes which model ships.

- **311 threshold — mild.** +-2.5 percentiles of the daily-count distribution moves point CSI
  by at most 0.0010 (0.0300 / **0.0310** / 0.0312 at q0.975 / q0.99 / q0.995) and cell CSI
  by at most 0.0068. The event count moves a lot (243 / **206** / 196 events) and the
  headline barely does.
- **Label radius — the sensitive knob, and the trap.** Raw point CSI runs 0.0237 (50 m) /
  **0.0310 (primary, 100 m)** / 0.0667 (200 m), which reads as "wider is twice as good".
  Divided by each universe's OWN B0 — under location blocking B0 IS the base rate, B2 having
  degenerated onto it — the lift runs **11.13x / 6.05x / 4.42x**: the widest radius has the
  highest raw CSI and the LOWEST skill. 200 m nearly triples the point base rate (0.00512 ->
  0.01509; positives 4,008 -> 11,818) because a 200 m circle round a doorway catches 311
  reports from the next street. **The radius moves what "flooded" MEANS at point grain, not
  how well the model finds it.**
- **Never compare a CSI across universes without dividing by that universe's own base rate.**
  This is the same monotone-in-alert-rate trap flood 09 had to correct in fold, one level up.
  Any table you publish that ranks alternatives on raw CSI ranks them backwards.
- **The radius is structurally INERT at Cell grain** (the cell branch attaches on
  `a.cell = oe.cell`, no distance predicate): both radius universes' `fit_cell` rows are
  BYTE-IDENTICAL to the primary's, cell CSI 0.1591 to four decimals. Verified, not assumed —
  two real-root tests pin it, and their `fit_point` positives demonstrably move.
- The primary is UNTOUCHED: `research/flood-09-fits.json` still stands at `fits_version`
  **8050dfa41fc1** over `matrix_version` **8bc1e8912b1b**, point CSI 0.0310, cell 0.1591.
  No number in flood 09's asset is superseded by this ticket.

**What this means for YOUR tiers.** Your provisional cutpoints (top 10% / top 2% within kind)
are a RANK, so they are unaffected by the base-rate moves above — that is a point in the
rank's favour and worth saying when ticket 12 weighs rank-only against calibrated tiers. But
the point model's skill is a function of a labelling choice (100 m) that the evidence does
not single out as optimal: 50 m scores better per unit of base rate and 200 m worse, and
neither is "the right radius", they are different questions. Do NOT present the point tier as
resting on a validated distance; the estimand is `flooded_reported` within 100 m of a report.
