# 01 Flood-event label set design

Type: grilling
Status: resolved

## Question

What is the canonical flood label table? Grain (event x location x time — and is
time an hour, a day, or an event window), which sources union in (311 unioned
2010-2026 ~395K rows, MTA alerts 2012-2026 with the measured dedupe keys, USGS
high-water marks, NOAA Storm Events, CO-OPS exceedances, Sandy zone polygons,
NFIP claims at block-group, FloodNet, MyCoast), per-source trust tiers (311 =
dense-but-noisy, FloodNet/HWM = high-confidence), what counts as one "event"
(clustering rule across sources and days), and the storage shape under the
pipeline-09 Silver conventions. Also: does the historical event spine (dated
event list for validation splits) fall out of this ticket or graduate as its own.

## Answer

Resolved 2026-08-22 (measured 311/alert series live; 3-lens adversarial review
in `../assets/01-adversarial-verdicts.json` refuted the first draft's event
spine, severity ordinal, and precip-join claims; Ross: yes to all
recommendations). Draft history: `../assets/01-label-draft.md`.

**Tables (three layers, sizes justify single files).**
- `silver/flood_obs` — one GeoParquet 1.1 file (~60K rows), sorted
  (source, ts_utc), label-grade sources ONLY: 311 SJ/SH points, FloodNet flood
  events, alert station labels, USGS high-water marks, Sandy inundation
  polygons. Columns: source, source_id, ts_utc, obs_ts_kind
  {incident,report,alert}, geom, cell (H3 res 8 of the point / polygon
  centroid), depth_mm (nullable, only where the source measures it), text
  (nullable). Covariate sources (NFIP, sewer backup SA, catch basin SC,
  MyCoast) never enter this table — 08 reads them from their own tables.
- `silver/flood_events` — the event spine (derived over Silver, so not
  `ref/`): event_id = ISO date of first event-day (deterministic on rebuild),
  day_start/day_end (America/New_York, tz-aware — DST days are 23/25 h),
  window_start_utc/window_end_utc (both hour_end values, ceil_hour semantics),
  trigger booleans by_311/by_alert/by_storm/by_tide, event_class, per-source
  coverage flags where a source was dark, label_version.
- `gold/flood_labels` — POSITIVES ONLY: asset_id, event_id, cell, source_mix
  bitmask, n_311, depth_mm + depth_source (nullable), first_obs_utc,
  label_support {entrance,station,cell}. No severity ordinal (it would rank
  sources, not severities). Negatives = anti-join (ref/assets x flood_events
  LEFT ANTI JOIN flood_labels) generated at consumption. label_version = sha1
  of (311 as-of date, alert as-of date, frozen thresholds, RADIUS_M).

**Event spine.** A day (America/New_York) is an event-day if ANY of:
(a) 311 count, descriptor IN ('Street Flooding (SJ)','Highway Flooding (SH)')
    — exact literals, never LIKE '%FLOOD%' (catches ~8.7K street-light rows) —
    >= frozen nearest-rank p99 per source dataset: **97/day** on `76ig-c548`
    (2010-2019), **84/day** on `erm2-nwe9` (2020+; base dataset, not the
    9qq5-d465 view), measured 2026-08-22, stamped frozen_at. p95 (37/29)
    rejected for v1; Irene enters via (c).
(b) >=1 subway-alert flood event (event_id post-2020 / status_id pre-2020,
    both "flood" and "water cond" phrasings) that NAMES >=1 station via 02's
    extractor; boilerplate flood-reminder footers and flood-mitigation/
    planned-work rows excluded; a system-wide-only alert day does not trigger.
(c) NOAA Storm Events EVENT_TYPE IN ('Flash Flood','Flood','Coastal Flood'),
    county rows via FIPS 36005/36047/36061/36081/36085, zone-coded rows
    (all coastal) via the enumerated CZ_NAME strings in the vault doc.
(d) CO-OPS `hourly_height` fetched `datum=STND` at Battery 8518750 or Kings
    Point 8516945, >=2 consecutive readings above that station's own
    floodlevels.json `nws_minor` (10.49 / 22.89) — same datum both sides, no
    arithmetic; <=365-day request chunks; gauge gaps recorded as
    coverage=missing, never an implicit non-event. Jamaica Bay/Rockaway has no
    gauge: documented blind spot (FloodNet's 55 coastal sensors partially
    cover it 2020-11+).
Contiguous event-days merge. Window = [NY-midnight of first day -3h,
NY-midnight after last day +3h] -> UTC hour_end bounds — deterministic, never
observation-derived (circularity refuted). Class: Storm Events FLOOD_CAUSE
where present; else coastal iff by_tide/Coastal-Flood-only, pluvial iff
by_311/by_alert/Flash-Flood, mixed iff both; Dec-Mar pluvial days with spine
t2m_c <= 0 reclass **snowmelt** (kept, excluded from pluvial training);
unclassified where the spine lacks coverage. GDELT stays out.

**Source roles.** Label-grade: 311 SJ/SH; FloodNet via Socrata event table
`aq7i-eu5q` (2,929 detected events 2020-11-16..2026-08-11 with
flood_start/end_time + max_depth_inches x25.4 -> mm; geometry joined on
sensor_id to the DEP sensor-location dataset, trailing-space quirk; NOT the
10k-row-capped raw API), FloodNet is TRUTH and therefore no FloodNet-derived
feature may enter 08's model; alert station labels PROVISIONAL, gated on 02
measuring precision >= 0.90 (below: demoted to garnish); USGS HWMs; Sandy
polygons (contains, that event only; per-event reporting in 08 keeps it from
owning the positive class). Spine-only: Storm Events, CO-OPS. Covariate-only:
NFIP (as-of cutoff strictly before each window; top-loss-days cross-checked
against the spine as a build check, not a trigger), 311 sewer backup + catch
basin, MyCoast. Bus flood alerts (665+472 rows) REJECTED as labels — route
grain, no point geometry; revisit only if segment-grain labels starve.
Coverage constants (code, not per-row flags): 311 2010-01-01+; alerts
2012-10-02..2020-03-31 + 2020-04-28+ (hole 2020-04-01..27, flood signal
effectively 2016+, Socrata tail ends 2026-06-29 vs archiver capture from
2026-08-16); FloodNet events 2020-11-16+; Storm Events 1996+.

**Attachment.** One constant RADIUS_M = 100 m, geodesic per pipeline-09,
identical for every point source (311, HWM, FloodNet sensor); Cell-grain asset
attaches by H3 equality; Sandy polygon by contains (points) / intersects
(Cells); alert station -> GTFS stop_id -> complex_id -> entrances directly, no
radius, rows carry label_support='station'. 311 rows with null/(0,0)
coordinates dropped, fraction reported (~2.4%). The {50,100,200} m sweep is a
named build item in 08, run inside the fold, full table published.

**Estimand and validation handoff (written into 08).** The default target is
`flooded_reported` — P(a report/detection is generated), stated plainly, not
P(asset floods). Observed-negative tier = an active in-radius FloodNet sensor
with no overlapping aq7i-eu5q event ("dry above curb height at the signpost",
never plain "dry"); observed subset reported separately from unlabeled, never
pooled into one CSI. 08 obligations: per-event CSI with intervals beside the
pooled number, errors clustered by event (pipeline-10 convention), radius +
threshold sweeps, precip-gap eras held out not imputed (no spine before AORC's
era; 2026-01-01..08-13 gap), detectability anti-join from sensor active
ranges + 02's parseability.

**Units/joins.** Pipeline-09 storage verbatim. Depth mm canonical (aq7i
inches converted at ingest); elevation columns belong to 07, not here. The
precip join is NOT free: explicit event-hours expansion
generate_series(window_start_utc, window_end_utc, 1 hour) joined on
(src, cell, hour_end_utc), src pinned per read, srcs never pooled.

## Comments

2026-08-22 — PAUSED mid-work (Ross going offline), ticket stays claimed.
State: measurements done (311 daily series, alert event clustering — numbers in
`assets/01-label-draft.md`); draft design D1-D6 written; 3-lens adversarial
review complete with heavy findings — D2 (event spine) refuted by all three
lenses, D3/D5 refuted or amended, ~40 missing-decision items. Draft:
`assets/01-label-draft.md`. Full verdicts: `assets/01-adversarial-verdicts.json`.
Next step on resume: fold verdicts into a revised draft, then the numbered
round to Ross. No numbered round has been presented yet; nothing resolved.
2026-08-22 (later) — resumed after Ross's "yes to all"; Answer recorded above,
ticket resolved; obligations propagated into tickets 02 and 08; event-spine fog
graduated into the Answer; new fog added (NB-offset trigger upgrade,
forcing-trimmed windows, Rockaway gauge blind spot, bus-alert revisit).
2026-08-22 — AMENDED by 06 (Asset registry design), Ross yes-to-all:
(a) the negative generator runs verbatim over the mixed-kind `ref/assets`
(now including 4,113 cell rows) with a per-kind grain filter — score units
only (complex, bus_stop, cell); (b) `label_support` enum renamed
{entrance, station, cell} -> **{radius, station, cell}** (no legal value
existed for bus stops, 84% of point assets); (c) `label_version` gains an
**assets_version** term (sha1 over sorted (asset_id, kind, lat, lon)) so a
registry rebuild forces a label-version bump; (d) alert-station labels land
as ONE row at `stn:<complex_id>` with label_support='station' — not fanned
to entrances (the "-> entrances directly" clause is superseded; entrances
inherit for display). Radius attachment targets are entrance/bus_stop/cell
rows only. Detail: issues/06-asset-registry.md.
2026-08-22 — AMENDED by 08 (Exposure score design), measurement-backed:
(a) the "311 threshold sweep run inside the fold" obligation is incoherent
as written — the threshold DEFINES the event spine, so changing it changes
fold membership; it becomes an OUTER replication (spine re-derived per
setting, compared on the common-event subset). The RADIUS_M sweep stays
in-fold (events fixed, labels re-derived from silver/flood_obs).
(b) "per-event CSI with intervals" is replaced by per-event POD + raw FP
count plus an event-cluster bootstrap CI on the POOLED statistic — 61% of
station-labeled alert events carry exactly ONE positive (measured
{1:43, 2:11, 3:7, 4:4, 5+:6}), so per-event CSI degenerates to a scaled
Bernoulli and a per-event interval has nothing to resample.
(c) the detectability anti-join is operationalized as per-source coverage
calendars (311 continuous; alerts effectively 2016+ minus 2020-04-01..27
and the 2026-06-30..08-15 Socrata-to-archiver dark gap; FloodNet
2020-11-16+): a negative pair is valid iff >=1 source covering that unit
kind was active — NOT "sensor active ranges" alone, which would delete
every pre-2020-11 negative.
(d) the NFIP/sewer-backup covariate obligation is carried but deferred to
fog (no ticket owns NFIP access); the v1 history covariate is own-source
SJ/SH trailing density with the same strict as-of + with/without
discipline.
(e) Sandy polygon labels stay in silver/flood_obs and gold/flood_labels
but are EXCLUDED from 08's fitted models (one coastal event would mint
~250-350 of ~1,350 cell positives); they validate the coastal rule layer
descriptively. Detail: issues/08-exposure-score-design.md.
2026-08-23 — AMENDED by 10 (Real-time detector design), measurement-backed:
(a) the 311 SJ/SH descriptor literals were RENAMED upstream. erm2-nwe9 is
alive (max created_date 2026-08-21) but 'Street Flooding (SJ)' ends
2026-07-29 and 'Highway Flooding (SH)' 2026-07-21; the successors
'Flooding on Street' (1,352 rows since 2023-09-28) and 'Flooding on
Highway' (39 rows since 2023-09-29) run to now. The frozen two-literal set
loses every 311 label after 2026-07 AND ~1,391 rows back to 2023-09-28 —
including the 2023-09-29 reference storm — and the frozen p99 day-count
thresholds (97/84) are biased low across the overlap era. Amendment: the
literal set becomes FOUR descriptors with an era note, the p99 thresholds
are re-measured on the union per era-dataset, the spine is re-derived, and
a descriptor canary (every frozen literal has rows in the trailing 30
days) joins the build checks.
(b) the alert flood vocabulary has a measured recall hole: the live LMM
alert family phrases flooding as "remove water from the tracks" (10
alert_ids in the archiver capture 2026-08-20..23; 35 distinct event_ids on
Socrata) and NONE of those carry 'flood' or 'water cond' in the header —
the (b)-trigger and the station labels are blind to the family. Vocabulary
extension + precision re-measure handed to 02. Detail:
issues/10-realtime-detector.md.
