# 10 Real-time detector design

Type: grilling
Status: resolved
Blocked by: 03, 05, 08

## Question

The live detector: inputs (MRMS RadarOnly live Cell-hours via the pipeline-07
`precip_live` agent, FloodNet live readings, CO-OPS 6-min obs, NWS coastal/flash
flood products from 05), how it relates to the static score (detector =
score x live forcing? separate thresholds?), output grain (Cell + station +
whatever 06 decided for segments), update cadence and staleness rules, what
"likely flooding" claims honestly given no ground truth at decision time, and
how bus-slowdown / subway-delay impact signals are displayed alongside without
feeding the detection. Any new poller is a new daemon = HITL yes; serving stays
local (likely a panel on pipeline 14's static page — that part may graduate
from the fog here).

## Answer

Resolved 2026-08-22 (measured live 2026-08-23 00:24-00:55Z; 3-lens adversarial
review in `../assets/10-adversarial-verdicts.json` — 45 verdicts + 24 missing
items; the review overturned the draft's display semantics, window rule,
coastal forecast query, and alert vocabulary, and surfaced a 311 label
amendment bigger than the draft's own reading; Ross's pre-authorized round,
presented with veto rights). Draft history: `../assets/10-detector-draft.md`.

**What the detector is.** One artifact chain, no second model: live eta per
score unit (complex = max over child-entrance etas with 08's zero-ok-children
fallback and flags carried; bus stops; cells_scored) from 08's coefficient
JSON on live RadarOnly forcing. **Displayed value = within-kind rank of live
eta across the CURRENT live eta vector** (a sort at export, "top X% of
<kind>") — the draft's score_ref-CDF percentile was REFUTED (a cross-unit CDF
at frozen forcing fed a live eta is a citywide-rainfall readout in rank
costume: sub-typical storms read ~0 everywhere, severe storms tie at 99+
exactly when ordering matters). The score_ref CDF stays on the STATIC
exposure view, which is also the dormant display: quiet weather shows
gold/flood_exposure's score_index ("static exposure under a typical trigger
storm"); the live rank takes over when the window is active. Stated on-panel:
within a Cell the live ordering is purely static (one shared forcing;
06 measured mean 12.9, max 67 stops/Cell).

**Forcing.** `data/live/precip_cell` RadarOnly :00 stamps only (hourly bin =
the model's mm_1h; the 2-min trailing stamps straddle clock-hour bins and
would converge from ABOVE — rejected, stays pipeline fog as a distinct
feature). AMENDS the precip_live build item: each run lists the source dir
and fetches EVERY missing :00 stamp within the source's measured ~25 h
retention (769 files / 25.6 h span, all 26 hourly stamps present), not
newest-only — sleep holes become healable instead of permanent. Window
coverage = present/expected stamps over [A, now] and [A-24h, A]; NULL
(negative-value) hours count as missing and are excluded from sums — never
zero. HOLES is its own panel state, distinct from staleness. Pass2 (measured
60-90 min lag) never feeds the live path; RadarOnly/Pass2 wet-month ratio is
a build item into detector.json; the within-kind rank is bias-tolerant, the
footer keeps the uncalibrated note.

**Window (08 obligation 2, owned here).** STATELESS backward walk recomputed
every cycle — the draft's loop-maintained 03:00 reset was refuted (undefined
on missing pad stamps both ways: NULL-comparison latches the window open on
a data-less night, coalesce-to-zero collapses it mid-storm; and state kept
by an on-demand loop contradicts determinism). A(now) = the most recent
21:00 America/New_York boundary (UTC-pinned hour_ends; DST handled by
converting the NY-local date once) whose three preceding pad hour_ends are
all dry citywide; else walk back a day; HARD CAP 6 days (window_capped
state, tier degraded). Dryness = wet-cell count < K at >= 1.0 mm (citywide
MAX refuted: one clutter cell in 1,336 latches the window; K frozen at build
from a measured dry week). Pad stamps missing -> INSUFFICIENT_DATA: hold A,
degrade the tier, never silently reset or latch. Running max mm_1h / window
total over [A, now]; antecedent mm_24h over [A-24h, A], frozen at A,
PERSISTED in window state with its own coverage fraction (< 0.75 ->
degraded; 08 forbids NULL scores). Convergence stated honestly: exact when
the pad was dry and the series is unrevised; live can converge from ABOVE
when the pre-anchor evening was wet but sub-trigger (counterexample in the
verdicts). Build item: AORC-era replay publishing the SIGNED live-minus-
offline delta per feature plus per-event tier flag volumes (POD + raw FP,
08's convention) — the replay is what freezes K and the cutpoints.

**Tiers.** On the live within-kind rank: ELEVATED = top 10%, HIGH = top 2%
(flag volume bounded by construction; constants provisional until the
replay measures per-event volumes; if FP volume is unacceptable v1 ships
rank-only with no tiers). Gates, both LATCHED within a window: unit's cell
window total >= 2.0 mm; citywide window active. Monotone-latch claim
restated conditional: nondecreasing given non-negative event-side
coefficients (asserted at JSON build) AND an unrevised series — latest-
fetched_at-wins revision is the designed read, so a downward revision is
logged and never clears a flag. Flags DIM (never vanish) when the citywide
wet-cell count has been < K for 3+ h, labelled "rain ended Xh ago"; they
clear at window roll. WINTER GATE: one api.weather.gov KNYC obs per cycle;
temp <= 0.5 C suppresses the tiers and labels the model tier "fitted on
rain — snow not modeled" (01's snowmelt exclusion, live analog; t2m_c is
NULL in the MRMS era, so this is the only phase signal).

**Coastal (deterministic, 08 obligation 4).** Three gauges {Battery, Kings
Point, Sandy Hook}: 6-min obs `datum=NAVD` direct (measured 7-min age),
shown "preliminary" (q:"p"); per-station threshold family frozen with the
Kings Point NOS/NWS inversion noted; build assert: the stage constant
EQUALS the one 08 froze for surge_margin_ft. Forecast: harmonic hilo with
`begin_date=<now UTC>&range=36` — the draft's bare `range=36` was REFUTED
by measurement (it returns the PAST 36 h); exact query strings frozen in
detector.json. Anomaly = mean(obs - pred) over the last 30-60 min (6-min
stamps align), persisted onto the next high <= 12 h out only. APPROACHING
= forecast next-high within 1.0 ft below nws_minor; EXCEEDING = obs >=
nws_minor; gauge-outage chip state defined (age from the returned t, grey
on error, never silent last-good). Assets assigned to an APPROACHING+
gauge recolor by static surge_margin_ft. CUT to fog: STOFS-2D (25.2
MB/cycle measured) + points.cwl.nc inventory + P-Surge storm mode (its
non-empty directory is an Atlantic-basin signal, not NYC) + the UGC freeze
script — trigger: a coastal event that needs forecast lead time. NWS
active-alerts stays: one call, five-borough UGC constants (NYZ072/073/075/
176/074, NYC061/005/047/081/085) in detector.json.

**FloodNet (truth tier, display/verification only — 01's bar stands).** One
bounded GraphQL query [now-60m, now+2m] per cycle (unbounded REFUTED: a
clock-broken sensor stamps year 2080 and tops every unbounded sort/filter;
`deployment_id: null` rows measured and dropped). Rule computed inside that
single response — no per-sensor baseline fan-out (the draft's trailing-12h
p10 was refuted: it straddles the nightly 23:30 recalibration, misses boxes
arriving inside the window, and fans out under storm load): latest
depth_proc_mm >= 15 mm AND rise >= 15 mm within the window AND >= 3
consecutive samples above AND recent onset; nulls dropped (documented
dropouts); sensor_status blacklist {noisy, signal, dead, low_charge,
hardware_issue, needs_*} from the daily-cached deployments; concurrent rain
in the sensor's own cell as a DISPLAY gate (display, not eta — legal).
Reporting-and-dry sensors render dim with 01's exact phrase ("dry above
curb height at the signpost", never plain "dry"). API error greys the tier
— never an absolute-depth fallback (measured dry-night standing offsets
18-528 mm). Caption names obstruction-under-sensor alongside snow.

**MTA alerts (reported tier).** The draft's vocabulary was REFUTED by
measurement: 449,737 captured rows, 2026-08-20..23, contain ZERO
'flood'/'water cond' alerts; the live family is "remove water from the
tracks" (10 alert_ids captured; 35 event_ids on Socrata with none carrying
the frozen literals), 02's extractor is structurally blind to it, and
informed-entity is no shortcut (stop_id NULL in 104/104 water rows). v1:
LIVE vocabulary frozen in detector.json anchored on the remove-water
clause, scan header AND description, extend 02's anchor set and re-measure
precision on the family BEFORE the chip ships (build gate >= 0.90); one
chip per incident (01's dedupe keys), first-seen time shown, active vs
cleared ("while"/"after") distinguished. Display-only; alert-derived
features stay barred from eta. Amendments posted on 01 and 02 — this is a
label-set recall hole, not only a display bug.

**311 rename (review finding, amends 01).** erm2-nwe9 is ALIVE (max
created_date 2026-08-21); the SJ/SH descriptors were RENAMED upstream:
'Flooding on Street' (1,352 rows since 2023-09-28) and 'Flooding on
Highway' (39) run to now while the frozen literals die 2026-07-29/21 —
~1,391 rows invisible back to 2023-09-28 INCLUDING the 2023-09-29
reference storm, and the frozen p99 thresholds (97/84) are biased low
across the overlap era. Amendment posted on 01 (four-literal set + era
note, p99 re-measured on the union, spine re-derived, descriptor canary).
311 remains NOT a live tier (renamed or not, the tail is weeks stale).

**Serving.** Third panel SECTION inside pipeline-14's page (that fog
graduates here): ONE loop — the flood tick joins 14's 30 s live-export loop
— one meta.json (flood keys merged by the single writer; no sibling
process, no second clock; cycles cannot overlap by construction). The
flood tick skips work unless max(valid_ts) advanced or a truth throttle
expired (FloodNet 120 s / CO-OPS 360 s / NWS 300 s); every fetch has a
hard 3 s timeout (all sources measured 0.06-0.25 s), last-good kept with
its own age, per-source error chips, one hung socket never stalls the bus
panel. Files: `flood_cells.geojson` (all cells), `flood_points.geojson`
(SCORE UNITS at ELEVATED+ only — entrances are never published; they
inherit their complex for display per 06/08), `flood_truth.json`; written
through 14's pure-SQL json_merge_patch path from a DuckDB temp table
(absent keys, never nulls — the MapLibre grey-guard rule), payload-then-
meta via os.replace, a failed tick leaves the payload and only meta goes
stale, one cycle_id stamps all files. Absent/down renders defined: truth
tiers plus "model tier unavailable since T". Staleness budgets: precip
fresh <= 90 min FROM valid_ts (healthy worst case measured ~68.5 min),
stale 90-180, down > 180, holes indicator separate; FloodNet > 10 min,
CO-OPS > 30 min, NWS > 15 min. Cross-map note for /to-spec: the panel
edits 14's index.html/export.sql — sequenced with 14's build, and the
flood panel's critical path (precip_live + 08's JSON + ref/assets + page
skeleton) needs neither Kafka nor the streaming job, so it can ship AHEAD
of the bus live view.

**Impact overlay (09's binding obligations honored).** Contract:
`web/files/impact_bus.json` (cell grain) and `impact_subway.json` (complex
grain), keys (cell | complex_id, hour_end_utc), last CLOSED hour under
pipeline-08 ceil_hour; written by 09's export step in the same loop; the
panel renders them when present, greys when absent; bus_stop units take
the cell fallback; never two kinds in one legend; labelled "impact — never
a detector input". The panel WANTS live bus impact, which activates 09's
conditional w3/2026 cell_hourofweek_baseline build item (never w1/w2);
subway ratios stay NULL until K >= 2 same-weekday capture baselines exist
and no cross-src display before 09's level comparison; subwaydata-derived
numbers stay local-page-only (09's license rule).

**Claims (08 obligation 6 + the estimand's confound, which the draft
omitted).** Headline label "flood-report exposure rank" — 'likelihood'
dropped; display "top X% of <kind>" / "rank N of M", never a bare 0-100
integer. Always-visible sentence: "This ranks where a flood REPORT is
likely, not where water is deepest — places whose residents report more,
and places with more stops and more prior calls, rank higher for that
reason." Window named in the tier label ("under the rain since <A,
local>"); degraded strings fixed ("ranks computed on N of M rainfall
hours"); per-kind base rates reworded so they cannot read as this-unit
probabilities ("in the fit era, X% of this kind were reported flooded
during a trigger event"); the within-cell static-ordering note; and the
operating truth: "a page you open during a storm, not a service that
watches." B2-honesty branch designed now: alternate panel strings in
detector.json keyed by the shipped model id ("where flooding was reported
before, scaled by current rain") — 08's if-B2-wins clause has a live face.

**Logging (draft's ~KB/cycle refuted — off by ~3 orders).** Slim NDJSON,
one file per day: full unit-state vector only when the model tier
recomputes (~24/day) + the flagged subset per cycle + truth snapshots on
change; ~3 MB/day, <= ~100 MB at the 30-day prune (on loop start), inside
05's 10 GB loud stop with the arithmetic stated. A torn last line costs
one row. Replay claim conditional on the catch-up fetch; capped or
insufficient-data windows are NOT replayable — stated.

**detector.json.** In-repo, beside 08's coefficient JSON: window-rule
constants (boundaries, K, 6-day cap, pad definition), tier cutpoints +
gates, staleness budgets + missing-hour policy, MRMS product string +
filename-pattern canary, mrms cell_pixel crosswalk sha, precip_live
retention + NULL rule, live alert vocabulary + scanned fields, gauge
threshold family + NAVD offsets + inversion note + exact query strings,
winter-gate constants, UGC list, alternate claim strings.
detector_version = sha1(file). The exporter loads BOTH JSONs and stamps
both digests — no copied score_version (clerical chaining refuted);
version skew -> the model tier refuses to render; a coefficient swap
mid-window forces a window roll, logged.

**Runnable checks (named).** (1) Fixture replay: live eta at window close
== offline event eta on one event day — 08 obligation 2 as an assert.
(2) The window rule reproduces 01's window on a fixture day; deleting one
interior hour trips HOLES/INSUFFICIENT_DATA. (3) The export emits absent
keys not nulls and survives a deleted live root with error + stale meta.
(4) Extractor live-parity: the frozen-rule holdout re-run over archiver
parquet serialization + remove-water-family precision >= 0.90. (5)
Canaries: all four 311 literals have trailing-30-day rows (build), the
MRMS filename pattern resolves, the mrms crosswalk covers every
cells_scored cell (the 08-style NULL-cell assertion, MRMS edition). (6)
Coastal: threshold stage equals 08's constant; the forward hilo query
returns future stamps.

**Build items handed to /to-spec.**
1. precip_live AMENDED: catch-up fetch of all missing :00 stamps within
   the ~25 h source retention.
2. Flood tick in 14's loop + third panel section (edits 14's page +
   export.sql) + the three flood files and writer rules.
3. AORC-era replay: signed feature deltas + per-event tier volumes ->
   freezes K and the cutpoints.
4. RadarOnly/Pass2 wet-month ratio -> detector.json.
5. Live alert vocabulary + 02 extractor extension + precision gate +
   incident dedupe.
6. w3/2026 cell_hourofweek_baseline (activated for 09's bus overlay).
7. Winter-gate wiring (KNYC obs call).
8. detector.json builder + sign/stage/CDF assertions + canaries + checks.
9. Slim NDJSON log + prune-on-start.

**Cut from v1 (fog, with triggers).** STOFS-2D / points.cwl.nc / P-Surge
storm mode (trigger: a coastal event needing forecast lead time);
FloodNet/CO-OPS/NWS capture pollers (trigger: post-event truth replay
demanded; new poller = new daemon = HITL yes); sub-hourly RadarOnly
features (pipeline fog, a distinct feature).

## Comments

2026-08-22 — obligations and interface from 08's resolution (binding):
(1) The detector consumes 08's in-repo coefficient JSON — coefficients,
preprocessing constants, feature definitions, per-kind eta->percentile
CDFs, reference forcings, score_version. One model, no reconciliation.
(2) Every event-side feature is a trailing/running statistic (running max
mm_1h, running window total; antecedent mm_24h frozen at event open), so
live evaluation uses IDENTICAL definitions and the live score CONVERGES to
the event score from below as the window fills — 10 owns the event-open
definition and the thresholding of a rising trajectory.
(3) Live output is RANK-ONLY and uncalibrated v1: the model is fitted on
src=aorc; live MRMS inputs run 8-14% low (pipeline-08's measured Pass2/
AORC band 0.86-0.92, carried in the JSON as an informational constant).
Never present live numbers as probabilities.
(4) The coastal layer is deterministic (surge_margin_ft vs assigned gauge
threshold); live CO-OPS obs compare against the SAME per-station NAVD88
thresholds — no fitted coastal terms exist.
(5) FloodNet live readings remain truth-tier: display/verification only,
never a detector input feature (01's bar).
(6) "Likely flooding" claims inherit the estimand: the model predicts
flooded_REPORTED; phrase live claims accordingly.

2026-08-22 — display obligations and facts from 09's resolution (binding):
(1) Latency: subwaydata.nyc updates ~07:00 next day (7-31 h lag) —
unusable live; the ticket-15 TU capture is the ONLY live subway path.
(2) The capture stores per-poll PREDICTIONS (no marked_past /
last_observed); realized arrivals require a stop-time-disappearance
inference pass — a named build item — and a LEVEL COMPARISON against
subwaydata.nyc on overlapping days (2026-08-17..) is REQUIRED before any
cross-src display. srcs never pooled; src=capture baselines accumulate
from capture days only, ratio NULL until K>=2 same-weekdays exist.
(3) Metrics are 09's: service_ratio + max_gap_ratio at complex grain,
route-mix residual for any flood attribution; estimand = observed service
per the feed, blind to shuttle substitution — phrase panel claims
accordingly.
(4) Bus impact live has a numerator (cell_hour_speed month=2026-08) but
NO denominator — a w3/2026 cell_hourofweek_baseline window is a
conditional build item IF the panel wants live bus impact; never borrow
w1/w2 (cross-era baseline).
(5) Hour alignment: last CLOSED hour_end_utc under pipeline-08's
ceil_hour; unit-grain display: bus_stop units have no own impact (cell
fallback); never two kinds in one legend (08's rule).
(6) Impact is display/validation ONLY — never a detector input (09's bar,
also recorded on 08).
