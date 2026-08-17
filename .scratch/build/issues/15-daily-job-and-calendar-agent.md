# 15 — Daily job and the 06:00 calendar agent

**What to build:** `make daily` builds every missing closed service day (events + leg_hours), refreshes the
current MRMS month and prunes the live tables, and a 06:00 America/New_York LaunchAgent runs
it so a day missed during sleep rebuilds itself. Spec: K.

**Blocked by:** 08, 11

**Status:** ready-for-agent

- [ ] `daily` lists service_date= partitions under silver/events against Bronze-present dates (bounded, last 14 days) and runs `events DATE=` for each gap, then precip-hourly and precip-cell for src=mrms on the current month, then drops live date=/hour= dirs older than 48 h by name; running it twice does nothing the second time
- [ ] the StartCalendarInterval 06:00 America/New_York plist is installed (10:00Z clears Pass2's tail for the last service-day hour in both DST regimes) and a real run is verified in the log
- [ ] a test seeds two closed days and one built day under a temp root and asserts exactly the two gaps are built and the neighbour is untouched
