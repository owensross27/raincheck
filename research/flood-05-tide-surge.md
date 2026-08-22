# NOAA Tide/Surge Products for NYC — History Stations + Real-Time/Forecast Guidance

Researched 2026-08-22. All findings below come from real HTTP requests (curl to `api.tidesandcurrents.noaa.gov`, `mesonet.agron.iastate.edu`, `nomads.ncep.noaa.gov`, `nco.ncep.noaa.gov`, `nhc.noaa.gov`, `tgftp.nws.noaa.gov`), not memory. A prior vault note (`~/vault/nyc-flood-history-elevation-2026-08-12.md`, CO-OPS section) made claims about the Battery station only; those are re-verified here (with one correction) and extended to five more stations plus the real-time/forecast half. See the Evidence table for exact status codes and payload sizes.

## Verdict

**History (Half 1):** Six CO-OPS stations qualify as "NYC-area with a populated `floodlevels.json`": Battery 8518750, Kings Point 8516945, Sandy Hook 8531680 (NJ), Bridgeport 8467150 (CT), New Haven 8465705 (CT), New London 8461490 (CT). The station named "Bergen Point West Reach" does not exist; the nearby candidate, Robbins Reef 8530973 (Upper NY Bay), exists but is a currents-only PORTS station — no flood thresholds, no historic water-level series. `datum=NAVD` works directly as a `datagetter` parameter and matches the manual STND-minus-offset calculation; the offset is confirmed per-station (Battery 6.06 ft, Kings Point 17.09 ft, Sandy Hook 5.33 ft, Bridgeport 5.82 ft) via `datums.json` — do not reuse Battery's 6.06 elsewhere. The Battery's "reaches back to 1920-06" claim is correct but **misleading**: the record has real gaps (no data 1923, 1925, 1926) before settling into continuity around 1927; Sandy Hook's clean record actually starts earlier (~1910). `high_low` truncation is **not** a fixed 1979 cutoff — it varies 1979-1980 station to station, and for younger stations equals whatever year `hourly_height` itself starts.

**Real-time/forecast (Half 2):** CO-OPS `water_level` (6-min) and `predictions` (harmonic, verified out to year 2100) both work exactly as expected, keyless, json/csv/xml, with a hard 365-day range cap (HTTP 400 past that). Of the three NWS/NOS surge-guidance products: **STOFS-2D-Global is live and directly fetchable today** (real 2.65 MB grib2 downloaded, 4 cycles/day, 0-180h horizon, confirmed both by download and by NCO's own product page). **ETSS is effectively dead** — its NOMADS path now 403s and its `tgftp` mirror's files are stale since 2025-09-02 (~11.5 months old), i.e. it has been superseded by STOFS operationally, matching the ticket's premise. **P-Surge exists and is structurally reachable** (`nomads.ncep.noaa.gov/.../psurge/prod/` returns HTTP 200) but is tropical-cyclone-conditioned — right now it's empty because there is no active Atlantic storm (confirmed via NHC's `CurrentStorms.json`, which shows only two Central/East Pacific storms). IEM's `watchwarn.py` works and returns real coastal-flood hits for OKX (confirmed for Hurricane Sandy Oct 2012 and a Jan 2024 nor'easter) — but **the `phenomena[]`/`significance[]` query params are silently ignored unless `limitps=yes` is also set**, and the similarly-named `limit1=yes` flag is a trap that actively excludes Coastal Flood (CF) events (it restricts to Thunderstorm/Marine/Flash-Flood Warnings only).

| Product | Status | Key numbers |
|---|---|---|
| CO-OPS `water_level` (6-min) | Live, keyless | 240 pts/day confirmed; json/csv/xml all 200 |
| CO-OPS `predictions` | Live, keyless | Works to year 2100 (harmonic, no real horizon limit) |
| CO-OPS `datum=NAVD` | **Works** | Matches STND-offset arithmetic to 0.003 ft (rounding only) |
| STOFS-2D-Global | **Fetchable now** | grib2, 4x/day (00/06/12/18z), FH 000-180 |
| ETSS | **Dead** | NOMADS 403; tgftp mirror last updated 2025-09-02 |
| P-Surge | Reachable, empty now | 200 OK, 0 bytes — no active Atlantic TC today |
| IEM `watchwarn.py` | Live, keyless | Real CF hits for OKX/Sandy and OKX/Jan-2024; `phenomena[]` needs `limitps=yes` |

---

## 1. NYC-area CO-OPS station inventory

`GET https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=waterlevels` → 200, 774,813 B, 301 stations nationwide. Filtered to state NY/NJ/CT:

| ID | Name | State | Notes |
|---|---|---|---|
| 8518750 | The Battery | NY | primary, in NY Harbor |
| 8516945 | Kings Point | NY | western Long Island Sound (Great Neck) |
| 8531680 | Sandy Hook | NJ | harbor entrance, surge-propagation relevant |
| 8467150 | Bridgeport | CT | central CT shoreline, LIS |
| 8465705 | New Haven | CT | central CT shoreline, LIS |
| 8461490 | New London | CT | eastern CT shoreline, mouth of LIS |
| 8510560 | Montauk | NY | far eastern LI, not harbor-relevant |
| 8518962 / 8518979 | Turkey Point / Coxsackie (Hudson R.) | NY | ~130 mi upriver, out of scope |
| 8534720 / 8536110 / 8537121 / 8539094 | Atlantic City / Cape May / Ship John Shoal / Burlington | NJ | Delaware Bay/River side, out of scope |

Of these, **Kings Point and Sandy Hook are the two that genuinely sit in/near NY Harbor or western LIS**; Bridgeport/New Haven/New London are farther up the Connecticut shoreline (included for completeness since they're the only other stations with populated flood thresholds in the region, but they're progressively less relevant to NYC-specific surge).

A full-text search of the unfiltered 301-station list for "robbins", "bergen", "narrows", "rockaway", "coney", "willets" returned **zero matches** — "Bergen Point West Reach" is not a CO-OPS station name. The closest real station is **Robbins Reef, 8530973** (Upper NY Bay, near the Verrazzano Narrows, NJ side) — found via `GET stations/8530973.json` (200, 2636 B). It exists in the metadata catalog but:
- `stormsurge: false`, `affiliations: "PORTS"` (a currents-focused tenant station)
- `GET stations/8530973/floodlevels.json` → **HTTP 200 but empty-of-content in the current-vs-nearby sense: real JSON with all four thresholds null-equivalent** — actually returned `HTTP:404` with a Tomcat 404 HTML body (431 B), i.e. the floodlevels resource doesn't exist for this station at all.
- `hourly_height` probes across 1900-2026 all returned `{"error":{"message":"No data was found. This product may not be offered at this station at the requested time."}}` — no historic water-level series either.

**Conclusion: Robbins Reef is not usable for either the flood-threshold half or the historic-series half of this ticket.**

## 2. Flood thresholds (`floodlevels.json`) — confirmed for six stations

All in feet on **Station Datum (STND)**, matching the prior note's units claim (re-verified, not assumed):

| Station | nos_minor | nos_moderate | nos_major | nws_minor | nws_moderate | nws_major | action |
|---|---|---|---|---|---|---|---|
| 8518750 Battery | 10.19 | 11.12 | 12.39 | 10.49 | 11.74 | 13.24 | 10.29 |
| 8516945 Kings Point | 22.64 | 23.55 | 24.84 | 22.89 | 23.39 | 25.89 | null |
| 8531680 Sandy Hook | 9.59 | 10.52 | 11.79 | 9.21 | 10.24 | 11.24 | 8.71 |
| 8467150 Bridgeport | 11.23 | 12.15 | 13.43 | 10.90 | 12.40 | 13.40 | null |
| 8465705 New Haven | 27.05 | 27.97 | 29.25 | 27.04 | 27.64 | 28.94 | null |
| 8461490 New London | 8.33 | 9.29 | 10.53 | 8.47 | 9.47 | 11.32 | null |
| 8530973 Robbins Reef | — | — | — | — | — | — | (404, not populated) |

Note: Kings Point's `nws_moderate` (23.39) is *below* its own `nos_moderate` (23.55) — an inversion not seen at any other station checked. This is real NOAA-published data, not a fetch error (re-fetched, reproducible); flag it if building any cross-station threshold logic that assumes NOS/NWS levels are monotonic in the same direction across stations.

Only Battery and Sandy Hook have a non-null `action` stage among the six.

## 3. Historic `hourly_height` earliest data and `high_low` truncation, per station

**Method:** binary search by year, probing a `begin_date=YYYY0101&end_date=YYYY0107` window (7 days) at each candidate year — this finds the earliest **January** with data, not necessarily the true start date, and cannot see gaps mid-record. Demonstrated directly on the Battery below.

### 3a. Battery 8518750 — the prior note's "1920-06" claim, checked with gaps exposed

| Query | Result |
|---|---|
| `hourly_height` 1920-01-01..07 | no data |
| `hourly_height` 1920-06-01..07 | **200, 167 pts** (t starts 1920-06-01 01:00) |
| `hourly_height` 1920-07-01..07 | 200, 168 pts |
| `hourly_height` 1920-12-01..07 | 200, 168 pts |
| `hourly_height` 1921-01-01..07 | 200, 168 pts |
| `hourly_height` 1923-01-01..07 | **no data** |
| `hourly_height` 1925-01-01..07 | **no data** |
| `hourly_height` 1926-01-01..07 | **no data** |
| `hourly_height` 1927-01-01..07 | 200, 168 pts |

**Correction to the prior vault note:** "reaches back to 1920-06" is true for the earliest timestamp, but the series is **not continuous** from there — there's a multi-year gap (data missing for at least 1923, 1925, 1926) before the record becomes reliably populated starting ~1927. Anyone building an exceedance series from 1920 needs gap-handling logic, not a straight "start=1920-06-01" assumption.

### 3b. Earliest year with January `hourly_height` data, all six stations (binary search, coarse)

| Station | Earliest year (Jan window) found |
|---|---|
| 8518750 Battery | 1927 (real start 1920-06, but gappy — see 3a) |
| 8531680 Sandy Hook | **1910** — spot-checked directly: 1908/1909 no data, 1910-01-01 → 200, 167 pts. Longer clean-looking record than the Battery. |
| 8461490 New London | 1939 |
| 8467150 Bridgeport | 1970 |
| 8516945 Kings Point | 1999 |
| 8465705 New Haven | 2000 |
| 8530973 Robbins Reef | never found (no `hourly_height` product at any year 1900-2026) |

### 3c. `high_low` truncation, per station

Tested 1978/1979/1980 boundary directly for five stations, then binary-searched the true earliest year:

| Station | 1978 | 1979 | 1980 | Earliest `high_low` year (binary search) |
|---|---|---|---|---|
| 8518750 Battery | no data | **200, 27 pts** | 200 | 1979 |
| 8461490 New London | no data | **200, 27 pts** | 200 | 1979 |
| 8531680 Sandy Hook | no data | no data | **200, 27 pts** | 1980 |
| 8467150 Bridgeport | no data | no data | **200, 27 pts** | 1980 |
| 8516945 Kings Point | no data | no data | no data | **1999** (matches its `hourly_height` start — no separate historic high/low product predating the hourly series) |

**Correction to the prior note:** the "high_low truncates at 1979" claim is Battery-specific, not universal. It's 1979 for Battery and New London, 1980 for Sandy Hook and Bridgeport, and for younger stations like Kings Point it simply starts whenever the station itself came online (1999) — there's no separate older `high_low`-only archive to fall back on.

`ty` field values observed directly in a real `high_low` payload (Battery, 2020-01-01..03): **`"HH"`, `"H "`, `"L "`, `"LL"`** — four codes (Higher-High, High, Low, Lower-Low), not just two. "H " and "L " are indeed space-padded to 2 chars as the prior note said, but the note's phrasing ("H ", "L ") should be read as *two of four* codes, with HH/LL unpadded.

## 4. NAVD88 conversion — `datum=NAVD` param and per-station offsets

`GET .../datagetter?product=hourly_height&station=8518750&begin_date=20120101&end_date=20120102&datum=NAVD&...` → **HTTP 200**, real values (e.g. `2012-01-01 00:00, -1.401`).

Cross-checked against the same request with `datum=STND` (`2012-01-01 00:00, 4.662`): `4.662 - (-1.401) = 6.063`. `GET stations/8518750/datums.json` (200, 2203 B) lists `{"name":"NAVD88","value":6.06}` — the true internal offset is **6.063 ft**, and the published `datums.json` value is the same number rounded to 2 decimals. So: **`datum=NAVD` works directly and is preferable to manual subtraction** — using the rounded 6.06 constant introduces up to a 0.003 ft error per point versus what the API actually applies.

Per-station NAVD88 offsets, confirmed via `datums.json` (all 200 OK):

| Station | NAVD88 offset from STND (ft) |
|---|---|
| 8518750 Battery | 6.06 |
| 8516945 Kings Point | **17.09** |
| 8531680 Sandy Hook | **5.33** |
| 8467150 Bridgeport | **5.82** |

**Confirms the prior note's caveat as fact, not assumption:** the STND→NAVD88 offset is entirely station-specific (Kings Point's is nearly 3x Battery's, because STND is an arbitrary station benchmark, not a shared reference). Never reuse 6.06 for any station other than 8518750 — either look up each station's own `datums.json` value, or just pass `datum=NAVD` directly and skip the arithmetic (recommended, since it also sidesteps the rounding gap above).

## 5. Real-time and forecast products — CO-OPS `water_level` / `predictions`

- **`product=water_level`** (6-minute observed): `GET .../datagetter?product=water_level&station=8518750&date=latest&datum=MLLW&...&format=json` → 200, single most-recent point, `"q":"p"` (preliminary, not yet QC'd — expected for real-time). A full-day request (`begin_date=end_date=20260821`) returned **exactly 240 points** (24h × 10/hr), confirming true 6-minute cadence. `"f"` flags field present (`"1,0,0,0"`).
- **`product=predictions`** (harmonic tide predictions): requested `begin_date=20351231` (9 years out) → 200 with real values; requested `begin_date=21000101` (74 years out) → **still 200 with real values**. Predictions are computed from harmonic constituents, not a forecast model, so there is effectively no near-term horizon limit — confirmed by not finding one even 74 years out.
- **Formats**: `format=json`, `format=csv`, `format=xml` all confirmed 200 with correctly-shaped payloads for `predictions`.
- **365-day cap**: `begin_date=20200101&end_date=20210102` (366 days) on `hourly_height` → **HTTP 400**, body `{"error":{"message":" Wrong Date: ... Range Limit Exceeded: The size limit for data retrieval for this product is 365 days "}}`. Confirms the prior note's cap claim, with the exact status code and message now on record (prior note didn't specify the status).

## 6. NWS/NOS storm-surge guidance: ETSS vs STOFS vs P-Surge

### ETSS (Extratropical Storm Surge) — dead in practice
- `GET https://nomads.ncep.noaa.gov/pub/data/nccf/com/etss/prod/` → **HTTP 403** (all four tested cycles, all 403)
- Fallback mirror `GET https://tgftp.nws.noaa.gov/SL.us008001/ST.expr/DF.gr2/DC.ndgd/GT.etss/AR.conus/` → **HTTP 200**, real directory listing, but every file's `Last modified` timestamp is **`02-Sep-2025`** — i.e. ~11.5 months stale relative to today (2026-08-22). NCO's own product-inventory page (`nco.ncep.noaa.gov/pmb/products/etss/`) is similarly dated "Updated: 02/25/2021". **ETSS is not being actively regenerated; treat it as decommissioned, not just hard-to-reach.**

### STOFS-2D-Global — live and fetchable today
- NCO product page (`nco.ncep.noaa.gov/pmb/products/stofs/`, 200, 25,996 B) documents the naming convention and explicitly states **`FH 000-180`** for `conus.east` (the grid that covers NYC).
- Directly fetched `https://nomads.ncep.noaa.gov/pub/data/nccf/com/stofs/prod/stofs_2d_glo.20260822/stofs_2d_glo.t12z.conus.east.f000.grib2` → **HTTP 200, 2,651,603 bytes**, real grib2 binary (saved and `ls -la` verified).
- Cycle availability tested for 2026-08-21 and 2026-08-22: **00z, 06z, 12z, 18z all HTTP 200** (except 18z for the current day, not yet produced at query time — normal for an in-progress cycle) → confirms **4 cycles/day**.
- Forecast-hour probe on the 12z cycle: f096, f120, f180 → 200; **f186, f192, f198, f204, f240 → 404**. Matches NCO's documented `FH 000-180` exactly — empirical result and vendor documentation agree.
- Products available per cycle include `.fxxx.grib2` (hourly forecast fields), `.cwl.grib2`/`.htp.grib2`/`.swl.grib2` (combined/tide/surge-only water level), and NetCDF variants (`fields.cwl.nc`, `points.cwl.nc` — the latter is likely a station-extracted product worth a follow-up look if point time series at named stations are wanted instead of gridded fields).
- **This is the operational replacement for ETSS** — matches the ticket's framing precisely.

### P-Surge / P-ETSS — reachable structure, empty without an active storm
- NCO product page (`nco.ncep.noaa.gov/pmb/products/psurge/`, 200, 23,041 B) confirms: "Tropical Cyclone Storm Surge Probabilities (P-Surge)", filename pattern uses `EE` = exceedance percent (10/20/30/40/50/90) and `GG` = probability threshold in feet, cycle times 00/06/12/18z — i.e. genuinely tropical-cyclone-conditioned, not a standing gridded product.
- `GET https://nomads.ncep.noaa.gov/pub/data/nccf/com/psurge/prod/` → **HTTP 200, 0 bytes body** (directory exists, currently empty).
- Cross-checked against NHC's live storm feed: `GET https://www.nhc.noaa.gov/CurrentStorms.json` → 200, 9,230 B, lists exactly two active systems today — **`cp012026` Lala (HU) and `cp022026` Moke (TS)**, both Central/East Pacific, nowhere near the Atlantic/NYC. **No Atlantic tropical cyclone is active, which fully explains the empty P-Surge directory** — the product genuinely only exists during an active storm threatening the relevant basin, exactly as hypothesized in the ticket. `nomads.ncep.noaa.gov/pub/data/nccf/com/psurge2/prod/` (a guessed alternate path) → 403, not a valid path.

**Ranking for the ticket's ask:** STOFS-2D-Global is fetchable right now with zero extra tooling (plain HTTPS GET, no NOMADS filter-download UI, no AWS bucket navigation needed) — this is the one to build against. ETSS should be dropped as a source entirely. P-Surge is real and reachable the same simple way, but only produces output during an active, relevant tropical cyclone — build the fetch logic to expect empty results most of the time and treat a populated response as itself a signal.

## 7. IEM `watchwarn.py` — phenomena/significance codes, and a real filtering trap

Endpoint: `https://mesonet.agron.iastate.edu/cgi-bin/request/gis/watchwarn.py`. Default (no `accept` param) returns a **zip of shapefile parts** (confirmed: `PK` zip header, 1,689 B for a small query). `accept=csv` returns a real CSV (confirmed against the live HTML form's own `accept` field, which only permits `^(shapefile|excel|csv|kml)$` — `accept=geojson` is **not valid** and correctly 422s with a pydantic validation message naming the allowed pattern).

**Codes confirmed live from the request form itself** (`GET https://mesonet.agron.iastate.edu/request/gis/watchwarn.phtml`, 200, 83,131 B — parsed the actual `<select>` options, not guessed):
- Phenomena (relevant subset): `CF`=Coastal Flood, `FA`=Flood (areal), `FF`=Flash Flood, `FL`=Flood, `LS`=Lakeshore Flood, **`SS`=Storm Surge (exists as a real VTEC phenomenon)**, `SU`=High Surf.
- Significance: `W`=Warning (default-selected), `Y`=Advisory, `A`=Watch, `S`=Statement, `O`=Outlook, `N`=Synopsis, `F`=Forecast.

**The trap — verified and root-caused, not just observed:** the query params `phenomena[]=CF&significance[]=Y` (or `phenomena=CF&significance=Y` without brackets — both tried) have **zero filtering effect** unless a separate flag, **`limitps=yes`**, is also set. Proven by diffing a "filtered" request against a genuinely unfiltered one for the same station/date range: byte-identical (764 lines each, `diff` empty) for OKX/Jan-2024. The form's own label for `limitps` is *"Limit output to selected VTEC phenomena and significance below"* — i.e. `limitps` is what actually turns the phenomena/significance filter on; without it those params are silently no-ops.

A second, differently-named flag, **`limit1`**, is a separate trap: its form label is *"Limit output to only Thunderstorm, Marine, and Flash Flood Warnings"* — setting `limit1=yes` while querying for Coastal Flood (CF) events **actively excludes them** (reproduced: same query with `limit1=yes&limitps=yes` → 0 rows; with `limitps=yes` alone → 18 real CF rows for the same window). Do not set `limit1` when the target phenomenon is CF/SS/FA.

**Real hits, confirmed with actual payload (not just 200-with-empty-CSV):**
- **Hurricane Sandy, OKX, 2012-10-27 to 2012-11-02, `phenomena[]=CF&significance[]=A,W,Y&limitps=yes`** → 200, real rows, e.g. `OKX,2012-10-28 23:00,...,CF,C,A,1,UPG,CTZ012,...,201210270946-KOKX-WHUS41-CFWOKX` (18 UGC-zone rows from a single Coastal Flood Watch product upgraded to Warning).
- **Jan 2024 nor'easter, OKX, unfiltered** → 764 total VTEC rows for the month; client-side-filtered to `phenomena=='CF'` → **110 rows**, real product IDs like `202401070745-KOKX-WHUS41-CFWOKX` (Advisory) and `202401290906-KOKX-WHUS41-CFWOKX` (Statement).

**Practical takeaway for the raincheck pipeline:** either always pass `limitps=yes` alongside `phenomena[]`/`significance[]` (and never `limit1`), or — safer, since the silent-ignore behavior means a future API change could re-break this quietly — fetch unfiltered by WFO/date-range and filter client-side on the returned `phenomena`/`significance` CSV columns, exactly as done for verification above.

---

## Evidence

| # | Request | Result |
|---|---|---|
| 1 | `GET mdapi/.../stations.json?type=waterlevels` | 200, 774,813 B, 301 stations |
| 2 | `GET mdapi/.../stations/8530973.json` | 200, 2,636 B — Robbins Reef metadata, `stormsurge:false` |
| 3 | `GET mdapi/.../stations/8530973/floodlevels.json` | **404**, 431 B, Tomcat error page |
| 4 | `GET mdapi/.../stations/{8518750,8516945,8531680,8467150,8465705,8461490}/floodlevels.json` | 200 ×6, ~257-262 B each, real threshold JSON |
| 5 | `GET datagetter?product=hourly_height&station=8518750&begin_date=1920060{1..7}` | 200, 167 pts, t starts `1920-06-01 01:00` |
| 6 | same, `begin_date=1923/1925/1926 0101` | no data (×3), error message re: product not offered |
| 7 | same, `station=8531680&begin_date=19100101` | 200, 167 pts (Sandy Hook data by 1910) |
| 8 | `GET datagetter?product=high_low&station={5 stations}&begin_date=1978/1979/1980 0101` | mixed 200/no-data, see table in §3c |
| 9 | `GET datagetter?product=hourly_height&station=8518750&datum=NAVD&begin_date=20120101` | 200, `-1.401` vs STND `4.662` → offset 6.063 |
| 10 | `GET mdapi/.../stations/{4 stations}/datums.json` | 200 ×4, NAVD88 values 6.06 / 17.09 / 5.33 / 5.82 |
| 11 | `GET datagetter?product=water_level&station=8518750&date=latest` | 200, 1 pt, `q:"p"` |
| 12 | `GET datagetter?product=water_level&station=8518750&begin_date=end_date=20260821` | 200, exactly 240 pts |
| 13 | `GET datagetter?product=predictions&station=8518750&begin_date=21000101` | 200, real values, 74 yrs out |
| 14 | `GET datagetter?product=hourly_height&station=8518750&begin_date=20200101&end_date=20210102` | **400**, "Range Limit Exceeded ... 365 days" |
| 15 | `GET nomads.ncep.noaa.gov/.../etss/prod/` | **403** (×4 cycles) |
| 16 | `GET tgftp.nws.noaa.gov/.../GT.etss/AR.conus/` | 200, 832 B listing, files dated 2025-09-02 |
| 17 | `GET nco.ncep.noaa.gov/pmb/products/stofs/` | 200, 25,996 B, documents `FH 000-180` |
| 18 | `GET nomads.ncep.noaa.gov/.../stofs_2d_glo.20260822/....t12z.conus.east.f000.grib2` | **200, 2,651,603 B**, real grib2 |
| 19 | same, f186/f192/f198/f204/f240 | all 404 (horizon confirmed ≤180h) |
| 20 | `GET nco.ncep.noaa.gov/pmb/products/psurge/` | 200, 23,041 B, describes EE/GG naming |
| 21 | `GET nomads.ncep.noaa.gov/.../psurge/prod/` | 200, 0 B (empty, no active storm) |
| 22 | `GET nhc.noaa.gov/CurrentStorms.json` | 200, 9,230 B, 2 active storms, both Pacific |
| 23 | `GET mesonet.../watchwarn.phtml` | 200, 83,131 B, live form with phenomena/significance `<select>` options |
| 24 | `GET .../watchwarn.py?...accept=geojson` | **422**, pydantic pattern-mismatch error |
| 25 | `GET .../watchwarn.py?...phenomena[]=CF&significance[]=Y&accept=csv` (no `limitps`) | 200, byte-identical to unfiltered (764 lines) |
| 26 | `GET .../watchwarn.py?...limitps=yes` (Sandy period) | 200, 18 real CF rows |
| 27 | `GET .../watchwarn.py?...limit1=yes&limitps=yes` (Sandy period) | 200, **0 rows** (limit1 excludes CF) |
| 28 | `GET .../watchwarn.py?sts=2024-01-01...&wfos[]=OKX&accept=csv` (unfiltered) | 200, 764 lines, 110 CF rows after client-side filter |

## Unverified

- **Kings Point `nws_moderate` < `nos_moderate` inversion** — confirmed as real API output (re-fetched), but not cross-checked against NOAA's public-facing flood-levels web page to rule out a data-entry artifact upstream of the API.
- **Binary-search "earliest year" values for Sandy Hook (1910), New London (1939), Bridgeport (1970), New Haven (2000)** are upper bounds from a January-window probe only — like the Battery, any of these could have gaps or an even-earlier true start in a different month. Only the Battery's gap pattern was actually mapped out.
- **STOFS `points.cwl.nc` product** — named in NCO's file inventory as a station-extracted NetCDF variant, not fetched or inspected; could be a more direct way to get point guidance near CO-OPS stations than parsing gridded `conus.east` output, worth a follow-up.
- **P-Surge cadence during an actual active storm** — the directory structure and file-naming convention are documented and the empty-when-no-storm behavior is confirmed, but no live P-Surge file was ever downloaded (no qualifying storm was active during this research session).
- **IEM `watchwarn.py` behavior for the `SS` (Storm Surge) phenomenon specifically** — confirmed to exist as a selectable code in the form, and queried (returned 0 rows for the pre-2017 Sandy period, which is expected since VTEC didn't carry a dedicated Storm Surge Watch/Warning phenomenon until 2017), but not confirmed against a post-2017 storm with a real Storm Surge Warning for OKX (e.g., an approaching major hurricane) since none occurred in a quick-checkable window this session.
- **Data licensing/terms for any of these products** — not investigated; out of scope for this ticket but relevant before bulk-downloading STOFS or CO-OPS data into the pipeline.
