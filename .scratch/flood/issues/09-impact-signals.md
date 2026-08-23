# 09 Impact signals: bus slowdowns and subway delays

Type: grilling
Status: resolved
Blocked by: 01

## Answer

Resolved 2026-08-22 (measured on real day-files; 3-lens adversarial review
in `../assets/09-adversarial-verdicts.json` — 68 verdicts + 27 missing;
Ross pre-authorized the reconciled round, presented with veto rights).
Draft history: `../assets/09-impact-draft.md`. Every probe number
reproduced to the digit by the reviewers; the interpretations and the
plumbing were rebuilt.

**Role (binding).** Impact signals VALIDATE and DISPLAY — never detector
inputs, never model features, never in any version hash, and their
coverage calendars never touch 08's negative universe. Enforced by
comments on 08 (Barred list) and 10 (display-only), not just asserted
here.

**Subway metrics — two, both from the day-files in hand.**
- `service_ratio` = arrivals(complex, bin) / baseline; arrivals = rows
  with non-null coalesce(arrival_time, departure_time), platform suffix
  stripped -> gtfs_stop_id -> complex_id (INNER join; the 24 unmatched
  parent ids are verified non-revenue timing/relay points — frozen canary
  list, count asserted and reported, ~0.7% of rows).
- `max_gap_ratio` = max inter-arrival gap per complex x route x direction
  vs baseline (one LAG window over the same rows; measured to recover
  623 Canal St — gap 20.4x, pr 0.052 — which arrivals miss; combined
  detection 5/7 vs 4/7 on 2023-09-29).
- Estimand honesty: both measure OBSERVED SERVICE as reported by
  subwaydata.nyc — service volume and gaps, not delay-vs-schedule (no
  subway schedule exists in-repo before ticket-15's daily captures), and
  blind to shuttle-bus substitution. Stated wherever the numbers appear.
  A day-level feed-health flag (citywide trips with num_updates > 0)
  distinguishes feed-dark from service-collapse.

**Day-file semantics (measured, was the draft's worst error).** Files are
keyed by trip-START local date (midnight-midnight); arrivals span
[D 00:00, D+1 ~06:00], so local hours 00-05 of day D live mostly in file
D-1 (94% undercount at 00-03 from a single file). Rule: union files D-1
and D, dedupe on (trip_uid, stop_id); service_date = local calendar day
of the arrival (DATE). Baselines: median over K<=4 prior same-weekdays,
union-event days AND DST-transition days excluded (gold.py's DST rule
mirrored), `n_baseline_days` carried, ratio NULL below K=2. Hour grain:
kept for daytime power (measured 17:00 ratios 0.07-0.09 at flagged
complexes) with a minimum-baseline rule — NULL below 5 baseline arrivals
in the bin; overnight hours stated unusable. This baseline is its OWN
convention — the draft's claim that it mirrors cell_hourofweek_baseline
was refuted on all four axes (sums-vs-median, window-vs-rolling,
dry-filter-vs-event-exclusion, DST).

**The validation statistic — route-mix residuals, neighbor controls,
08's shapes.** The raw-ratio tail is dominated by route-level service
decisions (measured: W 0.181, Franklin Shuttle 0.240, B 0.249 citywide;
Park Pl — the deepest complex — has residual p57 once its route mix is
removed; within a cut segment all complexes carry IDENTICAL counts, so
effective-n is line segments, ~3-4 on 2023-09-29). Therefore:
- Primary statistic: `residual_ratio` = actual / expected-from-route-mix
  (expected = baseline route shares x citywide per-route event ratios),
  compared against same-line adjacent complexes in the same hours.
- Per-event reporting: bottom-decile POD + raw FP count (08's convention;
  measured 4/7 with ~40 unlabeled bottom-decile complexes on
  2023-09-29) + pooled event-cluster statistics. Never per-event medians
  over size-1 sets.
- Multi-complex alerts count at ALERT grain (best residual among named
  complexes — 02's entity-grain lesson; resolves the Canal St spread
  p8/p40/p64 from one alert).
- Label-source split (alert-labeled vs 311/FloodNet-labeled) kept as the
  secondary cut behind the neighbor control (the suspension-alert
  circularity is the smaller confound; segment-zeroing is the larger).
- Placebo null: the baseline days' own residual distribution published
  beside each event table (GOs, signal problems, police activity all
  crush arrivals without flooding). Snowmelt-reclassed days excluded,
  aligned with 08's fit exclusions.
- Honest set-level result carried forward: all SEVEN 02-flagged complexes
  for 2023-09-29 have median percentile 0.083 (4/7 below p10, 3/7 at
  p36-p64); line-block permutation P ~ 1e-4. Real, but ~4 service
  decisions, not 10 independent stations.

**Coverage magnitudes (the ticket's headline honesty numbers, measured).**
Of 115 union (a)∪(b) event days: subway coverage 35 (30%); of the 71
station-labeled days, 20 (28%) are >= 2021-04-01. Bus coverage = the
BASELINED WINDOWS w1/w2, not the speed months (measured: 2021-10-26 has a
month partition ending 10-16 — no coverage): 6/115 days (5%), ~3 merged
events incl. both reference storms. 80/115 union days (70%) have neither.
Impact validation is deep on {Ida, 2023-09-29} and subway-only on ~28
more events. Pre-2021-04: subway impact ABSENT, stated in every table.
These calendars are impact-only.

**Bus reuse (confirmed, three corrections).** Ratio = merged sums
(sum dist_m_sum / sum dt_s_sum per cell-hour over routes) / speed_dry;
grain is (cell, hour_end_utc, route_id, route_class); window statistics
merge sums across hours — NEVER averages of per-hour ratios (the
mean-of-means bug pipeline-14 already fixed once); the post-storm
citywide depression (0.80-0.90 after rain ends, pipeline-10's measured
recovery effect) means the citywide same-window distribution is the only
reference — no absolute thresholds. w3/2026 baseline window = conditional
build item handed to 10 (live bus numerator exists in month=2026-08;
denominator does not).

**Storage: no new Silver table.** The draft's silver/impact_subway_hourly
had no consumer (validation views are build assets; the live path is
10's) and the whole corpus aggregates from raw CSVs in ~44 s (measured
0.14 s/day). Impact outputs = build assets linked here, stamped with the
day-file sha256 manifest + constants (K, exclusion set, min-baseline).

**Snapshots: `data/ext/subwaydata/` — deliberately OUTSIDE data/archive.**
Two measured collisions forced the move: (1) Makefile `coldpush` syncs
all of data/archive to R2 — license-unknown third-party bytes would be
rehosted automatically; (2) archiver BUDGET_BYTES counts every byte under
data/archive (10 GB; capture alone runs ~0.59 GB/day). Store the tar.xz
as fetched (~1 MB/day; unpack transiently), manifest = our sha256 +
fetched_at + resolved hash-URL per file; fetch-only-when-missing. Fetch
list is a FORMULA: files({window days ∪ baseline days} ∪ their D-1
predecessors) — 312 files / ~359 MB today for (a)∪(b), recomputed when
(c)/(d) are enumerated and when 08's p98/p99.5 outer replication mints
new days. Full-mirror rejected on YAGNI + 1,963 hash-redirect round trips
(the draft's ~9 GB disk argument was stale — 43 GiB free today).

**License (map-recorded, 03/04 precedent).** subwaydata.nyc data license
NOT FOUND (research/subway-rt-archives.md, verified): fetch-and-use,
local-only, NO cloud copy, NO rehosting; derived per-complex numbers
appear on the local page only (map's Out of scope already bars public
re-serving of MTA-derived data); revisit trigger: a license is published.

**Live counterpart -> ticket 10 wholesale (obligations posted there).**
subwaydata.nyc lags 7-31 h (updated ~07:00 next day) — unusable live;
the ticket-15 TU capture stores per-poll PREDICTIONS with no marked_past,
so realized arrivals need a disappearance-inference pass = a named build
item with its own error profile, and a LEVEL COMPARISON on overlapping
days (2026-08-17.. vs subwaydata; month=2026-08 is also the only
bus/capture overlap) is required before any cross-src display. srcs never
pooled; capture baselines accumulate from capture days only (NULL until
K>=2). 09 defines the metrics; 10 owns computation, staleness,
thresholds, and unit-grain display reconciliation (bus_stop units have no
own impact -> cell fallback; never two kinds in one legend).

**Cross-effort flag (not this ticket's to fix).** The running archiver
hits STOPPED_BUDGET ~2026-09-02 at the measured capture rate (3.7 GB in
6.3 days vs 10 GB default) independent of anything here — a prune/budget
decision for the build effort now that cold storage is live.

## Question

How the two transit impact measures are computed and joined to flood events for
validation (impact, never detector input): bus = raincheck Gold
`cell_hour_speed` ratios (already built for Ida and 2023-09-29 by pipeline 10);
subway = per-station delay/headway during event windows from subwaydata.nyc
per-trip CSVs (2021+, ~1 MB/day, keyless) and the ticket-15 TU capture
(2026-08-16+). Decide the subway delay metric (observed headway vs scheduled?
arrival gaps at flagged stations?), the event-window join grain (station-hour vs
Cell-hour), and whether a subwaydata.nyc backfill for the label-era event days
becomes a build item (a few hundred day-files) or only the two storm windows.
