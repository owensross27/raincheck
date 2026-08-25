# 11 — Detector core: the Window walk and live evaluation

**What to build:** The live detector as pure functions — the stateless backward Window walk, the live
evaluation producing within-kind ranks and latched tiers, the winter gate, and the detector
constants artifact — everything the panel will call, testable entirely on fixtures with no
network and no live table. Spec: Real-time detector; Testing seam 2.

**Blocked by:** 10

**Status:** DONE (2026-08-25, branch `flood11-detector-core`)

- [x] the detector IS the exposure model evaluated live — it loads ticket 10's coefficient JSON; no second model, no refit
- [x] forcing is the pipeline's live precip table at MRMS RadarOnly :00 stamps ONLY — the 2-min trailing stamps are rejected inputs (they converge from above and would break the converges-from-below contract), and Pass2 (60–90 min lag) never feeds the live path; a fixture asserts the stamp filter
- [x] stateless backward walk each cycle: anchor = the most recent 21:00 America/New_York boundary (UTC-pinned hour_ends, DST resolved from the NY-local date) whose three preceding pad hours are citywide dry (wet-cell count below frozen K at ≥ 1.0 mm — never a citywide max), else walk back a day, hard cap 6 days (window_capped); missing pad stamps → INSUFFICIENT_DATA: hold, degrade, never silently reset or latch
- [x] features over [anchor, now]: running max mm_1h and Window total; antecedent mm_24h frozen at the anchor, persisted with its own coverage fraction; NULL hours count as missing, never zero; Window coverage (present/expected stamps) tracked over the Window and the antecedent block; HOLES is a state distinct from staleness
- [x] evaluation: live eta per score Unit; display value = within-kind rank across the CURRENT eta vector; the score_ref CDF percentile is the STATIC view only (dormant weather); entrances never publish an independent live number
- [x] tiers, provisional until ticket 12's replay: ELEVATED = top 10% within kind, HIGH = top 2%; gates latched within a Window: own-Cell Window total ≥ 2.0 mm AND citywide Window active; a downward series revision is logged and never clears a flag; flags dim when citywide wet-cell count has been below K for 3+ hours ("rain ended Xh ago") and clear at Window roll
- [x] winter gate as a pure function of a supplied temperature: at or below 0.5 °C the tiers suppress and the model tier is labelled "fitted on rain — snow not modeled" (the per-cycle Central Park fetch itself lives in ticket 14)
- [x] the detector constants JSON (second in-repo artifact): window rule, cutpoints, gates, staleness budgets, vocabularies (including ticket 02's remove-water family), query strings, UGC zone list, winter gate, canary patterns; detector_version = sha1 of the file; loading both JSONs stamps BOTH digests; version skew refuses the model tier; a coefficient swap mid-Window forces a Window roll
- [x] the MRMS filename-pattern canary runs at build against the live source and fails the build if the pattern stops resolving (this ticket owns the canary patterns constant)
- [x] fixture tests (seam 2): the Window rule reproduces the offline window on a fixture event day; deleting one interior hour trips HOLES/INSUFFICIENT_DATA; live eta at Window close equals the offline event eta on a replayed fixture event (the converges-from-below contract as an assert)
- [x] Window and Tier graduate to CONTEXT.md's glossary


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


## What this ticket built and SETTLED (2026-08-25, branch `flood11-detector-core`)

`src/raincheck/flood_detect.py` — pure functions, no socket outside the build canary, no live
table read. `research/flood-11-detector.json` — the constants artifact.
`tests/test_flood_detect.py` +78, fixture `tests/fixtures/flood_detect_ida.json` (verbatim
real AORC rows for events 2021-09-01 and 2023-04-30). `make flood-detector`
(`SKIP_CANARY=1` offline). `CONTEXT.md` gained **Window** and **Tier**.

**The call surface tickets 12, 15 and notify 08 use** (`from raincheck import flood_detect as fd`):

    fd.DETECTOR                                   # research/flood-11-detector.json
    fd.constants()                     -> dict    # the rule book; one file, one call
    fd.detector_version(c)             -> str     # sha1 over fd.DIGESTED only
    fd.accepts(name)                   -> bool    # the MRMS RadarOnly :00 stamp filter
    fd.wet_counts(cell_hours)          -> {hour_end: int}          # citywide, a COUNT
    fd.walk(now, wet_by_hour)          -> {anchor, state, walked_days, pad, missing_pad}
    fd.window_features(cell_hours, anchor, now)
                                       -> {cells:{cell:{max_mm_1h,total_mm,
                                            antecedent_mm_24h,window_hours,antecedent_hours,
                                            window_coverage,antecedent_coverage}},
                                           coverage, unforced_cells, state, ...}
    fd.precip_terms(cell)              -> the three log1p terms
    fd.evaluate(art, units, feats)     -> [{asset_id,kind,cell,eta,rank}]
    fd.tiers(scored, feats, citywide_active) / fd.latch(prev, cur) / fd.revisions(prev, feats)
    fd.winter_gate(temp_c, now, stale) -> {suppressed, basis, temp_c, label}
    fd.staleness(newest, now) / fd.skew(art, table_score_version) / fd.rolled(...)
    fd.cycle(state, now, cell_hours, units, art, det, temp_c=, temp_stale=,
             table_score_version=, wet_by_hour=)   -> one whole detector read

`cycle`'s return value IS the `state` argument of the next cycle. `units` rows carry
`asset_id, kind, cell` plus, for point kinds, `elev_ft, relief_ft, stormwater_cat`, and for
`cell`, the four cell-model terms; `entrance` rows carry `complex_id` and publish NO row —
the registry's own `complex` row takes the max over its doorways, exactly as flood 10's build
does, and its gating Cell is the SCORING DOORWAY's so the score and the rain gate describe
one doorway.

**Verified against the real root, not asserted:** the live Window's three precip terms
reproduce `gold/flood_matrix`'s Ida row for **all 1,351 `fit_cell` Cells with ZERO mismatches
at 1e-6**; live eta at Window close equals the offline event eta to **2.3e-8** across those
Cells; eta never falls as the Window grows. A mutation round of 18 contracts is 18/18 RED.

### SETTLED — the NWS staleness budget (this ticket owned it)

**The spec's 15 min belongs to the per-cycle NWS ALERTS call, not to the KNYC observation.**
KNYC reports HOURLY at :51 (flood 14 measured 24 consecutive observations), so at 15 min
every observation reads stale and the winter gate could never fire. The observation budget is
**120 min = two report intervals** — one missed hourly report degrades nothing, two do.
`staleness_budgets.nws_knyc_obs_min` publishes it, `nws_alerts_min` = 15 sits beside it, and
a test asserts `flood_live.KNYC_STALE_MIN` and the artifact are ONE constant. flood 14's
"CONFLICT, recorded rather than silently resolved" comment is retired in the same commit.

### SETTLED — the scale band is NOT applied, and the reason is not deference

`scale_band.pass2_over_aorc` = [0.86, 0.92] was measured on MRMS **Pass2**. The live forcing
is MRMS **RadarOnly**, a different product whose bias against AORC nobody here has measured,
so dividing by that band would apply a correction fitted to the wrong product. Display is
**rank-only**; the one absolute gate (own-Cell Window total >= 2.0 mm) reads the RAW total,
where a low bias makes it strictly CONSERVATIVE — a Cell needs marginally more true rain to
raise a flag. **The RadarOnly-vs-AORC ratio is UNMEASURED and is owed to ticket 12's replay**,
which has both sides in hand.

### MEASURED — the frozen K is 5 wet Cells of 4,113, and the measurement is the argument

K has three jobs that pull opposite ways (it picks the anchor, it arms the citywide-active
gate, it dims a flag) and only one is sensitive to it. Over the whole **90,888-hour AORC
record only 1,540 hours (1.7%) hold between 1 and 41 wet Cells at all** — the distribution is
bimodal, 88% of hours have zero. So the anchor walk barely notices K: of **166 AORC-era
events with citywide rain the walk lands on the offline `window_start` for 88 at K=5 and 89
at K=41**. The citywide GATE does notice — 41 Cells is ~12 km2, enough to miss a convective
core dumping 50 mm on one neighbourhood, which is the flash-flood case. So K is small.
Measured MRMS speckle floor: **zero** hours in the 1-4 wet-Cell band across 744 batch hours
and 86 live hours, so K=5 sits above it with room.

### CORRECTED — the live walk does NOT reproduce the offline window in general (ticket 12)

The checklist says "reproduces the offline window on a fixture event day", and it does:
2021-09-01 evaluated mid-storm lands exactly on `window_start`. **Population-wide it agrees
on 89 of 166 AORC-era events (54%), and the usual disagreement is ONE DAY EARLIER (56 cases)
because the evening before the storm-eve was also wet.** That is the rule working — the live
anchor is observation-derived and the offline window is a calendar fact — but a replay that
expects agreement will read it as a defect. Distribution: -1 d 56 · -2 d 4 · -3 d 3 ·
0 d 89 · +1 d 10 · +2 d 1 · insufficient 3.

### CORRECTED — `detector_version` is NOT sha1 of the file

The checklist says "sha1 of the file". Shipped instead: sha1 over `fd.DIGESTED` — the eleven
keys that decide WHICH Units are flagged and WHEN — and deliberately not over `display` or
the `_note` prose, published as `detector_version_scope` so the claim can be audited. Reason
is TRAPS' rule, which names this stamp by name: hashing the file wholesale means a reworded
sentence rolls a live Window. Its limit is stated in the artifact: it hashes VALUES, so this
module's own code rides only as labels.

### DEFERRED with a reason — `nws_ugc_zones` is null, not invented

No NWS-alert fetch exists in this repo (13 is FloodNet+MTA, 14 is coastal+winter), the five
NYC zone codes are written down nowhere here, and inventing them would be a canary that can
never fail. The key is present and null with `nws_ugc_zones_note` naming the obligation: the
ticket that first fetches api.weather.gov alerts verifies them against the live API.

### Two things a later session would otherwise get wrong

- **AORC has 168 permanently dark Cells of 4,113** (every hour of 2021-09 has exactly 3,945
  non-null). A Cell with no value anywhere is UNFORCED and is left out of the coverage
  denominator; counting it as a hole makes every offline replay report HOLES forever. Live
  MRMS has all 4,113.
- **`cycle(wet_by_hour=...)` exists because "citywide" means the whole grid.** Defaulting it
  off `cell_hours` is right in production and wrong the moment a replay passes a SUBSET of
  Cells, which would silently redefine citywide as "these Cells".


### CORRECTED BY AN ADVERSARIAL REVIEW (same day, `d5e11f3`) — read this over the section above

Six lenses raised nine findings and a skeptic pass refuted all nine. **Four were fixed
anyway, on their own merits, and two of them change the interface written above.**

1. **`detector_version` is `01197991471f`, not the `91598b86edc0` the first build printed.**
   The scoping rule is about LEAVES, not top-level keys: `display` and `*_note` were excluded
   BY NAME while `cutpoints.basis`, `cutpoints.confirmed_by`, `forcing.stamp` and
   `canary.checks` sat as pure prose INSIDE digested dicts — so fixing a typo in one of them
   moved the digest, which `rolled()` turns into a Window roll and which clears every latched
   flag mid-storm. **All human-facing strings now live under `display`** (which is not
   digested): `display.tiers`, `display.cutpoint_basis`, `display.cutpoints_confirmed_by`,
   `display.window_interval`, `display.window_states`, `display.precip_states`,
   `display.forcing_stamp`, `display.winter_label`, `display.winter_unknown_label`, beside
   the existing `display.tier_labels` / `no_complex_skill_claim` / `within_cell`. So
   `cutpoints` is now `{ELEVATED, HIGH, provisional}`, `window` drops `interval`/`states`,
   `winter` is `{freeze_c, unknown_fallback_months}`, `forcing` drops `stamp`, `vocabularies`
   drops the two state lists and `canary` is `{pattern, product}`.
   `test_the_digested_leaves_are_frozen` pins all **72** digested leaf paths, so adding a
   field inside a digested dict is a deliberate act.
2. **`cycle()` emits H3 Cell ids as HEX, and that is the whole point of `cycle` being the
   boundary.** `fd.hexcell(cell) == format(cell, "x")`, the same spelling `ref.py` writes into
   `cell:<h3>`. Every `units[].cell`, every `revisions[].cell` and every `cell_totals` KEY is
   a hex string; `state["cell_totals"]` is read back as hex. **The lower seams
   (`window_features`, `evaluate`, `tiers`, `latch`, `revisions`) keep the int64** because
   they join on it. An H3 id is past 2^53 and JSON cannot carry one.
3. **A Window with no elapsed hours reported `HOLES` / coverage 0.0.** Nothing is missing when
   nothing is expected, and a Window opens at 21:00 NY, so this painted the degrade state over
   every cycle in the first hour of every Window, nightly. Now `OK` / 1.0. (The skeptic argued
   HOLES is the safer label for an unobserved interval; recorded as a disagreement, not a
   consensus — "not yet due" is what `staleness` reports, and `coverage` should mean what it
   says.)
4. **The budget pins were mirror-pins.** `assert artifact_budget == fl.KNYC_STALE_MIN`
   compares the artifact to the module it was built FROM, so it passes whether the value is
   derived or hard-coded at the same number. A monkeypatch test now MOVES `flood_live`'s and
   `flood_truth`'s constants and asserts the artifact follows.

The five findings left unfixed were prose-substring test assertions and one docstring
wording; each was refuted with reasoning I checked and agree with.

**Test count 84. Mutation rounds: 18/18 RED on the first pass, plus 4/4 RED on the review
fixes, pristine control green both times.**
