# Wayfinder map: NYC flood map

Label: `wayfinder:map`

## Destination

A build-ready spec for the flood effort: (1) a mapped history of NYC flood events
at point / street-segment / station grain from the ranked observed sources; (2) an
exposure/likelihood score per subway station/entrance, bus stop and street segment
from precip, elevation, tide/surge and stormwater data; (3) a real-time detector
flagging areas and stations likely flooding during an active rain event, with bus
slowdowns (raincheck Gold) and subway delays as impact signals — never detector
inputs. The map is done when nothing is left to decide before `/to-spec` collapses
it and `/to-tickets` slices the build.

## Notes

- Domain: NYC flooding x transit. Source facts pre-verified — consult before
  re-deriving: `/Users/ross/vault/nyc-flood-history-elevation-2026-08-12.md`
  (ranked flood sources, elevation stack, datum traps),
  `research/subway-flood-labels.md` (alert-label anatomy, 99 post-2020 subway
  events, dedupe keys), `research/subway-rt-archives.md` (subway RT history:
  subwaydata.nyc 2021+, gtfsrt.io 2026-03+),
  `/Users/ross/vault/nyc-mta-bus-feeds-reference.md` (bus feeds).
- Reuses the raincheck rails wholesale, no re-deciding: Cell-hour precip spine and
  features (pipeline 08: `silver/precip_cell_hourly`, src=aorc history /
  src=mrms live, `ceil_hour`), storage/CRS conventions (pipeline 09: plain
  Parquet Silver, GeoParquet 1.1 geometry tables, EPSG:4326, geodesic distances,
  TIMESTAMP_MICROS UTC), H3 res 8 Cell grain, and the running
  `com.raincheck.archiver` capture (pipeline 15: subway TU + alerts since
  2026-08-16). This map owns its labels, units, and validation only.
- Plan, don't do. Local-only, no cloud writes, no new daemons without a HITL yes.
  Ponytail rules apply.
- Spec published 2026-08-22: `.scratch/flood/spec.md` (`ready-for-agent`),
  collapsed from tickets 01-10 by `/to-spec`; all ten tickets resolved, no HITL
  gates open. Load-bearing ticket corrections are tabled in the spec's Further
  Notes.
- Build tickets published 2026-08-22: `/to-tickets` sliced the spec into 18
  tracer bullets at `.scratch/flood-build/issues/` (spec copy alongside,
  pipeline-build precedent). Frontier at publish: 01 (asset registry) + 02
  (alert extractor). Adversarially verified (3 opus lenses, 34 findings
  reconciled — verdicts in `.scratch/flood-build/assets/`); the live-precip
  catch-up amendment is posted on pipeline build ticket 11's comment tail.
  Next: `/implement` per ticket in fresh sessions.
- Ross blessed the breakdown 2026-08-23 (relayed via the overview session):
  spec and 18 tickets stand as published, no amendments; build resumes on the
  frontier at ONE ticket per session — the ticket-10 → spec → tickets → build-01
  chain in a single session was accepted this once, not precedent. Open veto
  items (granularity/edges) convert to in-ticket notes, surfaced ticket-by-
  ticket only if load-bearing.
- Flood-build 01 (asset registry) resolved 2026-08-23: ref/assets built and
  frozen (20,544 rows; cells_scored = 1,351 exactly; assets_version d3c7b0f3…),
  branch `claude/elastic-mclaren-ba31c3` pushed to origin. Frontier: 02 (alert
  extractor), then 03/04.
- Datum discipline: NAVD88 US ft is canonical for elevation; CO-OPS Battery
  thresholds are STND (NAVD88 = 6.06 ft on STND); five legacy borough datums and
  NGVD29 exist in old records — the vault doc's trap table governs.
- Known label caveats (measured, not to relearn): alert rows inflate distinct
  incidents 2.6x pre-2020 (`status_id`) / 4.4x post-2020 (`event_id`); pre-2020
  wording is "water condition" (66.7%) more than "flood" (21.5%); ~19% of events
  acquire flood wording only after update 0; station names are free text only.

## Decisions so far

- [04 Stormwater and sewer geodata access](issues/04-stormwater-geodata.md) — DEP Stormwater Flood Maps (`9i7c-xyvv`) are FGDB-only with no queryable service anywhere (4 scenarios, categories "Deep and Contiguous"/"Nuisance" flooding); green infrastructure, MS4 drainage/outfalls, and catch basins are all live no-auth queryable services matching prior counts; DEC CSO outfalls confirm fetch-and-use is fine (`Query,Extract` capability), only rehosting is barred.
- [03 FloodNet sensor data access](issues/03-floodnet-archive.md) — keyless REST + GraphQL API at `api.floodnet.nyc` (440 sensors, 2020-10-05 to 2026-08-13, depth_mm at ~60s), 10k-row/request cap and no anonymous bulk download (per-minute CSVs need a data-request form); data license is a custom NYU/CUNY non-commercial agreement.
- [05 Tide/surge history and nowcast products](issues/05-tide-surge-products.md) — six CO-OPS stations have populated flood thresholds (Battery, Kings Point, Sandy Hook, Bridgeport, New Haven, New London), each with its own STND->NAVD88 offset (`datum=NAVD` param preferred over the Battery-only 6.06 constant); real-time surge is STOFS-2D-Global (live, 4x/day, 0-180h) since ETSS is dead, P-Surge only populates during an active storm, and IEM watchwarn needs `limitps=yes` or its phenomena filters silently no-op.

- [01 Flood-event label set design](issues/01-flood-label-set.md) — resolved 2026-08-22 (measured + 3-lens adversarial review + Ross yes-to-all): three tables — `silver/flood_obs` (one GeoParquet, label-grade sources only: 311 SJ/SH exact descriptors, FloodNet via the Socrata event table `aq7i-eu5q` not the raw API, gated alert station labels, HWMs, Sandy polygon), `silver/flood_events` (spine: frozen 311 thresholds 97/84 per era-dataset, station-naming alert days, Storm Events by FIPS+zone, CO-OPS STND-vs-STND at Battery/Kings Point; deterministic midnight±3h windows; FLOOD_CAUSE-first classing with a snowmelt gate), `gold/flood_labels` (positives only, anti-join negatives, estimand named `flooded_reported`, label_version sha1); FloodNet is truth so FloodNet features are barred from 08; one 100 m geodesic attachment radius; bus flood alerts rejected; NFIP covariate-only. Event-spine fog resolved here.

- [02 Station-name extraction from alert text](issues/02-station-name-extraction.md) — resolved 2026-08-22: alert station labels are label-grade — the cause-anchored extractor measured precision 1.000 on both the 120-row sample and a 40-row frozen-rule holdout (gate was >= 0.90; recall 0.970/0.778), with the event-grain deliverable `research/flood-02-station-prototype/events_stations.json` (new era 38/99 events station-labeled, old era 57/72). Ida yields zero station labels (all system-wide phrasing; the spine absorbs it via 311 + Storm Events); one rename found ("149 St-Grand Concourse" -> "149 St-Hostos").

- [06 Asset registry design](issues/06-asset-registry.md) — resolved 2026-08-22 (measured + 3-lens review + Ross yes-to-all): one `ref/assets` GeoParquet, 20,544 rows (445 complexes + 496 stations + 2,120 entrances + 13,370 bus stops + 4,113 Cells), no-hash keys (entrance = corrected complex_id + 6-dp coords; bus coords = cross-feed mean), stations/entrances are carriers while complex/bus_stop/Cell are the score units, radius attachment hits entrance/bus_stop/cell rows only (19/445 complexes have no entrance in their own 100 m circle), LION rejected at a measured 122,256 segments, byte-identical build off pinned pick_ids + snapshotted Socrata pulls, key-stability contract with rebuild key-diff. Amended 01 (label_support -> {radius, station, cell}; label_version += assets_version; alert labels land at the complex row; generator verbatim with per-kind filter) and flagged 07 (sampling universe ~15,500 points) and 08 (churn/fan-out/effective-sample obligations). Comment 2026-08-22: ~2,759 of the 4,113 Cells touch no NYC land (bbox tiling) — scored cell universe restricted by 08.

- [07 Elevation feature set](issues/07-elevation-features.md) — resolved 2026-08-22 (measured + 3-lens review + Ross yes-to-all): `silver/asset_features` is point-assets-only — 15,490 rows (2,120 entrances + 13,370 bus stops), no cell/complex rows (aggregates are 08's read-side GROUP BYs); canonical elev = 2017 1-m ImageServer in NAVD88 US-survey ft (x 3.280833333), 2014 epoch as cross-check, plus an 8-point 15 m ring (ring15_min/med — the doorway-scale pluvial term); one `grade_ok` boolean off frozen constants (|Δepoch| > 2 m, elev < −1 m; measured 41/2,120 entrances, 4/4,557 stops; QC flags never model features); locationId-keyed batches at pinned request constants (nearest-neighbor interpolation frozen — bilinear moves values 0.34 m); build rides the ref/assets ticket with a 41-count service-drift canary and chained features_version. No queryable DSM exists (71 services enumerated); DEM_2024_Long_Island covers only the eastern Rockaways (upgrade path; Beach 25 St −1.29 m post-Sandy rebuild); the naive STND-vs-NAVD comparison inflates "below minor flood" entrances 103 → 3. Handed 08 seven obligations incl. the gauge assignment and the polluted cell negative universe.

- [08 Exposure/likelihood score design](issues/08-exposure-score-design.md) — resolved 2026-08-22 (measured + 3-lens review, the effort's heaviest teardown at 101 verdicts + Ross's pre-authorized yes): TWO fitted models, not three — a pooled point model (entrances + bus stops on 07's shared features) and a cell model, L2 logistic, pluvial events only; complex score = max over child-entrance scores, which frees the 155 alert-sourced complex pairs to be an independent validation set; coastal ships as a deterministic rule layer (surge_margin_ft vs nearest-of-three gauge thresholds), not a fitted model; four baselines with the headline "beat B2 unit-climatology AND B3 density under the location-blocked split" (measured: a prior storm's footprint ties precip, CSI 0.258 vs 0.264, and stop density beats every precip feature, AUC 0.704) and an if-B2-wins-ship-B2 honesty clause; per-event CSI abolished for per-event POD+FP (61% of alert events have one positive); threshold sweep moved to outer replication (amends 01); published object = evaluation at frozen reference forcings (score_ref/score_severe + within-kind percentile with published CDFs); all event features trailing/running so one JSON serves the detector, live output rank-only; negatives gated by per-source coverage calendars + anachronism rules (bus pairs >= 2020, replacing 06's unexecutable churn method); fit era 2010-2025 with the AORC flood-era extension named as a build item. Detector interface posted on 10; amendments posted on 01; NFIP deferred to fog.

- [09 Impact signals: bus slowdowns and subway delays](issues/09-impact-signals.md) — resolved 2026-08-22 (measured on real subwaydata.nyc day-files + 3-lens review + Ross's pre-authorized yes): two subway metrics from the per-day CSVs (service_ratio + max_gap_ratio at complex grain, both reproduce to the digit; combined they catch 5/7 of 02's flagged complexes on 2023-09-29), with the validation statistic rebuilt as route-mix RESIDUALS + same-line neighbor controls (the raw tail is ~4 route-level service cuts, effective-n = line segments); day-files are trip-start-keyed so hours 00-05 need the D-1 file union (94% undercount otherwise); no new Silver table (build assets; corpus aggregates in ~44 s); bus reuses cell_hour_speed/w1-w2 baselines with sums-merged window stats — coverage honesty: subway 35/115 union days, bus 6/115, 70% have neither; snapshots land at data/ext/subwaydata/ deliberately OUTSIDE data/archive (coldpush would rehost license-unknown bytes to R2; archiver budget); subwaydata.nyc license NOT FOUND -> fetch-and-use local-only, no cloud copy, derived numbers local-page-only, revisit if a license publishes; live counterpart handed wholesale to 10 (capture needs a realized-arrival inference pass + level comparison; subwaydata lags 7-31 h). Impact barred from 08's features/versions by comment.

- [10 Real-time detector design](issues/10-realtime-detector.md) — resolved 2026-08-22 (measured live + 3-lens review, 45 verdicts + 24 missing; Ross's pre-authorized yes): the detector IS 08's model on live RadarOnly :00 cell-hours — displayed as the within-kind rank of live eta over the CURRENT eta vector (the draft's score_ref-CDF percentile refuted as a rainfall gauge in rank costume; the static CDF keeps the dormant/static view); window = stateless backward walk to the last 21:00 NY boundary with a dry 3-h pad (wet-cell count < K, not citywide max), 6-day hard cap, INSUFFICIENT_DATA holds rather than resets, antecedent frozen at A and persisted; tiers ELEVATED/HIGH = top 10%/2% within kind, latched gates, winter gate off one KNYC obs, cutpoints frozen by an AORC-era replay publishing signed live-minus-offline deltas + per-event flag volumes; coastal = three gauges obs-vs-NAVD-thresholds + anomaly persistence onto the next high <= 12 h (bare `range=36` measured returning the PAST 36 h — corrected; STOFS/P-Surge cut to fog); FloodNet display rule = one bounded query (2080-clock sensor poisons unbounded reads), >= 3 consecutive rises, status blacklist, cell-rain display gate — measured dry-night standing offsets 18-528 mm kill absolute-depth rules; MTA chip vocabulary rebuilt on the measured "remove water from the tracks" family (zero 'flood'/'water cond' rows in 449,737 captured alerts) with an 02 extension gate; serving = third panel section in 14's page, one 30 s loop, one meta.json, absent-keys writer, score-units only; impact overlay = 09's two files at (cell|complex, hour_end_utc), activates the w3/2026 bus baseline; no new daemons — precip_live (amended: catch-up fetch over the ~25 h MRMS retention) is the only standing dependency. Found in review: the 311 SJ/SH descriptors were RENAMED upstream 2023-09 — amendment posted on 01 (four literals, p99 re-measure, spine re-derive, canary); alert-vocabulary recall hole posted on 02.

## Not yet specified

- Event-trigger upgrades if the frozen-count trigger proves biased: a
  negative-binomial expected-count offset (year/day-of-week/month — weekend
  reporting measured at 0.55x weekday), and forcing-trimmed event windows
  (precip-hours based) as an 08-era refinement.
- Jamaica Bay/Rockaway coastal gauge blind spot: no CO-OPS station in the
  criterion set; FloodNet's 55 coastal sensors partially cover 2020-11+ —
  revisit if coastal validation demands it.
- NFIP block-group claims disaggregated onto segments/stations (spatial support
  mismatch); Multiple Loss Properties NYC subset unverified. 08 deferred the
  NFIP + sewer-backup history covariates here explicitly (no ticket owns NFIP
  access; v1 uses own-source SJ/SH trailing density instead, same as-of +
  with/without discipline when these graduate).
- A fitted coastal model — 08 ships coastal as a deterministic rule layer;
  revisit when the coastal event count supports fitting (order 10-20 today).
- Historical-GTFS fetch for true bus-stop churn reconstruction (research/13:
  nothing public holds the bytes; transitland grant covers 2017-2024 only) —
  upgrade path for 08's era-restriction method; new source = HITL.
- Terrain-connectivity terms (RichDEM flow accumulation / HAND) — only if the
  score's CSI lands poor. Elevation upgrade paths now carry 07's sharpened
  triggers: per-station DSM tiles from finder.nyc.gov when 08 names specific
  suspect stations; LiDAR class-25 sills when complex-grain CSI beats
  Cell-grain by nothing; 2010 epoch when pre-2014 events score materially
  worse; DEM_2024_Long_Island re-sampling if Rockaway residuals demand
  post-2017 terrain. (InSAR ruled out for v1 by magnitude — 07.)
- MTA Climate Vulnerability Assessment (2024, names 10 flood-prone stations):
  mta.info 403s non-browser clients; browser session or FOIL retrieval.
- Hydro-OU US Flood Database (zenodo 4547036): 10-minute download-and-filter
  check for NYC granularity; could shortcut parts of the label union.
- Truth-tier capture pollers (FloodNet / CO-OPS / NWS) so post-event review can
  replay what the panel SHOWED — 10's v1 fetches at export time only, so
  truth tiers exist only while the loop runs; trigger: a storm review that
  demands them. New poller = new daemon = HITL yes.
- STOFS-2D-Global / points.cwl.nc / P-Surge storm mode (cut from 10's v1;
  25.2 MB/cycle measured, P-Surge non-empty is an Atlantic-basin signal):
  trigger = a coastal event that needs forecast lead time beyond the
  next-high-tide anomaly persistence 10 ships.
- MyCoast photographed reports (1,042 NYC points) as a validation garnish.

## Out of scope

- Alerting channels of any kind (standing rule).
- A hydrodynamic sewer/inundation model (needs the unpublished DEP sewer
  network; the score is statistical/heuristic by design).
- Commercial flood scores (First Street/ClimateCheck — gated, no public bulk).
- Scraping amNY/Brooklyn Paper/Gothamist (ToS prohibit; GDELT/CC-NEWS instead).
- Public hosting / re-serving of MTA-derived data.
