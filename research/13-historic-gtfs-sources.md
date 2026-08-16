# Where else could dated MTA bus GTFS (2017-07-14..2024-09-06) come from?

Sweep run 2026-08-16 while the Transitland Hobbyist/Academic grant (ticket 13) is
pending. Every claim below was measured today (curl / SODA / S3 / GCS / Wayback CDX /
gh api); anything not measured is marked [unverified]. Supersedes the Wayback and
"continuous coverage" statements in `11-historical-static-gtfs.md`.

## Verdict

Nothing public holds the bytes for the whole window. Ranked:

| # | Source | What it holds | Verdict |
|---|---|---|---|
| 1 | Transitland v2 (grant pending) | 423 in-window versions across the six feeds (bronx 54, brooklyn 67, manhattan 67, queens 52, staten_island 67, busco 116); calendars leave a 2019 hole (below) | the only complete source |
| 2 | Wayback: `web.mta.info/developers/data/nyct/bus/google_transit_*.zip` and `busco/google_transit.zip` | 9-12 distinct captures per feed: 2016-04, (SI 2018-07), 2020-04, 2021-03, 2021-04, 2021-10, 2022-07, 2022-11/12, 2023-05, 2023-08, 2023-10, 2024-02; **25 captures are byte-identical to a Transitland version** (CDX `digest` = base32 SHA-1 of the payload = Transitland `sha1`), all 2021 (+SI 2018-07-13); the ~35 captures from 2020-04 and 2022-2024 match no Transitland sha1 [unverified whether distinct picks, re-zips, or truncated: Wayback served 503 all day] | free now for 4-7% of days per feed; neither storm-day pick |
| 3 | data.ny.gov "MTA Bus Schedules: 2021..2026" (`d6ix-pek4`, `w6dm-6y5c`, `x5mx-4rfs`, `udt9-hvjq`, `t4bz-xqa9`, `4fnn-qsea`) | per schedule_date, per trip, timepoint stops only, ~130M rows/year, no auth, stamped with the MTA `bundle`; **`schedule_time` is date-only in both the SODA API and the CSV export** (hour histogram = 100% hour 0 on 2021 and 2024) | a stop-order/distance table, not a schedule, until MTA fixes it (opendata@mtahq.org); its `bundle` ranges are still a free ground truth for the pick in effect |
| 4 | Ask a human archive | Bus-Data-NYC (Neil Freeman / TransitCenter) ran `nyc-bus-stats` "for a particular release of GTFS" 2015-2019 and owns `nycbuspositions`; MTA Open Data / Bus Time team | plausible for 2017-2019, unmeasured |
| 5 | MobilityData | GCS `mdb-latest` is anonymously listable and downloadable but holds one rolling snapshot per feed (all six created 2026-06-04); catalogs.csv has no redirected/deprecated MTA entries; `mobilitydata-datasets-*` 401, `files.mobilitydatabase.org` 403 | current only |
| 6 | Transitland v1 datastore | `transit.land/api/v1` 404 everywhere; `transitland-gtfs` S3 bucket 403 on every key including a bogus one; zero Wayback captures | dead |
| 7 | transitfeeds / OpenMobilityData | site 403; download bucket `openmobilitydata-data.s3-us-west-1` exists but 403; Wayback holds only 2014-2016 subway download redirects | dead |
| 8 | GitHub | 16 code searches and 12 repo searches: no repo commits dated MTA bus zips or trips/stop_times in the window; `zubearc/transit-data` is one 2023-08 conversion (routes/stops/trips JSON, no stop_times); Bus-Data-NYC repos are code | none |
| 9 | archive.org items | search backend down all day (`[BACKEND_ERROR]` on every query) | [unverified] |
| 10 | Zenodo / figshare / IEEE DataPort / Harvard Dataverse / NYU FDA / Kaggle | 0 hits, 0 hits, none surfaced, WAF-blocked, one Dec-2019 routes item [unverified], Kaggle 2017 set is SIRI-derived Bus Time (needs login) | nothing usable |
| 11 | Wayback: `rrgtfsfeeds.s3.amazonaws.com/gtfs_*.zip` | 95 captures, earliest 2024-08-28; four inside the window (b 2024-08-31, m/q 2024-08-28, si 2024-08-29) | sliver |
| 12 | `nycbuspositions` bucket itself | 6,595 keys: `YYYY/MM/<date>-bus-{positions,trip-updates,alerts,messages}.csv.xz` (alerts 1,429 and messages 1,409 files, undocumented in ticket 10) plus `stats/` (TransitCenter monthly `speed/` 26 months and `bunching/` 11 months, 2015-2019, plus `stopdist/`); no README, no GTFS | no schedule; free speed benchmark for ticket 10 |

## The pick code is in the trip_id: resolver correction for ticket 12

Measured on the archive itself (`2021-09-01-bus-positions.csv.xz`, 1,332,701 rows;
`2023-09-29`, 1,373,812 rows):

- 2021-09-01: 1,040,872 rows carry `<depot>_C1-...`; 271,000 are MTA Bus Company ids
  of the form `31325137-LGPC1-LG_C1-Weekday-10` (also C1); 20,829 empty.
- 2023-09-29: 1,082,733 `D3`, 674 `M3` (MQ depot), 279,956 busco `...-JKPD3-JK_D3-...`.
- data.ny.gov `bundle` in effect (Brooklyn): 2021Jul 2021-06-27..2021-09-04, 2021Sep
  2021-09-05..; 2023Jul 2023-07-02..2023-09-02, 2023Sep 2023-09-03..; the 2021-01-01
  rows carry `EN_D0-Sunday` under bundle 2020Sep; today's zip is `C6`.

So `<pick>` = letter A/B/C/D for the Jan/Apr/Jul/Sep pick, digit = year mod 10, and
it is the MTA bundle name. Transitland metadata for the Ida day: `c244b822` (fetched
2021-08-31, cal 2021-08-04..2022-01-01) has trips 58,954 / stop_times 2,543,006 /
calendar 41 / calendar_dates 832 — identical to `5b7f197c` (fetched 2021-09-02, cal
2021-09-04.., in Wayback), i.e. it is the **2021Sep (D1) pick published early**; the
2021Jul (C1) pick is `4b8dec91` (fetched 2021-06-25, cal 2021-06-26..2021-09-04, trips
45,571). Ticket 12's rule "greatest fetched_at < D+1 whose calendar covers D" therefore
selects the wrong zip for 2021-09-01 (an exact-string trip_id join would match ~0%).
For 2023-09-29 the rule's pick `61d83dfe` is D3 and correct.

Resolver v2: the day's VP trip_ids name the pick; choose the version whose trips.txt
carries that code (parse `^[A-Z]{2}_([A-Z]\d+)-` and the busco `-..P(\w\d)-` form),
greatest fetched_at ≤ D+1 among those (mid-pick revisions supersede). Self-checking:
the join match rate is ~0 on a wrong zip and ~98% on the right one (ticket 06 measured
98.4% live). `pick_id` stays the zip sha1 (09).

## Transitland's own coverage holes (calendars, not fetches)

Days with no in-window version whose calendar covers them: Bronx / Queens / busco
2019-01-06..2019-11-14 (313 d), Brooklyn / Manhattan / SI 2019-06-30..2019-09-20 (83
d), plus 2018-07-01..02, 2020-09-06..07, 2021-01-03..22 (SI also 2018-02-04..03-02).
Wayback has nothing for 2019 either. `pick_gap=true` for these regardless of the grant.

## Wayback recipe (when web.archive.org recovers)

- Digest match without downloading: `base64.b32decode(cdx_digest).hex() == transitland.sha1`.
- Raw bytes: `https://web.archive.org/web/<timestamp>id_/http://web.mta.info/developers/data/nyct/bus/google_transit_<feed>.zip`.
- Unmatched captures to verify (sha1 vs digest, testzip, calendar range, pick codes,
  compare with the Transitland `files[]` rows of overlapping versions): Brooklyn
  20200426183023 (5.8 MB, suspiciously small), 20220713143528, 20221129213350,
  20230528055805, 20230825061329; Bronx 20220713143528; Manhattan 20240226011206.
- Rate limit fact: Transitland REST publishes `X-RateLimit-Limit-Minute: 600`.
