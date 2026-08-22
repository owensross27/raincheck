# FloodNet NYC Street-Flood Sensors — API, Coverage, Grain, Quirks

Researched 2026-08-22. All findings below come from live HTTP requests (curl,
direct to `api.floodnet.nyc`, `data.cityofnewyork.us`, `github.com`, and the
FloodNet Google-Docs data-access guide), not memory. See the Evidence table
for exact status codes, byte sizes, and row counts.

## Verdict

**FloodNet has a real, keyless, currently-working REST + GraphQL API at
`api.floodnet.nyc`, discovered via the project's public onboarding Colab
notebooks (linked from the data-access doc, not from the marketing site).**
No API key or auth header of any kind was needed for any request in this
session. Live-verified facts:

- **440 sensor deployments** returned by `GET
  https://api.floodnet.nyc/api/rest/deployments/flood` right now — 385
  `pluvial`, 55 `coastal`, only 2 marked retired (`date_down` set). Each
  record carries `name`, `deployment_id`, `date_deployed`, `date_down`,
  `deploy_type`, WGS84 lat/lon, `sensor_mount`, `mounted_over`,
  `sensor_status`.
- **Deployment dates span 2020-10-05 to 2026-08-13** (min/max
  `date_deployed` across all 440 live records) — i.e. real, continuing growth
  since 2020, not a static one-time install.
- **Depth grain: millimeters, ~60-second sampling**, confirmed by pulling
  live time series (`depth_proc_mm`/`depth_filt_mm`/`depth_raw_mm`) — samples
  landed ~63-64 seconds apart. The access doc states sensors before November
  2021 sampled every 5 minutes instead of 1 minute.
- **Historical depth data is reachable back through at least Hurricane Ida
  (2021-09-01)** and the sensor's own deployment date (as early as
  2020-10-05) via the same `/depth` REST endpoint and the GraphQL
  `depth_data` table — confirmed with real non-null readings during Ida (max
  263 mm on one sensor).
- **No bulk single-file historical download exists over HTTP without
  authorization.** The documented path is: fill out a data-request form ->
  get added to a permissioned Google Drive folder of per-sensor-per-month
  CSVs. The REST/GraphQL APIs are the only *unauthenticated* route to
  historical time series, and both are row-capped per request (empirically
  10,000 rows on `/depth` today — the notebook's own comment claiming a
  3,000-row/~2-day cap is stale and undershoots the current limit by 3.3x).
- **License is a custom NYU/CUNY non-commercial Data Access License
  Agreement** for the sensor data itself (distinct from the `floodnet-data`
  GitHub repo's own CC BY-NC-SA 4.0 tag, which covers that repo's
  documentation, not necessarily the data). Non-commercial-only is
  load-bearing for raincheck if the project has any commercial angle — see
  Unverified.
- **Documented data quirks are unusually well written up**: three named
  noise categories (blips, boxes, complex noise) from objects/animals under
  the sensor, a nightly (11:30pm) auto-recalibration against a 3-night
  rolling median baseline, an explicit rate-of-change filter (254 mm/min
  threshold, ~6x the fastest flood onset observed in NYC during Ida), and a
  live homepage banner (present at fetch time) warning that snow can produce
  false-positive-like readings.

If raincheck wants ground-truth flood depth at sensor points: the REST API
(`api.floodnet.nyc/api/rest/deployments/flood*`) and GraphQL API
(`api.floodnet.nyc/v1/graphql`) are real, free, keyless, and paginable by
date range per sensor — a scriptable backfill is possible today without
waiting on the data-request form, just capped at ~10k rows per call so a
multi-year pull needs date-range chunking per sensor.

---

## 1. API endpoints and auth

Two live APIs, both under `api.floodnet.nyc`, **zero auth required** for
either (no API key, no bearer token, no cookie) in every request made this
session:

### REST
```
GET https://api.floodnet.nyc/api/rest/deployments/flood
GET https://api.floodnet.nyc/api/rest/deployments/flood/near?lat=<f>&lon=<f>&radius_meters=<f>
GET https://api.floodnet.nyc/api/rest/deployments/flood/{deployment_id}/depth?start_time=<ISO8601>&end_time=<ISO8601>
```
- `deployments/flood` -> `{"deployments": [...]}`, 440 records, 200 OK,
  186,263 bytes.
- `deployments/flood/near` -> `{"deployments_within_radius": [...]}`, tested
  with the notebook's own Gowanus Canal example
  (`lat=40.67517255&lon=-73.99058232&radius_meters=750`) -> 5 sensors, 200
  OK, 2,058 bytes.
- `.../{deployment_id}/depth` -> `{"depth_data": [{"deployment_id","time","depth_proc_mm"}, ...]}`.
  A `HEAD` request to the base `deployments/flood` path returns 400 (the
  endpoint only implements `GET`) — noted so a future prober doesn't misread
  a `HEAD` probe as "API down."

### GraphQL (Hasura, supports subscriptions)
```
POST https://api.floodnet.nyc/v1/graphql
```
Confirmed live with a real query for `storm_events` (200 OK, 1,294 bytes) —
13 named storms cataloged from Tropical Storm Fay (2020-07-10) through the
September 29, 2023 event, each other than the newest with `name`,
`start_time`, `end_time`, `details`. Schema also exposes (per the linked
notebook, not independently introspected this session): `deployments`,
`deployments_within_radius`, `depth_data`, `sensor_events`, and a WebSocket
subscription on `depth_data` filtered to `depth_proc_mm > 0` for real-time
streaming. `depth_data_aggregate` does **not** exist (`GET` returns a GraphQL
validation error, not data) — there's no server-side row-count aggregate
exposed; row counts have to be pulled and counted client-side.

An unauthenticated GraphQL query for 5 raw `depth_data` rows (no filter)
succeeded (200 OK, 524 bytes) and returned real rows from December 2022 —
i.e. the GraphQL endpoint isn't restricted to the REST wrapper's
per-deployment scoping, though it's clearly meant to be used with a `where`
clause per the notebook examples.

**Where the endpoint URLs came from**: not the marketing site
(floodnet.nyc) and not general web search — they are hardcoded in two public
Google Colab notebooks linked from the project's data-access Google Doc
(itself linked from the `floodnet-nyc/floodnet-data` GitHub repo's README).
`https://api.floodnet.nyc/api/graphql` (a plausible guess) returned 404 both
GET and POST; the real path is `/v1/graphql`.

## 2. Sensor count and locations

Live count via REST, right now: **440 deployments** — 385 `pluvial`
(rainfall-driven), 55 `coastal` (tidal-driven). `sensor_status` breakdown:
353 `good`, 20 `good - fs`, 18 `noisy`, 17 `signal`, 10 `low_charge`, 6
`dead`, 4 `needs_driverail`, 3 `non-ota`, 2 each of `retired`,
`needs_sensor`, `hardware_issue`, `needs_ota_update`, 1 `removal_requested`.
`mounted_over`: 430 `sidewalk`, 6 `road`, 3 `dirt`, 1 `sidewalk ` (stray
trailing space in the data — a real quirk in the field itself, not a
transcription error here). Each deployment carries a GeoJSON `Point` in
EPSG:4326 (WGS84 lat/lon) — e.g. `BK - Marion St/Howard Ave` at
`[-73.91946, 40.680855]`.

NYC Open Data mirrors a subset of this via Socrata: **`FloodNet: Sensor
Deployment Metadata`**, dataset id `kb2e-tjy3` (**479 rows**, `$select=count(*)`
-> 200 OK), attributed to DEP, with fields including `sensor_id`, borough,
zipcode, community board, council district, census tract, NTA, and
`lowest_point_height_delta_inches` (a per-sensor elevation-offset field not
present in the live API response). The 479-vs-440 discrepancy wasn't
resolved this session — plausibly Open Data retains historical
rows/revisions the live API doesn't, or vice versa (see Unverified). A
second Socrata id, `ag7h-2pg6`, is a **map visualization lens of the same
underlying dataset** (`parent_fxf: ["kb2e-tjy3"]` per its catalog metadata),
not an independent dataset — its tabular JSON query returns an empty object
because it's a `visualization_canvas_map` view with no exposed columns, not
because it holds different data.

## 3. Deployment dates and coverage growth since 2020

- Earliest live `date_deployed`: **2020-10-05** (`BK - Hoyt St/5th St`,
  `daily_new_falcon`, status `good - fs`).
- Latest live `date_deployed`: **2026-08-13** (`BK - 49th St/1st Ave`,
  `sharp_green_turtle`) — 9 days before this research session, confirming
  the network is still actively growing today, not frozen.
- The GraphQL `storm_events` catalog's earliest entry (Tropical Storm Fay,
  2020-07-10) predates the earliest live sensor by three months — either an
  earlier sensor generation was later retired/dropped from the live
  `deployments/flood` list, or the storm catalog was back-filled for
  context even where sensor coverage was thin. Not resolved this session.
- No day-by-day or year-by-year deployment-count time series was pulled
  (would require bucketing all 440 `date_deployed` values) — flagged as a
  possible cheap follow-up rather than done here, since the raw per-record
  dates above already answer the ticket's coverage-since-2020 question.

## 4. Measurement grain

- **Units: millimeters** in the API and CSV field names
  (`depth_proc_mm`, `depth_filt_mm`, `depth_raw_mm`); the NYC Open Data
  street-flooding-events dataset reports the derived event summaries in
  **inches** instead (`max_depth_inches`, etc.) — so the two public
  distribution channels use different units for the same underlying
  measurement.
- **Sampling interval: 60 seconds**, confirmed by direct observation of
  consecutive `time` values in a live pull (`2026-08-20T04:00:12.338Z`,
  `...04:01:15.536Z`, `...04:02:18.321Z` — ~63s apart). The access doc states
  sensors deployed before November 2021 ran at 5-minute intervals instead,
  and that "a larger time interval may be observed if a sensor was
  temporarily down or if there was a data transmission failure" — i.e. gaps
  in the time series are an expected, documented condition, not necessarily
  a bug.
- Three parallel depth fields are served side by side for every reading:
  `depth_raw_mm` (no filtering), `depth_filt_mm` (values <10mm zeroed),
  `depth_proc_mm` (full heuristic-filtered "recommended" field). `null` is
  used for pings that got no echo back (confirmed live — several `null`
  `depth_proc_mm` values appeared in a same-day pull).

## 5. Historical bulk download

**No public single-URL bulk archive was found.** Three real paths exist,
none of them an anonymous one-shot download of the full multi-year dataset:

1. **REST/GraphQL API, per sensor, per date range** — free, keyless, works
   today, verified back to 2020-10-05 (a sensor's deployment date) and
   through Hurricane Ida (2021-09-01, non-null readings, max 263mm on one
   sensor). Row-capped: a 7-month window request
   (`2026-01-01`..`2026-08-01`) on one sensor returned exactly **10,000
   rows** and silently truncated to the first ~7 days of that window
   (`2026-01-01T04:00:24Z` through `2026-01-08T11:25:20Z`) rather than
   erroring — so a real multi-year backfill must chunk by date range per
   sensor and detect truncation by counting returned rows.
2. **Per-sensor-per-month CSVs via a gated Google Drive folder** — per the
   official data-access doc: "After you fill out the data request form, you
   will be notified when you are granted permission to access the data...
   you can access the CSV directory at this link," filename pattern
   `[slug]/[slug]+[YYYY]-[MM].csv`, updated daily at 5AM ET. The linked Drive
   folder (`drive.google.com/drive/folders/1Q92SqBQojRlJgaETJmqGFFAWyzgrikK8`)
   redirected to a Google sign-in page (200 OK on the redirect target,
   `accounts.google.com/v3/signin/...`) when fetched anonymously — confirming
   it's permission-gated, not publicly listable. The "data request form"
   itself wasn't located as a direct link in this session (see Unverified).
3. **NYC Open Data (Socrata), event summaries only** —
   **`FloodNet: Street Flooding Events Measured by FloodNet Sensors`**,
   dataset id `aq7i-eu5q`, **2,929 rows** (`$select=count(*)` -> 200 OK).
   Grain is one row per detected flood *event* (not per-minute readings),
   with `flood_start_time`, `flood_end_time`, `max_depth_inches`,
   `onset_time_mins`, `drain_time_mins`, plus two embedded arrays per row —
   `flood_profile_depth_inches` and `flood_profile_time_secs` — giving the
   full within-event depth curve at roughly 60-second resolution (confirmed
   by inspecting a real row: `Q - Beach 84 St`, event 2023-10-30, 17.72"
   max depth, 58-element profile array). This is public-domain-flavored NYC
   Open Data, no request form needed, but it is **not** the raw continuous
   time series — no data outside a detected flood event is included.

## 6. License / terms

Two different licenses cover different pieces of what's public:

- **The sensor data itself**: a custom **"Data Access License Agreement
  (non-commercial)"** between NYU and CUNY (joint owners) and any
  licensee, linked from the `floodnet-nyc/floodnet-data` GitHub repo's data
  access doc. Fetched directly (200 OK, 11,094 bytes as plain text). It is
  explicitly non-commercial in its title; full clause-by-clause terms
  (attribution requirements, redistribution limits, "Permitted Derivative
  Works" language) were skimmed but not exhaustively parsed this session —
  the license doc runs well past what was excerpted here (see Unverified).
- **The `floodnet-nyc/floodnet-data` GitHub repo's own content** (the CSV/API
  documentation repo, not the data): tagged **CC BY-NC-SA 4.0** via its
  README and `LICENSE` file. This governs the repo's own docs, not
  necessarily a separate grant over the dataset — the dataset's actual terms
  are the NYU/CUNY agreement above.
- **Citation requirement**: any publication/presentation using the data
  must cite the project as "FloodNet (New York University and The City
  University of New York)" and reference Mydlarz et al. (2024), *Water
  Resources Research*, https://doi.org/10.1029/2023WR036806.
- NYC Open Data's own terms of use apply to the `kb2e-tjy3` /`aq7i-eu5q`
  Socrata mirrors, which may or may not be identical in restrictiveness to
  the NYU/CUNY agreement — not reconciled this session (see Unverified).

## 7. Known data quirks

From the FloodNet documentation site (`floodnet-nyc.github.io`) and the
data-access doc, both fetched directly:

- **Nightly auto-recalibration**: every night at 11:30pm/5am, the sensor's
  "no-flood" baseline distance is recalculated as the median of the
  previous 3 nights' 10pm-5am readings; if that window's standard deviation
  exceeds 5mm (signaling a flood or high variance in progress), the
  previous day's baseline is reused instead. This means the depth-zero
  point can drift over time and is not a fixed installation-height constant.
- **Blips**: momentary single-reading jumps (a person/animal/object passing
  under the sensor at the instant of a ping), filtered by comparing 3
  consecutive readings.
- **Boxes**: a sudden jump that then holds steady (a parked car, garbage,
  a bike left under the sensor), filtered by a persistence check — but only
  for events that start at depth zero, specifically to avoid misclassifying
  the plateau at the top of a real flood as a "box."
  **Rate-of-change filter**: any depth change exceeding 254 mm/minute is
  discarded outright — chosen as ~6x the fastest flood onset FloodNet has
  measured in NYC (during Hurricane Ida).
  **Complex/chaotic noise**: aberrant reflections off uneven surfaces or
  vegetation; explicitly flagged in the docs as *not* fully solved by the
  blip/box filters — "some pulse chains and other complex noise may remain."
  **Dropouts**: "Sometimes the sensor will send out a ping, but will never
  receive an echo back. In these cases, the measurement is invalid and we
  record a null value" — a missing/`null` time point is a documented normal
  condition, confirmed live (several `null` `depth_proc_mm` values appeared
  in a same-day API pull).
- **Snow/ice false positives**: not detailed in the technical docs pulled
  this session, but the **live floodnet.nyc homepage carries a banner**
  fetched today (2026-08-22, mid-summer) reading "Note: Due to the recent
  snowstorm, FloodNet sensor readings likely reflect the presence of snow" —
  either a stale cached banner left over from a past winter event or an
  indicator the site doesn't always refresh this notice promptly; either
  way it confirms the project itself publicly flags snow/ice as a
  false-positive source, worth treating with caution in winter months (see
  Unverified — the banner's actual current relevance wasn't chased further).
- **Sensor placement bias**: sensors are mounted on existing street
  infrastructure (signposts), not necessarily at the true topographic low
  point of a block, and sensors mounted over sidewalks can't detect
  roadbed flooding until water rises above curb height — both explicitly
  called out in the access doc as reasons a sensor may under-report or miss
  a nearby flood.

---

## Evidence

| # | Request | Result |
|---|---|---|
| 1 | `GET floodnet.nyc/` | 200, 1,769,860 B |
| 2 | `GET floodnet.nyc/methodology` | 200, 857,282 B |
| 3 | `GET floodnet-nyc.github.io/` | 200, 7,525 B |
| 4 | `GET floodnet-nyc.github.io/real-time-data-pipeline/` | 200, 25,830 B |
| 5 | `GET api.github.com/orgs/floodnet-nyc/repos` | 200, listed 20 repos incl. `floodnet-data` |
| 6 | `GET raw.githubusercontent.com/floodnet-nyc/floodnet-data/main/README.md` | 200, README links data-access doc, states CC BY-NC-SA 4.0 for the repo |
| 7 | `GET docs.google.com/document/d/1fyryGTz2h6lSTPsXJEFqMSWjZJiF1Q.../export?format=txt` (data access doc) | 200, 18,624 B |
| 8 | `GET docs.google.com/document/d/1jd5Q2UYj_0PwMRplFISmhT6LswpS08D9/export?format=txt` (license agreement) | 200, 11,094 B, "Data Access License Agreement (non-commercial)" |
| 9 | `GET docs.google.com/uc?id=1BMFAwzKd9Oa8yn68E93vJMPGIDe4L3Lh&export=download` (REST Colab notebook) | 200, 1,366,418 B; contains real endpoint URLs |
| 10 | `GET docs.google.com/uc?id=1n00hQi3Li_NMj7xTCzvXOQDelbt5e0Kv&export=download` (GraphQL Colab notebook) | 200, 1,175,256 B; contains `https://api.floodnet.nyc/v1/graphql` |
| 11 | `GET api.floodnet.nyc/api/rest/deployments/flood` | 200, 186,263 B, 440 deployments (385 pluvial, 55 coastal) |
| 12 | `GET api.floodnet.nyc/api/rest/deployments/flood/near?lat=40.67517255&lon=-73.99058232&radius_meters=750` | 200, 2,058 B, 5 sensors |
| 13 | `GET api.floodnet.nyc/api/rest/deployments/flood/mainly_alert_magpie/depth?start_time=2021-09-01...` | 200, 17 B, `{"depth_data":[]}` (sensor not yet deployed then — correctly empty) |
| 14 | `GET .../daily_new_falcon/depth?start_time=2026-08-20T00:00:00-04:00&end_time=2026-08-21T00:00:00-04:00` | 200, 67,860 B, 715 rows, ~60s cadence confirmed |
| 15 | `GET .../daily_new_falcon/depth?start_time=2021-09-01T14:00:00-04:00&end_time=2021-09-02T06:00:00-04:00` (Hurricane Ida) | 200, 21,890 B, 223 rows, max depth_proc_mm=263mm |
| 16 | `GET .../daily_new_falcon/depth?start_time=2026-01-01...&end_time=2026-08-01...` (7-month window) | 200, 948,804 B, **exactly 10,000 rows**, truncated to first ~7 days — real row cap confirmed |
| 17 | `GET .../daily_new_falcon/depth?start_time=2020-10-05...&end_time=2020-10-12...` (first week post-deploy) | 200, 231,536 B, 2,363 rows |
| 18 | `HEAD api.floodnet.nyc/api/rest/deployments/flood` | 400 (endpoint only supports GET) |
| 19 | `GET api.floodnet.nyc/api/graphql` and `POST` same | 404 both (wrong path — real path is `/v1/graphql`) |
| 20 | `POST api.floodnet.nyc/v1/graphql` `{storm_events{name start_time end_time}}` | 200, 1,294 B, 13 storms, 2020-07-10 through 2023-09-28 |
| 21 | `POST api.floodnet.nyc/v1/graphql` `{depth_data_aggregate{aggregate{count}}}` | 200 (HTTP), GraphQL error: field not found — no aggregate exposed |
| 22 | `POST api.floodnet.nyc/v1/graphql` `{depth_data(limit:5){...}}` (unfiltered) | 200, 524 B, 5 real Dec-2022 rows returned unfiltered |
| 23 | `GET data.cityofnewyork.us/resource/kb2e-tjy3.json?$select=count(*)` | 200, `{"count":"479"}` |
| 24 | `GET data.cityofnewyork.us/resource/kb2e-tjy3.json?$limit=2` | 200, real sensor metadata rows w/ borough, census tract, `lowest_point_height_delta_inches` |
| 25 | `GET data.cityofnewyork.us/resource/ag7h-2pg6.json?$limit=1` | 200, `[{}]` — map-lens view of `kb2e-tjy3`, no tabular columns |
| 26 | `GET data.cityofnewyork.us/resource/aq7i-eu5q.json?$select=count(*)` | 200, `{"count":"2929"}` |
| 27 | `GET data.cityofnewyork.us/resource/aq7i-eu5q.json?$limit=2` | 200, real flood-event rows incl. `flood_profile_depth_inches`/`flood_profile_time_secs` arrays |
| 28 | `GET api.us.socrata.com/api/catalog/v1?domains=data.cityofnewyork.us&q=floodnet` | 200, 21,336 B, 3 results (`aq7i-eu5q`, `kb2e-tjy3`, `ag7h-2pg6`) |
| 29 | `GET drive.google.com/drive/folders/1Q92SqBQojRlJgaETJmqGFFAWyzgrikK8?usp=drive_link` | 200 (redirect target is `accounts.google.com` sign-in — confirms permission-gated) |
| 30 | `GET floodnet.nyc/` homepage text scan | live banner: "Due to the recent snowstorm, FloodNet sensor readings likely reflect the presence of snow" |

## Unverified

- Why NYC Open Data's `kb2e-tjy3` sensor-metadata mirror has **479** rows
  while the live REST API returns **440** deployments — not reconciled
  (revision history vs. a sync lag vs. different inclusion criteria).
- The full text of the NYU/CUNY Data Access License Agreement was fetched
  (11,094 bytes) but not exhaustively read clause-by-clause — specific
  redistribution/attribution/derivative-work terms beyond "non-commercial"
  and the citation requirement weren't fully extracted.
- Whether the NYC Open Data Socrata mirrors (`kb2e-tjy3`, `aq7i-eu5q`) carry
  NYC Open Data's own (typically permissive) terms of use, or whether the
  underlying NYU/CUNY non-commercial restriction still legally applies to
  data republished there — not reconciled.
- The actual "data request form" URL for the gated per-sensor-per-month CSV
  Google Drive folder was not located as a direct hyperlink in this session
  (the access doc references it as plain text, not a hyperlink, in the
  portion exported).
- GraphQL schema was not independently introspected (no
  `__schema`/`__type` query run) — the field list above (`sensor_events`,
  `flood_detected`, subscriptions, etc.) comes from the notebook's example
  queries, not a live introspection call.
- The gap between the GraphQL `storm_events` catalog's earliest entry
  (2020-07-10, Tropical Storm Fay) and the earliest live sensor deployment
  (2020-10-05) — not resolved; unclear if earlier sensors existed and were
  later dropped from the live list.
- The floodnet.nyc homepage's snow banner's actual current relevance (a
  live warning today, 2026-08-22, vs. a stale cached fragment) was not
  chased further — it's real content on the page at fetch time either way,
  but its currency wasn't independently confirmed.
- No day-by-day/year-by-year sensor-count growth curve was built from the
  440 `date_deployed` timestamps (only min/max were checked) — a real gap
  vs. the ticket's "coverage growth since 2020" phrasing, flagged rather
  than guessed at.
- `deploy_type` values `tidal` and `weather` are mentioned in the GraphQL
  notebook's example query comments alongside `pluvial`/`coastal`, but no
  live deployment with either of those two values was observed in the 440
  fetched — may be unused/future-reserved enum values, not confirmed.
