# 03 — Archive converter: nycbuspositions xz to Bronze VP

**What to build:** `make nbp DATE=YYYY-MM-DD` turns one nycbuspositions UTC-day file into Bronze VP partitions
in the live archiver's schema, so archive-era and live Pings are one table with one read rule.
The xz source is kept under the archive root; the conversion is idempotent by part name and
gated by the ms/s timestamp check. Spec: E; Testing 10-T1.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] one converter call writes `vp/date=<UTC date>/hour=HH/part-nbp-<date>.parquet` under the archive root with the archiver's explicit type map (an all-NULL column keeps its typed schema)
- [ ] column mapping per spec E: trip/route/stop empty -> NULL, direction_id NULL, start_date reformatted to YYYYMMDD, ts from the vehicle timestamp, occupancy NULL when the source day has one distinct value, fetched_at NULL, the listed archive columns dropped
- [ ] 10-T1 tier-1: rows == xz rows; unique (vehicle_id, ts) == rows; 0 rows with ts outside [D-1, D+2) UTC; lat/lon inside the bbox; three route classes non-empty; convert twice -> identical rows, no extra files, the neighbouring date= untouched
- [ ] the 20-column 2018-10-10 fragment and the DST 2021-11-07 fragment convert clean as committed fixtures
- [ ] the census test asserts converter columns and types == the decoder's VP keys and types
