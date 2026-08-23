# Draft — 08 Exposure/likelihood score design

Status: DRAFT for adversarial review, 2026-08-22. Numbers measured today
unless cited.

## Measured today

- **Trigger days reconstruct exactly**: 311 SJ/SH daily counts against 01's
  frozen thresholds give 34 old-era (>=97) + 23 new-era (>=84) = **57
  criterion-(a) trigger days** (01's ~57 estimate confirmed; consecutive-day
  chains like 2021-09-01/02 merge at window build; union with alert days /
  Storm Events / CO-OPS computed at build).
- **The 2026 precip gap is populated**: 5 of the 23 new-era trigger days
  (2026-05-20/21/24, 07-06, 07-18) predate the MRMS ingest start
  (2026-08-14) and AORC ends 2025-12-31 — these events can never carry
  fitted precip features. Pipeline-08 binding: **srcs are never pooled in
  one fit** (AORC vs MRMS collinear with era); AORC also has two known
  day-gaps (2024-06-18, 2024-11-27T20Z) and 168 permanently-NULL Cells.
- **Class balance at unit-event grain is extreme**: the two largest storms
  on record label Ida 692 geocoded points -> 39/2,120 entrances, 12/445
  complexes, 119/4,558 stops (one pick), 324 distinct cells; 2023-09-29:
  617 points -> 38 entrances, 17 complexes, 196 stops, 291 cells. Typical
  trigger days are far smaller. Ida's complex positives come entirely via
  the 311-radius->entrance-OR path (alerts gave Ida zero station labels) —
  the multi-source union works as designed.
- **Alert-sourced positive mass**: 93 station-labeled events -> **155
  complex-event pairs**, 100 distinct complexes, mean 1.67 stations/event;
  chronic repeaters exist (complex 519 labeled 7x, 611 5x) — reporting
  frequency is itself a signal and a bias.
- **Gauge assignment collapses to three**: nearest-of-six over 2,120
  entrances + 4,558 stops assigns Battery 5,847 / Kings Point 588 / Sandy
  Hook 243; the three CT stations get zero assets (they are event-spine
  criteria only). Max assignment distance 23.8 km (eastern Rockaways ->
  Battery — the map's Jamaica Bay blind spot, now quantified).

## Proposal

**Grain and target.** Unit-event pairs. y = `flooded_reported` in {0,1}
(01's estimand, named on every public artifact). Positives from
`gold/flood_labels` per kind (complex: OR over child-entrance radius labels
+ alert rows at `stn:`; bus_stop: radius; cell: cell-support labels).
Negatives by 01's anti-join at read, never materialized.

**Scored universes** (resolves 07's flag): 445 complexes; 13,370 bus stops
(churn sensitivity below); cells restricted to **NYC-land cells** — hex
intersects a taxi zone, EWR excluded (measured ~1,344 of 4,113; exact count
frozen at build as `cells_scored`). Negative bound: ~15,160 units x ~70
union events ~= 1.06M pairs at read.

**Model form (ponytail ladder).** Per-kind **L2-regularized logistic
regression** — three fits (complex, bus_stop, cell), because the feature
vectors differ by kind; identical spec pattern, frozen preprocessing,
coefficients published. Two mandatory baselines: **B0** = event base rate
(climatology); **B1** = precip-only logistic (cell precip features, nothing
else). The asset layer earns its keep only if the full model beats B1 on
held-out events — that comparison is the headline validation claim.
Rejected for v1: pooled model with kind interactions (forces one scale,
unreadable coefficients), trees/GBM (opacity + memorization risk at 06's
effective sample), hand-weighted index (pretends to dodge fitting but just
hides it — the logistic IS the transparent index once coefficients are
published). Upgrade trigger: full model fails to beat B1 -> the asset
features, not the model class, are the problem.

**Public units.** Per-kind **percentile index 0-100** (rank within kind —
robust to calibration failure, honest under PU labels). The conditional
probabilities per event class live in the validation tables with intervals,
never as the headline number. Event classes (from 01's FLOOD_CAUSE-first
classing: pluvial / coastal / mixed) are **validation strata, not model
inputs** — the model conditions on the physical drivers directly.

**Features (frozen pre-fit; all src-pinned; log1p on precip).**
- *Precip, event x cell* (silver/precip_cell_hourly src=aorc): max mm_1h,
  max mm_3h, max mm_6h in window; window total; antecedent mm_24h at window
  open; n wet hours. Disjoint lags by subtraction per pipeline-08 (VIF up
  to 12.5 on nested sums).
- *Elevation (07)*: complex — min & median elev_ft over grade_ok child
  entrances; bus_stop — elev_ft, relief terms (elev_ft − ring15_med x
  3.280833333, elev_ft − ring15_min); cell — member-asset aggregates
  (NULL for asset-less land cells -> missing-indicator column, no
  imputation).
- *Coastal*: static freeboard = elev_ft − assigned gauge's nws_minor in
  NAVD88 (05's per-station offsets); event-side max water-level margin
  over nws_minor at the assigned gauge in window. Main effects only in v1;
  the Rockaway->Battery 23.8 km caveat recorded.
- *Stormwater (04)*: DEP Stormwater Flood Map category at the point
  (ordinal none/nuisance/deep), **moderate-current scenario only** for v1;
  FGDB downloaded once at build, snapshot + coverage fraction reported.
  sewer_type SKIPPED v1: 97.7% of the GI proxy layer is Combined — a
  near-constant covariate (upgrade: if MS4/separate areas concentrate
  residuals).
- *History covariates, strict as-of before each window (01)*: NFIP claims
  count in the asset's block group; 311 sewer-backup density. Score
  reported **with and without** these two (the chronic-reporter channel).
- *Structure/categoricals*: complex — structure (mode over stations),
  n_entrances, borough; bus_stop — borough; cell — borough, n_assets.
- **Barred**: anything FloodNet-derived (01: truth tier); grade_ok /
  epoch deltas (07: QC only); anything alert-derived (labels); flagged
  elevation rows enter only via 07's fallback rules.

**Splits and validation (01's obligations made concrete).**
- Primary: **event-grouped 5-fold CV** — every pair of an event in one
  fold (~57 (a)-days, ~70 union events -> ~14/fold). Errors clustered by
  event.
- Fan-out control (06): inference clustered by event; PLUS a
  **spatially-thinned sensitivity fit** — one positive per 311 source
  point per kind (nearest unit keeps it) — published beside the main fit
  to show coefficients survive de-duplication. This is the answer to 06's
  "consider spatial blocking".
- Metrics: pooled CSI/POD/FAR at an in-fold-chosen operating point +
  **per-event CSI with event-bootstrap intervals** beside the pooled
  number; PR-AUC as the threshold-free secondary. Calibration expectations
  anchored: published FIM systems run CSI 0.26-0.45.
- Sweeps **inside the folds**, full tables published: RADIUS_M
  {50,100,200}; 311 era-threshold {p98, p99, p99.5}.
- Era honesty: fit on AORC-era events only (2010-2025). The five 2026
  precip-gap events are excluded from fit and reported in a
  validation-only table (no precip features exist); MRMS-era events
  (2026-08-14+) are an out-of-sample replication read, never pooled
  (pipeline-08 binding). AORC day-gap events -> NULL-row rule, not
  imputation.
- 07's obligations: complex aggregates over grade_ok only (zero-ok
  complexes counted); pre-/post-2014 event split reported beside pooled
  CSI; flagged-row fallback = drop.
- 06's obligations: bus-churn sensitivity — score fit/eval restricted to
  stops present in the era's picks vs all stops, delta published;
  effective-sample caveat carried into the write-up (13,370 stops in
  1,035 cells share precip features).
- Observed-vs-unlabeled (01): pairs with an active in-radius FloodNet
  sensor and no aq7i-eu5q event = **observed negatives**, reported
  separately, never pooled with unlabeled.
- Detectability anti-join (01): sensor active ranges + 02's alert
  parseability gate the negative universe.

**Outputs.**
- `gold/flood_exposure` — one row per scored unit: asset_id, kind,
  score_index (0-100 within kind), eta (linear predictor), score_version,
  frozen_at. Rebuilt whole; single sorted part file.
- `gold/flood_exposure_validation` — per-event rows: event_id, class, kind,
  CSI/POD/FAR, n_pos; plus the sweep and sensitivity tables as build
  assets linked from the ticket.
- **Model artifact = the 10 interface**: coefficients + preprocessing
  constants + feature definitions as JSON in-repo, with the
  live-computable subset marked (precip so far, live gauge margin). The
  detector re-evaluates the SAME linear model with live features — no
  second model to reconcile. score_version = sha1(label_version,
  features_version, model-constant JSON, scored-universe definition).

## Skipped, with reasons

- Hydrodynamic/HAND terms, class-25 sills, DSM tiles: fog triggers
  unchanged (07).
- sewer_type covariate v1 (near-constant, measured 97.7% Combined).
- Model interactions, GBM, stacking: only if full-vs-B1 fails.
- Absolute probability as the public number (PU labels make it a
  reporting-rate estimate; the percentile index + validation tables carry
  the honest version).

## Decision points for the numbered round

1. Grain/target/universes as stated (incl. land-cell restriction ~1,344).
2. Model form: 3 per-kind L2 logistics + B0/B1 baselines; headline =
   full beats B1 on held-out events.
3. Public number: per-kind percentile 0-100; probabilities confined to
   validation tables.
4. Feature set as listed (incl. sewer_type skip, moderate-current
   stormwater scenario only, with/without history covariates).
5. Validation plan: event-grouped 5-fold + thinned sensitivity fit +
   in-fold sweeps + era rules (2026 gap events validation-only; MRMS era
   replication-only) + pre/post-2014 + churn sensitivity + observed-vs-
   unlabeled separation.
6. Outputs: gold/flood_exposure + validation table + in-repo coefficient
   JSON as the detector interface; score_version chained.
