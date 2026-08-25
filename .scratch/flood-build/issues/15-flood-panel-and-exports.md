# 15 — Flood panel and exports: the third section, honestly degraded

**What to build:** The flood tick inside the existing 30 s export loop and the panel section it feeds:
three export files, the static-to-live display switch, latched tier chips, the truth tiers beside
the model, every source aging independently, and the fixed claim strings — no new daemons
anywhere. Spec: Real-time detector (serving, claims, logging); Testing seam 3.

**Blocked by:** 11, 12, 13, 14 — and externally on the pipeline build: 11 (live-precip job, as amended with the catch-up fetch) and 13 (page skeleton + the pure-SQL JSON writer / merge-patch path). Explicitly NOT blocked by pipeline 12 (Kafka/streaming) — the spec ships the flood panel ahead of the bus live view: the flood tick joins pipeline 14's 30 s loop if it has landed, else stands the loop up itself with flood keys only and pipeline 14 merges its bus payload into the same process later

**Status:** ready-for-agent

- [ ] the flood tick joins the existing 30 s export loop: one process, one meta file whose flood keys the single writer merges, cycles cannot overlap; the tick skips work unless the newest precip stamp advanced or a truth-source throttle expired (FloodNet 120 s, CO-OPS 360 s, NWS 300 s); every fetch has a hard 3 s timeout; last-good values keep their own age; one hung socket never stalls the bus panel
- [ ] three export files — all Cells as geometry, point Units only at ELEVATED+, the truth payload — written through the same pure-SQL merge-patch path (absent keys, never nulls), payload-then-meta atomic replace, one cycle_id across the set
- [ ] staleness budgets from measured cadences: precip fresh ≤ 90 min from the stamp, stale to 180, down past 180, holes indicated separately; FloodNet 10 min; CO-OPS 30 min; NWS 15 min — every panel source shows its own age and error state
- [ ] the panel: static exposure view (score_index) in dormant weather; an active Window switches to the live within-kind rank; tier chips latched per ticket 12's recorded decision — if the replay dropped v1 to rank-only, the panel renders rank without tier chips and says so; INSUFFICIENT_DATA and HOLES render as their own states ("ranks computed on N of M rainfall hours"); winter-gate suppression with its label; per-kind legends never mix kinds; base rates worded as fit-era frequencies
- [ ] claims as fixed strings: headline "flood-report exposure rank" with the estimand `flooded_reported` named; the always-visible reporting-propensity sentence; the panel trails the storm; rank-only and uncalibrated in v1; the Window named in the tier label; the within-Cell note (live ordering inside a Cell is purely static); the frozen operating-truth string, verbatim and unedited — "raincheck ranks where a flood REPORT is likely from rain that has already fallen, on hour-grain evidence that trails the storm. A rank is not an observation of water, and a quiet panel or a quiet inbox means nothing was flagged, not that nothing flooded." (frozen by notify 01, 2026-08-23; it replaces the retired storm-page claim, which a notifier falsifies, and notify 09's render reuses these exact words so the panel and a message cannot contradict each other); the B2-branch alternate strings selected by the shipped model id
- [ ] version-skew between the coefficient and detector JSONs refuses the model tier with the reason rendered; truth tiers stay up
- [ ] logging: one NDJSON file per day — the full unit-state vector only when the model tier recomputes (~24/day), the flagged subset per cycle, truth snapshots on change; ~3 MB/day, ≤ ~100 MB under the 30-day prune-on-start, inside the data-root byte budget
- [ ] export-file seam tests: absent keys never nulls; one cycle_id across the set; a deleted live root yields error + stale meta, not a crash; skew refusal; tier chips render from file data alone

## Inherited from frontend 02 (prototype, `4ac3ebe`, 2026-08-24) — measured against YOUR code

Frontend 02 built three throwaway variations of the integrated map and, because your three
export files do not exist yet, painted the flood tiers from `flood_truth.truth()` itself
rather than invent a schema. Three things it measured land on this ticket:

- [ ] **Emit COORDINATES on the truth payload's MTA chip.** `flood_truth.chips()` returns
  `{event_id, stations[{complex_id, name, state}], alert_ids, first_seen, last_seen, state,
  age_min}` — nothing spatial — so a page cannot put an affected station on the map without
  a second lookup against `ref/assets`. Measured price of closing it here: **all 445
  complexes with lon/lat = 30,087 B raw**, against the 161,455 B `truth()` already returns.
  (`ref/assets` is the only source of a complex's lon/lat, and it is exactly the join a
  serving page should not have to do.)
- [ ] **Export the staleness budgets as CONSTANTS, not prose.** Only
  `flood_truth.MAX_AGE_MIN = 10` exists in `src/`; the precip 90/180 ladder, CO-OPS 30 min
  and NWS 15 min are frozen in the spec and in no code. The page renders a freshness row
  PER SOURCE off a per-layer TABLE (frontend 01, D2) and has to get those numbers from
  somewhere — so name them where the page can be pointed at them. Until then the page can
  only show a bare AGE with no FRESH/STALE verdict, which is what frontend 02 had to build:
  it added a fifth chip, **AGE** (age known, no budget frozen). Counted off the running
  page: the map has **9 sources**, the repo's two frozen constants cover **3** of them, and
  the other **6 are in that state**.
- [ ] **NAME your three export files and their keys in the close-out.** Both specs describe
  them in prose only ("all Cells as geometry; point Units only at ELEVATED+; the truth
  payload"); nothing in the tree freezes a filename or a field. You are free to choose — and
  you are the one who freezes it, because the map's layer table is written against them.

Nothing here changes the two-meta-file MUST inherited from frontend 01; it sits beside it.

## Inherited from flood 10's build (2026-08-24, branch `flood10-exposure-artifact`)

`gold/flood_exposure` and `research/flood-10-coefficients.json` both exist. Two things on
this ticket's list are now settled by measurement rather than left to the panel:

- **`score_index` is real and bounded (0, 1]** — the within-kind empirical CDF of `score_ref`,
  one row per Unit, 15,166 rows, NO NULLS. That is your dormant-weather static view. The
  matching CDF knots are published in the coefficient JSON under `cdf.by_kind.<kind>`, so the
  panel can place a score on the same curve without reading the Gold table.
- **A score is the LINEAR PREDICTOR, not a probability, and it is NEGATIVE for almost every
  Unit** (real-root ranges: bus_stop -7.39..-3.91, complex -6.54..-4.12, cell -5.27..+1.06).
  **Never render a raw score.** Render `score_index`, or the live rank. A raw eta on a panel
  reads as a broken number, and printing it would also be the calibration claim the honesty
  strings exist to prevent.
- **Your per-kind legends have a fourth thing to say: `flags`.** A closed vocabulary, never
  NULL, empty for 14,726 of 15,166 rows: `elev_ring15_fallback` (36) · `no_dem_footprint`
  (60 — outside the NYC DEM, scored at the kind median, NOT an imputed elevation) ·
  `no_matrix_row` (0 here) · `score_fallback_kind_median` (60) · `no_surge_margin` (404 —
  NULL margin, never a zero). Every flag's own one-line explanation ships in the coefficient
  JSON under `flags`, so the panel can label a fallback row from the artifact it already
  loads rather than inventing wording. **A fallback row must not be presented as a modelled
  rank**; it is the kind's median with a reason attached.
- **`surge_margin_ft` is NULL for 404 Units and that is data, not a hole.** 344 Cells have no
  point child (they are scored through a taxi Zone) and 60 bus stops have no elevation at all.
  Render the absence, never a zero.
- **NO COMPLEX-GRAIN SKILL CLAIM anywhere on the panel.** A complex's number is the MAX over
  its child entrance scores — an aggregate of doorway scores. The independent complex-grain
  set caught 1 of 118 positives, so the strings say what the number IS, never what it was
  proven to do. The coefficient JSON carries no performance metric of any grain (asserted).
- **Version skew (your bullet 17) has a concrete comparison now.** `score_version` is stamped
  on every row of `gold/flood_exposure`, in its parquet footer as `b"score_version"`, and at
  the top of the coefficient JSON. Compare the artifact against the TABLE you actually read.
  It moves only when a published score can move — a reworded flag or a changed scale-band note
  does not bump it, so a refusal means something real.
- **`gate.panel_strings` is pre-selected in the coefficient JSON** (branch MODEL: headline
  "modelled flood exposure", release "v1 ships the fitted L2 logistic exposure score", caveat
  "fitted on reported flooding, 2010-2025 rain events"). The B2-branch alternates in your
  bullet 16 are therefore NOT the live branch; read `gate.branch` rather than choosing.

## MUST from frontend 05 (the chassis landed 2026-08-25, `frontend05-seven-layer-chassis`)

The page now FETCHES your two gate-side files by name, because nothing here had frozen one
and a chassis cannot read a URL that does not exist. **These are the two names the live page
reads today; land them, or land different ones and correct this line, the page's `LAYERS`
table and its summary line in the same commit:**

- **`web/files/flood.json`** — the UNGATED side: the FloodNet tier and its own meta keys.
  Nothing MTA-derived may appear in this file; it is published on the open side of the
  lineage gate.
- **`web/files/flood-mta.json`** — the `mta-alerts` gate side: the alert-derived tier only.

This is the two-meta-file MUST inherited from frontend 01 made concrete, and it sits beside
the existing one rather than replacing it.

Two more the page's rendering depends on, both cheap if done at write time and a rewrite if not:

- **Every FloodNet sensor feature must carry a boolean `display`.** The map paints a
  water-now sensor as a filled aqua disc and a dry/stale one as a HOLLOW RING, and the
  MapLibre expression that does it reads exactly `["get", "display"]` (three meanings on one
  grey was the collision this fixes). A missing key paints every sensor as a ring.
- **The budget constants you owe are what let the page render a VERDICT.** Until a source
  carries a frozen budget the page renders a bare AGE and judges nothing — that is
  deliberate, and it is why guessing a threshold downstream is refused by a test that counts
  the budgeted sources. FloodNet's is already derived from `flood_truth.MAX_AGE_MIN`; the
  precip / CO-OPS / NWS budgets are yours.


## Inherited from flood 11's build (2026-08-25, branch `flood11-detector-core`)

The tiers you render come from `src/raincheck/flood_detect.py`; the strings, budgets and
vocabularies come from `research/flood-11-detector.json`. Read them, never re-type them.

    from raincheck import flood_detect as fd
    fd.DETECTOR                                   # research/flood-11-detector.json
    fd.constants()                     -> dict    # the rule book; one file, one call
    det["detector_version"]                       # sha1 over fd.DIGESTED, NOT of the file
    fd.walk(now, wet_by_hour)          -> {anchor, state, walked_days, pad, missing_pad}
    fd.window_features(cell_hours, anchor, now)   # {cells:{...}, coverage, unforced_cells, state}
    fd.evaluate(art, units, feats)     -> [{asset_id, kind, cell, eta, rank}]
    fd.tiers(scored, feats, citywide_active) / fd.latch(prev, cur) / fd.revisions(prev, feats)
    fd.winter_gate(temp_c, now, stale) -> {suppressed, basis, temp_c, label}
    fd.staleness(newest, now) / fd.skew(art, table_score_version) / fd.rolled(...)
    fd.cycle(state, now, cell_hours, units, art, det, temp_c=, temp_stale=,
             table_score_version=, wet_by_hour=)   # one whole read; its return IS next state

Artifact keys: `window` {anchor_local_hour 21, tz, pad_hours 3, cap_days 6,
antecedent_hours 24, wet_mm 1.0, **wet_cells_k 5**, interval "(anchor, now]", states} ·
`cutpoints` {ELEVATED 0.10, HIGH 0.02, tiers, basis, **provisional true**, confirmed_by} ·
`gates` {own_cell_window_mm 2.0, citywide_active, latched_within_window,
dim_after_dry_hours 3, downward_revision_clears_a_flag **false**,
entrances_publish_a_live_number **false**, complex_rule} · `winter` {freeze_c 0.5, label,
unknown_label, unknown_fallback_months} · `staleness_budgets` {precip_fresh_min 90,
precip_stale_min 180, floodnet_min, coops_min, **nws_knyc_obs_min 120**, **nws_alerts_min
15**, clock_ahead_min} · `throttles` · `forcing` {product, rejected_products, stamp, url,
name, retention_days, **scale_band_applied false**} · `vocabularies` · `query_strings` ·
`nws_ugc_zones` **null, owed** · `canary` · `display` · `detector_version_scope`.

**THE VERSION-SKEW RULE.** `fd.skew(art, table_score_version)` compares
`art["score_version"]` against the score_version of **the table you actually read** —
the column on every row of `gold/flood_exposure` and its parquet footer key
`b"score_version"` — never a constant. An ABSENT table stamp REFUSES; "I could not tell" is
not "they match". `fd.rolled(prev_state, anchor, score_version, detector_version)` rolls the
Window when the anchor moves OR either digest moves, which is how a coefficient swap
mid-Window cannot leave latched tiers standing that the running model never produced.

**THE SETTLED STALENESS BUDGET.** The spec's 15 min is the per-cycle NWS **ALERTS** budget,
not the KNYC observation's. KNYC reports HOURLY, so at 15 min the winter gate could never
fire. The observation budget is **120 min = two report intervals**, published as
`staleness_budgets.nws_knyc_obs_min` and asserted equal to `flood_live.KNYC_STALE_MIN`.

**WHAT YOU MUST RENDER AS DATA, not as absence.** `window.state` is one of `OK` / `HOLES` /
`INSUFFICIENT_DATA` / `WINDOW_CAPPED`; `staleness.state` is `FRESH` / `STALE` / `DOWN`.
**HOLES and staleness are different facts** — a holed Window is still a Window and its anchor
still stands — and both are different from `INSUFFICIENT_DATA`, which means there is no
Window at all. `dim.dimmed` is true after `gates.dim_after_dry_hours` (3) consecutive
citywide-dry hours and `dim.dry_hours` is the "rain ended Xh ago" number.

**THE TIERS ARE PROVISIONAL AND THE PANEL SAYS SO.** `fd.TIERS_PROVISIONAL` is the sentence;
`cutpoints.provisional` is `true` until flood 12's replay lands, and **flood 12's verdict is
[YOU]-Ross's to read**. Never render a tier as confirmed. `display.tier_labels` is the
vocabulary; `display.no_complex_skill_claim` and `display.within_cell` are the two
disclaimers that must ride with a complex row and with any two Units in one Cell.

**NEVER present the point tier as resting on a validated distance.** The estimand is
`flooded_reported` WITHIN 100 m of a report, and flood 18 measured the radius as NOT optimal
(lift per own base rate 11.13x at 50 m / 6.05x at 100 m / 4.42x at 200 m — the widest radius
has the highest raw CSI and the LOWEST skill). `estimand_note` in the artifact says it.

**A SCORE IS THE LINEAR PREDICTOR AND IS NEGATIVE FOR NEARLY EVERY UNIT** (bus_stop
-7.39..-3.91, complex -6.54..-4.12, cell -5.27..+1.06). Anything human-facing is the RANK
(`rank`, 0..1 within kind) or `score_index`, never a raw eta, and never a probability —
do not sigmoid it. `art["cdf"].by_kind` is the STATIC view for DORMANT weather only.

**THE MODEL TIER REFUSES ON SKEW, and the payload says so even when it produced nothing.**
`cycle()` stamps `score_version` AND `detector_version` on every return, including an
`INSUFFICIENT_DATA` one. `skew.model_tier` is `"ok"` or `"refused"` with a `reason` — render
the refusal, do not fall back to a stale number.

**FRESHNESS IS DATED AT THE READER.** `fd.staleness(newest, now)` takes the newest stamp and
the reader's clock; a future stamp reads `DOWN`, never `FRESH`. Do not serve a
writer-frozen age (TRAPS: "frozen age is not an age").

**STILL OWED AND NOW TWICE SLID: flood 09's release checklist.** flood 11 did not create it
either — it is not this ticket's artifact and inventing one here would assert a branch nobody
re-evaluated. It stays yours, and `gate.panel_strings` in the coefficient JSON is the READ
that feeds it.


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

## Forward-context from DESTINATION-PLAN.md (copied verbatim by the WAVE 5 GATE PART 2, 2026-08-25, from this ticket's summary line in waves/wave-3-plus.md)

**FROM DESTINATION-PLAN (2026-08-25) — TWO THINGS LAND ON YOUR EXPORT LATER, BOTH ADDITIVE.** (1) flood-build 20 (wave 8) adds `design_storm: {rate_in_hr, bracket}` per Cell to the UNGATED file inside YOUR tick — leave the writer extensible (one dict per Cell, absent-never-null). (2) The `publish.FAMILIES` entry you add is one of THREE added in wave 6 (yours, flood-build 19's `geo`, frontend2 02's `tiles`) — distinct dict entries, the gate unions them; do NOT bump `contract.CONTRACT`.

## Inherited from flood-build 12's build (2026-08-25, branch `flood12-replay-harness`)

**THE VERDICT IS NOT RECORDED YET AND YOU MUST NOT ASSUME IT.** flood 12 measured and
recommended; Ross records it. Read `cutpoints.provisional` out of
`research/flood-11-detector.json` AT RENDER TIME and say "provisional" while it is `true`
— which it still is on master. Both branches are live:

* **If Ross confirms the cutpoints**, the tier labels render as they do today.
* **If v1 ships RANK-ONLY — which is what flood 12 RECOMMENDED — there is no badge to
  render.** `cutpoints` loses its meaning as a display object, the tier vocabulary
  collapses to the within-kind rank, and `detector_version` bumps (rolling every open
  Window). Your panel must degrade to an ORDERING with no flagged/not-flagged claim, and
  the honesty string you already carry verbatim is the one that still applies.

Either way **`detector_version` bumps**, so do not cache a rendered payload across it and
do not re-type the current digest (`01197991471f`) anywhere a bump would strand it.

**THE RADAR-ONLY-vs-AORC RATIO IS NOW MEASURED, and it is a CHAIN, not a band you apply.**
`research/flood-12-replay.json` -> `forcing_ratio`. A DIRECT measurement is impossible on
this root (`src=aorc` ends 2025-12-31, `src=mrms` begins 2026-07-31, **zero** shared hours,
asserted). What is measured: **RadarOnly / Pass2 = 0.933** on 8,549 wet paired Cell-hours
over 83 hours, times flood 06's published Pass2/AORC `[0.86, 0.92]`, giving **RadarOnly /
AORC = [0.803, 0.859]**. **The live forcing runs 14-20% LOW against the forcing the model
was fitted on, so the raw 2.0 mm own-Cell gate is CONSERVATIVE.** `forcing.scale_band_
applied` is still `false` and **nothing here changes that**: do not divide a rendered mm by
this ratio, do not render the ratio as a correction, and if you surface it at all surface it
as provenance with its limit attached (one storm carries the wet pairs).

**One number your panel can use as-is:** every OK replay cycle reported `coverage 1.0` and
`unforced_cells 168` — a Cell with no forcing anywhere is UNFORCED, not a hole, and the
panel should render those two as different states for exactly the reason the replay does.
