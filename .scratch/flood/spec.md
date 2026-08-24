# raincheck flood: build spec

Status: ready-for-agent
Source: wayfinder map `.scratch/flood/map.md` (10 tickets, all resolved). Written
2026-08-22. Vocabulary is CONTEXT.md's (Cell, Zone, Hour, Pixel, Precip source,
Trailing window, Live table, Bronze/Silver/Gold); ADR-0001 and ADR-0002 are binding
where precipitation or arrivals are touched. New terms this spec introduces are
defined inline and should graduate to CONTEXT.md at build: **Unit** (a scored asset:
complex, bus stop, or Cell), **Carrier** (a station or entrance row that locates and
aggregates but is never scored independently), **Window** (the flood event window,
offline or live), **Tier** (a truth level on the live panel: model / measured /
reported).

Where a ticket's original Answer was later corrected by a comment, this spec carries
the correction; the load-bearing corrections are tabled in Further Notes so an
implementer who opens a ticket for detail is not misled by its first text.

## Problem Statement

Ross wants to know — with public data and a method he can defend — where flooding
hits NYC transit: which subway stations, bus stops and street areas have flooded
before, which are most exposed when a storm comes, and, while rain is falling,
which are likely flooding right now. Nothing public answers this at asset grain:
flood records are scattered across 311 calls, MTA alert prose, sensor networks,
storm databases and tide gauges, each with its own units, datums, gaps and renames;
no score ranks individual stations and stops; and no live view exists at all. The
raincheck pipeline already owns the rails — the Cell grain, the precipitation
spine, the capture daemon, the serving page — so the flood effort should ride them
rather than rebuild them.

## Solution

Three deliverables on the existing rails, each honest about what it can claim:

- **A mapped flood history.** Every label-grade flood observation (311 street/
  highway flooding calls, FloodNet sensor events, station-named MTA alerts, USGS
  high-water marks, the Sandy inundation polygon) lands in one observation table;
  a deterministic event spine turns them into dated flood events with UTC windows;
  a positives-only label table attaches observations to transit assets. The
  estimand is named on every artifact: `flooded_reported` — where flooding was
  REPORTED, not where water necessarily stood.
- **An exposure score.** Two small fitted models (bus stops + subway entrances
  pooled; Cells) score every Unit's flood-report likelihood under frozen reference
  storms, validated against baselines that are designed to embarrass it (prior
  footprint, stop density) under a location-blocked split — with a standing clause
  that if the trivial baseline wins, the trivial baseline ships. Coastal exposure
  is a deterministic rule layer against tide-gauge thresholds, not a fitted model.
- **A live detector panel.** A third panel on the raincheck page, computed by the
  existing export loop with no new daemons: the same fitted model evaluated on
  live MRMS RadarOnly Cell-hours, displayed as a within-kind rank with latched
  flag tiers; beside it, three truth tiers that never feed the model (FloodNet
  sensor water detections, tide-gauge threshold status, MTA "remove water" alerts)
  and the bus/subway impact overlays from the pipeline's own Gold. Every source
  ages independently on screen; missing rainfall hours are their own visible
  state; and the panel says plainly what it is, in the frozen operating-truth
  string it shares verbatim with every flood notification [notify 01,
  2026-08-23]: "raincheck ranks where a flood REPORT is likely from rain that
  has already fallen, on hour-grain evidence that trails the storm. A rank is
  not an observation of water, and a quiet panel or a quiet inbox means nothing
  was flagged, not that nothing flooded."

## User Stories

Analyst = Ross doing the analysis; presenter = Ross showing the page; viewer =
anyone the page is shown to; implementer = the agent building a slice.

1. As an analyst, I want every label-grade flood observation in one table with
   source, time, geometry and depth where measured, so that every downstream
   artifact draws from one auditable well.
2. As an analyst, I want a deterministic event spine (dated flood events with UTC
   windows), so that "during the event" means the same hours in every table, fit
   and test.
3. As an analyst, I want event windows derived from calendar rules, never from the
   observations themselves, so that the spine cannot circularly confirm its own
   labels.
4. As an analyst, I want the 311 trigger thresholds frozen as named constants with
   the dataset era they were measured on, so that a rerun years later reproduces
   the same spine.
5. As an analyst, I want the 311 descriptor set to carry both the legacy literals
   and their 2023 renames, so that the label era does not silently end where the
   city renamed a dropdown.
6. As an analyst, I want a canary that fails the build when any frozen source
   literal stops matching recent rows, so that the next upstream rename is caught
   at build time, not by a reviewer a year later.
7. As an analyst, I want station-named MTA alerts extracted with a measured-
   precision extractor and gated on that precision, so that alert prose becomes
   labels only while it stays trustworthy.
8. As an analyst, I want FloodNet's curated event table as the sensor label
   source rather than the raw API, so that labels inherit the network's own
   quality control instead of its raw noise.
9. As an analyst, I want positives-only labels with negatives generated by
   anti-join at read under per-source coverage calendars, so that a Unit is only
   ever "dry" where some source could actually have seen it flood.
10. As an analyst, I want anachronism rules (station openings, bus-network
    redesigns) excluding Units from events that predate them, so that negatives
    never include assets that did not exist.
11. As an analyst, I want one asset registry holding complexes, stations,
    entrances, bus stops and Cells with stable keys and a byte-identical rebuild,
    so that every score and label joins the same universe every time.
12. As an analyst, I want elevation features (NAVD88 feet, doorway-scale relief
    ring) for every point asset with QC flags that are never model features, so
    that terrain enters the model without letting data quality leak into it.
13. As an analyst, I want the exposure model to be two small transparent logistic
    fits with a frozen feature list, so that every coefficient can be read and
    defended.
14. As an analyst, I want complex scores to be the max over child entrances, so
    that the sparse alert-labeled complexes stay out of training and become an
    independent validation set.
15. As an analyst, I want the headline validation claim to be "beats prior
    footprint AND stop density under the location-blocked split", so that the
    model must beat the two boring explanations before it may brag.
16. As an analyst, I want the if-the-baseline-wins-ship-the-baseline clause
    honored end to end, including alternate live-panel wording, so that honesty
    survives even an embarrassing result.
17. As an analyst, I want per-event reporting as POD plus raw false-positive
    count, so that single-positive events are not laundered through a degenerate
    per-event CSI. (The drafted "61% of them" is SUPERSEDED by flood 09's
    measurement on the landed matrix, 2026-08-24: single-positive events are 6 of
    100 at point grain, 7 of 133 at Cell grain and 55 of 71 at complex grain. The
    decision stands; the fraction was wrong.)
18. As an analyst, I want radius and threshold sweeps published as sensitivity
    tables around one frozen primary configuration, so that reviewers see the
    knobs without the knobs having selected the result.
19. As an analyst, I want coastal exposure as a deterministic margin against each
    Unit's assigned gauge threshold in one datum, so that storm-surge risk is
    stated without pretending ~15 coastal events could fit a model.
20. As an analyst, I want the fitted era pinned to the AORC Precip source with the
    MRMS era as out-of-sample replication under a stated scale band, so that the
    two rain stores are never pooled (ADR-0002 discipline).
21. As an analyst, I want subway impact metrics (service ratio, max gap ratio) and
    bus Speed ratios joined to event windows as impact evidence, never as model
    features, so that consequence and cause stay on opposite sides of the wall.
22. As a presenter, I want a static exposure view (score under a typical trigger
    storm, within-kind percentile), so that the exposure story stands on its own
    in dry weather.
23. As a presenter, I want the live panel to switch from the static view to a
    live within-kind rank when a Window is active, so that the display always
    answers "compared to what, right now".
24. As a presenter, I want flag tiers (ELEVATED, HIGH) that are top-N%-within-kind
    with latched gates, so that the flagged count is bounded by construction and
    flags never flap mid-storm.
25. As a presenter, I want the live Window anchored and reset by a stateless
    backward walk over the rain series, so that what the panel shows is a pure
    function of data and clock — reproducible after the fact.
26. As a presenter, I want missing rainfall hours displayed as their own state
    ("ranks computed on N of M rainfall hours"), so that a laptop sleep can never
    masquerade as a calm forecast.
27. As a presenter, I want FloodNet water detections shown as a measured truth
    tier with the network's own caveats (snow, obstruction), so that the model's
    guesses sit beside the ground truth that can shame them.
28. As a presenter, I want tide-gauge chips (quiet / approaching / exceeding, next
    high tide with anomaly), so that coastal state is visible at a glance during a
    surge event.
29. As a presenter, I want MTA "remove water from the tracks" alerts as chips with
    first-seen times and active/cleared distinction, so that the agency's own
    reports appear the moment the archiver sees them.
30. As a presenter, I want bus slowdown and subway service overlays beside the
    detector, labelled "impact — never a detector input", so that the causal
    direction of the display cannot be misread.
31. As a viewer, I want the headline label to say "flood-report exposure rank"
    with an always-visible sentence about reporting propensity, so that I am
    never invited to read the number as flood depth or probability.
32. As a viewer, I want per-kind legends that never mix Units of different kinds
    and base rates worded as fit-era frequencies, so that a Cell's 24% and an
    entrance's 2% never sit on one color scale.
33. As a viewer, I want every panel source to show its own age and error state,
    so that one dead API greys one tier instead of silently freezing the page.
34. As a viewer, I want the winter gate to suppress rank tiers under freezing
    temperatures with a plain explanation, so that a snowstorm is never ranked by
    a model fitted on rain.
35. As an implementer, I want every derived table to carry its version stamp
    (label_version, assets_version, features_version, score_version,
    detector_version) with structural — not clerical — chaining, so that any
    rebuild that changes an input forces the downstream stamps to change.
36. As an implementer, I want the detector's constants (window rule, cutpoints,
    gates, vocabularies, query strings, staleness budgets) in one versioned
    constants artifact, so that behavior changes are diffs, not code archaeology.
37. As an implementer, I want a replay harness over the AORC-era spine publishing
    signed live-minus-offline feature deltas and per-event flag volumes, so that
    the live rules are measured against history before they face a real storm.
38. As an implementer, I want each slice to end in a runnable check in the
    existing test suite's style, so that "done" is a passing assertion, not a
    claim.

## Implementation Decisions

### Labels and the event spine (tickets 01, 02; amended by 06, 08, 10)

- Three tables. `silver/flood_obs`: one GeoParquet file (~60K rows), label-grade
  sources only — 311 street/highway-flooding points, FloodNet events from the
  curated Socrata event table (never the row-capped raw API), station-labeled MTA
  alerts, USGS high-water marks, Sandy inundation polygons. Columns: source,
  source_id, ts_utc, obs_ts_kind {incident, report, alert}, geometry, Cell,
  depth_mm (nullable), text (nullable). Covariate sources never enter it.
- `silver/flood_events`: the spine. A day (America/New_York) is an event-day on
  any of four triggers: (a) 311 daily count at or above the frozen nearest-rank
  p99 per era-dataset — the descriptor set is FOUR exact literals ('Street
  Flooding (SJ)', 'Highway Flooding (SH)', and their 2023-09 renames 'Flooding on
  Street', 'Flooding on Highway'), with the p99 thresholds RE-MEASURED on the
  union per era-dataset at build (the original 97/84 were measured on the legacy
  literals alone and are biased low across the 2023-09..2026 overlap); (b) at
  least one station-naming alert flood event (the vocabulary includes the
  "remove water from the tracks" family measured in the live feed — see the
  extractor decision); (c) NOAA Storm Events flood types by county FIPS and the
  enumerated coastal zone names; (d) CO-OPS water level at the Battery or Kings
  Point at or above that station's own NWS minor threshold, station datum both
  sides, two consecutive readings. Contiguous event-days merge; window =
  [NY-midnight of first day − 3 h, NY-midnight after last day + 3 h] as UTC
  hour_end bounds, never observation-derived. Event class from Storm Events
  FLOOD_CAUSE where present, else trigger-based; Dec–Mar pluvial days with spine
  temperature at or below freezing reclass to snowmelt and leave the pluvial fit.
- `gold/flood_labels`: POSITIVES ONLY (asset_id, event_id, Cell, source-mix
  bitmask, depth where measured, label_support {radius, station, cell}).
  Negatives are an anti-join generated at read under per-source coverage
  calendars (311 continuous; alerts effectively 2016+ minus the 2020-04 hole and
  the 2026-06-30..08-15 Socrata-to-archiver dark gap; FloodNet 2020-11-16+) plus
  anachronism rules (frozen station-opening list; bus-stop pairs restricted to
  events from 2020 on). label_version = sha1 over source as-of dates, frozen
  thresholds, RADIUS_M, and assets_version.
- Attachment: one constant RADIUS_M = 100 m geodesic for every point source,
  identical everywhere; Cell-grain by H3 equality; polygons by contains/
  intersects; alert stations land as ONE row on the complex (entrances inherit
  for display only). The {50,100,200} m sweep is in-fold; the 311-threshold sweep
  is an outer replication (it redefines the event universe).
- The alert-station extractor: cause-anchored matching against the GTFS stop and
  complex names, measured precision 1.000 on both the hand-labeled sample and the
  frozen-rule holdout. Two live-era extensions, both gated: the anchor vocabulary
  extends to the "remove water from the tracks" family (zero live alerts carry
  the legacy 'flood'/'water cond' phrasing — measured over 449,737 captured
  rows), scanning header AND description; and precision is re-measured on that
  family and on the archiver's parquet serialization (≥ 0.90 to stay
  label-grade). Informed-entity is no shortcut: stop_id was NULL in 104/104
  captured water alerts.

### Asset registry (ticket 06)

- One `ref/assets` GeoParquet: 20,544 rows — 445 complexes + 496 stations + 2,120
  entrances + 13,370 bus stops + 4,113 Cells. Stations and entrances are
  Carriers; complexes, bus stops and Cells are the score Units. No-hash natural
  keys (entrance = corrected complex id + 6-dp coordinates; bus stop coordinates
  are the cross-feed mean); byte-identical rebuild off pinned Picks and
  snapshotted source pulls; a key-stability contract with a rebuild key-diff.
- Radius attachment targets entrance, bus_stop and cell rows only; 19/445
  complexes have no entrance inside their own 100 m circle — the station→complex
  path covers them.
- `cells_scored` = Cells intersecting a non-EWR taxi Zone UNION Cells containing
  a scored point asset (~1,351; ~2,759 of the registry's 4,113 Cells touch no
  NYC land and are excluded from the score universe). The count freezes at
  build; the permanently-NULL AORC Pixels are asserted disjoint from it, and the
  same coverage assertion runs for the MRMS crosswalk.

### Elevation features (ticket 07)

- `silver/asset_features` is point-assets-only: 15,490 rows (entrances + bus
  stops). Complex and Cell aggregates are read-side GROUP BYs over grade_ok
  children, never stored rows.
- Canonical elevation = the 2017 1-m DEM ImageServer in NAVD88 US-survey feet
  (× 3.280833333); the 2014 epoch is a cross-check only; plus an 8-point 15 m
  ring (ring15_min / ring15_med — the doorway-scale relief neighborhood).
  Request constants pinned; nearest-neighbor interpolation frozen (bilinear
  moves values 0.34 m).
- One `grade_ok` boolean from frozen constants (epoch delta > 2 m, elevation
  < −1 m; measured 41/2,120 entrances, 4/4,557 sampled stops). QC flags are
  FILTERS, never model features. Flagged rows fall back to ring15_med — never a
  Cell median (measured strictly worse). A 41-count service-drift canary guards
  the source; features_version chains on assets_version.
- Datum discipline is absolute: NAVD88 US feet canonical; the naive STND-vs-NAVD
  comparison inflates "below minor flood" entrances 103 → 3.

### Exposure score (ticket 08)

- Two fitted models, L2 logistic, pluvial events only, unweighted, lambda by
  inner CV: a pooled POINT model (entrances + bus stops, shared feature vector +
  kind indicator) and a CELL model over cells_scored. Complex score = max over
  child-entrance scores, which frees the alert-sourced complex-event pairs
  to be an independent complex-grain validation set (MEASURED 2026-08-24 by
  flood 08 against the landed gold/flood_labels: 140 complex labels in all,
  118 of them on pluvial fit-era events — the drafted 155 is superseded). Rejected and staying
  rejected: GBM, hand-weighted index, a third complex-level fit.
- Features, frozen pre-fit, Precip source pinned, log1p on precip: point model =
  running max mm_1h in Window, Window total, antecedent mm_24h frozen at Window
  open, elevation, ONE relief term ((elev − ring15_med) in feet), stormwater
  category (4 levels: deep / nuisance / analyzed-none / not-analyzed — never
  imputed), kind indicator; cell model = the three precip terms, stormwater area
  shares, own-source 311 trailing density (3 years strictly before Window open —
  the chronic-reporter control). Barred: anything FloodNet-derived, grade_ok or
  epoch deltas, alert-derived features, borough, asset counts, impact metrics.
- Sandy polygon labels are excluded from the fits (one coastal event would mint
  ~250–350 of ~1,350 cell positives); they validate the coastal layer
  descriptively.
- Coastal rule layer: surge_margin_ft = elevation − assigned gauge threshold
  (NAVD88), assignment = geodesic nearest of {Battery, Kings Point, Sandy Hook},
  per-station datum offsets, threshold stage frozen once and shared with the
  detector (asserted equal at build). No fitted coastal terms.
- Validation: primary split = event-grouped 5-fold (deterministic sha1 folds);
  secondary = location-blocked 5-fold (grouped by Cell) — the history-covariate
  with/without contrast reports under THIS split. Pooled CSI/POD/FAR at the
  in-fold operating point with an event-cluster bootstrap (B=1000); per-event
  POD + raw FP count; PR-AUC secondary. Four baselines: base rate, precip-only,
  unit climatology (B2), density-only (B3); headline = the model beats B2 AND B3
  under the location-blocked split; if B2 wins, v1 SHIPS B2 and the release and
  panel say so. One weight-sensitivity fit (1/fan-out); ~25 one-at-a-time
  configs around the frozen primary (100 m, p99-union, ring15_med, history-on).
- Era rules: fit on the AORC Precip source, union events 2010–2025; the 2026
  pre-MRMS gap (2026-01-01..08-13 by date range) is validation-only; the MRMS
  era is out-of-sample replication read against the measured 0.86–0.92
  Pass2/AORC band. Pre/post-2014 split reported with the label-availability
  confound stamped on it.
- Published object: `gold/flood_exposure`, one row per Unit — score_ref and
  score_severe (evaluation at frozen reference forcings: median and p90 of
  fit-era trigger-event precip), score_index (within-kind percentile on
  score_ref, CDFs published in the coefficient artifact), surge_margin_ft,
  flags, all version stamps. Plain Parquet, single sorted part, byte-identical
  gate, NO NULL scores (fallbacks guarantee coverage; reasons ride flags).
  Probabilities live in validation tables only. The coefficient artifact (one
  in-repo JSON) carries coefficients, preprocessing constants, feature
  definitions, per-kind CDFs, reference forcings, the scale band, and
  score_version = sha1 over label/features/precip identities plus model
  constants.

### Impact signals (ticket 09)

- Subway: service_ratio and max_gap_ratio at complex grain from subwaydata.nyc
  per-day CSVs (trip-start-keyed: hours 00–05 need the previous day's file
  unioned — 94% undercount otherwise), with route-mix residuals and same-line
  neighbor controls for any flood attribution; combined they catch 5/7 of the
  extractor-flagged complexes on the 2023-09-29 reference day. No new Silver
  table — corpus aggregates are build assets.
- Bus: Speed ratios from the existing Gold Cell-hour tables and their window
  baselines, sums-merged. Coverage honesty published: subway covers 35/115 union
  event days, bus 6/115, 70% have neither.
- subwaydata.nyc license was not found: fetch-and-use, local-only, snapshots
  outside the archive root (never cold-pushed), derived numbers local-page-only.
- Live: subwaydata lags 7–31 h — the ticket-15 TU capture is the only live
  subway path; realized arrivals need a stop-row-disappearance inference pass
  and a level comparison against subwaydata on overlapping days BEFORE any
  cross-source display; Precip-source-style discipline (srcs never pooled;
  capture-era baselines accumulate from capture days; ratios NULL until at least
  two same-weekday baselines exist).
- Impact is display/validation ONLY, on both sides of the wall: never a model
  feature, never a detector input, and the panel labels it so.

### Real-time detector (ticket 10)

- The detector IS the exposure model evaluated live — one artifact chain, no
  second model. Forcing = the pipeline's live precip table (MRMS RadarOnly :00
  stamps only; the 2-min trailing stamps would converge from above and are
  rejected; Pass2 lags 60–90 min and never feeds the live path). The live-precip
  job is AMENDED: each run fetches every missing :00 stamp within the source's
  measured ~25 h retention, so sleep holes heal.
- Display value = within-kind rank of live eta across the CURRENT eta vector
  ("top X% of bus stops"), computed at export. The score_ref CDF percentile is
  the STATIC view only (it is a fixed-forcing distribution; fed a live eta it
  reads ~0 in light rain and ties at the ceiling in severe storms). Dormant
  weather shows the static view; an active Window switches to the live rank.
  Score Units only — entrances never publish an independent live number.
- Live Window: a stateless backward walk each cycle — the anchor is the most
  recent 21:00 America/New_York boundary (UTC-pinned hour_ends, DST resolved
  from the NY-local date) whose three preceding pad hours are citywide dry
  (wet-cell count below frozen K at ≥ 1.0 mm — never a citywide max), else walk
  back a day, hard cap 6 days (window_capped). Missing pad stamps →
  INSUFFICIENT_DATA: hold, degrade, never silently reset or latch. Running max
  mm_1h and Window total over [anchor, now]; antecedent mm_24h frozen at the
  anchor, persisted with its own coverage fraction. Window coverage
  (present/expected stamps) is tracked over the Window and the antecedent block;
  NULL hours count as missing, never zero; HOLES is a panel state distinct from
  staleness.
- Tiers: ELEVATED = top 10% within kind, HIGH = top 2% (provisional until the
  replay measures per-event flag volumes; if false-positive volume is
  unacceptable, v1 ships rank-only). Gates, both latched within a Window: own-
  Cell Window total ≥ 2.0 mm; citywide Window active. Monotone-latch claim is
  conditional and stated: non-negative event-side coefficients (asserted at
  build) and an unrevised series (a downward revision is logged and never clears
  a flag). Flags dim when citywide wet-cell count has been below K for 3+ hours
  ("rain ended Xh ago") and clear at Window roll. Winter gate: one Central Park
  observation per cycle; at or below 0.5 C the tiers suppress and the model tier
  is labelled "fitted on rain — snow not modeled".
- Coastal live: the three gauges' 6-min observations in NAVD88 directly
  (labelled preliminary), margin against the same frozen threshold family (the
  Kings Point NWS/NOS inversion is recorded); forecast = harmonic next highs
  over a FORWARD window (begin_date + range — a bare range parameter returns the
  PAST N hours; exact query strings are frozen constants) plus a 30–60 min mean
  anomaly persisted only onto highs within 12 h. Chips: QUIET / APPROACHING
  (within 1.0 ft of minor) / EXCEEDING; gauge outage is its own chip state.
  Assets assigned to an APPROACHING+ gauge recolor by static surge margin.
- FloodNet truth tier (display only, the bar stands): one bounded query per
  cycle over [now − 60 min, now + 2 min] — unbounded reads are poisoned by a
  clock-broken sensor stamping year 2080; null deployment ids are dropped.
  Water detected = latest depth ≥ 15 mm AND a ≥ 15 mm in-window rise AND ≥ 3
  consecutive samples above AND recent onset, with the sensor-status blacklist
  from daily-cached deployment metadata and concurrent own-Cell rain as a
  display gate (absolute-depth rules are dead: 18–528 mm standing offsets were
  measured on a dry night). Dry-and-reporting sensors render dim as "dry above
  curb height at the signpost". API errors grey the tier.
- MTA alert tier: newest captured subway-alert rows each cycle, filtered by the
  frozen LIVE vocabulary (the remove-water family), one chip per incident
  (spine dedupe keys), first-seen time, active vs cleared ("while"/"after").
- Serving: a third panel SECTION on the raincheck page — the flood tick joins
  the existing 30 s export loop (one process, one meta file whose flood keys the
  single writer merges; cycles cannot overlap). The tick skips work unless the
  newest precip stamp advanced or a truth-source throttle expired (FloodNet
  120 s, CO-OPS 360 s, NWS 300 s); every fetch has a hard 3 s timeout; last-good
  values keep their own age; one hung socket never stalls the bus panel. Three
  export files (all Cells as geometry; point Units only at ELEVATED+; the truth
  payload), written through the same pure-SQL merge-patch path (absent keys,
  never nulls), payload-then-meta atomic replace, one cycle id across the set.
  Staleness budgets from measured cadences: precip fresh ≤ 90 min from the
  stamp, stale to 180, down past 180, holes indicated separately; FloodNet
  10 min, CO-OPS 30 min, NWS 15 min. Impact overlays: the bus file at Cell
  grain and the subway file at complex grain, keyed on (Cell | complex,
  hour_end_utc), last CLOSED Hour, rendered when present, greyed when absent,
  labelled "impact — never a detector input"; bus stops take the Cell fallback;
  never two kinds in one legend. The panel activates the conditional live-bus
  baseline build item (a 2026-era window; never the backfill-era baselines).
- Claims, fixed strings: headline "flood-report exposure rank"; always-visible
  reporting-propensity sentence ("ranks where a flood REPORT is likely… places
  whose residents report more rank higher for that reason"); Window named in
  the tier label; degraded-state strings; per-kind base rates worded as fit-era
  frequencies; the within-Cell note (live ordering inside a Cell is purely
  static); the frozen operating-truth string — "raincheck ranks where a flood
  REPORT is likely from rain that has already fallen, on hour-grain evidence
  that trails the storm. A rank is not an observation of water, and a quiet
  panel or a quiet inbox means nothing was flagged, not that nothing flooded."
  (frozen by notify 01; the notifier's render reuses it verbatim, so the panel
  and a message cannot contradict each other); and the B2-branch alternate
  strings selected by the shipped model id.
- Constants artifact: a second in-repo JSON (detector constants — window rule,
  cutpoints, gates, staleness budgets, vocabularies, query strings, UGC zone
  list, winter gate, canary patterns) with detector_version = sha1 of the file.
  The exporter loads both JSONs and stamps BOTH digests; version skew refuses
  the model tier; a coefficient swap mid-Window forces a Window roll.
- Logging: one NDJSON file per day — full unit-state vector only when the model
  tier recomputes (~24/day), the flagged subset per cycle, truth snapshots on
  change; ~3 MB/day, ≤ ~100 MB under the 30-day prune-on-start; inside the
  data-root byte budget. Replay is conditional on the catch-up fetch; capped or
  insufficient-data Windows are not replayable and say so.
- No new daemons anywhere: the only standing dependency is the already-approved
  live-precip agent; FloodNet/CO-OPS/NWS are fetched at export time while the
  loop runs.

### Storage and engine conventions (inherited, binding)

- Pipeline-09 verbatim: plain Parquet Silver batch-rebuilt per partition,
  GeoParquet 1.1 only where geometry is the payload, EPSG:4326, geodesic
  distances only, TIMESTAMP_MICROS UTC, Hive layouts read by DuckDB as the
  oracle. Spark writes every derived table the enrichment path owns; the DEP
  stormwater geodatabase is read once through DuckDB spatial's OpenFileGDB
  driver (verified in-venv, no new dependency) and snapshotted.
- The precip spine is the pipeline's: Cell-hour features join at read on (src,
  cell, hour_end_utc) with the Precip source pinned; the flood-era AORC
  extension (month partitions containing union-event windows + 24 h lookback,
  ~52 needed months of which 5 exist) runs through the existing per-(src,
  month) job, disk-checked against the cold-storage headroom, with a
  window-sliced flood-only fallback if disk blocks.

## Testing Decisions

A good test asserts external behavior at a seam — a written table read back by
DuckDB, a pure function on a fixture, an export file parsed from disk — never
implementation internals. Fixtures with known answers beat synthetic data
(the precedent: the Ida Central Park value asserted to the hundredth).

Three seams, two existing and one new:

1. **Written-table contract seam (existing — the repo's main seam).** Every
   derived table is tested by DuckDB assertions over the written Parquet: grain
   uniqueness, frozen counts (20,544 registry rows; 15,490 feature rows; the
   41-entrance canary; cells_scored), byte-identical rebuild gates,
   version-stamp chaining, and fixture values (the 2023-09-29 day must appear in
   the spine under the four-literal union; the 149 St rename must resolve).
   Prior art: the existing ref/precip/events/schedule test modules.
2. **Pure-function seam (existing pattern, new functions).** Label derivation,
   the event spine, the live Window walk, and the detector evaluation are pure
   functions tested on fixtures: the Window rule reproduces the offline window
   on a fixture event day; deleting one interior hour trips HOLES/
   INSUFFICIENT_DATA; live eta at Window close equals the offline event eta on a
   replayed event (the converges-from-below contract as an assert); the
   extractor's frozen-rule holdout re-runs against the archiver serialization
   and the remove-water family at ≥ 0.90 precision. Truth-tier parsers are
   tested on captured fixture responses (the 2080-clock response, the
   null-deployment response, a dry-night offsets response) — no network in
   tests, matching the decode-census precedent.
3. **Export-file seam (existing, from the serving build).** Exported GeoJSON/
   JSON read back and asserted: absent keys never nulls, one cycle id across
   the file set, staleness/hole/error states render as data, a deleted live
   root yields error + stale meta rather than a crash, and the model tier
   refuses to render on version skew.

The model's statistical validation (splits, baselines, sweeps) is build-asset
evidence, not pytest — published tables the release links, with the two
headline gates (beats B2 AND B3 location-blocked; else ship B2) asserted by the
release checklist. Canaries run at build time: the four 311 literals have
trailing-30-day rows, the MRMS filename pattern resolves, every frozen source
literal and endpoint answers.

## Out of Scope

- Alerting channels of any kind (standing rule) — LIFTED for flood tiers only
  (Ross's decision, 2026-08-23; scope, policy and message rules in
  `.scratch/notify/spec.md` section 7). Non-flood alerting, bus delay included,
  stays barred and would need its own validation and its own map. Still out:
  public hosting or re-serving of MTA-derived data; hydrodynamic
  sewer/inundation modeling; commercial flood scores; scraping paywalled/ToS-barred news sources.
- NFIP and sewer-backup covariates (no access path owned; the with/without
  discipline is reserved for when they graduate).
- Truth-tier capture pollers (FloodNet/CO-OPS/NWS history of what the panel
  showed) — new poller = new daemon = HITL yes; trigger is a storm review that
  demands them.
- STOFS-2D / P-Surge storm mode and any surge forecast beyond next-high-tide
  anomaly persistence; trigger is a coastal event needing real lead time.
- Sub-hourly RadarOnly features; a fitted coastal model; terrain-connectivity
  terms (flow accumulation / HAND); per-station DSM tiles and LiDAR sill
  heights; the 2010 DEM epoch; InSAR.
- The MTA Climate Vulnerability Assessment retrieval, the Hydro-OU database
  check, MyCoast garnish, historical-GTFS churn reconstruction — all fog with
  named triggers on the map.

## Further Notes

**Load-bearing corrections.** An implementer opening a ticket for detail must
read its comment tail; the corrections that override first text:

| Original claim | Corrected by | Correction |
|---|---|---|
| 01: two 311 descriptor literals, thresholds 97/84 | 10 | FOUR literals (2023-09 renames); p99 re-measured on the union; spine re-derived; descriptor canary |
| 01: alert vocabulary 'flood'/'water cond' | 10 | live LMM family is "remove water from the tracks"; zero live rows match the old literals |
| 01: per-event CSI with intervals; threshold sweep in-fold | 08 | per-event POD + raw FP; threshold sweep is an outer replication |
| 01: label_support {entrance, station, cell}; alerts fan to entrances | 06 | {radius, station, cell}; alerts land once at the complex |
| 02: recall 0.970/0.778 | 10 | measured on a sample selected by the old vocabulary; blind to the remove-water family; re-measure gated |
| 06: bus-stop churn sensitivity method | 08 | unexecutable (no historical Picks locally); replaced by era-restricted negatives + published deltas |
| 08 draft: three models, score_ref CDF as live display | 08 answer / 10 | two models; the CDF is static-view only; live display is the current-vector rank |
| 10 draft: CO-OPS `range=36` forecast; 03:00 stateful reset; absolute FloodNet depth | 10 answer | bare range returns the PAST N hours (begin_date required); stateless backward walk; rise + persistence + status rules |

**Sequencing.** The flood build interleaves with the pipeline build tickets: it
needs the live-precip job (pipeline build, now amended with the catch-up
fetch), the page skeleton and export loop, and the existing ref/precip rails —
and needs neither Kafka nor the streaming job, so the flood panel can ship
ahead of the bus live view. Suggested slice order for /to-tickets: registry →
elevation features → labels + spine (with the 311 re-measure) → AORC flood-era
extension → score + coefficient artifact → coastal layer → detector core
(window walk + evaluation + replay) → truth tiers → panel + exports → impact
overlays. Every slice lands its checks with it.

**Licenses.** FloodNet sensor data is a custom NYU/CUNY non-commercial
agreement with a citation requirement (cite "FloodNet (NYU and CUNY)", Mydlarz
et al. 2024, WRR) — fine for this local, non-commercial project; revisit before
any public artifact. subwaydata.nyc: license not found — local-only, no cloud
copies, derived numbers local-page-only. DEC/DEP services: fetch-and-use fine,
rehosting barred.

**Honesty clauses that survive to the release.** The estimand is
flooded_reported and every public artifact names it. If B2 (unit climatology)
wins the location-blocked headline, v1 ships B2 and both the release and the
live panel say so in the alternate strings. Published FIM systems run CSI
0.26–0.45 — expectations are calibrated to that band, and the FIM comparison
is stamped order-of-magnitude-only. The live panel trails the storm, is
rank-only and uncalibrated in v1, and states the frozen operating-truth string
verbatim, as every flood notification does [notify 01]: "raincheck ranks where a
flood REPORT is likely from rain that has already fallen, on hour-grain evidence
that trails the storm. A rank is not an observation of water, and a quiet panel
or a quiet inbox means nothing was flagged, not that nothing flooded."

**HITL gates.** None open. The two standing daemon approvals (archiver,
live-precip agent) cover everything this spec runs; any capture poller or new
standing process added later re-opens the HITL gate by rule.
