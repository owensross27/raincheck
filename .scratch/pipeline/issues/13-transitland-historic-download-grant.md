# 13 Transitland historic-download grant and one-zip proof

Type: task
Status: open
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
