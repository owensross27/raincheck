# 12 Transitland key and dated-pick download check

Type: task
Status: resolved
Blocked by: none

## Question

Ticket 06 decided the backfill computes schedule metrics, so the 2017-2024 static
picks must actually be fetchable. HITL: Ross signs up for a free Transitland API key
(the REST API returns 401 anonymously; the website browses free) and stores it in
the local env, not the repo. Then AFK: with the key, list `feed_versions` for one
feed (`f-dr5r-mtanyctbusbrooklyn`, 93 versions per ticket 11), download one version
that covers 2021-09-01, confirm it is a real GTFS zip (trips.txt, stop_times.txt,
calendar.txt) whose trip_ids match the nycbuspositions trip_id scheme
(`WF_C1-Weekday-033000_SBS6_153`), and record: the endpoint shape, the version's
`fetched_at` / calendar range fields that a pick-to-date resolver would key on, zip
size, and the free-tier rate limit. The Answer records the credential location, the
URL pattern, and the resolver rule; the bulk pull (~60-70 zips per borough) is
downstream build work for ticket 10's slice.

## Comments

### 2026-08-16 — AFK half done, HITL half waiting on Ross

**Premise correction.** A free key lists versions but does NOT download historic
zips. From the public OpenAPI spec (`https://transit.land/api/v2/rest/openapi.json`,
no key needed) and `https://www.transit.land/plans-pricing/`:

| Tier | REST quota | Current-feed download | Historic version download |
|---|---|---|---|
| Free (Explorer) | 10,000 queries/month | yes (metered as REST queries) | no |
| Professional ($200/mo annual, $250 monthly) | 200,000/month | yes | no (pricing page); OpenAPI text says "professional or enterprise" but the plans table says no — treat as no |
| Pay As You Go | "coming soon" | yes | yes, credit card |
| Hobbyist/Academic | free, non-commercial | yes | "free credits for up to 500 historical GTFS feed downloads" after a Free signup plus a form |
| Enterprise | custom | yes | yes (>1,000 downloads) |

Free tier gives everything the pick-to-date resolver needs; the *bytes* of a 2021
zip need the Hobbyist/Academic grant. Sizing: full window ~65 versions x 6 feeds
~ 390 downloads, under 500; ticket 10's ~120-day slice needs well under 20.
Per-second/burst limit is not published anywhere I found: [unverified].

**Endpoint shape (from the OpenAPI spec, verified 2026-08-16).** Base
`https://transit.land/api/v2/rest`, auth `?apikey=` or `apikey:` header. Anonymous
returns 401 on every path including `/query` (GraphQL).

- List: `GET /feed_versions?feed_onestop_id=f-dr5r-mtanyctbusbrooklyn&limit=N&after=<cursor>`
  (also `fetched_before`, `fetched_after` UTC datetime filters, `sha1`).
  Each item: `id`, `sha1`, `url`, `fetched_at`, `earliest_calendar_date`,
  `latest_calendar_date`, `feed_infos[]` (has MTA's own `feed_version` string, e.g.
  `gtfs_b_20260611T155327Z`, plus `feed_start_date`/`feed_end_date`), `files[]`
  (per-file name/rows/header, so trips.txt/stop_times.txt/calendar.txt presence is
  checkable before spending a download), `service_levels[]`.
- One version: `GET /feed_versions/{sha1 or id}`.
- Bytes: `GET /feed_versions/{sha1}/download` -> `application/octet-stream`; role
  `tl_download_fv_historic`; 401 if not entitled or license forbids. Current pick:
  `GET /feeds/{onestop_id}/download_latest_feed_version` (role `tl_download_fv_current`).
- Free-tier scheme probe without a download: `GET /routes/{route_key}/trips?feed_version_sha1=<sha1>`
  accepts a version sha1, so a 2021 version's `trip_id`s can be inspected via the
  API if Transitland imported that version into its DB (not every version is
  imported): [unverified until keyed].
- License: transitland-atlas DMFR for all six bus feeds sets `use_without_attribution`,
  `create_derived_product`, `commercial_use_allowed`, `share_alike_optional` = yes
  (`redistribution_allowed` unset). Not a wall.

**Trip_id scheme continuity (verified today, no key needed).** Current `gtfs_b.zip`
(13.5 MB; stop_times.txt 123.6 MB uncompressed; trips.txt, calendar.txt,
calendar_dates.txt, feed_info.txt present) uses `EN_C6-Weekday-028500_SBS82_901`;
live VP 2026-08-15 shows `EN_C6-Saturday-052800_B82_610`; nycbuspositions 2021 shows
`WF_C1-Weekday-033000_SBS6_153`. Same `<depot>_<pick>-<service>-<start>_<route>_<run>`
scheme end to end, so the historic zips will match; the byte-level check on one 2021
version is what the grant is for.

**Resolver rule (decision).** For service date D (per 06: the feed's `start_date`,
noon-minus-12h): among the feed's versions with `fetched_at` < D + 1 day (UTC), take
the one with the greatest `fetched_at` whose `[earliest_calendar_date,
latest_calendar_date]` covers D. If none covers D, take the greatest `fetched_at` <
D + 1 day anyway and flag `pick_gap=true`. Key the pick by `sha1`; carry
`feed_infos.feed_version` as provenance. Rationale: MTA publishes a pick ~2 weeks
before its calendar starts and Transitland fetches on change, so "latest fetched
before D that covers D" is the pick in effect; a mid-period re-publish supersedes
for later dates automatically.

**Credential location (decision).** `TRANSITLAND_API_KEY` in `.env` at the repo
root, gitignored (added today), read via `os.environ` — no new dependency,
docker-compose picks up `.env` natively. Never in the repo, never in the vault.

Note: the transit.land site's own JS bundle ships a client `apikey` for the
website's calls. Not ours to use; sign up properly.

### HITL checklist for Ross (the part I cannot do)

1. Sign up for a Free Transitland account at `https://www.transit.land/` ("Sign up
   now" on the plans page goes to `https://app.interline.io/products/tlv2_api/orders/new`).
   Copy the API key.
2. Put it in `/Users/ross/raincheck/.env` as `TRANSITLAND_API_KEY=...` (file is
   gitignored; `chmod 600 .env`).
3. Submit the Hobbyist/Academic form at
   `https://app.interline.io/contact_forms/hobbyist_academic` — non-commercial
   research: NYC bus delay vs rainfall, needs ~400 historical MTA bus GTFS versions
   (six feeds, 2017-2024). This is what unlocks `/feed_versions/{sha1}/download`.
4. Say "12: key is in .env" (and later "grant approved") in a session; the AFK
   remainder is: list Brooklyn versions, pick the one covering 2021-09-01 by the
   rule above, download it, confirm trips.txt/stop_times.txt/calendar.txt and the
   trip_id scheme, record zip size, then resolve.

## Answer

Resolved 2026-08-16. Free key obtained by Ross, stored as `TRANSITLAND_API_KEY` in
gitignored `/Users/ross/raincheck/.env` (mode 600), loaded with `set -a; . ./.env`.
Measured with the key:

- `GET https://transit.land/api/v2/rest/feed_versions?feed_onestop_id=f-dr5r-mtanyctbusbrooklyn&limit=100`
  with `apikey:` header returns all 93 versions in one page (no cursor needed); 67 of
  them were fetched inside 2017-07-14 to 2024-09-06. No rate-limit headers are
  returned; free quota is 10,000 REST queries/month (plans page).
- Resolver rule applied to 2021-09-01: two versions cover it (fetched 2021-06-25,
  calendar 2021-06-26 to 2021-09-04; fetched 2021-08-31, calendar 2021-08-04 to
  2022-01-01); greatest `fetched_at` wins, pick = `sha1
  c244b822b8d0120d40e5849369b451220e1bfdd2`, source URL
  `http://web.mta.info/developers/data/nyct/bus/google_transit_brooklyn.zip`. Its
  `files[]` metadata proves it is a real GTFS zip without a download: trips.txt
  58,954 rows, stop_times.txt 2,543,006 rows (159.6 MB uncompressed), calendar.txt
  41 rows, calendar_dates.txt 832 rows, no feed_info.txt (so `feed_infos` is empty
  on 2021 versions; provenance key is `sha1`, `feed_version` string only when present).
- `GET /feed_versions/{sha1}/download` -> 401 `{"error":"Unauthorized"}` on the free
  key, as the OpenAPI role `tl_download_fv_historic` says. Only the current
  2026-06-24 version is imported into Transitland's DB, so `/routes?feed_version_sha1=`
  returns `[]` for 2021: trip_ids cannot be inspected via the API either.
- Trip_id scheme continuity is established from the free evidence (2021
  nycbuspositions `WF_C1-Weekday-033000_SBS6_153`, 2026 static
  `EN_C6-Weekday-028500_SBS82_901`, 2026 live VP `EN_C6-Saturday-052800_B82_610`).
  The byte-level check on the 2021 zip moves to
  [13 Transitland historic-download grant](13-transitland-historic-download-grant.md)
  together with the Hobbyist/Academic form, which is the only free route to the bytes.

Endpoint shape, tier table, resolver rule and credential decision are in the
2026-08-16 comment above and stand as written.

### 2026-08-16 — corrections from ticket 13

- Trip_id scheme is `<depot>_<pick>-<service>[-<modifier>...]-<start>_<route>_<run>`,
  not a fixed five-token form: the service segment is the `service_id` tail and
  carries optional modifiers (`-SDon` on 13,090/46,115 = 28% of current Brooklyn
  trips, e.g. `EN_C6-Weekday-SDon-028500_SBS82_901`; rare `-BM`). The live VP feed
  carries the same strings (vault sample `EN_C6-Weekday-SDon-135000_B82_643`), so the
  string join is unaffected; any parser splits on the 6-digit start token.
- Rate limit IS published now: `X-RateLimit-Limit-Minute: 600` on every endpoint
  (600/min burst on top of the 10k/month Free quota). The bulk pull is not
  rate-bound.
