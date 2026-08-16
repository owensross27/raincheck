# NYC Subway GTFS-RT Historic Archives — Research Note

Researched 2026-08-16. All findings below come from real HTTP requests (curl/WebFetch/WebSearch/gh), not memory. See Evidence table for exact status codes and sizes.

## Verdict

**No single archive covers 2018-2026 for raw NYC subway GTFS-RT reliably.** The closest candidates, in order of how much of the ask each satisfies:

| Archive | Covers | Verified working today? | Grain |
|---|---|---|---|
| **subwaydata.nyc** | 2021-04-01 -> 2026-08-15 (1,963 days) | **Yes** — live, keyless, real per-day files confirmed | Derived per-trip/per-station arrivals (CSV) **and** raw GTFS-RT protobuf tarballs |
| **gtfsrt.io** | 2026-03-01 -> 2026-08-15 only (~5.5 months) | **Yes** — live, keyless, DuckDB/Parquet-over-HTTP | Raw TripUpdates (parquet) + service_alerts; no VehiclePositions for subway |
| **kenyoneda/mta-gtfs-rt-archive** | Claims 2018-04-27 -> present | **Partially** — one 2020-01-01 date worked (200 OK); 2022, 2024, and 2026 dates all returned HTTP 500 | Raw hourly protobuf snapshots (30s cadence), tar.bz2 |
| data.ny.gov (Socrata) "subway" datasets | 2015/2020 -> present | Yes, but wrong grain | **Monthly** aggregates by division/line — not per-train |

If you need continuous, currently-working, per-station/per-trip history: **subwaydata.nyc**, starting April 2021. If you need pre-2021 raw data, the only lead is kenyoneda's archive, which claims back to April 2018 but is failing on most dates probed just now — treat it as "found, currently degraded," not dependable without further investigation (see Unverified).

---

## 1. Current keyless MTA subway GTFS-RT feeds

Confirmed live via direct curl, zero auth headers sent:

```
https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs        (1/2/3/4/5/6/7/S)  -> 200, 100,675 B
https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace    (A/C/E)             -> 200, 66,035 B
https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm   (B/D/F/M)
https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g      (G)
https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz     (J/Z)
https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l      (L)
https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw   (N/Q/R/W)
https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si     (Staten Island Railway)
https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts  (service alerts)
```
Full canonical list cross-checked against gtfsrt.io's `inventory.json` (all `agency_id: "mta"`). Served `content-type: text/plain`, CloudFront-fronted, `access-control-allow-origin: *`. The `nyct-gtfs` library README states explicitly: *"API keys are no longer required to access MTA GTFS feeds"* (v2.0.0 change).

**VehiclePositions stop_id-only claim**: partially corroborated, not directly proven. `nyct-gtfs`'s `train.location` is documented as "the stop ID corresponding to... platform" (stop-based, not GPS-based), and gtfsrt.io's inventory has **zero** `vehicle_positions` records for any subway feed (only MTA bus has that table) — consistent with subway's VehiclePositions entities carrying no lat/lon, but the official reference PDF (mta.info/document/134521) returned HTTP 403 to WebFetch, so this wasn't confirmed at the protobuf-field level.

## 2. Public raw-GTFS-RT archives

### gtfsrt.io (JarvusInnovations) — real, keyless, but short window
Homepage: *"A continuously-updated archive of GTFS-Realtime feeds from transit agencies across the US. Raw protobuf snapshots and analytics-ready Parquet files, freely accessible... No authentication required."* Built on [gtfs-realtime-archiver](https://github.com/JarvusInnovations/gtfs-realtime-archiver) (AGPL-3.0 code).

- Parquet URL pattern: `https://parquet.gtfsrt.io/<feed_type>/date=<date>/base64url=<base64url>/data.parquet`
- Raw protobuf pattern: `gs://protobuf.gtfsrt.io/<feed_type>/date=<date>/hour=<ISO hour>/base64url=<base64url>/<timestamp>.pb` (bucket listing denied anonymously — 401 — but individual objects should still be fetchable by known key)
- Machine-readable feed catalog: `https://storage.googleapis.com/download/storage/v1/b/parquet.gtfsrt.io/o/inventory.json?alt=media` (200 OK, 33,169 B, 70 feeds across 20 agencies)
- **NYC subway is in it**: 7 line-group `trip_updates` entries (`subway-1234567`, `-nqrw`, `-ace`, `-bdfm`, `-g`, `-jz`, `-sir`) plus `subway-alerts`, all `agency_id: "mta"`.
- **But**: every MTA entry has `date_min: "2026-03-01"`, `date_max: "2026-08-15"` — only ~5.5 months, not 2018-2026. Volume for that window alone is large: `subway-1234567` = 2,858,703,175 records / 19.3 GB parquet.
- No `vehicle_positions` table exists for any subway feed (only MTA bus does), and DuckDB is the documented query tool (`SELECT * FROM read_parquet('https://parquet.gtfsrt.io/trip_updates/date=2026-08-01/base64url=.../data.parquet')`).

### kenyoneda/mta-gtfs-rt-archive — claims full 2018-2026, currently unreliable
GitHub repo (11 KB, `master` branch, last updated 2026-03-30). README:

> *"Description: Archive of MTA's GTFS-Realtime feeds. Packaged into archives every hour (one per feed). Every archive contains 120 files as the feed is generated every 30 seconds."*
> *"Archive Start: 16:00:00 EST, 27 April 2018"* (LIRR/MNR added 30 Apr 2020)
> *"To access via API, use following URL structure: `https://2m9ldwhcmh.execute-api.us-east-2.amazonaws.com/gtfs_rt/historic.mta/{feed}/{year}/{month}/{day}/{archive}`"* e.g. `feed26-2020-01-01-12.tar.bz2`, throttled to 10 req/s.

Feed-id map: `1`=123456, `26`=ACEHS, `16`=NQRW, `21`=BDFM, `2`=L, `11`=SIR, `31`=G, `36`=JZ, `51`=7, `-lirr`, `-mnr`.

**Real test results**:
- `feed26/2020/01/01/feed26-2020-01-01-12.tar.bz2` → **HTTP 200**, 424,788 bytes (`binary/octet-stream`) — archive genuinely has data at least for this date.
- `feed26/2022/06/01/...`, `feed26/2024/01/01/...`, `feed26/2026/08/15/...` → **all HTTP 500** `InternalServerErrorException`.

So the archive exists and at least one historical file is retrievable, but it is failing broadly right now. Treat as a lead requiring a wider sweep (different feeds/hours/date ranges) before relying on it, not as a working bulk source today.

### subwaydata.nyc — best currently-working option, derived + raw
Live site, keyless. Homepage: covers *"starting April 1, 2021"* through *"August 15, 2026"* (*"Number of days of data: 1963"*), updated *"every morning at around 7am with data from the previous day."* Grain: *"For each trip that runs in the subway, the dataset contains the list of stations the trip called at and the times it stopped"* — i.e. exactly a derived per-train/per-station arrival history.

Two products per day, both confirmed live:
- Processed CSV: `https://subwaydata.nyc/data/subwaydatanyc_YYYY-MM-DD_csv.tar.xz` → 302-redirects to `https://data.subwaydata.nyc/YYYY-MM/subwaydatanyc_<date>_csv_<hash>.tar.xz`. Real observed sizes: ~0.9–1.5 MB/day.
- Raw GTFS-RT protobuf tarball: `https://data.subwaydata.nyc/YYYY-MM/subwaydatanyc_<date>_gtfsrt_<hash>.tar.xz`. Real observed sizes: ~35–61 MB/day. Page states the full raw archive is "over 50GB" and that there's no single bulk-download link (bandwidth cost).
- No API key. License/terms of the data itself not found (only "the software... is open source").

## 3. Tools that are NOT hosted archives (ruled out)

- **toddwschneider/nyc-subway-data** — MIT-licensed collector script; writes to your *own* local Postgres (`realtime_feed_observations` → `realtime_trips`/`stop_time_updates`/`vehicle_positions`). No public download.
- **Bus-Data-NYC** GitHub org (13 repos, e.g. `mta-bus-archive` updated 2026-01-13, `bus-time-zipper` → `data.mytransit.nyc`) — entirely **bus**-focused; nothing subway.
- **tsdataclinic/gtfs-realtime-capsule**, **gtfs-tripify** — generic GTFS-RT archiving/parsing tools surfaced by search, not NYC-hosted archives; not investigated further given time budget.
- **Transitland** — surfaced repeatedly in search as holding "100+ archived versions" of the MTA feed, but this is understood to be **static GTFS schedule** version history, not GTFS-**RT** realtime snapshots (not directly re-verified via transit.land's own API this session — see Unverified).

## 4. data.ny.gov (Socrata) subway datasets — real counts, wrong grain

Socrata catalog search (`https://api.us.socrata.com/api/catalog/v1?domains=data.ny.gov&q=subway&limit=100`, 200 OK, 793 KB, ~70 results) surfaced every dataset named in the task. Row counts and grain confirmed via SODA (`$select=count(*)` and `$limit=1`):

| Dataset | ID | Rows | Grain | Since |
|---|---|---|---|---|
| MTA Subway Trains Delayed | `9zbp-wz3y` | 18,592 | monthly × division × line × day_type × reporting_category | 2020 |
| MTA Subway Customer Journey-Focused Metrics | `r7qk-6tcy` | 5,768 | monthly × division × line × period | 2015 |
| MTA Subway Terminal On-Time Performance | `f6rf-2a3t` | 5,092 | monthly × division × line × day_type | 2015 |
| MTA Subway Wait Assessment | `s666-h6b7` | 12,628 | monthly × division × line × day_type × period | 2015 |
| MTA Subway Service Delivered | `32ch-sei3` | 6,295 | monthly × division × line × day_type | 2015 |
| MTA Subway Major Incidents | `ereg-mcvp` | 5,732 | monthly × division × line × day_type × category | 2015 |

**All six are monthly, line/division-level aggregates — none are per-train or per-station.** They're KPI dashboards, not GTFS-RT-derived event logs. Three more 2019+ datasets turned up in the catalog but weren't queried for grain due to time (`MTA Subway 4 to 5 Minute Late Arriving Trains` `x7nj-r656`, `MTA Subway End-to-End Running Times` `sp9g-mzjh`, `MTA Subway Paths` `tdmq-asac`) — worth checking first in a follow-up, as their names suggest finer grain.

## 5. Checked, not found

- **Internet Archive** — confirmed down: two real requests to `archive.org/advancedsearch.php` (different queries, 3s apart) both returned **HTTP 503 "Internet Archive: Temporarily Offline."** Matches the task's warning. Retry: `https://archive.org/advancedsearch.php?q=nyct+gtfs-realtime&output=json`.
- **Kaggle / Zenodo** — web search found no NYC-subway-specific GTFS-RT dataset on either platform (only an unrelated turnstile entrance/exit dataset and an analysis notebook on Kaggle).
- **TransitLab / MIT / NYU** — no dedicated GTFS-RT archive found; only a tangential, unopened MIT Geodata catalog record.

---

## Evidence

See the `evidence` array for the full list (30 items) of exact URLs/commands with observed HTTP status, byte sizes, and row counts. Highlights:

| # | Request | Result |
|---|---|---|
| 1 | `GET storage.googleapis.com/.../parquet.gtfsrt.io/o/inventory.json?alt=media` | 200, 33,169 B, 70 feeds, 7 MTA subway trip_updates entries (date_min 2026-03-01) |
| 2 | `GET api-endpoint.mta.info/.../nyct%2Fgtfs-ace` | 200, text/plain, 66,035 B, keyless |
| 3 | `GET .../historic.mta/feed26/2020/01/01/feed26-2020-01-01-12.tar.bz2` (Range 0-500) | 200, 424,788 B (full file, Range ignored) |
| 4 | same endpoint, 2022/2024/2026 dates | 500 InternalServerErrorException (×3) |
| 5 | `HEAD subwaydata.nyc/data/subwaydatanyc_2026-08-15_csv.tar.xz` | 302 → `data.subwaydata.nyc/2026-08/...csv_810c3a5be9a6.tar.xz` |
| 6 | `GET api.us.socrata.com/api/catalog/v1?domains=data.ny.gov&q=subway` | 200, 793,142 B, ~70 datasets |
| 7 | `GET data.ny.gov/resource/9zbp-wz3y.json?$select=count(*)` | 200, `{"count":"18592"}` |
| 8 | `GET archive.org/advancedsearch.php?q=...` (×2, 3s apart) | 503 both times, "Temporarily Offline" |

## Unverified

See the `unverified` array for the full list (12 items). Key gaps:
- MTA VehiclePositions stop_id-only claim — indirectly supported, not proven at the protobuf field level (official ref doc blocked WebFetch with 403).
- kenyoneda archive's true usable date range — only one date (2020-01-01) confirmed working; 2022/2024/2026 all 500'd.
- Data-specific licenses for gtfsrt.io and subwaydata.nyc — not found (only code licenses: AGPL-3.0 and MIT respectively, for the *tools*, not confirmed for the *data*).
- Internet Archive holdings — site down all session; retry later.
- Transitland's archived-versions claim — believed to be static GTFS, not GTFS-RT; not re-verified via transit.land's API directly.
- Three finer-grained data.ny.gov datasets (4-5 Min Late Trains, End-to-End Running Times, Paths) not queried for row count/grain.

## Verification corrections (2026-08-16, opus skeptic re-ran the consequential claims; the counts and dates above reproduced to the digit, the access paths did not)

- gtfsrt.io Parquet must be fetched via `https://storage.googleapis.com/parquet.gtfsrt.io/<feed_type>/date=<date>/base64url=<b64>/data.parquet` (the bare `parquet.gtfsrt.io` host fails); the protobuf bucket is not anonymously listable. Inventory: `https://storage.googleapis.com/download/storage/v1/b/parquet.gtfsrt.io/o/inventory.json?alt=media`.
- The inventory holds **eight** subway trip_updates entries (the L, `nyct%2Fgtfs-l`, was omitted above), all 2026-03-01..2026-08-15, and — decisive for raincheck's bus side — **MTA bus vehicle_positions (31.1 GB), trip_updates (182.6 GB) and alerts (4.1 GB) since 2026-03-01**, plus subway alerts (6.5 GB), LIRR and MNR. So the public bus archive gap is 2024-09-06..2026-02-28, not 2024-09-06..today (raincheck ticket 05 rationale corrected).
- subwaydata.nyc's raw GTFS-RT tarball has no constructible URL (`/data/subwaydatanyc_<date>_gtfsrt.tar.xz` and variants -> 404); only the CSV `subwaydatanyc_YYYY-MM-DD_csv.tar.xz` redirects (302) to `data.subwaydata.nyc/<YYYY-MM>/..._<hash>.tar.xz`. Bulk raw access is "not offered" per their programmatic-access page.
- data.ny.gov `sp9g-mzjh` (141,501 rows, `origin_station_id`/`destination_station_id` fields — station-pair grain) exists beside the six monthly aggregates and was not queried; check it before charting.
- kenyoneda archive: `feed1/2020/01/01/...-12.tar.bz2` also returns 200 (698,454 B); 2022-2026 dates 500 across feeds, so the break is along the date axis, extent unmeasured.
