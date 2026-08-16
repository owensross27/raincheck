# 12 Transitland key and dated-pick download check

Type: task
Status: open
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
