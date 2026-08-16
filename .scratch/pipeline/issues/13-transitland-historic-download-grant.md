# 13 Transitland historic-download grant and one-zip proof

Type: task
Status: claimed (waiting on HITL: Hobbyist/Academic form, see checklist below)
Blocked by: none

## Question

[12 Transitland key and dated-pick download check](12-transitland-historical-picks.md)
proved the free key lists versions and resolves picks but `GET
/feed_versions/{sha1}/download` returns 401 on the free tier. HITL: Ross submits the
Hobbyist/Academic form at `https://app.interline.io/contact_forms/hobbyist_academic`
(non-commercial research, NYC bus delay vs rainfall, ~400 historical MTA bus GTFS
versions across six feeds 2017-2024; the grant is 500 downloads) and reports
approval. Then AFK: download the 2021-09-01 Brooklyn pick (`sha1
c244b822b8d0120d40e5849369b451220e1bfdd2`), confirm the zip opens with trips.txt,
stop_times.txt, calendar.txt, confirm trip_ids follow
`<depot>_<pick>-<service>-<start>_<route>_<run>` (e.g. `WF_C1-Weekday-033000_SBS6_153`),
record zip size and download latency, and note whether the grant is metered per
request or per distinct version (re-downloads). If the grant is refused, the fallback
decision is Enterprise quote vs backfill without schedule delay (speed/headway only,
per 06); record which. The bulk pull stays build work for ticket 10.

## Comments

### 2026-08-16 — AFK half prepared and verified, HITL half waiting on Ross

**State.** `GET /feed_versions/c244b822.../download` with the `.env` key still
returns 401 (`{"error":"Unauthorized"}`) at 2026-08-16 21:54 UTC: the grant is not
live. The form at `https://app.interline.io/contact_forms/hobbyist_academic`
redirects to the Interline login, so it is behind Ross's account and nothing can be
prefilled from here. The plans page says only that it asks about "your project or
your academic program".

**AFK proof is ready to run:** `research/13-one-zip-proof.py` (stdlib only). It
downloads the pick, asserts the bytes hash to Transitland's `sha1`, saves them as
Bronze `data/archive/static/brooklyn/2021-08-31.zip` (09 layout, `<fetched_at
date>.zip`), asserts trips.txt / stop_times.txt / calendar.txt are present and every
trip_id matches the scheme, prints size and latency, then downloads a second time and
prints any rate-limit / credit headers so the per-request vs per-version metering
question is answered by comparison (plus the Interline Portal usage page). Verified
today on both reachable paths: check-only against the current 13.5 MB MTA Brooklyn
zip (46,115 trips, PASS) and the live 401 path (clean exit 2).

**Two facts found on the way** (also recorded on ticket 12 and in the vault feed
reference):

- The trip_id scheme has an optional modifier segment:
  `<depot>_<pick>-<service>[-<modifier>...]-<start>_<route>_<run>`. `-SDon` (school
  days on) is on 28% of current Brooklyn trips (`EN_C6-Weekday-SDon-028500_SBS82_901`);
  `-BM` is rare. The service segment is the `service_id` tail. The live VP feed
  carries the same strings, so the string join is unaffected; parsers split on the
  6-digit start token. Ticket 12's five-token statement was too tight.
- Transitland now publishes its burst limit in headers on every endpoint:
  `X-RateLimit-Limit-Minute: 600` (10k/month on Free). Not a constraint for the
  ~390-download bulk pull.

### HITL checklist for Ross

1. Log in at `https://app.interline.io/` (the Free account that holds the
   `TRANSITLAND_API_KEY` in `.env`; the grant attaches to that account) and open
   `https://app.interline.io/contact_forms/hobbyist_academic`.
2. Fill it as non-commercial research. Draft, use the legal name Owens:

   > Ross Owens, independent non-commercial research project "raincheck": measuring
   > whether and where rainfall slows NYC buses. It joins the public nycbuspositions
   > GTFS-RT archive (2017-07 to 2024-09) to NOAA AORC hourly precipitation and needs
   > the dated static GTFS in effect on each service date to compute schedule
   > deviation and scheduled headway. The archive on transit.land is the only source
   > of those historical versions. Scope: the six MTA NYCT bus feeds (Bronx,
   > Brooklyn, Manhattan, Queens, Staten Island, MTA Bus Company), roughly 65
   > versions each, about 390 historical downloads total, starting with ~20 for one
   > borough. Output is analysis and open code, no redistribution of the feeds; the
   > Transitland attribution requirement is fine.

3. When Interline replies, say "13: grant approved" in a session, then run:

       set -a; . ./.env; set +a; python3 research/13-one-zip-proof.py

   Paste the output (size, latency, both header dumps). The session records the
   answer, closes 13, and the bulk pull remains ticket 10's build item.
4. If refused, say "13: refused" and pick the fallback. Recommendation on the
   record: backfill without schedule delay (speed/headway only per 06 — `segment_s`
   and `headway_obs_s` carry the rain headline; `delay_s`/`segment_excess_s` become
   live-era-only) rather than an Enterprise quote, unless the quote is trivial.

### 2026-08-16 — Ross submitted the form; source sweep run in the meantime

Form submitted by Ross 2026-08-16 (HITL step done; grant still 401 as of the last
probe). While waiting, a sweep of alternative sources for the bytes ran (8 probes +
inline measurements): `research/13-historic-gtfs-sources.md`. Gist: nothing public
holds the whole window; Wayback holds 25 byte-identical versions (2021, SI 2018) plus
~35 unverified 2020/2022-2024 captures; data.ny.gov's "MTA Bus Schedules" 2021+ has
the schedule at timepoint grain but with `schedule_time` stripped to dates (worth an
email to opendata@mtahq.org); everything else is dead or current-only. Two map-level
corrections came out of it and are recorded on 11 and 12: the trip_id pick code is
the MTA bundle and selects the zip (12's fetched_at rule chose the 2021Sep pick for
the Ida day; the C1 zip is `4b8dec91`), and Transitland calendars have a 2019 hole.
The proof script now targets `4b8dec91` by default and accepts a sha1 argument; the
grant sizing is 423 in-window versions (busco 116), still under 500 but with less
headroom than the form text's ~390.
