# 10 Real-time detector design — DRAFT (pre-review)

Draft 2026-08-22 (measured live 2026-08-23 00:24-00:35Z). Inherits 08's detector
interface (binding obligations posted on the ticket), 01's window geometry and
truth tiers, 06's score units, 07-pipeline's execution model, 14-pipeline's
serving contract. Ponytail rules apply.

## Measurements this session (2026-08-23 ~00:30Z, dry night, no active storm)

| # | Probe | Result |
|---|---|---|
| M1 | `launchctl` + `ps` | `com.raincheck.archiver` RUNNING (pid 8070 + caffeinate); `data/live/` EMPTY — **precip_live is designed (07) but NOT deployed**; silver has src=aorc backfill months only, no src=mrms |
| M2 | MRMS listing (note: `/data` prefix now 301s; live path is `mrms.ncep.noaa.gov/2D/...`) | RadarOnly_QPE_01H: 2-min stamps, newest 00:28 at 00:31:34Z (~3.5 min lag). Pass2: newest 23:00 at 00:31Z (~60-90 min lag) — Pass2 can never be the live forcing |
| M3 | FloodNet GraphQL `order_by time desc` unbounded | poisoned: sensor `only_wise_mule` stamps **year 2080** (clock-broken), tops every "latest" and passes every `_gte now-N` filter |
| M4 | FloodNet bounded window [now-30m, now+2m], depth>=10mm | on a DRY night: 8+ sensors reporting steady 18-528 mm (box/offset noise), plus rows with `deployment_id: null`. **Absolute depth is not a flooding signal**; freshness of good sensors ~1-2 min; query 0.06-0.24 s |
| M5 | CO-OPS `date=latest`, `datum=NAVD` | reading 7 min old, `q:"p"`, 0.07-0.16 s; Battery 0.76 ft / KP 3.46 / SH 0.47 NAVD (all quiet); `predictions&interval=hilo&range=36&datum=NAVD` works — next highs directly comparable to thresholds |
| M6 | api.weather.gov | keyless w/ User-Agent, `alerts/active?point=` 0.15 s, zone-list form 200; borough UGC anchors: zones NYZ072/073/075/176/074, counties NYC061/005/047/081/085 (`/points` 301s — need `-L`; full zone list = build item) |
| M7 | STOFS points.cwl.nc HEAD | **25.2 MB per cycle** (4x/day) — too heavy for routine polling |
| M8 | 311 erm2-nwe9 live tail | max SJ/SH created_date **2026-07-29** — 25 days stale. 311 is NOT a live tier; also a label-era warning for the build |
| M9 | aq7i-eu5q | newest flood_start_time 2026-08-11 (post-hoc verification tier only, cadence days not minutes) |
| M10 | archiver subway_alerts newest parquet | current hour, `header` text present (02's extractor input), `fetched_at` epoch; capture cadence 300 s |

## D1. What the detector IS: 08's model evaluated live, nothing else

One artifact chain, no reconciliation (08 obligation 1): live eta for every
scored unit = the 08 coefficient JSON (point model on entrances+bus stops,
cell model on cells_scored; complex = max over child-entrance etas). Live
display value = within-kind percentile of eta via the JSON's published
eta->CDF (computed on score_ref), shown as an integer 0-100, capped display
"99+" when eta exceeds the CDF support. RANK-ONLY, uncalibrated v1 (08
obligation 3): no probabilities anywhere on the panel. Estimand phrasing
inherited (obligation 6): the tier is named "flood-report likelihood rank".

## D2. Live forcing: RadarOnly :00 hourly cell-values, and only those

- Source table: `data/live/precip_cell` exactly as 07 designed it (300 s
  LaunchAgent, RadarOnly_QPE_01H at :00 stamps, cell mean via
  cell_pixel[grid_id='mrms'], 7-day retention). **Build dependency, not yet
  deployed (M1)** — the detector rides the pipeline spec's precip_live build
  item; nothing new to approve.
- New hour visible ~:07-:09 (file ~2-4 min after the hour + <=300 s poll).
- Pass2 (~60-90 min lag, M2) never feeds the live path; it remains the
  offline src=mrms.
- The 2-min RadarOnly stamps could give sub-hourly reaction, but a trailing
  1-h accumulation at :26 is NOT the hourly-binned mm_1h the model was fit
  on — a burst split across clock hours reads higher in a trailing window
  than in either bin, which would break 08's converges-from-below contract.
  REJECTED for v1; named upgrade (matches pipeline fog: sub-hourly is "a
  distinct feature").
- Scale honesty: the JSON carries Pass2/AORC 0.86-0.92 as an informational
  constant (08). RadarOnly-vs-Pass2 is an ADDITIONAL unmeasured gap; build
  item: once precip_live has captured a wet month, measure the
  RadarOnly/Pass2 cell-hour ratio on wet hours and record it in the detector
  JSON as a second informational constant. Until then the panel footer says
  "live radar rainfall is uncalibrated; ranks only".

## D3. Event window live: day-anchored running window with a dryness-gated reset (owned here per 08 obligation 2)

- At any instant the live window is [A, now]. A = 21:00 America/New_York of
  the previous NY day (= 01's offline window start, midnight-3h).
- Reset rule, evaluated once daily at 03:00 NY (= 01's offline close,
  midnight+3h): if citywide max cell mm_1h < 1.0 mm across the trailing 3
  hourly stamps (00:00, 01:00, 02:00 NY... i.e. the pad hours), roll A
  forward to yesterday 21:00. Otherwise KEEP the old A — the live analog of
  01's contiguous-event-day merge. Constants (1.0 mm, 3 h, boundary times)
  frozen in the detector JSON.
- Features from the RadarOnly series over [A, now]: running max mm_1h,
  running window total; antecedent mm_24h = sum over [A-24h, A], frozen at A
  (7-day retention covers merges up to ~6 days).
- Convergence: exact for single-day offline events (pre-rain zeros add
  nothing to max/total). For multi-day merges the live rule can disagree
  with the offline spine (which merges on trigger-day labels, unknowable
  live). Build check: REPLAY the rule over the AORC-era spine and publish
  the disagreement rate (fraction of event-hours where live-rule window !=
  offline window, and the feature deltas). Honesty, not hope.
- No separate "event open" decision exists: zeros make window-anchored
  running stats insensitive to when rain starts. Dormant vs active is
  display state (D5 gate + a "quiet" banner when citywide trailing-3h max
  mm_1h < 1.0 mm), never feature state.

## D4. Cadence and staleness

- Model tier recomputes when max(valid_ts) advances (hourly, ~:07-:09);
  the export loop checks each cycle.
- Serving rides pipeline-14's on-demand loop (make live-export / a
  flood-export sibling): 60 s display cycle; per-source fetch throttles:
  FloodNet 120 s, CO-OPS 360 s, NWS 300 s. On-demand only — runs while the
  page is being served, Ctrl-C stops it. No new daemon.
- Staleness budgets (meta.json ages, pipeline-14 STALE convention):
  precip fresh <= 75 min, stale 75-150 (grey the model tier + banner),
  down > 150 (hide model tier, keep truth tiers); FloodNet stale > 10 min;
  CO-OPS stale > 30 min; NWS stale > 15 min. Sources age independently; one
  stale tier never hides another.

## D5. Flag tiers and the rising trajectory (owned here per 08 obligation 2)

- Two flag tiers on the live percentile: ELEVATED at >= 80, HIGH at >= 95,
  gated by unit forcing: the unit's own cell running window total >= 2.0 mm
  (kills dry-day static-exposure flags). Constants frozen in the JSON.
- Monotone latch: running max and total are nondecreasing within a window
  and antecedent is frozen, so if every event-side coefficient is >= 0, eta
  is monotone nondecreasing until reset — flags cannot flap and need no
  hysteresis. The JSON build asserts the sign; if any event-side coefficient
  fits negative, the assertion records it and the latch claim is dropped
  (flags then follow the score both directions, stated in meta).
- Flags clear at window reset (03:00 NY, dry criterion) — never mid-window.
- Late-fire is inherent (converges from below): the panel says "ranks rise
  as rain accumulates; this view trails the storm, it does not forecast it".

## D6. Coastal live layer: deterministic, three gauges, no fitted terms (08 obligation 4)

- Per gauge {Battery 8518750, Kings Point 8516945, Sandy Hook 8531680}:
  6-min obs `datum=NAVD` (M5: 7 min old, direct); margin_ft = obs -
  nws_minor(NAVD, via 05's per-station offsets). Next-high forecast =
  harmonic `predictions&interval=hilo` + anomaly persistence (latest obs
  minus predicted at the same minute, added to the next 2 predicted highs) —
  the standard poor-man's surge nowcast, zero new bytes.
- Gauge chip states: QUIET / APPROACHING (forecast next-high within 1.0 ft
  below nws_minor) / EXCEEDING (obs >= nws_minor). When a gauge is
  APPROACHING+, the assets assigned to it (08's nearest-of-three) recolor
  by their static surge_margin_ft — the rule layer visualized live.
- STOFS-2D-Global: NOT polled routinely (M7: 25.2 MB/cycle). STORM-MODE
  ONLY: fetched when an NWS CF/SS watch+ is active for the frozen UGC list
  or P-Surge's prod directory is non-empty (its non-emptiness is itself a
  displayed signal, per 05). points.cwl.nc station inventory = build item.

## D7. FloodNet truth tier: display/verification only (01's bar, 08 obligation 5)

- Poll GraphQL with a BOUNDED window [now-30 min, now+2 min] (M3: unbounded
  queries are poisoned by a 2080-clock sensor), drop `deployment_id: null`
  rows (M4: they exist), join the daily-cached deployments metadata for
  location/status.
- "Water detected" rule (M4 kills absolute depth): latest depth_proc_mm >=
  15 mm AND rise >= 15 mm over that sensor's own baseline (p10 of its
  trailing 12 h, fetched per candidate sensor only — the wet-now list is
  short) AND newest sample <= 10 min old. Displayed as truth-styled markers
  with depth + trend and a count chip; winter snow caveat chip (03's
  banner). Never an input to eta.

## D8. MTA alert live tier: reported, not predicted

- Read the newest archiver `subway_alerts` parquets (M10: running, header
  text present, <= 5 min fresh), filter 01's flood/water-condition
  vocabulary minus boilerplate/planned-work, run 02's cause-anchored
  extractor (measured precision 1.000), map station -> complex via 06's
  registry. Display chips: "MTA reports: water condition at X" with age.
  Display-only; alert-derived features stay barred from eta (08).

## D9. Output surface: third panel on the pipeline-14 static page (fog graduates here)

- `web/files/flood_live.json` — per-unit: asset_id, kind, percentile, tier,
  window feature values, cell forcing summary; plus window state (A, reset
  history). `web/files/flood_truth.json` — FloodNet markers, MTA chips,
  gauge chips, active NWS products. meta.json gains per-source ages +
  versions. Geometry joined at export from ref/assets / ref/cells exactly as
  14 does for Cells.
- Legends per kind, never mixed (08's cross-kind obligation; per-kind
  event-conditional base rates printed beside the index). Impact signals
  (09): the panel reserves an overlay slot that renders whatever files 09
  publishes (bus cell-hour speed ratios, subway delays), greyed when absent,
  labelled "impact — never a detector input"; detector outputs carry no
  impact fields. Interface only; metric definitions are 09's.
- Local serving only (`python -m http.server`); public hosting stays out of
  scope.

## D10. Compute placement, logging, replay

- Detector evaluation is a pure function (numpy/DuckDB over live/precip_cell
  + the two JSONs); ~17K dot products — microseconds. It runs inside the
  on-demand export loop. NO new daemon, NO new pollers in v1: FloodNet /
  CO-OPS / NWS are fetched at export time only. The sole standing dependency
  is precip_live (already approved in 07, unbuilt, M1).
- Every export cycle appends its computed unit states + fetched truth
  snapshots to `data/live/flood_detector/date=/` (~KB/cycle, 30-day
  retention). Replay guarantee: the model tier is deterministic from
  (precip_cell series, JSONs, clock) for the 7-day RadarOnly retention even
  when nobody was watching; truth tiers replay only when the loop was
  running — stated limitation, capture pollers stay fog (HITL).

## D11. Honest claims (08 obligation 6 + no-ground-truth honesty)

- Fixed panel vocabulary: model tier = "flood-report likelihood rank
  (uncalibrated)"; tooltip: "ranks units by modeled likelihood that flooding
  would be REPORTED under the rain so far, fitted on 2010-2025 reported
  flooding; not a depth, not a certainty". Truth tiers = "observed /
  reported". FloodNet = "water detected at sensor (above its own recent
  baseline)". Footer: RadarOnly uncalibrated note (D2) + "this view trails
  the storm" (D5).
- Never: "flooding likely", bare percentages, mixed-kind rankings, FloodNet
  values presented as model validation in-panel.

## D12. Versioning and constants

- `detector.json` (in-repo, beside 08's coefficient JSON): window-rule
  constants, tier cutpoints, gates, staleness budgets, truth-tier rules,
  endpoint list + UGC list, sign-assertion outcome, and score_version (sha)
  of the coefficient JSON it binds to. detector_version = sha1(that file).
  Both versions stamped in every export and log row.

## Build items handed to /to-spec

1. precip_live deploy (already a pipeline build item; detector depends on it).
2. flood-export job + third panel (D4/D9); UGC zone list freeze script (M6).
3. Window-agreement replay over the AORC-era spine (D3) — published table.
4. RadarOnly/Pass2 wet-month ratio measurement -> detector.json (D2).
5. Live adaptation of 02's extractor over archiver alert parquets (D8).
6. STOFS points.cwl.nc station inventory; storm-mode fetch wiring (D6).
7. Detector log writer + 30-day retention (D10).
8. Sign assertion + CDF-support cap in the JSON build (D1/D5).

## Flags for the map

- M8: erm2-nwe9's live tail measured 25 days stale — a label-era coverage
  warning for the build (01's as-of stamps absorb it, but check before the
  label build; if the Socrata feed died, 311 labels end 2026-07).
