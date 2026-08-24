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


## Inherited from flood 10's build (2026-08-24, branch `flood10-exposure-artifact`)

THE coefficient JSON exists. It is a READ; there is no second model and nothing is refitted.

    from raincheck import flood_exposure as fe
    art = fe.coefficients()                      # research/flood-10-coefficients.json
    fe.COEFFICIENTS                              # the Path, if you need to digest the file
    fe.eta(art["models"][role], feats) -> float  # THE score, offline and live

- **`eta()` is the function that built `gold/flood_exposure`.** Call it with your live precip
  terms in `feats` and the offline and live numbers cannot drift apart. It is a plain dot
  product of `coef_raw` plus `intercept_raw`, and it RAISES `KeyError` on a missing feature
  rather than scoring it as zero — a silently absent term is a different model wearing a
  plausible number. Verified on the real root: all 13,310 model-scored bus stops and all 445
  complexes reproduce to 1e-12 from the JSON alone.
- **A score is the LINEAR PREDICTOR (eta), NOT a probability** (`art["score"]["is_probability"]`
  is `false`). Do not sigmoid it: your tiers are a within-kind rank, the spec keeps
  probabilities in the validation tables, and a squashed score would invite a calibration
  claim the evidence does not support.
- **Key shape** (every key is present; `art` is a plain dict from one `json.loads`):
  `estimand` (`flooded_reported`) · `score_version` · `identities`
  {`label_version`, `features_version`, `precip_identity`, `matrix_version`, `fits_version`} ·
  `gate` {`branch`, `shipped`, `split`, `panel_strings`} · `score` · `kind_model`
  {`bus_stop`->`point`, `complex`->`point`, `cell`->`cell`} · `complex_rule` ·
  `models.<role>` {`model_id`, `features`, `coef_raw`, `intercept_raw`, `coef_standardized`,
  `intercept_standardized`, `standardization`, `stormwater_base_level`, `lambda`} ·
  `preprocessing` · `reference_forcings.<role>.<score_ref|score_severe>.<log1p|mm>` ·
  `cdf` {`score`, `by_kind.<kind>` = {`n`, `percentile`[101], `score_ref`[101]}} ·
  `scale_band` · `flags` · `table`.
- **THE score_version RULE, for your version-skew refusal.** `art["score_version"]` is the
  same string stamped on every row of `gold/flood_exposure` and in its parquet footer
  (`b"score_version"`); compare against the table you read, not against a remembered value.
  It is sha1 over exactly what can MOVE A PUBLISHED SCORE: the four upstream identities, the
  per-role model constants (`model_id`, `features`, `coef_raw`, `intercept_raw`,
  `stormwater_base_level`), the reference forcings, `kind_model`, the stormwater level ->
  coefficient encoding, the kind indicator, the complex rule and the fallback rule.
  **Deliberately NOT in it: the flag vocabulary, the assertion scope and the scale band** —
  a reworded flag must never make the live model tier refuse itself. So: a changed digest
  always means a changed score, which is what makes refusing on skew honest.
  **Its real limit, stated so you do not over-trust it:** it hashes VALUES, so flood 10's own
  code (its SQL aggregation, its argmax) rides only as labels — editing that code moves a
  score without moving the digest. The stamp catches upstream and parameter drift; it is not
  a checksum of the builder, and the same is true of any `detector_version` you compute the
  same way.
- **`stormwater_base_level` is `analyzed-none` and gets NO term.** Use `fe.dummies(kind, cat)`
  rather than rebuilding the dummy coding; it raises on an unknown category, because
  stormwater is never imputed. If you would rather read it out of the artifact than import
  the module, `preprocessing.stormwater_dummy` publishes the level -> coefficient-name map
  and `preprocessing.kind_indicator` publishes {feature, one_when_kind_is} — neither is
  derivable from spelling, and a test replays a POINT score and the complex rollup out of
  the artifact alone to prove they are enough. If you would rather read it out of the artifact than import
  the module, `preprocessing.stormwater_dummy` publishes the level -> coefficient-name map
  and `preprocessing.kind_indicator` publishes {feature, one_when_kind_is} — neither is
  derivable from spelling, and a test replays a POINT score out of the artifact alone to
  prove they are enough.
- **The precip terms are log1p.** `reference_forcings` publishes both scales;
  `preprocessing.precip_note` says it in the file. `expm1` before quoting mm, never log1p
  twice — a build-time check refuses a JSON where the two scales disagree.
- **`scale_band.pass2_over_aorc` = [0.86, 0.92] is INFORMATIONAL and no code applies it.**
  The fit is AORC-only and your live forcing is MRMS RadarOnly, which runs 8-14% low against
  it. That is a decision this ticket owns: either divide your live mm_1h by the band and
  render a tier only where both ends agree, or ship rank-only. Do not threshold an unadjusted
  biased input behind a footer.
- **`cdf.by_kind.<kind>` is the STATIC view only** — 101 percentile knots of the published
  `score_ref`, the same distribution `gold/flood_exposure.score_index` reports (asserted equal
  to `cume_dist()` over all 15,166 rows). Fed a LIVE eta it reads ~0 in light rain and ties at
  the ceiling in a storm, which is exactly why your display value is the current-vector rank.
- **NO COMPLEX-GRAIN SKILL CLAIM.** `complex_rule` says what it is — max over child entrance
  scores, an aggregate of doorway scores — and the artifact publishes no metric of any grain
  at all (asserted: no metric FIELD anywhere in it; the one metric it QUOTES, in
  `complex_rule.evidence`, is that null result stated as the disclaimer). Entrances
  publish no row of their own in `gold/flood_exposure`; only the three Unit kinds do.
- **`gate.panel_strings` is already selected** by the re-evaluated branch (MODEL). Read it;
  do not re-derive the branch and never re-type the verdict — `flood_fits.gate(summary)` is
  the pure function, and this build refuses a fits asset whose stored verdict disagrees with
  its own tables.
