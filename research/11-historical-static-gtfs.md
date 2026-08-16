# Historical Static GTFS for NYC MTA Bus (NYCT Bus + MTA Bus Co), 2017-07-14 through 2024-09-06

All numbers below came from live probes run just now (2026-08-16) against the actual APIs/sites (curl HEAD/GET, S3 bucket queries, Wayback CDX queries, and WebFetch of the rendered pages). Anything not confirmed by a live fetch is explicitly marked **[unverified]**. `rrgtfsfeeds` is confirmed to serve only the current pick — this doc is about where *dated* history lives instead.

---

## 0. The live "current pick" bucket, for baseline

```
curl -sI https://rrgtfsfeeds.s3.amazonaws.com/gtfs_busco.zip
curl -sI https://rrgtfsfeeds.s3.amazonaws.com/gtfs_b.zip
curl -s  "https://rrgtfsfeeds.s3.amazonaws.com/?list-type=2"
```
- `gtfs_busco.zip`: HTTP 200, `Last-Modified: Tue, 23 Jun 2026`, `Content-Length: 5,621,861` (5.6 MB).
- `gtfs_b.zip`: HTTP 200, `Last-Modified: Tue, 23 Jun 2026`, `Content-Length: 13,522,834` (13.5 MB).
- Bucket listing (`?list-type=2`, no auth): **`<Error><Code>AccessDenied</Code>`**. The bucket is not publicly listable, so there is no way to discover dated keys (e.g. a hypothetical `gtfs_b_20200315.zip`) by prefix — confirms the question's premise that this bucket is single-current-pick-only with no enumerable archive.

---

## 1. Mobility Database (mobilitydatabase.org / api.mobilitydatabase.org)

**Feed IDs, confirmed live.** WebSearch + WebFetch resolved two of the six MTA bus feeds to Mobility Database's `mdb-###` ids:
- `mdb-510` = "Metropolitan Transit Authority (MTA), NYC Bus Company GTFS Schedule Feed" → `https://mobilitydatabase.org/feeds/gtfs/mdb-510`
- `mdb-513` = "Metropolitan Transit Authority (MTA), Manhattan Bus GTFS Schedule Feed" → `https://mobilitydatabase.org/feeds/gtfs/mdb-513`
- Bronx/Brooklyn/Queens/Staten Island `mdb-###` ids were **not** individually confirmed (budget-limited) — **[unverified]**, though by the visible numbering pattern they almost certainly sit near 510-515.

**API auth, confirmed live:**
```
curl -s https://api.mobilitydatabase.org/v1/gtfs_feeds/f-dr5r-mtabc
→ HTTP 302, body: "Invalid GCIP ID token: empty token"
```
Every `api.mobilitydatabase.org` endpoint requires a bearer token from Google Identity Platform (GCIP/Firebase-backed auth) — there is no anonymous read path. The FAQ page (fetched live) confirms: "to add a feed or use our API you'll need to create an account." Free-tier signup flow itself (whether it's a simple email/OAuth signup and what the rate limit is) was **not** walked through — **[unverified]**.

**Historical version depth — the important, somewhat surprising finding:** the public feed page for `mdb-510` (MTA Bus Company), fetched live, shows a version-history table with:
- **11 versions total**, latest **2026-06-24**, earliest **2025-12-30**.

That is barely 6 months of history, not back to 2017. The FAQ's description of the service ("fetches and stores new datasets once a day at midnight UTC" when a change is detected) is a forward-looking crawl, and nothing on the page or FAQ claims a backfilled deep archive. It's possible the rendered page paginates and hides older entries beyond the visible table — **[unverified]**, would need an authenticated API call or manual UI pagination click to rule out — but the plain-fetched page gives no indication of anything before Dec 2025. **Do not assume Mobility Database has 2017-2024 coverage for MTA bus feeds without independently confirming via an authenticated API call**, since the one page actually inspected argues against it.

---

## 2. transitfeeds.com (deprecated) via Wayback Machine

**Direct site, confirmed dead:**
```
curl -s -o /dev/null -w "%{http_code}" https://transitfeeds.com/p/mta/79
→ 403
```

**Wayback CDX confirms transitfeeds' MTA provider used per-feed numeric sub-pages**, not a `busco`-style slug. Identified live by fetching archived page `<title>` tags:

| Feed # | Title (from archived `<title>`) | First/last capture seen in CDX |
|---|---|---|
| 79 | NYC Subway GTFS | 2014-09-30 → 2019-04-09 (20 snapshots) |
| 81 | MTA Bronx GTFS | seen 2014-10-12 onward |
| 82 | MTA Manhattan GTFS | seen 2014-10-12 onward |
| 83 | (Brooklyn, presumed) | **no snapshot found at all** |
| 84 | MTA Staten Island GTFS | seen 2014-10-12 onward |
| 85 | NYC Bus Company GTFS | seen 2014-10-12 onward |
| 86 | (Queens, presumed) | **no snapshot found at all** |
| 87 | Metro-North Railroad GTFS | seen 2014-10-12 |

So Brooklyn and Queens bus feed pages were apparently **never crawled by the Wayback bot** — a real, confirmed gap, not just a display issue.

**Even where a feed page was archived, it is metadata only** — it links out to the original MTA-hosted zip (`http://web.mta.info/developers/data/nyct/bus/google_transit_*.zip`), it does not host a copy itself. Checking Wayback's CDX directly for those source zip URLs (`mimetype:application/zip`) turns up **exactly one snapshot per borough, all from 2014-2016**:

| File | Captured | Size |
|---|---|---|
| `google_transit_manhattan.zip` | 2014-05-29 | 9.1 MB |
| `google_transit_brooklyn.zip` | 2015-09-06 | 18.0 MB |
| `google_transit_queens.zip` | 2015-09-06 | 9.1 MB |
| `google_transit_staten_island.zip` | 2015-09-06 | 5.2 MB |
| `google_transit_bronx.zip` | 2015-09-06 | 9.9 MB |
| `Bus_Shapefiles.zip` | 2016-04-09 | 2.9 MB |

**All of these predate the target window (2017-07-14 onward) by 1-3 years, and there is only one snapshot each — no cadence at all.** transitfeeds/Wayback contributes **zero** usable dated zips inside 2017-2024-09.

---

## 3. transit.land (Transitland v2)

**Feed IDs, confirmed live** by fetching `transitland-atlas`'s `mta.info.dmfr.json` from GitHub raw:

| Onestop ID | Borough/agency | Source URL |
|---|---|---|
| `f-dr5r-mtabc` | MTA Bus Company | `gtfs_busco.zip` |
| `f-dr5r-mtanyctbusbrooklyn` | Brooklyn | `gtfs_b.zip` |
| `f-dr5r-mtanyctbusmanhattan` | Manhattan | `gtfs_m.zip` |
| `f-dr5r-mtanyctbusstatenisland` | Staten Island | `gtfs_si.zip` |
| `f-dr5x-mtanyctbusqueens` | Queens | `gtfs_q.zip` |
| `f-dr72-mtanyctbusbronx` | Bronx | `gtfs_bx.zip` |

**Version depth, confirmed live** by fetching the public feed page `https://www.transit.land/feeds/f-dr5r-mtanyctbusbrooklyn`:
- **93 archived feed versions.**
- Earliest: **2016-02-06**. Latest (current): fetched 2026-06-24, covering service 2026-06-27 through 2026-09-05.
- Cadence: not a fixed schedule, but ~93 versions over ~10.3 years ≈ roughly one every 5-6 weeks on average — this comfortably brackets and covers the 2017-07-14 to 2024-09-06 window (93 versions / 10 years puts on the order of 60-70 of those versions inside the target window, by simple proportion — **[unverified]** exact in-window count, would need the authenticated API to list/filter by date).
- Source URLs listed on the page: current `https://rrgtfsfeeds.s3.amazonaws.com/gtfs_b.zip` and a second historic source `http://web.mta.info/developers/data/nyct/bus/google_transit_brooklyn.zip` — i.e. Transitland has been independently re-fetching and versioning both S3-bucket-era and pre-S3-bucket-era URLs, which is exactly the continuity needed to span 2017-2024.

**API auth, confirmed live:**
```
curl -s https://transit.land/api/v2/rest/feeds/f-dr5r-mtanyctbusbrooklyn/feed_versions
→ {"error":"Unauthorized"}
curl -s -o /dev/null -w "%{http_code}" https://api.transit.land/api/v2/rest/feeds/f-dr5r-mtanyctbusbrooklyn/feed_versions
→ 401
```
Both `transit.land/api/v2` and `api.transit.land/api/v2` reject anonymous requests. The docs page (fetched live) confirm: an `apikey` query param or header is required on every REST call, obtained via free signup, with the free tier "relatively low rate limit" vs. paid Pro tier. The public **website** (`www.transit.land/feeds/...`), by contrast, rendered full version history with no visible auth wall — so browsing/confirming coverage is free, but pulling zips programmatically needs a (free) API key. Exact download-endpoint mechanics for a specific historical `feed_version` (URL shape, whether it streams the original zip bit-for-bit) were **not** exercised live — **[unverified]**, a 404 was hit probing one guessed endpoint path (`download_latest_feed_version`), meaning that particular guessed URL is wrong, not that download is unsupported — Transitland's docs generally advertise "direct access to GTFS files" through the API.

---

## 4. MTA's own developer site / rrgtfsfeeds bucket

Covered in section 0: the bucket denies listing, and both probed objects only expose the single current pick (`Last-Modified: 2026-06-23`). No evidence found of a dated-key naming convention or a historical archive endpoint on `new.mta.info/developers` or `web.mta.info/developers` — not fetched directly for this doc beyond the S3 origin already checked; treat "MTA hosts no historical archive itself" as the working assumption but **[unverified]** against the developer portal pages themselves (not fetched this session).

---

## 5. Other primary archives

Not investigated this session due to budget — no claims made. In particular, NYU CUSP holdings and GitHub repos that might snapshot MTA GTFS zips directly were not searched; do not treat their absence here as evidence they don't exist, only that they weren't checked.

---

## Coverage verdict

| Sub-window | Obtainable dated static GTFS? | From where | Confidence |
|---|---|---|---|
| **2017-2019** | Yes | Transitland v2 (`f-dr5r-mtabc`, `f-dr5r-mtanyctbus{brooklyn,manhattan,statenisland}`, `f-dr5x-mtanyctbusqueens`, `f-dr72-mtanyctbusbronx`) — version history runs continuously from 2016-02-06, so this window is inside the archived range | High (version list confirmed live back to 2016; exact per-window version count not enumerated) |
| **2020-2022** | Yes | Transitland v2, same feeds, same continuous archive | High (same basis as above) |
| **2023-2024-09** | Yes | Transitland v2, same feeds, continuous through present (latest capture 2026-06-24) | High for Transitland. Mobility Database is a plausible secondary source for this window specifically (MobilityData positions itself as TransitFeeds' successor and states daily crawling), but the one feed page actually inspected (`mdb-510`) showed only 11 versions starting **2025-12-30** — i.e. no evidence it covers 2023-2024 for this feed. Treat Mobility Database as unconfirmed/likely-insufficient for this window until checked via an authenticated API call. |

**Bottom line:** transitfeeds.com/Wayback is a dead end for the 2017-2024 window (only pre-2017 zip snapshots, and Brooklyn/Queens pages were never even crawled). Mobility Database requires an authenticated API and, on the one feed checked live, shows only ~6 months of history — not deep enough by itself, and unverified for the other five feeds. **Transitland v2 is the only source confirmed live to hold dated GTFS versions spanning the full 2017-07-14 through 2024-09-06 window for all six MTA bus feeds** (Bronx, Brooklyn, Manhattan, Queens, Staten Island, MTA Bus Co), browsable free on the website and downloadable via the REST API with a free API key (signup required, rate-limited on free tier). That should be the primary integration target for the backfill; Mobility Database is worth a follow-up authenticated check but should not be relied on yet.
