## research/subway-flood-labels.md — MTA Service Alerts: flood/water-condition labeling in `3h5b-5ktz` (2012-2020) and `7kct-peq7` (Apr 2020-)

**Method:** Socrata Open Data API (SODA) against `data.ny.gov`, no auth, `$select`/`$where`/`$group`. Flood filter used throughout:
```
upper(header) like '%FLOOD%' OR upper(description) like '%FLOOD%'
OR upper(header) like '%WATER COND%' OR upper(description) like '%WATER COND%'
```
(covers "flood", "flooding", and MTA's pre-2020 term-of-art "water condition"). All calls returned HTTP 200; sizes/rows quoted per call in Evidence.

### Verdict (one paragraph)

There is no dedicated "flood" label or structured station field in either dataset — flooding is only recoverable by text-matching `header`/`description`. Pre-2020 alerts used a near-universal boilerplate, `"... due to a water condition at <Station Name>."`; post-2020 alerts say `"flood"`/`"flooding"` directly, usually also naming a station. Both datasets show heavy within-incident repetition (the 2012-2020 set via a reused `status_id` — despite the dataset's own description claiming no such grouping — and the 2020+ set via explicit `event_id`/`update_number`), so raw keyword-matched row counts overstate the number of distinct flood incidents, sometimes by 3-5x. No "affected entities" companion table exists on the data.ny.gov catalog; `affected` is a free-text, pipe-delimited list of **routes/lines**, not stations.

---

### 1. Columns (GET `/api/views/<id>.json`)

**`3h5b-5ktz` — "MTA Service Alerts: 2012 - 2020"** (320,743 rows; date range 2012-10-02T10:21 to 2020-03-31T22:49; dataset page created 2025-02-04, i.e. published as a backfilled archive, not live since 2012)

| field | type | notes |
|---|---|---|
| `status_id` | text | Socrata's own column description: "Multiple records may share the same Status ID if they are revisions of the same alert" — the de facto revision key (see §5) |
| `date` | calendar_date | full timestamp, second precision |
| `agency` | text | values: `Subway`, `Bus`, `LIRR`, `BT`, `MNR` |
| `status_label` | text | alert type/status; 27 distinct values, Title Case (Delays, Service Change, Planned Work, Suspended, Sandy Reroute, …) |
| `affected` | text | pipe-delimited **routes/lines/branches** — "affected subway/rail line, branch, or bus routes" per Socrata column description |
| `header` | text | ≤160 chars |
| `description` | text | free text; often identical to header or empty |

**`7kct-peq7` — "MTA Service Alerts: Beginning April 2020"** (512,892 rows; date range 2020-04-28T13:08 to 2026-06-29T23:57 [most recent row as of this query]; dataset page created 2024-05-01)

| field | type | notes |
|---|---|---|
| `alert_id` | number | row key |
| `event_id` | number | "groups all updates for a particular incident" |
| `update_number` | number | sequence within `event_id`, starts at 0 |
| `date` | calendar_date | full timestamp |
| `agency` | text | values: `NYCT Subway`, `NYCT Bus`, `LIRR`, `MNR`, `BT` |
| `status_label` | text | alert type/status; kebab-case, pipe-combinable (`delays`, `part-suspended`, `station-notice`, `reroute \| delays`, …), 50+ distinct combos seen |
| `affected` | text | pipe-delimited routes/lines (same semantics as old dataset) |
| `header` | text | ≤160 chars |
| `description` | text | free text; frequently `null` |

**No lat/long, stop_id, station_id, or complex_id column in either dataset.** `affected` is documented by Socrata itself as routes/lines, not stations — there is no structured station field (see §3).

---

### 2. Flood/flooding/water-condition mentions, per year and per agency (raw keyword-matched row counts)

**`3h5b-5ktz` (2012-2020)** — 787 matching rows total

| year | n | | agency | n |
|---|---|---|---|---|
| 2013 | 1 | | Bus | 472 |
| 2014 | 14 | | Subway | 186 |
| 2015 | 26 | | BT | 89 |
| 2016 | 87 | | LIRR | 23 |
| 2017 | 214 | | MNR | 17 |
| 2018 | 282 | | | |
| 2019 | 160 | | | |
| 2020 | 3 | | | |

**`7kct-peq7` (Apr 2020 – Jun 2026)** — 1,521 matching rows total

| year | n | | agency | n |
|---|---|---|---|---|
| 2020 | 5 | | NYCT Bus | 665 |
| 2021 | 334 | | NYCT Subway | 435 |
| 2022 | 132 | | MNR | 234 |
| 2023 | 495 | | LIRR | 168 |
| 2024 | 324 | | BT | 19 |
| 2025 | 186 | | | |
| 2026 | 45 (partial year, through Jun 29) | | | |

Notable: 2018 is the pre-2020 peak (282, all agencies); 2023 is the post-2020 peak (495), consistent with the Sept 29 2023 flash flood. **Bus consistently has more flood-keyword rows than Subway in both eras** — plausible given bus routes cross more street-level flood-prone locations, but not investigated further.

**Caveat:** these are raw rows, not de-duplicated incidents — see §5.

---

### 3. Station-specificity of the subway subset

No structured stop/station field exists (confirmed from the full column list above). Analysis of all 621 flood-keyword-matched **subway** rows (186 old + 435 new):

| proxy measure | hits | fraction |
|---|---|---|
| literal word "station" in header/description | 146 / 621 | 23.5% |
| flood/water-condition keyword directly followed by "at/near \<location\>" | 200 / 621 | 32.2% |
| broader Street/Avenue/hyphenated-complex-name pattern anywhere in text | 479 / 621 | 77.1% |
| "flood protection/mitigation/barrier/resiliency" (planned work, not an active flood) | 5 / 621 | 0.8% |

Manual sampling confirms the dominant phrasing template names a specific station by its everyday name even though there's no field for it:
- Old: `"[R] trains are running with delays due to a water condition at Queens Plaza."`
- New: `"238 St on the 1 line is closed because of a flood at street-level."` / `"...flooding caused by overflowing street drains at 149 St - Grand Concourse."`

So **practical station-specificity is high (majority of alerts name a real station), but it is only recoverable by parsing free text** (regex/NER against the ~472-name GTFS subway stop list) — not by querying a column. During the largest events (Ida, Sept 2023) a meaningful share of alerts are deliberately system-wide ("across New York City" / "across the region") rather than station-specific, which is expected and lowers the measured fraction during those windows specifically.

---

### 4. Coverage of known events (NYCT Subway, flood-keyword filter)

**Hurricane Ida — 2021-09-01 to 2021-09-02**: 183 alert-updates across **29 distinct `event_id`**, all timestamped 2021-09-02 (00:00–23:59); **zero matches on 2021-09-01** by the literal keyword filter, even though a water-related precursor already existed that evening (`event_id 29572`, update 1, 2021-09-01T23:55: *"...crews drain water limiting our ability to move switches at 59 St-Columbus Circle"* — does not contain "flood" or "water condition" verbatim, so it's excluded by keyword matching though clearly related).

| event_id | first seen | updates | line(s) | first header (truncated) |
|---|---|---|---|---|
| 29609 | 02:31 | 30 | ALL (system-wide) | Train service is extremely limited, if not even suspended, because of heavy rainfall and flooding across the region… |
| 29637 | 05:36 | 8 | F | F service is extremely limited and partially suspended because of heavy rainfall and flooding… |
| 29639 | 05:45 | 8 | L | L service is extremely limited and partially suspended because of heavy rainfall and flooding… |
| 29640 | 05:46 | 8 | 2 | 2 service is extremely limited and partially suspended because of heavy rainfall and flooding… |
| 29641 | 05:48 | 5 | 4 | 4 service is extremely limited and partially suspended because of heavy rainfall and flooding… |
| 29642 | 05:49 | 11 | 1 | 1 service is extremely limited and partially suspended because of heavy rainfall and flooding… |
| 29643 | 05:51 | 6 | 6 | 6 service is extremely limited and partially suspended because of heavy rainfall and flooding… |
| 29647 | 06:56 | 7 | R | R service is extremely limited because of heavy rainfall and flooding… |
| 29648 | 06:57 | 9 | D | D service is extremely limited and partially suspended because of heavy rainfall and flooding… |
| 29649 | 06:59 | 5 | Q | Q service is extremely limited and partially suspended because of heavy rainfall and flooding… |
| 29660 | 08:28 | 4 | 7 | 7 service is extremely limited because of heavy rainfall and flooding… |
| 29662 | 08:35 | 7 | N | N service is extremely limited and partially suspended because of heavy rainfall and flooding… |
| 29666 | 08:51 | 7 | A | A service is extremely limited and partially suspended because of heavy rainfall and flooding… |
| 29670 | 09:12 | 7 | 5 | 5 service is extremely limited because of heavy rainfall and flooding… |
| 29679 | 09:44 | 5 | J | J service is extremely limited because of heavy rainfall and flooding… |
| 29681 | 09:49 | 7 | M | M service is extremely limited because of heavy rainfall and flooding… |
| 29688 | 10:17 | 4 | G | G service is extremely limited and partially suspended because of heavy rainfall and flooding… |
| 29692 | 10:22 | 4 | H (Rockaway Park Shuttle) | Rockaway Park Shuttle service is limited because of heavy rainfall and flooding… |
| 29699 | 10:42 | 4 | W | W trains are suspended … because of heavy rainfall and flooding… |
| 29700 | 10:42 | 8 | 3 | 3 service is suspended because of heavy rainfall and flooding… |
| 29707 | 10:58 | 3 | SI | Trains running only Great Kills–St George; delays due to heavy rainfall and flooding |
| 29736 | 11:55 | 4 | B | B service is extremely limited because of heavy rainfall and flooding… |
| 29755 | 12:54 | 3 | C | C service is extremely limited because of heavy rainfall and flooding… |
| 29760 | 13:08 | 6 | E | E service is suspended because of heavy rainfall and flooding… |
| 29767 | 13:19 | 6 | FS (Franklin Av Shuttle) | Franklin Av Shuttle service is suspended because of heavy rainfall and flooding… |
| 29773 | 13:35 | 2 | FS | No Franklin Av Shuttle at this station because of heavy rainfall and flooding… |
| 29796 | 16:53 | 3 | 4 | 4 service is suspended between Burnside Av and 125 St… |
| 29827 | 20:07 | 1 | E | *(E/third-rail incident; flood match is a boilerplate "Reminder: service is extremely limited… because of flooding" footer, not the cause)* |
| 29853 | 22:23 | 1 | E | *(E/switch-problem incident; same boilerplate flood-reminder footer)* |

Every numbered/lettered subway line plus SIR is represented — essentially full-system coverage, consistent with the real event.

**Sept 29-30, 2023 flash flood**: 104 alert-updates across **22 distinct `event_id`**, 2023-09-29T12:42 through 2023-09-30T16:51.

| event_id | first seen | updates | line(s) | first header (truncated) |
|---|---|---|---|---|
| 121651 | 09-29 12:42 | 4 | N | N trains delayed while we remove a train from service at 86 St because of flooding |
| 121646 | 09-29 12:47 | 4 | FS | Franklin Av Shuttle suspended both directions because of flooding at Botanic Garden |
| 121653 | 09-29 12:52 | 5 | B | Northbound B suspended because of flooding near Newkirk Plaza |
| 121654 | 09-29 12:56 | 1 | 1 (system note) | Major disruptions to subway service, especially in Brooklyn, because of flooding from heavy rainfall |
| 121661 | 09-29 13:18 | 7 | ALL (system-wide) | Only extremely limited subway service available because of heavy flooding from rainfall |
| 121662 | 09-29 13:20 | 2 | SI | SIR suspended between Huguenot and Tottenville because of flooding |
| 121664 | 09-29 13:31 | 10 | N, Q | Northbound N Q rerouted via R, DeKalb Av–Canal St, because of flooding on tracks at Canal St |
| 121667 | 09-29 13:34 | 6 | L | No L trains Bedford Av–Myrtle-Wyckoff Avs due to flooding from heavy rainfall in Brooklyn |
| 121648 | 09-29 13:43 | 9 | F, G | No F service Coney Island-Stillwell Av–2 Av; G suspended both directions |
| 121670 | 09-29 13:54 | 6 | 6 | 6 suspended in the Bronx because of flooding at various stations |
| 121673 | 09-29 14:02 | 3 | D | D suspended in Brooklyn both directions while addressing flooding from heavy rainfall |
| 121672 | 09-29 14:02 | 3 | A, C | C suspended because of heavy flooding; A running local |
| 121674 | 09-29 14:11 | 7 | 1, 2, 3 | 1 2 3 holding in Manhattan stations; 2 3 suspended in Brooklyn |
| 121677 | 09-29 14:28 | 1 | D, F, M | D F M holding in stations because of flooding at 47-50 Sts-Rockefeller Ctr |
| 121652 | 09-29 15:19 | 11 | 4, 5 | 4 suspended in Brooklyn; 5 suspended Brooklyn/Manhattan/most of Bronx |
| 121686 | 09-29 15:26 | 2 | W | W suspended while addressing heavy flooding |
| 121689 | 09-29 16:03 | 7 | N, R | N R suspended both directions while addressing heavy flooding |
| 121698 | 09-29 17:07 | 11 | N | N suspended Manhattan/Brooklyn; running only Astoria-Ditmars Blvd–Queensboro Plaza |
| 121703 | 09-29 17:27 | 2 | H (Rockaway Park Shuttle) | Rockaway Park Shuttle suspended both directions because of heavy flooding |
| 121688 | 09-29 17:33 | 1 | E, F, M, R | M suspended 57 St–Delancey St-Essex St; E F extensive delays; R delays |
| 121769 | 09-30 01:21 | 1 | 5 | 5 running with delays, Eastchester-Dyre Av–Bowling Green |
| 121835 | 09-30 16:51 | 1 | N | N running local, DeKalb Av–59 St, both directions |

Coverage again spans nearly every trunk line plus SIR and both shuttles — a known multi-borough event is fully represented in the dataset.

---

### 5. Update cadence and duplicates

**`7kct-peq7` (2020+):** explicit `event_id`/`update_number` model; header text evolves per update (e.g. "extremely limited" → "resumed"). Gaps between successive updates within an event during the two known-event windows:
- Ida: 154 gaps, min 0 min, **median 78 min**, max 363 min (6.05 h)
- Sept 2023: 82 gaps, min 0 min, **median 48 min**, max 888 min (14.8 h — overnight lull before a next-morning resolution update)

Across the full subway-flood subset (435 rows), rows collapse to **99 distinct `event_id`** (~4.4 updates/event). 80/99 events already used flood language in their very first message (`update_number=0`); the other 19 only acquired flood wording in a later update — i.e. a naive "first message only" query would undercount flood events by ~19%.

**`3h5b-5ktz` (2012-2020):** the dataset-level description claims *"it does not include an event_id or update_number to group updates for a single incident,"* but the `status_id` **column-level** description contradicts this ("multiple records may share the same Status ID if they are revisions of the same alert") — and that's confirmed empirically. In the 186-row subway-flood subset:
- 186 rows collapse to **72 distinct `status_id`** values
- 40 `status_id` groups have >1 row, covering **154/186 rows (82.8%)**
- Within a `status_id` group, timestamps are frequently identical to the second (not evolving over time like the new dataset), and text sometimes varies cosmetically between rows sharing one `status_id` and timestamp (two phrasing templates posted at the same instant for the same incident)
- **20 groups are exact (date, header) duplicates, covering 61/186 rows (32.8%)**

**Net effect:** raw keyword-matched row counts (§2) meaningfully overstate distinct flood incidents — by roughly 3-5x for the pre-2020 dataset (72 distinct `status_id` vs 186 rows in the subway sample) and by a smaller but still real factor post-2020 (99 distinct `event_id` vs 435 rows). Any downstream count should dedupe on `status_id` (old) / `event_id` (new) first.

**Dataset-level refresh cadence (separate from within-event update cadence):** `7kct-peq7` metadata reports `rowsUpdatedAt` = 2026-07-24T15:16:38Z, but the newest actual data row (`max(date)`) is 2026-06-29T23:57 — a roughly 7-week gap between the newest alert row and the date of this research run (2026-08-16). Reason not established (see Unverified).

---

### 6. Companion "affected entities" table — not found

Socrata catalog search (`api.us.socrata.com/api/catalog/v1`, `domains=data.ny.gov`):
- `q=Service Alerts` → 4 results; only `3h5b-5ktz` and `7kct-peq7` are MTA alert datasets (others: NYCT Customer Engagement Statistics 2017-2022; Office for the Aging Service Expenditures — unrelated).
- `q=affected entities` → 2 results, both unrelated (Corporations and Other Entities: All Filings; NYS Government Building Energy Use Intensity).
- `q=MTA alert` → 3 results, same two alert datasets plus Customer Engagement Statistics.

**No normalized "affected entities" (alert-to-stop/route) companion table exists in the data.ny.gov catalog.** The `affected` column (pipe-delimited route/line names, confirmed by Socrata's own column description) is the only structured line-level linkage; there is no equivalent for stations.

---

### Unverified

- Reason for the ~7-week gap between `7kct-peq7`'s newest data row (2026-06-29) and the research date (2026-08-16) / metadata `rowsUpdatedAt` (2026-07-24) — not established; could be a paused refresh, a query-time artifact, or normal batch cadence.
- Whether MTA's internal/non-public systems (or the live GTFS-RT alerts feed) carry a structured stop_id linkage that simply isn't exposed in these two Socrata datasets — only the public data.ny.gov schema was inspected.
- The 77.1% "names a location" figure is a regex heuristic (Street/Avenue/hyphenated-complex-name pattern), not validated against the official ~472-stop GTFS station list — true precision/recall not computed.
- Wayback Machine / archive.org was not needed or used for this task — every required source (data.ny.gov Socrata resource API and catalog API) was live and answered directly with HTTP 200, so the reported web.archive.org 503s were not encountered here.
- Whether boilerplate-reminder flood matches (like Ida `event_id` 29827/29853, where the flood text is a system-status footer, not the incident cause) are common outside the two sampled event windows — only spot-checked, not measured system-wide.

### Raw data saved this session (for reuse)
- `/private/tmp/claude-501/-Users-ross-raincheck/c53780b0-c135-45a4-906e-147e35100ce1/scratchpad/meta_3h5b.json`, `meta_7kct.json` — full dataset metadata
- `subway_old_flood.json` (186 rows), `subway_new_flood.json` (435 rows) — full subway flood-keyword subsets
- `ida_subway.json` (183 rows), `sep2023_subway.json` (104 rows) — the two known-event pulls
- `catalog_service_alerts.json`, `catalog_affected_entities.json`, `catalog_mta_alert.json` — Socrata catalog search results

## Verification corrections (2026-08-16, opus skeptic: 16 of 19 claims reproduced exactly, including every event_id and per-event update count in the section 4 tables)

- Distinct-incident inflation of keyword-matched rows: pre-2020 subway 186 rows / 72 distinct `status_id` = 2.6x; post-2020 435 rows / 99 distinct `event_id` = 4.4x (the note's "3-5x pre-2020, smaller post-2020" is inverted).
- Pre-2020 wording: 124/186 (66.7%) contain "water condition at", 146/186 contain "water condition", 40/186 (21.5%) contain "flood" — a strong tendency, not a universal boilerplate; match both phrasings.
- Ida intra-event update cadence: 154 gaps, min 0, median 77 min, max 363 (note said 78); Sept 2023: 82 gaps, median 48, max 888, reproduced.
