# 08 Exposure/likelihood score design

Type: grilling
Status: resolved
Blocked by: 01, 06, 07

## Answer

Resolved 2026-08-22 (measured; 3-lens adversarial review in
`../assets/08-adversarial-verdicts.json` — 101 verdicts + 40 missing items,
the heaviest teardown of the effort; Ross pre-authorized the reconciled
round and it was presented with veto rights). Draft history:
`../assets/08-score-draft.md`. The review overturned the draft's model
count, its headline, its sweep design, its published object, and its
detector interface; the resolved design below is the post-review form.
Where a review lens "re-measured" tables that do not exist yet (the rails
lens quoted numbers from the unbuilt silver/asset_features), those numbers
were rejected on adjudication (brute-force re-match confirmed the probe's
Ida figures: 12 complexes, 33 unique entrance coords); the qualitative
point — one-pick bus numbers understate citywide — is carried as build-time
measurement obligations, not asserted numbers.

**Grain and target.** Unit-event pairs; y = `flooded_reported` (01's
estimand, named on every public artifact). Positives from
gold/flood_labels; negatives by 01's anti-join at read, never materialized;
pair bound recomputed and frozen at build once the union spine is
enumerated (criterion (a) alone: 57 trigger days = 52 merged events, both
measured; (a)∪(b) exceeds 115 days; (c)/(d) enumerated at build).

**Two fitted models (not three).**
- **Point model**: entrances + bus stops pooled (07's identical feature
  vector + a kind indicator). Complex score = **max over child-entrance
  scores** (06's own positive rule), so complexes need no fit — and the
  155 alert-sourced complex-event pairs (93 station-labeled events, 100
  complexes, chronic repeaters incl. complex 519 x7) become an
  **independent complex-grain validation set** (rank lift / POD@k), never
  training data. This kills both the complex EPV crisis (~24 params vs
  ~130 labeled complexes) and the alert-repeater memorization channel.
- **Cell model**: over `cells_scored`.
- Form: L2 logistic, lambda by inner CV on training folds only (selected
  value recorded in the model-constant JSON). Unweighted fit; in-fold
  operating point, objective = max CSI (named). Rejections stand: GBM
  (memorizes locations; splits can't catch it), hand-weighted index (the
  logistic IS the transparent index), pooled cross-kind model.

**Pluvial-only fit; coastal is a rule layer.** The fitted models train on
pluvial events only: snowmelt-reclassed events excluded (01's gate; 18 of
52 (a)-events are Dec-Mar and exposed to it — counted at build), Sandy
polygon labels excluded from the fit (one coastal event would mint an
estimated 250-350 of ~1,350 cell positives). Coastal exposure ships as a
deterministic layer: `surge_margin_ft = elev_ft − assigned_gauge_threshold
(NAVD88, 05's offsets)`, assignment = geodesic nearest of {Battery, Kings
Point, Sandy Hook} (the three gauges that take assets; 01's spine fetches
only Battery/Kings Point and the CT stations were never asset gauges —
draft error corrected). No new water-level series needed (thresholds are
constants). Validated descriptively against the Sandy polygon overlap;
Rockaway assignment caveat recorded (map fog already carries the Jamaica
Bay blind spot). A fitted coastal model returns only when the coastal
event count supports it (fog).

**Features (frozen pre-fit, src-pinned, log1p on precip).**
- Point model: max mm_1h in window, window total, antecedent mm_24h at
  window open (pre-window = disjoint by construction); elev_ft; ONE relief
  term `(elev_2017_m − ring15_med_m) × 3.280833333` (draft had a
  feet-minus-meters unit bug, fixed; relief applies to entrances too — the
  doorways it was built for); stormwater category; kind indicator.
- Cell model: the 3 precip terms; stormwater area shares; SJ/SH-history
  control. No borough, no n_assets, no cell elevation aggregates
  (measured signal-free at hex grain; 07). Density belongs to baseline
  B3, not the model.
- Stormwater encoding: 4 levels — deep / nuisance / analyzed-none /
  **not-analyzed as its own level** (never imputed to none). Moderate-
  current scenario; FGDB read once via DuckDB spatial's OpenFileGDB
  (verified in-venv; no new dependency), snapshot + coverage fraction
  reported. sewer_type skipped v1 — but on the right denominator at
  build: MS42020_DrainageAreas point-in-polygon over scored units (the
  draft's 97.7%-Combined figure described GI siting, not the city;
  selection-bias error caught by review).
- History covariate v1 = **own-source SJ/SH trailing density** (count of
  SJ/SH points within RADIUS_M in the 3 years strictly before window
  open; exact descriptor literals; per-era datasets) — the covariate that
  actually tests the chronic-reporter channel. NFIP + sewer-backup
  deferred to fog (no ticket owns NFIP access; 01's with/without
  discipline preserved on what ships — comment posted on 01).
- Cut, with reasons: max mm_3h/mm_6h (windowed maxima of nested sums are
  MORE collinear than pipeline-08's VIF-12.5 hourly case; on Ida
  max mm_6h ~= window total), n wet hours (two live definitions:
  CONTEXT's Wet hour needs t2m_c, NULL in the MRMS era; pipeline-14 uses
  bare mm_1h>=1), borough (reporting-propensity control that would enter
  the published map), n_entrances (the fan-out multiplier of the label
  rule itself), structure (lossy mode over 9 mixed complexes; mechanism
  already in elev/relief), freeboard-as-feature + event gauge margin
  (rank-deficient given 3 gauges; replaced by the rule layer).
- Barred (inherited): FloodNet-derived anything; grade_ok/epoch deltas;
  alert-derived features.

**Baselines — four, and the headline.** B0 = event base rate; B1 =
precip-only; **B2 = unit climatology** (as-of prior positive footprint —
measured: one prior storm's footprint predicts the next as well as all
precip, CSI 0.258 vs 0.264, AUC 0.630 vs 0.642); **B3 = density-only**
(bus-stop count per cell — measured AUC 0.704/0.698, beating every precip
feature on both reference storms). Headline validation claim: **the full
model beats B2 AND B3 under the location-blocked split**. B1 comparisons
are reported per grain with the vacuity caveat (B1 is constant within a
cell, so within-cell features beat it by construction). Honesty clause:
if B2 wins, v1 ships B2 as the score and the release says so.

**Splits and reporting.**
- Primary: event-grouped 5-fold CV, deterministic folds =
  sha1(event_id) mod 5 (fold salt in the constant JSON).
- Secondary: **location-blocked 5-fold** (grouped by cell) — the only
  split that tests generalization to unseen places; the history-covariate
  with/without contrast is reported under THIS split (under event folds,
  location-memory covariates look excellent by construction).
- Pooled CSI/POD/FAR at the in-fold operating point + event-cluster
  bootstrap CI on the pooled statistic (frozen: B=1000, percentile
  intervals). **Per-event CSI abolished** — 61% of alert events have
  exactly one positive (measured distribution {1:43, 2:11, 3:7, 4:4, 5+:6});
  per-event reporting = POD (where >=1 positive) + raw FP count. PR-AUC
  secondary.
- Fan-out (06): event-clustering absorbs within-event duplication for
  inference (measured fan-out 1.69-2.07 stops per 311 point); one
  weight-sensitivity fit (positives weighted 1/fan-out) published; the
  draft's spatially-thinned fit is dropped (review: selects on distance,
  misses alert labels, and thins only 27%).
- Sweeps: RADIUS_M {50,100,200} in-fold (labels re-derived from
  silver/flood_obs; label_version per setting); 311 threshold
  {p98,p99,p99.5} is an **outer replication** — it redefines the event
  universe, so "inside the fold" was incoherent (amends 01's phrasing;
  comment posted); p98/p99.5 day-counts measured before running;
  compared on the common-event subset. 07's neighborhood sweep (ring15_med
  vs cell-median relief) added. All sensitivity, never selection; primary
  frozen at (100 m, p99, ring15_med, history-on). One-at-a-time around
  the primary: ~25 configs, not the crossed 180.
- Era rules: fit era = union events 2010-2025 on src=aorc only; 2026
  precip gap defined **by date range** 2026-01-01..2026-08-13 (all
  criteria, not an enumerated day list; 4 merged (a)-events),
  validation-only. MRMS era (2026-08-14+) = out-of-sample replication
  with an acceptance criterion: read against pipeline-08's measured
  0.86-0.92 Pass2/AORC scale band. AORC day-gap rule kept but noted
  vacuous for (a)-events (neither gap touches an (a)-window). Pre/post-
  2014 split reported WITH the label-availability confound stamped on it
  (alert labels are effectively 2016+: 2 labeled days before 2016,
  measured; 02's old-era recall 0.778 adds old-era false negatives) —
  07's 2010-epoch trigger must not fire on that artifact.
- Observed subset (01): FloodNet-active-in-radius negatives sized at
  build per kind; report-only, never in the fit.

**Negative universe: coverage calendars + existence rules.**
- Detectability = per-source coverage calendars: a negative pair is valid
  iff >=1 label source covering that unit kind was active at event time
  (311 continuous; alerts effectively 2016+ minus the 2020-04-01..27 hole
  and the 2026-06-30..08-15 Socrata-to-archiver dark gap; FloodNet
  2020-11-16+). The draft's one-liner is dead — read literally it deleted
  every pre-2020-11 negative.
- Anachronism: known post-2010 station openings (SAS 2017, Hudson Yards
  2015, WTC Cortlandt 2018 — frozen list measured at build) excluded from
  pre-opening events. **Bus_stop pairs restricted to events >= 2020**;
  Bronx pre-2022-06 and Queens pre-2025 stop-pairs dropped, deltas
  published — this REPLACES 06's churn method, which was unexecutable
  (no historical picks exist locally; research/13 measured that nothing
  public holds the bytes); historical-GTFS fetch recorded as the upgrade
  path (new source, HITL). The 72 stops outside every NYC taxi zone are
  excluded from the universe, counted.
- `cells_scored` = (hex intersects a non-EWR taxi zone) UNION (contains
  >=1 scored point asset) — measured 1,336 + ~15 stop-bearing edge cells;
  frozen count at build. (The draft's 1,344 mixed an intersects total
  with a centroid subtraction; resolved.) The 168 permanently-NULL AORC
  cells are provably disjoint (0 intersect any zone) — kept as a build
  assertion, which also retires the NULL-precip caveat for the cell model.

**The published object (the grain fix).** The fitted model is unit x
event; the public table is unit-grain via **evaluation at frozen
reference forcings**: `score_ref` (median of fit-era trigger-event precip
features — "a typical trigger storm", constants measured and frozen at
build) and `score_severe` (p90 forcing). Percentile index 0-100 within
kind computed on score_ref; the eta->percentile empirical CDF per kind is
published in the coefficient JSON. Cross-kind display obligation: per-kind
event-conditional base rates published beside the index (measured spread
~9x: Ida cells 24.3%, complexes 2.7%, entrances 1.8%); never two kinds in
one legend. Probabilities live in validation tables only, with the FIM
anchor stamped "inundation-extent estimand, order-of-magnitude only" and
the base rate printed beside it.

**Detector interface (ticket 10; obligations posted there).** Every
event-side feature is a trailing/running statistic (running max mm_1h,
running total; antecedent frozen at event open), so offline and live
definitions are IDENTICAL and the live score converges to the event score
as the window fills. One in-repo JSON artifact: coefficients,
preprocessing constants, feature definitions, per-kind CDFs, reference
forcings, the MRMS/AORC scale ratio (0.86-0.92) as an informational
constant, score_version. Live output declared **rank-only and
uncalibrated** for v1 (the model is AORC-fitted; MRMS inputs run 8-14%
low). 10 owns event-open definition and thresholding of the rising score.

**Fallbacks and flags (07 discharged).** Complex aggregation over
grade_ok children only, min semantics via max-over-children scores;
flagged/NoData rows score via ring15_med fallback grade — never silently
dropped; zero-ok complexes counted and flagged in an output column; the
grade_ok-filter selection sensitivity (aggregates with/without the filter
on the ~30 stations carrying the 41 flagged entrances) published once.

**Outputs.**
- `gold/flood_exposure`: one row per scored unit — asset_id, kind,
  score_ref, score_severe, score_index, surge_margin_ft, flags,
  label_version, features_version, score_version, src, frozen_at. Plain
  Parquet, single sorted part (asset_id), rebuilt whole, byte-identical
  gate. Absent-key rule: NO NULL scores — fallbacks guarantee coverage;
  reasons ride the flags column.
- Validation outputs (per-event POD/FP, sweep tables, sensitivity fits,
  alert-validation lift, Sandy descriptive overlap, churn deltas,
  coverage-calendar report) = **build assets linked from the ticket**,
  not Gold (no consumer; promoted when one asks).
- score_version = sha1(label_version, features_version, precip identity
  (src + grid sha256 + partition-set hash), stormwater snapshot date,
  model-constant JSON (lambda, radius, threshold, reference forcings,
  fold salt), universe counts). NFIP absent because NFIP is absent.
- Named build items handed to /to-spec: **AORC flood-era extension**
  (month partitions containing union-event windows + 24 h lookback via
  the existing per-(src,month) job — 5 of ~52+ needed months exist; disk
  estimate reported against ticket-18's ~9 GB headroom, window-sliced
  flood-only fallback table if disk blocks); union-spine enumeration
  ((c) Storm Events, (d) CO-OPS exceedance); DEP FGDB snapshot + reader;
  MS4 polygon coverage query; label-set materialization per radius
  setting; the frozen-constant measurements flagged above (p98/p99.5 day
  counts, opening-date list, citywide storm positives, observed-subset
  size, Sandy cell overlap).

## Question

The score itself: target definition (asset flooded within an event window, per
the 01 labels), model form (transparent heuristic index vs logistic regression
vs anything fancier — ponytail default is the simplest thing that validates),
units the public number is stated in (probability per event class? 0-100
index?), feature set (Cell-hour precip features from the pipeline-08 spine,
elevation terms from 07, tide/surge exceedance from 05, stormwater category and
sewer covariates from 04 — NO FloodNet-derived features: 01 made FloodNet the
truth tier, so it is barred from the model), and validation. Obligations
inherited from 01 (binding, not open): estimand is `flooded_reported`;
CSI/POD/FAR with event-held-out splits AND per-event CSI with intervals beside
the pooled number; errors clustered by event (pipeline-10 convention); observed
subset (active in-radius FloodNet sensor, no aq7i-eu5q event) reported
separately from unlabeled, never pooled; attachment-radius sweep {50,100,200} m
and the 311 threshold sweep run inside the fold, full tables published;
precip-gap eras held out, not imputed; detectability anti-join from sensor
active ranges + 02's parseability; NFIP/sewer-backup covariates use a strict
as-of cutoff before each event window, score reported with and without them;
honest calibration expectations (published FIM systems run CSI 0.26-0.45).
Still open here: model form, units, feature list, output tables and their
Silver/Gold shape.

## Comments

2026-08-22 — obligations added by 06's resolution: (1) bus-stop churn
sensitivity report — the 2022 Bronx and 2025 Queens network redesigns sit
inside the 2010-2026 label era and bus stops are 81% of point assets, so
anti-join negatives for pre-redesign events are dominated by stops that did
not exist; (2) label fan-out caveat — one 311 point mints ~2.8 bus-stop and
~4.7 entrance perfectly-correlated positives within RADIUS_M (clustered
errors by event alone do not absorb spatial duplication; consider spatial
blocking in splits); (3) effective-sample caveat — 13,370 bus stops occupy
1,035 Cells (mean 12.9, max 67 per Cell), so Cell-hour precip features are
shared across many bus-stop rows; (4) negative bounds: score units x events
~= 1.02M pairs at ~57 events, generated at read, never materialized.

2026-08-22 — obligations added by 07's resolution (binding; details and
measurements in 07's Answer):
(1) Elevation reads: `silver/asset_features` is point-assets-only. Complex
elevation = GROUP BY ref/assets parent_asset_id over grade_ok=TRUE child
entrances ONLY (min-vs-median is 08's call, made once here); 30 complexes
have a single entrance, so one flagged row voids the unit — report the
count of complexes with zero ok children. Cell elevation = GROUP BY cell
over member ok point assets.
(2) grade_ok and epoch deltas are QC FILTERS, never model features — the
41 flagged entrances concentrate on alert-heavy complexes inside the Sandy
polygon (memorization channel). Known blind class (Kings Hwy, measured):
both epochs contain the same el deck, so a wrong-high grade can pass QC —
cross-epoch agreement != correctness.
(3) Flagged-row fallback: drop the row, use the other epoch per-row, or
use ring15_med — NEVER a hex/cell median (measured strictly worse than the
15 m ring that already fails at repair).
(4) Temporal validity: elevation is a single 2017 surface (2014
cross-check; both epochs postdate Sandy) applied across the 2010-2026
label era; post-2017 rebuilds are unmodeled (Beach 25 St dropped 1.29 m in
the Rockaway rebuild per the 2024 LI DEM). Report the pre-/post-2014 event
split beside pooled CSI, or state the static-covariate limitation.
(5) Pluvial relief term: compose "local low" from elev_ft vs
ring15_min/ring15_med (doorway-scale, 15 m); the relative-elevation
neighborhood definition (ring vs cell window) is 08's, swept beside the
RADIUS_M sweep. Hex-grain anomaly measured signal-free (within-cell relief
p50 2.6 m is real terrain).
(6) Asset->CO-OPS gauge assignment is OWNED HERE: nearest of 05's six
threshold stations by geodesic distance, computed at read from ref/assets
geometry + 05's per-station STND->NAVD88 offsets. Without it neither the
freeboard term nor 10's live comparison exists.
(7) Cell negative universe is polluted: ~2,759 of ref/assets' 4,113 Cell
score units touch no NYC land (bbox tiling; measured via ref/cell_zone) —
restrict scored cells to land/asset-bearing cells or the ~1.02M-pair
negative class and CSI are silently diluted. Also noted on 06.

2026-08-22 — resolution notes against the inherited obligations: 06(1)
churn method replaced (no historical picks exist; local-data restriction +
deltas instead — see Answer); 06(2) answered with event-cluster inference
+ weight-sensitivity fit, spatial blocking adopted in the SPLIT (location-
blocked CV); 07(6) gauge assignment narrowed to the three asset-taking
gauges and consumed by the coastal rule layer, not a fitted term; 01's
"per-event CSI with intervals" and "threshold sweep inside the fold"
amended with measurement (see comment on 01). NFIP deferred to fog.

2026-08-22 — bar added by 09's resolution: transit impact signals
(subway service_ratio / max_gap_ratio, bus cell-hour speed ratios) join
the Barred list — never model features, never detector inputs, never
terms in label_version / features_version / score_version. Impact
coverage calendars (subway 2021-04+, capture 2026-08-16+, bus = baselined
windows w1/w2 only) are impact-only and must never gate 08's negative
universe. Detail: issues/09-impact-signals.md.
