# 03 — Archive converter: nycbuspositions xz to Bronze VP

**What to build:** `make nbp DATE=YYYY-MM-DD` turns one nycbuspositions UTC-day file into Bronze VP partitions
in the live archiver's schema, so archive-era and live Pings are one table with one read rule.
The xz source is kept under the archive root; the conversion is idempotent by part name and
gated by the ms/s timestamp check. Spec: E; Testing 10-T1.

**Blocked by:** 01

**Status:** resolved

- [x] one converter call writes `vp/date=<UTC date>/hour=HH/part-nbp-<date>.parquet` under the archive root with the archiver's explicit type map (an all-NULL column keeps its typed schema)
- [x] column mapping per spec E: trip/route/stop empty -> NULL, direction_id NULL, start_date reformatted to YYYYMMDD, ts from the vehicle timestamp, occupancy NULL when the source day has one distinct value, fetched_at NULL, the listed archive columns dropped
- [x] 10-T1 tier-1: rows == xz rows; unique (vehicle_id, ts) == rows; 0 rows with ts outside [D-1, D+2) UTC; lat/lon inside the bbox; three route classes non-empty; convert twice -> identical rows, no extra files, the neighbouring date= untouched
- [x] the 20-column 2018-10-10 fragment and the DST 2021-11-07 fragment convert clean as committed fixtures
- [x] the census test asserts converter columns and types == the decoder's VP keys and types

## Comments

**2026-08-22 (implemented).** `src/raincheck/nbp.py` (`convert(root, day)`, `make nbp
DATE=`; downloads the xz to `<root>/archive/nycbuspositions/YYYY/MM/` once via a
`.part`-then-rename if missing, converts with pyarrow), `tests/test_nbp.py` (14 tests,
JVM-free), fixtures `nbp-2018-10-10-fragment.csv.xz` (67 KB) and
`nbp-2021-11-07-fragment.csv.xz` (27 KB) — stratified cuts (header + every 700th row) so
all 24 hours and all three route classes appear in each; both convert clean.

Facts pinned by looking at the real files (both full days downloaded and inspected):
- The source `timestamp` is an ISO string `YYYY-MM-DD HH:MM:SS+00`, not epoch seconds
  (spec E's "epoch s" describes the output `ts`). Format is uniform on both era files
  (regex-checked on every row of both full days); the converter fails the file loudly if
  any row deviates, and parses via strptime on the first 19 chars.
- 20-column header confirmed (2018-10-10) and 22-column (2021-11-07: + `mid`,
  `stop_sequence`); column names are `vehicle_license_plate`, `trip_start_date` (ISO,
  can be D-1 for overnight runs), `occupancy_status`.
- The 2018 file has 1,849,584 rows (matches research 10's 1.85M/day for 2017-18), the
  DST day 715,495; files are NOT time-sorted internally; spans verified
  00:00:0x..23:59:5x Z.
- `date=`/`hour=` come from `ts` itself (spec: "partitions come from ts"), so a
  skew-across-midnight row would land in its own hour rather than be mislabelled; on
  the verified files every row lands in the source date.
- The ms/s gate fails the whole file (SystemExit naming the file and count) before
  anything is written; the mixed-occupancy branch (2019-09-11 case) is covered by a
  synthetic-day test.

Real run (`make nbp DATE=2021-11-07`, the DST fixture day, kept in Bronze for 06's
sched_ts unit test): 715,495 rows -> 24 parts in **1.8 s** (spec's ~1 min/file estimate
is very conservative; the 124-file slice conversion should be ~4 min of CPU), 12 MB
parquet + 9.6 MB xz retained. T1 on the real day: rows == xz rows, all (vehicle_id, ts)
unique, 0 outside the gate, 0 outside the bbox, 24 express / 19 SBS / 213 local routes.
Suite: 44 passed (both `make test` and bare `pytest`; 15 in test_nbp.py). Review round:
the census test's cross-module import broke bare `pytest` (fixed with a local `load()`),
and the download path gained a monkeypatched test (fetch once, recover a stale `.part`,
no refetch when cached).
