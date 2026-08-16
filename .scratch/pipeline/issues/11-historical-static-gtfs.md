# 11 Historical static GTFS for the backfill window

Type: research
Status: resolved
Blocked by: none

## Question

Schedule-based delay for the 2017-07-14 to 2024-09 backfill needs the static
GTFS that was in effect on each service date, and `rrgtfsfeeds.s3.amazonaws.com`
serves only the current pick. Where do dated historical MTA bus GTFS zips come
from (Mobility Database / mobilitydatabase.org historical archive, transitfeeds
Wayback copies, transit.land feed versions, MTA's own developer archive, any
academic mirror), how complete is coverage per borough across the window, and
what is the shape of a fetch (URL pattern, auth, size)? If no source covers a
sub-window, say which. Surfaced by [06 Delay metric design](06-delay-metric-design.md):
without dated schedules the backfill can only produce speed/headway metrics, not
schedule delay.

## Answer

Resolved 2026-08-16 by research subagent; full findings with live probes in
[research/11-historical-static-gtfs.md](../../../research/11-historical-static-gtfs.md).

- **Transitland v2 is the one source confirmed to hold dated MTA bus GTFS across
  the whole window.** Feed ids `f-dr5r-mtabc` (busco), `f-dr5r-mtanyctbus{brooklyn,
  manhattan,statenisland}`, `f-dr5x-mtanyctbusqueens`, `f-dr72-mtanyctbusbronx`.
  Brooklyn page (fetched live) lists 93 archived versions, 2016-02-06 to 2026-06-24,
  roughly one per 5-6 weeks, so 2017-07-14 to 2024-09-06 is covered end to end.
  Browsing is free; downloading versions needs a free API key (REST returns 401
  anonymously). Exact per-window version count and the download endpoint shape
  were not exercised: [unverified].
- Mobility Database: API needs a GCIP account token; the one feed page inspected
  (`mdb-510`, busco) shows 11 versions, earliest 2025-12-30. Not a history source.
- transitfeeds.com is dead (403) and its Wayback zip snapshots are all 2014-2016;
  Brooklyn/Queens pages were never crawled. Dead end for the window.
- `rrgtfsfeeds` bucket denies listing and serves only the current pick.

Consequence for [06 Delay metric design](06-delay-metric-design.md): schedule-based
delay is implementable for the backfill, at the price of a Transitland signup and
about 60-70 zips per borough. Whether the backfill computes schedule delay or only
observed metrics (speed, headway) is a 06/10 decision, not a data-availability wall.

## Comments

### 2026-08-16 — corrections from the ticket 13 source sweep (measured)

- Wayback is not "one snapshot per borough, 2014-2016". CDX for
  `web.mta.info/developers/data/nyct/bus/google_transit_*.zip` (and `busco/`) holds
  9-12 distinct captures per feed: 2016-04, SI 2018-07, 2020-04, 2021-03, 2021-04,
  2021-10, 2022-07, 2022-11/12, 2023-05, 2023-08, 2023-10, 2024-02. 25 of them are
  byte-identical to Transitland versions (CDX digest = base32 SHA-1 = Transitland
  `sha1`), all 2021 plus SI 2018-07-13; the 2020-04 and 2022-2024 captures match no
  Transitland sha1 and are unverified (Wayback 503 all day). Free coverage: 4-7% of
  window days per feed, neither storm-day pick, nothing in 2017-2019 except SI.
- Transitland's version list is continuous but its calendars are not: no version
  covers Bronx/Queens/busco 2019-01-06..2019-11-14 (313 d) or
  Brooklyn/Manhattan/SI 2019-06-30..2019-09-20 (83 d), plus 2018-07-01..02,
  2020-09-06..07, 2021-01-03..22. In-window version count is 423 (busco 116), not
  ~65 per feed.
- Everything else probed is dead or current-only: MobilityData `mdb-latest` (one
  rolling snapshot, 2026-06-04), Transitland v1 datastore, transitfeeds' S3 bucket,
  GitHub, Zenodo/figshare; archive.org item search was down. data.ny.gov "MTA Bus
  Schedules: 2021+" would cover 2021-2024 at timepoint grain but its `schedule_time`
  is published date-only. Full table: `research/13-historic-gtfs-sources.md`.
